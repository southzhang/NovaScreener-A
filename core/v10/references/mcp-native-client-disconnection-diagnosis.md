# MCP Native Client 断连排查

## 场景

调用 `mcp_ifind_stock_*` 等 MCP 工具返回以下错误之一：
- `"error": "MCP server 'ifind-stock' is not connected"`
- `"MCP server 'ifind-stock' is unreachable after 16 consecutive failures. Auto-retry available in ~37s"`

## 故障模式

| 模式 | 错误信息 | 根因 | HTTP直调结果 |
|------|----------|------|-------------|
| A: Native client 断连 | "is not connected" | Hermes 进程内 MCP client 启动时连接失败 | server 可达 |
| **B: 失败缓存（本会话发现）** | "unreachable after N consecutive failures" | MCP client 协议栈缓存了累计失败状态，将工具标记为不可用 | **server 可达，100% 可用** |
| C: Server 真实不可达 | 超时或 HTTP 非 200 | 网络/VPN/服务器宕机 | server 不可达 |
| D: Agent 无工具 | 工具列表中无 `mcp_ifind_*` | `enabled_toolsets` 没包含 MCP 工具（仅 cron agent 上下文） | server 可达 |

### 模式 B 详解（2026-05-22 会话发现）

**现象**：Hermes 客户端工具 `mcp_ifind_stock_get_stock_shareholders` 报错：
```
MCP server 'ifind-stock' is unreachable after 16 consecutive failures.
Auto-retry available in ~37s
```

但使用同配置（相同 URL、相同 Authorization header）的 curl 直接 HTTP POST 调用 JSON-RPC 端点，tools/list 和 tools/call 均成功返回。

**根因**：MCP 客户端协议栈（Hermes 进程内）缓存了 16 次连续失败的计数器，将该 server 标记为不可达。即使 server 已恢复健康，该缓存状态不会自动清除，直到超时（~37s）后重试。但 HTTP 直调用绕过了该计数器——每次 curl 新建连接，不受缓存影响。

**与模式 A 的区别**：模式 A 是 server 自始至终未连接成功；模式 B 是早期累计失败导致计数器被打满，后续正常请求也被阻挡。

## 诊断三查

### 1. 查 MCP server 是否可达（HTTP）

```bash
# 测试 HTTP 连通性（JWT token 从 config.yaml 获取）
curl -s -w "\n%{http_code}" \
  -X POST "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp" \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

- HTTP 200 → server 可达，问题在 native client 连接层（模式 A 或 B）
- HTTP 非 200 / 超时 → server 或网络问题（模式 C）

### 2. 查 Hermes native MCP client 状态

```bash
# 查看 agent.log 找 MCP 连接错误
grep -i "mcp.*not connected\|mcp.*error\|mcp.*failed\|consecutive failures\|unreachable" ~/.hermes/logs/agent.log | tail -20
```

### 3. 查进程/配置

```bash
# MCP server 进程（通常无独立进程，运行在 Hermes 进程内）
ps aux | grep -i mcp | grep -v grep

# config.yaml 检查
grep -A5 "ifind-stock" ~/.hermes/config.yaml
```

## 恢复方法

| 方法 | 适用模式 | 效果 | 备注 |
|------|----------|------|------|
| `hermes gateway restart` | A, B | 重启 gateway，重新初始化 MCP client，清除失败缓存 | 模式 B 推荐：重启后 client 从 0 开始重试 |
| 等待自动重连 | B | 被动等待 ~37s | 高峰期可能快些，但不可控 |
| **HTTP 直调用** | A, B, C? | **跳过 client 层，直接调用 server** | 适用于单次查询，不适合高频调用 |
| 在 config.yaml 中调高重试参数（如 connect_timeout/timeout） | A | 减少启动时连接失败 | 如果 server 响应较慢 |

## 绕过方案：HTTP 直调用 MCP server

当 native client 断连或失败缓存阻止时，直接用 curl 或 Python 调 MCP 的 HTTP 端点：

### 获取 tools 列表

```bash
curl -s -X POST "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp" \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq
```

### 调用工具（如 get_stock_shareholders）

```bash
curl -s -X POST "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp" \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/call",
    "params":{
      "name":"get_stock_shareholders",
      "arguments":{"query":"德尔股份 300473 总股本 流通股本 前十大股东 最新"}
    }
  }' | jq
```

### Python requests 示例（适合 execute_code 上下文）

```python
import requests, json

url = "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp"
headers = {"Authorization": "Bearer <JWT>", "Content-Type": "application/json"}

payload = {
    "jsonrpc": "2.0", "id": 1,
    "method": "tools/call",
    "params": {
        "name": "get_stock_performance",
        "arguments": {"query": "三花智控最近5日涨跌幅与换手率"}
    }
}
resp = requests.post(url, headers=headers, json=payload, timeout=30)
result = resp.json()
```

### 注意

- JWT token 从 `~/.hermes/config.yaml` 的 `mcp_servers.ifind-stock.headers.Authorization` 获取（不含 `Bearer` 前缀）
- 某些 server（如 ifind-news）的参数格式与 ifind-stock 不同，news 用结构化顶层参数而非 query 字符串
- 返回值格式是标准 JSON-RPC，`result.content[0].text` 是 JSON 字符串需要二次解析
- 详细 Streamable HTTP 调用示例见 `ifind-mcp-streamable-http-pattern.md`

## 本模式 vs cron-agent-mcp-not-available

| 场景 | 本次（native client 断连/失败缓存） | cron-agent-mcp-not-available |
|------|-------------------------------------|------------------------------|
| 错误信息 | "is not connected" / "unreachable after 16 consecutive failures" | Agent 工具列表无 `mcp_ifind_*` 工具 |
| 根因 | Hermes 进程内 MCP client 连接失败或累计失败计数器 | `enabled_toolsets` 没包含 MCP 工具 |
| HTTP 直调 | server 可达，100% 可用 | server 同样可达 |
| 修复方式 | 重启 gateway / HTTP 直调 | 修改 cron job 的 enabled_toolsets |
