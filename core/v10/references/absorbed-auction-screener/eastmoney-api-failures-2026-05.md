# 东方财富 API 故障记录 (2026-05-07)

## 故障现象

### 1. datacenter-web `RPT_LHBSCTJ` 报表失效

- **URL:** `https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_LHBSCTJ&...`
- **返回:** `{"success": false, "message": "报表配置不存在,RPT_LHBSCTJ", "code": 9501}`
- **原因:** 东方财富已下线/重命名该报表
- **影响:** `fetch_eastmoney_all()` 返回空列表，脚本误判为"无数据"

### 2. push2.eastmoney.com 持续断连

- **URL:** `https://push2.eastmoney.com/api/qt/clist/get?...`
- **返回:** `Remote end closed connection without response`
- **原因:** 服务器拒绝连接（可能是IP封禁或接口下线）
- **影响:** Akshare 底层依赖 push2，同样不可用

### 3. 脚本错误处理缺陷

原脚本 `fetch_eastmoney_all()` 只检查 `result.data` 是否存在，不检查 `success` 字段。
当 API 返回 `success: false` 时，`result` 为 `null`，函数返回空列表但不报错，
导致脚本误以为"东方财富无数据"而非"东方财富API报错"。

**修复建议:** 检查 `raw.get('success')` 字段，失败时打印错误信息并抛出异常触发降级。

### 4. 新浪全量API失效（2026-05-09新增）

- **URL:** `http://vip.stock.finance.sina.com.cn/quotes_service/api_json_v2.php/Market_Center.getHQNodeData`
- **返回:** HTTP 404 Not Found
- **原因:** 新浪已下线该API
- **影响:** 曾是唯一可靠兜底方案，现在也失效。需改用腾讯全量扫描兜底。

## 手动修复方案

当东方财富/Akshare均不可用时，使用腾讯全量扫描兜底：

```python
# 腾讯全量扫描（当前唯一可靠方案）
# 详见 references/tencent-full-pool-fallback.md
pool = gen_stock_pool()  # 生成~15000个代码
for batch in chunks(pool, 100):
    results = fetch_tencent_batch(batch)
    all_stocks.update(results)
```

新浪全量API已失效（2026-05-09实测404），不再作为兜底方案。

## 策略筛选条件（从脚本提取）

### 趋势共振
- 涨幅 3-6%, 金额 > 2000万, 流通 < 200亿, 量比 > 3
- K线: MA5 > MA10 > MA20 > MA60 多头排列

### 游资爆量V1
- 涨幅 3-7%, 金额 > 5000万, 流通 < 100亿, 量比 > 4

### 游资竞价V2
- 涨幅 2-5%, 流通 < 100亿, 量比 > 2
- 金额分档: <5亿→>2000万 | 5-10亿→>3500万 | 10-15亿→>5000万
