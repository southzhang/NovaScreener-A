# 2026-05-18 Hermes Venv Pandas 缺失事件

## 发现时间
用户 14:10 收到 V10 盘中盯盘推送，但观察池扫描于 10:59，间隔 3 小时 11 分钟。

## 症状
- V10 盘中盯盘 (995192ae60fa) 推送的股票涨幅（如康平科技 +8.4%）是基于 3 小时前价格
- 用户直接质疑："数据是不是严重失实了"
- 扫描缓存 `~/.hermes/cache/v10_watchlist.json` 的 scan_time 停留在 `2026-05-18 10:59:38`

## 排查过程
1. 检查 V10 全扫描 (5b9f04f29dfe) cron output → 所有 5/18 的 12 次运行都是 `Status: script failed`
2. 第 12 次 (14:56) 的 stderr 显示：`ModuleNotFoundError: No module named 'pandas'`
3. 手动跑 `/usr/bin/python3` → pandas OK
4. 手动跑 `~/.hermes/hermes-agent/venv/bin/python3` → **pandas 缺失！**
5. 确认：Hermes cron runner 执行 `no_agent` 脚本时用的是自己的 venv，不是系统 Python

## 10:59 的缓存哪来的？
当天手动跑过一次系统 Python 版本的扫描，那次成功了（pandas 可用），写了缓存文件。
之后 cron 所有运行失败，缓存从未更新。

## 影响范围
- **唯一受影响**：V10 全扫描 (5b9f04f29dfe)，脚本 `v10_realtime_scan.py`，依赖链中有 pandas
- **衍生影响**：V10 盘中盯盘 (995192ae60fa) 读到过期缓存，推送过时信息
- **未受影响**：实盘盯盘 (26daefd24af7)、资金面缓存 (b00d3fde7beb) 都是 agent 模式，不依赖 venv

## 修复
```bash
~/.hermes/hermes-agent/venv/bin/python3 -m pip install pandas
# Successfully installed pandas-3.0.3
```

## 防御措施
1. 新增脚本依赖时，必须给 Hermes venv 安装
2. 部署新脚本后，用 venv Python 手动跑一次验证
3. 在自检清单中加入 "venv 依赖完整性检查"
4. 在无数据也不跳过（空扫描也写缓存文件），防止消费者用过期数据
