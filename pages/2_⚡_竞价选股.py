"""竞价选股页面 — 09:28竞价结束扫描 + 6维评分买入推荐"""
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
    <span class="tag tag-info">🟡 普通竞价</span> 单策略命中 → 观察40+分
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


def _render_recommendation(s: AuctionStock):
    """渲染竞价股票的6维评分+买入推荐"""
    try:
        hist = get_stock_history(s.code, days=250)
        if hist.empty or len(hist) < 20:
            st.caption("⚠️ 历史数据不足，无法生成推荐")
            return

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

    except Exception as e:
        st.caption(f"⚠️ 推荐生成失败: {e}")


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

        st.divider()

        # ===== V10交叉重点 =====
        v10_cross = [s for s in stocks if s.in_v10]
        if v10_cross:
            st.html(f'<h2>📌 V10交叉印证 ({len(v10_cross)}只)</h2>')
            for s in v10_cross:
                sector_tag = f"<span class='tag tag-up'>🔥{s.sector}</span>" if s.sector_hot else f"<span class='tag tag-info'>{s.sector}</span>"
                vibe_tags = " ".join([f"<span class='tag tag-info'>{t}</span>" for t in s.vibe_tags])

                st.html(f"""
                <div class="scan-result-card" style="border-left:4px solid #42a5f5;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <div>
                            <span style="font-weight:700; color:var(--text-primary); font-size:1.05em;">{s.code}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{s.name}</span>
                            <span class="tag tag-accent" style="margin-left:8px;">V10+{s.strategy}</span>
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
                _render_recommendation(s)

        # ===== 三策略结果 =====
        for strat_name, strat_emoji in [("趋势共振", "🔥"), ("游资爆量V1", "🎯"), ("游资竞价V2", "💎")]:
            strat_stocks = [s for s in stocks if s.strategy == strat_name]
            st.html(f'<h2>{strat_emoji} {strat_name} ({len(strat_stocks)}只)</h2>')
            if not strat_stocks:
                st.caption("  - 无符合条件的股票")
            else:
                for s in strat_stocks:
                    v10_tag = "<span class='tag tag-accent' style='margin-left:6px;'>📌V10</span>" if s.in_v10 else ""
                    sector_tag = f"<span class='tag tag-up'>🔥{s.sector}</span>" if s.sector_hot else f"<span class='tag tag-info'>{s.sector}</span>"
                    vibe_tags = " ".join([f"<span class='tag tag-info'>{t}</span>" for t in s.vibe_tags])

                    st.html(f"""
                    <div class="scan-result-card">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                            <div>
                                <span style="font-weight:700; color:var(--text-primary);">{s.code}</span>
                                <span style="color:var(--text-secondary); margin-left:8px;">{s.name}</span>
                                {v10_tag}
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
                    _render_recommendation(s)

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
