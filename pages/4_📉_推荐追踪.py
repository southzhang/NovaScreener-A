"""推荐追踪页面 — 胜率仪表盘 · 冷静期 · 历史推荐 · 验证操作"""
import streamlit as st
import pandas as pd
from core.ui import inject_global_css, render_theme_toggle, render_page_header
from core.v10.data_service import (
    get_tracker,
    check_freshness,
    TRACKER_PATH,
    PROJECT_DIR,
    _run_script,
)

st.set_page_config(page_title="推荐追踪", page_icon="📉", layout="wide")
inject_global_css()
render_theme_toggle()
render_page_header("📉 推荐追踪", "胜率仪表盘 · 冷静期状态 · 历史推荐验证 · 收益追踪")

# ===== 加载数据 =====
tracker = get_tracker()
fresh = check_freshness(TRACKER_PATH, max_minutes=60)

# ===================================================================
# 1. 胜率仪表盘
# ===================================================================
st.html('<h2 style="margin-top:0;">📊 胜率仪表盘</h2>')

# 计算统计
total_recs = 0
next_day_wins = 0
day3_wins = 0
next_day_pcts = []
day3_pcts = []

for record in tracker:
    recs = record.get("recommendations", [])
    for r in recs:
        # 只统计已验证的
        if r.get("status") != "validated":
            continue
        total_recs += 1
        nd_pct = r.get("next_day_pct")
        d3_pct = r.get("day3_pct")
        if nd_pct is not None:
            next_day_pcts.append(nd_pct)
            if nd_pct > 0:
                next_day_wins += 1
        if d3_pct is not None:
            day3_pcts.append(d3_pct)
            if d3_pct > 0:
                day3_wins += 1

next_day_win_rate = (next_day_wins / total_recs * 100) if total_recs > 0 else 0
day3_win_rate = (day3_wins / total_recs * 100) if total_recs > 0 else 0
avg_next_day = (sum(next_day_pcts) / len(next_day_pcts)) if next_day_pcts else 0
avg_day3 = (sum(day3_pcts) / len(day3_pcts)) if day3_pcts else 0

# 仪表盘卡片
stat_cols = st.columns(4)
stat_items = [
    ("📋 总推荐次数", f"{total_recs}", "var(--text-primary)", ""),
    ("📈 次日胜率", f"{next_day_win_rate:.1f}%", "#ff4b4b" if next_day_win_rate >= 50 else "#00c853", f"{next_day_wins}胜/{total_recs - next_day_wins}亏" if total_recs > 0 else "—"),
    ("📈 3日胜率", f"{day3_win_rate:.1f}%", "#ff4b4b" if day3_win_rate >= 50 else "#00c853", f"{day3_wins}胜/{total_recs - day3_wins}亏" if total_recs > 0 else "—"),
    ("💰 平均次日收益", f"{avg_next_day:+.2f}%", "#ff4b4b" if avg_next_day >= 0 else "#00c853", f"3日平均 {avg_day3:+.2f}%" if day3_pcts else "—"),
]
for col, (label, value, color, sub) in zip(stat_cols, stat_items):
    with col:
        sub_html = f"<div class='dash-card-sub' style='color:var(--text-secondary);'>{sub}</div>" if sub else ""
        st.html(f"""
        <div class="dash-card" style="text-align:center;">
            <div class="dash-card-header">{label}</div>
            <div class="dash-card-value" style="color:{color}; font-size:1.4em;">{value}</div>
            {sub_html}
        </div>
        """)

# 数据时效性
badge, badge_color = ("✅ 新鲜", "#00c853") if fresh.get("fresh") else ("⚠️ 过期", "#ffab40") if fresh.get("exists") else ("❌ 无数据", "var(--text-primary)")
mtime = fresh.get("mtime", "—")
age = fresh.get("age_minutes")
age_str = f"{age:.0f}分钟前" if age is not None else "—"
st.html(f"""
<div style="color:var(--text-secondary); font-size:0.85em; margin-top:8px;">
    追踪数据状态: <b style="color:{badge_color};">{badge}</b> · 更新时间 {mtime} · {age_str}
</div>
""")

# ===================================================================
# 2. 冷静期状态
# ===================================================================
st.html('<h2>🧘 冷静期状态</h2>')

# 判断冷静期: 连续3次全亏（次日收益全部为负）
COOLDOWN_THRESHOLD = 3
is_cooldown = False
consecutive_all_loss = 0

if tracker:
    # 按日期倒序检查最近的推荐日
    sorted_records = sorted(tracker, key=lambda x: x.get("date", ""), reverse=True)
    for record in sorted_records:
        recs = record.get("recommendations", [])
        validated = [r for r in recs if r.get("status") == "validated" and r.get("next_day_pct") is not None]
        if not validated:
            continue
        # 检查该日是否全部亏损
        all_loss = all(r.get("next_day_pct", 0) < 0 for r in validated)
        if all_loss:
            consecutive_all_loss += 1
            if consecutive_all_loss >= COOLDOWN_THRESHOLD:
                is_cooldown = True
                break
        else:
            break

if is_cooldown:
    st.html(f"""
    <div style="background:#ff4b4b10; border:1px solid #ff4b4b30; border-left:4px solid #ff4b4b;
                border-radius:10px; padding:16px 20px; margin-bottom:16px;">
        <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:1.3em;">🔴</span>
            <div>
                <div style="font-weight:700; color:#ff4b4b; font-size:1.1em;">冷静中</div>
                <div style="color:var(--text-secondary); font-size:0.88em;">
                    连续 {consecutive_all_loss} 次全部亏损，建议暂停推荐，等待行情好转
                </div>
            </div>
        </div>
    </div>
    """)
else:
    st.html(f"""
    <div style="background:#00c85310; border:1px solid #00c85330; border-left:4px solid #00c853;
                border-radius:10px; padding:16px 20px; margin-bottom:16px;">
        <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:1.3em;">🟢</span>
            <div>
                <div style="font-weight:700; color:#00c853; font-size:1.1em;">可推荐</div>
                <div style="color:var(--text-secondary); font-size:0.88em;">
                    近期无连续全亏记录，推荐状态正常
                </div>
            </div>
        </div>
    </div>
    """)

# ===================================================================
# 3. 历史推荐列表
# ===================================================================
st.html('<h2>📜 历史推荐列表</h2>')

if not tracker:
    st.info("📭 暂无推荐追踪记录")
else:
    # 按日期倒序排列
    sorted_records = sorted(tracker, key=lambda x: x.get("date", ""), reverse=True)

    for record in sorted_records:
        date_str = record.get("date", "未知日期")
        recs = record.get("recommendations", [])
        rec_count = len(recs)

        # 计算该日整体胜率
        validated = [r for r in recs if r.get("status") == "validated" and r.get("next_day_pct") is not None]
        day_wins = sum(1 for r in validated if r.get("next_day_pct", 0) > 0)
        day_rate = (day_wins / len(validated) * 100) if validated else 0
        rate_color = "#ff4b4b" if day_rate >= 50 else "#00c853"

        st.html(f"""
        <div style="background:var(--bg-card); border:1px solid var(--border-color);
                    border-radius:10px; padding:14px 18px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
                <div>
                    <span style="font-weight:700; font-size:1.1em; color:var(--text-primary);">📅 {date_str}</span>
                    <span style="color:var(--text-secondary); margin-left:12px;">推荐 {rec_count} 只</span>
                </div>
                <div>
                    <span style="color:{rate_color}; font-weight:600;">次日胜率 {day_rate:.0f}%</span>
                    <span style="color:var(--text-secondary); margin-left:8px; font-size:0.85em;">
                        ({day_wins}胜/{len(validated) - day_wins}亏)
                    </span>
                </div>
            </div>
        """)

        for r in recs:
            code = r.get("code", "")
            name = r.get("name", "")
            signal = r.get("signal", "")
            price = r.get("price", 0)
            stop_loss = r.get("stop_loss")
            nd_open = r.get("next_day_open")
            nd_close = r.get("next_day_close")
            nd_pct = r.get("next_day_pct")
            d3_close = r.get("day3_close")
            d3_pct = r.get("day3_pct")
            status = r.get("status", "")

            # 信号等级边框色
            if signal == "全买入":
                border_c = "#ff4b4b"
                tag_class = "tag-up"
            elif signal == "强庄买":
                border_c = "#ffab40"
                tag_class = "tag-accent"
            elif signal == "基础买":
                border_c = "#ffeb3b"
                tag_class = "tag-info"
            else:
                border_c = "var(--border-color)"
                tag_class = "tag-accent"

            # 次日收益色
            if nd_pct is not None:
                nd_color = "#ff4b4b" if nd_pct >= 0 else "#00c853"
                nd_arrow = "▲" if nd_pct >= 0 else "▼"
                nd_str = f"{nd_arrow} {nd_pct:+.2f}%"
            else:
                nd_color = "var(--text-secondary)"
                nd_str = "—"

            # 3日收益色
            if d3_pct is not None:
                d3_color = "#ff4b4b" if d3_pct >= 0 else "#00c853"
                d3_arrow = "▲" if d3_pct >= 0 else "▼"
                d3_str = f"{d3_arrow} {d3_pct:+.2f}%"
            else:
                d3_color = "var(--text-secondary)"
                d3_str = "—"

            # 验证状态
            if status == "validated":
                status_badge = '<span style="color:#00c853; font-size:0.82em;">✅ 已验证</span>'
            else:
                status_badge = '<span style="color:#ffab40; font-size:0.82em;">⏳ 待验证</span>'

            # 止损价
            sl_str = f"¥{stop_loss:.2f}" if isinstance(stop_loss, (int, float)) and stop_loss else "—"

            st.html(f"""
            <div style="border-left:3px solid {border_c}; padding:8px 14px; margin:6px 0;
                        background:var(--bg-primary); border-radius:0 8px 8px 0;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                    <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                        <span style="font-weight:700; color:var(--text-primary);">{name}</span>
                        <span style="color:var(--text-secondary);">{code}</span>
                        <span class="tag {tag_class}">{signal}</span>
                    </div>
                    <div style="display:flex; align-items:center; gap:14px; flex-wrap:wrap; font-size:0.88em;">
                        <span style="color:var(--text-secondary);">推荐价 <b style="color:var(--text-primary);">¥{price:.2f}</b></span>
                        <span style="color:var(--text-secondary);">止损 <b style="color:#ff4b4b;">{sl_str}</b></span>
                        <span style="color:var(--text-secondary);">次日 <b style="color:{nd_color};">{nd_str}</b></span>
                        <span style="color:var(--text-secondary);">3日 <b style="color:{d3_color};">{d3_str}</b></span>
                        {status_badge}
                    </div>
                </div>
            </div>
            """)

        st.html("</div>")  # 关闭日期卡片

# ===================================================================
# 4. 验证操作
# ===================================================================
st.html('<h2>🔧 验证操作</h2>')

st.html("""
<div style="color:var(--text-secondary); font-size:0.9em; margin-bottom:12px;">
    手动触发验证，回填历史推荐的次日开盘/收盘价及3日收益数据。
    验证脚本会读取追踪记录，自动查询行情并更新。
</div>
""")

# 找到 tracker 脚本路径
import os
TRACKER_SCRIPT = os.path.join(PROJECT_DIR, "core", "v10", "tail_rec_tracker.py")

col1, col2 = st.columns([1, 2])
with col1:
    if st.button("▶️ 执行验证 (Validate)", type="primary", use_container_width=True):
        import time as _time
        _debug_log = f"[{_time.strftime('%H:%M:%S')}] 验证按钮被点击"
        st.write("⏳ 正在验证历史推荐数据，请稍候...")
        try:
            result = _run_script(TRACKER_SCRIPT, "推荐追踪验证", extra_args=["validate"], timeout=60)
            _debug_log += f" → success={result.get('success')}, desc={result.get('description','')}"
        except Exception as _e:
            result = {"success": False, "description": f"异常: {_e}", "stdout": "", "stderr": str(_e)}
            _debug_log += f" → 异常: {_e}"
        # 写调试日志
        import os as _os
        _log_path = _os.path.join(_os.path.expanduser("~"), ".hermes", "cache", "validate_debug.log")
        try:
            with open(_log_path, "a") as _f:
                _f.write(_debug_log + "\n")
        except Exception:
            pass
        if result.get("success"):
            st.success(f"✅ {result.get('description', '验证完成')}")
            if result.get("stdout"):
                st.code(result["stdout"][-500:], language="log")
            st.balloons()
            _time.sleep(2)  # 让用户看到成功消息
            st.rerun()
        else:
            st.error(f"❌ {result.get('description', '验证失败')}")
            if result.get("stderr"):
                st.code(result["stderr"][-500:], language="log")

with col2:
    # 显示待验证记录统计
    pending_count = 0
    validated_count = 0
    for record in tracker:
        for r in record.get("recommendations", []):
            if r.get("status") == "validated":
                validated_count += 1
            else:
                pending_count += 1

    st.html(f"""
    <div class="dash-card" style="display:flex; gap:24px; align-items:center;">
        <div style="text-align:center;">
            <div class="dash-card-header">已验证</div>
            <div class="dash-card-value" style="color:#00c853;">{validated_count}</div>
        </div>
        <div style="text-align:center;">
            <div class="dash-card-header">待验证</div>
            <div class="dash-card-value" style="color:#ffab40;">{pending_count}</div>
        </div>
        <div style="text-align:center;">
            <div class="dash-card-header">总记录</div>
            <div class="dash-card-value" style="color:var(--text-primary);">{validated_count + pending_count}</div>
        </div>
    </div>
    """)

# ===== 收益趋势 (简单表格视图) =====
if tracker:
    st.html('<h2>📈 收益明细</h2>')

    rows = []
    for record in sorted(tracker, key=lambda x: x.get("date", ""), reverse=True):
        date_str = record.get("date", "")
        for r in record.get("recommendations", []):
            nd_pct = r.get("next_day_pct")
            d3_pct = r.get("day3_pct")
            rows.append({
                "日期": date_str,
                "代码": r.get("code", ""),
                "名称": r.get("name", ""),
                "信号": r.get("signal", ""),
                "推荐价": r.get("price", 0),
                "次日收益%": nd_pct if nd_pct is not None else None,
                "3日收益%": d3_pct if d3_pct is not None else None,
                "状态": r.get("status", ""),
            })

    if rows:
        df = pd.DataFrame(rows)

        def _highlight_pct(val):
            if isinstance(val, (int, float)) and not pd.isna(val):
                if val > 0:
                    return "color: #ff4b4b"
                elif val < 0:
                    return "color: #00c853"
            return ""

        styled = df.style.map(_highlight_pct, subset=["次日收益%", "3日收益%"])
        st.dataframe(
            styled,
            width="stretch",
            hide_index=True,
            column_config={
                "推荐价": st.column_config.NumberColumn(format="¥%.2f"),
                "次日收益%": st.column_config.NumberColumn(format="%.2f%%"),
                "3日收益%": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
