#!/usr/bin/env python3
"""
V10 自动交易脚本 - 选股扫描 + mx-moni 自动买卖
策略：维加斯V10 + 强庄控盘 V5.1
数据源：腾讯K线API + 东方财富
交易：妙想模拟组合管理（mx-moni）

功能：
1. 全市场 V10 信号扫描
2. 查询现有持仓，检查止损/止盈/通道死叉/MACD死叉信号 → 自动卖出
3. 强庄买/基础买信号 → 自动买入（20%资金，最多5只）
4. 输出交易报告
"""

import os
import sys
import json
import time
import csv
import subprocess
import argparse
import threading
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
from collections import deque
from datetime import datetime
import requests

warnings.filterwarnings('ignore')

# ====== 加载环境变量 ======
def load_env():
    """从 ~/.hermes/.env 加载环境变量"""
    env_path = os.path.expanduser('~/.hermes/.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip())

load_env()

# ====== 配置 ======
MX_MONI_SCRIPT = os.path.expanduser('~/mx-moni/mx-moni/mx_moni.py')
MX_PYTHON = '/tmp/mx_venv/bin/python'
MX_APIKEY = os.environ.get('MX_APIKEY', '')
MX_API_URL = os.environ.get('MX_API_URL', 'https://mkapi2.dfcfs.com/finskillshub')
# ====== 参数（V5.1 优化版） ======
参数_放量 = 1.5
参数_强庄 = 2
参数_通道宽度 = 0.015
参数_硬止损 = 0.94       # -6% 无条件清仓
参数_移动激活 = 1.05     # 涨5%激活移动止盈
参数_移动回落 = 0.98     # 回落2%锁定利润
参数_震荡过滤 = 3.0      # 震荡过滤阈值
参数_持仓保护期天数 = 3    # 持仓保护期，期间跳过硬止损

POSITION_RATIO = 0.30    # 每只投入可用资金的30%
MAX_POSITIONS = 3        # 最多同时持有3只

PROXIES = {'http': None, 'https': None}

from v10_core import ema_fast, hhv_fast, llv_fast, barslast_fast

# Vibe增强：加载本地技术分析模块（K线形态/SMC/缠论/OIR）
try:
    sys.path.insert(0, os.path.dirname(__file__))
    from tech_analysis import compute_technical_score
    VIBE_ENABLED = True
except Exception:
    VIBE_ENABLED = False

def log(msg):
    print(msg, flush=True)

# ====== mx-moni API 调用 ======
def mx_api_call(endpoint, body, output_prefix='mx_call'):
    """直接调用 mx-moni API"""
    if not MX_APIKEY:
        log("⚠️ MX_APIKEY 未配置，跳过交易操作")
        return None
    full_url = f"{MX_API_URL}{endpoint}"
    headers = {'apikey': MX_APIKEY, 'Content-Type': 'application/json'}
    try:
        resp = requests.post(full_url, headers=headers, json=body, timeout=30)
        result = resp.json()
        return result
    except Exception as e:
        log(f"⚠️ API调用失败: {e}")
        return None

def get_positions():
    """查询持仓"""
    result = mx_api_call('/api/claw/mockTrading/positions', {'moneyUnit': 1})
    if result and result.get('code') == '200':
        return result.get('data', {})
    log(f"⚠️ 查询持仓失败: {result}")
    return None

def get_balance():
    """查询资金"""
    result = mx_api_call('/api/claw/mockTrading/balance', {'moneyUnit': 1})
    if result and result.get('code') == '200':
        return result.get('data', {})
    log(f"⚠️ 查询资金失败: {result}")
    return None

def buy_stock(code, quantity):
    """市价买入"""
    log(f"  📈 买入 {code} {quantity}股（市价）")
    body = {
        'type': 'buy',
        'stockCode': code,
        'quantity': quantity,
        'useMarketPrice': True
    }
    result = mx_api_call('/api/claw/mockTrading/trade', body)
    if result and result.get('code') == '200':
        log(f"  ✅ 买入成功: {code} {quantity}股")
        return True
    log(f"  ❌ 买入失败: {result}")
    return False

def sell_stock(code, quantity):
    """市价卖出"""
    log(f"  📉 卖出 {code} {quantity}股（市价）")
    body = {
        'type': 'sell',
        'stockCode': code,
        'quantity': quantity,
        'useMarketPrice': True
    }
    result = mx_api_call('/api/claw/mockTrading/trade', body)
    if result and result.get('code') == '200':
        log(f"  ✅ 卖出成功: {code} {quantity}股")
        return True
    log(f"  ❌ 卖出失败: {result}")
    return False

# ====== K线数据获取 ======
def get_klines(symbol, datalen=250):
    """获取新浪日K线"""
    url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    try:
        resp = requests.get(url, timeout=10, proxies=PROXIES)
        if resp.status_code == 200 and resp.text.strip():
            return json.loads(resp.text)
    except:
        pass
    return None

# ====== 卖出信号检测 ======
def check_sell_signals(close, high, low, open_price, volume, cost_price=None, max_price_since_buy=None, buy_date=None):
    """
    检查卖出信号（V5.1：含MACD死叉退出）
    返回: (信号列表, 最新MA7, 最新MA26, 最新EMA120, 最新EMA200)
    """
    n = len(close)
    if n < 200:
        return [], None, None, None, None
    
    MA7 = ema_fast(close, 7)
    MA26 = ema_fast(close, 26)
    EMA120 = ema_fast(close, 120)
    EMA200 = ema_fast(close, 200)
    
    # V5.1新增: MACD(20,80,9)
    MA20 = ema_fast(close, 20)
    EMA80 = ema_fast(close, 80)
    DIF = MA20 - EMA80
    DEA = ema_fast(DIF, 9)
    
    i = n - 1
    signals = []
    
    # 通道死叉: MA26上穿MA7（MA26>MA7且前一天MA26<=MA7）
    if i > 0 and MA26[i] > MA7[i] and MA26[i-1] <= MA7[i-1]:
        signals.append('★通道死叉')
    
    # V5.1新增: MACD死叉退出（DIF下穿DEA）
    if i > 0 and DIF[i] < DEA[i] and DIF[i-1] >= DEA[i-1]:
        signals.append('★MACD死叉')
    
    # 破隧道: 收盘价 < EMA120 或 < EMA200
    if close[i] < EMA120[i] or close[i] < EMA200[i]:
        signals.append('★破隧道')
    
    # 持仓保护期：保护期内跳过硬止损，保留其他卖出信号
    in_protection = False
    if buy_date and cost_price:
        try:
            buy_dt = datetime.strptime(buy_date, '%Y-%m-%d')
            hold_days = (datetime.now() - buy_dt).days
            if hold_days < 参数_持仓保护期天数:
                in_protection = True
        except:
            pass

    # 硬止损: 跌破买入价的6%（保护期内跳过）
    if not in_protection and cost_price and close[i] < cost_price * 参数_硬止损:
        signals.append('★硬止损')
    
    # 移动止盈: 最高价回落3%锁定利润（涨10%后激活）
    if max_price_since_buy and cost_price:
        if max_price_since_buy >= cost_price * 参数_移动激活:
            trailing_stop = max_price_since_buy * 参数_移动回落
            if close[i] < trailing_stop:
                signals.append('★移动止盈')
    
    # 转弱: MA7向下且收盘<MA26
    if MA7[i] < MA7[i-1] and close[i] < MA26[i]:
        signals.append('转弱')
    
    # 减仓: 转弱 + 缩量
    if '转弱' in signals and i > 0 and volume[i] < volume[i-1] * 0.7:
        signals.append('减仓')
    
    return signals, MA7[i], MA26[i], EMA120[i], EMA200[i]

# ====== 买入信号扫描 ======
def scan_stock(close, high, low, volume, open_price):
    """
    按同花顺公式扫描单只股票（V3混合版 + V4严格版）
    V3信号层级：强庄买 > 基础买 > 买入加仓 > 激进买
    V4精选：所有条件+MACD金叉同时满足（最高确定性）
    """
    n = len(close)
    if n < 200:
        return None
    
    隧道快 = ema_fast(close, 120)
    隧道慢 = ema_fast(close, 200)
    MA7 = ema_fast(close, 7)
    MA26 = ema_fast(close, 26)
    
    lowest9 = llv_fast(low, 9)
    highest9 = hhv_fast(high, 9)
    diff9 = highest9 - lowest9
    RSV = np.where(diff9 > 0, (close - lowest9) / diff9 * 100, 50.0)
    K = ema_fast(RSV, 3)
    QW = ema_fast(K, 3)
    
    通道间距 = np.where(MA26 > 0, (MA7 - MA26) / MA26, 0.0)
    
    VOL_MA5 = np.zeros(n, dtype=float)
    for i in range(4, n):
        VOL_MA5[i] = np.mean(volume[i-4:i+1])
    
    # MACD(20,80,9)
    DIF = ema_fast(close, 20) - ema_fast(close, 80)
    DEA = ema_fast(DIF, 9)
    
    # 震荡过滤指标
    趋势20 = ema_fast(close, 20)
    趋势40 = ema_fast(close, 40)
    
    WEIGHT = (2 * close + open_price + high + low) * 100
    WEIGHT_EMA = ema_fast(WEIGHT, 4)
    VAR1 = np.where(WEIGHT_EMA > 0, (WEIGHT / WEIGHT_EMA - 1) * 100, 0.0)
    VAR1_ABS = np.abs(VAR1)
    VAR1_HH20 = hhv_fast(VAR1_ABS, 20)
    STRONG = (VAR1_ABS >= VAR1_HH20 * 0.9999) & (VAR1 > 0)
    barslast_STRONG = barslast_fast(STRONG)
    
    i = n - 1
    
    # 震荡过滤判断
    T_W = abs(趋势20[i] - 趋势40[i]) / 趋势40[i] * 100
    is_震荡 = T_W < 参数_震荡过滤 or abs(DIF[i]) / close[i] * 100 < 1.5
    
    隧道多头 = close[i] > 隧道快[i] and close[i] > 隧道慢[i] and 隧道快[i] > 隧道慢[i]
    双线定式 = MA7[i] > MA26[i] and MA7[i] > MA7[i-1]
    QW上升 = QW[i] > QW[i-1]
    宽度OK = 通道间距[i] > 参数_通道宽度
    阳线 = close[i] > open_price[i]
    放量 = volume[i] > 参数_放量 * VOL_MA5[i] if VOL_MA5[i] > 0 else False
    放量13 = volume[i] > 1.3 * volume[i-1] if i > 0 else False
    
    ST_FIRST = STRONG[i] and barslast_STRONG[i-1] >= 参数_强庄
    强庄信号 = 放量 and 阳线 and ST_FIRST
    
    基础看多 = 隧道多头 and MA7[i] > MA26[i]
    基础买 = 隧道多头 and 双线定式 and QW上升 and 宽度OK and 阳线 and 放量
    强庄买 = 基础买 and 强庄信号
    
    MACD金叉 = DIF[i] > DEA[i] and (i > 0 and DIF[i-1] <= DEA[i-1])
    买入加仓 = 基础看多 and MACD金叉 and QW上升 and 放量13 and 阳线
    
    激进买 = 隧道多头 and MA7[i] > MA26[i] and QW上升 and 放量 and 阳线 and not 基础买 and not 强庄买
    
    # V4严格版：所有条件+MACD金叉同时满足
    v4精选 = (隧道多头 and 双线定式 and QW上升 and 宽度OK and 阳线 and 放量
              and 强庄信号 and MACD金叉)

    # 震荡市不发出V3信号，但V4精选不受影响
    signals = []
    if v4精选:
        signals.append("★V4精选★")
        signals.append("强庄买")
    elif not is_震荡:
        if 强庄买:
            signals.append("强庄买")
        elif 基础买:
            signals.append("基础买")
        elif 买入加仓:
            signals.append("买入加仓")
        elif 激进买:
            signals.append("激进买")
    
    info = {'通道间距': 通道间距[i], 'v4精选': v4精选}
    return signals, info

# ====== 获取股票列表 ======
def get_stock_list():
    """获取全市场A股列表"""
    stocks = []
    for node in ['sh_a', 'sz_a']:
        prefixes = ['sh6'] if node == 'sh_a' else ['sz0', 'sz3']
        for prefix in prefixes:
            for page in range(1, 50):
                try:
                    url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=80&sort=symbol&asc=1&node={node}&symbol=&_s_r_a=page"
                    resp = requests.get(url, timeout=10, proxies=PROXIES)
                    if resp.status_code == 200 and resp.text.strip():
                        data = json.loads(resp.text)
                        for item in data:
                            symbol = item.get('symbol', '')
                            if symbol.startswith(prefix):
                                name = item.get('name', '')
                                if 'ST' not in name and '退市' not in name:
                                    price = float(item.get('trade', 0))
                                    if price > 0:
                                        stocks.append({
                                            'code': symbol[2:],
                                            'name': name,
                                            'symbol': symbol,
                                            'price': price,
                                            'change': float(item.get('changepercent', 0)),
                                            'turnover': float(item.get('turnoverratio', 0)),
                                        })
                        if len(data) < 80:
                            break
                    time.sleep(0.1)
                except:
                    break
    return stocks

# ====== 周期运行状态 ======
STATE_PATH = os.path.expanduser('~/.hermes/workspace/v10_auto_trade_state.json')

def _load_state():
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {'last_buy_codes': [], 'held_codes': [], 'last_run_ts': 0}

def _save_state(state):
    try:
        state['last_run_ts'] = int(time.time())
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ====== 单只股票扫描（线程安全，供并行调用） ======
def _scan_one(stock):
    """线程安全：扫描单只股票，返回 dict 或 None"""
    try:
        symbol = stock['symbol']
        kdata = get_klines(symbol)
        if not kdata or len(kdata) < 200:
            return None
        close = np.array([float(d['close']) for d in kdata])
        high = np.array([float(d['high']) for d in kdata])
        low = np.array([float(d['low']) for d in kdata])
        vol = np.array([float(d['volume']) for d in kdata])
        open_p = np.array([float(d['open']) for d in kdata])
        result = scan_stock(close, high, low, vol, open_p)
        if result is None:
            return None
        signals, info = result
        if not signals:
            return None
        # Vibe增强评分（若可用）
        vibe = {'total_score': 0, 'signals': [], 'patterns': []}
        if VIBE_ENABLED:
            try:
                vol_ratio_i = float(vol[-1]) / float(np.mean(vol[-6:-1])) if len(vol) > 6 and float(np.mean(vol[-6:-1])) > 0 else 1.0
                change_pct_i = float((close[-1] / close[-2] - 1) * 100) if len(close) > 2 else 0.0
                vibe = compute_technical_score(close, high, low, open_p, vol_ratio=vol_ratio_i, change_pct=change_pct_i, amount_wan=0)
            except Exception:
                vibe = {'total_score': 0, 'signals': [], 'patterns': []}
        return {
            '代码': stock['code'],
            '名称': stock['name'],
            '价格': stock['price'],
            '涨跌幅': stock['change'],
            '换手率': stock['turnover'],
            '通道间距': info['通道间距'],
            '信号': ' + '.join(signals),
            'Vibe评分': int(vibe.get('total_score', 0)),
            'Vibe标签': '; '.join(vibe.get('signals', [])[:3]),
        }
    except Exception:
        return None


# ====== 主流程 ======
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--periodic', action='store_true', help='周期运行：有动作才输出，无动作静默')
    ap.add_argument('--sell-only', action='store_true', help='仅检查持仓卖出信号，跳过全市场扫描和买入')
    args = ap.parse_args()
    periodic = bool(args.periodic)
    sell_only = bool(args.sell_only)

    log("🚀 V10 V5.1 自动交易系统（Vibe增强 + mx-moni模拟盘）")

    state = _load_state()
    prev_buy_codes = set(state.get('last_buy_codes', []))
    sold_codes = []

    # Step 1: 查询持仓和资金
    log("\n[1/5] 查询账户状态...")
    pos_data = get_positions()
    balance_data = get_balance()

    if not pos_data:
        log("⚠️ 无法获取持仓数据，使用本地状态fallback")
        positions = []
        available_cash = 0
        held_codes = set(state.get('held_codes', []))
    else:
        positions = pos_data.get('posList', [])
        available_cash = pos_data.get('availBalance', 0)
        # 以API为权威来源，反向构建held_codes（只包括count>0的持仓）
        held_codes = set(pos['secCode'] for pos in positions if pos.get('count', 0) > 0)
        state['held_codes'] = sorted(list(held_codes))
        _save_state(state)
        log(f"  总资产: {pos_data.get('totalAssets', 0):.2f} 元")
        log(f"  可用资金: {available_cash:.2f} 元")
        log(f"  持仓数量: {len(positions)} 只")
        for pos in positions:
            log(f"    {pos['secCode']} {pos['secName']} {pos['count']}股 成本{pos.get('costPrice', 0)/100:.2f}")

    # Step 2: 检查持仓卖出信号
    log("\n[2/5] 检查持仓卖出信号...")
    sell_actions = []

    for pos in positions:
        code = pos['secCode']
        name = pos['secName']
        # 模拟盘无T+1限制，用总持仓count而非availCount（availCount可能为0）
        count = pos.get('count', 0) or pos.get('availCount', 0)
        # API返回的价格需要除以10^priceDec
        cost_dec = pos.get('costPriceDec', 2)
        cost_price = pos.get('costPrice', 0) / (10 ** cost_dec)

        # 获取K线数据
        symbol = f"{'sh' if code.startswith('6') else 'sz'}{code}"
        kdata = get_klines(symbol)
        if not kdata or len(kdata) < 170:
            log(f"  ⚠️ {code} {name} K线数据不足，跳过")
            continue

        close = np.array([float(d['close']) for d in kdata])
        high = np.array([float(d['high']) for d in kdata])
        low = np.array([float(d['low']) for d in kdata])
        vol = np.array([float(d['volume']) for d in kdata])
        open_p = np.array([float(d['open']) for d in kdata])

        # 计算最高价：从buy_date之后的K线取最高价，无buy_date则fallback近60日
        buy_date = state.get('buy_dates', {}).get(code)
        if buy_date and kdata:
            post_buy_highs = [float(d['high']) for d in kdata if d.get('day', '') >= buy_date]
            max_price = max(post_buy_highs) if post_buy_highs else np.max(high[-60:]) if len(high) >= 60 else np.max(high)
        else:
            max_price = np.max(high[-60:]) if len(high) >= 60 else np.max(high)
        # 保存max_price_since_buy到状态
        if 'max_price_since_buy' not in state:
            state['max_price_since_buy'] = {}
        prev_max = state['max_price_since_buy'].get(code, 0)
        state['max_price_since_buy'][code] = max(max_price, prev_max)
        max_price = state['max_price_since_buy'][code]

        signals, ma7, ma26, ema120, ema200 = check_sell_signals(
            close, high, low, open_p, vol, cost_price, max_price, buy_date
        )

        if signals:
            log(f"  🔴 {code} {name}: {', '.join(signals)}")
            vibe_sell = {'total_score': 0, 'signals': []}
            if VIBE_ENABLED:
                try:
                    vol_ratio_i = float(vol[-1]) / float(np.mean(vol[-6:-1])) if len(vol) > 6 and float(np.mean(vol[-6:-1])) > 0 else 1.0
                    change_pct_i = float((close[-1] / close[-2] - 1) * 100) if len(close) > 2 else 0.0
                    vibe_sell = compute_technical_score(close, high, low, open_p, vol_ratio=vol_ratio_i, change_pct=change_pct_i, amount_wan=0)
                except Exception:
                    vibe_sell = {'total_score': 0, 'signals': []}
            sell_actions.append({
                '代码': code,
                '名称': name,
                'count': count,
                'signals': signals,
                'Vibe评分': int(vibe_sell.get('total_score', 0)),
                'Vibe标签': '; '.join(vibe_sell.get('signals', [])[:3]),
            })
        else:
            log(f"  ✅ {code} {name}: 无卖出信号")

    # 执行卖出
    if sell_actions:
        log(f"\n  📉 执行卖出 ({len(sell_actions)} 只)...")
        for action in sell_actions:
            # 清仓信号：全仓卖出
            强制清仓 = any(s.startswith('★') for s in action['signals'])
            减仓信号 = '减仓' in action['signals']
            转弱信号 = '转弱' in action['signals'] and not 减仓信号
            
            if 强制清仓:
                if sell_stock(action['代码'], action['count']):
                    sold_codes.append(action['代码'])
            elif 减仓信号:
                # 减仓：卖出一半，确保至少100股
                sell_qty = max(100, int(action['count'] / 2) // 100 * 100)
                if sell_qty >= 100:
                    sell_stock(action['代码'], sell_qty)
            elif 转弱信号:
                # 转弱：只记录，不操作
                log(f"  ⚠️ {action['代码']} 转弱信号，暂不操作")
            
            time.sleep(0.5)

    # === sell-only 模式：跳过扫描和买入，直接输出 ===
    if sell_only:
        has_action = bool(sell_actions)
        if periodic and not has_action:
            log("无动作，静默退出")
            return
        log("\n" + "=" * 70)
        log("📊 V10 持仓卖出检查报告")
        log("=" * 70)
        if sell_actions:
            log(f"\n📉 卖出操作 ({len(sell_actions)} 只):")
            for a in sell_actions:
                log(f"  {a['代码']} {a['名称']} {a['count']}股 → {', '.join(a['signals'])}")
        else:
            log("\n✅ 所有持仓无卖出信号")
        log("\n✅ 卖出检查完成")
        return

    # Step 3: 获取股票列表（周期模式复用缓存）
    log("\n[3/5] 获取全市场股票列表...")
    stocks_cache_path = '/tmp/v10_stocks_cache.json'
    stocks = []
    if periodic:
        try:
            if os.path.exists(stocks_cache_path):
                with open(stocks_cache_path, 'r', encoding='utf-8') as f:
                    stocks = json.load(f)
        except Exception:
            stocks = []
    if not stocks:
        stocks = get_stock_list()
        try:
            with open(stocks_cache_path, 'w', encoding='utf-8') as f:
                json.dump(stocks, f, ensure_ascii=False)
        except Exception:
            pass
    log(f"  获取到 {len(stocks)} 只有效股票")

    # Step 4: V10 全市场扫描（周期模式可复用缓存）
    log("\n[4/5] V10 技术指标扫描...")
    results = []
    scan_cache_path = '/tmp/v10_scan_results_cache.json'
    # 缓存超过4小时则强制刷新
    cache_fresh = False
    if os.path.exists(scan_cache_path):
        cache_age_hours = (time.time() - os.path.getmtime(scan_cache_path)) / 3600
        cache_fresh = cache_age_hours < 4
    use_cache = periodic and cache_fresh and not sell_actions
    if use_cache:
        try:
            with open(scan_cache_path, 'r', encoding='utf-8') as f:
                results = json.load(f)
            log(f"  复用缓存信号池: {len(results)} 只")
        except Exception:
            results = []

    if not results:
        total = len(stocks)
        errors = 0
        _scan_done = [0]
        _scan_t0 = time.time()

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(_scan_one, s): s for s in stocks}
            for future in as_completed(futures):
                _scan_done[0] += 1
                if _scan_done[0] % 500 == 0:
                    elapsed = time.time() - _scan_t0
                    log(f"  进度: {_scan_done[0]}/{total} ({_scan_done[0]/total*100:.0f}%) 已找到 {len(results)} 只 | {elapsed:.0f}秒")
                try:
                    r = future.result()
                    if r:
                        results.append(r)
                except Exception:
                    errors += 1

        _scan_elapsed = time.time() - _scan_t0
        log(f"  扫描完成: {total} 只 | 耗时 {_scan_elapsed:.1f}秒 | 命中 {len(results)} 只 | 错误 {errors} 只")
        try:
            with open(scan_cache_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False)
        except Exception:
            pass
    
    # Step 5: 自动买入
    log("\n[5/5] 执行买入信号...")
    
    # 排序：强庄买优先
    results.sort(key=lambda r: 0 if '强庄买' in r['信号'] else 1)
    
    # 排除已持仓、刚卖出、以及周期模式的历史已买
    held_codes = held_codes - set(sold_codes)
    buy_candidates = [r for r in results if r['代码'] not in held_codes and r['代码'] not in prev_buy_codes]
    
    # 按信号层级排序：强庄买 > 基础买 > 加仓 > 激进
    def signal_priority(r):
        if '强庄买' in r['信号']: return 0
        if '基础买' in r['信号']: return 1
        if '加仓' in r['信号']: return 2
        if '激进' in r['信号']: return 3
        return 4
    buy_candidates.sort(key=signal_priority)
    
    strong_buy = [r for r in buy_candidates if '强庄买' in r['信号'] or '基础买' in r['信号']]
    other_buy = [r for r in buy_candidates if '加仓' in r['信号'] or '激进' in r['信号']]
    
    log(f"  强庄买/基础买: {len(strong_buy)} 只, 加仓/激进: {len(other_buy)} 只")
    log(f"  当前持仓: {len(held_codes)} 只 (已排除)")
    
    # 计算可买入数量
    buy_slots = MAX_POSITIONS - len(held_codes) + len(sold_codes)
    new_bought_codes = []
    if buy_slots <= 0:
        log(f"  ⚠️ 持仓已满 ({MAX_POSITIONS}只)，跳过买入")
    else:
        # 刷新可用资金
        pos_data2 = get_positions()
        if pos_data2:
            available_cash = pos_data2.get('availBalance', 0)
        log(f"  可用资金: {available_cash:.2f} 元")
        
        buy_amount = available_cash * POSITION_RATIO
        log(f"  每只投入: {buy_amount:.0f} 元")
        
        bought_count = 0
        # 先买强庄买/基础买
        for r in strong_buy:
            if bought_count >= buy_slots:
                break
            buy_amount = available_cash * POSITION_RATIO  # 每次循环重新计算
            if buy_amount < 100:
                log(f"  ⚠️ 可用资金不足，停止买入")
                break
            
            code = r['代码']
            price = r['价格']
            quantity = int(buy_amount / price / 100) * 100
            if quantity < 100:
                log(f"  ⚠️ {code} 价格{price}太高，100股需{price*100:.0f}元，跳过")
                continue
            
            if buy_stock(code, quantity):
                bought_count += 1
                held_codes.add(code)
                new_bought_codes.append(code)
                available_cash -= quantity * price
                # 记录买入日期
                if 'buy_dates' not in state:
                    state['buy_dates'] = {}
                state['buy_dates'][code] = time.strftime('%Y-%m-%d')
            time.sleep(0.5)

        # 再买加仓/激进（如果有剩余仓位）
        for r in other_buy:
            if bought_count >= buy_slots:
                break
            buy_amount = available_cash * POSITION_RATIO  # 每次循环重新计算
            if buy_amount < 100:
                break

            code = r['代码']
            price = r['价格']
            quantity = int(buy_amount / price / 100) * 100
            if quantity < 100:
                continue

            if buy_stock(code, quantity):
                bought_count += 1
                held_codes.add(code)
                new_bought_codes.append(code)
                available_cash -= quantity * price
                if 'buy_dates' not in state:
                    state['buy_dates'] = {}
                state['buy_dates'][code] = time.strftime('%Y-%m-%d')
            time.sleep(0.5)

    # 更新状态（周期模式）
    state['held_codes'] = sorted(list(held_codes))
    state['last_buy_codes'] = sorted(list(prev_buy_codes | set(new_bought_codes)))
    # 清理已卖出股票的buy_dates和max_price_since_buy
    for sc in sold_codes:
        state.get('buy_dates', {}).pop(sc, None)
        state.get('max_price_since_buy', {}).pop(sc, None)
    _save_state(state)

    # 输出报告（周期模式下无动作可静默）
    has_action = bool(sell_actions or new_bought_codes)
    if periodic and not has_action:
        log("无动作，静默退出")
        return
    
    log("\n" + "=" * 70)
    log("📊 V10+Vibe 自动交易报告")
    log("=" * 70)

    if sell_actions:
        log(f"\n📉 卖出操作 ({len(sell_actions)} 只):")
        for a in sell_actions:
            log(f"  {a['代码']} {a['名称']} {a['count']}股 → {', '.join(a['signals'])}")

    if results:
        # 分离V4精选和V3信号
        v4精选 = [r for r in results if '★V4精选★' in r['信号']]
        v3信号 = [r for r in results if '★V4精选★' not in r['信号']]

        if v4精选:
            log(f"\n{'★'*50}")
            log(f"🏆 V4 精选信号（最高确定性，所有条件同时满足）")
            log(f"{'★'*50}")
            for r in v4精选:
                log(f"  🌟 {r['代码']} {r['名称']} | ¥{r['价格']:.2f} {r['涨跌幅']:+.1f}% | 换手{r['换手率']:.1f}% | 通道{r['通道间距']:.4f} | Vibe {r.get('Vibe评分',0):+d}")

        if v3信号:
            log(f"\n📈 V3 选股信号 ({len(v3信号)} 只，按Vibe评分排序):")
            v3_sorted = sorted(v3信号, key=lambda r: (-r.get('Vibe评分',0), r['名称']))
            for r in v3_sorted[:20]:
                emoji = "🔴" if "强庄买" in r['信号'] else "🟡"
                vibe_tag = f" | Vibe {r.get('Vibe评分',0):+d} {r.get('Vibe标签','')}".rstrip()
                log(f"  {emoji} {r['代码']} {r['名称']} | ¥{r['价格']:.2f} {r['涨跌幅']:+.1f}% | 换手{r['换手率']:.1f}% | 通道{r['通道间距']:.4f} | {r['信号']}{vibe_tag}")
    else:
        log("\n📭 今日无符合条件的信号")

    # 保存结果
    if results:
        with open('/tmp/v10_scan_result.csv', 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        log(f"\n结果已保存: /tmp/v10_scan_result.csv")

    # 生成交易摘要（供外部读取）
    trade_summary = {
        'sell_count': len(sell_actions),
        'sell_codes': [a['代码'] for a in sell_actions],
        'buy_count': len(new_bought_codes),
        'hold_count': len(held_codes),
        'signal_count': len(results),
        'top_signals': [{'code': r['代码'], 'name': r['名称'], 'signal': r['信号'], 'vibe': r.get('Vibe评分',0)} for r in results[:8]],
    }
    try:
        with open('/tmp/v10_trade_summary.json', 'w', encoding='utf-8') as f:
            json.dump(trade_summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    log("\n✅ 自动交易流程完成")

if __name__ == '__main__':
    main()
