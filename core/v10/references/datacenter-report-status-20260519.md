# datacenter-web & push2 API 状态记录（2026-05-19确认）

> 记录时间：2026-05-19
> 数据源：东方财富系 API

## push2.eastmoney.com

### 批量行情 API ✅ 可用
```
GET /api/qt/ulist.np/get
```
- 需要 `fltt=2` 参数，否则返回flag值（非实际数值）
- field `f62`=主力净流入额(元)
- field `f184`=主力净流入占比(%)
- field `f45`=融资买入额(元)
- field `f47`=融券卖出额(元)
- ut token: `fa5fd1943c7b386f172d6893dbbd4848`
- **Python urllib 偶发 RemoteDisconnected**，curl fallback 可绕

### 个股板块归属 ❌ 永久挂掉
```
GET /api/qt/stock/get
```
- 返回空响应（7种方式测试均失败：URL编码、不同User-Agent、fltt=2、去掉fltt、不同ut参数、curl直调、Python urllib）
- **无备选方案**：新浪/腾讯/同花顺个股级板块API均404/空页面

### 行业板块榜单 ✅ 可用
```
GET /api/qt/clist/get?fs=m:90+t:2&fid=f3
```
- f14=板块名称, f3=涨跌幅(%), f20=总市值, f12=板块代码
- f3 > 0 为上涨板块，排序即可得板块涨幅排名

### 概念板块榜单 ❌ 挂掉
```
GET /api/qt/clist/get?fs=m:90+t:3&fid=f3
```
- 返回空响应
- 概念板块数据不可用

## datacenter-web.eastmoney.com

### 龙虎榜 ✅ 可用
```
RPT_DAILYBILLBOARD_DETAILSNEW
```
- 字段：BILLBOARD_BUY_AMT/SELL_AMT/NET_AMT
- ⚠️ 返回全量历史数据，需按TRADE_DATE过滤

### 融资融券 ⚠️ 间歇性
```
RPT_RZRQ_SECURITIES
```
- 2026-05-15：正常
- 2026-05-19：返回None结构（间歇性失效）

### 大宗交易 ❌ 永久挂掉
```
RPT_BLOCKTRADE_DETAILSNEW
```
- 返回"报表配置不存在"
- 所有大宗交易相关报表均失效

### 主力资金流向 ❌ 永久挂掉
```
RPT_MONEY_FLOW_STOCK / RPTA_WEB_MONEY_FLOW / RPT_MONEY_FLOW_STOCK_NEW
```
- 返回"报表配置不存在"

## 铁律

1. 个股板块归属无可用免费API替代
2. 主力净流入数据：MCP get_stock_performance → push2 批量(fltt=2) → 不可获取
3. 板块排名：MCP ifind-index（ths_hot_ranking）→ push2 行业板块榜单 → 腾讯ETF代理降级
4. 选股任务不要依赖东方财富个股板块归属API做板块风口验证
5. 所有资金面数据优先从MCP获取，push2作为备选
6. 预取脚本（no_agent）的板块数据源只能用 push2 行业板块榜单(fs=m:90+t:2) 和腾讯行情
