"""竞价选股页面 v2 — 竞价专属4维评分 + 进场建议

竞价 ≠ 盘中选股。竞价看的是：
  1. 位置（低位启动 vs 高位加速）— 最核心
  2. 高开幅度（2-4%最优，>6%是风险）
  3. 竞价量能（竞价成交 vs 近期均量）
  4. 板块共振（同板块异动 + 板块涨幅）

进场方式：开盘后等回调介入，不是竞价直接买
"""
import streamlit as st
import numpy as np
from core.auction import run_auction_scan, AuctionStock
from core.ui import inject_global_css, render_theme_toggle, render_page_header

st.set_page_config(page_title="竞价选股", page_icon="⚡", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("⚡ 竞价选股", "09:25竞价结束 → 4维评分 → 开盘后择机介入 · 位置+高开+量能+板块")

with st.expander("📖 竞价4维评分说明"):
    st.html("""
    <div style="color:var(--text-secondary); line-height:1.8;">
    <p style="color:#ff6b35; font-weight:700; font-size:1.05em;">竞价选股 ≠ 盘中选股，竞价看的是开盘前的信号质量</p>
    <table style="width:100%; border-collapse:collapse; margin:8px 0;">
    <tr style="border-bottom:2px solid #ff6b3540;">
        <th style="padding:8px 0; color:#ff6b35; text-align:left; width:25%;">维度</th>
        <th style="padding:8px 0; color:#ff6b35; text-align:left; width:15%;">满分</th>
        <th style="padding:8px 0; color:#ff6b35; text-align:left;">评分逻辑</th>
    </tr>
    <tr style="border-bottom:1px solid var(--border-color);">
        <td style="padding:8px 0;">📍 位置</td>
        <td style="padding:8px 0;">25分</td>
        <td style="color:var(--text-secondary);">近20日跌/横盘→25分(低位启动) | 涨0-5%→22分 | 涨5-10%→15分 | 涨15%+→0分(高位风险)</td>
    </tr>
    <tr style="border-bottom:1px solid var(--border-color);">
        <td style="padding:8px 0;">📈 高开幅度</td>
        <td style="padding:8px 0;">25分</td>
        <td style="color:var(--text-secondary);">2-4%→25分(最优) | 4-5%→15分 | 1-2%→15分 | >6%→0分(追高极险)</td>
    </tr>
    <tr style="border-bottom:1px solid var(--border-color);">
        <td style="padding:8px 0;">📊 竞价量能</td>
        <td style="padding:8px 0;">25分</td>
        <td style="color:var(--text-secondary);">竞价成交额/近5日均量 ≥0.5x→25分(爆量) | ≥0.3x→20分(放量) | ≥0.15x→15分</td>
    </tr>
    <tr>
        <td style="padding:8px 0;">🔥 板块共振</td>
        <td style="padding:8px 0;">25分</td>
        <td style="color:var(--text-secondary);">板块涨幅>2%→10分 | 热门板块→5分 | 同板块3+只异动→10分</td>
    </tr>
    </table>
    <br>
    <p><span style="background:#ff4b4b; color:#fff; padding:2px 8px; border-radius:4px; font-weight:700;">✅ 可进场</span>
    四维均达标 + 总分≥65 → <b>开盘5分钟等回调介入</b></p>
    <p><span style="background:#ffab40; color:#fff; padding:2px 8px; border-radius:4px; font-weight:700;">👁️ 观察</span>
    有亮点但有短板 → <b>等15分钟看走势再决定</b></p>
    <p><span style="background:#888; color:#fff; padding:2px 8px; border-radius:4px; font-weight:700;">❌ 放弃</span>
    多维不足 → <b>不追</b></p>
    <br>
    <p style="color:var(--text-secondary);">⚠️ 竞价选股的进场方式是<b>开盘后择机介入</b>，不是竞价直接买。小幅高开+放量+低位+板块共振是最优组合。</p>
    </div>
    """)


def _score_bar_html(score: float, max_score: float, label: str, desc: str) -> str:
    """渲染单个维度评分条"""
    pct = score / max_score if max_score > 0 else 0
    if pct >= 0.8:
        color = "#00c853"
        icon = "🟢"
    elif pct >= 0.6:
        color = "#ffab40"
        icon = "🟡"
    elif pct > 0:
        color = "#ff4b4b"
        icon = "🟠"
    else:
        color = "#888"
        icon = "⚪"
    return (f'<div style="display:flex; align-items:center; gap:6px; margin:2px 0;">'
            f'<span style="min-width:60px; color:var(--text-secondary); font-size:0.85em;">{icon}{label}</span>'
            f'<div style="flex:1; height:8px; background:var(--bg-card); border-radius:4px; overflow:hidden;">'
            f'<div style="width:{pct*100:.0f}%; height:100%; background:{color}; border-radius:4px;"></div>'
            f'</div>'
            f'<span style="min-width:30px; text-align:right; font-weight:600; color:{color};">{score:.0f}</span>'
            f'<span style="color:var(--text-secondary); font-size:0.8em;">{desc}</span>'
            f'</div>')


def _render_auction_card(s: AuctionStock):
    """渲染单只竞价股票的4维评分卡片"""
    # 4维评分条
    dims_html = (
        _score_bar_html(s.score_position, 25, "位置", s.desc_position) +
        _score_bar_html(s.score_open, 25, "高开", s.desc_open) +
        _score_bar_html(s.score_volume, 25, "量能", s.desc_volume) +
        _score_bar_html(s.score_sector, 25, "板块", s.desc_sector)
    )

    # 位置描述补充
    pos_desc = f"近20日{s.position_20d:+.1f}%" if s.position_20d != 0 else "位置未知"
    open_desc = f"高开{s.change_pct:+.1f}%"
    vol_desc = f"量比{s.vol_ratio:.1f}" if s.vol_ratio > 0 else ""
    sec_desc = f"{s.sector}" if s.sector else ""

    # 进场方式
    if s.action == "可进场":
        action_hint = "⏰ 开盘5分钟等回调介入"
    elif s.action == "观察":
        action_hint = "⏰ 等15分钟看走势再决定"
    else:
        action_hint = "❌ 不追"

    st.html(f"""
    <div style="background:var(--bg-card); border-radius:8px; padding:10px 14px; margin:4px 0;">
        {dims_html}
        <div style="display:flex; gap:16px; font-size:0.82em; color:var(--text-secondary); margin-top:6px; flex-wrap:wrap;">
            <span>{pos_desc}</span>
            <span>{open_desc}</span>
            <span>{vol_desc}</span>
            <span>成交{s.amount_wan/10000:.1f}亿</span>
            <span>{sec_desc}</span>
            {'<span>📌V10交叉</span>' if s.in_v10 else ''}
        </div>
        <div style="font-size:0.82em; color:#ff6b35; margin-top:4px;">{action_hint}</div>
        {'<div style="font-size:0.78em; color:#ef5350; margin-top:2px;">⚠️ ' + ' · '.join(s.missing_data) + '</div>' if s.missing_data else ''}
    </div>
    """)


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

# ===== 显示结果 =====
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
        # 分组
        buy_list = [s for s in stocks if s.action == "可进场"]
        watch_list = [s for s in stocks if s.action == "观察"]
        drop_list = [s for s in stocks if s.action == "放弃"]

        # 汇总卡片
        sum_cols = st.columns(6)
        sum_items = [
            ("📊 扫描", f"{stats.get('total_scanned', 0)}只", "var(--text-primary)"),
            ("🎯 候选", f"{stats.get('total_candidates', 0)}只", "#ff6b35"),
            ("✅ 可进场", f"{len(buy_list)}只", "#ff4b4b"),
            ("👁️ 观察", f"{len(watch_list)}只", "#ffab40"),
            ("📌 V10交叉", f"{stats.get('v10_cross', 0)}只", "#42a5f5"),
            ("⏱️ 耗时", f"{stats.get('elapsed', 0)}秒", "var(--text-secondary)"),
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

        # ===== ✅ 可进场 =====
        if buy_list:
            st.html('<h2>✅ 可进场 · 开盘5分钟等回调介入</h2>')
            for s in buy_list:
                v10_tag = " 📌V10交叉" if s.in_v10 else ""
                chg_color = "#ff4b4b" if s.change_pct > 0 else "#00c853" if s.change_pct < 0 else "var(--text-primary)"
                sec_tag = f"<span class='tag tag-up'>🔥{s.sector}</span>" if s.sector_hot else f"<span class='tag tag-info'>{s.sector}</span>" if s.sector else ""

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
                                量比{s.vol_ratio:.1f} 成交{s.amount_wan/10000:.1f}亿{v10_tag}
                            </span>
                        </div>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <span style="background:#ff4b4b; color:#fff; padding:3px 10px; border-radius:4px; font-size:0.85em; font-weight:700;">✅ 可进场</span>
                            <span style="color:#ff6b35; font-weight:700;">{s.total_score:.0f}分</span>
                            {sec_tag}
                        </div>
                    </div>
                    <div style="display:flex; flex-wrap:wrap; gap:20px; font-size:0.9em; margin-bottom:8px;">
                        <span style="color:var(--text-secondary);">位置 <b style="color:var(--text-primary);">{s.score_position:.0f}/25</b></span>
                        <span style="color:var(--text-secondary);">高开 <b style="color:var(--text-primary);">{s.score_open:.0f}/25</b></span>
                        <span style="color:var(--text-secondary);">量能 <b style="color:var(--text-primary);">{s.score_volume:.0f}/25</b></span>
                        <span style="color:var(--text-secondary);">板块 <b style="color:var(--text-primary);">{s.score_sector:.0f}/25</b></span>
                        <span style="color:var(--text-secondary);">流通 <b style="color:var(--text-primary);">{s.circulation:.0f}亿</b></span>
                    </div>
                    <div style="color:#ff6b35; font-size:0.85em;">⏰ {s.action_reason}</div>
                    {'<div style="color:#ef5350; font-size:0.8em; margin-top:2px;">⚠️ 数据不完整: ' + ' · '.join(s.missing_data) + '</div>' if s.missing_data else ''}
                </div>
                """)

        # ===== 📌 V10交叉印证（优先展示）=====
        v10_stocks = [s for s in stocks if s.in_v10]
        if v10_stocks:
            st.html(f'<h2>📌 V10交叉印证 · {len(v10_stocks)}只</h2>')
            st.caption("以下股票同时命中V10信号和竞价异动，信号确认度更高")
            for s in v10_stocks:
                chg_color = "#ff4b4b" if s.change_pct > 0 else "#00c853" if s.change_pct < 0 else "var(--text-primary)"
                if s.action == "可进场":
                    action_html = '<span style="background:#ff4b4b; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8em; font-weight:700;">✅ 可进场</span>'
                elif s.action == "观察":
                    action_html = '<span style="background:#ffab40; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8em; font-weight:700;">👁️ 观察</span>'
                else:
                    action_html = ""

                st.html(f"""
                <div class="scan-result-card" style="border-left:4px solid #42a5f5;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <div>
                            <span style="font-weight:700; color:var(--text-primary); font-size:1.05em;">{s.name}</span>
                            <span style="color:var(--text-secondary); margin-left:8px;">{s.code}</span>
                            <span class="tag tag-accent" style="margin-left:8px;">V10+竞价</span>
                            {action_html}
                        </div>
                        <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
                            <span style="color:{chg_color}; font-weight:600;">{s.change_pct:+.2f}%</span>
                            <span style="color:var(--text-secondary);">量比 <span style="color:var(--text-primary); font-weight:600;">{s.vol_ratio:.1f}</span></span>
                            <span style="color:var(--text-secondary);">成交 <span style="color:var(--text-primary); font-weight:600;">{s.amount_wan/10000:.1f}亿</span></span>
                            <span style="color:#ff6b35; font-weight:600;">{s.total_score:.0f}分</span>
                        </div>
                    </div>
                </div>
                """)
                _render_auction_card(s)

        # ===== 👁️ 观察 =====
        if watch_list:
            st.html(f'<h2>👁️ 观察 · 等15分钟看走势 · {len(watch_list)}只</h2>')
            for s in watch_list:
                v10_tag = " 📌V10" if s.in_v10 else ""
                chg_color = "#ff4b4b" if s.change_pct > 0 else "#00c853" if s.change_pct < 0 else "var(--text-secondary)"
                st.html(
                    f'<span style="display:inline-block; margin:2px 4px; padding:6px 10px; '
                    f'background:var(--bg-card); border:1px solid var(--border-color); border-radius:8px; font-size:0.85em;">'
                    f'<b>{s.name}</b> <span style="color:var(--text-secondary);">{s.code}</span> '
                    f'<span style="color:{chg_color};">{s.change_pct:+.2f}%</span> '
                    f'<span style="color:var(--text-secondary);">量比{s.vol_ratio:.1f}</span> '
                    f'<span style="color:#ffab40; font-weight:600;">{s.total_score:.0f}分</span>'
                    f'<span style="color:var(--text-secondary); font-size:0.85em;">{v10_tag}</span>'
                    f'<div style="font-size:0.8em; color:var(--text-secondary); margin-top:2px;">{s.action_reason}</div>'
                    f'</span>'
                )

        # ===== ❌ 放弃（折叠）=====
        if drop_list:
            with st.expander(f"❌ 放弃 · {len(drop_list)}只", expanded=False):
                for s in drop_list:
                    chg_color = "#ff4b4b" if s.change_pct > 0 else "#00c853" if s.change_pct < 0 else "var(--text-secondary)"
                    st.html(
                        f'<div style="font-size:0.85em; color:var(--text-secondary); padding:2px 0;">'
                        f'{s.name}({s.code}) <span style="color:{chg_color};">{s.change_pct:+.2f}%</span> '
                        f'量比{s.vol_ratio:.1f} {s.total_score:.0f}分 — {s.action_reason}'
                        f'</div>'
                    )

        # ===== 全部结果明细（折叠）=====
        all_stocks = [s for s in stocks if s.action != "放弃"]
        if all_stocks:
            with st.expander("📋 全部候选明细", expanded=False):
                for s in all_stocks:
                    chg_color = "#ff4b4b" if s.change_pct > 0 else "#00c853" if s.change_pct < 0 else "var(--text-secondary)"
                    v10_tag = " 📌V10" if s.in_v10 else ""
                    st.html(f"""
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid var(--border-color); font-size:0.9em;">
                        <div>
                            <b>{s.name}</b> <span style="color:var(--text-secondary);">{s.code}</span>{v10_tag}
                            <span style="color:{chg_color}; margin-left:8px;">{s.change_pct:+.2f}%</span>
                        </div>
                        <div style="display:flex; gap:12px; color:var(--text-secondary);">
                            <span>位置{s.score_position:.0f}</span>
                            <span>高开{s.score_open:.0f}</span>
                            <span>量能{s.score_volume:.0f}</span>
                            <span>板块{s.score_sector:.0f}</span>
                            <span style="color:#ff6b35; font-weight:600;">{s.total_score:.0f}分</span>
                        </div>
                    </div>
                    """)

        # ===== 操作区 =====
        st.divider()
        action_cols = st.columns(3)
        with action_cols[0]:
            st.info("💡 竞价进场方式：<b>开盘后等回调介入</b>，不是竞价直接买。小幅高开+放量+低位+板块共振是最优组合。")
        with action_cols[1]:
            if st.button("📤 发送到飞书", key="auction_feishu_btn", width='stretch'):
                from core.alerts import send_signal_alert
                success_count = 0
                for s in buy_list[:5]:
                    detail = (
                        f"竞价可进场 | 位置{s.score_position:.0f}/25 高开{s.score_open:.0f}/25 "
                        f"量能{s.score_volume:.0f}/25 板块{s.score_sector:.0f}/25 | "
                        f"总分{s.total_score:.0f} | {s.action_reason}"
                    )
                    if send_signal_alert(s.code, s.name, f"竞价进场", s.price, detail):
                        success_count += 1
                if success_count > 0:
                    st.success(f"已发送 {success_count} 只到飞书！")
                else:
                    st.warning("发送失败，请检查Webhook配置")
        with action_cols[2]:
            st.caption(f"竞价4维评分 v2 | 候选{stats.get('total_candidates', 0)}只")
