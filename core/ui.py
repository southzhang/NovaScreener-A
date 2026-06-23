"""共享 UI 样式模块 — 双主题 + 顺滑切换 + 专业配色"""
import streamlit as st

def inject_global_css():
    """注入全局 CSS 样式（动态主题变量 + 交互增强）"""
    pref = st.session_state.get("theme_pref", "auto")
    
    if pref == "auto":
        # 跟随系统：深色/浅色调色板都注入，用 prefers-color-scheme 控制
        light_vars = _get_theme_vars("light")
        dark_vars = _get_theme_vars("dark")
        theme_rule = "@media (prefers-color-scheme: dark) { :root { " + "; ".join(dark_vars) + "; } }"
        root_vars = ":root { " + "; ".join(light_vars) + "; }"
        theme_class = ""
    else:
        vars = _get_theme_vars(pref)
        root_vars = ":root { " + "; ".join(vars) + "; }"
        theme_rule = ""
        theme_class = ""
    
    # 平滑过渡 CSS（仅对主题变量生效，不卡顿其他交互）
    transition_css = """
    :root {
        transition: background-color 0.3s ease, color 0.3s ease;
    }
    .stApp, [data-testid="stSidebar"], .dash-card, .scan-result-card,
    [data-testid="stMetric"], [data-testid="stDataFrame"], .stTabs [data-baseweb="tab-list"],
    .stTextInput input, .stNumberInput input, .stTextArea textarea,
    .stButton button, [data-testid="stExpander"] {
        transition: background-color 0.3s ease, border-color 0.3s ease,
                    box-shadow 0.3s ease, color 0.3s ease;
    }
    """
    
    st.html(f"""
    <style>
    {root_vars}
    {theme_rule}

    /* ===== 全局 ===== */
    .stApp {{
        background: var(--bg-primary);
        color: var(--text-primary);
    }}
    [data-testid="stHeader"] {{ background: transparent !important; }}
    .block-container {{ padding-top: 1rem; }}
    #MainMenu, footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none; }}

    /* ===== 侧边栏 ===== */
    [data-testid="stSidebar"] {{
        background: var(--sidebar-bg);
        border-right: 1px solid var(--sidebar-border);
    }}
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span:not([role="img"]) {{ color: var(--text-primary); }}
    [data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small {{
        color: var(--text-muted) !important;
    }}
    [data-testid="stSidebarNav"] a, [data-testid="stSidebarNav"] span,
    [data-testid="stSidebarNav"] p {{ color: var(--text-primary) !important; }}
    [data-testid="stSidebarNav"] a:hover {{ color: var(--accent) !important; }}
    [data-testid="stSidebar"] .stButton button {{
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        color: var(--text-primary);
    }}
    [data-testid="stSidebar"] .stButton button:hover {{
        border-color: var(--accent);
        box-shadow: 0 0 12px var(--border-glow);
    }}

    /* ===== 覆盖 Streamlit 内置变量 ===== */
    :root {{
        --st-text-color: var(--text-primary) !important;
        --st-text-secondary-color: var(--text-secondary) !important;
        --st-text-tertiary-color: var(--text-muted) !important;
        --st-background-color: var(--bg-primary) !important;
        --st-secondary-background-color: var(--sidebar-bg) !important;
    }}

    /* ===== 表单控件 ===== */
    .stCheckbox label, .stRadio label, .stToggle label,
    .stCheckbox label p, .stRadio label p,
    [data-testid="stCheckbox"] label, [data-testid="stRadio"] label {{
        color: var(--text-primary) !important;
    }}
    .stCheckbox label:hover, .stRadio label:hover {{ color: var(--accent) !important; }}
    .stExpander summary p, .stExpander summary div, details[open] summary p {{
        color: var(--text-primary) !important;
    }}
    .stCaption, [data-testid="stCaption"], [data-testid="stCaption"] p {{
        color: var(--text-muted) !important;
    }}

    /* ===== 全局文字跟随主题（覆盖 Streamlit 内置主题） ===== */
    .stApp, .stApp *:not(svg):not(path):not(strong):not(b) {{ color: var(--text-primary); }}
    .stApp a {{ color: var(--accent); }}
    .stApp code {{ color: var(--text-secondary); }}

    /* ===== A股涨跌色 ===== */
    [data-testid="stMetricDelta"] [data-testid="stMetricDeltaIcon-Up"] svg {{ color: var(--up-color) !important; }}
    [data-testid="stMetricDelta"] [data-testid="stMetricDeltaIcon-Down"] svg {{ color: var(--down-color) !important; }}
    [data-testid="stMetricDelta"] div[data-testid="stMetricDeltaIcon-Up"] + span {{ color: var(--up-color) !important; }}
    [data-testid="stMetricDelta"] div[data-testid="stMetricDeltaIcon-Down"] + span {{ color: var(--down-color) !important; }}

    /* ===== Metric 卡片 ===== */
    [data-testid="stMetric"] {{
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 10px;
        padding: 12px 16px;
        box-shadow: var(--shadow);
    }}
    [data-testid="stMetric"]:hover {{ border-color: var(--accent); box-shadow: var(--shadow-hover); }}
    [data-testid="stMetric"] label {{ color: var(--text-secondary) !important; font-size: 0.78em !important; }}
    [data-testid="stMetric"] [data-testid="stMetricValue"] {{
        color: var(--text-primary) !important; font-weight: 700 !important;
    }}

    /* ===== 标题 ===== */
    h1, h2, h3 {{ color: var(--text-primary) !important; }}
    h1 {{
        background: linear-gradient(135deg, #ff6b35 0%, #ff8f60 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800 !important;
    }}
    h2 {{
        font-weight: 700 !important;
        border-bottom: 2px solid var(--border-color);
        padding-bottom: 8px;
        margin-top: 1.5rem !important;
    }}
    h3 {{ font-weight: 600 !important; }}

    /* ===== 分割线 ===== */
    hr {{
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, var(--border-color), transparent);
        margin: 1.5rem 0;
    }}

    /* ===== Tab ===== */
    .stTabs [data-baseweb="tab-list"] {{
        background: var(--tab-bg);
        border-radius: 10px;
        padding: 4px;
        gap: 4px;
        border: 1px solid var(--border-color);
    }}
    .stTabs [data-baseweb="tab"] {{ background: transparent; border-radius: 8px; color: var(--text-secondary); }}
    .stTabs [aria-selected="true"] {{
        background: linear-gradient(135deg, #ff6b35 0%, #e55a28 100%) !important;
        color: #fff !important;
    }}
    .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none; }}

    /* ===== 表格 ===== */
    .stDataFrame {{ border-radius: 10px; overflow: hidden; border: 1px solid var(--border-color); }}
    [data-testid="stDataFrame"] thead tr th {{
        background: var(--table-header-bg) !important;
        color: var(--table-header-color) !important;
        font-weight: 600 !important;
        border-bottom: 2px solid var(--accent) !important;
    }}
    [data-testid="stDataFrame"] tbody tr:hover {{ background: var(--table-row-hover) !important; }}

    /* ===== 输入框 ===== */
    .stTextInput input, .stNumberInput input, .stTextArea textarea {{
        background: var(--input-bg) !important;
        border-color: var(--input-border) !important;
        color: var(--text-primary) !important;
    }}

    /* ===== 通用组件类 ===== */
    .dash-card, .scan-result-card, .position-card {{
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 10px;
        box-shadow: var(--shadow);
    }}
    .dash-card:hover, .scan-result-card:hover, .position-card:hover {{
        border-color: var(--accent);
        box-shadow: var(--shadow-hover);
    }}
    .dash-card-header {{ color: var(--text-secondary); font-size: 0.82em; }}
    .dash-card-value {{ color: var(--text-primary); font-size: 1.1em; font-weight: 700; }}
    .dash-card-sub {{ color: var(--text-secondary); font-size: 0.85em; }}
    .position-metric {{ text-align: center; }}
    .position-metric-label {{ color: var(--text-secondary); font-size: 0.78em; }}
    .position-metric-value {{ color: var(--text-primary); font-weight: 600; }}

    /* ===== 标签徽章 ===== */
    .tag {{ display: inline-block; padding: 2px 10px; border-radius: 6px; font-size: 0.82em; font-weight: 600; }}
    .tag-up {{ background: var(--up-bg); color: var(--up-color); }}
    .tag-down {{ background: var(--down-bg); color: var(--down-color); }}
    .tag-accent {{ background: var(--accent-soft); color: var(--accent); }}
    .tag-info {{ background: color-mix(in srgb, var(--info-color) 15%, transparent); color: var(--info-color); }}

    /* ===== 状态指示 ===== */
    .status-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
    .status-dot-on {{ background: var(--down-color); animation: pulse 2s infinite; }}
    .status-dot-off {{ background: var(--up-color); }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.5}} }}

    /* ===== 提示框 ===== */
    .info-box {{ background: color-mix(in srgb, var(--info-color) 8%, var(--bg-card)); border-left: 3px solid var(--info-color); border-radius: 6px; padding: 10px 14px; margin: 8px 0; color: var(--text-primary); }}
    .warn-box {{ background: color-mix(in srgb, var(--warning-color) 8%, var(--bg-card)); border-left: 3px solid var(--warning-color); border-radius: 6px; padding: 10px 14px; margin: 8px 0; color: var(--text-primary); }}
    .empty-box {{ background: var(--bg-card); border: 1px dashed var(--border-color); border-radius: 10px; padding: 24px; text-align: center; color: var(--text-muted); }}

    /* ===== 价格色 ===== */
    .price-up {{ color: var(--up-color); font-weight: 600; }}
    .price-down {{ color: var(--down-color); font-weight: 600; }}
    .price-flat {{ color: var(--text-muted); }}

    /* ===== 滚动条 ===== */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: var(--bg-primary); }}
    ::-webkit-scrollbar-thumb {{ background: var(--border-color); border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--text-muted); }}



    /* ===== 段落间距 ===== */
    .stApp p {{ margin-bottom: 0.5rem; }}
    .stExpander {{ margin-bottom: 0.8rem; }}
    .stExpander div[data-testid="stExpanderDetails"] {{ padding-top: 0.5rem; }}

    {transition_css}
    </style>
    """)


def _get_theme_vars(theme: str) -> list:
    """返回主题色变量列表"""
    if theme == "dark":
        return [
            "--bg-primary: #0b1120",
            "--bg-secondary: #111827",
            "--bg-card: #182235",
            "--bg-card-hover: #1e2a40",
            "--border-color: #253349",
            "--border-glow: #ff6b3540",
            "--text-primary: #e8edf5",
            "--text-secondary: #b0c0d4",
            "--text-muted: #7a8aa0",
            "--accent: #ff6b35",
            "--accent-soft: #ff6b3518",
            "--up-color: #ff4757",
            "--down-color: #2ed573",
            "--up-bg: #ff475715",
            "--down-bg: #2ed57315",
            "--warning-color: #ffa502",
            "--info-color: #45aaf2",
            "--sidebar-bg: #0d1528",
            "--sidebar-border: #1a2740",
            "--table-header-bg: #182235",
            "--table-header-color: #ff6b35",
            "--table-row-hover: #1e2a40",
            "--input-bg: #182235",
            "--input-border: #2a3d55",
            "--tab-bg: #111827",
            "--shadow: 0 1px 3px rgba(0,0,0,0.35)",
            "--shadow-hover: 0 4px 14px rgba(0,0,0,0.45)",
        ]
    else:
        return [
            "--bg-primary: #f4f5f9",
            "--bg-secondary: #ffffff",
            "--bg-card: #ffffff",
            "--bg-card-hover: #ebedf2",
            "--border-color: #d0d7e5",
            "--border-glow: #ff6b3525",
            "--text-primary: #141b29",
            "--text-secondary: #2a3f5f",
            "--text-muted: #5a6e8a",
            "--accent: #ff6b35",
            "--accent-soft: #ff6b3515",
            "--up-color: #dc2626",
            "--down-color: #16a34a",
            "--up-bg: #dc262612",
            "--down-bg: #16a34a12",
            "--warning-color: #d97706",
            "--info-color: #2563eb",
            "--sidebar-bg: #ebedf2",
            "--sidebar-border: #d0d7e5",
            "--table-header-bg: #ebedf2",
            "--table-header-color: #ff6b35",
            "--table-row-hover: #f4f5f9",
            "--input-bg: #ffffff",
            "--input-border: #c4cbd8",
            "--tab-bg: #ebedf2",
            "--shadow: 0 1px 3px rgba(0,0,0,0.07)",
            "--shadow-hover: 0 4px 14px rgba(0,0,0,0.10)",
        ]


def render_theme_toggle():
    """在标题栏右侧渲染极简主题切换（三态：跟随系统 / 浅色 / 深色）"""
    pref = st.session_state.get("theme_pref", "auto")
    
    icon_map = {"auto": "\U0001f504", "light": "\u2600\ufe0f", "dark": "\U0001f319"}
    next_map = {"auto": "light", "light": "dark", "dark": "auto"}
    
    icon = icon_map.get(pref, "\U0001f504")
    next_pref = next_map[pref]
    
    _title_map = {"auto": "跟随系统", "light": "浅色", "dark": "深色"}
    _title = _title_map.get(pref, "跟随系统")
    
    st.html(f"""<div style="position:fixed;top:16px;right:20px;z-index:999;">
    <a href="?theme={next_pref}" style="text-decoration:none;font-size:1em;cursor:pointer;
    color:var(--text-muted);opacity:0.55;padding:6px 8px;border-radius:6px;
    transition:all 0.2s ease;display:inline-block;line-height:1;"
    title="{_title}（点击切换）"
    onmouseover="this.style.opacity='1';this.style.background='var(--accent-soft)';this.style.color='var(--accent)'"
    onmouseout="this.style.opacity='0.55';this.style.background='transparent';this.style.color='var(--text-muted)'"
    >{icon}</a></div>""")
    
    # 检测 URL 参数触发切换
    params = st.query_params
    tp = params.get("theme", "")
    if tp in ("light", "dark", "auto"):
        prev = st.session_state.get("theme_pref", "auto")
        if tp != prev:
            st.session_state["theme_pref"] = tp
            params.pop("theme", None)
            st.rerun()


def render_page_header(title: str, subtitle: str = ""):
    """渲染统一的页面标题"""
    st.html(f"""
    <div style="padding: 8px 0 20px 0;">
        <h1 style="margin:0; font-size:2em; line-height:1.1;">{title}</h1>
        {"<p style='margin:6px 0 0 0; color:var(--text-secondary); font-size:0.88em;'>" + subtitle + "</p>" if subtitle else ""}
    </div>
    """)


def render_metric_card(header: str, value: str, sub: str = "", color: str = "", border_color: str = ""):
    """渲染自定义指标卡片"""
    if not color:
        color = "var(--text-primary)"
    border_style = f"border-left:3px solid {border_color};" if border_color else ""
    return f"""
    <div class="dash-card" style="text-align:center; {border_style}">
        <div class="dash-card-header">{header}</div>
        <div class="dash-card-value" style="color:{color};">{value}</div>
        {"<div class='dash-card-sub'>" + sub + "</div>" if sub else ""}
    </div>
    """


def render_signal_card(code: str, name: str, price: str, signal_type: str = "", tags: str = "", border_color: str = "#ff6b35"):
    """渲染信号卡片"""
    return f"""
    <div class="scan-result-card" style="border-left:4px solid {border_color};">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-weight:700; color:var(--text-primary);">{code}</span>
                <span style="color:var(--text-secondary); margin-left:8px;">{name}</span>
                <span style="color:var(--accent); margin-left:12px; font-weight:600;">¥{price}</span>
            </div>
            <div>
                {"<span class='tag tag-accent'>" + signal_type + "</span>" if signal_type else ""}
                {"<span style='color:var(--text-secondary); font-size:0.85em;'>" + tags + "</span>" if tags else ""}
            </div>
        </div>
    </div>
    """


def render_status_badge(running: bool, text_on: str = "运行中", text_off: str = "已停止"):
    """渲染状态指示徽章"""
    if running:
        return f"""
        <div style="background:var(--down-bg); border:1px solid color-mix(in srgb, var(--down-color) 25%, transparent); border-radius:10px; padding:10px 14px;">
            <span class="status-dot status-dot-on"></span>
            <span style="color:var(--down-color); font-weight:600;">{text_on}</span>
        </div>
        """
    else:
        return f"""
        <div style="background:var(--up-bg); border:1px solid color-mix(in srgb, var(--up-color) 20%, transparent); border-radius:10px; padding:10px 14px;">
            <span class="status-dot status-dot-off"></span>
            <span style="color:var(--up-color); font-weight:600;">{text_off}</span>
        </div>
        """
