# urllib.request.urlopen() proxies 参数误用事故（2026-05-28）

## 事件

V10尾盘搏高开14:30任务输出"无推荐"——两只强庄买候选股（穗恒运000531、瑞泰新材301238）实时行情数据全部为0。

## 根因链

1. `v10_tail_prefetch_v2.py` 14:20运行
2. `tencent_batch_quote()` 调用 `urllib.request.urlopen(req, timeout=15, proxies=PROXIES)`
3. `urlopen()` **不支持 `proxies` 参数** → 抛 `TypeError: got an unexpected keyword argument 'proxies'`
4. `except Exception as e: print(..., file=sys.stderr)` 静默吞掉异常
5. 返回空 `results = {}` → 写入全零缓存（`yesterday_close=0, volume=0, change_pct=0`）
6. `current_price` 有值是因为 fallback 到 watchlist 价格，掩盖了API失败
7. 14:30 agent 读缓存判断"行情全零" → 放弃推荐

## 修复

```python
# 旧代码（broken）
resp = urllib.request.urlopen(req, timeout=15, proxies=PROXIES)

# 新代码（fixed）
opener = urllib.request.build_opener(urllib.request.ProxyHandler(PROXIES))
resp = opener.open(req, timeout=15)
```

同时加入：
- 首次获取不到全部行情 → 等3秒重试一次 → 合并结果
- `_fetch_failed` 标记写入缓存JSON，下游agent可识别
- `import time` 用于重试等待

## 教训

1. **`urllib.request.urlopen()` 不支持 `proxies`** — 这是 `requests` 库的参数，不要混用
2. **`PROXIES = {}` 时直接用 `urlopen()`** — 空dict=不走代理，无需ProxyHandler
3. **`except Exception` 不能静默吞掉** — 至少打印到stderr并设置错误标记
4. **预取脚本必须校验返回数据完整性** — 返回0只≠正常，需重试+标记失败
5. **`current_price` 有值不代表API成功** — 可能是fallback值掩盖了失败

## 防护措施

- 重试机制：首次获取不到 → 3秒后重试
- `_fetch_failed` 标记：两次均失败时写入缓存
- 下游agent校验：检查 `_fetch_failed` 字段
- 完整性校验：关键字段（yesterday_close, volume）全零 → 数据异常
