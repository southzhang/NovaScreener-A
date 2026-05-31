# iFinD MCP Streamable HTTP 调用模式

## 背景

通过 `mcp.client.streamable_http` SDK 直接调用 iFinD MCP 服务器。该模式用于：
- Agent cron 任务中需要直接查询结构化数据时
- execute_code() 中需要调用 MCP 但不想通过工具调用语法时
- 测试 MCP 工具是否可用时

## 依赖

```bash
pip install mcp httpx
```

## 通用调用模板

```python
import httpx, json, asyncio

MCP_BASE_URL = "https://api-mcp.51ifind.com:8643/ds-mcp-servers"
JWT_TOKEN = "eyJhbGci..."  # 从 config.yaml 的 Authorization 字段获取

async def call_ifind_mcp(server_name: str, tool_name: str, params: dict) -> dict:
    """通用 iFinD MCP Streamable HTTP 调用"""
    url = f"{MCP_BASE_URL}/hexin-ifind-ds-{server_name}-mcp"
    headers = {
        "Authorization": f"Bearer {JWT_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as http_client:
        transport = streamable_http_client(url, http_client, headers=headers)
        async with ClientSession(*transport) as session:
            result = await session.call_tool(tool_name, params)
            return result.content

# 运行
result = asyncio.run(call_ifind_mcp("stock", "get_stock_performance", {
    "query": "浩通科技301026今日涨跌幅和收盘价"
}))
```

## 各 Server 参数格式差异

### ifind-stock — 全部用 `query` 字符串（自然语言）

所有工具（get_stock_performance, get_stock_financials, get_stock_info, get_stock_shareholders, get_risk_indicators, get_esg_data, get_stock_events, get_stock_summary, search_stocks）**全部接受单个 `query` 字符串参数**。

自然语言查询格式：`"股票名/代码 + 想要的数据 + 时间范围"`

```python
# ✅ 有效格式
params = {"query": "浩通科技301026今日收盘价和涨跌幅"}
params = {"query": "风华高科000636最新PE和ROE"}
params = {"query": "三花智控最近5日涨跌幅与换手率"}
params = {"query": "科大讯飞在2025-12-31的ROE、净利润率"}

# 返回值：result.content 是 TextContent/RawResult 列表
# 在 Streamable HTTP 模式下，content 对象有 .text 或 .data 属性
```

### ifind-news — 接受**结构化字典参数**

```python
# ✅ search_news — 注意参数直接在顶层，不是包裹在 query 里
params = {
    "query": "浩通科技 新闻",
    "time_start": "2026-05-18",
    "time_end": "2026-05-20",
    "size": 5
}

# ✅ search_notice — 同格式
params = {
    "query": "光迅科技 2024年度报告",
    "time_start": "2025-01-01",
    "size": 5
}

# ✅ search_trending_news
params = {
    "keyword": "智能体",
    "time_scope": "24小时",
    "size": 5
}
```

⚠️ **不要**把 search_news 的参数包在 query 字符串里：
```python
# ❌ 错误：参数作为字符串包裹
{"query": '{"query": "新闻", "time_start": "2026-05-18", "size": 5}'}
```

### ifind-edb — 全部用 `query` 字符串

```python
params = {"query": "上证指数今日涨跌幅"}
params = {"query": "光伏电池产量当月值（202301-202506）"}
```

### ifind-fund — 全部用 `query` 字符串

```python
params = {"query": "蜂巢丰瑞债券A(010084)的基金经理"}
```

## 返回值解析

```python
async def handle_result(result):
    """解析 Streamable HTTP 返回的 ToolResult"""
    for item in result.content:
        # TextContent
        if hasattr(item, 'text'):
            return item.text
        # RawResult / JSON
        if hasattr(item, 'data'):
            return item.data if isinstance(item.data, str) else json.dumps(item.data, ensure_ascii=False)
        if hasattr(item, 'model_dump'):
            return item.model_dump()
    return str(result.content)
```

## 完整工作示例

```python
import httpx, json, asyncio
from mcp.client.streamable_http import streamable_http_client
from mcp import ClientSession

JWT = "eyJhbGci..."  # 从 config.yaml 获取

async def main():
    url = "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp"
    headers = {"Authorization": f"Bearer {JWT}"}

    async with httpx.AsyncClient() as http_client:
        transport = streamable_http_client(url, http_client, headers=headers)
        async with ClientSession(*transport) as session:
            # 初始化
            await session.initialize()

            # 调用 get_stock_performance
            result = await session.call_tool("get_stock_performance", {
                "query": "浩通科技301026今日收盘价、涨跌幅、成交额、换手率"
            })

            # 提取文本
            text = next((c.text for c in result.content if hasattr(c, 'text')), str(result.content))
            print(text)

asyncio.run(main())
```

## 服务名 → URL 映射

| server_name | URL 中的 key | 工具数 |
|-------------|-------------|--------|
| stock | `hexin-ifind-ds-stock-mcp` | 9 |
| fund | `hexin-ifind-ds-fund-mcp` | 7 |
| edb | `hexin-ifind-ds-edb-mcp` | 2 |
| news | `hexin-ifind-ds-news-mcp` | 3 |
