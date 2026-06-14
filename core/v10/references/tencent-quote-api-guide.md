# 腾讯股票行情接口 Python 开发指南

> 实测验证日期：2026-06-07 | 接口地址：`qt.gtimg.cn`
> 本文档基于大量实战踩坑总结，非官方文档翻译。

---

## 一、接口概览

### 基础行情

```
http://qt.gtimg.cn/q={股票代码}
https://qt.gtimg.cn/q={股票代码}   # HTTPS也支持，推荐
```

> HTTP和HTTPS均可，推荐HTTPS。无需注册，无需API Key，免费稳定。

### 请求要求

```python
# ⚠️ 必须加User-Agent，否则可能被拒
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}
```

### 频率控制

- 官方未明确QPS限制，但建议 **单IP不超过1次/秒**
- 批量查询（≤50只）比逐只查询更友好
- 高频场景建议加 `time.sleep(0.5)` 间隔
- 触发限流后IP会被临时封禁（通常10-30分钟解封）

**市场前缀：**

| 市场 | 前缀 | 示例 |
|------|------|------|
| 沪A | `sh` | `sh600936`（湖南黄金） |
| 深A/创业板 | `sz` | `sz300975`（商络电子） |
| 港股 | `r_hk` | `r_hk09988`（阿里巴巴） |
| 美股 | `s_us` | `s_usBABA`（阿里巴巴） |

**批量查询：** 逗号分隔，一次最多约50只
```
https://qt.gtimg.cn/q=sh603629,sz300975,sh600936
```

### 辅助接口

| 接口 | URL | 说明 |
|------|-----|------|
| 资金流向 | `https://qt.gtimg.cn/q=ff_sz300975` | 主力/散户资金流 |
| 盘口分析 | `https://qt.gtimg.cn/q=s_pksz300975` | 买卖五档 |
| 简要信息 | `https://qt.gtimg.cn/q=s_sz300975` | 精简行情 |
| K线数据 | `https://ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz300975,day,,,30` | 日/周/月K线 |
| 主力净流入 | `https://ifzq.gtimg.cn/appstock/app/fqkline/getff?_var=ff_kline&param=sz300975,day,,,30` | 日级资金流 |

---

## 二、返回格式

### 编码：GBK（必须转码！）

```python
raw = resp.read().decode('gbk', errors='ignore')
```

### 格式：`v_{前缀代码}="字段1~字段2~...~字段N"`

每只股票一行，以 `;` 分隔。核心是以 `~` 分隔的字段数组。

```
v_sh603629="1~利通电子~603629~180.38~200.42~200.43~337418~165308~172111~...";
```

---

## 三、字段索引速查表（0-indexed parts[]）

> ⚠️ 本表基于实测验证，与网上流传的部分文档有索引偏移差异。
> 部分文档使用1-indexed的"fields[]"编号，与代码中的0-indexed parts[]不同。
> **本文档全部使用 parts[] 索引，直接对应 Python split 后的数组下标。**

### 核心行情字段

| 索引 | 字段 | 类型 | 示例 | 说明 |
|------|------|------|------|------|
| 0 | 市场代码 | str | `1` | 1=沪,51=深 |
| **1** | **名称** | str | `利通电子` | |
| **2** | **代码** | str | `603629` | 不含前缀 |
| **3** | **现价** | float | `180.38` | |
| **4** | **昨收** | float | `200.42` | |
| **5** | **今开** | float | `200.43` | |
| **6** | **成交量** | int | `337418` | 单位：手 |
| **7** | **外盘(主动买入)** | int | `165308` | 以卖价成交，外>内=买方主导 |
| **8** | **内盘(主动卖出)** | int | `172111` | 以买价成交，内>外=卖方主导 |
| 9-18 | 买1-买5 | | | 价格+量交替 |
| 19-28 | 卖1-卖5 | | | 价格+量交替 |
| 30 | 时间 | str | `20260605141429` | yyyyMMddHHmmss |
| **31** | **涨跌额** | float | `-20.04` | |
| **32** | **涨跌幅(%)** | float | `-10.00` | ✅ 已验证准确 |
| **33** | **最高** | float | `202.58` | |
| **34** | **最低** | float | `180.38` | |
| 35 | 成交额复合 | str | `180.38/337418/6293126603` | 现价/成交量(手)/成交额(元) |
| **36** | **成交量** | int | `337418` | ⚠️ 与[6]重复，单位：手 |
| **37** | **成交额(万元)** | int | `629313` | 629313万=62.93亿 |
| **38** | **换手率(%)** | float | `13.08` | |
| **39** | **PE(TTM)** | float | `88.54` | 亏损股为负数 |
| 40 | 未知 | | | 通常为空 |
| 41 | 未知 | | | |
| 42 | 最高(复) | float | `202.58` | 同[33] |
| 43 | 最低(复) | float | `180.38` | 同[34] |
| **44** | **振幅(%)** | float | `11.08` | (最高-最低)/昨收×100 |
| **45** | **流通市值(亿)** | float | `465.44` | ✅ 实测确认 |
| **46** | **总市值(亿)** | float | `473.17` | ✅ 实测确认 |
| **47** | **涨停价** | float | `220.46` | ✅ 交易所标准计算，无需自行算 |
| **48** | **跌停价** | float | `180.38` | ✅ 交易所标准计算，无需自行算 |
| **49** | **量比** | float | `1.24` | 当日均量/近5日均量 |
| 50 | 未知/主力净流入 | | | ⚠️ 不可靠，不要用 |
| 51 | 流通市值/未知 | | | ⚠️ 数量级不稳定 |

### 涨停/跌停价验证数据（2026-06-07 盘后实测）

| 股票 | 代码 | 昨收 | 涨跌幅限制 | parts[47] | 理论涨停 | parts[48] | 理论跌停 |
|------|------|------|----------|----------|---------|----------|---------|
| 利通电子 | 603629 | 200.42 | 10% | 220.46 | 220.46 ✅ | 180.38 | 180.38 ✅ |
| 商络电子 | 300975 | 43.51 | 20% | 52.21 | 52.21 ✅ | 34.81 | 34.81 ✅ |
| 北投科技 | 600936 | 6.17 | 10% | 6.79 | 6.79 ✅ | 5.55 | 5.55 ✅ |

---

## 四、完整 Python 解析函数

```python
import urllib.request
import time
from typing import Dict, List, Optional

# === 请求配置 ===
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://gu.qq.com/',
}
REQUEST_INTERVAL = 0.3  # 秒，高频场景建议0.5+

def fetch_tencent_quotes(codes: List[str], timeout: int = 10) -> Dict[str, dict]:
    """
    批量获取腾讯实时行情
    
    Args:
        codes: 股票代码列表，含前缀，如 ['sh603629', 'sz300975']
        timeout: 请求超时秒数
    
    Returns:
        {code: {name, price, yclose, ...}} 字典
    """
    qs = ','.join(codes)
    url = f'https://qt.gtimg.cn/q={qs}'
    
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read().decode('gbk', errors='ignore')
    except Exception as e:
        print(f"腾讯行情请求失败: {e}")
        return {}
    
    results = {}
    for line in raw.strip().split(';'):
        if '=' not in line or '~' not in line:
            continue
        
        try:
            parts = line.split('=')[1].strip('"').split('~')
            if len(parts) < 49:
                continue
            
            code = parts[2]  # 纯数字代码
            
            results[code] = {
                # === 基本信息 ===
                'name': parts[1],                              # 名称
                'code': code,                                   # 代码
                'price': float(parts[3]) or 0,                 # 现价
                'yclose': float(parts[4]) or 0,                # 昨收
                'open': float(parts[5]) or 0,                  # 今开
                
                # === 涨跌 ===
                'change': float(parts[31]) or 0,               # 涨跌额
                'change_pct': float(parts[32]) or 0,           # 涨跌幅%
                
                # === 价格区间 ===
                'high': float(parts[33]) or 0,                 # 最高
                'low': float(parts[34]) or 0,                  # 最低
                'limit_up': float(parts[47]) if len(parts) > 47 and parts[47] else 0,    # 涨停价
                'limit_down': float(parts[48]) if len(parts) > 48 and parts[48] else 0,  # 跌停价
                
                # === 成交 ===
                'volume': int(float(parts[6])) if parts[6] else 0,    # 成交量(手)
                'amount': float(parts[37]) if parts[37] else 0,       # 成交额(万元)
                'turnover': float(parts[38]) if parts[38] else 0,     # 换手率%
                'vol_ratio': float(parts[49]) if len(parts) > 49 and parts[49] else 0,  # 量比
                
                # === 买卖盘 ===
                'outer': int(float(parts[7])) if parts[7] else 0,    # 外盘(主动买入)
                'inner': int(float(parts[8])) if parts[8] else 0,    # 内盘(主动卖出)
                
                # === 基本面 ===
                'pe': float(parts[39]) if parts[39] else 0,          # PE(TTM)
                'amplitude': float(parts[44]) if parts[44] else 0,   # 振幅%
                'circ_cap': float(parts[45]) if parts[45] else 0,    # 流通市值(亿)
                'total_cap': float(parts[46]) if parts[46] else 0,   # 总市值(亿)
            }
            
            # 派生指标
            if results[code]['outer'] > 0 or results[code]['inner'] > 0:
                net = results[code]['outer'] - results[code]['inner']
                results[code]['buy_pressure'] = '买方主导' if net > 0 else '卖方主导'
                results[code]['net_volume'] = net  # 净买入(手)，正=买方主导
            
            if results[code]['yclose'] > 0 and results[code]['limit_up'] > 0:
                price = results[code]['price']
                results[code]['dist_to_limit_up'] = round(
                    (results[code]['limit_up'] - price) / price * 100, 2
                )  # 距涨停空间%
                results[code]['dist_to_limit_down'] = round(
                    (price - results[code]['limit_down']) / price * 100, 2
                )  # 距跌停空间%
                
        except (ValueError, IndexError) as e:
            continue
    
    return results


# === 使用示例 ===
if __name__ == '__main__':
    codes = ['sh603629', 'sz300975', 'sh600936']
    quotes = fetch_tencent_quotes(codes)
    
    for code, q in quotes.items():
        print(f"{q['name']}({code}) 现价={q['price']} "
              f"涨跌={q['change_pct']:+.2f}% "
              f"涨停={q['limit_up']} 跌停={q['limit_down']} "
              f"距涨停={q.get('dist_to_limit_up', 'N/A')}% "
              f"距跌停={q.get('dist_to_limit_down', 'N/A')}% "
              f"换手={q['turnover']}% 量比={q['vol_ratio']} "
              f"买压={q.get('buy_pressure', 'N/A')}")
```

---

## 五、关键踩坑记录

### 1. 编码必须 GBK → UTF-8

```python
# ❌ 错误：直接decode utf-8会乱码
raw = resp.read().decode('utf-8')

# ✅ 正确
raw = resp.read().decode('gbk', errors='ignore')
```

### 2. 涨停价/跌停价不要自己算！

```python
# ❌ 错误：math.ceil/floor 精度偏差
limit_up = math.ceil(yclose * 1.1 * 100) / 100    # 200.42→220.47，应该是220.46
limit_down = math.floor(yclose * 0.9 * 100) / 100  # 200.42→180.37，应该是180.38

# ❌ 错误：round 也有精度问题
limit_up = round(yclose * 1.1, 2)    # 创业板20%时可能偏

# ✅ 正确：直接读API返回值，交易所标准计算
limit_up = float(parts[47])     # 220.46 ✅
limit_down = float(parts[48])   # 180.38 ✅
```

**原因：** 交易所的涨跌停价计算采用"先乘后取至0.01"的特定取整规则，不是简单的ceil/floor/round。不同交易所还有细微差异（如北交所、ST股5%）。腾讯API返回的值已经是交易所标准值。

### 3. MA字段不可信

```python
# ❌ 不要用
ma5 = parts[42]   # 严重失真，部分股票差10倍
ma10 = parts[43]  # 同上
ma20 = parts[44]  # 同上

# ✅ 自己从K线API计算
# https://ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh603629,day,,,120
```

### 4. field[50] 主力净流入不可靠

```python
# ❌ 绝对不要用
main_inflow = parts[50]  # 数量级严重偏差（成交8亿+的票显示1.99万）

# ✅ 替代方案：
# 1. 腾讯ff_接口（仅交易时段有效）
#    https://ifzq.gtimg.cn/appstock/app/fqkline/getff?_var=ff_kline&param=sz300975,day,,,30
# 2. 同花顺实时API
#    https://d.10jqka.com.cn/v2/realhead/hs_300975/last.js
# 3. 东方财富push2 API（需fltt=2参数）
# 4. iFinD MCP（最可靠，但有配额限制）
```

### 5. 批量查询限制

```python
# ⚠️ 单次查询建议不超过50只，否则可能截断
# 超过50只时分批，并加间隔避免限流：
def fetch_large_batch(all_codes, batch_size=50):
    results = {}
    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i+batch_size]
        results.update(fetch_tencent_quotes(batch))
        if i + batch_size < len(all_codes):
            time.sleep(REQUEST_INTERVAL)  # 批次间间隔
    return results
```

### requests 写法（替代 urllib）

```python
import requests

def fetch_tencent_quotes_requests(codes: list, timeout: int = 5) -> dict:
    """使用 requests 库的写法（更简洁，需 pip install requests）"""
    url = f"http://qt.gtimg.cn/q={','.join(codes)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = 'gbk'  # 关键：腾讯接口返回GBK编码
        raw = resp.text
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return {}
    
    results = {}
    for line in raw.strip().split(';'):
        if '=' not in line or '~' not in line:
            continue
        # ... 后续解析逻辑同 urllib 版 ...
    return results
```

### 6. 代理/网络问题

```python
# push2.eastmoney.com 已不可用（2026-05-26起）
# qt.gtimg.cn 在国内直连可用，不需要代理
# 如果开了VPN/Shadowrocket，需要排除国内域名

# 直连（推荐）
resp = urllib.request.urlopen(url, timeout=10)

# 走代理（如果必须）
proxy = urllib.request.ProxyHandler({'https': 'http://127.0.0.1:17891'})
opener = urllib.request.build_opener(proxy)
resp = opener.open(url, timeout=10)
```

---

## 六、买卖压力分析

利用外盘(parts[7])/内盘(parts[8])判断主力资金方向：

```python
def analyze_pressure(outer: int, inner: int) -> dict:
    """分析买卖压力"""
    net = outer - inner
    total = outer + inner
    if total == 0:
        return {'direction': '无成交', 'net': 0, 'ratio': 0}
    
    return {
        'direction': '买方主导' if net > 0 else '卖方主导',
        'net': net,                                        # 净买入手数（正=买方）
        'ratio': round(net / total * 100, 2),             # 净占比%
        'strength': '强' if abs(net/total) > 0.1 else '弱'  # 强弱判断
    }

# 使用
q = fetch_tencent_quotes(['sh603629'])['603629']
pressure = analyze_pressure(q['outer'], q['inner'])
# 输出: {'direction': '卖方主导', 'net': -6803, 'ratio': -1.01, 'strength': '弱'}
```

**注意：** 外盘/内盘是当日累计值。开盘初期数据量小参考性有限，下午盘更可靠。

---

## 七、实用工具函数

### 获取A股全市场代码

```python
def get_all_a_shares() -> list:
    """获取沪深A股全部代码（腾讯格式）"""
    # 沪市
    url_sh = 'https://qt.gtimg.cn/q=sha'
    # 深市
    url_sz = 'https://qt.gtimg.cn/q=sza'
    
    all_codes = []
    for url in [url_sh, url_sz]:
        try:
            resp = urllib.request.urlopen(url, timeout=15)
            raw = resp.read().decode('gbk', errors='ignore')
            for line in raw.strip().split(';'):
                if '~' not in line:
                    continue
                parts = line.split('=')[1].strip('"').split('~')
                if len(parts) > 2:
                    code = parts[2]
                    # 过滤：排除北交所(8/4开头)、科创(688)
                    if code.startswith(('6', '0', '3')) and not code.startswith('688'):
                        prefix = 'sh' if code.startswith('6') else 'sz'
                        all_codes.append(f'{prefix}{code}')
        except:
            continue
    return all_codes
```

### 判断涨跌幅限制类型

```python
def get_limit_pct(code: str, name: str = '') -> float:
    """根据代码和名称判断涨跌幅限制"""
    if code.startswith('68'):       # 科创板 20%
        return 0.20
    elif code.startswith('3'):      # 创业板 20%
        return 0.20
    elif 'ST' in name.upper():      # ST股 5%
        return 0.05
    else:                           # 主板 10%
        return 0.10

# ✅ 更好：直接用API返回的涨停/跌停价，不需要判断类型
# limit_pct = (limit_up / yclose - 1)  # 反推涨跌幅限制
```

### 距涨跌停空间计算

```python
def calc_limit_distance(price: float, limit_up: float, limit_down: float) -> dict:
    """计算距涨跌停的空间"""
    if price <= 0:
        return {'to_up': 0, 'to_down': 0}
    
    return {
        'to_up': round((limit_up - price) / price * 100, 2),      # 距涨停空间%
        'to_down': round((price - limit_down) / price * 100, 2),   # 距跌停空间%
        'is_limit_up': abs(price - limit_up) < 0.01,               # 是否涨停
        'is_limit_down': abs(price - limit_down) < 0.01,           # 是否跌停
    }
```

---

## 八、数据源优先级

| 场景 | 首选 | 降级1 | 降级2 |
|------|------|-------|-------|
| 实时行情(盘中) | 腾讯qt.gtimg.cn | 东方财富push2 | iFinD MCP |
| 涨停/跌停价 | 腾讯parts[47/48] | 自行计算(⚠️精度问题) | — |
| 资金流向(盘中) | 同花顺实时API | 腾讯ff_接口 | push2(fltt=2) |
| 资金流向(盘后) | iFinD MCP | 同花顺10jqka | web搜索 |
| K线数据 | 腾讯ifzq.gtimg.cn | 东方财富 | iFinD MCP |
| 全市场扫描 | 问财智能选股(预过滤) | 腾讯全量+本地过滤 | — |

---

## 九、已知限制

1. **非交易时段**：返回最近一个交易日的收盘数据，涨停/跌停价基于该日昨收计算
2. **停牌股**：parts[3]现价为0，需跳过（`if price <= 0: continue`）
3. **新股上市首日**：涨跌幅限制不同（主板44%，创业板/科创板无限制），parts[47/48]可能为0
4. **北交所(8/4开头)**：20%涨跌幅，但腾讯行情可能不稳定
5. **科创板(688)**：20%涨跌幅，parts[47/48]正确返回
6. **ST股**：5%涨跌幅，parts[47/48]正确返回
7. **港股/美股**：字段索引可能不同，本文档仅覆盖A股

---

## 十、变更记录

| 日期 | 变更 |
|------|------|
| 2026-06-07 | 初版：完整字段索引+涨停跌停验证+踩坑记录 |
| 2026-06-08 | V10脚本全量字段升级：6脚本补齐外盘/内盘/量比/换手率/振幅/PE/流通市值/总市值，全部20+字段覆盖 |
| 2026-05-27 | 确认field[50]主力净流入不可靠 |
| 2026-05-26 | push2.eastmoney.com 全域名不可用 |
| 2026-05-19 | 确认parts[45]为流通市值(非文档所标f44振幅) |
