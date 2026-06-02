"""策略回测页面 — 选股+选策略+选周期 → 跑回测 → 展示结果"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core.data import get_kline, get_stock_name
from core.strategies import STRATEGY_REGISTRY
from core.backtest import run_backtest
from core.ui import inject_global_css, render_theme_toggle

st.set_page_config(page_title="策略回测", page_icon="📊", layout="wide")
inject_global_css()
render_theme_toggle()

# ── 隐藏默认元素 ──
st.html("""
<style>
    #MainMenu, header, footer {visibility: hidden;}
    .stDeployButton {display: none;}
    .block-container {padding-top: 1rem;}
</style>
""")

st.title("📊 策略回测")
st.caption("选择股票 → 选择策略 → 选择周期 → 运行回测 → 查看收益曲线和交易明细")

# ── 输入区 ──
col_input, col_params = st.columns([2, 1])

with col_input:
    # 股票输入
    stock_code = st.text_input(
        "股票代码",
        value=st.session_state.get("bt_stock", ""),
        placeholder="输入6位代码，如 000001",
    ).strip()

    if stock_code:
        stock_name = get_stock_name(stock_code)
        st.caption(f"📌 {stock_name} ({stock_code})")
    else:
        stock_name = stock_code

    # 策略选择
    strategy_options = {v["name"]: k for k, v in STRATEGY_REGISTRY.items()}
    strategy_display = st.selectbox("选择策略", list(strategy_options.keys()))
    strategy_key = strategy_options[strategy_display]

    # 周期选择
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        period_options = {
            "日K": "day",
            "周K": "week",
            "月K": "month",
        }
        period_display = st.selectbox("K线周期", list(period_options.keys()))
        period = period_options[period_display]

    with col_p2:
        lookback_options = {
            "近3个月": 60,
            "近6个月": 120,
            "近1年": 250,
            "近2年": 500,
            "近3年": 750,
            "全部数据": 1500,
        }
        lookback_display = st.selectbox("回看范围", list(lookback_options.keys()), index=2)
        lookback = lookback_options[lookback_display]

with col_params:
    st.markdown("#### ⚙️ 交易参数")
    stop_loss = st.slider("止损 %", 1.0, 15.0, 5.0, 0.5)
    take_profit = st.slider("止盈 %", 2.0, 30.0, 10.0, 1.0)
    max_hold = st.slider("最大持仓天数", 3, 60, 20, 1)
    use_signal_exit = st.checkbox("信号反转卖出", value=True,
                                   help="持仓期间如果出现反向信号则卖出")

# ── 运行回测 ──
if st.button("🚀 开始回测", type="primary", width='stretch'):
    if not stock_code:
        st.error("请输入股票代码")
        st.stop()

    with st.spinner(f"正在获取 {stock_code} {period_display}数据..."):
        df = get_kline(stock_code, period=period, count=lookback)

    if df is None or df.empty:
        st.error(f"获取 {stock_code} K线数据失败")
        st.stop()

    dates = df["date"].values
    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    volume = df["volume"].values.astype(float)
    open_price = df["open"].values.astype(float)

    with st.spinner(f"正在回测 {strategy_display} 策略（{len(close)}根K线）..."):
        result = run_backtest(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_key=strategy_key,
            dates=dates,
            close=close,
            high=high,
            low=low,
            volume=volume,
            open_price=open_price,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
            max_hold_bars=max_hold,
            use_signal_exit=use_signal_exit,
        )

    st.session_state["bt_result"] = result
    st.session_state["bt_df"] = df

# ── 显示回测结果 ──
if "bt_result" in st.session_state:
    result = st.session_state["bt_result"]
    df = st.session_state["bt_df"]

    st.divider()

    # ===== 核心指标卡片 =====
    st.subheader(f"📋 {result.stock_name} · {result.strategy_name} · {result.period_name}")

    # 顶部概览指标
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        color = "#ef4444" if result.total_return >= 0 else "#22c55e"
        st.html(f"""
        <div style="text-align:center;padding:12px;background:#1a1a2e;border-radius:10px;">
            <div style="font-size:12px;color:#888;">总收益率</div>
            <div style="font-size:22px;font-weight:700;color:{color};">{result.total_return:+.2f}%</div>
        </div>""")
    with c2:
        st.html(f"""
        <div style="text-align:center;padding:12px;background:#1a1a2e;border-radius:10px;">
            <div style="font-size:12px;color:#888;">交易次数</div>
            <div style="font-size:22px;font-weight:700;">{len(result.trades)}</div>
        </div>""")
    with c3:
        st.html(f"""
        <div style="text-align:center;padding:12px;background:#1a1a2e;border-radius:10px;">
            <div style="font-size:12px;color:#888;">胜率</div>
            <div style="font-size:22px;font-weight:700;color:#00d4aa;">{result.win_rate:.1f}%</div>
        </div>""")
    with c4:
        st.html(f"""
        <div style="text-align:center;padding:12px;background:#1a1a2e;border-radius:10px;">
            <div style="font-size:12px;color:#888;">盈亏比</div>
            <div style="font-size:22px;font-weight:700;color:#fbbf24;">{result.profit_factor:.2f}</div>
        </div>""")
    with c5:
        st.html(f"""
        <div style="text-align:center;padding:12px;background:#1a1a2e;border-radius:10px;">
            <div style="font-size:12px;color:#888;">最大回撤</div>
            <div style="font-size:22px;font-weight:700;color:#ef4444;">-{result.max_drawdown:.2f}%</div>
        </div>""")
    with c6:
        st.html(f"""
        <div style="text-align:center;padding:12px;background:#1a1a2e;border-radius:10px;">
            <div style="font-size:12px;color:#888;">最大连亏</div>
            <div style="font-size:22px;font-weight:700;color:#ef4444;">{result.max_consecutive_losses}次</div>
        </div>""")

    # 详细统计
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.markdown(f"""
        | 指标 | 数值 |
        |---|---|
        | 📈 盈利次数 | {result.total_win} |
        | 📉 亏损次数 | {result.total_loss} |
        | 💰 平均盈利 | {result.avg_win_pnl:+.2f}% |
        | 💸 平均亏损 | {result.avg_loss_pnl:+.2f}% |
        | 📊 平均每笔 | {result.avg_trade_pnl:+.2f}% |
        """)

    with col_s2:
        # 持仓时间统计
        if result.trades:
            hold_bars = [t.bars_held for t in result.trades]
            st.markdown(f"""
        | 指标 | 数值 |
        |---|---|
        | ⏱ 平均持仓 | {np.mean(hold_bars):.1f}天 |
        | ⏱ 最短持仓 | {min(hold_bars)}天 |
        | ⏱ 最长持仓 | {max(hold_bars)}天 |
        | 🎯 信号次数 | {len(result.signal_dates)} |
        """)

    # ===== K线图 + 权益曲线 =====
    st.subheader("📈 K线走势与买卖点")

    # 获取K线数据
    dates_arr = df["date"].values
    close_arr = df["close"].values.astype(float)
    high_arr = df["high"].values.astype(float)
    low_arr = df["low"].values.astype(float)
    open_arr = df["open"].values.astype(float)

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3],
    )

    # K线
    colors_up = '#ef4444'
    colors_down = '#22c55e'

    fig.add_trace(go.Candlestick(
        x=dates_arr,
        open=open_arr,
        high=high_arr,
        low=low_arr,
        close=close_arr,
        increasing_line_color=colors_up,
        decreasing_line_color=colors_down,
        increasing_fillcolor=colors_up,
        decreasing_fillcolor=colors_down,
        name="K线",
    ), row=1, col=1)

    # 均线
    for ma_period in [5, 20, 60]:
        if len(close_arr) >= ma_period:
            ma = pd.Series(close_arr).rolling(ma_period).mean().values
            fig.add_trace(go.Scatter(
                x=dates_arr, y=ma,
                line=dict(width=1),
                name=f"MA{ma_period}",
                opacity=0.6,
            ), row=1, col=1)

    # 买卖点标记
    for t in result.trades:
        # 买入点
        fig.add_trace(go.Scatter(
            x=[t.entry_date],
            y=[t.entry_price],
            mode="markers",
            marker=dict(symbol="triangle-up", size=14, color=colors_up),
            name=f"买 {t.entry_price}",
            hovertext=f"买入 {t.entry_price}<br>{t.entry_date}",
            showlegend=False,
        ), row=1, col=1)

        # 卖出点
        sell_color = colors_up if t.pnl_pct > 0 else colors_down
        fig.add_trace(go.Scatter(
            x=[t.exit_date],
            y=[t.exit_price],
            mode="markers",
            marker=dict(symbol="triangle-down", size=14, color=sell_color),
            name=f"卖 {t.exit_price} ({t.pnl_pct:+.1f}%)",
            hovertext=f"卖出 {t.exit_price}<br>{t.exit_reason}<br>{t.pnl_pct:+.2f}%",
            showlegend=False,
        ), row=1, col=1)

    # 权益曲线
    if result.equity_curve:
        eq_dates = [e[0] for e in result.equity_curve]
        eq_values = [e[1] / 10000 for e in result.equity_curve]  # 转万元
        fig.add_trace(go.Scatter(
            x=eq_dates,
            y=eq_values,
            line=dict(color="#00d4aa", width=2),
            fill="tozeroy",
            fillcolor="rgba(0,212,170,0.1)",
            name="权益(万)",
        ), row=2, col=1)

        # 基准线
        fig.add_hline(y=100, line_dash="dash", line_color="#888",
                       annotation_text="本金100万", row=2, col=1)

    fig.update_layout(
        height=700,
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=0, r=0, t=30, b=0),
    )
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="权益(万元)", row=2, col=1)

    st.plotly_chart(fig, width='stretch')

    # ===== 交易明细 =====
    st.subheader(f"📋 交易明细（共 {len(result.trades)} 笔）")

    if result.trades:
        trade_data = []
        for i, t in enumerate(result.trades, 1):
            pnl_color = "🔴" if t.pnl_pct >= 0 else "🟢"
            trade_data.append({
                "序号": i,
                "买入日期": t.entry_date,
                "买入价": f"{t.entry_price:.2f}",
                "卖出日期": t.exit_date,
                "卖出价": f"{t.exit_price:.2f}",
                "盈亏%": f"{t.pnl_pct:+.2f}%",
                "持仓天数": t.bars_held,
                "退出原因": t.exit_reason,
            })

        trade_df = pd.DataFrame(trade_data)

        # 用颜色标记
        def highlight_pnl(row):
            styles = [""] * len(row)
            pnl_val = float(row["盈亏%"].replace("%", "").replace("+", ""))
            color = "#ef4444" if pnl_val >= 0 else "#22c55e"
            idx = list(row.index).index("盈亏%")
            styles[idx] = f"color: {color}; font-weight: bold"
            return styles

        styled = trade_df.style.apply(highlight_pnl, axis=1)
        st.dataframe(styled, width='stretch', hide_index=True, height=min(len(result.trades) * 40 + 50, 500))

        # 收益分布图
        st.subheader("📊 收益分布")
        pnl_values = [t.pnl_pct for t in result.trades]
        fig_dist = go.Figure()
        fig_dist.add_trace(go.Bar(
            x=list(range(1, len(pnl_values) + 1)),
            y=pnl_values,
            marker_color=[colors_up if v >= 0 else colors_down for v in pnl_values],
            hovertemplate="第%{x}笔: %{y:+.2f}%<extra></extra>",
        ))
        fig_dist.add_hline(y=0, line_color="#888")
        fig_dist.update_layout(
            height=300,
            template="plotly_dark",
            xaxis_title="交易序号",
            yaxis_title="盈亏 %",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_dist, width='stretch')

    else:
        st.warning("该策略在选定周期内没有触发任何信号，尝试调整参数或换一个周期")
