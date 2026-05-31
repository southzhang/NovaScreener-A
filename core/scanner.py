"""全市场扫描器 — V10 通达信公式 + 多线程并发"""
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from .data import get_stock_list, get_stock_history
from .strategies import STRATEGY_REGISTRY, StrategyResult, scan_v10_full
from .db import save_signal


def scan_single_stock_v10(code: str, name: str) -> list[StrategyResult]:
    """V10 全买入公式扫描单只股票"""
    results = []
    try:
        df = get_stock_history(code, days=350)  # V10需要200+根K线
        if df.empty or len(df) < 200:
            return results

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)
        open_p = df["open"].values.astype(np.float64)

        ret = scan_v10_full(close, high, low, volume, open_p)
        if ret is None:
            return results

        signals, info = ret
        if signals:
            price = close[-1]
            for sig in signals:
                detail_parts = []
                if info.get('隧道多头'): detail_parts.append("隧道多头")
                if info.get('MACD金叉'): detail_parts.append("MACD金叉")
                if info.get('强庄信号'): detail_parts.append("强庄控盘")
                if info.get('放量'): detail_parts.append("放量")
                detail = " | ".join(detail_parts) if detail_parts else sig

                r = StrategyResult(
                    code=code, name=name,
                    strategy="v10_full",
                    price=round(price, 2),
                    detail=detail,
                    info={**info, "signal_type": sig},
                )
                results.append(r)
                save_signal(code, name, f"v10_{sig}", price, detail)
    except Exception as e:
        print(f"[V10扫描] {code} 出错: {e}")
    return results


def scan_single_stock_classic(code: str, name: str, strategy_key: str, params: dict) -> StrategyResult | None:
    """经典策略扫描单只股票"""
    try:
        df = get_stock_history(code, days=150)
        if df.empty or len(df) < 20:
            return None

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)
        open_p = df["open"].values.astype(np.float64)

        info = STRATEGY_REGISTRY.get(strategy_key)
        if not info or not info.get("func"):
            return None

        triggered = info["func"](close, high, low, volume, open_p, params)
        if triggered:
            return StrategyResult(
                code=code, name=name,
                strategy=strategy_key,
                price=round(close[-1], 2),
                detail=f"触发{info['name']}",
            )
    except Exception as e:
        print(f"[扫描] {code} {strategy_key} 出错: {e}")
    return None


def scan_market(
    strategy_keys: list[str],
    params_dict: dict[str, dict] | None = None,
    stock_pool: list[str] | None = None,
    max_workers: int = 10,
    progress_callback=None,
) -> list[StrategyResult]:
    """全市场扫描
    
    如果 strategy_keys 包含 v10_full，使用 V10 全买入公式
    否则使用经典策略
    """
    if params_dict is None:
        params_dict = {}

    use_v10 = "v10_full" in strategy_keys
    classic_keys = [k for k in strategy_keys if k != "v10_full"]

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

    results: list[StrategyResult] = []
    total = len(codes)
    completed = 0
    _lock = __import__('threading').Lock()

    def _progress():
        nonlocal completed
        completed += 1
        if progress_callback and completed % 100 == 0:
            progress_callback(completed, total, "")

    if use_v10:
        # V10 全买入扫描（需要更多历史数据）
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(scan_single_stock_v10, code, names.get(code, "")): code
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
                    print(f"[V10扫描] 异常: {e}")

    if classic_keys:
        # 经典策略扫描
        tasks = []
        for code in codes:
            for sk in classic_keys:
                params = params_dict.get(sk, STRATEGY_REGISTRY.get(sk, {}).get("default_params", {}))
                tasks.append((code, names.get(code, ""), sk, params))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(scan_single_stock_classic, code, name, sk, params): code
                for code, name, sk, params in tasks
            }
            for future in as_completed(futures):
                _progress()
                try:
                    result = future.result()
                    if result:
                        with _lock:
                            results.append(result)
                            save_signal(result.code, result.name, result.strategy, result.price, result.detail)
                except Exception:
                    pass

    return results


def scan_watchlist(strategy_keys: list[str], params_dict: dict[str, dict] | None = None) -> list[StrategyResult]:
    """扫描自选股"""
    from .db import get_watchlist
    watchlist = get_watchlist()
    if not watchlist:
        return []
    codes = [w["code"] for w in watchlist]
    return scan_market(strategy_keys, params_dict, stock_pool=codes)
