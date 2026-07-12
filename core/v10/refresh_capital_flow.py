#!/usr/bin/env python3
"""
资金面缓存刷新脚本 v3 — 东方财富免费API版
v2使用MX妙想（已休眠10次/天），v3改用东方财富免费API：
  1. push2实时API（一次多只，最快）
  2. datacenter API（逐只，最稳定）
  3. push2his历史API（降级）
无需API Key，无调用限制，数据与MX妙想完全一致。
每30分钟运行一次，写入 ~/.hermes/cache/capital_flow.json
"""

import json, os, sys, time
from datetime import datetime

# 集合竞价时段跳过
_now = datetime.now()
if _now.hour == 9 and _now.minute < 30:
    print(f"⏳ 集合竞价中({_now.strftime('%H:%M')})，跳过资金面缓存")
    sys.exit(0)

SCRIPTS_DIR = os.path.expanduser("~/.hermes/scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

CACHE_FILE = os.path.expanduser("~/.hermes/cache/capital_flow.json")


def get_stock_codes():
    """获取需要查询的股票代码"""
    codes = set()
    
    # 1. 持仓
    try:
        from current_holdings import get_holdings
        for h in get_holdings():
            code = h.get("code", "").replace(".SH", "").replace(".SZ", "")
            if code:
                codes.add(code)
    except:
        pass
    
    # 2. V10 watchlist
    try:
        wl_path = os.path.expanduser("~/.hermes/cache/v10_watchlist.json")
        if os.path.exists(wl_path):
            with open(wl_path, "r", encoding="utf-8") as f:
                wl = json.load(f)
            for s in wl.get("stocks", []):
                code = s.get("code", "").replace(".SH", "").replace(".SZ", "")
                if code:
                    codes.add(code)
    except:
        pass
    
    # 3. 模拟盘持仓
    try:
        portfolio_path = os.path.expanduser("~/.hermes/workspace/qmt_sim_portfolio.json")
        if os.path.exists(portfolio_path):
            with open(portfolio_path, "r", encoding="utf-8") as f:
                portfolio = json.load(f)
            for pos in portfolio.get("positions", []):
                code = pos.get("code", "").replace(".SH", "").replace(".SZ", "")
                if code:
                    codes.add(code)
    except:
        pass
    
    return sorted(codes)


def main():
    print(f"[{datetime.now().strftime('%H:%M')}] 资金面缓存刷新 v3 (东方财富免费API)")
    
    codes = get_stock_codes()
    if not codes:
        print("没有需要查询的股票")
        return
    
    print(f"查询 {len(codes)} 只: {', '.join(codes[:10])}{'...' if len(codes) > 10 else ''}")
    
    # 优先使用东方财富免费API（三级降级：实时→数据中心→历史）
    results = {}
    try:
        from eastmoney_capital_flow import query_capital_flow_batch, save_capital_flow
        t0 = time.time()
        results = query_capital_flow_batch(codes)
        t1 = time.time()
        print(f"东方财富API: {len(results)}/{len(codes)}只成功 ({t1-t0:.1f}秒)")
    except Exception as e:
        print(f"东方财富API查询失败: {e}")
    
    # 降级：MX妙想（可能已休眠，仅作为备用）
    missing = [c for c in codes if c not in results]
    if missing and not results:
        print(f"⚠️ 东方财富API失败，尝试MX妙想备用...")
        try:
            from mx_capital_flow import query_capital_flow_simple, save_capital_flow_mx
            mx_results = query_capital_flow_simple(missing)
            if mx_results:
                results.update(mx_results)
                print(f"MX妙想备用: {len(mx_results)}只成功")
        except Exception as e:
            print(f"MX妙想也失败: {e}")
    
    # 保存
    if results:
        # 使用 eastmoney_capital_flow 的保存函数
        try:
            from eastmoney_capital_flow import save_capital_flow as save_em
            save_em(results, source="eastmoney_free")
        except ImportError:
            # 回退到旧格式
            from mx_capital_flow import save_capital_flow_mx
            save_capital_flow_mx(results, source="eastmoney_free")
        
        print(f"✅ 缓存已保存: {CACHE_FILE}")
        for code in sorted(results.keys()):
            val = results[code]
            if isinstance(val, dict):
                inflow = val.get('main_net_inflow', 0)
            else:
                inflow = val
            d = "流入" if inflow > 0 else "流出"
            amt = abs(inflow)
            s = f"{amt/10000:.2f}亿" if amt >= 10000 else f"{amt:.0f}万"
            print(f"  {code} 主力净{d}{s}")
    else:
        print("❌ 无数据")


if __name__ == "__main__":
    main()
