# iFinD HTTP API 使用模式（2026-05-13实测总结）

## Quota消耗速查表

**核心铁律：quota按数据条数计算，不是按API调用次数！**

| 接口 | 1只股票消耗 | 10只股票消耗 | 适用场景 |
|------|------------|-------------|----------|
| high_frequency (分钟K线) | 240条(全天) / 97条(5分钟) | 2400条 / 970条 | V10信号股盘中确认 |
| snap_shot (日内快照) | 4780条(全天) / 297条(15分钟) | 47800条 / 2970条 | TOP候选股盘口分析 |
| cmd_history_quotation (历史K线) | 250条(250天) | 2500条 | 信号股深度分析 |
| real_time_quotation (实时行情) | 1条 | 10条 | 不用（走腾讯免费） |
| smart_stock_picking (问财) | 不限量 | 不限量 | 预筛选/选股/板块 |
| date_sequence (日期序列) | 5条(5指标×1季度) | 50条 | 财务趋势分析(ROE/净利润/营收) |
| data_pool (专题报表) | 按报表 | 按报表 | 板块成分p03291 |

## 最佳实践

### 1. 预筛选（不限量，重度使用）
```python
# 问财自然语言选股
result = iFinD._post("smart_stock_picking", {
    "searchstring": "涨幅0.5%到9.8% 成交额大于5000万 非ST",
    "searchtype": "stock"
}, timeout=30)
```

### 2. 分钟K线（仅信号股）
```python
# 仅对V10信号股获取，不要对所有预过滤股票获取！
# 10只信号股 × 240根 = 2400次/扫描，月度~16万次（10.7%）
data = iFinD._post("high_frequency", {
    "codes": "600756.SH",
    "indicators": "open,high,low,close,volume",
    "starttime": "2026-05-13 09:30:00",
    "endtime": "2026-05-13 15:00:00"
}, timeout=15)
```

### 3. 盘口分析（TOP候选股）
```python
# 仅对TOP5-10只获取最近15分钟tick
# 10只 × 297条 = 2970次/扫描，月度~20万次（10%）
data = iFinD._post("snap_shot", {
    "codes": "600756.SH",
    "indicators": "latest,bid1,ask1,bidSize1,askSize1",
    "starttime": "2026-05-13 14:45:00",
    "endtime": "2026-05-13 15:00:00"
}, timeout=15)
```

### 4. 信号股深度分析
```python
# 对V10信号股获取完整历史K线做二次验证
# 10只 × 250天 = 2500次/扫描，月度~16.5万次（16.5%）
data = iFinD._post("cmd_history_quotation", {
    "codes": "600756.SH",
    "indicators": "open,high,low,close,volume,amount",
    "startdate": "2025-06-01",
    "enddate": "2026-05-13",
    "functionpara": {"Fill": "Blank"}
}, timeout=15)
```

### 5. 财务趋势分析（date_sequence）
```python
# 获取3年财务趋势（ROE/净利润/营收/EPS，按季度）
# 5指标×12季度=60条/只，月度~1320条（0.2%）
trend = iFinD.financial_trend("300446.SZ", years=3)
# trend["roe"] = [{"date": "2025-12-31", "value": 15.81}, ...]
# trend["np_yoy"] = [{"date": "2025-12-31", "value": 30.0}, ...]
```

### 6. 板块成分股（data_pool p03291）
```python
# 获取电子板块成分股列表
data = iFinD._post("data_pool", {
    "reportname": "p03291",
    "functionpara": {"date": "20260513", "blockname": "001031"},
    "outputpara": "p03291_f001:Y,p03291_f002:Y"
}, timeout=15)
# tables[0]["table"]["p03291_f002"] = ["000001.SZ", "000002.SZ", ...]
```

## 月度配额分配建议

| 接口 | 月度配额 | 建议消耗 | 占比 | 用途 |
|------|----------|----------|------|------|
| smart_stock_picking | 不限量 | 不限量 | - | 问财预筛选/选股/板块 |
| real_time_quotation | 300万 | ~15万 | 5% | 精确行情(PB等) |
| high_frequency | 150万 | ~2万 | 1.3% | 信号股盘中确认 |
| snap_shot | 200万 | ~20万 | 10% | 盘口深度分析 |
| cmd_history_quotation | 100万 | ~16.5万 | 16.5% | 信号股深度+回测 |
| basic_data_service | 60万 | ~2万 | 3.3% | 基本面(MCP更全) |
| date_sequence | 60万 | ~7000 | ~1% | 财务趋势(ROE/净利润/营收季度趋势) |
| data_pool | 60万 | ~66 | ~0% | 板块成分(p03291)/REITs(p03341) |

## 已踩过的坑

1. **high_frequency逐只调用**：1554只×240根=37万次/扫描，一次耗掉25%月度配额。**必须只对信号股调用！**
2. **real_time_quotation全市场扫描**：245k次/扫描，352次/月需8600万次，远超300万配额。**全市场扫描必须用腾讯！**
3. **iFinD实时行情字段限制**：pe_ttm/turnoverRate/volumeRatio返回null，仅pb可用。需要PE等走MCP或basic_data_service。
4. **问财不限量**：是唯一不限量的接口，预筛选/选股/板块风口全用问财，替代本地简单阈值过滤。
5. **date_sequence指标名陷阱**：很多指标名（如`ths_net_profit_atoopc_stock`）返回-4210。确认可用：ths_roe_stock, ths_np_stock, ths_np_yoy_stock, ths_revenue_stock, ths_basic_eps_stock, ths_current_ratio_stock, ths_equity_multiplier_stock, ths_np_ttm_stock。其他需超级命令生成。详见`references/ifind-date-sequence-data-pool.md`。
6. **data_pool的outputpara不能为空**：空字符串或省略都会返回-4203。必须指定至少一个字段。
7. **Token过期时data_pool返回-4203**：不是401，是"request format is wrong"。参数确认正确但返回-4203时先刷新token。
8. **date_sequence的indiparams不能省略**：即使不需要参数也要传`['']`，否则-4210。
