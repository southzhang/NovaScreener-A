# iFinD HTTP API 使用指南

## 模块位置
`~/.hermes/scripts/ifind_http_api.py`

## 快速使用
```python
import sys
sys.path.insert(0, '/Users/southzhang/.hermes/scripts')
from ifind_http_api import iFinD

# 分钟K线（V10盘中分析核心）
df = iFinD.high_frequency("600756.SH", "2026-05-13 09:30:00", "2026-05-13 15:00:00")

# 批量实时行情
df = iFinD.realtime(["600756.SH", "300033.SZ"], ["latest", "changeRatio", "volume"])

# 基本面数据
df = iFinD.basic_data(["600756.SH"], ["ths_pe_ratio_stock", "ths_roe_deducted_stock"])

# 历史日K线
df = iFinD.history(["600756.SH"], "2026-04-01", "2026-05-13")

# 公告查询（排雷）
df = iFinD.announcements("600756.SH", report_type="901", start_date="2026-04-13")

# 智能选股
results = iFinD.smart_picking("涨跌幅")

# 公告查询
df = iFinD.announcements("600756.SH", report_type="901", start_date="2026-04-13")

# 财务趋势（一键获取ROE/净利润/营收/EPS季度趋势）
trend = iFinD.financial_trend("300446.SZ", years=3)
# trend = {"roe": [{date, value}, ...], "net_profit": [...], "np_yoy": [...], "revenue": [...], "eps": [...]}

# 专题报表（板块成分股）
data = iFinD.data_pool("p03291", {"date": "20260513", "blockname": "001031"}, "p03291_f001:Y,p03291_f002:Y")
```

## Token管理
- 自动从环境变量 `IFIND_REFRESH_TOKEN` 或 `~/.hermes/.env` 读取
- 自动刷新access_token，缓存20小时
- 多线程安全：内部已加 `threading.Lock()`

## API端点对照表

| 功能 | 方法 | iFinD端点 | 备注 |
|------|------|-----------|------|
| 分钟K线 | `high_frequency()` | `/api/v1/high_frequency` | 最多返回当日数据 |
| 实时行情 | `realtime()` | `/api/v1/real_time_quotation` | 批量，延迟约3秒 |
| 日K线 | `history()` | `/api/v1/cmd_history_quotation` | 批量，含前复权 |
| 基本面 | `basic_data()` | `/api/v1/basic_data_service` | PE/PB/ROE等 |
| 时间序列 | `date_serial()` | `/api/v1/date_sequence` | 多季度财务趋势(ROE/净利润/营收) |
| 财务趋势 | `financial_trend()` | 便捷封装 | 一键获取ROE/净利润/营收/EPS季度趋势 |
| 专题报表 | `data_pool()` | `/api/v1/data_pool` | 板块成分(p03291)/REITs(p03341)等 |
| 智能选股 | `smart_picking()` | `/api/v1/smart_stock_picking` | 自然语言条件 |
| 公告 | `announcements()` | `/api/v1/report_query` | reportType: 901=全部 |
| EDB宏观 | `edb()` | `/api/v1/edb_service` | 宏观经济指标 |
| Tick快照 | `snapshot()` | `/api/v1/snap_shot` | 日内逐笔 |
| 交易日 | `trade_dates()` | `/api/v1/get_trade_dates` | 偏移查询 |

## 分钟K线返回格式
```python
# iFinD high_frequency 返回 tables[0].table 结构
inner = data['tables'][0].get('table', data['tables'][0])
# inner = {
#   'open': [16.93, 16.94, ...],    # 分钟开盘价数组
#   'high': [16.93, 16.94, ...],
#   'low': [16.93, 16.82, ...],
#   'close': [16.93, 16.82, ...],
#   'volume': [41500, 94100, ...],   # 成交量（股）
# }
```
注意：返回的是list，需转numpy数组。最少5根K线才有效。

## 与MCP的区别
| | HTTP API | MCP |
|--|----------|-----|
| Token | refresh_token→access_token | JWT |
| 分钟K线 | ✅ high_frequency | ❌ 没有 |
| 批量实时行情 | ✅ real_time_quotation（实测0.25秒/1000只） | ❌ 延迟高 |
| 结构化财务 | ✅ basic_data | ✅ 更全 |
| 公告语义搜索 | ⚠️ report_query（按报告类型） | ✅ search_notice（语义） |
| 智能选股 | ✅ smart_picking | ✅ search_stocks |

## 批量性能实测（2026-05-13）
| 批量大小 | 耗时 | 适用场景 |
|----------|------|----------|
| 11只 | 0.14秒 | 持仓股查询 |
| 50只 | 0.23秒 | 板块内选股 |
| 100只 | 0.15秒 | 小批量扫描 |
| 500只 | 0.16秒 | 中批量扫描 |
| 1000只 | 0.25秒 | 大批量扫描 |
| 20000只 | ~5秒（20批） | 全市场扫描（替代腾讯） |

**结论：iFinD批量实时行情速度与腾讯持平（0.14-0.25秒），完全可以替代腾讯作为首选数据源。**
