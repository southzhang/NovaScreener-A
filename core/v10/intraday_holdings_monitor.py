#!/usr/bin/env python3
"""实盘盯盘 - 持仓监控 + 进场信号
纯脚本版，无LLM幻觉风险。
v4: 动态读取current_holdings.py（不再硬编码持仓），行情通过quote_adapter
"""
import sys
import json
import os
from datetime import datetime

# ========== 交易时间检查 ==========
def is_trading_time():
    now = datetime.now()
    h, m = now.hour, now.minute
    t = h * 100 + m
    return (915 <= t <= 925) or (930 <= t <= 1130) or (1300 <= t <= 1500)

# ========== 动态读取持仓 ==========
def load_holdings():
    """从current_holdings.py动态读取实盘持仓"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    holdings_path = os.path.join(script_dir, 'current_holdings.py')
    if not os.path.exists(holdings_path):
        print("❌ current_holdings.py 不存在")
        return []
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("current_holdings", holdings_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        holdings = mod.get_holdings()
        portfolio_value = mod.get_portfolio_value()
        return holdings, portfolio_value
    except Exception as e:
        print(f"❌ 读取current_holdings.py失败: {e}")
        return [], 56000

# ========== 资金面三维度缓存 ==========
def load_capital_flow_cache():
    """读取agent写入的资金面三维度缓存"""
    cache_path = os.path.join(os.path.expanduser('~/.hermes/cache'), 'capital_flow.json')
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}

def get_capital_flow(code, cache):
    """获取主力资金净流入"""
    dims = cache.get('dimensions', cache)  # 兼容新旧格式
    stock_data = dims.get('capital_flow', dims.get('stocks', {})).get(code, {})
    if stock_data:
        return stock_data.get('main_net_inflow', 0), stock_data.get('main_net_pct', 0)
    return None, None

def get_dark_pool(code, cache):
    """获取暗盘资金（融资融券+大宗交易）"""
    dims = cache.get('dimensions', cache)
    dp = dims.get('dark_pool', {}).get(code, {})
    if dp:
        return {
            'margin_balance': dp.get('margin_balance'),
            'block_trade_amount': dp.get('block_trade_amount'),
            'block_trade_count': dp.get('block_trade_count', 0),
        }
    return None

def get_dragon_tiger(code, cache):
    """获取龙虎榜数据"""
    dims = cache.get('dimensions', cache)
    dt = dims.get('dragon_tiger', {}).get(code, {})
    if dt:
        return {
            'tt_count': dt.get('tt_count', 0),
            'tt_buy': dt.get('tt_buy'),
            'tt_sell': dt.get('tt_sell'),
        }
    return None

def fetch_quotes(codes):
    """通过quote_adapter获取行情，统一返回格式"""
    # 添加脚本目录到sys.path，确保能找到quote_adapter
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    try:
        from quote_adapter import get_quotes as qa_get_quotes, get_source_name
    except ImportError as e:
        print(f"❌ 无法导入quote_adapter: {e}")
        return {}

    try:
        raw = qa_get_quotes(codes)
    except Exception as e:
        print(f"❌ 行情获取失败: {e}")
        return {}

    # 归一化字段名：quote_adapter → 本脚本格式
    results = {}
    for code, q in raw.items():
        prev = q.get('prevClose', 0)
        last = q.get('lastPrice', 0)
        # change_pct：优先用数据源返回值，否则自行计算
        change_pct = q.get('change_pct', 0)
        if change_pct == 0 and prev > 0 and last > 0:
            change_pct = round((last - prev) / prev * 100, 2)

        results[code] = {
            'name': q.get('name', ''),
            'current': last,
            'yesterday': prev,
            'open': q.get('open', 0),
            'high': q.get('high', 0),
            'low': q.get('low', 0),
            'change_pct': change_pct,
            'volume': q.get('volume', 0),
            'amount': q.get('amount', 0),
            'turnover': q.get('turnover', 0),
            'upper_limit': q.get('limit_up', 0),
            'lower_limit': q.get('limit_down', 0),
            'outer_vol': q.get('outer_vol', 0),
            'inner_vol': q.get('inner_vol', 0),
            'pe_ttm': q.get('pe_ttm', 0),
            'amplitude': q.get('amplitude', 0),
            'circ_cap': q.get('circ_cap', 0),   # circ_cap=流通市值
            'total_cap': q.get('total_cap', 0),
            'vol_ratio': q.get('vol_ratio', 0),
            'source': q.get('source', ''),
        }
    return results

def generate_report():
    now = datetime.now()
    holdings, portfolio_value = load_holdings()
    
    # 空仓快速输出
    if not holdings:
        print(f"📊 **实盘盯盘报告**")
        print(f"**时间：** {now.strftime('%Y-%m-%d %H:%M')}")
        print(f"")
        print(f"📌 **当前空仓**，实盘账户无持仓，全部为现金。")
        print(f"💰 总资产: ¥{portfolio_value:,.2f} | 现金: ¥{portfolio_value:,.2f}")
        print(f"")
        print(f"💡 行情源：腾讯API(纯)，空仓无需拉取行情。")
        return

    codes = [h['code'] for h in holdings]
    quotes = fetch_quotes(codes)
    capital_cache = load_capital_flow_cache()

    if not quotes:
        print("❌ 获取行情失败，跳过本次监控")
        return

    # 数据时效验证：检查行情是否为当日交易时段数据
    def _verify_quote_freshness(q, code=''):
        """验证行情数据是否为当日实时数据（防止过期数据触发假止损）"""
        open_price = q.get('open', 0) or q.get('openPrice', 0)
        prev_close = q.get('prevClose', 0) or q.get('prev_close', 0)
        current = q.get('current', 0) or q.get('lastPrice', 0)
        # 非交易时段open=0可以接受，但交易时段open=0且current=prev_close→数据过期
        now_hm = datetime.now().hour * 100 + datetime.now().minute
        is_trading = (930 <= now_hm <= 1130) or (1300 <= now_hm <= 1500)
        if is_trading and open_price == 0 and current > 0 and prev_close > 0 and abs(current - prev_close) < 0.01:
            return False  # 交易时段：现价=昨收且开盘=0→过期数据
        return True

    lines = []
    alerts = []

    lines.append(f"📊 **实盘盯盘报告**")
    lines.append(f"**时间：** {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # 持仓监控
    lines.append("### 📋 持仓一览")
    lines.append("| 股票 | 代码 | 现价 | 涨跌 | 涨停/跌停 | 成本 | 盈亏 | 资金面 | 状态 |")
    lines.append("|------|------|------|------|-----------|------|------|--------|------|")

    total_pnl = 0
    for h in holdings:
        q = quotes.get(h['code'])
        if not q:
            lines.append(f"| {h['name']} | {h['code']} | ⚠️无数据 | - | - | {h['cost']} | - | - | ❌数据异常 |")
            continue

        current = q['current']
        change_pct = q['change_pct']

        # 数据时效检查（防止过期数据触发假止损）
        is_fresh = _verify_quote_freshness(q, h['code'])
        if not is_fresh:
            stale_note = "⚠️数据可能过期"
            lines.append(f"| {h['name']} | {h['code']} | {current:.2f} | {change_pct:+.2f}% | - | {h['cost']} | - | - | {stale_note} |")
            alerts.append(f"⚠️ {h['name']} {h['code']} 行情数据疑似过期（现价≈昨收且开盘=0），止损判断暂缓，请核实数据源")
            continue
        pnl = (current - h['cost']) * h['shares']
        total_pnl += pnl
        pnl_pct = (current / h['cost'] - 1) * 100

        # 涨停/跌停价
        upper = q.get('upper_limit', 0)
        lower = q.get('lower_limit', 0)
        if upper > 0 and lower > 0:
            limit_str = f"¥{upper:.2f}/¥{lower:.2f}"
            # 距跌停百分比
            dist_to_lower = (current - lower) / lower * 100 if lower > 0 else 999
        else:
            limit_str = "-"
            dist_to_lower = 999

        # 资金面
        main_net, main_pct = get_capital_flow(h['code'], capital_cache)
        if main_net is not None:
            flow_icon = '🟢' if main_net > 0 else '🔴'
            flow_str = f"{flow_icon}{main_net/10000:+.0f}万"
        else:
            flow_str = "⚪无数据"

        # 状态判断
        status = "✅正常"
        alert_msg = None

        # 止损线：优先取stop字段，否则默认成本-5%
        stop_price = h.get('stop', round(h['cost'] * 0.95, 2))

        if current <= stop_price:
            status = "🚨止损!"
            alert_msg = f"🚨 **{h['name']} {h['code']}** 已跌破止损线 **{stop_price}**，现价 **{current}**，请立即处理！"
        elif current <= h['cost'] * 0.94:
            status = "⚠️预警"
            alert_msg = f"⚠️ {h['name']} {h['code']} 浮亏{pnl_pct:.1f}%，接近止损"

        # 跌停预警：距跌停<3%
        if dist_to_lower < 3:
            dl_status = "🆘跌停预警"
            dl_alert = f"🆘 **{h['name']} {h['code']}** 距跌停仅 **{dist_to_lower:.1f}%**！现价¥{current:.2f}，跌停价¥{lower:.2f}"
            if alert_msg:
                alert_msg += f"\n{dl_alert}"
            else:
                alert_msg = dl_alert
            if "止损" not in status and "预警" not in status:
                status = dl_status

        # 资金面预警
        if main_net is not None and main_net < -50000000:
            flow_alert = f"⚠️ {h['name']} {h['code']} 主力大幅净流出 {main_net/10000:+,.0f}万"
            if alert_msg:
                alert_msg += f"\n{flow_alert}"
            else:
                alert_msg = flow_alert
                status = "⚠️资金预警"

        if alert_msg:
            alerts.append(alert_msg)

        sign = '+' if change_pct >= 0 else ''
        pnl_sign = '+' if pnl >= 0 else ''
        lines.append(f"| {h['name']} | {h['code']} | {current:.2f} | {sign}{change_pct:.2f}% | {limit_str} | {h['cost']} | {pnl_sign}{pnl:.0f}元 | {flow_str} | {status} |")

    lines.append("")

    # 总计
    total_sign = '+' if total_pnl >= 0 else ''
    lines.append(f"**💰 总盈亏：{total_sign}{total_pnl:.0f}元**")
    lines.append("")

    # 资金面三维度小结
    flow_update = capital_cache.get('last_update', '无')
    lines.append(f"### 💰 资金面三维度（更新: {flow_update}）")
    lines.append("")
    
    # 维度1: 主力资金净流入
    lines.append("**主力资金净流入：**")
    flow_items = []
    for h in holdings:
        main_net, _ = get_capital_flow(h['code'], capital_cache)
        if main_net is not None:
            icon = '🟢' if main_net > 0 else '🔴'
            flow_items.append(f"{icon}{h['name']}{main_net/10000:+.0f}万")
    if flow_items:
        lines.append(" | ".join(flow_items))
    else:
        lines.append("暂无数据")
    lines.append("")

    # 维度2: 暗盘资金（融资融券+大宗交易）
    lines.append("**暗盘资金（融资融券/大宗交易）：**")
    dp_items = []
    for h in holdings:
        dp = get_dark_pool(h['code'], capital_cache)
        if dp:
            parts = []
            mb = dp.get('margin_balance')
            if mb and mb != 'null':
                parts.append(f"融资{mb}")
            bc = dp.get('block_trade_count', 0)
            ba = dp.get('block_trade_amount')
            if bc and bc > 0:
                parts.append(f"大宗{bc}笔")
            elif ba:
                parts.append(f"大宗{ba}")
            if parts:
                dp_items.append(f"{h['name']}:{'|'.join(parts)}")
    if dp_items:
        lines.append(" | ".join(dp_items))
    else:
        lines.append("暂无暗盘数据（中小盘股通常无融资融券/大宗交易）")
    lines.append("")

    # 维度3: 龙虎榜
    lines.append("**龙虎榜：**")
    dt_items = []
    for h in holdings:
        dt = get_dragon_tiger(h['code'], capital_cache)
        if dt and dt.get('tt_count', 0) > 0:
            dt_items.append(f"{h['name']}:上榜{dt['tt_count']}次")
    if dt_items:
        lines.append(" | ".join(dt_items))
    else:
        lines.append("近5天无持仓股上榜")
    lines.append("")

    # 预警区
    if alerts:
        lines.append("### 🚨 紧急预警")
        for a in alerts:
            lines.append(a)
        lines.append("")

    # 提示
    lines.append("### 💡 提示")
    lines.append("- 持仓监控仅覆盖已列出的持仓，请结合大盘和板块判断")
    lines.append("- 止损线触发请立即处理，不要犹豫")
    lines.append("- 🆘跌停预警：距跌停<3%时触发，注意封板风险")
    lines.append("- 资金面数据由妙想MX提供，每30分钟更新一次；行情数据源：腾讯API(纯)")

    report = "\n".join(lines)
    print(report)

    # 如果有紧急预警（止损/跌停），返回非零退出码（方便监控）
    if any("🚨" in a or "🆘" in a for a in alerts):
        sys.exit(1)

if __name__ == '__main__':
    # 非交易时间直接退出，不输出
    if not is_trading_time():
        sys.exit(0)
    generate_report()
