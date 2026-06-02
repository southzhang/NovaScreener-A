"""
持仓顾问引擎 — 基于V10/趋势波段策略的动态操作建议

分析维度：
  1. 趋势状态（多头/空头/震荡）
  2. V10信号（七条件共振状态）
  3. 趋势波段信号（回调支撑/反弹）
  4. 持仓盈亏状态
  5. ATR动态止盈止损
  6. 量价配合

输出：操作建议 + 理由 + 紧急程度
"""
import numpy as np
from dataclasses import dataclass
from typing import Optional

from core.strategies import (
    ema_fast, calc_ma, calc_rsi, calc_macd,
    llv_fast, hhv_fast, crossover, crossunder,
)
from core.trend_swing import calc_atr


@dataclass
class PositionAdvice:
    """持仓操作建议"""
    action: str          # 🟢持有不动 / 🟡减仓 / 🔴清仓 / 🔵加仓 / 📈动态止盈 / 💰盈利离场
    urgency: int         # 1-5 紧急程度
    reason: str          # 操作理由
    details: list        # 详细分析项
    trend: str           # 趋势状态：强势多头/多头/震荡/空头/强势空头
    v10_state: str       # V10状态描述
    swing_state: str     # 趋势波段状态
    dynamic_stop: float  # 动态止损价
    dynamic_target: float # 动态目标价
    risk_score: int      # 风险评分 0-100（越高越危险）


def analyze_position(
    code: str,
    buy_price: float,
    current_price: float,
    quantity: int,
    stop_loss: float = 0,
    target_price: float = 0,
    close: np.ndarray = None,
    high: np.ndarray = None,
    low: np.ndarray = None,
    volume: np.ndarray = None,
    open_price: np.ndarray = None,
) -> Optional[PositionAdvice]:
    """
    分析单只持仓，给出操作建议

    需要传入K线数据（至少150根）
    """
    if close is None or len(close) < 50:
        return None

    n = len(close)
    i = n - 1
    details = []

    # ===== 1. 趋势分析 =====
    ema5 = ema_fast(close, 5)
    ema20 = ema_fast(close, 20)
    ema50 = ema_fast(close, 50)
    ema120 = ema_fast(close, 120)

    # 趋势判断
    if ema20[i] > ema50[i] > ema120[i]:
        if close[i] > ema20[i]:
            trend = "强势多头"
            trend_score = 90
        else:
            trend = "多头"
            trend_score = 70
    elif ema20[i] < ema50[i] < ema120[i]:
        if close[i] < ema20[i]:
            trend = "强势空头"
            trend_score = 10
        else:
            trend = "空头"
            trend_score = 30
    else:
        trend = "震荡"
        trend_score = 50

    details.append(f"趋势: {trend} (EMA20={ema20[i]:.2f} EMA50={ema50[i]:.2f})")

    # 均线多头排列强度
    if n >= 120:
        ma_aligned = ema5[i] > ema20[i] > ema50[i] > ema120[i]
        if ma_aligned:
            details.append("✅ 四线多头排列（EMA5>20>50>120）")

    # ===== 2. V10七条件分析 =====
    v10_conditions = []
    v10_pass = 0

    if n >= 200:
        # 隧道
        tunnel_ok = close[i] > ema120[i] and close[i] > ema_fast(close, 200)[i] and ema120[i] > ema_fast(close, 200)[i]
        v10_conditions.append(("隧道多头", tunnel_ok))
        if tunnel_ok: v10_pass += 1

        # 双线定式
        dual_ok = ema5[i] > ema20[i] and ema5[i] > ema5[i-1]
        v10_conditions.append(("双线定式", dual_ok))
        if dual_ok: v10_pass += 1

        # QW动能
        lowest9 = llv_fast(low, 9)
        highest9 = hhv_fast(high, 9)
        diff9 = highest9 - lowest9
        rsv = np.where(diff9 > 0, (close - lowest9) / diff9 * 100, 50.0)
        K = np.empty(n, dtype=float)
        K[0] = rsv[0]
        for j in range(1, n):
            K[j] = K[j-1] * 2/3 + rsv[j] / 3
        qw_up = K[i] > K[i-1]
        v10_conditions.append(("QW动能", qw_up))
        if qw_up: v10_pass += 1

        # 通道间距
        ch_width = (ema5[i] - ema20[i]) / ema20[i] if ema20[i] > 0 else 0
        ch_ok = ch_width > 0.008
        v10_conditions.append(("通道间距", ch_ok))
        if ch_ok: v10_pass += 1

        # 放量
        vol_ma5 = np.mean(volume[max(0,i-4):i+1])
        vol_ma20 = np.mean(volume[max(0,i-19):i+1])
        vol_up = volume[i] > vol_ma5 * 1.5 if vol_ma5 > 0 else False
        v10_conditions.append(("放量", vol_up))
        if vol_up: v10_pass += 1

        # 阳线
        yang = close[i] > open_price[i]
        v10_conditions.append(("阳线", yang))
        if yang: v10_pass += 1

        # MACD金叉
        dif = ema_fast(close, 20) - ema_fast(close, 80)
        dea = ema_fast(dif, 9)
        macd_golden = dif[i] > dea[i] and dif[i-1] <= dea[i-1]
        macd_bull = dif[i] > dea[i]
        v10_conditions.append(("MACD", macd_bull))
        if macd_bull: v10_pass += 1

        v10_state = f"V10 {v10_pass}/7 {'🟢共振' if v10_pass >= 6 else '🟡部分' if v10_pass >= 4 else '🔴缺失'}"
        for name, ok in v10_conditions:
            details.append(f"  {'✅' if ok else '❌'} {name}")
    else:
        v10_state = "数据不足"
        v10_pass = 0

    # ===== 3. 盈亏分析（提前，后面策略要用）=====
    pnl_pct = (current_price - buy_price) / buy_price * 100 if buy_price > 0 else 0

    # ===== 4. 趋势波段完整分析 =====
    swing_state = ""
    swing_entry = False
    swing_exit_layer = 0   # 0=无退出, 1=T1止盈, 2=跌破EMA20/MACD死叉, 3=趋势破坏
    swing_exit_reason = ""
    if n >= 50:
        # RSI
        rsi = calc_rsi(close, 14)
        # MACD标准(12,26,9)
        macd_dif = ema_fast(close, 12) - ema_fast(close, 26)
        macd_dea = ema_fast(macd_dif, 9)

        # ATR
        atr = calc_atr(high, low, close, 14)

        # --- 趋势波段5条件入场检测 ---
        cond_trend = ema20[i] > ema50[i] > ema120[i] if n >= 120 else False
        dist20 = (close[i] - ema20[i]) / ema20[i] * 100
        dist50 = (close[i] - ema50[i]) / ema50[i] * 100
        cond_support = (-5 <= dist20 <= 2) or (-2 <= dist50 <= 2)

        vol_ma20_local = float(np.mean(volume[max(0,i-19):i+1]))
        vol_recent_local = float(np.mean(volume[max(0,i-2):i+1]))
        cond_shrink = vol_recent_local < vol_ma20_local * 0.95 if vol_ma20_local > 0 else False

        cond_momentum = rsi[i] > 35 and (macd_dif[i] > 0 or macd_dif[i] > macd_dea[i] or rsi[i] > 50)

        yang_local = close[i] > open_price[i]
        # KDJ
        lowest9 = llv_fast(low, 9)
        highest9 = hhv_fast(high, 9)
        diff9 = highest9 - lowest9
        rsv_swing = np.where(diff9 > 0, (close - lowest9) / diff9 * 100, 50.0)
        K_swing = np.empty(n, dtype=float)
        K_swing[0] = rsv_swing[0]
        for j in range(1, n):
            K_swing[j] = K_swing[j-1] * 2/3 + rsv_swing[j] / 3
        kdj_up = K_swing[i] > K_swing[i-1]
        cond_bounce = yang_local or kdj_up

        swing_entry = cond_trend and cond_support and cond_shrink and cond_momentum and cond_bounce

        # 趋势波段状态描述
        if cond_trend:
            if cond_support and cond_shrink:
                swing_state = "🟢 回调到位+缩量"
            elif cond_support:
                swing_state = "🟡 接近支撑区"
            elif close[i] > ema20[i] * 1.05:
                swing_state = "⚠️ 偏离均线，注意回调"
            else:
                swing_state = "🔵 趋势中"
        else:
            if n >= 120:
                swing_state = "🔴 趋势未确认(非多头排列)"
            else:
                swing_state = ""

        # --- 趋势波段三层退出检测 ---
        if n >= 26:
            # 止损：跌破 买入价-2×ATR
            if atr > 0 and current_price <= buy_price - 2 * atr:
                swing_exit_layer = 3
                swing_exit_reason = f"止损(买入价-2ATR=¥{buy_price - 2*atr:.2f})"

            # 第一层止盈：盈利达 1.5×ATR
            if swing_exit_layer == 0 and atr > 0 and pnl_pct > 0:
                atr_pct_local = atr / buy_price * 100
                if pnl_pct >= 1.5 * atr_pct_local:
                    swing_exit_layer = 1
                    swing_exit_reason = f"T1止盈(盈利{pnl_pct:.1f}%≥1.5ATR)"

            # 第二层：跌破EMA20 或 MACD死叉
            if swing_exit_layer == 0 and pnl_pct > 0:
                if close[i] < ema20[i] * 0.99:
                    swing_exit_layer = 2
                    swing_exit_reason = f"跌破EMA20(¥{ema20[i]:.2f})"
                elif macd_dif[i] < macd_dea[i] and macd_dif[i-1] >= macd_dea[i-1]:
                    swing_exit_layer = 2
                    swing_exit_reason = "MACD死叉"

            # 第三层：趋势破坏（EMA20下穿EMA50）
            if swing_exit_layer == 0:
                if ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1]:
                    swing_exit_layer = 3
                    swing_exit_reason = "趋势破坏(EMA20↓EMA50)"

        # 输出详情
        if swing_entry:
            details.append(f"📈 趋势波段入场信号！5/5条件满足")
        details.append(f"  趋势{'✅' if cond_trend else '❌'} 支撑{'✅' if cond_support else '❌'} 缩量{'✅' if cond_shrink else '❌'} 动量{'✅' if cond_momentum else '❌'} 反弹{'✅' if cond_bounce else '❌'}")
        if swing_exit_layer > 0:
            details.append(f"⚠️ 趋势波段退出L{swing_exit_layer}: {swing_exit_reason}")
    else:
        atr = 0
        rsi = np.array([50])
        macd_dif = np.array([0])
        macd_dea = np.array([0])

    # ===== 5. 动态止盈止损 =====
    if atr > 0:
        # 动态止损：取 max(用户止损, EMA20-1.5ATR, 成本-2ATR)
        atr_stop = round(ema20[i] - 1.5 * atr, 2)
        cost_stop = round(buy_price - 2 * atr, 2)
        dynamic_stop = max(stop_loss, atr_stop, cost_stop) if stop_loss > 0 else max(atr_stop, cost_stop)

        # 动态目标：根据趋势强度调整
        if trend_score >= 80:
            dynamic_target = round(current_price + 3 * atr, 2)  # 强趋势看远
        elif trend_score >= 60:
            dynamic_target = round(current_price + 2 * atr, 2)
        else:
            dynamic_target = round(current_price + 1.5 * atr, 2)
    else:
        dynamic_stop = stop_loss
        dynamic_target = target_price

    # ===== 6. 综合评分 → 操作建议 =====
    risk_score = 0
    action = "🟢 持有不动"
    urgency = 1
    reason = ""

    # === 卖出信号检测 ===
    # 趋势波段退出信号（优先级最高）
    if swing_exit_layer == 3:
        risk_score += 50
        details.append(f"🔴 趋势波段L3清仓: {swing_exit_reason}")
    elif swing_exit_layer == 2:
        risk_score += 30
        details.append(f"🟡 趋势波段L2减仓: {swing_exit_reason}")
    elif swing_exit_layer == 1:
        risk_score += 10
        details.append(f"📈 趋势波段L1止盈: {swing_exit_reason}")

    # 强趋势破坏
    if n >= 50:
        ema20_cross_down = crossunder(ema5, ema20) if n >= 6 else False
        trend_broken = ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1]

        if trend_broken:
            risk_score += 40
            details.append("💀 EMA20下穿EMA50，趋势破坏")

        if ema20_cross_down:
            risk_score += 20
            details.append("⚠️ EMA5下穿EMA20，短线走弱")

    # MACD死叉
    if n >= 35:
        if macd_dif[i] < macd_dea[i] and macd_dif[i-1] >= macd_dea[i-1]:
            risk_score += 25
            details.append("📉 MACD死叉")

    # 跌破止损
    if dynamic_stop > 0 and current_price <= dynamic_stop:
        risk_score += 50
        details.append(f"⛔ 已跌破动态止损 ¥{dynamic_stop}")

    # RSI超买
    if rsi[i] > 75:
        risk_score += 15
        details.append(f"📊 RSI超买 {rsi[i]:.0f}")

    # 盈利回吐
    if pnl_pct > 5:
        # 从最高点回撤
        recent_high = np.max(close[max(0,i-19):i+1])
        drawdown = (recent_high - current_price) / recent_high * 100
        if drawdown > 5:
            risk_score += 20
            details.append(f"📉 从近期高点回撤 {drawdown:.1f}%")

    # === 加仓信号检测 ===
    add_signal = False
    if v10_pass >= 5 and pnl_pct > -3 and pnl_pct < 8:
        add_signal = True
        details.append(f"🔵 V10 {v10_pass}/7条件共振，可考虑加仓")
    if swing_entry and pnl_pct > -5:
        add_signal = True
        details.append("🔵 趋势波段入场信号，可考虑加仓")

    # === 盈利离场检测 ===
    if pnl_pct > 15:
        # 大盈利时看趋势是否还在
        if risk_score >= 20 or trend_score < 50:
            action = "💰 盈利离场"
            urgency = 3
            reason = f"已盈利{pnl_pct:.1f}%，趋势减弱，建议锁定利润"
        elif rsi[i] > 70:
            action = "📈 动态止盈"
            urgency = 2
            reason = f"已盈利{pnl_pct:.1f}%，RSI偏高，上移止损到成本上方"
            dynamic_stop = max(dynamic_stop, round(buy_price * 1.03, 2))  # 止损提到成本+3%
    elif pnl_pct > 8:
        if risk_score >= 30:
            action = "💰 盈利离场"
            urgency = 3
            reason = f"盈利{pnl_pct:.1f}%但风险累积，建议减仓"
        else:
            action = "📈 动态止盈"
            urgency = 2
            reason = f"盈利{pnl_pct:.1f}%，上移止损保护利润"
            dynamic_stop = max(dynamic_stop, round(buy_price * 1.02, 2))

    # === 减仓信号 ===
    if action == "🟢 持有不动" and risk_score >= 30:
        action = "🟡 减仓"
        urgency = 3
        reason = f"风险评分{risk_score}，建议减仓降低风险"

    # === 清仓信号 ===
    if risk_score >= 50:
        action = "🔴 清仓"
        urgency = 5
        reason = f"风险评分{risk_score}，强烈建议清仓"
        if dynamic_stop > 0 and current_price <= dynamic_stop:
            reason += f"（已跌破止损¥{dynamic_stop}）"
    elif risk_score >= 40 and pnl_pct < 0:
        action = "🔴 清仓"
        urgency = 4
        reason = f"亏损+高风险{risk_score}，建议止损"

    # === 加仓信号（优先级低于卖出） ===
    if action == "🟢 持有不动" and add_signal:
        action = "🔵 加仓"
        urgency = 2
        reason = "策略信号共振+位置合适，可分批加仓"

    # === 默认持有理由 ===
    if action == "🟢 持有不动":
        if trend_score >= 70 and risk_score < 20:
            reason = "趋势健康，风险可控，继续持有"
        elif trend_score >= 50:
            reason = "趋势中性，观望为主"
        else:
            reason = "趋势偏弱，密切关注"
            urgency = 2

    return PositionAdvice(
        action=action,
        urgency=urgency,
        reason=reason,
        details=details,
        trend=trend,
        v10_state=v10_state,
        swing_state=swing_state,
        dynamic_stop=round(dynamic_stop, 2),
        dynamic_target=round(dynamic_target, 2),
        risk_score=risk_score,
    )
