"""V10 综合评分系统 — 多维度评分 + 过滤"""
import numpy as np
from dataclasses import dataclass
from typing import Optional
from .strategies import scan_v10_full, scan_pullback, ema_fast, calc_ma
from .data import get_capital_flow, get_fundamental


@dataclass
class ScoreResult:
    """评分结果"""
    code: str
    name: str
    total_score: float
    level: str  # 强推/关注/观察/排除
    v10_score: float
    pullback_score: float
    capital_score: float
    fundamental_score: float
    price: float
    pct_change: float
    tags: list
    detail: dict


def score_stock(code: str, name: str, close: np.ndarray, high: np.ndarray, 
                low: np.ndarray, volume: np.ndarray, open_price: np.ndarray,
                price: float = 0, pct_change: float = 0) -> Optional[ScoreResult]:
    """对单只股票进行多维度评分"""
    n = len(close)
    if n < 50:
        return None

    tags = []
    detail = {}
    
    # ===== 1. V10技术面评分 (0-40分) =====
    v10_score = 0
    v10_info = {}
    
    if n >= 200:
        v10_signal = scan_v10_full(close, high, low, volume, open_price)
        if v10_signal:
            if v10_signal.signal_type == "全买入":
                v10_score = 40
                tags.append("🏆全买入")
            elif v10_signal.signal_type == "强庄买":
                v10_score = 30
                tags.append("🟠强庄买")
            elif v10_signal.signal_type == "基础买":
                v10_score = 20
                tags.append("🟡基础买")
            v10_info = v10_signal.detail
            
            # 附加分
            if v10_info.get("MACD金叉"):
                v10_score += 5
            if v10_info.get("隧道多头"):
                tags.append("隧道✅")
            if v10_info.get("强庄信号"):
                tags.append("强庄✅")
    
    detail["v10"] = v10_info
    
    # ===== 2. 波段回调评分 (0-25分) =====
    pullback_score = 0
    pullback_info = {}
    
    if n >= 50:
        pullback_signal = scan_pullback(close, high, low, volume)
        if pullback_signal:
            pullback_score = min(pullback_signal.score * 3.125, 25)  # 8分制->25分制
            pullback_info = pullback_signal.detail
            
            if pullback_signal.score >= 6:
                tags.append("⭐优质回调")
            elif pullback_signal.score >= 4:
                tags.append("回调观察")
    
    detail["pullback"] = pullback_info
    
    # ===== 3. 资金面评分 (0-20分) =====
    capital_score = 0
    capital_info = {}
    
    try:
        capital_data = get_capital_flow(code)
        if capital_data:
            inflow = capital_data.get("main_net_inflow", 0)
            if inflow > 0:
                capital_score = 20
                tags.append("资金流入✅")
            elif inflow > -1000:  # 小幅流出
                capital_score = 10
            capital_info = {"main_net_inflow": inflow}
    except Exception:
        pass
    
    detail["capital"] = capital_info
    
    # ===== 4. 基本面评分 (0-15分) =====
    fundamental_score = 0
    fundamental_info = {}
    
    try:
        fund_data = get_fundamental(code)
        if fund_data:
            roe = fund_data.get("roe", 0)
            np_yoy = fund_data.get("np_yoy", 0)
            
            if roe > 10:
                fundamental_score += 8
                tags.append("ROE✅")
            elif roe > 5:
                fundamental_score += 4
            
            if np_yoy > 20:
                fundamental_score += 7
                tags.append("增长✅")
            elif np_yoy > 0:
                fundamental_score += 3
            
            fundamental_info = {"roe": roe, "np_yoy": np_yoy}
    except Exception:
        pass
    
    detail["fundamental"] = fundamental_info
    
    # ===== 5. 趋势强度附加分 (0-10分) =====
    trend_score = 0
    
    # EMA多头排列
    ema20 = ema_fast(close, 20)
    ema50 = ema_fast(close, 50)
    
    if n >= 50:
        if ema20[-1] > ema50[-1]:
            trend_score += 5
            tags.append("短多头✅")
        
        # 通道间距
        通道间距 = (ema20[-1] - ema50[-1]) / ema50[-1] if ema50[-1] > 0 else 0
        if 通道间距 > 0.02:
            trend_score += 5
            tags.append(f"通道{通道间距:.3f}")
    
    # ===== 总分 =====
    total_score = v10_score + pullback_score + capital_score + fundamental_score + trend_score
    
    # 推荐等级
    if total_score >= 80:
        level = "🔴 强烈推荐"
    elif total_score >= 60:
        level = "🟠 值得关注"
    elif total_score >= 40:
        level = "🟡 观察等待"
    else:
        level = "⚪ 暂不推荐"
    
    return ScoreResult(
        code=code,
        name=name,
        total_score=round(total_score, 1),
        level=level,
        v10_score=round(v10_score, 1),
        pullback_score=round(pullback_score, 1),
        capital_score=round(capital_score, 1),
        fundamental_score=round(fundamental_score, 1),
        price=price,
        pct_change=pct_change,
        tags=tags[:6],  # 最多显示6个标签
        detail=detail,
    )


def score_batch(codes: list[str], names: dict[str, str] = None, 
                quotes: dict[str, dict] = None) -> list[ScoreResult]:
    """批量评分"""
    from .data import get_stock_history
    
    results = []
    
    for code in codes:
        name = names.get(code, "") if names else ""
        
        # 获取K线
        df = get_stock_history(code, days=250)
        if df.empty or len(df) < 50:
            continue
        
        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)
        open_p = df["open"].values.astype(np.float64)
        
        # 获取实时价格
        price = 0
        pct_change = 0
        if quotes and code in quotes:
            price = quotes[code].get("price", close[-1])
            pct_change = quotes[code].get("pct_change", 0)
        else:
            price = close[-1]
        
        # 评分
        result = score_stock(code, name, close, high, low, volume, open_p, price, pct_change)
        if result:
            results.append(result)
    
    # 按总分排序
    results.sort(key=lambda x: x.total_score, reverse=True)
    
    return results
