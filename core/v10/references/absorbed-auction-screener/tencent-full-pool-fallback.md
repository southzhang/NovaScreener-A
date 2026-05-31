# 腾讯全量A股扫描兜底方案 (2026-05-09验证)

## 背景
东方财富push2断连、Akshare失效、新浪全量API 404，腾讯API成为唯一可靠数据源。
2026-05-09 cron job实测成功：获取5536只有效A股，三策略筛出14只。

## 方案：代码池生成 + 批量腾讯拉取

### 1. 生成A股代码池
```python
def gen_stock_pool():
    pool = []
    # 沪市主板 600000-605999
    for i in range(600000, 606000):
        pool.append(f"sh{i}")
    # 科创板 688000-689999
    for i in range(688000, 690000):
        pool.append(f"sh{i}")
    # 深市主板 000001-003999
    for i in range(1, 4000):
        pool.append(f"sz{str(i).zfill(6)}")
    # 中小板 002000-002999
    for i in range(2000, 3000):
        pool.append(f"sz{str(i).zfill(6)}")
    # 创业板 300000-302000
    for i in range(300000, 302000):
        pool.append(f"sz{i}")
    return pool
```

### 2. 批量拉取（100只/批）
```python
def fetch_tencent_batch(codes):
    results = {}
    url = f"http://qt.gtimg.cn/q={','.join(codes)}"
    resp = urllib.request.urlopen(url, timeout=20)
    data = resp.read().decode('GBK', errors='ignore')
    for line in data.strip().split('\n'):
        m = re.match(r'v_(\w+)="(.*)"', line.strip().rstrip(';'))
        if not m:
            continue
        code_full = m.group(1)
        parts = m.group(2).split('~')
        if len(parts) < 40:
            continue
        price = float(parts[3]) if parts[3] else 0
        if price <= 0:
            continue  # 跳过无效/停牌
        # ... 解析其他字段
    return results
```

### 3. 关键参数
- 总代码数: ~15000个（含大量无效）
- 有效股票: ~5500只（price>0）
- 批量大小: 100只/请求
- 总请求数: ~150批
- 耗时: ~2-3分钟（含sleep 50ms/批）
- 带宽: 每批~50KB

### 4. 腾讯字段解析要点
| 索引 | 含义 | 注意 |
|------|------|------|
| 1 | 名称 | GBK编码 |
| 3 | 最新价 | — |
| 4 | 昨收 | — |
| 5 | 开盘价 | — |
| 6 | 成交量(手) | — |
| 9-10 | 买一价/量 | — |
| 19-20 | 卖一价/量 | — |
| 33 | 最高 | — |
| 34 | 最低 | — |
| 37 | 成交额(万元) | 单位是万元不是元 |
| 38 | 换手率(%) | — |
| 44 | 流通市值(亿) | ⚠️ 解析可能为0，需验证 |

### 5. 已知问题
- **流通市值字段(parts[44])可能返回空或0**: 导致量比估算失效
  - 影响: 量比=amount/(circ*12.5) 会得到极大值
  - 临时方案: 用成交额绝对值作为筛选依据，忽略量比
- **量比为估算值**: 腾讯不提供真实量比，需在报告中注明
- **非交易时段**: 返回收盘数据，量比偏高（全天量/基准）

### 6. 与原方案对比
| 方案 | 数据源 | 优点 | 缺点 |
|------|--------|------|------|
| 原方案 | 东方财富push2 | 真实量比、流通市值准确 | 已断连 |
| 腾讯兜底 | qt.gtimg.cn | 可靠、免费、无需认证 | 量比估算、流通市值可能为0 |

### 7. 执行时间参考
```
生成代码池: <1s
批量拉取: ~2-3min (150批 × 50ms sleep + 网络)
三策略筛选: <1s
基本面获取: ~2s (14只 × 100ms)
总计: ~3min
```
