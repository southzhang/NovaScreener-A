"""
买入推荐引擎 — 基于原始V10综合评分系统
6维评分 + 持仓决策 + 三层止盈
来源: v10_scorer.py + swing_trailing_stop.py
"""
import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from .strategies import ema_fast, calc_ma, hhv_fast, llv_fast


@dataclass
class DimensionScore:
    """单维度评分"""
    name: str
    score: float
    max_score: float
    detail: str


@dataclass
class TrailingStop:
    """三层止盈止损"""
    atr_stop: float
    atr_mode: str
    atr_stage: str
    ema20_status: str
    ema20_value: float
    structure_support: float
    structure_status: str
    final_stop: float
    risk_level: str
    action: str


@dataclass
class BuyRecommendation:
    """买入推荐"""
    code: str
    name: str
    signal_type: str
    # 6维评分
    total_score: float
    level: str           # 强推/关注/观察/排除
    dimensions: List[DimensionScore]
    # 价格建议
    current_price: float
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward: float
    # 仓位
    position_pct: int
    position_note: str
    # 止盈止损
    trailing_stop: TrailingStop
    # 操作建议
    action: str
    hold_days: str
    reason: str
    risk_note: str


def _calc_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
    """计算ATR"""
    n = len(close)
    if n < period + 1:
        return close[-1] * 0.03
    trs = []
    for i in range(n - period, n):
        h, l, pc = high[i], low[i], close[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return float(np.mean(trs))


def _calc_amplitude_percentile(high: np.ndarray, low: np.ndarray, close: np.ndarray, days: int = 30) -> Optional[float]:
    """计算当前振幅在近N日的分位数(0-100)"""
    n = len(close)
    if n < days:
        return None
    amps = []
    for i in range(n - days, n):
        if low[i] > 0:
            amps.append((high[i] - low[i]) / low[i] * 100)
    if not amps:
        return None
    today_amp = amps[-1]
    below = sum(1 for a in amps if a <= today_amp)
    return below / len(amps) * 100


def _find_swing_lows(low: np.ndarray, window: int = 5) -> list:
    """找到近期的波段低点"""
    n = len(low)
    lows = []
    for i in range(window, n - 1):
        is_low = True
        for j in range(i - window, min(i + window + 1, n)):
            if j != i and low[j] <= low[i]:
                is_low = False
                break
        if is_low:
            lows.append(float(low[i]))
    return lows


def calc_trailing_stop(
    close: np.ndarray, high: np.ndarray, low: np.ndarray,
    cost_price: float = 0
) -> TrailingStop:
    """
    三层止盈止损机制（来自 swing_trailing_stop.py）
    1. ATR追踪止盈（自适应波动率）
    2. EMA20趋势破位
    3. 结构破位（前低击穿）
    """
    n = len(close)
    price = float(close[-1])
    if cost_price <= 0:
        cost_price = price

    atr = _calc_atr(high, low, close, 14)
    atr_pct = atr / price * 100

    # 盈利程度
    profit_pct = (price - cost_price) / cost_price * 100

    # 近30日最高价
    recent = high[-min(30, n):]
    highest = float(np.max(recent))

    # ---- 第一层: ATR追踪止盈 ----
    if atr_pct >= 4.0:
        # 高波动票：固定止盈
        atr_mode = "高波动固定止盈"
        if profit_pct >= 5:
            atr_stop = cost_price * 1.02
            atr_stage = "锁定利润期"
        else:
            atr_stop = cost_price * 0.97
            atr_stage = "建仓期"
    elif atr_pct >= 3.0:
        # 中波动：ATR收紧
        atr_mode = "中波动收紧ATR"
        if profit_pct < 5:
            n_atr = 2.0
            atr_stage = "建仓期(收紧)"
        elif profit_pct < 15:
            n_atr = 1.5
            atr_stage = "盈利期"
        else:
            n_atr = 1.2
            atr_stage = "丰厚利润期"
        atr_stop = highest - n_atr * atr
    else:
        # 低波动：经典三层ATR
        atr_mode = "低波动ATR追踪"
        if profit_pct < 5:
            n_atr = 3.0
            atr_stage = "建仓期"
        elif profit_pct < 15:
            n_atr = 2.5
            atr_stage = "盈利期"
        else:
            n_atr = 2.0
            atr_stage = "丰厚利润期"
        atr_stop = highest - n_atr * atr

    atr_stop = round(atr_stop, 2)

    # ---- 第二层: EMA20趋势破位 ----
    ema20_arr = ema_fast(close, 20) if n >= 20 else close
    ema20_val = float(ema20_arr[-1])
    ema20_prev = float(ema20_arr[-2]) if n >= 2 else ema20_val

    broken_now = price < ema20_val
    broken_prev = close[-2] < ema20_prev if n >= 2 else False
    ema20_confirmed = broken_now and broken_prev

    if ema20_confirmed:
        ema20_status = "EMA20破位确认"
    elif broken_now:
        ema20_status = "EMA20跌破(观察次日)"
    else:
        dist = (price - ema20_val) / ema20_val * 100
        ema20_status = f"EMA20上方({dist:+.1f}%)"

    # ---- 第三层: 结构破位 ----
    swing_lows = _find_swing_lows(low, window=5)
    if swing_lows:
        recent_swing_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows
        structure_support = min(recent_swing_lows)
        structure_broken = float(low[-1]) < structure_support
        if structure_broken:
            structure_status = "前低已击穿!"
        else:
            dist = (price - structure_support) / structure_support * 100
            structure_status = f"前低支撑({dist:+.1f}%)"
    else:
        structure_support = float(np.min(low[-20:])) if n >= 20 else price * 0.95
        structure_status = "无有效前低"

    # ---- 综合止盈价 ----
    stops = [s for s in [atr_stop, structure_support] if s > 0]
    final_stop = round(min(stops), 2) if stops else atr_stop

    # ---- 风险等级 ----
    triggers = 0
    warnings = 0
    if price <= atr_stop:
        triggers += 1
    elif (price - atr_stop) / price * 100 < 3:
        warnings += 1
    if ema20_confirmed:
        triggers += 1
    elif broken_now:
        warnings += 1
    if swing_lows and structure_broken:
        triggers += 1

    if triggers >= 2 or (swing_lows and structure_broken):
        risk_level = "⛔ 触发"
        stop_action = "建议清仓/大幅减仓"
    elif triggers == 1:
        risk_level = "🔴 预警"
        stop_action = "建议减仓1/3"
    elif warnings >= 2:
        risk_level = "🟡 关注"
        stop_action = "密切关注"
    else:
        risk_level = "🟢 安全"
        stop_action = "趋势健康，持有"

    return TrailingStop(
        atr_stop=atr_stop,
        atr_mode=atr_mode,
        atr_stage=atr_stage,
        ema20_status=ema20_status,
        ema20_value=round(ema20_val, 2),
        structure_support=round(structure_support, 2),
        structure_status=structure_status,
        final_stop=final_stop,
        risk_level=risk_level,
        action=stop_action,
    )


def score_and_recommend(
    code: str,
    name: str,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    open_price: np.ndarray,
    signal_type: str = "基础买",
    signal_score: float = 60,
    capital_flow: float = 0,
    fundamental: Optional[dict] = None,
    change_pct: float = 0,
    sector_score: float = 0,
    cost_price: float = 0,
) -> Optional[BuyRecommendation]:
    """
    综合评分 + 买入推荐（V10 6维评分体系）
    来自 v10_scorer.py 的 score_stock()
    """
    n = len(close)
    if n < 20:
        return None

    price = float(close[-1])
    fundamental = fundamental if fundamental is not None else {}
    dimensions = []

    # ===== 1. V10信号级别 (30分) =====
    sig_map = {"全买入": 30, "强庄买": 20, "基础买": 10}
    sig_score = sig_map.get(signal_type, 0)
    dimensions.append(DimensionScore("V10信号", sig_score, 30, signal_type or "无信号"))

    # ===== 2. 基本面 (15分) - ROE =====
    roe = fundamental.get("roe")
    if roe is not None:
        if roe > 10:
            f_score = 15
        elif roe >= 5:
            f_score = 7.5
        else:
            f_score = 0
        f_desc = f"ROE {roe:.1f}%"
    else:
        f_score = 7.5
        f_desc = "ROE未知(给半分)"
    dimensions.append(DimensionScore("基本面", f_score, 15, f_desc))

    # ===== 3. 资金面 (20分) - 主力净流入 =====
    if capital_flow > 5000:
        c_score = 20
        c_desc = f"主力净流入+{capital_flow/10000:.1f}亿"
    elif capital_flow > 0:
        c_score = 10
        c_desc = f"主力净流入+{capital_flow:.0f}万"
    elif capital_flow < -5000:
        c_score = 0
        c_desc = f"主力净流出{capital_flow/10000:.1f}亿"
    else:
        c_score = 0
        c_desc = f"主力净流出{capital_flow:.0f}万"
    dimensions.append(DimensionScore("资金面", c_score, 20, c_desc))

    # ===== 4. 振幅分位 (15分) =====
    amp_pct = _calc_amplitude_percentile(high, low, close)
    if amp_pct is not None:
        if amp_pct < 40:
            a_score = 15
            a_desc = f"{amp_pct:.0f}%低位"
        elif amp_pct <= 60:
            a_score = 7.5
            a_desc = f"{amp_pct:.0f}%中位"
        else:
            a_score = 0
            a_desc = f"{amp_pct:.0f}%高位"
    else:
        a_score = 7.5
        a_desc = "数据缺失(给半分)"
    dimensions.append(DimensionScore("振幅分位", a_score, 15, a_desc))

    # ===== 5. 板块风口 (10分) =====
    if sector_score > 0:
        w_score = min(sector_score, 10)
        w_desc = f"板块加分+{w_score}"
    else:
        w_score = 0
        w_desc = "板块无加分"
    dimensions.append(DimensionScore("板块风口", w_score, 10, w_desc))

    # ===== 6. 追高风险 (10分) =====
    if abs(change_pct) < 3:
        r_score = 10
        r_desc = f"涨幅{change_pct:+.1f}%安全"
    elif abs(change_pct) <= 5:
        r_score = 5
        r_desc = f"涨幅{change_pct:+.1f}%适中"
    else:
        r_score = 0
        r_desc = f"涨幅{change_pct:+.1f}%追高"
    dimensions.append(DimensionScore("追高风险", r_score, 10, r_desc))

    # ===== 总分 =====
    total = sum(d.score for d in dimensions)

    if total >= 80:
        level = "🔴 强烈推荐"
    elif total >= 60:
        level = "🟠 值得关注"
    elif total >= 40:
        level = "🟡 观察等待"
    else:
        level = "⚪ 暂不推荐"

    # ===== 入场/止损/目标计算 =====
    atr = _calc_atr(high, low, close, 14)
    ema20 = float(ema_fast(close, 20)[-1]) if n >= 20 else price
    ema10 = float(ema_fast(close, 10)[-1]) if n >= 10 else price
    recent_low_5 = float(np.min(low[-min(5, n):]))
    recent_low_20 = float(np.min(low[-min(20, n):]))

    # 入场价（基于信号强度）
    if signal_type == "全买入":
        entry = round(price * 1.005, 2)  # 允许小幅追高
        stop_base = min(recent_low_5, ema20 * 0.97)
    elif signal_type == "强庄买":
        entry = round(ema10, 2)  # 回踩EMA10
        stop_base = min(recent_low_5, ema20 * 0.96)
    else:
        entry = round(ema20 * 1.01, 2)  # 回踩EMA20
        stop_base = recent_low_20 * 0.97

    stop_loss = round(stop_base, 2)
    risk = entry - stop_loss if entry > stop_loss else price * 0.05
    target_1 = round(price + risk * 2.5, 2)
    target_2 = round(price + risk * 4.0, 2)
    risk_reward = round(risk * 2.5 / max(risk, 0.01), 1)

    # 仓位（来自 v10_scorer.py）
    position_pct = 20
    if signal_type == "全买入" and total >= 70:
        position_pct = 30
    elif signal_type == "基础买":
        position_pct = 10
    position_note = f"仓位{position_pct}%（约{position_pct * 1000}元）"

    # ===== 三层止盈止损 =====
    trailing = calc_trailing_stop(close, high, low, cost_price or price)

    # ===== 操作建议（基于评分+信号综合判断）=====
    # 补充维度亮点/短板到理由
    dim_highlights = []
    dim_warnings = []
    for d in dimensions:
        pct = d.score / d.max_score if d.max_score > 0 else 0
        if pct >= 0.8:
            dim_highlights.append(d.name)
        elif pct <= 0.2 and d.max_score >= 10:
            dim_warnings.append(d.name)

    highlight_str = "、".join(dim_highlights) if dim_highlights else ""
    warning_str = "、".join(dim_warnings) if dim_warnings else ""

    if total >= 80:
        action = "🔴 强烈建议买入"
        hold_days = "5-15天"
        reason = f"✅ 综合评分{total:.0f}分，{highlight_str}全面领先，信号质量高，建议果断入场"
        risk_note = f"严格执行止损¥{stop_loss}，不追高不重仓"
    elif total >= 60:
        if signal_type == "全买入":
            action = "🟠 建议买入"
            hold_days = "5-15天"
            reason = f"✅ 全买入信号+评分{total:.0f}分，{highlight_str}支撑充分，可择机入场"
            risk_note = f"关注{warning_str}短板，分批建仓更稳妥" if warning_str else "注意仓位控制"
        elif signal_type == "强庄买":
            action = "🟠 建议买入（分批）"
            hold_days = "3-10天"
            reason = f"✅ 强庄信号+评分{total:.0f}分，{highlight_str}确认，建议首次建仓50%等MACD金叉加仓"
            risk_note = f"缺MACD确认，关注{warning_str}" if warning_str else "注意仓位控制"
        else:
            action = "🟡 建议观察，回调买入"
            hold_days = "3-7天"
            reason = f"⚠️ 评分{total:.0f}分尚可，{highlight_str}有支撑，但信号偏弱，等回调到入场价¥{entry}再买"
            risk_note = f"不追高，{warning_str}是短板" if warning_str else "轻仓试探"
    elif total >= 40:
        action = "🟡 继续观察，暂不买入"
        hold_days = "-"
        reason = f"⚠️ 评分{total:.0f}分偏低，虽{highlight_str}有亮点，但{warning_str}拖累明显，不建议当前入场"
        risk_note = "等待信号强化或评分提升至60+再考虑"
    else:
        action = "⚪ 不建议买入"
        hold_days = "-"
        reason = f"❌ 评分{total:.0f}分过低，各维度均无突出优势，风险收益不匹配"
        risk_note = "远离，等待更好的机会"

    return BuyRecommendation(
        code=code, name=name, signal_type=signal_type,
        total_score=round(total, 1), level=level, dimensions=dimensions,
        current_price=price, entry_price=entry, stop_loss=stop_loss,
        target_1=target_1, target_2=target_2, risk_reward=risk_reward,
        position_pct=position_pct, position_note=position_note,
        trailing_stop=trailing,
        action=action, hold_days=hold_days,
        reason=reason, risk_note=risk_note,
    )


def format_recommendation_card(rec: BuyRecommendation) -> str:
    """格式化为Markdown推荐卡片"""
    lines = []
    lines.append(f"**{rec.action}** | **{rec.code}** {rec.name}")
    lines.append(f"综合评分 **{rec.total_score}分** {rec.level} | 信号 `{rec.signal_type}`")
    lines.append("")

    # 评分表
    lines.append("| 维度 | 得分 | 详情 |")
    lines.append("|------|-----:|------|")
    for d in rec.dimensions:
        bar = "█" * int(d.score / d.max_score * 5) + "░" * (5 - int(d.score / d.max_score * 5))
        lines.append(f"| {d.name} | **{d.score:.0f}**/{d.max_score:.0f} | {bar} {d.detail} |")
    lines.append("")

    # 价格建议
    loss_pct = (rec.current_price - rec.stop_loss) / rec.current_price * 100
    gain1_pct = (rec.target_1 - rec.current_price) / rec.current_price * 100
    gain2_pct = (rec.target_2 - rec.current_price) / rec.current_price * 100
    rr_emoji = "🟢" if rec.risk_reward >= 2.0 else "🟡" if rec.risk_reward >= 1.5 else "🔴"

    lines.append(f"| 项目 | 建议 |")
    lines.append(f"|------|------|")
    lines.append(f"| 🎯 入场价 | **¥{rec.entry_price}** |")
    lines.append(f"| 🛑 止损价 | **¥{rec.stop_loss}** (-{loss_pct:.1f}%) |")
    lines.append(f"| 📈 目标价1 | **¥{rec.target_1}** (+{gain1_pct:.1f}%) |")
    lines.append(f"| 🚀 目标价2 | **¥{rec.target_2}** (+{gain2_pct:.1f}%) |")
    lines.append(f"| {rr_emoji} 盈亏比 | **{rec.risk_reward}:1** |")
    lines.append(f"| 💰 仓位 | **{rec.position_note}** |")
    lines.append(f"| ⏱️ 持有 | **{rec.hold_days}** |")
    lines.append("")

    # 三层止盈止损
    ts = rec.trailing_stop
    lines.append(f"**三层止盈止损** {ts.risk_level} {ts.action}")
    lines.append(f"- ATR止盈: ¥{ts.atr_stop} [{ts.atr_mode} {ts.atr_stage}]")
    lines.append(f"- EMA20: ¥{ts.ema20_value} {ts.ema20_status}")
    lines.append(f"- 结构支撑: ¥{ts.structure_support} {ts.structure_status}")
    lines.append(f"- **最终止损: ¥{ts.final_stop}**")
    lines.append("")

    # 理由和风险
    lines.append(f"> 💡 **买入理由:** {rec.reason}")
    lines.append(f"> ⚠️ **风险提示:** {rec.risk_note}")

    return "\n".join(lines)


def generate_buy_recommendation(
    code: str,
    name: str,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    open_price: np.ndarray,
    signal_type: str = "基础买",
    score: float = 60,
    detail: Optional[dict] = None,
    capital_flow: float = 0,
    fundamental: Optional[dict] = None,
    change_pct: float = 0,
    sector_score: float = 0,
    cost_price: float = 0,
) -> Optional[BuyRecommendation]:
    """
    兼容旧接口的包装函数
    """
    return score_and_recommend(
        code=code, name=name,
        close=close, high=high, low=low, volume=volume, open_price=open_price,
        signal_type=signal_type, signal_score=score,
        capital_flow=capital_flow, fundamental=fundamental,
        change_pct=change_pct, sector_score=sector_score,
        cost_price=cost_price,
    )
