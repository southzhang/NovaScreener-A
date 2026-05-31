"""量化盯盘选股 V10 — 完整版 Streamlit 主入口"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
from core.db import init_db, get_signals, get_watchlist, add_watchlist, remove_watchlist
from core.data import get_stock_list, get_top_gainers, get_top_losers, get_realtime_quote, get_stock_history
from core.strategies import STRATEGY_REGISTRY, get_strategy_names
from core.scanner import scan_market, scan_watchlist, get_market_overview
from core.scorer import score_stock, score_batch
from core.monitor import get_monitor, start_monitoring, stop_monitoring
from core.alerts import send_feishu_card, send_batch_signals

# 初始化
load_dotenv()
init_db()

st.set_page_config(
    page_title="V10 量化盯盘选股",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===== 自定义样式 =====
st.markdown("""
<style>
    .metric-card {
        background: #1e1e1e;
        border-radius: 8px;
        padding: 15px;
        border-left: 4px solid #4CAF50;
    }
</style>
""", unsafe_allow_html=True)

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
    
    if st.button("🔄 刷新数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ===== 主页面 =====
st.markdown("""
<div style="padding: 10px 0 20px 0;">
    <h2 style="margin:0; color:#ff6b35; font-size: 1.8em;">📊 V10 量化盯盘选股</h2>
    <p style="margin:5px 0 0 0; color:#888; font-size: 0.95em;">维加斯V10强庄策略 · 七条件共振 · 波段回调 · 多维评分 · 盯盘监控</p>
</div>
""", unsafe_allow_html=True)

# 市场概览
st.subheader("🏛️ 市场概览")
overview = get_market_overview()

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("总股票数", overview.get("total", 0))
with col2:
    st.metric("上涨", overview.get("up", 0), delta=f"{overview.get('up_ratio', 0)}%")
with col3:
    st.metric("下跌", overview.get("down", 0))
with col4:
    st.metric("涨停", overview.get("limit_up", 0), delta="家")
with col5:
    st.metric("跌停", overview.get("limit_down", 0), delta="家")

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
            st.dataframe(
                gainers.style.format({
                    "price": "¥{:.2f}", "pct_change": "{:+.2f}%",
                    "turnover": "{:.2f}%"
                }),
                use_container_width=True, hide_index=True,
            )
    except Exception as e:
        st.error(f"获取涨幅榜失败: {e}")

with tab2:
    try:
        losers = get_top_losers(15)
        if not losers.empty:
            st.dataframe(
                losers.style.format({
                    "price": "¥{:.2f}", "pct_change": "{:+.2f}%",
                    "turnover": "{:.2f}%"
                }),
                use_container_width=True, hide_index=True,
            )
    except Exception as e:
        st.error(f"获取跌幅榜失败: {e}")

# 最近信号
st.subheader("🎯 最近策略信号")
signals = get_signals(limit=20)
if signals:
    df_signals = pd.DataFrame(signals)
    st.dataframe(
        df_signals[["code", "name", "strategy", "price", "detail", "triggered_at"]],
        use_container_width=True, hide_index=True,
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
                "价格": f"¥{quote['price']:.2f}",
                "涨跌幅": f"{quote['pct_change']:+.2f}%",
                "成交额": f"{quote['amount']/10000:.0f}万",
                "换手率": f"{quote['turnover']:.2f}%",
            })
    
    if wl_data:
        st.dataframe(pd.DataFrame(wl_data), use_container_width=True, hide_index=True)
    else:
        st.warning("无法获取自选股数据")
else:
    st.info("还没有添加自选股，去「自选股」页面添加吧！")
