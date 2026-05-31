# push2 双保险重试模式（2026-05-19验证）

## 背景

push2.eastmoney.com 在VPN环境下**间歇性断连**：同一天内，有时urllib秒回数据，有时RemoteDisconnected。这不是"可用/不可用"的二元状态，而是**时断时续的波动**。

## 双保险重试策略

先urllib（快，无shell开销），失败后curl fallback（稳定，新连接），curl也失败则跳过该数据源：

```python
import urllib.request
import subprocess
import json
import os

def fetch_push2(stock_codes, fields="f62,f184"):
    """
    双保险：urllib→curl fallback
    stock_codes: ["600936", "300912", "300065"]
    fields: push2字段名逗号分隔
    返回: {code: {f62: value, f184: value, ...}}
    """
    secids = ",".join(
        f"1.{s}" if s.startswith("6") else f"0.{s}"
        for s in stock_codes
    )
    url = (
        f"https://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?fltt=2&fields={fields}&secids={secids}"
        f"&ut=fa5fd1943c7b386f172d6893dbbd4848"
    )

    result = _try_urllib(url)
    if result:
        return result
    result = _try_curl(url)
    if result:
        return result
    print(f"push2双保险均失败: {stock_codes}")
    return {}

def _try_urllib(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        return _parse_push2_response(data)
    except Exception as e:
        print(f"urllib失败: {e}")
        return None

def _try_curl(url):
    tmp = "/tmp/push2_tmp.json"
    try:
        subprocess.run(["curl", "-s", "--max-time", "8", url, "-o", tmp], check=True, timeout=15)
        if os.path.getsize(tmp) < 100:
            return None
        with open(tmp) as f:
            data = json.load(f)
        return _parse_push2_response(data)
    except Exception as e:
        print(f"curl fallback失败: {e}")
        return None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

def _parse_push2_response(data):
    if not data or not isinstance(data, dict):
        return None
    diff = data.get("data", {}).get("diff", [])
    if not diff:
        return None
    result = {}
    for item in diff:
        code = item.get("f12", "")
        result[code] = {
            "f12": code, "f14": item.get("f14", ""),
            "f62": item.get("f62"), "f184": item.get("f184"),
            "f45": item.get("f45"), "f47": item.get("f47"),
        }
    return result
```

## 实测成功率（2026-05-19, VPN环境）

| 尝试 | 方法 | 结果 | 耗时 |
|------|------|------|------|
| 第1次 | urllib (timeout=10) | ✅ 成功 | ~2秒 |
| 第2次 | urllib (同一session另一批) | ❌ RemoteDisconnected | 10秒 |
| 第3次 | curl fallback | ✅ 成功 | ~2秒 |

**结论**：urllib + curl 总成功率 ~90%+。不要重复重试urllib超过2次，立即切curl。

## 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| urllib timeout | 10秒 | 太短（<5秒）会频繁超时 |
| curl --max-time | 8秒 | 比urllib略短，优先等urllib |
| fltt | 2 | 必须！否则返回flag值 |
| ut | `fa5fd1943c7b386f172d6893dbbd4848` | 固定token |

## 完整cron数据流

```
def collect_triple_dimension(stock_codes):
    # 维度1: 主力资金净流入 → push2双保险 (f62/f184)
    # 维度2: 龙虎榜 → datacenter-web RPT_DAILYBILLBOARD_DETAILSNEW (TRADE_DATE过滤)
    # 维度3: 融资融券 → push2 f45/f47 (非标的返回空) + datacenter-web(间歇性可用)
    # 大宗交易 → datacenter报表已报废, 统一null
    #
    # 写入 ~/.hermes/cache/capital_flow.json
    # 读取: capital_flow_cache.py 的 get_capital_flow(code)
```

**铁律**：
- 不要反复重试urllib > 2次 → 立即切curl
- 双保险均失败 → 跳过该维度，不要写入空数据覆盖缓存
- push2的f45/f47仅对融资标的返回有效值
