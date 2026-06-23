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
        # 高波动票：给足空间
        atr_mode = "高波动ATR追踪"
        if profit_pct >= 5:
            n_atr = 1.5
            atr_stage = "锁定利润期"
            atr_stop = highest - n_atr * atr
        elif profit_pct >= 0:
            n_atr = 2.5
            atr_stage = "微盈期"
            atr_stop = highest - n_atr * atr
        else:
            n_atr = 3.0
            atr_stage = "建仓期"
            atr_stop = highest - n_atr * atr
    elif atr_pct >= 2.5:
        # 中波动：ATR递进收紧
        atr_mode = "中波动ATR追踪"
        if profit_pct >= 15:
            n_atr = 1.2
            atr_stage = "丰厚利润期"
        elif profit_pct >= 5:
            n_atr = 1.8
            atr_stage = "盈利期"
        elif profit_pct >= 0:
            n_atr = 2.5
            atr_stage = "微盈期"
        else:
            n_atr = 3.5
            atr_stage = "建仓期"
        atr_stop = highest - n_atr * atr
    else:
        # 低波动：给更多空间
        atr_mode = "低波动ATR追踪"
        if profit_pct >= 15:
            n_atr = 2.0
            atr_stage = "丰厚利润期"
        elif profit_pct >= 5:
            n_atr = 2.5
            atr_stage = "盈利期"
        elif profit_pct >= 0:
            n_atr = 3.0
            atr_stage = "微盈期"
        else:
            n_atr = 4.0
            atr_stage = "建仓期"
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
    # 结构支撑是更硬的技术位，权重更高；ATR是动态追踪，作为辅助
    # 建仓期：以结构支撑为主（避免被正常波动洗出）
    # 盈利期：收紧到两者中较低的（保护利润）
    if profit_pct >= 10:
        # 盈利丰厚：两取低值，优先保利润
        stops = [s for s in [atr_stop, structure_support] if s > 0]
        final_stop = round(min(stops), 2) if stops else atr_stop
    else:
        # 建仓/微盈期：以结构支撑为锚，ATR只作参考下限
        if structure_support > 0 and atr_stop > 0:
            final_stop = round(max(atr_stop, structure_support), 2)
        else:
            final_stop = round(max(atr_stop, structure_support, price * 0.92), 2)

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

    # ===== 2. 量价关系 (15分) - 成交活跃度 =====
    # 使用已有数据：成交量vs均量 + 量价配合
    vol_ma5 = calc_ma(volume, 5) if n >= 5 else np.array([np.mean(volume)])
    vol_ratio = volume[-1] / vol_ma5[-1] if vol_ma5[-1] > 0 else 1.0
    vol_trend = volume[-1] > volume[-3] if n >= 4 else True
    if vol_ratio > 2.0 and vol_trend:
        v_score = 15
        v_desc = f"放量{vol_ratio:.1f}x均量+递增✅"
    elif vol_ratio > 1.5:
        v_score = 12
        v_desc = f"放量{vol_ratio:.1f}x均量"
    elif vol_ratio > 1.0:
        v_score = 8
        v_desc = f"量能正常{vol_ratio:.1f}x"
    elif vol_ratio > 0.5:
        v_score = 4
        v_desc = f"缩量{vol_ratio:.1f}x均量"
    else:
        v_score = 0
        v_desc = f"严重缩量{vol_ratio:.1f}x"
    dimensions.append(DimensionScore("量价关系", v_score, 15, v_desc))

    # ===== 3. 均线结构 (20分) - EMA排列 + 通道健康度 =====
    # 使用已有K线数据计算均线状态，不用外部API
    ema20_local = ema_fast(close, 20) if n >= 20 else np.array([price])
    ema50_local = ema_fast(close, 50) if n >= 50 else ema20_local
    ema120_local = ema_fast(close, 120) if n >= 120 else ema50_local
    ma5_local = calc_ma(close, 5) if n >= 5 else np.array([price])
    
    _struct_score = 0
    _struct_parts = []
    if n >= 50 and ema20_local[-1] > ema50_local[-1]:
        _struct_score += 8
        _struct_parts.append("短多✅")
    if n >= 120 and close[-1] > ema120_local[-1]:
        _struct_score += 6
        _struct_parts.append("长多✅")
    if n >= 20:
        _channel = (ma5_local[-1] - ema20_local[-1]) / ema20_local[-1]
        if _channel > 0.015:
            _struct_score += 6
            _struct_parts.append(f"通道{_channel:.1%}✅")
        elif _channel > 0:
            _struct_score += 3
            _struct_parts.append(f"通道{_channel:.1%}")
    _struct_str = " ".join(_struct_parts) if _struct_parts else "均线空头"
    dimensions.append(DimensionScore("均线结构", _struct_score, 20, _struct_str))

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

    # ===== 5. 估值位置 (10分) - PE分位 + 价格位置 =====
    # 用已有quote数据：PE + 价格与EMA20距离
    _pe_val = fundamental.get("pe", 0) if fundamental else 0
    _pe_score = 0
    if _pe_val and _pe_val > 0:
        if _pe_val > 5 and _pe_val < 30:
            _pe_score = 5
            _pe_desc = f"PE{_pe_val:.0f}合理"
        elif _pe_val >= 30:
            _pe_score = 2
            _pe_desc = f"PE{_pe_val:.0f}偏高"
        else:
            _pe_score = 3
            _pe_desc = f"PE{_pe_val:.0f}偏低"
    else:
        _pe_desc = "PE未知"
        _pe_score = 3
    # 价格在EMA20位置
    if n >= 20 and ema20_local[-1] > 0:
        _dist_to_ma = (price - ema20_local[-1]) / ema20_local[-1]
        if _dist_to_ma > 0.02:
            _ma_score = 5
            _ma_desc = f"↑EMA20+{_dist_to_ma:.1%}"
        elif _dist_to_ma > -0.02:
            _ma_score = 3
            _ma_desc = f"≈EMA20{_dist_to_ma:+.1%}"
        else:
            _ma_score = 0
            _ma_desc = f"↓EMA20{_dist_to_ma:.1%}"
    else:
        _ma_score = 2
        _ma_desc = "数据不足"
    dimensions.append(DimensionScore("估值位置", _pe_score + _ma_score, 10, _pe_desc + " " + _ma_desc))

    # ===== 6. 追高风险 (10分) - 06-09升级 =====
    # 新规则：强趋势票(V10全买入/强庄买+资金流入)涨幅>5%给5分而非0分
    # LLM Vibe≥+2时后续合并会进一步豁免追高扣分
    # 一票否决线：主板9.5%，创业板/科创板19%（按涨跌幅限制分档）
    price_limit_pct = 20.0 if code.startswith(("300", "688")) else 10.0
    hard_limit_pct = price_limit_pct * 0.95  # 9.5% 或 19%
    if abs(change_pct) >= hard_limit_pct:
        r_score = 0
        r_desc = f"涨幅{change_pct:+.1f}%接近涨停(限制{price_limit_pct:.0f}%)，一票否决"
        dimensions.append(DimensionScore("追高风险", r_score, 10, r_desc))
    elif abs(change_pct) < 3:
        r_score = 10
        r_desc = f"涨幅{change_pct:+.1f}%安全"
        dimensions.append(DimensionScore("追高风险", r_score, 10, r_desc))
    elif abs(change_pct) <= 5:
        r_score = 5
        r_desc = f"涨幅{change_pct:+.1f}%适中"
        dimensions.append(DimensionScore("追高风险", r_score, 10, r_desc))
    else:
        if signal_type in ("全买入", "强庄买") and capital_flow > 0:
            r_score = 5
            r_desc = f"涨幅{change_pct:+.1f}%但强趋势+资金流入，追高可接受"
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
