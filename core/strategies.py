"""V10 完整策略引擎 — 七条件共振 + 波段回调 + 评分系统"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


# ===== V10 核心指标函数 =====

def ema_fast(series, period):
    """快速EMA"""
    alpha = 2.0 / (period + 1)
    result = np.empty_like(series, dtype=float)
    result[0] = series[0]
    for i in range(1, len(series)):
        result[i] = series[i] * alpha + result[i-1] * (1 - alpha)
    return result


def hhv_fast(series, period):
    """滑动窗口最高值 O(n)"""
    from collections import deque
    n = len(series)
    result = np.empty(n, dtype=float)
    dq = deque()
    for i in range(n):
        while dq and dq[0] < i - period + 1:
            dq.popleft()
        while dq and series[dq[-1]] <= series[i]:
            dq.pop()
        dq.append(i)
        result[i] = series[dq[0]]
    return result


def llv_fast(series, period):
    """滑动窗口最低值 O(n)"""
    from collections import deque
    n = len(series)
    result = np.empty(n, dtype=float)
    dq = deque()
    for i in range(n):
        while dq and dq[0] < i - period + 1:
            dq.popleft()
        while dq and series[dq[-1]] >= series[i]:
            dq.pop()
        dq.append(i)
        result[i] = series[dq[0]]
    return result


def barslast_fast(cond):
    """条件回溯"""
    n = len(cond)
    result = np.full(n, 999.0, dtype=float)
    last_true = -999
    for i in range(n):
        if cond[i]:
            result[i] = 0
            last_true = i
        else:
            result[i] = i - last_true if last_true >= 0 else 999
    return result


def calc_rsi(close, period=14):
    """RSI指标"""
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = ema_fast(gain, period)
    avg_loss = ema_fast(loss, period)
    rs = np.divide(avg_gain, avg_loss, out=np.ones_like(avg_gain), where=avg_loss != 0)
    return 100 - (100 / (1 + rs))


def calc_bollinger(close, window=20, num_std=2.0):
    """布林带"""
    middle = calc_ma(close, window)
    std = np.std(close[-window:], ddof=0)
    upper = middle[-1] + num_std * std
    lower = middle[-1] - num_std * std
    return upper, middle[-1], lower


def calc_macd(close, fast=12, slow=26, signal=9):
    """MACD指标"""
    dif = ema_fast(close, fast) - ema_fast(close, slow)
    dea = ema_fast(dif, signal)
    macd_bar = 2 * (dif - dea)
    return dif, dea, macd_bar


def crossover(a, b):
    """a上穿b"""
    if len(a) < 2 or len(b) < 2:
        return False
    return bool(a[-1] > b[-1] and a[-2] <= b[-2])


def crossunder(a, b):
    """a下穿b"""
    if len(a) < 2 or len(b) < 2:
        return False
    return bool(a[-1] < b[-1] and a[-2] >= b[-2])


def calc_ma(close, window):
    """简单移动平均"""
    s = pd.Series(close, dtype=float)
    return s.rolling(window=window, min_periods=window).mean().values


# ===== V10 七条件共振策略 =====

@dataclass
class V10Signal:
    """V10信号结果"""
    code: str
    name: str
    signal_type: str  # 全买入/强庄买/基础买
    price: float
    score: float
    detail: dict
    tags: list


def scan_v10_full(close, high, low, volume, open_price) -> Optional[V10Signal]:
    """V10全买入公式 - 七条件共振"""
    n = len(close)
    if n < 200:
        return None

    # 隧道: EMA(120) / EMA(200)
    隧道快 = ema_fast(close, 120)
    隧道慢 = ema_fast(close, 200)

    # 短线通道: EMA(5) / EMA(20)
    MA5 = ema_fast(close, 5)
    MA20 = ema_fast(close, 20)

    # MACD(20,80,9) - 非标准参数
    DIF = ema_fast(close, 20) - ema_fast(close, 80)
    DEA = ema_fast(DIF, 9)

    # QW动能（通达信SMA方式）
    lowest9 = llv_fast(low, 9)
    highest9 = hhv_fast(high, 9)
    diff9 = highest9 - lowest9
    RSV = np.where(diff9 > 0, (close - lowest9) / diff9 * 100, 50.0)
    K = np.empty(n, dtype=float)
    K[0] = RSV[0]
    for i in range(1, n):
        K[i] = K[i-1] * 2/3 + RSV[i] / 3
    QW = ema_fast(K, 3)

    # 通道间距
    通道间距 = np.where(MA20 > 0, (MA5 - MA20) / MA20, 0.0)

    # 放量（5日均量）
    VOL_MA5 = np.zeros(n, dtype=float)
    for i in range(4, n):
        VOL_MA5[i] = np.mean(volume[i-4:i+1])

    # 强庄控盘
    WEIGHT = (2 * close + open_price + high + low) * 100
    WEIGHT_EMA = ema_fast(WEIGHT, 4)
    VAR1 = np.where(WEIGHT_EMA > 0, (WEIGHT / WEIGHT_EMA - 1) * 100, 0.0)
    VAR1_ABS = np.abs(VAR1)
    VAR1_HH20 = hhv_fast(VAR1_ABS, 20)
    STRONG = (VAR1_ABS >= VAR1_HH20 * 0.9999) & (VAR1 > 0)
    barslast_STRONG = barslast_fast(STRONG)

    # 信号判断
    i = n - 1

    # 条件1: 隧道多头
    隧道多头 = close[i] > 隧道快[i] and close[i] > 隧道慢[i] and 隧道快[i] > 隧道慢[i]

    # 条件2: 双线定式
    双线定式 = MA5[i] > MA20[i] and MA5[i] > MA5[i-1]

    # 条件3: QW上升
    QW上升 = QW[i] > QW[i-1]

    # 条件4: 通道间距>0.8%
    宽度OK = 通道间距[i] > 0.008

    # 条件5: 阳线
    阳线 = close[i] > open_price[i]

    # 条件6: 放量（>1.5倍5日均量）
    放量 = volume[i] > 1.5 * VOL_MA5[i] if VOL_MA5[i] > 0 else False

    # 条件7: MACD金叉
    MACD金叉 = DIF[i] > DEA[i] and DIF[i-1] <= DEA[i-1]

    # 强庄信号
    ST_FIRST = STRONG[i] and barslast_STRONG[i-1] >= 3
    强庄信号 = 放量 and 阳线 and ST_FIRST

    # 信号组合
    基础买 = 隧道多头 and 双线定式 and QW上升 and 宽度OK and 阳线 and 放量
    全买入 = 基础买 and 强庄信号 and MACD金叉
    强庄买 = 基础买 and 强庄信号

    # 计算评分
    score = 0
    tags = []

    if 全买入:
        signal_type = "全买入"
        score = 100
        tags = ["🏆全买入", "隧道✅", "MACD✅", "强庄✅", "放量✅"]
    elif 强庄买:
        signal_type = "强庄买"
        score = 80
        tags = ["🟠强庄买", "隧道✅", "强庄✅", "放量✅"]
    elif 基础买:
        signal_type = "基础买"
        score = 60
        tags = ["🟡基础买", "隧道✅", "放量✅"]
    else:
        return None

    # 附加评分
    if MACD金叉:
        score += 5
    if 通道间距[i] > 0.02:
        score += 5
        tags.append(f"通道{通道间距[i]:.3f}")

    detail = {
        "隧道多头": 隧道多头,
        "双线定式": 双线定式,
        "QW上升": QW上升,
        "通道间距": round(通道间距[i], 4),
        "放量": 放量,
        "阳线": 阳线,
        "MACD金叉": MACD金叉,
        "强庄信号": 强庄信号,
        "QW值": round(QW[i], 1),
        "VAR1": round(VAR1[i], 2),
    }

    return V10Signal(
        code="", name="",
        signal_type=signal_type,
        price=round(close[i], 2),
        score=score,
        detail=detail,
        tags=tags,
    )


# ===== 波段回调策略 =====

@dataclass
class PullbackSignal:
    """波段回调信号"""
    code: str
    name: str
    score: float
    level: str  # 优质/一般/不推荐
    price: float
    detail: dict
    tags: list


def scan_pullback(close, high, low, volume) -> Optional[PullbackSignal]:
    """波段回调入场识别"""
    n = len(close)
    if n < 50:
        return None

    # EMA均线
    ema20 = ema_fast(close, 20)
    ema50 = ema_fast(close, 50)
    ema120 = ema_fast(close, 120)

    # RSI
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = ema_fast(gain, 14)
    avg_loss = ema_fast(loss, 14)
    rs = np.divide(avg_gain, avg_loss, out=np.ones_like(avg_gain), where=avg_loss != 0)
    rsi = 100 - (100 / (1 + rs))

    # MACD
    dif = ema_fast(close, 12) - ema_fast(close, 26)
    dea = ema_fast(dif, 9)

    # 评分
    score = 0
    tags = []

    # 1. 多头排列 (0-2分)
    if ema20[-1] > ema50[-1] > ema120[-1]:
        score += 2
        tags.append("多头排列✅")
    elif ema20[-1] > ema50[-1]:
        score += 1
        tags.append("短多头")

    # 2. 回调到支撑区 (0-2分)
    dist_ema20 = (close[-1] - ema20[-1]) / ema20[-1]
    dist_ema50 = (close[-1] - ema50[-1]) / ema50[-1]

    if -0.02 <= dist_ema20 <= 0.02:
        score += 2
        tags.append("接近EMA20✅")
    elif -0.05 <= dist_ema50 <= 0.02:
        score += 1
        tags.append("接近EMA50")

    # 3. 缩量回调 (0-2分)
    if len(volume) >= 20:
        vol_ma20 = np.mean(volume[-20:])
        vol_recent = np.mean(volume[-3:])
        if vol_ma20 > 0:
            vol_ratio = vol_recent / vol_ma20
            if vol_ratio < 0.8:
                score += 2
                tags.append("缩量回调✅")
            elif vol_ratio < 1.0:
                score += 1
                tags.append("量能收缩")

    # 4. 动量未死 (0-2分)
    if rsi[-1] > 40:
        score += 1
        tags.append(f"RSI={rsi[-1]:.0f}")
    if dif[-1] > dea[-1]:
        score += 1
        tags.append("MACD多头")

    # 推荐等级
    if score >= 6:
        level = "⭐ 优质入场"
    elif score >= 4:
        level = "🟡 观察等待"
    else:
        level = "🔴 暂不推荐"

    detail = {
        "ema20": round(ema20[-1], 2),
        "ema50": round(ema50[-1], 2),
        "ema120": round(ema120[-1], 2),
        "dist_ema20": round(dist_ema20 * 100, 2),
        "rsi": round(rsi[-1], 1),
        "macd_dif": round(dif[-1], 2),
        "macd_dea": round(dea[-1], 2),
    }

    return PullbackSignal(
        code="", name="",
        score=score,
        level=level,
        price=round(close[-1], 2),
        detail=detail,
        tags=tags,
    )


# ===== 经典策略 =====

def strategy_ma_cross(close, high, low, volume, open_price, params) -> bool:
    """均线金叉"""
    short, long = params.get("short", 5), params.get("long", 20)
    if len(close) < long + 2:
        return False
    return crossover(calc_ma(close, short), calc_ma(close, long))


def strategy_macd_cross(close, high, low, volume, open_price, params) -> bool:
    """标准MACD金叉(12,26,9)"""
    if len(close) < 35:
        return False
    dif = ema_fast(close, 12) - ema_fast(close, 26)
    dea = ema_fast(dif, 9)
    return crossover(dif, dea)


def strategy_volume_breakout(close, high, low, volume, open_price, params) -> bool:
    """放量突破"""
    w = params.get("vol_window", 20)
    r = params.get("vol_ratio", 2.0)
    if len(volume) < w + 1:
        return False
    avg = calc_ma(volume, w)
    return bool(volume[-1] > avg[-1] * r)


def strategy_rsi_oversold(close, high, low, volume, open_price, params) -> bool:
    """RSI超卖反弹"""
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = ema_fast(gain, 14)
    avg_loss = ema_fast(loss, 14)
    rs = np.divide(avg_gain, avg_loss, out=np.ones_like(avg_gain), where=avg_loss != 0)
    rsi = 100 - (100 / (1 + rs))
    t = params.get("threshold", 30)
    return bool(rsi[-1] > t and rsi[-2] <= t)


def strategy_bollinger_breakout(close, high, low, volume, open_price, params) -> bool:
    """布林带突破"""
    window = params.get("window", 20)
    num_std = params.get("num_std", 2.0)
    middle = calc_ma(close, window)
    std = np.std(close[-window:], ddof=0)
    upper = middle[-1] + num_std * std
    return bool(close[-1] > upper and close[-2] <= middle[-2] + num_std * np.std(close[-window-1:-1], ddof=0))


def strategy_kdj_golden(close, high, low, volume, open_price, params) -> bool:
    """KDJ金叉"""
    if len(close) < 12:
        return False
    lowest = llv_fast(low, 9)
    highest = hhv_fast(high, 9)
    diff = highest - lowest
    rsv = np.where(diff > 0, (close - lowest) / diff * 100, 50.0)
    K = ema_fast(rsv, 3)
    D = ema_fast(K, 3)
    return crossover(K, D)


def strategy_volume_price_up(close, high, low, volume, open_price, params) -> bool:
    """量价齐升"""
    if len(close) < 4:
        return False
    return bool(close[-1] > close[-2] > close[-3] and volume[-1] > volume[-2] > volume[-3])


# ===== 策略注册表 =====

STRATEGY_REGISTRY = {
    "v10_full": {
        "name": "V10 全买入",
        "func": None,
        "default_params": {},
        "desc": "通达信全买入公式：隧道+通道+QW+强庄+MACD+放量阳线",
        "is_v10": True,
    },
    "pullback": {
        "name": "波段回调",
        "func": None,
        "default_params": {},
        "desc": "EMA20/50/120回调入场",
        "is_v10": True,
    },
    "trend_swing": {
        "name": "趋势波段",
        "func": None,
        "default_params": {},
        "desc": "多头排列+回调支撑+缩量反弹+三层波段止盈",
        "is_v10": True,
    },
    "ma_cross": {
        "name": "均线金叉",
        "func": strategy_ma_cross,
        "default_params": {"short": 5, "long": 20},
        "desc": "短均线上穿长均线",
    },
    "macd_cross": {
        "name": "MACD金叉",
        "func": strategy_macd_cross,
        "default_params": {},
        "desc": "标准MACD(12,26,9) DIF上穿DEA",
    },
    "volume_breakout": {
        "name": "放量突破",
        "func": strategy_volume_breakout,
        "default_params": {"vol_window": 20, "vol_ratio": 2.0},
        "desc": "成交量突破近20日均量的2倍",
    },
    "rsi_oversold": {
        "name": "RSI超卖反弹",
        "func": strategy_rsi_oversold,
        "default_params": {"period": 14, "threshold": 30},
        "desc": "RSI从30以下回升",
    },
    "bollinger_breakout": {
        "name": "布林带突破",
        "func": strategy_bollinger_breakout,
        "default_params": {"window": 20, "num_std": 2.0},
        "desc": "价格突破布林带上轨",
    },
    "kdj_golden": {
        "name": "KDJ金叉",
        "func": strategy_kdj_golden,
        "default_params": {},
        "desc": "KDJ指标K线上穿D线",
    },
    "volume_price_up": {
        "name": "量价齐升",
        "func": strategy_volume_price_up,
        "default_params": {},
        "desc": "连续3天价涨量增",
    },
}


def get_strategy_names() -> list[str]:
    return list(STRATEGY_REGISTRY.keys())


def get_strategy_info(name: str) -> dict:
    return STRATEGY_REGISTRY.get(name, {})
