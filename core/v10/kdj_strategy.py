#!/usr/bin/env python3
"""
V12猎庄模块 — 中长线跟庄策略
回测验证：+23.25%平均收益，7/10盈利，盈亏比1.67，均持仓24天

核心逻辑：
  入场：KDJ金叉8 + EMA20>EMA60趋势过滤
  退出（任一触发，12天最低持仓后）：
    1. KDJ死叉8（跌破8）
    2. VAR1>95极端超买
    3. 破EMA144隧道
    4. MACD(20,80,9)死叉
    5. 移动止盈（盈利>10%后回撤5%）
    6. -8%止损（无条件，不受12天限制）

用法：
  from kdj_strategy import calc_indicators, check_entry, check_exit, scan_signals
  df = fetch_kline('sh600519')
  df = calc_indicators(df)
  entry = check_entry(df)       # True/False + 原因
  exit = check_exit(df, entry_price=10.5, peak_price=11.8, hold_days=15)  # 退出信号
"""
import json
import ssl
import urllib.request
import numpy as np
import pandas as pd
from datetime import datetime
from collections import deque

# ============================================================
# 数据获取 — 腾讯前复权日K线
# ============================================================

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

def fetch_kline(code, count=250, end_date=None):
    """腾讯前复权日K线
    code: 6位股票代码，如 '600519' 或 'sz300750'
    count: K线根数
    end_date: 'YYYY-MM-DD' 或 None(到最新)
    """
    if '.' in code:
        prefix = 'sh' if code.startswith(('6', '5', '9')) else 'sz'
        secid = prefix + code.split('.')[0]
    elif code.startswith(('sh', 'sz')):
        secid = code
    else:
        prefix = 'sh' if code.startswith(('6', '5', '9')) else 'sz'
        secid = prefix + code

    end = end_date or datetime.now().strftime('%Y-%m-%d')
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={secid},day,,{end},{count},qfq'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx)
        raw = resp.read().decode('utf-8')
        data = json.loads(raw)
        klines = data.get('data', {}).get(secid, {}).get('qfqday') or \
                 data.get('data', {}).get(secid, {}).get('day') or \
                 data.get('data', {}).get(secid, {}).get('klines')
        if not klines:
            return None
        rows = [k[:6] for k in klines]
        df = pd.DataFrame(rows, columns=['date', 'open', 'close', 'high', 'low', 'volume'])
        df['date'] = pd.to_datetime(df['date'])
        for c in ['open', 'close', 'high', 'low', 'volume']:
            df[c] = pd.to_numeric(df[c])
        df.set_index('date', inplace=True)
        return df
    except Exception as e:
        return None


def fetch_quote(code):
    """腾讯实时行情"""
    prefix = 'sh' if code.startswith(('6', '5', '9')) else 'sz'
    url = f'https://qt.gtimg.cn/q={prefix}{code}'
    try:
        resp = urllib.request.urlopen(url, timeout=5, context=_ssl_ctx)
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
        }
    except:
        return None


# ============================================================
# 指标计算
# ============================================================

def _tdx_sma(series, n, m=1):
    """通达信SMA(X,N,M) = (M*X + (N-M)*Y_prev) / N"""
    result = pd.Series(np.nan, index=series.index, dtype=float)
    y = 0.0
    for i in range(len(series)):
        x = series.iloc[i]
        if pd.isna(x):
            result.iloc[i] = y
            continue
        y = x if i == 0 else (m * x + (n - m) * y) / n
        result.iloc[i] = y
    return result

def _hhv_fast(series, period):
    """快速HHV — deque O(n)"""
    vals = series.values
    n = len(vals)
    result = np.empty(n, dtype=float)
    dq = deque()
    for i in range(n):
        while dq and dq[0] < i - period + 1:
            dq.popleft()
        while dq and series.iloc[dq[-1]] <= series.iloc[i]:
            dq.pop()
        dq.append(i)
        result[i] = vals[dq[0]]
    return pd.Series(result, index=series.index)

def _llv_fast(series, period):
    """快速LLV — deque O(n)"""
    vals = series.values
    n = len(vals)
    result = np.empty(n, dtype=float)
    dq = deque()
    for i in range(n):
        while dq and dq[0] < i - period + 1:
            dq.popleft()
        while dq and series.iloc[dq[-1]] >= series.iloc[i]:
            dq.pop()
        dq.append(i)
        result[i] = vals[dq[0]]
    return pd.Series(result, index=series.index)


def calc_indicators(df, n=5):
    """计算V12猎庄全部指标

    入场指标：
      kdj_cross_up: VAR1金叉8（买入信号）
      bull_trend: EMA20>EMA60（趋势过滤）

    退出指标：
      kdj_cross_down: VAR1死叉8
      kdj_overbought: VAR1>95极端超买
      macd_cross_down: MACD(20,80,9)死叉
      break_tunnel: 破EMA144隧道

    其他：
      VAR1: 改性KDJ J值
      VAR07: 中期超卖指标
      buildup_zone: VAR07<10建仓区
      tunnel_bull: V10隧道多头
      v10_buy: V10完整买入信号
    """
    close = df['close']
    high = df['high']
    low = df['low']
    vol = df['volume']
    open_ = df['open']

    # ─── KDJ改性指标 ───
    llv5 = low.rolling(n).min()
    hhv5 = high.rolling(n).max()
    rsv = (close - llv5) / (hhv5 - llv5) * 100
    rsv = rsv.replace([np.inf, -np.inf], 50).fillna(50)
    k = _tdx_sma(rsv, 5, 1)
    d = _tdx_sma(k, 3.2, 1)
    df['VAR1'] = 4 * k - 3 * d

    # 金叉/死叉
    df['kdj_cross_up'] = (df['VAR1'] > 8) & (df['VAR1'].shift(1) <= 8)
    df['kdj_cross_down'] = (df['VAR1'] < 8) & (df['VAR1'].shift(1) >= 8)
    df['kdj_overbought'] = df['VAR1'] > 95

    # 中期超卖
    var05 = low.rolling(27).min()
    var06 = high.rolling(34).max()
    var07_raw = (close - var05) / (var06 - var05) * 4
    var07_raw = var07_raw.replace([np.inf, -np.inf], 2).fillna(2)
    df['VAR07'] = var07_raw.ewm(span=4, adjust=False).mean() * 25
    df['buildup_zone'] = df['VAR07'] < 10

    # ─── 趋势过滤 ───
    df['EMA20'] = close.ewm(span=20, adjust=False).mean()
    df['EMA60'] = close.ewm(span=60, adjust=False).mean()
    df['bull_trend'] = df['EMA20'] > df['EMA60']

    # ─── V10指标 ───
    df['EMA144'] = close.ewm(span=144, adjust=False).mean()
    df['EMA169'] = close.ewm(span=169, adjust=False).mean()
    df['MA7'] = close.rolling(7).mean()
    df['MA26'] = close.rolling(26).mean()

    # MACD(20,80,9)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema80 = close.ewm(span=80, adjust=False).mean()
    df['DIF'] = ema20 - ema80
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['macd_cross_down'] = (df['DIF'] < df['DEA']) & (df['DIF'].shift(1) >= df['DEA'].shift(1))

    # 破隧道
    df['break_tunnel'] = close < df['EMA144']

    # V10隧道多头
    df['tunnel_bull'] = (close > df['EMA144']) & (close > df['EMA169']) & (df['EMA144'] > df['EMA169'])

    # QW动能
    llv9 = _llv_fast(low, 9)
    hhv9 = _hhv_fast(high, 9)
    rsv9 = (close - llv9) / (hhv9 - llv9) * 100
    rsv9 = rsv9.replace([np.inf, -np.inf], 50).fillna(50)
    df['K9'] = rsv9.ewm(span=3, adjust=False).mean()
    df['QW'] = df['K9'].ewm(span=3, adjust=False).mean()
    df['QW_rising'] = df['QW'] > df['QW'].shift(1)

    # 放量
    df['VOL_MA5'] = vol.rolling(5).mean()
    df['volume_surge'] = vol > 1.8 * df['VOL_MA5']
    df['bullish_candle'] = close > open_
    df['channel_width'] = (df['MA7'] - df['MA26']) / df['MA26']

    # V10完整买入信号
    df['v10_buy'] = (df['tunnel_bull'] & df['QW_rising'] &
                     (df['channel_width'] > 0.01) & df['bullish_candle'] & df['volume_surge'])

    return df


# ============================================================
# 信号检查
# ============================================================

# 策略参数（回测验证最优组合）
STOP_LOSS = -0.08          # -8%止损
MIN_HOLD_DAYS = 12         # 最低持仓12天
TP_ACTIVATE = 0.10         # 盈利10%启动移动止盈
TP_FALLBACK = 0.05         # 回撤5%止盈

def check_entry(df):
    """检查最新一天的入场信号
    返回: dict {signal: bool, reason: str, var1: float, trend: bool}
    """
    if df is None or len(df) < 60:
        return {'signal': False, 'reason': '数据不足', 'var1': None, 'trend': None}

    last = df.iloc[-1]
    prev = df.iloc[-2]

    kdj_cross = bool(last['kdj_cross_up'])
    bull_trend = bool(last['bull_trend'])
    tunnel_bull = bool(last['tunnel_bull'])

    # 入场条件：KDJ金叉 + 趋势过滤
    signal = kdj_cross and bull_trend

    # V10共振加分
    v10_resonance = kdj_cross and tunnel_bull and bool(last.get('dual_line', False))

    reasons = []
    if kdj_cross:
        reasons.append('KDJ金叉')
    if bull_trend:
        reasons.append('EMA20>EMA60多头')
    if tunnel_bull:
        reasons.append('V10隧道多头')
    if last.get('buildup_zone', False):
        reasons.append('建仓区共振')

    return {
        'signal': signal,
        'reason': '+'.join(reasons) if reasons else '无信号',
        'var1': round(float(last['VAR1']), 2),
        'var07': round(float(last['VAR07']), 2),
        'trend': bull_trend,
        'tunnel': tunnel_bull,
        'v10_resonance': v10_resonance,
        'buildup': bool(last.get('buildup_zone', False)),
        'close': float(last['close']),
    }


def check_exit(df, entry_price, peak_price, hold_days, entry_date=None):
    """检查退出信号（组合策略退出条件）

    返回: dict {signal: bool, reason: str, urgency: str}
    urgency: 'high'(立即) / 'medium'(关注) / 'low'(观察)
    """
    if df is None or len(df) < 2:
        return {'signal': False, 'reason': '数据不足', 'urgency': 'low'}

    last = df.iloc[-1]
    current = float(last['close'])
    pnl_pct = (current - entry_price) / entry_price

    # 1. 止损（无条件，不受12天限制）
    if pnl_pct <= STOP_LOSS:
        return {
            'signal': True,
            'reason': f'止损{STOP_LOSS*100:.0f}%(浮亏{pnl_pct*100:.1f}%)',
            'urgency': 'high',
            'pnl_pct': round(pnl_pct * 100, 2),
        }

    # 最低持仓期内的信号（只记录不触发）
    if hold_days < MIN_HOLD_DAYS:
        pending = []
        if bool(last['kdj_cross_down']):
            pending.append(f'KDJ死叉(待{MIN_HOLD_DAYS}天)')
        if bool(last['kdj_overbought']):
            pending.append(f'VAR1>95超买(待{MIN_HOLD_DAYS}天)')
        if bool(last['macd_cross_down']):
            pending.append(f'MACD死叉(待{MIN_HOLD_DAYS}天)')
        if bool(last['break_tunnel']):
            pending.append(f'破隧道(待{MIN_HOLD_DAYS}天)')
        return {
            'signal': False,
            'reason': f'持仓{hold_days}天<{MIN_HOLD_DAYS}天' + ('；待触发:' + ';'.join(pending) if pending else ''),
            'urgency': 'low',
            'pnl_pct': round(pnl_pct * 100, 2),
        }

    # 2. 12天后检查所有退出条件
    # KDJ死叉
    if bool(last['kdj_cross_down']):
        return {
            'signal': True,
            'reason': f'KDJ死叉8(VAR1={last["VAR1"]:.1f})',
            'urgency': 'high',
            'pnl_pct': round(pnl_pct * 100, 2),
        }

    # 3. VAR1极端超买
    if bool(last['kdj_overbought']):
        return {
            'signal': True,
            'reason': f'VAR1>95极端超买(VAR1={last["VAR1"]:.1f})',
            'urgency': 'high',
            'pnl_pct': round(pnl_pct * 100, 2),
        }

    # 4. MACD死叉
    if bool(last['macd_cross_down']):
        return {
            'signal': True,
            'reason': 'MACD死叉(20,80,9)',
            'urgency': 'medium',
            'pnl_pct': round(pnl_pct * 100, 2),
        }

    # 5. 破EMA144隧道
    if bool(last['break_tunnel']):
        return {
            'signal': True,
            'reason': f'破EMA144隧道(价{current:.2f}<EMA144={last["EMA144"]:.2f})',
            'urgency': 'high',
            'pnl_pct': round(pnl_pct * 100, 2),
        }

    # 6. 移动止盈
    if pnl_pct > TP_ACTIVATE:
        fallback = (peak_price - current) / peak_price if peak_price > 0 else 0
        if fallback >= TP_FALLBACK:
            return {
                'signal': True,
                'reason': f'移动止盈(峰值{peak_price:.2f}回撤{fallback*100:.1f}%,盈{pnl_pct*100:.1f}%)',
                'urgency': 'medium',
                'pnl_pct': round(pnl_pct * 100, 2),
            }

    # 无信号，返回当前状态
    return {
        'signal': False,
        'reason': f'持有中(VAR1={last["VAR1"]:.1f},浮盈{pnl_pct*100:.1f}%)',
        'urgency': 'low',
        'pnl_pct': round(pnl_pct * 100, 2),
    }


def get_signal_summary(df, entry_price=None, peak_price=None, hold_days=0):
    """获取完整信号摘要，用于报告输出"""
    if df is None or len(df) < 60:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    current = float(last['close'])

    summary = {
        'close': current,
        'var1': round(float(last['VAR1']), 2),
        'var07': round(float(last['VAR07']), 2),
        'ema20': round(float(last['EMA20']), 2),
        'ema60': round(float(last['EMA60']), 2),
        'ema144': round(float(last['EMA144']), 2),
        'bull_trend': bool(last['bull_trend']),
        'tunnel_bull': bool(last['tunnel_bull']),
        'kdj_cross_up': bool(last['kdj_cross_up']),
        'kdj_cross_down': bool(last['kdj_cross_down']),
        'kdj_overbought': bool(last['kdj_overbought']),
        'macd_cross_down': bool(last['macd_cross_down']),
        'break_tunnel': bool(last['break_tunnel']),
        'buildup_zone': bool(last.get('buildup_zone', False)),
        'v10_buy': bool(last.get('v10_buy', False)),
    }

    if entry_price and entry_price > 0:
        summary['entry_price'] = entry_price
        summary['pnl_pct'] = round((current - entry_price) / entry_price * 100, 2)
        if peak_price and peak_price > 0:
            summary['peak_price'] = peak_price
            summary['fallback_pct'] = round((peak_price - current) / peak_price * 100, 2)

        exit = check_exit(df, entry_price, peak_price or current, hold_days)
        summary['exit_signal'] = exit['signal']
        summary['exit_reason'] = exit['reason']
        summary['exit_urgency'] = exit['urgency']
    else:
        entry = check_entry(df)
        summary['entry_signal'] = entry['signal']
        summary['entry_reason'] = entry['reason']

    return summary


# ============================================================
# 批量扫描
# ============================================================

def scan_signals(symbols, with_holdings=None):
    """扫描股票列表的KDJ信号

    symbols: [(code, name), ...] 或 [code, ...]
    with_holdings: [{code, entry_price, peak_price, hold_days, ...}, ...] 或 None

    返回: {
        'entry_signals': [...],  # 入场信号列表
        'exit_signals': [...],   # 退出信号列表
        'all_scanned': [...],    # 全部扫描结果
        'scan_time': datetime string
    }
    """
    import time

    results = {'entry_signals': [], 'exit_signals': [], 'all_scanned': [], 'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

    holdings_map = {}
    if with_holdings:
        for h in with_holdings:
            holdings_map[h['code']] = h

    for sym in symbols:
        if isinstance(sym, tuple):
            code, name = sym[0], sym[1]
        else:
            code = sym
            name = holdings_map.get(code, {}).get('name', code)

        try:
            df = fetch_kline(code, count=250)
            if df is None or len(df) < 60:
                results['all_scanned'].append({'code': code, 'name': name, 'error': '数据不足'})
                continue

            df = calc_indicators(df)

            # 持仓退出检查
            if code in holdings_map:
                h = holdings_map[code]
                exit = check_exit(df, h.get('entry_price', 0), h.get('peak_price', 0), h.get('hold_days', 0))
                item = {
                    'code': code, 'name': name,
                    'close': float(df.iloc[-1]['close']),
                    'var1': round(float(df.iloc[-1]['VAR1']), 2),
                    'pnl_pct': exit.get('pnl_pct', 0),
                    'exit_signal': exit['signal'],
                    'exit_reason': exit['reason'],
                    'exit_urgency': exit['urgency'],
                    **{k: v for k, v in get_signal_summary(df, h.get('entry_price'), h.get('peak_price'), h.get('hold_days', 0)).items()
                       if k not in ('close', 'var1')},
                }
                results['all_scanned'].append(item)
                if exit['signal']:
                    results['exit_signals'].append(item)
            else:
                # 入场信号检查
                entry = check_entry(df)
                item = {
                    'code': code, 'name': name,
                    'close': float(df.iloc[-1]['close']),
                    'var1': entry.get('var1', 0),
                    'entry_signal': entry['signal'],
                    'entry_reason': entry['reason'],
                    'trend': entry.get('trend', False),
                    'tunnel': entry.get('tunnel', False),
                    'v10_resonance': entry.get('v10_resonance', False),
                    'buildup': entry.get('buildup', False),
                }
                results['all_scanned'].append(item)
                if entry['signal']:
                    results['entry_signals'].append(item)

            time.sleep(0.15)  # 避免请求过快
        except Exception as e:
            results['all_scanned'].append({'code': code, 'name': name, 'error': str(e)})

    return results


def format_report(results, title='V12猎庄扫描'):
    """格式化扫描结果为报告文本"""
    lines = [f"📊 {title}"]
    lines.append(f"⏰ 扫描时间: {results.get('scan_time', 'N/A')}")
    lines.append("")

    # 退出信号（持仓）
    exits = results.get('exit_signals', [])
    if exits:
        lines.append(f"🚨 退出信号 ({len(exits)}只)")
        for e in exits:
            urgency = '🔴' if e.get('exit_urgency') == 'high' else '🟡' if e.get('exit_urgency') == 'medium' else '🟢'
            lines.append(f"  {urgency} {e['code']} {e['name']} | 现价{e['close']} | 浮盈{e.get('pnl_pct',0):+.1f}% | {e['exit_reason']}")
        lines.append("")

    # 入场信号
    entries = results.get('entry_signals', [])
    if entries:
        lines.append(f"✅ 入场信号 ({len(entries)}只)")
        for e in entries:
            tags = []
            if e.get('tunnel'): tags.append('V10隧道')
            if e.get('buildup'): tags.append('建仓区')
            if e.get('v10_resonance'): tags.append('V10共振')
            tag_str = ' '.join(tags) if tags else ''
            lines.append(f"  ⭐ {e['code']} {e['name']} | 现价{e['close']} | VAR1={e['var1']} | {e['entry_reason']} {tag_str}")
        lines.append("")

    # 全部扫描摘要
    all_items = results.get('all_scanned', [])
    errors = [x for x in all_items if 'error' in x]
    if errors:
        lines.append(f"⚠️ 数据异常: {len(errors)}只")
        for e in errors:
            lines.append(f"  {e['code']} {e.get('name','')} - {e['error']}")

    total = len(all_items) - len(errors)
    lines.append(f"\n📈 扫描: {total}只 | 入场信号: {len(entries)} | 退出信号: {len(exits)}")

    return '\n'.join(lines)


# ============================================================
# 主程序 — 独立运行时扫描V10观察池+持仓
# ============================================================
if __name__ == '__main__':
    import sys
    import os

    sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))

    # 命令行参数
    quiet_mode = '--quiet' in sys.argv  # 只输出有信号的股票
    holdings_only = '--holdings-only' in sys.argv  # 只扫持仓

    # 读取持仓
    try:
        from current_holdings import get_holdings
        holdings = get_holdings()
        holdings_codes = [(h['code'], h['name']) for h in holdings]
        holdings_list = []
        for h in holdings:
            entry_dt = None
            if h.get('date'):
                try:
                    entry_dt = datetime.strptime(h['date'], '%Y-%m-%d')
                except:
                    pass
            hold_days = (datetime.now() - entry_dt).days if entry_dt else 0
            holdings_list.append({
                'code': h['code'],
                'name': h['name'],
                'entry_price': h.get('cost', 0),
                'peak_price': h.get('cost', 0),  # 简化：用成本价，实际应跟踪峰值
                'hold_days': hold_days,
            })
    except Exception as e:
        print(f"⚠️ 读取持仓失败: {e}")
        holdings_codes = []
        holdings_list = []

    # 读取V10观察池
    watchlist_codes = []
    if not holdings_only:
        watchlist_path = os.path.expanduser('~/.hermes/cache/v10_watchlist.json')
        try:
            with open(watchlist_path) as f:
                wl = json.load(f)
            wl_stocks = wl.get('stocks', wl.get('signals', []))
            watchlist_codes = [(s.get('code', s.get('symbol', '')), s.get('name', '')) for s in wl_stocks if s.get('code')]
        except:
            pass

    # 合并去重（持仓优先）
    seen = set()
    all_codes = []
    for code, name in holdings_codes + watchlist_codes:
        if code and code not in seen:
            seen.add(code)
            all_codes.append((code, name))

    if not all_codes:
        if not quiet_mode:
            print("❌ 无可扫描股票（持仓和V10观察池均为空）")
        sys.exit(0)

    # 扫描
    results = scan_signals(all_codes, with_holdings=holdings_list)

    # 输出
    exits = results.get('exit_signals', [])
    entries = results.get('entry_signals', [])

    if quiet_mode and not exits and not entries:
        # 静默模式：无信号不输出
        sys.exit(0)

    # 构建报告
    now = datetime.now()
    time_str = now.strftime('%H:%M')
    date_str = now.strftime('%Y-%m-%d')

    lines = [f"📊 V12猎庄扫描 {date_str} {time_str}"]
    lines.append(f"扫描: 持仓{len(holdings_codes)}只 + V10池{len(watchlist_codes)}只 = {len(all_codes)}只")
    lines.append("")

    # 退出信号（持仓）— 最高优先级
    if exits:
        lines.append(f"🚨 KDJ退出信号 ({len(exits)}只)")
        for e in exits:
            urgency = '🔴' if e.get('exit_urgency') == 'high' else '🟡'
            lines.append(
                f"  {urgency} {e['code']} {e['name']} | 现价{e['close']} | 浮盈{e.get('pnl_pct', 0):+.1f}% | {e['exit_reason']}"
            )
        lines.append("")

    # 入场信号
    if entries:
        lines.append(f"✅ KDJ入场信号 ({len(entries)}只)")
        for e in entries:
            tags = []
            if e.get('tunnel'): tags.append('V10隧道')
            if e.get('buildup'): tags.append('建仓区')
            if e.get('v10_resonance'): tags.append('V10共振')
            tag_str = ' '.join(tags) if tags else ''
            lines.append(
                f"  ⭐ {e['code']} {e['name']} | 现价{e['close']} | VAR1={e['var1']} | {e['entry_reason']} {tag_str}"
            )
        lines.append("")

    # 持仓KDJ状态摘要
    if holdings_list:
        lines.append("📋 持仓KDJ状态")
        for h in holdings_list:
            # 从all_scanned中找到对应的数据
            for item in results.get('all_scanned', []):
                if item.get('code') == h['code'] and 'exit_signal' in item:
                    ks = item
                    icon = '🔴' if ks.get('exit_signal') and ks.get('exit_urgency') == 'high' else \
                          '🟡' if ks.get('exit_signal') else '🟢'
                    lines.append(
                        f"  {icon} {h['code']} {h['name']} | VAR1={ks.get('var1', 'N/A')} | "
                        f"趋势{'多' if ks.get('bull_trend') else '空'} | {ks.get('exit_reason', '正常')}"
                    )
                    break
        lines.append("")

    # 统计
    total = len(results.get('all_scanned', []))
    errors = sum(1 for x in results.get('all_scanned', []) if 'error' in x)
    lines.append(f"📈 扫描{total}只(误差{errors}只) | 入场{len(entries)} | 退出{len(exits)}")

    print('\n'.join(lines))
