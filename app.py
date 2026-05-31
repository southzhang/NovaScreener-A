"""量化盯盘选股 - Streamlit 主入口"""
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from core.db import init_db, get_signals, get_watchlist
from core.data import get_stock_list, get_top_gainers, get_top_losers, get_sector_hot
from core.strategies import STRATEGY_REGISTRY

# 初始化
load_dotenv()
init_db()

st.set_page_config(
    page_title="量化盯盘选股",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===== 自定义样式 =====
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 12px;
        padding: 20px;
        color: white;
        text-align: center;
    }
    .metric-value { font-size: 2em; font-weight: bold; }
    .metric-label { font-size: 0.9em; opacity: 0.8; }
    .signal-card {
        background: #1e1e1e;
        border-left: 4px solid #4CAF50;
        padding: 12px;
        margin: 8px 0;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

# ===== 侧边栏 =====
with st.sidebar:
    st.title("📊 量化盯盘选股")
    st.caption("A股量化选股 & 盯盘工具")
    st.divider()
    st.markdown("**数据源**: akshare (免费)")
    st.markdown("**策略数**: " + str(len(STRATEGY_REGISTRY)))
    st.divider()
    if st.button("🔄 刷新数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ===== 主页面 =====
st.title("📊 Dashboard")
st.caption("市场概览 · 今日信号 · 自选股行情")

all_stocks = pd.DataFrame()

# 市场概览
st.subheader("🏛️ 市场概览")
col1, col2, col3, col4 = st.columns(4)

try:
    all_stocks = get_stock_list()
    if not all_stocks.empty:
        up_count = len(all_stocks[all_stocks["pct_change"] > 0])
        down_count = len(all_stocks[all_stocks["pct_change"] < 0])
        flat_count = len(all_stocks[all_stocks["pct_change"] == 0])
        limit_up = len(all_stocks[all_stocks["pct_change"] >= 9.9])
        limit_down = len(all_stocks[all_stocks["pct_change"] <= -9.9])

        with col1:
            st.metric("上涨", f"{up_count}", delta="家")
        with col2:
            st.metric("下跌", f"{down_count}", delta="家")
        with col3:
            st.metric("涨停", f"{limit_up}", delta="家")
        with col4:
            st.metric("跌停", f"{limit_down}", delta="家")
    else:
        st.warning("暂无市场数据（可能非交易时间）")
except Exception as e:
    st.error(f"获取市场数据失败: {e}")

# 涨跌幅排行
st.subheader("📈 涨跌幅排行")
tab1, tab2 = st.tabs(["🔴 涨幅榜", "🟢 跌幅榜"])

with tab1:
    try:
        gainers = get_top_gainers(15)
        if not gainers.empty:
            display_cols = ["code", "name", "price", "pct_change", "volume", "amount", "turnover"]
            available = [c for c in display_cols if c in gainers.columns]
            st.dataframe(
                gainers[available].style.format({
                    "price": "¥{:.2f}", "pct_change": "{:+.2f}%",
                    "amount": "{:,.0f}", "turnover": "{:.2f}%"
                }),
                use_container_width=True, hide_index=True,
            )
    except Exception as e:
        st.error(f"获取涨幅榜失败: {e}")

with tab2:
    try:
        losers = get_top_losers(15)
        if not losers.empty:
            display_cols = ["code", "name", "price", "pct_change", "volume", "amount", "turnover"]
            available = [c for c in display_cols if c in losers.columns]
            st.dataframe(
                losers[available].style.format({
                    "price": "¥{:.2f}", "pct_change": "{:+.2f}%",
                    "amount": "{:,.0f}", "turnover": "{:.2f}%"
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
    st.info("暂无信号记录，去「选股扫描」页面运行策略吧！")

# 自选股行情
st.subheader("⭐ 自选股行情")
watchlist = get_watchlist()
if watchlist:
    wl_codes = [w["code"] for w in watchlist]
    try:
        wl_data = all_stocks[all_stocks["code"].isin(wl_codes)] if not all_stocks.empty else pd.DataFrame()
        if not wl_data.empty:
            display_cols = ["code", "name", "price", "pct_change", "volume", "amount"]
            available = [c for c in display_cols if c in wl_data.columns]
            st.dataframe(
                wl_data[available].style.format({
                    "price": "¥{:.2f}", "pct_change": "{:+.2f}%",
                    "amount": "{:,.0f}"
                }),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("自选股数据暂不可用")
    except Exception as e:
        st.error(f"获取自选股数据失败: {e}")
else:
    st.info("还没有添加自选股，去「自选股」页面添加吧！")
