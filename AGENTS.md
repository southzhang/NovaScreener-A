# AGENTS.md - Quant Watchdog

## Project
A股量化盯盘选股工具。Python + Streamlit + akshare + SQLite。

## Structure
- `app.py` - Streamlit主入口
- `core/` - 核心逻辑
  - `data.py` - akshare数据获取、缓存
  - `strategies.py` - 选股策略引擎
  - `scanner.py` - 全市场扫描器
  - `alerts.py` - 飞书预警通知
  - `db.py` - SQLite数据库操作
- `pages/` - Streamlit多页面
  - `1_📊_Dashboard.py` - 首页仪表盘
  - `2_🔍_选股扫描.py` - 策略扫描
  - `3_⭐_自选股.py` - 自选股管理
  - `4_⚙️_策略配置.py` - 策略参数编辑
  - `5_🔔_预警设置.py` - 飞书webhook配置
  - `6_📈_回测.py` - 策略回测
- `config.yaml` - 配置文件
- `.env` - 敏感配置（飞书webhook等）
- `requirements.txt`

## Conventions
- Python 3.10+, type hints everywhere
- akshare 函数调用要做异常处理和缓存
- 所有金额用float，百分比用0-100
- 中文注释和docstring
- Streamlit session_state管状态
- SQLite用context manager

## Key Libraries
- akshare: A股数据
- streamlit: Web UI
- plotly: 图表
- pandas: 数据处理
- apscheduler: 定时任务
- requests: HTTP请求（飞书webhook）
- python-dotenv: 环境变量
