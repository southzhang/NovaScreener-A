"""选股策略引擎 - 技术指标计算 + 策略信号判断"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field


@dataclass
class StrategyResult:
    """策略扫描结果"""
    code: str
    name: str
    strategy: str
    price: float
    detail: str
    triggered: bool = True


def calc_ma(series: pd.Series, window: int) -> pd.Series:
    """计算移动平均线"""
    return series.rolling(window=window, min_periods=1).mean()


def calc_ema(series: pd.Series, span: int) -> pd.Series:
    """计算指数移动平均线"""
    return series.ewm(span=span, adjust=False).mean()


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """计算 MACD 指标，返回 (dif, dea, macd_bar)"""
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_bar = 2 * (dif - dea)
    return dif, dea, macd_bar


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI 指标"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=1).mean()
    avg_loss = loss.rolling(window=period, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0):
    """计算布林带，返回 (upper, middle, lower)"""
    middle = calc_ma(close, window)
    std = close.rolling(window=window, min_periods=1).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3):
    """计算 KDJ 指标"""
    lowest_low = low.rolling(window=n, min_periods=1).min()
    highest_high = high.rolling(window=n, min_periods=1).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan) * 100
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


# ===== 策略函数 =====
# 每个策略函数接收 DataFrame（含 open/high/low/close/volume 列）和参数 dict
# 返回最后一条数据是否触发信号

def strategy_ma_cross(df: pd.DataFrame, params: dict) -> bool:
    """均线金叉策略：短均线上穿长均线"""
    short = params.get("short", 5)
    long = params.get("long", 20)
    if len(df) < long + 1:
        return False
    ma_short = calc_ma(df["close"], short)
    ma_long = calc_ma(df["close"], long)
    # 今天短均线在上，昨天短均线在下
    return bool(ma_short.iloc[-1] > ma_long.iloc[-1] and ma_short.iloc[-2] <= ma_long.iloc[-2])


def strategy_macd_cross(df: pd.DataFrame, params: dict) -> bool:
    """MACD金叉策略：DIF上穿DEA"""
    if len(df) < 35:
        return False
    dif, dea, _ = calc_macd(df["close"])
    return bool(dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2])


def strategy_volume_breakout(df: pd.DataFrame, params: dict) -> bool:
    """放量突破策略：成交量突破近N日均量的M倍"""
    vol_window = params.get("vol_window", 20)
    vol_ratio = params.get("vol_ratio", 2.0)
    if len(df) < vol_window + 1:
        return False
    avg_vol = df["volume"].rolling(window=vol_window, min_periods=1).mean()
    return bool(df["volume"].iloc[-1] > avg_vol.iloc[-1] * vol_ratio)


def strategy_rsi_oversold(df: pd.DataFrame, params: dict) -> bool:
    """RSI超卖反弹策略：RSI从30以下回升"""
    period = params.get("period", 14)
    threshold = params.get("threshold", 30)
    if len(df) < period + 2:
        return False
    rsi = calc_rsi(df["close"], period)
    return bool(rsi.iloc[-1] > threshold and rsi.iloc[-2] <= threshold)


def strategy_bollinger_breakout(df: pd.DataFrame, params: dict) -> bool:
    """布林带突破策略：价格突破上轨"""
    window = params.get("window", 20)
    num_std = params.get("num_std", 2.0)
    if len(df) < window + 1:
        return False
    upper, _, _ = calc_bollinger(df["close"], window, num_std)
    return bool(df["close"].iloc[-1] > upper.iloc[-1] and df["close"].iloc[-2] <= upper.iloc[-2])


def strategy_kdj_golden(df: pd.DataFrame, params: dict) -> bool:
    """KDJ金叉策略：K线上穿D线"""
    if len(df) < 12:
        return False
    k, d, _ = calc_kdj(df["high"], df["low"], df["close"])
    return bool(k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2])


# ===== 策略注册表 =====

STRATEGY_REGISTRY: dict[str, dict] = {
    "ma_cross": {
        "name": "均线金叉",
        "func": strategy_ma_cross,
        "default_params": {"short": 5, "long": 20},
        "desc": "短均线上穿长均线（默认MA5上穿MA20）",
    },
    "macd_cross": {
        "name": "MACD金叉",
        "func": strategy_macd_cross,
        "default_params": {},
        "desc": "DIF上穿DEA，经典买入信号",
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
        "desc": "RSI从超卖区（30以下）反弹回升",
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
}


def get_strategy_names() -> list[str]:
    """获取所有策略名称"""
    return list(STRATEGY_REGISTRY.keys())


def get_strategy_info(name: str) -> dict:
    """获取策略信息"""
    return STRATEGY_REGISTRY.get(name, {})
