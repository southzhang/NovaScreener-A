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

# V12猎庄KDJ模块（可选导入，失败不影响主流程）
_KDJ_AVAILABLE = False
try:
    from kdj_strategy import calc_indicators, fetch_kline as _kdj_fetch_kline
    _KDJ_AVAILABLE = True
except ImportError:
    pass

# 全局变量：资金面缓存和大盘指数，供judge_entry使用
_cf_global = {}
_mkt_global = {}

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

    # 仓位提示（不拦截推荐，仅标注⚠️，仓位管理交给实盘盯盘）
    position_warning = ''
    try:
        import sys, os
        sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
        from current_holdings import get_holdings, get_portfolio_value, get_cash
        _holdings = get_holdings()
        _pv = get_portfolio_value()
        _cash = get_cash()
        _current_positions = len(_holdings)
        _total_position_pct = sum(h['shares'] * h['cost'] for h in _holdings) / _pv * 100 if _pv > 0 else 0
        _buy_amount = price * 100
        _new_position_pct = _buy_amount / _pv * 100
        if _current_positions >= 2:
            position_warning = f'⚠️已有{_current_positions}只持仓，注意仓位'
        elif _current_positions == 1 and _total_position_pct + _new_position_pct > 30:
            position_warning = f'⚠️加仓后仓位将超30%'
        elif _new_position_pct > 20:
            position_warning = f'⚠️单票仓位将超20%（{_new_position_pct:.1f}%）'
    except Exception:
        pass

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

    # 止损空间检查（七关第⑦关：止损空间≥8%，策略v2）
    if stop_loss > 0:
        stop_loss_pct = (price - stop_loss) / price * 100
        if stop_loss_pct < 8:
            return 'skip', f'⛔ 止损空间仅{stop_loss_pct:.1f}%（¥{price:.2f}→止损¥{stop_loss:.2f}），不足8%不可入场', 0
    elif ema20 > 0:
        # 无明确止损位时用EMA20作为参考止损
        ema_stop_pct = (price - ema20) / price * 100
        if ema_stop_pct < 8:
            return 'skip', f'⛔ 距EMA20仅{ema_stop_pct:.1f}%（¥{price:.2f}→EMA20¥{ema20:.2f}），止损空间不足8%', 0

    # ====== 增强因子（五因子：资金面+大盘+换手+内外盘+PE/PB） ======
    extra_warnings = []  # 附加到报告的warnings

    # 仓位提示（不拦截推荐，仅标注⚠️）
    if position_warning:
        extra_warnings.append(position_warning)

    # 资金面否决（从capital_flow缓存读取）
    _cf_data = _cf_global.get(code) if isinstance(_cf_global, dict) else None
    if _cf_data and isinstance(_cf_data, dict):
        _cf_inflow = _cf_data.get('main_net_inflow', 0)
        if isinstance(_cf_inflow, (int, float)) and _cf_inflow < -5000:
            is_strong = signal in ('全买入', '强庄买')
            if signal == '基础买':
                return 'skip', f'❌ 主力净流出{abs(_cf_inflow):.0f}万，资金面不支持', 0
            elif not is_strong:
                extra_warnings.append(f'⚠️主力净流出{abs(_cf_inflow):.0f}万')

    # 大盘环境
    _mkt = _mkt_global or {}
    if _mkt:
        _sh = _mkt.get('上证', {}).get('change_pct', 0)
        _sz = _mkt.get('深证', {}).get('change_pct', 0)
        _max_drop = min(_sh, _sz)
        if _max_drop < -2.0 and signal != '全买入':
            return 'skip', f'❌ 大盘暴跌（上证{_sh:+.1f}%/深证{_sz:+.1f}%），弱市只推★★★', 0
        elif _max_drop < -1.0:
            if signal == '基础买':
                return 'skip', f'❌ 大盘下跌{_max_drop:+.1f}%，★☆☆不推', 0
            if signal == '强庄买':
                return 'skip', f'❌ 大盘下跌{_max_drop:+.1f}%，★★☆也不推（弱市收紧）', 0
            extra_warnings.append(f'大盘下跌{_max_drop:+.1f}%')
        elif _max_drop < -0.5:
            if signal == '基础买':
                return 'skip', f'❌ 大盘微跌{_max_drop:+.1f}%，★☆☆不推', 0
            extra_warnings.append(f'大盘偏弱{_max_drop:+.1f}%')
    
    # 板块共振（问财热度）
    try:
        from iwencai_sector import is_hot_sector
        _code = stock.get('code', '')
        _name = stock.get('name', '')
        _is_hot, _hot_name = is_hot_sector(_code, _name)
        if _is_hot:
            extra_warnings.append(f'🔥板块共振({_hot_name})')
    except Exception:
        pass

    # 换手率
    _turnover = quote.get('turnover', 0)
    if _turnover > 15:
        extra_warnings.append(f'换手率{_turnover:.1f}%偏高')

    # 内外盘比
    _outer = quote.get('outer_vol', 0)
    _inner = quote.get('inner_vol', 0)
    if _outer > 0 and _inner > 0:
        _oi = _outer / _inner
        if _oi < 0.6:
            extra_warnings.append(f'外/内盘{_oi:.1f}x卖方主导')

    # PE极端
    _pe = quote.get('pe_ttm', 0)
    if _pe < 0:
        extra_warnings.append('PE为负(亏损)')
    elif _pe > 200 and signal == '基础买':
        return 'skip', f'❌ PE={_pe:.0f}估值过高，★☆☆不推', 0

    # 信号1：回踩支撑（现价接近EMA7或EMA20，且未破EMA20）
    if ema7 > 0 and ema20 > 0:
        near_ema7 = abs(price - ema7) / ema7 * 100
        near_ema20 = abs(price - ema20) / ema20 * 100

        if price >= ema20 and near_ema7 <= 1.5:
            _extra = ' '.join(extra_warnings) if extra_warnings else ''
            return 'buy', f'📍 回踩EMA7 ¥{ema7:.2f}（偏离{near_ema7:.1f}%）{_extra}'.strip(), 2

        if price >= ema20 and near_ema20 <= 1.5:
            _extra = ' '.join(extra_warnings) if extra_warnings else ''
            return 'buy', f'📍 回踩EMA20 ¥{ema20:.2f}（偏离{near_ema20:.1f}%）{_extra}'.strip(), 2

    # 信号2：缩量企稳（必须同时满足振幅小+价格在EMA20之上+不跌+量比低）
    if (day_range_pct < 3 and ema20 > 0 and price > ema20
            and change_pct > -1 and change_pct < 3):
        _extra = ' '.join(extra_warnings) if extra_warnings else ''
        return 'buy', f'🟢 缩量企稳(振幅{day_range_pct:.1f}% 涨跌{change_pct:+.1f}%) {_extra}'.strip(), 1

    # 信号3：放量突破30日高点（必须有量确认：成交额>5000万）
    if high_30d > 0 and price > high_30d and amount > 5000:
        _extra = ' '.join(extra_warnings) if extra_warnings else ''
        return 'buy', f'🚀 放量突破30日新高 ¥{high_30d:.2f}（成交额{amount:.0f}万）{_extra}'.strip(), 3

    # 信号4：V12猎庄KDJ金叉入场（改性KDJ VAR1上穿8 + EMA20>EMA60趋势过滤）
    kdj_entry = stock.get('_kdj_entry')
    if kdj_entry and kdj_entry.get('signal'):
        var1 = kdj_entry.get('var1', 0)
        tunnel = ' V10共振' if kdj_entry.get('v10_resonance') else ''
        buildup = ' 建仓区' if kdj_entry.get('buildup') else ''
        _extra = ' '.join(extra_warnings) if extra_warnings else ''
        return 'buy', f'🔮 V12金叉 VAR1={var1:.1f}{tunnel}{buildup} {_extra}'.strip(), 2

    # 其他：继续观察
    _extra = ' '.join(extra_warnings) if extra_warnings else ''
    return 'watch', f'👀 观察中 ¥{price:.2f} EMA20={ema20:.2f} {_extra}'.strip(), 0


def format_report(stock, quote, action, reason, level, capital_flow_data=None):
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

    # V10 v2增强标注
    v2_tags = []
    if stock.get('position_warning'):
        v2_tags.append(f'⚠️{stock["position_warning"]}')
    if stock.get('vol_quality'):
        v2_tags.append(stock['vol_quality'])
    v2_str = f' | {" | ".join(v2_tags)}' if v2_tags else ''

    # 涨停/跌停信息
    upper = quote.get('upper_limit', 0)
    lower = quote.get('lower_limit', 0)
    limit_str = ''
    if upper > 0 and lower > 0:
        limit_str = f' | 涨停¥{upper:.2f}/跌停¥{lower:.2f}'

    # 资金面信息
    cf_str = ''
    if capital_flow_data and isinstance(capital_flow_data, dict):
        cf = capital_flow_data.get('main_net_inflow', 0)
        if cf != 0:
            d = "流入" if cf > 0 else "流出"
            amt = abs(cf)
            s = f"{amt/10000:.2f}亿" if amt >= 10000 else f"{amt:.0f}万"
            cf_str = f'\n   💰 主力净{d}: {s}'

    return (
        f"{emoji} **{stock['name']}**({stock['code']}) {reason}{v2_str}\n"
        f"   信号:{signal_tag}{vibe_str}\n"
        f"   现价:¥{quote['price']:.2f} | 涨跌:{quote['change_pct']:+.1f}% | "
        f"振幅:{((quote['high']-quote['low'])/quote['yclose']*100) if quote['yclose']>0 else 0:.1f}% | "
        f"成交:{quote['amount']:.0f}万{limit_str}"
        f"{cf_str}"
        f"{note_str}"
    )


# ====== 多维度评分系统 ======

def score_buy_candidate(stock, quote, signal_tag, vibe_tags, reason_text,
                        capital_flow_data=None, fund_data=None, sector_data=None):
    """
    多维度评分买入候选股 (总分100)
    返回: (total_score, score_detail_dict)
    
    评分维度:
      ① 技术面 (30分): V10信号 + Vibe + 入场信号
      ② 资金面 (25分): 主力净流入 + 超大单/流入占比
      ③ 基本面 (20分): PE + 营收增长 + 净利增长
      ④ 板块热度 (15分): 板块评分 + 板块涨幅 + 热门共振
      ⑤ 风控 (10分): 止损空间 + 换手率 + 内外盘比
    """
    detail = {}
    code = stock.get('code', '')
    
    # ========== ① 技术面 (30分) ==========
    tech_score = 0
    
    # V10信号 (0-15)
    if '全买入' in signal_tag:
        tech_score += 15
        detail['V10信号'] = '★★★全买入(+15)'
    elif '强庄买' in signal_tag:
        tech_score += 10
        detail['V10信号'] = '★★☆强庄买(+10)'
    else:
        tech_score += 5
        detail['V10信号'] = '★☆☆基础买(+5)'
    
    # Vibe评分 (0-10)
    vibe_score_val = stock.get('vibe_score', 0)
    if not isinstance(vibe_score_val, (int, float)) or vibe_score_val == 0:
        # 尝试从vibe_tags解析
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
    
    vibe_pts = min(max(vibe_score_val * 1.5, 0), 10)
    tech_score += vibe_pts
    detail['Vibe'] = f'{vibe_score_val:+.0f}(+{vibe_pts:.0f})'

    # 入场信号 (0-5)
    if '放量突破' in reason_text:
        tech_score += 5
        detail['入场信号'] = '放量突破(+5)'
    elif '回踩EMA7' in reason_text or '回踩EMA20' in reason_text:
        tech_score += 3
        detail['入场信号'] = '回踩支撑(+3)'
    elif '缩量企稳' in reason_text:
        tech_score += 2
        detail['入场信号'] = '缩量企稳(+2)'

    # V10 v2增强：放量质量+量比趋势+位置（技术面加分/扣分）
    vol_quality = stock.get('vol_quality', '')
    vol_trend = stock.get('vol_trend', 0)
    position_warning = stock.get('position_warning', '')
    dist_ema7 = stock.get('dist_ema7', 0)
    dist_ema20 = stock.get('dist_ema20', 0)

    if vol_quality == '连续放量✅':
        tech_score += 2
        detail['放量趋势'] = '连续放量(+2)'
    elif vol_quality == '阴线放量⚠️':
        tech_score -= 3
        detail['放量质量'] = '阴线放量(-3)'

    if isinstance(vol_trend, (int, float)) and vol_trend > 1.3:
        tech_score += 1
        detail['量比趋势'] = f'{vol_trend:.1f}x(+1)'

    if position_warning:
        if '高位' in position_warning:
            tech_score -= 3
            detail['位置'] = f'{position_warning}(-3)'
        elif '偏高' in position_warning:
            tech_score -= 1
            detail['位置'] = f'{position_warning}(-1)'
    elif isinstance(dist_ema7, (int, float)) and dist_ema7 <= 3:
        tech_score += 2
        detail['位置'] = f'回调EMA7({dist_ema7:.1f}%)(+2)'

    # 技术面封顶30
    tech_score = min(tech_score, 30)
    detail['技术面'] = f'{tech_score:.0f}/30'
    
    # ========== ② 资金面 (25分) ==========
    fund_flow_score = 0
    
    if capital_flow_data and isinstance(capital_flow_data, dict):
        main_inflow = capital_flow_data.get('main_net_inflow', 0)
        if isinstance(main_inflow, (int, float)):
            abs_inflow = abs(main_inflow)
            # 主力净流入 (0-15)
            if main_inflow > 10000:  # >1亿
                fund_flow_score += 15
                detail['主力净流入'] = f'流入{abs_inflow/10000:.1f}亿(+15)'
            elif main_inflow > 5000:  # 5000万-1亿
                fund_flow_score += 10
                detail['主力净流入'] = f'流入{abs_inflow:.0f}万(+10)'
            elif main_inflow > 1000:  # 1000-5000万
                fund_flow_score += 5
                detail['主力净流入'] = f'流入{abs_inflow:.0f}万(+5)'
            elif main_inflow > 0:  # 0-1000万
                fund_flow_score += 2
                detail['主力净流入'] = f'流入{abs_inflow:.0f}万(+2)'
            elif main_inflow > -1000:  # 小幅流出
                fund_flow_score += 0
                detail['主力净流入'] = f'流出{abs_inflow:.0f}万(+0)'
            elif main_inflow > -5000:  # 中度流出
                fund_flow_score += 0
                detail['主力净流入'] = f'流出{abs_inflow:.0f}万⚠️'
            else:  # 大幅流出
                fund_flow_score += 0
                detail['主力净流入'] = f'流出{abs_inflow/10000:.1f}亿⚠️'
            
            # 主力净流入占比 (0-5)
            main_pct = capital_flow_data.get('main_net_pct', 0)
            if isinstance(main_pct, (int, float)):
                if main_pct > 2:
                    fund_flow_score += 5
                    detail['主力占比'] = f'{main_pct:.1f}%(+5)'
                elif main_pct > 1:
                    fund_flow_score += 3
                    detail['主力占比'] = f'{main_pct:.1f}%(+3)'
                elif main_pct > 0:
                    fund_flow_score += 1
                    detail['主力占比'] = f'{main_pct:.1f}%(+1)'
            
            # 超大单净流入 (0-5)
            super_large = capital_flow_data.get('super_large_net', 0)
            if isinstance(super_large, (int, float)) and super_large > 5000:
                fund_flow_score += 5
                detail['超大单'] = f'流入{super_large/10000:.1f}亿(+5)'
            elif isinstance(super_large, (int, float)) and super_large > 1000:
                fund_flow_score += 3
                detail['超大单'] = f'流入{super_large:.0f}万(+3)'
            elif isinstance(super_large, (int, float)) and super_large > 0:
                fund_flow_score += 1
                detail['超大单'] = f'流入{super_large:.0f}万(+1)'
    else:
        detail['资金面'] = '无数据'
    
    detail['资金面'] = f'{fund_flow_score:.0f}/25'
    
    # ========== ③ 基本面 (20分) ==========
    fundamental_score = 0
    
    # PE估值 (0-8) - 从实时行情获取
    pe_ttm = quote.get('pe_ttm', 0)
    if isinstance(pe_ttm, (int, float)) and pe_ttm > 0:
        if pe_ttm <= 30:
            fundamental_score += 8
            detail['PE'] = f'{pe_ttm:.0f}(+8低估值)'
        elif pe_ttm <= 60:
            fundamental_score += 5
            detail['PE'] = f'{pe_ttm:.0f}(+5合理)'
        elif pe_ttm <= 100:
            fundamental_score += 3
            detail['PE'] = f'{pe_ttm:.0f}(+3偏高)'
        else:
            fundamental_score += 0
            detail['PE'] = f'{pe_ttm:.0f}(+0过高)'
    elif isinstance(pe_ttm, (int, float)) and pe_ttm < 0:
        detail['PE'] = f'{pe_ttm:.0f}(+0亏损)'
    
    # 从基本面缓存读取增长率
    if fund_data and isinstance(fund_data, dict):
        # 营收增长 (0-8)
        rev_yoy = fund_data.get('revenue_yoy')
        if isinstance(rev_yoy, (int, float)):
            if rev_yoy > 30:
                fundamental_score += 8
                detail['营收YoY'] = f'{rev_yoy:+.0f}%(+8高增)'
            elif rev_yoy > 15:
                fundamental_score += 5
                detail['营收YoY'] = f'{rev_yoy:+.0f}%(+5稳健)'
            elif rev_yoy > 0:
                fundamental_score += 3
                detail['营收YoY'] = f'{rev_yoy:+.0f}%(+3微增)'
            else:
                fundamental_score += 0
                detail['营收YoY'] = f'{rev_yoy:+.0f}%(+0下滑)'
        elif fund_data.get('revenue_qoq') is not None:
            rev_qoq = fund_data['revenue_qoq']
            if isinstance(rev_qoq, (int, float)):
                if rev_qoq > 20:
                    fundamental_score += 5
                    detail['营收QoQ'] = f'{rev_qoq:+.0f}%(+5)'
                elif rev_qoq > 0:
                    fundamental_score += 2
                    detail['营收QoQ'] = f'{rev_qoq:+.0f}%(+2)'
        
        # 净利润增长 (0-4)
        np_yoy = fund_data.get('np_yoy')
        if isinstance(np_yoy, (int, float)):
            if np_yoy > 30:
                fundamental_score += 4
                detail['净利YoY'] = f'{np_yoy:+.0f}%(+4高增)'
            elif np_yoy > 15:
                fundamental_score += 3
                detail['净利YoY'] = f'{np_yoy:+.0f}%(+3稳健)'
            elif np_yoy > 0:
                fundamental_score += 1
                detail['净利YoY'] = f'{np_yoy:+.0f}%(+1微增)'
            else:
                fundamental_score += 0
                detail['净利YoY'] = f'{np_yoy:+.0f}%(+0下滑)'
        
        # EPS显示
        eps = fund_data.get('eps')
        if eps is not None:
            detail['EPS'] = f'{eps}'
    else:
        detail['基本面'] = '无数据'
    
    detail['基本面'] = f'{fundamental_score:.0f}/20'
    
    # ========== ④ 板块热度 (15分) ==========
    sector_score_pts = 0
    
    # 优先用iFinD行业分类+申万板块行情（精确匹配）
    try:
        from ifind_sector_cache import get_industry_sector_score, get_stock_industry
        ind_info = get_stock_industry(code)
        ind_name = ind_info.get('name', stock.get('name', '')) if ind_info else stock.get('name', '')
        ind_score, ind_detail = get_industry_sector_score(code, ind_name, quote.get('change_pct', 0))
        sector_score_pts = ind_score
        # 拆分显示（🔥优先匹配，避免+3/+5覆盖涨幅）
        for part in ind_detail.split():
            if '🔥' in part:
                detail['板块共振'] = part
            elif '主力净流入' in part or '主力净流出' in part:
                detail['板块资金'] = part
            elif '+8' in part or '暴涨' in part:
                detail['板块涨幅'] = part
            elif '+5' in part or '强势' in part:
                detail['板块涨幅'] = part
            elif '+3' in part or '偏强' in part:
                detail['板块涨幅'] = part
            elif '+1' in part or '微涨' in part:
                detail['板块涨幅'] = part
            elif '独立行情' in part:
                detail['板块涨幅'] = part
    except Exception:
        # 降级：旧逻辑（sector_analysis + 问财模糊匹配）
        try:
            from sector_analysis import get_sector_score, get_stock_sector
            sec_score, sec_desc = get_sector_score(code, quote.get('change_pct'))
            if sec_score >= 10:
                sector_score_pts += 8
            elif sec_score >= 7:
                sector_score_pts += 5
            elif sec_score >= 3:
                sector_score_pts += 2
            detail['板块评分'] = f'{sec_score}({sec_desc[:10]})(+{min(sec_score,8)})'
        except Exception:
            pass
    
    # 降级：旧逻辑（仅在iFinD缓存无数据时使用问财模糊匹配）
    if sector_score_pts == 0 and sector_data and isinstance(sector_data, dict):
        # 个股名称关键词 → 可能的板块关键词映射
        stock_name = stock.get('name', '')
        stock_keywords = set()
        for i in range(len(stock_name)):
            for l in range(2, min(4, len(stock_name) - i + 1)):
                stock_keywords.add(stock_name[i:i+l])
        
        best_sector_match = None
        best_sector_chg = 0
        
        hot_industries = sector_data.get('hot_industry', [])
        for ind in hot_industries[:20]:
            ind_name = ind.get('name', '')
            for kw in stock_keywords:
                if len(kw) >= 2 and kw in ind_name:
                    chg = ind.get('change_pct', 0)
                    if isinstance(chg, (int, float)) and chg > best_sector_chg:
                        best_sector_match = ind_name
                        best_sector_chg = chg
                    break
        
        hot_concepts = sector_data.get('hot_concept', [])
        for con in hot_concepts[:20]:
            con_name = con.get('name', '')
            for kw in stock_keywords:
                if len(kw) >= 2 and kw in con_name:
                    chg = con.get('change_pct', 0)
                    if isinstance(chg, (int, float)) and chg > best_sector_chg:
                        best_sector_match = con_name
                        best_sector_chg = chg
                    break
        
        # 问财热门板块共振
        try:
            from iwencai_sector import is_hot_sector
            _is_hot, _hot_name = is_hot_sector(code, stock_name)
            if _is_hot:
                sector_score_pts += 3
                detail['板块共振'] = f'🔥{_hot_name}(+3)'
        except Exception:
            pass
        
        # 板块涨幅评分（降级）
        if best_sector_match and best_sector_chg > 0:
            if best_sector_chg > 5:
                sector_score_pts += 5
                detail['板块涨幅'] = f'{best_sector_match}{best_sector_chg:+.1f}%(+5)'
            elif best_sector_chg > 3:
                sector_score_pts += 3
                detail['板块涨幅'] = f'{best_sector_match}{best_sector_chg:+.1f}%(+3)'
            elif best_sector_chg > 1:
                sector_score_pts += 2
                detail['板块涨幅'] = f'{best_sector_match}{best_sector_chg:+.1f}%(+2)'
            elif best_sector_chg > 0:
                sector_score_pts += 1
                detail['板块涨幅'] = f'{best_sector_match}{best_sector_chg:+.1f}%(+1)'
    
    detail['板块热度'] = f'{sector_score_pts:.0f}/15'
    
    # ========== ⑤ 风控 (10分) ==========
    risk_score = 0
    
    # 止损空间 (0-4)
    levels = stock.get('key_levels', {})
    stop_loss = levels.get('stop_loss', 0)
    price = quote.get('price', 0)
    if stop_loss > 0 and price > 0:
        stop_pct = (price - stop_loss) / price * 100
        if stop_pct > 10:
            risk_score += 4
            detail['止损空间'] = f'{stop_pct:.1f}%(+4宽)'
        elif stop_pct > 7:
            risk_score += 3
            detail['止损空间'] = f'{stop_pct:.1f}%(+3适中)'
        elif stop_pct > 5:
            risk_score += 1
            detail['止损空间'] = f'{stop_pct:.1f}%(+1偏紧)'
        else:
            detail['止损空间'] = f'{stop_pct:.1f}%(+0不足)'
    
    # 换手率 (0-3)
    turnover = quote.get('turnover', 0)
    if isinstance(turnover, (int, float)) and turnover > 0:
        if 3 <= turnover <= 8:
            risk_score += 3
            detail['换手率'] = f'{turnover:.1f}%(+3正常)'
        elif 1 <= turnover <= 15:
            risk_score += 1
            detail['换手率'] = f'{turnover:.1f}%(+1)'
        else:
            detail['换手率'] = f'{turnover:.1f}%(+0异常)'
    
    # 内外盘比 (0-3)
    outer_vol = quote.get('outer_vol', 0)
    inner_vol = quote.get('inner_vol', 0)
    if outer_vol > 0 and inner_vol > 0:
        oi_ratio = outer_vol / inner_vol
        if oi_ratio > 1.5:
            risk_score += 3
            detail['内外盘'] = f'{oi_ratio:.1f}x(+3买方强)'
        elif oi_ratio > 1.0:
            risk_score += 2
            detail['内外盘'] = f'{oi_ratio:.1f}x(+2)'
        elif oi_ratio > 0.6:
            risk_score += 1
            detail['内外盘'] = f'{oi_ratio:.1f}x(+1)'
        else:
            detail['内外盘'] = f'{oi_ratio:.1f}x(+0卖方强)'
    
    detail['风控'] = f'{risk_score:.0f}/10'
    
    # ========== 汇总 ==========
    total = tech_score + fund_flow_score + fundamental_score + sector_score_pts + risk_score
    total = min(total, 100)  # 封顶100
    
    # 星级映射
    if total >= 80:
        stars = '★★★'
    elif total >= 60:
        stars = '★★☆'
    elif total >= 40:
        stars = '★☆☆'
    else:
        stars = '❌'
    
    detail['总分'] = f'{total:.0f}'
    detail['星级'] = stars
    
    return total, stars, detail

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

    # [检查5] 加载资金面缓存
    capital_flow = {}
    try:
        cf_path = os.path.expanduser('~/.hermes/cache/capital_flow.json')
        if os.path.exists(cf_path):
            with open(cf_path, 'r', encoding='utf-8') as f:
                cf_data = json.load(f)
            for code_cf, val in cf_data.items():
                if isinstance(val, dict):
                    capital_flow[code_cf] = val
                else:
                    capital_flow[code_cf] = {'main_net_inflow': val}
    except Exception:
        pass

    # [检查5a] 加载基本面缓存（kuaicha利润表数据）
    fundamental = {}
    try:
        fund_path = os.path.expanduser('~/.hermes/cache/fundamental.json')
        if os.path.exists(fund_path):
            with open(fund_path, 'r', encoding='utf-8') as f:
                fundamental = json.load(f)
    except Exception:
        pass

    # [检查5b] 加载板块热度缓存
    sector_heat = {}
    try:
        sh_path = os.path.expanduser('~/.hermes/cache/sector_heat.json')
        if os.path.exists(sh_path):
            with open(sh_path, 'r', encoding='utf-8') as f:
                sector_heat = json.load(f)
    except Exception:
        pass

    # [检查5b] 获取大盘指数
    market_index = {}
    try:
        import urllib.request as _urllib
        for _idx_code, _idx_prefix, _idx_name in [('000001', 'sh', '上证'), ('399001', 'sz', '深证')]:
            try:
                _url = f"https://qt.gtimg.cn/q={_idx_prefix}{_idx_code}"
                _resp = _urllib.urlopen(_url, timeout=5)
                _raw = _resp.read().decode('gbk', errors='ignore')
                if '=' in _raw and '~' in _raw:
                    _parts = _raw.split('=')[1].strip('"').split('~')
                    if len(_parts) > 32:
                        market_index[_idx_name] = {'change_pct': float(_parts[32]) if _parts[32] else 0}
            except Exception:
                pass
    except Exception:
        pass

    # 全局变量供judge_entry使用
    global _cf_global, _mkt_global
    _cf_global = capital_flow
    _mkt_global = market_index

    # [检查5c] V12猎庄KDJ信号批量计算（并行拉K线+计算指标）
    kdj_signals = {}  # code -> entry_signal_dict
    if _KDJ_AVAILABLE:
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            def _calc_one_kdj(code):
                try:
                    df = _kdj_fetch_kline(code, count=120)
                    if df is None or len(df) < 60:
                        return code, None
                    df = calc_indicators(df)
                    entry = check_entry(df)
                    return code, entry
                except Exception:
                    return code, None
            
            # 只对观察池中有信号的票做KDJ计算（基础买以上的才值得算）
            kdj_codes = [s['code'] for s in stocks if s.get('signal') in ('全买入', '强庄买', '基础买')]
            if kdj_codes:
                with ThreadPoolExecutor(max_workers=6) as executor:
                    futures = {executor.submit(_calc_one_kdj, c): c for c in kdj_codes}
                    for future in as_completed(futures):
                        try:
                            code, entry = future.result(timeout=15)
                            if entry is not None:
                                kdj_signals[code] = entry
                        except Exception:
                            pass
        except Exception:
            pass  # KDJ计算失败不影响主流程

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

        # 注入V12 KDJ信号到stock，供judge_entry使用
        stock['_kdj_entry'] = kdj_signals.get(code)

        action, reason, level = judge_entry(stock, quote)
        cf = capital_flow.get(code)
        report = format_report(stock, quote, action, reason, level, capital_flow_data=cf)

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
    # 大盘指数
    if market_index:
        _sh = market_index.get('上证', {}).get('change_pct', 0)
        _sz = market_index.get('深证', {}).get('change_pct', 0)
        mkt_str = f"大盘: 上证{_sh:+.1f}% 深证{_sz:+.1f}%"
        if min(_sh, _sz) < -1.0:
            mkt_str += " ⚠️弱市"
        lines.append(mkt_str)
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

        # [买入推荐小结] 多维度综合评分
        pick_lines = []
        for r, level in buy_signals:
            for code, s in stock_map.items():
                if f'({code})' in r:
                    quote_d = quotes.get(code, {})
                    vibe = s.get('vibe_tags', '-')
                    signal_tag = s.get('signal', '')
                    price = quote_d.get('price', 0)
                    
                    # 获取各维度数据
                    cf_data = capital_flow.get(code)
                    fund_data = fundamental.get(code)
                    
                    # 多维度评分
                    total_score, stars, score_detail = score_buy_candidate(
                        s, quote_d, signal_tag, vibe, r,
                        capital_flow_data=cf_data,
                        fund_data=fund_data,
                        sector_data=sector_heat
                    )
                    
                    # 评分低于40不推荐
                    if total_score < 40:
                        stars = '❌'
                    
                    # 构建评分行
                    levels = s.get('key_levels', {})
                    stop_loss = levels.get('stop_loss', 0)
                    stop_str = ''
                    if stop_loss > 0 and price > 0:
                        stop_pct = (price - stop_loss) / price * 100
                        stop_str = f' | 止损¥{stop_loss:.2f}({stop_pct:.1f}%)'
                    
                    rating = f'{stars} {total_score:.0f}分 {s["name"]}({code}) ¥{price:.2f}'
                    
                    # 各维度分数摘要
                    dim_parts = []
                    for dim in ['技术面', '资金面', '基本面', '板块热度', '风控']:
                        v = score_detail.get(dim, '')
                        if v:
                            dim_parts.append(v)
                    if dim_parts:
                        rating += f'\n   📊 {" | ".join(dim_parts)}'
                    
                    # 关键指标摘要
                    key_parts = []
                    for key in ['V10信号', 'Vibe', '入场信号', '主力净流入', 'PE', '营收YoY', '净利YoY', '板块共振', '止损空间']:
                        v = score_detail.get(key)
                        if v:
                            key_parts.append(v)
                    if key_parts:
                        rating += f'\n   🔑 {" | ".join(key_parts)}'
                    
                    rating += stop_str
                    pick_lines.append((total_score, rating))
                    break
        
        if pick_lines:
            # 按总分降序排列
            pick_lines.sort(key=lambda x: -x[0])
            lines.append(f"**🎯 买入推荐（共{len(pick_lines)}只，按综合评分排序）:**")
            for _, pl in pick_lines:
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

    # [追高豁免评分] 对追高豁免的观察票也做评分推荐
    surge_exempt_stocks = []
    for stock in stocks:
        code = stock['code']
        quote_d = quotes.get(code, {})
        if not quote_d or quote_d.get('price', 0) <= 0:
            continue
        # 找追高豁免的票（涨超7%但Vibe≥+2）
        change_pct = quote_d.get('change_pct', 0)
        signal = stock.get('signal', '')
        vibe_tags = stock.get('vibe_tags', '')
        vibe_score_val = stock.get('vibe_score', 0)
        if not isinstance(vibe_score_val, (int, float)) or vibe_score_val == 0:
            if isinstance(vibe_tags, list):
                for tag in vibe_tags:
                    tag_s = str(tag).strip()
                    if tag_s.startswith('BOS'): vibe_score_val += 2
                    elif tag_s.startswith('ChoCH'): vibe_score_val += 2
                    elif tag_s.startswith('FVG'):
                        import re as _re2
                        _m2 = _re2.search(r'([+-]?\d+)', tag_s)
                        if _m2: vibe_score_val += int(_m2.group(1))
        # 判断追高豁免条件
        chase_limit = 15 if code.startswith('3') else 7
        if change_pct > chase_limit and vibe_score_val >= 2 and signal in ('全买入', '强庄买'):
            cf_data = capital_flow.get(code)
            if isinstance(cf_data, (int, float)):
                cf_data = {'main_net_inflow': cf_data}
            fund_data = fundamental.get(code)
            price = quote_d.get('price', 0)
            
            total_score, stars, score_detail = score_buy_candidate(
                stock, quote_d, signal, vibe_tags,
                f'追高豁免(涨{change_pct:.1f}%)',
                capital_flow_data=cf_data,
                fund_data=fund_data,
                sector_data=sector_heat
            )
            
            # 追高扣分（风险维度额外扣分）
            surge_penalty = min((change_pct - chase_limit) * 2, 15)
            total_score = max(total_score - surge_penalty, 0)
            if total_score < 60:
                stars = '⚠️'
            
            levels = stock.get('key_levels', {})
            stop_loss = levels.get('stop_loss', 0)
            stop_str = ''
            if stop_loss > 0 and price > 0:
                stop_pct = (price - stop_loss) / price * 100
                stop_str = f' | 止损¥{stop_loss:.2f}({stop_pct:.1f}%)'
            
            rating = f'{stars} {total_score:.0f}分 {stock["name"]}({code}) ¥{price:.2f} 涨{change_pct:+.1f}%'
            
            dim_parts = []
            for dim in ['技术面', '资金面', '基本面', '板块热度', '风控']:
                v = score_detail.get(dim, '')
                if v: dim_parts.append(v)
            if dim_parts:
                rating += f'\n   📊 {" | ".join(dim_parts)}'
            
            key_parts = []
            for key in ['V10信号', 'Vibe', '主力净流入', 'PE', '营收YoY', '净利YoY', '追高扣分']:
                v = score_detail.get(key)
                if v: key_parts.append(v)
            if surge_penalty > 0:
                key_parts.append(f'追高-{surge_penalty:.0f}')
            if key_parts:
                rating += f'\n   🔑 {" | ".join(key_parts)}'
            
            rating += stop_str
            surge_exempt_stocks.append((total_score, rating))
    
    if surge_exempt_stocks:
        surge_exempt_stocks.sort(key=lambda x: -x[0])
        lines.append(f"**⚡ 追高豁免评分（共{len(surge_exempt_stocks)}只，Vibe≥+2强趋势）:**")
        for _, sr in surge_exempt_stocks:
            lines.append(f"  {sr}")
        lines.append('')

    # ── 汇总可买入清单（从buy_signals评分和追高豁免评分中筛选≥60分且无❌的票） ──
    buyable_list = []  # (score, rating_text)
    
    # 从buy_signals评分(pick_lines)中收集
    try:
        if pick_lines:
            for _score, _rating in pick_lines:
                if _score < 60 or '❌' in _rating[:5]:
                    continue
                buyable_list.append((_score, _rating))
    except NameError:
        pass
    
    # 从追高豁免评分中收集
    if surge_exempt_stocks:
        for _score, _rating in surge_exempt_stocks:
            if _score < 60 or '❌' in _rating[:5]:
                continue
            buyable_list.append((_score, _rating))
    
    # 按分数降序排列
    buyable_list.sort(key=lambda x: -x[0])
    
    # ── 🚨🚨🚨 可买入信号 🚨🚨🚨 (顶部醒目汇总) ──
    # 找到信号列表开始的位置（在 全买入/强庄买 之前插入）
    buyable_header_idx = None
    for i, line in enumerate(lines):
        if line.startswith('**🔴 全买入') or line.startswith('**🟠 强庄买'):
            buyable_header_idx = i
            break
    if buyable_header_idx is None:
        # 如果既没有全买入也没有强庄买，插入到板块概况之后（板块概况之后有空白行作分隔）
        for i, line in enumerate(lines):
            if '观察池:' in line:
                buyable_header_idx = i + 2  # 跳过空行
                break
    if buyable_header_idx is None:
        buyable_header_idx = len(lines)

    buyable_signal_lines = []
    if buyable_list:
        buyable_signal_lines.append('━━━ **🚨🚨🚨 可买入信号 🚨🚨🚨** ━━━')
        for _score, _rating in buyable_list:
            first_line = _rating.strip().split('\n')[0]
            buyable_signal_lines.append(f'  {first_line}')
        buyable_signal_lines.append('')
    else:
        # 有信号但无合格的可买入（评分不足/❌），提示观望
        buyable_signal_lines.append('━━━ **🚨🚨🚨 可买入信号 🚨🚨🚨** ━━━')
        buyable_signal_lines.append('  今日暂无可买入信号（无≥60分且无❌的合格标的）')
        buyable_signal_lines.append('')

    for i, bl in enumerate(buyable_signal_lines):
        lines.insert(buyable_header_idx + i, bl)

    if skipped:
        lines.append(f"⚫ 跳过: {skipped}只（停牌/无数据）")

    report = '\n'.join(lines)

    # 输出
    if full_buy_stocks or strong_buy_stocks or buy_signals or risk_signals or surge_exempt_stocks:
        print(report)
    else:
        print(f"📡 {time_str[:5]} V10监控: {len(stocks)}只观察中 | 无信号无风险")

if __name__ == '__main__':
    main()
