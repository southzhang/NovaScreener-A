# 数据源脚本代码审查报告（2026-05-13 Claude Code）

审查范围：`~/.hermes/scripts/` 下6个数据源相关脚本。

## 🔴 严重问题（P0/P1）

### ifind_http_api.py
- **Token缓存无文件锁**：多进程并发时竞态条件，可能读到半写入JSON
- **`_refresh_access_token` 返回值被丢弃**：刷新失败后静默用无效token发请求
- **`_post` 不检查HTTP状态码**：401/500时JSON解析失败，真实错误被吞
- **`pd.json_normalize` 对嵌套table结构处理不符预期**：`tables[].table`嵌套字典变成一个列而非展开

### v10_realtime_scan.py
- **无iFinD降级**：文档承诺双数据源但实际只有腾讯单源，腾讯故障时完全无降级
- **`errors`计数器无锁**：多线程下裸递增
- **K线获取静默吞错**：所有异常返回None无日志

### v10_intraday_monitor.py
- **成交额单位未确认**：腾讯`parts[37]`是元还是万元？5000阈值可能偏差100倍
- **股票代码前缀bug**：ETF可能静默丢失

### intraday_holdings_monitor.py
- **SSL验证全局关闭**：`verify_mode = CERT_NONE`，中间人可篡改行情
- **持仓列表与其他脚本不同步**：差4只股票（凯龙/翰宇/君禾/南风）

### ifind_holdings_analysis.py
- **AUTH_TOKEN硬编码在源码中**：Token泄露风险，应改环境变量

### realtime_quotes.py
- **`urlopen`无异常捕获**：网络超时时直接崩溃

## 🟡 中等问题

| 脚本 | 问题 |
|------|------|
| ifind_http_api.py | `financial_trend`只处理`tables[0]`，多股票静默丢数据 |
| v10_realtime_scan.py | 线程数日志写10实际15；全市场枚举2万代码效率低 |
| v10_intraday_monitor.py | 7%追高阈值一刀切不区分板块；信号if-return链命中即返回 |
| intraday_holdings_monitor.py | 集合竞价9:15-9:25误判为交易时间 |
| ifind_holdings_analysis.py | MCP错误文本直接混入正常数据无区分 |

## 修复状态（2026-05-13已全部修复 ✅）

### P0 已修复
- ✅ Token硬编码 → 环境变量 `IFIND_MCP_JWT`（.env自动读取）
- ✅ SSL关闭 → 删除自定义context，使用系统默认SSL
- ✅ data_pool outputpara → 空值警告+错误提示

### P1 已修复
- ✅ Token缓存 → `threading.Lock()` 保护，双重检查锁定
- ✅ 刷新失败 → 返回False，调用方处理（打印警告）
- ✅ _post → 检查HTTP状态码，401自动重试
- ✅ 线程数日志 → 10→15统一
- ✅ 非交易时间 → 加日志说明
- ✅ 688过滤 → 删除无效死代码
- ✅ errors计数器 → 加Lock

### P2 已修复
- ✅ SSL删除（v10_intraday_monitor）
- ✅ 股票代码前缀 → 加注释确认逻辑正确
- ✅ 成交额单位 → 加注释确认万元
- ✅ 追高阈值 → 创业板15%/ST4%/其他7%
- ✅ urlopen异常 → 加try/except（realtime_quotes）
- ✅ 持仓列表 → 11只同步（ifind_holdings_analysis）

### 未修复（低优先级/设计选择）
- 🟡 pd.json_normalize嵌套table → 当前返回格式可接受，暂不改
- 🟡 financial_trend只处理tables[0] → 单股票调用，不影响
- 🟡 集合竞价时段 → 9:15-9:25不操作，影响不大
- 🟡 MCP错误文本混入 → 下游已有errorcode检查
