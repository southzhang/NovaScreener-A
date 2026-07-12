#!/usr/bin/env python3
"""竞价选股v7 — 独立于V10的竞价短线策略线
时间: 09:28跑(09:25竞价结束 → 09:30前出结果)
数据: quote_adapter统一行情(QMT优先→腾讯回退) + 东方财富板块热度 + K线30日位置
策略: 竞价优选(小幅高开+放量+低位+板块共振) + 竞价激进(高开高打+爆量) + V10交叉标记
核心核对: 位置+高开幅度+量能+板块 → 优选信号开盘后择机介入，不符合则放弃
"""
import urllib.request, json, re, sys, time, os
from datetime import datetime
from quote_adapter import get_full_market_quotes, get_source_name

# ── 常量 ──
V10_WATCHLIST = os.path.expanduser('~/.hermes/cache/v10_watchlist.json')
V10_TAIL_PREFETCH = os.path.expanduser('~/.hermes/workspace/v10_tail_prefetch.json')

# 排除板块（688=科创板, 北交所代码段）
EXCLUDE_CODES = {'688', '689', '8', '4'}  # 8xxx=北交所, 4xxx=老三板

# ── 东方财富量比字段 ──
# f10=量比, f2=现价, f3=涨跌幅, f5=成交量, f6=成交额
# 交易时段push2才有数据，凌晨返回空

def fetch_eastmoney_vol_ratio(codes):
    """从东方财富获取真实量比 — 批量"""
    results = {}
    # 按市场分组
    sz = [c for c in codes if c.startswith('0') or c.startswith('3')]
    sh = [c for c in codes if c.startswith('6')]
    
    def batch_fetch(secids, market_prefix):
        if not secids:
            return {}
        batch = ','.join([f"{market_prefix}.{c}" for c in secids])
        url = (f"https://push2.eastmoney.com/api/qt/stock/get?secid={batch}&fields=f10,f3,f6")
        raw = fetch_url(url)
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
                    change_r = item.get('f3')
                    amount_r = item.get('f6')
                    if vol_r is not None:
                        res[code] = {
                            'vol_ratio': float(vol_r),
                            'change_from_em': float(change_r) if change_r else None,
                            'amount_from_em': float(amount_r) if amount_r else None,
                        }
            return res
        except:
            return {}
    
    results.update(batch_fetch(sh, '1'))
    results.update(batch_fetch(sz, '0'))
    return results

# ── 辅助函数 ──

def fetch_url(url, timeout=15):
    """通用HTTP GET"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://quote.eastmoney.com/',
        })
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode('utf-8', errors='ignore')
    except Exception:
        return None

# ── 数据规范化和QMT补充 ──

def _normalize_market_data(raw_stocks):
    """将 get_full_market_quotes() 返回的数据规范化为策略所需格式
    兼容腾讯和QMT两种数据源格式：
    - 腾讯: price, prev_close, amount_wan, vol_ratio, circulation, turnover, limit_up/down 等
    - QMT:  lastPrice, prevClose, amount(元), 缺少量比/流通市值/换手率等字段
    """
    all_stocks = {}
    for code, s in raw_stocks.items():
        # 排除688/北交所
        if code[:3] in EXCLUDE_CODES or code[0] in {'8', '4'}:
            continue

        price = s.get('price') or s.get('lastPrice', 0)
        if price <= 0:
            continue

        prev_close = s.get('prev_close') or s.get('prevClose', 0)
        name = s.get('name', '')
        open_p = s.get('open', 0)
        volume = s.get('volume', 0)
        high = s.get('high', 0)
        low = s.get('low', 0)

        # amount字段：腾讯返回amount_wan(万)，QMT返回amount(元)
        amount_wan = s.get('amount_wan')
        if amount_wan is not None:
            amount_yuan = s.get('amount_yuan') or amount_wan * 10000
        else:
            raw_amount = s.get('amount', 0)
            # QMT amount通常>100000(元)，腾讯amount_wan通常<100000(万)
            if raw_amount > 100000:
                amount_wan = raw_amount / 10000
                amount_yuan = raw_amount
            else:
                amount_wan = raw_amount
                amount_yuan = raw_amount * 10000

        market = s.get('market', 'sh' if code.startswith('6') else 'sz')

        change_pct = s.get('change_pct', 0)
        if not change_pct and prev_close > 0:
            change_pct = round((price - prev_close) / prev_close * 100, 2)

        # 量比估算：成交额 / (流通市值 * 基准比率)
        # 优先使用API原始量比，无数据时用估算值
        # 注意：amount_wan单位是万，circulation单位是亿
        vol_ratio = s.get('vol_ratio', 0)
        circulation = s.get('circ_cap', 0)
        if vol_ratio <= 0 and circulation > 0:
            vol_ratio = round(amount_wan / max(circulation * 5.0 / 10000, 1), 1)

        all_stocks[code] = {
            'code': code, 'name': name, 'price': price,
            'prev_close': prev_close, 'open': open_p,
            'volume': volume, 'amount_wan': amount_wan,
            'turnover': s.get('turnover', 0),
            'high': high, 'low': low,
            'change_pct': change_pct, 'vol_ratio': vol_ratio,
            'circulation': circulation, 'market': market,
            'amount_yuan': amount_yuan,
            'limit_up': s.get('limit_up', 0),
            'limit_down': s.get('limit_down', 0),
            'outer_vol': s.get('outer_vol', 0),
            'inner_vol': s.get('inner_vol', 0),
            'pe_ttm': s.get('pe_ttm', 0),
            'amplitude': s.get('amplitude', 0),
            'total_cap': s.get('total_cap', 0),
        }

    return all_stocks


def _supplement_qmt_fields(all_stocks):
    """QMT模式缺少vol_ratio/circulation/turnover/limit_up/limit_down等字段，
    回退到腾讯全量补充这些字段。
    
    策略：QMT先做基础预筛（涨跌幅/成交额/非ST），然后用腾讯并行8线程补充缺失字段。
    """
    # 先用QMT基础字段做宽松预筛，减少需补充的股票数量
    pre_filter = []
    for code, s in all_stocks.items():
        if exclude_st(s['name']):
            continue
        if s['price'] <= 0 or s['prev_close'] <= 0:
            continue
        if s['volume'] <= 0:
            continue
        # 宽松涨跌幅范围(0-10%)和金额门槛(>500万)
        if not (0 <= s['change_pct'] <= 10):
            continue
        if s['amount_wan'] <= 500:
            continue
        pre_filter.append(code)

    if not pre_filter:
        print(f"  → QMT预筛无候选，跳过腾讯补充", file=sys.stderr)
        return

    print(f"  → QMT预筛候选: {len(pre_filter)}只，从腾讯补充缺失字段...", file=sys.stderr)

    # 强制使用腾讯获取全量数据（并行8线程，3-5秒）
    # 全量获取比逐只获取更快（腾讯API批量100只/请求，8线程并发）
    tencent_data = get_full_market_quotes(prefer_qmt=False)

    # 只提取QMT缺失的关键字段进行合并
    SUPPLEMENT_FIELDS = [
        'vol_ratio', 'circulation', 'turnover',
        'limit_up', 'limit_down', 'outer_vol',
        'inner_vol', 'pe_ttm', 'amplitude', 'total_cap',
    ]
    supplemented = 0
    for code, td in tencent_data.items():
        if code not in all_stocks:
            continue
        for field in SUPPLEMENT_FIELDS:
            val = td.get(field, 0)
            if val:  # 只覆盖非零值
                all_stocks[code][field] = val
        # 腾讯的change_pct更准确（含竞价阶段），覆盖QMT计算的值
        if td.get('change_pct'):
            all_stocks[code]['change_pct'] = td['change_pct']
        supplemented += 1

    # 重新估算量比（部分腾讯数据也可能返回0）
    # 注意：amount_wan单位是万，circulation单位是亿
    for code, s in all_stocks.items():
        if s['vol_ratio'] <= 0 and s['circulation'] > 0:
            s['vol_ratio'] = round(s['amount_wan'] / max(s['circulation'] * 5.0 / 10000, 1), 1)

    print(f"  → 腾讯补充 {supplemented} 只的缺失字段", file=sys.stderr)


# ── 板块热度 ──

def fetch_sector_rank():
    """东方财富行业板块涨跌排行 TOP15，降级到sector_analysis（腾讯ETF）"""
    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=15"
           "&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2"
           "&fields=f2,f3,f4,f12,f14&_=" + str(int(time.time()*1000)))
    raw = fetch_url(url)
    if raw:
        try:
            data = json.loads(raw)
            items = data.get('data', {}).get('diff', [])
            if items:
                result = {x.get('f14', ''): x.get('f3') for x in items if x.get('f14')}
                if result:
                    return result
        except:
            pass
    
    # 降级：使用sector_analysis模块（内含腾讯ETF降级逻辑）
    print("  ⚠️ 东方财富板块API不可用，降级到sector_analysis", file=sys.stderr)
    try:
        from sector_analysis import get_sector_ranking
        ranking = get_sector_ranking()
        if ranking and isinstance(ranking, dict):
            industry_list = ranking.get('industry', [])
            if industry_list:
                # sector_analysis返回的是列表格式，转为 {板块名: 涨幅} 字典
                result = {}
                for item in industry_list[:15]:
                    if isinstance(item, dict) and 'name' in item:
                        result[item['name']] = item.get('change', 0)
                if result:
                    return result
    except Exception as e:
        print(f"  ⚠️ sector_analysis降级也失败: {e}", file=sys.stderr)
    
    return {}

def get_stock_sector(code):
    """查个股所属行业板块 — 东方财富，降级到ifind_sector_cache"""
    secid = f"1.{code}" if code.startswith('6') else f"0.{code}"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f127"
    raw = fetch_url(url)
    if raw:
        try:
            data = json.loads(raw)
            industry = data.get('data', {}).get('f127', '')
            if industry:
                return industry
        except:
            pass
    
    # 降级：使用ifind_sector_cache的板块映射
    try:
        import os, json as _json
        cache_path = os.path.expanduser('~/.hermes/cache/ifind_sector.json')
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                sector_data = _json.load(f)
            # ifind_sector.json格式: {code: {name:..., sw_l1:..., ths_l1:...}} 
            entry = sector_data.get(code)
            if isinstance(entry, dict):
                result = entry.get('sw_l1') or entry.get('ths_l1') or entry.get('industry') or entry.get('sector')
                if result:
                    return result
            elif isinstance(entry, str):
                return entry
    except Exception:
        pass
    
    # 二次降级：sector_map.json（map字段）
    try:
        import os, json as _json
        cache_path = os.path.expanduser('~/.hermes/cache/sector_map.json')
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                sector_map_data = _json.load(f)
            # sector_map.json格式: {_time:..., map: {code: industry}}
            sector_map_inner = sector_map_data.get('map', sector_map_data)
            result = sector_map_inner.get(code)
            if result:
                return result
    except Exception:
        pass
    
    return None

def get_stock_sectors_batch(codes, max_workers=16, max_time=25):
    """批量获取个股所属行业板块 — 东方财富并发
    max_time: 总超时秒数，防止盘中API慢导致整体卡死
    """
    import concurrent.futures
    result = {}
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(get_stock_sector, code): code for code in codes}
        for future in concurrent.futures.as_completed(futures):
            if (time.time() - t0) > max_time:
                # 超时：取消未完成的futures
                for f in futures:
                    f.cancel()
                break
            try:
                sector = future.result(timeout=5)
                code = futures[future]
                if sector:
                    result[code] = sector
            except:
                pass
    return result

# ── V10交叉标记 ──

def load_v10_signals():
    """读取V10昨日watchlist信号"""
    v10_codes = set()
    for path in [V10_WATCHLIST, V10_TAIL_PREFETCH]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                stocks = data.get('stocks', data.get('candidates', []))
                for s in stocks:
                    code = s.get('code', '') or ''
                    code = re.sub(r'\D', '', code)
                    if code:
                        v10_codes.add(code)
            except:
                pass
    return v10_codes

# ── 三策略 ──

# ── K线位置计算 ──

def _fetch_klines_batch(codes, count=30):
    """批量获取日K线，计算30日位置指标
    返回: dict {code: {high_30d, low_30d, position_pct, change_30d, ma20}}
    
    优化：优先使用东方财富批量API（16线程并发，741只≈50秒），
    超时或失败时回退到quote_adapter。
    总超时60秒防止竞价时段卡住。
    """
    import concurrent.futures
    result = {}
    
    if not codes:
        return result
    
    t0 = time.time()
    max_time = 28  # 🛡️ 06-28 从40s调到28s，留余量给全局100s deadline
    
    # 方案1: 东方财富K线API批量并发（主力，速度快）
    em_result = {}
    try:
        def _fetch_em_kline(code):
            try:
                if code.startswith('6'):
                    secid = f'1.{code}'
                else:
                    secid = f'0.{code}'
                url = f'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&end=20500101&lmt={count}'
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Referer': 'https://quote.eastmoney.com/',
                })
                resp = urllib.request.urlopen(req, timeout=8)
                data = json.loads(resp.read().decode())
                klines = data.get('data', {}).get('klines', [])
                if klines and len(klines) >= 5:
                    bars = []
                    for line in klines:
                        parts = line.split(',')
                        if len(parts) >= 5:
                            bars.append({
                                'date': parts[0],
                                'open': float(parts[1]),
                                'close': float(parts[2]),
                                'high': float(parts[3]),
                                'low': float(parts[4]),
                            })
                    return code, bars
            except:
                pass
            return code, []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            futures = {executor.submit(_fetch_em_kline, code): code for code in codes}
            for future in concurrent.futures.as_completed(futures):
                if (time.time() - t0) > max_time:
                    break
                try:
                    code, bars = future.result(timeout=5)
                    if bars:
                        em_result[code] = bars
                except:
                    pass
        print(f"  → 东方财富K线获取: {len(em_result)}/{len(codes)}只, 耗时{time.time()-t0:.1f}s", file=sys.stderr)
    except Exception as e:
        print(f"  → 东方财富K线失败: {e}", file=sys.stderr)
    
    # 方案2: 对东方财富未拿到的用quote_adapter补充（最多50只，防止太慢）
    missing = [c for c in codes if c not in em_result]
    if missing:
        from quote_adapter import get_kline
        supplement_count = 0
        for code in missing[:50]:
            if (time.time() - t0) > max_time:
                break
            try:
                bars = get_kline(code, period='1d', count=count, prefer_qmt=False)
                if bars and len(bars) >= 5:
                    em_result[code] = bars
                    supplement_count += 1
            except:
                pass
        if supplement_count:
            print(f"  → quote_adapter补充K线: {supplement_count}只", file=sys.stderr)
    
    # 计算位置指标
    for code in codes:
        bars = em_result.get(code, [])
        if not bars or len(bars) < 5:
            continue
        
        try:
            highs = [b['high'] for b in bars if b.get('high', 0) > 0]
            lows = [b['low'] for b in bars if b.get('low', 0) > 0]
            closes = [b['close'] for b in bars if b.get('close', 0) > 0]
            
            if len(closes) < 5:
                continue
            
            high_30d = max(highs)
            low_30d = min(lows)
            last_close = closes[-1]
            first_close = closes[0]
            
            # 30日位置百分比（0=最低，100=最高）
            position_pct = (last_close - low_30d) / (high_30d - low_30d) * 100 if high_30d != low_30d else 50
            
            # 近30日涨幅
            change_30d = (last_close - first_close) / first_close * 100 if first_close > 0 else 0
            
            # MA20近似
            if len(closes) >= 20:
                window = closes[-20:]
                ma20 = sum(window) / len(window)
            else:
                ma20 = 0
            
            result[code] = {
                'high_30d': round(high_30d, 2),
                'low_30d': round(low_30d, 2),
                'position_pct': round(position_pct, 1),
                'change_30d': round(change_30d, 1),
                'ma20': round(ma20, 2),
            }
        except:
            continue
    
    return result


# ── 三策略 → 两策略重构 ──

def exclude_st(name):
    return 'ST' in name or '退' in name or name.startswith('N') or name.startswith('*ST')

def _sector_match(sector, top_sectors):
    """板块共振匹配：个股行业名与热门板块做双向子串匹配
    top_sectors可能是ETF名称(如"新能源ETF南方")或行业名(如"半导体")
    个股sector可能是申万行业(如"化学制品")或概念名
    匹配规则：任一方向包含对方关键词(2字+)即算共振
    """
    if not sector or not top_sectors:
        return False
    sector_clean = sector.replace('Ⅱ', '').replace('Ⅲ', '').strip()
    for hot_name in top_sectors:
        hot_clean = hot_name.replace('ETF', '').replace('基金', '').strip()
        # 个股行业名包含热门板块关键词
        if len(hot_clean) >= 2 and hot_clean in sector_clean:
            return True
        # 热门板块名包含个股行业关键词
        if len(sector_clean) >= 2 and sector_clean in hot_clean:
            return True
    return False

def strategy_preferred(stocks, positions, top_sectors, sector_map):
    """竞价优选 — 小幅高开+放量+低位+板块共振
    核心逻辑：位置好(低位启动) + 温和高开(1-4%) + 放量确认 + 板块配合
    这是最安全的竞价买点：空间大、追高风险小
    """
    candidates = []
    for code, s in stocks.items():
        if exclude_st(s['name']):
            continue
        # 流通市值：5-200亿（宽松：None/0不直接排除，标记后降级处理）
        circ = s.get('circulation', 0) or 0
        if circ > 0 and (circ >= 200 or circ < 5):
            continue
        # 高开幅度：1-4%（小幅高开，还有空间）
        if not (1 <= s['change_pct'] <= 4):
            continue
        # 量比：>1.5（竞价阶段放宽，盘中要求2+）
        if s['vol_ratio'] < 1.5:
            continue
        # 竞价成交额：>500万（从1500万放宽到500万，竞价阶段量本就少）
        if s['amount_wan'] <= 500:
            continue
        
        # 位置判断（无K线数据时不排除，标记为未知降级）
        pos = positions.get(code, {})
        position_pct = pos.get('position_pct', -1)
        change_30d = pos.get('change_30d', 999)
        
        # 低位优先：30日位置<60% 且 近30日涨幅<15%
        is_low_position = False
        if position_pct >= 0:
            if position_pct < 60 and change_30d < 15:
                is_low_position = True
        else:
            # 无K线数据，不排除，降级处理
            is_low_position = None
        
        # 板块共振（关键词匹配：个股行业名与热门板块名做子串匹配）
        sector = sector_map.get(code, '')
        in_hot_sector = _sector_match(sector, top_sectors)
        
        # 计算优选得分
        score = 0
        if is_low_position is True:
            score += 3  # 低位最强加分
        elif is_low_position is None:
            score += 1  # 未知位置，弱加分
        # else: 高位，不加分
        
        if in_hot_sector:
            score += 2  # 板块共振
        if 1.5 <= s['change_pct'] <= 3:
            score += 1  # 高开2-3%最优区间
        if 3 <= s['vol_ratio'] <= 8:
            score += 1  # 量比3-8最优区间
        
        s['_pref_score'] = score
        s['_is_low_position'] = is_low_position
        s['_in_hot_sector'] = in_hot_sector
        candidates.append(s)
    
    # 按优选得分排序，再按成交额
    candidates.sort(key=lambda x: (-x.get('_pref_score', 0), -x['amount_wan']))
    return candidates[:10]


def strategy_aggressive(stocks, positions, top_sectors, sector_map):
    """竞价激进 — 高开高打+爆量+游资风格
    核心逻辑：强势开盘(4-7%) + 爆量(量比>4) + 小盘(流通<100亿)
    风险较高，但可能是强势股加速段
    """
    candidates = []
    for code, s in stocks.items():
        if exclude_st(s['name']):
            continue
        # 流通市值：<100亿（宽松：None/0不排除）
        circ = s.get('circulation', 0) or 0
        if circ > 0 and circ >= 100:
            continue
        # 高开幅度：3-7%（从4-7放宽到3-7，给更多机会）
        if not (3 <= s['change_pct'] <= 7):
            continue
        # 爆量：量比>3（从>4放宽到>3）
        if s['vol_ratio'] < 3:
            continue
        # 成交额：>2000万（从3000万放宽到2000万）
        if s['amount_wan'] <= 2000:
            continue
        
        # 位置判断
        pos = positions.get(code, {})
        position_pct = pos.get('position_pct', -1)
        change_30d = pos.get('change_30d', 999)
        is_low_position = False
        if position_pct >= 0:
            if position_pct < 60 and change_30d < 15:
                is_low_position = True
        else:
            is_low_position = None
        
        sector = sector_map.get(code, '')
        in_hot_sector = _sector_match(sector, top_sectors)
        
        # 激进得分
        score = 0
        if is_low_position is True:
            score += 2  # 低位仍有加分
        if in_hot_sector:
            score += 2
        if s['vol_ratio'] > 6:
            score += 1  # 超爆量
        
        s['_aggr_score'] = score
        s['_is_low_position'] = is_low_position
        s['_in_hot_sector'] = in_hot_sector
        candidates.append(s)
    
    candidates.sort(key=lambda x: (-x.get('_aggr_score', 0), -x['amount_wan']))
    return candidates[:5]

# ── Vibe评分 ──

def vibe_score(s):
    """Vibe快速评分（竞价简化版：基于竞价可获取的指标，不含SMC/缠论）
    
    ⚠️ 与盘中完整版Vibe评分体系不同：
    - 竞价版：量价+位置评分（本函数），输出标注[竞价版]
    - 盘中版：SMC+缠论+K线形态（tech_analysis.vibe_score），输出无标注
    竞价版分数通常低于盘中版，两版不可直接对比。
    
    ⚠️ 竞价阶段量比为估算值（基于竞价成交额/流通市值），
    非盘中真实量比，阈值已适配竞价场景。
    """
    score = 0
    tags = []
    # 振幅（竞价阶段振幅=高开幅度，更直接）
    change_pct = s.get('change_pct', 0)
    if 1 <= change_pct <= 3:
        score += 1
        tags.append('温和高开')
    elif 3 < change_pct <= 5:
        score += 0  # 中性，不加分也不扣分
        tags.append('偏高开')
    elif change_pct > 5:
        tags.append('大幅高开')  # 不加分，追高风险
    
    # 量价齐升（竞价量比为估算值，阈值适当降低）
    vol_ratio = s.get('vol_ratio', 0)
    if vol_ratio > 1.5 and change_pct > 0:  # 盘中要求>3，竞价降低至>1.5
        score += 1
        tags.append('量价齐升')
    
    # 爆量（竞价量比3-10，盘中5-15，竞价阶段降低阈值）
    if 3 < vol_ratio < 10:  # 盘中5-15，竞价适配为3-10
        score += 1
        tags.append('爆量')
    
    # 低位启动加分
    is_low = s.get('_is_low_position')
    if is_low is True:
        score += 1
        tags.append('低位启动')
    
    return score, tags

# ── 买入推荐评级 ──

def buy_recommendation(s, v10_codes, sector_heat, top_sectors, strategy_name, positions=None, sentiment_data=None):
    """竞价选股买入推荐评级（对照推荐铁律七关验证中适用竞价场景的关卡）
    
    竞价核心核对：位置+高开幅度+量能+板块
    适用关卡：①V10信号 ②实时数据 ③Vibe评分 ④板块风口 ⑤追高安全垫
    不适用：⑥仓位 ⑦止损空间（竞价阶段无EMA/止损位数据，留待盯盘判断）
    
    返回: (stars, reasons, warnings)
      stars: '★★★' / '★★☆' / '★☆☆' / '⚠️观望'
      reasons: 推荐理由列表
      warnings: 风险提示列表
    """
    reasons = []
    warnings = []
    code = s['code']
    name = s.get('name', '')
    change_pct = s.get('change_pct', 0)
    vol_ratio = s.get('vol_ratio', 0)
    amount_wan = s.get('amount_wan', 0)
    circulation = s.get('circ_cap', 0)
    
    # ── 关① V10信号 ──
    in_v10 = code in v10_codes
    if in_v10:
        reasons.append('📌V10交叉')
    
    # ── 位置判断（竞价核心维度）──
    pos = (positions or {}).get(code, {})
    position_pct = pos.get('position_pct', -1)
    change_30d = pos.get('change_30d', 999)
    is_low_position = s.get('_is_low_position')  # 策略已算好
    is_high_position = False
    
    if position_pct >= 0:
        if position_pct >= 80:
            is_high_position = True
            warnings.append(f'📍30日高位({position_pct:.0f}%)')
        elif position_pct < 40:
            reasons.append(f'📍低位({position_pct:.0f}%)')
        elif position_pct < 60:
            reasons.append(f'📍中位({position_pct:.0f}%)')
        # 近30日涨幅过大
        if change_30d > 20:
            warnings.append(f'⚠️30日涨{change_30d:+.0f}%')
    
    # ── 关③ Vibe评分（竞价简化版：量价+位置，非SMC/缠论）──
    vibe_sc, vibe_tags = vibe_score(s)
    vibe_str = f"+{vibe_sc}" if vibe_sc > 0 else str(vibe_sc)
    vibe_source = '竞价版'  # 标注来源：竞价版=量价+位置评分，盘中版=SMC+缠论+K线形态
    if vibe_sc >= 2:
        reasons.append(f'Vibe{vibe_str}[{vibe_source}]({" ".join(vibe_tags)})')
    elif vibe_sc >= 1:
        reasons.append(f'Vibe{vibe_str}[{vibe_source}]({" ".join(vibe_tags)})')
    
    # ── 关④ 板块风口（iFinD行业+东方财富排名+问财热度三数据源） ──
    sector = get_stock_sector(code)
    if sector and _sector_match(sector, top_sectors):
        reasons.append(f'🔥{sector}')
    # iFinD行业分类+板块共振（优先，精确匹配）
    try:
        import os as _os, sys as _sys
        _sys.path.insert(0, _os.path.expanduser('~/.hermes/scripts'))
        from ifind_sector_cache import match_hot_sector, get_stock_industry, get_sector_change_pct
        ind_info = get_stock_industry(code)
        ind_name = ind_info.get('name', name) if ind_info else name
        _is_ifind_hot, _ifind_sector = match_hot_sector(code, ind_name)
        if _is_ifind_hot and _ifind_sector != sector:
            reasons.append(f'🔥{_ifind_sector}')
        # 补充：显示所属行业板块涨幅
        sw_l1 = ind_info.get('sw_l1', '') if ind_info else ''
        ths_l1 = ind_info.get('ths_l1', '') if ind_info else ''
        for sname in [sw_l1, ths_l1]:
            if sname:
                chg = get_sector_change_pct(sname)
                if chg is not None:
                    reasons.append(f'{sname}{chg:+.1f}%')
                    break
    except Exception:
        pass
    # 问财板块共振补充（降级）
    if not any('🔥' in r for r in reasons):
        try:
            import os as _os, sys as _sys
            _sys.path.insert(0, _os.path.expanduser('~/.hermes/scripts'))
            from iwencai_sector import is_hot_sector
            _is_iwencai_hot, _iwencai_sector = is_hot_sector(code, name)
            if _is_iwencai_hot:
                reasons.append(f'🔥问财({_iwencai_sector})')
        except Exception:
            pass
    
    # ── 关⑤ 追高安全垫（竞价版） ──
    price_limit_pct = 20.0 if code.startswith('3') else 10.0
    hard_limit_pct = price_limit_pct * 0.95  # 创业板19% / 主板9.5%
    
    # 涨停一票否决（06-15修复：之前只降级观望，没真正排除）
    if abs(change_pct) >= hard_limit_pct:
        return '⛔观望', [f'⛔接近涨停{change_pct:+.1f}%一票否决'], [f'⛔接近涨停{change_pct:+.1f}%一票否决']
    
    # 追高安全垫（竞价版，区分策略）
    if strategy_name == 'preferred':
        # 优选策略：小幅高开(1-4%)，追高阈值更严
        chase_limit = 5 if not code.startswith('3') else 8
    else:
        # 激进策略：高开(4-7%)，追高阈值放宽
        chase_limit = 7 if not code.startswith('3') else 12
    
    if 'ST' in name.upper():
        chase_limit = 4
    
    if change_pct > chase_limit:
        if vibe_sc >= 2 and in_v10:
            warnings.append(f'⚡涨{change_pct:.1f}%超阈值但Vibe≥+2+V10交叉，追高豁免')
        else:
            warnings.append(f'⚠️涨{change_pct:.1f}%超阈值{chase_limit}%，追高风险')
    
    # ── 关⑥ 仓位提示（不拦截推荐，仅标注⚠️，仓位管理交给实盘盯盘） ──
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.expanduser('~/.hermes/scripts'))
        from current_holdings import get_holdings, get_portfolio_value, get_cash
        _h = get_holdings()
        _pv = get_portfolio_value()
        _cash_val = get_cash()
        _n_pos = len(_h)
        _total_pct = sum(h['shares'] * h['cost'] for h in _h) / _pv * 100 if _pv > 0 else 0
        _buy_amt = (s.get('price', 0) or 0) * 100  # 最小1手
        _new_pct = _buy_amt / _pv * 100 if _pv > 0 and _buy_amt > 0 else 0
        if _n_pos >= 2:
            warnings.append(f'⚠️已有{_n_pos}只持仓，注意仓位')
        elif _n_pos == 1 and _total_pct + _new_pct > 30:
            warnings.append(f'⚠️加仓后仓位将超30%')
        elif _new_pct > 20:
            warnings.append(f'⚠️单票仓位将超20%（{_new_pct:.1f}%）')
    except Exception:
        pass  # 读取持仓失败不阻塞竞价流程
    
    # ── 关⑥b 冷静期（连亏3次冷静2天） ──
    try:
        import json as _json, os as _os
        from datetime import datetime as _dt
        _tracker_path = _os.path.expanduser('~/.hermes/cache/tail_rec_tracker.json')
        if _os.path.exists(_tracker_path):
            with open(_tracker_path) as _f:
                _tracker = _json.load(_f)
            _streak_loss = _tracker.get('streak_loss', 0)
            _cooldown = _tracker.get('cooldown_until', '')
            if _cooldown:
                try:
                    _cd_time = _dt.strptime(_cooldown, '%Y-%m-%d')
                    if _dt.now() < _cd_time:
                        warnings.append(f'🧊冷静期中（连亏{_streak_loss}次，至{_cooldown}）')
                except ValueError:
                    pass
            if _streak_loss >= 3:
                warnings.append(f'🧊连亏{_streak_loss}次，触发冷静期')
    except Exception:
        pass  # 冷静期读取失败不阻塞
    
    # ── 量能确认 ──
    if amount_wan >= 10000:
        reasons.append(f'放量{amount_wan/10000:.1f}亿')
    elif amount_wan >= 5000:
        reasons.append(f'成交{amount_wan/10000:.1f}亿')
    
    # ── 增强因子（五因子：资金面+大盘+换手+内外盘+PE/PB） ──
    
    # 资金面：优先实时push2代理，降级到缓存
    _cf_inflow = None
    _cf_pct = None
    _cf_super_large = None
    _cf_large = None
    _cf_source = '缓存'
    try:
        from push2_proxy import fetch_capital_flow_realtime
        _cf_rt = fetch_capital_flow_realtime([code])
        if _cf_rt and code in _cf_rt:
            _cf_data = _cf_rt[code]
            _cf_inflow = _cf_data.get('main_net_inflow')
            _cf_pct = _cf_data.get('main_net_pct')
            _cf_super_large = _cf_data.get('super_large_net')
            _cf_large = _cf_data.get('large_net')
            _cf_source = '实时'
    except Exception:
        pass
    # 降级到缓存
    if _cf_inflow is None:
        try:
            import json as _json_cf
            cf_path = os.path.expanduser('~/.hermes/cache/capital_flow.json')
            if os.path.exists(cf_path):
                with open(cf_path) as _f:
                    _cf_all = _json_cf.load(_f)
                _cf_item = _cf_all.get(code)
                if _cf_item and isinstance(_cf_item, dict):
                    _cf_inflow = _cf_item.get('main_net_inflow', 0)
                    _cf_pct = _cf_item.get('main_net_pct')
                elif _cf_item and isinstance(_cf_item, (int, float)):
                    _cf_inflow = _cf_item
        except Exception:
            pass
    
    # 资金面否决 + 增强评分
    if isinstance(_cf_inflow, (int, float)) and _cf_inflow != 0:
        if _cf_inflow < -5000:
            # 主力净流出超5000万 → 直接降为⚠️观望（资金面否决）
            return '⚠️观望', reasons, warnings + [f'❌主力净流出{abs(_cf_inflow):.0f}万，资金面不支持({_cf_source})']
        elif _cf_inflow < -2000:
            # 主力净流出2000-5000万 → ★★☆降级
            warnings.append(f'⚠️主力净流出{abs(_cf_inflow):.0f}万({_cf_source})')
            if not in_v10:
                return '⚠️观望', reasons, warnings + [f'❌主力净流出{abs(_cf_inflow):.0f}万，非V10票资金面不支持']
        elif _cf_inflow > 3000:
            # 主力净流入超3000万 → 正面信号
            reasons.append(f'💰主力净流入{_cf_inflow:.0f}万({_cf_source})')
            # 超大单+大单同步流入 → 加分
            if isinstance(_cf_super_large, (int, float)) and _cf_super_large > 0 and isinstance(_cf_large, (int, float)) and _cf_large > 0:
                reasons.append(f'💰超大+大单双流入(超大{_cf_super_large:.0f}万+大{_cf_large:.0f}万)')
        # 主力占比显示
        if isinstance(_cf_pct, (int, float)) and _cf_pct != 0:
            if _cf_pct < -20:
                warnings.append(f'📉主力占比{_cf_pct:.1f}%')
            elif _cf_pct > 15:
                reasons.append(f'📈主力占比{_cf_pct:.1f}%')
    
    # 大盘环境
    try:
        import urllib.request as _urlb
        for _idx_code, _idx_prefix, _idx_name in [('000001', 'sh', '上证'), ('399001', 'sz', '深证')]:
            try:
                _url = f"https://qt.gtimg.cn/q={_idx_prefix}{_idx_code}"
                _resp = _urlb.urlopen(_url, timeout=3)
                _raw = _resp.read().decode('gbk', errors='ignore')
                if '=' in _raw and '~' in _raw:
                    _parts = _raw.split('=')[1].strip('"').split('~')
                    if len(_parts) > 32:
                        _idx_pct = float(_parts[32]) if _parts[32] else 0
                        if _idx_pct < -2.0:
                            if not in_v10:
                                return '⚠️观望', reasons, warnings + [f'❌{_idx_name}{_idx_pct:+.1f}%暴跌']
                            warnings.append(f'⚠️{_idx_name}{_idx_pct:+.1f}%弱市')
                        elif _idx_pct < -1.0:
                            warnings.append(f'⚠️{_idx_name}{_idx_pct:+.1f}%')
            except Exception:
                pass
    except Exception:
        pass
    
    # 换手率
    _turnover = s.get('turnover', 0)
    if _turnover > 15:
        warnings.append(f'⚠️换手率{_turnover:.1f}%偏高')
    
    # 内外盘比
    _outer = s.get('outer_vol', 0)
    _inner = s.get('inner_vol', 0)
    if _outer > 0 and _inner > 0:
        _oi = _outer / _inner
        if _oi > 1.5:
            reasons.append(f'📈外/内{_oi:.1f}x')
        elif _oi < 0.6:
            warnings.append(f'⚠️外/内{_oi:.1f}x卖方主导')
    
    # PE极端过滤
    _pe = s.get('pe_ttm', 0)
    if _pe != 0:
        if _pe < 0:
            warnings.append('⚠️PE为负(亏损)')
        elif _pe > 200:
            if not in_v10:
                return '⚠️观望', reasons, warnings + [f'❌PE={_pe:.0f}估值过高']
            warnings.append(f'⚠️PE={_pe:.0f}估值偏高')
    
    # ── 情绪面（iFinD新闻情绪，竞价信息维度） ──
    if sentiment_data and sentiment_data.get('news_count', 0) > 0:
        _sent_score = sentiment_data.get('score', 0)
        _sent_label = sentiment_data.get('label', '')
        _sent_news = sentiment_data.get('news_count', 0)
        if _sent_score >= 3:
            reasons.append(f'📰情绪利好({_sent_score:+d},{_sent_news}条)')
        elif _sent_score >= 1:
            reasons.append(f'📰情绪偏利好({_sent_score:+d})')
        elif _sent_score <= -3:
            warnings.append(f'📰情绪利空({_sent_score:+d},{_sent_news}条)')
        elif _sent_score <= -1:
            warnings.append(f'📰情绪偏利空({_sent_score:+d})')
    
    # ── 策略标签 ──
    strategy_map = {
        'preferred': '竞价优选',
        'aggressive': '竞价激进',
        'trend': '趋势共振',  # 兼容旧代码
        'youzi_v1': '游资爆量',
        'youzi_v2': '游资竞价',
    }
    reasons.append(strategy_map.get(strategy_name, strategy_name))
    
    # ── 综合评级（竞价核心：位置+量能+板块） ──
    # ★★★ 强推：低价位 + (V10交叉或Vibe≥2) + 板块共振 + 无追高警告
    # ★★☆ 可关注：低价位 + Vibe≥1 或 V10交叉 + 无涨停否决
    # ★☆☆ 一般：无硬伤但不满足上述条件
    # ⚠️观望：涨停否决/高位30日涨>20%/严重追高
    
    has_veto = any('⛔' in w for w in warnings)
    has_chase_warning = any('⚠️' in w and '⚡' not in w for w in warnings)
    has_high_pos_warning = any('📍30日高位' in w for w in warnings)
    
    if has_veto:
        stars = '⚠️观望'
    elif is_low_position is True and in_v10 and (sector and _sector_match(sector, top_sectors)) and not has_chase_warning:
        stars = '★★★'  # 低价位+V10+板块+无追高 = 最强信号
    elif is_low_position is True and vibe_sc >= 2 and not has_chase_warning and not has_high_pos_warning:
        stars = '★★★'  # 低价位+Vibe强+无追高 = 最强信号
    elif (is_low_position is True or is_low_position is None) and (in_v10 or vibe_sc >= 1) and not has_chase_warning:
        stars = '★★☆'  # 低价位/未知+信号确认+无追高
    elif is_high_position and has_chase_warning:
        stars = '⚠️观望'  # 高位+追高 = 观望
    elif has_chase_warning:
        stars = '★☆☆'  # 有追高警告但非高位
    elif is_high_position:
        stars = '★☆☆'  # 高位但无追高
    elif not has_chase_warning and strategy_name == 'preferred':
        stars = '★☆☆'  # 优选策略基础分
    else:
        stars = '★☆☆'  # 激进策略默认
    
    return stars, reasons, warnings


# ── 主逻辑 ──

def main():
    t0 = time.time()
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')
    print(f"📊 竞价选股 v7 | {date_str} {time_str}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    sys.stdout.flush()

    # 🛡️ 06-28 全局超时兜底：cron硬编码120s超时，脚本自己要在100s处提前收尾
    # 超过100s时输出已抓数据并退出，避免被cron杀掉导致247B超时日志
    GLOBAL_DEADLINE = 100

    def _overdue():
        return (time.time() - t0) > GLOBAL_DEADLINE

    def _remaining():
        return max(0, int(GLOBAL_DEADLINE - (time.time() - t0)))

    # 1. 统一行情获取 — 竞价/开盘初段QMT的change_pct全为0，必须强制用腾讯
    # 竞价09:28跑，QMT返回的现价=昨收价导致change_pct=0，所有高开票被漏掉
    # 修复：竞价脚本始终强制prefer_qmt=False，用腾讯数据源
    source_name = "腾讯(竞价专用)"
    print(f"\n🔄 [1/4] 行情获取 (数据源: {source_name})...", file=sys.stderr)
    raw_stocks = get_full_market_quotes(prefer_qmt=False)
    print(f"  → 原始数据 {len(raw_stocks)} 只", file=sys.stderr)

    # 规范化数据格式（兼容QMT/腾讯两种格式）
    all_stocks = _normalize_market_data(raw_stocks)

    # QMT模式下补充缺失字段（量比/流通市值/换手率/涨跌停价等）
    if raw_stocks:
        sample = next(iter(raw_stocks.values()))
        is_qmt = sample.get('source', '').startswith('qmt')
        if is_qmt:
            _supplement_qmt_fields(all_stocks)

    print(f"  → {len(all_stocks)} 只有效股票 (排除688/北交所)", file=sys.stderr)
    if len(all_stocks) < 100:
        print("⚠️ 数据不足，可能非交易时段")
        return

    # 2. 板块热度
    print(f"\n🔄 [2/4] 东方财富板块热度获取...", file=sys.stderr)
    sector_heat = fetch_sector_rank()
    top_sectors = set(sector_heat.keys())
    print(f"  → {len(sector_heat)} 个行业板块", file=sys.stderr)

    # 3. V10交叉信号
    print(f"\n🔄 [3/4] V10交叉标记读取...", file=sys.stderr)
    v10_codes = load_v10_signals()
    if v10_codes:
        print(f"  → {len(v10_codes)} 只V10信号股", file=sys.stderr)
    else:
        print(f"  → 未找到V10昨日信号", file=sys.stderr)

    # 4. 第一轮筛选（宽松门槛）
    print(f"\n🔄 [4/6] 双轨筛选：第一轮（初步快筛）...", file=sys.stderr)
    
    # 先用宽松条件圈候选池（量比硬门槛降低，涨幅放宽到1-7%覆盖优选+激进）
    candidates_pool = []
    for code, s in all_stocks.items():
        if exclude_st(s['name']):
            continue
        if s['circulation'] >= 200 or s['circulation'] <= 0:
            continue
        if not (1 <= s['change_pct'] <= 7):
            continue
        # 腾讯/QMT端只保留量比>1.0的即可（竞价阶段量比偏低，放宽到>1.0）
        if s['vol_ratio'] <= 1.0:
            continue
        # 竞价成交额>300万（从1500万放宽到300万，竞价阶段量本就少）
        if s['amount_wan'] <= 300:
            continue
        candidates_pool.append(s)
    print(f"  → 快筛候选池: {len(candidates_pool)}只", file=sys.stderr)
    
    # 候选池封顶：按成交额降序取top150，防止盘中350+只候选拖垮K线/板块批量获取
    MAX_CANDIDATES = 150
    if len(candidates_pool) > MAX_CANDIDATES:
        candidates_pool.sort(key=lambda s: s.get('amount_wan', 0), reverse=True)
        candidates_pool = candidates_pool[:MAX_CANDIDATES]
        print(f"  → 封顶{MAX_CANDIDATES}只（按成交额降序）", file=sys.stderr)
    
    # 5. 东方财富真实量比修正
    candidate_codes = [s['code'] for s in candidates_pool]
    print(f"\n🔄 [5/6] 双轨筛选：东方财富量比修正...", file=sys.stderr)
    em_vol = fetch_eastmoney_vol_ratio(candidate_codes) if candidate_codes else {}
    print(f"  → 修正 {len(em_vol)} 只", file=sys.stderr)
    
<<<<<<< Updated upstream
    # 用东方财富真实量比 + 涨跌幅覆盖（竞价阶段腾讯change_pct=0，push2才是实时）
    em_overrides = 0
=======
    # 用东方财富真实量比覆盖（竞价时段东方财富量比可能为0/空，不能覆盖腾讯有效值）
>>>>>>> Stashed changes
    for code, em_data in em_vol.items():
        if code in all_stocks:
            em_vr = em_data.get('vol_ratio', 0)
            # 只在东方财富返回有效量比(>0)时覆盖，避免竞价时段0值覆盖腾讯有效量比
            if em_vr > 0:
                all_stocks[code]['vol_ratio'] = em_vr
            if em_data.get('amount_from_em') and em_data['amount_from_em'] > 0:
                all_stocks[code]['amount_wan'] = em_data['amount_from_em'] / 10000
                all_stocks[code]['amount_yuan'] = em_data['amount_from_em']
            # 竞价阶段腾讯change_pct不可靠，用push2的f3覆盖
            if em_data.get('change_from_em') is not None:
                all_stocks[code]['change_pct'] = em_data['change_from_em']
                em_overrides += 1
    for s in candidates_pool:
        if s['code'] in em_vol:
<<<<<<< Updated upstream
            s['vol_ratio'] = em_vol[s['code']]['vol_ratio']
            if em_vol[s['code']].get('change_from_em') is not None:
                s['change_pct'] = em_vol[s['code']]['change_from_em']
    if em_overrides:
        print(f"  → push2覆盖{em_overrides}只涨跌幅 (竞价实时修正)", file=sys.stderr)
=======
            em_vr = em_vol[s['code']].get('vol_ratio', 0)
            # 同理：只覆盖有效量比
            if em_vr > 0:
                s['vol_ratio'] = em_vr
>>>>>>> Stashed changes

    # 5.5 板块归属（并发获取，策略需要用）
    t_sector = time.time()
    sector_budget = min(25, _remaining() - 5)  # 🛡️ 06-28 动态预算，留5s给K线和后续步骤
    sector_map = get_stock_sectors_batch(candidate_codes, max_workers=16) if sector_budget > 5 else {}
    print(f"  → 板块归属: {len(sector_map)}只, 耗时{time.time()-t_sector:.1f}s", file=sys.stderr)

    # 5.6 K线位置计算（对候选池拉30日K线）
    print(f"\n🔄 [5.5/6] K线位置计算（{len(candidate_codes)}只候选票）...", file=sys.stderr)
    if _overdue():
        print(f"  ⚠️ 全局超时({GLOBAL_DEADLINE}s)已到，跳过K线拉取", file=sys.stderr)
        positions = {}
    else:
        positions = _fetch_klines_batch(candidate_codes, count=30)
    print(f"  → 位置数据: {len(positions)}只", file=sys.stderr)

    # 6. 两策略正式筛选（用东方财富修正后的数据 + 位置 + 板块）
    print(f"\n🔄 [6/6] 两策略正式筛选...", file=sys.stderr)
    pref = strategy_preferred(all_stocks, positions, top_sectors, sector_map)
    aggr = strategy_aggressive(all_stocks, positions, top_sectors, sector_map)

    # 去重合并
    selected = {}
    for s in pref + aggr:
        selected[s['code']] = s

    # Vibe评分
    vibes = {code: vibe_score(s) for code, s in selected.items()}

    print(f"  优选:{len(pref)} 激进:{len(aggr)} → 合并{len(selected)}只", file=sys.stderr)

    # ── 提前计算买入推荐评级（供顶部汇总使用）──
    all_selected_for_rating = list(selected.values())
    rated = []
    for s in all_selected_for_rating:
        s_strategies = []
        if s in pref: s_strategies.append('preferred')
        if s in aggr: s_strategies.append('aggressive')
        strategy_key = s_strategies[0] if s_strategies else 'preferred'
        # positions 已就绪，sentiment 待获取（buy_recommendation 可选接入）
        stars, reasons, warnings = buy_recommendation(s, v10_codes, sector_heat, top_sectors, strategy_key, positions, sentiment_data=None)
        rated.append((s, stars, reasons, warnings))
    star_order = {'★★★': 0, '★★☆': 1, '★☆☆': 2, '⚠️观望': 3}
    rated.sort(key=lambda x: star_order.get(x[1], 9))
    top_picks_prelim = [r for r in rated if r[1] in ('★★★', '★★☆')]

    # 6.5 情绪面预获取（iFinD新闻情绪，仅对选中股票批量获取）
    sentiment_cache = {}
    if selected:
        print(f"\n🔄 [6.5/6] 情绪面获取（{len(selected)}只）...", file=sys.stderr)
        try:
            from ifind_news_sentiment import get_stock_sentiment
            for code, s in selected.items():
                try:
                    _sent = get_stock_sentiment(code, s['name'], size=5)
                    if _sent and _sent['news_count'] > 0:
                        sentiment_cache[code] = _sent
                        print(f"  {s['name']}({code}): {_sent['label']}({_sent['score']:+d},{_sent['news_count']}条)", file=sys.stderr)
                except Exception:
                    pass
            print(f"  → 情绪面获取完成: {len(sentiment_cache)}/{len(selected)}只有新闻数据", file=sys.stderr)
        except ImportError:
            print(f"  → ifind_news_sentiment模块不可用，跳过情绪面", file=sys.stderr)
        except Exception as e:
            print(f"  → 情绪面获取异常: {str(e)[:50]}", file=sys.stderr)

    # ── 输出报告 ──
    report = []
    def p(line=""):
        report.append(line)
        print(line)

    p(f"📅 **竞价选股报告** | {date_str} {time_str}")
    p(f"> 核心逻辑：位置+高开幅度+量能+板块 → 优选小幅高开+放量+低位+板块共振")
    p()

    # 今日板块热度
    if sector_heat:
        top5 = sorted(sector_heat.items(), key=lambda x: x[1] or 0, reverse=True)[:5]
        heat_str = " | ".join([f"{name}+{v:.1f}%" if v else name for name, v in top5])
        p(f"📊 **今日热点板块TOP5**: {heat_str}")
        p()

    # ── 🚨🚨🚨 可买入 🚨🚨🚨 (顶部醒目汇总) ──
    if top_picks_prelim:
        p()
        p("━━━ **🚨🚨🚨 可买入 🚨🚨🚨** ━━━")
        for s, stars, reasons, warnings in top_picks_prelim:
            pos = positions.get(s['code'], {})
            pos_str = f" 位{pos.get('position_pct', '?')}%" if pos else ""
            in_v10_tag = " 📌V10" if s['code'] in v10_codes else ""
            strategy_tag = ""
            if s in pref: strategy_tag = "优选"
            if s in aggr: strategy_tag = "激进"
            reason_1line = ' | '.join(reasons[:2]) if reasons else ''
            p(f"  {stars} **{s['code']} {s['name']}** +{s['change_pct']:.1f}% 量{s['vol_ratio']:.1f} 成{s['amount_wan']/10000:.1f}亿{pos_str}{in_v10_tag} [{strategy_tag}]")
            if reason_1line:
                p(f"    理由: {reason_1line}")
            if warnings:
                p(f"    ⚠️ {' '.join(warnings)}")
        p()
    else:
        p()
        p("━━━ **🚨🚨🚨 可买入 🚨🚨🚨** ━━━")
        p("  今日暂无★★★/★★☆推荐标的")
        p()

    # ── 竞价优选 ──
    p(f"━━━ **🟢 竞价优选** ({len(pref)}只) — 小幅高开+放量+低位+板块共振 ━━━")
    if pref:
        for s in pref:
            sector = sector_map.get(s['code'], '')
            in_v10 = "📌 V10" if s['code'] in v10_codes else ""
            sc, tags = vibes.get(s['code'], (0, []))
            tag_str = f" | {' '.join(tags)}" if tags else ""
            limit_tag = f" 涨停{s['limit_up']:.2f}/跌停{s['limit_down']:.2f}" if s.get('limit_up') else ""
            stars, reasons, warnings = buy_recommendation(s, v10_codes, sector_heat, top_sectors, 'preferred', positions, sentiment_data=sentiment_cache.get(s['code']))
            reason_str = ' | '.join(reasons)
            pos = positions.get(s['code'], {})
            pos_str = f" 位{pos.get('position_pct', '?')}%" if pos else ""
            p(f"  {stars} **{s['code']} {s['name']}** +{s['change_pct']:.1f}%{limit_tag} 量{s['vol_ratio']:.1f} 成{s['amount_wan']/10000:.1f}亿{pos_str}")
            p(f"    {reason_str}{tag_str} {in_v10}")
            if warnings:
                p(f"    {' '.join(warnings)}")
    else:
        p("  — 无符合条件标的")
    p()

    # ── 竞价激进 ──
    p(f"━━━ **🔴 竞价激进** ({len(aggr)}只) — 高开高打+爆量+游资风格 ━━━")
    if aggr:
        for s in aggr:
            sector = sector_map.get(s['code'], '')
            in_v10 = "📌 V10" if s['code'] in v10_codes else ""
            sc, tags = vibes.get(s['code'], (0, []))
            tag_str = f" | {' '.join(tags)}" if tags else ""
            limit_tag = f" 涨停{s['limit_up']:.2f}/跌停{s['limit_down']:.2f}" if s.get('limit_up') else ""
            stars, reasons, warnings = buy_recommendation(s, v10_codes, sector_heat, top_sectors, 'aggressive', positions, sentiment_data=sentiment_cache.get(s['code']))
            reason_str = ' | '.join(reasons)
            pos = positions.get(s['code'], {})
            pos_str = f" 位{pos.get('position_pct', '?')}%" if pos else ""
            p(f"  {stars} **{s['code']} {s['name']}** +{s['change_pct']:.1f}%{limit_tag} 量{s['vol_ratio']:.1f} 成{s['amount_wan']/10000:.1f}亿{pos_str}")
            p(f"    {reason_str}{tag_str} {in_v10}")
            if warnings:
                p(f"    {' '.join(warnings)}")
    else:
        p("  — 无符合条件标的")
    p()

    # ── V10交叉重点 ──
    cross = [s for s in selected.values() if s['code'] in v10_codes]
    if cross:
        p(f"━━━ **📌 V10交叉印证** ({len(cross)}只) ━━━")
        for s in cross:
            sector = sector_map.get(s['code'], '')
            sc, tags = vibes.get(s['code'], (0, []))
            tag_str = f" | {' '.join(tags)}" if tags else ""
            # 标记所在策略
            strategies = []
            if s in pref: strategies.append("竞价优选")
            if s in aggr: strategies.append("竞价激进")
            limit_tag = f" 涨停{s['limit_up']:.2f}/跌停{s['limit_down']:.2f}" if s.get('limit_up') else ""
            # 用第一个策略做评级
            primary_strategy = strategies[0] if strategies else 'preferred'
            strategy_key = {'竞价优选': 'preferred', '竞价激进': 'aggressive'}.get(primary_strategy, 'preferred')
            stars, reasons, warnings = buy_recommendation(s, v10_codes, sector_heat, top_sectors, strategy_key, positions, sentiment_data=sentiment_cache.get(s['code']))
            reason_str = ' | '.join(reasons)
            pos = positions.get(s['code'], {})
            pos_str = f" 位{pos.get('position_pct', '?')}%" if pos else ""
            p(f"  {stars} **{s['code']} {s['name']}** {'+'.join(strategies)}")
            p(f"    +{s['change_pct']:.1f}%{limit_tag} 量{s['vol_ratio']:.1f} 成{s['amount_wan']/10000:.1f}亿{pos_str} | {reason_str}{tag_str}")
            if warnings:
                p(f"    {' '.join(warnings)}")
        p()
    
    # ── 买入推荐详情（复用顶部已计算的 rated，补充情绪面）──
    # 用情绪面重新计算一次 rated（sentiment 在顶部评级之后才获取）
    all_selected = list(selected.values())
    rated = []
    for s in all_selected:
        s_strategies = []
        if s in pref: s_strategies.append('preferred')
        if s in aggr: s_strategies.append('aggressive')
        strategy_key = s_strategies[0] if s_strategies else 'preferred'
        stars, reasons, warnings = buy_recommendation(s, v10_codes, sector_heat, top_sectors, strategy_key, positions, sentiment_data=sentiment_cache.get(s['code']))
        rated.append((s, stars, reasons, warnings))
    star_order = {'★★★': 0, '★★☆': 1, '★☆☆': 2, '⚠️观望': 3}
    rated.sort(key=lambda x: star_order.get(x[1], 9))
    top_picks = [r for r in rated if r[1] in ('★★★', '★★☆')]

    if top_picks:
        p(f"━━━ **🎯 买入推荐** ({len(top_picks)}只) ━━━")
        for s, stars, reasons, warnings in top_picks:
            reason_str = ' | '.join(reasons)
            warn_str = ' '.join(warnings) if warnings else ''
            pos = positions.get(s['code'], {})
            pos_str = f" 位{pos.get('position_pct', '?')}%" if pos else ""
            p(f"  {stars} **{s['code']} {s['name']}** +{s['change_pct']:.1f}% 量{s['vol_ratio']:.1f} 成{s['amount_wan']/10000:.1f}亿{pos_str}")
            p(f"    {reason_str}")
            if warn_str:
                p(f"    {warn_str}")
            # 情绪面新闻标题（仅推荐票展示）
            _sent = sentiment_cache.get(s['code'])
            if _sent and _sent.get('news_count', 0) > 0:
                for _title in _sent.get('top_news', [])[:2]:
                    p(f"    📰 {_title}")
        p()
        p("💡 优选信号：小幅高开+放量+低位+板块共振 → 开盘后择机介入")
        p("💡 激进信号：高开高打+爆量 → 需盯盘确认，不符合则放弃")
    else:
        p("━━━ **🎯 买入推荐** ━━━")
        p("  今日无★★★/★★☆推荐，★☆☆及⚠️观望见上方各策略详情")
        p()

    # ── 统计 ──
    p(f"━━━ 📊 统计 ━━━")
    data_source = source_name if raw_stocks else "无数据"
    p(f"数据源: {data_source} | 全市场扫描: {len(all_stocks)}只 | 板块热点: {len(sector_heat)}个 | K线位置: {len(positions)}只")
    p(f"选股结果: 优选{len(pref)} 激进:{len(aggr)} | V10交叉: {len(cross)}只")
    p(f"情绪面: {len(sentiment_cache)}/{len(selected)}只有新闻数据 | ⏱ 耗时: {time.time()-t0:.1f}秒")

    # ── 保存结果供V10尾盘做双线印证 ──
    output = {
        'fetch_time': date_str + ' ' + time_str,
        'data_source': data_source,
        'strategy_preferred': [s['code'] for s in pref],
        'strategy_aggressive': [s['code'] for s in aggr],
        'selected': [s['code'] for s in selected.values()],
        'v10_cross': [s['code'] for s in cross],
        'sector_heat': sector_heat,
        'positions': {code: pos for code, pos in positions.items()},
        'stocks': {code: {'name': s['name'], 'price': s['price'], 'prev_close': s['prev_close'],
                          'change_pct': s['change_pct'], 'limit_up': s.get('limit_up', 0),
                          'limit_down': s.get('limit_down', 0)}
                   for code, s in selected.items()},
        'sentiment': {code: {'score': _s['score'], 'label': _s['label'], 'news_count': _s['news_count'],
                              'top_news': _s.get('top_news', [])[:2], 'summary': _s.get('summary', '')}
                      for code, _s in sentiment_cache.items()},
    }
    out_path = '/tmp/auction_v7_result.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存 → {out_path}", file=sys.stderr)

if __name__ == '__main__':
    main()
