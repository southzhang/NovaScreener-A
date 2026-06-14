#!/usr/bin/env python3
"""
V10 尾盘信号摘要 (14:30)
从全扫描watchlist读取信号 → 多层把关筛选 → 评分 → 推荐

把关流程：
  1. 信号等级过滤：基础买只进观察池，不推荐
  2. 基本面排雷：ST/低ROE/亏损股排除（iFinD，可降级）
  3. 资金面验证：主力净流出排除（缓存+iFinD，可降级）
  4. 涨停价确认：已涨停/接近涨停排除
  5. 评分门槛：60分以下不推荐，40分以下从观察池移除
  6. 冷静期检查：连续全亏暂停推荐

输出格式：
  🏆 推荐买入 (TOP1-2，带详细信息)
  👁️ 观察池 (基础买+低分候选，仅供参考)
  ⚠️ 被过滤 (列出排除原因)
"""
import json, os, sys, time, urllib.request
from datetime import datetime

# 评分模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v10_scorer import score_stock, load_capital_flow, load_fundamental_data

WATCHLIST = os.path.expanduser("~/.hermes/cache/v10_watchlist.json")
CACHE_DIR = os.path.expanduser("~/.hermes/cache")
TRACKER_PATH = os.path.expanduser("~/.hermes/cache/tail_rec_tracker.json")

# 信号等级排序权重
SIGNAL_RANK = {"全买入": 3, "强庄买": 2, "基础买": 1}
SIGNAL_EMOJI = {"全买入": "🔴", "强庄买": "🟠", "基础买": "🟡"}

# ===== 把关阈值 =====
SCORE_RECOMMEND_MIN = 55   # 推荐最低评分（旧值60→50→45→55，与扫描选股60分门槛对齐，强庄买+10后55≈原始45）
SCORE_OBSERVE_MIN = 30     # 观察池最低评分（旧值40→35→30，基础买数据不全时容易不够）
COOLDOWN_LOSS_STREAK = 3   # 连续全亏次数触发冷静期
LIMIT_UP_PCT = 9.5         # 涨停阈值（%），接近此值排除
NEAR_LIMIT_UP_PCT = 9.0    # 接近涨停阈值

# 信号等级动态门槛：强信号放宽门槛，弱信号保持严格
# 理由：全买入/强庄买本身就是强确认，评分维度扣分不应过度惩罚
SIGNAL_SCORE_BONUS = {
    "全买入": 15,   # 全买入额外加15分信号确认分
    "强庄买": 10,   # 强庄买额外加10分信号确认分
    "基础买": 0,    # 基础买不加
}


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
        parts = raw.split('=')[1].strip('";\n').split('~')
        if len(parts) < 50:
            return None
        return {
            'price': float(parts[3]) if parts[3] else 0,
            'change': float(parts[32]) if parts[32] else 0,
            'amount': float(parts[37]) if parts[37] else 0,
            'volume': float(parts[36]) if parts[36] else 0,
            'high': float(parts[33]) if parts[33] else 0,
            'low': float(parts[34]) if parts[34] else 0,
            'open': float(parts[5]) if parts[5] else 0,
            'yclose': float(parts[4]) if parts[4] else 0,
            'limit_up': float(parts[47]) if len(parts) > 47 and parts[47] else 0,
            'limit_down': float(parts[48]) if len(parts) > 48 and parts[48] else 0,
            'pe': float(parts[39]) if parts[39] else 0,
            'turnover_rate': float(parts[38]) if parts[38] else 0,
            'circ_cap': float(parts[44]) if len(parts) > 44 and parts[44] else 0,
        }
    except Exception:
        return None


def load_watchlist():
    """加载watchlist缓存"""
    if not os.path.exists(WATCHLIST):
        return None
    with open(WATCHLIST) as f:
        return json.load(f)


# ===== 把关1: 冷静期检查 =====
def check_cooldown():
    """检查是否处于冷静期（连续N次全亏）"""
    if not os.path.exists(TRACKER_PATH):
        return False, None
    try:
        with open(TRACKER_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return False, None

    recs = data.get("recommendations", [])
    if not recs:
        return False, None

    # 从最近往回数，连续全亏次数
    consecutive_loss = 0
    for rec in sorted(recs, key=lambda x: x.get("date", ""), reverse=True):
        nd = rec.get("next_day", {})
        if not nd:
            continue  # 未验证的跳过
        # 检查该日是否全亏
        all_loss = all(v.get("pnl_pct", 0) < 0 for v in nd.values())
        if all_loss:
            consecutive_loss += 1
        else:
            break

    if consecutive_loss >= COOLDOWN_LOSS_STREAK:
        until = data.get("cooldown_until")
        return True, until
    return False, None


# ===== 把关2: 涨停价确认 =====
def check_limit_up(code, rt_quote):
    """检查是否涨停/接近涨停，返回 (is_excluded, reason)"""
    if not rt_quote:
        return False, None

    price = rt_quote.get('price', 0)
    change_pct = rt_quote.get('change', 0)
    limit_up = rt_quote.get('limit_up', 0)
    yclose = rt_quote.get('yclose', 0)

    # 方法1: 用涨停价判断
    if limit_up > 0 and price > 0:
        if price >= limit_up:
            return True, f"已涨停 ¥{price:.2f}=涨停价¥{limit_up:.2f}"
        # 距涨停价2%以内
        near_pct = (limit_up - price) / price * 100
        if near_pct < 2.0:
            return True, f"接近涨停 ¥{price:.2f}，距涨停价仅{near_pct:.1f}%"

    # 方法2: 用涨幅判断（无涨停价数据时）
    if change_pct >= LIMIT_UP_PCT:
        return True, f"涨幅{change_pct:+.1f}%≥{LIMIT_UP_PCT}%（涨停/近涨停）"

    return False, None


# ===== 把关3: 基本面排雷（可降级） =====
def filter_fundamental_safe(stocks):
    """基本面过滤，iFinD不可用时降级跳过"""
    try:
        from v10_fundamental_filter import filter_by_fundamental
        passed, rejected = filter_by_fundamental(stocks)
        reject_map = {}
        # 提取拒绝原因
        for r in rejected:
            orig = r["stock"]
            code = orig.get("code", orig) if isinstance(orig, dict) else str(orig)
            reasons = "; ".join(r["reasons"])
            reject_map[code] = reasons
        passed_codes = set()
        for s in passed:
            if isinstance(s, dict):
                passed_codes.add(s.get("code", ""))
            else:
                passed_codes.add(str(s))
        return passed_codes, reject_map
    except ImportError:
        log("  ⚠️ v10_fundamental_filter不可用，跳过基本面过滤")
        return None, {}
    except Exception as e:
        log(f"  ⚠️ 基本面过滤异常: {e}，跳过")
        return None, {}


# ===== 把关4: 资金面验证（可降级） =====
def filter_capital_safe(codes):
    """资金面过滤，不可用时降级跳过"""
    try:
        from v10_capital_filter import filter_by_capital_flow
        # 转换为iFinD格式
        ifind_codes = []
        for c in codes:
            if "." in c:
                ifind_codes.append(c)
            elif c.startswith("6"):
                ifind_codes.append(f"{c}.SH")
            else:
                ifind_codes.append(f"{c}.SZ")
        result = filter_by_capital_flow(ifind_codes)
        passed_bare = set(_strip_suffix(c) for c in result["passed"])
        reject_map = {}
        for ex in result.get("excluded", []):
            bare = _strip_suffix(ex["code"])
            reject_map[bare] = ex["reason"]
        return passed_bare, reject_map
    except ImportError:
        log("  ⚠️ v10_capital_filter不可用，跳过资金面验证")
        return None, {}
    except Exception as e:
        log(f"  ⚠️ 资金面过滤异常: {e}，跳过")
        return None, {}


def _strip_suffix(code):
    return code.split(".")[0] if "." in code else code


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
    # 基础买评分≥60的也进入推荐池（旧逻辑直接排除，导致优质基础买永远无法推荐）
    recommend_pool = [s for s in stocks if s.get("signal") in ("全买入", "强庄买")]
    base_buy_pool = [s for s in stocks if s.get("signal") == "基础买"]
    observe_pool = []  # 基础买先不进观察池，评分后再分流
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

    # 基础买评分分流：≥60进推荐池，40-59进观察池，<40排除
    for s in scored_base:
        if s["score"] >= SCORE_RECOMMEND_MIN:
            scored_recommend.append(s)
            log(f"  ⬆️ {s['name']}({s['code']}) 基础买评分{s['score']}≥{SCORE_RECOMMEND_MIN}，升级到推荐池")
        elif s["score"] >= SCORE_OBSERVE_MIN:
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
        try:
            _sync_to_tracker(filtered_recommend[:_top_n], date_str=scan_time[:10] if scan_time[:4].isdigit() else datetime.now().strftime("%Y-%m-%d"))
        except Exception as e:
            log(f"⚠️ 同步追踪器失败: {e}")


def _build_recommend_json(recommend, observe, excluded, scan_time, cooldown=False):
    """输出结构化推荐JSON，供页面读取进场建议"""
    # 动态止损/目标价计算
    def _calc_levels(stock):
        price = stock.get("price", 0) or 0
        sig = stock.get("signal", "基础买")
        if price <= 0:
            return {}
        if sig == "全买入":
            stop_pct, target_pct, pos = 0.08, 0.15, "25%"
        elif sig == "强庄买":
            stop_pct, target_pct, pos = 0.10, 0.12, "20%"
        else:
            stop_pct, target_pct, pos = 0.14, 0.08, "10%"
        stop_loss = round(price * (1 - stop_pct), 2)
        target = round(price * (1 + target_pct), 2)
        risk_reward = (target - price) / (price - stop_loss) if (price - stop_loss) > 0 else 0
        return {
            "entry_price": price,
            "stop_loss": stop_loss,
            "stop_pct": f"-{stop_pct*100:.0f}%",
            "target": target,
            "target_pct": f"+{target_pct*100:.0f}%",
            "position": pos,
            "risk_reward": f"{risk_reward:.1f}:1",
        }

    def _stock_entry(stock, action, reason=""):
        sig = stock.get("signal", "基础买")
        levels = _calc_levels(stock)
        return {
            "code": stock.get("code", ""),
            "name": stock.get("name", ""),
            "signal": sig,
            "signal_emoji": SIGNAL_EMOJI.get(sig, "⚪"),
            "score": stock.get("score", 0),
            "price": stock.get("price", 0),
            "change_pct": stock.get("change_pct", 0),
            "action": action,  # "推荐进场" / "观察" / "不建议"
            "reason": reason,
            **levels,
        }

    rec_list = []
    for s in recommend:
        reason = "综合评分达标，信号确认度高"
        if s.get("_fundamental_penalty"):
            reason += "（基本面扣分保留）"
        if s.get("_capital_penalty"):
            reason += "（资金面扣分保留）"
        rec_list.append(_stock_entry(s, "推荐进场", reason))

    obs_list = []
    for s in observe:
        if isinstance(s, dict):
            obs_list.append(_stock_entry(s, "观察", "评分未达推荐门槛或基础买信号"))

    exc_list = []
    for s, reason in excluded:
        exc_list.append(_stock_entry(s, "不建议", reason))

    result = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan_time": scan_time,
        "recommend": rec_list,
        "observe": obs_list,
        "excluded": exc_list,
        "summary": {
            "recommend_count": len(rec_list),
            "observe_count": len(obs_list),
            "excluded_count": len(exc_list),
            "in_cooldown": cooldown,
        },
    }

    json_path = os.path.join(CACHE_DIR, "v10_tail_recommend.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"📊 推荐JSON已写入 {json_path} (推荐{len(rec_list)} 观察{len(obs_list)} 排除{len(exc_list)})")


def _sync_to_tracker(recommendations, date_str=None):
    """将推荐结果写入 tail_rec_tracker.json"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # 构造推荐记录
    stocks = []
    for r in recommendations:
        price = r.get("price", 0) or 0
        sig = r.get("signal", "基础买")
        # 动态止损
        stop_pct = 0.08 if sig == "全买入" else (0.10 if sig == "强庄买" else 0.14)
        stocks.append({
            "code": r.get("code", ""),
            "name": r.get("name", ""),
            "price": price,
            "signal": sig,
            "score": r.get("score", 0),
            "stop_loss": round(price * (1 - stop_pct), 2) if price > 0 else 0,
        })

    if not stocks:
        return

    # 读取现有 tracker
    if os.path.exists(TRACKER_PATH):
        try:
            with open(TRACKER_PATH) as f:
                tracker = json.load(f)
        except (json.JSONDecodeError, IOError):
            tracker = {"recommendations": [], "cooldown_until": None, "stats": {}}
    else:
        tracker = {"recommendations": [], "cooldown_until": None, "stats": {}}

    recs = tracker.get("recommendations", [])

    # 检查是否已有同日推荐（避免重复）
    existing_codes = set()
    for rec in recs:
        if rec.get("date") == date_str:
            for s in rec.get("stocks", []):
                existing_codes.add(s.get("code"))

    new_codes = [s["code"] for s in stocks if s["code"] not in existing_codes]
    if not new_codes:
        log(f"📋 追踪器: {date_str} 已有推荐记录，跳过重复写入")
        return

    # 追加新推荐
    recs.append({
        "date": date_str,
        "stocks": stocks,
        "validated": False,
        "next_day": {},
        "three_day": {},
        "source": "v10_tail_summary",
    })
    # 只保留最近30条
    tracker["recommendations"] = recs[-30:]

    os.makedirs(os.path.dirname(TRACKER_PATH), exist_ok=True)
    with open(TRACKER_PATH, 'w') as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)

    log(f"📋 已同步{len(new_codes)}只推荐到追踪器: {', '.join(new_codes)}")


if __name__ == "__main__":
    main()
