#!/usr/bin/env python3
"""
问财板块热度查询模块 — 基于同花顺问财API
提供：行业板块涨跌幅排行、主力资金流向、个股所属板块
数据源：同花顺问财 openapi.iwencai.com
"""

import os
import json
import secrets
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 缓存路径
CACHE_PATH = os.path.expanduser("~/.hermes/cache/sector_heat.json")
CACHE_TTL = 1800  # 30分钟缓存

# API配置
BASE_URL = os.environ.get("IWENCAI_BASE_URL", "https://openapi.iwencai.com")
# API Key优先级：环境变量 > ~/.hermes/.env文件
def _load_api_key():
    key = os.environ.get("IWENCAI_API_KEY", "")
    if key:
        return key
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith("IWENCAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""
API_KEY = _load_api_key()

# 请求头模板
def _headers(call_type="normal"):
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": call_type,
        "X-Claw-Skill-Id": "hithink-sector-selector",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    }

def _api_query(query: str, page: str = "1", limit: str = "20", call_type: str = "normal", timeout: int = 20) -> Optional[dict]:
    """调用问财API"""
    if not API_KEY:
        return None
    url = f"{BASE_URL}/v1/query2data"
    payload = {
        "query": query,
        "page": page,
        "limit": limit,
        "is_cache": "1",
        "expand_index": "true",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(call_type), method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        result = json.loads(resp.read().decode("utf-8"))
        return result
    except Exception as e:
        # 重试一次（放宽条件由调用方处理）
        if call_type == "normal":
            return _api_query(query, page, limit, "retry", timeout)
        return None


def get_hot_sectors(top_n: int = 10, sector_type: str = "行业") -> List[Dict]:
    """获取热门板块（涨幅前N）
    
    Args:
        top_n: 返回前N个板块
        sector_type: "行业"或"概念"
    
    Returns:
        [{name, code, change_pct, main_inflow, sector_type}, ...]
    """
    query = f"今日涨幅前{top_n}的{sector_type}板块"
    result = _api_query(query, limit=str(top_n))
    if not result or not result.get("datas"):
        return []
    
    sectors = []
    for item in result["datas"]:
        name = item.get("指数简称", "")
        code = item.get("指数代码", "")
        change_pct = item.get("最新涨跌幅:前复权", 0)
        # 主力资金字段可能不同日期格式
        main_inflow = 0
        for key in item:
            if "主力净买入额" in key:
                main_inflow = float(item[key]) if item[key] else 0
                break
        
        sectors.append({
            "name": name,
            "code": code,
            "change_pct": round(change_pct, 2) if change_pct else 0,
            "main_inflow": main_inflow,  # 元
            "main_inflow_wan": round(main_inflow / 10000, 0) if main_inflow else 0,  # 万元
            "type": item.get("指数类型", ""),
        })
    
    return sectors


def get_capital_flow_sectors(top_n: int = 10) -> List[Dict]:
    """获取主力资金净流入前N的行业板块"""
    query = f"今日主力资金净流入前{top_n}的行业板块"
    result = _api_query(query, limit=str(top_n))
    if not result or not result.get("datas"):
        return []
    
    sectors = []
    for item in result["datas"]:
        name = item.get("指数简称", "")
        code = item.get("指数代码", "")
        change_pct = item.get("最新涨跌幅:前复权", 0)
        main_inflow = 0
        for key in item:
            if "主力净买入额" in key:
                main_inflow = float(item[key]) if item[key] else 0
                break
        
        sectors.append({
            "name": name,
            "code": code,
            "change_pct": round(change_pct, 2) if change_pct else 0,
            "main_inflow": main_inflow,
            "main_inflow_wan": round(main_inflow / 10000, 0) if main_inflow else 0,
            "type": item.get("指数类型", ""),
        })
    
    return sectors


def get_stock_sectors(stock_name: str = "", stock_code: str = "") -> List[Dict]:
    """查询个股所属板块（含涨跌幅和主力资金）
    
    Args:
        stock_name: 股票名称，如"永杉锂业"
        stock_code: 股票代码，如"603399"
    
    Returns:
        [{name, code, change_pct, main_inflow}, ...]
    """
    identifier = stock_name or stock_code
    if not identifier:
        return []
    
    query = f"{identifier}所属行业板块涨跌幅和主力资金"
    result = _api_query(query, limit="10")
    if not result or not result.get("datas"):
        return []
    
    sectors = []
    for item in result["datas"]:
        name = item.get("指数简称", "")
        code = item.get("指数代码", "")
        change_pct = 0
        for key in item:
            if "涨跌幅" in key:
                change_pct = float(item[key]) if item[key] else 0
                break
        main_inflow = 0
        for key in item:
            if "主力净买入额" in key:
                main_inflow = float(item[key]) if item[key] else 0
                break
        
        sectors.append({
            "name": name,
            "code": code,
            "change_pct": round(change_pct, 2) if change_pct else 0,
            "main_inflow": main_inflow,
            "main_inflow_wan": round(main_inflow / 10000, 0) if main_inflow else 0,
        })
    
    return sectors


def get_sector_heat() -> Dict:
    """获取板块热度综合数据（缓存30分钟）
    
    Returns:
        {
            "hot_industry": [...],  # 涨幅前10行业
            "hot_concept": [...],   # 涨幅前10概念
            "capital_inflow": [...], # 主力净流入前5行业
            "update_time": "...",
            "source": "iwencai"
        }
    """
    # 检查缓存
    cached = None
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as f:
                cached = json.load(f)
            cache_time = datetime.strptime(cached.get("update_time", "2000-01-01"), "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - cache_time).seconds < CACHE_TTL:
                return cached
        except Exception:
            pass
    
    # 获取数据
    result = {
        "hot_industry": [],
        "hot_concept": [],
        "capital_inflow": [],
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "iwencai",
    }
    
    got_data = False
    try:
        data = get_hot_sectors(10, "行业")
        if data:
            result["hot_industry"] = data
            got_data = True
    except Exception:
        pass
    
    try:
        data = get_hot_sectors(10, "概念")
        if data:
            result["hot_concept"] = data
            got_data = True
    except Exception:
        pass
    
    try:
        data = get_capital_flow_sectors(5)
        if data:
            result["capital_inflow"] = data
            got_data = True
    except Exception:
        pass
    
    # 写入缓存（有数据才覆盖旧缓存）
    if got_data:
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH, "w") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    elif cached:
        # 无新数据则保留旧缓存
        return cached
    
    return result


def is_hot_sector(stock_code: str, stock_name: str = "") -> Tuple[bool, str]:
    """判断个股是否属于热门板块
    
    Args:
        stock_code: 股票代码
        stock_name: 股票名称
    
    Returns:
        (is_hot, sector_name) - 是否热门，所属热门板块名
    """
    heat = get_sector_heat()
    stock_sectors = get_stock_sectors(stock_name=stock_name, stock_code=stock_code)
    
    if not stock_sectors:
        return False, ""
    
    # 收集所有热门板块名
    hot_names = set()
    for s in heat.get("hot_industry", []):
        hot_names.add(s["name"])
    for s in heat.get("hot_concept", []):
        hot_names.add(s["name"])
    for s in heat.get("capital_inflow", []):
        hot_names.add(s["name"])
    
    # 匹配
    for sector in stock_sectors:
        if sector["name"] in hot_names:
            return True, sector["name"]
    
    return False, ""


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "heat"
    
    if cmd == "heat":
        data = get_sector_heat()
        print(f"📊 板块热度更新: {data['update_time']}")
        print(f"\n🔥 热门行业板块 (涨幅前10):")
        for i, s in enumerate(data.get("hot_industry", [])[:10], 1):
            inflow = f" 主力净流入{s['main_inflow_wan']:.0f}万" if s['main_inflow_wan'] else ""
            print(f"  {i}. {s['name']} {s['change_pct']:+.2f}%{inflow}")
        print(f"\n💡 热门概念板块 (涨幅前10):")
        for i, s in enumerate(data.get("hot_concept", [])[:10], 1):
            print(f"  {i}. {s['name']} {s['change_pct']:+.2f}%")
        print(f"\n💰 主力资金净流入前5:")
        for i, s in enumerate(data.get("capital_inflow", [])[:5], 1):
            print(f"  {i}. {s['name']} {s['change_pct']:+.2f}% 主力净流入{s['main_inflow_wan']:.0f}万")
    elif cmd == "stock":
        code = sys.argv[2] if len(sys.argv) > 2 else "603399"
        name = sys.argv[3] if len(sys.argv) > 3 else ""
        sectors = get_stock_sectors(stock_code=code, stock_name=name)
        print(f"📊 {name or code} 所属板块:")
        for s in sectors:
            inflow = f" 主力净流入{s['main_inflow_wan']:.0f}万" if s['main_inflow_wan'] else ""
            print(f"  {s['name']} {s['change_pct']:+.2f}%{inflow}")
    elif cmd == "hot":
        code = sys.argv[2] if len(sys.argv) > 2 else "603399"
        name = sys.argv[3] if len(sys.argv) > 3 else ""
        is_hot, sector = is_hot_sector(code, name)
        print(f"{'🔥 属于热门板块' if is_hot else '⚪ 不属于热门板块'}: {sector or '无匹配'}")
    else:
        print("Usage: iwencai_sector.py [heat|stock|hot] [code] [name]")
