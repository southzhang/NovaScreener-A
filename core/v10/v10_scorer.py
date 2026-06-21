#!/usr/bin/env python3
"""V10综合评分系统 - 对V10观察池股票进行多维度评分并生成推荐"""

import json
import os
import sys
import time
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

# 添加scripts目录到路径
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from sector_analysis import get_sector_score, get_sector_ranking, get_stock_sector

WORKSPACE = os.path.expanduser("~/.hermes/workspace")
CACHE_DIR = os.path.expanduser("~/.hermes/cache")
HOLDINGS_FILE = os.path.join(WORKSPACE, "v10_holdings.json")
SIGNAL_LOG = os.path.join(WORKSPACE, "v10_signal_log.json")
CAPITAL_FLOW_CACHE = os.path.join(CACHE_DIR, "capital_flow.json")

HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_url(url, timeout=8):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("gbk", errors="ignore")
    except Exception as e:
        print(f"  ⚠️ 请求失败 {url[:60]}... {e}", file=sys.stderr)
        return None


# ── 实时行情 ──────────────────────────────────────────────
def get_realtime(code):
    """返回 {price, change_pct, amount_wan, circ_yi} 或 None"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    text = fetch_url(url)
    if not text or "=" not in text:
        return None
    parts = text.split("=")[1].strip('";\n').split("~")
    if len(parts) < 50:
        return None
    price_val = float(parts[3]) if parts[3] else 0
    yclose_val = float(parts[4]) if parts[4] else 0
    api_chg = float(parts[32]) if parts[32] else None
    if api_chg is not None:
        chg = api_chg
    elif yclose_val > 0 and price_val > 0:
        chg = round((price_val / yclose_val - 1) * 100, 2)
    else:
        chg = 0
    try:
        return {
            "price": price_val,
            "change_pct": chg,
            "amount_wan": float(parts[37]) if parts[37] else 0,
            "circ_yi": float(parts[44]) if len(parts) > 44 and parts[44] else 0,
            "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
            "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
            "open": float(parts[5]) if parts[5] else 0,
            "volume": float(parts[36]) if len(parts) > 36 and parts[36] else 0,
        }
    except (ValueError, IndexError):
        return None


# ── K线振幅分位 ───────────────────────────────────────────
def _is_trading_day() -> bool:
    """判断今天是否可能是交易日（工作日）
    
    简单判断：周一至周五。法定节假日无法精确判断，
    但腾讯行情有成交量>0可兜底。
    """
    return datetime.now().weekday() < 5


def get_amplitude_percentile(code):
    """计算当前振幅在近30日的分位数(0-100)（盘中/盘后自动拼接今日数据）"""
    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"
    url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={symbol},day,,,30,qfq"
    text = fetch_url(url)
    if not text:
        return None
    try:
        data = json.loads(text.split("=", 1)[1] if "=" in text else text)
        klines = data["data"][symbol].get("day") or data["data"][symbol].get("qfqday") or []
    except (json.JSONDecodeError, KeyError):
        return None
    if len(klines) < 5:
        return None
    # 盘中/盘后拼接今日K线（只要当天有成交就拼，不限时段）
    if _is_trading_day():
        today_str = datetime.now().strftime("%Y-%m-%d")
        if not klines[-1][0].startswith(today_str):
            rt = get_realtime(code)
            if rt and rt.get("high", 0) > 0 and rt.get("low", 0) > 0 and rt.get("volume", 0) > 0:
                # 休市日防护：OHLC与最后一条K线一致→不拼
                last_k = klines[-1]
                if (float(last_k[1]) == rt["open"] and float(last_k[2]) == rt["high"] and
                    float(last_k[3]) == rt["low"] and abs(float(last_k[4]) - rt["price"]) < 0.001):
                    pass  # 休市日缓存数据，不拼
                else:
                    today_bar = [today_str, str(rt["open"]), str(rt["high"]),
                                 str(rt["low"]), str(rt["price"]), str(rt.get("volume", 0))]
                    klines.append(today_bar)
    amps = []
    for k in klines:
        hi, lo = float(k[2]), float(k[3])
        if lo > 0:
            amps.append((hi - lo) / lo * 100)
    if not amps:
        return None
    today_amp = amps[-1]
    below = sum(1 for a in amps if a <= today_amp)
    return below / len(amps) * 100


# ── 资金面缓存 ────────────────────────────────────────────
def load_capital_flow():
    """从缓存加载资金面数据 {code: net_inflow_wan}"""
    if not os.path.exists(CAPITAL_FLOW_CACHE):
        return {}
    try:
        with open(CAPITAL_FLOW_CACHE) as f:
            raw = json.load(f)
        result = {}
        for item in raw if isinstance(raw, list) else []:
            c = item.get("code", "")
            net = item.get("net_inflow", 0)  # 万元
            result[c] = net
        return result
    except Exception:
        return {}


# ── 基本面缓存 ────────────────────────────────────────────
def load_fundamental_data():
    """尝试从v10_fundamental_filter的输出获取ROE数据"""
    cache_file = os.path.join(CACHE_DIR, "fundamental_data.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# ── 评分核心 ──────────────────────────────────────────────
def score_stock(code, name, signal_level, key_levels=None, capital_flow=None, fundamental=None):
    """对单只股票打分，返回 (total, details_dict)"""
    details = {}
    total = 0

    # 1. V10信号级别 (30分)
    signal_map = {"全买入": 30, "强庄买": 20, "基础买": 10}
    sig_score = signal_map.get(signal_level, 0)
    details["V10信号"] = (sig_score, 30, signal_level or "无信号")
    total += sig_score

    # 2. 基本面 (15分) - ROE
    fund = (fundamental or {}).get(code, {})
    roe = fund.get("roe")
    if roe is not None:
        if roe > 10:
            f_score = 15
        elif roe >= 5:
            f_score = 7.5
        else:
            f_score = 0
        details["基本面"] = (f_score, 15, f"ROE {roe:.1f}%")
    else:
        details["基本面"] = (7.5, 15, "ROE 未知(给半分)")
        f_score = 7.5
    total += f_score

    # 3. 资金面 (20分) - 主力净流入
    cap = (capital_flow or {}).get(code, 0)
    if cap > 5000:
        c_score = 20
        c_desc = f"主力净流入+{cap/10000:.1f}亿"
    elif cap > 0:
        c_score = 10
        c_desc = f"主力净流入+{cap:.0f}万"
    else:
        c_score = 0
        c_desc = f"主力净流出{cap:.0f}万"
    details["资金面"] = (c_score, 20, c_desc)

    # 4. 振幅分位 (15分)
    amp_pct = get_amplitude_percentile(code)
    if amp_pct is not None:
        if amp_pct < 40:
            a_score = 15
            a_desc = f"{amp_pct:.0f}%低位"
        elif amp_pct <= 60:
            a_score = 7.5
            a_desc = f"{amp_pct:.0f}%中位"
        else:
            a_score = 0
            a_desc = f"{amp_pct:.0f}%高位"
    else:
        a_score = 7.5
        a_desc = "数据缺失(给半分)"
    details["振幅分位"] = (a_score, 15, a_desc)
    total += a_score

    # 获取实时行情用于板块风口和追高风险
    rt = get_realtime(code)
    change_pct = rt["change_pct"] if rt else 0

    # 5. 板块风口 (10分) - 使用板块分析模块
    w_score, w_desc = get_sector_score(code, change_pct)
    details["板块风口"] = (w_score, 10, w_desc)
    total += w_score

    # 6. 追高风险 (10分) - 06-09升级：Vibe≥+2强时追高豁免
    # 新规则：强力趋势票不该因"涨多了"就一票否决
    # - 涨幅<3%: 满分10
    # - 涨幅3-5%: 5分
    # - 涨幅>5%: 但如果是强趋势(V10全买入+资金流入>0)，给5分而非0分
    #   （LLM Vibe≥+2会在后续合并时进一步豁免追高扣分）
    # 一票否决线：主板9.5%，创业板/科创板19%（按涨跌幅限制分档）
    price_limit_pct = 20.0 if code.startswith(("300", "688")) else 10.0
    hard_limit_pct = price_limit_pct * 0.95  # 9.5% 或 19%
    if abs(change_pct) >= hard_limit_pct:
        r_score = 0
        r_desc = f"涨幅{change_pct:+.1f}%接近涨停(限制{price_limit_pct:.0f}%)，一票否决"
        details["追高风险"] = (r_score, 10, r_desc)
        total += r_score
    elif abs(change_pct) < 3:
        r_score = 10
        r_desc = f"涨幅{change_pct:+.1f}%安全"
        details["追高风险"] = (r_score, 10, r_desc)
        total += r_score
    elif abs(change_pct) <= 5:
        r_score = 5
        r_desc = f"涨幅{change_pct:+.1f}%适中"
        details["追高风险"] = (r_score, 10, r_desc)
        total += r_score
    else:
        # 涨幅>5%：强趋势给5分(不完全否定)，弱趋势0分
        if signal_level in ("全买入", "强庄买") and (capital_flow or {}).get(code, 0) > 0:
            r_score = 5
            r_desc = f"涨幅{change_pct:+.1f}%但强趋势+资金流入，追高可接受"
        else:
            r_score = 0
            r_desc = f"涨幅{change_pct:+.1f}%追高"
        details["追高风险"] = (r_score, 10, r_desc)
        total += r_score

    price = rt["price"] if rt else 0
    return round(total), details, price, change_pct


# ── 持仓评分 ──────────────────────────────────────────────
def score_holdings(holdings_data=None):
    """对当前持仓打分"""
    if holdings_data is None:
        holdings_data = load_holdings()
    holdings = holdings_data.get("holdings", [])
    if not holdings:
        return []

    capital_flow = load_capital_flow()
    fundamental = load_fundamental_data()
    results = []

    for h in holdings:
        code, name = h["code"], h["name"]
        # 持仓用当前信号级别(如果没有信号则用基础买)
        sig = h.get("signal_level", "基础买")
        total, details, price, change = score_stock(
            code, name, sig, capital_flow=capital_flow, fundamental=fundamental
        )
        cost = h.get("cost", 0)
        shares = h.get("shares", 0)
        pnl_pct = ((price - cost) / cost * 100) if cost > 0 else 0
        results.append({
            "code": code, "name": name, "score": total, "details": details,
            "price": price, "change_pct": change, "cost": cost,
            "shares": shares, "pnl_pct": round(pnl_pct, 2)
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ── 持仓文件管理 ──────────────────────────────────────────
def load_holdings():
    os.makedirs(WORKSPACE, exist_ok=True)
    if os.path.exists(HOLDINGS_FILE):
        with open(HOLDINGS_FILE) as f:
            return json.load(f)
    return {"holdings": [], "max_count": 3}


def save_holdings(data):
    os.makedirs(WORKSPACE, exist_ok=True)
    data["last_update"] = datetime.now().strftime("%Y-%m-%d")
    with open(HOLDINGS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── V10信号池加载 ─────────────────────────────────────────
def load_watch_pool():
    """从signal_log加载最近的V10观察池（最近1天的pending信号）"""
    if not os.path.exists(SIGNAL_LOG):
        return []
    try:
        with open(SIGNAL_LOG) as f:
            data = json.load(f)
        records = data.get("records", [])
        if not records:
            return []
        # 取最近日期的pending信号
        dates = sorted(set(r.get("date", "") for r in records), reverse=True)
        latest_date = dates[0]
        pool = []
        seen = set()
        for r in records:
            if r.get("date") == latest_date and r.get("result") == "pending":
                code = r.get("code", "")
                if code not in seen:
                    seen.add(code)
                    pool.append({
                        "code": code,
                        "name": r.get("name", ""),
                        "signal_level": r.get("signal_level", "基础买"),
                        "buy_price": r.get("buy_price"),
                    })
        return pool
    except Exception as e:
        print(f"  ⚠️ 加载信号日志失败: {e}", file=sys.stderr)
        return []


# ── 扫描评分 ──────────────────────────────────────────────
def cmd_scan():
    """对V10观察池评分排序"""
    pool = load_watch_pool()
    if not pool:
        print("⚠️ V10观察池为空，请先运行 v10_realtime_scan.py")
        return

    capital_flow = load_capital_flow()
    fundamental = load_fundamental_data()
    results = []

    print(f"📊 V10综合评分 | {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    for item in pool:
        code = item.get("code", "")
        name = item.get("name", "")
        sig = item.get("signal_level", item.get("signal", "基础买"))
        key_levels = item.get("key_levels", {})

        total, details, price, change = score_stock(
            code, name, sig, key_levels, capital_flow, fundamental
        )
        results.append({
            "code": code, "name": name, "score": total, "details": details,
            "signal": sig, "price": price, "change_pct": change
        })
        time.sleep(0.3)  # 限速

    results.sort(key=lambda x: x["score"], reverse=True)

    # 输出Markdown表格
    lines = []
    lines.append(f"🏆 **V10综合评分排行** | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("| 排名 | 股票 | 评分 | 信号 | 现价 | 涨幅 |")
    lines.append("|:----:|------|:----:|------|-----:|-----:|")
    for i, r in enumerate(results, 1):
        emoji = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else f"{i}."))
        lines.append(
            f"| {emoji} | {r['name']}({r['code']}) | **{r['score']}** | "
            f"{r['signal']} | {r['price']:.2f} | {r['change_pct']:+.1f}% |"
        )

    # TOP3详细评分
    lines.append("")
    for i, r in enumerate(results[:3], 1):
        lines.append(f"**TOP{i}: {r['name']}({r['code']}) 综合评分 {r['score']}分**")
        lines.append("| 维度 | 得分 | 详情 |")
        lines.append("|------|-----:|------|")
        for dim, (sc, max_sc, desc) in r["details"].items():
            lines.append(f"| {dim} | {sc}/{max_sc} | {desc} |")
        lines.append("")

    output = "\n".join(lines)
    print(output)
    return results


# ── 推荐 ──────────────────────────────────────────────────
def cmd_recommend():
    """生成推荐（考虑持仓）"""
    holdings_data = load_holdings()
    holdings = holdings_data.get("holdings", [])
    max_count = holdings_data.get("max_count", 3)

    # 先扫描评分
    pool = load_watch_pool()
    if not pool:
        print("⚠️ V10观察池为空")
        return

    capital_flow = load_capital_flow()
    fundamental = load_fundamental_data()

    # 评分观察池
    candidates = []
    for item in pool:
        code = item.get("code", "")
        name = item.get("name", "")
        sig = item.get("signal_level", item.get("signal", "基础买"))
        total, details, price, change = score_stock(
            code, name, sig, capital_flow=capital_flow, fundamental=fundamental
        )
        candidates.append({
            "code": code, "name": name, "score": total, "details": details,
            "signal": sig, "price": price, "change_pct": change
        })
        time.sleep(0.3)

    candidates.sort(key=lambda x: x["score"], reverse=True)

    # 评分持仓
    holding_scores = score_holdings(holdings_data)
    holding_codes = {h["code"] for h in holdings}

    # 排除已持仓的候选
    new_candidates = [c for c in candidates if c["code"] not in holding_codes]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append(f"🏆 **V10综合推荐** | {now}")
    lines.append("")

    # 输出持仓评分
    if holding_scores:
        lines.append("**📋 当前持仓评分**")
        lines.append("| 股票 | 评分 | 成本 | 现价 | 盈亏 |")
        lines.append("|------|:----:|-----:|-----:|-----:|")
        for h in holding_scores:
            pnl_emoji = "📈" if h["pnl_pct"] >= 0 else "📉"
            lines.append(
                f"| {h['name']}({h['code']}) | **{h['score']}** | "
                f"{h['cost']:.3f} | {h['price']:.2f} | {pnl_emoji}{h['pnl_pct']:+.1f}% |"
            )
        lines.append("")

    if not new_candidates:
        lines.append("⚠️ 无可推荐的新标的")
        print("\n".join(lines))
        return

    top1 = new_candidates[0]

    # 决策逻辑
    if len(holdings) < max_count:
        # 仓位未满，推荐新增
        _format_buy_recommendation(lines, top1)
        action = "新增买入"
    elif holding_scores:
        worst = holding_scores[-1]
        if top1["score"] > worst["score"]:
            # 换股
            _format_switch_recommendation(lines, top1, worst)
            action = "换股"
        else:
            lines.append("✅ **继续持有** — 当前持仓评分均高于候选标的")
            lines.append(f"📌 持仓最低分: {worst['name']}({worst['code']}) {worst['score']}分")
            lines.append(f"📌 候选最高分: {top1['name']}({top1['code']}) {top1['score']}分")
            action = "持有"
    else:
        _format_buy_recommendation(lines, top1)
        action = "新增买入"

    print("\n".join(lines))
    return {"action": action, "candidates": candidates[:5], "holdings": holding_scores}


def generate_recommendation(candidates, holdings, max_count=5):
    """
    供其他脚本调用的推荐接口。
    参数:
        candidates: V10扫描结果列表，每项需有 code/name/signal_level/price/change/key_levels
        holdings: 当前持仓列表
        max_count: 持仓上限
    返回:
        推荐报告字符串，或None
    """
    if not candidates:
        return None

    capital_flow = load_capital_flow()
    fundamental = load_fundamental_data()

    # 评分候选
    scored = []
    for item in candidates:
        code = item.get("code", "")
        name = item.get("name", "")
        sig = item.get("signal_level", item.get("signal", "基础买"))
        total, details, price, change = score_stock(
            code, name, sig, key_levels=item.get("key_levels"),
            capital_flow=capital_flow, fundamental=fundamental
        )
        scored.append({
            "code": code, "name": name, "score": total, "details": details,
            "signal": sig, "price": price, "change_pct": change
        })
        time.sleep(0.2)

    scored.sort(key=lambda x: x["score"], reverse=True)

    # 评分持仓
    holdings_data = {"holdings": holdings, "max_count": max_count}
    holding_scores = score_holdings(holdings_data)
    holding_codes = {h["code"] for h in holdings}

    # 排除已持仓
    new_candidates = [c for c in scored if c["code"] not in holding_codes]

    if not new_candidates:
        return "⚠️ 无可推荐的新标的"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append(f"🏆 **V10综合推荐** | {now}")
    lines.append("")

    # 输出持仓评分
    if holding_scores:
        lines.append("**📋 当前持仓评分**")
        lines.append("| 股票 | 评分 | 成本 | 现价 | 盈亏 |")
        lines.append("|------|:----:|-----:|-----:|-----:|")
        for h in holding_scores:
            pnl_emoji = "📈" if h["pnl_pct"] >= 0 else "📉"
            lines.append(
                f"| {h['name']}({h['code']}) | **{h['score']}** | "
                f"{h['cost']:.3f} | {h['price']:.2f} | {pnl_emoji}{h['pnl_pct']:+.1f}% |"
            )
        lines.append("")

    top1 = new_candidates[0]

    # 决策逻辑
    if len(holdings) < max_count:
        _format_buy_recommendation(lines, top1)
    elif holding_scores:
        worst = holding_scores[-1]
        if top1["score"] > worst["score"]:
            _format_switch_recommendation(lines, top1, worst)
        else:
            lines.append("✅ **继续持有** — 当前持仓评分均高于候选标的")
            lines.append(f"📌 持仓最低分: {worst['name']}({worst['code']}) {worst['score']}分")
            lines.append(f"📌 候选最高分: {top1['name']}({top1['code']}) {top1['score']}分")
    else:
        _format_buy_recommendation(lines, top1)

    return "\n".join(lines)


def _format_buy_recommendation(lines, stock):
    price = stock["price"]
    stop_loss = round(price * 0.858, 2)  # -14.2%

    lines.append(f"**TOP1: {stock['name']}({stock['code']}) 综合评分 {stock['score']}分**")
    lines.append("| 维度 | 得分 | 详情 |")
    lines.append("|------|-----:|------|")
    for dim, (sc, max_sc, desc) in stock["details"].items():
        lines.append(f"| {dim} | {sc}/{max_sc} | {desc} |")
    lines.append("")
    lines.append("📌 **推荐：新增买入**")
    lines.append(f"💰 现价{price:.2f} | 仓位20%（约2万）")
    lines.append(f"📍 止损{stop_loss:.2f}（-14.2%）")
    lines.append("")


def _format_switch_recommendation(lines, new_stock, worst_stock):
    improvement = new_stock["score"] - worst_stock["score"]
    lines.append("🔄 **换股建议**")
    lines.append(f"❌ 卖出：{worst_stock['name']}({worst_stock['code']}) 评分{worst_stock['score']}分")
    lines.append(f"✅ 买入：{new_stock['name']}({new_stock['code']}) 评分{new_stock['score']}分")
    lines.append(f"📈 预期提升：+{improvement}分")
    lines.append("")
    lines.append(f"**新标的评分明细：**")
    lines.append("| 维度 | 得分 | 详情 |")
    lines.append("|------|-----:|------|")
    for dim, (sc, max_sc, desc) in new_stock["details"].items():
        lines.append(f"| {dim} | {sc}/{max_sc} | {desc} |")
    lines.append("")
    price = new_stock["price"]
    lines.append(f"💰 买入价{price:.2f} | 止损{price*0.858:.2f}（-14.2%）")


# ── 更新持仓 ──────────────────────────────────────────────
def cmd_update_holdings():
    """更新持仓状态"""
    data = load_holdings()
    print("当前持仓:")
    for i, h in enumerate(data.get("holdings", []), 1):
        print(f"  {i}. {h['name']}({h['code']}) 成本{h['cost']} {h['shares']}股")
    print(f"  上限: {data.get('max_count', 3)}只")
    print()

    new_holdings = []
    print("输入持仓（空行结束，格式: 代码 名称 成本 股数）:")
    while True:
        line = input("> ").strip()
        if not line:
            break
        parts = line.split()
        if len(parts) >= 4:
            new_holdings.append({
                "code": parts[0],
                "name": parts[1],
                "cost": float(parts[2]),
                "shares": int(parts[3])
            })
        elif len(parts) == 1 and parts[0].lower() == "done":
            break

    if new_holdings:
        data["holdings"] = new_holdings
        save_holdings(data)
        print(f"✅ 已更新 {len(new_holdings)} 只持仓")
    else:
        print("未做修改")


# ── 主入口 ────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("用法: python3 v10_scorer.py [scan|recommend|update_holdings]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "scan":
        cmd_scan()
    elif cmd == "recommend":
        cmd_recommend()
    elif cmd == "update_holdings":
        cmd_update_holdings()
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
