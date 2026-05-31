#!/usr/bin/env python3
"""
V10 基本面过滤模块
对股票列表做基本面排雷，规则：
  1. 扣非ROE < 5% → 排除
  2. 净利润同比增速 < 0% → 排除
  3. 股票名称含"ST" → 排除
  4. 股票名称含"*ST" → 排除

使用 iFinD HTTP API 的 basic_data 方法批量查询指标。
返回 (passed_stocks, rejected_stocks) 元组。
"""

import re
import sys
import os

# 确保能导入同目录的 ifind_http_api
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ifind_http_api import iFinD

# 阈值配置
ROE_MIN = 5.0        # 扣非ROE最低阈值（%）
NP_YOY_MIN = 0.0     # 净利润同比增速最低阈值（%）

# 批量查询大小（避免单次请求过大）
BATCH_SIZE = 50


def _stock_code_to_ifind(code: str) -> str:
    """
    将纯数字股票代码转为 iFinD 格式。
    600936 → 600936.SH  (6开头=上交所)
    300065 → 300065.SZ  (0/3开头=深交所)
    已带后缀的原样返回。
    """
    code = code.strip()
    if "." in code:
        return code
    if code.startswith("6"):
        return f"{code}.SH"
    else:
        return f"{code}.SZ"


def _ifind_code_to_plain(code: str) -> str:
    """iFinD代码 → 纯数字代码"""
    return code.split(".")[0] if "." in code else code


def _query_basic_data(api: iFinD, ifind_codes: list) -> dict:
    """
    批量查询 ths_roe_deducted_stock 和 ths_np_yoy_stock。
    返回 {ifind_code: {"roe": float|None, "np_yoy": float|None}}
    """
    indicators = ["ths_roe_deducted_stock", "ths_np_yoy_stock"]
    result = {}

    for i in range(0, len(ifind_codes), BATCH_SIZE):
        batch = ifind_codes[i:i + BATCH_SIZE]
        codes_str = ",".join(batch)

        indipara = [
            {"indicator": ind, "indiparams": []} for ind in indicators
        ]
        params = {"codes": codes_str, "indipara": indipara}

        try:
            data = api._post("basic_data_service", params)
        except Exception as e:
            print(f"[v10_filter] API请求异常: {e}")
            # 异常时这批股票数据全部记为 None
            for c in batch:
                result[c] = {"roe": None, "np_yoy": None}
            continue

        if not data or "tables" not in data:
            for c in batch:
                result[c] = {"roe": None, "np_yoy": None}
            continue

        tables = data["tables"]
        if isinstance(tables, list):
            for row in tables:
                code = row.get("codes", row.get("code", ""))
                roe_val = row.get("ths_roe_deducted_stock", None)
                np_yoy_val = row.get("ths_np_yoy_stock", None)
                result[code] = {"roe": roe_val, "np_yoy": np_yoy_val}
        elif isinstance(tables, dict):
            # 某些情况下 tables 可能是 dict 结构
            for code in batch:
                result[code] = {
                    "roe": tables.get("ths_roe_deducted_stock"),
                    "np_yoy": tables.get("ths_np_yoy_stock"),
                }

        # 确保 batch 中每个代码都有记录
        for c in batch:
            if c not in result:
                result[c] = {"roe": None, "np_yoy": None}

    return result


def filter_by_fundamental(stocks: list) -> tuple:
    """
    对股票列表做基本面排雷过滤。

    参数:
        stocks: 股票列表，每项可以是:
            - 纯代码字符串: "600936"
            - iFinD格式: "600936.SH"
            - dict: {"code": "600936", "name": "旗滨集团"} 或
                    {"code": "600936.SH", "name": "旗滨集团"}

    返回:
        (passed_stocks, rejected_stocks) 元组，其中:
        - passed_stocks: 通过过滤的股票列表（保留原始输入格式）
        - rejected_stocks: 被排除的股票列表，每项为 dict:
            {"stock": 原始输入, "reasons": ["原因1", "原因2"]}
    """
    if not stocks:
        return [], []

    # 解析输入：提取 (原始项, 代码, 名称, iFinD代码)
    parsed = []
    for s in stocks:
        if isinstance(s, dict):
            raw_code = s.get("code", s.get("thscode", ""))
            name = s.get("name", s.get("secName", s.get("stock_name", "")))
        elif isinstance(s, str):
            raw_code = s
            name = ""
        else:
            raw_code = str(s)
            name = ""

        ifind_code = _stock_code_to_ifind(raw_code)
        parsed.append({
            "original": s,
            "raw_code": raw_code,
            "name": name,
            "ifind_code": ifind_code,
        })

    # ===== 第一轮：名称规则过滤（无需API调用） =====
    need_api = []       # 需要查API的
    rejected = []       # 被排除的

    for item in parsed:
        name = item["name"]
        reasons = []

        # ST / *ST 排除
        if name:
            if "*ST" in name or "*st" in name:
                reasons.append(f"名称含*ST: {name}")
            elif "ST" in name or "st" in name:
                reasons.append(f"名称含ST: {name}")

        if reasons:
            rejected.append({"stock": item["original"], "reasons": reasons})
        else:
            need_api.append(item)

    if not need_api:
        return [], rejected

    # ===== 第二轮：API查询 ROE 和 净利润同比 =====
    api = iFinD
    ifind_codes = [item["ifind_code"] for item in need_api]
    data = _query_basic_data(api, ifind_codes)

    passed = []
    for item in need_api:
        ic = item["ifind_code"]
        info = data.get(ic, {"roe": None, "np_yoy": None})
        roe = info.get("roe")
        np_yoy = info.get("np_yoy")
        reasons = []

        # ROE 过滤
        if roe is not None:
            try:
                roe_f = float(roe)
                if roe_f < ROE_MIN:
                    reasons.append(f"扣非ROE={roe_f:.2f}% < {ROE_MIN}%")
            except (ValueError, TypeError):
                pass  # 无法解析时不作为排除理由
        # 如果ROE为None，不排除（容错）

        # 净利润同比 过滤
        if np_yoy is not None:
            try:
                np_yoy_f = float(np_yoy)
                if np_yoy_f < NP_YOY_MIN:
                    reasons.append(f"净利润同比={np_yoy_f:.2f}% < {NP_YOY_MIN}%")
            except (ValueError, TypeError):
                pass

        if reasons:
            rejected.append({"stock": item["original"], "reasons": reasons})
        else:
            passed.append(item["original"])

    return passed, rejected


# ===== 命令行测试 =====
if __name__ == "__main__":
    import json

    test_stocks = [
        {"code": "600936", "name": "旗滨集团"},
        {"code": "300065", "name": "海兰信"},
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000001", "name": "平安银行"},
        {"code": "601318", "name": "中国平安"},
        {"code": "000725", "name": "*ST京东方A"},  # 应被ST规则排除
    ]

    print("=" * 60)
    print("V10 基本面过滤测试")
    print("=" * 60)

    passed, rejected = filter_by_fundamental(test_stocks)

    print(f"\n✅ 通过 ({len(passed)}只):")
    for s in passed:
        print(f"  {s}")

    print(f"\n❌ 排除 ({len(rejected)}只):")
    for r in rejected:
        print(f"  {r['stock']} → {'; '.join(r['reasons'])}")

    print(f"\n总计: {len(test_stocks)}只 → 通过{len(passed)}只, 排除{len(rejected)}只")
