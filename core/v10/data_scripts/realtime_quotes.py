#!/usr/bin/env python3
"""获取A股实时行情 - 腾讯行情API
用法: python3 realtime_quotes.py sh600936 sz300455 sh603012 ...
或: python3 realtime_quotes.py 600936 300455 603012 ... (自动判断市场)

⚠️ 已知限制：批量查询时，一次传入7只或更多股票代码，可能只返回第1只。
         建议分批调用，每批≤6只。已验证各批独立调用正常。

字段说明:
  parts[3]  = 现价（实时）  ← 必须用这个！
  parts[4]  = 昨收（昨天收盘价）
  parts[5]  = 开盘
  parts[32] = 涨跌幅%
  parts[33] = 最高
  parts[34] = 最低

⚠️ 关键坑：LLM agent在cron任务中容易把parts[4]（昨收）误用为parts[3]（现价），
导致报告中所有价格都等于昨天收盘价。务必用此脚本获取准确数据。
"""
import sys
import json
import urllib.request

def auto_prefix(code):
    """根据代码自动加市场前缀"""
    code = code.strip()
    if code.startswith(('sh', 'sz')):
        return code
    if code.startswith(('6', '9')):
        return f'sh{code}'
    elif code.startswith(('0', '3')):
        return f'sz{code}'
    return f'sh{code}'

def fetch_quotes(codes):
    """批量获取实时行情，返回dict列表"""
    symbols = [auto_prefix(c) for c in codes]
    url = f'https://qt.gtimg.cn/q={",".join(symbols)}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode('gbk')

    results = []
    for line in data.strip().split(';'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        parts = line.split('~')
        if len(parts) < 40:
            continue
        yesterday_val = float(parts[4]) if parts[4] else 0
        current_val = float(parts[3]) if parts[3] else 0
        api_chg = float(parts[32]) if parts[32] else None
        if api_chg is not None:
            chg = api_chg
        elif yesterday_val > 0 and current_val > 0:
            chg = round((current_val / yesterday_val - 1) * 100, 2)
        else:
            chg = 0
        results.append({
            'name': parts[1],
            'code': parts[2],
            'current': current_val,       # ⭐ 现价
            'yesterday': yesterday_val,      # 昨收
            'open': float(parts[5]) if parts[5] else 0,
            'change_amt': float(parts[31]) if parts[31] else 0,   # 涨跌额
            'change_pct': chg,
            'high': float(parts[33]) if parts[33] else 0,
            'low': float(parts[34]) if parts[34] else 0,
            'volume': float(parts[36]) if parts[36] else 0,       # 成交量(手)
            'amount': float(parts[37]) if parts[37] else 0,       # 成交额(万元)
            'turnover': float(parts[38]) if parts[38] else 0,     # 换手率%
            'pe': float(parts[39]) if len(parts) > 39 and parts[39] else 0,            # 市盈率
            'circ_market_cap': float(parts[44]) if len(parts) > 44 and parts[44] else 0,  # 流通市值(亿)
            'total_market_cap': float(parts[45]) if len(parts) > 45 and parts[45] else 0, # 总市值(亿)
            'limit_up': float(parts[47]) if len(parts) > 47 and parts[47] else 0,      # 涨停价
            'limit_down': float(parts[48]) if len(parts) > 48 and parts[48] else 0,    # 跌停价
        })
    return results

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 realtime_quotes.py 600936 300455 ...")
        sys.exit(1)

    quotes = fetch_quotes(sys.argv[1:])

    # 输出格式化表格
    print(f"{'股票':<10} {'代码':<8} {'现价':>8} {'涨跌%':>8} {'开盘':>8} {'最高':>8} {'最低':>8} {'昨收':>8}")
    print('-' * 80)
    for q in quotes:
        sign = '+' if q['change_pct'] >= 0 else ''
        print(f"{q['name']:<10} {q['code']:<8} {q['current']:>8.2f} {sign}{q['change_pct']:>7.2f}% {q['open']:>8.2f} {q['high']:>8.2f} {q['low']:>8.2f} {q['yesterday']:>8.2f}")

    print()
    print("--- JSON ---")
    print(json.dumps(quotes, ensure_ascii=False, indent=2))
