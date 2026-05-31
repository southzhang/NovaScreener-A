"""选股策略引擎 — V10 通达信全买入公式 + 经典策略"""
import numpy as np
from dataclasses import dataclass
from .v10_core import ema_fast, hhv_fast, llv_fast, barslast_fast, crossover, calc_ma


@dataclass
class StrategyResult:
    """策略扫描结果"""
    code: str
    name: str
    strategy: str
    price: float
    detail: str
    triggered: bool = True
    info: dict = None  # 附加指标数据


# ===== V10 参数 =====
参数_放量 = 1.5
参数_强庄 = 3
参数_通道宽度 = 0.008


def calc_macd_v10(close, fast=20, slow=80, signal=9):
    """V10 MACD(20,80,9) — 非标准参数，过滤噪音"""
    dif = ema_fast(close, fast) - ema_fast(close, slow)
    dea = ema_fast(dif, signal)
    macd_bar = 2 * (dif - dea)
    return dif, dea, macd_bar


def calc_rsi(close, period=14):
    """RSI"""
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = ema_fast(gain, period)
    avg_loss = ema_fast(loss, period)
    rs = np.divide(avg_gain, avg_loss, out=np.ones_like(avg_gain), where=avg_loss != 0)
    return 100 - (100 / (1 + rs))


def calc_kdj(high, low, close, n=9, m1=3, m2=3):
    """KDJ"""
    lowest = llv_fast(low, n)
    highest = hhv_fast(high, n)
    diff = highest - lowest
    rsv = np.where(diff > 0, (close - lowest) / diff * 100, 50.0)
    k = ema_fast(rsv, m1)
    d = ema_fast(k, m2)
    j = 3 * k - 2 * d
    return k, d, j


def calc_bollinger(close, window=20, num_std=2.0):
    """布林带"""
    middle = calc_ma(close, window)
    n = len(close)
    std = np.empty(n, dtype=float)
    std[:window-1] = np.nan
    for i in range(window-1, n):
        std[i] = np.std(close[i-window+1:i+1], ddof=0)
    return middle + num_std * std, middle, middle - num_std * std


# =====================================================
#  V10 主策略：通达信全买入公式
# =====================================================

def scan_v10_full(close, high, low, volume, open_price) -> tuple[list[str], dict] | None:
    """V10 全买入公式扫描
    
    返回: (signals_list, info_dict) 或 None
    signals: ["全买入"] / ["强庄买"] / ["基础买"] / []
    """
    n = len(close)
    if n < 200:
        return None

    # 隧道: EMA(120) / EMA(200)
    隧道快 = ema_fast(close, 120)
    隧道慢 = ema_fast(close, 200)

    # 短线通道: EMA(5) / EMA(20)
    MA5 = ema_fast(close, 5)
    MA20 = ema_fast(close, 20)

    # MACD(20,80,9)
    DIF, DEA, _ = calc_macd_v10(close)

    # QW 动能（通达信 SMA 方式）
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

    # ===== 信号判断 =====
    i = n - 1

    隧道多头 = close[i] > 隧道快[i] and close[i] > 隧道慢[i] and 隧道快[i] > 隧道慢[i]
    双线定式 = MA5[i] > MA20[i] and MA5[i] > MA5[i-1]
    QW上升 = QW[i] > QW[i-1]
    宽度OK = 通道间距[i] > 参数_通道宽度
    阳线 = close[i] > open_price[i]
    放量 = volume[i] > 参数_放量 * VOL_MA5[i] if VOL_MA5[i] > 0 else False
    MACD金叉 = DIF[i] > DEA[i] and DIF[i-1] <= DEA[i-1]

    ST_FIRST = STRONG[i] and barslast_STRONG[i-1] >= 参数_强庄
    强庄信号 = 放量 and 阳线 and ST_FIRST

    基础买 = 隧道多头 and 双线定式 and QW上升 and 宽度OK and 阳线 and 放量
    全买入 = 基础买 and 强庄信号 and MACD金叉
    强庄买 = 基础买 and 强庄信号

    signals = []
    if 全买入:
        signals.append("全买入")
    elif 强庄买:
        signals.append("强庄买")
    elif 基础买:
        signals.append("基础买")

    info = {
        '通道间距': round(通道间距[i], 4),
        'VAR1': round(VAR1[i], 2),
        'HH20': round(VAR1_HH20[i], 2),
        'QW': round(QW[i], 1),
        'MACD_DIF': round(DIF[i], 2),
        'MACD_DEA': round(DEA[i], 2),
        '隧道多头': 隧道多头,
        '双线定式': 双线定式,
        'QW上升': QW上升,
        '放量': 放量,
        '阳线': 阳线,
        'MACD金叉': MACD金叉,
        '强庄信号': 强庄信号,
    }
    return signals, info


# =====================================================
#  经典策略（简化版，快速筛选）
# =====================================================

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
    rsi = calc_rsi(close, params.get("period", 14))
    t = params.get("threshold", 30)
    return bool(rsi[-1] > t and rsi[-2] <= t)


def strategy_bollinger_breakout(close, high, low, volume, open_price, params) -> bool:
    """布林带突破"""
    upper, _, _ = calc_bollinger(close, params.get("window", 20), params.get("num_std", 2.0))
    return crossover(close, upper)


def strategy_kdj_golden(close, high, low, volume, open_price, params) -> bool:
    """KDJ金叉"""
    if len(close) < 12:
        return False
    k, d, _ = calc_kdj(high, low, close)
    return crossover(k, d)


def strategy_volume_price_up(close, high, low, volume, open_price, params) -> bool:
    """量价齐升：连续3天"""
    if len(close) < 4:
        return False
    return bool(close[-1] > close[-2] > close[-3] and volume[-1] > volume[-2] > volume[-3])


# ===== 策略注册表 =====

STRATEGY_REGISTRY = {
    # --- V10 主策略 ---
    "v10_full": {
        "name": "V10 全买入",
        "func": None,  # 特殊处理，用 scan_v10_full
        "default_params": {},
        "desc": "通达信全买入公式：隧道多头+通道+QW动能+强庄控盘+MACD金叉+放量阳线",
        "is_v10": True,
    },
    # --- 经典策略 ---
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
