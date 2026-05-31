"""量化盯盘选股 V10 — Streamlit 主入口"""
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from core.db import init_db, get_signals, get_watchlist
from core.data import get_stock_list, get_top_gainers, get_top_losers
from core.strategies import STRATEGY_REGISTRY

# 初始化
load_dotenv()
init_db()

st.set_page_config(
    page_title="量化盯盘选股 V10",
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
    .v10-badge {
        background: linear-gradient(135deg, #ff6b35 0%, #f7931e 100%);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 0.9em;
    }
</style>
""", unsafe_allow_html=True)

# ===== 侧边栏 =====
with st.sidebar:
    st.title("📊 量化盯盘选股")
    st.markdown('<span class="v10-badge">V10 通达信全买入公式</span>', unsafe_allow_html=True)
    st.caption("维加斯强庄策略 + 波段回调")
    st.divider()
    st.markdown("**策略引擎:** V10 全买入公式")
    st.markdown("**数据源:** akshare + 腾讯K线")
    st.markdown("**内置策略:** " + str(len(STRATEGY_REGISTRY)) + " 个")
    st.divider()
    if st.button("🔄 刷新数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ===== 主页面 =====
st.title("📊 Dashboard")
st.caption("V10 策略信号 · 市场概览 · 自选股行情")

# V10 策略概览
st.subheader("🏆 V10 策略引擎")
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("隧道趋势", "EMA120/200", delta="长期趋势")
with col2:
    st.metric("短线通道", "EMA5/20", delta="通道间距>0.8%")
with col3:
    st.metric("QW动能", "自定义", delta="SMA(RSV,9)")
with col4:
    st.metric("强庄控盘", "加权价格", delta="突变检测")

st.caption("V10 全买入 = 隧道多头 + 双线定式 + QW上升 + 通道间距 + 放量阳线 + 强庄控盘 + MACD金叉")

# 市场概览
st.subheader("🏛️ 市场概览")
col1, col2, col3, col4 = st.columns(4)

all_stocks = pd.DataFrame()
try:
    all_stocks = get_stock_list()
    if not all_stocks.empty:
        up_count = len(all_stocks[all_stocks["pct_change"] > 0])
        down_count = len(all_stocks[all_stocks["pct_change"] < 0])
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
    st.info("暂无信号记录，去「选股扫描」页面运行V10策略吧！")

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
