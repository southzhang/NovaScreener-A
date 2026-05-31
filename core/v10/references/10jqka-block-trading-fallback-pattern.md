# 同花顺10jqka大宗交易降级查询模式

## 背景

当iFinD MCP返回"用户使用工具已超限"或datacenter-web报表全部返回9501"报表配置不存在"时，同花顺10jqka的大宗交易页面可作为降级源。

web_extract 直连可用，无 VPN 依赖。

## URL 格式

```
https://data.10jqka.com.cn/market/dzjy/stock/{code}/
```

其中 code 为6位数字股票代码（不含前缀），例如 `https://data.10jqka.com.cn/market/dzjy/stock/300410/`

## 调用方式

```python
from hermes_tools import web_extract
result = web_extract(urls=["https://data.10jqka.com.cn/market/dzjy/stock/300410/"])
# result["results"][0]["content"] 包含大宗交易数据markdown格式
```

## 返回内容

页面返回 近2个交易日（含当天）的大宗交易数据汇总表，包含：

- 股票代码、股票简称、最新价、成交价
- 总成交量(万股)、笔数、溢价率
- 买方营业部(简)、卖方营业部(简)、交易日期

## 数据过滤要点

- 页面包含所有股票的大宗交易记录（多只股票混合显示）
- 需要自行按股票代码过滤：搜索内容中是否包含目标代码
- 如果目标股票不在返回表格中，说明该股近期无大宗交易

## 局限性

- **仅限近2个交易日**（当天+昨天），无法查询历史区间
- 返回的是表格摘要而非完整原始数据（成交量已合并、营业部名已简化）
- 不区分上交所/深交所（所有股票混合显示）
- 数据更新有时延（收盘后约30分钟更新）
- 盘中不更新当日大宗交易数据

---

## 方案二：新浪财经 — 历史区间查询（2026-05-26新增确认）

新浪的**大宗交易页面**（区别于已死的K线/列表API）支持指定日期范围的历史查询，返回完整的单股大宗交易明细。

### URL 格式

```
https://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/dzjy/index.phtml?symbol=sz{code}&bdate={yyyy-mm-dd}&edate={yyyy-mm-dd}
```

代码前缀：sz=深交所, sh=上交所。

### 调用方式（execute_code）

```python
import urllib.request, re

url = 'https://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/dzjy/index.phtml?symbol=sz300410&bdate=2026-01-01&edate=2026-05-26'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=10) as resp:
    html = resp.read().decode('gbk', errors='replace')

# 提取表格
tables = re.findall(r'<table[^>]*>.*?</table>', html, re.DOTALL)
for tbl in tables:
    if '万元' in tbl or '成交价' in tbl:
        text = re.sub(r'<[^>]+>', ' ', tbl)
        text = re.sub(r'\s+', ' ', text).strip()
```

### 返回内容

每条记录：交易日期 | 证券代码 | 证券简称 | 成交价格(元) | 成交量(万股) | 成交金额(万元) | 买方营业部 | 卖方营业部 | 证券类型

### 表格判空

表头有但无数据行 = 该股在此时间区间无大宗交易。

### 局限性

- gbk编码，需 `decode('gbk', errors='replace')`
- 返回HTML表格非JSON，用正则提取
- 新浪财经无反爬限制（2026-05-26实测通过）
- 更新时效推测T+1

### 实测案例（2026-05-26）

正业科技(300410)：2026-01-01至2026-05-26区间无大宗交易。历史记录到2025年（2025-07-07 成交7.46元 175.85万股 1311.84万元）。

---

## 降级源对比

| 维度 | iFinD MCP get_stock_performance | 10jqka 页面 | 新浪财经页面 |
|------|-------------------------------|------------|------------|
| 覆盖区间 | 时间范围查询 | **仅近2天** | **历史区间查询** |
| 数据精度 | 精确金额 | 汇总表格 | 完整明细 |
| 可用性 | 受MCP额度/限流 | web_extract直连 | execute_code直连 |
| 营业部信息 | 无 | 有(简化) | 完整 |
| 数据格式 | JSON | Markdown | HTML表格需提取 |
| 单股过滤 | 自动 | 手动筛选 | 自带单股查询 |

## 降级优先级

MCP限流时：
1. **iFinD重试** -- 等2分钟再试（用户使用工具已超限是临时性的）
2. **新浪财经** -- 如需查某只股的历史区间大宗交易
3. **10jqka** -- 如需快速确认近2天行情
4. 均无数据 -> 该股近期/区间内无大宗交易

## 典型场景

- 查某只股当天是否有大宗交易 -> 新浪（历史区间含当天）
- 快速确认近2天 -> 10jqka
- 看营业部信息 -> 新浪（更完整）

注意：新浪已死仅针对K线API（456/IP封禁）和列表API（404），大宗交易页面是独立端点仍正常可用。
