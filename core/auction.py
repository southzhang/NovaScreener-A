"""竞价选股引擎 — 独立于V10的竞价短线策略
时间: 09:28跑(09:25竞价结束 → 09:30前出结果)
数据: 腾讯API全市场行情 + 东方财富板块热度 + 东方财富真实量比
策略: 趋势共振/游资爆量V1/游资竞价V2 + 板块热度过滤 + V10交叉标记
来源: auction_screener_v7.py
"""
import json
import re
import time
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# 排除板块（688=科创板, 北交所代码段）
EXCLUDE_CODES = {'688', '689', '8', '4'}
BATCH_SIZE = 100


@dataclass
class AuctionStock:
    """竞价选股结果"""
    code: str
    name: str
    price: float
    change_pct: float
    vol_ratio: float      # 量比
    amount_wan: float     # 成交额(万)
    turnover: float       # 换手率
    high: float
    low: float
    prev_close: float
    open_price: float
    circulation: float    # 流通市值(亿)
    strategy: str         # 趋势共振/游资爆量V1/游资竞价V2
    vibe_score: int = 0
    vibe_tags: list = field(default_factory=list)
    sector: str = ""
    sector_hot: bool = False
    in_v10: bool = False


# ===== 数据获取 =====

def _fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://quote.eastmoney.com/',
        })
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode('utf-8', errors='ignore')
    except Exception:
        return None


def _gen_stock_pool() -> list:
    pool = []
    for i in range(600000, 606000):
        pool.append(f"sh{i}")
    for i in range(1, 4000):
        pool.append(f"sz{str(i).zfill(6)}")
    for i in range(300000, 302000):
        pool.append(f"sz{i}")
    return pool


def _fetch_tencent_batch(codes: list) -> dict:
    results = {}
    url = f"https://qt.gtimg.cn/q={','.join(codes)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=20)
        data = resp.read().decode('gbk', errors='ignore')
        for line in data.strip().split('\n'):
            line = line.strip().rstrip(';')
            if not line:
                continue
            m = re.match(r'v_(\w+)="(.*)"', line)
            if not m:
                continue
            code_full = m.group(1)
            parts = m.group(2).split('~')
            if len(parts) < 40:
                continue
            try:
                name = parts[1]
                price = float(parts[3]) if parts[3] else 0
                if price <= 0:
                    continue
                code = code_full.replace('sh', '').replace('sz', '')
                if code[:3] in EXCLUDE_CODES or code[0] in {'8', '4'}:
                    continue
                prev_close = float(parts[4]) if parts[4] else 0
                open_p = float(parts[5]) if parts[5] else 0
                volume = float(parts[36]) if parts[36] else 0     # 成交量(手)
                high = float(parts[33]) if parts[33] else 0
                low = float(parts[34]) if parts[34] else 0
                amount = float(parts[37]) if len(parts) > 37 and parts[37] else 0  # 成交额(万元)
                turnover = float(parts[38]) if len(parts) > 38 and parts[38] else 0
                circ_cap = float(parts[44]) if len(parts) > 44 and parts[44] else 0
                change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                vol_ratio = round(amount / max(circ_cap * 12.5 / 10000, 1), 1) if circ_cap > 0 else 0
                results[code] = {
                    'code': code, 'name': name, 'price': price,
                    'prev_close': prev_close, 'open': open_p,
                    'volume': volume, 'amount_wan': amount,
                    'turnover': turnover, 'high': high, 'low': low,
                    'change_pct': change_pct, 'vol_ratio': vol_ratio,
                    'circulation': circ_cap,
                }
            except (ValueError, IndexError):
                continue
    except Exception:
        pass
    return results


def _fetch_eastmoney_vol_ratio(codes: list) -> dict:
    results = {}
    sz = [c for c in codes if c.startswith('0') or c.startswith('3')]
    sh = [c for c in codes if c.startswith('6')]

    def batch_fetch(secids, market_prefix):
        if not secids:
            return {}
        batch = ','.join([f"{market_prefix}.{c}" for c in secids])
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={batch}&fields=f10,f3,f6"
        raw = _fetch_url(url)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            arr = data.get('data', [])
            res = {}
            for item in arr:
                if isinstance(item, dict) and 'f57' in item:
                    code = item['f57']
                    vol_r = item.get('f10')
                    if vol_r is not None:
                        res[code] = {'vol_ratio': float(vol_r)}
            return res
        except Exception:
            return {}

    results.update(batch_fetch(sh, '1'))
    results.update(batch_fetch(sz, '0'))
    return results


# ===== 板块热度 =====

def fetch_sector_rank(limit: int = 15) -> dict:
    url = (f"https://push2.eastmoney.com/api/qt/clist/get?cb=&pn=1&pz={limit}"
           "&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2"
           "&fields=f2,f3,f4,f12,f14")
    raw = _fetch_url(url)
    if raw:
        try:
            data = json.loads(raw)
            items = data.get('data', {}).get('diff', [])
            return {x.get('f14', ''): x.get('f3') for x in items if x.get('f14')}
        except Exception:
            pass
    return {}


def get_stock_sector(code: str) -> Optional[str]:
    secid = f"1.{code}" if code.startswith('6') else f"0.{code}"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f127"
    raw = _fetch_url(url)
    if raw:
        try:
            data = json.loads(raw)
            industry = data.get('data', {}).get('f127', '')
            return industry if industry else None
        except Exception:
            pass
    return None


# ===== 三策略 =====

def _exclude_st(name: str) -> bool:
    return 'ST' in name or '退' in name or 'N' in name


def strategy_trend(stocks: dict) -> list:
    """趋势共振 — 多头排列+量比>3+涨幅3-6%"""
    candidates = []
    for code, s in stocks.items():
        if _exclude_st(s['name']):
            continue
        if s['circulation'] >= 200 or s['circulation'] <= 0:
            continue
        if not (3 <= s['change_pct'] <= 6):
            continue
        if s['amount_wan'] <= 2000:
            continue
        if s['vol_ratio'] <= 3:
            continue
        candidates.append(s)
    candidates.sort(key=lambda x: x['amount_wan'], reverse=True)
    return candidates[:8]


def strategy_youzi_v1(stocks: dict) -> list:
    """游资爆量V1 — 量比>4+成交额>5000万+涨幅3-7%"""
    results = []
    for code, s in stocks.items():
        if _exclude_st(s['name']):
            continue
        if s['circulation'] >= 100 or s['circulation'] <= 0:
            continue
        if not (3 <= s['change_pct'] <= 7):
            continue
        if s['amount_wan'] <= 5000:
            continue
        if s['vol_ratio'] < 4:
            continue
        results.append(s)
    return sorted(results, key=lambda x: x['amount_wan'], reverse=True)[:5]


def strategy_youzi_v2(stocks: dict) -> list:
    """游资竞价V2 — 涨幅2-5%+分档成交额+量比>2"""
    results = []
    for code, s in stocks.items():
        if _exclude_st(s['name']):
            continue
        if s['circulation'] >= 100 or s['circulation'] <= 0:
            continue
        if not (2 <= s['change_pct'] <= 5):
            continue
        mv = s['circulation']
        if mv < 5 and s['amount_wan'] <= 2000:
            continue
        elif 5 <= mv < 10 and s['amount_wan'] <= 3500:
            continue
        elif 10 <= mv < 15 and s['amount_wan'] <= 5000:
            continue
        if s['vol_ratio'] <= 2:
            continue
        results.append(s)
    return sorted(results, key=lambda x: x['amount_wan'], reverse=True)[:5]


# ===== Vibe评分 =====

def vibe_score(s: dict) -> tuple:
    score = 0
    tags = []
    amp = 0
    if s['high'] > 0 and s['low'] > 0 and s['prev_close'] > 0:
        amp = round((s['high'] - s['low']) / s['prev_close'] * 100, 1)
    if amp > 5:
        score += 1
        tags.append('振幅大')
    if s['vol_ratio'] > 3 and s['change_pct'] > 0:
        score += 1
        tags.append('量价齐升')
    if s['change_pct'] > 3:
        score += 1
        tags.append('强势开盘')
    if 5 < s['vol_ratio'] < 500:
        score += 1
        tags.append('爆量')
    return score, tags


# ===== 主入口 =====

def run_auction_scan(progress_callback=None) -> dict:
    """
    运行竞价选股扫描
    返回: {stocks: [AuctionStock], sector_heat: {}, stats: {}}
    """
    t0 = time.time()
    v10_codes = set()

    # 尝试读取V10信号
    for path in [
        os.path.expanduser('~/.hermes/cache/v10_watchlist.json'),
        os.path.expanduser('~/.hermes/cache/v10_tail_prefetch.json'),
    ]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                for s in data.get('stocks', data.get('candidates', [])):
                    code = re.sub(r'\D', '', s.get('code', ''))
                    if code:
                        v10_codes.add(code)
            except Exception:
                pass

    # 1. 腾讯全量行情
    if progress_callback:
        progress_callback(0.1, "获取腾讯全量行情...")
    pool = _gen_stock_pool()
    all_stocks = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for i in range(0, len(pool), BATCH_SIZE):
            futures.append(executor.submit(_fetch_tencent_batch, pool[i:i + BATCH_SIZE]))
        for f in as_completed(futures):
            all_stocks.update(f.result())

    if len(all_stocks) < 100:
        return {"stocks": [], "sector_heat": {}, "stats": {"error": "数据不足，可能非交易时段"}}

    # 2. 板块热度
    if progress_callback:
        progress_callback(0.4, "获取板块热度...")
    sector_heat = fetch_sector_rank()
    top_sectors = set(sector_heat.keys())

    # 3. 快筛候选池
    if progress_callback:
        progress_callback(0.6, "快筛候选池...")
    candidate_codes = []
    for code, s in all_stocks.items():
        if _exclude_st(s['name']):
            continue
        if s['circulation'] >= 200 or s['circulation'] <= 0:
            continue
        if not (2 <= s['change_pct'] <= 7):
            continue
        if s['vol_ratio'] <= 1.5:
            continue
        if s['amount_wan'] <= 2000:
            continue
        candidate_codes.append(code)

    # 4. 东方财富量比修正
    if progress_callback:
        progress_callback(0.7, "东方财富量比修正...")
    em_vol = _fetch_eastmoney_vol_ratio(candidate_codes[:500]) if candidate_codes else {}
    for code, em_data in em_vol.items():
        if code in all_stocks:
            all_stocks[code]['vol_ratio'] = em_data['vol_ratio']

    # 5. 三策略筛选
    if progress_callback:
        progress_callback(0.85, "三策略筛选...")
    trend = strategy_trend(all_stocks)
    yz1 = strategy_youzi_v1(all_stocks)
    yz2 = strategy_youzi_v2(all_stocks)

    # 6. 组装结果
    results = []
    seen = set()

    for s, strat in [(trend, "趋势共振"), (yz1, "游资爆量V1"), (yz2, "游资竞价V2")]:
        for stock in s:
            if stock['code'] in seen:
                continue
            seen.add(stock['code'])
            sc, tags = vibe_score(stock)
            sector = get_stock_sector(stock['code'])
            results.append(AuctionStock(
                code=stock['code'], name=stock['name'],
                price=stock['price'], change_pct=stock['change_pct'],
                vol_ratio=stock['vol_ratio'], amount_wan=stock['amount_wan'],
                turnover=stock['turnover'], high=stock['high'], low=stock['low'],
                prev_close=stock['prev_close'], open_price=stock['open'],
                circulation=stock['circulation'], strategy=strat,
                vibe_score=sc, vibe_tags=tags,
                sector=sector or "", sector_hot=sector in top_sectors,
                in_v10=stock['code'] in v10_codes,
            ))

    # V10交叉排前面
    results.sort(key=lambda x: (not x.in_v10, -x.vibe_score, -x.amount_wan))

    elapsed = time.time() - t0
    stats = {
        "total_scanned": len(all_stocks),
        "trend_count": len(trend),
        "youzi_v1_count": len(yz1),
        "youzi_v2_count": len(yz2),
        "total_selected": len(results),
        "v10_cross": sum(1 for r in results if r.in_v10),
        "elapsed": round(elapsed, 1),
    }

    return {"stocks": results, "sector_heat": sector_heat, "stats": stats}
