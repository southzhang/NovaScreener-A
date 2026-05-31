#!/usr/bin/env python3
"""
V10 尾盘预取脚本 (14:25)
从V10 watchlist读取信号股，用腾讯行情API获取实时行情+资金面，
写入 ~/.hermes/cache/v10_tail_prefetch.json 供14:30 agent消费。

no_agent模式运行，不调LLM，纯机械数据采集。
"""
import json, os, re, sys, urllib.request, urllib.error
from datetime import datetime

# 不使用代理（腾讯行情是国内API，直接访问）
PROXIES = {}

CACHE_DIR = os.path.expanduser("~/.hermes/cache")
WATCHLIST_PATH = os.path.join(CACHE_DIR, "v10_watchlist.json")
OUTPUT_PATH = os.path.join(CACHE_DIR, "v10_tail_prefetch.json")
def is_trading_time():
    """检查是否在交易时段（14:20-14:50给预取用）"""
    now = datetime.now()
    h, m = now.hour, now.minute
    # 宽松窗口：14:20-15:00
    if h == 14 and 20 <= m <= 59:
        return True
    if h == 15 and m == 0:
        return True
    return False

def tencent_batch_quote(codes):
    """批量获取腾讯实时行情，codes是股票代码列表(如['600203','300410'])"""
    if not codes:
        return {}
    
    # 构建secid列表
    secids = []
    for c in codes:
        if c.startswith('6'):
            secids.append(f"sh{c}")
        else:
            secids.append(f"sz{c}")
    
    # 加上三大指数
    secids.extend(['sh000001', 'sz399001', 'sz399006'])
    
    # 批量查询（每批最多80个）
    results = {}
    for i in range(0, len(secids), 80):
        batch = secids[i:i+80]
        qs = ",".join(batch)
        url = f"https://qt.gtimg.cn/q={qs}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            txt = resp.read().decode('gbk', errors='ignore')
            results.update(parse_tencent_batch(txt))
        except Exception as e:
            print(f"⚠️ 腾讯行情批次{i//80}失败: {e}", file=sys.stderr)
    
    return results

def parse_tencent_batch(output):
    """解析腾讯qt.gtimg.cn批量返回"""
    stocks = {}
    for line in output.strip().split('\n'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        try:
            # 格式: v_sh600203="1~福日电子~600203~...~";
            m = re.search(r'v_(\w+)="(.+)"', line)
            if not m:
                continue
            secid = m.group(1)
            parts = m.group(2).split('~')
            if len(parts) < 50:
                continue
            
            code = parts[2]
            name = parts[1]
            
            def safe_float(idx, default=0):
                try:
                    return float(parts[idx]) if parts[idx] else default
                except (ValueError, IndexError):
                    return default
            
            def safe_int(idx, default=0):
                try:
                    return int(float(parts[idx])) if parts[idx] else default
                except (ValueError, IndexError):
                    return default
            
            # 判断是指数还是个股
            is_index = code in ['000001', '399001', '399006']
            
            stocks[code] = {
                "secid": secid,
                "name": name,
                "code": code,
                "current_price": safe_float(3),
                "yesterday_close": safe_float(4),
                "open_price": safe_float(5),
                "volume": safe_int(6),  # 手
                "buy_volume": safe_int(7),  # 外盘(手)
                "sell_volume": safe_int(8),  # 内盘(手)
                "change": safe_float(31),
                "change_pct": safe_float(32),
                "high": safe_float(33),
                "low": safe_float(34),
                "amount": safe_float(37),  # 万元
                "turnover_rate": safe_float(38),
                "pe_dynamic": safe_float(39) if not is_index else 0,
                "amplitude": safe_float(43),
                "main_inflow": safe_float(49) if len(parts) > 49 else 0,  # 主力净流入(万元)
                "is_index": is_index,
            }
            
            # 计算振幅（如果字段43为0则手动算）
            if stocks[code]["amplitude"] == 0 and stocks[code]["yesterday_close"] > 0:
                h, l = stocks[code]["high"], stocks[code]["low"]
                if h > 0 and l > 0:
                    stocks[code]["amplitude"] = round((h - l) / stocks[code]["yesterday_close"] * 100, 2)
            
        except Exception:
            continue
    
    return stocks

def main():
    # 交易时间检查（注释掉方便调试，生产环境取消注释）
    # if not is_trading_time():
    #     print("非交易时间，跳过预取")
    #     return
    
    # Step 1: 读取watchlist
    if not os.path.exists(WATCHLIST_PATH):
        print("⛔ watchlist.json不存在", file=sys.stderr)
        # 写空缓存
        write_empty_cache("watchlist不存在")
        return
    
    with open(WATCHLIST_PATH) as f:
        watchlist = json.load(f)
    
    stocks = watchlist.get("stocks", [])
    scan_time = watchlist.get("scan_time", "")
    count = watchlist.get("count", 0)
    
    if count == 0:
        print("今日无V10信号，写入空缓存")
        write_empty_cache("今日无V10信号", scan_date=scan_time)
        return
    
    # 只取全买入和强庄买
    candidates_list = [s for s in stocks if s.get("signal") in ["全买入", "强庄买"]]
    
    # 如果没有全买入/强庄买，也包含基础买（但标注）
    if not candidates_list:
        candidates_list = stocks  # 全部纳入
        print(f"⚠️ 无全买入/强庄买信号，纳入全部{len(candidates_list)}只基础买", file=sys.stderr)
    
    codes = [s["code"] for s in candidates_list]
    print(f"📊 候选股: {len(codes)}只 - {', '.join(codes[:10])}")
    
    # Step 2: 腾讯行情批量获取
    print("⏳ 获取腾讯实时行情...")
    quotes = tencent_batch_quote(codes)
    print(f"✅ 获取到{len(quotes)}只股票行情")
    
    # 提取指数数据
    index_data = {}
    for idx_code in ['000001', '399001', '399006']:
        if idx_code in quotes:
            q = quotes[idx_code]
            index_data[f"{'sh' if idx_code.startswith('0') else 'sz'}{idx_code}"] = {
                "name": q["name"],
                "price": q["current_price"],
                "change_pct": q["change_pct"],
                "amount": q["amount"],
            }
    
    # Step 3: 组装candidates
    candidates = {}
    for s in candidates_list:
        code = s["code"]
        q = quotes.get(code, {})
        
        # 构建real_time_quote
        rt_quote = {
            "name": q.get("name", s.get("name", "")),
            "code": code,
            "current_price": q.get("current_price", s.get("price", 0)),
            "yesterday_close": q.get("yesterday_close", 0),
            "open_price": q.get("open_price", 0),
            "change_pct": q.get("change_pct", 0),
            "change": q.get("change", 0),
            "high": q.get("high", 0),
            "low": q.get("low", 0),
            "volume": q.get("volume", 0),
            "amount": q.get("amount", 0),
            "turnover_rate": q.get("turnover_rate", 0),
            "amplitude": q.get("amplitude", 0),
            "buy_volume": q.get("buy_volume", 0),
            "sell_volume": q.get("sell_volume", 0),
            "pe_dynamic": q.get("pe_dynamic", 0),
        }
        
        # 判断尾盘走势
        if q.get("current_price", 0) > 0 and q.get("high", 0) > 0:
            price_pos = (q["current_price"] - q.get("low", 0)) / (q["high"] - q.get("low", 0)) if q["high"] != q.get("low", 0) else 0.5
            if price_pos > 0.8:
                rt_quote["latest_change"] = "尾盘运行在日内高位"
            elif price_pos > 0.5:
                rt_quote["latest_change"] = "尾盘运行在日内中高位"
            elif price_pos > 0.3:
                rt_quote["latest_change"] = "尾盘运行在日内中位"
            else:
                rt_quote["latest_change"] = "尾盘运行在日内低位"
        
        candidates[code] = {
            "code": code,
            "name": s.get("name", q.get("name", "")),
            "signal": s.get("signal", ""),
            "real_time_quote": rt_quote,
            "sector_info": {"raw_content": "行业归属：需手动查（同花顺API在no_agent模式不可用）"},
            "capital_flow": {
                "source": "腾讯field[50]",
                "value": q.get("main_inflow", 0),
                "has_data": q.get("main_inflow", 0) != 0,
            },
            "key_levels": s.get("key_levels", {}),
        }
    
    # Step 4: 写入缓存
    output = {
        "prefetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan_date": scan_time,
        "signals": {
            "full_buy": [s["code"] for s in candidates_list if s.get("signal") == "全买入"],
            "strong_buy": [s["code"] for s in candidates_list if s.get("signal") == "强庄买"],
            "base_buy": [s["code"] for s in candidates_list if s.get("signal") == "基础买"],
        },
        "candidates": candidates,
        "sectors": {"trending_sectors": [], "concepts": []},
        "index": index_data,
    }
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 预取完成: {len(candidates)}只候选股，写入 {OUTPUT_PATH}")
    print(f"📊 大盘: {index_data.get('sh000001', {}).get('price', 'N/A')} ({index_data.get('sh000001', {}).get('change_pct', 'N/A')}%)")

def write_empty_cache(reason="", scan_date=""):
    """写入空缓存（0信号场景）"""
    output = {
        "prefetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan_date": scan_date,
        "signals": {"full_buy": [], "strong_buy": [], "base_buy": []},
        "candidates": {},
        "sectors": {"trending_sectors": [], "concepts": []},
        "index": {},
        "_note": reason,
    }
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"写入空缓存: {reason}")

if __name__ == "__main__":
    main()
