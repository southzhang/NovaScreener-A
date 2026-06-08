"""尾盘选股页面 — 大盘指数 · 信号概览 · 候选详情 · 板块热度 · 操作按钮"""
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
freshness = data["freshness"]

# ===================================================================
# 1. 大盘指数概览
# ===================================================================
st.html('<h2 style="margin-top:0;">📊 大盘指数概览</h2>')

index_data = prefetch.get("index", {})
# 按常见顺序排列: 上证 / 深证 / 创业板
INDEX_ORDER = ["sh000001", "sz399001", "sz399006"]
INDEX_DEFAULTS = {
    "sh000001": {"name": "上证指数", "price": 0, "change_pct": 0, "amount": 0},
    "sz399001": {"name": "深证成指", "price": 0, "change_pct": 0, "amount": 0},
    "sz399006": {"name": "创业板指", "price": 0, "change_pct": 0, "amount": 0},
}

idx_cols = st.columns(3)
for i, key in enumerate(INDEX_ORDER):
    idx = index_data.get(key, INDEX_DEFAULTS.get(key, {}))
    name = idx.get("name", INDEX_DEFAULTS.get(key, {}).get("name", key))
    price = idx.get("price", 0)
    pct = idx.get("change_pct", 0)
    amount = idx.get("amount", 0)

    if pct > 0:
        color = "#ff4b4b"
        arrow = "▲"
    elif pct < 0:
        color = "#00c853"
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
# 2. 时效性状态
# ===================================================================
st.html('<h2>⏱️ 时效性状态</h2>')

def _freshness_badge(f: dict) -> tuple[str, str]:
    """根据时效性返回 (状态标签, 颜色)"""
    if not f.get("exists"):
        return "❌ 无数据", "var(--text-primary)"
    if f.get("fresh"):
        return "✅ 新鲜", "#00c853"
    return "⚠️ 过期", "#ffab40"


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
    ("🔴 全买入", "full_buy", "#ff4b4b"),
    ("🟠 强庄买", "strong_buy", "#ffab40"),
    ("🟡 基础买", "base_buy", "#ffeb3b"),
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
            chg_color = "#ff4b4b"
            chg_arrow = "▲"
        elif change_pct < 0:
            chg_color = "#00c853"
            chg_arrow = "▼"
        else:
            chg_color = "var(--text-primary)"
            chg_arrow = "—"

        vibe_str = f"Vibe {vibe_score}" if vibe_score is not None else ""
        conf_str = f"✅ {confirmation}" if confirmation else ""

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
                    {f'<span style="color:#00c853; font-size:0.85em;">{conf_str}</span>' if conf_str else ''}
                </div>
            </div>
        </div>
        """)

if not has_any_signal:
    st.info("📭 暂无信号数据，请先运行扫描或预取")

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
            chg_color = "#ff4b4b"
            chg_arrow = "▲"
        elif change_pct < 0:
            chg_color = "#00c853"
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
            cf_color = "#ff4b4b"
            cf_str = f"净流入 {cf_value / 1e4:.0f}万" if abs(cf_value) < 1e8 else f"净流入 {cf_value / 1e8:.2f}亿"
        elif cf_value < 0:
            cf_color = "#00c853"
            cf_str = f"净流出 {abs(cf_value) / 1e4:.0f}万" if abs(cf_value) < 1e8 else f"净流出 {abs(cf_value) / 1e8:.2f}亿"
        else:
            cf_color = "var(--text-secondary)"
            cf_str = "无数据" if not cf_has else "持平"

        # 板块归属
        sectors = sector_info.get("sectors", [])
        sector_str = " · ".join(sectors) if sectors else (sector_info.get("raw_content", "") or "—")

        # 信号等级边框色
        if signal == "全买入":
            border_c = "#ff4b4b"
        elif signal == "强庄买":
            border_c = "#ffab40"
        elif signal == "基础买":
            border_c = "#ffeb3b"
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
                <span style="color:var(--text-secondary);">止损 <b style="color:#ff4b4b;">{_fmt_ema(stop_loss)}</b></span>
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
                color_continuous_scale=["#00c853", "#ffffff", "#ff4b4b"],
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
                color = "#ff4b4b" if pct >= 0 else "#00c853"
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
    st.info("⏰ 当前非交易时间（9:25-15:00），预取/汇总可能写入空数据。全扫描可随时运行。")
elif _prefetch_time:
    st.success("🟢 尾盘时段（14:20-15:00），建议点击预取+汇总获取实时数据")

btn_cols = st.columns(3)
with btn_cols[0]:
    if st.button("📥 一键预取", type="primary", use_container_width=True):
        with st.spinner("正在预取尾盘数据..."):
            result = run_prefetch()
        if result["success"]:
            stdout = result.get("stdout", "")
            if "空缓存" in stdout or "非交易" in stdout:
                st.warning(f"⚠️ 预取完成但写入了空缓存（可能非交易时间）\n{stdout.strip()}")
            else:
                st.success("✅ 尾盘预取成功")
                st.rerun()
        else:
            st.error(f"❌ {result['description']}")

with btn_cols[1]:
    if st.button("📝 一键汇总", type="primary", use_container_width=True):
        with st.spinner("正在生成尾盘摘要..."):
            result = run_summary()
        if result["success"]:
            st.success("✅ 尾盘摘要生成成功")
            st.rerun()
        else:
            st.error(f"❌ {result['description']}")

with btn_cols[2]:
    if st.button("🔍 一键全扫描", type="primary", use_container_width=True):
        with st.spinner("正在运行V10全市场扫描（约2-5分钟），请耐心等待..."):
            result = run_scan()
        if result["success"]:
            st.success("✅ V10全市场扫描完成")
            st.rerun()
        else:
            stderr = result.get("stderr", "")
            st.error(f"❌ {result['description']}")
            if stderr:
                with st.expander("查看错误详情"):
                    st.code(stderr[-500:])

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
