"""V10 全市场扫描器 — 多策略 + 多线程 + 过滤"""
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from .data import get_stock_list, get_stock_history, get_realtime_quote, get_capital_flow
from .strategies import (
    STRATEGY_REGISTRY, V10Signal, PullbackSignal,
    scan_v10_full, scan_pullback,
)
from .trend_swing import scan_trend_swing
from .db import save_signal


def scan_single_stock(code: str, name: str, strategy_keys: list[str], params_dict: dict) -> list[dict]:
    """扫描单只股票的所有策略"""
    results = []

    try:
        # 获取K线数据（V10需要200+根）
        df = get_stock_history(code, days=350)
        if df.empty or len(df) < 50:
            return results

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
                results.append({
                    "type": "v10",
                    "code": code,
                    "name": name,
                    "strategy": "V10全买入",
                    "signal_type": signal.signal_type,
                    "price": signal.price,
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
    max_workers: int = 10,
    progress_callback=None,
    apply_filters: bool = True,
) -> list[dict]:
    """全市场扫描
    
    Args:
        strategy_keys: 策略列表
        params_dict: 策略参数
        stock_pool: 股票池（None=全市场）
        max_workers: 并发数
        progress_callback: 进度回调
        apply_filters: 是否应用资金面/基本面过滤
    """
    if params_dict is None:
        params_dict = {}

    # 获取股票池
    if stock_pool:
        codes = stock_pool
        names = {code: "" for code in codes}
        all_stocks = get_stock_list()
        if not all_stocks.empty:
            name_map = dict(zip(all_stocks["code"], all_stocks["name"]))
            names = {code: name_map.get(code, "") for code in codes}
    else:
        all_stocks = get_stock_list()
        if all_stocks.empty:
            return []
        codes = all_stocks["code"].tolist()
        names = dict(zip(all_stocks["code"], all_stocks["name"]))

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


def get_market_overview() -> dict:
    """获取市场概览"""
    all_stocks = get_stock_list()
    if all_stocks.empty:
        return {}

    up_count = len(all_stocks[all_stocks["pct_change"] > 0])
    down_count = len(all_stocks[all_stocks["pct_change"] < 0])
    limit_up = len(all_stocks[all_stocks["pct_change"] >= 9.9])
    limit_down = len(all_stocks[all_stocks["pct_change"] <= -9.9])

    return {
        "total": len(all_stocks),
        "up": up_count,
        "down": down_count,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "up_ratio": round(up_count / len(all_stocks) * 100, 1) if len(all_stocks) > 0 else 0,
    }
