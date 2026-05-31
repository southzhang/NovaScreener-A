# Cron Agent任务MCP工具不可用排查记录

## 场景

资金面缓存刷新cron job `b00d3fde7beb`，每30分钟执行一次，SA schedule `*/30 9-15 * * 1-5`。

## 现象

- Agent cron任务报告"数据来自缓存"或"使用回退数据源"
- 实际缓存中数据来自几十分钟前（上一轮有MCP的上下文写入的）
- 但cron job每次执行只能读，不能刷新

## 排查（2026-05-19）

### cron job配置

```json
{
  "id": "b00d3fde7beb",
  "name": "资金流向缓存刷新(V10资本流必须走MCP)",
  "schedule": "*/30 9-15 * * 1-5",
  "prompt": "...调MCP查三只持仓股的三维度数据...写入JSON缓存...",
  "no_agent": false,
  "enabled_toolsets": ["terminal", "file", "skills", "web"]
}
```

### 可用工具集（从session输出确认）

执行时的tools列表：`delegate_task, execute_code, memory, patch, process, read_file, search_files, session_search, skill_manage, skill_view, skills_list, terminal, text_to_speech, todo, vision_analyze, web_extract, web_search, write_file`

**`mcp_ifind_*` 工具完全不在列表中。**

### 根因

`enabled_toolsets` 限制了工具集为 `["terminal", "file", "skills", "web"]`，MCP tools (`ifind-stock`, `ifind-fund`, `ifind-news`, `ifind-edb`) 没有被包含。甚至在 config.yaml 中设置了 `mcp_servers`，但如果没有对应的toolset允许MCP，LLM就收不到MCP工具的签名。

即使 `no_agent: false`（agent模式），没有注册的工具在LLM眼中就不存在。

### 修复方向

**方案A：放宽enabled_toolsets**
```json
{
  "enabled_toolsets": ["terminal", "file", "skills", "web", "ifind-stock", "ifind-fund", "ifind-news", "ifind-edb"]
}
```
或直接不传enabled_toolsets（使用全部默认工具）。

⚠️ 但这种方法可能无效——如果MCP tools的注册依赖于 `mcp_tools` 这个system toolset（而不是独立toolset），无法通过enabled_toolsets选择性启用。需查看hermes-agent源码确认。

**方案B：修改prompt，不依赖MCP**
改为在prompt中让agent用Python脚本通过iFinD HTTP API获取数据：
```
Step 1: python3 -c "import sys; sys.path.insert(0, '~/.hermes/scripts'); from ifind_http_api import iFinD; df = iFinD.realtime(['600936.SH','300912.SZ','300065.SZ'], ['capital_flow']); print(df)"
Step 2: 解析结果写入~/.hermes/cache/capital_flow.json
```

该方案已验证：`get_real_time_quotation` 传入 `["capital_flow"]` 字段返回12个子字段。

## 教训

1. 创建cron job时设定了 `enabled_toolsets` 可能导致关键工具缺失——设之前确认该job到底需要哪些工具
2. MCP工具并非默认在cron上下文中可用，需要显式注册
3. 如果prompt里写"调MCP"，但job运行后agent只读缓存不回传新数据——检查tools列表
4. 诊断最快方法：读cron execution的输出文件看available tools
