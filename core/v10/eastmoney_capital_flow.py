#!/usr/bin/env python3
"""
东方财富免费资金面数据源 v1.0
替代MX妙想API（休眠/限额问题），直接使用东方财富web接口获取个股主力资金流向。
无需API Key，免费，稳定。

输出格式与 mx_capital_flow.py 完全兼容：
  {code: {main_net_inflow: 万, super_large_net: 万, large_net: 万, medium_net: 万, small_net: 万, date: str, source: str}}

用法:
  from eastmoney_capital_flow import query_capital_flow_batch, query_capital_flow_single
  result = query_capital_flow_batch(['603399', '600519'])
"""

import json, os, time, requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

CACHE_FILE = Path.home() / ".hermes" / "cache" / "capital_flow.json"
HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
# 实时资金流向API（更稳定，单次查询多只股票）
REALTIME_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
# 数据中心API（最稳定，但只能逐只查询）
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://quote.eastmoney.com/",
}

DATACENTER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Referer": "https://data.eastmoney.com/",
}


def _get_market(code: str) -> int:
    """判断市场：6开头=上海(1)，0/3开头=深圳(0)"""
    return 1 if code.startswith("6") else 0


def query_capital_flow_realtime(codes: list) -> Dict:
    """实时资金流向查询（push2 API，一次可查多只，更稳定）
    
    字段映射:
      f62=主力净流入, f66=超大单净流入, f72=大单净流入,
      f78=中单净流入, f84=小单净流入, f184=主力净流入占比(%)
    
    Returns:
        {code: {main_net_inflow: 万, super_large_net: 万, ...}, ...}
    """
    # 构建secids参数：1.603399,0.000001,...
    secids = ",".join(f"{_get_market(c)}.{c}" for c in codes if c.isdigit())
    if not secids:
        return {}
    
    params = {
        "fltt": "2",
        "fields": "f2,f3,f12,f14,f62,f66,f69,f72,f75,f78,f81,f84,f87,f184",
        "secids": secids,
    }
    
    try:
        resp = requests.get(REALTIME_URL, params=params, headers=HEADERS, timeout=15)
        data = resp.json()
        
        if data.get("rc") != 0:
            return {}
        
        diff = data.get("data", {}).get("diff", [])
        if not diff:
            return {}
        
        results = {}
        for item in diff:
            code = item.get("f12", "")
            if not code or not code.isdigit():
                continue
            
            def to_wan(val):
                try:
                    v = float(val) if val is not None else 0
                    return round(v / 10000, 2)  # 元→万
                except (ValueError, TypeError):
                    return 0
            
            results[code] = {
                "main_net_inflow": to_wan(item.get("f62")),      # 主力净流入（万）
                "super_large_net": to_wan(item.get("f66")),       # 超大单净流入（万）
                "large_net": to_wan(item.get("f72")),             # 大单净流入（万）
                "medium_net": to_wan(item.get("f78")),            # 中单净流入（万）
                "small_net": to_wan(item.get("f84")),             # 小单净流入（万）
                "main_net_pct": item.get("f184", 0),              # 主力净流入占比(%)
                "price": item.get("f2", 0),                       # 最新价
                "change_pct": item.get("f3", 0),                  # 涨跌幅(%)
                "date": datetime.now().strftime("%Y-%m-%d"),
                "source": "eastmoney_realtime",
            }
        
        return results
        
    except Exception as e:
        print(f"  ⚠️ 实时资金面查询失败: {e}")
        return {}


def query_capital_flow_datacenter(code: str) -> Optional[Dict]:
    """数据中心API查询（最稳定，逐只查询）
    
    字段映射:
      PRIME_INFLOW=主力净流入(元), SUPERDEAL_INFLOW/OUTFLOW=超大单,
      BIGDEAL_INFLOW/OUTFLOW=大单, CLOSE_PRICE, CHANGE_RATE等
    
    Returns:
        {main_net_inflow: 万, ...} 或 None
    """
    params = {
        "reportName": "RPT_DMSK_TS_STOCKNEW",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,PRIME_INFLOW,SUPERDEAL_INFLOW,SUPERDEAL_OUTFLOW,BIGDEAL_INFLOW,BIGDEAL_OUTFLOW,CLOSE_PRICE,CHANGE_RATE,RANK,RATIO",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageNumber": "1",
        "pageSize": "1",
        "sortTypes": "-1",
        "sortColumns": "TRADE_DATE",
    }
    
    try:
        resp = requests.get(DATACENTER_URL, params=params, headers=DATACENTER_HEADERS, timeout=15)
        data = resp.json()
        
        if not data.get("success"):
            return None
        
        result = data.get("result", {})
        rows = result.get("data", [])
        if not rows:
            return None
        
        r = rows[0]
        prime_inflow = r.get("PRIME_INFLOW", 0) or 0
        super_inflow = r.get("SUPERDEAL_INFLOW", 0) or 0
        super_outflow = r.get("SUPERDEAL_OUTFLOW", 0) or 0
        big_inflow = r.get("BIGDEAL_INFLOW", 0) or 0
        big_outflow = r.get("BIGDEAL_OUTFLOW", 0) or 0
        
        def to_wan(val):
            try:
                return round(float(val) / 10000, 2)  # 元→万
            except (ValueError, TypeError):
                return 0
        
        return {
            "main_net_inflow": to_wan(prime_inflow),
            "super_large_net": to_wan(super_inflow - super_outflow),
            "large_net": to_wan(big_inflow - big_outflow),
            "medium_net": 0,  # 数据中心不单独提供
            "small_net": 0,   # 数据中心不单独提供
            "main_net_pct": r.get("RATIO", 0) or 0,
            "price": r.get("CLOSE_PRICE", 0),
            "change_pct": r.get("CHANGE_RATE", 0),
            "rank": r.get("RANK", 0),
            "date": (r.get("TRADE_DATE", "") or "")[:10],
            "source": "eastmoney_datacenter",
        }
        
    except Exception as e:
        print(f"  ⚠️ 数据中心查询失败 ({code}): {e}")
        return None


def query_capital_flow_single(code: str, days: int = 1) -> Optional[Dict]:
    """查询单只股票主力资金流向（最新N天）
    
    Returns:
        {main_net_inflow: 万, super_large_net: 万, large_net: 万, 
         medium_net: 万, small_net: 万, date: str, source: str}
        或 None（查询失败）
    """
    market = _get_market(code)
    params = {
        "secid": f"{market}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "klt": "101",  # 日K
        "lmt": str(min(days, 5)),  # 最多5天
        "ut": "b955e6154b0e4b3698b3562c7f51e8e4",
    }
    
    try:
        resp = requests.get(HISTORY_URL, params=params, headers=HEADERS, timeout=15)
        data = resp.json()
        
        if data.get("rc") != 0:
            return None
        
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return None
        
        # 取最新一天的K线
        latest = klines[-1].split(",")
        # fields: 日期,主力净流入,小单净流入,中单净流入,大单净流入,超大单净流入,主力净流入占比,小单净流入占比,...
        if len(latest) < 6:
            return None
        
        # 原始值单位：元，转换为万元
        def to_wan(val_str):
            try:
                return round(float(val_str) / 10000, 2)
            except (ValueError, TypeError):
                return 0
        
        result = {
            "main_net_inflow": to_wan(latest[1]),      # 主力净流入（万）
            "small_net": to_wan(latest[2]),              # 小单净流入（万）
            "medium_net": to_wan(latest[3]),              # 中单净流入（万）
            "large_net": to_wan(latest[4]),              # 大单净流入（万）
            "super_large_net": to_wan(latest[5]),        # 超大单净流入（万）
            "date": latest[0],                            # 日期
            "source": "eastmoney_free",
        }
        
        # 补充多日数据（如有）
        if days > 1 and len(klines) > 1:
            multi_day = []
            for k in klines:
                f = k.split(",")
                if len(f) >= 2:
                    multi_day.append({"date": f[0], "main_net_inflow": to_wan(f[1])})
            result["history"] = multi_day
        
        return result
        
    except Exception as e:
        print(f"  ⚠️ {code} 资金面查询失败: {e}")
        return None


def query_capital_flow_batch(codes: list, days: int = 1, delay: float = 0.3) -> Dict:
    """批量查询主力资金流向（三级降级：实时→数据中心→历史）
    
    Args:
        codes: 股票代码列表
        days: 查询天数(1-5)，仅历史API使用
        delay: API每次请求间隔(秒)，避免限流
    
    Returns:
        {code: {main_net_inflow: 万, ...}, ...}
    """
    # 第一优先级：实时API（一次查多只，最快）
    results = query_capital_flow_realtime(codes)
    if results:
        return results
    
    # 第二优先级：数据中心API（逐只查询，最稳定）
    print("  ⚠️ 实时API失败，尝试数据中心API...")
    dc_results = {}
    for i, code in enumerate(codes):
        code = code.strip()
        if not code or not code.isdigit():
            continue
        flow = query_capital_flow_datacenter(code)
        if flow:
            dc_results[code] = flow
        if i < len(codes) - 1:
            time.sleep(delay)
    if dc_results:
        return dc_results
    
    # 第三优先级：历史K线API（逐只查询，可能被限流）
    print("  ⚠️ 数据中心API也失败，尝试历史API...")
    fallback_results = {}
    for i, code in enumerate(codes):
        code = code.strip()
        if not code or not code.isdigit():
            continue
        
        flow = query_capital_flow_single(code, days)
        if flow:
            fallback_results[code] = flow
        
        if i < len(codes) - 1:
            time.sleep(delay)
    
    return fallback_results


def save_capital_flow(data: dict, source: str = "eastmoney_free"):
    """保存资金面数据到缓存（兼容mx_capital_flow格式）
    
    Args:
        data: {code: {main_net_inflow: 万, ...}} 或 {code: net_inflow_wan}
    """
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    save_data = {}
    for code, val in data.items():
        if isinstance(val, dict):
            save_data[code] = val
        else:
            save_data[code] = {
                "main_net_inflow": val,
                "net_inflow": val,
                "source": source,
                "date": datetime.now().strftime("%Y-%m-%d"),
            }
    
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 资金面缓存已保存: {CACHE_FILE} ({len(save_data)}只)")


def load_capital_flow() -> dict:
    """从缓存加载资金面数据（兼容v10_scorer格式）
    
    Returns:
        {code: main_net_inflow_万元}
    """
    if not CACHE_FILE.exists():
        return {}
    
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        result = {}
        for code, val in data.items():
            if isinstance(val, dict):
                result[code] = val.get("main_net_inflow", val.get("net_inflow", 0))
            else:
                result[code] = val
        
        return result
    except Exception:
        return {}


if __name__ == "__main__":
    import sys
    codes = sys.argv[1:] if len(sys.argv) > 1 else ["603399", "600519", "000001"]
    
    print(f"📊 东方财富资金面查询 ({datetime.now().strftime('%H:%M')})")
    print(f"查询: {codes}")
    print("-" * 50)
    
    results = query_capital_flow_batch(codes)
    
    if results:
        for code in sorted(results.keys()):
            r = results[code]
            inflow = r["main_net_inflow"]
            d = "流入" if inflow > 0 else "流出"
            amt = abs(inflow)
            s = f"{amt:.2f}亿" if amt >= 10000 else f"{amt:.0f}万"
            print(f"  {code} 主力净{d}{s} ({r.get('date', '?')})")
        
        # 保存到缓存
        save_capital_flow(results, source="eastmoney_free")
    else:
        print("❌ 无数据")
