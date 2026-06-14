#!/usr/bin/env python3
"""
行情数据源适配器 v3.1
数据源：纯腾讯API（QMT已禁用）

v3.1 变更（2026-06-12）：彻底禁用QMT fallback，只走腾讯API。
原因：QMT数据不稳定，容易用过期数据导致推荐错误。

用法：
  from quote_adapter import get_quotes, get_quote, get_kline, get_batch_klines
  from quote_adapter import get_full_market_quotes, get_source_name

  # 批量行情
  quotes = get_quotes(["600519", "000001", "300750"])

  # K线
  kline = get_kline("600519", period="1d", count=250)

  # 批量K线（V10扫描专用）
  klines = get_batch_klines(["600519", "000001"], period="1d", count=250)

  # 全市场行情（竞价选股用）
  all_stocks = get_full_market_quotes()
"""

import json
import time
import sys
import subprocess
import os
from urllib.request import urlopen, Request
from urllib.error import URLError

# ============ 配置 ============
QMT_DATA_URL = "http://127.0.0.1:18888"  # SSH隧道转发到Windows
QMT_SSH_HOST = "windows-qmt"  # SSH alias
TENCENT_BASE = "https://qt.gtimg.cn/q="
HEADERS = {"User-Agent": "Mozilla/5.0"}

# QMT连接状态缓存
_qmt_http_ok = None
_qmt_http_check_time = 0
_qmt_ssh_ok = None
_qmt_ssh_check_time = 0
CHECK_INTERVAL = 300  # 5分钟检查一次

# ============ QMT HTTP隧道 ============
def is_qmt_available():
    """检查QMT HTTP数据服务是否可用（向后兼容）"""
    return is_qmt_http_available()

def is_qmt_http_available():
    """检查QMT HTTP隧道是否可用"""
    global _qmt_http_ok, _qmt_http_check_time
    now = time.time()
    if _qmt_http_ok is not None and (now - _qmt_http_check_time) < CHECK_INTERVAL:
        return _qmt_http_ok
    try:
        r = urlopen(f"{QMT_DATA_URL}/health", timeout=3)
        data = json.loads(r.read().decode())
        _qmt_http_ok = data.get("xtdata", False) and data.get("status") == "ok"
    except:
        _qmt_http_ok = False
    _qmt_http_check_time = now
    return _qmt_http_ok

def is_qmt_ssh_available():
    """检查QMT SSH直连是否可用"""
    global _qmt_ssh_ok, _qmt_ssh_check_time
    now = time.time()
    if _qmt_ssh_ok is not None and (now - _qmt_ssh_check_time) < CHECK_INTERVAL:
        return _qmt_ssh_ok
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", QMT_SSH_HOST, "echo ok"],
            capture_output=True, timeout=5, text=True
        )
        _qmt_ssh_ok = result.returncode == 0 and "ok" in result.stdout
    except:
        _qmt_ssh_ok = False
    _qmt_ssh_check_time = now
    return _qmt_ssh_ok

# ============ QMT SSH直连 ============
def _qmt_ssh_query(query_type, codes=None, period="1d", count=250):
    """
    通过SSH直连Windows执行QMT查询（最可靠的方式）
    query_type: 'quote' | 'kline' | 'batch_kline' | 'full_market'
    codes: 股票代码列表（无后缀）
    period: K线周期 1d/1m/5m/15m/30m/60m
    count: K线条数
    """
    if codes:
        code_str = ",".join(codes)
    else:
        code_str = ""

    # 结果文件固定路径（不依赖stdout，避免xtdata欢迎消息干扰）
    RESULT_FILE_WIN = "C:/Users/qmt/qmt_result.json"
    RESULT_FILE_LOCAL = "/tmp/qmt_result.json"

    # 构建Python脚本（在Windows端执行）
    # xtquant已pip安装到Python312/Lib/site-packages，直接import即可
    script = f'''
import sys, json, os
# 抑制xtdata欢迎信息
try:
    import xtquant.xtdata as _xtd
    _xtd.enable_hello = False
except:
    pass
from xtquant.xtdata import connect, get_market_data_ex, get_stock_list_in_sector, get_instrument_detail
connect()

query_type = "{query_type}"
codes_str = "{code_str}"
period = "{period}"
count = {count}

def to_qmt_code(c):
    if '.' in c: return c
    return c + '.SH' if c.startswith(('6','5')) else c + '.SZ'

result = {{"status": "ok", "source": "qmt_ssh", "data": {{}}}}

try:
    if query_type == "full_market":
        # 全市场行情：用get_market_data_ex获取K线(有OHLCV) + get_instrument_detail获取名称
        all_codes = get_stock_list_in_sector('沪深A股')
        qmt_codes = [c for c in all_codes if not c.startswith(('688','689'))]
        # 先获取名称映射
        name_map = {{}}
        for qc in qmt_codes[:]:
            try:
                detail = get_instrument_detail(qc)
                if detail:
                    name_map[qc] = detail.get('InstrumentName', '')
            except:
                pass
        # K线数据(取2根，用前一根close作为prevClose，解决lastClose字段缺失问题)
        data = get_market_data_ex(
            field_list=[], stock_list=qmt_codes,
            period='1d', count=2
        )
        for qmt_code, df in data.items():
            if df is None or df.empty: continue
            row = df.iloc[-1]
            code = qmt_code.split('.')[0]
            if code[:3] in ('688','689') or code[0] in ('8','4','9'): continue
            close_price = float(row.get('close', 0))
            # prevClose: 优先lastClose字段，否则用前一根K线的close
            prev_close = float(row.get('lastClose', 0))
            if prev_close <= 0 and len(df) >= 2:
                prev_close = float(df.iloc[-2].get('close', 0))
            if prev_close <= 0:
                prev_close = close_price  # 最后兜底
            result['data'][code] = {{
                'lastPrice': close_price if close_price > 0 else prev_close,
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'prevClose': prev_close,
                'volume': float(row.get('volume', 0)),
                'amount': float(row.get('amount', 0)),
                'name': name_map.get(qmt_code, qmt_code),
                'source': 'qmt_ssh',
            }}

    elif query_type == "quote":
        qmt_codes = [to_qmt_code(c) for c in codes_str.split(',') if c]
        # 获取名称
        name_map = {{}}
        for qc in qmt_codes:
            try:
                detail = get_instrument_detail(qc)
                if detail:
                    name_map[qc] = detail.get('InstrumentName', '')
            except:
                pass
        # K线数据(取2根，用前一根close作为prevClose，解决lastClose字段缺失问题)
        data = get_market_data_ex(
            field_list=[], stock_list=qmt_codes,
            period='1d', count=2
        )
        for qmt_code, df in data.items():
            if df is None or df.empty: continue
            row = df.iloc[-1]
            code = qmt_code.split('.')[0]
            close_price = float(row.get('close', 0))
            # prevClose: 优先lastClose字段，否则用前一根K线的close
            prev_close = float(row.get('lastClose', 0))
            if prev_close <= 0 and len(df) >= 2:
                prev_close = float(df.iloc[-2].get('close', 0))
            if prev_close <= 0:
                prev_close = close_price  # 最后兜底
            result['data'][code] = {{
                'lastPrice': close_price if close_price > 0 else prev_close,
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'prevClose': prev_close,
                'volume': float(row.get('volume', 0)),
                'amount': float(row.get('amount', 0)),
                'name': name_map.get(qmt_code, qmt_code),
                'source': 'qmt_ssh',
            }}

    elif query_type == "kline":
        code = codes_str.split(",")[0] if codes_str else ""
        qmt_code = to_qmt_code(code)
        data = get_market_data_ex(
            field_list=[], stock_list=[qmt_code],
            period=period, count=count
        )
        df = data.get(qmt_code)
        if df is not None and not df.empty:
            result["data"] = []
            for idx, row in df.iterrows():
                result["data"].append({{
                    "time": str(idx)[:10] if period == "1d" else str(idx),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", 0)),
                    "amount": float(row.get("amount", 0)),
                }})

    elif query_type == "batch_kline":
        codes_list = [c for c in codes_str.split(",") if c]
        qmt_codes = [to_qmt_code(c) for c in codes_list]
        for i in range(0, len(qmt_codes), 50):
            batch = qmt_codes[i:i+50]
            data = get_market_data_ex(
                field_list=[], stock_list=batch,
                period=period, count=count
            )
            for qmt_code, df in data.items():
                if df is None or df.empty: continue
                code = qmt_code.split(".")[0]
                bars = []
                for idx, row in df.iterrows():
                    bars.append({{
                        "time": str(idx)[:10] if period == "1d" else str(idx),
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "close": float(row.get("close", 0)),
                        "volume": float(row.get("volume", 0)),
                        "amount": float(row.get("amount", 0)),
                    }})
                result["data"][code] = bars
except Exception as e:
    result["status"] = "error"
    result["error"] = str(e)

# 写入固定路径（避免xtdata输出干扰stdout）
with open(r"C:\\Users\\qmt\\qmt_result.json", "w") as f:
    json.dump(result, f)
'''

    # 写脚本到Mac临时文件
    tmp_script = "/tmp/qmt_query_ssh.py"
    with open(tmp_script, "w") as f:
        f.write(script)

    # SCP到Windows
    try:
        subprocess.run(
            ["scp", "-q", tmp_script, f"{QMT_SSH_HOST}:C:/Users/qmt/qmt_query_ssh.py"],
            capture_output=True, timeout=10
        )
    except:
        return {}

    # SSH执行前先删除旧结果文件，防止脚本失败时读到过期数据
    try:
        subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8", QMT_SSH_HOST,
             f"del /f {RESULT_FILE_WIN.replace('/', chr(92))} 2>nul"],
            capture_output=True, timeout=5
        )
    except:
        pass

    # SSH执行（不关心stdout，结果写入固定文件）
    try:
        result_proc = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8", QMT_SSH_HOST,
             "C:\\Python312\\python.exe C:\\Users\\qmt\\qmt_query_ssh.py"],
            capture_output=True, timeout=120
        )
        # 检查SSH执行是否成功（非零退出码=脚本执行失败）
        if result_proc.returncode != 0:
            return {}
    except:
        return {}

    # SCP结果文件回来
    try:
        subprocess.run(
            ["scp", "-q", f"{QMT_SSH_HOST}:{RESULT_FILE_WIN}", RESULT_FILE_LOCAL],
            capture_output=True, timeout=10
        )
        with open(RESULT_FILE_LOCAL) as f:
            data = json.load(f)
        if data.get("status") == "ok" and data.get("data"):
            return data.get("data", {})
        return {}
    except:
        return {}


def _qmt_ssh_get_quotes(codes):
    """通过SSH直连获取批量行情"""
    return _qmt_ssh_query("quote", codes=codes)

def _qmt_ssh_get_kline(code, period="1d", count=250):
    """通过SSH直连获取K线"""
    data = _qmt_ssh_query("kline", codes=[code], period=period, count=count)
    return data if isinstance(data, list) else []

def _qmt_ssh_batch_klines(codes, period="1d", count=250):
    """通过SSH直连批量获取K线"""
    return _qmt_ssh_query("batch_kline", codes=codes, period=period, count=count)

def _qmt_http_full_market():
    """通过QMT HTTP服务获取全市场行情"""
    try:
        url = f"{QMT_DATA_URL}/full_market"
        r = urlopen(url, timeout=60)  # 全量数据较大，timeout放长
        data = json.loads(r.read().decode())
        if data.get("count", 0) > 100:
            return data.get("data", {})
    except Exception:
        pass
    return {}


def _qmt_ssh_full_market():
    """通过SSH直连获取全市场行情"""
    return _qmt_ssh_query("full_market")


# ============ QMT HTTP隧道 ============
def _qmt_http_get_quotes(codes):
    """通过QMT HTTP服务获取批量行情"""
    if not codes:
        return {}
    qmt_codes = []
    code_map = {}
    for code in codes:
        if "." in code:
            qmt_code = code
        elif code.startswith("6") or code.startswith("5"):
            qmt_code = f"{code}.SH"
        else:
            qmt_code = f"{code}.SZ"
        qmt_codes.append(qmt_code)
        code_map[qmt_code] = code

    try:
        url = f"{QMT_DATA_URL}/quote?codes={','.join(qmt_codes)}"
        r = urlopen(url, timeout=8)
        data = json.loads(r.read().decode())
        result = {}
        for qmt_code, info in data.get("data", {}).items():
            orig_code = code_map.get(qmt_code, qmt_code.split(".")[0])
            result[orig_code] = {
                "lastPrice": info.get("lastPrice"),
                "open": info.get("open"),
                "high": info.get("high"),
                "low": info.get("low"),
                "prevClose": info.get("lastClose"),
                "volume": info.get("volume"),
                "amount": info.get("amount"),
                "name": info.get("name", ""),
                "bidPrice": info.get("bidPrice", [])[:5],
                "bidVol": info.get("bidVol", [])[:5],
                "askPrice": info.get("askPrice", [])[:5],
                "askVol": info.get("askVol", [])[:5],
                "source": "qmt",
            }
        return result
    except:
        return {}

def _qmt_http_get_kline(code, period="1d", count=250):
    """通过QMT HTTP服务获取K线"""
    if "." not in code:
        code = f"{code}.SH" if code.startswith("6") or code.startswith("5") else f"{code}.SZ"
    try:
        url = f"{QMT_DATA_URL}/kline?code={code}&period={period}&count={count}"
        r = urlopen(url, timeout=15)
        data = json.loads(r.read().decode())
        return data.get("data", [])
    except:
        return []


# ============ 腾讯数据源（fallback）============
def _tencent_get_quotes(codes):
    """通过腾讯API获取批量行情"""
    if not codes:
        return {}
    result = {}
    for i in range(0, len(codes), 30):
        batch = codes[i:i+30]
        secids = []
        code_map = {}
        for code in batch:
            if code.startswith("6") or code.startswith("5"):
                secid = f"sh{code}"
            else:
                secid = f"sz{code}"
            secids.append(secid)
            code_map[secid] = code
        url = f"https://qt.gtimg.cn/q={','.join(secids)}"
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=8) as resp:
                text = resp.read().decode("gbk", errors="ignore")
            for line in text.strip().split(";"):
                if not line or "=" not in line:
                    continue
                parts = line.split("=")[1].strip('";\n')
                if not parts:
                    continue
                fields = parts.split("~")
                if len(fields) < 50:
                    continue
                secid = line.split("=")[0].split("_")[-1].split(".")[0]
                orig_code = code_map.get(secid, "")
                if not orig_code:
                    continue
                try:
                    result[orig_code] = {
                        "lastPrice": float(fields[3]) if fields[3] else 0,
                        "open": float(fields[5]) if fields[5] else 0,
                        "high": float(fields[33]) if fields[33] else 0,
                        "low": float(fields[34]) if fields[34] else 0,
                        "prevClose": float(fields[4]) if fields[4] else 0,
                        "volume": float(fields[6]) if fields[6] else 0,
                        "amount": float(fields[37]) if fields[37] else 0,
                        "name": fields[1] if len(fields) > 1 else "",
                        "change_pct": float(fields[32]) if fields[32] else 0,
                        "turnover": float(fields[38]) if fields[38] else 0,
                        "circ_cap": float(fields[44]) if fields[44] else 0,    # 流通市值(亿) fields[44]
                        "total_cap": float(fields[45]) if fields[45] else 0,    # 总市值(亿) fields[45]
                        "pe_ttm": float(fields[39]) if fields[39] else 0,
                        "amplitude": float(fields[43]) if len(fields) > 43 and fields[43] else 0,  # 振幅% fields[43]
                        "pb": float(fields[46]) if len(fields) > 46 and fields[46] else 0,         # 市净率PB fields[46]
                        "vol_ratio": float(fields[49]) if len(fields) > 49 and fields[49] else 0,
                        "limit_up": float(fields[47]) if len(fields) > 47 and fields[47] else 0,
                        "limit_down": float(fields[48]) if len(fields) > 48 and fields[48] else 0,
                        "outer_vol": float(fields[7]) if len(fields) > 7 and fields[7] else 0,
                        "inner_vol": float(fields[8]) if len(fields) > 8 and fields[8] else 0,
                        "source": "tencent",
                    }
                except (ValueError, IndexError):
                    continue
        except:
            continue
    return result

def _tencent_get_kline(code, period="day", count=250):
    """腾讯K线"""
    prefix = "sh" if code.startswith("6") or code.startswith("5") else "sz"
    secid = f"{prefix}{code}"
    # 腾讯period映射
    tencent_period = "day" if period in ("1d", "day") else period
    url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={secid},{tencent_period},,,{count},qfq"
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=8) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(text.split("=", 1)[1])
        d = data.get("data", {})
        kkey = list(d.keys())[0]
        klines = d[kkey].get("qfqday", d[kkey].get("day", []))
        result = []
        for k in klines[-count:]:
            try:
                result.append({
                    "time": k[0],
                    "open": float(k[1]), "close": float(k[2]),
                    "high": float(k[3]), "low": float(k[4]),
                    "volume": float(k[5]) if len(k) > 5 else 0,
                    "amount": float(k[6]) if len(k) > 6 and isinstance(k[6], (int, float, str)) else 0,
                })
            except (ValueError, IndexError, TypeError):
                continue  # 跳过解析失败的K线条目（如除权日带分红dict的条目）
        return result if result else []
    except:
        return []


# ============ 统一接口 ============
def _is_stale_quote(quote, code=''):
    """检查QMT行情数据是否过期（价格=昨收且开盘=0说明非交易时段或停牌）"""
    price = quote.get('lastPrice', 0)
    prev = quote.get('prevClose', 0)
    open_price = quote.get('open', 0)
    # 非停牌情况下：价格=昨收且开盘=0 → 数据源返回的是昨收，不是实时价
    if price > 0 and prev > 0 and price == prev and open_price == 0:
        return True
    # prevClose=lastPrice（QMT lastClose字段缺失的典型表现）→ 涨跌幅必为0
    if price > 0 and prev > 0 and price == prev and abs(price - prev) < 0.001:
        # 如果价格完全等于昨收，检查是否交易时段（交易时段内不应该完全相等）
        now = __import__('datetime').datetime.now()
        h, m = now.hour, now.minute
        t = h * 100 + m
        is_trading = (930 <= t <= 1130) or (1300 <= t <= 1500)
        if is_trading:
            return True
    return False


def get_quotes(codes, prefer_qmt=False):
    """
    批量获取行情数据
    v3.1: 纯腾讯数据源，QMT已禁用（2026-06-12：小南要求停用QMT，只走腾讯）
    codes: list of str, e.g. ["600519", "000001"]
    返回: dict {code: {lastPrice, open, high, low, prevClose, volume, amount, name, ...}}
    """
    if not codes:
        return {}

    # 纯腾讯API，不走QMT（2026-06-12 禁用QMT fallback）
    result = _tencent_get_quotes(codes)
    return result

def get_quote(code, prefer_qmt=False):
    """单只股票行情"""
    result = get_quotes([code], prefer_qmt=prefer_qmt)
    return result.get(code, {})

def get_kline(code, period="1d", count=250, prefer_qmt=False):
    """
    获取K线数据
    v3.1: 纯腾讯数据源，QMT已禁用
    period: 1d, 1m, 5m, 15m, 30m, 60m
    返回: list of dict [{time, open, high, low, close, volume, amount}, ...]
    """
    # 纯腾讯K线（2026-06-12 禁用QMT）
    kline = _tencent_get_kline(code, period, count)
    if kline:
        return kline

    return []

def get_batch_klines(codes, period="1d", count=250, prefer_qmt=False):
    """
    批量获取K线（V10扫描专用，比逐只快很多）
    v3.1: 纯腾讯数据源，QMT已禁用
    返回: dict {code: [{time, open, high, low, close, volume, amount}, ...]}
    """
    if not codes:
        return {}

    # 纯腾讯逐只K线（2026-06-12 禁用QMT）
    result = {}
    for code in codes:
        kline = _tencent_get_kline(code, period, count)
        if kline:
            result[code] = kline
    return result

def get_full_market_quotes(prefer_qmt=False):
    """
    获取全市场行情（竞价选股/V10全扫描用）
    v3.1: 纯腾讯数据源，QMT已禁用
    返回: dict {code: {name, lastPrice, prevClose, open, high, low, volume, amount, ...}}
    """
    # 纯腾讯全量扫描（2026-06-12 禁用QMT）
    result = _tencent_full_market()
    return result

def _tencent_full_market():
    """腾讯并发全量扫描（fallback）"""
    import concurrent.futures
    import re

    EXCLUDE_CODES = {'688', '689', '8', '4'}
    BATCH_SIZE = 100

    def gen_pool():
        pool = []
        for i in range(600000, 606000):
            pool.append(f"sh{i}")
        for i in range(1, 4000):
            pool.append(f"sz{str(i).zfill(6)}")
        for i in range(2000, 3000):
            pool.append(f"sz{str(i).zfill(6)}")
        for i in range(300000, 302000):
            pool.append(f"sz{i}")
        return pool

    def fetch_batch(codes):
        results = {}
        url = f"http://qt.gtimg.cn/q={','.join(codes)}"
        try:
            resp = urlopen(url, timeout=20)
            raw = resp.read()
            data = raw.decode("GBK", errors="ignore")
            for line in data.strip().split('\n'):
                line = line.strip().rstrip(';')
                if not line:
                    continue
                m = re.match(r'v_(\w+)="(.*)"', line)
                if not m:
                    continue
                code_full = m.group(1)
                parts = m.group(2).split('~')
                if len(parts) < 40:
                    continue
                try:
                    name = parts[1]
                    price = float(parts[3]) if parts[3] else 0
                    if price <= 0:
                        continue
                    code = code_full.replace('sh', '').replace('sz', '')
                    market = 'sh' if code_full.startswith('sh') else 'sz'
                    if code[:3] in EXCLUDE_CODES or code[0] in {'8', '4'}:
                        continue
                    prev_close = float(parts[4]) if parts[4] else 0
                    limit_up = float(parts[47]) if len(parts) > 47 and parts[47] else 0
                    limit_down = float(parts[48]) if len(parts) > 48 and parts[48] else 0
                    open_p = float(parts[5]) if parts[5] else 0
                    volume = float(parts[6]) if parts[6] else 0
                    high = float(parts[33]) if parts[33] else 0
                    low = float(parts[34]) if parts[34] else 0
                    amount = float(parts[37]) if len(parts) > 37 and parts[37] else 0
                    turnover = float(parts[38]) if len(parts) > 38 and parts[38] else 0
                    circ_cap = float(parts[44]) if len(parts) > 44 and parts[44] else 0    # 流通市值(亿) fields[44]
                    total_cap = float(parts[45]) if len(parts) > 45 and parts[45] else 0    # 总市值(亿) fields[45]
                    pe_ttm = float(parts[39]) if len(parts) > 39 and parts[39] else 0
                    amplitude = float(parts[43]) if len(parts) > 43 and parts[43] else 0    # 振幅% fields[43]
                    pb = float(parts[46]) if len(parts) > 46 and parts[46] else 0            # 市净率PB fields[46]
                    vol_ratio = float(parts[49]) if len(parts) > 49 and parts[49] else 0
                    outer_vol = float(parts[7]) if len(parts) > 7 and parts[7] else 0
                    inner_vol = float(parts[8]) if len(parts) > 8 and parts[8] else 0
                    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                    if vol_ratio <= 0 and circ_cap > 0:
                        vol_ratio = round(amount / max(circ_cap * 12.5 / 10000, 1), 1)

                    results[code] = {
                        'code': code, 'name': name, 'price': price,
                        'prev_close': prev_close, 'open': open_p,
                        'volume': volume, 'amount_wan': amount,
                        'turnover': turnover, 'high': high, 'low': low,
                        'change_pct': change_pct, 'vol_ratio': vol_ratio,
                        'circ_cap': circ_cap, 'market': market,
                        'amount_yuan': amount * 10000,
                        'limit_up': limit_up, 'limit_down': limit_down,
                        'outer_vol': outer_vol, 'inner_vol': inner_vol,
                        'pe_ttm': pe_ttm, 'amplitude': amplitude, 'pb': pb,
                        'total_cap': total_cap,
                        'lastPrice': price, 'prevClose': prev_close,
                        'source': 'tencent',
                    }
                except (ValueError, IndexError):
                    continue
        except:
            pass
        return results

    pool = gen_pool()
    all_stocks = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for i in range(0, len(pool), BATCH_SIZE):
            batch = pool[i:i+BATCH_SIZE]
            futures.append(executor.submit(fetch_batch, batch))
        for f in concurrent.futures.as_completed(futures):
            all_stocks.update(f.result())
    return all_stocks

def get_source_name():
    """返回当前使用的数据源名称（v3.1: 纯腾讯，QMT已禁用）"""
    return "腾讯(纯)"

def force_refresh():
    """强制刷新数据源可用性缓存"""
    global _qmt_http_ok, _qmt_http_check_time, _qmt_ssh_ok, _qmt_ssh_check_time
    _qmt_http_ok = None
    _qmt_http_check_time = 0
    _qmt_ssh_ok = None
    _qmt_ssh_check_time = 0


if __name__ == "__main__":
    import sys
    codes = sys.argv[1:] if len(sys.argv) > 1 else ["600519", "000001", "300750"]

    force_refresh()
    source = get_source_name()
    print(f"📊 数据源: {source}")
    print("=" * 60)

    t0 = time.time()
    quotes = get_quotes(codes)
    t1 = time.time()

    print(f"获取 {len(quotes)} 只股票，耗时 {(t1-t0)*1000:.0f}ms")
    print("-" * 60)
    for code, info in quotes.items():
        name = info.get("name", "?")
        last = info.get("lastPrice", info.get("price", 0))
        src = info.get("source", "?")
        print(f"  {code} {name} ¥{last} [{src}]")

    # 测试K线
    print("\n📈 K线测试:")
    t2 = time.time()
    kline = get_kline("600519", period="1d", count=5)
    t3 = time.time()
    print(f"  茅台日K 5条，耗时 {(t3-t2)*1000:.0f}ms, 数据源: {source}")
    if kline:
        for bar in kline[-3:]:
            print(f"    {bar['time']} O:{bar['open']} H:{bar['high']} L:{bar['low']} C:{bar['close']}")

    # 测试全市场
    print(f"\n🌐 全市场行情测试:")
    t4 = time.time()
    all_q = get_full_market_quotes()
    t5 = time.time()
    print(f"  {len(all_q)} 只股票，耗时 {(t5-t4)*1000:.0f}ms, 数据源: {source}")
