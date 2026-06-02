#!/usr/bin/env python3
"""
V10 尾盘信号摘要 (14:30)
从全扫描watchlist读取信号 → 评分 → 推荐TOP1-2 + 其余进表格

输出格式：
  🏆 推荐买入 (TOP1-2，带详细信息)
  📋 其余符合条件 (简洁表格：代码、名称、等级、评分)
"""
import json, os, sys, time, urllib.request
from datetime import datetime

# 评分模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v10_scorer import score_stock, load_capital_flow, load_fundamental_data

WATCHLIST = os.path.expanduser("~/.hermes/cache/v10_watchlist.json")
CACHE_DIR = os.path.expanduser("~/.hermes/cache")

# 信号等级排序权重
SIGNAL_RANK = {"全买入": 3, "强庄买": 2, "基础买": 1}
SIGNAL_EMOJI = {"全买入": "🔴", "强庄买": "🟠", "基础买": "🟡"}


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
            'yclose': float(parts[4]) if parts[4] else 0,
        }
    except Exception:
        return None


def load_watchlist():
    """加载watchlist缓存"""
    if not os.path.exists(WATCHLIST):
        return None
    with open(WATCHLIST) as f:
        return json.load(f)


def score_all_candidates(stocks):
    """对所有候选股评分，返回排序后的列表"""
    capital_flow = load_capital_flow()
    fundamental = load_fundamental_data()
    results = []

    for s in stocks:
        code = s.get("code", "")
        name = s.get("name", "")
        sig = s.get("signal", "基础买")
        key_levels = s.get("key_levels", {})

        try:
            total, details, price, change = score_stock(
                code, name, sig, key_levels,
                capital_flow=capital_flow, fundamental=fundamental
            )
        except Exception as e:
            log(f"  ⚠️ {name}({code}) 评分失败: {e}")
            total, details, price, change = 0, {}, 0, 0

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


def format_top_recommendation(lines, stock, rank_label):
    """格式化单个推荐股的详细信息"""
    price = stock["price"]
    change = stock["change_pct"]
    score = stock["score"]
    sig = stock["signal"]
    emoji = SIGNAL_EMOJI.get(sig, "⚪")

    # 止损价（-14.2%）
    stop_loss = round(price * 0.858, 2) if price > 0 else 0

    lines.append(f"**{rank_label} {emoji} {stock['name']}（{stock['code']}）**")
    lines.append(f"信号等级：{sig} | 综合评分：**{score}分**")
    lines.append(f"现价 ¥{price:.2f} | 涨幅 {change:+.1f}%")

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
        lines.append(f"📍 止损位：¥{stop_loss:.2f}（-14.2%）")
    lines.append("")


def format_others_table(lines, stocks):
    """格式化其余候选股的简洁表格"""
    if not stocks:
        return

    lines.append(f"📋 **其余符合条件**（{len(stocks)}只）")
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
    log(f"全扫描时间: {scan_time} | 信号数: {len(stocks)}只")
    log("")
    log("⏳ 正在评分...")

    # 评分所有候选
    scored = score_all_candidates(stocks)
    log(f"✅ 评分完成，{len(scored)}只候选")

    # ── 构建输出 ──
    lines = []
    lines.append("")
    lines.append(f"📊 **V10 尾盘信号摘要** | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"全扫描时间: {scan_time} | 信号数: {len(stocks)}只")
    lines.append("")

    # 推荐 TOP1-2
    top_n = min(2, len(scored))
    if top_n > 0:
        lines.append(f"🏆 **推荐买入**（TOP {top_n}）")
        lines.append("")
        for i, s in enumerate(scored[:top_n], 1):
            label = f"TOP{i}"
            format_top_recommendation(lines, s, label)

    # 其余进表格
    others = scored[top_n:]
    if others:
        format_others_table(lines, others)

    # 无信号兜底
    if not scored:
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


if __name__ == "__main__":
    main()
