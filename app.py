"""量化盯盘选股 V10 — 完整版 Streamlit 主入口"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
from core.db import init_db, get_signals, get_watchlist, add_watchlist, remove_watchlist, get_positions
from core.data import get_stock_list, get_top_gainers, get_top_losers, get_realtime_quote, get_stock_history
from core.strategies import STRATEGY_REGISTRY, get_strategy_names
from core.scanner import scan_market, scan_watchlist, get_market_overview
from core.scorer import score_stock, score_batch
from core.monitor import get_monitor, start_monitoring, stop_monitoring
from core.alerts import send_feishu_card, send_batch_signals
from core.ui import inject_global_css, render_theme_toggle

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
    
    # 监控状态
    monitor = get_monitor()
    status = monitor.get_status()
    
    if status["running"]:
        st.success(f"🟢 盯盘监控运行中")
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

# ===== 主页面 =====
# 主题切换按钮（右上角）
render_theme_toggle()

st.html("""
<div style="padding: 10px 0 20px 0;">
    <h2 style="margin:0; color:#ff6b35; font-size: 1.8em;">📊 V10 量化盯盘选股</h2>
    <p style="margin:5px 0 0 0; color:#888; font-size: 0.95em;">维加斯V10强庄策略 · 七条件共振 · 波段回调 · 多维评分 · 盯盘监控</p>
</div>
""")

# 市场概览（红涨绿跌）
st.subheader("🏛️ 市场概览")
overview = get_market_overview()

_mkt_html = f"""
<div style="display:flex; gap:12px; flex-wrap:wrap;">
  <div style="flex:1; background:var(--bg-secondary); border:1px solid #1e2d40; border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">总股票数</div>
    <div style="font-size:1.6em; font-weight:700;">{overview.get("total", 0)}</div>
  </div>
  <div style="flex:1; background:var(--bg-secondary); border:1px solid #1e2d40; border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">上涨</div>
    <div style="font-size:1.6em; font-weight:700; color:#ef4444;">{overview.get("up", 0)}</div>
    <div style="color:#ef4444; font-size:0.85em;">▲ {overview.get("up_ratio", 0)}%</div>
  </div>
  <div style="flex:1; background:var(--bg-secondary); border:1px solid #1e2d40; border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">下跌</div>
    <div style="font-size:1.6em; font-weight:700; color:#22c55e;">{overview.get("down", 0)}</div>
  </div>
  <div style="flex:1; background:var(--bg-secondary); border:1px solid #1e2d40; border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">涨停</div>
    <div style="font-size:1.6em; font-weight:700; color:#ef4444;">{overview.get("limit_up", 0)}</div>
    <div style="color:#ef4444; font-size:0.85em;">家</div>
  </div>
  <div style="flex:1; background:var(--bg-secondary); border:1px solid #1e2d40; border-radius:10px; padding:14px; text-align:center;">
    <div style="color:var(--text-muted); font-size:0.85em;">跌停</div>
    <div style="font-size:1.6em; font-weight:700; color:#22c55e;">{overview.get("limit_down", 0)}</div>
    <div style="color:#22c55e; font-size:0.85em;">家</div>
  </div>
</div>
"""
st.html(_mkt_html)

# V10 策略信号
st.subheader("🏆 V10 策略信号")

# 快速扫描
col1, col2 = st.columns([3, 1])
with col1:
    st.caption("选择策略 → 扫描市场 → 发现机会")
with col2:
    if st.button("🚀 快速扫描", type="primary"):
        with st.spinner("扫描中..."):
            results = scan_market(["v10_full"], max_workers=8)
            if results:
                st.success(f"找到 {len(results)} 个V10信号！")
                for r in results[:5]:
                    with st.container():
                        cols = st.columns([1, 2, 1, 1, 2])
                        with cols[0]:
                            st.markdown(f"**{r['code']}**")
                        with cols[1]:
                            st.markdown(f"**{r['name']}**")
                        with cols[2]:
                            st.markdown(f"¥{r['price']}")
                        with cols[3]:
                            st.markdown(f"**{r['signal_type']}**")
                        with cols[4]:
                            st.markdown(" ".join(r['tags'][:3]))
            else:
                st.info("未找到V10信号（可能非交易时间或无符合条件）")

# 涨跌幅排行
st.subheader("📈 涨跌幅排行")
tab1, tab2 = st.tabs(["🔴 涨幅榜", "🟢 跌幅榜"])

with tab1:
    try:
        gainers = get_top_gainers(15)
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
        losers = get_top_losers(15)
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

# 最近信号（含实时涨跌幅）
st.subheader("🎯 最近策略信号")
signals = get_signals(limit=50)
if signals:
    df_signals = pd.DataFrame(signals)
    df_signals = df_signals.sort_values("triggered_at", ascending=False).drop_duplicates(subset=["code"], keep="first").head(15)
    cols = ["code", "name", "strategy", "price", "score", "grade", "triggered_at"]
    for c in cols:
        if c not in df_signals.columns:
            df_signals[c] = "" if c in ("grade",) else 0
    
    # 获取实时行情
    realtime_data = {}
    for _, row in df_signals.iterrows():
        q = get_realtime_quote(row["code"])
        if q:
            realtime_data[row["code"]] = q
    
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
            "信号价": f"¥{row['price']:.2f}" if row["price"] else "-",
            "现价": f"¥{cur_price:.2f}" if cur_price else "-",
            "涨跌幅": pct,
            "得分": row["score"],
            "等级": row["grade"],
            "触发时间": row["triggered_at"],
        })
    
    df_display = pd.DataFrame(rows)
    
    # 红涨绿跌配色
    def _color_pct(val):
        if isinstance(val, (int, float)):
            if val > 0:
                return "color: #ef4444; font-weight: 600"
            elif val < 0:
                return "color: #22c55e; font-weight: 600"
        return ""
    
    df_styled = df_display.style.map(_color_pct, subset=["涨跌幅"])
    st.dataframe(
        df_styled,
        width='stretch', hide_index=True,
        column_config={
            "涨跌幅": st.column_config.NumberColumn("涨跌幅", format="%+.2f%%"),
        }
    )
else:
    st.info("暂无信号记录，点击「快速扫描」开始！")

# 自选股行情
st.subheader("⭐ 自选股实时行情")
watchlist = get_watchlist()
if watchlist:
    wl_data = []
    for stock in watchlist:
        quote = get_realtime_quote(stock["code"])
        if quote:
            wl_data.append({
                "代码": stock["code"],
                "名称": stock["name"],
                "分组": stock["group"],
                "价格": quote['price'],
                "涨跌幅": quote['pct_change'],
                "成交额": f"{quote['amount']/10000:.0f}万",
                "换手率": f"{quote['turnover']:.2f}%",
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
    pos_data = []
    for p in positions:
        # 计算持仓盈亏
        current_price = get_realtime_quote(p["code"])
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
                "盈亏": "-",
                "盈亏%": "-",
                "止损": f"¥{p.get('stop_loss', 0):.2f}" if p.get('stop_loss') else "-",
                "目标": f"¥{p.get('target_price', 0):.2f}" if p.get('target_price') else "-",
                "建议": "⚠️ 无法获取",
            })
    
    if pos_data:
        st.dataframe(pd.DataFrame(pos_data), width='stretch', hide_index=True)
    else:
        st.warning("无法获取持仓数据")
else:
    st.info("还没有添加持仓，去「持仓管理」页面添加吧！")
