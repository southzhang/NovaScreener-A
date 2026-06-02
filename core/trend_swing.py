"""
趋势波段策略 — 趋势确认 + 回调入场 + 三层波段止盈

入场逻辑：
  1. 趋势确认：EMA20 > EMA50 > EMA120（多头排列）
  2. 回调到支撑：价格接近 EMA20 或 EMA50（-5%~+2%）
  3. 缩量回调：近3日量 < 20日均量的80%
  4. 动量未死：RSI > 40，MACD DIF > 0 或 DIF > DEA
  5. 反弹信号：当日收阳线 且 KDJ的K值上升

出场逻辑（三层波段止盈）：
  第一层：盈利达 1.5×ATR → 卖出1/3，止损提到成本
  第二层：跌破EMA20 或 MACD死叉 → 卖出1/3
  第三层：EMA20下穿EMA50 → 清仓（趋势破坏）
  兜底：跌破买入价 - 2×ATR → 止损清仓
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, List

from core.strategies import (
    ema_fast, calc_ma, calc_rsi, calc_macd,
    llv_fast, hhv_fast, crossover, crossunder,
)


@dataclass
class TrendSwingSignal:
    """趋势波段信号"""
    code: str
    name: str
    score: float
    price: float
    atr: float
    stop_loss: float
    target_1: float     # 第一层止盈
    target_2: float     # 第二层止盈（趋势破坏）
    tags: list
    detail: dict


def calc_atr(high, low, close, period=14):
    """计算ATR"""
    n = len(close)
    if n < period + 1:
        return 0.0
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                     abs(high[i] - close[i-1]),
                     abs(low[i] - close[i-1]))
    return float(np.mean(tr[-period:]))


def scan_trend_swing(close, high, low, volume, open_price) -> Optional[TrendSwingSignal]:
    """
    趋势波段入场扫描

    返回 TrendSwingSignal 或 None
    """
    n = len(close)
    if n < 150:
        return None

    # ── 均线 ──
    ema20 = ema_fast(close, 20)
    ema50 = ema_fast(close, 50)
    ema120 = ema_fast(close, 120)

    i = n - 1

    # ── 条件1: 多头排列 ──
    trend_up = ema20[i] > ema50[i] > ema120[i]
    if not trend_up:
        return None

    # ── 条件2: 回调到支撑区 ──
    dist_ema20 = (close[i] - ema20[i]) / ema20[i]
    dist_ema50 = (close[i] - ema50[i]) / ema50[i]
    near_support = (-0.05 <= dist_ema20 <= 0.02) or (-0.02 <= dist_ema50 <= 0.02)
    if not near_support:
        return None

    # ── 条件3: 缩量回调 ──
    vol_ma20 = float(np.mean(volume[max(0, i-19):i+1]))
    vol_recent = float(np.mean(volume[max(0, i-2):i+1]))
    vol_shrink = vol_recent < vol_ma20 * 0.95 if vol_ma20 > 0 else False
    if not vol_shrink:
        return None

    # ── 条件4: 动量未死 ──
    rsi = calc_rsi(close[:i+1], 14)
    dif = ema_fast(close[:i+1], 12) - ema_fast(close[:i+1], 26)
    dea = ema_fast(dif, 9)
    momentum_ok = rsi[i] > 35 and (dif[i] > 0 or dif[i] > dea[i] or rsi[i] > 50)
    if not momentum_ok:
        return None

    # ── 条件5: 反弹信号（阳线 或 KDJ上升）──
    yang = close[i] > open_price[i]

    # KDJ
    lowest9 = llv_fast(low[:i+1], 9)
    highest9 = hhv_fast(high[:i+1], 9)
    diff9 = highest9 - lowest9
    rsv = np.where(diff9 > 0, (close[:i+1] - lowest9) / diff9 * 100, 50.0)
    K = np.empty(i + 1, dtype=float)
    K[0] = rsv[0]
    for j in range(1, i + 1):
        K[j] = K[j-1] * 2/3 + rsv[j] / 3
    kdj_up = K[i] > K[i-1]

    bounce = yang or kdj_up
    if not bounce:
        return None

    # ── 评分 ──
    score = 50  # 基础分

    # 多头排列强度
    if ema20[i] > ema50[i] * 1.02:
        score += 5
    if ema50[i] > ema120[i] * 1.03:
        score += 5

    # 缩量程度
    if vol_ma20 > 0 and vol_recent / vol_ma20 < 0.6:
        score += 5  # 明显缩量

    # 支撑位精度
    if -0.02 <= dist_ema20 <= 0.01:
        score += 5  # 精准回踩EMA20

    # RSI位置
    if 40 < rsi[i] < 60:
        score += 5  # 中性区反弹最佳

    # MACD状态
    if dif[i] > dea[i]:
        score += 5  # MACD多头

    # 阳线力度
    body = (close[i] - open_price[i]) / open_price[i] * 100
    if body > 1.5:
        score += 5

    score = min(score, 100)

    # ── ATR + 止盈止损 ──
    atr = calc_atr(high[:i+1], low[:i+1], close[:i+1], 14)
    stop_loss = round(close[i] - 2 * atr, 2)
    target_1 = round(close[i] + 1.5 * atr, 2)    # 第一层止盈
    target_2 = round(close[i] + 3 * atr, 2)       # 第二层（趋势破坏时）

    # ── 标签 ──
    tags = ["📈趋势波段"]
    if dist_ema20 <= 0.01:
        tags.append("回踩EMA20✅")
    elif dist_ema50 <= 0.01:
        tags.append("回踩EMA50✅")
    tags.append(f"RSI={rsi[i]:.0f}")
    tags.append(f"缩量{vol_recent/vol_ma20*100:.0f}%")
    if dif[i] > dea[i]:
        tags.append("MACD多头✅")

    detail = {
        "EMA20": round(ema20[i], 2),
        "EMA50": round(ema50[i], 2),
        "EMA120": round(ema120[i], 2),
        "距EMA20%": round(dist_ema20 * 100, 2),
        "距EMA50%": round(dist_ema50 * 100, 2),
        "量比": round(vol_recent / vol_ma20, 2) if vol_ma20 > 0 else 0,
        "RSI": round(rsi[i], 1),
        "ATR": round(atr, 2),
        "KDJ_K": round(K[i], 1),
    }

    return TrendSwingSignal(
        code="", name="",
        score=score,
        price=round(close[i], 2),
        atr=round(atr, 2),
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        tags=tags,
        detail=detail,
    )


# ===== 回测专用：逐K线信号检测 =====

def check_trend_swing_signal_at_bar(close, high, low, volume, open_price, end_idx) -> bool:
    """检查第end_idx根K线是否触发趋势波段入场"""
    if end_idx < 150:
        return False

    c = close[:end_idx+1]
    h = high[:end_idx+1]
    lo = low[:end_idx+1]
    v = volume[:end_idx+1]
    o = open_price[:end_idx+1]

    ema20 = ema_fast(c, 20)
    ema50 = ema_fast(c, 50)
    ema120 = ema_fast(c, 120)

    i = end_idx

    # 多头排列
    if not (ema20[i] > ema50[i] > ema120[i]):
        return False

    # 回调到支撑
    dist20 = (c[i] - ema20[i]) / ema20[i]
    dist50 = (c[i] - ema50[i]) / ema50[i]
    if not ((-0.05 <= dist20 <= 0.02) or (-0.02 <= dist50 <= 0.02)):
        return False

    # 缩量
    vol_ma20 = float(np.mean(v[max(0, i-19):i+1]))
    vol_recent = float(np.mean(v[max(0, i-2):i+1]))
    if vol_ma20 <= 0 or vol_recent >= vol_ma20 * 0.95:
        return False

    # 动量
    rsi = calc_rsi(c, 14)
    dif = ema_fast(c, 12) - ema_fast(c, 26)
    dea = ema_fast(dif, 9)
    if not (rsi[i] > 35 and (dif[i] > 0 or dif[i] > dea[i] or rsi[i] > 50)):
        return False

    # 反弹（阳线 或 KDJ上升）
    yang = c[i] > o[i]

    # KDJ上升
    lowest9 = llv_fast(lo, 9)
    highest9 = hhv_fast(h, 9)
    diff9 = highest9 - lowest9
    rsv = np.where(diff9 > 0, (c - lowest9) / diff9 * 100, 50.0)
    K = np.empty(len(c), dtype=float)
    K[0] = rsv[0]
    for j in range(1, len(c)):
        K[j] = K[j-1] * 2/3 + rsv[j] / 3

    kdj_up = K[i] > K[i-1]
    return yang or kdj_up


def check_trend_swing_exit_at_bar(close, high, low, volume, open_price, end_idx,
                                   entry_price, atr_at_entry) -> tuple:
    """
    检查趋势波段出场条件

    返回: (should_exit: bool, exit_reason: str, exit_fraction: float)
      exit_fraction: 本次卖出的比例 (0.33, 0.33, 1.0)
    """
    if end_idx < 25:
        return False, "", 0

    c = close[:end_idx+1]
    h = high[:end_idx+1]
    lo = low[:end_idx+1]
    i = end_idx

    ema20 = ema_fast(c, 20)
    ema50 = ema_fast(c, 50)
    dif = ema_fast(c, 12) - ema_fast(c, 26)
    dea = ema_fast(dif, 9)

    pnl_pct = (c[i] - entry_price) / entry_price * 100
    atr_pct = atr_at_entry / entry_price * 100

    # 止损：跌破 entry - 2×ATR
    if c[i] <= entry_price - 2 * atr_at_entry:
        return True, "止损", 1.0

    # 第一层止盈：盈利达 1.5×ATR
    if pnl_pct >= 1.5 * atr_pct:
        return True, "止盈T1(1.5ATR)", 0.33

    # 第二层：跌破EMA20 或 MACD死叉
    if pnl_pct > 0:
        if c[i] < ema20[i] * 0.99:
            return True, "跌破EMA20", 0.5
        if crossunder(dif, dea):
            return True, "MACD死叉", 0.5

    # 第三层：趋势破坏（EMA20下穿EMA50）
    if crossunder(ema20, ema50):
        return True, "趋势破坏(EMA20↓EMA50)", 1.0

    return False, "", 0
