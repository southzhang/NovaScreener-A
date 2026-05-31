#!/usr/bin/env python3
"""
资金流向缓存读取器 - 供盯盘脚本调用
读取agent写入的capital_flow.json，输出格式化数据
支持三维度结构：dimensions.capital_flow / dimensions.dark_pool / dimensions.dragon_tiger
"""
import json
import os
from datetime import datetime

CACHE_FILE = os.path.expanduser('~/.hermes/cache/capital_flow.json')

HOLDINGS = [
    {"name": "北投科技", "code": "600936"},
    {"name": "航天智装", "code": "300455"},
    {"name": "创力集团", "code": "603012"},
    {"name": "金道科技", "code": "301279"},
    {"name": "安彩高科", "code": "600207"},
    {"name": "凯龙高科", "code": "300912"},
    {"name": "海兰信", "code": "300065"},
    {"name": "翰宇药业", "code": "300199"},
    {"name": "君禾股份", "code": "603617"},
    {"name": "南风股份", "code": "300004"},
    {"name": "保变电气", "code": "600550"},
]

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def get_flow(code):
    cache = load_cache()
    dims = cache.get('dimensions', cache)
    stocks = dims.get('capital_flow', dims.get('stocks', {}))
    stock_data = stocks.get(code, {})
    if stock_data:
        val = stock_data.get('main_net_inflow')
        return val  # Return None if value is None, don't default to 0
    return None

def get_note():
    """Return the note field (useful for pre-market data date info)"""
    cache = load_cache()
    return cache.get('note', '')

def get_all_flows():
    cache = load_cache()
    dims = cache.get('dimensions', cache)
    stocks = dims.get('capital_flow', dims.get('stocks', {}))
    last_update = cache.get('last_update', '无')
    
    lines = []
    alerts = []
    
    for h in HOLDINGS:
        code = h['code']
        name = h['name']
        stock_data = stocks.get(code, {})
        
        if stock_data:
            main_net = stock_data.get('main_net_inflow', 0)
            main_pct = stock_data.get('main_net_pct', 0)
            icon = '🟢' if main_net > 0 else '🔴'
            lines.append(f"| {icon} {name} | {main_net/10000:+,.0f}万 | {main_pct:+.2f}% |")
            
            # 资金面预警: 大幅流出
            if main_net < -50000000:  # 净流出>5000万
                alerts.append(f"⚠️ {name} 主力大幅净流出 {main_net/10000:+,.0f}万")
        else:
            lines.append(f"| ⚪ {name} | 无数据 | - |")
    
    return lines, alerts, last_update

if __name__ == '__main__':
    lines, alerts, last_update = get_all_flows()
    note = get_note()
    print(f"📊 资金流向 (更新: {last_update})")
    if note:
        print(f"📝 {note}")
    print("| 股票 | 主力净流入 | 占比 |")
    print("|------|-----------|------|")
    for l in lines:
        print(l)
    if alerts:
        print("\n🚨 资金面预警:")
        for a in alerts:
            print(a)
