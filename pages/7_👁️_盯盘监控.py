"""盯盘监控页面 — 实时行情 + 异动提醒"""
import streamlit as st
import pandas as pd
from datetime import datetime
from core.monitor import get_monitor, start_monitoring, stop_monitoring
from core.data import get_realtime_quote
from core.db import get_watchlist as db_get_watchlist
from core.alerts import send_feishu_card

st.set_page_config(page_title="盯盘监控", page_icon="👁️", layout="wide")
st.title("👁️ 盯盘监控")
st.caption("实时行情 · 异动提醒 · 飞书通知")

# 监控状态
monitor = get_monitor()
status = monitor.get_status()

st.subheader("📊 监控状态")
col1, col2, col3, col4 = st.columns(4)
with col1:
    if status["running"]:
        st.success("🟢 运行中")
    else:
        st.error("🔴 已停止")
with col2:
    st.metric("监控股票", status["watchlist_count"])
with col3:
    st.metric("今日提醒", status["alerts_sent"])
with col4:
    st.metric("最后更新", status["last_update"])

# 控制按钮
col1, col2 = st.columns(2)
with col1:
    if not status["running"]:
        if st.button("▶ 启动监控", type="primary", use_container_width=True):
            start_monitoring()
            st.rerun()
    else:
        if st.button("⏹ 停止监控", use_container_width=True):
            stop_monitoring()
            st.rerun()

with col2:
    interval = st.selectbox("刷新间隔", [15, 30, 60, 120], index=1)

# 自选股实时行情
st.subheader("⭐ 自选股实时行情")

watchlist = db_get_watchlist()
if watchlist:
    # 手动刷新按钮
    if st.button("🔄 刷新行情"):
        st.rerun()
    
    # 获取实时行情
    quotes = []
    for stock in watchlist:
        quote = get_realtime_quote(stock["code"])
        if quote:
            quotes.append({
                "代码": stock["code"],
                "名称": stock["name"],
                "分组": stock["group"],
                "价格": f"¥{quote['price']:.2f}",
                "涨跌幅": quote["pct_change"],
                "涨跌幅显示": f"{quote['pct_change']:+.2f}%",
                "成交额": f"{quote['amount']/10000:.0f}万",
                "换手率": f"{quote['turnover']:.2f}%",
                "最高": f"¥{quote['high']:.2f}",
                "最低": f"¥{quote['low']:.2f}",
            })
    
    if quotes:
        df = pd.DataFrame(quotes)
        
        # 高亮涨跌幅
        def highlight_pct(val):
            if isinstance(val, (int, float)):
                if val > 0:
                    return 'color: #ef5350'
                elif val < 0:
                    return 'color: #26a69a'
            return ''
        
        st.dataframe(
            df.style.map(highlight_pct, subset=['涨跌幅']),
            use_container_width=True,
            hide_index=True,
        )
        
        # 异动提醒
        st.subheader("⚠️ 异动提醒")
        
        anomalies = [q for q in quotes if abs(q["涨跌幅"]) > 5]
        if anomalies:
            for q in anomalies:
                if q["涨跌幅"] > 5:
                    st.warning(f"📈 **{q['名称']}**（{q['代码']}）大涨 {q['涨跌幅显示']} — 当前价 {q['价格']}")
                else:
                    st.error(f"📉 **{q['名称']}**（{q['代码']}）大跌 {q['涨跌幅显示']} — 当前价 {q['价格']}")
        else:
            st.info("暂无异动")
    else:
        st.warning("无法获取行情数据")
else:
    st.info("还没有添加自选股")

# 预警历史
st.divider()
st.subheader("📜 预警历史")

from core.db import get_db
with get_db() as conn:
    rows = conn.execute("SELECT * FROM alerts ORDER BY sent_at DESC LIMIT 50").fetchall()
    alerts = [dict(r) for r in rows]

if alerts:
    df = pd.DataFrame(alerts)
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("暂无预警记录")

# 飞书通知配置
st.divider()
st.subheader("🔔 飞书通知配置")

import os
webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "")
if webhook_url:
    st.success("✅ 飞书 Webhook 已配置")
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
