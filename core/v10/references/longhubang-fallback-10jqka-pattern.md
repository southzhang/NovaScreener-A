# 龙虎榜数据获取策略（2026-05-22更新）

## 数据源对比

| 数据源 | 方式 | 状态 | 说明 |
|--------|------|------|------|
| **iFinD MCP get_stock_performance** | MCP协议 | ✅ 首选，数据最全 | query="XX近5天 龙虎榜 上榜次数 买入额 卖出额" |
| **东方财富 datacenter-web** | REST API | ❌ 2026-05-22确认全部报废 | 所有RPT_LHB_*/RPT_BILLBOARD_* report name均返回9501"报表配置不存在" |
| **同花顺 10jqka** | web_extract | ⚠️ 静态HTML页面可抓取历史全量数据，但无当日数据（日频，15:05后更新） | **2026-05-26实测**：`data.10jqka.com.cn/market/lhbgg/code/XXXXXX` 页面web_extract可获取完整历史龙虎榜（含日期/类型/净买卖额），数据截至上一交易日所有历史记录。不适用于查"今天是否上榜"这类实时场景。|
| **搜狐证券** | API | ❌ enconding乱码+JS渲染 | 页面编码问题，数据不可用 |
| **新浪财经** | API/页面 | ❌ 龙虎榜接口失效 | "Invalid view go" |
| **Akshare** | Python包 `stock_lhb_detail_em()` | ✅ **2026-05-22实测可行** — 全市场龙虎榜数据，含代码+名称+上榜日期+买入额+卖出额+净额+上榜原因等完整字段。需指定起止日期，返回DataFrame | `start_date="20250515", end_date="20250522"` 返回520行 |

## iFinD MCP查询方式

```python
mcp_ifind_stock_get_stock_performance(
    query="德尔股份300473最近5天的龙虎榜上榜次数和龙虎榜买入额、龙虎榜卖出额"
)
```

**注意**：默认返回52周累计数据（不是5天）。需要在代码中按TRADE_DATE过滤：
```python
cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
# 只取 cutoff 之后的记录
```

## 2026-05-22实测：全部东财LHB接口报废

当日对300473德尔股份的所有东财API尝试均失败：

```
RPT_LHB_DETAIL          → 9501 报表配置不存在
RPT_LHB_LHBJJ           → 9501
RPT_LHB_F10             → 9501
RPT_LHB                 → 9501
RPT_F10_LHB             → 9501
RPT_BILLBOARD_F10       → 9501
RPT_BILLBOARD_DETAIL    → 9501
RPT_LHB_INDIVIDUAL      → 9501
RPT_BILLBOARD_INDIVIDUAL→ 9501
RPT_LHB_MX_TJ           → 9501
RPT_LHB_F10_DETAIL      → 9501
RPT_LHB_F10_PROBATION   → 9501
RPT_LHB_MX_DETAIL       → 9501
RPT_LHB_F10_DETAIL_NOTS → 9501
RPT_LHB_F10_LHB_JJ      → 9501
RPT_EAM_BILLBOARD_DETAIL→ 9501
RPT_EAM_BILLBOARDSUMMARY→ 9501
RPT_BILLBOARD_DAILYDETAIL       → 9501
RPT_BILLBOARD_DAILYBILLBOARDDETAIL → 9501
RPTF10_BILLBOARD_DETAIL         → 9501
RPTF10_BILLBOARDSUMMARY         → 9501
```

**结论**：东方财富整个datacenter-web的龙虎榜API体系已全面下线。之前报告的 `RPT_DAILYBILLBOARD_DETAILSNEW`（还在可用清单里）也已失效。降级路径只剩iFinD MCP。

## 当iFinD MCP也不可用时

### 替代方案1：web_search搜新闻
```python
r = web_search(query="德尔股份 300473 龙虎榜 2026", limit=5)
# 搜索结果可能包含历史上榜报道
```

### 替代方案2：直接查东财龙虎榜页面
```python
url = "https://data.eastmoney.com/stock/lhb/lcsb/300473.html"
# 注意：页面JS动态渲染，web_extract只能拿到模板HTML，拿不到表格数据
# 实际数据通过 ajax 接口加载
```

### 替代方案3：使用东方财富龙虎榜H5版
```python
url = "https://wap.eastmoney.com/a/202503033334804524.html"
# 历史龙虎榜新闻报道，可以在搜索中找到
```

## iFinD MCP限流错误："用户使用工具已超限"

**2026-05-27发现**：iFinD MCP 返回的限流错误消息**有不同版本**，不能一概按 403 "quota exhausted" 处理：

| 错误消息 | 含义 | 处理方式 |
|----------|------|----------|
| `Iapi_error: quota exhausted` | MCP统一额度耗尽（403） | 所有MCP工具不可用，降级到其他数据源 |
| `用户使用工具已超限` | 当前会话/短时间内调用频率过高 | **非永久限流**，等待几分钟再试，或换查询方式（简化query、减少参数量） |

### 限流失效后的完整诊断路径

当 get_stock_performance 返回"用户使用工具已超限"时：

```
Step 1: 等2分钟后重试一次（简化为单只股票查询，不加日期范围词）
  ├── 成功 → 返回数据
  └── 仍超限 → Step 2

Step 2: 跳过iFinD MCP，直接走web层
  ├── web_search("300410 龙虎榜 上榜") → 查看搜索结果中的日期和摘要
  │   └── 同花顺结果中提到的上榜日期可确认上榜次数
  ├── 同花顺10jqka页面 web_extract → 获取完整历史记录
  │   URL: data.10jqka.com.cn/market/lhbgg/code/{code}
  │   └── 从表格中按日期筛选统计上榜次数、买卖净额
  └── 两路取交集 → 得到完整龙虎榜记录

Step 3: 同花顺页面提取数据后，手动统计：
  ├── 近1年次数 = 统计2025-05至当前
  ├── 近3年次数 = 统计2023至当前
  ├── 总历史上榜次数 = 所有记录计数
  └── 最近一次明细 = 日期 / 买入额 / 卖出额 / 净额 / 上榜原因
```

### 2026-05-27实测案例：正业科技(300410)

iFinD MCP 返回"用户使用工具已超限"后，完整降级流程：

1. `web_search("正业科技 300410 龙虎榜 上榜次数 2025 2026")`
   → 搜索结果中证券时报报道提到2025-09-04涨停(+20%)，龙虎榜详细数据

2. `web_extract("https://data.10jqka.com.cn/market/lhbgg/code/300410")`
   → 返回完整历史龙虎榜表格，从2015年至2025年所有记录

3. 统计结果：
   - 近1年上榜：2次（2025-09-04+20%涨停, 2025-09-05换手30%）
   - 历史累计：约40+次（2015年上市以来）
   - 2025-09-04明细：买入16556万，卖出4792.90万，净买入11763.10万

## 当前结论（2026-05-27更新）

1. **iFinD MCP 是唯一可靠的龙虎榜数据源**，当它断连或限流时需降级
2. **iFinD限流有两种表现**：403 "quota exhausted"（永久性，当天不可恢复） vs "用户使用工具已超限"（临时性，等几分钟再试）
3. **同花顺 10jqka web_extract 是iFinD MCP限流时的最佳降级方案**——可获取完整历史全量数据，比Akshare更稳定（不受VPN影响），但无法实时查询当日是否已上榜
4. **Akshare stock_lhb_detail_em()** 在VPN环境下仍可用（2026-05-22实测），但受网络环境影响
5. **web_search 搜索结果中的新闻报道**可提供某次具体上榜的快速摘要，适合快速确认某日是否有龙虎榜异动
6. 东方财富数据中心的龙虎榜report name已全部失效，无需再试

## 使用Akshare查询龙虎榜（2026-05-22实测方案）

### 安装检查
```python
import akshare as ak
# 确保已安装: pip install akshare
```

### 查询全市场龙虎榜（按日期范围）
```python
import akshare as ak

# 返回DataFrame，字段包括：
# 代码, 名称, 上榜日, 收盘价, 涨跌幅%, 换手率%,
# 龙虎榜买入额(万), 龙虎榜卖出额(万), 龙虎榜净额(万),
# 龙虎榜买入额占比%, 上榜原因等

df = ak.stock_lhb_detail_em(
    start_date="20250515",
    end_date="20250522"
)
```

### 按股票代码过滤
```python
df_filtered = df[df["代码"] == "301026"]
# 如果为空，说明该期间未上榜
```

### 聚合统计（近N天）
```python
df_recent = df[df["代码"] == code]
count = len(df_recent)                              # 上榜次数
buy_total = df_recent["龙虎榜买入额"].sum()          # 总买入额(万)
sell_total = df_recent["龙虎榜卖出额"].sum()          # 总卖出额(万)
net_total = df_recent["龙虎榜净额"].sum()             # 总净额(万)
```

### 注意事项
- `start_date` 和 `end_date` 格式为 `YYYYMMDD`（字符串）
- 返回数据是全市场的，代码过滤在获取后进行
- VPN环境下**可能失败**（akshare底层走urllib，受代理影响）。若失败则切回iFinD MCP或web_search
- 2026-05-22实测：Akshare在VPN开启环境下成功返回520行数据
- akshare版本兼容性：stock_lhb_detail_em接口签名稳定（截至2026-05-22）

## 近5天无龙虎榜时的判断

中小盘股上榜频率低，近5天无上榜是正常现象。判断标准：
- 近5天无上榜 → 正常，不代表资金面异常
- 但需关注其他维度：主力净流入、大宗交易、融资融券
- 如同时出现"大幅涨幅(>10%) + 高换手(>15%) + 但无龙虎榜" → 可能是非上榜条件的涨幅（创业板>20%才上榜）

**创业板龙虎榜触发条件**：
- 日收盘价涨幅>15%(创业板) 或 >20%(主板)
- 日换手率>20%
- 日价格振幅>15%
- 连续3个交易日累计偏离>30%
