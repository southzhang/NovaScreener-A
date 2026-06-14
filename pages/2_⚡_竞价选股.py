"""竞价选股页面 — 09:28竞价结束扫描 + 6维评分买入推荐 + 进场建议"""
import streamlit as st
import pandas as pd
import numpy as np
from core.auction import run_auction_scan, AuctionStock
from core.data import get_stock_history, get_capital_flow, get_sector_score
from core.recommend import generate_buy_recommendation
from core.ui import inject_global_css, render_theme_toggle, render_page_header

st.set_page_config(page_title="竞价选股", page_icon="⚡", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("⚡ 竞价选股", "09:25竞价结束 → 09:28扫描 → 09:30前出结果 · 趋势共振 · 游资爆量V1 · 游资竞价V2 + 板块热度 + V10交叉")

with st.expander("📖 策略说明"):
    st.html("""
    <div style="color:var(--text-secondary); line-height:1.8;">
    <table style="width:100%; border-collapse:collapse;">
    <tr style="border-bottom:2px solid #ff6b3540;">
        <th style="padding:8px 0; color:#ff6b35; text-align:left;">策略</th>
        <th style="padding:8px 0; color:#ff6b35; text-align:left;">条件</th>
        <th style="padding:8px 0; color:#ff6b35; text-align:left;">适合</th>
    </tr>
    <tr style="border-bottom:1px solid var(--border-color);">
        <td style="padding:8px 0;">🔥 趋势共振</td>
        <td style="color:var(--text-secondary);">量比>3 + 涨幅3-6% + 成交额>2000万 + 流通<200亿</td>
        <td style="color:var(--text-secondary);">趋势确认型</td>
    </tr>
    <tr style="border-bottom:1px solid var(--border-color);">
        <td style="padding:8px 0;">🎯 游资爆量V1</td>
        <td style="color:var(--text-secondary);">量比>4 + 涨幅3-7% + 成交额>5000万 + 流通<100亿</td>
        <td style="color:var(--text-secondary);">爆量追涨型</td>
    </tr>
    <tr>
        <td style="padding:8px 0;">💎 游资竞价V2</td>
        <td style="color:var(--text-secondary);">量比>2 + 涨幅2-5% + 分档成交额 + 流通<100亿</td>
        <td style="color:var(--text-secondary);">低吸潜伏型</td>
    </tr>
    </table>
    <br>
    <strong style="color:#ff6b35;">Vibe评分</strong>: 振幅大+1 / 量价齐升+1 / 强势开盘+1 / 爆量+1 (满分4分)<br>
    <strong style="color:#ff6b35;">竞价6维评分（100分制）：</strong>竞价信号级别 30分 | 基本面(ROE) 15分 | 资金面 20分 | 振幅分位 15分 | 板块风口 10分 | 追高风险 10分<br><br>
    <span class="tag tag-up">🔴 强势竞价</span> 趋势共振 + V10交叉 + Vibe≥3 → 强推80+分<br>
    <span class="tag tag-accent">🟠 活跃竞价</span> 游资爆量V1/V2 + 板块热 → 关注60+分<br>
    <span class="tag tag-info">🟡 普通竞价</span> 单策略命中 → 观察40+分<br><br>
    <strong style="color:#ff6b35;">进场建议分级：</strong><br>
    ✅ <b>可进场</b> — 强势竞价(评分≥75) 或 V10交叉+活跃竞价(评分≥70)<br>
    👁️ <b>观察</b> — 活跃竞价(评分≥55) 或 V10交叉(评分≥50)<br>
    ❌ <b>不建议</b> — 评分不足或追高风险过大
    </div>
    """)


def _auction_signal_type(strategy: str, vibe_score: int, in_v10: bool, sector_hot: bool) -> tuple:
    """将竞价策略映射为信号类型和评分基数"""
    if strategy == "趋势共振" and in_v10 and vibe_score >= 3:
        return "强势竞价", 85
    elif strategy == "趋势共振" and (in_v10 or vibe_score >= 3):
        return "强势竞价", 75
    elif strategy == "趋势共振":
        return "活跃竞价", 65
    elif strategy == "游资爆量V1" and sector_hot:
        return "活跃竞价", 70
    elif strategy == "游资爆量V1":
        return "活跃竞价", 60
    elif strategy == "游资竞价V2" and sector_hot:
        return "活跃竞价", 60
    elif strategy == "游资竞价V2":
        return "普通竞价", 50
    else:
        return "普通竞价", 40


def _classify_action(rec, signal_type: str, in_v10: bool) -> str:
    """根据推荐结果+信号类型判定进场建议

    返回: "可进场" / "观察" / "不建议"
    """
    score = rec.total_score if rec else 0

    # ✅ 可进场：强信号+高评分
    if signal_type == "强势竞价" and score >= 75:
        return "可进场"
    if in_v10 and signal_type == "活跃竞价" and score >= 70:
        return "可进场"

    # 👁️ 观察：中等评分
    if signal_type == "活跃竞价" and score >= 55:
        return "观察"
    if signal_type == "强势竞价" and score >= 55:
        return "观察"
    if in_v10 and score >= 50:
        return "观察"

    # ❌ 不建议
    return "不建议"


def _build_recommendation(s: AuctionStock):
    """生成推荐结果，返回 (rec, signal_type) 或 (None, signal_type)"""
    try:
        hist = get_stock_history(s.code, days=250)
        if hist.empty or len(hist) < 20:
            return None, None

        close_arr = hist["close"].values.astype(np.float64)
        high_arr = hist["high"].values.astype(np.float64)
        low_arr = hist["low"].values.astype(np.float64)
        vol_arr = hist["volume"].values.astype(np.float64)
        open_arr = hist["open"].values.astype(np.float64)

        flow_data = get_capital_flow(s.code)
        capital_flow = flow_data.get("main_net_inflow", 0) if flow_data else 0
        sector_score = get_sector_score(s.code)

        signal_type, base_score = _auction_signal_type(
            s.strategy, s.vibe_score, s.in_v10, s.sector_hot
        )

        rec = generate_buy_recommendation(
            code=s.code, name=s.name,
            close=close_arr, high=high_arr, low=low_arr,
            volume=vol_arr, open_price=open_arr,
            signal_type=signal_type, score=base_score,
            change_pct=s.change_pct,
            capital_flow=capital_flow,
            sector_score=sector_score,
        )
        return rec, signal_type
    except Exception:
        return None, None


def _render_recommendation_card(rec, signal_type: str, action: str):
    """渲染6维评分+买入推荐指标"""
    if not rec:
        return

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

    # ---- 核心指标一行（自定义HTML，红涨绿跌）----
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
    st.caption(f"💡 {rec.reason} | ⚠️ {rec.risk_note}")


# ===== 扫描按钮 =====
if st.button("🚀 开始竞价扫描", type="primary", width='stretch'):
    progress = st.progress(0)
    status = st.empty()

    def on_progress(pct, msg):
        progress.progress(pct)
        status.text(msg)

    result = run_auction_scan(progress_callback=on_progress)
    progress.progress(1.0)

    stocks = result.get("stocks", [])
    sector_heat = result.get("sector_heat", {})
    stats = result.get("stats", {})

    # 保存到 session_state
    st.session_state["auction_stocks"] = stocks
    st.session_state["auction_sector_heat"] = sector_heat
    st.session_state["auction_stats"] = stats
    st.session_state["auction_scanned"] = True

    if stats.get("error"):
        st.error(stats["error"])
    elif not stocks:
        st.info("📭 竞价时段无符合条件的股票")
        st.caption("注意: 竞价选股需在09:25-09:30之间运行")
    else:
        status.text("扫描完成！")
        st.rerun()

# ===== 显示结果（从 session_state 读取）=====
if st.session_state.get("auction_scanned"):
    stocks = st.session_state.get("auction_stocks", [])
    sector_heat = st.session_state.get("auction_sector_heat", {})
    stats = st.session_state.get("auction_stats", {})

    if stats.get("error"):
        st.error(stats["error"])
    elif not stocks:
        st.info("📭 竞价时段无符合条件的股票")
        st.caption("注意: 竞价选股需在09:25-09:30之间运行")
    else:
        # ===== 预计算推荐结果和进场建议 =====
        rec_cache = {}  # code -> (rec, signal_type, action)
        for s in stocks:
            rec, signal_type = _build_recommendation(s)
            if signal_type:
                action = _classify_action(rec, signal_type, s.in_v10)
            else:
                action = "不建议"
            rec_cache[s.code] = (rec, signal_type, action)

        buy_list = [s for s in stocks if rec_cache.get(s.code, (None, None, "不建议"))[2] == "可进场"]
        watch_list = [s for s in stocks if rec_cache.get(s.code, (None, None, "不建议"))[2] == "观察"]

        # 汇总卡片
        sum_cols = st.columns(5)
        sum_items = [
            ("📊 扫描", f"{stats['total_scanned']}只", "var(--text-primary)"),
            ("🎯 选出", f"{stats['total_selected']}只", "#ff6b35"),
            ("🔥 趋势", f"{stats['trend_count']}", "#ff4b4b"),
            ("🎯 游V1+V2", f"{stats['youzi_v1_count'] + stats['youzi_v2_count']}", "#ffab40"),
            ("📌 V10交叉", f"{stats['v10_cross']}只", "#42a5f5"),
        ]
        for col, (label, value, color) in zip(sum_cols, sum_items):
            with col:
                st.html(f"""
                <div class="dash-card" style="text-align:center;">
                    <div class="dash-card-header">{label}</div>
                    <div class="dash-card-value" style="color:{color};">{value}</div>
                </div>
                """)

        # 板块热度
        if sector_heat:
            top5 = sorted(sector_heat.items(), key=lambda x: x[1] or 0, reverse=True)[:5]
            heat_parts = []
            for name, v in top5:
                if v:
                    heat_parts.append(f"<span class='tag tag-up'>🔥{name} +{v:.1f}%</span>")
                else:
                    heat_parts.append(f"<span class='tag tag-info'>{name}</span>")
            st.html(f"<div style='margin:12px 0;'>📊 今日热点板块: {' '.join(heat_parts)}</div>")

        # ===== 🎯 进场建议汇总 =====
        if buy_list or watch_list:
            st.html('<h2>🎯 进场建议</h2>')

            # 可进场卡片
            if buy_list:
                for s in buy_list:
                    rec, signal_type, action = rec_cache.get(s.code, (None, "", "可进场"))
                    score = rec.total_score if rec else 0
                    entry = rec.entry_price if rec else s.price
                    stop = rec.stop_loss if rec else 0
                    stop_pct = f"-{(s.price - stop) / s.price * 100:.0f}%" if stop > 0 and s.price > 0 else ""
                    target = rec.target_1 if rec else 0
                    target_pct = f"+{(target - s.price) / s.price * 100:.0f}%" if target > 0 and s.price > 0 else ""
                    position = f"{rec.position_pct}%" if rec else ""
                    rr = f"{rec.risk_reward}:1" if rec else ""
                    reason = rec.reason if rec else ""
                    v10_tag = " 📌V10交叉" if s.in_v10 else ""
                    vibe_str = f" Vibe{s.vibe_score}/4" if s.vibe_score else ""

                    # 涨跌色
                    chg_color = "#ff4b4b" if s.change_pct > 0 else "#00c853" if s.change_pct < 0 else "var(--text-primary)"

                    st.html(f"""
                    <div style="background:var(--bg-card); border:1px solid var(--border-color);
                                border-left:4px solid #ff4b4b; border-radius:10px;
                                padding:16px 20px; margin-bottom:12px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
                            <div>
                                <span style="font-weight:800; color:var(--text-primary); font-size:1.15em;">{s.name}</span>
                                <span style="color:var(--text-secondary); margin-left:8px;">{s.code}</span>
                                <span style="color:{chg_color}; font-weight:600; margin-left:12px;">
                                    ¥{s.price:.2f} {s.change_pct:+.2f}%
                                </span>
                                <span style="color:var(--text-secondary); margin-left:8px; font-size:0.85em;">
                                    量比{s.vol_ratio} {s.strategy}{v10_tag}{vibe_str}
                                </span>
                            </div>
                            <div style="display:flex; gap:8px; align-items:center;">
                                <span style="background:#ff4b4b; color:#fff; padding:3px 10px; border-radius:4px; font-size:0.85em; font-weight:700;">✅ 可进场</span>
                                <span class="tag tag-accent">{signal_type}</span>
                                <span style="color:var(--text-secondary); font-size:0.85em;">评分 {score:.0f}</span>
                            </div>
                        </div>
                        <div style="display:flex; flex-wrap:wrap; gap:20px; font-size:0.9em; margin-bottom:8px;">
                            <span style="color:var(--text-secondary);">买入 <b style="color:var(--text-primary);">¥{entry:.2f}</b></span>
                            <span style="color:var(--text-secondary);">止损 <b style="color:#00c853;">¥{stop:.2f}（{stop_pct}）</b></span>
                            <span style="color:var(--text-secondary);">目标 <b style="color:#ff4b4b;">¥{target:.2f}（{target_pct}）</b></span>
                            <span style="color:var(--text-secondary);">仓位 <b style="color:var(--text-primary);">{position}</b></span>
                            <span style="color:var(--text-secondary);">盈亏比 <b style="color:var(--text-primary);">{rr}</b></span>
                        </div>
                        {f'<div style="color:var(--text-secondary); font-size:0.82em;">💡 {reason}</div>' if reason else ''}
                    </div>
                    """)

            # 观察池简要
            if watch_list:
                st.html(f'<h3 style="color:var(--text-primary);">👁️ 观察 · {len(watch_list)}只</h3>')
                watch_rows = []
                for s in watch_list:
                    rec, signal_type, action = rec_cache.get(s.code, (None, "", "观察"))
                    score = rec.total_score if rec else 0
                    v10_tag = " 📌V10" if s.in_v10 else ""
                    chg_color = "#ff4b4b" if s.change_pct > 0 else "#00c853" if s.change_pct < 0 else "var(--text-secondary)"
                    watch_rows.append(
                        f'<span style="display:inline-block; margin:2px 4px; padding:3px 8px; '
                        f'background:var(--bg-card); border:1px solid var(--border-color); border-radius:6px; font-size:0.85em;">'
                        f'{s.name} <span style="color:var(--text-secondary);">{s.code}</span> '
                        f'<span style="color:{chg_color};">{s.change_pct:+.2f}%</span> '
                        f'<span style="color:var(--text-secondary); font-size:0.85em;">{signal_type}{v10_tag} {score:.0f}分</span>'
                        f'</span>'
                    )
                st.html("".join(watch_rows))

            st.divider()

        # ===== V10交叉重点 =====
        v10_cross = [s for s in stocks if s.in_v10]
        if v10_cross:
            st.html(f'<h2>📌 V10交叉印证 ({len(v10_cross)}只)</h2>')
            for s in v10_cross:
                rec, signal_type, action = rec_cache.get(s.code, (None, None, "不建议"))
                sector_tag = f"<span class='tag tag-up'>🔥{s.sector}</span>" if s.sector_hot else f"<span class='tag tag-info'>{s.sector}</span>"
                vibe_tags = " ".join([f"<span class='tag tag-info'>{t}</span>" for t in s.vibe_tags])

                # 进场标签
                if action == "可进场":
                    action_html = '<span style="background:#ff4b4b; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8em; font-weight:700;">✅ 可进场</span>'
                elif action == "观察":
                    action_html = '<span style="background:#ffab40; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8em; font-weight:700;">👁️ 观察</span>'
                else:
                    action_html = ""

                st.html(f"""
                <div class="scan-result-card" style="border-left:4px solid #42a5f5;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <div>
                            <span style="font-weight:700; color:var(--text-primary); font-size:1.05em;">{s.code}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{s.name}</span>
                            <span class="tag tag-accent" style="margin-left:8px;">V10+{s.strategy}</span>
                            {action_html}
                        </div>
                        <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
                            <span style="color:#ff4b4b; font-weight:600;">+{s.change_pct}%</span>
                            <span style="color:var(--text-secondary);">量比 <span style="color:var(--text-primary); font-weight:600;">{s.vol_ratio}</span></span>
                            <span style="color:var(--text-secondary);">成交额 <span style="color:var(--text-primary); font-weight:600;">{s.amount_wan/10000:.1f}亿</span></span>
                            <span style="color:var(--text-secondary);">Vibe <span style="color:#ff6b35; font-weight:600;">{s.vibe_score}/4</span></span>
                            {sector_tag} {vibe_tags}
                        </div>
                    </div>
                </div>
                """)
                _render_recommendation_card(rec, signal_type, action)

        # ===== 三策略结果 =====
        for strat_name, strat_emoji in [("趋势共振", "🔥"), ("游资爆量V1", "🎯"), ("游资竞价V2", "💎")]:
            strat_stocks = [s for s in stocks if s.strategy == strat_name]
            st.html(f'<h2>{strat_emoji} {strat_name} ({len(strat_stocks)}只)</h2>')
            if not strat_stocks:
                st.caption("  - 无符合条件的股票")
            else:
                for s in strat_stocks:
                    rec, signal_type, action = rec_cache.get(s.code, (None, None, "不建议"))
                    v10_tag = "<span class='tag tag-accent' style='margin-left:6px;'>📌V10</span>" if s.in_v10 else ""
                    sector_tag = f"<span class='tag tag-up'>🔥{s.sector}</span>" if s.sector_hot else f"<span class='tag tag-info'>{s.sector}</span>"
                    vibe_tags = " ".join([f"<span class='tag tag-info'>{t}</span>" for t in s.vibe_tags])

                    # 进场标签
                    if action == "可进场":
                        action_html = '<span style="background:#ff4b4b; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8em; font-weight:700; margin-left:6px;">✅ 可进场</span>'
                    elif action == "观察":
                        action_html = '<span style="background:#ffab40; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8em; font-weight:700; margin-left:6px;">👁️ 观察</span>'
                    else:
                        action_html = ""

                    st.html(f"""
                    <div class="scan-result-card">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                            <div>
                                <span style="font-weight:700; color:var(--text-primary);">{s.code}</span>
                                <span style="color:var(--text-secondary); margin-left:8px;">{s.name}</span>
                                {v10_tag}
                                {action_html}
                            </div>
                            <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
                                <span style="color:#ff4b4b; font-weight:600;">+{s.change_pct}%</span>
                                <span style="color:var(--text-secondary);">量比 <span style="color:var(--text-primary);">{s.vol_ratio}</span></span>
                                <span style="color:var(--text-secondary);">成交额 <span style="color:var(--text-primary);">{s.amount_wan/10000:.1f}亿</span></span>
                                <span style="color:var(--text-secondary);">换手 <span style="color:var(--text-primary);">{s.turnover}%</span></span>
                                <span style="color:var(--text-secondary);">Vibe <span style="color:#ff6b35;">{s.vibe_score}</span></span>
                                {sector_tag} {vibe_tags}
                            </div>
                        </div>
                    </div>
                    """)
                    _render_recommendation_card(rec, signal_type, action)

        # ===== 操作区 =====
        st.divider()
        action_cols = st.columns(3)
        with action_cols[0]:
            st.info("💡 扫描结果可一键添加到**💼 持仓管理**页面跟踪盈亏和止盈止损")
        with action_cols[1]:
            if st.button("📤 发送到飞书", width='stretch'):
                from core.alerts import send_signal_alert
                success_count = 0
                for s in stocks[:10]:
                    signal_type, _ = _auction_signal_type(s.strategy, s.vibe_score, s.in_v10, s.sector_hot)
                    detail = (
                        f"竞价{signal_type} | 量比{s.vol_ratio} | "
                        f"成交额{s.amount_wan/10000:.1f}亿 | "
                        f"Vibe{s.vibe_score}/4 | "
                        f"板块:{s.sector}{'🔥' if s.sector_hot else ''} | "
                        f"V10:{'✅' if s.in_v10 else '❌'}"
                    )
                    if send_signal_alert(s.code, s.name, f"竞价-{s.strategy}", s.price, detail):
                        success_count += 1
                if success_count > 0:
                    st.success(f"已发送 {success_count} 只到飞书！")
                else:
                    st.warning("发送失败，请检查Webhook配置")
        with action_cols[2]:
            st.caption(f"⏱ 耗时{stats['elapsed']}秒 | 全市场{stats['total_scanned']}只 | 竞价选股v7引擎 + 6维评分")
