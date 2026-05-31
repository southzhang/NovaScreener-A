"""全市场扫描器 - 遍历A股运行选股策略"""
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from .data import get_stock_list, get_stock_history
from .strategies import STRATEGY_REGISTRY, StrategyResult
from .db import save_signal


def scan_single_stock(code: str, name: str, strategy_key: str, params: dict) -> StrategyResult | None:
    """扫描单只股票的单个策略"""
    try:
        df = get_stock_history(code, days=120)
        if df.empty or len(df) < 20:
            return None

        strategy_info = STRATEGY_REGISTRY.get(strategy_key)
        if not strategy_info:
            return None

        func = strategy_info["func"]
        triggered = func(df, params)

        if triggered:
            price = df["close"].iloc[-1]
            detail = f"触发{strategy_info['name']}策略"
            return StrategyResult(
                code=code, name=name,
                strategy=strategy_key,
                price=round(price, 2),
                detail=detail,
            )
    except Exception as e:
        print(f"[扫描] {code} {strategy_key} 出错: {e}")
    return None


def scan_market(
    strategy_keys: list[str],
    params_dict: dict[str, dict] | None = None,
    stock_pool: list[str] | None = None,
    max_workers: int = 8,
    progress_callback=None,
) -> list[StrategyResult]:
    """全市场策略扫描
    
    Args:
        strategy_keys: 要运行的策略key列表
        params_dict: {strategy_key: params} 覆盖默认参数
        stock_pool: 股票池（代码列表），None则扫描全市场
        max_workers: 并发数
        progress_callback: 进度回调 callback(current, total, code)
    
    Returns:
        触发信号的股票列表
    """
    if params_dict is None:
        params_dict = {}

    # 获取股票池
    if stock_pool:
        codes = stock_pool
        names = {code: "" for code in codes}
        # 尝试获取名称
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

    # 构建任务列表
    tasks = []
    for code in codes:
        for sk in strategy_keys:
            params = params_dict.get(sk, STRATEGY_REGISTRY.get(sk, {}).get("default_params", {}))
            tasks.append((code, names.get(code, ""), sk, params))

    # 并发执行
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(scan_single_stock, code, name, sk, params): (code, sk)
            for code, name, sk, params in tasks
        }
        seen_codes = set()
        for future in as_completed(futures):
            completed += 1
            code, sk = futures[future]
            if progress_callback and completed % 50 == 0:
                progress_callback(completed, len(tasks), code)
            try:
                result = future.result()
                if result and result.code not in seen_codes:
                    results.append(result)
                    seen_codes.add(result.code)
                    # 保存到数据库
                    save_signal(result.code, result.name, result.strategy, result.price, result.detail)
            except Exception as e:
                print(f"[扫描] 任务异常: {e}")

    return results


def scan_watchlist(strategy_keys: list[str], params_dict: dict[str, dict] | None = None) -> list[StrategyResult]:
    """扫描自选股"""
    from .db import get_watchlist
    watchlist = get_watchlist()
    if not watchlist:
        return []
    codes = [w["code"] for w in watchlist]
    return scan_market(strategy_keys, params_dict, stock_pool=codes)
