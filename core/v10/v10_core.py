#!/usr/bin/env python3
"""
V10 共享核心函数
从 v10_auto_trade.py 和 v10_scan_strict.py 提取的公共技术指标计算函数
"""
import numpy as np
from collections import deque


def ema_fast(series, period):
    alpha = 2.0 / (period + 1)
    result = np.empty_like(series, dtype=float)
    result[0] = series[0]
    for i in range(1, len(series)):
        result[i] = series[i] * alpha + result[i-1] * (1 - alpha)
    return result


def hhv_fast(series, period):
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
