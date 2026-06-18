"""预警设置页面"""
import streamlit as st
import os
import pandas as pd
from core.alerts import send_feishu_card
from core.db import get_db
from core.ui import inject_global_css, render_theme_toggle, render_page_header

st.set_page_config(page_title="预警设置", page_icon="🔔", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("🔔 预警设置", "配置飞书 Webhook、设置提醒规则")

# 飞书 Webhook 配置
st.html('<h2 style="margin-top:0;">🔗 飞书 Webhook 配置</h2>')
st.html("""
<div style="color:var(--text-secondary); line-height:2; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:16px 20px;">
<strong style="color:var(--accent);">配置步骤：</strong><br>
1. 在飞书群聊中添加「自定义机器人」<br>
2. 复制 Webhook URL<br>
3. 粘贴到下方输入框<br>
4. 点击「测试」验证连接
</div>
""")

current_url = os.getenv("FEISHU_WEBHOOK_URL", "")
webhook_url = st.text_input(
    "Webhook URL",
    value=current_url,
    placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_HOOK_ID",
    type="password",
)

col1, col2 = st.columns(2)
with col1:
    if st.button("🧪 测试连接", width='stretch'):
        if webhook_url:
            os.environ["FEISHU_WEBHOOK_URL"] = webhook_url
            success = send_feishu_card(
                "🔔 测试消息",
                [{
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "✅ 量化盯盘选股预警配置成功！\n\n后续策略信号和自选股异动将通过此 Webhook 推送。",
                    },
                }],
            )
            if success:
                st.success("✅ 测试消息发送成功！请检查飞书群。")
            else:
                st.error("❌ 发送失败，请检查 Webhook URL 是否正确")
        else:
            st.warning("请输入 Webhook URL")

with col2:
    if st.button("💾 保存配置", width='stretch'):
        if webhook_url:
            env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
            lines = []
            if os.path.exists(env_path):
                with open(env_path) as f:
                    lines = f.readlines()

            found = False
            new_lines = []
            for line in lines:
                if line.startswith("FEISHU_WEBHOOK_URL="):
                    new_lines.append(f"FEISHU_WEBHOOK_URL={webhook_url}\n")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"FEISHU_WEBHOOK_URL={webhook_url}\n")

            with open(env_path, "w") as f:
                f.writelines(new_lines)

            os.environ["FEISHU_WEBHOOK_URL"] = webhook_url
            st.success("✅ 配置已保存到 .env 文件")
        else:
            st.warning("请输入 Webhook URL")

# 预警规则
st.divider()
st.html('<h2>📏 预警规则</h2>')

col1, col2 = st.columns(2)
with col1:
    st.html("""
    <div style="background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:16px; margin-bottom:12px;">
        <div style="color:var(--accent); font-weight:600; margin-bottom:8px;">📡 策略信号预警</div>
    </div>
    """)
    signal_alert = st.checkbox("启用策略信号推送", value=True)
    alert_mode = st.radio("推送模式", ["即时推送", "扫描后汇总"], horizontal=True)

with col2:
    st.html("""
    <div style="background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:16px; margin-bottom:12px;">
        <div style="color:var(--accent); font-weight:600; margin-bottom:8px;">⭐ 自选股异动预警</div>
    </div>
    """)
    watchlist_alert = st.checkbox("启用自选股异动推送", value=True)
    pct_threshold = st.slider("涨跌幅阈值 (%)", 3, 10, 5)

# 持仓预警
st.divider()
st.html("""
<div style="background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:10px; padding:16px; margin-bottom:12px;">
    <div style="color:var(--accent); font-weight:600; margin-bottom:4px;">💼 持仓预警</div>
    <div style="color:var(--text-muted); font-size:0.85em;">基于V10策略+趋势波段分析，当持仓股出现减仓/清仓/止盈/加仓信号时自动推送飞书通知</div>
</div>
""")
position_alert = st.checkbox("启用持仓预警推送", value=True)
st.caption("⚠️ 需同时开启盯盘监控（盯盘监控页面）才会生效，监控器每轮检查持仓并推送紧急程度≥3的操作建议")

# 历史预警记录
st.divider()
st.html('<h2>📜 预警历史</h2>')
with get_db() as conn:
    rows = conn.execute("SELECT * FROM alerts ORDER BY sent_at DESC LIMIT 50").fetchall()
    alerts = [dict(r) for r in rows]

if alerts:
    df = pd.DataFrame(alerts)
    st.dataframe(df, width='stretch', hide_index=True)
else:
    st.info("暂无预警记录")
