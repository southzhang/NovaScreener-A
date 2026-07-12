#!/usr/bin/env python3
"""
趋势质量评分模块 v2.1
====================
基于11只A股2年回测数据校准的6因子评分体系。

v2.1 改进：
  1. 近期窗口加权：60日近期权重55% + 全期权重45%（v2的65/35太偏短期）
  2. 平滑波动惩罚：sigmoid替代阶梯函数
  3. 新增趋势动量因子（权重降至8%，避免回调期误杀）
  4. 均线完全多头占比权重提升至22%（结构比动量更重要）
  5. 近期趋势健康因子：近60日价格>EMA20占比

评分因子（权重）：
  F1: 连涨连跌比(streak_ratio)       权重22%  — 趋势方向性
  F2: 均线完全多头占比(full_bull)     权重22%  — 趋势结构（核心）
  F3: 维加斯隧道多头占比(vegas_bull)  权重18%  — 长期趋势
  F4: 近期趋势健康(recent_health)     权重15%  — 近期价>EMA20
  F5: 趋势动量(momentum)             权重8%   — EMA7/26间距变化（轻量）
  F6: 上涨天数占比(up_day_pct)        权重8%   — 多空力量
  波动惩罚: sigmoid平滑，CV中心0.45

等级划分：
  A级 ≥75分: 趋势极强 → 推荐买入 ★★★
  B级 ≥58分: 趋势良好 → 推荐买入 ★★☆/★★★
  C级 ≥45分: 趋势一般 → 标注等级，不推荐买入 ★☆☆
  D级 <45分: 趋势差   → 不推荐买入 ⛔

使用方法:
  from trend_quality import TrendQuality
  tq = TrendQuality()
  result = tq.score(df)
  # 或
  result = tq.score_from_code('600584')
  print(result['grade'], result['score'])
"""

import math
import numpy as np
import pandas as pd


class TrendQuality:
    """趋势质量评分器 v2.1"""

    # 因子权重
    WEIGHTS = {
        'streak_ratio': 0.22,
        'full_bull_pct': 0.22,
        'vegas_bull_pct': 0.18,
        'recent_health': 0.15,
        'momentum': 0.08,
        'up_day_pct': 0.08,
        # 合计 = 0.93，预留0.07给波动惩罚加成
    }

    # 等级阈值
    GRADE_THRESHOLDS = {
        'A': 75,
        'B': 58,
        'C': 45,
    }

    GRADE_RECOMMEND = {
        'A': '推荐买入',
        'B': '推荐买入',
        'C': '趋势一般，不推荐',
        'D': '趋势差，不推荐买入',
    }

    GRADE_STARS = {
        'A': '★★★',
        'B': '★★☆',
        'C': '★☆☆',
        'D': '⛔',
    }

    # 近期窗口权重（v2.1: 55/45，比v2的65/35更平衡）
    RECENT_WEIGHT = 0.55
    FULL_WEIGHT = 0.45

    RECENT_DAYS = 60

    def score(self, df: pd.DataFrame, lookback: int = None) -> dict:
        """
        计算趋势质量评分

        参数:
            df: DataFrame，需包含 close, high, low, volume 列，date为索引
            lookback: 回看天数，None则使用全部数据

        返回:
            dict: {score, grade, stars, recommend, details, factors}
        """
        if lookback:
            df = df.tail(lookback).copy()

        if len(df) < 60:
            return self._insufficient_data(len(df))

        close = df['close']
        high = df['high']
        low = df['low']

        # 计算EMA
        ema7 = close.ewm(span=7, adjust=False).mean()
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        ema144 = close.ewm(span=144, adjust=False).mean()
        ema169 = close.ewm(span=169, adjust=False).mean()

        # 有效起始位置
        warmup = min(169, len(df) - 1)
        recent_start = max(len(df) - self.RECENT_DAYS, warmup)

        # ─── F1: 连涨连跌比 ───
        daily_ret = close.pct_change()
        max_streak_up, max_streak_down = self._calc_streak(daily_ret)
        streak_ratio = max_streak_up / max(max_streak_down, 1)

        if len(df) > self.RECENT_DAYS:
            recent_ret = daily_ret.iloc[-self.RECENT_DAYS:]
            r_max_up, r_max_down = self._calc_streak(recent_ret)
            recent_streak_ratio = r_max_up / max(r_max_down, 1)
        else:
            recent_streak_ratio = streak_ratio

        # ─── F2: 均线完全多头占比 ───
        full_bull = ((ema7 > ema26) & (ema26 > ema144) & (ema144 > ema169))
        full_bull_pct_full = full_bull.iloc[warmup:].mean()
        full_bull_pct_recent = full_bull.iloc[recent_start:].mean() if len(df) > recent_start + 10 else full_bull_pct_full

        # ─── F3: 维加斯隧道多头占比 ───
        vegas_bull = ema144 > ema169
        vegas_bull_pct_full = vegas_bull.iloc[warmup:].mean()
        vegas_bull_pct_recent = vegas_bull.iloc[recent_start:].mean() if len(df) > recent_start + 10 else vegas_bull_pct_full

        # ─── F4: 近期趋势健康（近60日价>EMA20占比）───
        above_ema20 = close > ema20
        recent_health = above_ema20.iloc[-self.RECENT_DAYS:].mean() if len(df) > self.RECENT_DAYS else above_ema20.iloc[warmup:].mean()

        # ─── F5: 趋势动量（EMA7/EMA26间距变化率）───
        spread = (ema7 - ema26) / close * 100
        if len(df) > 20:
            recent_spread = spread.iloc[-5:].mean()
            prev_spread = spread.iloc[-20:-15].mean()
            if abs(prev_spread) > 0.01:
                momentum = (recent_spread - prev_spread) / max(abs(prev_spread), 0.1)
            else:
                momentum = 1.0 if recent_spread > 0 else -1.0
            momentum = max(-1.0, min(1.0, momentum))
            momentum_score = (momentum + 1.0) / 2.0
        else:
            momentum_score = 0.5

        # ─── F6: 上涨天数占比 ───
        up_days_full = (daily_ret.iloc[warmup:] > 0).mean()
        up_days_recent = (daily_ret.iloc[-self.RECENT_DAYS:] > 0).mean() if len(df) > self.RECENT_DAYS else up_days_full

        # ─── 近期/全期加权 ───
        streak_blended = self.RECENT_WEIGHT * recent_streak_ratio + self.FULL_WEIGHT * streak_ratio
        full_bull_blended = self.RECENT_WEIGHT * full_bull_pct_recent + self.FULL_WEIGHT * full_bull_pct_full
        vegas_bull_blended = self.RECENT_WEIGHT * vegas_bull_pct_recent + self.FULL_WEIGHT * vegas_bull_pct_full
        up_day_blended = self.RECENT_WEIGHT * up_days_recent + self.FULL_WEIGHT * up_days_full

        # ─── 归一化 ───
        norm_streak = min(streak_blended, 2.0) / 2.0
        norm_full_bull = min(full_bull_blended, 1.0)
        norm_vegas_bull = min(vegas_bull_blended, 1.0)
        norm_recent_health = min(recent_health, 1.0)
        norm_momentum = momentum_score
        norm_up = min(up_day_blended, 1.0)

        # ─── 波动惩罚（平滑sigmoid）───
        tr = pd.concat([high - low,
                         (high - close.shift(1)).abs(),
                         (low - close.shift(1)).abs()], axis=1).max(axis=1)
        atr14 = tr.rolling(14, min_periods=14).mean()
        atr_pct = atr14 / close

        if len(atr_pct) > self.RECENT_DAYS:
            recent_atr_pct = atr_pct.iloc[-self.RECENT_DAYS:]
        else:
            recent_atr_pct = atr_pct.iloc[warmup:]

        valid_recent_atr = recent_atr_pct.dropna()
        if len(valid_recent_atr) > 10:
            vol_cv = float(valid_recent_atr.std() / valid_recent_atr.mean())
        else:
            vol_cv = 0.5

        # sigmoid惩罚：CV<0.2→0.98, CV=0.33→0.88, CV=0.5→0.26, CV>0.7→0.02
        vol_penalty = 1.0 / (1.0 + math.exp(20 * (vol_cv - 0.45)))

        # ─── 加权得分 ───
        raw_score = (
            norm_streak * self.WEIGHTS['streak_ratio']
            + norm_full_bull * self.WEIGHTS['full_bull_pct']
            + norm_vegas_bull * self.WEIGHTS['vegas_bull_pct']
            + norm_recent_health * self.WEIGHTS['recent_health']
            + norm_momentum * self.WEIGHTS['momentum']
            + norm_up * self.WEIGHTS['up_day_pct']
        )
        score = raw_score * vol_penalty * 100

        # ─── 评级 ───
        grade = self._calc_grade(score)

        # ─── 明细 ───
        factors = {
            'streak_ratio': round(streak_blended, 3),
            'streak_ratio_full': round(streak_ratio, 3),
            'streak_ratio_recent': round(recent_streak_ratio, 3),
            'max_streak_up': max_streak_up,
            'max_streak_down': max_streak_down,
            'full_bull_pct': round(full_bull_blended, 3),
            'full_bull_pct_recent': round(full_bull_pct_recent, 3),
            'vegas_bull_pct': round(vegas_bull_blended, 3),
            'vegas_bull_pct_recent': round(vegas_bull_pct_recent, 3),
            'recent_health': round(recent_health, 3),
            'momentum': round(momentum, 3),
            'momentum_score': round(momentum_score, 3),
            'up_day_pct': round(up_day_blended, 3),
            'up_day_pct_recent': round(up_days_recent, 3),
            'vol_cv': round(vol_cv, 3),
            'vol_penalty': round(vol_penalty, 3),
        }

        details = {
            'streak_ratio': {'value': round(streak_blended, 2), 'norm': round(norm_streak, 3),
                            'weight': self.WEIGHTS['streak_ratio'],
                            'desc': f'连涨{max_streak_up}/连跌{max_streak_down}(近{recent_streak_ratio:.1f})'},
            'full_bull_pct': {'value': f'{full_bull_pct_recent:.0%}→{full_bull_blended:.0%}', 'norm': round(norm_full_bull, 3),
                             'weight': self.WEIGHTS['full_bull_pct'],
                             'desc': f'均线多头(近{full_bull_pct_recent:.0%})'},
            'vegas_bull_pct': {'value': f'{vegas_bull_pct_recent:.0%}→{vegas_bull_blended:.0%}', 'norm': round(norm_vegas_bull, 3),
                              'weight': self.WEIGHTS['vegas_bull_pct'],
                              'desc': f'隧道多头(近{vegas_bull_pct_recent:.0%})'},
            'recent_health': {'value': f'{recent_health:.1%}', 'norm': round(norm_recent_health, 3),
                             'weight': self.WEIGHTS['recent_health'],
                             'desc': '近60日价>EMA20'},
            'momentum': {'value': round(momentum, 2), 'norm': round(norm_momentum, 3),
                        'weight': self.WEIGHTS['momentum'],
                        'desc': 'EMA7/26间距变化'},
            'up_day_pct': {'value': f'{up_day_blended:.1%}', 'norm': round(norm_up, 3),
                          'weight': self.WEIGHTS['up_day_pct'],
                          'desc': f'上涨天数(近{up_days_recent:.0%})'},
            'vol_penalty': {'value': round(vol_cv, 3), 'norm': round(vol_penalty, 3),
                           'weight': '惩罚',
                           'desc': f'波动CV={vol_cv:.2f}→系数{vol_penalty:.0%}'},
        }

        return {
            'score': round(score, 1),
            'grade': grade,
            'stars': self.GRADE_STARS[grade],
            'recommend': self.GRADE_RECOMMEND[grade],
            'details': details,
            'factors': factors,
        }

    def score_from_code(self, code: str, days: int = 300) -> dict:
        """从股票代码获取评分"""
        df = self._fetch_klines(code, days)
        if df is None or len(df) < 60:
            return self._insufficient_data(len(df) if df is not None else 0)
        return self.score(df)

    def quick_score(self, code: str) -> str:
        """快速获取评分字符串"""
        result = self.score_from_code(code)
        return f"{result['grade']}({result['score']}分)"

    def score_batch(self, codes: list, names: dict = None) -> list:
        """批量评分"""
        results = []
        for code in codes:
            name = (names or {}).get(code, code)
            result = self.score_from_code(code)
            results.append({
                'code': code,
                'name': name,
                'score': result['score'],
                'grade': result['grade'],
                'stars': result['stars'],
                'recommend': result['recommend'],
                'factors': result.get('factors', {}),
            })
        return results

    # ─── 内部方法 ───

    def _calc_streak(self, daily_ret: pd.Series) -> tuple:
        max_up = max_down = cur_up = cur_down = 0
        for r in daily_ret:
            if pd.isna(r):
                continue
            if r > 0:
                cur_up += 1
                cur_down = 0
                max_up = max(max_up, cur_up)
            else:
                cur_down += 1
                cur_up = 0
                max_down = max(max_down, cur_down)
        return max_up, max_down

    def _calc_grade(self, score: float) -> str:
        if score >= self.GRADE_THRESHOLDS['A']:
            return 'A'
        if score >= self.GRADE_THRESHOLDS['B']:
            return 'B'
        if score >= self.GRADE_THRESHOLDS['C']:
            return 'C'
        return 'D'

    def _insufficient_data(self, n: int) -> dict:
        return {
            'score': 0, 'grade': 'D', 'stars': '⛔',
            'recommend': f'数据不足({n}天)，无法评分',
            'details': {}, 'factors': {},
        }

    def _fetch_klines(self, code: str, days: int = 300) -> pd.DataFrame:
        import urllib.request, json
        from datetime import datetime, timedelta

        prefix = 'sh' if code.startswith('6') else 'sz'
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=int(days * 1.5))).strftime('%Y-%m-%d')

        url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,{start},{end},500,qfq'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req, timeout=15).read().decode('utf-8')
            data = json.loads(resp)
            key = f'{prefix}{code}'
            klines = data['data'][key].get('qfqday', data['data'][key].get('day', []))
            if not klines:
                return None

            df = pd.DataFrame([k[:6] for k in klines],
                              columns=['date', 'open', 'close', 'high', 'low', 'volume'])
            for col in ['open', 'close', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            return df.tail(days)
        except Exception:
            return None


# ─── CLI入口 ───
if __name__ == '__main__':
    import sys

    tq = TrendQuality()

    if len(sys.argv) > 1:
        codes = sys.argv[1:]
    else:
        codes = ['600584', '601899', '603399', '300750', '603993',
                 '300308', '002594', '002371', '000977', '601233', '603225']

    names = {
        '600584': '长电科技', '601899': '紫金矿业', '603399': '永杉锂业',
        '300750': '宁德时代', '603993': '洛阳钼业', '300308': '中际旭创',
        '002594': '比亚迪', '002371': '北方华创', '000977': '浪潮信息',
        '601233': '桐昆股份', '603225': '新凤鸣',
    }

    backtest = {
        '600584': '+61%', '601899': '+23%', '603399': '+16%',
        '300750': '+13%', '603993': '+12%', '300308': '+7.4%(0笔)',
        '002594': '+7.4%', '002371': '+3.6%', '000977': '-2.5%',
        '601233': '-5.3%', '603225': '-6.3%',
    }

    print(f"{'代码':8s} {'名称':8s} {'评分':>6s} {'等级':4s} {'星级':5s} {'推荐':14s} {'回测':>10s} │ {'streak':>7s} {'bull%':>6s} {'vegas%':>6s} {'health':>7s} {'动量':>5s} {'up%':>5s} {'CV':>5s} {'惩罚':>4s}")
    print("─" * 130)

    for code in codes:
        name = names.get(code, code)
        bt = backtest.get(code, '?')
        result = tq.score_from_code(code)
        if result['details']:
            f = result['factors']
            print(f"{code:8s} {name:8s} {result['score']:6.1f} {result['grade']:4s} {result['stars']:5s} {result['recommend']:14s} {bt:>10s} │ "
                  f"{f['streak_ratio']:7.2f} {f['full_bull_pct']:6.1%} {f['vegas_bull_pct']:6.1%} "
                  f"{f['recent_health']:7.1%} {f['momentum']:5.2f} {f['up_day_pct']:5.1%} "
                  f"{f['vol_cv']:5.2f} {f['vol_penalty']:4.0%}")
        else:
            print(f"{code:8s} {name:8s} {result['score']:6.1f} {result['grade']:4s} {result['stars']:5s} {result['recommend']:30s} {bt:>10s}")
