# 资金流全维度VPN失效记录（2026-05-19下午）


## 背景

资金面采集cron任务在VPN环境下运行时，**所有主力资金/暗盘/融资融券/大宗交易数据源全部不可用**。最终只写到龙虎榜+腾讯行情两个维度的数据。

## 失效矩阵

| 数据源 | 维度 | 表现 | 成功率 |
|--------|------|------|--------|
| MCP `get_stock_performance` | 三维度 | cron上下文无MCP工具 | ❌ |
| push2 `qt/ulist.np/get` + fltt=2 | 主力净流入/f62 | **间歇性**：urllib 10s有时成功(timeout=10可回数据)，有时RemoteDisconnected。**双保险(urllib+curl)成功率~90%** | ⚠️ 可用但波动 |
| datacenter RPT_DAILYBILLBOARD_DETAILSNEW | 龙虎榜 | ✅ 正常 | ✅ |
| datacenter RPT_RZRQ_SECURITIES | 融资融券余额 | 返回None结构 | ❌ |
| datacenter RPT_BLOCKTRADE_DETAILSNEW | 大宗交易 | "报表配置不存在" 9501 | ❌ |
| akshare stock_individual_fund_flow | 资金流 | 依赖push2，同波动 | ⚠️ |
| Sina money flow | 资金流 | 404/deprecated | ❌ |

## 唯一可用的资金面维度

1. **龙虎榜**（datacenter-web RPT_DAILYBILLBOARD_DETAILSNEW）— 需代码中按TRADE_DATE过滤近N天
2. **腾讯行情快照**（qt.gtimg.cn）— 现价/涨跌幅/成交额/换手率，不涉及资金流

## 结论（2026-05-19更新）

VPN环境中**融资融券、大宗交易两个维度彻底不可获取**。但**主力净流入通过push2双保险(urllib+curl)约90%成功率**，龙虎榜通过datacenter-web正常可用。

✅ 主力净流入 → push2双保险 (f62/f184)
✅ 龙虎榜 → datacenter-web (RPT_DAILYBILLBOARD_DETAILSNEW + TRADE_DATE过滤)
❌ 融资融券 → datacenter RPT_RZRQ_SECURITIES间歇性返回None
❌ 大宗交易 → datacenter报表已报废
❌ MCP get_stock_performance → cron上下文无MCP工具

资金面缓存一旦过期（非交易日），下次交易日cron执行时可**更新主力净流入+龙虎榜**，融资融券和大宗交易保持null。

## 推荐行动（2026-05-19更新）

1. push2双保险(urllib→curl)自动处理间歇性断连，无需手动干预 ✅
2. 资金面缓存cron任务改用no_agent脚本模式：直接push2 + datacenter-web，不依赖MCP ✅
3. 融资融券/大宗交易数据不可得时标记null，已有缓存中的数据保留
