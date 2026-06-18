"""V10 综合评分页面 — 多维度评分 + 推荐"""
import streamlit as st
import pandas as pd
import numpy as np
from core.scorer import score_stock, score_batch
from core.data import get_realtime_quote, get_stock_history
from core.db import get_watchlist as db_get_watchlist
from core.alerts import send_feishu_card
from core.ui import inject_global_css, render_theme_toggle, render_page_header

st.set_page_config(page_title="V10 评分系统", page_icon="🏆", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("🏆 V10 综合评分系统", "多维度评分：技术面 + 资金面 + 基本面 + 波段回调")

# 评分维度说明
with st.expander("📊 评分维度详解"):
    st.html("""
    <div style="color:var(--text-secondary); line-height:1.8;">
    <table style="width:100%; border-collapse:collapse;">
    <tr style="border-bottom:2px solid var(--accent)40;">
        <th style="padding:8px 0; color:var(--accent); text-align:left;">维度</th>
        <th style="padding:8px 0; color:var(--accent); text-align:left;">权重</th>
        <th style="padding:8px 0; color:var(--accent); text-align:left;">说明</th>
    </tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:8px 0;">V10技术信号</td><td>40分</td><td style="color:var(--text-secondary);">隧道+通道+QW+强庄+MACD+放量</td></tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:8px 0;">波段回调</td><td>25分</td><td style="color:var(--text-secondary);">EMA20/50/120 + RSI + MACD</td></tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:8px 0;">资金面</td><td>20分</td><td style="color:var(--text-secondary);">主力净流入 > 0</td></tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:8px 0;">基本面</td><td>15分</td><td style="color:var(--text-secondary);">ROE>5%, 净利润增速>0%</td></tr>
    <tr><td style="padding:8px 0;">趋势强度</td><td>10分</td><td style="color:var(--text-secondary);">EMA多头排列 + 通道间距</td></tr>
    </table>
    <br>
    <strong style="color:var(--accent);">推荐等级：</strong><br>
    <span class="tag tag-up">🔴 强烈推荐</span> ≥80分 &nbsp;
    <span class="tag tag-accent">🟠 值得关注</span> 60-79分 &nbsp;
    <span class="tag tag-info">🟡 观察等待</span> 40-59分 &nbsp;
    <span class="tag" style="background:#5a657720; color:var(--text-muted); border:1px solid #5a657740;">⚪ 暂不推荐</span> &lt;40分
    </div>
    """)

# 输入方式
st.html('<h2 style="margin-top:0;">📋 股票输入</h2>')
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


def _build_extra_info(price: float, extras: dict) -> str:
    """构建PE/市值/涨跌停信息行"""
    parts = []
    pe = extras.get("pe", 0)
    circ_cap = extras.get("circ_cap", 0)
    limit_up = extras.get("limit_up", 0)
    if pe and pe > 0:
        parts.append(f"PE {pe:.1f}")
    if circ_cap and circ_cap > 0:
        parts.append(f"流通{circ_cap:.0f}亿")
    if limit_up > 0 and price > 0:
        pct_to_limit = (limit_up - price) / price * 100
        if pct_to_limit < 2:
            parts.append(f"<span style='color:var(--up-color);'>距涨停{pct_to_limit:.1f}%</span>")
        elif price >= limit_up:
            parts.append("<span style='color:var(--up-color);'>已涨停</span>")
    return " · ".join(parts)


# 运行评分
if st.button("🚀 开始评分", type="primary", width='stretch') and codes:
    results = []
    _quote_extras = {}
    progress = st.progress(0)
    status = st.empty()

    for i, code in enumerate(codes):
        pct = (i + 1) / len(codes)
        progress.progress(pct)
        status.text(f"评分中: {code} ({i+1}/{len(codes)})")

        try:
            df = get_stock_history(code, days=250)
            if df.empty or len(df) < 50:
                continue

            close = df["close"].values.astype(np.float64)
            high = df["high"].values.astype(np.float64)
            low = df["low"].values.astype(np.float64)
            volume = df["volume"].values.astype(np.float64)
            open_p = df["open"].values.astype(np.float64)

            quote = get_realtime_quote(code)
            price = quote["price"] if quote else close[-1]
            pct_change = quote["pct_change"] if quote else 0
            name = quote["name"] if quote else code
            pe = quote.get("pe", 0) if quote else 0
            circ_cap = quote.get("circ_market_cap", 0) if quote else 0
            limit_up = quote.get("limit_up", 0) if quote else 0

            result = score_stock(code, name, close, high, low, volume, open_p, price, pct_change)
            if result:
                results.append(result)
                _quote_extras[code] = {"pe": pe, "circ_cap": circ_cap, "limit_up": limit_up}

        except Exception as e:
            st.error(f"{code} 评分失败: {e}")

    progress.progress(1.0)
    status.text("评分完成！")

    if results:
        results.sort(key=lambda x: x.total_score, reverse=True)

        st.success(f"✅ 完成 {len(results)} 只股票评分")

        st.html('<h2>📊 评分结果</h2>')

        # 强推 (>=80分)
        strong = [r for r in results if r.total_score >= 80]
        if strong:
            st.html('<h3>🔴 强烈推荐 (≥80分)</h3>')
            for r in strong:
                _ex = _quote_extras.get(r.code, {})
                _info = _build_extra_info(r.price, _ex)
                st.html(f"""
                <div class="scan-result-card" style="border-left:4px solid var(--up-color);">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                        <div>
                            <span style="font-weight:700; color:var(--text-primary); font-size:1.05em;">{r.code}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{r.name}</span>
                            <span style="color:var(--accent); margin-left:12px; font-weight:600;">¥{r.price:.2f}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{r.pct_change:+.1f}%</span>
                        </div>
                        <div style="display:flex; gap:16px; align-items:center;">
                            <span style="color:var(--up-color); font-weight:700; font-size:1.2em;">{r.total_score}分</span>
                            <span style="color:var(--text-secondary);">V10:<span style="color:var(--text-primary);">{r.v10_score}</span> 回调:<span style="color:var(--text-primary);">{r.pullback_score}</span></span>
                            <span style="color:var(--text-secondary); font-size:0.85em;">{" ".join(r.tags[:3])}</span>
                        </div>
                    </div>
                    {"<div style='margin-top:4px; font-size:0.82em; color:var(--text-muted);'>📊 " + _info + "</div>" if _info else ""}
                </div>
                """)

        # 关注 (60-79分)
        watch = [r for r in results if 60 <= r.total_score < 80]
        if watch:
            st.html('<h3>🟠 值得关注 (60-79分)</h3>')
            for r in watch:
                _ex = _quote_extras.get(r.code, {})
                _info = _build_extra_info(r.price, _ex)
                st.html(f"""
                <div class="scan-result-card" style="border-left:4px solid var(--warning-color);">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                        <div>
                            <span style="font-weight:700; color:var(--text-primary);">{r.code}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{r.name}</span>
                            <span style="color:var(--accent); margin-left:12px;">¥{r.price:.2f}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{r.pct_change:+.1f}%</span>
                        </div>
                        <div style="display:flex; gap:16px; align-items:center;">
                            <span style="color:var(--warning-color); font-weight:700; font-size:1.1em;">{r.total_score}分</span>
                            <span style="color:var(--text-secondary);">V10:<span style="color:var(--text-primary);">{r.v10_score}</span> 回调:<span style="color:var(--text-primary);">{r.pullback_score}</span></span>
                            <span style="color:var(--text-secondary); font-size:0.85em;">{" ".join(r.tags[:3])}</span>
                        </div>
                    </div>
                    {"<div style='margin-top:4px; font-size:0.82em; color:var(--text-muted);'>📊 " + _info + "</div>" if _info else ""}
                </div>
                """)

        # 观察 (40-59分)
        observe = [r for r in results if 40 <= r.total_score < 60]
        if observe:
            st.html('<h3>🟡 观察等待 (40-59分)</h3>')
            for r in observe:
                st.caption(f"{r.code} {r.name} — {r.total_score}分 — {' '.join(r.tags[:2])}")

        # 完整表格
        st.divider()
        st.html('<h2>📋 完整评分表</h2>')

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

        st.dataframe(pd.DataFrame(table_data), width='stretch', hide_index=True)

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
