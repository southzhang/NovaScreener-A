#!/usr/bin/env python3
"""
V10 资金面验证模块（东财push2 + 腾讯缓存 + iFinD降级）

验证规则：主力净流入 > 0 才通过

降级链：
  1. 本地 capital_flow.json 缓存
  2. 东财 push2 批量接口（f62=主力净流入）
  3. iFinD 实时查询（兜底）
  4. 全部不可用时保守放行（不排除）

返回 {"passed": [...], "excluded": [...], "stats": {...}}。
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

CACHE_PATH = Path.home() / ".hermes" / "cache" / "capital_flow.json"

# push2 批量大小
PUSH2_BATCH = 50


def _strip_suffix(code: str) -> str:
    """600936.SH -> 600936"""
    return code.split(".")[0] if "." in code else code


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


def _push2_batch_capital_flow(codes: list) -> dict:
    """
    东财 push2 批量查询主力净流入。
    codes: 纯数字代码列表 ['600519', '000001']
    返回 {code: {"main_net_inflow": float(元), "source": "push2"}}
    """
    if not codes:
        return {}

    # 转换为东财 secid 格式: 1.600519(沪) 0.000001(深)
    secids = []
    for c in codes:
        bare = _strip_suffix(c)
        market = "1" if bare.startswith("6") else "0"
        secids.append(f"{market}.{bare}")

    result = {}
    for i in range(0, len(secids), PUSH2_BATCH):
        batch = secids[i:i + PUSH2_BATCH]
        secids_str = ",".join(batch)
        url = (
            f"https://push2.eastmoney.com/api/qt/ulist.np/get"
            f"?fltt=2&secids={secids_str}"
            f"&fields=f12,f14,f62,f184"
            f"&ut=fa5fd1943c7b386f172d6893dbbd4848"
        )
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://data.eastmoney.com/",
                },
            )
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("data", {}).get("diff"):
                for item in data["data"]["diff"]:
                    code = str(item.get("f12", ""))
                    f62 = item.get("f62")  # 主力净流入（元）
                    if code and f62 is not None:
                        try:
                            inflow = float(f62)
                            result[code] = {
                                "name": item.get("f14", code),
                                "main_net_inflow": inflow,
                                "source": "push2",
                            }
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass
        time.sleep(0.1)

    return result


def _ifind_capital_flow(codes: list) -> dict:
    """iFinD降级：实时查询主力净流入"""
    try:
        sys.path.insert(0, str(Path.home() / ".hermes" / "scripts"))
        from ifind_http_api import iFinD  # type: ignore
    except ImportError:
        return {}

    ifind_codes = []
    for c in codes:
        bare = _strip_suffix(c)
        suffix = ".SH" if bare.startswith("6") else ".SZ"
        ifind_codes.append(f"{bare}{suffix}")

    try:
        df = iFinD.stock_snapshot_batch(ifind_codes, ["main_net_inflow"])
        if df is None or isinstance(df, dict) or (hasattr(df, 'empty') and df.empty):
            return {}
        result = {}
        for _, row in df.iterrows():
            code = str(row.get("thscode", row.iloc[0])).strip()
            bare = _strip_suffix(code)
            inflow = None
            for col in ["table.main_net_inflow", "main_net_inflow"]:
                if col in df.columns:
                    val = row.get(col)
                    if val is not None:
                        try:
                            inflow = float(val[0]) if isinstance(val, list) else float(val)
                        except (TypeError, ValueError, IndexError):
                            pass
                        break
            if inflow is not None:
                result[bare] = {"name": bare, "main_net_inflow": inflow, "source": "ifind_realtime"}
        return result
    except Exception as e:
        print(f"  [capital_filter] iFinD 实时查询失败: {e}", file=sys.stderr)
        return {}


def filter_by_capital_flow(stocks: list) -> dict[str, Any]:
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

    bare_codes = [_strip_suffix(c) for c in unique_codes]

    # 1. 缓存
    cache = _load_cache()

    # 2. 分离：已缓存 vs 未缓存
    cached_info = {}
    missing_bare = []
    for code, bare in zip(unique_codes, bare_codes):
        if bare in cache:
            cached_info[code] = cache[bare]
        elif code in cache:
            cached_info[code] = cache[code]
        else:
            missing_bare.append(bare)

    # 3. push2 批量查询未命中的
    push2_info = {}
    if missing_bare:
        push2_info_raw = _push2_batch_capital_flow(missing_bare)
        # push2返回的key是纯数字代码，映射回原始代码
        for code, bare in zip(unique_codes, bare_codes):
            if bare in push2_info_raw:
                push2_info[code] = push2_info_raw[bare]

    # 4. 仍未命中的，尝试iFinD
    still_missing = [code for code in unique_codes if code not in cached_info and code not in push2_info]
    still_missing_bare = [_strip_suffix(c) for c in still_missing]
    ifind_info = {}
    if still_missing_bare:
        ifind_raw = _ifind_capital_flow(still_missing)
        for code in still_missing:
            bare = _strip_suffix(code)
            if bare in ifind_raw:
                ifind_info[code] = ifind_raw[bare]

    # 5. 合并结果并判定
    passed = []
    excluded = []
    no_data_count = 0

    for code, bare in zip(unique_codes, bare_codes):
        # 优先级：缓存 > push2 > iFinD
        info = cached_info.get(code)
        if info is None:
            info = push2_info.get(code)
        if info is None:
            info = ifind_info.get(code) or ifind_info.get(bare)

        if info is None:
            # 全部数据源都无数据 → 保守放行，不排除
            no_data_count += 1
            passed.append(code)
            continue

        inflow = info.get("main_net_inflow")
        name = info.get("name", code)

        if inflow is None:
            # 数据存在但净流入字段为空 → 保守放行
            no_data_count += 1
            passed.append(code)
        elif inflow > 0:
            passed.append(code)
        else:
            # 格式化净流入
            if abs(inflow) >= 1e8:
                inflow_str = f"{inflow/1e8:.2f}亿"
            elif abs(inflow) >= 1e4:
                inflow_str = f"{inflow/1e4:.0f}万"
            else:
                inflow_str = f"{inflow:.0f}元"
            excluded.append({
                "code": code,
                "reason": f"主力净流出 ({inflow_str}, {name})",
            })

    source_summary = f"缓存{len(cached_info)}只+push2{len(push2_info)}只+iFinD{len(ifind_info)}只"
    if no_data_count:
        source_summary += f"+无数据保守放行{no_data_count}只"
    print(f"  [capital_filter] 资金面验证: {source_summary}")

    return {
        "passed": passed,
        "excluded": excluded,
        "stats": {
            "total": len(unique_codes),
            "passed": len(passed),
            "excluded": len(excluded),
            "no_data_released": no_data_count,
        },
    }


# ── CLI 测试入口 ──
if __name__ == "__main__":
    test_stocks = sys.argv[1:] if len(sys.argv) > 1 else ["600519", "000001", "300410"]
    print(f"测试股票: {test_stocks}")
    result = filter_by_capital_flow(test_stocks)
    print(json.dumps(result, ensure_ascii=False, indent=2))
