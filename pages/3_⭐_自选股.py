"""自选股管理页面"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from core.db import add_watchlist, remove_watchlist, get_watchlist, get_watchlist_groups
from core.data import get_stock_list, get_stock_history
from core.strategies import ema_fast, calc_ma
from core.ui import inject_global_css, render_theme_toggle, render_page_header

st.set_page_config(page_title="自选股", page_icon="⭐", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("⭐ 自选股管理", "管理你的自选股列表，查看K线图")

# 添加自选股
st.html('<h2 style="margin-top:0;">➕ 添加自选股</h2>')
col1, col2, col3 = st.columns([2, 2, 1])

all_stocks = get_stock_list()

with col1:
    search_code = st.text_input("股票代码", placeholder="如 000001")
with col2:
    search_name = st.text_input("股票名称", placeholder="如 平安银行")
    if search_name and not all_stocks.empty:
        matches = all_stocks[all_stocks["name"].str.contains(search_name, na=False)].head(5)
        if not matches.empty:
            suggestions = [f"{row['code']} {row['name']}" for _, row in matches.iterrows()]
            st.caption("💡 " + " | ".join(suggestions))
with col3:
    group = st.text_input("分组", value="默认")
    if st.button("添加", width='stretch'):
        code = search_code.strip()
        name = search_name.strip()
        if code and name:
            add_watchlist(code, name, group)
            st.success(f"已添加 {name}({code})")
            st.rerun()
        elif code and not name:
            if not all_stocks.empty:
                match = all_stocks[all_stocks["code"] == code]
                if not match.empty:
                    name = match.iloc[0]["name"]
                    add_watchlist(code, name, group)
                    st.success(f"已添加 {name}({code})")
                    st.rerun()
                else:
                    st.error("未找到该股票代码")
            else:
                st.error("请输入股票代码和名称")
        else:
            st.warning("请输入股票代码")

# 自选股列表
st.html('<h2>📋 自选股列表</h2>')
watchlist = get_watchlist()
if watchlist:
    groups = get_watchlist_groups()
    filter_group = st.selectbox("按分组筛选", ["全部"] + groups)
    if filter_group != "全部":
        watchlist = [w for w in watchlist if w["group"] == filter_group]

    df = pd.DataFrame(watchlist)
    if not df.empty and not all_stocks.empty:
        codes = df["code"].tolist()
        realtime = all_stocks[all_stocks["code"].isin(codes)]
        if not realtime.empty:
            display = df.merge(
                realtime[["code", "price", "pct_change", "volume", "amount"]],
                on="code", how="left"
            )
            if "amount" in display.columns:
                display["amount"] = display["amount"] / 1e8
            display = display.rename(columns={
                "code": "代码", "name": "名称", "group": "分组",
                "price": "价格", "pct_change": "涨跌幅",
                "volume": "成交量", "amount": "成交额(亿)"
            })
            fmt = {"价格": "¥{:.2f}", "涨跌幅": "{:+.2f}%", "成交额(亿)": "{:.2f}"}
            st.dataframe(
                display.style.format(fmt),
                width='stretch', hide_index=True,
            )

    # 删除操作
    st.html('<h3>🗑️ 删除自选股</h3>')
    del_code = st.selectbox("选择要删除的股票", [f"{w['code']} {w['name']}" for w in watchlist])
    if st.button("删除", type="secondary"):
        code = del_code.split(" ")[0]
        remove_watchlist(code)
        st.success(f"已删除 {del_code}")
        st.rerun()
else:
    st.info("还没有添加自选股")

# K线图
st.divider()
st.html('<h2>📈 K线图</h2>')
if watchlist:
    kline_code = st.selectbox(
        "选择股票查看K线",
        [f"{w['code']} {w['name']}" for w in watchlist],
        key="kline_select",
    )
    period = st.selectbox("周期", ["日K", "周K", "月K"], key="kline_period")
    period_map = {"日K": "daily", "周K": "weekly", "月K": "monthly"}

    if kline_code:
        code = kline_code.split(" ")[0]
        hist = get_stock_history(code, days=120)
        if not hist.empty:
            hist["ma5"] = calc_ma(hist["close"], 5)
            hist["ma10"] = calc_ma(hist["close"], 10)
            hist["ma20"] = calc_ma(hist["close"], 20)

            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                vertical_spacing=0.03, row_heights=[0.7, 0.3],
            )

            fig.add_trace(
                go.Candlestick(
                    x=hist["date"], open=hist["open"],
                    high=hist["high"], low=hist["low"],
                    close=hist["close"], name="K线",
                    increasing_line_color="#ef5350",
                    decreasing_line_color="#26a69a",
                ),
                row=1, col=1,
            )

            for ma, color, name in [(5, "#FFD700", "MA5"), (10, "#FF69B4", "MA10"), (20, "#00BFFF", "MA20")]:
                col = f"ma{ma}"
                if col in hist.columns:
                    fig.add_trace(
                        go.Scatter(x=hist["date"], y=hist[col], name=name, line=dict(color=color, width=1)),
                        row=1, col=1,
                    )

            colors = ["#ef5350" if c >= o else "#26a69a" for c, o in zip(hist["close"], hist["open"])]
            fig.add_trace(
                go.Bar(x=hist["date"], y=hist["volume"], name="成交量", marker_color=colors),
                row=2, col=1,
            )

            # 根据主题选择图表配色
            _is_dark = st.session_state.get("theme", "light") == "dark"
            fig.update_layout(
                height=600, xaxis_rangeslider_visible=False,
                template="plotly_dark" if _is_dark else "plotly_white", showlegend=True,
                margin=dict(l=50, r=50, t=30, b=30),
                paper_bgcolor="#0a0e17" if _is_dark else "#ffffff",
                plot_bgcolor="#0f1520" if _is_dark else "#f8f9fb",
                font=dict(color="#c8cdd8" if _is_dark else "#0f1419"),
            )
            _grid = "#1e2d40" if _is_dark else "#e2e8f0"
            fig.update_xaxes(type="category", nticks=20, gridcolor=_grid)
            fig.update_yaxes(gridcolor=_grid)
            st.plotly_chart(fig, width='stretch')
        else:
            st.warning("无法获取K线数据")
else:
    st.info("请先添加自选股")
