#!/usr/bin/env python3
"""
Vibe-Trading 技术分析模块
─────────────────────────
纯numpy实现，无外部依赖。
提供K线形态识别、SMC信号检测、缠论买点判断。

用法:
    from tech_analysis import compute_technical_score, detect_smc_signals, detect_chanlun_buy_signal

    # OHLC为numpy数组，至少30根K线
    tech = compute_technical_score(close, high, low, open_)
    # tech = {'candlestick': int, 'patterns': [str], 'trend': str, 'volume': str}

    bos, choch, fvg, sigs = detect_smc_signals(high, low, close)
    # bos: >0多头/<0空头/0无, choch同理, fvg: 缺口数, sigs: 信号列表

    ok, ctype, desc = detect_chanlun_buy_signal(high, low, close)
    # ok: bool, ctype: '一买'/'二买'/'三买', desc: 描述
"""

import numpy as np

# ═══════════════════════════════════════════════════════════════
# 1. K线形态识别 (15种形态 + 综合评分)
# ═══════════════════════════════════════════════════════════════

def _detect_patterns(o, h, l, c):
    """
    检测单根K线形态。
    返回 (score, patterns): score>0看多,<0看空, patterns为形态名称列表。
    """
    patterns = []
    score = 0
    body = c - o
    abs_body = abs(body)
    total_range = h - l
    if total_range < 1e-8:
        return 0, ['十字星']

    upper = h - max(c, o)
    lower = min(c, o) - l
    body_ratio = abs_body / total_range

    # 1. 锤子线 (下影线长，实体小，看多)
    if lower > 2 * abs_body and upper < abs_body * 0.5 and total_range > 0:
        patterns.append('锤子线')
        score += 1

    # 2. 倒锤子线 (上影线长，实体小)
    if upper > 2 * abs_body and lower < abs_body * 0.5 and total_range > 0:
        patterns.append('倒锤子')
        score += 1  # 需要确认

    # 3. 十字星 (实体极小)
    if body_ratio < 0.1 and total_range > 0:
        patterns.append('十字星')
        # 十字星本身中性，需结合趋势

    # 4. 大阳线
    if body > 0 and body_ratio > 0.7:
        patterns.append('大阳线')
        score += 2

    # 5. 大阴线
    if body < 0 and body_ratio > 0.7:
        patterns.append('大阴线')
        score -= 2

    # 6. 长上影线 (空头信号)
    if upper > 2 * abs_body and abs_body > 0:
        patterns.append('长上影')
        score -= 1

    # 7. 长下影线 (多头信号)
    if lower > 2 * abs_body and abs_body > 0:
        patterns.append('长下影')
        score += 1

    # 8. 吞没形态需要前一根K线，在此只标记单根特征
    # (在compute_technical_score中用双根判断)

    # 9. 螺旋桨 (上下影线都长，实体小)
    if upper > abs_body * 1.5 and lower > abs_body * 1.5 and body_ratio < 0.3:
        patterns.append('螺旋桨')

    # 10. 光头光脚 (无影线)
    if upper < total_range * 0.02 and lower < total_range * 0.02:
        if body > 0:
            patterns.append('光头光脚阳')
            score += 1
        else:
            patterns.append('光头光脚阴')
            score -= 1

    return score, patterns


def compute_technical_score(close, high, low, open_, **kwargs):
    """
    综合技术评分（K线形态 + 趋势 + 量价）。

    参数:
        close, high, low, open_: numpy数组，至少5根K线
        **kwargs: 可选参数（向后兼容）
            vol_ratio: 量比
            change_pct: 涨跌幅%
            amount_wan: 成交额(万元)

    返回:
        dict: {
            'candlestick': int,  # K线形态得分 (>0看多 <0看空)
            'patterns': [str],  # 检测到的形态名称
            'trend': str,       # 趋势描述
            'volume': str,      # 量价描述
            'total': int,       # 综合得分 (旧版兼容字段)
            'signals': [str],   # 信号标签列表 (旧版兼容字段)
        }
    """
    n = len(close)
    if n < 5:
        return {'candlestick': 0, 'patterns': ['数据不足'], 'trend': '未知', 'volume': '未知', 'total': 0}

    result = {'candlestick': 0, 'patterns': [], 'trend': '', 'volume': '', 'total': 0}

    # --- 单根K线形态 (最近3根) ---
    cs_score = 0
    cs_patterns = []
    for i in range(max(0, n - 3), n):
        s, p = _detect_patterns(open_[i], high[i], low[i], close[i])
        cs_score += s
        cs_patterns.extend(p)

    # --- 双根形态: 看涨吞没/看跌吞没 ---
    if n >= 2:
        prev_o, prev_c = open_[-2], close[-2]
        curr_o, curr_c = open_[-1], close[-1]
        # 看涨吞没: 前阴后阳，后实体完全包住前实体
        if prev_c < prev_o and curr_c > curr_o:
            if curr_c > prev_o and curr_o < prev_c:
                cs_score += 2
                cs_patterns.append('看涨吞没')
        # 看跌吞没
        if prev_c > prev_o and curr_c < curr_o:
            if curr_c < prev_o and curr_o > prev_c:
                cs_score -= 2
                cs_patterns.append('看跌吞没')

    # --- 趋势判断 ---
    ma5 = np.mean(close[-5:]) if n >= 5 else close[-1]
    ma10 = np.mean(close[-10:]) if n >= 10 else ma5
    ma20 = np.mean(close[-20:]) if n >= 20 else ma10

    trend = ''
    if close[-1] > ma5 > ma10 > ma20 and ma20 > 0:
        trend = '多头排列'
    elif close[-1] < ma5 < ma10 < ma20:
        trend = '空头排列'
    elif close[-1] > ma5:
        trend = '短期偏多'
    elif close[-1] < ma5:
        trend = '短期偏空'
    else:
        trend = '震荡'

    # --- 量价 (如果有足够数据) ---
    # 注意：外部传入的volume可能没有，这里只用价格
    volume_desc = '需量数据'

    total = cs_score
    if '多头排列' in trend:
        total += 1
    elif '空头排列' in trend:
        total -= 1

    # 量比加分（向后兼容）
    vol_ratio = kwargs.get('vol_ratio', 1.0)
    if vol_ratio > 1.5:
        total += 1
        cs_patterns.append(f'放量{vol_ratio:.1f}x')

    result['candlestick'] = cs_score
    result['patterns'] = cs_patterns[:5]  # 最多5个
    result['trend'] = trend
    result['volume'] = volume_desc
    result['total'] = total
    result['signals'] = cs_patterns[:3]  # 旧版兼容
    return result


# ═══════════════════════════════════════════════════════════════
# 2. SMC信号检测 (BOS / ChoCH / FVG)
# ═══════════════════════════════════════════════════════════════

def detect_smc_signals(high, low, close):
    """
    Smart Money Concepts信号检测。

    参数:
        high, low, close: numpy数组，至少10根K线

    返回:
        bos: >0多头突破结构,<0空头突破, 0无
        choch: >0多头趋势改变,<0空头趋势改变, 0无
        fvg: Fair Value Gap数量 (公允价值缺口)
        signals: [str] 详细信号描述列表
    """
    n = len(close)
    if n < 10:
        return 0, 0, 0, ['数据不足']

    signals = []
    bos = 0
    choch = 0

    # --- BOS (Break of Structure) ---
    # 找最近的swing high和swing low
    swing_highs = []
    swing_lows = []
    # 宽松检测: >两侧各1根(短数据也有效) + 严格检测: >两侧各2根
    for i in range(1, n - 1):
        is_sh = high[i] > high[i-1] and high[i] > high[i+1]
        is_sl = low[i] < low[i-1] and low[i] < low[i+1]
        if i >= 2 and i < n - 2:
            is_sh = is_sh and high[i] > high[i-2] and high[i] > high[i+2]
            is_sl = is_sl and low[i] < low[i-2] and low[i] < low[i+2]
        if is_sh:
            swing_highs.append((i, high[i]))
        if is_sl:
            swing_lows.append((i, low[i]))

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        # 多头BOS: 最新收盘价突破最近的swing high
        last_sh = swing_highs[-1][1]
        last_sl = swing_lows[-1][1]
        prev_sh = swing_highs[-2][1] if len(swing_highs) >= 2 else last_sh

        if close[-1] > last_sh and close[-2] <= last_sh:
            bos = 1
            signals.append(f'BOS多头突破{last_sh:.2f}')
        elif close[-1] < last_sl and close[-2] >= last_sl:
            bos = -1
            signals.append(f'BOS空头跌破{last_sl:.2f}')

        # ChoCH (Change of Character): 趋势改变信号
        # 多头趋势中，跌破最近swing low → ChoCH空头
        if close[-1] < last_sl and len(swing_lows) >= 2:
            prev_sl = swing_lows[-2][1]
            if last_sl > prev_sl:  # 之前是higher low (多头结构)
                choch = -1
                signals.append(f'ChoCH空头:跌破{last_sl:.2f}(前低{prev_sl:.2f})')

        # 空头趋势中，突破最近swing high → ChoCH多头
        if close[-1] > last_sh and len(swing_highs) >= 2:
            prev_sh2 = swing_highs[-2][1]
            if last_sh < prev_sh2:  # 之前是lower high (空头结构)
                choch = 1
                signals.append(f'ChoCH多头:突破{last_sh:.2f}(前高{prev_sh2:.2f})')

    # --- FVG (Fair Value Gap) ---
    fvg_count = 0
    for i in range(2, n):
        # Bullish FVG: 当前最低 > 两根前最高
        if low[i] > high[i-2]:
            fvg_count += 1
            if len(signals) < 5:
                signals.append(f'FVG多头缺口({i-2}→{i})')
        # Bearish FVG: 当前最高 < 两根前最低
        elif high[i] < low[i-2]:
            fvg_count -= 1
            if len(signals) < 5:
                signals.append(f'FVG空头缺口({i-2}→{i})')

    return bos, choch, fvg_count, signals


# ═══════════════════════════════════════════════════════════════
# 3. 缠论买点检测 (简化版)
# ═══════════════════════════════════════════════════════════════

def _merge_klines(high, low, close, open_):
    """
    缠论K线合并处理（包含关系处理）。
    返回合并后的 (merged_high, merged_low)。
    """
    n = len(high)
    mh = [high[0]]
    ml = [low[0]]
    direction = 1 if close[0] >= open_[0] else -1  # 1=向上 -1=向下

    for i in range(1, n):
        if direction >= 0:  # 向上合并
            if high[i] >= mh[-1]:  # 新K线包含当前
                mh[-1] = high[i]
                ml[-1] = max(ml[-1], low[i])
            elif low[i] <= ml[-1]:  # 当前包含新K线
                pass  # 保持当前
            else:
                mh.append(high[i])
                ml.append(low[i])
                if high[i] < mh[-2]:  # 转向下
                    direction = -1
        else:  # 向下合并
            if low[i] <= ml[-1]:
                ml[-1] = low[i]
                mh[-1] = min(mh[-1], high[i])
            elif high[i] >= mh[-1]:
                pass
            else:
                mh.append(high[i])
                ml.append(low[i])
                if low[i] > ml[-2]:  # 转向上
                    direction = 1

    return np.array(mh), np.array(ml)


def detect_chanlun_buy_signal(high, low, close, open_=None):
    """
    缠论买点检测（简化版：一买/二买/三买）。

    参数:
        high, low, close: numpy数组，至少20根K线
        open_: 可选，开盘价数组。不传则用close近似。

    返回:
        ok: bool 是否有买点
        buy_type: str '一买'/'二买'/'三买'/'' 
        desc: str 描述
    """
    n = len(close)
    if n < 20:
        return False, '', '数据不足'

    if open_ is None:
        open_ = close  # fallback

    # 合并K线
    mh, ml = _merge_klines(high, low, close, open_)
    mn = len(mh)

    if mn < 6:
        return False, '', '合并后数据不足'

    # --- 一买: 下跌趋势末端反转 ---
    # 找最近的下降趋势: 连续降低的低点
    lows_descending = 0
    for i in range(mn - 1, max(0, mn - 6), -1):
        if ml[i] < ml[i - 1]:
            lows_descending += 1
        else:
            break

    if lows_descending >= 2:
        # 最后一根K线收盘高于前一根高点 → 趋势反转
        if close[-1] > mh[-2]:
            return True, '一买', f'下降{lows_descending}段后反转突破{mh[-2]:.2f}'

    # --- 二买: 回踩不破前低 ---
    # 找最近的两个swing low
    if mn >= 4:
        # 找最近的两个swing low（局部最低，非全局最低）
        swing_lows_idx = []
        for i in range(mn - 2, max(0, mn - 8), -1):
            if i > 0 and i < mn - 1:
                if ml[i] <= ml[i - 1] and ml[i] <= ml[i + 1]:
                    swing_lows_idx.append(i)
                    if len(swing_lows_idx) >= 2:
                        break
        if len(swing_lows_idx) == 2:
            i1, i2 = sorted(swing_lows_idx)  # i1较早, i2较晚
            if ml[i2] > ml[i1]:  # 后低不破前低
                if close[-1] > ml[i2] and close[-2] <= ml[i2]:
                    return True, '二买', f'回踩{ml[i2]:.2f}不破前低{ml[i1]:.2f}'

    # --- 三买: 突破中枢上沿回踩不入 ---
    if mn >= 6:
        # 缠论中枢 = 连续3根K线的重叠区间
        best_zhong = None
        for i in range(mn - 6, mn - 2):
            if i < 0:
                continue
            oh = min(mh[i], mh[i + 1], mh[i + 2])  # 重叠上沿 = 三者最小高点
            ol = max(ml[i], ml[i + 1], ml[i + 2])  # 重叠下沿 = 三者最大低点
            if oh > ol:
                best_zhong = (ol, oh)
                break  # 取最近的有效中枢

        if best_zhong:
            zhong_low, zhong_high = best_zhong
            # 最新K线突破中枢上沿
            if close[-1] > zhong_high and close[-2] <= zhong_high:
                # 回踩不跌破中枢上沿
                if low[-1] >= zhong_high * 0.99:
                    return True, '三买', f'突破中枢上沿{zhong_high:.2f}回踩确认'

    return False, '', '无买点信号'


# ═══════════════════════════════════════════════════════════════
# 4. 辅助: Vibe综合评分
# ═══════════════════════════════════════════════════════════════

def vibe_score(high, low, close, open_):
    """
    Vibe综合评分（SMC + 缠论 + K线形态）。

    参数:
        high, low, close, open_: numpy数组，至少30根K线（推荐60根以获得更可靠的缠论信号）

    返回:
        dict: {
            'score': int,     # 综合得分 (>=2推荐, >=0可观察, <0回避)
            'tags': [str],    # 标签列表
            'bos': int,
            'choch': int,
            'fvg': int,
            'chan_ok': bool,
            'chan_type': str,
            'tech': dict
        }
    """
    score = 0
    tags = []

    # SMC
    bos, choch, fvg, smc_sigs = detect_smc_signals(high, low, close)
    if bos > 0:
        score += 2
        tags.append('BOS多头')
    elif bos < 0:
        score -= 1
        tags.append('BOS空头')

    if choch > 0:
        score += 1
        tags.append('ChoCH多头')
    elif choch < 0:
        score -= 1
        tags.append('ChoCH空头')

    if fvg > 0:
        score += 1
        tags.append(f'FVG+{fvg}')
    elif fvg < 0:
        tags.append(f'FVG{fvg}')

    # 缠论
    chan_ok, chan_type, chan_desc = detect_chanlun_buy_signal(high, low, close)
    if chan_ok:
        score += 2
        tags.append(f'缠论{chan_type}')

    # K线形态
    tech = compute_technical_score(close, high, low, open_)
    if tech['candlestick'] > 0:
        score += 1
        patterns_str = '+'.join(tech['patterns'][:2])
        tags.append(f'K线看多({patterns_str})')
    elif tech['candlestick'] < 0:
        score -= 1

    return {
        'score': score,
        'tags': tags,
        'bos': bos,
        'choch': choch,
        'fvg': fvg,
        'chan_ok': chan_ok,
        'chan_type': chan_type,
        'tech': tech
    }
