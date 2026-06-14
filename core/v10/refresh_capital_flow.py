#!/usr/bin/env python3
"""
资金面缓存刷新脚本（替代原iFinD MCP版本）
从腾讯行情API获取持仓股的主力净流入数据
每30分钟运行一次，写入 ~/.hermes/cache/capital_flow.json

数据源：腾讯行情 qt.gtimg.cn field[50]=主力净流入(万元)
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime

# 集合竞价时段跳过
_now = datetime.now()
if _now.hour == 9 and _now.minute < 30:
    print(f"⏳ 集合竞价中({_now.strftime('%H:%M')})，跳过现金流缓存")
    sys.exit(0)

# 全局变量
SCRIPTS_DIR = os.path.expanduser("~/.hermes/scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

CACHE_FILE = os.path.expanduser("~/.hermes/cache/capital_flow.json")


def get_holdings():
    """读取当前持仓"""
    from current_holdings import get_holdings as gh
    return gh()


def fetch_tencent_quote(codes):
    """批量获取腾讯行情 + 资金流向(ff_接口，降级到普通行情parts[50])"""
    code_str = ",".join(
        [f"sh{c}" if c.startswith("6") else f"sz{c}" for c in codes]
    )
    # 同时请求行情和资金流向(ff_前缀)
    ff_codes = ",".join(
        [f"ff_sh{c}" if c.startswith("6") else f"ff_sz{c}" for c in codes]
    )
    url = f"https://qt.gtimg.cn/q={code_str},{ff_codes}"
    req = urllib.request.Request(url)
    req.add_header("Referer", "https://qt.gtimg.cn")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk", errors="ignore")
    except Exception as e:
        print(f"腾讯行情请求失败: {e}")
        return {}

    # 先解析ff_资金流向
    ff_inflow = {}  # code -> main_inflow
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line.startswith("v_ff_"):
            continue
        m = re.search(r'=(.+?);?$', line)
        if not m:
            continue
        parts = m.group(1).strip('"').split("~")
        if len(parts) < 4:
            continue
        code = parts[2] if len(parts) > 2 else ""
        if code and parts[3]:
            try:
                ff_inflow[code] = float(parts[3])
            except (ValueError, IndexError):
                pass

    # 再解析普通行情
    results = {}
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line.startswith("v_sh") and not line.startswith("v_sz"):
            continue
        m = re.search(r'=(.+?);?$', line)
        if not m:
            continue
        parts = m.group(1).strip('"').split("~")
        if len(parts) < 40:
            continue
        code = parts[2]
        # 主力净流入：ff_接口优先，降级到parts[50]
        main_inflow = ff_inflow.get(code)
        if main_inflow is None and len(parts) > 50 and parts[50]:
            try:
                main_inflow = float(parts[50])
            except (ValueError, IndexError):
                pass
        yclose_val = float(parts[4]) if parts[4] else 0
        price_val = float(parts[3]) if parts[3] else 0
        api_chg = float(parts[32]) if parts[32] else None
        if api_chg is not None:
            chg = api_chg
        elif yclose_val > 0 and price_val > 0:
            chg = round((price_val / yclose_val - 1) * 100, 2)
        else:
            chg = 0
        results[code] = {
            "name": parts[1],
            "code": code,
            "current_price": price_val,
            "change_pct": chg,
            "amount": int(float(parts[37]) * 10000) if parts[37] else 0,
            "turnover_rate": float(parts[38]) if parts[38] else 0,
            "main_inflow": main_inflow,  # 万元，ff_接口>parts[50]降级
        }
    return results


def main():
    print(f"[{datetime.now().strftime('%H:%M')}] 资金面缓存刷新开始")

    # 获取持仓
    try:
        holdings = get_holdings()
    except Exception as e:
        print(f"读取持仓失败: {e}")
        result = {"stocks": {}, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "error": str(e)}
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"已写入空缓存 (读取持仓失败)")
        return

    if not holdings:
        result = {"stocks": {}, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "note": "无持仓"}
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"已写入空缓存 (无持仓)")
        return

    # 提取代码
    codes = []
    for h in holdings:
        if not isinstance(h, dict):
            continue
        code = str(h.get("code", ""))
        if code:
            codes.append(code)

    if not codes:
        print("无法提取持仓代码")
        return

    print(f"查询 {len(codes)} 只持仓股: {codes}")

    # 获取腾讯行情
    quotes = fetch_tencent_quote(codes)
    print(f"获取到 {len(quotes)} 只股票的行情数据")

    # 组装结果
    stocks_data = {}
    for h in holdings:
        if not isinstance(h, dict):
            continue
        code = str(h.get("code", ""))
        name = h.get("name", "")
        q = quotes.get(code, {})
        stocks_data[code] = {
            "name": name or q.get("name", ""),
            "code": code,
            "主力净流入(万元)": q.get("main_inflow"),
            "现价": q.get("current_price"),
            "涨幅%": q.get("change_pct"),
            "成交额(万元)": q.get("amount"),
            "换手率%": q.get("turnover_rate"),
            "更新时间": datetime.now().strftime("%H:%M"),
            "note": None if q.get("main_inflow") is not None else "腾讯行情无主力净流入数据(非交易时段或停牌)",
        }

    # 写入缓存
    result = {
        "stocks": stocks_data,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_source": "腾讯行情qt.gtimg.cn + ff_资金流向接口(主力净流入,万元)",
    }

    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"已写入 {CACHE_FILE}")
    print(f"  共 {len(stocks_data)} 只股票")
    for code, data in stocks_data.items():
        mi = data.get("主力净流入(万元)")
        inflow_str = f"{mi:+.0f}万元" if mi is not None else "无数据"
        print(f"  {data['name']}({code}): {inflow_str}")


if __name__ == "__main__":
    main()
