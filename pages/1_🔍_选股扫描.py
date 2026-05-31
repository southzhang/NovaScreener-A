"""选股扫描页面"""
import streamlit as st
import pandas as pd
from core.strategies import STRATEGY_REGISTRY, get_strategy_names
from core.scanner import scan_market, scan_watchlist
from core.alerts import send_batch_signals
from core.db import get_signals

st.set_page_config(page_title="选股扫描", page_icon="🔍", layout="wide")
st.title("🔍 选股扫描")
st.caption("选择策略 → 运行扫描 → 查看结果")

# 策略选择
st.subheader("📋 选择策略")
strategy_names = get_strategy_names()
selected = []
cols = st.columns(3)
for i, key in enumerate(strategy_names):
    info = STRATEGY_REGISTRY[key]
    with cols[i % 3]:
        if st.checkbox(f"{info['name']}", value=True, key=f"sel_{key}"):
            selected.append(key)
            st.caption(info["desc"])

# 参数配置
st.subheader("⚙️ 策略参数")
params_dict = {}
for key in selected:
    info = STRATEGY_REGISTRY[key]
    default = info.get("default_params", {})
    if default:
        with st.expander(f"{info['name']} 参数"):
            params = {}
            for pkey, pval in default.items():
                if isinstance(pval, int):
                    params[pkey] = st.number_input(
                        pkey, value=pval, key=f"param_{key}_{pkey}"
                    )
                elif isinstance(pval, float):
                    params[pkey] = st.number_input(
                        pkey, value=pval, step=0.1, format="%.2f", key=f"param_{key}_{pkey}"
                    )
            params_dict[key] = params

# 扫描范围
st.subheader("🎯 扫描范围")
scan_mode = st.radio("扫描范围", ["全市场", "自选股"], horizontal=True)

# 运行扫描
if st.button("🚀 开始扫描", type="primary", use_container_width=True):
    if not selected:
        st.warning("请至少选择一个策略！")
    else:
        with st.spinner("正在扫描中...请稍候（全市场扫描可能需要几分钟）"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            def on_progress(current, total, code):
                pct = min(current / total, 1.0)
                progress_bar.progress(pct)
                status_text.text(f"扫描进度: {current}/{total} - {code}")

            if scan_mode == "自选股":
                results = scan_watchlist(selected, params_dict)
            else:
                results = scan_market(selected, params_dict, progress_callback=on_progress)

            progress_bar.progress(1.0)
            status_text.text(f"扫描完成！")

        if results:
            st.success(f"🎯 找到 {len(results)} 个信号！")

            # 构建结果表格
            data = []
            for r in results:
                info = STRATEGY_REGISTRY.get(r.strategy, {})
                data.append({
                    "代码": r.code,
                    "名称": r.name,
                    "策略": info.get("name", r.strategy),
                    "价格": f"¥{r.price:.2f}",
                    "详情": r.detail,
                })
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # 发送飞书通知
            if st.button("📤 发送到飞书"):
                signal_dicts = [{"code": r.code, "name": r.name, "strategy": STRATEGY_REGISTRY.get(r.strategy, {}).get("name", r.strategy), "price": r.price} for r in results]
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
