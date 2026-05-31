# iFinD MCP 服务器配置

## 配置位置

`~/.hermes/config.yaml` → `mcp_servers` 部分

## 4个MCP Server

**⚠️ Authorization值必须是JWT token（`eyJhbGci...`格式），不是 `get_access_token` 返回的hash！**

```yaml
mcp_servers:
  ifind-stock:
    url: "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp"
    headers:
      Authorization: "<access_token_jwt>"
    timeout: 180
    connect_timeout: 60
  ifind-fund:
    url: "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-fund-mcp"
    headers:
      Authorization: "<access_token_jwt>"
    timeout: 180
    connect_timeout: 60
  ifind-edb:
    url: "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-edb-mcp"
    headers:
      Authorization: "<access_token_jwt>"
    timeout: 180
    connect_timeout: 60
  ifind-news:
    url: "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-news-mcp"
    headers:
      Authorization: "<access_token_jwt>"
    timeout: 180
    connect_timeout: 60
```

## 工具清单（21个）

### ifind-stock (9个)
| 工具名 | 功能 | 常用参数 |
|--------|------|---------|
| `search_stocks` | 智能选股（自然语言） | `{"query": "电子行业市值大于100亿"}` |
| `get_stock_summary` | 股票信息摘要 | `{"query": "茅台财务状况"}` |
| `get_stock_info` | 基本资料+日频行情+技术指标 | `{"query": "格力电器上市时间"}` |
| `get_stock_financials` | 财务数据与指标 | `{"query": "科大讯飞2025年三季度的ROE"}` |
| `get_stock_shareholders` | 股本结构与股东 | `{"query": "光明乳业流通股占比"}` |
| `get_risk_indicators` | 风险定量指标 | `{"query": "航天电子在2026-03-19的夏普比率"}` |
| `get_stock_events` | 重大事件 | `{"query": "摩尔线程IPO首发股本数量"}` |
| `get_esg_data` | ESG评级 | `{"query": "诚意药业中诚信ESG评级"}` |
| `get_stock_performance` | 历史行情+技术形态 | （K线数据，但不如腾讯K线API） |

### ifind-fund (7个)
| 工具名 | 功能 |
|--------|------|
| `search_funds` | 基金搜索 |
| `get_fund_profile` | 基金基本资料 |
| `get_fund_market_performance` | 基金行情与业绩 |
| `get_fund_ownership` | 份额与持有人 |
| `get_fund_portfolio` | 持仓明细 |
| `get_fund_financials` | 基金财务指标 |
| `get_fund_company_info` | 基金公司信息 |

### ifind-edb (2个)
| 工具名 | 功能 |
|--------|------|
| `search_edb` | 宏观/行业指标搜索 |
| `get_edb_data` | 指标数据查询 |

### ifind-news (3个)
| 工具名 | 功能 | 常用参数 |
|--------|------|---------|
| `search_news` | 新闻语义检索 | `{"query": "内容", "time_start": "2025-01-01", "size": 5}` |
| `search_notice` | 公告语义检索 | `{"query": "光迅科技2024年度报告", "size": 5}` |
| `search_trending_news` | 热点事件 | `{"keyword": "智能体", "time_scope": "24小时"}` |

## 连接验证

```bash
hermes mcp test ifind-stock   # 9个工具
hermes mcp test ifind-fund    # 7个工具
hermes mcp test ifind-edb     # 2个工具
hermes mcp test ifind-news    # 3个工具
```

## 常用调用模式

### 选股时查基本面
```
mcp_ifind_stock_get_stock_financials: {"query": "XX股票 最新季度 ROE 净利润增速"}
mcp_ifind_news_search_notice: {"query": "XX股票 近期公告", "size": 5}
mcp_ifind_news_search_news: {"query": "XX股票 最新新闻", "size": 5}
```

### 智能选股
```
mcp_ifind_stock_search_stocks: {"query": "电子行业市值大于100亿的股票"}
```

### 宏观研究
```
mcp_ifind_edb_search_edb: {"query": "新能源汽车产量相关指标"}
mcp_ifind_edb_get_edb_data: {"query": "新能源汽车产量当月值（202301-202506）"}
```

## 已知限制

1. **不提供实时行情轮询** → 实时行情仍走腾讯 `qt.gtimg.cn`
2. **不提供K线数据** → K线仍走腾讯K线API `web.ifzq.gtimg.cn`
3. **JWT token 长期有效**（跟随账号到期日，不是7天）。7天过期的是HTTP API的access_token，两者不同。健康检查: `~/.hermes/scripts/ifind_refresh_token.py`
4. **query参数多主体时不宜超过10个** → 分批查询

## iFinD HTTP API 端点（PDF手册提取）

除MCP外，iFinD还有HTTP API（需要账号密码登录，非token模式）：

| 端点 | 用途 |
|------|------|
| `https://quantapi.51ifind.com/api/v1/get_access_token` | 用refresh_token获取access_token |
| `https://quantapi.51ifind.com/api/v1/update_access_token` | 重置IP绑定 |
| `https://quantapi.51ifind.com/api/v1/real_time_quotation` | 实时行情 |
| `https://quantapi.51ifind.com/api/v1/basic_data_service` | 基础数据 |
| `https://quantapi.51ifind.com/api/v1/edb_service` | 宏观数据 |
| `https://quantapi.51ifind.com/api/v1/smart_stock_picking` | 智能选股 |
| `https://quantapi.51ifind.com/api/v1/data_pool` | 数据池 |
| `https://quantapi.51ifind.com/api/v1/portfolio_manage` | 组合管理 |
| `https://quantapi.51ifind.com/api/v1/report_query` | 报表查询 |

这些端点需要账号密码认证，当前MCP模式使用token认证，不直接调用这些端点。
