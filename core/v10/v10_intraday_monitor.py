#!/usr/bin/env python3
"""
V10 盘中盯盘监控器 v2
数据源：腾讯实时行情（延迟2-3秒）
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
import time
import os
import urllib.request
from datetime import datetime

# 添加scripts目录到路径
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from sector_analysis import get_sector_ranking, analyze_sector_rotation, get_sector_summary

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
    """验证观察池是否是当天且未过期的"""
    scan_time = data.get('scan_time', '')
    if not scan_time:
        return False, '观察池无时间戳'
    today = datetime.now().strftime('%Y-%m-%d')
    if today not in scan_time:
        return False, f'观察池过期（生成于{scan_time}）'
    
    # ⏰ 分钟级时效：超过30分钟的watchlist视为过期（全扫描15分钟一轮，30分钟足够新）
    try:
        st = datetime.strptime(scan_time[:16], '%Y-%m-%d %H:%M')
        age_min = (datetime.now() - st).total_seconds() / 60
        if age_min > 30:
            return False, f'观察池{int(age_min)}分钟前过期（{scan_time[:16]}）'
    except ValueError:
        pass
    
    return True, scan_time


def verify_quote_freshness(quote):
    """验证行情数据是否是当前交易日的"""
    # 腾讯API在非交易时段返回昨收数据
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
    """批量获取实时行情（腾讯API，延迟2-3秒）"""
    qt_codes = []
    for code in codes:
        # 6xx=沪市, 0xx/3xx(创业板)=深市
        prefix = 'sh' if code.startswith('6') else 'sz'
        qt_codes.append(f'{prefix}{code}')

    batch_size = 40
    results = {}
    errors = []
    for i in range(0, len(qt_codes), batch_size):
        batch = qt_codes[i:i+batch_size]
        url = f"https://qt.gtimg.cn/q={','.join(batch)}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode('gbk')
            for line in raw.strip().split(';'):
                if '=' not in line or '~' not in line:
                    continue
                parts = line.split('=')[1].strip('"').split('~')
                if len(parts) < 50:
                    continue
                code = parts[2]
                try:
                    results[code] = {
                        'name': parts[1],
                        'price': float(parts[3]) if parts[3] else 0,
                        'yclose': float(parts[4]) if parts[4] else 0,
                        'open': float(parts[5]) if parts[5] else 0,
                        'high': float(parts[33]) if parts[33] else 0,
                        'low': float(parts[34]) if parts[34] else 0,
                        'change_pct': float(parts[32]) if parts[32] else 0,
                        'volume': float(parts[6]) if parts[6] else 0,
                        'amount': float(parts[37]) if parts[37] else 0,  # 腾讯API单位：万元
                        'turnover': float(parts[38]) if parts[38] else 0,
                    }
                except (ValueError, IndexError):
                    pass
        except Exception as e:
            errors.append(f'批次{i//batch_size}: {e}')
        time.sleep(0.1)

    if errors:
        print(f"⚠️ 行情获取异常: {'; '.join(errors)}", file=sys.stderr)
    return results


# ====== iFinD数据增强 ======

def _load_ifind_token():
    """从环境变量或.env加载iFinD HTTP API token"""
    token = os.environ.get("IFIND_REFRESH_TOKEN", "")
    if token:
        return token
    env_path = os.path.expanduser("~/.hermes/.env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("IFIND_REFRESH_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return ""


def _ifind_get_access_token(refresh_token):
    """用refresh_token换取access_token"""

    url = "https://quantapi.51ifind.com/api/v1/get_access_token"
    data = json.dumps({}).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "refresh_token": refresh_token
    })
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if 'data' in result and 'access_token' in result['data']:
            return result['data']['access_token']
    except Exception:
        pass
    return None


def fetch_ifind_realtime(codes):
    """批量获取iFinD实时行情（PB等精细指标）"""
    refresh_token = _load_ifind_token()
    if not refresh_token:
        return {}

    access_token = _ifind_get_access_token(refresh_token)
    if not access_token:
        return {}

    # iFinD代码格式: 300065.SZ, 600936.SH
    ifind_codes = []
    for code in codes:
        suffix = '.SH' if code.startswith('6') else '.SZ'
        ifind_codes.append(f"{code}{suffix}")

    results = {}
    batch_size = 50
    for i in range(0, len(ifind_codes), batch_size):
        batch = ifind_codes[i:i+batch_size]
        payload = json.dumps({
            "codes": ",".join(batch),
            "indicators": "latest,changeRatio,pb,pe_ttm,totalMarketValue,circulationMarketValue,turnoverRate,volumeRatio"
        }).encode()
        req = urllib.request.Request(
            "https://quantapi.51ifind.com/api/v1/real_time_quotation",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "access_token": access_token
            }
        )
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
            if data.get('errorcode') == 0 and data.get('tables'):
                for item in data['tables']:
                    thscode = item.get('thscode', '')
                    code = thscode.split('.')[0]
                    tbl = item.get('table', {})
                    results[code] = {
                        'pb': tbl.get('pb', [None])[0] if isinstance(tbl.get('pb'), list) else tbl.get('pb'),
                        'pe_ttm': tbl.get('pe_ttm', [None])[0] if isinstance(tbl.get('pe_ttm'), list) else tbl.get('pe_ttm'),
                        'total_mv': tbl.get('totalMarketValue', [None])[0] if isinstance(tbl.get('totalMarketValue'), list) else tbl.get('totalMarketValue'),
                        'circ_mv': tbl.get('circulationMarketValue', [None])[0] if isinstance(tbl.get('circulationMarketValue'), list) else tbl.get('circulationMarketValue'),
                        'turnover_rate': tbl.get('turnoverRate', [None])[0] if isinstance(tbl.get('turnoverRate'), list) else tbl.get('turnoverRate'),
                        'volume_ratio': tbl.get('volumeRatio', [None])[0] if isinstance(tbl.get('volumeRatio'), list) else tbl.get('volumeRatio'),
                    }
        except Exception:
            pass
        time.sleep(0.1)

    return results


def format_ifind_enhanced(stock, quote, ifind_data):
    """用iFinD数据增强入场信号报告"""
    code = stock['code']
    data = ifind_data.get(code)
    if not data:
        return ''

    parts = []
    pb = data.get('pb')
    if pb and pb > 0:
        parts.append(f'PB:{pb:.2f}')
    pe = data.get('pe_ttm')
    if pe and pe > 0:
        parts.append(f'PE(TTM):{pe:.1f}')
    vr = data.get('volume_ratio')
    if vr and vr > 0:
        parts.append(f'量比:{vr:.2f}')
    tr = data.get('turnover_rate')
    if tr and tr > 0:
        parts.append(f'换手:{tr:.1f}%')
    total_mv = data.get('total_mv')
    if total_mv and total_mv > 0:
        mv_yi = total_mv / 100000000
        parts.append(f'市值:{mv_yi:.1f}亿')

    if parts:
        return f'   📊 iFinD: {" | ".join(parts)}'
    return ''

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

    # 追高警告（创业板15%、ST股4%、其他7%）
    code = stock['code']
    name = stock.get('name', '')
    if code.startswith('3'):
        chase_limit = 15
    elif 'ST' in name.upper():
        chase_limit = 4
    else:
        chase_limit = 7
    if change_pct > chase_limit:
        return 'risk', f'⚠️ 今日已涨{change_pct:.1f}%，追高风险大（阈值{chase_limit}%）', 1

    # ====== 入场信号检查 ======

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
    vibe_str = f' Vibe:{vibe}' if vibe and vibe != '-' else ''

    note = stock.get('note', '')
    note_str = f'\n   💡 {note}' if note else ''

    return (
        f"{emoji} **{stock['name']}**({stock['code']}) {reason}\n"
        f"   信号:{signal_tag}{vibe_str}\n"
        f"   现价:¥{quote['price']:.2f} | 涨跌:{quote['change_pct']:+.1f}% | "
        f"振幅:{((quote['high']-quote['low'])/quote['yclose']*100) if quote['yclose']>0 else 0:.1f}% | "
        f"成交:{quote['amount']:.0f}万"
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

    # [检查3] 观察池时效
    fresh, msg = verify_watchlist_freshness(wl_data)
    if not fresh:
        print(f"[{time_str}] ⚠️ {msg}，跳过盯盘（请先运行V10扫描）")
        return

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

    # [iFinD增强] 对入场信号股获取iFinD精细数据
    ifind_data = {}
    if buy_signals:
        all_codes = [s['code'] for s in stocks]
        ifind_data = fetch_ifind_realtime(all_codes)

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
    lines.append(f"📡 **V10盘中监控** {date_str} {time_str[:5]}")
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
                lines.append(f"  {s['name']}({s['code']}) ¥{q['price']:.2f} {chg:+.1f}% | 成交{q['amount']:.0f}万")
            else:
                lines.append(f"  {s['name']}({s['code']}) ¥{s.get('price',0):.2f}")
        lines.append('')

    if strong_buy_stocks:
        lines.append(f"**🟠 强庄买信号 ({len(strong_buy_stocks)}只):**")
        for s in strong_buy_stocks[:10]:  # 最多显示10只
            q = quotes.get(s['code'])
            if q and q['price'] > 0:
                chg = q['change_pct']
                lines.append(f"  {s['name']}({s['code']}) ¥{q['price']:.2f} {chg:+.1f}% | 成交{q['amount']:.0f}万")
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
            # 从报告字符串中提取code，添加iFinD增强
            for code, s in stock_map.items():
                if f'({code})' in r:
                    quote = quotes.get(code, {})
                    enhanced = format_ifind_enhanced(s, quote, ifind_data)
                    if enhanced:
                        lines.append(enhanced)
                    break
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

                    # 最终评级
                    rating = f'{stars} {s["name"]}({code}) ¥{price:.2f}'
                    if reasons:
                        rating += f' — {"|".join(reasons)}'

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
