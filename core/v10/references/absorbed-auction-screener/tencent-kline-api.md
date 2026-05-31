# 腾讯K线API — Vibe分析数据源

## 概述
Vibe-Trading增强层需要K线数据做形态/SMC/OIR/缠论分析。腾讯K线API是当前唯一可靠的数据源。

## 接口

### 日K线（前复权）
```
GET http://web.ifzq.gtimg.cn/appstock/app/fqkline/get
参数: param={market}{code},day,,,{count},qfq
示例: param=sz002475,day,,,30,qfq
```

### 返回结构
```json
{
  "code": 0,
  "data": {
    "sz002475": {
      "qfqday": [
        ["2026-04-10", "72.50", "73.80", "74.20", "71.90", "123456"],
        // [date, open, close, high, low, volume]
      ]
    }
  }
}
```

**⚠️ 注意:** 
- 字段顺序是 `open, close, high, low`（不是 `open, high, low, close`）
- 如果 `qfqday` 为空，fallback到 `day` 字段
- volume单位是手

## 用法
```python
def fetch_tencent_kline(code, market, days=30):
    symbol = f"{market}{code}"
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{days},qfq"
    resp = urllib.request.urlopen(url, timeout=15)
    data = json.loads(resp.read().decode('utf-8'))
    klines = data.get('data', {}).get(symbol, {}).get('qfqday', [])
    if not klines:
        klines = data.get('data', {}).get(symbol, {}).get('day', [])
    result = []
    for k in klines:
        if len(k) >= 6:
            result.append({
                'date': k[0],
                'open': float(k[1]),
                'close': float(k[2]),
                'high': float(k[3]),
                'low': float(k[4]),
                'volume': float(k[5]),
            })
    return result
```

## 性能
- 单次请求: ~50-100ms
- 10只股票: ~1秒（串行）/ ~200ms（并行）
- 无需认证，无需特殊header

## 限制
- 非交易时段返回上一交易日收盘数据
- 前复权价格，适合做形态分析
- 不提供分钟级K线（如需可用 `scale=60` 参数获取60分钟线）
