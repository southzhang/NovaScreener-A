# 尾盘选股任务：no_agent脚本 → Agent+MCP混合架构演进

## 架构演进历史

```
第一阶段(05-19上午): Agent全流程 → 慢(2-5min)
    ↓
第二阶段(05-19下午): no_agent脚本(v10_tail_prefetch.py) → 快但数据不全
    ↓
第三阶段(05-19晚): Agent预取(v10_tail_prefetch.md) + MCP实时查 → 快且全
```

## 第一代：纯Agent驱动（2026-05-19初）

14:30任务(`5f403ea5f0ca`)是LLM agent驱动：
1. 重新全市场扫描 → 约45s
2. iFinD MCP基本面验证 → 约15-30s
3. 挑TOP3候选 → 看板块风口
4. 输出推荐报告

**问题**：全流程2-5分钟，14:35才出结果，用户反映"推送太慢快收盘了"。

## 第二代：no_agent脚本预取（2026-05-19优化）

拆成两步：14:25 no_agent脚本(`v10_tail_prefetch.py`) + 14:30 agent分析(`5f403ea5f0ca`)

**no_agent脚本**：读缓存+腾讯行情，不依赖LLM，<3秒。
**14:30 agent**：读预取缓存做分析，不重新扫描。

**三个关键问题（05-19晚发现）**：
1. **candidates为空**：信号格式不匹配（上游写"全买入"，脚本用'★★★'判断）
2. **sectors/concepts=null**：东方财富push2板块API被VPN拦截(exit code 52)
3. **capital_flow仅含旧股**：缓存依赖其他cron任务

**修复**：信号格式兼容+实时API替代缓存依赖+时效校验——但东方财富全部失效后，板块数据仍为null。

## 第三代：Agent预取 + MCP实时查（B+C混合方案，2026-05-19晚落地）

### 核心变革：no_agent脚本 → Agent预取任务

14:25任务(`7fd58d356bcf`)从 `no_agent: true, script: v10_tail_prefetch.py` 改为 `no_agent: false, prompt: v10_tail_prefetch.md`。

### 架构对比

| 维度 | 第二代(no_agent脚本) | 第三代(Agent预取) |
|------|---------------------|-------------------|
| no_agent | `true` | `false` |
| 执行方式 | 脚本直接运行 | LLM agent驱动 |
| 数据源 | 腾讯行情+push2(被墙) | MCP实时查询 |
| 板块数据 | null（push2被墙） | ✅ MCP get_stock_info查所属板块 |
| 概念数据 | null | ✅ MCP search_news查概念热度 |
| 资金流数据 | 依赖旧缓存 | ✅ MCP get_stock_performance实时查 |
| 速度 | ~3秒 | ~10-15秒（含MCP调用） |
| 脚本状态 | 已备份到 backup/ | 不再被cron调用 |

### 关键配置变更

```json
// 14:25 任务（之前 no_agent: true, script 模式）
{
  "id": "7fd58d356bcf",
  "no_agent": false,
  "prompt": "~/.hermes/scripts/v10_tail_prefetch.md 的内容",
  "enabled_toolsets": ["terminal", "file", "mcp_ifind_stock", "mcp_ifind_news"],
  "script": ""  // 已清除
}

// 14:30 任务（prompt更新，告知预取数据来源）
{
  "id": "5f403ea5f0ca",
  "no_agent": false,
  "prompt": "已更新，提示：预取缓存包含MCP取得的板块/概念/资金面数据",
  "enabled_toolsets": ["terminal", "file", "skills", "mcp_ifind_stock", "mcp_ifind_news"]
}
```

### Cron Agent任务enabled_toolsets铁律

Agent cron任务必须显式设置 `enabled_toolsets` 包含 `mcp_ifind_stock` 和 `mcp_ifind_news`，否则MCP工具不可用。

| 场景 | enabled_toolsets | MCP可用性 |
|------|-----------------|-----------|
| 纯脚本任务(`no_agent: true`) | 不传或`[]` | N/A（脚本直接运行） |
| Agent任务需调MCP | `["mcp_ifind_stock", "mcp_ifind_news", ...]` | ✅ |
| Agent任务不调MCP | 不传或`[]` | ❌ 工具未注册 |
| 不传enabled_toolsets | `null` | 默认加载所有工具（含MCP）✅ |

### 预取Agent Prompt结构（v10_tail_prefetch.md）

```markdown
# 任务：14:25尾盘预取
时间：交易日14:25，当前日期 YYYY-MM-DD

## Step 1: 读取V10扫描结果
读取 ~/.hermes/cache/v10_watchlist.json
提取 scan_time（校验时效性）和 signals（按信号级别排序）

## Step 2: 用MCP补充数据
对每只候选股，用MCP查询：
- get_stock_info → 所属行业/概念
- get_stock_performance → 主力资金净流入(近3天)
- search_news → 近期新闻（正面/负面）

## Step 3: 写入预取缓存
写入 ~/.hermes/cache/v10_tail_prefetch.json
包含：candidates、sectors(从MCP取得)、concepts(从MCP取得)、
      capital_flow(从MCP取得)、prefetch_time
```

### 旧脚本备份

```bash
cp ~/.hermes/scripts/v10_tail_prefetch.py ~/.hermes/scripts/backup/
# scripts/目录下只剩 v10_tail_prefetch.md（agent prompt）
```

### 本次优化未解决的问题

1. **东方财富全部API被VPN拦截**(exit code 52)：push2、datacenter-web、新浪全部失效。唯一可连通：腾讯行情(qt.gtimg.cn, 496字节)和腾讯K线(web.ifzq.gtimg.cn)
2. **同花顺个股板块API返回404**：`d.10jqka.com.cn/stock/*/industry.json` 404，无法通过HTTP API查个股所属行业
3. **MCP是板块/概念数据的唯一可靠来源**：但MCP查询较慢（~10-15秒含网络延迟）
4. **24:00+后续 cron job run 异步不可追踪**：`cronjob action=run` 触发异步任务，当前session无法查看输出
5. **v10_tail_prefetch.md prompt内容**：agent按prompt执行预取后写入缓存。实际内容详见 `~/.hermes/scripts/v10_tail_prefetch.md`
