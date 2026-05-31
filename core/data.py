"""数据获取模块 V10 — 完整数据源整合

数据源优先级（来自V10经验）：
- K线数据：腾讯K线（免费无限制）> akshare（VPN不稳）
- 实时行情：腾讯行情 qt.gtimg.cn（免费无限制）
- 板块数据：腾讯板块ETF
- 资金面：iFinD HTTP API > 10jqka > 缓存
- 基本面：iFinD HTTP API
"""
import time
import json
import numpy as np
import requests
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import os

# 代理清除（VPN会拦截请求）
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(k, None)
os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("NO_PROXY", "*")

HEADERS = {"User-Agent": "Mozilla/5.0"}

# 内存缓存
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 300  # 5分钟


def _get_cached(key: str):
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None


def _set_cache(key: str, data):
    _cache[key] = (time.time(), data)


# ===== 腾讯K线（首选）=====

def tencent_klines(code: str, days: int = 250) -> pd.DataFrame:
    """腾讯前复权日K线"""
    cache_key = f"tencent_kline_{code}_{days}"
    cached = _get_cached(cache_key)
    if cached is not None and isinstance(cached, pd.DataFrame):
        return cached

    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{days},qfq"

    try:
        resp = requests.get(url, timeout=15, headers=HEADERS)
        data = json.loads(resp.text)
        sec_data = data.get("data", {}).get(symbol, {})
        bars = sec_data.get("qfqday", []) or sec_data.get("day", [])

        if not bars:
            return pd.DataFrame()

        records = []
        for b in bars:
            records.append({
                "date": b[0],
                "open": float(b[1]),
                "close": float(b[2]),
                "high": float(b[3]),
                "low": float(b[4]),
                "volume": float(b[5]) if len(b) > 5 and b[5] else 0,
            })

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        _set_cache(cache_key, df)
        return df.copy()
    except Exception as e:
        print(f"[数据] 腾讯K线 {code} 失败: {e}")
        return pd.DataFrame()


def akshare_klines(code: str, days: int = 250) -> pd.DataFrame:
    """akshare 日K线（备用）"""
    cache_key = f"akshare_kline_{code}_{days}"
    cached = _get_cached(cache_key)
    if cached is not None and isinstance(cached, pd.DataFrame):
        return cached

    try:
        import akshare as ak
        symbol = f"sz{code}" if not code.startswith("6") else f"sh{code}"
        df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
        if df is None or len(df) < 20:
            return pd.DataFrame()
        df = df.tail(days).copy()
        df["date"] = pd.to_datetime(df["date"])
        _set_cache(cache_key, df)
        return df.copy()
    except Exception as e:
        print(f"[数据] akshare {code} 失败: {e}")
        return pd.DataFrame()


def get_stock_history(code: str, days: int = 250) -> pd.DataFrame:
    """获取K线（腾讯优先，akshare降级）"""
    df = tencent_klines(code, days)
    if not df.empty and len(df) >= 20:
        return df
    df = akshare_klines(code, days)
    if not df.empty and len(df) >= 20:
        return df
    return pd.DataFrame()


# ===== 腾讯实时行情 =====

def get_realtime_quote(code: str) -> dict | None:
    """腾讯实时行情"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"http://qt.gtimg.cn/q={prefix}{code}"

    try:
        resp = requests.get(url, timeout=5, headers=HEADERS)
        text = resp.text
        if "=" not in text:
            return None
        parts = text.split("=")[1].strip('";\n').split("~")
        if len(parts) < 50:
            return None

        return {
            "code": code,
            "name": parts[1],
            "price": float(parts[3]) if parts[3] else 0,
            "pct_change": float(parts[32]) if parts[32] else 0,
            "volume": float(parts[6]) if parts[6] else 0,
            "amount": float(parts[37]) if parts[37] else 0,
            "turnover": float(parts[38]) if parts[38] else 0,
            "high": float(parts[33]) if parts[33] else 0,
            "low": float(parts[34]) if parts[34] else 0,
            "open": float(parts[5]) if parts[5] else 0,
            "pre_close": float(parts[4]) if parts[4] else 0,
        }
    except Exception as e:
        print(f"[数据] 腾讯行情 {code} 失败: {e}")
        return None


def get_realtime_quotes_batch(codes: list[str]) -> list[dict]:
    """批量获取实时行情"""
    results = []
    for code in codes:
        quote = get_realtime_quote(code)
        if quote:
            results.append(quote)
    return results


# ===== 股票列表（腾讯行情源）=====

# 常用股票池（可扩展）
_STOCK_POOL = [
    # 沪市主板
    '600519', '601318', '600036', '601166', '600276', '600887', '601888', '600900',
    '601398', '601939', '600028', '601088', '600050', '601857', '600585', '601601',
    '600016', '601328', '601668', '600031', '601288', '600000', '600104', '600309',
    # 深市主板
    '000001', '000002', '000858', '000333', '000568', '000651', '000725', '000063',
    '002415', '002594', '002714', '002304', '000538', '000661', '002352', '000002',
    # 创业板
    '300750', '300059', '300015', '300122', '300760', '300124', '300033', '300274',
    # 科创板
    '688981', '688111', '688036', '688009', '688012', '688005', '688003', '688002',
]


def get_stock_list() -> pd.DataFrame:
    """获取股票列表（腾讯行情API）"""
    cache_key = "stock_list"
    cached = _get_cached(cache_key)
    if cached is not None and isinstance(cached, pd.DataFrame):
        return cached

    stocks = []
    
    # 用腾讯行情API批量获取
    for code in _STOCK_POOL:
        quote = get_realtime_quote(code)
        if quote:
            stocks.append({
                "code": code,
                "name": quote["name"],
                "price": quote["price"],
                "pct_change": quote["pct_change"],
                "turnover": quote["turnover"],
                "volume": quote["volume"],
                "amount": quote["amount"],
            })

    if stocks:
        df = pd.DataFrame(stocks)
        _set_cache(cache_key, df)
        return df.copy()
    
    return pd.DataFrame()


# ===== 板块数据 =====

def get_sector_data() -> pd.DataFrame:
    """获取板块数据（东方财富）"""
    cache_key = "sector_data"
    cached = _get_cached(cache_key)
    if cached is not None and isinstance(cached, pd.DataFrame):
        return cached

    try:
        import akshare as ak
        df = ak.stock_board_concept_name_em()
        df = df.rename(columns={
            "板块名称": "name", "板块代码": "code",
            "最新价": "price", "涨跌幅": "pct_change",
        })
        _set_cache(cache_key, df)
        return df.copy()
    except Exception as e:
        print(f"[数据] 板块数据失败: {e}")
        return pd.DataFrame()


# ===== 资金面数据 =====

def get_capital_flow(code: str) -> dict | None:
    """获取资金面数据（主力净流入）"""
    cache_key = f"capital_flow_{code}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    # 尝试从缓存文件读取
    cache_path = os.path.expanduser("~/.hermes/cache/capital_flow.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                data = json.load(f)
            flow_data = data.get("dimensions", {}).get("capital_flow", {})
            if code in flow_data:
                result = flow_data[code]
                _set_cache(cache_key, result)
                return result
        except Exception:
            pass

    # 尝试10jqka实时查询
    try:
        url = f"http://d.10jqka.com.cn/v2/realhead/hs_{code}/last.js"
        resp = requests.get(url, timeout=5, headers=HEADERS)
        if resp.status_code == 200:
            text = resp.text
            # 解析JSONP格式
            json_str = text[text.index("(") + 1:text.rindex(")")]
            data = json.loads(json_str)
            result = {
                "main_net_inflow": float(data.get("main_net_inflow", 0)),
                "name": data.get("name", code),
            }
            _set_cache(cache_key, result)
            return result
    except Exception:
        pass

    return None


# ===== 基本面数据 =====

def get_fundamental(code: str) -> dict | None:
    """获取基本面数据（ROE、净利润增速）"""
    cache_key = f"fundamental_{code}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    # 尝试从iFinD HTTP API获取
    try:
        sys_path = os.path.expanduser("~/.hermes/scripts")
        if sys_path not in os.sys.path:
            os.sys.path.insert(0, sys_path)
        from ifind_http_api import iFinD

        ifind_code = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
        df = iFinD.basic_data([ifind_code], ["ths_roe_deducted_stock", "ths_np_yoy_stock"])
        if df is not None and not df.empty:
            result = {
                "roe": float(df.iloc[0].get("ths_roe_deducted_stock", 0)),
                "np_yoy": float(df.iloc[0].get("ths_np_yoy_stock", 0)),
            }
            _set_cache(cache_key, result)
            return result
    except Exception:
        pass

    return None


# ===== 排行榜 =====

def get_top_gainers(limit: int = 20) -> pd.DataFrame:
    """涨幅榜"""
    df = get_stock_list()
    if df.empty:
        return df
    return df.nlargest(limit, "pct_change")


def get_top_losers(limit: int = 20) -> pd.DataFrame:
    """跌幅榜"""
    df = get_stock_list()
    if df.empty:
        return df
    return df.nsmallest(limit, "pct_change")


def get_top_volume(limit: int = 20) -> pd.DataFrame:
    """成交额排行"""
    df = get_stock_list()
    if df.empty:
        return df
    return df.nlargest(limit, "amount") if "amount" in df.columns else df.head(limit)
