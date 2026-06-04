"""盯盘监控页面 — 实时行情 + 异动提醒"""
import streamlit as st
import pandas as pd
from datetime import datetime
from core.monitor import get_monitor, start_monitoring, stop_monitoring
from core.data import get_realtime_quote
from core.db import get_watchlist as db_get_watchlist
from core.alerts import send_feishu_card
from core.ui import inject_global_css, render_theme_toggle, render_page_header, render_status_badge

st.set_page_config(page_title="盯盘监控", page_icon="👁️", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("👁️ 盯盘监控", "实时行情 · 异动提醒 · 飞书通知")

# 监控状态
monitor = get_monitor()
status = monitor.get_status()

st.html('<h2 style="margin-top:0;">📊 监控状态</h2>')

# 状态卡片
status_items = [
    ("运行状态", "🟢 运行中" if status["running"] else "🔴 已停止", "#00c853" if status["running"] else "#ff4b4b"),
    ("监控股票", f"{status['watchlist_count']}", "var(--text-primary)"),
    ("今日提醒", f"{status['alerts_sent']}", "#ff6b35"),
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

    quotes = []
    for stock in watchlist:
        quote = get_realtime_quote(stock["code"])
        if quote:
            quotes.append({
                "代码": stock["code"],
                "名称": stock["name"],
                "分组": stock["group"],
                "价格": quote['price'],
                "涨跌幅": quote['pct_change'],  # 已经是百分比值
                "成交额": quote['amount'] / 1e8,
                "换手率": quote['turnover'],  # 已经是百分比值
                "最高": quote['high'],
                "最低": quote['low'],
            })

    if quotes:
        df = pd.DataFrame(quotes)

        def highlight_pct(val):
            if isinstance(val, (int, float)):
                if val > 0:
                    return 'color: #ff4b4b'
                elif val < 0:
                    return 'color: #00c853'
            return ''

        st.dataframe(
            df.style.map(highlight_pct, subset=['涨跌幅']),
            width='stretch',
            hide_index=True,
            column_config={
                "价格": st.column_config.NumberColumn(format="¥%.2f"),
                "涨跌幅": st.column_config.NumberColumn(format="%.2f%%"),
                "成交额": st.column_config.NumberColumn(format="%.2f亿"),
                "换手率": st.column_config.NumberColumn(format="%.2f%%"),
                "最高": st.column_config.NumberColumn(format="¥%.2f"),
                "最低": st.column_config.NumberColumn(format="¥%.2f"),
            }
        )

        # 异动提醒
        st.html('<h2>⚠️ 异动提醒</h2>')

        anomalies = [q for q in quotes if abs(q["涨跌幅"]) > 5]
        if anomalies:
            for q in anomalies:
                pct_display = f"{q['涨跌幅']:+.2f}%"
                if q["涨跌幅"] > 5:
                    st.html(f"""
                    <div style="background:#ff4b4b10; border:1px solid #ff4b4b30; border-left:4px solid var(--up-color); border-radius:10px; padding:14px 18px; margin-bottom:10px;">
                        <span style="font-size:1.1em;">📈</span>
                        <span style="font-weight:700; color:var(--text-primary);">{q['名称']}</span>
                        <span style="color:var(--text-secondary);">（{q['代码']}）</span>
                        <span style="color:#ff4b4b; font-weight:600; margin-left:8px;">大涨 {pct_display}</span>
                        <span style="color:var(--text-secondary); margin-left:8px;">当前价 ¥{q['价格']:.2f}</span>
                    </div>
                    """)
                else:
                    st.html(f"""
                    <div style="background:#00c85310; border:1px solid #00c85330; border-left:4px solid var(--down-color); border-radius:10px; padding:14px 18px; margin-bottom:10px;">
                        <span style="font-size:1.1em;">📉</span>
                        <span style="font-weight:700; color:var(--text-primary);">{q['名称']}</span>
                        <span style="color:var(--text-secondary);">（{q['代码']}）</span>
                        <span style="color:#00c853; font-weight:600; margin-left:8px;">大跌 {pct_display}</span>
                        <span style="color:var(--text-secondary); margin-left:8px;">当前价 ¥{q['价格']:.2f}</span>
                    </div>
                    """)
        else:
            st.info("暂无异动")
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
    <div style="background:#00c85310; border:1px solid #00c85330; border-radius:10px; padding:14px 18px;">
        <span style="color:#00c853; font-weight:600;">✅ 飞书 Webhook 已配置</span>
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
