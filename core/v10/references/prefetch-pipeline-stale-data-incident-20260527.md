# Prefetch Pipeline Stale Data Incident — 2026-05-27

## What happened

The 14:30 tail-end stock picker (`5f403ea5f0ca`) recommended stocks based on **2026-05-25 data** instead of today's (05-27) data. User was trading on these recommendations — this caused real financial risk.

## Root cause chain

```
14:25 prefetch task (7fd58d356bcf) — v10_tail_prefetch.py
  ↓ PROXIES variable undefined → NameError on every API call
  ↓ Script completely non-functional
  ↓ Ran at 14:32 (7 min late) → FAILED
  ↓ Wrote nothing to cache (or stale cache remained)
  
14:30 stock picker task (5f403ea5f0ca)
  ↓ Read ~/.hermes/cache/v10_tail_prefetch.json
  ↓ Cache contained scan_date: "2026-05-25" (2 days old)
  ↓ No freshness validation in the task
  ↓ Recommended stocks based on 05-25 prices/signals
  ↓ User received recommendations and almost traded on stale data
```

## The three bugs that enabled this

1. **PROXIES undefined** (v10_tail_prefetch.py:50) — `urllib.request.urlopen(req, proxies=PROXIES)` with no `PROXIES` defined → NameError. Fixed: added `PROXIES = {}`.

2. **No freshness validation** — The 14:30 task prompt says "read the cache file" but never checks `prefetch_time` or `scan_date`. If the cache is stale, it silently uses old data.

3. **Consumer trusts producer blindly** — The stock picker assumes the prefetch succeeded and has fresh data. No guard clause.

## Prevention pattern: Consumer-side data freshness validation

Every cron task that reads from a shared cache MUST validate freshness before using the data. This applies to:

- `v10_tail_prefetch.json` — read by 14:30 stock picker
- `v10_watchlist.json` — read by all monitoring tasks
- `capital_flow.json` — read by monitoring scripts

### Implementation in prompt (agent tasks)

```
## Data validation (MANDATORY — do this FIRST)
Before analyzing any data:
1. Read ~/.hermes/cache/v10_tail_prefetch.json
2. Check: prefetch_time must be today AND after 14:20
3. Check: scan_date must be today
4. If either check fails → output "缓存未就绪/过期" and STOP. Do NOT recommend anything.
```

### Implementation in script (no_agent tasks)

```python
from datetime import datetime
import json

with open(cache_path) as f:
    data = json.load(f)

prefetch_time = data.get("prefetch_time", "")
today = datetime.now().strftime("%Y-%m-%d")

if not prefetch_time.startswith(today):
    print(f"[SILENT] Cache stale: prefetch_time={prefetch_time}, expected {today}")
    sys.exit(0)
```

## Cron dependency map

| Producer (writes cache) | Consumer (reads cache) | Cache file | Freshness check |
|------------------------|----------------------|------------|-----------------|
| `7fd58d356bcf` V10尾盘预取 14:25 | `5f403ea5f0ca` V10尾盘搏高开 14:30 | `v10_tail_prefetch.json` | prefetch_time ≥ today 14:20 |
| `5b9f04f29dfe` V10全扫描 每15分 | `995192ae60fa` V10盘中盯盘 每30分 | `v10_watchlist.json` | scan_time within 10 min |
| `b00d3fde7beb` 资金面缓存 每30分 | 盯盘脚本/选股任务 | `capital_flow.json` | timestamp within 60 min |

## Lessons

1. **Producer failure must not silently propagate** — If the prefetch fails, the consumer must know and refuse to proceed
2. **Cache files should always contain a timestamp** — Every cache write must include `prefetch_time` or `timestamp` field
3. **Empty/stale cache is better than wrong cache** — If prefetch fails, write nothing (or write with a clear "failed" marker). Don't leave yesterday's data in place.
4. **User was trading on these recommendations** — This is not a theoretical data quality issue. Real money depends on data freshness.
