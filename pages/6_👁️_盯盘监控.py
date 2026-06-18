"""盯盘监控页面 — 实时行情 + 异动提醒 + 涨跌停预警 + 盘口详情"""
import streamlit as st
import pandas as pd
from datetime import datetime
from core.monitor import get_monitor, start_monitoring, stop_monitoring
from core.data import get_realtime_quote, get_realtime_quotes_batch, get_order_book, get_quote_brief
from core.db import get_watchlist as db_get_watchlist
from core.alerts import send_feishu_card
from core.ui import inject_global_css, render_theme_toggle, render_page_header, render_status_badge

st.set_page_config(page_title="盯盘监控", page_icon="👁️", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("👁️ 盯盘监控", "实时行情 · 异动提醒 · 涨跌停预警 · 盘口详情")

# 监控状态
monitor = get_monitor()
status = monitor.get_status()

st.html('<h2 style="margin-top:0;">📊 监控状态</h2>')

# 状态卡片
status_items = [
    ("运行状态", "🟢 运行中" if status["running"] else "🔴 已停止", "var(--down-color)" if status["running"] else "var(--up-color)"),
    ("监控股票", f"{status['watchlist_count']}", "var(--text-primary)"),
    ("今日提醒", f"{status['alerts_sent']}", "var(--accent)"),
    ("最后更新", status["last_update"], "var(--text-muted)"),
]
status_cols = st.columns(4)
for col, (label, value, color) in zip(status_cols, status_items):
    with col:
        st.html(f"""
        <div class="dash-card" style="text-align:center;">
            <div class="dash-card-header">{label}</div>
            <div class="dash-card-value" style="color:{color}; font-size:1.2em;">{value}</div>
        </div>
        """)

# 控制按钮
col1, col2 = st.columns(2)
with col1:
    if not status["running"]:
        if st.button("▶ 启动监控", type="primary", width='stretch'):
            start_monitoring()
            st.rerun()
    else:
        if st.button("⏹ 停止监控", width='stretch'):
            stop_monitoring()
            st.rerun()

with col2:
    interval = st.selectbox("刷新间隔", [15, 30, 60, 120], index=1)

# 自选股实时行情
st.html('<h2>⭐ 自选股实时行情</h2>')

watchlist = db_get_watchlist()
if watchlist:
    if st.button("🔄 刷新行情"):
        st.rerun()

    # 批量获取行情（含新字段：PE/市值/涨跌停/涨跌额）
    codes = [s["code"] for s in watchlist]
    quotes_list = get_realtime_quotes_batch(codes)
    quotes = {q["code"]: q for q in quotes_list}

    rows = []
    for stock in watchlist:
        q = quotes.get(stock["code"])
        if not q:
            continue
        price = q.get("price", 0)
        limit_up = q.get("limit_up", 0)
        limit_down = q.get("limit_down", 0)
        rows.append({
            "代码": stock["code"],
            "名称": stock["name"],
            "分组": stock["group"],
            "价格": price,
            "涨跌额": q.get("change_amt", 0),
            "涨跌幅": q.get("pct_change", 0),
            "成交额(亿)": q.get("amount", 0) / 10000 if q.get("amount") else 0,  # 万元→亿
            "换手率": q.get("turnover", 0),
            "PE": q.get("pe", 0),
            "流通市值(亿)": q.get("circ_market_cap", 0),
            "最高": q.get("high", 0),
            "最低": q.get("low", 0),
            "涨停价": limit_up,
            "跌停价": limit_down,
        })

    if rows:
        df = pd.DataFrame(rows)

        def highlight_pct(val):
            if isinstance(val, (int, float)):
                if val > 0:
                    return 'color: var(--up-color)'
                elif val < 0:
                    return 'color: var(--down-color)'
            return ''

        st.dataframe(
            df.style.map(highlight_pct, subset=['涨跌幅', '涨跌额']),
            width='stretch',
            hide_index=True,
            column_config={
                "价格": st.column_config.NumberColumn(format="¥%.2f"),
                "涨跌额": st.column_config.NumberColumn(format="¥%.2f"),
                "涨跌幅": st.column_config.NumberColumn(format="%.2f%%"),
                "成交额(亿)": st.column_config.NumberColumn(format="%.2f"),
                "换手率": st.column_config.NumberColumn(format="%.2f%%"),
                "PE": st.column_config.NumberColumn(format="%.1f"),
                "流通市值(亿)": st.column_config.NumberColumn(format="%.1f"),
                "最高": st.column_config.NumberColumn(format="¥%.2f"),
                "最低": st.column_config.NumberColumn(format="¥%.2f"),
                "涨停价": st.column_config.NumberColumn(format="¥%.2f"),
                "跌停价": st.column_config.NumberColumn(format="¥%.2f"),
            }
        )

        # ===== 异动提醒 =====
        st.html('<h2>⚠️ 异动提醒</h2>')

        anomalies = []
        for r in rows:
            alerts = []
            code = r["代码"]
            name = r["名称"]
            price = r["价格"]
            pct = r["涨跌幅"]
            limit_up = r["涨停价"]
            limit_down = r["跌停价"]

            # 大涨大跌
            if pct > 5:
                alerts.append(("📈 大涨", f"+{pct:.2f}%", "var(--up-color)"))
            elif pct < -5:
                alerts.append(("📉 大跌", f"{pct:.2f}%", "var(--down-color)"))

            # 逼近涨停（距涨停<2%）
            if limit_up > 0 and price > 0:
                pct_to_limit = (limit_up - price) / price * 100
                if 0 < pct_to_limit < 2:
                    alerts.append(("🔴 逼近涨停", f"距涨停¥{limit_up:.2f}仅{pct_to_limit:.1f}%", "var(--up-color)"))
                elif price >= limit_up:
                    alerts.append(("⛔ 涨停", f"已封涨停 ¥{limit_up:.2f}", "var(--up-color)"))

            # 逼近跌停
            if limit_down > 0 and price > 0:
                pct_to_down = (price - limit_down) / price * 100
                if 0 < pct_to_down < 2:
                    alerts.append(("🟢 逼近跌停", f"距跌停¥{limit_down:.2f}仅{pct_to_down:.1f}%", "var(--down-color)"))
                elif price <= limit_down:
                    alerts.append(("⛔ 跌停", f"已封跌停 ¥{limit_down:.2f}", "var(--down-color)"))

            for tag, detail, color in alerts:
                anomalies.append((code, name, price, tag, detail, color))

        if anomalies:
            for code, name, price, tag, detail, color in anomalies:
                bg = color.replace("#", "") + "10"
                border = color.replace("#", "") + "30"
                st.html(f"""
                <div style="background:#{bg}; border:1px solid #{border}; border-left:4px solid {color}; border-radius:10px; padding:14px 18px; margin-bottom:10px;">
                    <span style="font-weight:700; color:var(--text-primary);">{name}</span>
                    <span style="color:var(--text-secondary);">（{code}）</span>
                    <span style="color:{color}; font-weight:600; margin-left:8px;">{tag}</span>
                    <span style="color:var(--text-secondary); margin-left:8px;">{detail}</span>
                    <span style="color:var(--text-secondary); margin-left:8px;">¥{price:.2f}</span>
                </div>
                """)
        else:
            st.info("暂无异动")

        # ===== 盘口详情 =====
        st.html('<h2>📊 盘口详情</h2>')
        selected_code = st.selectbox(
            "选择股票查看盘口",
            options=[f"{r['名称']}({r['代码']})" for r in rows],
            key="monitor_orderbook_select"
        )
        if selected_code:
            # 从选项中提取代码
            sel_code = selected_code.split("(")[-1].rstrip(")")
            ob = get_order_book(sel_code)
            if ob:
                bid_cols = st.columns(5)
                ask_cols = st.columns(5)
                st.html('<div style="display:flex;justify-content:space-between;font-size:0.82em;color:var(--text-muted);margin-bottom:2px;"><span>🟢 买盘</span><span>🔴 卖盘</span></div>')
                for i in range(5):
                    bid = ob.get(f"bid{i+1}", (0, 0))
                    ask = ob.get(f"ask{i+1}", (0, 0))
                    with bid_cols[i]:
                        st.html(f"""
                        <div style="text-align:center; background:var(--down-color)10; border-radius:6px; padding:6px 4px;">
                            <div style="font-size:0.75em; color:var(--text-muted);">买{i+1}</div>
                            <div style="color:var(--up-color); font-weight:600;">¥{bid[0]:.2f}</div>
                            <div style="color:var(--down-color); font-size:0.85em;">{bid[1]}手</div>
                        </div>
                        """)
                    with ask_cols[i]:
                        st.html(f"""
                        <div style="text-align:center; background:var(--up-color)10; border-radius:6px; padding:6px 4px;">
                            <div style="font-size:0.75em; color:var(--text-muted);">卖{i+1}</div>
                            <div style="color:var(--up-color); font-weight:600;">¥{ask[0]:.2f}</div>
                            <div style="color:var(--up-color); font-size:0.85em;">{ask[1]}手</div>
                        </div>
                        """)

                # 委比
                cr = ob.get("commission_ratio", 0)
                cd = ob.get("commission_diff", 0)
                if cr != 0:
                    cr_color = "var(--up-color)" if cr > 0 else "var(--down-color)"
                    cr_arrow = "▲" if cr > 0 else "▼"
                    st.html(f"""
                    <div style="display:flex; gap:24px; font-size:0.9em; margin-top:8px; justify-content:center;">
                        <span style="color:var(--text-secondary);">委比 <b style="color:{cr_color};">{cr_arrow} {abs(cr)*100:.1f}%</b></span>
                        <span style="color:var(--text-secondary);">委差 <b style="color:{cr_color};">{cd:+.0f}万</b></span>
                        <span style="color:var(--text-secondary);">内盘比 <b>{ob.get('inner_ratio', 0)*100:.1f}%</b></span>
                        <span style="color:var(--text-secondary);">外盘比 <b>{ob.get('outer_ratio', 0)*100:.1f}%</b></span>
                    </div>
                    """)
            else:
                st.caption("暂无盘口数据（非交易时段可能无数据）")

    else:
        st.warning("无法获取行情数据")
else:
    st.info("还没有添加自选股")

# 预警历史
st.divider()
st.html('<h2>📜 预警历史</h2>')

from core.db import get_db
with get_db() as conn:
    rows = conn.execute("SELECT * FROM alerts ORDER BY sent_at DESC LIMIT 50").fetchall()
    alerts = [dict(r) for r in rows]

if alerts:
    df = pd.DataFrame(alerts)
    st.dataframe(df, width='stretch', hide_index=True)
else:
    st.info("暂无预警记录")

# 飞书通知配置
st.divider()
st.html('<h2>🔔 飞书通知配置</h2>')

import os
webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "")
if webhook_url:
    st.html(f"""
    <div style="background:var(--down-color)10; border:1px solid var(--down-color)30; border-radius:10px; padding:14px 18px;">
        <span style="color:var(--down-color); font-weight:600;">✅ 飞书 Webhook 已配置</span>
    </div>
    """)
    if st.button("🧪 测试通知"):
        elements = [{
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "✅ 盯盘监控测试通知\n\n监控功能正常工作！",
            },
        }]
        if send_feishu_card("🔔 盯盘监控测试", elements):
            st.success("测试消息已发送！")
        else:
            st.error("发送失败")
else:
    st.warning("⚠️ 飞书 Webhook 未配置")
    st.caption("请在「预警设置」页面配置 Webhook URL")
