#!/usr/bin/env python3
"""
V10 尾盘信号摘要 (14:30)
直接从全扫描的watchlist里读信号，不做重新扫描。
只做：读取信号 + 补充基本面验证 + 输出推荐
"""
import json, os, sys, urllib.request

WATCHLIST = os.path.expanduser("~/.hermes/cache/v10_watchlist.json")
HOME = os.path.expanduser("~")

def log(msg):
    print(msg, flush=True)

def get_realtime(code):
    """腾讯实时行情"""
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
            'price': float(parts[3]) if parts[3] else 0,
            'change': float(parts[32]) if parts[32] else 0,
            'amount': float(parts[37]) if parts[37] else 0,
            'volume': float(parts[6]) if parts[6] else 0,
            'high': float(parts[33]) if parts[33] else 0,
            'low': float(parts[34]) if parts[34] else 0,
            'open': float(parts[5]) if parts[5] else 0,
            'yclose': float(parts[4]) if parts[4] else 0
        }
    except:
        return None

def load_cache():
    if not os.path.exists(WATCHLIST):
        return None
    with open(WATCHLIST) as f:
        return json.load(f)

# ---- MAIN ----
data = load_cache()
if not data:
    log("❌ 未找到全扫描缓存 (v10_watchlist.json)，请先执行全扫描")
    sys.exit(0)

stocks = data.get('stocks', [])
scan_time = data.get('scan_time', '未知')
log(f"📊 V10 尾盘信号摘要 (14:30)")
log(f"━━━━━━━━━━━━━━━━━━━━━━")
log(f"全扫描数据时间: {scan_time}")
log(f"备选信号: {len(stocks)} 只")
log("")

# 过滤当天可用信号
# ★★★全买入 = 强信号, ★★☆强庄买 = 中等, ★☆☆基础买 = 弱
strong = [s for s in stocks if '★★★' in s.get('signal', '')]
medium = [s for s in stocks if '★★☆' in s.get('signal', '')]
weak = [s for s in stocks if '★☆☆' in s.get('signal', '')]

# 获取最新实时行情确认尾盘情况
for s in stocks:
    rt = get_realtime(s['code'])
    if rt:
        s['realtime_price'] = rt['price']
        s['realtime_change'] = rt['change']

log(f"🏆 全买入信号 (★★★): {len(strong)} 只")
for s in strong:
    name = s.get('name', '')
    code = s.get('code', '')
    price = s.get('realtime_price', s.get('price', 0))
    chg = s.get('realtime_change', s.get('change', 0))
    cap = s.get('capital_note', '')
    log(f"  {name}({code}) ¥{price:.2f} {chg:+.2f}% {cap}")

log("")
log(f"⚡ 强庄买入 (★★☆): {len(medium)} 只")
for s in medium:
    name = s.get('name', '')
    code = s.get('code', '')
    price = s.get('realtime_price', s.get('price', 0))
    chg = s.get('realtime_change', s.get('change', 0))
    cap = s.get('capital_note', '')
    log(f"  {name}({code}) ¥{price:.2f} {chg:+.2f}% {cap}")

log("")
log(f"📎 基础买入 (★☆☆): {len(weak)} 只")
for s in weak:
    name = s.get('name', '')
    code = s.get('code', '')
    price = s.get('realtime_price', s.get('price', 0))
    chg = s.get('realtime_change', s.get('change', 0))
    cap = s.get('capital_note', '')
    log(f"  {name}({code}) ¥{price:.2f} {chg:+.2f}% {cap}")

log("")
log("=" * 40)

# 推荐结论
if strong:
    log(f"\n✅ 推荐关注: 全买入信号 ★★★")
    for s in strong:
        name = s.get('name', '')
        code = s.get('code', '')
        sname = s.get('signal', '')
        chg = s.get('realtime_change', 0)
        log(f"  → {name}({code}) {chg:+.2f}% | {sname}")
elif medium:
    log(f"\n✅ 推荐关注: 强庄买入信号 ★★☆")
    for s in medium[:3]:
        name = s.get('name', '')
        code = s.get('code', '')
        chg = s.get('realtime_change', 0)
        log(f"  → {name}({code}) {chg:+.2f}%")
elif weak:
    log(f"\n📌 仅基础买入信号 ★☆☆，需谨慎")
else:
    log(f"\n⛔ 今日尾盘无V10进场信号")
    log(f"   继续保持空仓等待")
