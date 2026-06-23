"""量化盯盘选股 V10 — 完整版 Streamlit 主入口"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
from core.db import init_db, get_signals, get_watchlist, add_watchlist, remove_watchlist, get_positions
from core.data import get_stock_list, get_top_gainers, get_top_losers, get_realtime_quote, get_realtime_quotes_batch, get_stock_history, get_market_indices, _is_trading_session
from core.strategies import STRATEGY_REGISTRY, get_strategy_names
from core.scanner import scan_market, scan_watchlist, get_market_overview
from core.scorer import score_stock, score_batch
from core.monitor import get_monitor, start_monitoring, stop_monitoring
from core.alerts import send_feishu_card, send_batch_signals
from core.ui import inject_global_css, render_theme_toggle, render_page_header
from version import VERSION, check_update

# 初始化
load_dotenv()
init_db()

st.set_page_config(
    page_title="V10 量化盯盘选股",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===== 全局样式 =====
inject_global_css()

# ===== 侧边栏 =====
with st.sidebar:
    st.title("📊 V10 量化选股")
    st.markdown("**维加斯V10强庄策略**")
    st.caption("七条件共振 · 波段回调 · 多维评分")
    st.divider()
    
    # 监控状态（带数据源指示）
    monitor = get_monitor()
    status = monitor.get_status()
    
    if status["running"]:
        st.success(f"🟢 盯盘监控运行中")
        _ds = "🟢 盘中实时" if _is_trading_session() else "🔵 盘后数据"
        st.caption(f"📡 数据源: {_ds}")
        st.caption(f"监控 {status['watchlist_count']} 只 | {status['last_update']}")
        if st.button("⏹ 停止监控"):
            stop_monitoring()
            st.rerun()
    else:
        st.info("🔴 盯盘监控未启动")
        if st.button("▶ 启动监控"):
            start_monitoring()
            st.rerun()
    
    st.divider()
    st.markdown(f"**内置策略:** {len(STRATEGY_REGISTRY)} 个")
    st.markdown("**数据源:** 腾讯K线 + 实时行情")
    
    if st.button("🔄 刷新数据", width='stretch'):
        st.cache_data.clear()
        st.rerun()
    
    st.divider()
    # ===== 版本信息 =====
    _v_col1, _v_col2 = st.columns([1, 3])
    with _v_col1:
        st.caption(f"**{VERSION}**")
    with _v_col2:
        _update_key = "_update_checked"
        if _update_key not in st.session_state:
            st.session_state[_update_key] = check_update()
        
        _vr = st.session_state[_update_key]
        if _vr["has_update"]:
            if st.button(f"⬆️ 更新至 {_vr['latest']}", type="primary", use_container_width=True):
                with st.status("更新中...", expanded=True) as status:
                    import subprocess, os, sys
                    _cwd = os.path.dirname(os.path.abspath(__file__))
                    
                    # 1. 暂存本地修改
                    st.write("📦 暂存本地修改...")
                    stash_r = subprocess.run(["git", "stash"], cwd=_cwd, capture_output=True, text=True, timeout=10)
                    had_stash = stash_r.returncode == 0 and "Saved" in (stash_r.stdout or "")
                    
                    # 2. 拉取最新代码
                    st.write("⬇️ 拉取最新代码...")
                    r = subprocess.run(
                        ["git", "pull"],
                        capture_output=True, text=True, timeout=60,
                        cwd=_cwd,
                    )
                    st.code(r.stdout or r.stderr or "无输出")
                    
                    # 3. 恢复本地修改
                    if had_stash:
                        st.write("📂 恢复本地修改...")
                        stash_pop_r = subprocess.run(
                            ["git", "stash", "pop"],
                            capture_output=True, text=True, timeout=10,
                            cwd=_cwd,
                        )
                        if stash_pop_r.returncode != 0:
                            st.warning("本地修改恢复有冲突，已保留在 git stash 中")
                    
                    if r.returncode == 0:
                        status.update(label="✅ 更新成功！正在重启...", state="complete")
                        st.session_state.pop(_update_key, None)
                        st.cache_data.clear()
                        # 真正重启 Streamlit 进程
                        os.execv(sys.executable, [sys.executable] + sys.argv)
                    else:
                        status.update(label="❌ 更新失败", state="error")
                        st.error(r.stderr or r.stdout or "未知错误")
        elif _vr["error"]:
            st.caption("⚠️ 无法检查更新")
        else:
            st.caption("✅ 已是最新")

# ===== 主页面 =====
# 主题切换按钮（右上角）
render_theme_toggle()

st.html("""
<div style="padding: 10px 0 20px 0;">
    <h2 style="margin:0; color:#ff6b35; font-size: 1.8em;">📊 V10 量化盯盘选股</h2>
    <p style="margin:5px 0 0 0; color:var(--text-secondary); font-size: 0.95em;">维加斯V10强庄策略 · 七条件共振 · 波段回调 · 多维评分 · 盯盘监控</p>
</div>
""")


# 快捷导航卡片
_nav_html = """
<div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px;">
<a href="/1_🔍_选股扫描" target="_self" style="flex:1; min-width:100px; text-decoration:none;">
<div style="background:linear-gradient(135deg, #ff6b35 0%, #e55a28 100%); border-radius:10px; padding:12px; text-align:center; color:#fff; font-weight:600; font-size:0.9em; box-shadow:0 2px 8px rgba(255,107,53,0.3);">🔍 选股扫描</div>
</a>
<a href="/6_👁️_盯盘监控" target="_self" style="flex:1; min-width:100px; text-decoration:none;">
<div style="background:linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); border-radius:10px; padding:12px; text-align:center; color:#fff; font-weight:600; font-size:0.9em; box-shadow:0 2px 8px rgba(37,99,235,0.3);">👁️ 盯盘监控</div>
</a>
<a href="/7_💼_持仓管理" target="_self" style="flex:1; min-width:100px; text-decoration:none;">
<div style="background:linear-gradient(135deg, #059669 0%, #047857 100%); border-radius:10px; padding:12px; text-align:center; color:#fff; font-weight:600; font-size:0.9em; box-shadow:0 2px 8px rgba(5,150,105,0.3);">💼 持仓管理</div>
</a>
<a href="/8_🏆_V10评分" target="_self" style="flex:1; min-width:100px; text-decoration:none;">
<div style="background:linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%); border-radius:10px; padding:12px; text-align:center; color:#fff; font-weight:600; font-size:0.9em; box-shadow:0 2px 8px rgba(124,58,237,0.3);">🏆 V10评分</div>
</a>
</div>
"""
st.html(_nav_html)

# 市场概览（红涨绿跌）— 只拉一次全市场数据，三个模块共享
st.subheader("🏛️ 市场概览")
_df_market = get_stock_list()  # 只拉一次！

def _make_breadth_bar(up_pct, down_pct, flat_pct, up, down, flat, total):
    """生成涨跌比例条HTML"""
    return f"""
    <div style="background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:10px 14px; margin-top:8px;">
        <div style="display:flex; justify-content:space-between; margin-bottom:4px; font-size:0.82em;">
            <span style="color:#ef4444; font-weight:600;">🔴 上涨 {up} ({up_pct:.1f}%)</span>
            <span style="color:var(--text-muted);">平盘 {flat}</span>
            <span style="color:#22c55e; font-weight:600;">🟢 下跌 {down} ({down_pct:.1f}%)</span>
        </div>
        <div style="display:flex; height:16px; border-radius:4px; overflow:hidden; background:var(--border-color);">
            <div style="width:{up_pct:.1f}%; background:#ef4444; min-width:2px;"></div>
            <div style="width:{flat_pct:.1f}%; background:#888; min-width:1px;"></div>
            <div style="width:{down_pct:.1f}%; background:#22c55e; min-width:2px;"></div>
        </div>
    </div>
    """

# 四大指数实时行情
_indices = get_market_indices()
if _indices:
    _idx_cards = ""
    for _idx in _indices:
        _pct = _idx["pct_change"]
        _color = "#ef4444" if _pct >= 0 else "#22c55e"
        _arrow = "▲" if _pct >= 0 else "▼"
        _price_str = f"{_idx['price']:.2f}" if _idx['price'] > 100 else f"{_idx['price']:.3f}"
        _idx_cards += f"""
        <div style="flex:1; min-width:120px; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:10px 14px; text-align:center;">
            <div style="color:var(--text-muted); font-size:0.82em; margin-bottom:2px;">{_idx['name']}</div>
            <div style="font-size:1.3em; font-weight:700; color:{_color};">{_price_str}</div>
            <div style="color:{_color}; font-size:0.85em; font-weight:600;">{_arrow} {_idx['change']:+.2f} ({_pct:+.2f}%)</div>
        </div>"""
    st.html(f"""<div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:12px;">{_idx_cards}</div>""")

overview = get_market_overview(df=_df_market)

_total = overview.get("total", 0)
_up = overview.get("up", 0)
_down = overview.get("down", 0)
_flat = overview.get("flat", 0)
_limit_up = overview.get("limit_up", 0)
_limit_down = overview.get("limit_down", 0)
_up_ratio = overview.get("up_ratio", 0)
_down_ratio = overview.get("down_ratio", 0)

# 涨跌比例条
_up_pct = _up / _total * 100 if _total > 0 else 0
_down_pct = _down / _total * 100 if _total > 0 else 0
_flat_pct = _flat / _total * 100 if _total > 0 else 0

_mkt_html = f"""
<div style="display:flex; gap:12px; flex-wrap:wrap;">
  <div style="flex:1; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">总股票数</div>
    <div style="font-size:1.6em; font-weight:700;">{_total}</div>
  </div>
  <div style="flex:1; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">上涨</div>
    <div style="font-size:1.6em; font-weight:700; color:#ef4444;">{_up}</div>
    <div style="color:#ef4444; font-size:0.85em;">▲ {_up_ratio}%</div>
  </div>
  <div style="flex:1; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">平盘</div>
    <div style="font-size:1.6em; font-weight:700;">{_flat}</div>
  </div>
  <div style="flex:1; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">下跌</div>
    <div style="font-size:1.6em; font-weight:700; color:#22c55e;">{_down}</div>
    <div style="color:#22c55e; font-size:0.85em;">▼ {_down_ratio}%</div>
  </div>
  <div style="flex:1; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">涨停</div>
    <div style="font-size:1.6em; font-weight:700; color:#ef4444;">{_limit_up}</div>
    <div style="color:#ef4444; font-size:0.85em;">家</div>
  </div>
  <div style="flex:1; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">跌停</div>
    <div style="font-size:1.6em; font-weight:700; color:#22c55e;">{_limit_down}</div>
    <div style="color:#22c55e; font-size:0.85em;">家</div>
  </div>
</div>
{_make_breadth_bar(_up_pct, _down_pct, _flat_pct, _up, _down, _flat, _total) if _total > 0 else ''}
"""
st.html(_mkt_html)

# V10 策略信号 — 扫描按钮 + 信号列表合一
st.subheader("🎯 最近策略信号")
col1, col2 = st.columns([3, 1])
with col1:
    st.caption("选择策略 → 扫描市场 → 发现机会")
with col2:
    _scan_clicked = st.button("🚀 快速扫描", type="primary")

if _scan_clicked:
    st.write("⏳ 扫描中...（粗筛+精扫）")
    try:
        _ = scan_market(["v10_full"], max_workers=25)
    except Exception as e:
        st.error(f"❌ 扫描异常: {e}")
    else:
        st.success("扫描完成！结果已更新到下方列表")

# 显示今天的信号（扫描结果自动存入数据库，统一从此读取）
signals = get_signals(limit=50)
if signals:
    df_signals = pd.DataFrame(signals)
    # 只显示今天的信号
    today_str = datetime.now().strftime("%Y-%m-%d")
    df_signals = df_signals[df_signals["triggered_at"].str.startswith(today_str, na=False)]
    df_signals = df_signals.sort_values("triggered_at", ascending=False).drop_duplicates(subset=["code"], keep="first").head(15)
    cols = ["code", "name", "strategy", "price", "score", "grade", "triggered_at"]
    for c in cols:
        if c not in df_signals.columns:
            df_signals[c] = "" if c in ("grade",) else 0
    
    # 获取实时行情（并行加速）
    signal_codes = df_signals["code"].tolist()
    realtime_data = {}
    if signal_codes:
        signal_quotes = get_realtime_quotes_batch(signal_codes)
        realtime_data = {q["code"]: q for q in signal_quotes}
    
    # 构建显示数据
    rows = []
    for _, row in df_signals.iterrows():
        q = realtime_data.get(row["code"], {})
        cur_price = q.get("price", 0)
        pct = q.get("pct_change", 0)
        rows.append({
            "代码": row["code"],
            "名称": row["name"],
            "策略": row["strategy"],
            "信号价": row["price"] if row["price"] else 0,
            "现价": cur_price if cur_price else 0,
            "涨跌幅": pct,
            "得分": row["score"],
            "等级": row["grade"],
            "触发时间": row["triggered_at"],
        })
    
    df_display = pd.DataFrame(rows)
    
    if df_display.empty:
        st.info("今天暂无信号记录，点击「快速扫描」开始！")
    else:
        # 红涨绿跌配色
        def _color_pct(val):
            if isinstance(val, (int, float)):
                if val > 0: return "color: #ef4444; font-weight: 600"
                elif val < 0: return "color: #22c55e; font-weight: 600"
            return ""
        st.dataframe(
            df_display.style.format({
                "信号价": "¥{:.2f}", "现价": "¥{:.2f}", "涨跌幅": "{:+.2f}%", "得分": "{:.0f}",
            }).map(_color_pct, subset=["涨跌幅"]),
            width='stretch', hide_index=True,
        )
else:
    st.info("暂无信号记录，点击「快速扫描」开始！")

# 涨跌幅排行
st.subheader("📈 涨跌幅排行")
tab1, tab2, tab3 = st.tabs(["🔴 涨幅榜", "🟢 跌幅榜", "📊 板块热点"])

with tab1:
    try:
        gainers = get_top_gainers(15, df=_df_market)
        if not gainers.empty:
            gainers_display = gainers[["code", "name", "price", "pct_change", "turnover"]].copy()
            gainers_display.columns = ["代码", "名称", "现价", "涨跌幅", "换手率"]
            
            def _color_pct_red(val):
                if isinstance(val, (int, float)):
                    if val > 0: return "color: #ef4444; font-weight: 600"
                    elif val < 0: return "color: #22c55e; font-weight: 600"
                return ""
            
            st.dataframe(
                gainers_display.style.format({
                    "现价": "¥{:.2f}", "涨跌幅": "{:+.2f}%",
                    "换手率": "{:.2f}%"
                }).map(_color_pct_red, subset=["涨跌幅"]),
                width='stretch', hide_index=True,
            )
    except Exception as e:
        st.error(f"获取涨幅榜失败: {e}")

with tab2:
    try:
        losers = get_top_losers(15, df=_df_market)
        if not losers.empty:
            losers_display = losers[["code", "name", "price", "pct_change", "turnover"]].copy()
            losers_display.columns = ["代码", "名称", "现价", "涨跌幅", "换手率"]
            
            def _color_pct_green(val):
                if isinstance(val, (int, float)):
                    if val > 0: return "color: #ef4444; font-weight: 600"
                    elif val < 0: return "color: #22c55e; font-weight: 600"
                return ""
            
            st.dataframe(
                losers_display.style.format({
                    "现价": "¥{:.2f}", "涨跌幅": "{:+.2f}%",
                    "换手率": "{:.2f}%"
                }).map(_color_pct_green, subset=["涨跌幅"]),
                width='stretch', hide_index=True,
            )
    except Exception as e:
        st.error(f"获取跌幅榜失败: {e}")

with tab3:
    try:
        from core.data import get_sector_ranking
        sectors = get_sector_ranking(limit=20)
        if sectors:
            sector_data = []
            for s in sectors:
                pct = s.get("change_pct", 0)
                sector_data.append({"板块": s["name"], "涨幅": pct})
            if sector_data:
                max_pct = max(abs(s["涨幅"]) for s in sector_data) or 1
                html_parts = []
                html_parts.append('<div style="display:flex; flex-direction:column; gap:4px;">')
                for s2 in sorted(sector_data, key=lambda x: x["涨幅"], reverse=True)[:15]:
                    pct2 = s2["涨幅"]
                    bp = abs(pct2) / max_pct * 100
                    bc = "#ef4444" if pct2 >= 0 else "#22c55e"
                    sg = "▲" if pct2 >= 0 else "▼"
                    html_parts.append(f'<div style="display:flex; align-items:center; gap:8px; padding:4px 8px; border-radius:4px; background:var(--bg-card);"><span style="width:100px; font-size:0.85em; color:var(--text-primary);">{s2["板块"]}</span><div style="flex:1; height:18px; background:var(--border-color); border-radius:3px; overflow:hidden;"><div style="width:{bp:.0f}%; height:100%; background:{bc}; border-radius:3px;"></div></div><span style="width:70px; text-align:right; color:{bc}; font-weight:600; font-size:0.85em;">{sg} {pct2:+.2f}%</span></div>')
                html_parts.append("</div>")
                st.html("".join(html_parts))
        else:
            st.info("暂无板块数据")
    except Exception:
        pass


# 自选股行情
st.subheader("⭐ 自选股实时行情")
watchlist = get_watchlist()
if watchlist:
    # 并行获取行情
    wl_codes = [s["code"] for s in watchlist]
    wl_quotes = get_realtime_quotes_batch(wl_codes)
    wl_quote_map = {q["code"]: q for q in wl_quotes}
    
    wl_data = []
    for stock in watchlist:
        quote = wl_quote_map.get(stock["code"])
        if quote:
            wl_data.append({
                "代码": stock["code"],
                "名称": stock["name"],
                "分组": stock["group"],
                "价格": quote['price'],
                "涨跌幅": quote['pct_change'],
                "成交额": f"{quote['amount']/10000:.0f}万",
                "换手率": f"{quote['turnover']:.2f}%",
                "PE": f"{quote['pe']:.1f}" if quote.get('pe') and quote['pe'] > 0 else "-",
                "流通市值": f"{quote['circ_market_cap']:.0f}亿" if quote.get('circ_market_cap') and quote['circ_market_cap'] > 0 else "-",
            })
    
    if wl_data:
        df_wl = pd.DataFrame(wl_data)
        
        def _color_wl_pct(val):
            if isinstance(val, (int, float)):
                if val > 0: return "color: #ef4444; font-weight: 600"
                elif val < 0: return "color: #22c55e; font-weight: 600"
            return ""
        
        st.dataframe(
            df_wl.style.format({
                "价格": "¥{:.2f}", "涨跌幅": "{:+.2f}%",
            }).map(_color_wl_pct, subset=["涨跌幅"]),
            width='stretch', hide_index=True,
        )
    else:
        st.warning("无法获取自选股数据")
else:
    st.info("还没有添加自选股，去「自选股」页面添加吧！")

# 持仓概览
st.subheader("💼 持仓概览")
positions = get_positions()
if positions:
    # 并行获取所有持仓的实时行情
    pos_codes = [p["code"] for p in positions]
    pos_quotes_list = get_realtime_quotes_batch(pos_codes)
    pos_quotes = {q["code"]: q for q in pos_quotes_list}
    
    pos_data = []
    for p in positions:
        # 计算持仓盈亏
        current_price = pos_quotes.get(p["code"])
        if current_price:
            profit_pct = (current_price["price"] - p["buy_price"]) / p["buy_price"] * 100
            profit_amount = (current_price["price"] - p["buy_price"]) * p["quantity"]
            # 红涨绿跌配色
            profit_color = "#ff4b4b" if profit_pct >= 0 else "#00c853"
            
            # 获取持仓建议
            try:
                from core.data import get_stock_history
                from core.portfolio_advisor import analyze_position
                
                hist = get_stock_history(p["code"], days=250)
                if hist is not None and len(hist) >= 50:
                    close_arr = hist["close"].values.astype(np.float64)
                    high_arr = hist["high"].values.astype(np.float64)
                    low_arr = hist["low"].values.astype(np.float64)
                    vol_arr = hist["volume"].values.astype(np.float64)
                    open_arr = hist["open"].values.astype(np.float64)
                    
                    advice = analyze_position(
                        code=p["code"],
                        buy_price=p["buy_price"],
                        current_price=current_price["price"],
                        quantity=p["quantity"],
                        stop_loss=p.get("stop_loss", 0),
                        target_price=p.get("target_price", 0),
                        close=close_arr,
                        high=high_arr,
                        low=low_arr,
                        volume=vol_arr,
                        open_price=open_arr,
                    )
                    if advice:
                        action = advice.action
                        reason = advice.reason
                    else:
                        action = "📊 数据不足"
                        reason = "无法生成建议"
                else:
                    action = "📊 数据不足"
                    reason = "历史数据不足"
            except Exception as e:
                action = "⚠️ 分析失败"
                reason = str(e)[:20]
            
            pos_data.append({
                "代码": p["code"],
                "名称": p["name"],
                "买入价": f"¥{p['buy_price']:.2f}",
                "现价": f"¥{current_price['price']:.2f}",
                "数量": p["quantity"],
                "市值": f"¥{current_price['price'] * p['quantity']:,.0f}",
                "盈亏": f"¥{profit_amount:+.2f}",
                "盈亏%": f"{profit_pct:+.2f}%",
                "止损": f"¥{p.get('stop_loss', 0):.2f}" if p.get('stop_loss') else "-",
                "目标": f"¥{p.get('target_price', 0):.2f}" if p.get('target_price') else "-",
                "建议": action,
            })
        else:
            pos_data.append({
                "代码": p["code"],
                "名称": p["name"],
                "买入价": f"¥{p['buy_price']:.2f}",
                "现价": "获取失败",
                "数量": p["quantity"],
                "市值": "-",
                "盈亏": "-",
                "盈亏%": "-",
                "止损": f"¥{p.get('stop_loss', 0):.2f}" if p.get('stop_loss') else "-",
                "目标": f"¥{p.get('target_price', 0):.2f}" if p.get('target_price') else "-",
                "建议": "⚠️ 无法获取",
            })
    
    if pos_data:
        # 强制浅色下 DataFrame 单元格白底黑字
        _df = pd.DataFrame(pos_data)
        st.dataframe(
            _df.style.set_table_styles([
                {"selector": "th", "props": [("background", "var(--table-header-bg)"), ("color", "var(--table-header-color)"), ("font-weight", "600")]},
                {"selector": "td", "props": [("background", "var(--bg-card)"), ("color", "var(--text-primary)")]},
                {"selector": "tr:hover td", "props": [("background", "var(--table-row-hover)")]},
            ]),
            width='stretch', hide_index=True,
        )
    else:
        st.warning("无法获取持仓数据")
else:
    st.info("还没有添加持仓，去「持仓管理」页面添加吧！")
