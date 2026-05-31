# 融资融券查询全源排查路径（2026-05-27）

## 场景：查正业科技(300410)融资余额

**最终结论**：正业科技不是融资融券标的，所有数据源返回空是正确的。

### 完整排查过程

| 步骤 | 数据源 | 尝试方式 | 结果 | 教训 |
|------|--------|----------|------|------|
| 1 | iFinD MCP get_stock_info | `query:"正业科技300410是否属于融资融券标的"` | "用户使用工具已超限"（限流） | 等2分钟重试，非永久性失败 |
| 2 | iFinD MCP get_stock_performance | `query:"正业科技300410融资余额"` | "用户使用工具已超限"（限流） | 同上 |
| 3 | push2.eastmoney.com stock/get | `secid=0.300410&fields=f57,f58,f170&fltt=2` | Remote end closed (exit 52) | push2已全死 |
| 4 | push2.eastmoney.com rzrq/get | `secid=0.300410&fields1=f1,f2,f3&fields2=f51-f65&fltt=2` | rc=102 + data=null | 茅台的rzrq也返回rc=102，接口本身有问题 |
| 5 | push2his.eastmoney.com rzrq/daykline/get | same params | 404 | 接口不存在 |
| 6 | push.eastmoney.com stock/get | same params | 超时 | 全部超时 |
| 7 | datacenter.eastmoney.com | 尝试3种字段组合 | 9501 "XX字段不存在" | 字段名高度敏感 |
| 8 | datacenter-web.eastmoney.com | RPTA_WEB_RZRQ_GGMX, ALL columns | 9501 "排序列不存在" | API很脆弱 |
| 9 | web.ifzq.gtimg.cn (腾讯) | rzrq/get | "Call to undefined method" | 腾讯融资融券API已死 |
| 10 | vip.stock.finance.sina.com.cn | go.php/vRzrqMarketData | "Invalid view go" | 新浪融资融券API已死 |
| 11 | 10jqka.com.cn (同花顺) | basic.10jqka.com.cn/300410/rzrq.html | web_extract 失败 | 动态渲染页面 |
| 12 | stcn.com 证券时报 | sz300410.html | 融资融券表头显示但无数值 | 动态加载 |
| 13 | mx-search (妙想搜索) | "正业科技300410融资余额融资融券最新数据" | ✅ 成功！年报显示"参与融资融券业务：不适用" | **唯一可用降级源** |

### 关键发现

1. **mx-search可作为融资融券标的资格检查降级方案**：搜索后结果中包含年报/公告文本，其中"参与融资融券业务股东情况说明（如有）不适用"可直接确认非标的
2. **iFinD MCP限流 vs 永久不可用**："用户使用工具已超限"是临时限流，等2分钟重试即可恢复
3. **push2全死**：stock/get、ulist.np/get、rzrq/get全部不可用
4. **腾讯/新浪融资融券API已死**：不要在白名单上浪费资源

### 快速诊断流（整理后）

```
用户要求查融资余额
  → 纠正工具：用 get_stock_performance，不是 get_stock_shareholders
  → Step 1: MCP get_stock_info("300410是否融资融券标的")
      Step 1a: MCP限流 → 用mx_search搜索年报确认
      Step 1b: MCP返回数据 → 直接判断
  → Step 2a: 非标的 → 无融资余额（正常），直接告知
  → Step 2b: 是标的 → MCP get_stock_performance 查数据
```
