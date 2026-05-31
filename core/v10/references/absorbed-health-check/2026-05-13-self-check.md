# 2026-05-13 自检报告

## 已修复（2项）

### 1. v10_realtime_scan.py 板块排名日期硬编码
- **文件**: `~/.hermes/workspace/v10_realtime_scan.py` L530
- **问题**: `changes = table.get('涨跌幅:前复权[20260513]', [])` 日期硬编码
- **修复**: `today_str = datetime.now().strftime('%Y%m%d')` 动态生成
- **注意**: `from datetime import datetime` (不是 `import datetime`)

### 2. 实盘盯盘cron指向旧版脚本
- **任务**: `26daefd24af7` (实盘盯盘)
- **问题**: prompt中 `cd ~/.hermes/scripts && python3 v10_intraday_monitor.py` 指向旧版(纯腾讯)
- **修复**: 改为 `cd ~/.hermes/workspace && python3 v10_intraday_monitor.py` (含iFinD)

## 低优先级（不阻塞运行）

| 问题 | 文件 | 说明 |
|------|------|------|
| SSL全局禁用 | v10_realscan + intraday_monitor | 腾讯API用HTTPS+禁验证，功能正常但不安全 |
| sys重复import | v10_intraday_monitor.py L19+L26 | 冗余不报错 |
| vibe_tags字段缺失 | v10_intraday_monitor.py | 报告中Vibe标签永远为空（有保护不报错） |
| 两版脚本共存 | scripts/ vs workspace/ | 已统一cron指向workspace版 |

## Hermes版本缓存问题
- `hermes version` 显示 "489 commits behind" 但git pull是 "Already up to date"
- 原因: `~/.hermes/.update_check` 缓存文件过期
- 修复: `rm ~/.hermes/.update_check`
- 现在显示 "Up to date"
