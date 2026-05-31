#!/usr/bin/env python3
"""
V10 资金面验证模块
根据主力净流入(main_net_inflow) > 0 过滤股票。
先查本地缓存 ~/.hermes/cache/capital_flow.json，未命中的股票用 iFinD HTTP API 实时查询。
返回 {"passed": [...], "excluded": [{"code", "reason"}], "stats": {...}}。
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

CACHE_PATH = Path.home() / ".hermes" / "cache" / "capital_flow.json"


def _strip_suffix(code: str) -> str:
    """600936.SH -> 600936"""
    return code.split(".")[0]


def _load_cache() -> dict:
    """加载资金面缓存文件，返回 {stock_code: {name, main_net_inflow, ...}} 或空 dict。"""
    if not CACHE_PATH.exists():
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("dimensions", {}).get("capital_flow", {})
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def _query_ifind_realtime(codes: list[str]) -> dict[str, dict]:
    """
    用 iFinD HTTP API 实时查询股票主力净流入。
    codes: 带后缀的代码列表，如 ['600936.SH']
    返回 {code: {name, main_net_inflow, ...}} 或 {}。
    """
    if not codes:
        return {}
    try:
        api_dir = str(Path.home() / ".hermes" / "scripts")
        if api_dir not in sys.path:
            sys.path.insert(0, api_dir)
        from ifind_http_api import iFinD  # type: ignore

        df = iFinD.stock_snapshot_batch(codes, ["main_net_inflow"])
        if df is None or isinstance(df, dict) or df.empty:
            return {}

        result = {}
        for _, row in df.iterrows():
            code = str(row.get("thscode", row.iloc[0])).strip()
            # 尝试从 table.main_net_inflow 或 main_net_inflow 列取值
            inflow = None
            for col in ["table.main_net_inflow", "main_net_inflow"]:
                if col in df.columns:
                    val = row.get(col)
                    if val is not None:
                        try:
                            if isinstance(val, list):
                                inflow = float(val[0]) if val else None
                            else:
                                inflow = float(val)
                        except (TypeError, ValueError, IndexError):
                            pass
                    break
            result[code] = {"name": code, "main_net_inflow": inflow, "source": "ifind_realtime"}
        return result
    except Exception as e:
        print(f"[v10_capital_filter] iFinD 实时查询失败: {e}", file=sys.stderr)
        return {}


def filter_by_capital_flow(stocks: list[str]) -> dict[str, Any]:
    """
    对股票列表做资金面验证：主力净流入 > 0 才通过。

    参数:
        stocks: 股票代码列表，如 ['600936.SH', '000001.SZ']
               也支持无后缀代码如 ['600936']（会自动匹配缓存）

    返回:
        {
            "passed": ["600936.SH", ...],
            "excluded": [
                {"code": "000001.SZ", "reason": "主力净流入 <= 0 (xxx)"},
                {"code": "600000.SH", "reason": "无法获取资金面数据"},
            ],
            "stats": {"total": 10, "passed": 7, "excluded": 3}
        }
    """
    if not stocks:
        return {"passed": [], "excluded": [], "stats": {"total": 0, "passed": 0, "excluded": 0}}

    # 去重保持顺序
    seen = set()
    unique_codes = []
    for c in stocks:
        code = str(c).strip()
        if code and code not in seen:
            seen.add(code)
            unique_codes.append(code)

    # 1. 加载缓存
    cache = _load_cache()

    # 2. 分离已缓存和未缓存的股票（缓存 key 为无后缀代码）
    cached: dict[str, dict] = {}
    missing: list[str] = []
    for code in unique_codes:
        bare = _strip_suffix(code)
        if bare in cache:
            cached[code] = cache[bare]
        elif code in cache:
            cached[code] = cache[code]
        else:
            missing.append(code)

    # 3. 对缺失的股票做 iFinD 实时查询
    realtime: dict[str, dict] = _query_ifind_realtime(missing)

    # 4. 合并结果并判定
    passed = []
    excluded = []
    for code in unique_codes:
        bare = _strip_suffix(code)
        # 先查缓存，再查实时
        info = cached.get(code)
        if info is None:
            info = realtime.get(code) or realtime.get(bare)

        if info is None:
            excluded.append({"code": code, "reason": "无法获取资金面数据（缓存未命中且实时查询无结果）"})
            continue

        inflow = info.get("main_net_inflow")
        name = info.get("name", code)
        if inflow is None:
            excluded.append({"code": code, "reason": f"主力净流入数据为空 (股票: {name})"})
        elif inflow > 0:
            passed.append(code)
        else:
            excluded.append({"code": code, "reason": f"主力净流入 <= 0 ({inflow}, 股票: {name})"})

    return {
        "passed": passed,
        "excluded": excluded,
        "stats": {
            "total": len(unique_codes),
            "passed": len(passed),
            "excluded": len(excluded),
        },
    }


# ── CLI 测试入口 ──
if __name__ == "__main__":
    test_stocks = sys.argv[1:] if len(sys.argv) > 1 else ["600936.SH", "300912.SZ", "300065.SZ"]
    print(f"测试股票: {test_stocks}")
    result = filter_by_capital_flow(test_stocks)
    print(json.dumps(result, ensure_ascii=False, indent=2))
