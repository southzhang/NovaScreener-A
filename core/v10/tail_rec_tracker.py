#!/usr/bin/env python3
"""
尾盘选股推荐验证追踪器
- 记录每日推荐
- 自动验证次日/3日表现
- 连续亏损触发冷静期
"""
import json, os, sys, urllib.request
from datetime import datetime, timedelta

CACHE_PATH = os.path.expanduser("~/.hermes/cache/tail_rec_tracker.json")

def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {"recommendations": [], "cooldown_until": None, "stats": {"total": 0, "win_1d": 0, "win_3d": 0, "streak_loss": 0}}

def save_cache(data):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_kline_after(code, buy_date, days=3):
    """获取买入日后的K线数据"""
    secid = ("sh" if code.startswith("6") else "sz") + code
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_day&param={secid},day,,,15,qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    txt = resp.read().decode("utf-8", errors="ignore")
    data = json.loads(txt.split("=", 1)[1])
    d = data.get("data", {})
    kkey = list(d.keys())[0]
    klines = d[kkey].get("qfqday", d[kkey].get("day", []))
    after = [k for k in klines if k[0] > buy_date]
    return after[:days]

def add_recommendation(date, stocks):
    """记录推荐 stocks=[{"name":"xx","code":"000636","price":33.99,"signal":"★★☆"},...]"""
    cache = load_cache()
    rec = {
        "date": date,
        "stocks": stocks,
        "validated": False,
        "next_day": {},
        "three_day": {}
    }
    cache["recommendations"].append(rec)
    cache["recommendations"] = cache["recommendations"][-30:]
    save_cache(cache)
    return rec

def validate_recommendations():
    """验证历史推荐的次日/3日表现"""
    cache = load_cache()
    today = datetime.now().strftime("%Y-%m-%d")
    
    for rec in cache["recommendations"]:
        if rec["validated"]:
            continue
        
        rec_date = rec["date"]
        days_since = (datetime.now() - datetime.strptime(rec_date, "%Y-%m-%d")).days
        if days_since < 1:
            continue
        
        for stock in rec["stocks"]:
            code = stock["code"]
            buy_price = stock["price"]
            key = f"{rec_date}_{code}"
            
            if key not in rec.get("next_day", {}):
                klines = get_kline_after(code, rec_date, 1)
                if klines:
                    next_close = float(klines[0][4])
                    next_high = float(klines[0][2])
                    pnl = (next_close / buy_price - 1) * 100
                    rec.setdefault("next_day", {})[key] = {
                        "close": next_close,
                        "high": next_high,
                        "pnl_pct": round(pnl, 2),
                        "win": pnl > 0
                    }
            
            if key not in rec.get("three_day", {}) and days_since >= 3:
                klines = get_kline_after(code, rec_date, 3)
                if len(klines) >= 2:
                    last_close = float(klines[-1][4])
                    max_high = max(float(k[2]) for k in klines)
                    pnl = (last_close / buy_price - 1) * 100
                    best = (max_high / buy_price - 1) * 100
                    rec.setdefault("three_day", {})[key] = {
                        "close": last_close,
                        "max_high": max_high,
                        "pnl_pct": round(pnl, 2),
                        "best_pct": round(best, 2),
                        "win": pnl > 0
                    }
        
        if days_since >= 1:
            rec["validated"] = days_since >= 3
    
    # 更新统计
    total = 0
    win_1d = 0
    win_3d = 0
    for rec in cache["recommendations"]:
        for key, v in rec.get("next_day", {}).items():
            total += 1
            if v["win"]:
                win_1d += 1
        for key, v in rec.get("three_day", {}).items():
            if v["win"]:
                win_3d += 1
    
    # 连续亏损计数
    streak = 0
    for rec in reversed(cache["recommendations"]):
        rec_results = []
        for key, v in rec.get("next_day", {}).items():
            rec_results.append(v["win"])
        if rec_results:
            if all(not r for r in rec_results):
                streak += 1
            else:
                break
    
    cache["stats"] = {
        "total": total,
        "win_1d": win_1d,
        "win_3d": win_3d,
        "win_rate_1d": round(win_1d / total * 100, 1) if total > 0 else 0,
        "win_rate_3d": round(win_3d / max(total, 1) * 100, 1),
        "streak_loss": streak
    }
    
    # 冷静期：连续3次次日全亏 → 冷静2个交易日
    if streak >= 3:
        cooldown_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        cache["cooldown_until"] = cooldown_date
    elif cache.get("cooldown_until") and today > cache["cooldown_until"]:
        cache["cooldown_until"] = None
    
    save_cache(cache)
    return cache

def check_cooldown():
    """检查是否在冷静期内"""
    cache = load_cache()
    today = datetime.now().strftime("%Y-%m-%d")
    if cache.get("cooldown_until") and today <= cache["cooldown_until"]:
        return True, cache["cooldown_until"]
    return False, None

def get_stats():
    """获取推荐统计摘要"""
    cache = load_cache()
    return cache.get("stats", {})

def main():
    if len(sys.argv) < 2:
        print("Usage: tail_rec_tracker.py [add|validate|stats|cooldown]")
        return
    
    cmd = sys.argv[1]
    
    if cmd == "add":
        date = sys.argv[2]
        stocks = json.loads(sys.argv[3])
        add_recommendation(date, stocks)
        print(f"OK: recorded {len(stocks)} stocks for {date}")
    
    elif cmd == "validate":
        cache = validate_recommendations()
        stats = cache["stats"]
        print(f"验证完成: 总{stats['total']}次, 次日胜率{stats.get('win_rate_1d',0)}%, 3日胜率{stats.get('win_rate_3d',0)}%, 连亏{stats.get('streak_loss',0)}次")
        if cache.get("cooldown_until"):
            print(f"⚠️ 冷静期至: {cache['cooldown_until']}")
    
    elif cmd == "stats":
        stats = get_stats()
        print(f"总推荐: {stats.get('total',0)}次")
        print(f"次日胜率: {stats.get('win_rate_1d',0)}%")
        print(f"3日胜率: {stats.get('win_rate_3d',0)}%")
        print(f"连续亏损: {stats.get('streak_loss',0)}次")
        
        cache = load_cache()
        recent = cache["recommendations"][-5:]
        for rec in reversed(recent):
            print(f"\n  {rec['date']}:")
            for s in rec["stocks"]:
                key = f"{rec['date']}_{s['code']}"
                nd = rec.get("next_day", {}).get(key, {})
                td = rec.get("three_day", {}).get(key, {})
                pnl_1d = f"{nd['pnl_pct']:+.2f}%" if nd else "待验证"
                pnl_3d = f"{td['pnl_pct']:+.2f}%" if td else "待验证"
                print(f"    {s['name']}({s['code']}): 次日{pnl_1d}, 3日{pnl_3d}")
    
    elif cmd == "cooldown":
        in_cd, until = check_cooldown()
        if in_cd:
            print(f"COOLDOWN: 冷静期至{until}")
        else:
            print("OK: 可正常推荐")
    
    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()
