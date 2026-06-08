"""共享 UI 样式模块 — 所有页面统一导入（含双主题 + 切换按钮）"""
import streamlit as st

# ===== 完整双主题 CSS（用 data-theme 属性控制） =====
GLOBAL_CSS = """
<style>
    /* ========== 浅色主题（默认） ========== */
    :root, :root[data-theme="light"] {
        --bg-primary: #f8f9fb;
        --bg-secondary: #ffffff;
        --bg-card: #ffffff;
        --bg-card-hover: #f0f2f5;
        --border-color: #d0d7e2;
        --border-glow: #ff6b3520;
        --text-primary: #0f1419;
        --text-secondary: #1a365d;
        --text-muted: #42526b;
        --accent: #ff6b35;
        --accent-soft: #ff6b3515;
        --up-color: #dc2626;
        --down-color: #16a34a;
        --up-bg: #dc262610;
        --down-bg: #16a34a10;
        --warning-color: #d97706;
        --info-color: #2563eb;
        --sidebar-bg: #f1f3f5;
        --sidebar-border: #d0d7e2;
        --table-header-bg: #f1f3f5;
        --table-header-color: #ff6b35;
        --table-row-hover: #f8f9fb;
        --input-bg: #ffffff;
        --input-border: #c4cad5;
        --tab-bg: #f1f3f5;
        --shadow: 0 1px 3px rgba(0,0,0,0.08);
        --shadow-hover: 0 4px 12px rgba(0,0,0,0.1);
    }

    /* ========== 深色主题 ========== */
    :root[data-theme="dark"] {
        --bg-primary: #0a0e17;
        --bg-secondary: #111827;
        --bg-card: #1a2332;
        --bg-card-hover: #1f2b3d;
        --border-color: #2a3a4e;
        --border-glow: #ff6b3540;
        --text-primary: #f0f4f8;
        --text-secondary: #c8d0dc;
        --text-muted: #8892a4;
        --up-color: #ff4b4b;
        --down-color: #00c853;
        --up-bg: #ff4b4b15;
        --down-bg: #00c85315;
        --warning-color: #ffab40;
        --info-color: #42a5f5;
        --sidebar-bg: #0d1320;
        --sidebar-border: #1e2d40;
        --table-header-bg: #1a2332;
        --table-header-color: #ff6b35;
        --table-row-hover: #1f2b3d;
        --input-bg: #1a2332;
        --input-border: #3a4e66;
        --tab-bg: #111827;
        --shadow: 0 1px 3px rgba(0,0,0,0.3);
        --shadow-hover: 0 4px 12px rgba(0,0,0,0.4);
    }

    /* ========== 全局背景 ========== */
    .stApp {
        background: var(--bg-primary);
        color: var(--text-primary);
    }
    [data-testid="stHeader"] { background: transparent !important; }

    /* ========== 侧边栏 ========== */
    [data-testid="stSidebar"] {
        background: var(--sidebar-bg);
        border-right: 1px solid var(--sidebar-border);
    }
    [data-testid="stSidebar"] [data-testid="stMarkdown"] { color: var(--text-secondary); }
    [data-testid="stSidebar"] .stButton button {
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        color: var(--text-primary);
        transition: all 0.2s ease;
    }
    [data-testid="stSidebar"] .stButton button:hover {
        border-color: var(--accent);
        box-shadow: 0 0 12px var(--border-glow);
    }

    /* ========== 覆盖 Streamlit 内置主题变量 ========== */
    :root {
        --st-text-color: var(--text-primary) !important;
        --st-text-secondary-color: var(--text-secondary) !important;
        --st-text-tertiary-color: var(--text-muted) !important;
        --st-background-color: var(--bg-primary) !important;
        --st-secondary-background-color: var(--sidebar-bg) !important;
    }
    /* Streamlit 1.58 侧边栏导航字体 */
    [data-testid="stSidebarNav"] {
        color: var(--text-primary) !important;
    }
    [data-testid="stSidebarNav"] * {
        color: var(--text-primary);
    }

    /* ========== Streamlit 表单控件文字色 ========== */
    .stCheckbox label,
    .stRadio label,
    .stToggle label,
    .stCheckbox label p,
    .stRadio label p,
    [data-testid="stCheckbox"] label,
    [data-testid="stCheckbox"] label p,
    [data-testid="stRadio"] label,
    [data-testid="stRadio"] label p {
        color: var(--text-primary) !important;
    }
    .stCheckbox label:hover,
    .stRadio label:hover {
        color: var(--accent) !important;
    }
    /* Expander 标题 */
    .stExpander summary p,
    .stExpander summary div,
    .stExpander summary span,
    [data-testid="stExpander"] summary p,
    details[open] summary p {
        color: var(--text-primary) !important;
    }
    /* caption 用 muted 色 */
    .stCaption,
    [data-testid="stCaption"],
    [data-testid="stCaption"] p {
        color: var(--text-muted) !important;
    }
    /* 全局强制文字色跟随主题（覆盖 Streamlit 内置主题） */
    .stApp, .stApp *:not(svg):not(path):not(strong):not(b) {
        color: var(--text-primary);
    }
    /* 恢复需要特殊颜色的元素 */
    .stApp a { color: var(--accent); }
    .stApp code { color: var(--text-secondary); }

    /* ========== A股配色 ========== */
    [data-testid="stMetricDelta"] [data-testid="stMetricDeltaIcon-Up"] svg { color: var(--up-color) !important; }
    [data-testid="stMetricDelta"] [data-testid="stMetricDeltaIcon-Down"] svg { color: var(--down-color) !important; }
    [data-testid="stMetricDelta"] div[data-testid="stMetricDeltaIcon-Up"] + span { color: var(--up-color) !important; }
    [data-testid="stMetricDelta"] div[data-testid="stMetricDeltaIcon-Down"] + span { color: var(--down-color) !important; }

    /* ========== Metric 卡片 ========== */
    [data-testid="stMetric"] {
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 10px;
        padding: 12px 16px;
        box-shadow: var(--shadow);
    }
    [data-testid="stMetric"]:hover { border-color: var(--accent); box-shadow: var(--shadow-hover); }
    [data-testid="stMetric"] label { color: var(--text-secondary) !important; font-size: 0.78em !important; }
    [data-testid="stMetric"] [data-testid="stMetricValue"] { color: var(--text-primary) !important; font-weight: 700 !important; }

    /* ========== 标题 ========== */
    h1, h2, h3 {
        color: var(--text-primary) !important;
    }
    h1 {
        background: linear-gradient(135deg, #ff6b35 0%, #ff8f60 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800 !important;
    }
    h2 {
        font-weight: 700 !important;
        border-bottom: 2px solid var(--border-color);
        padding-bottom: 8px;
        margin-top: 1.5rem !important;
    }
    h3 { font-weight: 600 !important; }

    /* ========== 分割线 ========== */
    hr {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, var(--border-color), transparent);
        margin: 1.5rem 0;
    }

    /* ========== Tab ========== */
    .stTabs [data-baseweb="tab-list"] {
        background: var(--tab-bg);
        border-radius: 10px;
        padding: 4px;
        gap: 4px;
        border: 1px solid var(--border-color);
    }
    .stTabs [data-baseweb="tab"] { background: transparent; border-radius: 8px; color: var(--text-secondary); }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #ff6b35 0%, #e55a28 100%) !important;
        color: #fff !important;
    }
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] { display: none; }

    /* ========== 表格 ========== */
    .stDataFrame { border-radius: 10px; overflow: hidden; border: 1px solid var(--border-color); }
    [data-testid="stDataFrame"] thead tr th {
        background: var(--table-header-bg) !important;
        color: var(--table-header-color) !important;
        font-weight: 600 !important;
        border-bottom: 2px solid var(--accent) !important;
    }
    [data-testid="stDataFrame"] tbody tr:hover { background: var(--table-row-hover) !important; }

    /* ========== 输入框 ========== */
    .stTextInput input, .stNumberInput input, .stTextArea textarea {
        background: var(--input-bg) !important;
        border-color: var(--input-border) !important;
        color: var(--text-primary) !important;
    }

    /* ========== 通用卡片 ========== */
    .dash-card { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px; box-shadow: var(--shadow); }
    .dash-card-header { color: var(--text-secondary); font-size: 0.82em; }
    .dash-card-value { color: var(--text-primary); font-size: 1.1em; font-weight: 700; }
    .dash-card-sub { color: var(--text-secondary); font-size: 0.85em; }

    /* ========== 扫描/持仓卡片 ========== */
    .scan-result-card, .position-card {
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 10px;
        box-shadow: var(--shadow);
    }
    .scan-result-card:hover, .position-card:hover { border-color: var(--accent); box-shadow: var(--shadow-hover); }
    .position-metric { text-align: center; }
    .position-metric-label { color: var(--text-secondary); font-size: 0.78em; }
    .position-metric-value { color: var(--text-primary); font-weight: 600; }

    /* ========== 标签 ========== */
    .tag { display: inline-block; padding: 2px 10px; border-radius: 6px; font-size: 0.82em; font-weight: 600; }
    .tag-up { background: var(--up-bg); color: var(--up-color); }
    .tag-down { background: var(--down-bg); color: var(--down-color); }
    .tag-accent { background: var(--accent-soft); color: var(--accent); }
    .tag-info { background: color-mix(in srgb, var(--info-color) 15%, transparent); color: var(--info-color); }

    /* ========== 状态指示 ========== */
    .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
    .status-dot-on { background: var(--down-color); animation: pulse 2s infinite; }
    .status-dot-off { background: var(--up-color); }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }

    /* ========== 隐藏元素 ========== */
    #MainMenu, footer { visibility: hidden; }
    .stDeployButton { display: none; }
    /* Streamlit 1.58 折叠按钮默认 hover 才显示，强制始终可见 */
    [data-testid="stSidebarCollapseButton"] {
        visibility: visible !important;
    }
    .block-container { padding-top: 1rem; }

    /* ========== 侧边栏导航菜单强制文字色 ========== */
    [data-testid="stSidebarNav"] a,
    [data-testid="stSidebarNav"] span,
    [data-testid="stSidebarNav"] p {
        color: var(--text-primary) !important;
    }
    [data-testid="stSidebarNav"] a:hover,
    [data-testid="stSidebarNav"] a:focus {
        color: var(--accent) !important;
    }
    /* 侧边栏通用文字 */
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span:not([role="img"]) {
        color: var(--text-primary);
    }
    /* 侧边栏次级/辅助文字 */
    [data-testid="stSidebar"] .stCaption,
    [data-testid="stSidebar"] small,
    [data-testid="stSidebar"] p[data-testid="stMarkdownCaptionText"] {
        color: var(--text-muted) !important;
    }
    /* 侧边栏粗体 */
    [data-testid="stSidebar"] strong {
        color: var(--text-primary);
    }

    /* ========== 滚动条 ========== */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: var(--bg-primary); }
    ::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

    /* ========== 背景渐变 ========== */
    :root .stApp, :root[data-theme="light"] .stApp { 
        background: linear-gradient(180deg, #f8f9fb 0%, #eef1f5 100%); 
    }
    :root[data-theme="dark"] .stApp { 
        background: linear-gradient(180deg, #0a0e17 0%, #111827 100%); 
    }
    :root[data-theme="light"] [data-testid="stSidebar"] { 
        background: linear-gradient(180deg, #f1f3f5 0%, #e8ecf0 100%); 
    }
    :root[data-theme="dark"] [data-testid="stSidebar"] { 
        background: linear-gradient(180deg, #0d1320 0%, #111827 100%); 
    }
</style>
"""


def _detect_system_theme() -> str:
    """检测系统明暗模式偏好
    
    优先级：
    1. session_state 中的手动选择（theme_pref != auto）
    2. URL query param system_theme（JS 回传）
    3. macOS 系统设置（subprocess 检测）
    4. 默认 light
    """
    pref = st.session_state.get("theme_pref", "auto")
    
    # 手动选择的优先
    if pref in ("light", "dark"):
        return pref
    
    # auto 模式：依次尝试检测
    # 1. JS 通过 query params 回传的值（最准确，反映浏览器端系统偏好）
    params = st.query_params
    sys_theme = params.get("system_theme")
    if sys_theme in ("light", "dark"):
        return sys_theme
    
    # 2. macOS 系统检测（后端检测）
    try:
        import subprocess
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and "Dark" in result.stdout:
            return "dark"
    except Exception:
        pass
    
    return "light"


def _inject_system_theme_detector():
    """注入 JS 检测系统主题偏好，通过 query params 回传给 Python
    
    只在 auto 模式下且 query params 中没有 system_theme 时执行。
    JS 检测到系统主题变化时自动刷新页面。
    """
    params = st.query_params
    if params.get("system_theme") in ("light", "dark"):
        return  # 已经有值了，不需要再检测
    
    st.html("""
    <script>
    (function() {
        const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const theme = dark ? 'dark' : 'light';
        const url = new URL(window.location);
        url.searchParams.set('system_theme', theme);
        // 用 replace 避免产生历史记录
        window.location.replace(url.toString());
    })();
    </script>
    """)


def inject_global_css():
    """注入全局 CSS 样式（根据 session_state 选择主题变量，支持跟随系统）"""
    # 主题优先级：手动选择 > 跟随系统
    theme_pref = st.session_state.get("theme_pref", "auto")  # auto / light / dark
    if theme_pref == "auto":
        # 跟随系统：检测系统主题偏好
        _inject_system_theme_detector()
        theme = _detect_system_theme()
        st.session_state["theme"] = theme
    else:
        theme = theme_pref
        st.session_state["theme"] = theme
    if theme == "dark":
        css_vars = """
        --bg-primary: #0a0e17;
        --bg-secondary: #111827;
        --bg-card: #1a2332;
        --bg-card-hover: #1f2b3d;
        --border-color: #2a3a4e;
        --border-glow: #ff6b3540;
        --text-primary: #f0f4f8;
        --text-secondary: #c8d0dc;
        --text-muted: #8892a4;
        --accent: #ff6b35;
        --accent-soft: #ff6b3515;
        --up-color: #ff4b4b;
        --down-color: #00c853;
        --up-bg: #ff4b4b15;
        --down-bg: #00c85315;
        --warning-color: #ffab40;
        --info-color: #42a5f5;
        --sidebar-bg: #0d1320;
        --sidebar-border: #1e2d40;
        --table-header-bg: #1a2332;
        --table-header-color: #ff6b35;
        --table-row-hover: #1f2b3d;
        --input-bg: #1a2332;
        --input-border: #3a4e66;
        --tab-bg: #111827;
        --shadow: 0 1px 3px rgba(0,0,0,0.3);
        --shadow-hover: 0 4px 12px rgba(0,0,0,0.4);
        """
        bg_gradient = "linear-gradient(180deg, #0a0e17 0%, #111827 100%)"
        sidebar_gradient = "linear-gradient(180deg, #0d1320 0%, #111827 100%)"
    else:
        css_vars = """
        --bg-primary: #f8f9fb;
        --bg-secondary: #ffffff;
        --bg-card: #ffffff;
        --bg-card-hover: #f0f2f5;
        --border-color: #d0d7e2;
        --border-glow: #ff6b3520;
        --text-primary: #0f1419;
        --text-secondary: #1a365d;
        --text-muted: #42526b;
        --accent: #ff6b35;
        --accent-soft: #ff6b3515;
        --up-color: #dc2626;
        --down-color: #16a34a;
        --up-bg: #dc262610;
        --down-bg: #16a34a10;
        --warning-color: #d97706;
        --info-color: #2563eb;
        --sidebar-bg: #f1f3f5;
        --sidebar-border: #d0d7e2;
        --table-header-bg: #f1f3f5;
        --table-header-color: #ff6b35;
        --table-row-hover: #f8f9fb;
        --input-bg: #ffffff;
        --input-border: #c4cad5;
        --tab-bg: #f1f3f5;
        --shadow: 0 1px 3px rgba(0,0,0,0.08);
        --shadow-hover: 0 4px 12px rgba(0,0,0,0.1);
        """
        bg_gradient = "linear-gradient(180deg, #f8f9fb 0%, #eef1f5 100%)"
        sidebar_gradient = "linear-gradient(180deg, #f1f3f5 0%, #e8ecf0 100%)"
    
    # 注入主题 CSS
    themed_css = GLOBAL_CSS.replace(
        "/* ========== 浅色主题（默认） ========== */\n    :root, :root[data-theme=\"light\"] {",
        f":root {{"
    ).replace(
        "    /* ========== 深色主题 ========== */\n    :root[data-theme=\"dark\"] {",
        "    /* dark theme vars removed - using Python injection */\n    .unused {"
    )
    # 直接注入带变量的 CSS
    final_css = f"""
    <style>
    :root {{
        {css_vars}
    }}
    /* ========== 全局背景 ========== */
    .stApp {{
        background: var(--bg-primary);
        color: var(--text-primary);
    }}
    [data-testid="stHeader"] {{ background: transparent !important; }}
    /* ========== 侧边栏 ========== */
    [data-testid="stSidebar"] {{
        background: var(--sidebar-bg);
        border-right: 1px solid var(--sidebar-border);
    }}
    [data-testid="stSidebar"] [data-testid="stMarkdown"] {{ color: var(--text-secondary); }}
    [data-testid="stSidebar"] .stButton button {{
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        color: var(--text-primary);
        transition: all 0.2s ease;
    }}
    [data-testid="stSidebar"] .stButton button:hover {{
        border-color: var(--accent);
        box-shadow: 0 0 12px var(--border-glow);
    }}

    /* ========== 覆盖 Streamlit 内置主题变量 ========== */
    :root {{
        --st-text-color: var(--text-primary) !important;
        --st-text-secondary-color: var(--text-secondary) !important;
        --st-text-tertiary-color: var(--text-muted) !important;
        --st-background-color: var(--bg-primary) !important;
        --st-secondary-background-color: var(--sidebar-bg) !important;
    }}
    /* Streamlit 1.58 侧边栏导航字体 */
    [data-testid="stSidebarNav"] {{
        color: var(--text-primary) !important;
    }}
    [data-testid="stSidebarNav"] * {{
        color: var(--text-primary);
    }}

    /* ========== Streamlit 表单控件文字色 ========== */
    .stCheckbox label,
    .stRadio label,
    .stToggle label,
    .stCheckbox label p,
    .stRadio label p,
    [data-testid="stCheckbox"] label,
    [data-testid="stCheckbox"] label p,
    [data-testid="stRadio"] label,
    [data-testid="stRadio"] label p {{
        color: var(--text-primary) !important;
    }}
    .stCheckbox label:hover,
    .stRadio label:hover {{
        color: var(--accent) !important;
    }}
    /* Expander 标题 */
    .stExpander summary p,
    .stExpander summary div,
    .stExpander summary span,
    [data-testid="stExpander"] summary p,
    details[open] summary p {{
        color: var(--text-primary) !important;
    }}
    /* caption 用 muted 色 */
    .stCaption,
    [data-testid="stCaption"],
    [data-testid="stCaption"] p {{
        color: var(--text-muted) !important;
    }}
    /* 全局强制文字色跟随主题（覆盖 Streamlit 内置主题） */
    .stApp, .stApp *:not(svg):not(path):not(strong):not(b) {{
        color: var(--text-primary);
    }}
    /* 恢复需要特殊颜色的元素 */
    .stApp a {{ color: var(--accent); }}
    .stApp code {{ color: var(--text-secondary); }}

    /* ========== A股配色 ========== */
    [data-testid="stMetricDelta"] [data-testid="stMetricDeltaIcon-Up"] svg {{ color: var(--up-color) !important; }}
    [data-testid="stMetricDelta"] [data-testid="stMetricDeltaIcon-Down"] svg {{ color: var(--down-color) !important; }}
    [data-testid="stMetricDelta"] div[data-testid="stMetricDeltaIcon-Up"] + span {{ color: var(--up-color) !important; }}
    [data-testid="stMetricDelta"] div[data-testid="stMetricDeltaIcon-Down"] + span {{ color: var(--down-color) !important; }}
    /* ========== Metric 卡片 ========== */
    [data-testid="stMetric"] {{
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 10px;
        padding: 12px 16px;
        box-shadow: var(--shadow);
    }}
    [data-testid="stMetric"]:hover {{ border-color: var(--accent); box-shadow: var(--shadow-hover); }}
    [data-testid="stMetric"] label {{ color: var(--text-secondary) !important; font-size: 0.78em !important; }}
    [data-testid="stMetric"] [data-testid="stMetricValue"] {{ color: var(--text-primary) !important; font-weight: 700 !important; }}
    /* ========== 标题 ========== */
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
    /* ========== 分割线 ========== */
    hr {{
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, var(--border-color), transparent);
        margin: 1.5rem 0;
    }}
    /* ========== Tab ========== */
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
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] {{ display: none; }}
    /* ========== 表格 ========== */
    .stDataFrame {{ border-radius: 10px; overflow: hidden; border: 1px solid var(--border-color); }}
    [data-testid="stDataFrame"] thead tr th {{
        background: var(--table-header-bg) !important;
        color: var(--table-header-color) !important;
        font-weight: 600 !important;
        border-bottom: 2px solid var(--accent) !important;
    }}
    [data-testid="stDataFrame"] tbody tr:hover {{ background: var(--table-row-hover) !important; }}
    /* ========== 输入框 ========== */
    .stTextInput input, .stNumberInput input, .stTextArea textarea {{
        background: var(--input-bg) !important;
        border-color: var(--input-border) !important;
        color: var(--text-primary) !important;
    }}
    /* ========== 通用卡片 ========== */
    .dash-card {{ background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px; box-shadow: var(--shadow); }}
    .dash-card-header {{ color: var(--text-secondary); font-size: 0.82em; }}
    .dash-card-value {{ color: var(--text-primary); font-size: 1.1em; font-weight: 700; }}
    .dash-card-sub {{ color: var(--text-secondary); font-size: 0.85em; }}
    /* ========== 扫描/持仓卡片 ========== */
    .scan-result-card, .position-card {{
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 10px;
        box-shadow: var(--shadow);
    }}
    .scan-result-card:hover, .position-card:hover {{ border-color: var(--accent); box-shadow: var(--shadow-hover); }}
    .position-metric {{ text-align: center; }}
    .position-metric-label {{ color: var(--text-secondary); font-size: 0.78em; }}
    .position-metric-value {{ color: var(--text-primary); font-weight: 600; }}
    /* ========== 标签 ========== */
    .tag {{ display: inline-block; padding: 2px 10px; border-radius: 6px; font-size: 0.82em; font-weight: 600; }}
    .tag-up {{ background: var(--up-bg); color: var(--up-color); }}
    .tag-down {{ background: var(--down-bg); color: var(--down-color); }}
    .tag-accent {{ background: var(--accent-soft); color: var(--accent); }}
    .tag-info {{ background: color-mix(in srgb, var(--info-color) 15%, transparent); color: var(--info-color); }}
    /* ========== 状态指示 ========== */
    .status-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
    .status-dot-on {{ background: var(--down-color); animation: pulse 2s infinite; }}
    .status-dot-off {{ background: var(--up-color); }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.5}} }}
    /* ========== 隐藏元素 ========== */
    #MainMenu, footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none; }}
    /* Streamlit 1.58 折叠按钮默认 hover 才显示，强制始终可见 */
    [data-testid="stSidebarCollapseButton"] {{
        visibility: visible !important;
    }}
    .block-container {{ padding-top: 1rem; }}

    /* ========== 侧边栏导航菜单强制文字色 ========== */
    [data-testid="stSidebarNav"] a,
    [data-testid="stSidebarNav"] span,
    [data-testid="stSidebarNav"] p {{
        color: var(--text-primary) !important;
    }}
    [data-testid="stSidebarNav"] a:hover,
    [data-testid="stSidebarNav"] a:focus {{
        color: var(--accent) !important;
    }}
    /* 侧边栏通用文字 */
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span:not([role="img"]) {{
        color: var(--text-primary);
    }}
    /* 侧边栏次级/辅助文字 */
    [data-testid="stSidebar"] .stCaption,
    [data-testid="stSidebar"] small,
    [data-testid="stSidebar"] p[data-testid="stMarkdownCaptionText"] {{
        color: var(--text-muted) !important;
    }}
    /* 侧边栏粗体用 secondary 强调 */
    [data-testid="stSidebar"] strong {{
        color: var(--text-primary);
    }}
    /* ========== 滚动条 ========== */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: var(--bg-primary); }}
    ::-webkit-scrollbar-thumb {{ background: var(--border-color); border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--text-muted); }}
    /* ========== 背景渐变 ========== */
    .stApp {{ background: {bg_gradient}; }}
    [data-testid="stSidebar"] {{ background: {sidebar_gradient}; }}
    </style>
    """
    st.html(final_css)


def render_theme_toggle():
    """在右上角渲染主题切换按钮（三态：跟随系统 / 浅色 / 深色）"""
    pref = st.session_state.get("theme_pref", "auto")
    
    # 三态循环：auto → light → dark → auto
    icon_map = {"auto": "🔄", "light": "☀️", "dark": "🌙"}
    label_map = {"auto": "跟随系统", "light": "浅色模式", "dark": "深色模式"}
    next_map = {"auto": "light", "light": "dark", "dark": "auto"}
    
    icon = icon_map.get(pref, "🔄")
    tooltip = f"{label_map.get(pref, '跟随系统')}（点击切换）"
    
    if st.button(icon, key="theme_toggle_btn", help=tooltip, type="secondary"):
        new_pref = next_map[pref]
        st.session_state["theme_pref"] = new_pref
        if new_pref == "auto":
            # auto 模式下清掉手动 theme，让 _sync_system_theme 决定
            st.session_state.pop("theme", None)
        else:
            st.session_state["theme"] = new_pref
        # 清掉 query param 避免残留
        st.query_params.pop("system_theme", None)
        st.rerun()
    
    # 用 JavaScript 精确定位按钮（找到包含主题图标的那个）
    st.html("""
    <script>
    function positionThemeBtn() {
        const buttons = document.querySelectorAll('[data-testid="stButton"] button');
        for (const btn of buttons) {
            const text = btn.textContent.trim();
            if (text === '☀️' || text === '🌙' || text === '🔄') {
                btn.style.position = 'fixed';
                btn.style.top = '12px';
                btn.style.right = '24px';
                btn.style.zIndex = '9999';
                btn.style.width = '42px';
                btn.style.height = '42px';
                btn.style.borderRadius = '50%';
                btn.style.padding = '0';
                btn.style.fontSize = '1.3em';
                btn.style.boxShadow = '0 2px 8px rgba(0,0,0,0.15)';
                btn.style.transition = 'all 0.3s ease';
                btn.onmouseover = function() {
                    this.style.borderColor = '#ff6b35';
                    this.style.boxShadow = '0 0 16px rgba(255,107,53,0.25)';
                    this.style.transform = 'scale(1.1)';
                };
                btn.onmouseout = function() {
                    this.style.borderColor = '';
                    this.style.boxShadow = '0 2px 8px rgba(0,0,0,0.15)';
                    this.style.transform = '';
                };
                break;
            }
        }
    }
    setTimeout(positionThemeBtn, 100);
    </script>
    """)


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
