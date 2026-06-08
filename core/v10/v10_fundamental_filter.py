#!/usr/bin/env python3
"""
V10 基本面过滤模块（腾讯行情PE + 东财datacenter降级版）

排雷规则：
  1. PE ≤ 0 → 排除（亏损股）
  2. PE > 200 → 排除（微利/异常）
  3. 名称含"ST"/"*ST"/"退" → 排除
  4. 名称以"N"开头 → 排除（次新股首日）

降级链：腾讯行情PE → iFinD ROE/净利润同比 → 跳过（容错）

返回 (passed_stocks, rejected_stocks) 元组。
"""

import sys
import os
import time
import json
import urllib.request
import urllib.error

# iFinD 降级
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ifind_http_api import iFinD
    HAS_IFIND = True
except ImportError:
    HAS_IFIND = False

# 阈值
PE_MAX = 200       # PE上限（排除微利/异常）
PE_MIN = 0         # PE下限（≤0=亏损）

# 批量请求大小
BATCH_SIZE = 80


def log(msg):
    print(f"  [fundamental] {msg}", flush=True)


def _tencent_batch_pe(codes: list) -> dict:
    """腾讯行情批量获取PE，返回 {code: pe_value_or_None}"""
    result = {}
    # 构建前缀代码
    tc_codes = []
    for c in codes:
        c = str(c).split(".")[0]
        prefix = "sh" if c.startswith("6") else "sz"
        tc_codes.append(f"{prefix}{c}")

    for i in range(0, len(tc_codes), BATCH_SIZE):
        batch = tc_codes[i:i + BATCH_SIZE]
        qs = ",".join(batch)
        url = f"https://qt.gtimg.cn/q={qs}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode("gbk", errors="ignore")
            for line in raw.strip().split(";"):
                if "=" not in line or "~" not in line:
                    continue
                parts = line.split("=")[1].strip('"').split("~")
                if len(parts) < 40:
                    continue
                code = parts[2]
                pe_str = parts[39]
                try:
                    pe = float(pe_str) if pe_str else None
                except (ValueError, TypeError):
                    pe = None
                name = parts[1]
                result[code] = {"pe": pe, "name": name}
        except Exception:
            pass
        time.sleep(0.1)

    return result


def _ifind_fundamental(codes: list) -> dict:
    """iFinD降级：批量查ROE和净利润同比"""
    if not HAS_IFIND:
        return {}

    try:
        from ifind_http_api import iFinD as _iFinD  # noqa: F811
        from v10_fundamental_filter_orig import _stock_code_to_ifind, _query_basic_data, ROE_MIN, NP_YOY_MIN  # type: ignore
    except ImportError:
        # 旧版v10_fundamental_filter不存在时，直接用iFinD查
        return _ifind_fundamental_direct(codes)

    try:
        ifind_codes = [_stock_code_to_ifind(c) for c in codes]
        data = _query_basic_data(_iFinD, ifind_codes)
        result = {}
        for ic, info in data.items():
            bare = ic.split(".")[0]
            result[bare] = {
                "roe": info.get("roe"),
                "np_yoy": info.get("np_yoy"),
            }
        return result
    except Exception:
        return {}


def _ifind_fundamental_direct(codes: list) -> dict:
    """iFinD降级（无旧版filter依赖时直接查）"""
    if not HAS_IFIND:
        return {}
    try:
        from ifind_http_api import iFinD as _api
        ifind_codes = []
        for c in codes:
            bare = str(c).split(".")[0]
            suffix = ".SH" if bare.startswith("6") else ".SZ"
            ifind_codes.append(f"{bare}{suffix}")

        indicators = ["ths_roe_deducted_stock", "ths_np_yoy_stock"]
        indipara = [{"indicator": ind, "indiparams": []} for ind in indicators]
        params = {"codes": ",".join(ifind_codes[:50]), "indipara": indipara}
        data = _api._post("basic_data_service", params)
        if not data or "tables" not in data:
            return {}
        result = {}
        tables = data["tables"]
        rows = tables if isinstance(tables, list) else []
        for row in rows:
            code = str(row.get("codes", row.get("code", "")))
            bare = code.split(".")[0]
            roe = row.get("ths_roe_deducted_stock")
            np_yoy = row.get("ths_np_yoy_stock")
            result[bare] = {"roe": roe, "np_yoy": np_yoy}
        return result
    except Exception:
        return {}


def filter_by_fundamental(stocks: list) -> tuple:
    """
    对股票列表做基本面排雷过滤。

    参数:
        stocks: 股票列表，每项可以是:
            - 纯代码字符串: "600936"
            - iFinD格式: "600936.SH"
            - dict: {"code": "600936", "name": "旗滨集团"}

    返回:
        (passed_stocks, rejected_stocks) 元组，其中:
        - passed_stocks: 通过过滤的股票列表（保留原始输入格式）
        - rejected_stocks: 被排除的股票列表，每项为 dict:
            {"stock": 原始输入, "reasons": ["原因1", "原因2"]}
    """
    if not stocks:
        return [], []

    # 解析输入
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
        bare_code = raw_code.split(".")[0] if "." in raw_code else raw_code
        parsed.append({
            "original": s,
            "bare_code": bare_code,
            "name": name,
        })

    # ===== 第一轮：名称规则过滤（无需API） =====
    need_pe = []
    rejected = []

    for item in parsed:
        name = item["name"]
        reasons = []

        if name:
            if "*ST" in name or "*st" in name:
                reasons.append(f"名称含*ST: {name}")
            elif "ST" in name or "st" in name:
                reasons.append(f"名称含ST: {name}")
            if "退" in name:
                reasons.append(f"名称含退: {name}")
            if name.startswith("N"):
                reasons.append(f"次新股首日: {name}")

        if reasons:
            rejected.append({"stock": item["original"], "reasons": reasons})
        else:
            need_pe.append(item)

    if not need_pe:
        return [], rejected

    # ===== 第二轮：腾讯行情PE过滤 =====
    log(f"腾讯PE过滤 {len(need_pe)} 只...")
    codes_for_pe = [item["bare_code"] for item in need_pe]
    pe_data = _tencent_batch_pe(codes_for_pe)

    # 合并腾讯返回的名称
    for item in need_pe:
        code = item["bare_code"]
        if code in pe_data and not item["name"]:
            item["name"] = pe_data[code].get("name", "")

    # PE过滤
    passed_pe = []
    rejected_by_pe = []
    need_ifind = []  # PE获取失败的，尝试iFinD

    for item in need_pe:
        code = item["bare_code"]
        info = pe_data.get(code, {})
        pe = info.get("pe")
        name = item["name"] or info.get("name", code)

        if pe is not None:
            if pe <= PE_MIN:
                rejected_by_pe.append({"stock": item["original"], "reasons": [f"PE={pe:.1f}≤0（亏损股）: {name}"]})
            elif pe > PE_MAX:
                rejected_by_pe.append({"stock": item["original"], "reasons": [f"PE={pe:.1f}>{PE_MAX}（微利/异常）: {name}"]})
            else:
                passed_pe.append(item)
        else:
            # PE获取失败，尝试iFinD降级
            need_ifind.append(item)

    if rejected_by_pe:
        log(f"PE排除 {len(rejected_by_pe)} 只")
    rejected.extend(rejected_by_pe)

    # ===== 第三轮：iFinD降级（仅对PE获取失败的股票） =====
    if need_ifind and HAS_IFIND:
        log(f"iFinD降级过滤 {len(need_ifind)} 只（PE获取失败）...")
        ifind_codes = [item["bare_code"] for item in need_ifind]
        ifind_data = _ifind_fundamental(ifind_codes)

        ifind_passed = []
        ifind_rejected = []

        for item in need_ifind:
            code = item["bare_code"]
            info = ifind_data.get(code, {})
            roe = info.get("roe")
            np_yoy = info.get("np_yoy")
            reasons = []

            if roe is not None:
                try:
                    roe_f = float(roe)
                    if roe_f < 5:
                        reasons.append(f"扣非ROE={roe_f:.1f}%<5%")
                except (ValueError, TypeError):
                    pass

            if np_yoy is not None:
                try:
                    np_yoy_f = float(np_yoy)
                    if np_yoy_f < 0:
                        reasons.append(f"净利润同比={np_yoy_f:.1f}%<0%")
                except (ValueError, TypeError):
                    pass

            if reasons:
                ifind_rejected.append({"stock": item["original"], "reasons": reasons})
            else:
                ifind_passed.append(item)

        if ifind_rejected:
            log(f"iFinD排除 {len(ifind_rejected)} 只")
        rejected.extend(ifind_rejected)
        passed_pe.extend(ifind_passed)
    elif need_ifind:
        # iFinD不可用，PE也没拿到，保守放行
        log(f"⚠️ {len(need_ifind)}只PE数据缺失且iFinD不可用，保守放行")
        passed_pe.extend(need_ifind)

    passed = [item["original"] for item in passed_pe]
    return passed, rejected


# ===== CLI测试 =====
if __name__ == "__main__":
    test_stocks = [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000001", "name": "平安银行"},
        {"code": "300410", "name": "正业科技"},
        {"code": "000725", "name": "*ST京东方A"},
        {"code": "600234", "name": "ST天龙"},
    ]
    print("=" * 60)
    print("V10 基本面过滤测试（腾讯PE + iFinD降级）")
    print("=" * 60)

    passed, rejected = filter_by_fundamental(test_stocks)

    print(f"\n✅ 通过 ({len(passed)}只):")
    for s in passed:
        print(f"  {s}")

    print(f"\n❌ 排除 ({len(rejected)}只):")
    for r in rejected:
        print(f"  {r['stock']} → {'; '.join(r['reasons'])}")

    print(f"\n总计: {len(test_stocks)}只 → 通过{len(passed)}只, 排除{len(rejected)}只")
