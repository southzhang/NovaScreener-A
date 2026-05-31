# V10观察池文件路径与过期数据陷阱

## 背景

V10扫描系统由两个独立脚本组成：
- **v10_realtime_scan.py**（生产者）— 每30分钟全市场扫描，写入观察池JSON
- **v10_intraday_monitor.py**（消费者）— 每10分钟读取观察池，监控入场信号

两者通过共享的JSON文件 `v10_watchlist.json` 解耦。

## Bug 1: 路径不一致（2026-05-15发现）

**症状**：盯盘任务报告"观察池过期（生成于2026-05-14 14:36:14）"，但全扫描任务显示"ok"且一直在运行。

**根因**：
```python
# ❌ v10_realtime_scan.py 写入 /tmp/（重启后丢失，且不是盯盘脚本读取的路径）
wl_path = '/tmp/v10_watchlist.json'

# ✅ 修复：写入 workspace 目录
wl_path = os.path.expanduser('~/.hermes/workspace/v10_watchlist.json')
```

**教训**：生产者和消费者共享文件时，路径必须完全一致。`/tmp/` 目录重启后会被清空，不适合持久化数据。

## Bug 2: 空信号不更新文件（2026-05-15发现）

**症状**：全扫描命中0只股票时，观察池文件不更新，盯盘脚本无限期读取过期数据。

**根因**：原代码只在 `if results:` 分支写入文件，`else` 分支仅打印日志。

```python
# ❌ 原代码
if results:
    # ... 构建 watchlist ...
    with open(wl_path, 'w') as f:
        json.dump({...}, f)
else:
    log("📭 当前无V10信号")  # 文件不更新！

# ✅ 修复：else 分支也写入（清空观察池）
else:
    with open(wl_path, 'w') as f:
        json.dump({
            'scan_time': f"{date_str} {time_str}",
            'count': 0,
            'stocks': [],
        }, f, ensure_ascii=False, indent=2)
    log("📭 当前无V10信号（观察池已清空）")
```

**铁律**：生产者-消费者模式中，即使没有数据也要更新共享文件（或至少更新时间戳）。消费者需要区分"没有数据"和"数据过期"两种状态。

## 通用模式

任何通过文件解耦的 cron 任务对，检查清单：
1. ✅ 生产者和消费者的文件路径完全一致（用 `os.path.expanduser` 而非硬编码）
2. ✅ 生产者在无输出时也更新文件（清空 + 更新时间戳）
3. ✅ 消费者检查时间戳，区分"无数据"vs"过期数据"
4. ✅ 不用 `/tmp/` 存储持久化数据
