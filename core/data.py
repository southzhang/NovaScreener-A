"""数据获取模块 V10 — 腾讯K线优先 + akshare 降级 + 实时行情

数据源优先级（来自你的SKILL.md经验）：
- K线数据：腾讯K线 > akshare（VPN不稳）
- 实时行情：腾讯行情 qt.gtimg.cn（免费无限制）
- 板块分析：sector_analysis.py（iFinD优先）
"""
import time
import json
import numpy as np
import requests
import pandas as pd
from datetime import datetime, timedelta

# 内存缓存
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 300  # 5分钟缓存

# 代理清除（你的经验：VPN代理会拦截请求）
import os
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(k, None)
os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("NO_PROXY", "*")

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _get_cached(key: str):
    """从缓存获取"""
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data if isinstance(data, pd.DataFrame) else data
    return None


def _set_cache(key: str, data):
    """写入缓存"""
    _cache[key] = (time.time(), data)


# ===== 腾讯K线（首选数据源）=====

def tencent_klines(code: str, days: int = 250) -> pd.DataFrame:
    """腾讯前复权日K线（你的经验：ifzq.gtimg.cn HTTPS正常，免费无限制）"""
    cache_key = f"tencent_kline_{code}_{days}"
    cached = _get_cached(cache_key)
    if cached is not None:
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
        print(f"[数据] 腾讯K线获取 {code} 失败: {e}")
        return pd.DataFrame()


def akshare_klines(code: str, days: int = 250) -> pd.DataFrame:
    """akshare 日K线（备用数据源，VPN可能不稳定）"""
    cache_key = f"akshare_kline_{code}_{days}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        import akshare as ak
        symbol = f"sz{code}" if not code.startswith("6") else f"sh{code}"
        df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
        if df is None or len(df) < 20:
            return pd.DataFrame()

        df = df.tail(days).copy()
        df = df.rename(columns={"date": "date"})
        df["date"] = pd.to_datetime(df["date"])
        _set_cache(cache_key, df)
        return df.copy()
    except Exception as e:
        print(f"[数据] akshare获取 {code} 失败: {e}")
        return pd.DataFrame()


def get_stock_history(code: str, days: int = 250) -> pd.DataFrame:
    """获取个股历史K线（腾讯优先，akshare降级）"""
    # 先试腾讯
    df = tencent_klines(code, days)
    if not df.empty and len(df) >= 20:
        return df

    # 降级到akshare
    df = akshare_klines(code, days)
    if not df.empty and len(df) >= 20:
        return df

    return pd.DataFrame()


# ===== 腾讯实时行情（免费无限制）=====

def get_realtime_quote(code: str) -> dict | None:
    """腾讯实时行情（你的经验：qt.gtimg.cn 免费无限制，field[3]=价格，field[32]=涨跌幅）"""
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
        print(f"[数据] 腾讯行情获取 {code} 失败: {e}")
        return None


def get_realtime_quotes_batch(codes: list[str]) -> list[dict]:
    """批量获取实时行情"""
    results = []
    for code in codes:
        quote = get_realtime_quote(code)
        if quote:
            results.append(quote)
    return results


# ===== 股票列表（新浪源）=====

def get_stock_list() -> pd.DataFrame:
    """获取A股列表（新浪行情API，你的经验：vip.stock.finance.sina.com.cn）"""
    cache_key = "stock_list"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    stocks = []

    def _fetch_node(node, prefixes):
        node_stocks = []
        for prefix in prefixes:
            for page in range(1, 50):
                try:
                    url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api_json_v2.php/Market_Center.getHQNodeData?page={page}&num=80&sort=symbol&asc=1&node={node}&symbol=&_s_r_a=page"
                    resp = requests.get(url, timeout=10)
                    if resp.status_code == 200 and resp.text.strip():
                        data = json.loads(resp.text)
                        for item in data:
                            symbol = item.get("symbol", "")
                            if symbol.startswith(prefix):
                                name = item.get("name", "")
                                if "ST" not in name and "退市" not in name:
                                    price = float(item.get("trade", 0))
                                    if price > 0:
                                        node_stocks.append({
                                            "code": symbol[2:],
                                            "name": name,
                                            "price": price,
                                            "pct_change": float(item.get("changepercent", 0)),
                                            "turnover": float(item.get("turnoverratio", 0)),
                                        })
                        if len(data) < 80:
                            break
                except Exception:
                    break
        return node_stocks

    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_sh = ex.submit(_fetch_node, "sh_a", ["sh6"])
            f_sz = ex.submit(_fetch_node, "sz_a", ["sz0", "sz3"])
            stocks = f_sh.result() + f_sz.result()

        if stocks:
            df = pd.DataFrame(stocks)
            _set_cache(cache_key, df)
            return df.copy()
    except Exception as e:
        print(f"[数据] 获取股票列表失败: {e}")

    return pd.DataFrame()


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
