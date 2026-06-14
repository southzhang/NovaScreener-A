"""竞价选股引擎 v2 — 基于竞价场景的专属4维评分

竞价选股 ≠ 盘中/尾盘选股。竞价看的是：
  1. 位置（低位启动 vs 高位加速）— 最核心
  2. 高开幅度（小幅高开优选，大幅高开是风险）
  3. 竞价量能（竞价成交 vs 近期均量）
  4. 板块共振（同板块多只异动 + 板块涨幅）

优选信号 = 位置≥15 AND 高开≥15 AND 量能≥15 AND 板块≥10
进场方式 = 开盘后5分钟等回调介入，不是竞价直接买
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
    price: float               # 竞价/开盘价
    change_pct: float           # 高开幅度(%)
    open_price: float           # 开盘价
    prev_close: float           # 昨收
    vol_ratio: float            # 量比
    amount_wan: float           # 竞价成交额(万)
    turnover: float             # 换手率
    high: float
    low: float
    circulation: float          # 流通市值(亿)

    # 竞价专属字段
    auction_volume: float = 0   # 竞价成交量(手)
    auction_amount: float = 0   # 竞价成交额(万) — 来自东方财富
    near_avg_amount: float = 0  # 近5日均成交额(万)
    position_20d: float = 0     # 近20日涨幅(%)，判断位置
    sector: str = ""
    sector_hot: bool = False
    sector_change: float = 0    # 板块涨幅
    sector_auction_count: int = 0  # 同板块竞价异动数量
    in_v10: bool = False

    # 竞价4维评分
    score_position: float = 0   # 位置分(0-25)
    score_open: float = 0       # 高开幅度分(0-25)
    score_volume: float = 0     # 竞价量能分(0-25)
    score_sector: float = 0     # 板块共振分(0-25)
    total_score: float = 0      # 总分(0-100)
    action: str = "放弃"         # 可进场/观察/放弃
    action_reason: str = ""      # 进场/观察/放弃原因
    desc_position: str = ""     # 位置描述
    desc_open: str = ""         # 高开描述
    desc_volume: str = ""       # 量能描述
    desc_sector: str = ""       # 板块描述

    # 数据缺失标记（用于UI提示）
    missing_data: list = field(default_factory=list)  # 如 ["位置数据缺失", "板块数据缺失"]

    # 兼容旧字段
    strategy: str = ""          # 保留用于飞书推送
    vibe_score: int = 0
    vibe_tags: list = field(default_factory=list)


# ===== 数据获取 =====

def _fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
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
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
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
            if len(parts) < 50:
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
                # 量比：用成交额/流通市值近似（竞价阶段没有真正的量比）
                vol_ratio = round(amount / max(circ_cap * 12.5 / 10000, 1), 1) if circ_cap > 0 else 0
                # 竞价成交量(手)和买一卖一挂单
                auction_vol = float(parts[6]) if parts[6] else 0  # 成交量(手)
                results[code] = {
                    'code': code, 'name': name, 'price': price,
                    'prev_close': prev_close, 'open': open_p,
                    'volume': volume, 'amount_wan': amount,
                    'auction_volume': auction_vol,
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
    """东方财富量比修正"""
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


def _fetch_recent_avg_amount(code: str, days: int = 5) -> float:
    """获取近N日平均成交额(万) — 用于竞价量能比较"""
    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"
    # 新浪K线取近5日
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={days + 2}"
    try:
        raw = _fetch_url(url, timeout=8)
        if not raw:
            return 0
        data = json.loads(raw)
        if not isinstance(data, list) or len(data) < 2:
            return 0
        amounts = []
        for bar in data[-days:]:
            vol = float(bar.get('volume', 0))
            close = float(bar.get('close', 0))
            # 成交额 ≈ 成交量 * 收盘价（手→股→万元）
            amounts.append(vol * close / 100)  # 手*元/100=万元
        return sum(amounts) / len(amounts) if amounts else 0
    except Exception:
        return 0


def _fetch_position_20d(code: str) -> float:
    """计算近20日涨幅(%) — 判断位置高低"""
    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=25"
    try:
        raw = _fetch_url(url, timeout=8)
        if not raw:
            return 0
        data = json.loads(raw)
        if not isinstance(data, list) or len(data) < 21:
            return 0
        close_20d_ago = float(data[-21].get('close', 0))
        close_today = float(data[-1].get('close', 0))
        if close_20d_ago <= 0:
            return 0
        return round((close_today - close_20d_ago) / close_20d_ago * 100, 2)
    except Exception:
        return 0


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
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
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


# ===== 竞价4维评分 =====

def _score_position(position_20d: float, has_data: bool = True) -> tuple:
    """位置评分(0-25分)
    低位启动(近20日跌或横盘): 25分 — 竞价最安全的位置
    中位(近20日涨0-15%): 15分 — 可以但需谨慎
    高位(近20日涨15%+): 0分 — 高位加速最危险
    
    无数据时: 12分(中间偏保守) + 标记缺失
    """
    if not has_data:
        return 12, "位置未知(数据缺失)"
    if position_20d <= 0:
        return 25, f"低位启动({position_20d:+.1f}%)"
    elif position_20d <= 5:
        return 22, f"低位偏强({position_20d:+.1f}%)"
    elif position_20d <= 10:
        return 15, f"中位({position_20d:+.1f}%)"
    elif position_20d <= 15:
        return 8, f"中位偏高({position_20d:+.1f}%)"
    else:
        return 0, f"高位风险({position_20d:+.1f}%)"


def _score_open_pct(change_pct: float) -> tuple:
    """高开幅度评分(0-25分)
    2-4%最优(25分) — 小幅高开，有空间不追高
    4-5%次之(15分) — 稍高但可接受
    1-2%(15分) — 偏弱但有放量可能
    >6%(0分) — 高开太多，追高风险大
    <1%(5分) — 几乎没高开，竞价信号弱
    """
    if 2 <= change_pct <= 4:
        return 25, f"小幅高开{change_pct:+.1f}%(最优)"
    elif 4 < change_pct <= 5:
        return 15, f"偏高开{change_pct:+.1f}%"
    elif 1 <= change_pct < 2:
        return 15, f"低开{change_pct:+.1f}%"
    elif 5 < change_pct <= 6:
        return 5, f"大幅高开{change_pct:+.1f}%(追高风险)"
    elif change_pct > 6:
        return 0, f"极端高开{change_pct:+.1f}%(追高极险)"
    else:
        return 5, f"微开{change_pct:+.1f}%(信号弱)"


def _score_auction_volume(amount_wan: float, near_avg: float) -> tuple:
    """竞价量能评分(0-25分)
    竞价成交额 vs 近5日均量：放量越大越好
    """
    if near_avg <= 0:
        # 无历史数据时用成交额绝对值判断
        if amount_wan >= 8000:
            return 20, f"竞价放量{amount_wan:.0f}万(大量)"
        elif amount_wan >= 3000:
            return 15, f"竞价放量{amount_wan:.0f}万(中等)"
        elif amount_wan >= 1000:
            return 10, f"竞价{amount_wan:.0f}万(一般)"
        else:
            return 5, f"竞价{amount_wan:.0f}万(偏小)"

    ratio = amount_wan / near_avg
    # 竞价阶段成交额通常是全天的5-15%，所以 ratio > 0.3 就算放量了
    if ratio >= 0.5:
        return 25, f"竞价爆量{ratio:.1f}x均量"
    elif ratio >= 0.3:
        return 20, f"竞价放量{ratio:.1f}x均量"
    elif ratio >= 0.15:
        return 15, f"竞价量能{ratio:.1f}x均量"
    elif ratio >= 0.05:
        return 8, f"竞价量一般{ratio:.1f}x均量"
    else:
        return 0, f"竞价缩量{ratio:.1f}x均量"


def _score_sector(sector: str, sector_hot: bool, sector_change: float,
                  sector_auction_count: int) -> tuple:
    """板块共振评分(0-25分)
    同板块多只竞价异动 + 板块涨幅 = 共振强
    
    无板块数据时: 8分(保守) + 标记缺失
    """
    if not sector:
        return 8, "板块未知(数据缺失)"

    score = 0
    parts = []

    # 板块涨幅
    if sector_change and sector_change > 2:
        score += 10
        parts.append(f"板块+{sector_change:.1f}%")
    elif sector_change and sector_change > 0:
        score += 5
        parts.append(f"板块+{sector_change:.1f}%")
    else:
        score += 0
        parts.append("板块弱")

    # 板块热度标记
    if sector_hot:
        score += 5
        parts.append("热门板块")

    # 同板块竞价异动数量
    if sector_auction_count >= 3:
        score += 10
        parts.append(f"板块{sector_auction_count}只异动(强共振)")
    elif sector_auction_count >= 2:
        score += 5
        parts.append(f"板块{sector_auction_count}只异动")
    else:
        score += 0

    desc = " ".join(parts) if parts else "无板块共振"
    return min(score, 25), desc


def _classify_action(total: float, sp: float, so: float, sv: float, ss: float,
                     in_v10: bool) -> tuple:
    """判定进场建议

    返回: (action, reason)
    - 可进场: 四维都达标，开盘后等回调介入
    - 观察: 有亮点但有短板，等15分钟看走势
    - 放弃: 多维不足
    """
    # ✅ 可进场：四维均达标
    if sp >= 15 and so >= 15 and sv >= 15 and ss >= 10 and total >= 65:
        reasons = []
        if sp >= 22:
            reasons.append("低位启动")
        if so >= 25:
            reasons.append("小幅高开最优")
        if sv >= 20:
            reasons.append("竞价放量")
        if ss >= 15:
            reasons.append("板块共振")
        if in_v10:
            reasons.append("V10交叉")
        return "可进场", "开盘5分钟等回调介入 · " + " · ".join(reasons) if reasons else "开盘5分钟等回调介入"

    # V10交叉加分：如果V10信号+任意两维达标，可进场
    if in_v10 and sp >= 10 and so >= 10 and sv >= 10 and total >= 55:
        return "可进场", "V10交叉+竞价信号确认 · 开盘5分钟等回调介入"

    # 👁️ 观察：有亮点但有短板
    bright_dims = sum(1 for s in [sp, so, sv, ss] if s >= 15)
    if bright_dims >= 2 and total >= 40:
        weak = []
        if sp < 15:
            weak.append("位置偏高")
        if so < 15:
            weak.append("高开幅度不理想")
        if sv < 15:
            weak.append("量能不足")
        if ss < 10:
            weak.append("板块弱")
        return "观察", "等15分钟看走势 · 短板: " + " / ".join(weak)

    # V10交叉保底观察
    if in_v10 and total >= 35:
        return "观察", "V10交叉但竞价信号一般 · 等15分钟确认"

    # ❌ 放弃
    weak = []
    if sp < 10:
        weak.append("高位")
    if so < 10:
        weak.append("高开过大" if so == 0 and so != 5 else "高开不足")
    if sv < 8:
        weak.append("缩量")
    if ss < 5:
        weak.append("无板块共振")
    reason = " / ".join(weak) if weak else "多维不足"
    return "放弃", reason


# ===== 主入口 =====

def _exclude_st(name: str) -> bool:
    return 'ST' in name or '退' in name or name.startswith('N')


def run_auction_scan(progress_callback=None) -> dict:
    """
    运行竞价选股扫描 v2
    返回: {stocks: [AuctionStock], sector_heat: {}, stats: {}}
    """
    t0 = time.time()
    v10_codes = set()
    v10_recommend_codes = set()   # V10推荐进场的票
    v10_observe_codes = set()     # V10观察池的票

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

    # 尝试读取V10推荐结果（交叉验证用）
    rec_path = os.path.expanduser('~/.hermes/cache/v10_tail_recommend.json')
    if os.path.exists(rec_path):
        try:
            with open(rec_path) as f:
                rec_data = json.load(f)
            for s in rec_data.get('recommend', []):
                code = re.sub(r'\D', '', s.get('code', ''))
                if code:
                    v10_recommend_codes.add(code)
            for s in rec_data.get('observe', []):
                code = re.sub(r'\D', '', s.get('code', ''))
                if code:
                    v10_observe_codes.add(code)
        except Exception:
            pass

    # 1. 腾讯全量行情
    if progress_callback:
        progress_callback(0.1, "获取竞价行情...")
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
        progress_callback(0.3, "获取板块热度...")
    sector_heat = fetch_sector_rank()
    top_sectors = set(sector_heat.keys())

    # 3. 快筛候选池 — 竞价阶段筛选条件
    if progress_callback:
        progress_callback(0.5, "快筛候选池...")
    candidates = {}
    for code, s in all_stocks.items():
        if _exclude_st(s['name']):
            continue
        if s['circulation'] >= 200 or s['circulation'] <= 0:
            continue
        # 竞价阶段：只看高开1-7%的票（小幅高开+适度高开）
        if not (1 <= s['change_pct'] <= 7):
            continue
        # 竞价有成交（过滤停牌/未开盘）
        if s['amount_wan'] <= 500:
            continue
        # 量比最低要求
        if s['vol_ratio'] <= 1.5:
            continue
        candidates[code] = s

    # 4. 东方财富量比修正
    if progress_callback:
        progress_callback(0.6, "量比修正...")
    candidate_codes = list(candidates.keys())
    em_vol = _fetch_eastmoney_vol_ratio(candidate_codes[:500]) if candidate_codes else {}
    for code, em_data in em_vol.items():
        if code in all_stocks:
            all_stocks[code]['vol_ratio'] = em_data['vol_ratio']

    # 5. 并发获取位置和量能数据（竞价4维评分核心数据）
    if progress_callback:
        progress_callback(0.7, "获取位置和量能数据...")

    # 先获取所有候选的板块，统计同板块异动数
    sector_map = {}  # code -> sector
    sector_auction_count = {}  # sector -> 异动数量

    # 批量获取板块
    def _get_sector_batch(code_list):
        result = {}
        for code in code_list:
            sec = get_stock_sector(code)
            if sec:
                result[code] = sec
        return result

    with ThreadPoolExecutor(max_workers=10) as executor:
        chunks = [candidate_codes[i:i+20] for i in range(0, len(candidate_codes), 20)]
        sector_futures = [executor.submit(_get_sector_batch, chunk) for chunk in chunks]
        for f in as_completed(sector_futures):
            sector_map.update(f.result())

    # 统计同板块异动数量
    for code, sec in sector_map.items():
        sector_auction_count[sec] = sector_auction_count.get(sec, 0) + 1

    # 并发获取位置(20日涨幅)和近期均量（不限80只，全部候选都取）
    position_cache = {}
    avg_amount_cache = {}
    # 追踪数据获取失败
    position_failed = set()
    avg_failed = set()

    def _fetch_position(code):
        try:
            pos = _fetch_position_20d(code)
            return code, pos, pos != 0 or True  # 0可能是真实数据
        except Exception:
            return code, 0, False

    def _fetch_avg(code):
        try:
            avg = _fetch_recent_avg_amount(code, 5)
            return code, avg, avg > 0  # avg=0意味着数据缺失
        except Exception:
            return code, 0, False

    # 限制并发量避免API限流，分批处理
    MAX_POSITION_FETCH = 150  # 最多取150只的位置数据
    MAX_AVG_FETCH = 150
    fetch_codes_pos = candidate_codes[:MAX_POSITION_FETCH]
    fetch_codes_avg = candidate_codes[:MAX_AVG_FETCH]

    with ThreadPoolExecutor(max_workers=10) as executor:
        pos_futures = {executor.submit(_fetch_position, c): c for c in fetch_codes_pos}
        avg_futures = {executor.submit(_fetch_avg, c): c for c in fetch_codes_avg}
        for f in as_completed(pos_futures):
            try:
                code, pos, ok = f.result()
                position_cache[code] = pos
                if not ok:
                    position_failed.add(code)
            except Exception:
                code = pos_futures[f]
                position_failed.add(code)
        for f in as_completed(avg_futures):
            try:
                code, avg, ok = f.result()
                avg_amount_cache[code] = avg
                if not ok:
                    avg_failed.add(code)
            except Exception:
                code = avg_futures[f]
                avg_failed.add(code)

    # 6. 竞价4维评分
    if progress_callback:
        progress_callback(0.9, "竞价4维评分...")

    results = []
    seen = set()

    for code, s in candidates.items():
        if code in seen:
            continue
        seen.add(code)

        # 获取板块信息
        sec = sector_map.get(code, "")
        sec_hot = sec in top_sectors
        sec_change = sector_heat.get(sec, 0) if sec else 0
        sec_auction_n = sector_auction_count.get(sec, 0) if sec else 0

        # 获取位置和量能
        pos_20d = position_cache.get(code, 0)
        near_avg = avg_amount_cache.get(code, 0)
        has_pos_data = code in position_cache and code not in position_failed
        has_avg_data = code in avg_amount_cache and code not in avg_failed

        # 数据缺失追踪
        missing = []
        if code not in position_cache:
            missing.append("位置数据缺失")
        if code not in avg_amount_cache or code in avg_failed:
            missing.append("均量数据缺失")
        if not sec:
            missing.append("板块数据缺失")

        # 4维评分
        sp, sp_desc = _score_position(pos_20d, has_data=has_pos_data)
        so, so_desc = _score_open_pct(s['change_pct'])
        sv, sv_desc = _score_auction_volume(s['amount_wan'], near_avg)
        ss, ss_desc = _score_sector(sec, sec_hot, sec_change, sec_auction_n)
        total = sp + so + sv + ss

        # 判定策略标签（兼容旧字段）
        if s['change_pct'] >= 3 and s['amount_wan'] >= 2000 and s['vol_ratio'] >= 3 and s['circulation'] < 200:
            strategy = "趋势共振"
        elif s['change_pct'] >= 3 and s['amount_wan'] >= 5000 and s['vol_ratio'] >= 4 and s['circulation'] < 100:
            strategy = "游资爆量V1"
        elif s['change_pct'] >= 2 and s['vol_ratio'] >= 2 and s['circulation'] < 100:
            strategy = "游资竞价V2"
        else:
            strategy = "竞价异动"

        # Vibe评分（保留兼容）
        vibe = 0
        vtags = []
        if s['change_pct'] > 3:
            vibe += 1; vtags.append('强势开盘')
        if s['vol_ratio'] > 3:
            vibe += 1; vtags.append('量价齐升')
        if s.get('high', 0) > 0 and s.get('low', 0) > 0 and s['prev_close'] > 0:
            amp = (s['high'] - s['low']) / s['prev_close'] * 100
            if amp > 5:
                vibe += 1; vtags.append('振幅大')
        if 5 < s['vol_ratio'] < 500:
            vibe += 1; vtags.append('爆量')

        # 判定进场建议
        action, action_reason = _classify_action(
            total, sp, so, sv, ss, code in v10_codes
        )

        # V10交叉验证：如果V10推荐结果是"观察"（非"推荐进场"），
        # 竞价的"可进场"应降级为"观察"，避免两个模块结论矛盾
        if action == "可进场" and code in v10_observe_codes and code not in v10_recommend_codes:
            action = "观察"
            action_reason = "V10评分未达推荐门槛 · " + action_reason + " · 降级为观察"
        
        # V10推荐进场的票，观察升级为"可进场（V10确认）"
        if action == "观察" and code in v10_recommend_codes:
            action = "可进场"
            action_reason = "V10推荐进场+竞价信号确认 · " + action_reason

        stock = AuctionStock(
            code=code, name=s['name'],
            price=s['price'], change_pct=s['change_pct'],
            open_price=s.get('open', s['price']),
            prev_close=s['prev_close'],
            vol_ratio=s['vol_ratio'], amount_wan=s['amount_wan'],
            turnover=s['turnover'], high=s['high'], low=s['low'],
            circulation=s['circulation'],
            auction_volume=s.get('auction_volume', 0),
            near_avg_amount=near_avg,
            position_20d=pos_20d,
            sector=sec or "", sector_hot=sec_hot,
            sector_change=sec_change if isinstance(sec_change, (int, float)) else 0,
            sector_auction_count=sec_auction_n,
            in_v10=code in v10_codes,
            score_position=sp, score_open=so, score_volume=sv, score_sector=ss,
            total_score=total, action=action, action_reason=action_reason,
            desc_position=sp_desc, desc_open=so_desc, desc_volume=sv_desc, desc_sector=ss_desc,
            missing_data=missing,
            strategy=strategy, vibe_score=vibe, vibe_tags=vtags,
        )
        results.append(stock)

    # 排序：可进场优先，再按总分降序
    action_order = {"可进场": 0, "观察": 1, "放弃": 2}
    results.sort(key=lambda x: (action_order.get(x.action, 3), -x.total_score))

    elapsed = time.time() - t0

    # 统计
    buy_count = sum(1 for r in results if r.action == "可进场")
    watch_count = sum(1 for r in results if r.action == "观察")
    drop_count = sum(1 for r in results if r.action == "放弃")

    stats = {
        "total_scanned": len(all_stocks),
        "total_candidates": len(candidates),
        "total_selected": len(results),
        "buy_count": buy_count,
        "watch_count": watch_count,
        "drop_count": drop_count,
        "v10_cross": sum(1 for r in results if r.in_v10),
        "elapsed": round(elapsed, 1),
    }

    return {"stocks": results, "sector_heat": sector_heat, "stats": stats}
