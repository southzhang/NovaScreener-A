"""数据获取模块 V10 — 完整数据源整合

数据源优先级：
- K线数据：新浪财经（免费稳定）> 腾讯K线（WAF封禁备用）> akshare（mini_racer不可用）
- 实时行情：腾讯行情 qt.gtimg.cn（免费无限制）
- 板块数据：问财(iwencai) > 东方财富 > 腾讯ETF降级
- 资金面：iFinD HTTP API > 10jqka > 缓存
- 基本面：iFinD HTTP API
"""
import time
import json
import subprocess
import numpy as np
import requests
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import os

# 代理清除（VPN会拦截请求）
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(k, None)
os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("NO_PROXY", "*")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 全局Session：TCP连接复用，减少TLS握手开销；禁用系统代理
_session = requests.Session()
_session.headers.update(HEADERS)
_session.trust_env = False  # 不走系统代理
_session.mount("https://", requests.adapters.HTTPAdapter(
    pool_connections=25, pool_maxsize=25, max_retries=0
))
_session.mount("http://", requests.adapters.HTTPAdapter(
    pool_connections=25, pool_maxsize=25, max_retries=0
))

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


# ===== 新浪K线（首选 — 腾讯fqkline已被WAF封禁）=====

def sina_klines(code: str, days: int = 250) -> pd.DataFrame:
    """新浪日K线（前复权），免费稳定，并发友好
    
    API: money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
    - scale=240 日K, datalen=数量
    - 返回字段: day, open, high, low, close, volume
    - 支持 sh/sz 前缀，并发0.1s/5只
    """
    cache_key = f"sina_kline_{code}_{days}"
    cached = _get_cached(cache_key)
    if cached is not None and isinstance(cached, pd.DataFrame):
        return cached

    # 前缀映射：6/68x=sh, 0/3=sz, 北交所不支持新浪K线
    if code.startswith("6"):
        prefix = "sh"
    elif code.startswith(("0", "3")):
        prefix = "sz"
    else:
        # 北交所暂无新浪K线支持，返回空
        return pd.DataFrame()
    symbol = f"{prefix}{code}"

    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={days}"

    for attempt in range(2):
        try:
            timeout = 10 if attempt == 1 else 8
            resp = _session.get(url, timeout=timeout)
            if resp.status_code != 200 or not resp.text.strip():
                if attempt == 0:
                    continue
                return pd.DataFrame()
            data = json.loads(resp.text)
            if not isinstance(data, list) or len(data) < 20:
                return pd.DataFrame()
            records = []
            for bar in data:
                try:
                    records.append({
                        "date": bar["day"],
                        "open": float(bar["open"]),
                        "close": float(bar["close"]),
                        "high": float(bar["high"]),
                        "low": float(bar["low"]),
                        "volume": float(bar["volume"]) if bar.get("volume") else 0,
                    })
                except (KeyError, ValueError, TypeError):
                    continue
            if not records:
                return pd.DataFrame()
            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            _set_cache(cache_key, df)
            return df.copy()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 0:
                continue
            return pd.DataFrame()
        except Exception as e:
            if attempt == 0:
                continue
            print(f"[数据] 新浪K线 {code} 失败: {e}")
            return pd.DataFrame()
    return pd.DataFrame()


# ===== 腾讯K线（备用 — web.ifzq.gtimg.cn 已被WAF封禁，仅做降级尝试）=====

def _parse_tencent_kline_resp(text: str, symbol: str) -> pd.DataFrame | None:
    """解析腾讯K线API响应，返回DataFrame或None（含防御性类型检查）"""
    try:
        # _var格式: kline_dayqfq={...json...}
        json_str = text.split('=', 1)[1] if '=' in text else text
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    sec_data = data.get("data", {})
    if not isinstance(sec_data, dict):
        return None
    stock_data = sec_data.get(symbol, {})
    if not isinstance(stock_data, dict):
        return None
    bars = stock_data.get("qfqday", []) or stock_data.get("day", [])
    if not bars:
        return None
    records = []
    for b in bars:
        try:
            records.append({
                "date": b[0],
                "open": float(b[1]),
                "close": float(b[2]),
                "high": float(b[3]),
                "low": float(b[4]),
                "volume": float(b[5]) if len(b) > 5 and b[5] else 0,
            })
        except (IndexError, ValueError):
            continue
    if not records:
        return None
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df


def tencent_klines(code: str, days: int = 250) -> pd.DataFrame:
    """腾讯前复权日K线（超时自动重试1次）"""
    cache_key = f"tencent_kline_{code}_{days}"
    cached = _get_cached(cache_key)
    if cached is not None and isinstance(cached, pd.DataFrame):
        return cached

    # 前缀映射：6/68x=sh, 0/3=sz, 83/87/43=bj(北交所)
    if code.startswith("6"):
        prefix = "sh"
    elif code.startswith(("0", "3")):
        prefix = "sz"
    else:
        prefix = "bj"
    symbol = f"{prefix}{code}"
    url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={symbol},day,,,{days},qfq"

    for attempt in range(2):  # 最多2次尝试
        try:
            timeout = 10 if attempt == 1 else 8  # 重试时给更长超时
            resp = _session.get(url, timeout=timeout)
            df = _parse_tencent_kline_resp(resp.text, symbol)
            if df is not None and len(df) >= 20:
                _set_cache(cache_key, df)
                return df.copy()
            # 解析成功但数据不足，不重试
            return pd.DataFrame()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 0:
                continue  # 重试1次
            return pd.DataFrame()
        except Exception as e:
            if attempt == 0:
                continue
            print(f"[数据] 腾讯K线 {code} 失败: {e}")
            return pd.DataFrame()
    return pd.DataFrame()


def akshare_klines(code: str, days: int = 250) -> pd.DataFrame:
    """akshare 日K线（备用）— mini_racer不可用时直接跳过"""
    # mini_racer 已卸载，akshare依赖它会报错，跳过避免5秒超时
    try:
        import py_mini_racer  # noqa: F401
    except ImportError:
        return pd.DataFrame()

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


def _is_trading_day() -> bool:
    """判断今天是否可能是交易日（工作日）
    
    简单判断：周一至周五。法定节假日无法精确判断，
    但腾讯行情有成交量>0可兜底。
    """
    from datetime import datetime
    return datetime.now().weekday() < 5


def _append_today_kline(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """盘中/盘后用腾讯实时行情拼一条当日K线到日K线末尾
    
    新浪日K线盘中不更新（只到上一交易日收盘），
    导致均线/趋势/信号全部滞后。用腾讯实时行情的
    开高低收+成交量拼一条当日K线，让V10信号反映今天。
    
    拼接条件：
    1. 今天是工作日（周末不需要拼）
    2. 新浪K线最后一条不是今天（避免重复）
    3. 腾讯实时行情有成交量>0（确认今天确实有交易）
    4. 实时行情OHLC与最后一条K线不完全一致（防止休市日缓存数据误拼）
    """
    if df.empty:
        return df
    if not _is_trading_day():
        return df
    # 检查最后一条是否已经是今天
    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    last_date = df["date"].iloc[-1]
    if isinstance(last_date, str):
        last_date = pd.Timestamp(last_date)
    if last_date.strftime("%Y-%m-%d") == today_str:
        return df  # 已有今天数据（腾讯K线可能直接返回今天）
    
    quote = get_realtime_quote(code)
    if not quote or not quote.get("price") or quote["price"] <= 0:
        return df
    
    # 成交量换算：腾讯返回"手"，新浪K线用"股"，需 ×100
    vol = quote.get("volume", 0)
    if vol <= 0:
        return df  # 没有成交量说明还没成交（节假日/非交易日）
    
    # 休市日防护：腾讯返回缓存数据OHLC与昨天K线完全一致→不拼
    last_bar = df.iloc[-1]
    if (last_bar["open"] == quote["open"] and
        last_bar["high"] == quote["high"] and
        last_bar["low"] == quote["low"] and
        abs(last_bar["close"] - quote["price"]) < 0.001):
        return df  # OHLC与昨天完全一致，今天是休市日，腾讯返回缓存
    
    today_bar = pd.DataFrame([{
        "date": pd.Timestamp(today_str),
        "open": quote["open"],
        "high": quote["high"],
        "low": quote["low"],
        "close": quote["price"],
        "volume": float(vol) * 100,  # 手→股
    }])
    
    return pd.concat([df, today_bar], ignore_index=True)


def get_stock_history(code: str, days: int = 250) -> pd.DataFrame:
    """获取K线（新浪优先，腾讯降级，akshare兜底）
    
    优先级变更：2026-06 腾讯 web.ifzq.gtimg.cn/fqkline 被WAF封禁返回501，
    新浪财经K线API成为首选数据源。
    
    盘中自动拼接当日K线（来自腾讯实时行情），确保信号实时。
    """
    df = sina_klines(code, days)
    if not df.empty and len(df) >= 20:
        df = _append_today_kline(df, code)
        return df
    df = tencent_klines(code, days)
    if not df.empty and len(df) >= 20:
        df = _append_today_kline(df, code)
        return df
    df = akshare_klines(code, days)
    if not df.empty and len(df) >= 20:
        df = _append_today_kline(df, code)
        return df
    return pd.DataFrame()


def get_kline(code: str, period: str = "day", count: int = 250) -> pd.DataFrame:
    """
    获取K线数据，支持日K/周K/月K
    period: "day" | "week" | "month"
    count: 请求的K线数量（周/月K会多取日线再重采样）
    """
    if period == "day":
        return get_stock_history(code, count)

    # 周K/月K: 先取日线再重采样
    multiplier = 5 if period == "week" else 22
    df = get_stock_history(code, count * multiplier + 10)
    if df.empty:
        return df

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")

    rule = "W" if period == "week" else "ME"
    resampled = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    resampled = resampled.tail(count).reset_index()
    resampled.columns = ["date", "open", "high", "low", "close", "volume"]
    return resampled


def get_stock_name(code: str) -> str:
    """获取股票名称"""
    quote = get_realtime_quote(code)
    if quote and quote.get("name"):
        return quote["name"]
    return code


# ===== 腾讯实时行情 =====

def get_realtime_quote(code: str) -> dict | None:
    """腾讯实时行情"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code}"

    try:
        resp = _session.get(url, timeout=5)
        resp.encoding = 'gbk'
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
            "change_amt": float(parts[31]) if parts[31] else 0,      # 涨跌额
            "volume": float(parts[36]) if parts[36] else 0,          # 成交量(手)
            "amount": float(parts[37]) if parts[37] else 0,          # 成交额(万元)
            "turnover": float(parts[38]) if parts[38] else 0,        # 换手率%
            "high": float(parts[33]) if parts[33] else 0,
            "low": float(parts[34]) if parts[34] else 0,
            "open": float(parts[5]) if parts[5] else 0,
            "pre_close": float(parts[4]) if parts[4] else 0,
            "pe": float(parts[39]) if len(parts) > 39 and parts[39] else 0,           # 市盈率
            "circ_market_cap": float(parts[44]) if len(parts) > 44 and parts[44] else 0,  # 流通市值(亿)
            "total_market_cap": float(parts[45]) if len(parts) > 45 and parts[45] else 0, # 总市值(亿)
            "limit_up": float(parts[47]) if len(parts) > 47 and parts[47] else 0,     # 涨停价
            "limit_down": float(parts[48]) if len(parts) > 48 and parts[48] else 0,   # 跌停价
        }
    except Exception as e:
        print(f"[数据] 腾讯行情 {code} 失败: {e}")
        return None


def get_realtime_quotes_batch(codes: list[str]) -> list[dict]:
    """批量获取实时行情（并行加速）"""
    if not codes:
        return []
    results = []
    with ThreadPoolExecutor(max_workers=min(len(codes), 10)) as pool:
        quotes = pool.map(get_realtime_quote, codes)
        for q in quotes:
            if q:
                results.append(q)
    return results


# ===== 股票列表（腾讯行情源）=====

# 常用股票池（备用，仅在API拉取失败时使用）
_STOCK_POOL_FALLBACK = [
    '600519', '601318', '600036', '601166', '600276', '600887', '601888', '600900',
    '601398', '601939', '600028', '601088', '600050', '601857', '600585', '601601',
    '600016', '601328', '601668', '600031', '601288', '600000', '600104', '600309',
    '000001', '000002', '000858', '000333', '000568', '000651', '000725', '000063',
    '002415', '002594', '002714', '002304', '000538', '000661', '002352',
    '300750', '300059', '300015', '300122', '300760', '300124', '300033', '300274',
]


def _parse_tencent_realtime_batch(raw: str) -> list[dict]:
    """解析腾讯qt.gtimg.cn批量返回"""
    stocks = []
    for line in raw.strip().split(';'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        try:
            parts = line.split('=')[1].strip('"').split('~')
            if len(parts) < 40:
                continue
            code = parts[2]
            name = parts[1]
            price = float(parts[3]) if parts[3] else 0
            if price <= 0:
                continue
            # 过滤ST/退市
            if 'ST' in name or '退' in name:
                continue
            # parts[37] = 成交额(万元) | parts[36] = 成交量(手)
            stocks.append({
                "code": code,
                "name": name,
                "price": price,
                "pct_change": float(parts[32]) if parts[32] else 0,
                "turnover": float(parts[38]) if parts[38] else 0,
                "volume": float(parts[36]) if parts[36] else 0,           # 成交量(手)
                "amount": float(parts[37]) if parts[37] else 0,           # 成交额(万元)
                "outer_vol": float(parts[7]) if parts[7] else 0,          # 外盘(手)
                "inner_vol": float(parts[8]) if parts[8] else 0,          # 内盘(手)
                "pe": float(parts[39]) if len(parts) > 39 and parts[39] else 0,           # 市盈率
                "circ_market_cap": float(parts[44]) if len(parts) > 44 and parts[44] else 0,  # 流通市值(亿)
                "total_market_cap": float(parts[45]) if len(parts) > 45 and parts[45] else 0, # 总市值(亿)
                "limit_up": float(parts[47]) if len(parts) > 47 and parts[47] else 0,     # 涨停价
                "limit_down": float(parts[48]) if len(parts) > 48 and parts[48] else 0,   # 跌停价
            })
        except Exception:
            continue
    return stocks


def get_stock_list() -> pd.DataFrame:
    """获取全市场A股列表（腾讯行情API批量拉取，并行加速）"""
    cache_key = "stock_list"
    cached = _get_cached(cache_key)
    if cached is not None and isinstance(cached, pd.DataFrame):
        return cached

    all_stocks = []

    # 沪深代码（密集号段，500/批高效）
    shsz_codes = []
    # 沪市主板 600000-605999 + 603000-603999（覆盖60xxxx主要号段）
    for i in range(600000, 606000):
        shsz_codes.append(f"sh{i:06d}")
    for i in range(603000, 604000):
        shsz_codes.append(f"sh{i:06d}")
    # 深市主板 000001-004999
    for i in range(1, 5000):
        shsz_codes.append(f"sz{i:06d}")
    # 创业板 300000-301999
    for i in range(300000, 302000):
        shsz_codes.append(f"sz{i:06d}")
    # 科创板 688000-689999
    for i in range(688000, 690000):
        shsz_codes.append(f"sh{i:06d}")

    # 北交所代码（稀疏号段，800/批压缩空号开销）
    bj_codes = []
    for i in range(830000, 840000):
        bj_codes.append(f"bj{i:06d}")
    for i in range(870000, 874000):
        bj_codes.append(f"bj{i:06d}")

    # 批量拉取：沪深500/批 + 北交所800/批，20线程并行
    shsz_batches = [shsz_codes[i:i + 500] for i in range(0, len(shsz_codes), 500)]
    bj_batches = [bj_codes[i:i + 800] for i in range(0, len(bj_codes), 800)]

    def _fetch_batch(batch_codes):
        qs = ",".join(batch_codes)
        url = f"https://qt.gtimg.cn/q={qs}"
        try:
            resp = _session.get(url, timeout=10)
            resp.encoding = 'gbk'
            return _parse_tencent_realtime_batch(resp.text)
        except Exception:
            return []

    all_stocks = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        for parsed in pool.map(_fetch_batch, shsz_batches + bj_batches):
            all_stocks.extend(parsed)

    if not all_stocks:
        # 降级到备用池
        print("[数据] 腾讯全量拉取失败，降级到备用股票池")
        for code in _STOCK_POOL_FALLBACK:
            quote = get_realtime_quote(code)
            if quote:
                all_stocks.append({
                    "code": code, "name": quote["name"],
                    "price": quote["price"], "pct_change": quote["pct_change"],
                    "turnover": quote["turnover"], "volume": quote["volume"],
                    "amount": quote["amount"],
                })

    if all_stocks:
        df = pd.DataFrame(all_stocks)
        # 基本过滤：只去掉停牌（无成交）的，保留低价股以统计完整市场
        df = df[df["volume"] > 0]
        _set_cache(cache_key, df)
        print(f"[数据] 获取到 {len(df)} 只有效股票")
        return df.copy()

    return pd.DataFrame()


# ===== 大盘指数 =====

# 主要指数代码（腾讯行情格式）
_INDEX_CODES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000688": "科创50",
}


def get_market_indices() -> list[dict]:
    """获取四大指数实时行情（腾讯API，单次请求）"""
    cache_key = "market_indices"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    secids = ",".join(_INDEX_CODES.keys())
    url = f"https://qt.gtimg.cn/q={secids}"
    try:
        resp = _session.get(url, timeout=5)
        resp.encoding = 'gbk'
        text = resp.text
        results = []
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            try:
                parts = line.split("=")[1].strip('"').split("~")
                if len(parts) < 40:
                    continue
                secid = line.split("=")[0].split("_")[-1].split(".")[-1] if "_" in line.split("=")[0] else ""
                # 从腾讯返回的v_字段中提取secid
                var_part = line.split("=")[0]
                # var_part 如: v_sh000001
                raw_code = var_part.replace("v_", "").strip()
                name = _INDEX_CODES.get(raw_code, parts[1] if len(parts) > 1 else "")
                price = float(parts[3]) if parts[3] else 0
                pct_change = float(parts[32]) if parts[32] else 0
                pre_close = float(parts[4]) if parts[4] else 0
                change = round(price - pre_close, 2) if pre_close > 0 else 0
                results.append({
                    "code": raw_code,
                    "name": name,
                    "price": price,
                    "change": change,
                    "pct_change": pct_change,
                    "high": float(parts[33]) if parts[33] else 0,
                    "low": float(parts[34]) if parts[34] else 0,
                    "amount": float(parts[37]) if parts[37] else 0,
                })
            except (ValueError, IndexError):
                continue
        _set_cache(cache_key, results)
        return results
    except Exception as e:
        print(f"[数据] 获取指数行情失败: {e}")
        return []


# ===== 板块数据 =====

# 问财(iwencai)板块数据 — 优先数据源
_IWENCAI_CLI = os.path.expanduser("~/Projects/quant-watchdog/skills/hithink-sector-selector/scripts/cli.py")
_iwencai_sector_cache = {}     # {板块名: 涨幅%}
_iwencai_sector_cache_ts = 0   # 缓存时间戳
_iwencai_stock_cache = {}      # {code: 一级行业}
_iwencai_stock_cache_ts = 0


def _iwencai_query(query: str, limit: int = 20) -> dict | None:
    """调用问财CLI查询"""
    if not os.path.exists(_IWENCAI_CLI):
        return None
    try:
        result = subprocess.run(
            ["python3", _IWENCAI_CLI, "--query", query, "--limit", str(limit)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if data.get("success"):
                return data
    except Exception:
        pass
    return None


def _get_iwencai_sector_ranking(limit: int = 20) -> dict:
    """问财获取行业板块涨幅排名 → {板块名: 涨幅%}
    同时包含三级行业和一级行业（从三级行业汇总），方便个股匹配
    """
    global _iwencai_sector_cache, _iwencai_sector_cache_ts
    # 5分钟缓存
    if _iwencai_sector_cache and time.time() - _iwencai_sector_cache_ts < 300:
        return _iwencai_sector_cache

    result = _iwencai_query("今日涨幅最大的行业板块", limit=limit)
    if not result:
        result = _iwencai_query("涨幅前N的行业板块", limit=limit)
    if not result:
        return _iwencai_sector_cache  # 返回旧缓存或空dict

    ranking = {}
    # 一级行业汇总: {一级行业: [涨幅列表]}
    level1_groups = {}
    for item in result.get("datas", []):
        name = item.get("指数简称", "")
        change = item.get("最新涨跌幅:前复权") or item.get("涨跌幅") or 0
        itype = item.get("指数类型", "")
        if name and change:
            try:
                pct = float(change)
                ranking[name] = pct
                # 如果是同花顺三级行业，查一下它的父行业
                # 通过问财的个股行业映射反推不太现实
                # 直接把排名里的三级行业也用一级行业名加入
                # 例如: "铜"→"有色金属", "钴"→"有色金属"
                # 我们需要额外查询来建立这个映射
            except (ValueError, TypeError):
                pass

    # 查排名里三级行业对应的一级行业
    # 用排名里的板块名查所属行业（问财会返回该板块的代表性股票）
    if ranking:
        top_names = list(ranking.keys())[:10]  # 只查前10
        query = "、".join(top_names) + "所属行业"
        data = _iwencai_query(query, limit=10)
        if data:
            for item in data.get("datas", []):
                industries = item.get("所属同花顺行业", [])
                if isinstance(industries, list) and len(industries) >= 1:
                    level1 = industries[0]  # 一级行业，如"有色金属"
                    # 匹配排名名：三级行业名在industries列表中
                    level3 = industries[-1] if len(industries) >= 3 else industries[-1]
                    if level3 in ranking:
                        if level1 not in level1_groups:
                            level1_groups[level1] = []
                        level1_groups[level1].append(ranking[level3])

    # 把一级行业的平均涨幅加入排名
    for level1, changes in level1_groups.items():
        if changes and level1 not in ranking:
            ranking[level1] = round(sum(changes) / len(changes), 2)

    if ranking:
        _iwencai_sector_cache = ranking
        _iwencai_sector_cache_ts = time.time()
    return _iwencai_sector_cache


def _get_iwencai_stock_sectors(codes: list[str]) -> dict:
    """问财批量获取股票所属行业 → {code: 一级行业}"""
    global _iwencai_stock_cache, _iwencai_stock_cache_ts
    # 30分钟缓存
    if _iwencai_stock_cache and time.time() - _iwencai_stock_cache_ts < 1800:
        return _iwencai_stock_cache

    result_map = {}
    batch_size = 15
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        query = "、".join(batch) + "所属行业板块"
        data = _iwencai_query(query, limit=batch_size)
        if not data:
            continue
        for item in data.get("datas", []):
            code_raw = item.get("股票代码", "")
            code = code_raw.replace(".SH", "").replace(".SZ", "")
            industries = item.get("所属同花顺行业", [])
            if isinstance(industries, list) and industries:
                result_map[code] = industries  # 返回全部层级[一级行业, 二级行业, 三级行业]
            elif isinstance(industries, str):
                result_map[code] = [industries]
        time.sleep(0.3)

    if result_map:
        _iwencai_stock_cache = result_map
        _iwencai_stock_cache_ts = time.time()
    return result_map

# 缓存板块排名
_sector_cache = {}
_sector_cache_ts = 0


def get_sector_ranking(limit: int = 30) -> list[dict]:
    """获取板块涨幅排名（问财优先，东方财富fallback）
    返回: [{'name': 板块名, 'code': 代码, 'change_pct': 涨幅, 'type': 类型}, ...]
    """
    # 1) 问财优先
    iwencai_rank = _get_iwencai_sector_ranking(limit)
    if iwencai_rank:
        return [
            {"name": name, "code": "", "change_pct": pct, "type": "问财行业"}
            for name, pct in sorted(iwencai_rank.items(), key=lambda x: x[1], reverse=True)[:limit]
        ]

    # 2) 东方财富fallback
    global _sector_cache, _sector_cache_ts
    import time
    if _sector_cache and time.time() - _sector_cache_ts < 300:
        return _sector_cache.get("ranking", [])[:limit]

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    ranking = []
    for fs_type, type_name in [("m:90+t:2", "行业"), ("m:90+t:3", "概念")]:
        params = {
            "pn": 1, "pz": 30, "po": 1, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": fs_type,
            "fields": "f2,f3,f4,f12,f14",
        }
        try:
            resp = _session.get(url, params=params, timeout=10)
            data = resp.json()
            for item in data.get("data", {}).get("diff", []):
                ranking.append({
                    "name": item.get("f14", ""),
                    "code": item.get("f12", ""),
                    "change_pct": item.get("f3", 0),
                    "type": type_name,
                })
        except Exception:
            continue

    ranking.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    _sector_cache = {"ranking": ranking}
    _sector_cache_ts = time.time()
    return ranking[:limit]


def get_stock_sectors(code: str) -> list[str]:
    """获取股票所属板块（问财优先，东方财富F10 fallback）
    返回所有层级行业名（一级行业优先），用于板块评分匹配
    """
    # 1) 问财优先（返回全部层级：一级行业、二级行业、三级行业）
    if _iwencai_stock_cache and code in _iwencai_stock_cache:
        sectors = _iwencai_stock_cache[code]
        if isinstance(sectors, list):
            return sectors
        elif isinstance(sectors, str):
            return [sectors]

    # 2) 内存缓存
    cache_key = f"sectors_{code}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    # 3) 东方财富F10
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
        "columns": "BOARD_NAME,BOARD_CODE,BOARD_TYPE",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageSize": 30,
    }
    try:
        resp = _session.get(url, params=params, timeout=10)
        data = resp.json()
        items = data.get("result", {}).get("data", [])
        sectors = [item.get("BOARD_NAME", "") for item in items if item.get("BOARD_NAME")]
        _set_cache(cache_key, sectors)
        return sectors
    except Exception:
        pass

    return []


def get_sector_score(code: str) -> float:
    """计算板块风口得分（0-10分）
    股票所属板块在涨幅排名前10 → +10分
    前20 → +7分
    前30 → +4分
    不在前30 → 0分
    
    匹配策略：先精确匹配，再模糊匹配（包含关系）
    """
    sectors = get_stock_sectors(code)
    if not sectors:
        return 0

    ranking = get_sector_ranking(limit=50)
    if not ranking:
        return 0

    # 找股票所属板块在排名中的位置
    best_rank = 999
    for sector_name in sectors:
        for rank_idx, r in enumerate(ranking):
            rname = r.get("name", "")
            # 精确匹配
            if sector_name == rname:
                best_rank = min(best_rank, rank_idx)
                break
            # 包含匹配（双向）
            if sector_name in rname or rname in sector_name:
                best_rank = min(best_rank, rank_idx)
                break
            # 行业归属匹配：同花顺三级行业和一级行业的对应
            # 如 "锂" 属于 "有色金属"，"铜" 属于 "有色金属"
            # 排名里的三级行业如果属于同一一级行业，也算匹配
            if len(sectors) >= 2:
                # sectors[0] 是一级行业，如"有色金属"
                # 排名里的"铜"、"锂"可能是同属一级行业的三级行业
                top_level = sectors[0]
                if top_level and (top_level in rname or rname in top_level):
                    best_rank = min(best_rank, rank_idx)
                    break

    if best_rank < 10:
        return 10
    elif best_rank < 20:
        return 7
    elif best_rank < 30:
        return 4
    else:
        return 0


# ===== 资金面数据 =====

def get_capital_flow(code: str) -> dict | None:
    """获取资金面数据
    腾讯行情:
    - field[7] = 外盘(手) — 主动买入
    - field[8] = 内盘(手) — 主动卖出
    - 用外盘/内盘比例判断资金方向
    - field[44] = 总成交额(万元)
    """
    cache_key = f"capital_flow_{code}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    try:
        resp = _session.get(url, timeout=5)
        resp.encoding = 'gbk'
        text = resp.text
        if "=" in text:
            parts = text.split("=")[1].strip('";\n').split("~")
            if len(parts) > 50:
                buy_vol = float(parts[7]) if parts[7] else 0   # 外盘(手)
                sell_vol = float(parts[8]) if parts[8] else 0  # 内盘(手)
                total_vol = buy_vol + sell_vol
                # 买盘占比
                buy_ratio = buy_vol / total_vol * 100 if total_vol > 0 else 50
                # 推算主力净流入(万元): 用成交额 × 买卖差比例
                amount = float(parts[37]) if parts[37] else 0  # 成交额(万元)
                net_inflow = amount * (buy_ratio - 50) / 100

                result = {
                    "main_net_inflow": round(net_inflow, 2),  # 万元
                    "buy_ratio": round(buy_ratio, 1),  # 买盘占比%
                    "buy_vol": buy_vol,
                    "sell_vol": sell_vol,
                    "name": parts[1] if len(parts) > 1 else code,
                    "source": "tencent_buy_sell_ratio",
                }
                _set_cache(cache_key, result)
                return result
    except Exception:
        pass

    return {"main_net_inflow": 0, "buy_ratio": 50, "name": code}


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

def get_top_gainers(limit: int = 20, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """涨幅榜（接收已拉取的DataFrame，避免重复请求）"""
    if df is None:
        df = get_stock_list()
    if df.empty:
        return df
    return df.nlargest(limit, "pct_change")


def get_top_losers(limit: int = 20, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """跌幅榜（接收已拉取的DataFrame，避免重复请求）"""
    if df is None:
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


# ===== 盘口数据（买卖五档） =====

def get_order_book(code: str) -> dict | None:
    """获取买卖五档盘口数据（腾讯完整行情接口的[9]-[28]字段）
    返回: {bid1-bid5: (价格, 量), ask1-ask5: (价格, 量), ...}
    也可获取s_pk接口的委比数据: {commission_ratio, commission_diff, inner_ratio, outer_ratio}
    """
    prefix = "sh" if code.startswith("6") else "sz"

    # 买卖五档从完整行情接口获取（字段9-28）
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    try:
        resp = _session.get(url, timeout=5)
        resp.encoding = 'gbk'
        text = resp.text
        if "=" not in text:
            return None
        parts = text.split("=")[1].strip('";\n').split("~")
        if len(parts) < 29:
            return None

        result = {
            "code": code,
            "name": parts[1] if len(parts) > 1 else "",
            "price": float(parts[3]) if parts[3] else 0,
        }
        # 买盘 [9]买一量 [10]买一价 [11]买二量 [12]买二价 ... [17]买五量 [18]买五价
        for i in range(5):
            qty_idx = 9 + i * 2
            price_idx = 10 + i * 2
            if len(parts) > price_idx:
                result[f"bid{i+1}"] = (
                    float(parts[price_idx]) if parts[price_idx] else 0,
                    int(float(parts[qty_idx])) if parts[qty_idx] else 0,
                )
        # 卖盘 [19]卖一量 [20]卖一价 [21]卖二量 [22]卖二价 ... [27]卖五量 [28]卖五价
        for i in range(5):
            qty_idx = 19 + i * 2
            price_idx = 20 + i * 2
            if len(parts) > price_idx:
                result[f"ask{i+1}"] = (
                    float(parts[price_idx]) if parts[price_idx] else 0,
                    int(float(parts[qty_idx])) if parts[qty_idx] else 0,
                )

        # 委比数据（s_pk接口: 委比~委差~内盘比~外盘比）
        try:
            pk_url = f"https://qt.gtimg.cn/q=s_pk{prefix}{code}"
            pk_resp = _session.get(pk_url, timeout=3)
            pk_resp.encoding = 'gbk'
            pk_text = pk_resp.text
            if "=" in pk_text:
                pk_parts = pk_text.split("=")[1].strip('";\n').split("~")
                if len(pk_parts) >= 4:
                    result["commission_ratio"] = float(pk_parts[0]) if pk_parts[0] else 0
                    result["commission_diff"] = float(pk_parts[1]) if pk_parts[1] else 0
                    result["inner_ratio"] = float(pk_parts[2]) if pk_parts[2] else 0
                    result["outer_ratio"] = float(pk_parts[3]) if pk_parts[3] else 0
        except Exception:
            pass  # 委比数据非关键，失败不影响

        _set_cache(f"orderbook_{code}", result)
        return result
    except Exception as e:
        print(f"[数据] 盘口数据 {code} 失败: {e}")
        return None


# ===== 简要行情（轻量轮询） =====

def get_quote_brief(code: str) -> dict | None:
    """获取简要行情（腾讯s_接口，数据量小，适合高频轮询）
    返回: {code, name, price, change_pct} 等核心字段
    """
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://qt.gtimg.cn/q=s_{prefix}{code}"
    try:
        resp = _session.get(url, timeout=5)
        resp.encoding = 'gbk'
        text = resp.text
        if "=" not in text:
            return None
        # s_接口返回格式: v_s_sz000001="1~平安银行~000001~11.07~0.82~..."
        # [1]名称 [2]代码 [3]现价 [4]涨跌额 [5]涨跌幅% [6]成交量(手) [7]成交额(万)
        parts = text.split("=")[1].strip('";\n').split("~")
        if len(parts) < 8:
            return None
        return {
            "code": parts[2] if len(parts) > 2 else code,
            "name": parts[1] if len(parts) > 1 else "",
            "price": float(parts[3]) if parts[3] else 0,
            "change_amt": float(parts[4]) if parts[4] else 0,
            "change_pct": float(parts[5]) if parts[5] else 0,
            "volume": int(float(parts[6])) if parts[6] else 0,     # 手
            "amount": float(parts[7]) if parts[7] else 0,          # 万元
        }
    except Exception as e:
        print(f"[数据] 简要行情 {code} 失败: {e}")
        return None
