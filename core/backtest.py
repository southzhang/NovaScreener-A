"""
策略回测引擎 — 支持所有内置策略的逐K线回测
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from core.strategies import (
    STRATEGY_REGISTRY, scan_v10_full, scan_pullback,
    calc_ma, ema_fast, calc_macd, calc_rsi,
    calc_bollinger, crossover, crossunder,
    llv_fast, hhv_fast,
)
from core.trend_swing import scan_trend_swing, check_trend_swing_signal_at_bar, check_trend_swing_exit_at_bar, calc_atr as ts_calc_atr


@dataclass
class Trade:
    """单笔交易"""
    entry_date: str
    entry_price: float
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""  # 止盈/止损/信号卖出/超时
    pnl_pct: float = 0.0
    bars_held: int = 0


@dataclass
class BacktestResult:
    """回测结果"""
    stock_code: str
    stock_name: str
    strategy_name: str
    period_name: str
    total_bars: int
    trades: list
    total_return: float = 0.0        # 总收益率 %
    win_rate: float = 0.0            # 胜率 %
    max_drawdown: float = 0.0        # 最大回撤 %
    avg_trade_pnl: float = 0.0       # 平均每笔收益 %
    avg_win_pnl: float = 0.0         # 平均盈利 %
    avg_loss_pnl: float = 0.0        # 平均亏损 %
    profit_factor: float = 0.0       # 盈亏比
    max_consecutive_losses: int = 0  # 最大连续亏损
    total_win: int = 0
    total_loss: int = 0
    equity_curve: list = field(default_factory=list)  # 权益曲线 [(date, value)]
    signal_dates: list = field(default_factory=list)   # 信号触发日期


def _check_signal_at_bar(strategy_key: str, close, high, low, volume, open_price, end_idx, params=None) -> bool:
    """检查第end_idx根K线是否触发买入信号"""
    if strategy_key == "v10_full":
        sig = scan_v10_full(close[:end_idx+1], high[:end_idx+1],
                            low[:end_idx+1], volume[:end_idx+1], open_price[:end_idx+1])
        return sig is not None
    elif strategy_key == "pullback":
        sig = scan_pullback(close[:end_idx+1], high[:end_idx+1],
                            low[:end_idx+1], volume[:end_idx+1])
        return sig is not None
    elif strategy_key == "trend_swing":
        return check_trend_swing_signal_at_bar(close, high, low, volume, open_price, end_idx)
    else:
        strat = STRATEGY_REGISTRY.get(strategy_key)
        if not strat or not strat.get("func"):
            return False
        p = {**(strat.get("default_params", {})), **(params or {})}
        return strat["func"](close[:end_idx+1], high[:end_idx+1],
                             low[:end_idx+1], volume[:end_idx+1],
                             open_price[:end_idx+1], p)


def _check_exit_signal(strategy_key: str, close, high, low, volume, open_price, end_idx) -> bool:
    """检查是否触发卖出信号（与买入相反的逻辑）"""
    if strategy_key == "v10_full":
        # V10卖出: MA5下穿MA20 或 MACD死叉
        if end_idx < 21:
            return False
        ma5 = ema_fast(close[:end_idx+1], 5)
        ma20 = ema_fast(close[:end_idx+1], 20)
        dif = ema_fast(close[:end_idx+1], 20) - ema_fast(close[:end_idx+1], 80)
        dea = ema_fast(dif, 9)
        # 通道走坏 或 MACD死叉
        if crossunder(ma5, ma20):
            return True
        if crossunder(dif, dea):
            return True
        return False
    elif strategy_key == "pullback":
        # 波段卖出: 跌破EMA20
        if end_idx < 21:
            return False
        ema20 = ema_fast(close[:end_idx+1], 20)
        return close[end_idx] < ema20[end_idx] * 0.97  # 跌破EMA20超3%
    elif strategy_key == "trend_swing":
        # 趋势波段的通用退出信号（简化版，完整版用 check_trend_swing_exit_at_bar）
        if end_idx < 26:
            return False
        ema20 = ema_fast(close[:end_idx+1], 20)
        ema50 = ema_fast(close[:end_idx+1], 50)
        # 趋势破坏
        if crossunder(ema20, ema50):
            return True
        # 跌破EMA20
        if close[end_idx] < ema20[end_idx] * 0.98:
            return True
        return False
    elif strategy_key == "ma_cross":
        # 均线死叉
        if end_idx < 22:
            return False
        return crossunder(calc_ma(close[:end_idx+1], 5), calc_ma(close[:end_idx+1], 20))
    elif strategy_key == "macd_cross":
        if end_idx < 36:
            return False
        dif = ema_fast(close[:end_idx+1], 12) - ema_fast(close[:end_idx+1], 26)
        dea = ema_fast(dif, 9)
        return crossunder(dif, dea)
    elif strategy_key == "kdj_golden":
        if end_idx < 12:
            return False
        lowest = llv_fast(low[:end_idx+1], 9)
        highest = hhv_fast(high[:end_idx+1], 9)
        diff = highest - lowest
        rsv = np.where(diff > 0, (close[:end_idx+1] - lowest) / diff * 100, 50.0)
        k_val = ema_fast(rsv, 3)
        d_val = ema_fast(k_val, 3)
        return crossunder(k_val, d_val)
    elif strategy_key == "rsi_oversold":
        if end_idx < 16:
            return False
        rsi = calc_rsi(close[:end_idx+1], 14)
        return rsi[end_idx] > 70  # RSI超买
    elif strategy_key == "bollinger_breakout":
        if end_idx < 22:
            return False
        ma = calc_ma(close[:end_idx+1], 20)
        return close[end_idx] < ma[end_idx]  # 跌回中轨
    else:
        return False


def _calc_atr(high, low, close, period=14):
    """计算ATR"""
    n = len(close)
    if n < period + 1:
        return 0.0
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                     abs(high[i] - close[i-1]),
                     abs(low[i] - close[i-1]))
    return np.mean(tr[-period:])


def run_backtest(
    stock_code: str,
    stock_name: str,
    strategy_key: str,
    dates: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    open_price: np.ndarray,
    stop_loss_pct: float = 5.0,       # 止损 %
    take_profit_pct: float = 10.0,    # 止盈 %
    max_hold_bars: int = 20,          # 最大持仓天数
    use_signal_exit: bool = True,     # 是否用信号卖出
    params: dict = None,
) -> BacktestResult:
    """
    逐K线回测核心引擎

    流程:
    1. 从第min_bars根K线开始扫描
    2. 每根K线检查买入信号
    3. 持仓后检查止损/止盈/信号卖出/超时
    4. 统计所有交易数据
    """
    strat_info = STRATEGY_REGISTRY.get(strategy_key, {})
    strategy_name = strat_info.get("name", strategy_key)
    min_bars = 200 if strategy_key == "v10_full" else 50

    n = len(close)
    if n < min_bars:
        return BacktestResult(
            stock_code=stock_code, stock_name=stock_name,
            strategy_name=strategy_name,
            period_name=f"共{n}根K线(需≥{min_bars})",
            total_bars=n, trades=[]
        )

    trades: list[Trade] = []
    signal_dates = []
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    entry_date = ""

    # 权益曲线（假设初始100万）
    initial_capital = 1_000_000
    capital = initial_capital
    position_value = 0.0
    equity_curve = []

    for i in range(min_bars, n):
        current_equity = capital
        if in_position:
            # 持仓中，按收盘价估值
            position_value = capital * (close[i] / entry_price)
            current_equity = position_value

        equity_curve.append((str(dates[i]), current_equity))

        if not in_position:
            # 检查买入信号
            try:
                if _check_signal_at_bar(strategy_key, close[:i+1], high[:i+1],
                                         low[:i+1], volume[:i+1], open_price[:i+1], i, params):
                    in_position = True
                    entry_price = close[i]
                    entry_idx = i
                    entry_date = str(dates[i])
                    signal_dates.append(entry_date)
                    capital = current_equity  # 全仓买入
                    position_value = capital
            except Exception:
                continue
        else:
            # 持仓中，检查退出条件
            bars_held = i - entry_idx
            pnl_pct = (close[i] - entry_price) / entry_price * 100
            exit_reason = ""

            # 止损
            # 日内最低点触发止损
            low_pnl = (low[i] - entry_price) / entry_price * 100
            if low_pnl <= -stop_loss_pct:
                exit_reason = "止损"
                # 止损价
                exit_price = entry_price * (1 - stop_loss_pct / 100)
                pnl_pct = -stop_loss_pct

            # 止盈
            elif pnl_pct >= take_profit_pct:
                exit_reason = "止盈"

            # 信号卖出
            elif use_signal_exit and bars_held >= 3:
                try:
                    if _check_exit_signal(strategy_key, close[:i+1], high[:i+1],
                                           low[:i+1], volume[:i+1], open_price[:i+1], i):
                        exit_reason = "信号卖出"
                except Exception:
                    pass

            # 超时
            if not exit_reason and bars_held >= max_hold_bars:
                exit_reason = "超时"

            if exit_reason:
                if exit_reason != "止损":
                    exit_price = close[i]
                else:
                    exit_price = entry_price * (1 - stop_loss_pct / 100)

                final_pnl = (exit_price - entry_price) / entry_price * 100

                trades.append(Trade(
                    entry_date=entry_date,
                    entry_price=round(entry_price, 2),
                    exit_date=str(dates[i]),
                    exit_price=round(exit_price, 2),
                    exit_reason=exit_reason,
                    pnl_pct=round(final_pnl, 2),
                    bars_held=bars_held,
                ))

                # 更新资金
                capital = capital * (1 + final_pnl / 100)
                in_position = False

    # 未平仓处理
    if in_position:
        final_pnl = (close[-1] - entry_price) / entry_price * 100
        trades.append(Trade(
            entry_date=entry_date,
            entry_price=round(entry_price, 2),
            exit_date=str(dates[-1]),
            exit_price=round(close[-1], 2),
            exit_reason="未平仓",
            pnl_pct=round(final_pnl, 2),
            bars_held=n - 1 - entry_idx,
        ))
        capital = capital * (1 + final_pnl / 100)

    # ===== 统计 =====
    total_return = (capital - initial_capital) / initial_capital * 100
    total_win = sum(1 for t in trades if t.pnl_pct > 0)
    total_loss = sum(1 for t in trades if t.pnl_pct <= 0)
    win_rate = total_win / len(trades) * 100 if trades else 0

    avg_trade_pnl = np.mean([t.pnl_pct for t in trades]) if trades else 0
    avg_win_pnl = np.mean([t.pnl_pct for t in trades if t.pnl_pct > 0]) if total_win else 0
    avg_loss_pnl = np.mean([t.pnl_pct for t in trades if t.pnl_pct <= 0]) if total_loss else 0

    # 盈亏比
    if avg_loss_pnl != 0:
        profit_factor = abs(avg_win_pnl / avg_loss_pnl)
    else:
        profit_factor = float('inf') if avg_win_pnl > 0 else 0

    # 最大回撤
    peak = initial_capital
    max_dd = 0
    for _, eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # 最大连续亏损
    max_consec_loss = 0
    curr_loss = 0
    for t in trades:
        if t.pnl_pct <= 0:
            curr_loss += 1
            max_consec_loss = max(max_consec_loss, curr_loss)
        else:
            curr_loss = 0

    # 计算回测周期名称
    if len(dates) > 0:
        period_name = f"{dates[0]} ~ {dates[-1]} ({n}根K线)"
    else:
        period_name = f"{n}根K线"

    return BacktestResult(
        stock_code=stock_code,
        stock_name=stock_name,
        strategy_name=strategy_name,
        period_name=period_name,
        total_bars=n,
        trades=trades,
        total_return=round(total_return, 2),
        win_rate=round(win_rate, 1),
        max_drawdown=round(max_dd, 2),
        avg_trade_pnl=round(avg_trade_pnl, 2),
        avg_win_pnl=round(avg_win_pnl, 2),
        avg_loss_pnl=round(avg_loss_pnl, 2),
        profit_factor=round(profit_factor, 2),
        max_consecutive_losses=max_consec_loss,
        total_win=total_win,
        total_loss=total_loss,
        equity_curve=equity_curve,
        signal_dates=signal_dates,
    )
