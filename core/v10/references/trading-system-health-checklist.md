# 交易系统健康检查清单

> 吸收自 `trading-system-health-check` skill (2026-05-20 合并归档)。
> 完整诊断流程、脚本和已知陷阱。

## 检查清单（按优先级）

### 1. Cron任务数据源一致性
```bash
python3 -c "
import json
with open('$HOME/.hermes/cron/jobs.json') as f:
    data = json.load(f)
for job in data.get('jobs', []):
    if job.get('enabled'):
        script = job.get('script', '')
        prompt = job.get('prompt', '')
        print(f\"{job['name']}: script={script or 'agent'}\")
"
```
**检查点：**
- 每个任务的数据架构描述（prompt中的数据源层级）是否与实际脚本一致
- 脚本路径是否指向正确版本（workspace/ vs scripts/ 可能有旧版共存）
- `no_agent: true` 的脚本任务引用的.py文件是否存在

### 2. 脚本数据源审计
- **实时行情源**：腾讯(`qt.gtimg.cn`) vs iFinD(`quantapi.51ifind.com`) vs 新浪？
- **K线数据源**：腾讯K线(`web.ifzq.gtimg.cn`) vs iFinD分钟K线?
- **基本面数据源**：iFinD MCP工具 vs iFinD HTTP API?
- **SSL配置**：`ssl.create_default_context()` + `check_hostname=False` 是否必要
- **Token管理**：刷新逻辑、缓存锁、过期处理

### 3. 硬编码陷阱
```bash
# 搜索硬编码日期
grep -n '\[20[0-9]\{6\}\]' ~/.hermes/workspace/v10_*.py
# 搜索 /tmp/ 硬编码路径（重启丢失风险）
grep -rn "'/tmp/" ~/.hermes/scripts/ ~/.hermes/workspace/
# 搜索 cron prompt 中的 /tmp/ 引用
python3 -c "
import json
with open('$HOME/.hermes/cron/jobs.json') as f:
    data = json.load(f)
for j in data.get('jobs', []):
    p = j.get('prompt', '')
    if '/tmp/' in p:
        print(f'{j[\"id\"]}: {j[\"name\"]}')"
```
**常见硬编码：** 板块排名日期、历史K线起始日、持仓列表、`/tmp/` 路径（用 `~/.hermes/cache/` 替代）

### 4. 持仓列表一致性
```bash
# 对比 intraday_holdings_monitor.py 中的持仓
grep -A 20 'HOLDINGS = \[' ~/.hermes/workspace/intraday_holdings_monitor.py
```
Agent驱动的cron任务也需检查：`26daefd24af7`(实盘盯盘) prompt中硬编码 vs `e2172fd4cc89`(复盘) 动态读取 `current_holdings.py`

### 5. 双版本脚本检查
```bash
# 检查同一脚本是否在多处存在
ls -la ~/.hermes/scripts/v10_*.py ~/.hermes/workspace/v10_*.py 2>/dev/null
# 确认cron的script路径指向正确版本
python3 -c "
import json, os
with open('$HOME/.hermes/cron/jobs.json') as f:
    data = json.load(f)
for job in data.get('jobs', []):
    s = job.get('script', '')
    if s and not s.startswith('/'):
        resolved = os.path.expanduser(f'~/.hermes/scripts/{s}')
        workspace = os.path.expanduser(f'~/.hermes/workspace/{s}')
        if os.path.exists(workspace) and os.path.exists(resolved):
            scripts_size = os.path.getsize(resolved)
            workspace_size = os.path.getsize(workspace)
            if scripts_size != workspace_size:
                print(f'⚠️  {job[\"name\"]}: scripts/ ({scripts_size}B) vs workspace/ ({workspace_size}B) 内容不同!')"
```
**铁律：** cron任务脚本推荐用绝对路径（`~/.hermes/workspace/xxx.py`）

### 6. Python编译检查
```bash
cd ~/.hermes/workspace && python3 -c "
import py_compile
for f in ['v10_realtime_scan.py', 'v10_intraday_monitor.py', 'v10_auto_trade.py',
          'tech_analysis.py', 'intraday_holdings_monitor.py']:
    try:
        py_compile.compile(f, doraise=True)
        print(f'✅ {f}')
    except Exception as e:
        print(f'❌ {f}: {e}')"
```

### 7. Hermes版本缓存检查
```bash
git -C ~/.hermes/hermes-agent pull
cat ~/.hermes/.update_check
rm ~/.hermes/.update_check  # 清缓存强制刷新
hermes version
```

### 8. 任务去重检查
```bash
python3 -c "
import json
with open('/Users/southzhang/.hermes/cron/jobs.json') as f:
    data = json.load(f)
active = [j for j in data.get('jobs',[]) if j.get('enabled') and not j.get('paused')]
scripts = [(j['name'], j.get('script','')) for j in active if j.get('script')]
print('启用的脚本任务:')
for name, script in scripts:
    print(f'  {name}: {script}')"
```

### 9. 资金面三维度缓存检查
```bash
python3 -c "
import json, os
from datetime import datetime, timedelta
path = os.path.expanduser('~/.hermes/cache/capital_flow.json')
if not os.path.exists(path):
    print('❌ capital_flow.json 不存在')
else:
    with open(path) as f:
        data = json.load(f)
    dims = data.get('dimensions', {})
    expected = ['capital_flow', 'dark_pool', 'dragon_tiger']
    missing = [d for d in expected if d not in dims]
    if missing:
        print(f'❌ 缺少维度: {missing}')
    else:
        print(f'✅ 三维度完整: {list(dims.keys())}')
        print(f'   更新时间: {data.get(\"last_update\", \"未知\")}')"
```

### 10. Vibe模块完整性检查
```bash
cd ~/.hermes/workspace && python3 -c "
from tech_analysis import vibe_score, compute_technical_score, detect_smc_signals, detect_chanlun_buy_signal
print('✅ tech_analysis.py 所有函数可导入')"
```

## 已知陷阱（实战收集）

### Hermes版本缓存过期
`hermes version` 的"X commits behind"来自 `~/.hermes/.update_check`（6小时过期）。
**修复：** `rm ~/.hermes/.update_check`

### scripts/ vs workspace/ 版本分裂
`v10_intraday_monitor.py` 存在两个版本：
- `~/.hermes/scripts/` (17K)：旧版，纯腾讯行情
- `~/.hermes/workspace/` (22K)：新版，含iFinD集成

当cron设置 `script: v10_realtime_scan.py`（相对路径）→ Hermes解析到 `~/.hermes/scripts/`。**两个同名文件可能功能完全不同。**
**诊断：** `ls -la ~/.hermes/scripts/v10_realtime_scan.py ~/.hermes/workspace/v10_realtime_scan.py`
**修复：** 用绝对路径：`script: ~/.hermes/workspace/v10_realtime_scan.py`

### Cron update的隐坑
更新cron时传新prompt不会清除旧的`script`和`no_agent`。从脚本模式切到agent模式需显式传 `no_agent:false` + `script:""`。

### enabled_toolsets 限缩导致MCP不可用
Agent cron任务如果设了`enabled_toolsets`但不含`mcp`，prompt中引用的MCP工具静默失败。
**铁律：** 实盘盯盘等需要iFinD MCP的任务，`enabled_toolsets`必须包含`mcp`。
**案例：** `26daefd24af7` 曾缺少 `mcp` → prompt中iFinD不可用。

### 盘中盯盘 ≠ 实盘盯盘（不可合并）
V10盘中盯盘（观察池入场信号）和实盘盯盘（持仓风险监控）功能完全不同。
**铁律：** 合并cron前必须确认监控对象和输出是否真的重叠。

### 依赖任务顺序反转
V10全扫描写 `/tmp/v10_watchlist.json`，V10盯盘读该文件。盯盘 `:0/:10/:20/:30/:40/:50` 必须晚于全扫描 `:5/:35`。
**铁律：** 有数据依赖的cron任务，上游早于下游，留≥5分钟间隔。

### Hermes venv 缺少Python依赖
`no_agent: true` 的脚本任务使用 Hermes venv (`~/.hermes/hermes-agent/venv/bin/python3`)。
**系统Python能跑 ≠ Hermes cron能跑。**
**诊断：** `~/.hermes/hermes-agent/venv/bin/python3 -c "import pandas; print('OK')"`
**修复：** `~/.hermes/hermes-agent/venv/bin/python3 -m pip install pandas`
**铁律：** 新加脚本依赖时，必须同时给 Hermes venv 安装该包。

### import os缺失（Python常见坑）
Python脚本新增文件I/O函数时忘记 `import os`。
**铁律：** 给已有Python脚本新增文件I/O函数时，先确认 `import os` 已存在。

### 局部import不传播到外层作用域
函数内 `import x as y` 是局部变量，不会泄漏到调用方或模块顶层。
**快速自检：** `grep -n 'import.*as ' script.py` — 如果别名在函数内定义但在函数外使用，就是这个bug。

### Token缓存线程安全
iFinD token缓存必须加 `threading.Lock`，30线程并发扫描时无锁会导致重复刷新。

### Cron飞书推送失败
agent.log显示"delivered"但用户未收到。根因：scheduler的 `_deliver_result()` 默认 `success=True`。
**排查：** `grep "Job.*delivered\|Job.*delivery error" ~/.hermes/logs/agent.log`
**临时方案：** 在会话中手动输出报告。

### "清仓了"触发确认铁律
**用户说"清仓了"≠空仓**——可能是部分清仓或口头汇报。
**铁律：** 先问再操作，宁可不改不可错改。

### 空仓状态系统配置
当确认用户空仓后：暂停实盘盯盘 `26daefd24af7`、资金面缓存刷新 `b00d3fde7beb`。
保留：V10全扫描、V10盘中盯盘、14:30尾盘选股、竞价选股。

## 原始引用文件归档

本清单吸收自 `trading-system-health-check` skill 的以下引用文件（已归档至 `.archive/`）：
- `2026-05-13-audit.md` — 首次系统审计记录
- `2026-05-13-self-check.md` — 自检脚本和流程
- `2026-05-18-cron-timeline-tuning.md` — Cron时间线调整经验
- `2026-05-18-feishu-truncation-audit.md` — 飞书推送截断审计
- `2026-05-18-venv-pandas-missing.md` — Venv缺少pandas排查
