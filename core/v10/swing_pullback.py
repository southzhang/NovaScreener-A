#!/usr/bin/env python3
"""
Swing Pullback Detector - 波段回调识别模块
在V10趋势信号基础上，识别最佳回调入场点

核心逻辑:
  1. 主趋势向上: EMA20 > EMA50 > EMA120 (多头排列)
  2. 价格回调到支撑区: 接近EMA20或EMA50
  3. 缩量回调: 近3日成交量 < 20日均量 * 0.8
  4. 动量未死: RSI(14) > 40, MACD未死叉

评分: 每条件0-2分, 总分0-8
  >=6分: 优质回调入场点
  4-5分: 一般, 观察等待更好价格
  <4分:  回调不到位或趋势已弱

用法:
  python3 swing_pullback.py 300065                    # 单只
  python3 swing_pullback.py 300065 002185              # 多只
  python3 swing_pullback.py --watchlist                # 从V10观察池读取
  python3 swing_pullback.py --json 300065              # JSON输出

数据源: 腾讯K线(60-120天)

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
# K线数据获取
# ============================================================

def fetch_klines(code, days=120):
    """从腾讯K线API获取日K线数据"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_day&param={prefix}{code},day,,,{days+10},qfq"
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
    """获取实时价格"""
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


# ============================================================
# 技术指标计算（纯Python，无外部依赖）
# ============================================================

def calc_ema(values, period):
    """计算EMA"""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_atr(klines, period=14):
    """计算ATR(14)"""
    if len(klines) < period + 1:
        return []
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = klines[i]["high"], klines[i]["low"], klines[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    # 用EMA平滑
    return calc_ema(trs, period)


def calc_rsi(closes, period=14):
    """计算RSI"""
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    rsi = []
    if avg_loss == 0:
        rsi.append(100)
    else:
        rs = avg_gain / avg_loss
        rsi.append(100 - 100 / (1 + rs))
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100 - 100 / (1 + rs))
    return rsi


def calc_macd(closes, fast=12, slow=26, signal=9):
    """计算MACD，返回(macd_line, signal_line, histogram)"""
    if len(closes) < slow + signal:
        return [], [], []
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    # 对齐
    offset = len(ema_fast) - len(ema_slow)
    dif = [ef - es for ef, es in zip(ema_fast[offset:], ema_slow)]
    dea = calc_ema(dif, signal)
    offset2 = len(dif) - len(dea)
    hist = [d - e for d, e in zip(dif[offset2:], dea)]
    return dif[offset2:], dea, hist


# ============================================================
# 波段回调评分
# ============================================================

def score_trend_alignment(ema20, ema50, ema120):
    """趋势排列评分: EMA20>EMA50>EMA120=完美多头"""
    if not ema20 or not ema50 or not ema120:
        return 0, "EMA数据不足"
    e20, e50, e120 = ema20[-1], ema50[-1], ema120[-1]
    if e20 > e50 > e120:
        return 2, f"完美多头(EMA20>{e50:.2f}>EMA120={e120:.2f})"
    elif e20 > e50:
        return 1, f"短多(EMA20>EMA50, 但EMA50<EMA120)"
    else:
        return 0, f"非多头(EMA20={e20:.2f}<EMA50={e50:.2f})"


def score_pullback_position(price, ema20, ema50, atr_value):
    """回调位置评分: 价格接近EMA支撑"""
    if not ema20 or not ema50 or not atr_value:
        return 0, "数据不足"
    
    e20, e50 = ema20[-1], ema50[-1]
    dist_e20 = (price - e20) / e20 * 100  # 距EMA20的百分比
    dist_e50 = (price - e50) / e50 * 100  # 距EMA50的百分比
    
    # ATR的2倍作为支撑区间
    atr_pct = atr_value / price * 100
    
    if abs(dist_e20) <= atr_pct:  # 价格在EMA20的1ATR范围内
        return 2, f"回踩EMA20(偏离{dist_e20:+.1f}%, 1ATR={atr_pct:.1f}%)"
    elif abs(dist_e50) <= atr_pct * 1.5:  # 价格在EMA50的1.5ATR范围内
        return 2, f"回踩EMA50(偏离{dist_e50:+.1f}%)"
    elif 0 < dist_e20 <= 3:  # 价格在EMA20上方0-3%
        return 1, f"接近EMA20(偏离+{dist_e20:.1f}%)"
    elif -3 < dist_e20 <= 0:  # 略跌破EMA20
        return 1, f"略破EMA20(偏离{dist_e20:.1f}%)"
    elif dist_e20 > 5:  # 远离EMA20
        return 0, f"远离EMA20(+{dist_e20:.1f}%), 等回调"
    elif dist_e50 < -3:  # 跌破EMA50太多
        return 0, f"跌破EMA50({dist_e50:.1f}%), 趋势可能走坏"
    else:
        return 0, f"位置中性(距EMA20={dist_e20:+.1f}%)"


def score_volume_shrink(klines):
    """缩量回调评分: 近3日缩量"""
    if len(klines) < 20:
        return 0, "K线数据不足"
    
    vols = [k["volume"] for k in klines if k["volume"] > 0]
    if len(vols) < 10:
        return 0, "成交量数据不足"
    
    avg_20 = sum(vols[-20:]) / len(vols[-20:])
    recent_3 = sum(vols[-3:]) / 3
    
    ratio = recent_3 / avg_20 if avg_20 > 0 else 1
    
    if ratio < 0.5:
        return 2, f"极度缩量(近3日均量/20日均量={ratio:.1%})"
    elif ratio < 0.8:
        return 1, f"缩量({ratio:.1%})"
    else:
        return 0, f"放量或持平({ratio:.1%}), 非回调特征"


def score_momentum(rsi_values, macd_hist):
    """动量状态评分: RSI未超卖+MACD未死叉"""
    score = 0
    desc_parts = []
    
    # RSI
    if rsi_values:
        rsi = rsi_values[-1]
        if 40 <= rsi <= 60:
            score += 1
            desc_parts.append(f"RSI中性({rsi:.0f})")
        elif 30 <= rsi < 40:
            score += 2  # 接近超卖=更好的入场价
            desc_parts.append(f"RSI偏低({rsi:.0f}), 更好的入场点")
        elif rsi > 70:
            score += 0
            desc_parts.append(f"RSI超买({rsi:.0f}), 追高风险")
        else:
            score += 0
            desc_parts.append(f"RSI={rsi:.0f}")
    
    # MACD
    if macd_hist and len(macd_hist) >= 3:
        if macd_hist[-1] > 0:
            score += 1
            desc_parts.append("MACD红柱")
        elif macd_hist[-1] > macd_hist[-2]:
            score += 0  # 绿柱缩短，可能金叉
            desc_parts.append("MACD绿柱缩短")
        else:
            desc_parts.append("MACD绿柱扩大")
    
    return min(score, 2), ", ".join(desc_parts) if desc_parts else "数据不足"


# ============================================================
# 综合评分
# ============================================================

def analyze_swing_pullback(code):
    """分析单只股票的波段回调机会"""
    result = {
        "code": code, "name": "",
        "total_score": 0, "max_score": 8,
        "factors": {},
        "entry_zone": {"low": 0, "high": 0},
        "stop_loss": 0,
        "verdict": ""
    }

    # 获取K线
    klines = fetch_klines(code, 120)
    if len(klines) < 60:
        result["verdict"] = "K线数据不足(<60天)"
        return result

    closes = [k["close"] for k in klines]
    # 获取名称和现价
    price = fetch_realtime_price(code)
    if not price:
        price = closes[-1]
    
    # 获取名称
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        txt = resp.read().decode("gbk", errors="ignore")
        parts = txt.split("~")
        if len(parts) > 1:
            result["name"] = parts[1]
    except Exception:
        pass

    # 计算指标
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema120 = calc_ema(closes, 120)
    atr_values = calc_atr(klines, 14)
    rsi_values = calc_rsi(closes, 14)
    macd_dif, macd_dea, macd_hist = calc_macd(closes)

    current_atr = atr_values[-1] if atr_values else 0

    # 1. 趋势排列 (0-2)
    s1, d1 = score_trend_alignment(ema20, ema50, ema120)
    result["factors"]["trend"] = {"score": s1, "desc": d1}

    # 2. 回调位置 (0-2)
    s2, d2 = score_pullback_position(price, ema20, ema50, current_atr)
    result["factors"]["pullback"] = {"score": s2, "desc": d2}

    # 3. 缩量回调 (0-2)
    s3, d3 = score_volume_shrink(klines)
    result["factors"]["volume"] = {"score": s3, "desc": d3}

    # 4. 动量状态 (0-2)
    s4, d4 = score_momentum(rsi_values, macd_hist)
    result["factors"]["momentum"] = {"score": s4, "desc": d4}

    # 汇总
    total = s1 + s2 + s3 + s4
    result["total_score"] = total

    # 入场区间: EMA20 ± 1ATR 或 EMA50 ± 1.5ATR
    e20 = ema20[-1] if ema20 else price
    e50 = ema50[-1] if ema50 else price
    if s1 >= 1:  # 趋势至少短多
        if s2 == 2:  # 已经在支撑位
            result["entry_zone"] = {
                "low": round(e20 - current_atr, 2),
                "high": round(e20 + current_atr * 0.5, 2)
            }
        else:
            result["entry_zone"] = {
                "low": round(e20 - current_atr * 1.5, 2),
                "high": round(e20, 2)
            }
    else:
        result["entry_zone"] = {"low": 0, "high": 0}

    # 止损: EMA50 - 2ATR 或 前低
    if e50 > 0 and current_atr > 0:
        result["stop_loss"] = round(e50 - current_atr * 2, 2)

    # 评级
    if total >= 6:
        result["verdict"] = "优质回调入场点"
    elif total >= 4:
        result["verdict"] = "观察, 等更好价格"
    else:
        result["verdict"] = "回调不到位或趋势已弱"

    # 附加指标
    result["indicators"] = {
        "price": price,
        "ema20": round(e20, 2) if ema20 else None,
        "ema50": round(e50, 2) if ema50 else None,
        "ema120": round(ema120[-1], 2) if ema120 else None,
        "atr14": round(current_atr, 2) if current_atr else None,
        "rsi14": round(rsi_values[-1], 1) if rsi_values else None,
    }

    return result


def load_watchlist():
    """读取V10观察池"""
    wl_path = os.path.expanduser("~/.hermes/cache/v10_watchlist.json")
    try:
        with open(wl_path) as f:
            data = json.load(f)
        codes = [s.get("code", "") for s in data.get("signals", []) if s.get("code")]
        return codes
    except Exception:
        return []


def format_results(results):
    """格式化输出"""
    lines = []
    lines.append("# 波段回调识别")
    lines.append("")
    lines.append("| 维度 | 0分 | 1分 | 2分 |")
    lines.append("|------|-----|-----|-----|")
    lines.append("| 趋势排列 | 非多头 | 短多(EMA20>50) | 完美多头(20>50>120) |")
    lines.append("| 回调位置 | 远离支撑/跌破EMA50 | 接近EMA20 | 回踩EMA20/50±ATR |")
    lines.append("| 缩量 | 放量/持平(>80%) | 缩量(50-80%) | 极度缩量(<50%) |")
    lines.append("| 动量 | RSI超买/MACD绿柱扩大 | RSI中性/MACD红柱 | RSI偏低/MACD红柱 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for r in sorted(results, key=lambda x: x["total_score"], reverse=True):
        name = r.get("name", r["code"])
        score = r["total_score"]
        max_s = r["max_score"]
        verdict = r["verdict"]
        
        lines.append(f"## {name} ({r['code']}) | {score}/{max_s} {verdict}")
        lines.append("")
        
        # 评分表
        lines.append("| 维度 | 得分 | 说明 |")
        lines.append("|------|------|------|")
        for fname in ["trend", "pullback", "volume", "momentum"]:
            f = r["factors"].get(fname, {})
            lines.append(f"| {fname} | {f.get('score', 0)} | {f.get('desc', '')} |")
        lines.append("")
        
        # 指标和操作建议
        ind = r.get("indicators", {})
        if ind.get("price"):
            entry = r.get("entry_zone", {})
            stop = r.get("stop_loss", 0)
            lines.append(f"现价: {ind['price']} | EMA20: {ind.get('ema20','-')} | EMA50: {ind.get('ema50','-')} | ATR: {ind.get('atr14','-')} | RSI: {ind.get('rsi14','-')}")
            if entry.get("low", 0) > 0:
                lines.append(f"入场区间: {entry['low']} ~ {entry['high']} | 止损: {stop}")
            lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 swing_pullback.py <code1> [code2] ... [--json] [--watchlist]")
        sys.exit(1)

    json_output = "--json" in sys.argv
    
    if "--watchlist" in sys.argv:
        codes = load_watchlist()
        if not codes:
            print("V10观察池为空或不存在", file=sys.stderr)
            sys.exit(0)
    else:
        codes = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not codes:
        print("No stock codes provided", file=sys.stderr)
        sys.exit(1)

    results = []
    for code in codes:
        print(f"  Analyzing {code}...", file=sys.stderr)
        r = analyze_swing_pullback(code)
        results.append(r)

    if json_output:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_results(results))


if __name__ == "__main__":
    main()
