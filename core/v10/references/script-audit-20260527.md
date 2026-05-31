# 脚本审计工作流（2026-05-27）

## 背景

用户要求检查所有在用脚本的逻辑问题和报错。使用Claude Code进行批量审计，发现并修复了多个严重Bug。

## 审计方法

### Step 1: 收集在用脚本
```bash
hermes cron list 2>&1 | grep "Script:" | awk '{print $2}' | sort -u
```

### Step 2: 使用Claude Code审计
```bash
cd ~/.hermes/scripts && claude --print "请检查以下5个Python脚本，找出逻辑问题、潜在报错和性能问题：
1. v10_intraday_monitor.py
2. v10_realtime_scan.py  
3. v10_tail_prefetch.py
4. refresh_capital_flow.py
5. ifind_refresh_token.py
对每个脚本列出问题和修复建议，最后汇总哪些需要立即修复。"
```

### Step 3: 验证修复
```bash
cd ~/.hermes/scripts && python3 <script_name>.py
```

## 发现的问题（2026-05-27）

### P0 - 必须立即修复
| 脚本 | 问题 | 修复 |
|------|------|------|
| v10_tail_prefetch.py:50 | PROXIES变量未定义 | 添加 `PROXIES = {}` |
| v10_tail_prefetch.py:114 | 字段索引错误 | `safe_float(50)` → `safe_float(49)` |
| v10_tail_prefetch.py:210 | 除零bug | 添加 `if high != low` 保护 |

### P1 - 当天修复
| 脚本 | 问题 | 修复 |
|------|------|------|
| v10_realtime_scan.py:54 | 全局禁用SSL | 改为仅iFinD使用自定义context |
| ifind_refresh_token.py:16 | JWT硬编码 | 改为环境变量读取 |

## 脚本清单（2026-05-27）

| 脚本 | 用途 | 调度 |
|------|------|------|
| v10_intraday_monitor.py | V10盘中盯盘 | 每30分钟 |
| v10_realtime_scan.py | V10全市场扫描 | 每15分钟 |
| v10_tail_prefetch.py | V10尾盘预取 | 14:20 |
| refresh_capital_flow.py | 资金面缓存刷新 | 每30分钟 |
| ifind_refresh_token.py | iFinD token刷新 | 每3天 |

## 关键教训

1. **PROXIES变量必须模块级定义** — 不能在函数调用时才引用
2. **腾讯API field索引是1-based** — field[50]对应parts[49]
3. **除零保护必须有** — 特别是价格计算（high==low时）
4. **SSL context按域隔离** — 不同API可能需要不同的SSL配置
5. **JWT token不能硬编码** — 必须从环境变量读取
