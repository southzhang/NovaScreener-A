# 脚本版本一致性审计检查清单（2026-05-16确立）

## 触发条件
- 策略参数改动后
- 回测发现新退出信号/入场条件后
- 脚本文件头版本号与实际参数不符时

## 检查清单

### 1. 脚本参数一致性
```bash
grep -n "volume_ratio\|channel_width\|hard_stop\|trailing" ~/.hermes/workspace/v10_auto_trade.py ~/.hermes/workspace/v10_scan_strict.py ~/.hermes/workspace/v10_realtime_scan.py
```

### 2. 版本声明一致性
```bash
grep -rn "V3\.4\|V5\.1" ~/.hermes/workspace/v10_auto_trade.py ~/.hermes/workspace/v10_scan_strict.py ~/.hermes/workspace/v10_realtime_scan.py ~/.hermes/workspace/v10_intraday_monitor.py
```

### 3. 退出信号完整性
回测发现的每个退出信号，必须在 `check_sell_signals()` 中实现：
- ✅ 硬止损-6%
- ✅ 移动止盈（涨10%回落3%）
- ✅ 通道死叉（MA26上穿MA7）
- ✅ 破隧道（收盘<EMA144或<EMA169）
- ✅ MACD死叉（DIF下穿DEA）— 2026-05-16补上

### 4. Cron prompt描述一致性
```bash
grep "V3\.4\|V5\.1\|移动止盈.*5%\|移动止盈.*3%" ~/.hermes/cron/jobs.json
```

### 5. 语法验证
```bash
python3 -c "import py_compile; py_compile.compile('path/to/script.py', doraise=True)"
```

## 已知修复记录
| 日期 | 脚本 | 问题 | 修复 |
|------|------|------|------|
| 2026-05-16 | v10_auto_trade.py | 缺MACD死叉退出 | 添加★MACD死叉信号 |
| 2026-05-16 | v10_auto_trade.py | 注释写V3.4 | 改为V5.1 |
| 2026-05-16 | v10_realtime_scan.py | backtest函数缺MACD死叉 | 添加退出逻辑 |
