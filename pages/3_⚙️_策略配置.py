"""策略配置页面"""
import streamlit as st
import json
from core.strategies import STRATEGY_REGISTRY, get_strategy_names
from core.db import save_strategy, get_strategies

st.set_page_config(page_title="策略配置", page_icon="⚙️", layout="wide")
st.title("⚙️ 策略配置")
st.caption("编辑策略参数、启用/禁用策略")

# 内置策略列表
st.subheader("📋 内置策略")
for key in get_strategy_names():
    info = STRATEGY_REGISTRY[key]
    with st.expander(f"📊 {info['name']} ({key})"):
        st.markdown(f"**说明**: {info['desc']}")
        st.markdown(f"**默认参数**:")
        st.json(info.get("default_params", {}))

# 自定义策略配置
st.divider()
st.subheader("🛠️ 自定义策略参数")

# 加载已保存的策略配置
saved = get_strategies()
saved_dict = {s["name"]: s for s in saved}

# 编辑每个策略的参数
for key in get_strategy_names():
    info = STRATEGY_REGISTRY[key]
    default_params = info.get("default_params", {})
    saved_params = saved_dict.get(key, {}).get("params", {})

    if default_params:
        st.markdown(f"### {info['name']}")
        params = {}
        cols = st.columns(len(default_params))
        for i, (pkey, pval) in enumerate(default_params.items()):
            with cols[i]:
                current = saved_params.get(pkey, pval)
                if isinstance(pval, int):
                    params[pkey] = st.number_input(
                        pkey, value=int(current), key=f"cfg_{key}_{pkey}"
                    )
                elif isinstance(pval, float):
                    params[pkey] = st.number_input(
                        pkey, value=float(current), step=0.1, format="%.2f",
                        key=f"cfg_{key}_{pkey}",
                    )

        col1, col2 = st.columns(2)
        with col1:
            enabled = saved_dict.get(key, {}).get("enabled", 1) == 1
            if st.button(
                f"{'禁用' if enabled else '启用'} {info['name']}",
                key=f"toggle_{key}",
            ):
                save_strategy(key, params, not enabled)
                st.success(f"已{'禁用' if enabled else '启用'}")
                st.rerun()
        with col2:
            if st.button(f"💾 保存 {info['name']} 参数", key=f"save_{key}"):
                save_strategy(key, params, enabled)
                st.success(f"已保存 {info['name']} 参数")

# 回测预览
st.divider()
st.subheader("📈 策略回测预览")
st.info("💡 选择一只股票，查看策略信号在历史数据上的表现")

from core.data import get_stock_history
from core.strategies import ema_fast, calc_ma, calc_rsi, calc_bollinger
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

test_code = st.text_input("输入股票代码进行回测", value="000001")
test_strategy = st.selectbox(
    "选择策略",
    get_strategy_names(),
    format_func=lambda x: STRATEGY_REGISTRY[x]["name"],
)

if st.button("运行回测") and test_code:
    hist = get_stock_history(test_code, days=250)
    if hist.empty:
        st.error("无法获取历史数据")
    else:
        # 找出所有触发点
        strategy_info = STRATEGY_REGISTRY[test_strategy]
        func = strategy_info["func"]
        params = strategy_info.get("default_params", {})

        trigger_dates = []
        for i in range(30, len(hist)):
            window = hist.iloc[:i+1]
            try:
                if func(window, params):
                    trigger_dates.append(hist.iloc[i]["date"])
            except:
                pass

        # 画图
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=hist["date"], open=hist["open"],
            high=hist["high"], low=hist["low"],
            close=hist["close"], name="K线",
        ))

        if trigger_dates:
            trigger_prices = [hist[hist["date"] == d]["close"].values[0] for d in trigger_dates]
            fig.add_trace(go.Scatter(
                x=trigger_dates, y=trigger_prices,
                mode="markers", name="买入信号",
                marker=dict(size=12, color="yellow", symbol="triangle-up"),
            ))

        fig.update_layout(
            height=500, template="plotly_dark",
            title=f"{test_code} - {strategy_info['name']} 回测",
            xaxis_rangeslider_visible=False,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.info(f"在过去250个交易日中，共触发 {len(trigger_dates)} 次信号")
