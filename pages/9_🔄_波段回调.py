"""波段回调入场识别页面"""
import streamlit as st
import numpy as np
import sys, os
from core.ui import inject_global_css, render_theme_toggle, render_page_header

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "v10"))

st.set_page_config(page_title="波段回调", page_icon="🔄", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("🔄 波段回调入场识别", "在V10趋势基础上，识别最佳回调入场点")

# 策略说明
with st.expander("📖 策略详解"):
    st.html("""
    <div style="color:var(--text-secondary); line-height:1.8;">
    <strong style="color:var(--accent);">核心逻辑：</strong><br>
    1. <strong>主趋势向上</strong>: EMA20 > EMA50 > EMA120（多头排列）<br>
    2. <strong>价格回调到支撑区</strong>: 接近EMA20或EMA50<br>
    3. <strong>缩量回调</strong>: 近3日成交量 < 20日均量 × 0.8<br>
    4. <strong>动量未死</strong>: RSI(14) > 40, MACD未死叉<br><br>
    <strong style="color:var(--accent);">评分标准（0-8分）：</strong><br>
    <span class="tag tag-up">⭐ 优质入场</span> ≥6分 &nbsp;
    <span class="tag tag-info">🟡 观察等待</span> 4-5分 &nbsp;
    <span class="tag" style="background:#5a657720; color:var(--text-muted); border:1px solid #5a657740;">🔴 暂不推荐</span> &lt;4分
    </div>
    """)

# 输入
st.html('<h2 style="margin-top:0;">📋 股票输入</h2>')
input_mode = st.radio("输入方式", ["手动输入", "从自选股导入"], horizontal=True)

codes = []
if input_mode == "手动输入":
    code_input = st.text_area("输入股票代码（每行一个）", placeholder="300065\n002185", height=100)
    if code_input:
        codes = [c.strip() for c in code_input.strip().split("\n") if c.strip()]
else:
    from core.db import get_watchlist
    watchlist = get_watchlist()
    if watchlist:
        codes = [w["code"] for w in watchlist]
        st.info(f"已导入 {len(codes)} 只自选股")

if st.button("🔍 扫描回调机会", type="primary", width='stretch') and codes:
    results = []
    progress = st.progress(0)

    for i, code in enumerate(codes):
        progress.progress((i + 1) / len(codes))

        try:
            import requests, json
            prefix = "sh" if code.startswith("6") else "sz"
            url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={prefix}{code},day,,,120,qfq"
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            json_str = resp.text.split("=", 1)[1] if "=" in resp.text else resp.text; data = json.loads(json_str)
            sec_data = data.get("data", {}).get(f"{prefix}{code}", {})
            bars = sec_data.get("qfqday", []) or sec_data.get("day", [])

            if len(bars) < 50:
                continue

            from core.v10_core import ema_fast, calc_ma

            close = np.array([float(b[2]) for b in bars])
            high = np.array([float(b[3]) for b in bars])
            low = np.array([float(b[4]) for b in bars])
            volume = np.array([float(b[5]) for b in bars]) if len(bars[0]) > 5 else np.ones(len(bars))

            ema20 = ema_fast(close, 20)
            ema50 = ema_fast(close, 50)
            ema120 = ema_fast(close, 120)

            delta = np.diff(close, prepend=close[0])
            gain = np.where(delta > 0, delta, 0.0)
            loss = np.where(delta < 0, -delta, 0.0)
            avg_gain = ema_fast(gain, 14)
            avg_loss = ema_fast(loss, 14)
            rs = np.divide(avg_gain, avg_loss, out=np.ones_like(avg_gain), where=avg_loss != 0)
            rsi = 100 - (100 / (1 + rs))

            dif = ema_fast(close, 12) - ema_fast(close, 26)
            dea = ema_fast(dif, 9)

            score = 0
            tags = []

            if ema20[-1] > ema50[-1] > ema120[-1]:
                score += 2
                tags.append("多头排列✅")
            elif ema20[-1] > ema50[-1]:
                score += 1
                tags.append("短多头")

            dist_ema20 = (close[-1] - ema20[-1]) / ema20[-1]
            dist_ema50 = (close[-1] - ema50[-1]) / ema50[-1]

            if -0.02 <= dist_ema20 <= 0.02:
                score += 2
                tags.append("接近EMA20✅")
            elif -0.05 <= dist_ema50 <= 0.02:
                score += 1
                tags.append("接近EMA50")

            if len(volume) >= 20:
                vol_ma20 = np.mean(volume[-20:])
                vol_recent = np.mean(volume[-3:])
                if vol_ma20 > 0:
                    vol_ratio = vol_recent / vol_ma20
                    if vol_ratio < 0.8:
                        score += 2
                        tags.append("缩量回调✅")
                    elif vol_ratio < 1.0:
                        score += 1
                        tags.append("量能收缩")

            if rsi[-1] > 40:
                score += 1
                tags.append(f"RSI={rsi[-1]:.0f}")
            if dif[-1] > dea[-1]:
                score += 1
                tags.append("MACD多头")

            try:
                rt_url = f"https://qt.gtimg.cn/q={prefix}{code}"
                rt_resp = requests.get(rt_url, timeout=5)
                parts = rt_resp.text.split("=")[1].strip('";\n').split("~")
                price = float(parts[3])
                change_pct = float(parts[32])
                name = parts[1]
            except:
                price = close[-1]
                change_pct = 0
                name = code

            if score >= 6:
                level = "⭐ 优质入场"
            elif score >= 4:
                level = "🟡 观察等待"
            else:
                level = "🔴 暂不推荐"

            results.append({
                "代码": code,
                "名称": name,
                "价格": f"¥{price:.2f}",
                "涨跌幅": f"{change_pct:+.1f}%",
                "评分": score,
                "等级": level,
                "标签": " ".join(tags),
                "RSI": f"{rsi[-1]:.1f}",
                "距EMA20": f"{dist_ema20*100:+.1f}%",
            })

        except Exception as e:
            st.error(f"{code} 分析失败: {e}")

    progress.progress(1.0)

    if results:
        results.sort(key=lambda x: x["评分"], reverse=True)

        st.html('<h2>📊 回调机会</h2>')

        star = [r for r in results if r["评分"] >= 6]
        if star:
            st.html('<h3>⭐ 优质回调入场 (≥6分)</h3>')
            for r in star:
                tags_html = " ".join([f"<span class='tag tag-info'>{t}</span>" for t in r['标签'].split()])
                st.html(f"""
                <div class="scan-result-card" style="border-left:4px solid var(--warning-color);">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <div>
                            <span style="font-weight:700; color:var(--text-primary);">{r['代码']}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{r['名称']}</span>
                            <span style="color:var(--accent); margin-left:12px;">{r['价格']}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{r['涨跌幅']}</span>
                        </div>
                        <div style="display:flex; gap:12px; align-items:center;">
                            <span style="color:var(--warning-color); font-weight:700; font-size:1.1em;">{r['评分']}分</span>
                            <span style="color:var(--text-secondary);">{r['距EMA20']}</span>
                            <span style="color:var(--text-secondary);">RSI {r['RSI']}</span>
                            {tags_html}
                        </div>
                    </div>
                </div>
                """)

        yellow = [r for r in results if 4 <= r["评分"] < 6]
        if yellow:
            st.html('<h3>🟡 观察等待 (4-5分)</h3>')
            for r in yellow:
                tags_html = " ".join([f"<span class='tag tag-info'>{t}</span>" for t in r['标签'].split()])
                st.html(f"""
                <div class="scan-result-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <div>
                            <span style="font-weight:700; color:var(--text-primary);">{r['代码']}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{r['名称']}</span>
                            <span style="color:var(--accent); margin-left:12px;">{r['价格']}</span>
                        </div>
                        <div style="display:flex; gap:12px; align-items:center;">
                            <span style="color:var(--info-color); font-weight:700;">{r['评分']}分</span>
                            <span style="color:var(--text-secondary);">{r['距EMA20']}</span>
                            <span style="color:var(--text-secondary);">RSI {r['RSI']}</span>
                            {tags_html}
                        </div>
                    </div>
                </div>
                """)

        red = [r for r in results if r["评分"] < 4]
        if red:
            st.html('<h3>🔴 暂不推荐 (<4分)</h3>')
            for r in red:
                st.caption(f"{r['代码']} {r['名称']} — {r['评分']}分 — {r['标签']}")

        st.divider()
        import pandas as pd
        st.dataframe(pd.DataFrame(results), width='stretch', hide_index=True)
