# iFinD date_sequence & data_pool 使用指南

## date_sequence（日期序列）

### 可用指标（2026-05-13实测确认）

| 指标 | 说明 | indiparams | 状态 |
|------|------|-----------|------|
| `ths_roe_stock` | ROE季度趋势 | `[""]` | ✅ |
| `ths_np_stock` | 归母净利润 | `[""]` | ✅ |
| `ths_np_yoy_stock` | 净利润同比增速(%) | `[""]` | ✅ |
| `ths_revenue_stock` | 营业收入 | `[""]` | ✅ |
| `ths_basic_eps_stock` | 基本每股收益 | `[""]` | ✅ |
| `ths_current_ratio_stock` | 流动比率 | `[""]` | ✅ |
| `ths_equity_multiplier_stock` | 权益乘数 | `[""]` | ✅ |
| `ths_np_ttm_stock` | TTM净利润 | `[""]` | ✅ |
| `ths_revenue_yoy_stock` | 营收同比增速 | `[""]` | ⚠️返回null |
| `ths_eps_stock` | 每股收益 | `[""]` | ❌报错 |

### 正确请求格式

```python
data = iFinD._post("date_sequence", {
    "codes": "300446.SZ",
    "startdate": "20230101",
    "enddate": "20260513",
    "functionpara": {"Interval": "Q", "Fill": "Blank"},
    "indipara": [{"indicator": "ths_roe_stock", "indiparams": [""]}]
}, timeout=15)
```

### functionpara参数说明

| Key | 值 | 说明 |
|-----|-----|------|
| Interval | D/W/M/Q/S/Y | 数据频率，Q=季度（财务分析最常用） |
| Fill | Blank/Previous | 缺失值处理，Blank=空值 |

### 常见错误

- 缺少`Interval` → -4210错误
- `indiparams`传`[]`而非`[""]` → 可能报错
- 指标名拼写错误 → -4210错误

## data_pool（专题报表）

### 可用报表

| 报表编码 | 说明 | functionpara |
|----------|------|-------------|
| p03291 | 板块成分股 | date, blockname |

### p03291 板块成分股

```python
data = iFinD._post("data_pool", {
    "reportname": "p03291",
    "functionpara": {"date": "20260513", "blockname": "001031"},
    "outputpara": "p03291_f001:Y,p03291_f002:Y"
}, timeout=15)
```

**字段说明：**
- `p03291_f001` = 日期（如"2026/05/13"）
- `p03291_f002` = 同花顺代码（如"000001.SZ"）

**常见错误：**
- `outputpara`为空字符串 → -4203错误（必须非空！）
- `outputpara`不传 → -4203错误
- blockname错误 → 返回空数据

### 板块代码对照（常用）

| blockname | 板块 |
|-----------|------|
| 001031 | 电子 |
| 001032 | 计算机 |
| 001033 | 传媒 |
| 001034 | 通信 |
| 001035 | 医药生物 |
| 001036 | 食品饮料 |
| 001037 | 银行 |
| 001038 | 非银金融 |
| 001039 | 房地产 |
| 001040 | 机械设备 |

## financial_trend() 便捷方法

```python
from ifind_http_api import iFinD
trend = iFinD.financial_trend("300446.SZ", years=2)
```

返回值：
- `trend["roe"]` → `[{"date": "2025-12-31", "value": 15.81}, ...]`
- `trend["np_yoy"]` → 净利润同比增速趋势
- `trend["revenue"]` → 营业收入趋势
- `trend["eps"]` → 基本每股收益趋势
- `trend["net_profit"]` → 归母净利润趋势
