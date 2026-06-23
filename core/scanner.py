"""V10 全市场扫描器 — 多策略 + 多线程 + 过滤"""
from __future__ import annotations
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from .data import get_stock_list, get_stock_history, get_realtime_quote, get_realtime_quotes_batch, get_capital_flow, clear_data_cache, _is_trading_session
from .strategies import (
    STRATEGY_REGISTRY, V10Signal, PullbackSignal,
    scan_v10_full, scan_pullback,
)
from .trend_swing import scan_trend_swing
from .db import save_signal


def scan_single_stock(code: str, name: str, strategy_keys: list[str], params_dict: dict) -> list[dict]:
    """扫描单只股票的所有策略（增强版：盘中自动使用实时行情）"""
    results = []

    try:
        # 盘中扫描：先清K线缓存确保获取最新数据
        rt_key = f"rt_kline_{code}_250"
        if _is_trading_session():
            clear_data_cache(rt_key)
        
        # 获取K线数据（V10需要200+根，250够用，盘中自动拼接当日K线）
        df = get_stock_history(code, days=250, use_rt_cache=False)
        if df.empty or len(df) < 50:
            return results
        
        # 获取实时行情覆写最新价格
        rt_quote = get_realtime_quote(code)
        rt_price = rt_quote["price"] if rt_quote and rt_quote.get("price", 0) > 0 else df["close"].values[-1]
        rt_pct = rt_quote["pct_change"] if rt_quote else 0

        # 转numpy数组
        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)
        open_p = df["open"].values.astype(np.float64)

        # V10全买入
        if "v10_full" in strategy_keys and len(close) >= 200:
            signal = scan_v10_full(close, high, low, volume, open_p)
            if signal:
                signal.code = code
                signal.name = name
                # 用实时行情覆写信号价格
                signal_price = rt_price
                results.append({
                    "type": "v10",
                    "code": code,
                    "name": name,
                    "strategy": "V10全买入",
                    "signal_type": signal.signal_type,
                    "price": signal_price,
                    "score": signal.score,
                    "detail": signal.detail,
                    "tags": signal.tags,
                })

        # 波段回调
        if "pullback" in strategy_keys and len(close) >= 50:
            signal = scan_pullback(close, high, low, volume)
            if signal and signal.score >= 4:
                signal.code = code
                signal.name = name
                results.append({
                    "type": "pullback",
                    "code": code,
                    "name": name,
                    "strategy": "波段回调",
                    "level": signal.level,
                    "price": signal.price,
                    "score": signal.score,
                    "detail": signal.detail,
                    "tags": signal.tags,
                })

        # 趋势波段
        if "trend_swing" in strategy_keys and len(close) >= 150:
            signal = scan_trend_swing(close, high, low, volume, open_p)
            if signal:
                signal.code = code
                signal.name = name
                results.append({
                    "type": "pullback",
                    "code": code,
                    "name": name,
                    "strategy": "趋势波段",
                    "level": "⭐ 趋势波段" if signal.score >= 70 else "🟡 观察",
                    "price": signal.price,
                    "score": signal.score,
                    "detail": signal.detail,
                    "tags": signal.tags,
                })

        # 经典策略
        for sk in strategy_keys:
            if sk in ["v10_full", "pullback"]:
                continue
            info = STRATEGY_REGISTRY.get(sk)
            if not info or not info.get("func"):
                continue

            params = params_dict.get(sk, info.get("default_params", {}))
            try:
                triggered = info["func"](close, high, low, volume, open_p, params)
                if triggered:
                    results.append({
                        "type": "classic",
                        "code": code,
                        "name": name,
                        "strategy": info["name"],
                        "price": round(close[-1], 2),
                        "score": 50,
                        "detail": {},
                        "tags": [info["name"]],
                    })
            except Exception:
                continue

        # 保存信号到数据库
        for r in results:
            # 计算等级
            score = r.get("score", 0)
            if score >= 80:
                grade = "🔴 强推"
            elif score >= 60:
                grade = "🟠 关注"
            elif score >= 40:
                grade = "🟡 观察"
            else:
                grade = "⚪ 弱势"
            save_signal(r["code"], r["name"], r["strategy"], r["price"], str(r.get("detail", "")), score, grade)

    except Exception as e:
        print(f"[扫描] {code} 出错: {e}")

    return results


def scan_market(
    strategy_keys: list[str],
    params_dict: dict[str, dict] | None = None,
    stock_pool: list[str] | None = None,
    max_workers: int = 25,
    progress_callback=None,
    apply_filters: bool = True,
) -> list[dict]:
    """全市场扫描（粗筛+精扫）
    
    粗筛：用实时行情过滤低成交额/低价/ST股，大幅减少K线拉取量
    精扫：只对粗筛通过的股票拉K线做策略分析
    
    Args:
        strategy_keys: 策略列表
        params_dict: 策略参数
        stock_pool: 股票池（None=全市场）
        max_workers: 并发数（默认25，腾讯K线API甜区）
        progress_callback: 进度回调
        apply_filters: 是否应用资金面/基本面过滤
    """
    if params_dict is None:
        params_dict = {}
    
    # 盘中扫描开始前清空K线缓存，确保使用最新行情
    if _is_trading_session():
        clear_data_cache("rt_kline_")
        print("[扫描] 盘中模式：已清空K线缓存，使用实时行情")

    # 获取股票池
    all_stocks = get_stock_list()
    if all_stocks.empty:
        return []

    if stock_pool:
        # 指定股票池：只保留指定的
        codes = stock_pool
        names = dict(zip(all_stocks["code"], all_stocks["name"]))
        names = {c: names.get(c, "") for c in codes}
    else:
        codes = all_stocks["code"].tolist()
        names = dict(zip(all_stocks["code"], all_stocks["name"]))

    # 粗筛：基于实时行情快速过滤（不做K线请求）
    if not stock_pool and apply_filters and len(codes) > 500:
        pre = all_stocks[all_stocks["code"].isin(codes)].copy()
        # 过滤ST/退市
        pre = pre[~pre["name"].str.contains("ST|退", na=False)]
        # 过滤停牌（成交额=0）
        pre = pre[pre["amount"] > 0]
        # 过滤低价股
        pre = pre[pre["price"] >= 5]
        # 过滤低成交额（< 2000万）— V10需要一定活跃度
        if "amount" in pre.columns:
            pre = pre[pre["amount"] >= 2000]
        
        total_after_filter = len(pre)
        # 成交额Top 1500进入精扫（覆盖绝大多数V10候选）
        # 超过1500只时按成交额截断，避免K线请求过多
        SCAN_TOP_N = 1500
        if total_after_filter > SCAN_TOP_N:
            pre = pre.nlargest(SCAN_TOP_N, "amount")
        codes = pre["code"].tolist()
        names = dict(zip(pre["code"], pre["name"]))
        print(f"[扫描] 粗筛: {len(all_stocks)} → {total_after_filter}（过滤后）→ {len(codes)} 只（Top {SCAN_TOP_N}）")

    # 过滤ST和退市股
    codes = [c for c in codes if "ST" not in names.get(c, "") and "退市" not in names.get(c, "")]

    results = []
    total = len(codes)
    completed = 0
    _lock = __import__('threading').Lock()

    def _progress():
        nonlocal completed
        completed += 1
        if progress_callback and completed % 50 == 0:
            progress_callback(completed, total)

    # 并发扫描
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(scan_single_stock, code, names.get(code, ""), strategy_keys, params_dict): code
            for code in codes
        }
        for future in as_completed(futures):
            _progress()
            try:
                stock_results = future.result()
                if stock_results:
                    with _lock:
                        results.extend(stock_results)
            except Exception as e:
                print(f"[扫描] 异常: {e}")

    # 按评分排序
    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    return results


def scan_watchlist(strategy_keys: list[str], params_dict: dict[str, dict] | None = None) -> list[dict]:
    """扫描自选股"""
    from .db import get_watchlist
    watchlist = get_watchlist()
    if not watchlist:
        return []
    codes = [w["code"] for w in watchlist]
    return scan_market(strategy_keys, params_dict, stock_pool=codes)


def get_market_overview(df: pd.DataFrame | None = None) -> dict:
    """获取市场概览（接收已拉取的DataFrame，避免重复请求）"""
    if df is None:
        from .data import get_stock_list
        df = get_stock_list()
    if df.empty:
        return {}

    up_count = len(df[df["pct_change"] > 0])
    down_count = len(df[df["pct_change"] < 0])
    flat_count = len(df[df["pct_change"] == 0])
    total = len(df)

    # 优先用精确涨跌停价判断，降级到涨跌幅近似
    if "limit_up" in df.columns and "limit_down" in df.columns and "price" in df.columns:
        _valid_up = df["limit_up"] > 0
        _valid_down = df["limit_down"] > 0
        _hit_up = (df["price"] >= df["limit_up"]) & _valid_up
        _hit_down = (df["price"] <= df["limit_down"]) & _valid_down
        limit_up = int(_hit_up.sum()) if _valid_up.any() else len(df[df["pct_change"] >= 9.9])
        limit_down = int(_hit_down.sum()) if _valid_down.any() else len(df[df["pct_change"] <= -9.9])
    else:
        limit_up = len(df[df["pct_change"] >= 9.9])
        limit_down = len(df[df["pct_change"] <= -9.9])

    return {
        "total": total,
        "up": up_count,
        "down": down_count,
        "flat": flat_count,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "up_ratio": round(up_count / total * 100, 1) if total > 0 else 0,
        "down_ratio": round(down_count / total * 100, 1) if total > 0 else 0,
    }
