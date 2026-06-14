#!/usr/bin/env python3
"""
V10 盘中盯盘监控器 v2
数据源：quote_adapter统一接口（QMT/腾讯自动切换）
观察池：~/.hermes/cache/v10_watchlist.json（每日盘前V10扫描生成）

入场条件（满足任一即触发）：
1. 回踩支撑：现价接近EMA7/EMA20（±1.5%）且未破EMA20
2. 缩量企稳：今日振幅<3% 且 现价>EMA20 且 量比<1.5 且 涨跌>-1%
3. 放量突破：现价>30日最高 且 成交额>5000万（确认有量）

风控条件（触发任一则标记风险）：
- 破止损位（现价<stop_loss）
- 破EMA20（现价<EMA20 * 0.98）
- 今日涨幅>7%（追高警告）
"""

import json
import sys
import os
from datetime import datetime

# 添加scripts目录到路径
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from sector_analysis import get_sector_ranking, analyze_sector_rotation, get_sector_summary
from quote_adapter import get_quotes, get_source_name

WATCHLIST_PATH = os.path.expanduser('~/.hermes/cache/v10_watchlist.json')
ALERT_STATE_PATH = os.path.expanduser('~/.hermes/cache/v10_monitor_alerted.json')

# ====== 数据源验证 ======

def verify_market_open():
    """验证当前是否在交易时间（含集合竞价）"""
    now = datetime.now()
    h, m = now.hour, now.minute
    t = h * 100 + m
    # 9:15-9:25 竞价, 9:30-11:30 上午, 13:00-15:00 下午
    return (915 <= t <= 925) or (930 <= t <= 1130) or (1300 <= t <= 1500)


def verify_watchlist_freshness(data):
    """验证观察池是否是当天且未过期的
    返回: (is_fresh, message)
    is_fresh=False 但仍可降级使用（不再直接跳过），主流程根据返回值决定标记
    """
    scan_time = data.get('scan_time', '')
    if not scan_time:
        return False, '观察池无时间戳'
    today = datetime.now().strftime('%Y-%m-%d')
    if today not in scan_time:
        return False, f'观察池过期（生成于{scan_time}）'
    
    # ⏰ 分钟级时效：超过30分钟的watchlist标记为过期但仍可降级使用
    # 全扫描15分钟一轮，30分钟内数据较新；30-120分钟降级使用加⚠️；超120分钟不使用
    try:
        st = datetime.strptime(scan_time[:16], '%Y-%m-%d %H:%M')
        age_min = (datetime.now() - st).total_seconds() / 60
        if age_min > 120:
            return False, f'观察池严重过期{int(age_min)}分钟（{scan_time[:16]}），不可使用'
        if age_min > 30:
            # 降级：可用但标记为过期
            return True, f'⚠️观察池{int(age_min)}分钟前（{scan_time[:16]}），降级使用'
    except ValueError:
        pass
    
    return True, scan_time


def verify_quote_freshness(quote):
    """验证行情数据是否是当前交易日的"""
    # 非交易时段数据源可能返回昨收数据
    # 如果价格=昨收 且 开盘=0，说明是停牌或非交易时段
    if quote['open'] == 0 and quote['price'] == quote['yclose']:
        return False, '可能停牌或非交易时段'
    return True, '正常'


# ====== 数据获取 ======

def load_watchlist():
    """加载观察池"""
    try:
        with open(WATCHLIST_PATH, 'r') as f:
            data = json.load(f)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_alerted():
    """加载已推送记录"""
    try:
        with open(ALERT_STATE_PATH, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return {}


def save_alerted(alerted):
    """保存已推送记录"""
    try:
        with open(ALERT_STATE_PATH, 'w') as f:
            json.dump(alerted, f, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ 保存推送记录失败: {e}", file=sys.stderr)


def fetch_realtime_quotes(codes):
    """批量获取实时行情（通过quote_adapter统一接口，纯腾讯API）"""
    raw = get_quotes(codes)
    results = {}
    for code, q in raw.items():
        # quote_adapter字段映射到monitor内部格式
        price = q.get('lastPrice', 0) or q.get('price', 0)
        prev_close = q.get('prevClose', 0) or q.get('yclose', 0)
        change_pct = q.get('change_pct', 0)
        if not change_pct and prev_close > 0 and price > 0:
            change_pct = round((price - prev_close) / prev_close * 100, 2)

        amount = q.get('amount', 0)
        # QMT返回amount单位为元，需转为万元；腾讯返回万元
        source = q.get('source', '')
        if source.startswith('qmt') and amount > 0:
            amount = amount / 10000

        results[code] = {
            'name': q.get('name', ''),
            'price': price,
            'yclose': prev_close,
            'open': q.get('open', 0),
            'high': q.get('high', 0),
            'low': q.get('low', 0),
            'change_pct': change_pct,
            'volume': q.get('volume', 0),
            'amount': amount,
            'turnover': q.get('turnover', 0),
            'upper_limit': q.get('limit_up', 0),
            'lower_limit': q.get('limit_down', 0),
            'outer_vol': q.get('outer_vol', 0),
            'inner_vol': q.get('inner_vol', 0),
            'pe_ttm': q.get('pe_ttm', 0),
            'amplitude': q.get('amplitude', 0),
            'circ_cap': q.get('circ_cap', 0),
            'total_cap': q.get('total_cap', 0),
            'vol_ratio': q.get('vol_ratio', 0),
            'source': source,
        }
    return results


# ====== 信号判断 ======

def judge_entry(stock, quote):
    """
    判断入场/风险信号
    返回: (action, reason, level)
    action: 'buy' | 'risk' | 'watch' | 'skip'
    """
    price = quote['price']
    if price <= 0:
        return 'skip', '停牌', 0

    # 数据有效性检查
    fresh, msg = verify_quote_freshness(quote)
    if not fresh:
        return 'skip', f'⚠️ {msg}', 0

    levels = stock.get('key_levels', {})
    ema7 = levels.get('ema7', 0)
    ema20 = levels.get('ema20', 0)
    ema120 = levels.get('ema120', 0)
    ema200 = levels.get('ema200', 0)
    high_30d = levels.get('high_30d', 0)
    stop_loss = levels.get('stop_loss', 0)

    yclose = quote['yclose']
    change_pct = quote['change_pct']
    amount = quote['amount']  # 成交额（万元）

    # 日内指标
    day_range = quote['high'] - quote['low'] if quote['low'] > 0 else 0
    day_range_pct = (day_range / yclose * 100) if yclose > 0 else 0

    # ====== 风控检查（优先级最高）======

    # 破止损位
    if stop_loss > 0 and price < stop_loss:
        return 'risk', f'🔴 破止损位 ¥{stop_loss:.2f}（现价{price:.2f}）', 3

    # 破EMA20
    if ema20 > 0 and price < ema20 * 0.98:
        return 'risk', f'🔴 跌破EMA20 ¥{ema20:.2f}（现价{price:.2f}）', 2

    # 追高警告（06-10升级：Vibe感知版）
    # 新规则：Vibe≥+2强时追高豁免（强趋势票不因涨多了就标risk）
    code = stock['code']
    name = stock.get('name', '')
    vibe_tags = stock.get('vibe_tags', '')
    signal = stock.get('signal', '')
    # 判断是否强趋势票：Vibe≥+2 且 信号为全买入/强庄买
    is_strong_trend = False
    # 优先读vibe_score整数字段（V10扫描已保存），回退从vibe_tags提取
    vibe_score_val = stock.get('vibe_score', 0)
    if not isinstance(vibe_score_val, (int, float)) or vibe_score_val == 0:
        # 回退：从vibe_tags列表中计算（BOS多头+2, ChoCH多头+2, FVG+N取N, 其余+1）
        if isinstance(vibe_tags, list):
            for tag in vibe_tags:
                tag_s = str(tag).strip()
                if tag_s.startswith('BOS'):
                    vibe_score_val += 2
                elif tag_s.startswith('ChoCH'):
                    vibe_score_val += 2
                elif tag_s.startswith('FVG'):
                    import re as _re
                    _m = _re.search(r'([+-]?\d+)', tag_s)
                    if _m:
                        vibe_score_val += int(_m.group(1))
                elif tag_s in ('K线看多', '缠论二买', '缠论三买'):
                    vibe_score_val += 1
        elif isinstance(vibe_tags, str) and vibe_tags.strip():
            import re as _re
            _m = _re.match(r'([+-]?\d+)', vibe_tags.strip())
            if _m:
                vibe_score_val = int(_m.group(1))
    if vibe_score_val >= 2 and signal in ('全买入', '强庄买'):
        is_strong_trend = True
    # 涨停一票否决线（不变）
    price_limit_pct = 20.0 if code.startswith('3') else 10.0
    hard_limit_pct = price_limit_pct * 0.95  # 创业板19% / 主板9.5%
    if code.startswith('3'):
        chase_limit = 15
    elif 'ST' in name.upper():
        chase_limit = 4
    else:
        chase_limit = 7
    if abs(change_pct) >= hard_limit_pct:
        return 'risk', f'⛔ 接近涨停{change_pct:+.1f}%（限制{price_limit_pct:.0f}%），一票否决', 3
    if change_pct > chase_limit:
        if is_strong_trend:
            # Vibe≥+2强 + 强信号：追高豁免，降级为观察+提醒
            return 'watch', f'⚡ 涨{change_pct:.1f}%超阈值但Vibe≥+2强趋势，追高豁免', 0
        else:
            return 'risk', f'⚠️ 今日已涨{change_pct:.1f}%，追高风险大（阈值{chase_limit}%）', 1

    # ====== 入场信号检查 ======

    # 仓位控制检查（铁律：单票≤20%，两票≤30%）
    try:
        import sys, os
        sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
        from current_holdings import get_holdings, get_portfolio_value, get_cash
        _holdings = get_holdings()
        _pv = get_portfolio_value()
        _cash = get_cash()
        _current_positions = len(_holdings)
        _total_position_pct = sum(h['shares'] * h['cost'] for h in _holdings) / _pv * 100 if _pv > 0 else 0
        # 检查是否还能买入
        _buy_amount = price * 100  # 最小1手100股
        _new_position_pct = _buy_amount / _pv * 100
        if _current_positions >= 2:
            return 'skip', f'⛔ 已有{_current_positions}只持仓，仓位上限（两票≤30%），不可再加仓', 0
        if _current_positions == 1 and _total_position_pct + _new_position_pct > 30:
            return 'skip', f'⛔ 加仓后总仓位将超30%（当前{_total_position_pct:.1f}%+新{_new_position_pct:.1f}%）', 0
        if _new_position_pct > 20:
            return 'skip', f'⛔ 单票仓位将超20%（{_new_position_pct:.1f}%）', 0
        if _cash < _buy_amount:
            return 'skip', f'⛔ 现金不足（¥{_cash:.0f} < 1手¥{_buy_amount:.0f}）', 0
    except Exception:
        pass  # 读取持仓失败不阻塞，但继续后续检查

    # 冷静期检查（连亏3次冷静2天）
    try:
        import json as _json
        _tracker_path = os.path.expanduser('~/.hermes/cache/tail_rec_tracker.json')
        if os.path.exists(_tracker_path):
            with open(_tracker_path) as _f:
                _tracker = _json.load(_f)
            _streak_loss = _tracker.get('streak_loss', 0)
            _cooldown = _tracker.get('cooldown_until', '')
            if _cooldown:
                from datetime import datetime as _dt
                try:
                    _cd_time = _dt.strptime(_cooldown, '%Y-%m-%d')
                    if _dt.now() < _cd_time:
                        return 'skip', f'🧊 冷静期中（连亏{_streak_loss}次，至{_cooldown}），暂停推荐', 0
                except ValueError:
                    pass
            if _streak_loss >= 3:
                return 'skip', f'🧊 连亏{_streak_loss}次，触发冷静期', 0
    except Exception:
        pass

    # 止损空间检查（七关第⑦关：止损空间≥5%）
    if stop_loss > 0:
        stop_loss_pct = (price - stop_loss) / price * 100
        if stop_loss_pct < 5:
            return 'skip', f'⛔ 止损空间仅{stop_loss_pct:.1f}%（¥{price:.2f}→止损¥{stop_loss:.2f}），不足5%不可入场', 0
    elif ema20 > 0:
        # 无明确止损位时用EMA20作为参考止损
        ema_stop_pct = (price - ema20) / price * 100
        if ema_stop_pct < 5:
            return 'skip', f'⛔ 距EMA20仅{ema_stop_pct:.1f}%（¥{price:.2f}→EMA20¥{ema20:.2f}），止损空间不足5%', 0

    # 信号1：回踩支撑（现价接近EMA7或EMA20，且未破EMA20）
    if ema7 > 0 and ema20 > 0:
        near_ema7 = abs(price - ema7) / ema7 * 100
        near_ema20 = abs(price - ema20) / ema20 * 100

        if price >= ema20 and near_ema7 <= 1.5:
            return 'buy', f'📍 回踩EMA7 ¥{ema7:.2f}（偏离{near_ema7:.1f}%）', 2

        if price >= ema20 and near_ema20 <= 1.5:
            return 'buy', f'📍 回踩EMA20 ¥{ema20:.2f}（偏离{near_ema20:.1f}%）', 2

    # 信号2：缩量企稳（必须同时满足振幅小+价格在EMA20之上+不跌+量比低）
    if (day_range_pct < 3 and ema20 > 0 and price > ema20
            and change_pct > -1 and change_pct < 3):
        return 'buy', f'🟢 缩量企稳(振幅{day_range_pct:.1f}% 涨跌{change_pct:+.1f}%)', 1

    # 信号3：放量突破30日高点（必须有量确认：成交额>5000万）
    if high_30d > 0 and price > high_30d and amount > 5000:
        return 'buy', f'🚀 放量突破30日新高 ¥{high_30d:.2f}（成交额{amount:.0f}万）', 3

    # 其他：继续观察
    return 'watch', f'👀 观察中 ¥{price:.2f} EMA20={ema20:.2f}', 0


def format_report(stock, quote, action, reason, level):
    """格式化单只股票的报告"""
    emoji_map = {'buy': '🟢', 'risk': '🔴', 'watch': '⚪', 'skip': '⚫'}
    emoji = emoji_map.get(action, '⚪')

    signal_tag = stock.get('signal', '')
    vibe = stock.get('vibe_tags', '')
    vibe_score_val = stock.get('vibe_score', 0)
    # 盘中版Vibe来自tech_analysis（SMC+缠论+K线形态），无[竞价版]标注
    vibe_str = f' Vibe:{vibe}' if vibe and vibe != '-' else ''
    if vibe_score_val != 0:
        vibe_str = f' Vibe{"+" if vibe_score_val > 0 else ""}{vibe_score_val}({vibe})' if vibe else vibe_str

    note = stock.get('note', '')
    note_str = f'\n   💡 {note}' if note else ''

    # 涨停/跌停信息
    upper = quote.get('upper_limit', 0)
    lower = quote.get('lower_limit', 0)
    limit_str = ''
    if upper > 0 and lower > 0:
        limit_str = f' | 涨停¥{upper:.2f}/跌停¥{lower:.2f}'

    return (
        f"{emoji} **{stock['name']}**({stock['code']}) {reason}\n"
        f"   信号:{signal_tag}{vibe_str}\n"
        f"   现价:¥{quote['price']:.2f} | 涨跌:{quote['change_pct']:+.1f}% | "
        f"振幅:{((quote['high']-quote['low'])/quote['yclose']*100) if quote['yclose']>0 else 0:.1f}% | "
        f"成交:{quote['amount']:.0f}万{limit_str}"
        f"{note_str}"
    )


# ====== 主流程 ======

def main():
    now = datetime.now()
    time_str = now.strftime('%H:%M:%S')
    date_str = now.strftime('%Y-%m-%d')

    # [检查1] 交易时间 — 非交易时间直接退出，不输出任何内容（避免cron推送垃圾信息）
    if not verify_market_open():
        return

    # [检查2] 观察池
    wl_data = load_watchlist()
    if not wl_data or not wl_data.get('stocks'):
        print(f"[{time_str}] 观察池为空，跳过盯盘")
        return

    # [检查3] 观察池时效（降级机制：30-120分钟降级使用，>120分钟才跳过）
    fresh, msg = verify_watchlist_freshness(wl_data)
    if not fresh:
        print(f"[{time_str}] ❌ {msg}，跳过盯盘")
        return
    is_stale = '⚠️' in msg  # 降级使用标记

    stocks = wl_data['stocks']
    scan_time = wl_data.get('scan_time', '未知')

    # [检查4] 获取实时行情
    codes = [s['code'] for s in stocks]
    quotes = fetch_realtime_quotes(codes)
    if not quotes:
        print(f"[{time_str}] ❌ 获取行情失败，请检查网络")
        return

    # 逐只判断
    buy_signals = []
    risk_signals = []
    watch_list = []
    skipped = 0

    for stock in stocks:
        code = stock['code']
        quote = quotes.get(code)
        if not quote or quote['price'] <= 0:
            skipped += 1
            continue

        action, reason, level = judge_entry(stock, quote)
        report = format_report(stock, quote, action, reason, level)

        if action == 'buy':
            buy_signals.append((report, level))
        elif action == 'risk':
            risk_signals.append((report, level))
        elif action == 'skip':
            skipped += 1
        else:
            watch_list.append(report)

    # 按level排序（风险高的在前）
    buy_signals.sort(key=lambda x: -x[1])
    risk_signals.sort(key=lambda x: -x[1])

    # 生成报告
    lines = []
    # 计算观察池数据距今时间
    age_text = ''
    try:
        scan_dt = datetime.strptime(scan_time[:16], '%Y-%m-%d %H:%M')
        now_dt = datetime.now()
        age_min = int((now_dt - scan_dt).total_seconds() / 60)
        if age_min < 1:
            age_text = '(刚刚)'
        elif age_min < 5:
            age_text = f'({age_min}分钟前)'
        elif age_min < 60:
            age_text = f'(⚠️{age_min}分钟前)'
        else:
            age_text = f'(❌过期{age_min}分钟)'
    except:
        pass
    source_name = get_source_name()
    stale_marker = ' ⚠️降级数据' if is_stale else ''
    lines.append(f"📡 **V10盘中监控** {date_str} {time_str[:5]} | 数据源:{source_name}{stale_marker}")
    lines.append(f"观察池:{len(stocks)}只 | 扫描于:{scan_time[:16]} {age_text}")
    lines.append('')
    
    # 添加板块概况
    try:
        sector_summary = get_sector_summary()
        if sector_summary and "不可用" not in sector_summary:
            lines.append(sector_summary)
            lines.append('')
    except Exception as e:
        pass  # 板块信息获取失败不影响主报告

    # [1] 当天全买入信号（无论是否触发入场，全部列出）
    full_buy_stocks = [s for s in stocks if '全买入' in s.get('signal', '')]
    strong_buy_stocks = [s for s in stocks if '强庄买' in s.get('signal', '') and '全买入' not in s.get('signal', '')]

    if full_buy_stocks:
        lines.append(f"**🔴 全买入信号 ({len(full_buy_stocks)}只):**")
        for s in full_buy_stocks:
            q = quotes.get(s['code'])
            if q and q['price'] > 0:
                chg = q['change_pct']
                ul = q.get('upper_limit', 0)
                ll = q.get('lower_limit', 0)
                lim = f' 涨停¥{ul:.2f}/跌停¥{ll:.2f}' if ul > 0 and ll > 0 else ''
                lines.append(f"  {s['name']}({s['code']}) ¥{q['price']:.2f} {chg:+.1f}% | 成交{q['amount']:.0f}万{lim}")
            else:
                lines.append(f"  {s['name']}({s['code']}) ¥{s.get('price',0):.2f}")
        lines.append('')

    if strong_buy_stocks:
        lines.append(f"**🟠 强庄买信号 ({len(strong_buy_stocks)}只):**")
        for s in strong_buy_stocks[:10]:  # 最多显示10只
            q = quotes.get(s['code'])
            if q and q['price'] > 0:
                chg = q['change_pct']
                ul = q.get('upper_limit', 0)
                ll = q.get('lower_limit', 0)
                lim = f' 涨停¥{ul:.2f}/跌停¥{ll:.2f}' if ul > 0 and ll > 0 else ''
                lines.append(f"  {s['name']}({s['code']}) ¥{q['price']:.2f} {chg:+.1f}% | 成交{q['amount']:.0f}万{lim}")
        if len(strong_buy_stocks) > 10:
            lines.append(f"  ...及{len(strong_buy_stocks)-10}只")
        lines.append('')

    # [2] 入场/风控信号
    if buy_signals:
        lines.append(f"**🟢 入场信号 ({len(buy_signals)}只):**")
        # 构建code→stock映射
        stock_map = {s['code']: s for s in stocks}
        for r, level in buy_signals:
            lines.append(r)
        lines.append('')

        # [买入推荐小结] 综合评估可入场标的
        pick_lines = []
        for r, level in buy_signals:
            for code, s in stock_map.items():
                if f'({code})' in r:
                    quote = quotes.get(code, {})
                    vibe = s.get('vibe_tags', '-')
                    signal_tag = s.get('signal', '')
                    change_pct = quote.get('change_pct', 0)
                    amount = quote.get('amount', 0)
                    price = quote.get('price', 0)

                    # 评分维度
                    stars = ''
                    reasons = []

                    # V10信号：全买入★★★ 强庄买★★☆ 基础买★☆☆
                    if '全买入' in signal_tag:
                        stars = '★★★'
                        reasons.append('V10全买入')
                    elif '强庄买' in signal_tag:
                        stars = '★★☆'
                        reasons.append('V10强庄买')
                    else:
                        stars = '★☆☆'
                        reasons.append('V10基础信号')

                    # Vibe评分
                    try:
                        vs = float(vibe) if vibe.replace('.','',1).lstrip('-').isdigit() else 0
                    except:
                        vs = 0

                    # 入场理由
                    if '回踩EMA7' in r:
                        reasons.append('回踩EMA7支撑')
                    elif '回踩EMA20' in r:
                        reasons.append('回踩EMA20支撑')
                    elif '放量突破' in r:
                        reasons.append('放量突破新高')
                    elif '缩量企稳' in r:
                        reasons.append('缩量企稳')

                    # 量能判断
                    if amount > 10000:
                        reasons.append(f'放量{amount/10000:.1f}亿')
                    elif amount > 5000:
                        reasons.append(f'成交{amount:.0f}万')

                    # 盘口判断
                    if -0.5 <= change_pct <= 1.5:
                        reasons.append('窄幅盘整')
                    elif 1.5 < change_pct < 7:
                        reasons.append('温和上涨')

                    # 最终评级 + 止损位
                    levels = s.get('key_levels', {})
                    stop_loss = levels.get('stop_loss', 0)
                    rating = f'{stars} {s["name"]}({code}) ¥{price:.2f}'
                    if reasons:
                        rating += f' — {"|".join(reasons)}'
                    if stop_loss > 0:
                        stop_pct = (price - stop_loss) / price * 100
                        rating += f' | 止损¥{stop_loss:.2f}({stop_pct:.1f}%)'

                    pick_lines.append(rating)
                    break

        if pick_lines:
            lines.append(f"**🎯 买入推荐（共{len(pick_lines)}只）:**")
            for pl in pick_lines:
                lines.append(f"  {pl}")
            lines.append('')

    if risk_signals:
        lines.append(f"**🔴 风险预警 ({len(risk_signals)}只):**")
        for r, _ in risk_signals:
            lines.append(r)
        lines.append('')

    if watch_list and (buy_signals or risk_signals):
        lines.append(f"**⚪ 观察中 ({len(watch_list)}只):**")
        for r in watch_list[:5]:
            lines.append(r)
        if len(watch_list) > 5:
            lines.append(f"  ...及{len(watch_list)-5}只")
        lines.append('')

    if skipped:
        lines.append(f"⚫ 跳过: {skipped}只（停牌/无数据）")

    report = '\n'.join(lines)

    # 输出
    if full_buy_stocks or strong_buy_stocks or buy_signals or risk_signals:
        print(report)
    else:
        print(f"📡 {time_str[:5]} V10监控: {len(stocks)}只观察中 | 无信号无风险")

if __name__ == '__main__':
    main()
