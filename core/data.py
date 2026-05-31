"""数据获取模块 - 基于 akshare 的 A股数据接口（带缓存）"""
import time
import akshare as ak
import pandas as pd
from functools import lru_cache
from datetime import datetime, timedelta

# 内存缓存：{key: (timestamp, data)}
_cache: dict[str, tuple[float, pd.DataFrame]] = {}
CACHE_TTL = 300  # 5分钟缓存


def _get_cached(key: str) -> pd.DataFrame | None:
    """从缓存获取数据"""
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data.copy()
    return None


def _set_cache(key: str, data: pd.DataFrame):
    """写入缓存"""
    _cache[key] = (time.time(), data.copy())


def get_stock_list() -> pd.DataFrame:
    """获取全部A股列表（沪深主板+创业板+科创板）"""
    cache_key = "stock_list"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        df = ak.stock_zh_a_spot_em()
        # 标准化列名
        df = df.rename(columns={
            "代码": "code", "名称": "name",
            "最新价": "price", "涨跌幅": "pct_change",
            "涨跌额": "change", "成交量": "volume",
            "成交额": "amount", "振幅": "amplitude",
            "最高": "high", "最低": "low",
            "今开": "open", "昨收": "pre_close",
            "换手率": "turnover", "市盈率-动态": "pe",
            "市净率": "pb", "总市值": "market_cap",
            "流通市值": "float_cap",
        })
        # 过滤：只保留主板、创业板、科创板
        df = df[df["code"].str.match(r"^(00|30|60|68)\d{4}$")]
        _set_cache(cache_key, df)
        return df.copy()
    except Exception as e:
        print(f"[数据] 获取股票列表失败: {e}")
        return pd.DataFrame()


def get_stock_history(code: str, period: str = "daily", days: int = 120) -> pd.DataFrame:
    """获取个股历史K线数据
    
    Args:
        code: 股票代码 (如 '000001')
        period: 'daily' / 'weekly' / 'monthly'
        days: 获取天数
    """
    cache_key = f"history_{code}_{period}_{days}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        end = datetime.now().strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(
            symbol=code, period=period,
            start_date=start, end_date=end, adjust="qfq"
        )
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "成交额": "amount", "振幅": "amplitude",
            "涨跌幅": "pct_change", "涨跌额": "change",
            "换手率": "turnover",
        })
        df["date"] = pd.to_datetime(df["date"])
        _set_cache(cache_key, df)
        return df.copy()
    except Exception as e:
        print(f"[数据] 获取 {code} 历史数据失败: {e}")
        return pd.DataFrame()


def get_realtime_quotes(codes: list[str]) -> pd.DataFrame:
    """获取多只股票的实时行情"""
    all_stocks = get_stock_list()
    if all_stocks.empty:
        return pd.DataFrame()
    return all_stocks[all_stocks["code"].isin(codes)]


def get_sector_hot() -> pd.DataFrame:
    """获取板块热度排行"""
    cache_key = "sector_hot"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        df = ak.stock_board_concept_name_em()
        df = df.rename(columns={
            "板块名称": "name", "板块代码": "code",
            "最新价": "price", "涨跌幅": "pct_change",
            "总市值": "market_cap",
        })
        _set_cache(cache_key, df)
        return df.copy()
    except Exception as e:
        print(f"[数据] 获取板块数据失败: {e}")
        return pd.DataFrame()


def get_top_gainers(limit: int = 20) -> pd.DataFrame:
    """获取涨幅榜"""
    df = get_stock_list()
    if df.empty:
        return df
    return df.nlargest(limit, "pct_change")


def get_top_losers(limit: int = 20) -> pd.DataFrame:
    """获取跌幅榜"""
    df = get_stock_list()
    if df.empty:
        return df
    return df.nsmallest(limit, "pct_change")


def get_top_volume(limit: int = 20) -> pd.DataFrame:
    """获取成交额排行"""
    df = get_stock_list()
    if df.empty:
        return df
    return df.nlargest(limit, "amount")
