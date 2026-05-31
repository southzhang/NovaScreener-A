#!/usr/bin/env python3
"""
资金流向缓存管理器
支持三维度结构：capital_flow / dark_pool / dragon_tiger
"""
import json
import os
from datetime import datetime

CACHE_DIR = os.path.expanduser('~/.hermes/cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'capital_flow.json')

def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)

def load_cache():
    """读取缓存"""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(data):
    """保存缓存（带完整性校验，防止空数据覆盖有效数据）"""
    ensure_cache_dir()
    # 完整性校验：至少capital_flow维度要有非null数据
    dims = data.get('dimensions', {})
    cf = dims.get('capital_flow', {})
    has_valid_data = any(
        v.get('main_net_inflow') is not None 
        for v in cf.values()
    ) if cf else False
    
    if not has_valid_data and os.path.exists(CACHE_FILE):
        print(f"⚠️ 资金流数据全为null，跳过写入保留旧缓存")
        return False
    
    with open(CACHE_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True

def get_capital_flow(code):
    """获取单只股票的资金流向（供盯盘脚本调用）"""
    cache = load_cache()
    dims = cache.get('dimensions', cache)
    stock_data = dims.get('capital_flow', dims.get('stocks', {})).get(code, {})
    if stock_data:
        return {
            'main_net_inflow': stock_data.get('main_net_inflow', 0),
            'main_net_pct': stock_data.get('main_net_pct', 0),
        }
    return None

def get_dark_pool(code):
    """获取暗盘资金数据"""
    cache = load_cache()
    dims = cache.get('dimensions', cache)
    dp = dims.get('dark_pool', {}).get(code, {})
    if dp:
        return {
            'margin_balance': dp.get('margin_balance'),
            'block_trade_amount': dp.get('block_trade_amount'),
            'block_trade_count': dp.get('block_trade_count', 0),
        }
    return None

def get_dragon_tiger(code):
    """获取龙虎榜数据"""
    cache = load_cache()
    dims = cache.get('dimensions', cache)
    dt = dims.get('dragon_tiger', {}).get(code, {})
    if dt:
        return {
            'tt_count': dt.get('tt_count', 0),
            'tt_buy': dt.get('tt_buy'),
            'tt_sell': dt.get('tt_sell'),
        }
    return None

if __name__ == '__main__':
    cache = load_cache()
    print(f"缓存文件: {CACHE_FILE}")
    print(f"最后更新: {cache.get('last_update', '无')}")
    dims = cache.get('dimensions', cache)
    for dim, stocks in dims.items():
        print(f"\n{dim}: {len(stocks)}只")
        for code, data in list(stocks.items())[:3]:
            print(f"  {code}: {data}")
