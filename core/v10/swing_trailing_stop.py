#!/usr/bin/env python3
"""
Swing Trailing Stop - 动态移动止盈模块
追踪趋势利润，防止回撤吃掉收益

核心逻辑:
  三层止盈机制，由松到紧：
  
  1. ATR追踪止盈(基础): 止盈线 = 最高价 - N×ATR
     - 盈利<5%: N=3 (宽松, 给趋势空间)
     - 盈利5-15%: N=2.5
     - 盈利>15%: N=2 (收紧, 锁定利润)
  
  2. EMA趋势破位(辅助): 收盘价跌破EMA20且次日未收回 → 触发
  
  3. 结构破位(最终防线): 前低被击穿 → 无条件触发

输出:
  - 当前止盈价
  - 止盈触发状态(安全/预警/触发)
  - 建议操作(持有/减仓/清仓)

用法:
  python3 swing_trailing_stop.py 002185              # 默认成本价=买入价
  python3 swing_trailing_stop.py 002185 --cost 19.35  # 指定成本
  python3 swing_trailing_stop.py 002185 --cost 19.35 --shares 700
  python3 swing_trailing_stop.py --portfolio          # 读取current_holdings.py

数据源: 腾讯K线(60-120天) + 实时价格

Version: 1.0 (2026-05-30)
"""

import sys
import os
import json
import urllib.request
import math
from datetime import datetime

# 代理清除
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(k, None)


# ============================================================
# K线数据获取 (同swing_pullback)
# ============================================================

def fetch_klines(code, days=120):
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_day&param={prefix}{code},day,,,{days+10},qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        txt = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(txt.split("=", 1)[1])
        for key in ["qfqday", "day"]:
            klines = data.get("data", {}).get(f"{prefix}{code}", {}).get(key)
            if klines:
                result = []
                for k in klines[-days:]:
                    result.append({
                        "date": k[0],
                        "open": float(k[1]),
                        "close": float(k[2]),
                        "high": float(k[3]),
                        "low": float(k[4]),
                        "volume": float(k[5]) if len(k) > 5 and k[5] else 0
                    })
                return result
    except Exception as e:
        print(f"[WARN] K-line fetch failed for {code}: {e}", file=sys.stderr)
    return []


def fetch_realtime_price(code):
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        txt = resp.read().decode("gbk", errors="ignore")
        parts = txt.split("~")
        if len(parts) > 5:
            return float(parts[3])
    except Exception:
        pass
    return None


def fetch_stock_name(code):
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        txt = resp.read().decode("gbk", errors="ignore")
        parts = txt.split("~")
        if len(parts) > 1:
            return parts[1]
    except Exception:
        pass
    return code


# ============================================================
# 技术指标计算
# ============================================================

def calc_ema(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_atr(klines, period=14):
    if len(klines) < period + 1:
        return []
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = klines[i]["high"], klines[i]["low"], klines[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return calc_ema(trs, period)


def find_swing_highs(klines, window=5):
    """找到近期的波段高点"""
    highs = []
    for i in range(window, len(klines) - window):
        is_high = True
        for j in range(i - window, i + window + 1):
            if j != i and klines[j]["high"] >= klines[i]["high"]:
                is_high = False
                break
        if is_high:
            highs.append({"date": klines[i]["date"], "price": klines[i]["high"]})
    return highs


def find_swing_lows(klines, window=5):
    """找到近期的波段低点"""
    lows = []
    for i in range(window, len(klines) - window):
        is_low = True
        for j in range(i - window, i + window + 1):
            if j != i and klines[j]["low"] <= klines[i]["low"]:
                is_low = False
                break
        if is_low:
            lows.append({"date": klines[i]["date"], "price": klines[i]["low"]})
    return lows


# ============================================================
# 三层止盈计算
# ============================================================

def calc_atr_trailing_stop(klines, cost_price, current_price):
    """
    第一层: 自适应止盈
    根据ATR/价格比自动选择止盈模式：
    - ATR/价格 < 3%: 低波动票 → ATR追踪给足空间(三层收紧)
    - ATR/价格 ≥ 4%: 高波动票 → 固定-3%/+5%快进快出
    - 3%-4%之间: 混合模式，ATR追踪但倍数收紧
    """
    atr_values = calc_atr(klines, 14)
    if not atr_values:
        return {"stop": 0, "atr_multiple": 0, "pct_from_high": 0, "mode": "数据不足"}

    atr = atr_values[-1]
    atr_pct = atr / current_price * 100  # ATR占价格比
    
    # 持仓以来的最高价
    recent = klines[-30:] if len(klines) >= 30 else klines
    highest = max(k["high"] for k in recent)
    
    # 盈利程度
    profit_pct = (current_price - cost_price) / cost_price * 100
    
    # ===== 自适应核心：根据波动率选择止盈模式 =====
    if atr_pct >= 4.0:
        # 高波动票：固定止盈，快进快出
        mode = "高波动固定止盈"
        if profit_pct >= 5:
            stop = cost_price * 1.02  # 盈利>5%后，止损不低于成本+2%
            stage = "锁定利润期"
        else:
            stop = cost_price * 0.97  # -3%硬止损
            stage = "建仓期"
        # 盈利到5%触发止盈
        take_profit = cost_price * 1.05
        
        return {
            "stop": round(stop, 2),
            "take_profit": round(take_profit, 2),
            "highest": round(highest, 2),
            "atr": round(atr, 2),
            "atr_pct": round(atr_pct, 2),
            "atr_multiple": 0,
            "profit_pct": round(profit_pct, 2),
            "stage": stage,
            "mode": mode,
            "pct_from_high": round((highest - stop) / highest * 100, 2)
        }
    
    elif atr_pct >= 3.0:
        # 中波动：ATR追踪但倍数收紧
        mode = "中波动收紧ATR"
        if profit_pct < 5:
            n_atr = 2.0
            stage = "建仓期(收紧)"
        elif profit_pct < 15:
            n_atr = 1.5
            stage = "盈利期"
        else:
            n_atr = 1.2
            stage = "丰厚利润期"
        
        stop = highest - n_atr * atr
        pct_from_high = (highest - stop) / highest * 100
        
        return {
            "stop": round(stop, 2),
            "highest": round(highest, 2),
            "atr": round(atr, 2),
            "atr_pct": round(atr_pct, 2),
            "atr_multiple": n_atr,
            "profit_pct": round(profit_pct, 2),
            "stage": stage,
            "mode": mode,
            "pct_from_high": round(pct_from_high, 2)
        }
    
    else:
        # 低波动：经典三层ATR追踪，给足空间
        mode = "低波动ATR追踪"
        if profit_pct < 5:
            n_atr = 3.0
            stage = "建仓期"
        elif profit_pct < 15:
            n_atr = 2.5
            stage = "盈利期"
        else:
            n_atr = 2.0
            stage = "丰厚利润期"
        
        stop = highest - n_atr * atr
        pct_from_high = (highest - stop) / highest * 100
        
        return {
            "stop": round(stop, 2),
            "highest": round(highest, 2),
            "atr": round(atr, 2),
            "atr_pct": round(atr_pct, 2),
            "atr_multiple": n_atr,
            "profit_pct": round(profit_pct, 2),
            "stage": stage,
            "mode": mode,
            "pct_from_high": round(pct_from_high, 2)
        }


def calc_ema_trend_stop(klines):
    """
    第二层: EMA20趋势破位
    收盘跌破EMA20且次日未收回 → 预警
    """
    closes = [k["close"] for k in klines]
    ema20 = calc_ema(closes, 20)
    
    if len(ema20) < 3 or len(closes) < 3:
        return {"status": "数据不足", "ema20": 0, "broken": False}
    
    # 对齐: ema20长度 = len(closes) - 20 + 1
    # 最新EMA20值
    e20 = ema20[-1]
    latest_close = closes[-1]
    prev_close = closes[-2]
    
    # 昨天EMA20
    prev_ema20 = ema20[-2] if len(ema20) >= 2 else e20
    
    # 当前: 是否跌破EMA20
    broken_now = latest_close < e20
    # 昨天: 是否跌破EMA20
    broken_prev = prev_close < prev_ema20
    
    # 连续2日跌破 = 确认破位
    confirmed_break = broken_now and broken_prev
    
    # 距EMA20的距离
    dist_pct = (latest_close - e20) / e20 * 100
    
    if confirmed_break:
        status = "EMA20破位确认"
    elif broken_now:
        status = "EMA20跌破(观察次日能否收回)"
    elif dist_pct < 2:
        status = "逼近EMA20"
    else:
        status = "EMA20上方安全"
    
    return {
        "status": status,
        "ema20": round(e20, 2),
        "dist_pct": round(dist_pct, 2),
        "broken": confirmed_break
    }


def calc_structure_stop(klines):
    """
    第三层: 结构破位(前低击穿)
    最近一个波段低点被击穿 → 无条件触发
    """
    lows = find_swing_lows(klines, window=5)
    
    if not lows:
        return {"status": "无有效前低", "support": 0, "broken": False}
    
    current_price = klines[-1]["close"]
    latest_low_price = klines[-1]["low"]
    
    # 取最近的波段低点作为关键支撑
    recent_lows = lows[-3:] if len(lows) >= 3 else lows
    key_support = min(l["price"] for l in recent_lows)
    
    # 最新K线最低价是否击穿
    broken = latest_low_price < key_support
    
    dist_pct = (current_price - key_support) / key_support * 100
    
    if broken:
        status = "前低已击穿, 结构破位!"
    elif dist_pct < 3:
        status = "逼近前低支撑"
    else:
        status = "前低上方安全"
    
    return {
        "status": status,
        "support": round(key_support, 2),
        "dist_pct": round(dist_pct, 2),
        "broken": broken,
        "swing_lows": [{"date": l["date"], "price": round(l["price"], 2)} for l in recent_lows]
    }


# ============================================================
# 综合止盈判断
# ============================================================

def analyze_trailing_stop(code, cost_price, shares=0):
    """综合分析止盈状态"""
    result = {
        "code": code,
        "name": "",
        "cost_price": cost_price,
        "current_price": 0,
        "shares": shares,
        "profit": 0,
        "profit_pct": 0,
        "layers": {},
        "action": "",
        "stop_price": 0,
        "risk_level": ""
    }
    
    name = fetch_stock_name(code)
    result["name"] = name
    
    price = fetch_realtime_price(code)
    if not price:
        klines = fetch_klines(code, 5)
        price = klines[-1]["close"] if klines else cost_price
    result["current_price"] = price
    
    profit = (price - cost_price) * shares if shares > 0 else (price - cost_price)
    profit_pct = (price - cost_price) / cost_price * 100
    result["profit"] = round(profit, 2)
    result["profit_pct"] = round(profit_pct, 2)
    
    # 获取K线
    klines = fetch_klines(code, 120)
    if len(klines) < 30:
        result["action"] = "数据不足, 无法判断"
        return result
    
    # 三层止盈
    layer1 = calc_atr_trailing_stop(klines, cost_price, price)
    layer2 = calc_ema_trend_stop(klines)
    layer3 = calc_structure_stop(klines)
    
    result["layers"] = {
        "atr_trailing": layer1,
        "ema_trend": layer2,
        "structure": layer3
    }
    
    # 综合判断: 取最紧的止盈价
    stops = []
    if layer1.get("stop", 0) > 0:
        stops.append(layer1["stop"])
    if layer3.get("support", 0) > 0 and not layer3.get("broken"):
        stops.append(layer3["support"])
    
    final_stop = min(stops) if stops else 0
    result["stop_price"] = final_stop
    
    # 风险等级和操作建议
    triggers = 0
    warnings = 0
    
    if layer1.get("stop", 0) > 0 and price <= layer1["stop"]:
        triggers += 1
    elif layer1.get("stop", 0) > 0 and (price - layer1["stop"]) / price * 100 < 3:
        warnings += 1
    
    if layer2.get("broken"):
        triggers += 1
    elif "逼近" in layer2.get("status", ""):
        warnings += 1
    
    if layer3.get("broken"):
        triggers += 1
    elif "逼近" in layer3.get("status", ""):
        warnings += 1
    
    if triggers >= 2 or layer3.get("broken"):
        result["risk_level"] = "⛔ 触发"
        result["action"] = "建议清仓/大幅减仓"
    elif triggers == 1:
        result["risk_level"] = "🔴 预警"
        result["action"] = "建议减仓1/3, 提高警惕"
    elif warnings >= 2:
        result["risk_level"] = "🟡 关注"
        result["action"] = "密切关注, 可考虑减仓1/4"
    elif warnings == 1:
        result["risk_level"] = "🟢 观察"
        result["action"] = "趋势尚可, 注意支撑位"
    else:
        result["risk_level"] = "🟢 安全"
        result["action"] = "趋势健康, 持有"
    
    return result


def load_portfolio():
    """读取current_holdings.py"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "holdings",
        os.path.expanduser("~/.hermes/scripts/current_holdings.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "HOLDINGS", [])


def format_results(results):
    """格式化输出"""
    lines = []
    lines.append("# 动态移动止盈")
    lines.append("")
    lines.append("三层止盈机制: ATR追踪(基础) → EMA20破位(辅助) → 前低击穿(防线)")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    for r in results:
        name = r.get("name", r["code"])
        price = r["current_price"]
        cost = r["cost_price"]
        pct = r["profit_pct"]
        profit = r["profit"]
        
        # 盈亏标识
        if pct > 0:
            pnl = f"+{pct:.1f}% (+{profit:.0f}元)" if r["shares"] > 0 else f"+{pct:.1f}%"
        else:
            pnl = f"{pct:.1f}% ({profit:.0f}元)" if r["shares"] > 0 else f"{pct:.1f}%"
        
        lines.append(f"## {name} ({r['code']}) | {r['risk_level']} {r['action']}")
        lines.append(f"成本: {cost} → 现价: {price} | {pnl}")
        lines.append("")
        
        layers = r.get("layers", {})
        
        # 第一层: ATR追踪
        l1 = layers.get("atr_trailing", {})
        if l1.get("stop"):
            mode_tag = f" [{l1.get('mode', 'ATR追踪')}]" if l1.get("mode") else ""
            atr_pct_tag = f" | ATR/价格={l1.get('atr_pct', 0):.1f}%" if l1.get("atr_pct") else ""
            if l1.get("atr_multiple", 0) > 0:
                lines.append(f"**止盈模式{mode_tag}**: 止盈线={l1['stop']} | 阶段={l1['stage']} | ATR×{l1['atr_multiple']}={l1['atr']}×{l1['atr_multiple']}={round(l1['atr']*l1['atr_multiple'],2)} | 近期高点={l1['highest']}{atr_pct_tag}")
            else:
                # 固定止盈模式
                tp = l1.get('take_profit', 0)
                lines.append(f"**止盈模式{mode_tag}**: 止损线={l1['stop']} | 止盈线={tp} | 阶段={l1['stage']} | ATR/价格={l1.get('atr_pct', 0):.1f}%")
        
        # 第二层: EMA趋势
        l2 = layers.get("ema_trend", {})
        if l2.get("ema20"):
            lines.append(f"**EMA20趋势**: EMA20={l2['ema20']} | 距离={l2['dist_pct']:+.1f}% | {l2['status']}")
        
        # 第三层: 结构支撑
        l3 = layers.get("structure", {})
        if l3.get("support"):
            lows_str = ", ".join(f"{l['price']}({l['date']})" for l in l3.get("swing_lows", []))
            lines.append(f"**前低支撑**: 关键支撑={l3['support']} | 距离={l3['dist_pct']:+.1f}% | {l3['status']}")
            lines.append(f"  波段低点: {lows_str}")
        
        # 最终止盈价
        if r.get("stop_price", 0) > 0:
            dist_to_stop = (price - r["stop_price"]) / price * 100
            lines.append(f"**综合止盈价**: {r['stop_price']} (距当前-{dist_to_stop:.1f}%)")
        
        lines.append("")
    
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Swing Trailing Stop")
    parser.add_argument("codes", nargs="*", help="Stock codes")
    parser.add_argument("--cost", type=float, default=0, help="Cost price (for single stock)")
    parser.add_argument("--shares", type=int, default=0, help="Number of shares")
    parser.add_argument("--portfolio", action="store_true", help="Read from current_holdings.py")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    
    positions = []
    
    if args.portfolio:
        try:
            holdings = load_portfolio()
            for h in holdings:
                positions.append({
                    "code": h["code"],
                    "cost": h.get("avg_cost", h.get("cost", 0)),
                    "shares": h.get("shares", 0)
                })
        except Exception as e:
            print(f"Failed to load portfolio: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.codes:
        for code in args.codes:
            positions.append({
                "code": code,
                "cost": args.cost,
                "shares": args.shares
            })
    else:
        print("Usage: python3 swing_trailing_stop.py <code> [--cost X] [--shares N] [--portfolio] [--json]")
        sys.exit(1)
    
    results = []
    for pos in positions:
        print(f"  Analyzing {pos['code']}...", file=sys.stderr)
        r = analyze_trailing_stop(pos["code"], pos["cost"], pos["shares"])
        results.append(r)
    
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_results(results))


if __name__ == "__main__":
    main()
