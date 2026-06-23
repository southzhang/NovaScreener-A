"""
尾盘选股策略 — 专用于收盘前30分钟的信号确认

与V10全买入/强庄买策略的核心区别：
  V10全天策略：7条件K线共振 → 盘中任何时候可用
  尾盘策略：V10信号(前提) + 尾盘专属过滤 → 仅14:20-15:00可用

尾盘专属维度：
  1. 尾盘30分钟量比
  2. 尾盘拉升确认
  3. 日内趋势确认
  4. 出货迹象规避
  5. 尾盘异动捕捉
"""
import numpy as np
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class TailEndSignal:
    """尾盘选股信号"""
    code: str = ""
    name: str = ""
    signal_type: str = ""
    v10_score: float = 0
    price: float = 0
    pct_change: float = 0
    tail_volume_score: float = 0
    tail_momentum_score: float = 0
    tail_trend_score: float = 0
    tail_distribution: float = 10
    tail_catch_up: float = 0
    total_tail_score: float = 0
    tail_action: str = "放弃"
    tail_reason: str = ""
    tail_detail: Optional[dict] = None
    can_add: bool = False
    add_reason: str = ""


def score_tail_end_candidate(
    code: str, name: str,
    signal_type: str, v10_score: float,
    current_price: float, pct_change: float,
    day_open: float = 0, day_high: float = 0,
    day_low: float = 0, day_volume: float = 0,
    day_amount: float = 0,
    last_30min_volume: float = 0,
    last_15min_volume: float = 0,
    price_30min_ago: float = 0,
    price_15min_ago: float = 0,
    price_5min_ago: float = 0,
    ema20: float = 0, ema50: float = 0,
    ema120: float = 0, ema200: float = 0,
    sector_name: str = "",
    sector_change: float = 0,
    capital_flow: float = 0,
    limit_up: float = 0, limit_down: float = 0,
) -> Optional[TailEndSignal]:
    """
    尾盘选股评分 — 在已有V10信号基础上做尾盘专属过滤
    """
    if current_price <= 0:
        return None

    scores = {}
    details = {}

    # ---- 1. 尾盘量能 (0-20分) ----
    if day_volume > 0 and last_30min_volume > 0:
        tail_vol_ratio = last_30min_volume / day_volume
        if tail_vol_ratio >= 0.25:
            scores["volume"] = 20
            details["volume"] = f"尾盘爆量{tail_vol_ratio:.0%}"
        elif tail_vol_ratio >= 0.18:
            scores["volume"] = 15
            details["volume"] = f"尾盘放量{tail_vol_ratio:.0%}"
        elif tail_vol_ratio >= 0.12:
            scores["volume"] = 10
            details["volume"] = f"尾盘正常{tail_vol_ratio:.0%}"
        else:
            scores["volume"] = 5
            details["volume"] = f"尾盘缩量{tail_vol_ratio:.0%}"
    else:
        scores["volume"] = 10
        details["volume"] = "量能未知"

    # ---- 2. 尾盘动量 (0-20分) ----
    if price_15min_ago > 0:
        m15 = (current_price - price_15min_ago) / price_15min_ago * 100
        if m15 >= 0.5:
            scores["momentum"] = 20
            details["momentum"] = f"尾盘拉升{m15:+.2f}%"
        elif m15 >= 0.3:
            scores["momentum"] = 15
            details["momentum"] = f"尾盘反弹{m15:+.2f}%"
        elif m15 >= 0:
            scores["momentum"] = 10
            details["momentum"] = f"尾盘持平{m15:+.2f}%"
        else:
            scores["momentum"] = 0
            details["momentum"] = f"尾盘下跌{m15:.2f}%"
    else:
        scores["momentum"] = 10
        details["momentum"] = "动量未知"

    # ---- 3. 趋势确认 (0-20分) ----
    trend_ok = 0
    trend_parts = []
    if ema20 > 0 and current_price > ema20:
        trend_ok += 8
        trend_parts.append("EMA20上")
    elif ema20 > 0:
        trend_ok -= 3
        trend_parts.append("跌破EMA20")
    if day_low > 0 and day_open > 0 and abs(day_low - day_open) / max(day_open, 0.01) < 0.005:
        trend_ok += 6
        trend_parts.append("低开高走")
    if day_high > day_low > 0:
        pos = (current_price - day_low) / (day_high - day_low) * 100
        if pos > 70:
            trend_ok += 6
            trend_parts.append(f"强势({pos:.0f}%)")
        elif pos > 40:
            trend_ok += 3
        else:
            trend_parts.append(f"低位({pos:.0f}%)")
    scores["trend"] = max(0, min(20, trend_ok))
    details["trend"] = " ".join(trend_parts) if trend_parts else "数据不足"

    # ---- 4. 出货检测 (0-20分, 越高越安全) ----
    dist_score = 10
    dist_parts = []
    if pct_change > 2 and price_15min_ago > 0:
        m15 = (current_price - price_15min_ago) / price_15min_ago * 100
        if m15 < -0.5:
            dist_score -= 10
            dist_parts.append("全天涨尾盘跌(出货)")
        elif m15 < -0.3:
            dist_score -= 3
            dist_parts.append("尾盘小幅回落")
        else:
            dist_score += 5
            dist_parts.append("尾盘仍涨")
    if (scores.get("volume", 0) >= 15 and scores.get("momentum", 0) < 5
            and last_30min_volume > 0 and day_volume > 0):
        if last_30min_volume / day_volume > 0.25:
            dist_score -= 5
            dist_parts.append("放量不涨(对倒)")
    if limit_up > 0 and current_price > 0:
        dist = (limit_up - current_price) / current_price * 100
        if dist < 1.5:
            dist_score -= 3
            dist_parts.append(f"距涨停{dist:.1f}%")
    scores["distribution"] = max(0, min(20, dist_score))
    details["distribution"] = " ".join(dist_parts) if dist_parts else "正常"

    # ---- 5. 尾盘异动 (0-20分) ----
    catch_up = 0
    catch_parts = []
    if price_5min_ago > 0 and price_15min_ago > 0:
        m5 = (current_price - price_5min_ago) / price_5min_ago * 100
        m15 = (current_price - price_15min_ago) / price_15min_ago * 100
        if m5 > 0.3 and m15 > 0.3:
            catch_up += 20
            catch_parts.append(f"最后5分拉升{m5:.2f}%")
        elif m5 > 0.2:
            catch_up += 12
            catch_parts.append(f"最后5分异动{m5:.2f}%")
        elif m5 > 0:
            catch_up += 5
    if last_30min_volume > 0 and last_15min_volume > 0:
        r15 = last_15min_volume / last_30min_volume
        if r15 > 0.6:
            catch_up += 5
            catch_parts.append("尾盘集中放量")
    scores["catch_up"] = min(20, catch_up)
    details["catch_up"] = " ".join(catch_parts) if catch_parts else "无"

    # ---- 总分(加权) ----
    weighted = (
        scores.get("volume", 0) * 1.0
        + scores.get("momentum", 0) * 1.2
        + scores.get("trend", 0) * 1.0
        + scores.get("distribution", 10) * 1.5
        + scores.get("catch_up", 0) * 1.0
    )
    final_score = min(100, weighted / 1.14)

    # ---- 进场判定 ----
    action = "放弃"
    action_reason = ""
    can_add = False
    add_reason = ""

    if scores.get("distribution", 10) < 3:
        action = "放弃"
        action_reason = "出货迹象: " + details.get("distribution", "")
    elif scores.get("momentum", 10) == 0:
        action = "放弃"
        action_reason = "尾盘下跌不参与"
    elif final_score >= 65 and all(v >= 5 for k, v in scores.items()):
        action = "可进场"
        highs = [d for s, d in details.items() if scores.get(s, 0) >= 15]
        action_reason = "尾盘确认 · " + " · ".join(highs[:3])
        if scores.get("catch_up", 0) >= 15 and scores.get("volume", 0) >= 15:
            can_add = True
            add_reason = "尾盘放量拉升，可加仓"
    elif final_score >= 40:
        action = "观察"
        weaks = [d for s, d in details.items() if scores.get(s, 0) < 8]
        action_reason = "信号一般 · " + "/".join(weaks[:3])
    else:
        action_reason = "尾盘信号不足"

    return TailEndSignal(
        code=code, name=name,
        signal_type=signal_type, v10_score=v10_score,
        price=current_price, pct_change=pct_change,
        tail_volume_score=scores.get("volume", 0),
        tail_momentum_score=scores.get("momentum", 0),
        tail_trend_score=scores.get("trend", 0),
        tail_distribution=scores.get("distribution", 10),
        tail_catch_up=scores.get("catch_up", 0),
        total_tail_score=round(final_score, 1),
        tail_action=action, tail_reason=action_reason,
        tail_detail=details,
        can_add=can_add, add_reason=add_reason,
    )
