# V10 Realtime Scan 架构（2026-05-13v8 最终版）

## 文件位置
`~/.hermes/workspace/v10_realtime_scan.py`

## 数据流（最终版）

```
main()
│
├── Step 1: fetch_all_realtime()
│   └── 腾讯行情 (qt.gtimg.cn) → 4122只 (43秒,免费)
│
├── Step 2: prefilter_stocks() [问财预过滤]
│   ├── 首选: iFinD smart_stock_picking (问财,不限量)
│   │   └── "涨幅0.5%到9.8% 成交额大于5000万 股价5元到150元 非ST 非北交所"
│   │   └── 4290→1554只 (0.3秒,过滤64%)
│   └── 备用: 本地简单过滤 (change>0.5, amount>5000, price 5-150)
│
├── Step 3: fetch_ifind_detailed() [iFinD精确行情]
│   └── iFinD real_time_quotation → PB数据 (1秒)
│   └── ⚠️ 仅pb可用, pe_ttm/turnoverRate/volumeRatio返回null
│
├── Step 4: fetch_sector_ranking() [板块排名]
│   └── iFinD smart_stock_picking → "涨幅前3板块的股票" (0.2秒)
│
├── Step 5: 并行K线扫描 (30线程)
│   ├── fetch_klines(code, 250) → 腾讯日K线 → EMA120/200
│   ├── scan_stock_rt() → V10信号判断
│   ├── fetch_minute_klines_today() → iFinD分钟K线
│   ├── calc_intraday_indicators() → 6维盘中指标
│   └── intraday_confirmation() → 盘中确认
│
└── Step 6: 输出结果 + 保存观察池
```

## 性能数据（v8最终版）

| 步骤 | 数据源 | 耗时 | 说明 |
|------|--------|------|------|
| 全市场行情 | 腾讯 | 43秒 | 免费无限制 |
| 问财预过滤 | iFinD | 0.3秒 | 不限量 |
| iFinD PB数据 | iFinD | 1秒 | ~800次API/月 |
| 板块排名 | iFinD | 0.2秒 | 不限量 |
| K线扫描 | 腾讯 | ~10秒 | 30线程并行 |
| 分钟K线 | iFinD | ~1.5秒 | 仅信号股 |
| **总耗时** | | **~45秒** | |

## iFinD HTTP API Quota分配（月度）

| 端点 | 月度限制 | 建议用量 | 用途 |
|------|----------|----------|------|
| smart_stock_picking (问财) | **不限量** | 重度使用 | 预筛选/选股/板块 |
| real_time_quotation | 300万 | ~15万 | PB数据补充 |
| high_frequency | 150万 | ~1万 | 分钟K线 |
| cmd_history_quotation | 100万 | ~10万 | 日K线(备用) |
| snap_shot | 200万 | ~3万 | tick快照(备用) |
| basic_data_service | 60万 | ~2万 | 基本面(备用) |
| date_sequence | 60万 | ~5000 | 财务趋势(备用) |
| data_pool | 60万 | ~1000 | 专题报表(备用) |

## Token管理
```python
IFIND_REFRESH_TOKEN = os.environ.get("IFIND_REFRESH_TOKEN", "")
# 备用: ~/.hermes/.env 文件
_token_lock = threading.Lock()  # ⚠️ 必须加锁，防止多线程重复刷新

def _get_ifind_token():
    with _token_lock:
        # 检查缓存 → 刷新 → 缓存20小时
```

## 关键函数

### fetch_all_realtime()
- 腾讯首选，免费无限制
- 批量80只/请求，43秒完成4122只
- 返回: code, name, symbol, price, yclose, open, high, low, change, volume, amount

### prefilter_stocks()
- 问财首选 (smart_stock_picking, 不限量)
- 自然语言查询: "涨幅0.5%到9.8% 成交额大于5000万 股价5元到150元 非ST"
- 4290→1554只 (过滤64%)
- 返回: 与fetch_all_realtime相同的格式

### fetch_ifind_detailed(stocks)
- iFinD real_time_quotation 补充PB数据
- 批量500只/请求，~800次API/月
- ⚠️ 仅pb可用, pe_ttm/turnoverRate/volumeRatio返回null

### fetch_sector_ranking()
- 问财 smart_stock_picking
- "涨幅前3板块的股票"
- 返回: [{code, name, change}, ...]

### fetch_minute_klines_today(code)
- iFinD high_frequency
- 返回今日分钟K线 (open/high/low/close/volume数组)
- 最少5根才有效

### calc_intraday_indicators(minute_data)
6维盘中指标:
1. VWAP - 成交量加权平均价
2. buy_ratio - 买入量占比 (阳线分钟成交量/总成交量)
3. momentum_5m - 近5分钟动量
4. vol_concentration - 量能集中度 (后半段/前半段)
5. tail_vol_ratio - 尾盘异动 (近15分钟/全天均量)
6. price_position - 价格位置 (当前价在今日高低点位置)

### intraday_confirmation(v10_result, intraday)
- confidence >= 2 → 确认通过
- 返回: (confirmed_result, confidence, notes_string)

## iFinD实时行情字段限制（实测）

| 字段 | 是否可用 | 说明 |
|------|----------|------|
| open/high/low/latest | ✅ | 基础价格 |
| yclose | ❌ | 需从changeRatio反推 |
| changeRatio | ✅ | 涨跌幅 |
| volume/amount | ✅ | 成交量/额 |
| pb | ✅ | 市净率 |
| pe_ttm | ❌ | 返回null |
| turnoverRate | ❌ | 不存在 |
| volumeRatio | ❌ | 返回null |
| totalMarketValue | ❌ | 不存在 |
| secName | ❌ | 不存在 |

## 腾讯备用解析
```python
def _parse_tencent_realtime(raw):
    # parts[2]=code, parts[1]=name, parts[3]=price
    # parts[4]=yclose, parts[5]=open, parts[33]=high, parts[34]=low
    # parts[32]=change, parts[6]=volume(手), parts[37]=amount(万元)

def _filter_stocks(stocks):
    # 去ST/跌停/停牌/低价/科创/无成交
```

## 常见问题

### ⚠️ 致命错误：对所有预过滤股票获取分钟K线
- **错误做法**：对1554只预过滤股票逐只获取分钟K线
- **后果**：1554只 × 240根K线 = 372,960条quota/扫描，一次测试就用了110万（73%配额）
- **正确做法**：仅对V10信号股（~10只）获取分钟K线做盘中确认
- **原因**：`high_frequency`端点按**每根K线**计费，不是按API调用次数
- **铁律**：分钟K线仅用于最终确认，绝不用于预筛选阶段

### iFinD获取<100只
- 原因：token过期或API异常
- 处理：自动降级到腾讯备用

### iFinD返回空tables
- 原因：代码格式错误或无效代码
- 处理：跳过该批次，继续下一批

### 分钟K线<5根
- 原因：开盘初期数据不足
- 处理：返回None，盘中确认跳过

### 问财预过滤返回0只
- 原因：查询条件太严格或API异常
- 处理：降级为本地简单过滤

### iFinD PB数据全为0
- 原因：iFinD API返回null
- 处理：PB数据非必须，不影响V10核心逻辑

### ⚠️ 板块分析降级到腾讯ETF后 KeyError: 'code'（2026-05-18发现）

**症状**：`v10_realtime_scan.py` 第1038行崩溃，`KeyError: 'code'`。

**根因**：`fetch_sector_ranking()` 调用 iFinD MCP `ths_hot_ranking` 超时 → 降级到腾讯板块ETF。但降级路径返回的 `sector_leaders` 是 dict 类型（key=ETF代码, value=板块名称），而主路径返回的是 pandas DataFrame 有 `code` 列。后续代码用 `sector_leaders[0].code` 访问 → 踩 KeyError。

**修复**：降级路径返回的 dict 需要转换为与主路径一致的结构（包含 `code` 和 `name` 字段的列表），或者后处理代码统一用 `.get('code', ...)` 防御式访问。

**教训**：降级路径的数据结构必须与主路径保持字段名完全一致。不能只验证“功能可用”就认为降级安全。
