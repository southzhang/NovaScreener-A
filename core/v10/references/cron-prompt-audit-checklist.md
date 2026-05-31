# Cron Prompt 审计清单

## 何时需要审计
改了策略参数/skill文档后，必须逐一检查所有引用该策略的cron任务prompt，确认参数同步。

## 典型问题模式（05-14实测）

### 模式1：参数不同步
- skill文档：移动止盈 0.97（回落3%）
- cron prompt：仍是 0.95（回落5%）
- **根因**：改skill不会自动改prompt

### 模式2：引用不存在的脚本参数
- cron prompt：`python3 v10_auto_trade.py --scan-only`
- 实际脚本：只有 `--periodic` 和 `--sell-only`
- **根因**：copy-paste错误，或旧版参数残留

### 模式3：macOS反模式
- cron prompt：`timeout 120 python3 ...`
- macOS：`timeout`命令不可用（GNU coreutils）
- **根因**：Linux思维带到macOS

## 审计步骤

1. **列出所有启用的cron任务**
2. **对照skill文档逐项检查每个prompt**：
   - 策略参数（止损/止盈/通道宽度）是否与skill一致
   - 脚本路径是否正确
   - CLI参数是否有效
   - 是否有macOS反模式（timeout/gtimeout）
   - 持仓列表是否最新
   - 数据源架构是否与当前一致
3. **修复后重启gateway**让改动生效
4. **验证**：读取修改后的prompt确认改动已写入

## 铁律
改策略参数时必须grep所有cron prompt确认同步。
