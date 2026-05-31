# iFinD Token 管理

## ⚠️ 核心：两套Token，用途完全不同

iFinD有**两种认证token**，绝不能混用：

| Token | 格式 | 用途 | 有效期 | 获取方式 |
|-------|------|------|--------|----------|
| **JWT Token** | RS256+JWE（`eyJhbGci...`长字符串） | **MCP Gateway认证** | **长期有效**（跟随账号到期日） | iFinD终端 → 工具 → 数据MCP |
| access_token | 简单hash（`ed5f15c...signs_`短字符串） | **HTTP API认证** | 7天 | `get_access_token` 接口 |

### ⛔ 铁律：不要用 `get_access_token` 返回的hash替换MCP config里的JWT！

**2026-05-13事故复盘：**
1. 用 `get_access_token` 接口获取了hash token
2. 把hash替换到 `config.yaml` 的4个MCP server Authorization头
3. 导致全部4个MCP server 401 Unauthorized
4. Gateway日志：`MCP: registered 0 tool(s) from 0 server(s) (4 failed)`

**根因：** MCP gateway要求JWT格式认证，hash token只适用于HTTP API端点（quantapi.51ifind.com）。两者不互通。

### JWT 有效期观测（2026-05-28 更新）
- **原以为长期有效**，但实践发现 JWT 在 iFinD MCP 环境下约 **3天** 过期
- 观测：05-25 09:02 刷新成功 → 05-28 所有6个log全部401
- **每3天需要从终端重新获取**，所以要保证cron检查频率 ≥ 每3天

## MCP认证（JWT Token）

**当前JWT：** 在 `~/.hermes/config.yaml` → `mcp_servers.ifind-*.headers.Authorization`
- 格式：`eyJhbGciOiJSU0EtT0FFUC0yNTYiLCJlbmMiOiJBMjU2R0NNIn0...`
- 有效期：**长期**（跟随账号到期日，不是7天）
- 何时需要更换：账号到期续费后、权限变更后

## 手动更新JWT流程：
1. iFinD终端 → 工具 → 常用工具 → 数据MCP → 获取token
2. 更新 `~/.hermes/config.yaml` 中4个 `ifind-*` 的Authorization值
3. 执行 `hermes gateway restart`
4. 验证：`hermes mcp test ifind-stock`

### ⚠️ YAML路径踩坑（2026-05-19发现）

用Python脚本更新config.yaml时，易错点：

| ✅ 正确 | ❌ 错误 |
|---------|---------|
| `data["mcp_servers"]` | `data["mcp"]["servers"]`（嵌套key不存在） |

**config.yaml 的 MCP servers 顶层key是 `mcp_servers`**，不是 `mcp.servers`。后者是hermes内部概念，YAML文件中不存在。

**手动替换4个Authorization的Python代码（已验证）：**
```python
import yaml
from pathlib import Path

path = Path.home() / ".hermes" / "config.yaml"
with open(path) as f:
    data = yaml.safe_load(f)

new_token = "eyJhbGciOi..."  # 从iFinD终端获取的新JWT

for key in ["ifind-stock", "ifind-fund", "ifind-edb", "ifind-news"]:
    if key in data.get("mcp_servers", {}):
        data["mcp_servers"][key]["headers"]["Authorization"] = f"Bearer {new_token}"

with open(path, "w") as f:
    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

print("✅ 4个MCP server Authorization已更新")
```

## HTTP API认证（access_token）

**端点：** `POST https://quantapi.51ifind.com/api/v1/get_access_token`

**请求：** `{"refresh_token": "<refresh_token>"}`

**返回：**
```json
{
  "errorcode": 0,
  "data": {
    "access_token": "ed5f15cdde06e5503eeb...",
    "expired_time": "2026-05-20 10:44:36"
  }
}
```

**用途：** 调用 `quantapi.51ifind.com/api/v1/*` 的HTTP API端点
**不用途：** MCP gateway认证（会401）

**封装模块：** `~/.hermes/scripts/ifind_http_api.py`
- 自动管理access_token刷新和缓存（`~/.hermes/scripts/ifind_token_cache.json`）
- 缓存有效期20小时（token本身7天）
- 环境变量 `IFIND_REFRESH_TOKEN` 存储refresh_token
- 用法：`from ifind_http_api import iFinD` → `iFinD.realtime(...)`, `iFinD.high_frequency(...)` 等

**refresh_token获取方式：** iFinD Windows终端 → 超级命令 → 工具 → refresh_token查询
**refresh_token到期：** 2026-06-12（JWT payload的refreshTokenExpiredTime字段）
**到期后：** 需从终端重新获取，更新环境变量

## 凭证信息

- uid: 868754040
- refresh_token到期: 2026-06-12
- MCP JWT配置位置: `~/.hermes/config.yaml` → `mcp_servers.ifind-*.headers.Authorization`
- HTTP API refresh_token: 环境变量 `IFIND_REFRESH_TOKEN`（~/.hermes/.env + ~/.zshrc）

## 健康检查

**脚本：** `~/.hermes/scripts/ifind_refresh_token.py`
- 功能：测试JWT token是否有效（连接MCP获取工具列表）
- 不会修改config（避免误操作）

**Cron定时检查：** `ifind-token-refresh`（job 211fd36abfea）
- 调度: 每3天 09:00（`0 9 */3 * *`）
- 测试MCP连接，JWT失效时提醒用户从终端重新获取
- ⚠️ 2026-05-28实测：JWT约3天过期，cron间隔刚好匹配但偏紧，建议改每2天

**快速检查：**
```bash
hermes mcp test ifind-stock 2>&1 | head -3
# ✅ Connected + Tools discovered: 9 → 正常
# ✗ 401 Unauthorized → JWT失效，需从iFinD终端重新获取
```

## 过期症状

JWT失效后，4个MCP server全部401：
```
tools.mcp_tool: Failed to connect to MCP server 'ifind-stock': 401 Unauthorized
tools.mcp_tool: MCP: registered 0 tool(s) from 0 server(s) (4 failed)
```

## Refresh Token 更新

refresh_token更新后，所有环境的旧token均会失效。
获取新refresh_token: iFinD终端 → 数据MCP → 刷新token查询
