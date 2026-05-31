# akshare 融资融券数据查询

## 背景

2026-05-22 查浩通科技(301026)融资融券余额时发现：iFinD MCP get_stock_performance 可查到但内容不明确（210字符仅含股票名称和融资融券余额数值，无详细列名）；东方财富 push2 / datacenter-web 融资融券接口均被 VPN 拦截或已失效。最终 akshare 成功获取完整数据。

## 可用函数

### 深交所融资融券明细（含创业板300/中小板002/深主板000）

```python
import akshare as ak

# 日期格式 YYYYMMDD，查询指定交易日
sz_df = ak.stock_margin_detail_szse(date="20260521")
```

**返回列名**：`['证券代码', '证券简称', '融资买入额', '融资余额', '融券卖出量', '融券余量', '融券余额', '融资融券余额']`

各列单位：融资买入额/融资余额/融券余额/融资融券余额 = 元，融券卖出量/融券余量 = 股。

### 上交所融资融券明细（含沪主板600/科创板688）

```python
sse_df = ak.stock_margin_detail_sse(date="20260521")
```

返回列名与深交所一致。

### 单只股票筛选

```python
code = "301026"
result = sz_df[sz_df["证券代码"] == code]
if not result.empty:
    record = result.iloc[0].to_dict()
    # record 示例:
    # {'证券代码': '301026', '证券简称': '浩通科技',
    #  '融资买入额': 34632230, '融资余额': 204486986,
    #  '融券卖出量': 0, '融券余量': 5800,
    #  '融券余额': 196330, '融资融券余额': 204683316}
```

## 关键特性

- **无需 API Key** — akshare 基于东方财富公开数据
- **Hermes venv 可用** — `~/.hermes/hermes-agent/venv/bin/python -c "import akshare"`
- **VPN 友好** — akshare 底层用 urllib 连接东方财富，不会被 Shadowrocket 的 `198.18.x.x` 劫持
- **全市场一次性获取** — 深交所单表 ~2800 行，上交所 ~2300 行，无需分页

## 局限性

| 场景 | 限制 | 替代 |
|------|------|------|
| 盘中实时融资融券余额 | 交易所数据 T+1 更新，盘中查到的是前一交易日数据 | MCP `get_stock_performance` 可查当日 |
| 非交易时段 | 非 9:00-17:00 调用可能报 `RemoteDisconnected` | 等交易所数据更新后再查 |
| 单只快速查询 | 需全量下载后再过滤（~0.5秒） | MCP 更直接 |

## 选择建议

| 场景 | 推荐 | 原因 |
|------|------|------|
| 盘后批量/全市场融资融券 | akshare | 一次性获取，不限量，VPN 友好 |
| 盘中实时融资融券 | MCP `get_stock_performance` query="融资融券余额" | 盘中数据可用 |
| MCP 不可用时的降级 | akshare | 走交易所公开接口，Hermes venv 已安装 |
| 融资融券 + 主力资金流同时查 | MCP（一揽子返回） | 避免调两个数据源 |

## 坑

### scope 参数已废弃
`ak.stock_margin_detail_szse()` 无 `scope` 参数（旧版可能有，新版 1.18.62 已移除）。
如果遇到 `TypeError: stock_margin_detail_szse() got an unexpected keyword argument 'scope'`，去掉 scope 参数即可。

### VPN 下首次调用可能超时
首次 import akshare 较慢（~1 秒），加上东方财富响应慢，总耗时 ~3 秒。
建议：保持连接不关，或设置 urllib 的默认 timeout。
