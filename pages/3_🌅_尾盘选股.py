"""尾盘选股页面 — 大盘指数 · 信号概览 · 候选详情 · 板块热度 · 操作按钮"""
import time
import streamlit as st
import pandas as pd
from datetime import datetime, time as dt_time
from core.ui import inject_global_css, render_theme_toggle, render_page_header
from core.v10.data_service import (
    get_dashboard_data,
    get_watchlist,
    get_prefetch,
    get_summary,
    check_freshness,
    run_prefetch,
    run_summary,
    run_scan,
    WATCHLIST_PATH,
    PREFETCH_PATH,
    SUMMARY_PATH,
    RECOMMEND_PATH,
)

st.set_page_config(page_title="尾盘选股", page_icon="🌅", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("🌅 尾盘选股", "大盘指数 · 信号概览 · 候选详情 · 板块热度 · 一键操作")

# ===== 加载数据 =====
data = get_dashboard_data()
watchlist = data["watchlist"]
prefetch = data["prefetch"]
summary_text = data["summary"]
recommend = data["recommend"]
freshness = data["freshness"]

# 构建进场建议索引：code → recommend info
_action_map = {}
for item in recommend.get("recommend", []):
    _action_map[item.get("code", "")] = item
for item in recommend.get("observe", []):
    _action_map[item.get("code", "")] = item
for item in recommend.get("excluded", []):
    _action_map[item.get("code", "")] = item

# ===================================================================
# 1. 大盘指数概览
# ===================================================================
st.html('<h2 style="margin-top:0;">📊 大盘指数概览</h2>')

index_data = prefetch.get("index", {})
# 按常见顺序排列: 上证 / 深证 / 创业板 / 科创50
INDEX_ORDER = ["sh000001", "sz399001", "sz399006", "sh000688"]
INDEX_DEFAULTS = {
    "sh000001": {"name": "上证指数", "price": 0, "change_pct": 0, "amount": 0},
    "sz399001": {"name": "深证成指", "price": 0, "change_pct": 0, "amount": 0},
    "sz399006": {"name": "创业板指", "price": 0, "change_pct": 0, "amount": 0},
    "sh000688": {"name": "科创50", "price": 0, "change_pct": 0, "amount": 0},
}

idx_cols = st.columns(4)
for i, key in enumerate(INDEX_ORDER):
    idx = index_data.get(key, INDEX_DEFAULTS.get(key, {}))
    name = idx.get("name", INDEX_DEFAULTS.get(key, {}).get("name", key))
    price = idx.get("price", 0)
    pct = idx.get("change_pct", 0)
    amount = idx.get("amount", 0)

    if pct > 0:
        color = "var(--up-color)"
        arrow = "▲"
    elif pct < 0:
        color = "var(--down-color)"
        arrow = "▼"
    else:
        color = "var(--text-primary)"
        arrow = "—"

    # 成交额: 如果大于1亿则显示亿
    if amount > 1e8:
        amt_str = f"{amount / 1e8:.0f}亿"
    elif amount > 1e4:
        amt_str = f"{amount / 1e4:.0f}万"
    else:
        amt_str = f"{amount:.0f}"

    with idx_cols[i]:
        st.html(f"""
        <div class="dash-card" style="text-align:center;">
            <div class="dash-card-header">{name}</div>
            <div class="dash-card-value" style="color:{color}; font-size:1.3em;">
                {arrow} {price:.2f}
            </div>
            <div class="dash-card-sub" style="color:{color};">
                {arrow} {pct:+.2f}%
            </div>
            <div style="color:var(--text-secondary); font-size:0.8em; margin-top:4px;">
                成交额 {amt_str}
            </div>
        </div>
        """)

# ===================================================================
# 1.5. 市场宽度统计
# ===================================================================
breadth = prefetch.get("market_breadth", {})
if breadth and breadth.get("source") != "unavailable":
    st.html('<h2>📈 市场宽度</h2>')
    
    total_up = breadth.get("total_up", 0)
    total_down = breadth.get("total_down", 0)
    total_flat = breadth.get("total_flat", 0)
    total = breadth.get("total", 0)
    
    if total > 0:
        up_pct = total_up / total * 100
        down_pct = total_down / total * 100
        flat_pct = total_flat / total * 100
        
        # 涨跌比例条
        st.html(f"""
        <div style="background:var(--bg-card); border:1px solid var(--border-color); border-radius:10px; padding:14px 18px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                <span style="font-weight:700; color:var(--up-color);">🔴 上涨 {total_up}</span>
                <span style="color:var(--text-secondary);">⬜ 平盘 {total_flat}</span>
                <span style="font-weight:700; color:var(--down-color);">🟢 下跌 {total_down}</span>
            </div>
            <div style="display:flex; height:24px; border-radius:6px; overflow:hidden; background:var(--border-color);">
                <div style="width:{up_pct:.1f}%; background:var(--up-color); min-width:2px; border-radius:6px 0 0 6px;"></div>
                <div style="width:{flat_pct:.1f}%; background:#888; min-width:1px;"></div>
                <div style="width:{down_pct:.1f}%; background:var(--down-color); min-width:2px; border-radius:0 6px 6px 0;"></div>
            </div>
            <div style="display:flex; justify-content:space-between; margin-top:6px; font-size:0.82em; color:var(--text-secondary);">
                <span>{up_pct:.1f}%</span>
                <span>共 {total} 家</span>
                <span>{down_pct:.1f}%</span>
            </div>
        </div>
        """)
        
        # 分市场明细
        sh_up = breadth.get("sh_up", 0)
        sh_down = breadth.get("sh_down", 0)
        sh_flat = breadth.get("sh_flat", 0)
        sz_up = breadth.get("sz_up", 0)
        sz_down = breadth.get("sz_down", 0)
        sz_flat = breadth.get("sz_flat", 0)
        
        if sh_up or sz_up:
            detail_cols = st.columns(2)
            with detail_cols[0]:
                sh_total = sh_up + sh_down + sh_flat
                st.html(f"""
                <div style="background:var(--bg-card); border:1px solid var(--border-color); border-radius:8px; padding:10px 14px; text-align:center;">
                    <div style="font-weight:600; color:var(--text-primary); margin-bottom:4px;">沪市 <span style="color:var(--text-secondary); font-weight:400;">{sh_total}家</span></div>
                    <span style="color:var(--up-color); font-weight:600;">{sh_up}涨</span>
                    <span style="color:var(--text-secondary); margin:0 6px;">{sh_flat}平</span>
                    <span style="color:var(--down-color); font-weight:600;">{sh_down}跌</span>
                </div>
                """)
            with detail_cols[1]:
                sz_total = sz_up + sz_down + sz_flat
                st.html(f"""
                <div style="background:var(--bg-card); border:1px solid var(--border-color); border-radius:8px; padding:10px 14px; text-align:center;">
                    <div style="font-weight:600; color:var(--text-primary); margin-bottom:4px;">深市 <span style="color:var(--text-secondary); font-weight:400;">{sz_total}家</span></div>
                    <span style="color:var(--up-color); font-weight:600;">{sz_up}涨</span>
                    <span style="color:var(--text-secondary); margin:0 6px;">{sz_flat}平</span>
                    <span style="color:var(--down-color); font-weight:600;">{sz_down}跌</span>
                </div>
                """)
        
        # 创业板/科创50 明细
        cyb_up = breadth.get("cyb_up", 0)
        cyb_down = breadth.get("cyb_down", 0)
        kc_up = breadth.get("kc_up", 0)
        kc_down = breadth.get("kc_down", 0)
        if cyb_up or kc_up:
            sub_cols = st.columns(2)
            if cyb_up:
                cyb_flat = breadth.get("cyb_flat", 0)
                cyb_total = cyb_up + cyb_down + cyb_flat
                with sub_cols[0]:
                    st.html(f"""
                    <div style="background:var(--bg-card); border:1px solid var(--border-color); border-radius:8px; padding:8px 14px; text-align:center; font-size:0.9em;">
                        <span style="color:var(--text-primary);">创业板</span>
                        <span style="color:var(--text-secondary); margin-left:4px;">{cyb_total}家</span>
                        <span style="color:var(--up-color); margin-left:8px;">{cyb_up}涨</span>
                        <span style="color:var(--down-color); margin-left:8px;">{cyb_down}跌</span>
                    </div>
                    """)
            if kc_up:
                kc_flat = breadth.get("kc_flat", 0)
                kc_total = kc_up + kc_down + kc_flat
                with sub_cols[1]:
                    st.html(f"""
                    <div style="background:var(--bg-card); border:1px solid var(--border-color); border-radius:8px; padding:8px 14px; text-align:center; font-size:0.9em;">
                        <span style="color:var(--text-primary);">科创板</span>
                        <span style="color:var(--text-secondary); margin-left:4px;">{kc_total}家</span>
                        <span style="color:var(--up-color); margin-left:8px;">{kc_up}涨</span>
                        <span style="color:var(--down-color); margin-left:8px;">{kc_down}跌</span>
                    </div>
                    """)
    elif breadth.get("total", 0) > 0:
        # 只有总数没有涨跌分布（新浪降级模式）
        total_only = breadth["total"]
        sh_total = breadth.get("sh_total", 0)
        sz_total = breadth.get("sz_total", 0)
        bj_total = breadth.get("bj_total", 0)
        # 分市场卡片
        market_parts = []
        if sh_total:
            market_parts.append(f"沪市 {sh_total}")
        if sz_total:
            market_parts.append(f"深市 {sz_total}")
        if bj_total:
            market_parts.append(f"北交所 {bj_total}")
        market_str = " · ".join(market_parts)
        st.html(f"""
        <div style="background:var(--bg-card); border:1px solid var(--border-color); border-radius:10px; padding:14px 18px; margin-bottom:12px; text-align:center;">
            <div style="margin-bottom:6px;">
                <span style="color:var(--text-secondary);">A股上市公司共</span>
                <span style="font-weight:700; color:var(--text-primary); font-size:1.3em; margin:0 6px;">{total_only}</span>
                <span style="color:var(--text-secondary);">家</span>
            </div>
            <div style="color:var(--text-secondary); font-size:0.85em;">{market_str}</div>
        </div>
        """)

# ===================================================================
# 2. 时效性状态
# ===================================================================
st.html('<h2>⏱️ 时效性状态</h2>')

def _freshness_badge(f: dict) -> tuple[str, str]:
    """根据时效性返回 (状态标签, 颜色)"""
    if not f.get("exists"):
        return "❌ 无数据", "var(--text-primary)"
    if f.get("fresh"):
        return "✅ 新鲜", "var(--down-color)"
    return "⚠️ 过期", "var(--warning-color)"


fresh_cols = st.columns(3)
fresh_items = [
    ("Watchlist", freshness.get("watchlist", {})),
    ("Prefetch", freshness.get("prefetch", {})),
    ("Summary", freshness.get("summary", {})),
]
for col, (label, f) in zip(fresh_cols, fresh_items):
    badge, badge_color = _freshness_badge(f)
    mtime = f.get("mtime", "—")
    age = f.get("age_minutes")
    age_str = f"{age:.0f}分钟前" if age is not None else "—"
    with col:
        st.html(f"""
        <div class="dash-card" style="text-align:center;">
            <div class="dash-card-header">{label}</div>
            <div style="font-weight:700; color:{badge_color}; font-size:1.1em; margin:6px 0;">{badge}</div>
            <div style="color:var(--text-secondary); font-size:0.82em;">{mtime}</div>
            <div style="color:var(--text-secondary); font-size:0.82em;">{age_str}</div>
        </div>
        """)

# ===================================================================
# 3. 今日信号概览
# ===================================================================
st.html('<h2>📋 今日信号概览</h2>')

# 合并 watchlist 和 prefetch 的信号数据，prefetch 优先
# 从 prefetch 中获取更丰富的信号信息
prefetch_candidates = prefetch.get("candidates", {})
prefetch_signals = prefetch.get("signals", {})

SIGNAL_GROUPS = [
    ("🔴 全买入", "full_buy", "var(--up-color)"),
    ("🟠 强庄买", "strong_buy", "var(--warning-color)"),
    ("🟡 基础买", "base_buy", "var(--warning-color)"),
]

signal_cols = st.columns(3)
has_any_signal = False
for col, (label, key, border_color) in zip(signal_cols, SIGNAL_GROUPS):
    # 优先取 prefetch signals，其次取 watchlist
    group_stocks = prefetch_signals.get(key, []) or watchlist.get(key, [])
    count = len(group_stocks)
    has_any_signal = has_any_signal or (count > 0)
    with col:
        st.html(f"""
        <div style="background:var(--bg-card); border:1px solid var(--border-color);
                    border-top:3px solid {border_color}; border-radius:10px;
                    padding:14px 18px; text-align:center; margin-bottom:10px;">
            <div style="font-weight:700; font-size:1.05em; color:var(--text-primary);">{label}</div>
            <div style="font-size:1.8em; font-weight:800; color:{border_color}; margin:6px 0;">{count}</div>
        </div>
        """)

# 详细信号卡片
# 信号列表可能有两种格式：字典列表 [{code,name,...}, ...] 或字符串列表 ["600403", ...]
def _normalize_stock(s, prefetch_candidates=None):
    """统一信号股为字典格式，字符串代码转为 {code, name, ...}"""
    if isinstance(s, dict):
        return s
    if isinstance(s, str):
        code = s
        p_data = (prefetch_candidates or {}).get(code, {})
        rt = p_data.get("real_time_quote", {})
        return {
            "code": code,
            "name": p_data.get("name", code),
            "price": rt.get("current_price", 0) or 0,
            "change_pct": rt.get("change_pct", 0) or 0,
            "signal": "",
        }
    return {"code": str(s), "name": str(s), "price": 0, "change_pct": 0, "signal": ""}

for label, key, border_color in SIGNAL_GROUPS:
    group_stocks = prefetch_signals.get(key, []) or watchlist.get(key, [])
    if not group_stocks:
        continue
    st.html(f'<h3 style="color:var(--text-primary);">{label} · {len(group_stocks)}只</h3>')
    for s in group_stocks:
        stock = _normalize_stock(s, prefetch_candidates)
        code = stock.get("code", "")
        name = stock.get("name", "")
        price = stock.get("price", 0)
        # 尝试从 prefetch 获取实时行情
        p_data = prefetch_candidates.get(code, {})
        rt = p_data.get("real_time_quote", {})
        if rt:
            price = rt.get("current_price", price) or price
            change_pct = rt.get("change_pct", 0) or 0
        else:
            change_pct = stock.get("change_pct", 0) or 0

        signal = stock.get("signal", "")
        vibe_score = stock.get("vibe_score") or stock.get("signal_score")
        confirmation = stock.get("confirmation", "")

        # 涨跌色
        if change_pct > 0:
            chg_color = "var(--up-color)"
            chg_arrow = "▲"
        elif change_pct < 0:
            chg_color = "var(--down-color)"
            chg_arrow = "▼"
        else:
            chg_color = "var(--text-primary)"
            chg_arrow = "—"

        vibe_str = f"Vibe {vibe_score}" if vibe_score is not None else ""
        conf_str = f"✅ {confirmation}" if confirmation else ""

        # 进场建议标签
        rec = _action_map.get(code)
        if rec:
            action = rec.get("action", "")
            if action == "推荐进场":
                action_tag = '<span style="background:var(--up-color); color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8em; font-weight:700;">✅ 可进场</span>'
            elif action == "观察":
                action_tag = '<span style="background:var(--warning-color); color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8em; font-weight:700;">👁️ 观察</span>'
            else:
                action_tag = '<span style="background:#888; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8em; font-weight:700;">❌ 不建议</span>'
            # 进场详情
            entry = rec.get("entry_price", 0)
            stop = rec.get("stop_loss", 0)
            stop_pct = rec.get("stop_pct", "")
            target = rec.get("target", 0)
            target_pct = rec.get("target_pct", "")
            position = rec.get("position", "")
            rr = rec.get("risk_reward", "")
            score = rec.get("score", 0)
            detail_parts = []
            if score:
                detail_parts.append(f"评分 {score}")
            if entry and entry > 0:
                detail_parts.append(f"买入 ¥{entry:.2f}")
            if stop and stop > 0:
                detail_parts.append(f"止损 ¥{stop:.2f}({stop_pct})")
            if target and target > 0:
                detail_parts.append(f"目标 ¥{target:.2f}({target_pct})")
            if position:
                detail_parts.append(f"仓位 {position}")
            if rr:
                detail_parts.append(f"盈亏比 {rr}")
            detail_str = " · ".join(detail_parts)
            action_detail = f'<div style="margin-top:6px; color:var(--text-secondary); font-size:0.82em;">{detail_str}</div>' if detail_str else ""
        else:
            action_tag = ""
            action_detail = ""

        st.html(f"""
        <div class="scan-result-card" style="border-left:4px solid {border_color};">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                <div>
                    <span style="font-weight:700; color:var(--text-primary); font-size:1.05em;">{name}</span>
                    <span style="color:var(--text-secondary); margin-left:8px;">{code}</span>
                    <span style="color:{chg_color}; font-weight:600; margin-left:12px;">
                        ¥{price:.2f} {chg_arrow} {change_pct:+.2f}%
                    </span>
                </div>
                <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                    <span class="tag tag-accent">{signal}</span>
                    {f'<span class="tag tag-info">{vibe_str}</span>' if vibe_str else ''}
                    {f'<span style="color:var(--down-color); font-size:0.85em;">{conf_str}</span>' if conf_str else ''}
                    {action_tag}
                </div>
            </div>
            {action_detail}
        </div>
        """)

if not has_any_signal:
    st.info("📭 暂无信号数据，请先运行扫描或预取")

# ===================================================================
# 3.5 进场建议汇总
# ===================================================================
rec_summary = recommend.get("summary", {})
rec_list = recommend.get("recommend", [])
obs_list = recommend.get("observe", [])
exc_list = recommend.get("excluded", [])
rec_count = rec_summary.get("recommend_count", len(rec_list))
obs_count = rec_summary.get("observe_count", len(obs_list))
exc_count = rec_summary.get("excluded_count", len(exc_list))

if rec_list or obs_list:
    st.html('<h2>🎯 进场建议</h2>')

    # 冷静期提示
    if rec_summary.get("in_cooldown"):
        st.warning("🔴 **冷静期中** — 连续多次全亏，暂停推荐进场")

    # 推荐进场卡片
    if rec_list:
        for item in rec_list:
            sig = item.get("signal", "")
            sig_emoji = item.get("signal_emoji", "⚪")
            name = item.get("name", item.get("code", ""))
            code = item.get("code", "")
            score = item.get("score", 0)
            entry = item.get("entry_price", 0)
            change_pct = item.get("change_pct", 0)
            stop = item.get("stop_loss", 0)
            stop_pct = item.get("stop_pct", "")
            target = item.get("target", 0)
            target_pct = item.get("target_pct", "")
            position = item.get("position", "")
            rr = item.get("risk_reward", "")
            reason = item.get("reason", "")

            # 涨跌色
            if change_pct > 0:
                chg_color = "var(--up-color)"
                chg_arrow = "▲"
            elif change_pct < 0:
                chg_color = "var(--down-color)"
                chg_arrow = "▼"
            else:
                chg_color = "var(--text-primary)"
                chg_arrow = "—"

            st.html(f"""
            <div style="background:var(--bg-card); border:1px solid var(--border-color);
                        border-left:4px solid var(--up-color); border-radius:10px;
                        padding:16px 20px; margin-bottom:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
                    <div>
                        <span style="font-weight:800; color:var(--text-primary); font-size:1.15em;">{sig_emoji} {name}</span>
                        <span style="color:var(--text-secondary); margin-left:8px;">{code}</span>
                        <span style="color:{chg_color}; font-weight:600; margin-left:12px;">
                            ¥{entry:.2f} {chg_arrow} {change_pct:+.2f}%
                        </span>
                    </div>
                    <div style="display:flex; gap:8px; align-items:center;">
                        <span style="background:var(--up-color); color:#fff; padding:3px 10px; border-radius:4px; font-size:0.85em; font-weight:700;">✅ 可进场</span>
                        <span class="tag tag-accent">{sig}</span>
                        <span style="color:var(--text-secondary); font-size:0.85em;">评分 {score}</span>
                    </div>
                </div>
                <div style="display:flex; flex-wrap:wrap; gap:20px; font-size:0.9em; margin-bottom:8px;">
                    <span style="color:var(--text-secondary);">买入 <b style="color:var(--text-primary);">¥{entry:.2f}</b></span>
                    <span style="color:var(--text-secondary);">止损 <b style="color:var(--up-color);">¥{stop:.2f}（{stop_pct}）</b></span>
                    <span style="color:var(--text-secondary);">目标 <b style="color:var(--down-color);">¥{target:.2f}（{target_pct}）</b></span>
                    <span style="color:var(--text-secondary);">仓位 <b style="color:var(--text-primary);">{position}</b></span>
                    <span style="color:var(--text-secondary);">盈亏比 <b style="color:var(--text-primary);">{rr}</b></span>
                </div>
                {f'<div style="color:var(--text-secondary); font-size:0.82em;">💡 {reason}</div>' if reason else ''}
            </div>
            """)

    # 观察池简要
    if obs_list:
        st.html(f'<h3 style="color:var(--text-primary);">👁️ 观察池 · {obs_count}只</h3>')
        obs_rows = []
        for item in obs_list:
            sig_emoji = item.get("signal_emoji", "⚪")
            name = item.get("name", item.get("code", ""))
            code = item.get("code", "")
            sig = item.get("signal", "")
            score = item.get("score", 0)
            entry = item.get("entry_price", 0)
            stop = item.get("stop_loss", 0)
            target = item.get("target", 0)
            obs_rows.append(f'<span style="margin-right:16px;">{sig_emoji} {name}({code}) {sig} {score}分 · ¥{entry:.2f} 止损¥{stop:.2f} 目标¥{target:.2f}</span>')
        st.html(f'<div style="background:var(--bg-card); border:1px solid var(--border-color); border-radius:8px; padding:12px 16px; font-size:0.88em; line-height:1.8;">{"".join(obs_rows)}</div>')

elif recommend.get("update_time"):
    # 有推荐数据但都空 = 全被过滤
    st.html('<h2>🎯 进场建议</h2>')
    if exc_count > 0:
        st.warning(f"⛔ 今日无推荐进场标的 — {exc_count}只被过滤，暂不符合进场条件")
    else:
        st.info("📭 今日无信号，继续保持空仓等待")
    # 排除详情
    if exc_list:
        with st.expander(f"查看被过滤详情（{exc_count}只）"):
            for item in exc_list:
                name = item.get("name", item.get("code", ""))
                code = item.get("code", "")
                sig = item.get("signal", "")
                reason = item.get("reason", "")
                st.html(f'<div style="margin-bottom:4px;"><span style="color:var(--text-secondary);">{name}({code})</span> <span class="tag tag-accent">{sig}</span> <span style="color:var(--up-color); font-size:0.85em;">❌ {reason}</span></div>')

# ===================================================================
# 4. 候选股详情
# ===================================================================
st.html('<h2>🔍 候选股详情</h2>')

if not prefetch_candidates:
    st.info("📭 暂无候选股数据，请先运行预取(prefetch)")
else:
    for code, c in prefetch_candidates.items():
        name = c.get("name", code)
        signal = c.get("signal", "")
        rt = c.get("real_time_quote", {})
        sector_info = c.get("sector_info", {})
        capital_flow = c.get("capital_flow", {})
        key_levels = c.get("key_levels", {})

        # 实时行情
        current_price = rt.get("current_price", 0) or 0
        change_pct = rt.get("change_pct", 0) or 0
        amount = rt.get("amount", 0) or 0
        turnover = rt.get("turnover", 0) or 0

        # 涨跌色
        if change_pct > 0:
            chg_color = "var(--up-color)"
            chg_arrow = "▲"
        elif change_pct < 0:
            chg_color = "var(--down-color)"
            chg_arrow = "▼"
        else:
            chg_color = "var(--text-primary)"
            chg_arrow = "—"

        # 成交额
        if amount > 1e8:
            amt_str = f"{amount / 1e8:.2f}亿"
        elif amount > 1e4:
            amt_str = f"{amount / 1e4:.0f}万"
        else:
            amt_str = f"{amount:.0f}"

        # 主力净流入
        cf_value = capital_flow.get("value", 0) or 0
        cf_has = capital_flow.get("has_data", False)
        if cf_value > 0:
            cf_color = "var(--up-color)"
            cf_str = f"净流入 {cf_value / 1e4:.0f}万" if abs(cf_value) < 1e8 else f"净流入 {cf_value / 1e8:.2f}亿"
        elif cf_value < 0:
            cf_color = "var(--down-color)"
            cf_str = f"净流出 {abs(cf_value) / 1e4:.0f}万" if abs(cf_value) < 1e8 else f"净流出 {abs(cf_value) / 1e8:.2f}亿"
        else:
            cf_color = "var(--text-secondary)"
            cf_str = "无数据" if not cf_has else "持平"

        # 板块归属
        sectors = sector_info.get("sectors", [])
        sector_str = " · ".join(sectors) if sectors else (sector_info.get("raw_content", "") or "—")

        # 信号等级边框色
        if signal == "全买入":
            border_c = "var(--up-color)"
        elif signal == "强庄买":
            border_c = "var(--warning-color)"
        elif signal == "基础买":
            border_c = "var(--warning-color)"
        else:
            border_c = "var(--accent)"

        # 关键价位
        ema7 = key_levels.get("ema7", "—")
        ema20 = key_levels.get("ema20", "—")
        ema120 = key_levels.get("ema120", "—")
        ema200 = key_levels.get("ema200", "—")
        stop_loss = key_levels.get("stop_loss", "—")

        def _fmt_ema(v):
            return f"¥{v:.2f}" if isinstance(v, (int, float)) and v else "—"

        st.html(f"""
        <div class="scan-result-card" style="border-left:4px solid {border_c};">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
                <div>
                    <span style="font-weight:700; color:var(--text-primary); font-size:1.1em;">{name}</span>
                    <span style="color:var(--text-secondary); margin-left:8px;">{code}</span>
                    <span style="color:{chg_color}; font-weight:600; margin-left:12px;">
                        ¥{current_price:.2f} {chg_arrow} {change_pct:+.2f}%
                    </span>
                </div>
                <div>
                    <span class="tag tag-accent">{signal}</span>
                </div>
            </div>
            <div style="display:flex; flex-wrap:wrap; gap:16px; font-size:0.88em;">
                <span style="color:var(--text-secondary);">成交额 <b style="color:var(--text-primary);">{amt_str}</b></span>
                <span style="color:var(--text-secondary);">换手 <b style="color:var(--text-primary);">{turnover:.2f}%</b></span>
                <span style="color:var(--text-secondary);">主力 <b style="color:{cf_color};">{cf_str}</b></span>
                <span style="color:var(--text-secondary);">板块 <b style="color:var(--text-primary);">{sector_str}</b></span>
            </div>
            <div style="display:flex; flex-wrap:wrap; gap:14px; margin-top:8px; font-size:0.85em;">
                <span style="color:var(--text-secondary);">EMA7 <b style="color:var(--text-primary);">{_fmt_ema(ema7)}</b></span>
                <span style="color:var(--text-secondary);">EMA20 <b style="color:var(--text-primary);">{_fmt_ema(ema20)}</b></span>
                <span style="color:var(--text-secondary);">EMA120 <b style="color:var(--text-primary);">{_fmt_ema(ema120)}</b></span>
                <span style="color:var(--text-secondary);">EMA200 <b style="color:var(--text-primary);">{_fmt_ema(ema200)}</b></span>
                <span style="color:var(--text-secondary);">止损 <b style="color:var(--up-color);">{_fmt_ema(stop_loss)}</b></span>
            </div>
        </div>
        """)

# ===================================================================
# 5. 板块热度
# ===================================================================
st.html('<h2>🔥 板块热度 TOP15</h2>')

trending = prefetch.get("sectors", {}).get("trending_sectors", [])
if not trending:
    st.info("📭 暂无板块热度数据")
else:
    top15 = trending[:15]
    # 构建条形图用 DataFrame
    sector_rows = []
    for s in top15:
        name = s.get("name", "")
        pct = s.get("change_pct", 0) or 0
        sector_rows.append({"板块": name, "涨跌幅": pct})
    df_sectors = pd.DataFrame(sector_rows)

    if not df_sectors.empty:
        # 按涨跌幅排序
        df_sectors = df_sectors.sort_values("涨跌幅", ascending=True)

        # 用 plotly 做横向条形图
        try:
            import plotly.express as px
            fig = px.bar(
                df_sectors,
                x="涨跌幅",
                y="板块",
                orientation="h",
                color="涨跌幅",
                color_continuous_scale=["var(--down-color)", "var(--bg-card)", "var(--up-color)"],
            )
            fig.update_layout(
                height=max(300, len(df_sectors) * 28),
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="涨跌幅(%)",
                yaxis_title="",
                coloraxis_showscale=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="var(--text-primary)"),
            )
            fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.15)")
            fig.update_yaxes(tickfont=dict(size=12))
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            # fallback: 用 HTML 条形图
            for _, row in df_sectors.iterrows():
                pct = row["涨跌幅"]
                color = "var(--up-color)" if pct >= 0 else "var(--down-color)"
                width = min(abs(pct) * 10, 100)
                st.html(f"""
                <div style="display:flex; align-items:center; gap:10px; margin-bottom:4px;">
                    <span style="min-width:100px; color:var(--text-primary); font-size:0.88em; text-align:right;">{row['板块']}</span>
                    <div style="flex:1; background:var(--border-color); border-radius:4px; height:18px; overflow:hidden;">
                        <div style="background:{color}; height:100%; width:{width}%; border-radius:4px;"></div>
                    </div>
                    <span style="min-width:60px; color:{color}; font-weight:600; font-size:0.88em;">{pct:+.2f}%</span>
                </div>
                """)

# ===================================================================
# 6. 操作按钮
# ===================================================================
st.html('<h2>⚡ 操作</h2>')

# 交易时间提示
_now = datetime.now().time()
_trading = dt_time(9, 25) <= _now <= dt_time(15, 0)
_prefetch_time = dt_time(14, 20) <= _now <= dt_time(15, 0)
if not _trading:
    st.info("⏰ 当前非交易时间（9:25-15:00），数据可能为空。全扫描可随时运行。")
elif _prefetch_time:
    st.success("🟢 尾盘时段（14:20-15:00），一键扫描获取实时数据")

# 一键全流程按钮
if st.button("🚀 尾盘选股扫描", type="primary", use_container_width=True):
    # Step 1: 全市场扫描 → 信号股
    step1 = st.empty()
    step1.info("⏳ **Step 1/3** 全市场扫描中，寻找信号股...")
    try:
        result1 = run_scan()
    except Exception as e:
        result1 = {"success": False, "description": f"异常: {e}", "stdout": "", "stderr": str(e)}
    if not result1.get("success"):
        st.error(f"❌ 全扫描失败: {result1.get('description', '未知错误')}")
        stderr1 = result1.get("stderr", "")
        if stderr1:
            with st.expander("查看错误详情"):
                st.code(stderr1[-500:])
    else:
        step1.success("✅ **Step 1/3** 全扫描完成")
        # Step 2: 预取 → 候选股详情+行情+板块
        step2 = st.empty()
        step2.info("⏳ **Step 2/3** 预取候选股详情+行情+板块...")
        try:
            result2 = run_prefetch()
        except Exception as e:
            result2 = {"success": False, "description": f"异常: {e}", "stdout": "", "stderr": str(e)}
        if not result2.get("success"):
            st.warning(f"⚠️ 预取失败: {result2.get('description', '未知错误')}，跳过继续汇总")
        else:
            stdout2 = result2.get("stdout", "")
            if "空缓存" in stdout2 or "非交易" in stdout2:
                step2.warning("⚠️ **Step 2/3** 预取完成但数据可能为空（非交易时间）")
            else:
                step2.success("✅ **Step 2/3** 预取完成")

        # Step 3: 汇总 → 推荐结果
        step3 = st.empty()
        step3.info("⏳ **Step 3/3** 生成推荐摘要...")
        try:
            result3 = run_summary()
        except Exception as e:
            result3 = {"success": False, "description": f"异常: {e}", "stdout": "", "stderr": str(e)}
        if not result3.get("success"):
            st.error(f"❌ 汇总失败: {result3.get('description', '未知错误')}")
        else:
            step3.success("✅ **Step 3/3** 推荐摘要生成完成")

        # 全部完成，刷新页面
        st.balloons()
        time.sleep(2)
        st.rerun()

# ===================================================================
# 7. 推荐摘要
# ===================================================================
st.html('<h2>📝 推荐摘要</h2>')

if summary_text:
    # 将摘要文本格式化显示
    # 保留换行和缩进
    formatted = summary_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    st.html(f"""
    <div style="background:var(--bg-card); border:1px solid var(--border-color);
                border-radius:10px; padding:18px 22px; font-size:0.92em;
                line-height:1.7; color:var(--text-primary);
                max-height:500px; overflow-y:auto;">
        {formatted}
    </div>
    """)
else:
    st.info("📭 暂无推荐摘要，请先运行汇总(Summary)")
