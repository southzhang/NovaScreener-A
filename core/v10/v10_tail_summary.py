#!/usr/bin/env python3
"""
V10 尾盘信号摘要 v4 (14:30)
直接从全扫描的watchlist里读信号 + 实时行情确认 + 七关验证 + iFinD补充评分
输出经过完整验证的推荐，不再是"有信号就全推"

v4新增(06-22):
- iFinD补充评分：财务质量+机构持仓+估值评估+异动风险
- 从config.yaml读取iFinD token，通过HTTP API获取数据
- 推荐输出中展示iFinD基本面评级标签

关键修正(06-13):
- watchlist中signal格式为文本(全买入/强庄买/基础买)，不是★★★格式
- 七关验证完整：V10信号+实时数据+Vibe+追高安全垫+涨停否决+仓位+冷静期+止损空间
- 数据时效降级机制(30-120min降级,>120min拒绝)
- 追高安全垫结合Vibe感知
"""
import json, os, sys, urllib.request, re, time
from datetime import datetime
import yaml  # for reading config

WATCHLIST = os.path.expanduser("~/.hermes/cache/v10_watchlist.json")
TRACKER = os.path.expanduser("~/.hermes/cache/tail_rec_tracker.json")
HOLDINGS_SCRIPT = os.path.expanduser("~/.hermes/scripts/current_holdings.py")
CAPITAL_FLOW_CACHE = os.path.expanduser("~/.hermes/cache/capital_flow.json")
IFIND_CACHE = os.path.expanduser("~/.hermes/cache/ifind_scoring_cache.json")

def get_market_index():
    """获取大盘指数（上证+深证），用于④关量化判断"""
    indices = {}
    for code, prefix, name in [('000001', 'sh', '上证'), ('399001', 'sz', '深证')]:
        try:
            url = f"https://qt.gtimg.cn/q={prefix}{code}"
            resp = urllib.request.urlopen(url, timeout=5)
            raw = resp.read().decode('gbk', errors='ignore')
            if '=' in raw and '~' in raw:
                parts = raw.split('=')[1].strip('"').split('~')
                if len(parts) > 32:
                    indices[name] = {
                        'change_pct': float(parts[32]) if parts[32] else 0,
                        'amount': float(parts[37]) if len(parts) > 37 and parts[37] else 0,
                    }
        except Exception:
            pass
    return indices

def log(msg):
    print(msg, flush=True)

def get_realtime(code):
    """腾讯实时行情（纯腾讯API，不使用QMT）"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        raw = resp.read().decode('gbk', errors='ignore')
        if '=' not in raw or '~' not in raw:
            return None
        parts = raw.split('=')[1].strip('"').split('~')
        if len(parts) < 40:
            return None
        return {
            'code': parts[2] if len(parts) > 2 else '',
            'price': float(parts[3]) if parts[3] else 0,
            'change_pct': float(parts[32]) if parts[32] else 0,
            'amount': float(parts[37]) if parts[37] else 0,
            'volume': float(parts[6]) if parts[6] else 0,
            'high': float(parts[33]) if parts[33] else 0,
            'low': float(parts[34]) if parts[34] else 0,
            'open': float(parts[5]) if parts[5] else 0,
            'yclose': float(parts[4]) if parts[4] else 0,
            'turnover': float(parts[38]) if len(parts) > 38 and parts[38] else 0,
            'pe_ttm': float(parts[39]) if len(parts) > 39 and parts[39] else 0,
            'amplitude': float(parts[43]) if len(parts) > 43 and parts[43] else 0,
            'circ_cap': float(parts[44]) if len(parts) > 44 and parts[44] else 0,
            'pb': float(parts[46]) if len(parts) > 46 and parts[46] else 0,
            'limit_up': float(parts[47]) if len(parts) > 47 and parts[47] else 0,
            'limit_down': float(parts[48]) if len(parts) > 48 and parts[48] else 0,
            'vol_ratio': float(parts[49]) if len(parts) > 49 and parts[49] else 0,
            'outer_vol': float(parts[7]) if len(parts) > 7 and parts[7] else 0,
            'inner_vol': float(parts[8]) if len(parts) > 8 and parts[8] else 0,
        }
    except:
        return None

# ============ iFinD 补充评分模块 ============
IFIND_TOKEN = None
IFIND_BASE_URL = "https://api-mcp.51ifind.com:8643/ds-mcp-servers"

<<<<<<< Updated upstream
def load_watchlist():
    """加载watchlist缓存，检查时效性"""
=======
def _load_ifind_token():
    global IFIND_TOKEN
    if IFIND_TOKEN:
        return IFIND_TOKEN
    try:
        config_path = os.path.expanduser("~/.hermes/config.yaml")
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
        # iFinD所有服务共享同一个token，从ifind-stock读
        if cfg and 'mcp_servers' in cfg and 'ifind-stock' in cfg['mcp_servers']:
            h = cfg['mcp_servers']['ifind-stock'].get('headers', {})
            IFIND_TOKEN = h.get('Authorization', '')
    except Exception:
        IFIND_TOKEN = ''
    return IFIND_TOKEN or ''

def _ifind_call(service, method, args, timeout=30):
    """通过HTTP调用iFinD MCP工具的通用函数"""
    token = _load_ifind_token()
    if not token:
        return None
    services = {
        'stock': 'hexin-ifind-ds-stock-mcp',
        'index': 'hexin-ifind-ds-index-mcp',
        'news': 'hexin-ifind-ds-news-mcp',
    }
    path = services.get(service)
    if not path:
        return None
    url = f"{IFIND_BASE_URL}/{path}"
    payload = {
        'jsonrpc': '2.0', 'id': int(time.time() % 10000),
        'method': 'tools/call',
        'params': {'name': method, 'arguments': args}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': token,
            'Content-Type': 'application/json'
        },
        method='POST'
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode('utf-8'))
        content = data.get('result', {}).get('content', [])
        if content:
            text = content[0].get('text', '') if isinstance(content, list) else ''
            if text:
                parsed = json.loads(text)
                return parsed
        return None
    except Exception as e:
        log(f"⚠️ iFinD API失败({service}.{method}): {str(e)[:80]}")
        return None

def _parse_financial_from_ifind(raw):
    """从iFinD财务数据中提取关键指标
    表格格式: |代码|名称|日期|ROE加权|ROE扣摊|ROE摊含|ROE_TTM|净利同比|净利润|ROE平均含|ROE扣加|销售净利率|...
    索引:                         3       4       5       6       7       8     9         10      11       12
    """
    result = {}
    if not raw:
        return result
    answer = raw.get('data', {}).get('answer', '') if isinstance(raw, dict) else ''
    if not answer:
        return result
    
    # 表格行：|600584.SH|长电科技|20251231|5.56|4.7765|5.0184|5.2832|-2.7546|...
    for line in answer.split('\n'):
        if line.count('|') >= 12 and '|' in line:
            cols = [c.strip() for c in line.split('|')]
            if len(cols) >= 12 and (cols[1].startswith('6') or cols[1].startswith('3') or cols[1].startswith('0')):
                try:
                    if cols[11] and cols[11].replace('.','').replace('-','').isdigit():
                        result['net_profit_margin'] = float(cols[11])
                    if cols[4] and cols[4].replace('.','').replace('-','').isdigit():
                        result['roe'] = float(cols[4])
                    if cols[8] and cols[8].replace('.','').replace('-','').isdigit():
                        result['profit_growth'] = float(cols[8])
                except (ValueError, IndexError):
                    pass
    
    # 如果表格解析失败，fallback到文本搜索
    if not result:
        m = re.search(r'销售净利率.*?([\d.+-]+)', answer)
        if m: result['net_profit_margin'] = float(m.group(1))
        m = re.search(r'净资产收益率ROE\(加权.*?\)（单位：%）.*?([\d.+-]+)', answer)
        if m: result['roe'] = float(m.group(1))
        m = re.search(r'归属母公司股东的净利润\(同比增长率\).*?（单位：%）.*?([\d.+-]+)', answer)
        if m: result['profit_growth'] = float(m.group(1))
    
    return result

def _parse_shareholder_from_ifind(raw):
    """从iFinD股东数据中提取关键指标
    表格格式: |代码|名称|流通占比|前十比例|前十数量|第1名名称|第1名数量|第1名比例|第1名股份性质|第1名股东性质|...
    索引:     1    2      3         4        5        6          7         8          9             10
    """
    result = {}
    if not raw:
        return result
    answer = raw.get('data', {}).get('answer', '') if isinstance(raw, dict) else ''
    if not answer:
        return result
    
    # 表格解析
    for line in answer.split('\n'):
        if '|' in line and line.count('|') >= 5:
            cols = [c.strip() for c in line.split('|')]
            if len(cols) >= 11:
                try:
                    # 流通占比 col[3]
                    if cols[3] and cols[3].replace('.','').isdigit():
                        result['float_ratio'] = float(cols[3])
                    # 前十大股东 col[4]
                    if cols[4] and cols[4].replace('.','').isdigit():
                        result['top10_ratio'] = float(cols[4])
                    # 大股东性质 col[10]
                    if cols[10]:
                        result['top1_nature'] = cols[10]
                except (ValueError, IndexError):
                    pass
    
    return result

def get_ifind_scoring(code, name=''):
    """获取iFinD补充评分 — 委托给独立模块ifind_scoring.py"""
    try:
        from ifind_scoring import combined_ifind_score
        return combined_ifind_score(code, name)
    except Exception as e:
        log(f"  ⚠️ iFinD评分失败: {str(e)[:60]}")
        return None

# ============ 尾盘选股主逻辑 ============

def load_cache():
>>>>>>> Stashed changes
    if not os.path.exists(WATCHLIST):
        return None
    with open(WATCHLIST) as f:
        return json.load(f)

def load_holdings():
    """读取持仓信息（直接import，避免subprocess开销和超时风险）"""
    try:
        from current_holdings import get_account_info
        return get_account_info()
    except Exception:
        # fallback: subprocess方式
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, HOLDINGS_SCRIPT],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except:
            pass
    return {'holdings': [], 'portfolio_value': 56000, 'cash': 56000}

def load_tracker():
    """读取推荐记录（冷静期检查）"""
    if not os.path.exists(TRACKER):
        return {'streak_loss': 0, 'cooldown_until': ''}
    try:
        with open(TRACKER) as f:
            return json.load(f)
    except:
        return {'streak_loss': 0, 'cooldown_until': ''}

def check_cooldown():
    """冷静期检查：连亏3次冷静2天"""
    tracker = load_tracker()
    streak_loss = tracker.get('streak_loss', 0)
    cooldown = tracker.get('cooldown_until', '')
    if cooldown:
        try:
            cd_time = datetime.strptime(cooldown, '%Y-%m-%d')
            # 冷静期到当天收盘(15:00)有效，加1天使得当天仍在冷静期内
            from datetime import timedelta
            cd_end = cd_time + timedelta(days=1)
            if datetime.now() < cd_end:
                return True, f'🧊 冷静期中（连亏{streak_loss}次，至{cooldown}），暂停推荐'
        except ValueError:
            pass
    if streak_loss >= 3:
        return True, f'🧊 连亏{streak_loss}次，触发冷静期'
    return False, ''

def check_position(portfolio_info, price):
    """仓位提示（不拦截推荐，仅标注⚠️，仓位管理交给实盘盯盘）"""
    holdings = portfolio_info.get('holdings', [])
    pv = portfolio_info.get('portfolio_value', 56000)
    cash = portfolio_info.get('cash', 56000)
    
    warnings = []
    if len(holdings) >= 2:
        warnings.append(f'⚠️ 已有{len(holdings)}只持仓，注意仓位')
    
    buy_amount = price * 100  # 最小1手
    new_pct = buy_amount / pv * 100
    
    if len(holdings) == 1:
        current_pct = sum(h['shares'] * h['cost'] for h in holdings) / pv * 100
        if current_pct + new_pct > 30:
            warnings.append(f'⚠️ 加仓后仓位将超30%')
    
    if new_pct > 20:
        warnings.append(f'⚠️ 单票仓位将超20%（{new_pct:.1f}%）')
    
    if cash < buy_amount:
        warnings.append(f'⚠️ 现金不足（¥{cash:.0f} < 1手¥{buy_amount:.0f}）')
    
    return True, ' '.join(warnings)  # 始终通过，返回提示

def signal_to_stars(signal):
    """V10信号文本→星级映射（watchlist存的是全买入/强庄买/基础买）"""
    if '全买入' in signal:
        return '★★★'
    elif '强庄买' in signal:
        return '★★☆'
    elif '基础买' in signal:
        return '★☆☆'
    return '⚪'

def seven_gates_check(stock, rt, portfolio_info, capital_flow=None, market_index=None, capital_flow_detail=None):
    """七关验证 — 尾盘版（v4 五因子增强：资金面+大盘+换手+内外盘+PE/PB）
    返回: (passed, reasons, warnings)
    passed=True表示通过所有关卡
    
    watchlist中signal格式为文本：全买入/强庄买/基础买
    """
    code = stock.get('code', '')
    name = stock.get('name', '')
    signal = stock.get('signal', '')
    price = rt.get('price', 0) if rt else 0
    change_pct = rt.get('change_pct', 0) if rt else 0
    limit_up = rt.get('limit_up', 0) if rt else 0
    limit_down = rt.get('limit_down', 0) if rt else 0
    yclose = rt.get('yclose', 0) if rt else 0
    
    reasons = []
    warnings = []
    stars = signal_to_stars(signal)
    
    if price <= 0 or yclose <= 0:
        return False, ['❌ 无有效行情数据'], []
    
    # ① V10信号（必须有）
    is_full_buy = '全买入' in signal
    is_strong_buy = '强庄买' in signal and not is_full_buy
    is_base_buy = '基础买' in signal and not is_strong_buy and not is_full_buy
    
    if is_full_buy:
        reasons.append(f'V10全买入★★★')
    elif is_strong_buy:
        reasons.append(f'V10强庄买★★☆')
    elif is_base_buy:
        warnings.append(f'V10仅基础买★☆☆，弱市需谨慎')
    else:
        return False, [f'❌ 无V10信号({signal})'], []
    
    # ② 实时数据有效性
    if rt.get('open', 0) == 0 and abs(price - yclose) < 0.01:
        return False, [f'❌ 数据可能过期（开=0,价≈昨收）'], []
    
    # ③ Vibe评分（从watchlist读取，已由全扫描计算）
    vibe_score = stock.get('vibe_score', 0)
    vibe_tags = stock.get('vibe_tags', [])
    
    # 兼容：如果vibe_score不是数字，从vibe_tags提取
    if not isinstance(vibe_score, (int, float)):
        vibe_score = 0
    if vibe_score == 0 and isinstance(vibe_tags, list) and len(vibe_tags) > 0:
        for tag in vibe_tags:
            ts = str(tag).strip()
            if ts.startswith('BOS'): vibe_score += 2
            elif ts.startswith('ChoCH'): vibe_score += 2
            elif ts.startswith('FVG'):
                m = re.search(r'([+-]?\d+)', ts)
                if m: vibe_score += int(m.group(1))
            elif ts in ('K线看多', '缠论二买', '缠论三买'): vibe_score += 1
    
    vibe_str = f'+{vibe_score}' if vibe_score > 0 else str(vibe_score)
    vibe_tags_str = ' '.join(str(t) for t in vibe_tags) if isinstance(vibe_tags, list) else str(vibe_tags)
    
    if vibe_score >= 2:
        reasons.append(f'Vibe{vibe_str}({vibe_tags_str})')
    elif vibe_score >= 1:
        reasons.append(f'Vibe{vibe_str}({vibe_tags_str})')
    elif vibe_score < 0:
        return False, [f'❌ Vibe{vibe_str}为负，不推荐'], []
    # vibe_score == 0: 中性，不加分不扣分
    
    # ⑤ 追高安全垫 + 涨停一票否决（结合Vibe感知）
    # 创业板20%涨跌幅，主板10%，ST 5%
    if code.startswith('3'):
        price_limit_pct = 20.0
    elif 'ST' in name.upper():
        price_limit_pct = 5.0
    else:
        price_limit_pct = 10.0
    hard_limit_pct = price_limit_pct * 0.95  # 涨停一票否决线
    
    # 涨停一票否决
    if change_pct >= hard_limit_pct:
        return False, [f'⛔ 接近涨停{change_pct:+.1f}%，一票否决'], []
    
    # 追高安全垫（Vibe≥+2强 + V10全买入/强庄买 → 追高豁免）
    is_strong_trend = vibe_score >= 2 and (is_full_buy or is_strong_buy)
    
    if code.startswith('3'):
        chase_limit = 15  # 创业板
    elif 'ST' in name.upper():
        chase_limit = 4   # ST
    else:
        chase_limit = 7   # 主板
    
    if change_pct > chase_limit:
        if is_strong_trend:
            warnings.append(f'⚡ 涨{change_pct:.1f}%超阈值但Vibe≥+2强趋势，追高豁免')
        else:
            return False, [f'❌ 今日已涨{change_pct:.1f}%，追高风险大（阈值{chase_limit}%）'], []
    
    # ⑤b 偏离EMA20检查（Vibe+1中时）
    levels = stock.get('key_levels', {})
    ema20 = levels.get('ema20', 0)
    ema7 = levels.get('ema7', 0)
    if ema20 > 0 and vibe_score <= 1 and change_pct > 0:
        deviation = (price - ema20) / ema20 * 100
        if deviation > 15:
            return False, [f'❌ 偏离EMA20达{deviation:.1f}%，Vibe仅{vibe_str}不豁免，等回调'], []

    # ⑤c 位置审查（回调到支撑才推，从源头解决追涨问题）
    # V10信号=趋势已走强，直接买=追涨。必须等回调到EMA7/EMA20支撑才推。
    # Vibe≥+2强趋势票豁免（强趋势可追）
    if not is_strong_trend and ema7 > 0 and ema20 > 0:
        dist_ema7 = abs(price - ema7) / ema7 * 100
        dist_ema20 = abs(price - ema20) / ema20 * 100
        # 回调到支撑：距EMA7≤3%或距EMA20≤5%
        at_support = dist_ema7 <= 3.0 or dist_ema20 <= 5.0
        # 远离支撑：距EMA7>8%且距EMA20>10%
        far_from_support = dist_ema7 > 8.0 and dist_ema20 > 10.0
        if far_from_support:
            return False, [f'❌ 位置过高：距EMA7 {dist_ema7:.1f}%/EMA20 {dist_ema20:.1f}%，远离支撑等回调'], []
        elif not at_support:
            warnings.append(f'⚠️ 位置偏高：距EMA7 {dist_ema7:.1f}%/EMA20 {dist_ema20:.1f}%')
        else:
            reasons.append(f'📍回调支撑(EMA7±{dist_ema7:.1f}%)')
    
    # ⑥ 仓位提示（不拦截，仅标注⚠️）
    pos_ok, pos_msg = check_position(portfolio_info, price)
    if pos_msg:
        reasons.append(pos_msg)  # 仓位提示加入reasons，不否决
    
    # ⑥b 冷静期
    cooldown, cd_msg = check_cooldown()
    if cooldown:
        return False, [cd_msg], []
    
    # ⑦ 止损空间≥8%（策略v2：从5%放宽到8%，配合分层止损体系）
    stop_loss = levels.get('stop_loss', 0)
    if stop_loss > 0:
        stop_pct = (price - stop_loss) / price * 100
        if stop_pct < 8:
            return False, [f'❌ 止损空间仅{stop_pct:.1f}%（¥{price:.2f}→¥{stop_loss:.2f}），不足8%'], []
        reasons.append(f'止损¥{stop_loss:.2f}({stop_pct:.1f}%)')
    elif ema20 > 0:
        ema_stop_pct = (price - ema20) / price * 100
        if ema_stop_pct < 8:
            return False, [f'❌ 距EMA20仅{ema_stop_pct:.1f}%，止损空间不足8%'], []
        reasons.append(f'EMA20止损{ema_stop_pct:.1f}%')
    
    # ── ④b 大盘环境量化（替代LLM主观判断） ──
    if market_index:
        sh_pct = market_index.get('上证', {}).get('change_pct', 0)
        sz_pct = market_index.get('深证', {}).get('change_pct', 0)
        max_drop = min(sh_pct, sz_pct)
        if max_drop < -2.0:
            if not is_full_buy:
                return False, [f'❌ 大盘暴跌（上证{sh_pct:+.1f}%/深证{sz_pct:+.1f}%），弱市只推★★★'], []
            warnings.append(f'⚠️ 大盘暴跌{max_drop:+.1f}%，仅★★★通过')
        elif max_drop < -1.0:
            if is_base_buy:
                return False, [f'❌ 大盘下跌{max_drop:+.1f}%，★☆☆不推'], []
            if is_strong_buy:
                return False, [f'❌ 大盘下跌{max_drop:+.1f}%，★★☆也不推（弱市收紧）'], []
            warnings.append(f'⚠️ 大盘下跌{max_drop:+.1f}%，仅★★★通过')
        elif max_drop < -0.5:
            if is_base_buy:
                return False, [f'❌ 大盘微跌{max_drop:+.1f}%，★☆☆不推'], []
            warnings.append(f'⚠️ 大盘偏弱{max_drop:+.1f}%，★★☆降级观察')
    
    # ── ④c 板块共振（iFinD行业+问财热度+板块资金流三数据源） ──
    sector_hot = False
    sector_name = ''
    # 优先：板块资金流向（跟资金走）
    try:
        sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
        from sector_capital_flow import get_stock_capital_sector
        stock_sector, sector_cf_inflow, sector_is_hot = get_stock_capital_sector(code)
        if stock_sector:
            sector_name = stock_sector
            if sector_cf_inflow > 0:
                reasons.append(f'💰板块资金流入{sector_cf_inflow:.0f}万({stock_sector})')
                sector_hot = True
            elif sector_cf_inflow < -3000:
                # 个股资金流出+板块资金流出 = 双杀
                warnings.append(f'⚠️板块资金流出{abs(sector_cf_inflow):.0f}万({stock_sector})')
    except Exception:
        pass
    # 次选：iFinD行业匹配
    try:
        sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
        from ifind_sector_cache import match_hot_sector, get_stock_industry
        ind_info = get_stock_industry(code)
        ind_name = ind_info.get('name', name) if ind_info else name
        if ind_name and not sector_name:
            sector_name = ind_name
        ind_hot, ind_hot_name = match_hot_sector(code, ind_name)
        if ind_hot:
            sector_hot = True
            if ind_hot_name and ind_hot_name != sector_name:
                reasons.append(f'🔥板块共振({ind_hot_name})')
    except Exception:
        pass
    # 降级：问财在线匹配
    if not sector_hot:
        try:
            sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
            from iwencai_sector import is_hot_sector
            sector_hot_iwc, sector_name_iwc = is_hot_sector(code, name)
            if sector_hot_iwc:
                sector_hot = True
                reasons.append(f'🔥板块共振({sector_name_iwc})')
        except Exception:
            pass
    
    # ── ③b 资金面否决（增强版：实时push2代理+超大单大单结构+主力占比） ──
    if capital_flow and isinstance(capital_flow, dict):
        cf_inflow = capital_flow.get('main_net_inflow', 0)
        # 增强因子：超大单+大单结构、主力占比
        cf_detail = capital_flow_detail.get(code, {}) if capital_flow_detail else {}
        cf_super_large = cf_detail.get('super_large_net') if isinstance(cf_detail, dict) else None
        cf_large = cf_detail.get('large_net') if isinstance(cf_detail, dict) else None
        cf_pct = cf_detail.get('main_net_pct') if isinstance(cf_detail, dict) else None
        cf_source = cf_detail.get('source', '缓存') if isinstance(cf_detail, dict) else '缓存'
        
        if isinstance(cf_inflow, (int, float)) and cf_inflow < -5000:
            # 主力净流出超5000万 → ★☆☆否决，★★☆降级，★★★警告
            if is_base_buy:
                return False, [f'❌ 主力净流出{abs(cf_inflow):.0f}万，资金面不支持({cf_source})'], []
            elif is_strong_buy:
                warnings.append(f'⚠️ 主力净流出{abs(cf_inflow):.0f}万，★★☆降级观察({cf_source})')
            else:  # 全买入
                warnings.append(f'⚠️ 主力净流出{abs(cf_inflow):.0f}万，注意资金面({cf_source})')
        elif isinstance(cf_inflow, (int, float)) and cf_inflow > 3000:
            reasons.append(f'💰主力净流入{cf_inflow:.0f}万({cf_source})')
            # 超大单+大单同步流入 → 加分
            if isinstance(cf_super_large, (int, float)) and cf_super_large > 0 and isinstance(cf_large, (int, float)) and cf_large > 0:
                reasons.append(f'💰超大+大单双流入(超大{cf_super_large:.0f}万+大{cf_large:.0f}万)')
        # 主力占比判断
        if isinstance(cf_pct, (int, float)) and cf_pct != 0:
            if cf_pct < -20:
                warnings.append(f'📉主力占比{cf_pct:.1f}%')
            elif cf_pct > 15:
                reasons.append(f'📈主力占比{cf_pct:.1f}%')
    
    # ── 换手率过滤 ──
    turnover_rate = rt.get('turnover', 0)  # 注意：腾讯字段38是换手率
    if turnover_rate > 0:
        if turnover_rate < 1.0:
            warnings.append(f'⚠️ 换手率{turnover_rate:.1f}%偏低，流动性差')
        elif turnover_rate > 15.0:
            warnings.append(f'⚠️ 换手率{turnover_rate:.1f}%偏高，可能见顶')
    
    # ── 内外盘比 ──
    outer_vol = rt.get('outer_vol', 0)
    inner_vol = rt.get('inner_vol', 0)
    if outer_vol > 0 and inner_vol > 0:
        vol_ratio_oi = outer_vol / inner_vol
        if vol_ratio_oi > 1.5:
            reasons.append(f'📈外/内盘{vol_ratio_oi:.1f}x买方主导')
        elif vol_ratio_oi < 0.6:
            warnings.append(f'⚠️ 外/内盘{vol_ratio_oi:.1f}x卖方主导')
    
    # ── PE/PB极端过滤 ──
    pe_ttm = rt.get('pe_ttm', 0)
    pb = rt.get('pb', 0)
    if pe_ttm != 0:
        if pe_ttm < 0:
            warnings.append(f'⚠️ PE为负(亏损)')
        elif pe_ttm > 200:
            if is_base_buy:
                return False, [f'❌ PE={pe_ttm:.0f}估值过高，★☆☆不推'], []
            warnings.append(f'⚠️ PE={pe_ttm:.0f}估值偏高')
    if pb != 0 and pb > 20:
        warnings.append(f'⚠️ PB={pb:.1f}偏高')

    # ── 龙头筛选标注（板块内相对强度，不拦截） ──
    # 龙头=板块内涨幅+成交额排名前30%，不是看绝对市值
    circ_cap = rt.get('circ_cap', 0)  # 流通市值（亿）
    amount_wan = rt.get('amount', 0)  # 成交额（万）
    is_dragon = False

    # 板块内强度判断（需要板块涨幅数据）
    try:
        from sector_capital_flow import get_sector_capital_flow
        sectors_data = get_sector_capital_flow()
        if sectors_data and sector_name:
            # 找该板块在资金流排名中的位置
            sector_rank = None
            sector_change = None
            for i, s in enumerate(sectors_data):
                if s['name'] == sector_name or sector_name in s['name'] or s['name'] in sector_name:
                    sector_rank = i + 1
                    sector_change = s.get('change_pct', 0)
                    break
            if sector_rank and sector_rank <= 5:
                reasons.append(f'🐲板块龙头({sector_name}排名第{sector_rank}/30,涨{sector_change:+.1f}%)')
                is_dragon = True
            elif sector_rank and sector_rank <= 15:
                reasons.append(f'板块偏强({sector_name}第{sector_rank}/30)')
    except Exception:
        pass

    # 市值/成交额标注
    if circ_cap > 0:
        if circ_cap >= 100:
            reasons.append(f'大盘股(流通{circ_cap:.0f}亿)')
        elif circ_cap < 20:
            warnings.append(f'⚠️小盘股(流通{circ_cap:.1f}亿)')
    if amount_wan > 0:
        if amount_wan < 3000:
            warnings.append(f'⚠️成交额仅{amount_wan:.0f}万，流动性不足')
        elif amount_wan > 50000:
            reasons.append(f'💰成交额{amount_wan/10000:.1f}亿活跃')

    return True, reasons, warnings


# ---- MAIN ----
# 数据时效：30-120分钟降级使用，>120分钟拒绝
MAX_AGE_HARD = 120  # 硬过期120分钟
MAX_AGE_WARN = 30   # 30分钟以上降级标记

data = load_cache()
if not data:
    log("❌ 未找到全扫描缓存 (v10_watchlist.json)，请先执行全扫描")
    sys.exit(0)

stocks = data.get('stocks', [])
scan_time = data.get('scan_time', '未知')

# 数据时效校验（降级机制）
is_stale = False
if scan_time and scan_time != '未知':
    try:
        st = datetime.strptime(scan_time, "%Y-%m-%d %H:%M:%S")
        age_minutes = (datetime.now() - st).total_seconds() / 60
        if age_minutes > MAX_AGE_HARD:
            log(f"❌ 数据严重过期！scan_time={scan_time}，距今{age_minutes:.0f}分钟（超过{MAX_AGE_HARD}分钟红线）")
            log(f"❌ 拒绝使用严重过期数据做推荐！")
            sys.exit(1)
        elif age_minutes > MAX_AGE_WARN:
            is_stale = True
            log(f"⚠️ 数据{age_minutes:.0f}分钟前（{scan_time}），降级使用")
        else:
            log(f"✅ 数据新鲜度OK: scan_time={scan_time}，距今{age_minutes:.0f}分钟")
    except ValueError:
        log(f"⚠️ 无法解析scan_time: {scan_time}，继续但风险自负")
        is_stale = True
else:
    log(f"⚠️ scan_time为空或未知，无法校验数据新鲜度！")
    is_stale = True

# 加载持仓
portfolio_info = load_holdings()
n_holdings = len(portfolio_info.get('holdings', []))

# 加载资金面：优先实时push2代理，降级到缓存
capital_flow = {}
capital_flow_detail = {}  # 保留完整资金面数据用于增强评分
try:
    from push2_proxy import fetch_capital_flow_realtime
    # 收集所有候选票的代码
    _cf_codes = list(set([c.get('code', '') for c in stocks if c.get('code')]))
    if _cf_codes:
        _cf_rt = fetch_capital_flow_realtime(_cf_codes)
        if _cf_rt:
            for code, d in _cf_rt.items():
                capital_flow[code] = d.get('main_net_inflow', 0)
                capital_flow_detail[code] = d
            log(f"✅ 资金面: 实时push2代理获取{len(capital_flow)}只")
except Exception as e:
    log(f"⚠️ 实时资金面获取失败({e})，降级到缓存")
# 降级：从缓存补充
if len(capital_flow) < len(stocks) * 0.5:
    try:
        if os.path.exists(CAPITAL_FLOW_CACHE):
            with open(CAPITAL_FLOW_CACHE, 'r', encoding='utf-8') as f:
                cf_data = json.load(f)
            for code, val in cf_data.items():
                if code not in capital_flow:  # 不覆盖实时数据
                    if isinstance(val, dict):
                        capital_flow[code] = val.get('main_net_inflow', 0)
                        capital_flow_detail[code] = val
                    else:
                        capital_flow[code] = val
                        capital_flow_detail[code] = {'main_net_inflow': val, 'source': '缓存'}
            log(f"📊 资金面: 缓存补充至{len(capital_flow)}只")
    except Exception:
        pass

# 获取大盘指数
market_index = get_market_index()
if market_index:
    sh_pct = market_index.get('上证', {}).get('change_pct', 0)
    sz_pct = market_index.get('深证', {}).get('change_pct', 0)
    market_str = f"上证{sh_pct:+.1f}% 深证{sz_pct:+.1f}%"
    if min(sh_pct, sz_pct) < -1.0:
        market_str += " ⚠️弱市"
else:
    market_str = "未获取"

log(f"")
log(f"📊 **V10 尾盘选股摘要** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
log(f"━━━━━━━━━━━━━━━━━━━━━━")
log(f"数据源: 腾讯API(纯){' ⚠️降级数据' if is_stale else ''}")
log(f"全扫描时间: {scan_time}")
log(f"大盘: {market_str}")
log(f"备选信号: {len(stocks)} 只")
log(f"当前持仓: {n_holdings}只 | 可用资金: ¥{portfolio_info.get('cash', 0):.0f}")
log(f"")

# 获取实时行情并做七关验证
passed = []
failed = []

for s in stocks:
    code = s.get('code', '')
    name = s.get('name', '')
    signal = s.get('signal', '')
    
    rt = get_realtime(code)
    if not rt:
        failed.append((name, code, signal, '❌ 无实时行情'))
        continue
    
    ok, reasons, warnings = seven_gates_check(s, rt, portfolio_info, 
        capital_flow=capital_flow.get(code), market_index=market_index, capital_flow_detail=capital_flow_detail)
    
    price = rt.get('price', 0)
    change_pct = rt.get('change_pct', 0)
    vibe_score = s.get('vibe_score', 0)
    
    if ok:
        # ── RSV超卖标注（借鉴同花顺公式，辅助参考不拦截） ──
        # 6周期RSV：(CLOSE-LLV(LOW,6))/(HHV(HIGH,6)-LLV(LOW,6))*100
        # RSV<20=超卖区，RSV从<20回升=底部反弹信号
        try:
            from quote_adapter import get_kline
            kl = get_kline(code, period='1d', count=7)
            if kl and len(kl) >= 6:
                lows_6 = [k['low'] for k in kl[-6:]]
                highs_6 = [k['high'] for k in kl[-6:]]
                lowv = min(lows_6)
                highv = max(highs_6)
                if highv > lowv and price > 0:
                    rsv = (price - lowv) / (highv - lowv) * 100
                    if rsv < 20:
                        reasons.append(f'📍超卖区(RSV={rsv:.0f}%)')
                        # 检测超卖反弹：前一日RSV<20，今日回升到≥20
                        if len(kl) >= 7:
                            prev_lows = [k['low'] for k in kl[-7:-1]]
                            prev_highs = [k['high'] for k in kl[-7:-1]]
                            prev_lowv = min(prev_lows)
                            prev_highv = max(prev_highs)
                            if prev_highv > prev_lowv:
                                prev_close = kl[-2]['close']
                                prev_rsv = (prev_close - prev_lowv) / (prev_highv - prev_lowv) * 100
                                if prev_rsv < 20 and rsv >= 20:
                                    reasons.append(f'🔥超卖反弹(RSV {prev_rsv:.0f}%→{rsv:.0f}%)')
                    elif rsv > 80:
                        warnings.append(f'⚠️超买区(RSV={rsv:.0f}%)')
        except Exception:
            pass  # RSV获取失败不影响推荐
        
        passed.append({
            'name': name, 'code': code, 'signal': signal,
            'price': price, 'change_pct': change_pct,
            'vibe_score': vibe_score,
            'vibe_tags': s.get('vibe_tags', []),
            'reasons': reasons, 'warnings': warnings,
            'stop_loss': s.get('key_levels', {}).get('stop_loss', 0),
            'key_levels': s.get('key_levels', {}),
            'trend_quality_score': s.get('trend_quality_score', 0),
            'trend_quality_grade': s.get('trend_quality_grade', 'D'),
            'trend_quality_stars': s.get('trend_quality_stars', '⛔'),
            'trend_quality_recommend': s.get('trend_quality_recommend', ''),
        })
    else:
        fail_reason = ' | '.join(reasons) if reasons else '未知原因'
        failed.append((name, code, signal, fail_reason))

# 按信号强度排序（全买入 > 强庄买 > 基础买）
def sort_key(x):
    if '全买入' in x['signal']: return 0
    if '强庄买' in x['signal']: return 1
    return 2

passed.sort(key=sort_key)

# ── 获取iFinD补充评分（对推荐候选和观察池批量获取） ──
ifind_results = {}
if passed or failed:
    log(f"📊 获取iFinD补充评分...")
    target_codes = set()
    for p in passed:
        target_codes.add((p['code'], p['name']))
    for f_item in failed:
        if isinstance(f_item, tuple) and len(f_item) >= 2:
            target_codes.add((f_item[1], f_item[0]))
    for code, name in target_codes:
        if len(target_codes) <= 6:  # 最多查6只，避免超时
            scoring = get_ifind_scoring(code, name)
            if scoring:
                ifind_results[code] = scoring
        else:
            break
    log(f"✅ iFinD补充评分: {len(ifind_results)}/{len(target_codes)}")

# 为pass列表注入iFinD评分
for p in passed:
    if p['code'] in ifind_results:
        p['ifind'] = ifind_results[p['code']]
    else:
        p['ifind'] = None

# ---- 已持仓代码 ----
holding_codes = set()
for h in portfolio_info.get('holdings', []):
    if h.get('code'):
        holding_codes.add(h['code'])

# ---- 回归观察池检查 ----
# 止损出局的票，V10信号重新归来时可再进
RETURN_WATCHLIST = os.path.expanduser("~/.hermes/cache/watchlist_return.json")
return_pool = []
if os.path.exists(RETURN_WATCHLIST):
    try:
        with open(RETURN_WATCHLIST, 'r', encoding='utf-8') as f:
            rdata = json.load(f)
        today_str = datetime.now().strftime("%Y-%m-%d")
        for rs in rdata.get('stocks', []):
            expire = rs.get('expire_date', '')
            if expire and expire < today_str:
                continue  # 已过期
            cooldown = rs.get('cooldown_until', '')
            rs['_is_cooling'] = cooldown > today_str if cooldown else False
            rs['_is_watching'] = not rs['_is_cooling']
            return_pool.append(rs)
    except Exception:
        pass

def estimate_holding_period(p, capital_flow_detail, sentiment_score=0):
    """估算建议锁仓时间（天）
    基于V10信号、Vibe、趋势质量、位置、资金面、板块、情绪面等因素综合判断。
    今天买明天卖=50%赌博，锁仓期让逻辑有时间兑现。
    返回 (天数, 分类, 逻辑说明)
    """
    signal = p.get('signal', '')
    vibe = p.get('vibe_score', 0)
    tq_grade = p.get('trend_quality_grade', 'D')
    reasons_text = ' '.join(p.get('reasons', []))
    warnings_text = ' '.join(p.get('warnings', []))
    price = p.get('price', 0)
    code = p.get('code', '')
    levels = p.get('key_levels', {})
    ema7 = levels.get('ema7', 0)
    ema20 = levels.get('ema20', 0)

    # 基础天数：信号强度
    if '全买入' in signal:
        days = 3
        base = '★★★基础3天'
    elif '强庄买' in signal:
        days = 2
        base = '★★☆基础2天'
    else:
        days = 1
        base = '★☆☆基础1天'

    mods = []

    # Vibe评分
    if vibe >= 5:
        days += 2
        mods.append(f'Vibe+{vibe}+2天')
    elif vibe >= 2:
        days += 1
        mods.append(f'Vibe+{vibe}+1天')
    elif vibe <= 0:
        days -= 1
        mods.append(f'Vibe{vibe}-1天')

    # 趋势质量
    if tq_grade in ('A', 'B'):
        days += 1
        mods.append(f'趋势{tq_grade}+1天')
    elif tq_grade == 'D':
        days -= 1
        mods.append('趋势D-1天')

    # 位置
    if ema7 > 0 and price > 0:
        dist_ema7 = abs(price - ema7) / ema7 * 100
        if dist_ema7 <= 3:
            days += 1
            mods.append('回调支撑+1天')
        elif dist_ema7 > 8:
            days -= 1
            mods.append('位置偏高-1天')

    # 资金面
    cf_detail = capital_flow_detail.get(code, {}) if capital_flow_detail else {}
    if isinstance(cf_detail, dict):
        cf_inflow = cf_detail.get('main_net_inflow', 0)
        if isinstance(cf_inflow, (int, float)):
            if cf_inflow > 3000:
                days += 1
                mods.append(f'主力流入+1天')
            elif cf_inflow < -5000:
                days -= 1
                mods.append('主力流出-1天')

    # 板块
    if '🐲板块龙头' in reasons_text:
        days += 1
        mods.append('板块龙头+1天')
    if '💰板块资金流入' in reasons_text:
        days += 1
        mods.append('板块资金+1天')
    if '超大+大单双流入' in reasons_text:
        days += 1
        mods.append('双单流入+1天')

    # 风险减分
    if '换手率' in warnings_text and '偏高' in warnings_text:
        days -= 1
        mods.append('换手过高-1天')
    if '大盘暴跌' in warnings_text or '大盘下跌' in warnings_text or '大盘偏弱' in warnings_text:
        days -= 1
        mods.append('弱市-1天')
    if '主力净流出' in warnings_text:
        days -= 1
        mods.append('主力流出-1天')

    # 情绪面（iFinD新闻情绪）
    if sentiment_score >= 3:
        days += 1
        mods.append(f'情绪利好({sentiment_score})+1天')
    elif sentiment_score <= -3:
        days -= 1
        mods.append(f'情绪利空({sentiment_score})-1天')

    days = max(1, min(7, days))

    if days <= 2:
        category = '超短线(快闪)'
    elif days <= 4:
        category = '短线波段'
    else:
        category = '短中线'

    logic = base + ('/' + '、'.join(mods) if mods else '')
    return days, category, logic


# ---- 生成推荐买入指令 ----
# 推荐标准：七关通过 + 信号≥★★☆（强庄买），★☆☆基础买只看不推
# 排除已持仓票（不加仓）
# 回归票：止损出局的票V10信号归来时标注，止损线用割肉价
buy_recs = []
watch_only = []
return_signals = []  # 回归信号票

return_codes = {r['code'] for r in return_pool if r.get('_is_watching')}

for p in passed:
    is_full_buy = '全买入' in p['signal']
    is_strong_buy = '强庄买' in p['signal'] and not is_full_buy
    is_base_buy = not is_full_buy and not is_strong_buy
    already_held = p['code'] in holding_codes
    is_return = p['code'] in return_codes

    if already_held:
        p['_note'] = '已持仓'
        watch_only.append(p)
        continue

    # 回归票检查：V10★★☆+ + 七关通过 → 止损线改为割肉价
    if is_return:
        return_info = next((r for r in return_pool if r['code'] == p['code']), None)
        if return_info and (is_full_buy or is_strong_buy):
            # 回归票：止损线改为割肉价
            sell_price = return_info.get('sell_price', 0)
            if sell_price > 0:
                p['stop_loss'] = sell_price  # 回归止损=割肉价
                p['_return_info'] = return_info
                p['_note'] = f'🔄回归（割肉¥{sell_price:.2f}，止损=割肉价）'
                return_signals.append(p)
                continue  # 回归票单独列出，不混入普通推荐

    if is_full_buy or is_strong_buy:
        # ★★★/★★☆ → 推荐买入
        pv = portfolio_info.get('portfolio_value', 56000)
        cash = portfolio_info.get('cash', 56000)
        price = p['price']
        # 单票仓位≤20%
        max_amount = pv * 0.20
        max_shares = int(max_amount / price / 100) * 100  # 取整手
        max_shares = max(max_shares, 100)  # 至少1手
        buy_amount = max_shares * price
        # 现金够不够
        if buy_amount > cash:
            max_shares = int(cash / price / 100) * 100
            buy_amount = max_shares * price
        p['_shares'] = max_shares
        p['_amount'] = buy_amount
        p['_position_pct'] = buy_amount / pv * 100
        buy_recs.append(p)
    else:
        # ★☆☆ → 只看不推
        watch_only.append(p)

# ---- 输出 ----

# 1️⃣ 推荐买入（直接可操作）
if buy_recs:
    log(f"🔴 **推荐买入（{len(buy_recs)}只）:**")
    for p in buy_recs:
        stars = signal_to_stars(p['signal'])
        vibe_str = f"+{p['vibe_score']}" if p['vibe_score'] > 0 else str(p['vibe_score'])
        vibe_tags_str = ' '.join(str(t) for t in p['vibe_tags']) if isinstance(p['vibe_tags'], list) else ''
        stop_str = f"¥{p['stop_loss']:.2f}" if p['stop_loss'] > 0 else "EMA20参考"
        warn_str = f" ⚠️{'⚠️'.join(p['warnings'])}" if p['warnings'] else ""
        # 趋势质量标注
        tq_grade = p.get('trend_quality_grade', 'D')
        tq_score = p.get('trend_quality_score', 0)
        tq_stars = p.get('trend_quality_stars', '⛔')
        tq_tag = f" | 趋势{tq_grade}({tq_score:.0f}分){tq_stars}"
        tq_warn = ""
        if tq_grade in ('C', 'D'):
            tq_warn = f"\n  │ ⚠️ 趋势质量{tq_grade}级，不推荐买入（{p.get('trend_quality_recommend', '趋势弱')}）"
        log(f"")
        log(f"  **{p['name']}({p['code']})** {stars}{tq_tag}")
        log(f"  │ 买入价: ¥{p['price']:.2f}")
        log(f"  │ 买入量: {p['_shares']}股（{p['_shares']//100}手）")
        log(f"  │ 买入额: ¥{p['_amount']:,.0f}（仓位{p['_position_pct']:.1f}%）")
        log(f"  │ 止损位: {stop_str}")
        if p['stop_loss'] > 0:
            stop_pct = (p['price'] - p['stop_loss']) / p['price'] * 100
            log(f"  │ 止损幅度: -{stop_pct:.1f}%")
        # 📰 iFinD情绪面分析
        sentiment_score = 0
        sentiment_label = ''
        sentiment_news_count = 0
        sentiment_top_news = []
        try:
            from ifind_news_sentiment import get_stock_sentiment
            sentiment = get_stock_sentiment(p['code'], p['name'], size=5)
            if sentiment and sentiment['news_count'] > 0:
                sentiment_score = sentiment['score']
                sentiment_label = sentiment['label']
                sentiment_news_count = sentiment['news_count']
                sentiment_top_news = sentiment['top_news'][:2]
                log(f"  │ 情绪面{sentiment['label']}(评分{sentiment['score']:+d}, {sentiment['news_count']}条新闻)")
                for title in sentiment_top_news:
                    log(f"  │   📰 {title}")
        except Exception as e:
<<<<<<< Updated upstream
            log(f"  ⚠️ {name}({code}) 评分失败: {e}")
            total, details, price, change = 0, {}, 0, 0

        # 基本面扣分：被排雷但保留的强信号股，基本面维度给保底分而非0分
        # 强信号(全买入/强庄买)基本面扣分后保底5分(而非0分)，因为强庄信号本身有价值
        if s.get("_fundamental_penalty") and "基本面" in details:
            old_score, max_score, old_desc = details["基本面"]
            penalty = 5 if sig in ("全买入", "强庄买") else 0  # 强信号保底5分
            details["基本面"] = (penalty, max_score, f"{old_desc}+排雷扣分")
            total = total - old_score + penalty

        # 资金面扣分：被排除但保留的强信号股，资金面维度给保底分
        # 强信号资金面扣分后保底5分，主力净流出不一定代表不能买
        if s.get("_capital_penalty") and "资金面" in details:
            old_score, max_score, old_desc = details["资金面"]
            penalty = 5 if sig in ("全买入", "强庄买") else 0  # 强信号保底5分
            details["资金面"] = (penalty, max_score, f"{old_desc}+净流出扣分")
            total = total - old_score + penalty

        # 信号确认加分：强信号本身就是高置信度，额外加分避免被其他维度拖垮
        signal_bonus = SIGNAL_SCORE_BONUS.get(sig, 0)
        if signal_bonus > 0:
            total += signal_bonus
            details["信号确认"] = (signal_bonus, 0, f"{sig}信号确认+{signal_bonus}分")

        results.append({
            "code": code,
            "name": name,
            "signal": sig,
            "score": total,
            "details": details,
            "price": price,
            "change_pct": change,
            "rank": SIGNAL_RANK.get(sig, 0),
        })
        time.sleep(0.2)  # 限速

    # 按信号等级降序 → 评分降序
    results.sort(key=lambda x: (x["rank"], x["score"]), reverse=True)
    return results


def format_top_recommendation(lines, stock, rank_label, rt_quote=None):
    """格式化单个推荐股的详细信息"""
    price = stock["price"]
    change = stock["change_pct"]
    score = stock["score"]
    sig = stock["signal"]
    emoji = SIGNAL_EMOJI.get(sig, "⚪")

    # 动态止损：根据信号等级调整
    if sig == "全买入":
        stop_pct = 0.08   # 8% 止损
    elif sig == "强庄买":
        stop_pct = 0.10   # 10% 止损
    else:
        stop_pct = 0.14   # 14% 止损
    stop_loss = round(price * (1 - stop_pct), 2) if price > 0 else 0

    # 目标价
    if sig == "全买入":
        target_pct = 0.15
    elif sig == "强庄买":
        target_pct = 0.12
    else:
        target_pct = 0.08
    target = round(price * (1 + target_pct), 2) if price > 0 else 0

    lines.append(f"**{rank_label} {emoji} {stock['name']}（{stock['code']}）**")
    lines.append(f"信号等级：{sig} | 综合评分：**{score}分**")
    lines.append(f"现价 ¥{price:.2f} | 涨幅 {change:+.1f}%")

    # 涨停价/跌停价
    if rt_quote and rt_quote.get("limit_up"):
        lines.append(f"涨停价 ¥{rt_quote['limit_up']:.2f} | 跌停价 ¥{rt_quote['limit_down']:.2f}")

    # 评分明细
    if stock.get("details"):
        lines.append("")
        lines.append("| 维度 | 得分 | 详情 |")
        lines.append("|------|-----:|------|")
        for dim, (sc, max_sc, desc) in stock["details"].items():
            lines.append(f"| {dim} | {sc}/{max_sc} | {desc} |")

    lines.append("")
    if price > 0:
        lines.append(f"💰 建议买入价：¥{price:.2f} | 仓位 20%（约2万）")
        lines.append(f"📍 止损位：¥{stop_loss:.2f}（-{stop_pct*100:.0f}%）| 目标价：¥{target:.2f}（+{target_pct*100:.0f}%）")
        risk_reward = (target - price) / (price - stop_loss) if (price - stop_loss) > 0 else 0
        lines.append(f"📊 盈亏比：{risk_reward:.1f}:1")
    lines.append("")


def format_others_table(lines, stocks, label="📋 其余符合条件"):
    """格式化其余候选股的简洁表格"""
    if not stocks:
        return

    lines.append(f"{label}（{len(stocks)}只）")
    lines.append("")
    lines.append("| 代码 | 名称 | 信号等级 | 买入评分 |")
    lines.append("|:----:|------|:--------:|:--------:|")
    for s in stocks:
        emoji = SIGNAL_EMOJI.get(s["signal"], "⚪")
        lines.append(
            f"| {s['code']} | {s['name']} | {emoji} {s['signal']} | {s['score']}分 |"
        )
    lines.append("")


# ── MAIN ──────────────────────────────────────────────────
def main():
    data = load_watchlist()
    if not data:
        log("❌ 未找到全扫描缓存 (v10_watchlist.json)，请先执行全扫描")
        sys.exit(0)

    stocks = data.get("stocks", [])
    scan_time = data.get("scan_time", "未知")

    # === 时效性校验：watchlist必须是今天的数据 ===
    today_str = datetime.now().strftime("%Y-%m-%d")
    if scan_time and not scan_time.startswith(today_str):
        log(f"⚠️ watchlist数据过期: scan_time={scan_time} (非今日 {today_str})")
        log(f"   不生成推荐，避免用过期信号误导")
        # 写空推荐JSON，清除旧的过期推荐
        _build_recommend_json([], [], [], scan_time, cooldown=False)
        sys.exit(0)

    if not stocks:
        log("📊 V10 尾盘信号摘要")
        log("━━━━━━━━━━━━━━━━━━━━━━")
        log(f"扫描时间: {scan_time}")
        log("")
        log("⛔ 今日尾盘无V10进场信号")
        log("   继续保持空仓等待")
        sys.exit(0)

    log(f"📊 V10 尾盘信号摘要 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log(f"━━━━━━━━━━━━━━━━━━━━━━")
    log(f"全扫描时间: {scan_time} | 原始信号数: {len(stocks)}只")
    log("")

    # ===== 把关1: 冷静期检查 =====
    in_cooldown, cooldown_until = check_cooldown()

    # ===== 把关2: 信号等级分流 =====
    # 全买入 + 强庄买 → 候选推荐池
    # 基础买 → 直接进观察池（弱信号，不推荐）
    recommend_pool = [s for s in stocks if s.get("signal") in ("全买入", "强庄买")]
    base_buy_pool = [s for s in stocks if s.get("signal") == "基础买"]
    observe_pool = []  # 基础买先收集，评分后决定去留
    log(f"📋 信号分流: 推荐{(len(recommend_pool))}只(全买入+强庄买) + 基础买{len(base_buy_pool)}只(待评分分流)")

    # ===== 把关3: 基本面排雷 =====
    log("🔍 基本面排雷...")
    fund_passed, fund_rejected = filter_fundamental_safe(recommend_pool)
    if fund_passed is not None:
        before = len(recommend_pool)
        # 强信号（全买入/强庄买）被PE排雷时保留在推荐池，但在评分中扣分
        # 理由：强庄信号本身说明主力在控盘，PE为负可能是周期反转/成长期
        # 旧逻辑直接排除导致强庄买因PE为负永远无法推荐
        new_recommend = []
        for s in recommend_pool:
            code = s.get("code", "")
            sig = s.get("signal", "")
            if code in fund_passed:
                new_recommend.append(s)
            elif sig in ("全买入", "强庄买"):
                # 强信号被排雷 → 保留在推荐池，但标记基本面扣分
                reason = fund_rejected.get(code, "基本面不达标")
                log(f"  ⚠️ {s.get('name','')}({code}) {sig}基本面不达标({reason})，评分将扣分")
                s["_fundamental_penalty"] = True  # 评分时扣基本面分
                new_recommend.append(s)
            # else: 基础买被排雷 → 降级到观察池
            else:
                reason = fund_rejected.get(code, "基本面不达标")
                log(f"  ⬇️ {s.get('name','')}({code}) 基础买被排雷({reason})，降级到观察池")
                observe_pool.append(s)
        recommend_pool = new_recommend
        excluded_by_fund = before - len(recommend_pool)
        downgraded = sum(1 for s in observe_pool if isinstance(s, dict))
        if excluded_by_fund > 0 or downgraded > 0:
            log(f"  结果: 通过{len(recommend_pool)}只 | 基本面扣分保留{sum(1 for s in recommend_pool if s.get('_fundamental_penalty'))}只 | 降级{downgraded}只")
        else:
            log(f"  ✅ 基本面全部通过")
    else:
        log(f"  ⚠️ 基本面过滤降级跳过")

    # ===== 把关4: 资金面验证 =====
    log("💰 资金面验证...")
    codes_to_check = [s.get("code", "") for s in recommend_pool]
    cap_passed, cap_rejected = filter_capital_safe(codes_to_check)
    if cap_passed is not None:
        before = len(recommend_pool)
        # 强信号被资金面排除时保留但扣分（和基本面排雷同理）
        new_recommend = []
        for s in recommend_pool:
            code = s.get("code", "")
            sig = s.get("signal", "")
            if code in cap_passed:
                new_recommend.append(s)
            elif sig in ("全买入", "强庄买"):
                # 强信号被资金面排除 → 保留但扣资金面分
                reason = cap_rejected.get(code, "主力净流出")
                log(f"  ⚠️ {s.get('name','')}({code}) {sig}资金面不达标({reason})，评分将扣分")
                s["_capital_penalty"] = True  # 标记资金面扣分
                new_recommend.append(s)
            else:
                # 基础买被资金面排除 → 降级到观察池
                reason = cap_rejected.get(code, "主力净流出")
                log(f"  ⬇️ {s.get('name','')}({code}) 基础买资金面不达标({reason})，降级到观察池")
                observe_pool.append(s)
        recommend_pool = new_recommend
        cap_excluded = before - len(recommend_pool) + sum(1 for s in observe_pool if isinstance(s, dict))
        if cap_excluded > 0:
            log(f"  结果: 通过{len(recommend_pool)}只 | 资金面扣分保留{sum(1 for s in recommend_pool if s.get('_capital_penalty'))}只 | 降级{cap_excluded}只")
        else:
            log(f"  ✅ 资金面全部通过")
    else:
        log(f"  ⚠️ 资金面验证降级跳过")

    # ===== 把关5: 评分 =====
    log("⏳ 正在评分...")
    scored_recommend = score_all_candidates(recommend_pool)
    scored_base = score_all_candidates(base_buy_pool) if base_buy_pool else []
    log(f"✅ 评分完成: 推荐池{len(scored_recommend)}只 + 基础买{len(scored_base)}只")

    # 基础买评分分流：只进观察池，不进推荐池（弱信号不具备推荐价值）
    for s in scored_base:
        if s["score"] >= SCORE_OBSERVE_MIN:
            observe_pool.append(s)
        # <40的直接排除（不进任何池）
    
    # 推荐池按信号等级+评分排序
    scored_recommend.sort(key=lambda x: (x["rank"], x["score"]), reverse=True)
    log(f"📊 分流结果: 推荐池{len(scored_recommend)}只 + 观察池{len(observe_pool)}只")

    # ===== 把关6: 涨停价确认 + 评分门槛 =====
    log("🚫 涨停/评分筛选...")
    filtered_recommend = []
    excluded_reasons = []

    for s in scored_recommend:
        code = s["code"]

        # 涨停价确认
        rt = get_realtime(code)
        excluded, reason = check_limit_up(code, rt)
        if excluded:
            excluded_reasons.append((s, reason))
            continue

        # 存实时行情供推荐详情使用
        s["_rt"] = rt

        # 评分门槛
        if s["score"] < SCORE_RECOMMEND_MIN:
            excluded_reasons.append((s, f"评分{s['score']}<{SCORE_RECOMMEND_MIN}"))
            # 低于推荐门槛但≥观察门槛的降级到观察池
            if s["score"] >= SCORE_OBSERVE_MIN:
                observe_pool.append(s)
            continue

        filtered_recommend.append(s)

    # 观察池也做评分门槛
    observe_pool = [s for s in observe_pool if isinstance(s, dict) and s.get("score", 0) >= SCORE_OBSERVE_MIN]

    log(f"  ✅ 推荐池剩余{len(filtered_recommend)}只 | 排除{len(excluded_reasons)}只")
    if excluded_reasons:
        for s, reason in excluded_reasons[:5]:
            log(f"    ❌ {s['name']}({s['code']}): {reason}")
        if len(excluded_reasons) > 5:
            log(f"    ... 共{len(excluded_reasons)}只被排除")

    # ── 构建输出 ──
    lines = []
    lines.append("")
    lines.append(f"📊 **V10 尾盘信号摘要** | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"全扫描时间: {scan_time} | 原始信号: {len(stocks)}只")
    lines.append(f"把关: 信号分流→基本面排雷→资金面验证→评分→涨停确认")
    lines.append(f"结果: 推荐{len(filtered_recommend)}只 | 观察{len(observe_pool)}只 | 排除{len(excluded_reasons)}只")
    lines.append("")

    # ===== 冷静期提示 =====
    if in_cooldown:
        lines.append(f"🔴 **冷静期中** — 连续{COOLDOWN_LOSS_STREAK}次全亏，暂停推荐")
        if cooldown_until:
            lines.append(f"   冷静期至: {cooldown_until}")
        lines.append("")

    # ===== 推荐 TOP1-2 =====
    if not in_cooldown and filtered_recommend:
        top_n = min(2, len(filtered_recommend))
        lines.append(f"🏆 **推荐买入**（TOP {top_n}）")
        lines.append("")
        for i, s in enumerate(filtered_recommend[:top_n], 1):
            label = f"TOP{i}"
            rt = s.pop("_rt", None)
            format_top_recommendation(lines, s, label, rt_quote=rt)
    elif not in_cooldown:
        lines.append("⛔ **无可推荐标的** — 所有候选未通过把关筛选")
        lines.append("")

    # ===== 观察池 =====
    if observe_pool:
        format_others_table(lines, observe_pool, label="👁️ 观察池（基础买/低分候选）")

    # ===== 被过滤详情 =====
    if excluded_reasons:
        lines.append(f"⚠️ **被过滤**（{len(excluded_reasons)}只）")
        lines.append("")
        lines.append("| 代码 | 名称 | 信号 | 评分 | 排除原因 |")
        lines.append("|:----:|------|------|-----:|----------|")
        for s, reason in excluded_reasons:
            emoji = SIGNAL_EMOJI.get(s["signal"], "⚪")
            lines.append(f"| {s['code']} | {s['name']} | {emoji}{s['signal']} | {s['score']}分 | {reason} |")
        lines.append("")

    # 无信号兜底
    if not filtered_recommend and not observe_pool and not excluded_reasons:
        lines.append("⛔ 今日尾盘无V10进场信号")
        lines.append("   继续保持空仓等待")

    output = "\n".join(lines)
    log("")
    log(output)

    # 同时写一份到缓存，供cron job消费
    summary_cache = os.path.join(CACHE_DIR, "v10_tail_summary.txt")
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(summary_cache, 'w') as f:
        f.write(output)
    log(f"\n💾 摘要已写入 {summary_cache}")

    # ===== 输出结构化推荐JSON，供页面读取 =====
    _build_recommend_json(filtered_recommend, observe_pool, excluded_reasons, scan_time, in_cooldown)

    # ===== 自动同步推荐到追踪器 =====
    _top_n = min(2, len(filtered_recommend)) if not in_cooldown and filtered_recommend else 0
    if _top_n > 0:
=======
            log(f"  │ 情绪面: 获取失败({str(e)[:40]})")
        # 📊 股吧情绪面（散户视角，与iFinD新闻情绪互补）
        guba_score = 0
        guba_contrary = ''
>>>>>>> Stashed changes
        try:
            from guba_sentiment import fetch_guba_posts, analyze_guba_sentiment
            posts = fetch_guba_posts(p['code'], pages=1)
            if posts:
                guba = analyze_guba_sentiment(posts)
                guba_score = guba['score']
                guba_label = guba['label']
                guba_contrary = guba.get('contrary_signal', '')
                log(f"  │ 股吧{guba_label}(评分{guba_score:+d}, {guba['post_count']}条)")
                # 极端情绪反向信号
                if guba_contrary:
                    log(f"  │   ⚠️ {guba_contrary}")
                    p['warnings'].append(guba_contrary)
                # 与iFinD新闻情绪对比
                if sentiment_score != 0 and guba_score != 0:
                    if sentiment_score > 0 and guba_score < 0:
                        log(f"  │   ⚡ 分歧：新闻利好({sentiment_score:+d}) vs 股吧看空({guba_score:+d})，机构看好散户恐慌")
                    elif sentiment_score < 0 and guba_score > 0:
                        log(f"  │   ⚡ 分歧：新闻利空({sentiment_score:+d}) vs 股吧看多({guba_score:+d})，散户盲目乐观")
                    elif sentiment_score * guba_score > 0:
                        log(f"  │   ✅ 共振：新闻({sentiment_score:+d})与股吧({guba_score:+d})同向")
                # 极端看多反向指标 → 锁仓-1天
                if guba_score >= 8 and guba.get('extreme_bull'):
                    sentiment_score -= 1  # 影响锁仓时间
                    log(f"  │   📉 股吧极度看多，锁仓-1天")
        except Exception as e:
            log(f"  │ 股吧情绪: 获取失败({str(e)[:40]})")
        # 🔒 锁仓时间分析（含情绪面因子）
        hold_days, hold_cat, hold_logic = estimate_holding_period(p, capital_flow_detail, sentiment_score)
        log(f"  │ 🔒 建议锁仓: {hold_days}天（{hold_cat}）| {hold_logic}")
        log(f"  │ 涨跌: {p['change_pct']:+.1f}% | Vibe: {vibe_str}({vibe_tags_str})")
        # 资金面信息
        cf = capital_flow.get(p['code'], 0)
        if cf != 0:
            d = "流入" if cf > 0 else "流出"
            amt = abs(cf)
            cf_str = f"{amt/10000:.2f}亿" if amt >= 10000 else f"{amt:.0f}万"
            log(f"  │ 主力净{d}: {cf_str}")
        # iFinD基本面补充评分
        ifind = p.get('ifind')
        if ifind:
            ig = ifind.get('ifind_grade', 'C')
            isc = ifind.get('ifind_score', 50)
            itag = ifind.get('ifind_tag', '')
            ifin = ifind.get('financial', {}).get('details', [])
            iinst = ifind.get('institution', {}).get('details', [])
            ifin_str = ' '.join(ifin[:2]) if ifin else ''
            iinst_str = ' '.join(iinst[:2]) if iinst else ''
            log(f"  │ 基本面{ig}({isc:.0f}分){itag}")
            if ifin_str:
                log(f"  │   ├财务: {ifin_str}")
            if iinst_str:
                log(f"  │   └机构: {iinst_str}")
        log(f"  │ 通过: {' | '.join(p['reasons'])}{warn_str}")
        if tq_warn:
            log(tq_warn)
else:
    log(f"⛔ 今日无推荐买入")

log(f"")

# 2️⃣ 观察池（七关通过但信号弱或已持仓）
if watch_only:
    log(f"👀 **观察池（{len(watch_only)}只，不推荐买入）:**")
    for p in watch_only:
        stars = signal_to_stars(p['signal'])
        vibe_str = f"+{p['vibe_score']}" if p['vibe_score'] > 0 else str(p['vibe_score'])
        note = p.get('_note', '')
        stop_str = f" | 止损¥{p['stop_loss']:.2f}" if p['stop_loss'] > 0 else ""
        warn_str = f" ⚠️{'⚠️'.join(p['warnings'])}" if p['warnings'] else ""
        extra = f" [{note}]" if note else ""
        # 趋势质量标注
        tq_grade = p.get('trend_quality_grade', 'D')
        tq_score = p.get('trend_quality_score', 0)
        tq_stars = p.get('trend_quality_stars', '⛔')
        tq_tag = f" | 趋势{tq_grade}({tq_score:.0f}分)"
        tq_note = f"⛔" if tq_grade == 'D' else ("⚠️" if tq_grade == 'C' else "")
        # iFinD基本面评分
        ifind = p.get('ifind')
        ifind_tag = ''
        if ifind:
            ig = ifind.get('ifind_grade', '')
            isc = ifind.get('ifind_score', 0)
            ifind_tag = f" | 基本面{ig}({isc:.0f})"
        log(f"  {stars} {p['name']}({p['code']}) ¥{p['price']:.2f} {p['change_pct']:+.1f}% Vibe{vibe_str}{tq_tag}{tq_stars}{tq_note}{ifind_tag}{stop_str}{warn_str}{extra}")

log(f"")

# 3️⃣ 未通过验证
if failed:
    log(f"⚪ **未通过验证（{len(failed)}只）:**")
    for name, code, signal, reason in failed[:10]:
        stars = signal_to_stars(signal)
        log(f"  {stars} {name}({code}) → {reason}")
    if len(failed) > 10:
        log(f"  ...及{len(failed)-10}只")

log(f"")

# 4️⃣ 回归信号（止损出局的票V10信号归来）
if return_signals:
    log(f"🔄 **回归信号（{len(return_signals)}只，曾割肉V10归来）:**")
    for p in return_signals:
        stars = signal_to_stars(p['signal'])
        vibe_str = f"+{p['vibe_score']}" if p['vibe_score'] > 0 else str(p['vibe_score'])
        ri = p.get('_return_info', {})
        sell_price = ri.get('sell_price', 0)
        sell_pnl = ri.get('sell_pnl_pct', 0)
        cooldown_until = ri.get('cooldown_until', '')
        stop_str = f"¥{p['stop_loss']:.2f}" if p['stop_loss'] > 0 else "EMA20参考"
        if p['stop_loss'] > 0:
            stop_pct = (p['price'] - p['stop_loss']) / p['price'] * 100
            stop_detail = f"-{stop_pct:.1f}%"
        else:
            stop_detail = ""
        log(f"")
        log(f"  **{p['name']}({p['code']})** {stars} 🔄")
        log(f"  │ 现价: ¥{p['price']:.2f} | 涨跌: {p['change_pct']:+.1f}%")
        log(f"  │ 割肉价: ¥{sell_price:.2f}（当时{sell_pnl:+.1f}%）")
        log(f"  │ 回归止损: {stop_str}（=割肉价，最差平出）{stop_detail}")
        log(f"  │ Vibe: {vibe_str}")
        log(f"  │ 通过: {' | '.join(p['reasons'])}")
elif return_pool:
    # 冷静期中的回归票
    cooling = [r for r in return_pool if r.get('_is_cooling')]
    watching_no_signal = [r for r in return_pool if r.get('_is_watching') and r['code'] not in {p['code'] for p in passed}]
    if cooling or watching_no_signal:
        log(f"🔄 **回归观察池（{len(return_pool)}只）:**")
        for r in return_pool:
            status = "🧊冷静中" if r.get('_is_cooling') else "👁️观察中"
            sell_pct = r.get('sell_pnl_pct', 0)
            log(f"  {status} {r['name']}({r['code']}) | 割肉¥{r['sell_price']:.2f}({sell_pct:+.1f}%) | 回归止损¥{r.get('return_stop', 0):.2f} | 冷静至{r.get('cooldown_until', '?')} | 过期{r.get('expire_date', '?')}")

log(f"")
log(f"📌 七关验证v6: ①V10信号 ②实时数据 ③Vibe+资金面 ④大盘量化+风口 ⑤追高安全垫+涨停否决+位置审查 ⑥仓位+冷静期 ⑦止损空间≥8%(策略v2) | 龙头标注+弱市收紧 | 🔒锁仓时间=信号强度+Vibe+趋势+位置+资金面+板块综合估算")
log(f"📌 推荐规则: ★★★/★★☆ → 推荐买入 | ★☆☆/已持仓 → 观察池 | 🔄 → 回归信号 | 未通过 → 拦截 | 趋势C/D⚠️不推荐买入 | iFinD基本面仅供参考不否决 | 🔒锁仓1-2天=超短线快闪 3-4天=短线波段 5-7天=短中线")
