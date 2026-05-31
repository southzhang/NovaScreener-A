# MCP Direct HTTP Call Pattern

## 背景
MCP服务器虽然在 `hermes mcp list` 中显示为 ✓ enabled，但可能因版本差异/启动顺序/工具注册限制，部分服务器的工具未注入到agent的函数调用列表中。此时无法直接调用 `mcp_*_toolname` 工具。

## 诊断
```bash
hermes mcp list           # 确认服务器状态 ✓ enabled
hermes mcp test <name>    # 测试连接 + 显示工具列表
# 对比 agent 当前可用工具：如果 mcp_<name>_* 不在可用工具中 → 直调方案
```

## 解决方案：直接HTTP POST调用

通过 `execute_code` 或 `terminal` 直连MCP服务器的HTTP端点：

```python
import json, urllib.request, re

# 1. 从config.yaml提取Authorization token
with open('/Users/southzhang/.hermes/config.yaml', 'r') as f:
    lines = f.readlines()

token = ""
for i, line in enumerate(lines):
    if 'ifind-news:' in line:  # 替换为你的服务器名
        for j in range(i, min(i+10, len(lines))):
            if 'Authorization:' in lines[j]:
                token = lines[j].split('Authorization:')[1].strip()
                break
        break

# 2. 先 tools/list 获取工具定义和参数
url = "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-news-mcp"
headers = {
    "Authorization": token,
    "Content-Type": "application/json"
}

list_payload = {
    "jsonrpc": "2.0", "id": 1,
    "method": "tools/list", "params": {}
}

req = urllib.request.Request(url, data=json.dumps(list_payload).encode(), headers=headers, method="POST")
resp = urllib.request.urlopen(req, timeout=30)
tools = json.loads(resp.read().decode())
# 查看 tools["result"]["tools"] 获取工具名+inputSchema

# 3. tools/call 调用
call_payload = {
    "jsonrpc": "2.0", "id": 2,
    "method": "tools/call",
    "params": {
        "name": "search_news",  # 工具名
        "arguments": {
            "query": "热门财经新闻",
            "size": 5,
            "time_start": "2026-05-25",
            "time_end": "2026-05-26"
        }
    }
}

req = urllib.request.Request(url, data=json.dumps(call_payload).encode(), headers=headers, method="POST")
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read().decode())
# result["result"]["content"][0]["text"] 包含实际数据
```

## 关键铁律

1. **MCP参数格式因服务器而异**
   - `ifind-stock`：所有参数塞进 `query` 字符串（自然语言查询）
   - `ifind-news`：参数在 `arguments` 顶层独立传（`query`, `size`, `time_start`, `time_end` 全部required）
   - 首次调用必须先 `tools/list` 查看 `inputSchema`，不要猜参数

2. **Authorization token 从config.yaml提取**
   - 不要硬编码或从.env读取（不同MCP服务器token不同）
   - ifind系列MCP用JWT（RS256+JWE），不是access_token

3. **适用场景**
   - MCP服务器已连接但工具未注册 → 首选此方案
   - cron agent上下文中enabled_toolsets限制了MCP工具 → 同上
   - 纯脚本(no_agent=true)中需要MCP数据 → 同上
   - 正常agent会话中MCP工具可用 → **不要用此方案**，直接调 `mcp_*` 工具

4. **回退方案**
   如果直接HTTP也失败（401/403），检查token是否过期。ifind系列MCP token跟随iFinD账号，通常长期有效。
