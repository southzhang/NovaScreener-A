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
if now.weekday() >= 5:
    print(f"⏳ 周末({now.strftime('%A')})，跳过扫描")
    sys.exit(0)
if now.hour == 9 and now.minute < 30:
    print(f"⏳ 集合竞价中({now.strftime('%H:%M')})，跳过扫描，等9:30开盘")
    sys.exit(0)

# 14:55之后停止扫描，保留尾盘时段数据（14:50那轮仍可捕捉尾盘信号）
if now.hour > 14 or (now.hour == 14 and now.minute >= 55):
    print(f"⏳ 14:55后跳过扫描，保留尾盘时段数据")
    sys.exit(0)

sys.path.insert(0, os.path.expanduser('~/.hermes/workspace'))
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from v10_core import ema_fast, hhv_fast, llv_fast, barslast_fast
from tech_analysis import vibe_score as _vibe_score_fn

# 数据源：纯腾讯API（QMT已禁用 v3.1）
try:
    from quote_adapter import (
        get_full_market_quotes, get_kline, get_batch_klines,
        get_source_name, force_refresh,
        is_qmt_ssh_available, is_qmt_http_available,
    )
    _HAS_QUOTE_ADAPTER = True
except ImportError:
    _HAS_QUOTE_ADAPTER = False

# iFinD HTTP API (分钟K线 + 基本面)
# 统一使用 ifind_http_api.iFinDAPI 管理 token，避免双份token不一致
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

# 统一使用 ifind_http_api.iFinDAPI 实例（自带token缓存+自动刷新+线程安全）
try:
    from ifind_http_api import iFinDAPI
    _ifind_api = iFinDAPI(refresh_token=IFIND_REFRESH_TOKEN)
    _HAS_IFIND = True
except ImportError:
    _ifind_api = None
    _HAS_IFIND = False

# iFinD API 需要自定义 SSL context（证书问题）
_ifind_ctx = ssl.create_default_context()
_ifind_ctx.check_hostname = False
_ifind_ctx.verify_mode = ssl.CERT_NONE

# ====== HTTP连接池（复用TCP连接，减少握手开销）======
# 用于腾讯K线批量获取等高频请求，30线程×200只股票可省5-15秒
import requests as _requests
from requests.adapters import HTTPAdapter
_http_session = _requests.Session()
_http_session.mount('https://', HTTPAdapter(pool_connections=10, pool_maxsize=30))
_http_session.headers.update({'User-Agent': 'Mozilla/5.0'})

# ====== V10 参数（与strategies.py scan_v10_full 对齐）======
参数_放量 = 1.5
参数_强庄 = 3
参数_通道宽度 = 0.008  # 0.8%，与strategies.py一致（旧值0.015过严，漏掉0.8%-1.5%的信号）


def log(msg):
    print(msg, flush=True)


# ====== iFinD Token管理（委托给 ifind_http_api.iFinDAPI）======
def _get_ifind_token():
    """获取iFinD access_token（通过iFinDAPI实例自动管理缓存+刷新）"""
    if not _ifind_api or not IFIND_REFRESH_TOKEN:
        return None
    try:
        if _ifind_api._refresh_access_token():
            return _ifind_api.access_token
    except Exception as e:
        log(f"  ⚠️ iFinD token刷新失败: {e}")
    return None


def _ifind_post(endpoint, params, timeout=30):
    """iFinD API通用POST（委托给iFinDAPI实例，统一token管理）"""
    if not _ifind_api:
        log(f"  ⚠️ iFinD不可用，跳过{endpoint}")
        return None
    try:
        return _ifind_api._post(endpoint, params, timeout=timeout)
    except Exception as e:
        log(f"  ⚠️ iFinD请求失败 {endpoint}: {e}")
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
        "indicators": "open,high,low,close,volume",
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

    # 综合判断（06-10升级：Vibe感知版）
    # Vibe≥+2强 + V10全买入/强庄买 → 强趋势票，盘中确认自动通过
    signal_name = v10_result.get('signal', '')
    vibe_sc = v10_result.get('vibe_score', 0)
    is_strong_trend = vibe_sc >= 2 and signal_name in ('全买入', '强庄买')
    if is_strong_trend:
        # Vibe≥+2强趋势：即使盘中confidence不足也放行
        intraday_ok = True
        if confidence < 2:
            notes.append(f"Vibe≥+2强趋势豁免盘中确认(confidence={confidence})")
    else:
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
    """解析腾讯行情原始文本（只提取V10扫描实际使用的字段）"""
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
        # 涨停价/跌停价：直接从腾讯API读取（parts[47]=涨停价, parts[48]=跌停价），交易所标准计算
        limit_up = float(parts[47]) if len(parts) > 47 and parts[47] else 0
        limit_down = float(parts[48]) if len(parts) > 48 and parts[48] else 0
        open_p = float(parts[5]) if parts[5] else 0
        high = float(parts[33]) if parts[33] else 0
        low = float(parts[34]) if parts[34] else 0
        change = float(parts[32]) if parts[32] else 0
        volume = float(parts[6]) if parts[6] else 0
        amount = float(parts[37]) if parts[37] else 0
        result.append({
            'code': code, 'name': name,
            'price': price, 'yclose': yclose, 'open': open_p,
            'high': high, 'low': low, 'change': change,
            'volume': volume * 100, 'amount': amount,
            'limit_up': limit_up, 'limit_down': limit_down,
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
        if s['amount'] < 500:
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
            # 问财查询：成交额>1.5亿 + 换手率>2% + 股价5-150 + 非ST
            # 涨跌幅条件由_filter_stocks统一处理（排除跌停<-9.5%）
            query = "成交额大于1.5亿 换手率大于2% 股价5元到150元 非ST 非北交所"
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
        if change > 9.8:
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
    """全市场A股实时行情
    优先级：腾讯串行获取(稳定可靠) → 腾讯并发降级(快但易限流) → QMT兜底
    
    2026-06-11修复：腾讯8线程并发在盘中高峰易被限流，返回<100只，
    误触发QMT降级。QMT /full_market基于日K线，非交易时段amount=0，
    经_filter_stocks后只剩6-15只，导致全天扫描数据无效。
    恢复腾讯串行获取（已稳定运行数月），增加重试机制。
    """
    t_start = time.time()
    
    tc_codes = []
    for i in range(600000, 606000):
        tc_codes.append(f"sh{i:06d}")
    for i in range(1, 4000):
        tc_codes.append(f"sz{i:06d}")
    for i in range(300000, 310000):
        tc_codes.append(f"sz{i:06d}")
    # 688科创板不添加（用户无权限）

    batch_size = 80
    result = []
    
    # ====== 腾讯串行获取（稳定可靠，已运行数月） ======
    for i in range(0, len(tc_codes), batch_size):
        batch = tc_codes[i:i+batch_size]
        qs = ",".join(batch)
        url = f"https://qt.gtimg.cn/q={qs}"
        for retry in range(3):  # 最多重试3次
            try:
                resp = urllib.request.urlopen(url, timeout=15)
                raw = resp.read().decode('gbk', errors='ignore')
                result.extend(_parse_tencent_realtime(raw))
                break
            except Exception as e:
                if retry < 2:
                    time.sleep(0.5 * (retry + 1))  # 退避重试
                elif i % 2000 == 0:
                    log(f"  ⚠️ 腾讯批次异常: {e}")
        if i % 2000 == 0 and i > 0:
            log(f"  行情进度: {i}/{len(tc_codes)} 已获取{len(result)}只")
    
    if len(result) > 100:
        result = _filter_stocks(result)
        t_end = time.time()
        log(f"  ✅ 腾讯获取{len(result)}只有效股票 ({t_end-t_start:.1f}秒)")
        return result
    
    # ====== 腾讯并发降级（串行获取不足时尝试） ======
    if len(result) <= 100:
        log(f"  ⚠️ 腾讯串行仅获取{len(result)}只，尝试并发降级...")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        tc_result2 = []
        def _fetch_tc_batch(batch_codes):
            qs = ",".join(batch_codes)
            url = f"https://qt.gtimg.cn/q={qs}"
            try:
                resp = urllib.request.urlopen(url, timeout=10)
                raw = resp.read().decode('gbk', errors='ignore')
                return _parse_tencent_realtime(raw)
            except Exception:
                return []
        
        with ThreadPoolExecutor(max_workers=4) as executor:  # 降到4线程减少限流风险
            futures = []
            for i in range(0, len(tc_codes), batch_size):
                batch = tc_codes[i:i+batch_size]
                futures.append(executor.submit(_fetch_tc_batch, batch))
            for future in as_completed(futures):
                tc_result2.extend(future.result())
        
        if len(tc_result2) > 100:
            tc_result2 = _filter_stocks(tc_result2)
            t_end = time.time()
            log(f"  ✅ 腾讯并发降级获取{len(tc_result2)}只有效股票 ({t_end-t_start:.1f}秒)")
            return tc_result2
    
    # ====== QMT兜底已禁用（06-12）======
    # QMT full_market返回日K数据非盘中实时，用作行情源等于用过期数据推荐
    # 腾讯失败时宁可报错不用QMT糊弄，实盘用过期数据是严重风险
    # if _HAS_QUOTE_ADAPTER:
    #     log("  ⚠️ 腾讯行情均不足，降级QMT...")
    #     ... (原QMT兜底代码已注释，见git历史)

    # 腾讯行情获取失败，直接报错不降级
    result = _filter_stocks(result)
    t_end = time.time()
    log(f"  ⚠️ 腾讯仅获取{len(result)}只有效股票 ({t_end-t_start:.1f}秒)")
    if len(result) < 100:
        log(f"⛔ 严重警告: 腾讯行情仅获取{len(result)}只（正常应>3000），QMT日K数据不可用作实时行情，本次扫描结果不可靠！")
    return result







# ====== Step 2: K线获取 ======

def fetch_klines(code, count=250):
    """日K线数据（纯腾讯API，QMT已禁用）
    腾讯逐只~0.1s/只
    批量场景走batch_prefetch_klines的缓存
    """
    # ====== 腾讯优先（单只最快）======
    # 腾讯K线：ifzq.gtimg.cn（web.ifzq已501被WAF封，2026-06起改用裸域名+_var参数）
    secid = f"sh{code}" if code.startswith('6') else f"sz{code}"
    url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={secid},day,,,{count},qfq"
    try:
        resp = _http_session.get(url, timeout=8, verify=False)
        raw = resp.text
        # _var格式: kline_dayqfq={...json...}
        json_str = raw.split('=', 1)[1] if '=' in raw else raw
        data = json.loads(json_str)
        sec_data = data.get('data', {}).get(secid, {})
        bars = sec_data.get('qfqday', []) or sec_data.get('day', [])
        if bars and len(bars) >= 200:
            return {
                'open': np.array([float(b[1]) for b in bars]),
                'close': np.array([float(b[2]) for b in bars]),
                'high': np.array([float(b[3]) for b in bars]),
                'low': np.array([float(b[4]) for b in bars]),
                'volume': np.array([float(b[5]) for b in bars]),
                'last_date': bars[-1][0] if bars[-1] else '',
            }
    except Exception:
        pass

    # ====== QMT降级（已禁用，保留代码结构但不走QMT）======
    if _HAS_QUOTE_ADAPTER:
        try:
            kline_bars = get_kline(code, period="1d", count=count, prefer_qmt=False)
            if kline_bars and len(kline_bars) >= 200:
                return {
                    'open': np.array([float(b['open']) for b in kline_bars]),
                    'close': np.array([float(b['close']) for b in kline_bars]),
                    'high': np.array([float(b['high']) for b in kline_bars]),
                    'low': np.array([float(b['low']) for b in kline_bars]),
                    'volume': np.array([float(b['volume']) for b in kline_bars]),
                }
        except Exception:
            pass

    return None


# ====== Step 2.5: QMT批量K线预取（性能关键优化）======
# 全局K线缓存：预过滤后一次性批量拉取，_scan_one_rt直接查缓存
_kline_cache = {}

def batch_prefetch_klines(codes):
    """批量预取K线（腾讯30线程并发优先，QMT SSH降级）
    实测：腾讯30线程1500只~25s vs QMT SSH批量~60s+
    QMT仅作降级兜底
    结果存入全局 _kline_cache，_scan_one_rt 直接查缓存
    """
    global _kline_cache
    _kline_cache = {}  # 清空旧缓存

    if not codes:
        return

    t0 = time.time()

    # ====== 腾讯30线程并发（最快）======
    log(f"  📡 腾讯K线批量获取({len(codes)}只, 20线程)...")
    _tencent_fill_klines(codes)
    t1 = time.time()
    tc_count = len(_kline_cache)
    log(f"  ✅ 腾讯K线: {tc_count}/{len(codes)}只 ({t1-t0:.1f}秒)")

    # ====== QMT补缺（腾讯未获取到的）======
    # 06-12: 腾讯K线API被WAF封501时，tc_count=0，QMT补缺会处理全部
    # 阈值从0.9降到0.5，腾讯拿到一半以上就用腾讯，否则QMT全补
    if _HAS_QUOTE_ADAPTER and tc_count < len(codes) * 0.5:
        missing = [c for c in codes if c not in _kline_cache]
        if missing and len(missing) > 5:
            log(f"  ⚡ QMT补缺{len(missing)}只K线（腾讯仅获{tc_count}只）...")
            try:
                force_refresh()
                batch_size = 50
                qmt_filled = 0
                for i in range(0, len(missing), batch_size):
                    batch = missing[i:i+batch_size]
                    batch_data = get_batch_klines(batch, period="1d", count=250, prefer_qmt=False)
                    if batch_data:
                        for code, bars in batch_data.items():
                            if bars and len(bars) >= 200:
                                _kline_cache[code] = {
                                    'open': np.array([float(b['open']) for b in bars]),
                                    'close': np.array([float(b['close']) for b in bars]),
                                    'high': np.array([float(b['high']) for b in bars]),
                                    'low': np.array([float(b['low']) for b in bars]),
                                    'volume': np.array([float(b['volume']) for b in bars]),
                                }
                                qmt_filled += 1
                if qmt_filled > 0:
                    log(f"  ✅ QMT补缺: +{qmt_filled}只 → 总计{len(_kline_cache)}/{len(codes)}只")
            except Exception as e:
                log(f"  ⚠️ QMT批量K线异常: {e}")

    # ====== 腾讯部分补缺（腾讯拿到50%以上但不到100%）======
    elif _HAS_QUOTE_ADAPTER and tc_count < len(codes) * 0.95:
        missing = [c for c in codes if c not in _kline_cache]
        if missing and len(missing) > 5:
            log(f"  ⚡ QMT补缺{len(missing)}只K线（腾讯缺漏）...")
            try:
                force_refresh()
                batch_size = 50
                qmt_filled = 0
                for i in range(0, len(missing), batch_size):
                    batch = missing[i:i+batch_size]
                    batch_data = get_batch_klines(batch, period="1d", count=250, prefer_qmt=False)
                    if batch_data:
                        for code, bars in batch_data.items():
                            if bars and len(bars) >= 200:
                                _kline_cache[code] = {
                                    'open': np.array([float(b['open']) for b in bars]),
                                    'close': np.array([float(b['close']) for b in bars]),
                                    'high': np.array([float(b['high']) for b in bars]),
                                    'low': np.array([float(b['low']) for b in bars]),
                                    'volume': np.array([float(b['volume']) for b in bars]),
                                }
                                qmt_filled += 1
                if qmt_filled > 0:
                    log(f"  ✅ QMT补缺: +{qmt_filled}只 → 总计{len(_kline_cache)}/{len(codes)}只")
            except Exception as e:
                log(f"  ⚠️ QMT批量K线异常: {e}")


def _tencent_fill_klines(codes):
    """腾讯逐只获取K线，填入缓存（20线程并发，降低WAF风险）"""
    _lock = threading.Lock()

    def _fetch_one(code):
        data = _fetch_klines_tencent(code)  # 直接走腾讯，不走QMT
        if data:
            with _lock:
                _kline_cache[code] = data

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_fetch_one, c): c for c in codes}
        done = 0
        for f in as_completed(futures):
            done += 1
            if done % 200 == 0:
                log(f"    腾讯K线进度: {done}/{len(codes)}")


def _fetch_klines_tencent(code, count=250):
    """纯腾讯K线获取（不尝试QMT，用于批量预取的腾讯降级路径）
    使用模块级requests.Session连接池复用TCP连接。
    """
    # 腾讯K线：ifzq.gtimg.cn（web.ifzq已501被WAF封，2026-06起改用裸域名+_var参数）
    secid = f"sh{code}" if code.startswith('6') else f"sz{code}"
    url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={secid},day,,,{count},qfq"
    try:
        resp = _http_session.get(url, timeout=8, verify=False)
        raw = resp.text
        # _var格式: kline_dayqfq={...json...}
        json_str = raw.split('=', 1)[1] if '=' in raw else raw
        data = json.loads(json_str)
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
            'last_date': bars[-1][0] if bars[-1] else '',
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
    """扫描单只股票（日K线 + 分钟K线混合模式）
    优先从批量预取缓存取K线，缓存miss再单独拉
    """
    code = stock['code']

    # 优先从批量预取缓存取K线
    kdata = _kline_cache.get(code)
    if kdata is None:
        # 缓存miss，单独拉取（走QMT+腾讯降级）
        kdata = fetch_klines(code)
    if kdata is None:
        return None

    # K线API在盘中已返回今日K线（日期=今天，close=实时价）
    # 直接用，不追加虚拟K线，避免重复
    # BUT: QMT补缺的K线可能截止到昨天，缺少今日数据
    # 检测最后K线日期是否为今天，如果不是则用实时行情追加虚拟K线
    close_ext = kdata['close']
    high_ext = kdata['high']
    low_ext = kdata['low']
    vol_ext = kdata['volume']
    open_ext = kdata['open']
    
    # 06-12: 腾讯K线WAF封禁时走QMT补缺，QMT K线可能缺今日数据
    # 检测方法：如果最后一根K线的收盘价==最高价==最低价（盘中虚拟K线特征不明显）
    # 更可靠：用stock的实时行情数据追加今日虚拟K线
    # 检查K线最后一天是否为今天，如果不是则追加今日虚拟K线
    # 旧版用2%涨跌阈值判断，涨跌<2%时漏拼今日数据导致信号滞后
    # 新版用K线日期精确判断，无日期时回退到2%阈值
    if stock and len(close_ext) > 0:
        rt_price = stock.get('price', 0)
        rt_open = stock.get('open', 0)
        rt_high = stock.get('high', 0)
        rt_low = stock.get('low', 0)
        rt_vol = stock.get('volume', 0)
        last_close = float(close_ext[-1])
        last_date = kdata.get('last_date', '')
        today_str = datetime.now().strftime('%Y-%m-%d')
        # 优先用日期判断：K线最后一天不是今天 → 追加虚拟K线
        need_append = False
        if last_date and not last_date.startswith(today_str):
            need_append = True
        elif not last_date:
            # 无日期信息时回退到2%阈值（QMT补缺的K线无日期）
            if rt_price > 0 and abs(rt_price - last_close) / last_close > 0.02:
                need_append = True
        if need_append and rt_price > 0:
            # 追加今日虚拟K线
            close_ext = np.append(close_ext, rt_price)
            high_ext = np.append(high_ext, rt_high if rt_high > 0 else rt_price)
            low_ext = np.append(low_ext, rt_low if rt_low > 0 else rt_price)
            vol_ext = np.append(vol_ext, rt_vol if rt_vol > 0 else 0)
            open_ext = np.append(open_ext, rt_open if rt_open > 0 else rt_price)

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
        # 取最近60根K线做Vibe分析（30根太少，缠论信号需更多数据确认）
        n = len(close_ext)
        _s = max(0, n - 60)
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
        'limit_up': stock.get('limit_up', 0),
        'limit_down': stock.get('limit_down', 0),
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

    # 数据源报告
    if _HAS_QUOTE_ADAPTER:
        log(f"📊 数据源: 腾讯API(纯) — QMT已禁用")
    else:
        log(f"📊 数据源: 腾讯(主), quote_adapter未安装")

    log(f"{'='*60}")
    log(f"⚡ V10 盘中实时全扫描 {date_str} {time_str}")
    log(f"{'='*60}")

    # [1/5] 全市场实时行情
    log("\n[1/5] 获取全市场实时行情...")
    t0 = time.time()
    stocks = fetch_all_realtime()
    t1 = time.time()
    log(f"  获取到 {len(stocks)} 只有效股票 ({t1-t0:.1f}秒)")

    # [2/5] V10预过滤（问财智能筛选）
    prefiltered = prefilter_stocks(stocks)
    log(f"  预过滤: {len(stocks)}只 → {len(prefiltered)}只 (省{len(stocks)-len(prefiltered)}只)")
    
    # [3/5] 批量K线预取（纯腾讯API）
    log(f"\n[3/5] 批量K线预取（{len(prefiltered)}只）...")
    prefiltered_codes = [s['code'] for s in prefiltered]
    batch_prefetch_klines(prefiltered_codes)
    cache_hit = len(_kline_cache)
    log(f"  K线缓存: {cache_hit}/{len(prefiltered_codes)}只")

    # [4/5] V10扫描（K线已预取，扫描阶段直接查缓存 + iFinD分钟K线确认）
    log(f"\n[4/5] V10实时扫描（⚡30线程 + iFinD分钟K线确认）...")
    log(f"  K线缓存命中率: {cache_hit}/{len(prefiltered_codes)} ({cache_hit/max(len(prefiltered_codes),1)*100:.0f}%)")
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
    log(f"\n[5/5] 扫描完成: {len(prefiltered)}只 | 耗时{t3-t1:.1f}秒 | 命中{len(results)}只 | 错误{errors}只")

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
                limit_tag = f" 涨停{r.get('limit_up',0):.2f}/跌停{r.get('limit_down',0):.2f}" if r.get('limit_up') else ""
                log(f"  {r['name']}({r['code']}) ¥{r['price']:.2f} {r['change']:+.1f}%{limit_tag} | 成交{r['amount']:.0f}万 | {r['signal']}{intra_tag}{vibe_tag}")
                if r.get('intraday_notes', '') != '无分钟数据':
                    log(f"    📊 {r['intraday_notes']}")

        if strong_buy:
            log(f"\n🟠 强庄买 ({len(strong_buy)}只):")
            for r in strong_buy:
                intra_tag = f" | 盘中{r['intraday_confidence']}分✅" if r.get('intraday_ok') else f" | 盘中{r['intraday_confidence']}分⚠️" if r.get('intraday_notes', '') != '无分钟数据' else ""
                vibe_tag = f" | Vibe:{r.get('vibe_score',0):+d}({' '.join(r.get('vibe_tags',[])[:3])})" if r.get('vibe_tags') else ""
                limit_tag = f" 涨停{r.get('limit_up',0):.2f}/跌停{r.get('limit_down',0):.2f}" if r.get('limit_up') else ""
                log(f"  {r['name']}({r['code']}) ¥{r['price']:.2f} {r['change']:+.1f}%{limit_tag} | 成交{r['amount']:.0f}万 | {r['signal']}{intra_tag}{vibe_tag}")
                if r.get('intraday_notes', '') != '无分钟数据':
                    log(f"    📊 {r['intraday_notes']}")

        if base_buy:
            log(f"\n🟡 基础买 ({len(base_buy)}只):")
            for r in base_buy:
                intra_tag = f" | 盘中{r['intraday_confidence']}分✅" if r.get('intraday_ok') else f" | 盘中{r['intraday_confidence']}分⚠️" if r.get('intraday_notes', '') != '无分钟数据' else ""
                vibe_tag = f" | Vibe:{r.get('vibe_score',0):+d}({' '.join(r.get('vibe_tags',[])[:3])})" if r.get('vibe_tags') else ""
                limit_tag = f" 涨停{r.get('limit_up',0):.2f}/跌停{r.get('limit_down',0):.2f}" if r.get('limit_up') else ""
                log(f"  {r['name']}({r['code']}) ¥{r['price']:.2f} {r['change']:+.1f}%{limit_tag} | 成交{r['amount']:.0f}万 | {r['signal']}{intra_tag}{vibe_tag}")
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
                'limit_up': r.get('limit_up', 0),
                'limit_down': r.get('limit_down', 0),
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

        # 保存观察池
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
