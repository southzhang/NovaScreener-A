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
        results.append({
            'name': parts[1],
            'code': parts[2],
            'current': float(parts[3]),       # ⭐ 现价
            'yesterday': float(parts[4]),      # 昨收
            'open': float(parts[5]),
            'high': float(parts[33]),
            'low': float(parts[34]),
            'change_pct': float(parts[32]) if parts[32] else 0,
            'change_amt': float(parts[31]) if parts[31] else 0,
            'volume': parts[36],
            'amount': parts[37],
            'turnover': parts[38],
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
