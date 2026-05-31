"""选股扫描页面 — V10 + 经典策略 + 波段回调"""
import streamlit as st
import pandas as pd
from core.strategies import STRATEGY_REGISTRY, get_strategy_names
from core.scanner import scan_market, scan_watchlist
from core.alerts import send_batch_signals
from core.db import get_signals

st.set_page_config(page_title="选股扫描", page_icon="🔍", layout="wide")
st.title("🔍 选股扫描")
st.caption("V10全买入 · 波段回调 · 经典策略")

# ===== V10 策略 =====
st.subheader("🏆 V10 策略引擎")

with st.expander("📖 V10 策略详解", expanded=False):
    st.markdown("""
    **V10 全买入公式** — 七条件共振，宁缺毋滥：
    
    | 条件 | 说明 |
    |------|------|
    | 🏔️ 隧道多头 | 收盘价 > EMA(120) > EMA(200) |
    | 📈 双线定式 | EMA(5) > EMA(20) 且上升 |
    | ⚡ QW动能 | 自定义动量指标上升 |
    | 📏 通道间距 | (EMA5-EMA20)/EMA20 > 0.8% |
    | 🔊 放量 | 成交量 > 1.5x 5日均量 |
    | 🔴 阳线 | 收盘 > 开盘 |
    | 💪 强庄控盘 | 加权价格突变检测 |
    | 📊 MACD金叉 | DIF(20,80) 上穿 DEA(9) |
    
    **信号分级：**
    - 🔴 **全买入** = 所有条件满足（最强）
    - 🟠 **强庄买** = 缺MACD金叉
    - 🟡 **基础买** = 缺强庄信号
    """)

col1, col2 = st.columns(2)
with col1:
    v10_enabled = st.checkbox("🏆 V10 全买入公式", value=True)
with col2:
    pullback_enabled = st.checkbox("🔄 波段回调入场", value=False)

# ===== 经典策略 =====
st.subheader("📋 经典策略")
classic_names = [k for k in get_strategy_names() if k not in ["v10_full", "pullback"]]

selected_classic = []
cols = st.columns(3)
for i, key in enumerate(classic_names):
    info = STRATEGY_REGISTRY[key]
    with cols[i % 3]:
        if st.checkbox(f"{info['name']}", value=False, key=f"sel_{key}"):
            selected_classic.append(key)
            st.caption(info["desc"])

# 参数配置
params_dict = {}
for key in selected_classic:
    info = STRATEGY_REGISTRY[key]
    default = info.get("default_params", {})
    if default:
        with st.expander(f"{info['name']} 参数"):
            params = {}
            for pkey, pval in default.items():
                if isinstance(pval, int):
                    params[pkey] = st.number_input(pkey, value=pval, key=f"param_{key}_{pkey}")
                elif isinstance(pval, float):
                    params[pkey] = st.number_input(pkey, value=pval, step=0.1, format="%.2f", key=f"param_{key}_{pkey}")
            params_dict[key] = params

# 合并策略
all_selected = []
if v10_enabled:
    all_selected.append("v10_full")
if pullback_enabled:
    all_selected.append("pullback")
all_selected.extend(selected_classic)

# 扫描范围
st.subheader("🎯 扫描范围")
scan_mode = st.radio("扫描范围", ["全市场", "自选股"], horizontal=True)
max_workers = st.slider("并发线程数", 5, 20, 10)

# 运行扫描
if st.button("🚀 开始扫描", type="primary", use_container_width=True):
    if not all_selected:
        st.warning("请至少选择一个策略！")
    else:
        with st.spinner("正在扫描中...V10全市场扫描约需3-8分钟"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            def on_progress(current, total):
                pct = min(current / total, 1.0) if total > 0 else 0
                progress_bar.progress(pct)
                status_text.text(f"扫描进度: {current}/{total} ({pct*100:.0f}%)")

            if scan_mode == "自选股":
                results = scan_watchlist(all_selected, params_dict)
            else:
                results = scan_market(all_selected, params_dict, max_workers=max_workers, progress_callback=on_progress)

            progress_bar.progress(1.0)
            status_text.text("扫描完成！")

        if results:
            st.success(f"🎯 找到 {len(results)} 个信号！")

            # V10 信号
            v10_results = [r for r in results if r.get("type") == "v10"]
            pullback_results = [r for r in results if r.get("type") == "pullback"]
            classic_results = [r for r in results if r.get("type") == "classic"]

            if v10_results:
                st.subheader("🏆 V10 全买入信号")
                for r in v10_results:
                    signal_type = r.get("signal_type", "")
                    if signal_type == "全买入":
                        emoji = "🔴"
                    elif signal_type == "强庄买":
                        emoji = "🟠"
                    else:
                        emoji = "🟡"
                    
                    cols = st.columns([1, 2, 1, 1, 2])
                    with cols[0]:
                        st.markdown(f"**{emoji} {r['code']}**")
                    with cols[1]:
                        st.markdown(f"**{r['name']}** — ¥{r['price']}")
                    with cols[2]:
                        st.markdown(f"`{signal_type}`")
                    with cols[3]:
                        st.markdown(f"**{r['score']}分**")
                    with cols[4]:
                        st.markdown(" ".join(r['tags'][:4]))

            if pullback_results:
                st.subheader("🔄 波段回调机会")
                for r in pullback_results:
                    cols = st.columns([1, 2, 1, 1, 2])
                    with cols[0]:
                        st.markdown(f"**{r['code']}**")
                    with cols[1]:
                        st.markdown(f"**{r['name']}** — ¥{r['price']}")
                    with cols[2]:
                        st.markdown(f"`{r.get('level', '')}`")
                    with cols[3]:
                        st.markdown(f"**{r['score']}分**")
                    with cols[4]:
                        st.markdown(" ".join(r['tags'][:4]))

            if classic_results:
                st.subheader("📋 经典策略信号")
                df = pd.DataFrame(classic_results)
                st.dataframe(df[["code", "name", "strategy", "price"]], use_container_width=True, hide_index=True)

            # 发送飞书
            if st.button("📤 发送到飞书"):
                signal_dicts = []
                for r in results:
                    signal_dicts.append({
                        "code": r["code"], "name": r["name"],
                        "strategy": r["strategy"], "price": r["price"],
                    })
                if send_batch_signals(signal_dicts):
                    st.success("已发送到飞书！")
                else:
                    st.warning("发送失败，请检查Webhook配置")
        else:
            st.info("未找到符合条件的股票")

# 历史信号
st.divider()
st.subheader("📜 历史信号")
signals = get_signals(limit=50)
if signals:
    df = pd.DataFrame(signals)
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("暂无历史信号")
