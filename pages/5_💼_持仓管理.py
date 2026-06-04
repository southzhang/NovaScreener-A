"""持仓管理页面 — 实盘盯盘 + 盈亏追踪 + 止损提醒"""
import streamlit as st
import pandas as pd
from datetime import datetime
from core.db import add_position, get_positions, sell_position, delete_position, update_position
from core.data import get_realtime_quote, get_stock_history
from core.recommend import calc_trailing_stop
from core.alerts import send_feishu_card
from core.ui import inject_global_css, render_theme_toggle, render_page_header
from core.portfolio_advisor import analyze_position
import numpy as np

st.set_page_config(page_title="持仓管理", page_icon="💼", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("💼 持仓管理", "实盘盯盘 · 盈亏追踪 · 三层止盈止损 · 飞书提醒")

# ===== 添加持仓 =====
st.html('<h2 style="margin-top:0;">➕ 添加持仓</h2>')

with st.form("add_position", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        code = st.text_input("股票代码", placeholder="600519")
    with col2:
        quantity = st.number_input("买入数量（股）", min_value=100, step=100, value=100)
    with col3:
        buy_price = st.number_input("买入价格", min_value=0.01, step=0.01, format="%.2f")
    with col4:
        st.write("")
        st.write("")
        auto_fetch = st.checkbox("自动获取股票名", value=True)

    col5, col6, col7 = st.columns(3)
    with col5:
        stop_loss = st.number_input("止损价（选填，0=自动计算）", min_value=0.0, step=0.01, format="%.2f")
    with col6:
        target_price = st.number_input("目标价（选填）", min_value=0.0, step=0.01, format="%.2f")
    with col7:
        notes = st.text_input("备注", placeholder="V10全买入信号")

    submitted = st.form_submit_button("✅ 添加持仓", type="primary", width='stretch')

    if submitted and code:
        code = code.strip()
        name = code
        if auto_fetch:
            quote = get_realtime_quote(code)
            if quote:
                name = quote["name"]
                if stop_loss == 0:
                    try:
                        df = get_stock_history(code, days=120)
                        if not df.empty and len(df) >= 20:
                            close = df["close"].values.astype(np.float64)
                            high = df["high"].values.astype(np.float64)
                            low = df["low"].values.astype(np.float64)
                            ts = calc_trailing_stop(close, high, low, buy_price)
                            stop_loss = ts.final_stop
                    except Exception:
                        stop_loss = round(buy_price * 0.86, 2)

        position_id = add_position(
            code=code, name=name, buy_price=buy_price, quantity=quantity,
            stop_loss=round(stop_loss, 2), target_price=round(target_price, 2),
            notes=notes
        )
        st.success(f"✅ 已添加 {name}({code}) {quantity}股 @ ¥{buy_price}")
        st.rerun()


# ===== 当前持仓 =====
st.divider()
st.html('<h2>📊 当前持仓</h2>')

positions = get_positions(status="holding")

if not positions:
    st.info("📭 暂无持仓，请在上方添加")
else:
    codes = [p["code"] for p in positions]
    quotes = {}
    for code in codes:
        q = get_realtime_quote(code)
        if q:
            quotes[code] = q

    total_cost = 0
    total_value = 0
    total_pnl = 0

    for p in positions:
        code = p["code"]
        q = quotes.get(code, {})
        current_price = q.get("price", p["buy_price"])
        cost = p["buy_price"] * p["quantity"]
        value = current_price * p["quantity"]
        pnl = value - cost
        total_cost += cost
        total_value += value
        total_pnl += pnl

    # 汇总卡片
    pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0
    s_color = "#ff4b4b" if total_pnl >= 0 else "#00c853"
    s_arrow = "▲" if total_pnl >= 0 else "▼"
    win_cnt = len([p for p in positions if quotes.get(p['code'], {}).get('price', 0) > p['buy_price']])
    lose_cnt = len([p for p in positions if quotes.get(p['code'], {}).get('price', 0) < p['buy_price']])

    sum_cols = st.columns(5)
    sum_items = [
        ("📦 持仓数", f"{len(positions)}只", "var(--text-primary)", ""),
        ("💰 总成本", f"¥{total_cost:,.0f}", "var(--text-primary)", ""),
        ("📈 总市值", f"¥{total_value:,.0f}", "var(--text-primary)", ""),
        ("💹 总盈亏", f"¥{total_pnl:+,.0f}", s_color, f"{s_arrow} {pnl_pct:+.2f}%"),
        ("📊 盈亏比", f"{win_cnt}盈 / {lose_cnt}亏", "var(--text-primary)", ""),
    ]
    for col, (label, value, color, sub) in zip(sum_cols, sum_items):
        with col:
            sub_html = f"<div class='dash-card-sub' style='color:{color};'>{sub}</div>" if sub else ""
            st.html(f"""
            <div class="dash-card" style="text-align:center;">
                <div class="dash-card-header">{label}</div>
                <div class="dash-card-value" style="color:{color};">{value}</div>
                {sub_html}
            </div>
            """)

    st.divider()

    # 逐只股票显示
    for p in positions:
        code = p["code"]
        q = quotes.get(code, {})
        current_price = q.get("price", p["buy_price"])
        pct_change = q.get("pct_change", 0)

        cost = p["buy_price"] * p["quantity"]
        value = current_price * p["quantity"]
        pnl = value - cost
        pnl_pct = (current_price - p["buy_price"]) / p["buy_price"] * 100 if p["buy_price"] > 0 else 0

        stop_loss = p.get("stop_loss", 0)
        target_price = p.get("target_price", 0)

        # 三层止盈止损 + 持仓顾问分析
        try:
            df = get_stock_history(code, days=250)
            if not df.empty and len(df) >= 20:
                close_arr = df["close"].values.astype(np.float64)
                high_arr = df["high"].values.astype(np.float64)
                low_arr = df["low"].values.astype(np.float64)
                vol_arr = df["volume"].values.astype(np.float64)
                open_arr = df["open"].values.astype(np.float64)
                ts = calc_trailing_stop(close_arr, high_arr, low_arr, p["buy_price"])
                trailing_info = ts

                # 持仓顾问分析
                advisor = analyze_position(
                    code=code, buy_price=p["buy_price"],
                    current_price=current_price, quantity=p["quantity"],
                    stop_loss=stop_loss, target_price=target_price,
                    close=close_arr, high=high_arr, low=low_arr,
                    volume=vol_arr, open_price=open_arr,
                )
            else:
                trailing_info = None
                advisor = None
        except Exception:
            trailing_info = None
            advisor = None

        # 风险等级
        if trailing_info:
            risk_level = trailing_info.risk_level
        elif stop_loss > 0 and current_price <= stop_loss:
            risk_level = "⛔ 触发"
        elif stop_loss > 0 and (current_price - stop_loss) / current_price * 100 < 3:
            risk_level = "🔴 预警"
        else:
            risk_level = "🟢 安全"

        # 卡片颜色
        pnl_color = "#ff4b4b" if pnl >= 0 else "#00c853"
        chg_color = "#ff4b4b" if pct_change >= 0 else "#00c853"
        chg_arrow = "▲" if pct_change >= 0 else "▼"
        pnl_arrow = "▲" if pnl >= 0 else "▼"

        # 止损距离
        if stop_loss > 0:
            loss_from_stop = (current_price - stop_loss) / current_price * 100
            stop_html = f"<span style='color:{('#ff4b4b' if loss_from_stop < 3 else 'var(--text-muted)')};'>¥{stop_loss} ({loss_from_stop:+.1f}%)</span>"
        else:
            stop_html = "<span style='color:var(--text-muted);'>未设置</span>"

        if target_price > 0:
            gain_to_target = (target_price - current_price) / current_price * 100
            target_html = f"<span style='color:var(--text-secondary);'>¥{target_price} ({gain_to_target:+.1f}%)</span>"
        else:
            target_html = "<span style='color:var(--text-muted);'>未设置</span>"

        atr_html = f"<span style='color:var(--text-secondary);'>¥{trailing_info.atr_stop}</span>" if trailing_info else ""

        risk_bg = "#ff4b4b10" if "触发" in risk_level else "#ffab4010" if "预警" in risk_level else "var(--bg-card)"
        risk_border = "#ff4b4b40" if "触发" in risk_level else "#ffab4040" if "预警" in risk_level else "var(--border-color)"

        st.html(f"""
        <div class="position-card" style="border-color:{risk_border}; background: linear-gradient(135deg, var(--bg-card) 0%, {risk_bg} 100%);">
            <div class="position-card-header">
                <div>
                    <span style="font-size:1.2em;">{'🔴' if pnl >= 0 else '🟢'}</span>
                    <span style="font-weight:700; color:var(--text-primary); font-size:1.15em; margin-left:4px;">{p['name']}</span>
                    <span style="color:var(--text-secondary); margin-left:8px;">{code}</span>
                </div>
                <div style="text-align:right;">
                    <span style="font-size:0.82em; color:var(--text-muted);">风险状态</span><br>
                    <span style="font-weight:600;">{risk_level}</span>
                </div>
            </div>
            <div style="display:flex; justify-content:space-around; flex-wrap:wrap; gap:12px;">
                <div class="position-metric">
                    <div class="position-metric-label">现价</div>
                    <div class="position-metric-value">¥{current_price:.2f}</div>
                    <div style="color:{chg_color}; font-size:0.85em;">{chg_arrow} {pct_change:+.1f}%</div>
                </div>
                <div class="position-metric">
                    <div class="position-metric-label">买入价</div>
                    <div class="position-metric-value">¥{p['buy_price']:.2f}</div>
                </div>
                <div class="position-metric">
                    <div class="position-metric-label">持仓量</div>
                    <div class="position-metric-value">{p['quantity']}股</div>
                </div>
                <div class="position-metric">
                    <div class="position-metric-label">成本</div>
                    <div class="position-metric-value">¥{cost:,.0f}</div>
                </div>
                <div class="position-metric">
                    <div class="position-metric-label">市值</div>
                    <div class="position-metric-value">¥{value:,.0f}</div>
                </div>
                <div class="position-metric">
                    <div class="position-metric-label">盈亏</div>
                    <div class="position-metric-value" style="color:{pnl_color};">¥{pnl:+,.0f}</div>
                    <div style="color:{pnl_color}; font-size:0.85em;">{pnl_arrow} {pnl_pct:+.2f}%</div>
                </div>
                <div class="position-metric">
                    <div class="position-metric-label">止损</div>
                    <div class="position-metric-value">{stop_html}</div>
                </div>
                <div class="position-metric">
                    <div class="position-metric-label">目标</div>
                    <div class="position-metric-value">{target_html}</div>
                </div>
                {"<div class='position-metric'><div class='position-metric-label'>ATR止盈</div><div class='position-metric-value'>" + atr_html + "</div></div>" if atr_html else ""}
            </div>
        </div>
        """)

        # ===== 操作建议面板 =====
        if advisor:
            # 紧急程度颜色
            urg_colors = {1: "#00c853", 2: "#42a5f5", 3: "#ffab40", 4: "#ff6b35", 5: "#ff4b4b"}
            urg_color = urg_colors.get(advisor.urgency, "var(--text-muted)")

            # 风险条颜色
            if advisor.risk_score >= 50:
                risk_bar_color = "#ff4b4b"
            elif advisor.risk_score >= 30:
                risk_bar_color = "#ffab40"
            else:
                risk_bar_color = "#00c853"

            st.html(f"""
            <div style="background:var(--bg-card); border:1px solid {urg_color}40;
                        border-left:4px solid {urg_color}; border-radius:10px; padding:14px 18px; margin:8px 0;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                    <div>
                        <span style="font-size:1.15em; font-weight:700; color:{urg_color};">{advisor.action}</span>
                        <span style="color:var(--text-secondary); margin-left:12px;">{advisor.reason}</span>
                    </div>
                    <div style="text-align:right;">
                        <span style="font-size:0.8em; color:var(--text-muted);">风险</span>
                        <span style="font-weight:700; color:{risk_bar_color}; margin-left:4px;">{advisor.risk_score}</span>
                        <span style="font-size:0.8em; color:var(--text-muted);">/100</span>
                    </div>
                </div>
                <div style="display:flex; gap:16px; flex-wrap:wrap; margin-top:8px; font-size:0.85em;">
                    <span style="color:var(--text-secondary);">📊 趋势: <b style="color:{'#00c853' if '多头' in advisor.trend else '#ff4b4b' if '空头' in advisor.trend else '#ffab40'};">{advisor.trend}</b></span>
                    <span style="color:var(--text-secondary);">🏆 {advisor.v10_state}</span>
                    {f'<span style="color:var(--text-secondary);">📉 {advisor.swing_state}</span>' if advisor.swing_state else ''}
                    <span style="color:var(--text-secondary);">🛑 动态止损: <b style="color:#ff4b4b;">¥{advisor.dynamic_stop}</b></span>
                    <span style="color:var(--text-secondary);">🎯 动态目标: <b style="color:#00c853;">¥{advisor.dynamic_target}</b></span>
                </div>
                <div style="margin-top:6px; font-size:0.82em; color:var(--text-secondary);">
                    {" · ".join(advisor.details[:5])}
                </div>
                <!-- 风险条 -->
                <div style="background:var(--border-color); border-radius:4px; height:4px; margin-top:8px; overflow:hidden;">
                    <div style="background:{risk_bar_color}; height:100%; width:{advisor.risk_score}%; border-radius:4px; transition:width 0.3s;"></div>
                </div>
            </div>
            """)

        # 止损触发提醒
        if trailing_info and "触发" in trailing_info.risk_level:
            st.error(f"⛔ **{p['name']}** {trailing_info.action} | ATR止盈¥{trailing_info.atr_stop} | EMA20¥{trailing_info.ema20_value} | 结构支撑¥{trailing_info.structure_support}")
        elif trailing_info and "预警" in trailing_info.risk_level:
            st.warning(f"🔴 **{p['name']}** {trailing_info.action} | 距止损还有{(current_price - trailing_info.final_stop) / current_price * 100:.1f}%")

        # 操作按钮
        btn_cols = st.columns([1, 1, 1, 3])
        with btn_cols[0]:
            if st.button(f"📤 卖出", key=f"sell_{p['id']}"):
                sell_position(p["id"], current_price)
                st.success(f"已卖出 {p['name']} @ ¥{current_price}")
                st.rerun()
        with btn_cols[1]:
            if st.button(f"🗑️ 删除", key=f"del_{p['id']}"):
                delete_position(p["id"])
                st.rerun()
        with btn_cols[2]:
            if st.button(f"🔔 止损提醒", key=f"alert_{p['id']}"):
                if stop_loss > 0:
                    msg = f"⚠️ {p['name']}({code}) 现价¥{current_price} | 止损价¥{stop_loss} | 距止损{(current_price - stop_loss) / current_price * 100:.1f}%"
                    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": msg}}]
                    if send_feishu_card(f"止损提醒: {p['name']}", elements):
                        st.success("已发送飞书提醒！")
                    else:
                        st.warning("发送失败，请检查Webhook配置")

        st.html("<hr style='margin:8px 0;'>")


# ===== 已卖出记录 =====
with st.expander("📋 已卖出记录"):
    sold = get_positions(status="sold")
    if not sold:
        st.info("暂无卖出记录")
    else:
        sold_data = []
        for p in sold:
            pnl = (p.get("sell_price", 0) - p["buy_price"]) * p["quantity"]
            pnl_pct = (p.get("sell_price", 0) - p["buy_price"]) / p["buy_price"] * 100 if p["buy_price"] > 0 else 0
            sold_data.append({
                "代码": p["code"],
                "名称": p["name"],
                "买入价": f"¥{p['buy_price']:.2f}",
                "卖出价": f"¥{p.get('sell_price', 0):.2f}",
                "数量": p["quantity"],
                "盈亏": f"¥{pnl:+,.0f}",
                "收益率": f"{pnl_pct:+.2f}%",
                "买入日": p.get("buy_date", ""),
                "卖出日": p.get("sell_date", ""),
            })
        st.dataframe(pd.DataFrame(sold_data), width='stretch', hide_index=True)
