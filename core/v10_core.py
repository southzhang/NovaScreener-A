"""V10 高性能核心函数"""
import numpy as np
from collections import deque


def ema_fast(series, period):
    """快速 EMA"""
    alpha = 2.0 / (period + 1)
    result = np.empty_like(series, dtype=float)
    result[0] = series[0]
    for i in range(1, len(series)):
        result[i] = series[i] * alpha + result[i-1] * (1 - alpha)
    return result


def hhv_fast(series, period):
    """滑动窗口最高值 O(n)"""
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
    """条件回溯：距离上次 condition=True 的距离"""
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


def crossover(a, b):
    """a 上穿 b"""
    if len(a) < 2 or len(b) < 2:
        return False
    return bool(a[-1] > b[-1] and a[-2] <= b[-2])


def calc_ma(close, window):
    """简单移动平均"""
    n = len(close)
    result = np.empty(n, dtype=float)
    result[:window-1] = np.nan
    cumsum = np.cumsum(close)
    result[window-1:] = (cumsum[window-1:] - np.concatenate([[0], cumsum[:-window]])[window-1:]) / window
    return result
