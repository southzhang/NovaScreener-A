"""选股扫描页面 — V10 + 经典策略 + 波段回调 + 6维评分买入推荐 + 快捷操作"""
import streamlit as st
import pandas as pd
import numpy as np
from core.strategies import STRATEGY_REGISTRY, get_strategy_names
from core.scanner import scan_market, scan_watchlist
from core.alerts import send_batch_signals
from core.db import get_signals, add_watchlist, get_watchlist, add_position
from core.data import get_stock_history, get_realtime_quote
from core.recommend import generate_buy_recommendation, format_recommendation_card
from core.ui import inject_global_css, render_theme_toggle, render_page_header

st.set_page_config(page_title="选股扫描", page_icon="🔍", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("🔍 选股扫描", "V10全买入 · 波段回调 · 经典策略 · 6维评分 · 买入推荐")

# ===== V10 策略 =====
st.html('<h2 style="margin-top:0;">🏆 V10 策略引擎</h2>')

with st.expander("📖 V10 策略详解", expanded=False):
    st.html("""
    <div style="color:var(--text-secondary); line-height:1.8;">
    <strong style="color:#ff6b35;">V10 全买入公式</strong> — 七条件共振，宁缺毋滥：<br><br>
    <table style="width:100%; border-collapse:collapse;">
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:6px 0;">🏔️ 隧道多头</td><td style="color:var(--text-secondary);">收盘价 > EMA(120) > EMA(200)</td></tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:6px 0;">📈 双线定式</td><td style="color:var(--text-secondary);">EMA(5) > EMA(20) 且上升</td></tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:6px 0;">⚡ QW动能</td><td style="color:var(--text-secondary);">自定义动量指标上升</td></tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:6px 0;">📏 通道间距</td><td style="color:var(--text-secondary);">(EMA5-EMA20)/EMA20 > 0.8%</td></tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:6px 0;">🔊 放量</td><td style="color:var(--text-secondary);">成交量 > 1.5x 5日均量</td></tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:6px 0;">🔴 阳线</td><td style="color:var(--text-secondary);">收盘 > 开盘</td></tr>
    <tr style="border-bottom:1px solid var(--border-color);"><td style="padding:6px 0;">💪 强庄控盘</td><td style="color:var(--text-secondary);">加权价格突变检测</td></tr>
    <tr><td style="padding:6px 0;">📊 MACD金叉</td><td style="color:var(--text-secondary);">DIF(20,80) 上穿 DEA(9)</td></tr>
    </table>
    <br>
    <strong style="color:#ff6b35;">6维综合评分（100分制）：</strong><br>
    V10信号级别 30分 | 基本面(ROE) 15分 | 资金面 20分 | 振幅分位 15分 | 板块风口 10分 | 追高风险 10分
    <br><br>
    <strong style="color:#ff6b35;">信号分级：</strong><br>
    <span class="tag tag-up">🔴 全买入</span> 所有条件满足（最强）→ 强推80+分<br>
    <span class="tag tag-accent">🟠 强庄买</span> 缺MACD金叉 → 关注60+分<br>
    <span class="tag tag-info">🟡 基础买</span> 缺强庄信号 → 观察40+分
    </div>
    """)

col1, col2, col3 = st.columns(3)
with col1:
    v10_enabled = st.checkbox("🏆 V10 全买入公式", value=True)
with col2:
    pullback_enabled = st.checkbox("🔄 波段回调入场", value=False)
with col3:
    trend_swing_enabled = st.checkbox("📈 趋势波段", value=False,
        help="多头排列+回调支撑+缩量反弹+三层波段止盈")

# ===== 经典策略 =====
st.html('<h2>📋 经典策略</h2>')
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
if trend_swing_enabled:
    all_selected.append("trend_swing")
all_selected.extend(selected_classic)

# 扫描范围
st.html('<h2>🎯 扫描范围</h2>')
scan_mode = st.radio("扫描范围", ["全市场", "自选股"], horizontal=True)


def _render_recommendation(code, name, signal_type, score, change_pct=0):
    """渲染单只股票的6维评分+买入推荐（紧凑版）"""
    try:
        hist = get_stock_history(code, days=250)
        if hist.empty or len(hist) < 20:
            return

        close_arr = hist["close"].values.astype(np.float64)
        high_arr = hist["high"].values.astype(np.float64)
        low_arr = hist["low"].values.astype(np.float64)
        vol_arr = hist["volume"].values.astype(np.float64)
        open_arr = hist["open"].values.astype(np.float64)

        from core.data import get_capital_flow, get_sector_score as calc_sector_score
        flow_data = get_capital_flow(code)
        capital_flow = flow_data.get("main_net_inflow", 0) if flow_data else 0
        sector_score = calc_sector_score(code)

        rec = generate_buy_recommendation(
            code=code, name=name,
            close=close_arr, high=high_arr, low=low_arr,
            volume=vol_arr, open_price=open_arr,
            signal_type=signal_type, score=score,
            change_pct=change_pct,
            capital_flow=capital_flow,
            sector_score=sector_score,
        )
        if not rec:
            return

        # ---- 进场建议标签 ----
        action = rec.action
        level = rec.level
        if "强烈" in action or "强烈推荐" in level:
            action_bg = "#ff4b4b"
        elif "建议买入" in action or "值得关注" in level:
            action_bg = "#ffab40"
        elif "观察" in action or "观察等待" in level:
            action_bg = "#b39700"
        else:
            action_bg = "#888888"
        rr_color = "#00c853" if rec.risk_reward >= 2.0 else "#ffab40" if rec.risk_reward >= 1.5 else "#ff4b4b"

        st.html(f"""
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:4px;">
            <div style="display:flex; gap:8px; align-items:center;">
                <span style="background:{action_bg}; color:#fff; padding:3px 12px; border-radius:4px; font-size:0.9em; font-weight:700;">{action}</span>
                <span style="color:var(--text-secondary); font-size:0.85em;">{rec.hold_days}</span>
            </div>
            <div style="display:flex; gap:12px; align-items:center; font-size:0.85em;">
                <span style="color:var(--text-secondary);">盈亏比 <b style="color:{rr_color};">{rec.risk_reward}:1</b></span>
                <span style="color:var(--text-secondary);">仓位 <b style="color:var(--text-primary);">{rec.position_pct}%</b></span>
            </div>
        </div>
        """)

        # ---- 紧凑评分条 ----
        dim_parts = []
        for d in rec.dimensions:
            pct = d.score / d.max_score if d.max_score > 0 else 0
            if pct >= 0.8:
                icon = "🟢"
            elif pct >= 0.5:
                icon = "🟡"
            elif pct > 0:
                icon = "🟠"
            else:
                icon = "⚪"
            dim_parts.append(f"{icon}{d.name}{d.score:.0f}")
        st.caption(" · ".join(dim_parts))

        # ---- 核心指标一行（自定义HTML，7列紧凑布局）----
        ts = rec.trailing_stop
        loss_pct = (rec.current_price - rec.stop_loss) / rec.current_price * 100
        gain1_pct = (rec.target_1 - rec.current_price) / rec.current_price * 100
        rr_color = "#00c853" if rec.risk_reward >= 2.0 else "#ffab40" if rec.risk_reward >= 1.5 else "#ff4b4b"

        st.html(f"""
        <div style="display:flex; gap:8px; flex-wrap:wrap; padding:8px 0; font-size:0.82em;">
            <div style="flex:1; min-width:70px; text-align:center; background:var(--bg-card); border-radius:6px; padding:6px 4px;">
                <div style="color:var(--text-secondary); font-size:0.8em;">📊 总分</div>
                <div style="font-weight:700; color:#ff6b35;">{rec.total_score}分</div>
            </div>
            <div style="flex:1; min-width:70px; text-align:center; background:var(--bg-card); border-radius:6px; padding:6px 4px;">
                <div style="color:var(--text-secondary); font-size:0.8em;">🎯 入场</div>
                <div style="font-weight:700;">¥{rec.entry_price}</div>
            </div>
            <div style="flex:1; min-width:70px; text-align:center; background:var(--bg-card); border-radius:6px; padding:6px 4px;">
                <div style="color:var(--text-secondary); font-size:0.8em;">🛑 止损</div>
                <div style="font-weight:700; color:#00c853;">¥{rec.stop_loss}</div>
                <div style="color:#00c853; font-size:0.85em;">-{loss_pct:.1f}%</div>
            </div>
            <div style="flex:1; min-width:70px; text-align:center; background:var(--bg-card); border-radius:6px; padding:6px 4px;">
                <div style="color:var(--text-secondary); font-size:0.8em;">📈 目标</div>
                <div style="font-weight:700; color:#ff4b4b;">¥{rec.target_1}</div>
                <div style="color:#ff4b4b; font-size:0.85em;">+{gain1_pct:.1f}%</div>
            </div>
            <div style="flex:1; min-width:70px; text-align:center; background:var(--bg-card); border-radius:6px; padding:6px 4px;">
                <div style="color:var(--text-secondary); font-size:0.8em;">盈亏比</div>
                <div style="font-weight:700; color:{rr_color};">{rec.risk_reward}:1</div>
            </div>
            <div style="flex:1; min-width:70px; text-align:center; background:var(--bg-card); border-radius:6px; padding:6px 4px;">
                <div style="color:var(--text-secondary); font-size:0.8em;">💰 仓位</div>
                <div style="font-weight:700;">{rec.position_pct}%</div>
            </div>
            <div style="flex:2; min-width:120px; text-align:left; background:var(--bg-card); border-radius:6px; padding:6px 8px;">
                <div style="color:var(--text-secondary); font-size:0.8em;">💡 推荐理由</div>
                <div style="font-size:0.85em; color:var(--text-secondary); line-height:1.3;">{rec.reason}</div>
            </div>
        </div>
        """)

        # ---- 风险提示 ----
        st.caption(f"⚠️ {rec.risk_note}")

    except Exception as e:
        st.caption(f"⚠️ 推荐生成失败: {e}")


def _render_stock_actions(code, name, price, stop_loss=0, target_price=0, key_prefix=""):
    """渲染单只股票的操作按钮：加入盯盘 + 加入持仓"""
    col_watch, col_hold, col_spacer = st.columns([1, 1, 4])

    with col_watch:
        if st.button("👁️ 加入盯盘", key=f"{key_prefix}watch_{code}"):
            existing = [w["code"] for w in get_watchlist()]
            if code in existing:
                st.toast(f"⚠️ {code} 已在盯盘列表中", icon="⚠️")
            else:
                add_watchlist(code, name)
                st.toast(f"✅ {code} 已加入盯盘监控", icon="✅")

    with col_hold:
        with st.expander("💼 加入持仓"):
            with st.form(key=f"{key_prefix}hold_form_{code}", clear_on_submit=True):
                st.markdown(f"**{code} — {name}**")
                fcol1, fcol2 = st.columns(2)
                with fcol1:
                    buy_price = st.number_input(
                        "买入价格", value=float(price), min_value=0.01,
                        step=0.01, format="%.2f", key=f"{key_prefix}bp_{code}"
                    )
                with fcol2:
                    quantity = st.number_input(
                        "买入数量（股）", value=100, min_value=100,
                        step=100, key=f"{key_prefix}qty_{code}"
                    )
                fcol3, fcol4 = st.columns(2)
                with fcol3:
                    sl = st.number_input(
                        "止损价", value=float(stop_loss) if stop_loss else 0.0,
                        min_value=0.0, step=0.01, format="%.2f", key=f"{key_prefix}sl_{code}"
                    )
                with fcol4:
                    tp = st.number_input(
                        "目标价", value=float(target_price) if target_price else 0.0,
                        min_value=0.0, step=0.01, format="%.2f", key=f"{key_prefix}tp_{code}"
                    )
                notes = st.text_input("备注", "", key=f"{key_prefix}notes_{code}")

                if st.form_submit_button("✅ 确认添加", type="primary", width='stretch'):
                    add_position(
                        code=code, name=name,
                        buy_price=buy_price, quantity=int(quantity),
                        stop_loss=sl, target_price=tp, notes=notes,
                    )
                    st.toast(f"✅ {code} 已加入持仓：{int(quantity)}股 @ ¥{buy_price:.2f}", icon="💼")


# ===== 结果渲染函数 =====
def _render_results(results):
    """渲染扫描结果（从session_state取或新扫描）"""
    v10_results = [r for r in results if r.get("type") == "v10"]
    pullback_results = [r for r in results if r.get("type") == "pullback"]
    classic_results = [r for r in results if r.get("type") == "classic"]
    _seen_keys = {}  # key_suffix counter to guarantee unique Streamlit keys

    def _unique_prefix(base, code):
        """生成唯一的 key 前缀，防止同一 code 在不同分组重复"""
        k = f"{base}_{code}"
        cnt = _seen_keys.get(k, 0)
        _seen_keys[k] = cnt + 1
        return f"{base}{cnt}_" if cnt > 0 else f"{base}_"

    if v10_results:
        st.html('<h2>🏆 V10 信号 · 6维评分 · 买入推荐</h2>')
        # 批量获取实时行情
        _codes = [r['code'] for r in v10_results]
        _quotes = {}
        for _c in _codes:
            _q = get_realtime_quote(_c)
            if _q:
                _quotes[_c] = _q
        
        for r in v10_results:
            signal_type = r.get("signal_type", "基础买")
            if signal_type == "全买入":
                emoji = "🔴"
                border_color = "#ff4b4b"
            elif signal_type == "强庄买":
                emoji = "🟠"
                border_color = "#ffab40"
            else:
                emoji = "🟡"
                border_color = "#42a5f5"

            # 实时行情
            _q = _quotes.get(r['code'], {})
            _cur = _q.get('price', 0)
            _pct = _q.get('pct_change', 0)
            _pct_color = "#ef4444" if _pct > 0 else "#22c55e" if _pct < 0 else "var(--text-secondary)"
            _pct_str = f"{_pct:+.2f}%" if _pct else "-"
            _cur_str = f"¥{_cur:.2f}" if _cur else "-"
            # PE/市值/涨跌停
            _pe = _q.get('pe', 0)
            _circ_cap = _q.get('circ_market_cap', 0)
            _limit_up = _q.get('limit_up', 0)
            _extra_parts = []
            if _pe and _pe > 0:
                _extra_parts.append(f"PE {_pe:.1f}")
            if _circ_cap and _circ_cap > 0:
                _extra_parts.append(f"流通{_circ_cap:.0f}亿")
            if _limit_up > 0 and _cur > 0:
                _pct_to_limit = (_limit_up - _cur) / _cur * 100
                if _pct_to_limit < 2:
                    _extra_parts.append(f"<span style='color:#ef4444;'>距涨停{_pct_to_limit:.1f}%</span>")
                elif _cur >= _limit_up:
                    _extra_parts.append("<span style='color:#ef4444;'>已涨停</span>")
            _extra_html = " · ".join(_extra_parts) if _extra_parts else ""

            # 进场建议标签（基于推荐引擎的level和action）
            _level_color_map = {
                "强烈推荐": "#ff4b4b",
                "值得关注": "#ffab40",
                "观察等待": "#ffeb3b",
                "暂不推荐": "#888888",
            }
            _level_bg = "#888888"
            _level_text = "⚪ 暂不推荐"
            # 从_render_recommendation的rec里取level不太方便，直接用score和signal_type判断
            _total_score = r.get("score", 0)
            _signal_type = signal_type
            if _total_score >= 80 or (_signal_type == "全买入" and _total_score >= 60):
                _level_text = "🔴 可进场"
                _level_bg = "#ff4b4b"
            elif _total_score >= 60 or (_signal_type == "强庄买" and _total_score >= 50):
                _level_text = "🟠 建议买入"
                _level_bg = "#ffab40"
            elif _total_score >= 40:
                _level_text = "🟡 观察等回调"
                _level_bg = "#b39700"
            else:
                _level_text = "⚪ 暂不建议"
                _level_bg = "#888888"

            st.html(f"""
            <div class="scan-result-card" style="border-left:4px solid {border_color};">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                    <div>
                        <span style="font-size:1.2em; margin-right:4px;">{emoji}</span>
                        <span style="font-weight:700; color:var(--text-primary); font-size:1.05em;">{r['code']}</span>
                        <span style="color:var(--text-secondary); margin-left:8px;">{r['name']}</span>
                        <span style="color:#ff6b35; margin-left:12px; font-weight:600;">¥{r['price']}</span>
                        <span style="color:var(--text-muted); margin-left:4px;">→</span>
                        <span style="color:var(--text-primary); margin-left:4px; font-weight:600;">{_cur_str}</span>
                        <span style="color:{_pct_color}; margin-left:6px; font-weight:600;">{_pct_str}</span>
                    </div>
                    <div style="display:flex; gap:10px; align-items:center;">
                        <span style="background:{_level_bg}; color:#fff; padding:2px 10px; border-radius:4px; font-size:0.85em; font-weight:700;">{_level_text}</span>
                        <span class="tag tag-accent">{signal_type}</span>
                        <span style="color:#ff6b35; font-weight:700;">{r['score']}分</span>
                        <span style="color:var(--text-secondary); font-size:0.85em;">{" ".join(r['tags'][:4])}</span>
                    </div>
                </div>
                {"<div style='margin-top:4px; font-size:0.82em; color:var(--text-muted);'>📊 " + _extra_html + "</div>" if _extra_html else ""}
            </div>
            """)

            _render_recommendation(
                code=r["code"], name=r["name"],
                signal_type=signal_type, score=r["score"],
            )
            _render_stock_actions(
                code=r["code"], name=r["name"], price=r["price"],
                key_prefix=_unique_prefix("v10", r["code"]),
            )

    if pullback_results:
        st.html('<h2>🔄 波段回调机会 · 买入推荐</h2>')
        _codes_pb = [r['code'] for r in pullback_results]
        _quotes_pb = {}
        for _c in _codes_pb:
            _q = get_realtime_quote(_c)
            if _q:
                _quotes_pb[_c] = _q
        
        for r in pullback_results:
            _q = _quotes_pb.get(r['code'], {})
            _cur = _q.get('price', 0)
            _pct = _q.get('pct_change', 0)
            _pct_color = "#ef4444" if _pct > 0 else "#22c55e" if _pct < 0 else "var(--text-secondary)"
            _pct_str = f"{_pct:+.2f}%" if _pct else "-"
            _cur_str = f"¥{_cur:.2f}" if _cur else "-"
            # PE/市值/涨跌停
            _pe = _q.get('pe', 0)
            _circ_cap = _q.get('circ_market_cap', 0)
            _limit_up = _q.get('limit_up', 0)
            _pb_parts = []
            if _pe and _pe > 0:
                _pb_parts.append(f"PE {_pe:.1f}")
            if _circ_cap and _circ_cap > 0:
                _pb_parts.append(f"流通{_circ_cap:.0f}亿")
            if _limit_up > 0 and _cur > 0:
                _pct_to_limit = (_limit_up - _cur) / _cur * 100
                if _pct_to_limit < 2:
                    _pb_parts.append(f"<span style='color:#ef4444;'>距涨停{_pct_to_limit:.1f}%</span>")
                elif _cur >= _limit_up:
                    _pb_parts.append("<span style='color:#ef4444;'>已涨停</span>")
            _pb_extra = " · ".join(_pb_parts) if _pb_parts else ""

            st.html(f"""
            <div class="scan-result-card" style="border-left:4px solid #ab47bc;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                    <div>
                        <span style="font-weight:700; color:var(--text-primary); font-size:1.05em;">{r['code']}</span>
                        <span style="color:var(--text-secondary); margin-left:8px;">{r['name']}</span>
                        <span style="color:#ff6b35; margin-left:12px; font-weight:600;">¥{r['price']}</span>
                        <span style="color:var(--text-muted); margin-left:4px;">→</span>
                        <span style="color:var(--text-primary); margin-left:4px; font-weight:600;">{_cur_str}</span>
                        <span style="color:{_pct_color}; margin-left:6px; font-weight:600;">{_pct_str}</span>
                    </div>
                    <div style="display:flex; gap:10px; align-items:center;">
                        <span class="tag tag-info">{r.get('level', '')}</span>
                        <span style="color:#ff6b35; font-weight:700;">{r['score']}分</span>
                        <span style="color:var(--text-secondary); font-size:0.85em;">{" ".join(r['tags'][:4])}</span>
                    </div>
                </div>
                {"<div style='margin-top:4px; font-size:0.82em; color:var(--text-muted);'>📊 " + _pb_extra + "</div>" if _pb_extra else ""}
            </div>
            """)

            _render_recommendation(
                code=r["code"], name=r["name"],
                signal_type="基础买", score=r["score"],
            )
            _render_stock_actions(
                code=r["code"], name=r["name"], price=r["price"],
                key_prefix=_unique_prefix("pb", r["code"]),
            )

    if classic_results:
        st.html('<h2>📋 经典策略信号</h2>')
        _codes_cl = [r['code'] for r in classic_results]
        _quotes_cl = {}
        for _c in _codes_cl:
            _q = get_realtime_quote(_c)
            if _q:
                _quotes_cl[_c] = _q
        
        for r in classic_results:
            tags_html = " ".join([f"<span class='tag tag-info'>{t}</span>" for t in r.get('tags', [])[:2]])
            _q = _quotes_cl.get(r['code'], {})
            _cur = _q.get('price', 0)
            _pct = _q.get('pct_change', 0)
            _pct_color = "#ef4444" if _pct > 0 else "#22c55e" if _pct < 0 else "var(--text-secondary)"
            _pct_str = f"{_pct:+.2f}%" if _pct else "-"
            _cur_str = f"¥{_cur:.2f}" if _cur else "-"

            st.html(f"""
            <div class="scan-result-card">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                    <div>
                        <span style="font-weight:700; color:var(--text-primary);">{r['code']}</span>
                        <span style="color:var(--text-secondary); margin-left:8px;">{r['name']}</span>
                        <span style="color:#ff6b35; margin-left:12px;">¥{r['price']}</span>
                        <span style="color:var(--text-muted); margin-left:4px;">→</span>
                        <span style="color:var(--text-primary); margin-left:4px; font-weight:600;">{_cur_str}</span>
                        <span style="color:{_pct_color}; margin-left:6px; font-weight:600;">{_pct_str}</span>
                    </div>
                    <div style="display:flex; gap:10px; align-items:center;">
                        <span class="tag tag-accent">{r['strategy']}</span>
                        {tags_html}
                    </div>
                </div>
            </div>
            """)
            _render_stock_actions(
                code=r["code"], name=r["name"], price=r["price"],
                key_prefix=_unique_prefix("cl", r["code"]),
            )


# 运行扫描（结果存session_state，切页面不丢失）
if st.button("🚀 开始扫描", type="primary", width='stretch'):
    if not all_selected:
        st.warning("请至少选择一个策略！")
    else:
        st.write("⏳ 正在扫描中...V10全市场扫描约需1-2分钟")
        progress_bar = st.progress(0)
        status_text = st.empty()

        def on_progress(current, total):
            pct = min(current / total, 1.0) if total > 0 else 0
            progress_bar.progress(pct)
            status_text.text(f"扫描进度: {current}/{total} ({pct*100:.0f}%)")

        try:
            if scan_mode == "自选股":
                results = scan_watchlist(all_selected, params_dict)
            else:
                results = scan_market(all_selected, params_dict, max_workers=25, progress_callback=on_progress)
        except Exception as e:
            results = []
            st.error(f"❌ 扫描异常: {e}")

        progress_bar.progress(1.0)
        status_text.text("扫描完成！")

        # 存入session_state
        st.session_state["scan_results"] = results
        st.rerun()

# 显示结果（优先取session_state缓存）
if "scan_results" in st.session_state and st.session_state["scan_results"]:
    results = st.session_state["scan_results"]
    st.success(f"🎯 共 {len(results)} 个信号（上次扫描结果）")
    _render_results(results)

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

# 快速入口
st.divider()
st.info("💡 扫描结果中每只股票都有 **👁️ 加入盯盘** 和 **💼 加入持仓** 按钮，可直接操作。持仓管理页面支持实时行情同步、三层止盈止损、飞书止损提醒。")
