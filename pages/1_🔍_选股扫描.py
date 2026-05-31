"""选股扫描页面 — V10 全买入公式 + 经典策略"""
import streamlit as st
import pandas as pd
from core.strategies import STRATEGY_REGISTRY, get_strategy_names
from core.scanner import scan_market, scan_watchlist
from core.alerts import send_batch_signals
from core.db import get_signals

st.set_page_config(page_title="选股扫描", page_icon="🔍", layout="wide")
st.title("🔍 选股扫描")

# ===== V10 策略（重点突出）=====
st.subheader("🏆 V10 通达信全买入公式")
with st.expander("V10 策略详解", expanded=False):
    st.markdown("""
    **V10 全买入** = 隧道趋势 + 短线通道 + QW动能 + 强庄控盘 + MACD金叉 + 放量阳线
    
    所有条件同时满足才触发，信号质量极高：
    
    | 条件 | 说明 |
    |------|------|
    | 隧道多头 | 收盘价 > EMA(120) > EMA(200)，长期趋势向上 |
    | 双线定式 | EMA(5) > EMA(20) 且 EMA(5) 上升 |
    | QW动能 | 自定义动量指标上升 |
    | 通道间距 | (EMA5-EMA20)/EMA20 > 0.8%，趋势有力度 |
    | 放量 | 成交量 > 1.5倍5日均量 |
    | 阳线 | 收盘 > 开盘 |
    | 强庄控盘 | 加权价格EMA突变，庄家动作 |
    | MACD金叉 | DIF(20,80) 上穿 DEA(9) |
    """)

v10_enabled = st.checkbox("🏆 启用 V10 全买入公式", value=True)

# ===== 经典策略 =====
st.subheader("📋 经典策略")
strategy_names = get_strategy_names()
classic_names = [k for k in strategy_names if k != "v10_full"]

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

# 合并策略列表
all_selected = []
if v10_enabled:
    all_selected.append("v10_full")
all_selected.extend(selected_classic)

# 扫描范围
st.subheader("🎯 扫描范围")
scan_mode = st.radio("扫描范围", ["全市场", "自选股"], horizontal=True)

# 运行扫描
if st.button("🚀 开始扫描", type="primary", use_container_width=True):
    if not all_selected:
        st.warning("请至少选择一个策略！")
    else:
        with st.spinner("正在扫描中...全市场V10扫描约需3-8分钟"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            def on_progress(current, total, code):
                pct = min(current / total, 1.0) if total > 0 else 0
                progress_bar.progress(pct)
                status_text.text(f"扫描进度: {current}/{total} ({pct*100:.0f}%)")

            if scan_mode == "自选股":
                results = scan_watchlist(all_selected, params_dict)
            else:
                results = scan_market(all_selected, params_dict, progress_callback=on_progress)

            progress_bar.progress(1.0)
            status_text.text("扫描完成！")

        if results:
            st.success(f"🎯 找到 {len(results)} 个信号！")

            # V10 信号分类展示
            v10_results = [r for r in results if r.strategy == "v10_full"]
            classic_results = [r for r in results if r.strategy != "v10_full"]

            if v10_results:
                st.subheader("🏆 V10 全买入信号")
                # 按信号类型排序
                def v10_sort(r):
                    sig_type = (r.info or {}).get("signal_type", "")
                    if sig_type == "全买入": return 0
                    elif sig_type == "强庄买": return 1
                    else: return 2
                v10_results.sort(key=v10_sort)

                for r in v10_results:
                    sig_type = (r.info or {}).get("signal_type", "")
                    if sig_type == "全买入":
                        emoji = "🔴"
                    elif sig_type == "强庄买":
                        emoji = "🟠"
                    else:
                        emoji = "🟡"
                    
                    info = r.info or {}
                    cols = st.columns([1, 2, 1, 1, 2])
                    with cols[0]:
                        st.markdown(f"**{emoji} {r.code}**")
                    with cols[1]:
                        st.markdown(f"**{r.name}** — ¥{r.price}")
                    with cols[2]:
                        st.markdown(f"`{sig_type}`")
                    with cols[3]:
                        st.markdown(f"通道 {info.get('通道间距', '-')}")
                    with cols[4]:
                        tags = []
                        if info.get('MACD金叉'): tags.append("MACD✅")
                        if info.get('强庄信号'): tags.append("强庄✅")
                        if info.get('放量'): tags.append("放量✅")
                        st.markdown(" ".join(tags))

            if classic_results:
                st.subheader("📋 经典策略信号")
                data = []
                for r in classic_results:
                    info = STRATEGY_REGISTRY.get(r.strategy, {})
                    data.append({
                        "代码": r.code, "名称": r.name,
                        "策略": info.get("name", r.strategy),
                        "价格": f"¥{r.price:.2f}", "详情": r.detail,
                    })
                st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

            # 发送飞书通知
            if st.button("📤 发送到飞书"):
                signal_dicts = []
                for r in results:
                    info = STRATEGY_REGISTRY.get(r.strategy, {})
                    signal_dicts.append({
                        "code": r.code, "name": r.name,
                        "strategy": info.get("name", r.strategy),
                        "price": r.price,
                    })
                if send_batch_signals(signal_dicts):
                    st.success("已发送到飞书！")
                else:
                    st.warning("发送失败，请检查 Webhook 配置")
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
