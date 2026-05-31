# 免费 A 股数据源速查（2026-05-29）

> 用户明确偏好：**能免费绝不付费**。分钟K线/全市场批量/财务数据，优先选免费的。

## 一、你要什么？

| 你需要 | 免费方案 | 付费/受限方案 | 时效性 |
|--------|---------|-------------|--------|
| **日K线（历史）** | ✅ TickFlow `/v1/klines?symbol=X.SZ&period=1d`（10000根免费） | 腾讯K线 `ifzq.gtimg.cn` 免费 | 免费层足够 |
| **分钟K线（盘中）** | ✅ **新浪分钟K线** `money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz{CODE}&scale=60&ma=no&datalen=120` | TickFlow 完整版 / iFinD HTTP API | ✅ 实时 |
| **实时行情（单只）** | ✅ 腾讯 `qt.gtimg.cn?q=sh{X}` | TickFlow 完整版 / iFinD MCP | ✅ 实时 |
| **实时行情（批量）** | ✅ **腾讯** `qt.gtimg.cn?q=shX,szY,...`（200只/批） | TickFlow 完整版（一次全市场5517只，秒级） | ✅ 实时 |
| **实时行情（全市场）** | ⚠️ 无免费方案（腾讯需18批串行~43秒） | TickFlow 完整版 `universes=["CN_Equity_A"]` | 免费层403 |
| **财务数据** | ✅ **iFinD MCP**（结构化查询，免费额度用完前） | TickFlow 完整版 / iFinD HTTP API | 取决于额度 |
| **智能选股/问财** | ✅ **iFinD MCP** `search_stocks` / HTTP `smart_stock_picking`（不限量） | 无 | ✅ 不限量 |
| **五档行情** | ❌ 无免费方案 | TickFlow 完整版 | — |
| **复权K线** | ✅ TickFlow（内置forward/backward/none） | 无（腾讯K线无复权参数，需手工算） | ✅ |
| **融资融券** | ✅ **搜狐证券** `q.stock.sohu.com/app2/mpssTrade.up?code={code}`（web_extract） / **凤凰网财经** `finance.ifeng.com/app/hq/stock/sz{code}` | iFinD MCP（额度内） | ✅ |
| **龙虎榜** | ✅ **同花顺10jqka** `data.10jqka.com.cn/market/lhbgg/code/{code}`（web_extract） | iFinD MCP（额度内） | 盘后更新 |
| **大宗交易** | ✅ **同花顺10jqka** 页面（web_extract） | iFinD MCP（额度内） | 盘后更新 |

## 二、核心免费数据源详解

### ① 腾讯行情（实时行情 + 批量）🥇

**推荐场景**：任何需要实时行情的场景。免费、无限制、支持批量（200只/批）。

- 单只：`https://qt.gtimg.cn/q=sh600519`
- 批量：`https://qt.gtimg.cn/q=sh600519,sz000001,sz300750`
- 前缀：sh=上海/科创板，sz=深圳/创业板/北交所
- 编码：`iconv -f gbk -t utf-8`
- 解析：`split('~')`，字段索引见 `references/tencent-qt-fields.md`

### ② 新浪分钟K线（盘中分钟K线）🥇

**推荐场景**：盘中需要分钟K线做分析时，无需任何认证，完全免费。

**2026-05-29 实测结果**：

| 频率 | scale | 结果 |
|:---|:-----:|:----:|
| 5分钟 | `5` | ✅ 实时可用 |
| 15分钟 | `15` | ✅ |
| 30分钟 | `30` | ✅ |
| 60分钟 | `60` | ✅ |

> ⚠️ **1分钟线不可用**（返回 `null`）。需要1分钟K线走 iFinD HTTP API 或 TickFlow 完整版。

```python
import urllib.request, json

code = "sz300410"  # 前缀：sh=上海/科创板, sz=深圳/创业板/北交所
scale = 5          # 5分钟线。实测支持：5/15/30/60（不支持1）
datalen = 120      # 最多返回多少根（最近约24小时）

url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale={scale}&ma=no&datalen={datalen}"

resp = urllib.request.urlopen(url, timeout=10)
data = json.loads(resp.read().decode("gbk"))
# data = [{"day": "2026-05-29 10:00", "open": "16.80", "high": "...", "low": "...", "close": "...", "volume": "..."}, ...]
```

**重要注意事项**：
- **⚠️ 代理问题**：该API曾被IP封禁（返回456状态码）。如果走代理被封，用 `--noproxy "*"` 直连可绕过
- **字段限制**：只返回 `day/open/high/low/close/volume`，无成交额(amount)和无复权
- **时效性**：仅最近约24小时的分钟K线，无历史分钟K
- **沪市代码**：`sh600519`，深市：`sz300410`
- **编码**：返回的 `day` 字段是 `"2026-05-29 14:55"` 格式，含日期+时间
- **频率选择**：5分钟线是推荐的均衡选择（120根可覆盖全天10小时），60分钟线适合看趋势方向

**V10集成价值**：可用60分钟线替代日K线做盘中V10趋势判断（EMA50/150/300在60分钟线和日线级别一致，但60分钟线可提前获得信号）。

### ③ TickFlow 日K线（免费层，含复权）

**推荐场景**：需要复权K线时，免费层10000根够用。

```bash
curl -s "https://api.tickflow.org/v1/klines?symbol=300410.SZ&period=1d&count=250" -H "x-api-key: $TICKFLOW_API_KEY"
```

- 格式：`code.SH` / `code.SZ`（先腾讯格式→转TickFlow格式）
- 免费层禁：分钟K线(403)、全市场批量(403)、财务(401/403)

### ④ 搜狐证券（融资融券 fallback）

**推荐场景**：iFinD MCP额度耗尽/限流时查融资融券。

```python
from hermes_tools import web_extract

result = web_extract(urls=["http://q.stock.sohu.com/app2/mpssTrade.up?code=sz410"])
# 返回近30天表格，含融资余额/融资买入/融券余额/两融余额
```

- 代码格式：`sh{CODE}` / `sz{CODE}`（不用前缀数字）
- web_extract 直连可用，无VPN依赖

## 三、场景速查（找对应数据源）

```
场景: 我要查单只股票实时价
  答: 腾讯 qt.gtimg.cn/q=sz300410 → split('~')[3]

场景: 我要批量查50只股票的实时行情
  答: 腾讯 200只/批，qt.gtimg.cn/q=shX,szY,...

场景: 我要查今天5分钟K线
  答: 新浪分钟K线，http://money.finance.sina.com.cn/...getKLineData?symbol=sz300410&scale=5&datalen=120

场景: 我要250天日K线，要复权
  答: TickFlow /v1/klines?symbol=300410.SZ&period=1d&count=250&adjust=forward

场景: 我要查一只小盘股的融资余额
  答: 先iFinD MCP查是否为融资标的 → 是则搜狐证券/凤凰网降级

场景: 我要问财选股（自然语言条件）
  答: iFinD MCP search_stocks 或 HTTP smart_stock_picking（不限量）

场景: 我要全市场一次快照（5517只）
  答: 免费层无解，必须TickFlow完整版或腾讯18批串行
```

## 四、经典"不能免费"的

| 你想要的 | 免费能做到吗 | 原因 |
|---------|:---------:|------|
| 一次拉全市场5517只实时数据 | ❌ | 腾讯只支持200只/批，TickFlow免费层UNIVERSE查询返回403 |
| 9:25竞价行情数据 | ❌ | 腾讯竞价时段无数据，新浪相同，需要iFinD/付费数据 |
| Level-2/五档行情 | ❌ | 所有免费API只提供Level-1快照 |
| 分钟级历史K线（非今日） | ❌ | 新浪只有近120根分钟K线，历史分钟K需要iFinD/TickFlow完整版 |
| 资金流/主力净流入全市场 | ❌ | iFinD MCP有限额，免费全市场扫描不存在 |
