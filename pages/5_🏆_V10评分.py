"""V10 综合评分页面 — 多维度评分 + 推荐"""
import streamlit as st
import pandas as pd
import numpy as np
from core.scorer import score_stock, score_batch
from core.data import get_realtime_quote, get_stock_history
from core.db import get_watchlist as db_get_watchlist
from core.alerts import send_feishu_card

st.set_page_config(page_title="V10 评分系统", page_icon="🏆", layout="wide")
st.title("🏆 V10 综合评分系统")
st.caption("多维度评分：技术面 + 资金面 + 基本面 + 波段回调")

# 评分维度说明
with st.expander("📊 评分维度详解"):
    st.markdown("""
    | 维度 | 权重 | 说明 |
    |------|------|------|
    | V10技术信号 | 40分 | 隧道+通道+QW+强庄+MACD+放量 |
    | 波段回调 | 25分 | EMA20/50/120 + RSI + MACD |
    | 资金面 | 20分 | 主力净流入 > 0 |
    | 基本面 | 15分 | ROE>5%, 净利润增速>0% |
    | 趋势强度 | 10分 | EMA多头排列 + 通道间距 |
    
    **推荐等级：**
    - 🔴 强烈推荐 (≥80分)
    - 🟠 值得关注 (60-79分)
    - 🟡 观察等待 (40-59分)
    - ⚪ 暂不推荐 (<40分)
    """)

# 输入方式
st.subheader("📋 股票输入")
input_mode = st.radio("输入方式", ["手动输入代码", "从自选股导入", "从V10观察池导入"], horizontal=True)

codes = []
if input_mode == "手动输入代码":
    code_input = st.text_area(
        "输入股票代码（每行一个）",
        placeholder="300065\n002185\n600936",
        height=150,
    )
    if code_input:
        codes = [c.strip() for c in code_input.strip().split("\n") if c.strip()]

elif input_mode == "从自选股导入":
    watchlist = db_get_watchlist()
    if watchlist:
        codes = [w["code"] for w in watchlist]
        st.info(f"已导入 {len(codes)} 只自选股")
    else:
        st.warning("自选股为空，请先添加")

elif input_mode == "从V10观察池导入":
    import os, json
    watchlist_path = os.path.expanduser("~/.hermes/cache/v10_watchlist.json")
    if os.path.exists(watchlist_path):
        with open(watchlist_path) as f:
            data = json.load(f)
        codes = [item.get("code", "") for item in data if item.get("code")]
        st.info(f"已导入 {len(codes)} 只V10观察池股票")
    else:
        st.warning("V10观察池文件不存在，请先运行V10扫描")

# 运行评分
if st.button("🚀 开始评分", type="primary", use_container_width=True) and codes:
    results = []
    progress = st.progress(0)
    status = st.empty()

    for i, code in enumerate(codes):
        pct = (i + 1) / len(codes)
        progress.progress(pct)
        status.text(f"评分中: {code} ({i+1}/{len(codes)})")

        try:
            # 获取K线
            df = get_stock_history(code, days=250)
            if df.empty or len(df) < 50:
                continue

            close = df["close"].values.astype(np.float64)
            high = df["high"].values.astype(np.float64)
            low = df["low"].values.astype(np.float64)
            volume = df["volume"].values.astype(np.float64)
            open_p = df["open"].values.astype(np.float64)

            # 获取实时价格
            quote = get_realtime_quote(code)
            price = quote["price"] if quote else close[-1]
            pct_change = quote["pct_change"] if quote else 0
            name = quote["name"] if quote else code

            # 评分
            result = score_stock(code, name, close, high, low, volume, open_p, price, pct_change)
            if result:
                results.append(result)

        except Exception as e:
            st.error(f"{code} 评分失败: {e}")

    progress.progress(1.0)
    status.text("评分完成！")

    if results:
        # 按总分排序
        results.sort(key=lambda x: x.total_score, reverse=True)

        st.success(f"✅ 完成 {len(results)} 只股票评分")

        # 分级展示
        st.subheader("📊 评分结果")

        # 强推 (>=80分)
        strong = [r for r in results if r.total_score >= 80]
        if strong:
            st.markdown("### 🔴 强烈推荐 (≥80分)")
            for r in strong:
                cols = st.columns([1, 2, 1, 1, 2, 2])
                with cols[0]:
                    st.markdown(f"**{r.code}**")
                with cols[1]:
                    st.markdown(f"**{r.name}**")
                with cols[2]:
                    st.markdown(f"¥{r.price:.2f}")
                with cols[3]:
                    st.markdown(f"**{r.total_score}分**")
                with cols[4]:
                    st.markdown(f"V10:{r.v10_score} 回调:{r.pullback_score}")
                with cols[5]:
                    st.markdown(" ".join(r.tags[:3]))

        # 关注 (60-79分)
        watch = [r for r in results if 60 <= r.total_score < 80]
        if watch:
            st.markdown("### 🟠 值得关注 (60-79分)")
            for r in watch:
                cols = st.columns([1, 2, 1, 1, 2, 2])
                with cols[0]:
                    st.markdown(f"**{r.code}**")
                with cols[1]:
                    st.markdown(f"**{r.name}**")
                with cols[2]:
                    st.markdown(f"¥{r.price:.2f}")
                with cols[3]:
                    st.markdown(f"**{r.total_score}分**")
                with cols[4]:
                    st.markdown(f"V10:{r.v10_score} 回调:{r.pullback_score}")
                with cols[5]:
                    st.markdown(" ".join(r.tags[:3]))

        # 观察 (40-59分)
        observe = [r for r in results if 40 <= r.total_score < 60]
        if observe:
            st.markdown("### 🟡 观察等待 (40-59分)")
            for r in observe:
                st.caption(f"{r.code} {r.name} — {r.total_score}分 — {' '.join(r.tags[:2])}")

        # 完整表格
        st.divider()
        st.subheader("📋 完整评分表")
        
        table_data = []
        for r in results:
            table_data.append({
                "代码": r.code,
                "名称": r.name,
                "价格": f"¥{r.price:.2f}",
                "涨跌幅": f"{r.pct_change:+.1f}%",
                "总分": r.total_score,
                "V10": r.v10_score,
                "回调": r.pullback_score,
                "资金": r.capital_score,
                "基本面": r.fundamental_score,
                "等级": r.level,
                "标签": " ".join(r.tags[:3]),
            })
        
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

        # 发送飞书
        if st.button("📤 发送到飞书"):
            lines = []
            for r in results[:10]:
                lines.append(f"• **{r.name}**（{r.code}）— {r.total_score}分 — {r.level}")
            content = "\n".join(lines)
            elements = [{"tag": "div", "text": {"tag": "lark_md", "content": content}}]
            if send_feishu_card(f"🏆 V10评分结果: {len(results)}只", elements):
                st.success("已发送到飞书！")
            else:
                st.warning("发送失败，请检查Webhook配置")
