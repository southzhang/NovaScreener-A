#!/usr/bin/env python3
"""
板块分析模块 - 热门板块识别、板块轮动分析、板块强度评分
用于V10选股系统和盯盘系统
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

WORKSPACE = os.path.expanduser("~/.hermes/workspace")
CACHE_DIR = os.path.expanduser("~/.hermes/cache")
SECTOR_CACHE = os.path.join(CACHE_DIR, "sector_analysis.json")

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _log(msg):
    print(f"[板块分析] {msg}", file=sys.stderr)


def fetch_url(url, timeout=8):
    """通用URL请求"""
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("gbk", errors="ignore")
    except Exception as e:
        _log(f"⚠️ 请求失败 {url[:60]}... {e}")
        return None


def _ifind_post(api_name, params, timeout=8):
    """调用iFinD HTTP API"""
    try:
        import urllib.request
        import json
        
        url = f"http://192.168.110.210:18080/{api_name}"
        data = json.dumps(params).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        _log(f"iFinD API调用失败: {e}")
        return None


def fetch_sector_ranking():
    """用问财获取今日板块涨幅排名
    返回: [{'name': 板块名, 'change': 涨幅, 'leaders': [领涨股列表]}, ...]
    """
    t0 = time.time()
    result = []
    try:
        data = _ifind_post("smart_stock_picking", {
            "searchstring": "涨幅前3板块的股票",
            "searchtype": "stock"
        }, timeout=15)
        if data and data.get('errorcode') == 0 and data.get('tables'):
            table = data['tables'][0].get('table', {})
            codes = table.get('股票代码', [])
            names = table.get('股票简称', [])
            today_str = datetime.now().strftime('%Y%m%d')
            changes = table.get(f'涨跌幅:前复权[{today_str}]', [])
            for i in range(min(20, len(codes))):
                code = str(codes[i]).split('.')[0] if i < len(codes) else ''
                name = names[i] if i < len(names) else ''
                change = float(changes[i]) if i < len(changes) else 0
                result.append({'code': code, 'name': name, 'change': change})
    except Exception as e:
        _log(f"⚠️ 板块排名查询异常: {e}")
    t1 = time.time()
    if result:
        _log(f"📊 板块排名: {len(result)}只 ({t1-t0:.2f}秒)")
    return result


def get_sector_data_from_ifind():
    """从iFinD获取板块数据（行业板块+概念板块）"""
    try:
        # 获取行业板块涨幅排名
        industry_data = _ifind_post("ths_hot_ranking", {
            "index_type": "industry",
            "top_n": 20
        }, timeout=5)  # 缩短超时时间
        
        # 获取概念板块涨幅排名
        concept_data = _ifind_post("ths_hot_ranking", {
            "index_type": "concept",
            "top_n": 20
        }, timeout=5)  # 缩短超时时间
        
        result = {
            'industry': [],
            'concept': [],
            'timestamp': datetime.now().isoformat()
        }
        
        if industry_data and industry_data.get('errorcode') == 0:
            result['industry'] = industry_data.get('tables', [{}])[0].get('table', {})
        
        if concept_data and concept_data.get('errorcode') == 0:
            result['concept'] = concept_data.get('tables', [{}])[0].get('table', {})
        
        return result
    except Exception as e:
        _log(f"⚠️ iFinD板块数据获取失败: {e}")
        return None


def get_sector_data_from_tencent():
    """从腾讯行情获取板块ETF数据（降级方案）"""
    sector_etfs = {
        'sh512010': '医药', 'sh512880': '证券', 'sh512660': '军工',
        'sh515030': '新能源', 'sh512480': '半导体', 'sh512690': '酒',
        'sh515790': '光伏', 'sh512200': '房地产', 'sh512400': '有色金属',
        'sh512800': '银行', 'sh516160': '新能源车', 'sh512670': '国防',
        'sh515210': '钢铁', 'sh515220': '煤炭',
    }
    
    try:
        codes = ','.join(sector_etfs.keys())
        url = f"http://qt.gtimg.cn/q={codes}"
        text = fetch_url(url, timeout=10)
        if not text:
            return []
        
        results = []
        for line in text.strip().split(';'):
            if '=' not in line:
                continue
            parts = line.split('=')[1].strip('"\n').split('~')
            if len(parts) < 50:
                continue
            code = parts[2]
            name = sector_etfs.get(code, parts[1])
            price = float(parts[3]) if parts[3] else 0
            yclose = float(parts[4]) if parts[4] else 0
            change = ((price - yclose) / yclose * 100) if yclose > 0 else 0
            results.append({
                'code': code,
                'name': name,
                'change': change,
                'price': price
            })
        
        # 按涨幅排序
        results.sort(key=lambda x: x['change'], reverse=True)
        return results
    except Exception as e:
        _log(f"⚠️ 腾讯板块ETF获取失败: {e}")
        return []


def get_sector_ranking():
    """获取板块涨幅排名（优先iFinD，降级腾讯ETF）"""
    # 尝试iFinD
    ifind_data = get_sector_data_from_ifind()
    if ifind_data and ifind_data.get('industry'):
        _log("✅ 使用iFinD板块数据")
        return ifind_data
    
    # 降级到腾讯ETF
    _log("⚠️ iFinD不可用，降级到腾讯板块ETF")
    etf_data = get_sector_data_from_tencent()
    if etf_data:
        return {
            'industry': [{'name': e['name'], 'change': e['change']} for e in etf_data[:10]],
            'concept': [],
            'source': 'tencent_etf',
            'timestamp': datetime.now().isoformat()
        }
    
    return None


def get_stock_sector(code):
    """获取个股所属板块"""
    try:
        # 从腾讯行情获取板块信息
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"http://qt.gtimg.cn/q={prefix}{code}"
        text = fetch_url(url, timeout=5)
        if not text:
            return None
        
        parts = text.split('=')[1].strip('"\n').split('~')
        if len(parts) > 100:
            # 腾讯行情的第100个字段是所属板块
            sector = parts[100] if parts[100] else None
            return sector
        return None
    except Exception as e:
        _log(f"⚠️ 获取个股板块失败 {code}: {e}")
        return None


def analyze_sector_rotation(days=3):
    """分析板块轮动趋势
    返回: {
        'hot_sectors': [连续多日上涨的板块],
        'new_sectors': [新进TOP10的板块],
        'cooling_sectors': [从TOP10退出的板块],
        'rotation_trend': '轮动方向描述'
    }
    """
    try:
        # 获取历史板块数据（从缓存）
        history_file = os.path.join(CACHE_DIR, "sector_history.json")
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        else:
            history = []
        
        # 获取今日板块数据
        today_data = get_sector_ranking()
        if not today_data:
            return None
        
        # 保存今日数据
        today_entry = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'industry': today_data.get('industry', [])[:10],
            'concept': today_data.get('concept', [])[:10]
        }
        history.append(today_entry)
        
        # 只保留最近N天
        history = history[-days:]
        
        # 保存历史
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        
        # 分析轮动
        if len(history) < 2:
            return {
                'hot_sectors': [],
                'new_sectors': [s['name'] for s in today_data.get('industry', [])[:5]],
                'cooling_sectors': [],
                'rotation_trend': '数据不足，需要至少2天数据'
            }
        
        # 获取今日和昨日的板块
        today_sectors = {s['name'] for s in today_data.get('industry', [])[:10]}
        yesterday_sectors = {s['name'] for s in history[-2].get('industry', [])[:10]}
        
        # 热门板块：连续2天都在TOP10
        hot_sectors = today_sectors & yesterday_sectors
        
        # 新进板块：今日TOP10但昨日不在
        new_sectors = today_sectors - yesterday_sectors
        
        # 降温板块：昨日TOP10但今日不在
        cooling_sectors = yesterday_sectors - today_sectors
        
        # 轮动趋势
        if new_sectors:
            rotation_trend = f"资金流入: {', '.join(list(new_sectors)[:3])}"
        elif cooling_sectors:
            rotation_trend = f"资金流出: {', '.join(list(cooling_sectors)[:3])}"
        else:
            rotation_trend = "板块格局稳定"
        
        return {
            'hot_sectors': list(hot_sectors),
            'new_sectors': list(new_sectors),
            'cooling_sectors': list(cooling_sectors),
            'rotation_trend': rotation_trend,
            'today_top5': [s['name'] for s in today_data.get('industry', [])[:5]]
        }
    except Exception as e:
        _log(f"⚠️ 板块轮动分析失败: {e}")
        return None


def get_sector_score(code, change_pct=None):
    """获取个股的板块风口评分（满分10分）
    
    评分逻辑：
    - 个股所属板块在今日TOP3：10分
    - 个股所属板块在今日TOP10：7分
    - 个股涨幅>5%（可能是独立行情）：5分
    - 个股涨幅>2%：3分
    - 其他：0分
    
    返回: (score, description)
    """
    try:
        # 获取板块排名
        sector_data = get_sector_ranking()
        if not sector_data:
            # 降级：用个股涨幅作为代理
            if change_pct is None:
                return 0, "板块数据不可用"
            if change_pct > 5:
                return 5, f"涨幅+{change_pct:.1f}%（板块数据不可用）"
            elif change_pct > 2:
                return 3, f"涨幅+{change_pct:.1f}%（板块数据不可用）"
            else:
                return 0, f"涨幅{change_pct:+.1f}%"
        
        # 获取个股所属板块
        stock_sector = get_stock_sector(code)
        
        # 获取TOP板块列表
        top_sectors = [s['name'] for s in sector_data.get('industry', [])[:10]]
        top3_sectors = top_sectors[:3]
        
        # 评分
        if stock_sector and stock_sector in top3_sectors:
            return 10, f"板块{stock_sector}排名TOP3"
        elif stock_sector and stock_sector in top_sectors:
            return 7, f"板块{stock_sector}排名TOP10"
        elif change_pct is not None and change_pct > 5:
            return 5, f"涨幅+{change_pct:.1f}%（独立行情）"
        elif change_pct is not None and change_pct > 2:
            return 3, f"涨幅+{change_pct:.1f}%"
        else:
            return 0, f"板块{stock_sector or '未知'}不在风口"
    except Exception as e:
        _log(f"⚠️ 板块评分失败 {code}: {e}")
        return 0, f"评分异常: {e}"


def get_sector_summary():
    """获取板块概况（用于报告输出）"""
    try:
        sector_data = get_sector_ranking()
        if not sector_data:
            return "板块数据不可用"
        
        industry = sector_data.get('industry', [])[:5]
        concept = sector_data.get('concept', [])[:5]
        
        lines = []
        lines.append("📊 **板块概况**")
        lines.append("")
        
        if industry:
            lines.append("**行业板块TOP5：**")
            for i, s in enumerate(industry, 1):
                change = s.get('change', 0)
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                lines.append(f"{i}. {s['name']} {emoji}{change:+.2f}%")
        
        if concept:
            lines.append("")
            lines.append("**概念板块TOP5：**")
            for i, s in enumerate(concept, 1):
                change = s.get('change', 0)
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                lines.append(f"{i}. {s['name']} {emoji}{change:+.2f}%")
        
        # 轮动分析
        rotation = analyze_sector_rotation()
        if rotation:
            lines.append("")
            lines.append(f"**轮动趋势：** {rotation['rotation_trend']}")
            if rotation['hot_sectors']:
                lines.append(f"**热门板块：** {', '.join(rotation['hot_sectors'][:3])}")
            if rotation['new_sectors']:
                lines.append(f"**新进板块：** {', '.join(rotation['new_sectors'][:3])}")
        
        return "\n".join(lines)
    except Exception as e:
        return f"板块概况获取失败: {e}"


if __name__ == '__main__':
    # 测试
    print("=" * 60)
    print("板块分析模块测试")
    print("=" * 60)
    
    # 1. 获取板块排名
    print("\n1. 板块排名:")
    ranking = get_sector_ranking()
    if ranking:
        print(f"  行业板块: {len(ranking.get('industry', []))}个")
        print(f"  概念板块: {len(ranking.get('concept', []))}个")
    
    # 2. 板块轮动分析
    print("\n2. 板块轮动:")
    rotation = analyze_sector_rotation()
    if rotation:
        print(f"  热门板块: {rotation['hot_sectors']}")
        print(f"  新进板块: {rotation['new_sectors']}")
        print(f"  轮动趋势: {rotation['rotation_trend']}")
    
    # 3. 个股板块评分
    print("\n3. 个股板块评分:")
    test_codes = ['002600', '600936', '300912']
    for code in test_codes:
        score, desc = get_sector_score(code)
        print(f"  {code}: {score}分 - {desc}")
    
    # 4. 板块概况
    print("\n4. 板块概况:")
    summary = get_sector_summary()
    print(summary)
