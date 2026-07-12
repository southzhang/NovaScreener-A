#!/usr/bin/env python3
"""实盘持仓盯盘监控器 v3 (新策略v2)
分层止损+补仓监控+只报异常。
读取current_holdings.py持仓 → 腾讯实时行情 → K线算EMA20/30日高低 →
三层止损(软-8%/硬-12%/绝对-15%) + 补仓触发(长线-8%/-12%) + 动态止盈(15%+启动) →
大盘指数 → 格式化报告

新策略v2 (06-23):
- 止损三层: soft_stop(-8%观察不卖) / hard_stop(-12%决策) / abs_stop(-15%建议卖)
- 止盈: 长线15%+启动trailing 8% / 短线10%+启动trailing 5%
- 补仓: 长线票-8%第一笔/-12%第二笔, 短线票不补仓
- 浮亏8%以内静默, 只报异常
"""
import json
import os
import sys
import ssl
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
from current_holdings import get_holdings, get_portfolio_value, get_cash, get_stop_tiers, get_dca_plan, get_category, get_tp_config

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_quote(code):
    """腾讯实时行情（单只）"""
    prefix = 'sh' if code.startswith(('6', '5')) else 'sz'
    url = f'https://qt.gtimg.cn/q={prefix}{code}'
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        raw = resp.read().decode('gbk', errors='ignore')
        if '=' not in raw or '~' not in raw:
            return None
        parts = raw.split('=')[1].strip('"').split('~')
        if len(parts) < 40:
            return None
        return {
            'name': parts[1],
            'price': float(parts[3]) if parts[3] else 0,
            'yclose': float(parts[4]) if parts[4] else 0,
            'open': float(parts[5]) if parts[5] else 0,
            'volume': float(parts[6]) if parts[6] else 0,
            'high': float(parts[33]) if len(parts) > 33 and parts[33] else 0,
            'low': float(parts[34]) if len(parts) > 34 and parts[34] else 0,
            'change_pct': float(parts[32]) if len(parts) > 32 and parts[32] else 0,
            'amount': float(parts[37]) if len(parts) > 37 and parts[37] else 0,
            'turnover': float(parts[38]) if len(parts) > 38 and parts[38] else 0,
            'limit_up': float(parts[47]) if len(parts) > 47 and parts[47] else 0,
            'limit_down': float(parts[48]) if len(parts) > 48 and parts[48] else 0,
            'outer_vol': float(parts[7]) if len(parts) > 7 and parts[7] else 0,
            'inner_vol': float(parts[8]) if len(parts) > 8 and parts[8] else 0,
        }
    except Exception:
        return None


def fetch_kline(code, count=30):
    """腾讯日K线 → EMA20 + 10日/30日高低点"""
    secid = f'sh{code}' if code.startswith(('6', '5')) else f'sz{code}'
    url = f'https://ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={secid},day,,,{count},qfq'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=8, context=_ssl_ctx)
        raw = resp.read().decode('utf-8')
        json_str = raw.split('=', 1)[1] if '=' in raw else raw
        data = json.loads(json_str)
        sec_data = data.get('data', {}).get(secid, {})
        bars = sec_data.get('qfqday', []) or sec_data.get('day', [])
        if not bars or len(bars) < 5:
            return None
        closes = [float(b[2]) for b in bars]
        highs = [float(b[3]) for b in bars]
        lows = [float(b[4]) for b in bars]
        ema20 = None
        if len(closes) >= 20:
            k = 2 / (20 + 1)
            ema20 = sum(closes[:20]) / 20
            for c in closes[20:]:
                ema20 = c * k + ema20 * (1 - k)
        return {
            'ema20': ema20,
            'high_10d': max(highs[-10:]) if len(highs) >= 10 else max(highs),
            'high_30d': max(highs),
            'low_30d': min(lows),
        }
    except Exception:
        return None


def get_market_indices():
    """上证/深证/创业板指数"""
    indices = {}
    for code, prefix, name in [('000001', 'sh', '上证'), ('399001', 'sz', '深证'), ('399006', 'sz', '创业板')]:
        try:
            url = f'https://qt.gtimg.cn/q={prefix}{code}'
            resp = urllib.request.urlopen(url, timeout=5)
            raw = resp.read().decode('gbk', errors='ignore')
            if '=' in raw and '~' in raw:
                parts = raw.split('=')[1].strip('"').split('~')
                if len(parts) > 32:
                    indices[name] = {
                        'price': float(parts[3]) if parts[3] else 0,
                        'change_pct': float(parts[32]) if parts[32] else 0,
                    }
        except Exception:
            pass
    return indices


def load_watchlist_vibe(code):
    """从V10 watchlist读取Vibe评分（如果有）"""
    try:
        path = os.path.expanduser('~/.hermes/cache/v10_watchlist.json')
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        for s in data.get('stocks', []):
            if s.get('code') == code:
                return s.get('vibe_score', 0), s.get('vibe_tags', []), s.get('signal', '')
    except Exception:
        pass
    return None


def load_capital_flow(code):
    """从资金面缓存读取主力净流入
    返回: float（主力净流入，万元）或 None（无数据）
    注意: 返回的是标量值，与v10_scorer.load_capital_flow返回dict不同
    """
    try:
        path = os.path.expanduser('~/.hermes/cache/capital_flow.json')
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        val = data.get(code)
        if isinstance(val, dict):
            return val.get('main_net_inflow', 0)
        return val
    except Exception:
        return None


def main():
    now = datetime.now()
    time_str = now.strftime('%H:%M')
    date_str = now.strftime('%Y-%m-%d')

    holdings = get_holdings()
    cash = get_cash()

    if not holdings:
        print(f'📊 盯盘 {date_str} {time_str} | 空仓 现金¥{cash:,.0f}')
        return

    # 大盘指数
    indices = get_market_indices()
    mkt_parts = []
    for name in ['上证', '深证', '创业板']:
        if name in indices:
            d = indices[name]
            mkt_parts.append(f"{name}{d['change_pct']:+.2f}%")
    mkt_str = ' '.join(mkt_parts) if mkt_parts else '未获取'
    sh = indices.get('上证', {}).get('change_pct', 0)
    sz = indices.get('深证', {}).get('change_pct', 0)
    cyb = indices.get('创业板', {}).get('change_pct', 0)
    mkt_warn = ''
    if min(sh, sz) < -2:
        mkt_warn = ' ⚠️弱市'
    elif min(sh, sz) < -1:
        mkt_warn = ' ⚠️偏弱'
    if cyb < -2:
        mkt_warn += ' 创业板大跌'

    # 逐只分析
    results = []
    total_mv = 0
    total_profit = 0
    has_alert = False
    has_warning = False

    for h in holdings:
        code = h['code']
        name = h['name']
        shares = h['shares']
        cost = h['cost']
        stop = h.get('stop', 0) or cost * 0.95
        tiers = get_stop_tiers(h)
        soft_stop = tiers['soft_stop']
        hard_stop = tiers['hard_stop']
        abs_stop = tiers['abs_stop']
        category = get_category(h)
        dca_plan = get_dca_plan(h)
        tp_trigger_pct, tp_trail_pct = get_tp_config(h)

        q = fetch_quote(code)
        if not q or q['price'] <= 0:
            results.append({'name': name, 'code': code, 'error': '行情获取失败'})
            has_warning = True
            continue

        price = q['price']
        change_pct = q['change_pct']
        mv = shares * price
        total_mv += mv
        pnl = (price - cost) * shares
        pnl_pct = (price / cost - 1) * 100
        total_profit += pnl
        stop_pct = (price - hard_stop) / price * 100
        soft_pct = (price - soft_stop) / price * 100
        hard_pct = (price - hard_stop) / price * 100
        abs_pct = (price - abs_stop) / price * 100

        # K线（取30日K线，用于EMA20+持仓期最高价）
        kl = fetch_kline(code, count=30)
        ema20 = kl['ema20'] if kl else None
        high_30d = kl['high_30d'] if kl else None
        ema_dev = (price - ema20) / ema20 * 100 if ema20 and ema20 > 0 else 0

        # 动态止盈（新策略v2: 长线15%+启动trailing 8%, 短线10%+启动trailing 5%）
        tp_line = None
        tp_pct = None
        tp_tier = ''
        if pnl_pct >= tp_trigger_pct:
            today_high = q.get('high', 0) or price
            # 优先用K线30日最高价作为峰值，fallback用今日最高价
            est_peak = high_30d if high_30d and high_30d > today_high else today_high
            # 确保峰值至少不低于成本价+触发涨幅
            min_peak = cost * (1 + tp_trigger_pct / 100)
            if est_peak < min_peak:
                est_peak = min_peak
            tp_line = est_peak * (1 - tp_trail_pct / 100)
            tp_tier = f'>{tp_trigger_pct}%'
            tp_pct = (price - tp_line) / price * 100

        # Vibe
        wl = load_watchlist_vibe(code)
        vibe_score = 0
        vibe_str = ''
        if wl:
            vibe_score = wl[0]
            if vibe_score != 0:
                vibe_str = f' Vibe{"+" if vibe_score > 0 else ""}{vibe_score}'

        # 资金面
        cf = load_capital_flow(code)
        cf_str = ''
        if cf is not None and cf < -5000:
            cf_str = f' 主力流出{abs(cf):.0f}万⚠️'
            has_warning = True
        elif cf is not None and cf > 3000:
            cf_str = f' 主力流入{cf:.0f}万'

        # 情绪面（iFinD新闻情绪，轻量获取）
        sent_str = ''
        sent_alert = False
        try:
            from ifind_news_sentiment import get_stock_sentiment
            _sent = get_stock_sentiment(code, name, size=3)
            if _sent and _sent['news_count'] > 0:
                _ss = _sent['score']
                if _ss >= 3:
                    sent_str = f' 📰利好({_ss:+d})'
                elif _ss >= 1:
                    sent_str = f' 📰偏利好({_ss:+d})'
                elif _ss <= -3:
                    sent_str = f' 📰利空({_ss:+d})⚠️'
                    sent_alert = True
                    has_warning = True
                elif _ss <= -1:
                    sent_str = f' 📰偏利空({_ss:+d})'
        except Exception:
            pass

        # 状态判断（新策略v2: 三层止损+补仓监控+只报异常）
        emoji = '🟢'
        alerts = []
        dca_alert = None

        # 三层止损
        if abs_pct < 0:
            emoji = '⛔'
            alerts.append(f'绝对止损¥{abs_stop:.2f}已破！建议卖出')
            has_alert = True
        elif hard_pct < 0:
            emoji = '🔴'
            alerts.append(f'硬止损¥{hard_stop:.2f}已破，需决策')
            has_alert = True
        elif soft_pct < 0:
            emoji = '🟡'
            alerts.append(f'软止损¥{soft_stop:.2f}触发(-{(cost-soft_stop)/cost*100:.0f}%)，观察不卖')
            has_warning = True
        # 浮亏8%以内静默，不设alert

        # 补仓监控（仅长线票）
        if dca_plan and pnl_pct < 0:
            for d in dca_plan:
                trigger_price = d['price']
                trigger_pct = d['trigger_pct']
                # 价格跌到补仓触发价或以下(含1.5%容差，防止盘中瞬间击穿后反弹错过)
                if price <= trigger_price * 1.015:
                    dca_alert = f'补仓触发: {category}票跌至¥{price:.2f}(触发价¥{trigger_price:.2f},{trigger_pct}%)，可补{d["shares"]}股'
                    if emoji == '🟢':
                        emoji = '🟡'
                    has_warning = True

        # EMA20偏离
        if ema_dev > 20:
            alerts.append(f'EMA20偏离+{ema_dev:.1f}%过热')
            if emoji == '🟢':
                emoji = '🟡'
            has_warning = True

        # 动态止盈
        if tp_line and tp_pct is not None:
            if tp_pct < 1:
                alerts.append(f'距止盈线仅{tp_pct:.1f}%！')
                if emoji == '🟢':
                    emoji = '🟡'
                has_warning = True
            elif tp_pct < 3:
                alerts.append(f'止盈线¥{tp_line:.2f}(距{tp_pct:.1f}%)')

        # Vibe负值
        if vibe_score < 0:
            alerts.append(f'Vibe{vibe_score}建议减仓')
            if emoji != '🔴':
                emoji = '🔴'
            has_alert = True

        # 涨停
        limit_up = q.get('limit_up', 0)
        if limit_up > 0 and abs(price - limit_up) / limit_up < 0.01:
            alerts.append('涨停板')

        status_str = ' | '.join(alerts) if alerts else '正常'
        if dca_alert:
            status_str = dca_alert + (' | ' + status_str if alerts else '')

        pnl_str = f'+{pnl_pct:.1f}%' if pnl_pct >= 0 else f'{pnl_pct:.1f}%'
        ema_str = f'EMA20={ema20:.2f}(偏离{ema_dev:+.1f}%)' if ema20 else 'EMA20=N/A'
        tp_str = f' | 止盈¥{tp_line:.2f}(距{tp_pct:.1f}%)' if tp_line else ''

        results.append({
            'name': name, 'code': code, 'price': price, 'change_pct': change_pct,
            'cost': cost, 'pnl_pct': pnl_pct, 'pnl': pnl, 'mv': mv,
            'category': category,
            'soft_stop': soft_stop, 'hard_stop': hard_stop, 'abs_stop': abs_stop,
            'soft_pct': soft_pct, 'hard_pct': hard_pct, 'abs_pct': abs_pct,
            'stop_pct': stop_pct,
            'ema20': ema20, 'ema_dev': ema_dev,
            'tp_line': tp_line, 'tp_pct': tp_pct, 'tp_tier': tp_tier,
            'tp_trigger_pct': tp_trigger_pct, 'tp_trail_pct': tp_trail_pct,
            'vibe_score': vibe_score, 'vibe_str': vibe_str,
            'cf_str': cf_str, 'sent_str': sent_str, 'emoji': emoji, 'status': status_str,
            'dca_alert': dca_alert, 'dca_plan': dca_plan,
            'amount': q['amount'], 'turnover': q.get('turnover', 0),
            'high': q['high'], 'low': q['low'],
        })

    total_asset = cash + total_mv

    # 构建报告
    lines = []
    header_emoji = '🔴' if has_alert else ('🟡' if has_warning else '✅')
    profit_str = f'浮盈¥{total_profit:+,.0f}' if total_profit >= 0 else f'浮亏¥{total_profit:+,.0f}'
    lines.append(f'📊 盯盘 {date_str} {time_str} | {header_emoji} 持仓{len(holdings)}只 | 总资产¥{total_asset:,.0f}(现金¥{cash:,.0f}+市值¥{total_mv:,.0f}) {profit_str}')
    lines.append(f'大盘: {mkt_str}{mkt_warn}')
    lines.append('')

    for r in results:
        if 'error' in r:
            lines.append(f"⚠️ {r['name']}({r['code']}) {r['error']}")
            continue
        pnl_emoji = '🟢' if r['pnl_pct'] >= 0 else '🔴'
        pnl_str = f"+{r['pnl_pct']:.1f}%" if r['pnl_pct'] >= 0 else f"{r['pnl_pct']:.1f}%"
        ema_str = f"EMA20={r['ema20']:.2f}(偏离{r['ema_dev']:+.1f}%)" if r['ema20'] else 'EMA20=N/A'
        tp_str = f" | 止盈¥{r['tp_line']:.2f}(距{r['tp_pct']:.1f}%)" if r['tp_line'] else ''
        cat_tag = f"[{r['category']}]" if r.get('category') else ''
        # 三层止损显示
        stop_str = f"软¥{r['soft_stop']:.2f}({r['soft_pct']:+.1f}%)/硬¥{r['hard_stop']:.2f}({r['hard_pct']:+.1f}%)"
        lines.append(
            f"{r['emoji']} **{r['name']}**({r['code']}) {cat_tag} ¥{r['price']:.2f} {r['change_pct']:+.1f}% "
            f"| 成本¥{r['cost']:.2f} {pnl_emoji}{pnl_str} "
            f"| {stop_str}{tp_str} "
            f"| {ema_str}{r['vibe_str']}{r['cf_str']}{r.get('sent_str', '')}"
        )
        lines.append(f"   {r['status']}")

    # 操作建议（新策略v2: 三层止损+补仓+只报异常）
    lines.append('')
    lines.append('📌 操作建议:')
    advice_items = []
    for r in results:
        if 'error' in r:
            advice_items.append(f"⚠️ {r['name']}({r['code']}): 行情获取失败，需人工检查")
            continue
        parts = []
        cat = r.get('category', '短线')
        # 三层止损建议
        if r['abs_pct'] < 0:
            parts.append(f'⛔绝对止损¥{r["abs_stop"]:.2f}已破，建议卖出')
        elif r['hard_pct'] < 0:
            parts.append(f'🔴硬止损¥{r["hard_stop"]:.2f}已破，需决策')
        elif r['soft_pct'] < 0:
            parts.append(f'🟡软止损¥{r["soft_stop"]:.2f}触发，观察不卖')
        # 补仓提醒
        if r.get('dca_alert'):
            parts.append(r['dca_alert'])
        # 止盈提醒
        if r['tp_line'] and r['tp_pct'] is not None and r['tp_pct'] < 1:
            parts.append(f'距止盈线仅{r["tp_pct"]:.1f}%，注意锁利')
        elif r['tp_line'] and r['tp_pct'] is not None and r['tp_pct'] < 3:
            parts.append(f'止盈线¥{r["tp_line"]:.2f}')
        # EMA偏离
        if r['ema_dev'] > 20:
            parts.append(f'EMA20偏离{r["ema_dev"]:.1f}%过热')
        # Vibe
        if r['vibe_score'] < 0:
            parts.append(f'Vibe{r["vibe_score"]}，建议减仓')
        # 新闻利空
        if r.get('sent_str') and '利空' in r.get('sent_str', ''):
            parts.append(f'新闻情绪{r["sent_str"].strip()}')
        if not parts:
            parts.append(f'{cat}票正常持有')
        emoji_map = {'⛔': '⛔', '🔴': '🔴', '🟡': '🟡', '🟢': '🟢', '⚠️': '⚠️'}
        advice_items.append(f"{emoji_map.get(r['emoji'], '🟢')} {r['name']}({r['code']})[{cat}]: {' | '.join(parts)}")

    for i, item in enumerate(advice_items, 1):
        lines.append(f"{i}. {item}")

    print('\n'.join(lines))


if __name__ == '__main__':
    main()
