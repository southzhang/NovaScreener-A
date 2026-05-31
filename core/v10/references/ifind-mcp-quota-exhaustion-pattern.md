# iFinD MCP 额度耗尽级联故障模式（2026-05-22发现）

## 症状

资金面缓存刷新 cron 任务（b00d3fde7beb）返回 403 错误：

```
RuntimeError: Error code: 403 - {'error': {'message': 'User quota is exhausted, please recharge',
 'type': 'Iapi_error'}}
```

## 与 HTTP API 额度的区别

| 维度 | HTTP API | MCP |
|------|----------|-----|
| 计费 | 按端点/记录数（各端点独立配额） | **统一额度**（所有MCP调用共享） |
| 错误码 | 不同端点返回不同错误 | 统一 `403 Iapi_error: quota exhausted` |
| 额度恢复 | 每月1日重置 | 需手动充值/联系客服 |
| 监控 | 代码中可统计 | 只有运行时错误才能发现 |

## 级联影响

```
MCP 额度耗尽
  ↓
资金面缓存刷新失败 (b00d3fde7beb)
  → capital_flow.json 停止更新
  → 过期数据被保留/不更新
  ↓
V10 全扫描 资金面验证 (5b9f04f29dfe)
  → 缓存未命中 → 尝试HTTP API实时查
  → HTTP API snap_shot 不含资金流字段
  → 降级通过/排除，标注"资金面待验证"
  ↓
盯盘报告/选股推荐
  → 资金面数据为旧/空
  → 推荐可靠性下降
```

## 诊断步骤

1. **确认是否是 MCP 额度问题**：
   ```
   grep "quota exhausted" ~/.hermes/cron/output/b00d3fde7beb/*.md
   ```

2. **确认影响的 cron 任务范围**：
   ```bash
   # 哪些任务依赖 MCP
   grep -l "mcp_ifind" ~/.hermes/cron/jobs.json
   ```

3. **检查 V10 扫描是否受影响**：
   ```bash
   grep -l "资金面无数据\|降级通过\|待验证" ~/.hermes/cron/output/5b9f04f29dfe/*.md
   ```

## 影响范围分析

**直接影响任务**（使用 MCP 进行资金面/基本面查询）：
| Job ID | 名称 | 影响 |
|--------|------|------|
| b00d3fde7beb | 资金面三维度缓存刷新 | **直接失败** ❌ |
| 5b9f04f29dfe | V10全扫描（no_agent脚本） | ⚠️ 资金面验证降级（脚本有自己的iFinD HTTP API，独立于MCP） |
| 90890e1b5e47 | 实盘盯盘-持仓监控 | ⚠️ 持仓MCP分析降级 |
| e2172fd4cc89 | 实盘每日复盘 | ⚠️ 当日分析无法用MCP查基本面 |

**间接影响**：
- V10 扫描 → 资金面验证降级 → 信号可靠性下降
- 实盘盯盘 → 持仓资金面数据不可用
- 每日复盘 → 基本面分析无法更新

## 解决方案

1. **联系 iFinD 充值**（唯一根治方案）
2. **临时降级策略**（额度恢复前）：
   - V10 全扫描跳过资金面验证，仅做基本面过滤
   - 实盘盯盘改用 HTTP API basic_data_service 查简单指标
   - 资金面缓存用 push2 批量 API 替代（`f62` 字段查主力净流入）
3. **长期规避**：控制 MCP 调用频率，不要在短时间内（<30分钟）让多个 cron 任务同时调 MCP

## 预防性监控

在 ifind-token-refresh cron（211fd36abfea）中增加 quota 检测：

```python
# 检测 MCP 是否返回 quota 耗尽
import json, urllib.request
try:
    # 尝试一次 MCP 查询，验证是否可用
    ...
except Exception as e:
    if "quota exhausted" in str(e):
        print("⚠️ iFinD MCP 额度耗尽，请充值")
```

## 变体：Per-User 限速（"用户使用工具已超限"，2026-05-26发现）

**与 quota exhausted 不同**：这是另一种 MCP 限流模式，不是 403 错误。

**症状**：
```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "answer": "用户使用工具已超限 "
  }
}
```
- HTTP 状态码 **200**（不是 403）
- `code: 1`（不是 0）
- 错误信息为 **中文**："用户使用工具已超限"
- 而非英文 "quota exhausted"

**推测根因**：这是 iFinD MCP 的 **per-user 频率限制**（rate limiting），与 account-level 月度额度无关。可能是：
- 对单个用户短时间内的 API 调用频率有限制（如 X 次/分钟）
- 会在短时间内自动恢复（典型 rate limit 行为）

**诊断**：Quota exhausted 返回 403 + 英文错误；而本变体返回 200 + 中文"用户使用工具已超限" + code:1。两者可通过状态码+错误信息区分。

**应对**：
1. 等待 1-2 分钟后再试（rate limit 通常会自动解除）
2. 如果反复出现，减少批处理密度（如把每批 ≤6 只股票进一步降到 ≤3 只）
3. 降级到 capital_flow.json 缓存或 push2 批量 API（见主 skill 的降级方案）

## 历史记录

| 日期 | 事件 | 持续时间 | 影响 |
|------|------|----------|------|
| 2026-05-22 10:22 | 首次发现 MCP quota exhausted | 待确认 | 资金面缓存刷新任务失败 |
| 2026-05-26 15:52 | 发现 MCP 返回"用户使用工具已超限"(非403) | 短时（推测rate limit） | 海兰信300065主力净流入查询失败，走缓存capital_flow.json降级 |
