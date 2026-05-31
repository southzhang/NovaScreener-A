# akshare 金融数据查询参考

当妙想API不可用时（数据延迟、超时、次数用完），使用akshare作为备用数据源。

## 安装
```
pip3 install akshare
```

## 常用查询

### 大盘实时行情
```python
import akshare as ak
df = ak.stock_zh_index_spot_em()
# 筛选重要指数
important = ["上证指数", "深证成指", "创业板指", "沪深300", "科创50"]
df[df["名称"].isin(important)][["名称", "最新价", "涨跌幅", "成交额"]]
```

### A股实时全市场行情
```python
df = ak.stock_zh_a_spot_em()
# 成交额排序前20
df.sort_values("成交额", ascending=False).head(20)[["代码", "名称", "最新价", "涨跌幅", "成交额"]]
```

### 个股历史K线
```python
df = ak.stock_zh_a_hist(symbol="002384", period="daily", start_date="20260401", adjust="qfq")
df.tail(20)[["日期", "收盘", "涨跌幅", "成交量"]]
```

### ⚠️ 盘中K线只有昨日数据（2026-05-13实测确认）
`stock_zh_a_hist()` 和 `stock_zh_a_daily()` 返回的是**已完成的日线bar**。盘中（9:30-15:00）运行时，今日bar未收盘不返回，最后一根K线是**昨天**的。

**后果：** 用Akshare K线计算EMA/MACD/V10信号 → 信号基于昨日数据 → 推荐过时。

**替代方案：** 盘中必须用腾讯K线API（`web.ifzq.gtimg.cn`），它在交易时段已返回今日未完成K线（close=实时价）。详见 `vegas-v10-strategy-v34` skill 的 `v10_scan_strict.py vs v10_realtime_scan.py` 章节。

**规则：**
- 盘中选股/扫描 → **禁止**用Akshare K线，必须用腾讯K线API
- 盘后分析/回测 → 可以用Akshare（此时日K线已含当日收盘数据）

### 数据延迟
akshare的数据源也是东方财富，但比妙想免费版更及时（接近实时）。
比妙想API的优势：**不需要API Key、无调用次数限制、数据更新更快**。

## 融资融券数据

见独立的 `references/akshare-margin-data.md`（深交所 stock_margin_detail_szse + 上交所 stock_margin_detail_sse）。通用场景：

```python
df = ak.stock_margin_detail_szse(date="20260521")
# 筛选单只：df[df["证券代码"] == "301026"]
# 返回列：证券代码、证券简称、融资买入额、融资余额、融券余量、融券余额、融资融券余额
```

## 已知问题

### ⚠️ 非交易时段连接拒绝
东方财富分钟级API（`stock_zh_a_hist_min_em`）在非交易时段（15:00-次日09:00）直接拒绝连接：
```
RemoteDisconnected: Remote end closed connection without response
```
**替代方案：** 腾讯行情 `qt.gtimg.cn` 或新浪 `hq.sinajs.cn` 全天可用。

### ⚠️ 盘前分钟线数据不含竞价量
`stock_zh_a_hist_pre_min_em` 在竞价时段（9:15-9:25）虽然返回价格数据，但**成交量列=0**——东方财富不提供竞价撮合量的分钟级数据。

### ⚠️ VPN冲突（Shadowrocket/Surge）
Shadowrocket 会劫持东方财富API的DNS解析，返回 198.18.0.x（虚拟接口IP），导致连接失败。
**解决：** 临时关VPN，或加直连规则 `82.push2.eastmoney.com`, `push2ipv6.trafficmanager.cn`

### ⚠️ macOS Python3.9 LibreSSL 限制
系统 Python 3.9 的 LibreSSL 2.8.3 无法连接到东方财富API的HTTPS服务器。
**解决：** 使用 Vibe-Trading .venv 的 Python 3.12: `~/.hermes/workspace/Vibe-Trading/.venv/bin/python3`

### ⚠️ 腾讯API逗号分隔（常见坑）
```python
# ✅ 正确：逗号分隔
url = "http://qt.gtimg.cn/q=sh600000,sh600004,sh600006"

# ❌ 错误：斜杠分隔 → 返回 pv_none_match
url = "http://qt.gtimg.cn/q=sh600000/sh600004/sh600006"
```

## 替代数据源（无akshare可用时）

| 数据源 | 接口 | 全天可用 | 全市场批量 |
|--------|------|----------|-----------|
| 腾讯行情 | `qt.gtimg.cn/q=code1,code2,...` | ✅ | 100只/次 |
| 新浪行情 | `hq.sinajs.cn/list=sh600519` | ✅ | ❌ 逐只 |
| 新浪全量 | `vip.stock.finance.sina.com.cn` | ❌ 收盘后404 | ✅ 分页 |
| 新浪K线 | `money.finance.sina.com.cn` | ✅ | ❌ 逐只 |
