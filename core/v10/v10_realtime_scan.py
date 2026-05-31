#!/usr/bin/env python3
"""
V10 盘中实时全扫描
iFinD实时行情首选+腾讯备用，分钟K线盘中确认，重跑V10全量判断。
每30分钟执行一次，捕捉盘中突发信号。

流程：
1. iFinD批量拉全市场实时行情（~5秒）+ 腾讯备用
2. 预过滤：去ST/停牌/跌停，保留有信号可能的票
3. 10线程并行拉K线（~40秒）
4. 追加"今日虚拟K线"到历史数据末尾
5. 跑V10 scan_stock判断
6. 输出信号 + 保存观察池
"""

import json
import time
import urllib.request
import ssl
import numpy as np
import sys
import os
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# 集合竞价时段(9:00-9:25)跳过，等9:30开盘有真实数据再跑
now = datetime.now()
if now.hour == 9 and now.minute < 30:
    print(f"⏳ 集合竞价中({now.strftime('%H:%M')})，跳过扫描，等9:30开盘")
    sys.exit(0)

# 14:45之后停止扫描，保留尾盘时段最后两轮（14:30/14:45）为尾盘链路更新watchlist
if now.hour > 14 or (now.hour == 14 and now.minute >= 45):
    print(f"⏳ 14:45后跳过扫描，保留尾盘时段数据")
    sys.exit(0)

sys.path.insert(0, '/Users/southzhang/.hermes/workspace')
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from v10_core import ema_fast, hhv_fast, llv_fast, barslast_fast
from tech_analysis import vibe_score as _vibe_score_fn
from sector_analysis import get_sector_ranking, analyze_sector_rotation, get_sector_summary, get_sector_score

# iFinD HTTP API (分钟K线 + 基本面)
IFIND_BASE_URL = "https://quantapi.51ifind.com/api/v1"
IFIND_REFRESH_TOKEN = os.environ.get("IFIND_REFRESH_TOKEN", "")
# 备用：从.env文件读取
if not IFIND_REFRESH_TOKEN:
    try:
        _env_path = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(_env_path):
            with open(_env_path) as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line.startswith("IFIND_REFRESH_TOKEN="):
                        IFIND_REFRESH_TOKEN = _line.split("=", 1)[1]
                        break
    except Exception:
        pass
IFIND_ACCESS_TOKEN = None
IFIND_TOKEN_EXPIRY = 0
_token_lock = threading.Lock()

# iFinD API 需要自定义 SSL context（证书问题）
_ifind_ctx = ssl.create_default_context()
_ifind_ctx.check_hostname = False
_ifind_ctx.verify_mode = ssl.CERT_NONE

# ====== V10 参数（与v10_scan_strict.py一致）======
参数_放量 = 1.5
参数_强庄 = 3
参数_通道宽度 = 0.015


def log(msg):
    print(msg, flush=True)


# ====== iFinD Token管理 ======
def _get_ifind_token():
    """获取iFinD access_token（自动刷新）"""
    global IFIND_ACCESS_TOKEN, IFIND_TOKEN_EXPIRY
    with _token_lock:
        if IFIND_ACCESS_TOKEN and time.time() < IFIND_TOKEN_EXPIRY - 300:
            return IFIND_ACCESS_TOKEN
        if not IFIND_REFRESH_TOKEN:
            return None
        try:
            resp = requests.post(
                url=f"{IFIND_BASE_URL}/get_access_token",
                headers={"Content-Type": "application/json", "refresh_token": IFIND_REFRESH_TOKEN},
                timeout=10
            )
            data = json.loads(resp.content)
            if data.get('data', {}).get('access_token'):
                IFIND_ACCESS_TOKEN = data['data']['access_token']
                IFIND_TOKEN_EXPIRY = time.time() + 72000  # 20小时
                return IFIND_ACCESS_TOKEN
        except Exception as e:
            log(f"  ⚠️ iFinD token刷新失败: {e}")
        return None


def _ifind_post(endpoint, params, timeout=30):
    """iFinD API通用POST"""
    token = _get_ifind_token()
    if not token:
        log(f"  ⚠️ iFinD token不可用，跳过{endpoint}")
        return None
    try:
        resp = requests.post(
            url=f"{IFIND_BASE_URL}/{endpoint}",
            json=params,
            headers={"Content-Type": "application/json", "access_token": token},
            timeout=timeout
        )
        return json.loads(resp.content)
    except Exception:
        return None


# ====== iFinD 分钟K线 ======
def fetch_minute_klines_today(code):
    """
    获取今日分钟K线（iFinD HTTP API）
    code: 纯数字代码，如 "600756"
    返回: dict with open/high/low/close/volume arrays, or None
    """
    # 转换代码格式: 600756 → 600756.SH
    suffix = ".SH" if code.startswith('6') else ".SZ"
    ifind_code = f"{code}{suffix}"

    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    start_time = f"{date_str} 09:30:00"
    end_time = f"{date_str} {now.strftime('%H:%M:%S')}"

    data = _ifind_post("high_frequency", {
        "codes": ifind_code,
        "indicators": "open,high,low,close,volume,amount",
        "starttime": start_time,
        "endtime": end_time
    }, timeout=15)

    if not data or 'tables' not in data or not data.get('tables'):
        log(f"  ⚠️ iFinD分钟K线无数据: {code}")
        return None

    try:
        table = data['tables'][0]
        inner = table.get('table', table)

        opens = inner.get('open', [])
        highs = inner.get('high', [])
        lows = inner.get('low', [])
        closes = inner.get('close', [])
        volumes = inner.get('volume', [])

        if not closes or len(closes) < 5:
            return None

        return {
            'open': np.array(opens, dtype=float),
            'high': np.array(highs, dtype=float),
            'low': np.array(lows, dtype=float),
            'close': np.array(closes, dtype=float),
            'volume': np.array(volumes, dtype=float),
            'count': len(closes),
        }
    except Exception:
        return None


# ====== 盘中指标计算 ======
def calc_intraday_indicators(minute_data):
    """
    基于分钟K线计算盘中指标
    返回: dict with VWAP, buy_ratio, momentum_5m, vol_concentration
    """
    if minute_data is None or minute_data['count'] < 5:
        return None

    close = minute_data['close']
    high = minute_data['high']
    low = minute_data['low']
    volume = minute_data['volume']
    n = len(close)

    # 1. VWAP (成交量加权平均价)
    typical_price = (high + low + close) / 3
    cum_tpv = np.cumsum(typical_price * volume)
    cum_vol = np.cumsum(volume)
    vwap = cum_tpv[-1] / cum_vol[-1] if cum_vol[-1] > 0 else close[-1]

    # 2. 买入量占比（阳线分钟的成交量 / 总成交量）
    open_arr = minute_data['open']
    bullish_mask = close > open_arr
    buy_volume = np.sum(volume[bullish_mask]) if np.any(bullish_mask) else 0
    total_volume = np.sum(volume)
    buy_ratio = buy_volume / total_volume if total_volume > 0 else 0.5

    # 3. 近5分钟动量（最近5根K线的涨跌幅）
    lookback = min(5, n)
    momentum_5m = (close[-1] - close[-lookback]) / close[-lookback] * 100 if close[-lookback] > 0 else 0

    # 4. 量能集中度（后半段成交量 / 前半段成交量）
    mid = n // 2
    if mid > 0:
        vol_first_half = np.sum(volume[:mid])
        vol_second_half = np.sum(volume[mid:])
        vol_concentration = vol_second_half / vol_first_half if vol_first_half > 0 else 1.0
    else:
        vol_concentration = 1.0

    # 5. 尾盘异动（最近15分钟 vs 全天均量）
    tail_lookback = min(15, n)
    if n > tail_lookback:
        tail_avg_vol = np.mean(volume[-tail_lookback:])
        full_avg_vol = np.mean(volume)
        tail_vol_ratio = tail_avg_vol / full_avg_vol if full_avg_vol > 0 else 1.0
    else:
        tail_vol_ratio = 1.0

    # 6. 价格位置（当前价在今日高低点中的位置）
    day_high = np.max(high)
    day_low = np.min(low)
    price_position = (close[-1] - day_low) / (day_high - day_low) if day_high > day_low else 0.5

    return {
        'vwap': round(float(vwap), 3),
        'buy_ratio': round(float(buy_ratio), 3),
        'momentum_5m': round(float(momentum_5m), 3),
        'vol_concentration': round(float(vol_concentration), 3),
        'tail_vol_ratio': round(float(tail_vol_ratio), 3),
        'price_position': round(float(price_position), 3),
        'current_price': round(float(close[-1]), 3),
    }


def intraday_confirmation(v10_result, intraday):
    """
    盘中确认：基于分钟K线指标增强/验证V10信号
    返回: (confirmed_signal, confidence_boost, notes)
    """
    if intraday is None:
        return v10_result, 0, "无分钟数据"

    signal = v10_result.get('signal', '')
    notes = []
    confidence = 0

    # 1. 价格在VWAP上方 → 买入确认
    if intraday['current_price'] > intraday['vwap']:
        notes.append("价格>VWAP✅")
        confidence += 1
    else:
        notes.append("价格<VWAP⚠️")
        confidence -= 1

    # 2. 买入量占比>55% → 买盘主导
    if intraday['buy_ratio'] > 0.55:
        notes.append(f"买盘主导{intraday['buy_ratio']:.0%}✅")
        confidence += 1
    elif intraday['buy_ratio'] < 0.45:
        notes.append(f"卖盘主导{intraday['buy_ratio']:.0%}⚠️")
        confidence -= 1

    # 3. 近5分钟动量>0 → 短期上涨
    if intraday['momentum_5m'] > 0.1:
        notes.append(f"5分钟动量+{intraday['momentum_5m']:.2f}%✅")
        confidence += 1
    elif intraday['momentum_5m'] < -0.1:
        notes.append(f"5分钟动量{intraday['momentum_5m']:.2f}%⚠️")
        confidence -= 1

    # 4. 量能集中度>1.2 → 后半段放量（资金进场）
    if intraday['vol_concentration'] > 1.2:
        notes.append("后半段放量✅")
        confidence += 1

    # 5. 尾盘异动>1.3 → 尾盘有资金
    if intraday['tail_vol_ratio'] > 1.3:
        notes.append(f"尾盘异动{intraday['tail_vol_ratio']:.1f}x✅")
        confidence += 1

    # 6. 价格位置60-80% → 强势但未过热
    if 0.6 <= intraday['price_position'] <= 0.8:
        notes.append("强势未过热✅")
        confidence += 1
    elif intraday['price_position'] > 0.9:
        notes.append("接近高点⚠️")
        confidence -= 1

    # 综合判断
    intraday_ok = confidence >= 2  # 至少2个正面确认

    return {
        **v10_result,
        'intraday': intraday,
        'intraday_notes': notes,
        'intraday_confidence': confidence,
        'intraday_ok': intraday_ok,
    }, confidence, "; ".join(notes)




# ====== Step 1: 全市场实时行情 ======

def _parse_tencent_realtime(raw):
    """解析腾讯行情原始文本"""
    result = []
    for line in raw.strip().split(';'):
        if '=' not in line or '~' not in line:
            continue
        parts = line.split('=')[1].strip('"').split('~')
        if len(parts) < 40:
            continue
        code = parts[2]
        name = parts[1]
        price = float(parts[3]) if parts[3] else 0
        yclose = float(parts[4]) if parts[4] else 0
        open_p = float(parts[5]) if parts[5] else 0
        high = float(parts[33]) if parts[33] else 0
        low = float(parts[34]) if parts[34] else 0
        change = float(parts[32]) if parts[32] else 0
        volume = float(parts[6]) if parts[6] else 0
        amount = float(parts[37]) if parts[37] else 0
        result.append({
            'code': code, 'name': name,
            'symbol': f"{'sh' if code.startswith('6') else 'sz'}{code}",
            'price': price, 'yclose': yclose, 'open': open_p,
            'high': high, 'low': low, 'change': change,
            'volume': volume * 100, 'amount': amount,
        })
    return result


def _filter_stocks(stocks):
    """统一过滤：去ST/停牌/跌停/低价/科创/无成交"""
    result = []
    for s in stocks:
        if s['price'] <= 0:
            continue
        if s.get('yclose', 0) <= 0:
            change = s.get('change', 0)
            if change != -100:
                s['yclose'] = s['price'] / (1 + change / 100)
            else:
                s['yclose'] = s['price']
        # ST过滤：名称包含ST，或涨跌幅限制为5%（ST特征）
        name = s.get('name', '')
        if 'ST' in name or '退' in name or name.startswith('N'):
            continue
        # iFinD不返回名称时，通过涨跌幅限制间接判断ST（ST股涨跌±5%）
        if name == s.get('code', '') and abs(s['change']) > 9.5 and s['change'] != 0:
            # 非ST股涨跌停是10%，如果只涨了5%左右且是涨跌停，可能是ST
            pass  # 这个判断不准确，跳过
        if s['change'] < -9.5:
            continue
        if s['volume'] <= 0:
            continue
        if s['change'] < -3:
            continue
        if s['amount'] < 500:
            continue
        if s['price'] < 3:
            continue
        if s['code'].startswith('688'):
            continue
        result.append(s)
    return result


def prefilter_stocks(stocks):
    """V10预过滤：用问财接口智能筛选，减少K线请求量
    目标：从4290只筛到~500-1000只，K线扫描时间大幅缩短
    
    优先使用问财接口（更精准），失败时降级为本地过滤
    """
    # ====== 首选：问财智能选股 ======
    token = _get_ifind_token()
    if token:
        try:
            t0 = time.time()
            # 问财查询：涨幅0.5%-9.8% + 成交额>1.5亿 + 换手率>2% + 股价5-150 + 非ST
            query = "涨幅0.5%到9.8% 成交额大于1.5亿 换手率大于2% 股价5元到150元 非ST 非北交所"
            data = _ifind_post("smart_stock_picking", {
                "searchstring": query,
                "searchtype": "stock"
            }, timeout=30)
            
            if data and data.get('errorcode') == 0 and data.get('tables'):
                table = data['tables'][0].get('table', {})
                codes_raw = table.get('股票代码', [])
                names_raw = table.get('股票简称', [])
                
                # 提取纯数字代码
                wc_codes = set()
                for c in codes_raw:
                    code = str(c).split('.')[0]
                    if code and code.isdigit():
                        wc_codes.add(code)
                
                if wc_codes:
                    # 用问财结果过滤原始列表
                    result = [s for s in stocks if s['code'] in wc_codes]
                    t1 = time.time()
                    log(f"  ✅ 问财预过滤: {len(stocks)}只 → {len(result)}只 ({t1-t0:.2f}秒)")
                    return result
        except Exception as e:
            log(f"  ⚠️ 问财接口异常: {e}，降级为本地过滤")
    
    # ====== 降级：本地简单过滤（与问财条件一致）======
    result = []
    for s in stocks:
        change = s.get('change', 0)
        amount = s.get('amount', 0)
        price = s.get('price', 0)
        if change < 0.5 or change > 9.8:
            continue
        if amount < 15000:
            continue
        if price < 5 or price > 150:
            continue
        if 'ST' in s.get('name', ''):
            continue
        if s.get('code', '').startswith('688'):
            continue
        result.append(s)
    log(f"  📡 本地预过滤: {len(stocks)}只 → {len(result)}只")
    return result


def _safe_float(val, default=0):
    """安全提取数值（处理iFinD返回的列表/标量混合格式）"""
    if isinstance(val, list):
        val = val[0] if val else default
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def fetch_all_realtime():
    """全市场A股实时行情（腾讯首选，快速免费无限制）"""
    t_start = time.time()
    result = []
    tc_codes = []
    for i in range(600000, 606000):
        tc_codes.append(f"sh{i:06d}")
    for i in range(1, 4000):
        tc_codes.append(f"sz{i:06d}")
    for i in range(300000, 310000):
        tc_codes.append(f"sz{i:06d}")
    # 688科创板不添加（用户无权限）

    batch_size = 80
    for i in range(0, len(tc_codes), batch_size):
        batch = tc_codes[i:i+batch_size]
        qs = ",".join(batch)
        url = f"https://qt.gtimg.cn/q={qs}"
        try:
            resp = urllib.request.urlopen(url, timeout=10)
            raw = resp.read().decode('gbk', errors='ignore')
            result.extend(_parse_tencent_realtime(raw))
        except Exception as e:
            if i % 2000 == 0:
                log(f"  ⚠️ 腾讯批次异常: {e}")
        if i % 2000 == 0 and i > 0:
            log(f"  行情进度: {i}/{len(tc_codes)} 已获取{len(result)}只")
    t_end = time.time()
    result = _filter_stocks(result)
    log(f"  ✅ 腾讯获取{len(result)}只有效股票 ({t_end-t_start:.1f}秒)")
    if len(result) < 100:
        log(f"⚠️ 警告: 仅获取{len(result)}只股票（正常应>3000），API可能故障")
    return result


# ====== Step 1.5: iFinD精确行情（补充指标）======
def fetch_ifind_detailed(stocks):
    """用iFinD获取预过滤股票的PB等精确行情
    iFinD实时行情仅支持: open/high/low/latest/yclose/changeRatio/volume/amount/pb
    其他字段(pe_ttm/turnoverRate/volumeRatio)返回null，暂不获取
    月度消耗: ~800次API调用（1554只÷500只/批×3次/天×22天）
    """
    token = _get_ifind_token()
    if not token:
        log("  ⚠️ iFinD token不可用，跳过精确行情")
        return stocks
    
    t0 = time.time()
    codes = [f"{s['code']}.{'SH' if s['code'].startswith('6') else 'SZ'}" for s in stocks]
    
    detailed = {}
    batch_size = 500
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        codes_str = ",".join(batch)
        data = _ifind_post("real_time_quotation", {
            "codes": codes_str,
            "indicators": "open,high,low,latest,yclose,changeRatio,volume,amount,pb"
        }, timeout=30)
        if data and 'tables' in data and data['tables']:
            for table in data['tables']:
                try:
                    inner = table.get('table', table)
                    thscode = table.get('thscode', '')
                    if isinstance(thscode, list):
                        thscode = thscode[0] if thscode else ''
                    code = str(thscode).split('.')[0] if '.' in str(thscode) else ''
                    if not code:
                        continue
                    detailed[code] = {
                        'pb': _safe_float(inner.get('pb')),
                    }
                except Exception:
                    continue
    
    # 合并精确数据到原始股票列表
    for s in stocks:
        if s['code'] in detailed:
            s.update(detailed[s['code']])
    
    t1 = time.time()
    if detailed:
        log(f"  ✅ iFinD精确行情: {len(detailed)}只 (PB数据) ({t1-t0:.2f}秒)")
    else:
        log(f"  ⚠️ iFinD精确行情: 无数据")
    return stocks


def fetch_sector_ranking():
    """获取板块涨幅排名（使用板块分析模块）
    返回: [{'name': 板块名, 'change': 涨幅, 'leaders': [领涨股列表]}, ...]
    """
    t0 = time.time()
    try:
        # 使用板块分析模块获取板块排名
        sector_data = get_sector_ranking()
        if sector_data:
            result = []
            # 处理行业板块
            for s in sector_data.get('industry', [])[:20]:
                result.append({
                    'name': s.get('name', ''),
                    'change': s.get('change', 0),
                    'leaders': []
                })
            t1 = time.time()
            log(f"  📊 板块排名: {len(result)}个板块 ({t1-t0:.2f}秒)")
            return result
    except Exception as e:
        log(f"  ⚠️ 板块排名查询异常: {e}")
    return []


# ====== 信号股深度分析（iFinD历史K线）======
def fetch_signal_deep_analysis(signal_stocks):
    """对V10信号股获取iFinD完整历史K线，做深度技术验证
    消耗: ~2500条/次（10只×250天），月度~16.5万条/100万配额=16.5%
    """
    token = _get_ifind_token()
    if not token:
        log("  ⚠️ iFinD token不可用，跳过深度分析")
        return signal_stocks
    
    if not signal_stocks:
        return signal_stocks
    
    t0 = time.time()
    
    for stock in signal_stocks:
        code = stock['code']
        suffix = ".SH" if code.startswith('6') else ".SZ"
        ifind_code = f"{code}{suffix}"
        
        try:
            data = _ifind_post("cmd_history_quotation", {
                "codes": ifind_code,
                "indicators": "open,high,low,close,volume,amount,changeRatio",
                "startdate": "2025-06-01",  # 约250个交易日
                "enddate": datetime.now().strftime('%Y-%m-%d'),
                "functionpara": {"Fill": "Blank"}
            }, timeout=15)
            
            if not data or 'tables' not in data or not data.get('tables'):
                continue
            
            table = data['tables'][0]
            inner = table.get('table', table)
            dates = inner.get('time', [])
            closes = inner.get('close', [])
            highs = inner.get('high', [])
            lows = inner.get('low', [])
            volumes = inner.get('volume', [])
            
            if not closes or len(closes) < 100:
                continue
            
            import numpy as np
            close_arr = np.array(closes, dtype=float)
            high_arr = np.array(highs, dtype=float)
            low_arr = np.array(lows, dtype=float)
            vol_arr = np.array(volumes, dtype=float)
            n = len(close_arr)
            
            # === 深度技术指标 ===
            
            # 1. 长期趋势（EMA120/200）
            def ema(data, period):
                alpha = 2.0 / (period + 1)
                result = np.empty_like(data, dtype=float)
                result[0] = data[0]
                for i in range(1, len(data)):
                    result[i] = data[i] * alpha + result[i-1] * (1 - alpha)
                return result
            
            ema120 = ema(close_arr, 120)
            ema200 = ema(close_arr, 200)
            
            # 2. 长期高点（120日最高）
            high_120 = float(np.max(high_arr[-120:])) if n >= 120 else float(np.max(high_arr))
            low_120 = float(np.min(low_arr[-120:])) if n >= 120 else float(np.min(low_arr))
            
            # 3. 成交量趋势（近20日均量 vs 近60日均量）
            vol_20 = float(np.mean(vol_arr[-20:])) if n >= 20 else float(np.mean(vol_arr))
            vol_60 = float(np.mean(vol_arr[-60:])) if n >= 60 else float(np.mean(vol_arr))
            vol_trend = vol_20 / vol_60 if vol_60 > 0 else 1.0
            
            # 4. 价格位置（当前价在120日高低点中的位置）
            current_price = close_arr[-1]
            price_pos = (current_price - low_120) / (high_120 - low_120) if high_120 > low_120 else 0.5
            
            # 5. 长期支撑位（120日最低+5%）
            support_120 = low_120 * 1.05
            
            # 6. 突破确认（当前价>120日高点）
            breakout = current_price > high_120 * 0.98
            
            # 保存深度分析结果
            stock['deep_analysis'] = {
                'ema120': round(float(ema120[-1]), 3),
                'ema200': round(float(ema200[-1]), 3),
                'high_120d': round(high_120, 3),
                'low_120d': round(low_120, 3),
                'vol_trend': round(vol_trend, 3),
                'price_position': round(price_pos, 3),
                'support_120d': round(support_120, 3),
                'breakout': breakout,
                'long_trend': '多头' if ema120[-1] > ema200[-1] else '空头',
            }
            
            # 深度评分（0-5分）
            deep_score = 0
            if ema120[-1] > ema200[-1]:
                deep_score += 1  # 长期多头
            if vol_trend > 1.2:
                deep_score += 1  # 放量趋势
            if price_pos > 0.5:
                deep_score += 1  # 价格位置强
            if breakout:
                deep_score += 1  # 突破确认
            if current_price > ema120[-1]:
                deep_score += 1  # 站上EMA120
            
            stock['deep_score'] = deep_score
            stock['deep_tag'] = f"{'⭐' * deep_score} 深度评分{deep_score}/5"
            
        except Exception:
            continue
    
    t1 = time.time()
    log(f"  ✅ 信号股深度分析: {len(signal_stocks)}只 ({t1-t0:.2f}秒)")
    return signal_stocks


# ====== 策略回测验证 ======
def backtest_v10_strategy(code, days=500):
    """用iFinD历史数据回测V10策略
    返回: 回测结果（胜率/盈亏比/最大回撤等）
    """
    token = _get_ifind_token()
    if not token:
        return None
    
    suffix = ".SH" if code.startswith('6') else ".SZ"
    ifind_code = f"{code}{suffix}"
    
    try:
        # 获取历史K线
        data = _ifind_post("cmd_history_quotation", {
            "codes": ifind_code,
            "indicators": "open,high,low,close,volume",
            "startdate": (datetime.now() - __import__('datetime').timedelta(days=days)).strftime('%Y-%m-%d'),
            "enddate": datetime.now().strftime('%Y-%m-%d'),
            "functionpara": {"Fill": "Blank"}
        }, timeout=20)
        
        if not data or 'tables' not in data or not data.get('tables'):
            return None
        
        table = data['tables'][0]
        inner = table.get('table', table)
        closes = inner.get('close', [])
        highs = inner.get('high', [])
        lows = inner.get('low', [])
        volumes = inner.get('volume', [])
        opens = inner.get('open', [])
        
        if not closes or len(closes) < 200:
            return None
        
        import numpy as np
        close_arr = np.array(closes, dtype=float)
        high_arr = np.array(highs, dtype=float)
        low_arr = np.array(lows, dtype=float)
        vol_arr = np.array(volumes, dtype=float)
        open_arr = np.array(opens, dtype=float)
        n = len(close_arr)
        
        # 模拟V10策略回测
        def ema(data, period):
            alpha = 2.0 / (period + 1)
            result = np.empty_like(data, dtype=float)
            result[0] = data[0]
            for i in range(1, len(data)):
                result[i] = data[i] * alpha + result[i-1] * (1 - alpha)
            return result
        
        ema7 = ema(close_arr, 7)
        ema20 = ema(close_arr, 20)
        ema120 = ema(close_arr, 120)
        ema200 = ema(close_arr, 200)
        
        # V5.1: MACD(20,80,9) for death cross exit
        ema20_macd = ema(close_arr, 20)
        ema80 = ema(close_arr, 80)
        dif = ema20_macd - ema80
        dea = ema(dif, 9)
        
        # VOL_MA5
        kernel = np.ones(5) / 5
        vol_ma5 = np.convolve(vol_arr, kernel, mode='full')[:n]
        
        # 模拟交易
        trades = []
        position = None
        stop_loss_pct = -0.06
        take_profit_pct = 0.10
        
        for i in range(200, n):
            # 买入条件
            if position is None:
                if (close_arr[i] > ema120[i] and close_arr[i] > ema200[i] and
                    ema120[i] > ema200[i] and
                    ema7[i] > ema20[i] and
                    close_arr[i] > open_arr[i] and
                    vol_arr[i] > vol_ma5[i] * 1.5):
                    position = {
                        'buy_price': close_arr[i],
                        'buy_idx': i,
                        'stop_loss': close_arr[i] * (1 + stop_loss_pct),
                    }
            
            # 卖出条件
            elif position is not None:
                pnl = (close_arr[i] - position['buy_price']) / position['buy_price']
                
                # 止损
                if close_arr[i] < position['stop_loss']:
                    trades.append({
                        'buy_price': position['buy_price'],
                        'sell_price': close_arr[i],
                        'pnl': pnl,
                        'hold_days': i - position['buy_idx'],
                        'exit_reason': '止损'
                    })
                    position = None
                # 止盈
                elif pnl >= take_profit_pct:
                    trades.append({
                        'buy_price': position['buy_price'],
                        'sell_price': close_arr[i],
                        'pnl': pnl,
                        'hold_days': i - position['buy_idx'],
                        'exit_reason': '止盈'
                    })
                    position = None
                # 移动止盈（从最高点回撤3%）
                elif ema7[i] < ema20[i]:  # 通道死叉退出
                    trades.append({
                        'buy_price': position['buy_price'],
                        'sell_price': close_arr[i],
                        'pnl': pnl,
                        'hold_days': i - position['buy_idx'],
                        'exit_reason': '通道死叉'
                    })
                    position = None
                # V5.1新增: MACD死叉退出（DIF下穿DEA）
                elif i > 0 and dif[i] < dea[i] and dif[i-1] >= dea[i-1]:
                    trades.append({
                        'buy_price': position['buy_price'],
                        'sell_price': close_arr[i],
                        'pnl': pnl,
                        'hold_days': i - position['buy_idx'],
                        'exit_reason': 'MACD死叉'
                    })
                    position = None
        
        # 统计
        if not trades:
            return None
        
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]
        
        win_rate = len(wins) / len(trades) if trades else 0
        avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
        avg_loss = np.mean([abs(t['pnl']) for t in losses]) if losses else 0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        total_return = np.prod([1 + t['pnl'] for t in trades]) - 1
        
        # 最大回撤
        equity = [1]
        for t in trades:
            equity.append(equity[-1] * (1 + t['pnl']))
        equity = np.array(equity)
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        max_drawdown = float(np.min(drawdown))
        
        return {
            'total_trades': len(trades),
            'win_rate': round(win_rate * 100, 1),
            'avg_win': round(avg_win * 100, 2),
            'avg_loss': round(avg_loss * 100, 2),
            'profit_factor': round(profit_factor, 2),
            'total_return': round(total_return * 100, 2),
            'max_drawdown': round(max_drawdown * 100, 2),
            'avg_hold_days': round(np.mean([t['hold_days'] for t in trades]), 1),
            'trades': trades[-5:],  # 最近5笔交易
        }
        
    except Exception as e:
        return None



# ====== Step 2: K线获取 ======

def fetch_klines(code, count=250):
    """腾讯前复权日K线"""
    secid = f"sh{code}" if code.startswith('6') else f"sz{code}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={secid},day,,,{count},qfq"
    try:
        resp = urllib.request.urlopen(url, timeout=8, context=_ifind_ctx)
        data = json.loads(resp.read())
        sec_data = data.get('data', {}).get(secid, {})
        bars = sec_data.get('qfqday', []) or sec_data.get('day', [])
        if not bars or len(bars) < 200:
            return None
        return {
            'open': np.array([float(b[1]) for b in bars]),
            'close': np.array([float(b[2]) for b in bars]),
            'high': np.array([float(b[3]) for b in bars]),
            'low': np.array([float(b[4]) for b in bars]),
            'volume': np.array([float(b[5]) for b in bars]),
            'dates': [b[0] for b in bars],
        }
    except Exception:
        return None


# ====== Step 3: V10 扫描（带今日虚拟K线）======

def scan_stock_rt(close, high, low, volume, open_price):
    """V10扫描（与v10_scan_strict.py逻辑一致）"""
    n = len(close)
    if n < 200:
        return None

    隧道快 = ema_fast(close, 120)
    隧道慢 = ema_fast(close, 200)
    MA5 = ema_fast(close, 5)
    MA20 = ema_fast(close, 20)
    EMA80 = ema_fast(close, 80)
    DIF = MA20 - EMA80
    DEA = ema_fast(DIF, 9)

    lowest9 = llv_fast(low, 9)
    highest9 = hhv_fast(high, 9)
    diff9 = highest9 - lowest9
    RSV = np.where(diff9 > 0, (close - lowest9) / diff9 * 100, 50.0)
    K = np.empty(n, dtype=float)
    K[0] = RSV[0]
    for i in range(1, n):
        K[i] = K[i-1] * 2/3 + RSV[i] / 3
    QW = ema_fast(K, 3)

    通道间距 = np.where(MA20 > 0, (MA5 - MA20) / MA20, 0.0)
    kernel = np.ones(5) / 5
    VOL_MA5 = np.convolve(volume, kernel, mode='full')[:n]
    VOL_MA5[:4] = 0

    WEIGHT = (2 * close + open_price + high + low) * 100
    WEIGHT_EMA = ema_fast(WEIGHT, 4)
    VAR1 = np.where(WEIGHT_EMA > 0, (WEIGHT / WEIGHT_EMA - 1) * 100, 0.0)
    VAR1_ABS = np.abs(VAR1)
    VAR1_HH20 = hhv_fast(VAR1_ABS, 20)
    STRONG = (VAR1_ABS >= VAR1_HH20 * 0.9999) & (VAR1 > 0)
    barslast_STRONG = barslast_fast(STRONG)

    i = n - 1
    隧道多头 = close[i] > 隧道快[i] and close[i] > 隧道慢[i] and 隧道快[i] > 隧道慢[i]
    双线定式 = MA5[i] > MA20[i] and MA5[i] > MA5[i-1]
    QW上升 = QW[i] > QW[i-1]
    宽度OK = 通道间距[i] > 参数_通道宽度
    阳线 = close[i] > open_price[i]
    放量 = volume[i] > 参数_放量 * VOL_MA5[i] if VOL_MA5[i] > 0 else False
    MACD金叉 = DIF[i] > DEA[i] and DIF[i-1] <= DEA[i-1]

    ST_FIRST = STRONG[i] and barslast_STRONG[i-1] >= 参数_强庄
    强庄信号 = 放量 and 阳线 and ST_FIRST

    基础买 = 隧道多头 and 双线定式 and QW上升 and 宽度OK and 阳线 and 放量
    全买入 = 基础买 and 强庄信号 and MACD金叉
    强庄买 = 基础买 and 强庄信号
    MACD加分 = DIF[i] > DEA[i]

    signals = []
    if 全买入:
        signals.append("全买入")
    elif 强庄买:
        signals.append("强庄买")
    elif 基础买:
        signals.append("基础买")

    # 计算关键价位（供盯盘用）
    ema7 = ema_fast(close, 7)[-1]
    ema20_val = MA20[-1]
    ema120 = 隧道快[-1]
    ema200 = 隧道慢[-1]
    h30 = float(np.max(high[-30:]))
    l30 = float(np.min(low[-30:]))
    stop_loss = max(ema200, l30)

    return {
        'signals': signals,
        'full_buy': 全买入,
        'strong_buy': 强庄买,
        'base_buy': 基础买,
        'key_levels': {
            'ema7': round(float(ema7), 3),
            'ema20': round(float(ema20_val), 3),
            'ema120': round(float(ema120), 3),
            'ema200': round(float(ema200), 3),
            'high_30d': round(h30, 3),
            'low_30d': round(l30, 3),
            'stop_loss': round(stop_loss, 3),
        },
    }


def _scan_one_rt(stock):
    """扫描单只股票（日K线 + 分钟K线混合模式）"""
    code = stock['code']
    kdata = fetch_klines(code)
    if kdata is None:
        return None

    # K线API在盘中已返回今日K线（日期=今天，close=实时价）
    # 直接用，不追加虚拟K线，避免重复
    close_ext = kdata['close']
    high_ext = kdata['high']
    low_ext = kdata['low']
    vol_ext = kdata['volume']
    open_ext = kdata['open']

    result = scan_stock_rt(close_ext, high_ext, low_ext, vol_ext, open_ext)
    if result is None or not result['signals']:
        return None

    # iFinD分钟K线盘中确认
    minute_data = fetch_minute_klines_today(code)
    intraday = calc_intraday_indicators(minute_data)
    confirmed, conf_score, conf_notes = intraday_confirmation(result, intraday)

    # Vibe-Trading技术确认 (SMC + 缠论 + K线形态)
    vibe_result = {'score': 0, 'tags': []}
    try:
        # 取最近30根K线做Vibe分析
        n = len(close_ext)
        _s = max(0, n - 30)
        v_h = high_ext[_s:].copy()
        v_l = low_ext[_s:].copy()
        v_c = close_ext[_s:].copy()
        v_o = open_ext[_s:].copy()
        if len(v_c) >= 10:
            vibe_result = _vibe_score_fn(v_h, v_l, v_c, v_o)
    except Exception as e:
        log(f"  ⚠️ Vibe评分异常({code}): {e}")

    return {
        'code': code,
        'name': stock['name'],
        'signal': ' + '.join(result['signals']),
        'price': stock['price'],
        'change': stock['change'],
        'amount': stock['amount'],
        'key_levels': result['key_levels'],
        'intraday_notes': conf_notes,
        'intraday_confidence': conf_score,
        'intraday_ok': confirmed.get('intraday_ok', False) if confirmed else False,
        'vibe_score': vibe_result.get('score', 0),
        'vibe_tags': vibe_result.get('tags', []),
    }


# ====== 主流程 ======

def main():
    # 交易时间检查 — 非交易时间直接退出
    now = datetime.now()
    h, m = now.hour, now.minute
    t = h * 100 + m
    if not ((915 <= t <= 925) or (930 <= t <= 1130) or (1300 <= t <= 1500)):
        return

    time_str = now.strftime('%H:%M:%S')
    date_str = now.strftime('%Y-%m-%d')

    log(f"{'='*60}")
    log(f"⚡ V10 盘中实时全扫描 {date_str} {time_str}")
    log(f"{'='*60}")

    # [1/4] 全市场实时行情
    log("\n[1/4] 获取全市场实时行情...")
    t0 = time.time()
    stocks = fetch_all_realtime()
    t1 = time.time()
    log(f"  获取到 {len(stocks)} 只有效股票 ({t1-t0:.1f}秒)")

    # [2/5] V10预过滤（问财智能筛选）
    prefiltered = prefilter_stocks(stocks)
    log(f"  预过滤: {len(stocks)}只 → {len(prefiltered)}只 (省{len(stocks)-len(prefiltered)}只)")
    
    # [3/5] iFinD精确行情（补充PE/PB/换手率/量比）
    prefiltered = fetch_ifind_detailed(prefiltered)
    
    # [4/5] 板块排名（用于报告输出）
    sector_leaders = fetch_sector_ranking()
    # sector_codes 不再计算——sector_leaders 已改为 {'name','change','leaders'} 结构，无 'code' 字段
    # 原逻辑期望旧数据结构，这里保留调用（日志有用），sector_codes 后续未被使用
    
    # [5/5] 并行扫描
    log(f"\n[2/4] V10实时扫描（⚡30线程 + iFinD分钟K线确认）...")
    results = []
    errors = 0
    _lock = threading.Lock()
    _counter = [0]
    _t2 = time.time()

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(_scan_one_rt, s): s for s in prefiltered}
        for future in as_completed(futures):
            _counter[0] += 1
            done = _counter[0]
            if done % 500 == 0:
                elapsed = time.time() - _t2
                with _lock:
                    n_found = len(results)
                log(f"  进度: {done}/{len(prefiltered)} ({done/len(prefiltered)*100:.0f}%) 命中{n_found}只 | {elapsed:.0f}秒")
            try:
                r = future.result()
                if r:
                    with _lock:
                        results.append(r)
            except Exception:
                errors += 1

    t3 = time.time()
    log(f"\n[3/4] 扫描完成: {len(prefiltered)}只 | 耗时{t3-t1:.1f}秒 | 命中{len(results)}只 | 错误{errors}只")

    # [4/4] 输出结果
    if results:
        # Vibe排序: 按Vibe得分降序
        results.sort(key=lambda x: x.get('vibe_score', 0), reverse=True)

        # 分类
        full_buy = [r for r in results if '全买入' in r['signal']]
        strong_buy = [r for r in results if '强庄买' in r['signal'] and '全买入' not in r['signal']]
        base_buy = [r for r in results if '基础买' in r['signal'] and '强庄买' not in r['signal'] and '全买入' not in r['signal']]

        log(f"\n{'='*60}")
        log(f"📊 V10 盘中实时信号")
        log(f"{'='*60}")

        if full_buy:
            log(f"\n🔴 全买入 ({len(full_buy)}只):")
            for r in full_buy:
                intra_tag = f" | 盘中{r['intraday_confidence']}分✅" if r.get('intraday_ok') else f" | 盘中{r['intraday_confidence']}分⚠️" if r.get('intraday_notes', '') != '无分钟数据' else ""
                vibe_tag = f" | Vibe:{r.get('vibe_score',0):+d}({' '.join(r.get('vibe_tags',[])[:3])})" if r.get('vibe_tags') else ""
                log(f"  {r['name']}({r['code']}) ¥{r['price']:.2f} {r['change']:+.1f}% | 成交{r['amount']:.0f}万 | {r['signal']}{intra_tag}{vibe_tag}")
                if r.get('intraday_notes', '') != '无分钟数据':
                    log(f"    📊 {r['intraday_notes']}")

        if strong_buy:
            log(f"\n🟠 强庄买 ({len(strong_buy)}只):")
            for r in strong_buy:
                intra_tag = f" | 盘中{r['intraday_confidence']}分✅" if r.get('intraday_ok') else f" | 盘中{r['intraday_confidence']}分⚠️" if r.get('intraday_notes', '') != '无分钟数据' else ""
                vibe_tag = f" | Vibe:{r.get('vibe_score',0):+d}({' '.join(r.get('vibe_tags',[])[:3])})" if r.get('vibe_tags') else ""
                log(f"  {r['name']}({r['code']}) ¥{r['price']:.2f} {r['change']:+.1f}% | 成交{r['amount']:.0f}万 | {r['signal']}{intra_tag}{vibe_tag}")
                if r.get('intraday_notes', '') != '无分钟数据':
                    log(f"    📊 {r['intraday_notes']}")

        if base_buy:
            log(f"\n🟡 基础买 ({len(base_buy)}只):")
            for r in base_buy:
                intra_tag = f" | 盘中{r['intraday_confidence']}分✅" if r.get('intraday_ok') else f" | 盘中{r['intraday_confidence']}分⚠️" if r.get('intraday_notes', '') != '无分钟数据' else ""
                vibe_tag = f" | Vibe:{r.get('vibe_score',0):+d}({' '.join(r.get('vibe_tags',[])[:3])})" if r.get('vibe_tags') else ""
                log(f"  {r['name']}({r['code']}) ¥{r['price']:.2f} {r['change']:+.1f}% | 成交{r['amount']:.0f}万 | {r['signal']}{intra_tag}{vibe_tag}")
                if r.get('intraday_notes', '') != '无分钟数据':
                    log(f"    📊 {r['intraday_notes']}")

        # 保存观察池
        watchlist = []
        for r in results:
            wl_item = {
                'code': r['code'],
                'name': r['name'],
                'signal': r['signal'],
                'price': r['price'],
                'change': f"{r['change']:+.1f}%",
                'key_levels': r['key_levels'],
                'vibe_score': r.get('vibe_score', 0),
                'vibe_tags': r.get('vibe_tags', []),
                'scan_date': date_str,
            }
            if r.get('intraday_notes', '') != '无分钟数据':
                wl_item['intraday_notes'] = r['intraday_notes']
                wl_item['intraday_confidence'] = r['intraday_confidence']
                wl_item['intraday_ok'] = r['intraday_ok']
            watchlist.append(wl_item)

        # [6/5] 信号股深度分析（iFinD历史K线）
        if results:
            log(f"\n[6/5] 信号股深度分析...")
            results = fetch_signal_deep_analysis(results)
        
        # [7/5] 保存观察池
        wl_path = os.path.expanduser('~/.hermes/cache/v10_watchlist.json')
        with open(wl_path, 'w', encoding='utf-8') as f:
            json.dump({
                'scan_time': f"{date_str} {time_str}",
                'count': len(watchlist),
                'stocks': watchlist,
            }, f, ensure_ascii=False, indent=2)
        log(f"\n📋 观察池已更新: {wl_path} ({len(watchlist)}只)")
    else:
        # 没有信号时也要更新观察池（清空），避免盯盘脚本读到过期数据
        wl_path = os.path.expanduser('~/.hermes/cache/v10_watchlist.json')
        with open(wl_path, 'w', encoding='utf-8') as f:
            json.dump({
                'scan_time': f"{date_str} {time_str}",
                'count': 0,
                'stocks': [],
            }, f, ensure_ascii=False, indent=2)
        log(f"\n📭 当前无V10信号（观察池已清空）")

    log(f"\n完成！总耗时: {time.time()-t0:.1f}秒")


if __name__ == '__main__':
    t2 = time.time()
    main()
