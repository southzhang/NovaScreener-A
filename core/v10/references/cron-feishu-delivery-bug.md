# 飞书 Cron 推送 Bug 与排查记录

## Bug: "cannot schedule new futures after interpreter shutdown"

### 现象
- cron scheduler 日志显示 "delivered to feishu via live adapter" ✅
- 但用户实际未收到飞书消息
- 部分轮次报错: `delivery error: Feishu send failed: cannot schedule new futures after interpreter shutdown`

### 根因
`scheduler.py:588` 用 `asyncio.run_coroutine_threadsafe()` 把飞书发送调度到 gateway 事件循环。cron session 结束太快（Python interpreter shutdown），asyncio 无法调度新任务。

**两层问题：**
1. **误报 "delivered"**: `scheduler.py:617` 检查 send_result 的 success 属性默认 True，如果返回 None 也认为成功
2. **interpreter shutdown**: cron session 生命周期与 asyncio 事件循环不同步

### 排查路径
```
1. agent.log → 确认 "delivered to feishu via live adapter" 日志
2. gateway.log → 检查 "[Feishu] Sending response" 是否存在（cron 路径不走这个）
3. scheduler.py 源码 → 追踪 _deliver_result() 的 live adapter 路径
4. 确认是 gateway 代码 bug，非用户配置问题
```

### Gateway 重启能否修复？
**不能。** 这是代码层面的时序问题，重启只重置状态不改代码。

### 临时解决方案
1. **手动推送**: `python3 ~/.hermes/scripts/feishu_direct_push.py "消息内容"`
   - ⚠️ 需要 bot 在飞书中被加入群聊才能发
   - 当前 bot (cli_a97352262f389cc6) 不在任何群里，HTTP API 推送失败
2. **在会话中手动输出报告**: cron 跑完后手动在 feishu 会话中输出
3. **等官方修复**: 向 Hermes GitHub 提 issue

### 飞书直接推送脚本
位置: `~/.hermes/scripts/feishu_direct_push.py`
用法: `python3 feishu_direct_push.py "消息内容"`
依赖: `~/.hermes/.env` 中的 FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_HOME_CHANNEL
前提: bot 需要在目标群聊中（通过飞书开发者后台或群设置添加）

### Gateway 源码定位（05-14深入排查）

**`cron/scheduler.py` _deliver_result() 函数（line 482-656）：**

1. **Live adapter 路径（line 577-624）：**
   ```python
   # line 581: 检查 loop 是否运行
   if runtime_adapter is not None and loop is not None and getattr(loop, "is_running", lambda: False)():
       # line 588: 调度到 gateway 事件循环
       future = asyncio.run_coroutine_threadsafe(
           runtime_adapter.send(chat_id, text_to_send, metadata=send_metadata),
           loop,
       )
       send_result = future.result(timeout=60)  # line 593
       # line 597-598: 检查成功状态
       if send_result and not getattr(send_result, "success", True):  # ← 默认 True！
           adapter_ok = False  # 只有明确失败才走 standalone
   # line 617-618: 如果 adapter_ok，记录 "delivered"
   if adapter_ok:
       logger.info("Job '%s': delivered to %s:%s via live adapter", ...)
       delivered = True
   ```

2. **Standalone 路径（line 626-653）：**
   ```python
   if not delivered:
       coro = _send_to_platform(...)
       try:
           result = asyncio.run(coro)  # ← 这里报 interpreter shutdown
       except RuntimeError:
           # fallback to ThreadPoolExecutor
           with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
               future = pool.submit(asyncio.run, _send_to_platform(...))
               result = future.result(timeout=30)  # ← 也可能报错
   ```

**关键发现：**
- Live adapter 路径的 `getattr(send_result, "success", True)` 默认值为 True → 即使 send 返回 None 也认为成功
- `asyncio.run_coroutine_threadsafe` 在 interpreter shutdown 时抛 RuntimeError
- `asyncio.run()` 在已有 running loop 时也抛 RuntimeError
- Gateway 重启**不能**修复此问题（是代码逻辑 bug，非状态问题）

### 飞书直推脚本测试结果（05-14）

**脚本**: `~/.hermes/scripts/feishu_direct_push.py`

**测试结果：**
| 方式 | API返回 | 用户收到？ |
|------|---------|-----------|
| HTTP API + chat_id (群聊) | code:0, success | ❌ |
| HTTP API + open_id (私聊) | code:0, success | ❌ |
| lark_oapi SDK + chat_id | success:True, code:0 | ❌ |

**根因**：`GET /im/v1/chats` 返回 `items: []` — bot不在任何chat中。HTTP API发送虽然返回成功，但消息可能被飞书过滤或投递到机器人专属区域。

**对比**：Gateway通过websocket连接可以正常收发消息（用户全天正常聊天），但HTTP API路径需要bot在chat中才能投递。

### 影响范围
所有 `deliver: feishu` 的 cron 任务都可能受影响，尤其是：
- 实盘盯盘 (26daefd24af7)
- V10盘中盯盘 (995192ae60fa)
- 选股任务 (bea10c4a52f9, f6ddabdafca8, 5f403ea5f0ca)
