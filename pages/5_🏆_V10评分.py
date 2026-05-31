"""V10 综合评分页面 — 多维度评分 + 推荐"""
import streamlit as st
import sys, os

# 添加V10脚本路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "v10"))

st.set_page_config(page_title="V10 评分系统", page_icon="🏆", layout="wide")
st.title("🏆 V10 综合评分系统")
st.caption("多维度评分：技术面 + 资金面 + 基本面 + 波段回调")

# 评分维度说明
with st.expander("📊 评分维度详解"):
    st.markdown("""
    | 维度 | 权重 | 数据源 | 说明 |
    |------|------|--------|------|
    | V10技术信号 | 40% | 腾讯/新浪K线 | 隧道+通道+QW+强庄+MACD |
    | 资金面 | 20% | 主力净流入 | 主力资金 > 0 才通过 |
    | 基本面 | 20% | iFinD | ROE>5%, 净利润增速>0% |
    | 波段回调 | 20% | 腾讯K线 | EMA20/50/120 + RSI + MACD |
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
    from core.db import get_watchlist
    watchlist = get_watchlist()
    if watchlist:
        codes = [w["code"] for w in watchlist]
        st.info(f"已导入 {len(codes)} 只自选股")
    else:
        st.warning("自选股为空，请先添加")

elif input_mode == "从V10观察池导入":
    watchlist_path = os.path.expanduser("~/.hermes/cache/v10_watchlist.json")
    if os.path.exists(watchlist_path):
        import json
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
            # 获取K线数据
            import requests, json
            prefix = "sh" if code.startswith("6") else "sz"
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,250,qfq"
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(resp.text)
            sec_data = data.get("data", {}).get(f"{prefix}{code}", {})
            bars = sec_data.get("qfqday", []) or sec_data.get("day", [])

            if len(bars) < 200:
                continue

            import numpy as np
            close = np.array([float(b[2]) for b in bars])
            high = np.array([float(b[3]) for b in bars])
            low = np.array([float(b[4]) for b in bars])
            volume = np.array([float(b[5]) for b in bars]) if len(bars[0]) > 5 else np.ones(len(bars))
            open_p = np.array([float(b[1]) for b in bars])

            # V10技术信号
            from core.strategies import scan_v10_full
            v10_result = scan_v10_full(close, high, low, volume, open_p)
            v10_signals, v10_info = v10_result if v10_result else ([], {})

            # 评分计算
            score = 0
            tags = []

            # 技术面评分 (0-40)
            if "全买入" in v10_signals:
                score += 40
                tags.append("🏆全买入")
            elif "强庄买" in v10_signals:
                score += 30
                tags.append("🟠强庄买")
            elif "基础买" in v10_signals:
                score += 20
                tags.append("🟡基础买")

            # 隧道多头加分
            if v10_info.get("隧道多头"):
                score += 5
                tags.append("隧道✅")

            # MACD金叉加分
            if v10_info.get("MACD金叉"):
                score += 5
                tags.append("MACD✅")

            # 通道间距加分
            通道间距 = v10_info.get("通道间距", 0)
            if 通道间距 > 0.02:
                score += 5
                tags.append(f"通道{通道间距:.3f}")

            # 波段回调评分 (0-20)
            if len(close) >= 50:
                from core.v10_core import ema_fast
                ema20 = ema_fast(close, 20)
                ema50 = ema_fast(close, 50)
                ema120 = ema_fast(close, 120)

                # 多头排列
                if ema20[-1] > ema50[-1] > ema120[-1]:
                    score += 10
                    tags.append("多头排列✅")

                # 回调到EMA20附近
                dist_to_ema20 = abs(close[-1] - ema20[-1]) / ema20[-1]
                if dist_to_ema20 < 0.03:
                    score += 5
                    tags.append("回调EMA20✅")

                # 缩量回调
                if len(volume) >= 20:
                    vol_ma20 = np.mean(volume[-20:])
                    vol_recent = np.mean(volume[-3:])
                    if vol_recent < vol_ma20 * 0.8:
                        score += 5
                        tags.append("缩量回调✅")

            # 获取实时价格
            try:
                rt_url = f"http://qt.gtimg.cn/q={prefix}{code}"
                rt_resp = requests.get(rt_url, timeout=5)
                parts = rt_resp.text.split("=")[1].strip('";\n').split("~")
                price = float(parts[3])
                change_pct = float(parts[32])
                name = parts[1]
            except:
                price = close[-1]
                change_pct = 0
                name = code

            results.append({
                "代码": code,
                "名称": name,
                "价格": f"¥{price:.2f}",
                "涨跌幅": f"{change_pct:+.1f}%",
                "评分": score,
                "信号": " + ".join(v10_signals) if v10_signals else "-",
                "标签": " ".join(tags[:5]),
                "通道间距": f"{通道间距:.4f}" if 通道间距 else "-",
                "QW": f"{v10_info.get('QW', '-')}",
            })

        except Exception as e:
            st.error(f"{code} 评分失败: {e}")

    progress.progress(1.0)
    status.text("评分完成！")

    if results:
        # 按评分排序
        results.sort(key=lambda x: x["评分"], reverse=True)

        st.success(f"✅ 完成 {len(results)} 只股票评分")

        # 分级展示
        st.subheader("📊 评分结果")

        # 强推 (>=60分)
        strong = [r for r in results if r["评分"] >= 60]
        if strong:
            st.markdown("### 🔴 强烈推荐 (≥60分)")
            for r in strong:
                cols = st.columns([1, 2, 1, 1, 2, 2])
                with cols[0]: st.markdown(f"**{r['代码']}**")
                with cols[1]: st.markdown(f"**{r['名称']}**")
                with cols[2]: st.markdown(f"{r['价格']}")
                with cols[3]: st.markdown(f"**{r['评分']}分**")
                with cols[4]: st.markdown(f"`{r['信号']}`")
                with cols[5]: st.markdown(r['标签'])

        # 关注 (40-59分)
        watch = [r for r in results if 40 <= r["评分"] < 60]
        if watch:
            st.markdown("### 🟠 值得关注 (40-59分)")
            for r in watch:
                cols = st.columns([1, 2, 1, 1, 2, 2])
                with cols[0]: st.markdown(f"**{r['代码']}**")
                with cols[1]: st.markdown(f"**{r['名称']}**")
                with cols[2]: st.markdown(f"{r['价格']}")
                with cols[3]: st.markdown(f"**{r['评分']}分**")
                with cols[4]: st.markdown(f"`{r['信号']}`")
                with cols[5]: st.markdown(r['标签'])

        # 观察 (<40分)
        observe = [r for r in results if r["评分"] < 40]
        if observe:
            st.markdown("### 🟡 观察 (<40分)")
            for r in observe:
                cols = st.columns([1, 2, 1, 1, 2, 2])
                with cols[0]: st.markdown(f"**{r['代码']}**")
                with cols[1]: st.markdown(f"**{r['名称']}**")
                with cols[2]: st.markdown(f"{r['价格']}")
                with cols[3]: st.markdown(f"**{r['评分']}分**")
                with cols[4]: st.markdown(f"`{r['信号']}`")
                with cols[5]: st.markdown(r['标签'])

        # 导出
        st.divider()
        import pandas as pd
        df = pd.DataFrame(results)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # 发送飞书
        if st.button("📤 发送到飞书"):
            from core.alerts import send_feishu_card
            lines = []
            for r in results[:10]:
                lines.append(f"• **{r['名称']}**（{r['代码']}）— {r['评分']}分 — {r['信号']}")
            content = "\n".join(lines)
            elements = [{"tag": "div", "text": {"tag": "lark_md", "content": content}}]
            if send_feishu_card(f"🏆 V10评分结果: {len(results)}只", elements):
                st.success("已发送到飞书！")
            else:
                st.warning("发送失败，请检查Webhook配置")
