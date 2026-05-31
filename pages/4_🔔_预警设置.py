"""预警设置页面"""
import streamlit as st
import os
import pandas as pd
from core.alerts import send_feishu_card
from core.db import get_db

st.set_page_config(page_title="预警设置", page_icon="🔔", layout="wide")
st.title("🔔 预警设置")
st.caption("配置飞书 Webhook、设置提醒规则")

# 飞书 Webhook 配置
st.subheader("🔗 飞书 Webhook 配置")
st.markdown("""
**配置步骤：**
1. 在飞书群聊中添加「自定义机器人」
2. 复制 Webhook URL
3. 粘贴到下方输入框
4. 点击「测试」验证连接
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
    if st.button("🧪 测试连接", use_container_width=True):
        if webhook_url:
            # 临时设置环境变量
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
    if st.button("💾 保存配置", use_container_width=True):
        if webhook_url:
            # 更新 .env 文件
            env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
            lines = []
            if os.path.exists(env_path):
                with open(env_path) as f:
                    lines = f.readlines()

            # 更新或添加
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
st.subheader("📏 预警规则")

col1, col2 = st.columns(2)
with col1:
    st.markdown("**策略信号预警**")
    signal_alert = st.checkbox("启用策略信号推送", value=True)
    alert_mode = st.radio("推送模式", ["即时推送", "扫描后汇总"], horizontal=True)

with col2:
    st.markdown("**自选股异动预警**")
    watchlist_alert = st.checkbox("启用自选股异动推送", value=True)
    pct_threshold = st.slider("涨跌幅阈值 (%)", 3, 10, 5)

# 历史预警记录
st.divider()
st.subheader("📜 预警历史")
# 从数据库获取
from core.db import get_db
with get_db() as conn:
    rows = conn.execute("SELECT * FROM alerts ORDER BY sent_at DESC LIMIT 50").fetchall()
    alerts = [dict(r) for r in rows]

if alerts:
    df = pd.DataFrame(alerts)
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("暂无预警记录")
