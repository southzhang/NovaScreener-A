# 腾讯K线API分页陷阱（2026-05-16实测）

## 问题

分页模式（`param={symbol},day,,,{page},qfq`）对多数股票**只返回1根K线**（`qfqday`字段），无法获取完整历史数据。

## 正确用法：日期范围+大数量参数

```python
# ✅ 正确：指定日期范围+数量上限，返回全量K线
url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,2020-01-01,2026-05-15,2000,qfq'
# 返回 qfqday 字段，约640-800根K线

# ❌ 错误：分页模式，对多数股票只返回1根
url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{page},qfq'
```

## 关键区别

| 模式 | URL参数 | 返回字段 | 数据量 |
|------|---------|---------|--------|
| 分页 | `day,,,{page},qfq` | `klines`（可能为空）| 通常1根 |
| 日期范围 | `day,2020-01-01,2026-05-15,2000,qfq` | `qfqday` | 640-800根 |

## 注意事项

1. `klines` 和 `qfqday` 是不同字段，日期范围模式下数据在 `qfqday` 中
2. 代码必须优先读 `qfqday`：
   ```python
   bars = klines.get('qfqday', []) or klines.get('klines', []) or klines.get('day', [])
   ```
3. 影响范围：所有用腾讯K线API的回测/扫描脚本（v10_backtest.py、Vibe-Trading回测框架等）

## 验证方法

```python
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

# 分页模式（通常只有1根）
url1 = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz300065,day,,,1,qfq'
resp1 = json.loads(urllib.request.urlopen(urllib.request.Request(url1, headers={'User-Agent':'Mozilla/5.0'}), timeout=15, context=ctx).read())
bars1 = resp1['data']['sz300065'].get('qfqday', resp1['data']['sz300065'].get('klines', []))
print(f"分页模式: {len(bars1)}根")  # 通常: 1

# 日期范围模式（完整数据）
url2 = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz300065,day,2020-01-01,2026-05-15,2000,qfq'
resp2 = json.loads(urllib.request.urlopen(urllib.request.Request(url2, headers={'User-Agent':'Mozilla/5.0'}), timeout=15, context=ctx).read())
bars2 = resp2['data']['sz300065'].get('qfqday', resp2['data']['sz300065'].get('klines', []))
print(f"日期范围: {len(bars2)}根")  # 通常: 640-800
```
