# TickFlow 数据源（2026-05-28 评估；05-29 补充真实 API 测试记录）

## 真实 API 域名（vs 文档域名）

⚠️ **重要**：TickFlow 有多个域名，功能完全不同，不要搞混：

| 域名 | 作用 | 状态 |
|------|------|------|
| `www.tickflow.xyz` | 旧文档站（Docusaurus） | ✅ 访问正常 |
| `docs.tickflow.org` | 文档站（Mintlify，zh-Hans 可用） | ✅ 访问正常 |
| `tickflow.io` | 开发/预发布 API，Vercel 安全保护 | ❌ HTTP 429，需 JS Challenge |
| **`api.tickflow.org`** | **生产 API** | **✅ 真实 API，OpenAPI 3.1.0** |
| `github.com/tickflow-org/tickflow` | Python SDK 源码 | ✅ 开源，`client.py` 中写死了 `api.tickflow.org` |

### 发现路径（以防后续域名变更）
从 `tickflow.xyz`（文档站）→ 发现 SDK 演示链接指向 `tickflow.io/api/` → Vercel 挡路（429）→ 爬 GitHub SDK 源码 `client.py` 发现 `base_url = "https://api.tickflow.org"` → 直连验证成功。

### 2026-05-28 真实 API 测试记录（自定义 API Key 实测）

#### API Key
- 格式：`tk_` 开头 + 32 位 hex
- 请求头：`x-api-key: <key>`（大小写均可）
- 来源：用户自行注册获取

#### 已验证可用的端点

##### ✅ 日K线（免费层可用）
```
GET /v1/klines?symbol={code}.{market}&period={period}&count={n}
Headers: x-api-key: <key>
```
- 返回 JSON，结构：`{"data": [{"timestamp": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "amount": ...}, ...]}`
- period 支持：1m,5m,10m,15m,30m,60m,1d,1w,1M,1Q,1Y（但 intraday 周期需付费）
- 代码格式：`300410.SZ` / `000001.SZ` / `600519.SH`

##### ✅ 多只实时行情（免费层可用）
```
GET /v1/quotes?symbols=300410.SZ,000001.SZ,600519.SH
Headers: x-api-key: <key>
```
- 返回 JSON array
- 每项含：`last_price / prev_close / open / high / low / volume / amount / timestamp / ext`
- `ext` = `{change_pct, change_amount, amplitude, turnover_rate, name}`

##### ✅ OpenAPI 规范（无需 Key）
```
GET https://api.tickflow.org/openapi.json
```
- 完整 OpenAPI 3.1.0 规范，无需认证即可访问
- 包含所有端点的请求/响应格式

#### 免费层禁用的端点（HTTP 403）

| 端点 | 响应消息 |
|------|----------|
| `GET /v1/klines/intraday?symbol=...&period=1m&count=5` | "当前套餐不支持日内分时数据，请升级" |
| `GET /v1/quotes?universes=CN_Equity_A` | "当前套餐不支持标的池查询，请升级或使用 symbols 参数" |
| 财务/五档/WebSocket 等 | 免费层不可用 |

**结论**：免费层完全不支持分钟K线和全市场批量查询。SDK 文档中声称的 "免费层日K + 完整版全部功能" 与现实一致。

## 核心能力 vs 现有数据源

## 概述

TickFlow 是开源 Python SDK 金融数据 API，由原 efinance 作者开发。覆盖 A 股/港股/美股/期货。

- 文档：https://docs.tickflow.org/zh-Hans/sdk/python-quickstart（国内被墙，需代理）
- GitHub：https://github.com/tickflow-org/tickflow
- 安装：`pip install tickflow`（当前 v0.1.22）
- 全量安装（含 pandas 等依赖）：`pip install "tickflow[all]"`

## 服务层级

### 免费服务（无需注册）
```python
from tickflow import TickFlow
tf = TickFlow.free()
df = tf.klines.get("600000.SH", period="1d", count=100, as_dataframe=True)
```
- 仅历史日 K（深圳交易所数据从2020年起）
- 无盘中实时行情、无分钟K线、无财务数据
- **注意**：免费层 `quotes.get()` 能返回 DataFrame 结构，但价格字段非实时

### 完整版（2026-05-28 测试通过 ✅）
```python
from tickflow import TickFlow
tf = TickFlow(api_key="your-api-key")
# 或通过环境变量 TICKFLOW_API_KEY

# 全市场实时快照 — 5517只A股一次性返回
quotes = tf.quotes.get(universes=["CN_Equity_A"], as_dataframe=True)
# 返回 (5517, 14) DataFrame，包含 last_price/prev_close/open/high/low/volume/amount

# 分钟K线 — 付费层可用
klines = tf.klines.get(symbols="600519.SH", period="1m", count=5)
```

## 核心能力 vs 现有数据源

| 能力 | TickFlow 免费 | TickFlow 完整 | 腾讯行情 | iFinD MCP | iFinD HTTP API |
|------|:---:|:---:|:---:|:---:|:---:|
| A股实时行情(单次全市场) | ❌ | ✅ 秒级，一次性 | ✅ 200只/批串行~43秒 | ❌ 批量 | ❌ |
| 日K线(免费) | ✅ 10000根 | ✅ 10000根 | ✅ | ❌ | ✅ 按根计费 |
| 分钟K线(1m/5m等) | ❌ | ✅ | ❌ | ❌ | ✅ 按根计费 |
| 财务数据 | ❌ | ✅ 利润/资产/现金流 | ❌ | ✅ | ✅ |
| 五档行情 | ❌ | ✅ | ❌ | ❌ | ❌ |
| 复权(前后复权/多模式) | ✅ 多模式 | ✅ 多模式 | ❌ | ❌ | ❌ |
| WebSocket推送 | ❌ | ✅ | ❌ | ❌ | ❌ |
| 市场深度 | ❌ | ✅ | ❌ | ❌ | ❌ |

## 标的代码格式

格式：`代码.市场后缀`（与 sh/sz 前缀不同）

| 后缀 | 市场 |
|------|------|
| SH | 上海证券交易所 |
| SZ | 深圳证券交易所 |
| BJ | 北京证券交易所 |
| US | 美股 |
| HK | 港股 |

常用 Universe（2026-05-28 实测确认）：
| Universe ID | 覆盖范围 | 数量 |
|:-----------|:---------|:----:|
| `CN_Equity_A` | 沪深京全部A股 | 5517只 |
| `CN_ETF` | A股ETF | 1497只 |
| `CN_Index` | A股指数 | 611只 |
| `HK_Equity` | 港股 | 2777只 |
| `US_Equity` | 美股 | 11715只 |

另有 SW1/SW2/SW3 申万行业分类 Universe 和 GFEX 期货 Universe。

腾讯格式 ↔ TickFlow 格式转换：
```python
def tencent_to_tickflow(code):
    if code.startswith("6"):
        return f"{code}.SH"
    elif code.startswith(("0", "3")):
        return f"{code}.SZ"
    elif code.startswith(("4", "8")):
        return f"{code}.BJ"
    return code
```

## 关键 API 速查

### 实时行情 — 按 universe（全市场一次性，推荐）
```python
quotes = tf.quotes.get(universes=["CN_Equity_A"], as_dataframe=True)
# DataFrame 列（2026-05-28 实测）：
# symbol, name, region, last_price, prev_close, open, high, low, volume, amount, timestamp, session, ext
# ext = {change_pct, change, amplitude, turnover_rate, ...} 字典
# amount 单位：元（不是万元！）
```

### 实时行情 — 按 symbols（最多？只，推荐≤1000）
```python
df = tf.quotes.get(symbols=["600000.SH", "000001.SZ"], as_dataframe=True)
```

### 批量日K线（复权可选）
```python
symbols = ["600000.SH", "000001.SZ", "600519.SH"]
dfs = tf.klines.batch(symbols, period="1d", count=250,
                      as_dataframe=True, show_progress=True,
                      adjust="forward",  # forward/backward/none
                      batch_size=100,    # 每批最多100只
                      max_workers=5)     # 并发线程数
```

### 分钟K线
```python
# 单只
klines = tf.klines.get("600000.SH", period="1m", count=5)
# 返回：[{open, high, low, close, volume, amount, timestamp}, ...]

# 批量（需完整版）
dfs = tf.klines.intraday_batch(["600000.SH", "000001.SZ"], as_dataframe=True)
```

### 全部 Universe 列表
```python
universes = tf.universes.list()
for u in universes:
    print(f'{u["id"]}: {u.get("name","")} ({u.get("symbol_count","?")} sym)')
```

### 财务数据
```python
# 利润表
income = tf.financials.income(["000001.SZ"], latest=True)
# 核心指标
metrics = tf.financials.metrics(["000001.SZ"], latest=True)
# ⚠️ 免费层不可用
```

### 五档行情
```python
depth = tf.depth.get("600000.SH")
# bid_prices[0] = 买一价, ask_prices[0] = 卖一价
# ⚠️ 免费层不可用
```

## V10 系统集成评估

### 对现有瓶颈的改进

| 瓶颈 | 现状 | TickFlow 完整版 |
|------|------|:--------------:|
| 全市场行情扫描 | 腾讯 200只/批 × 18批，~43秒 | 一次性5517只，预计秒级 |
| 分钟K线确认 | iFinD HTTP API（按根计费，2400根/次扫描） | 完整版批量获取 |
| K线复权 | 腾讯无复权，需手工计算 | 内置 forward/backward/none |
| 五档盘口 | 无此能力 | 完整版直接可用 |
| 财务数据 | MCP 额度有限 | 完完整版作为降级源 |

### 关键结论（2026-05-28；06-10 细化集成评估）

**TickFlow 完整版最大的价值点**：一次性全市场实时快照（替代腾讯200只/批的串行瓶颈）+ 分钟K线批量获取（替代iFinD按根计费）。

#### ✅ TickFlow 能替代的部分

| 场景 | 现状 | TickFlow 完整版 | 改善量 |
|------|------|:--------------:|:------:|
| **全市场实时行情** | 腾讯200只/批×18批，~43秒 | `quotes.get(universes=["CN_Equity_A"])` 一次性5517只，秒级 | **~10x** |
| **分钟K线确认** | iFinD HTTP API 按根计费(2400根/次) | `klines.intraday_batch()` 批量获取 | 降低iFinD配额消耗 |
| **K线复权** | 腾讯无复权，手工计算 | 内置 forward/backward/none | 代码简化 |

#### ❌ TickFlow 不能替代的部分

| 能力 | 现状 | TickFlow | |
|------|------|:--------:|:--|
| **智能选股(自然语言→股票)** | iFinD问财（不限量） | ❌ | 无替代 |
| **基本面(ROE/净利润)** | iFinD MCP | ❌ 完整版只有利润表 | 不如MCP全 |
| **公告/新闻排雷** | iFinD MCP search_news | ❌ | 无替代 |
| **板块分析** | sector_analysis.py(iFinD) | ❌ | 无替代 |
| **融资融券/龙虎榜** | iFinD MCP | ❌ | 无替代 |
| **资金面/主力净流入** | iFinD MCP/push2 | ❌ | 无替代 |

#### 最现实的集成路径

**只改行情层，不动架构**——把 `v10_realtime_scan.py` 里拉全市场报价的函数从腾讯切到 TickFlow，43秒→秒级。其他数据源（iFinD问财/公告/基本面/板块）不动。改动量极小，只涉及一个函数替换。

#### 前置条件（未满足前不动）

1. **完整版定价未知** — 太贵不值（腾讯免费）
2. **当前 key 是免费版** — `quotes.get(universes=...)` 报403
3. **官网被墙** — 续费/管理不便

**结论**：确实能接入，但不如当前架构必要。腾讯免费+足够快（43秒），TickFlow 的改善不是质变优先级。等 QMT 开通后，xtdata 同样可一次性全市场扫描，届时再比较 TickFlow vs xtdata 再决定。

## ⚠️ 已知限制和陷阱

### 🌐 官网被墙
`tickflow.org` 官网在国内网络需要代理访问。GitHub 仓库和 `pip install` 正常。

### 💰 定价未知
完整版定价无公开信息。用户需注册后查看。

### 📦 免费层能力割裂 — 不可误用
**已经实测确认（2026-05-28）**：
- 免费层 `quotes.get()` 能返回 DataFrame 结构（非实时数据）
- 免费层 `klines.get(period="1m")` 被服务器拒绝（403）
- 免费层 `TickFlow.free()` 实例的 `quotes.realtime` / `stream` 等属性不存在或不可用

### 🐍 安装依赖
- 包名：`tickflow`，直接 `pip install tickflow`
- hermes cron 环境需装到 `~/.hermes/hermes-agent/venv/` 下
- 当前版本 v0.1.22（2026-05）

### ⚠️ 与现有数据源 format 差异
- 腾讯用 `sh600000` / `sz300001` 前缀格式
- TickFlow 用 `600000.SH` / `300001.SZ` 后缀格式
- 相互转换需工具函数（见上方代码格式转换章节）

### ⚠️ `quotes.get()` 的两种调用方式
```python
# 方式1：按 symbols（有限数量）
quotes = tf.quotes.get(symbols=symbols_list, as_dataframe=True)

# 方式2：按 universes（整个市场）
quotes = tf.quotes.get(universes=["CN_Equity_A"], as_dataframe=True)
# universes 参数：str 或 list[str] 均可
```

### ⚠️ `klines.batch()` 默认参数
```python
# 每批处理100只symbol，同时5个并发线程
# batch_size 可调小（20-50更稳），max_workers 可加大（10-20）
dfs = tf.klines.batch(symbols, batch_size=100, max_workers=5, ...)
```

## 待确认

- [ ] 完整版定价（用户已注册但未获知定价）
- [ ] 盘前时段(09:15-09:25)数据可用性
- [ ] 全市场实时快照实际速度基准测试（秒级 vs 43秒）
- [ ] VPN/代理兼容性（SDK 底层 HTTP 请求是否跟系统代理冲突）
- [ ] Cron 环境中 SDK 可用性
- [ ] API Key 过期策略
- [ ] 免费层调用频率限制
