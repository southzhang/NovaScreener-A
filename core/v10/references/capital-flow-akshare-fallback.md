# 资金面三维度 — Akshare 回退方案（Cron Agent MCP不可用时）

当 MCP 工具在 cron 上下文中不可用时（`mcp_ifind_*` 未注册），用 akshare 作为回退数据源获取资金面三维度数据。

## 适用场景

- Cron Agent 任务的 `enabled_toolsets` 限制了 MCP 工具
- MCP 服务器宕机或 token 过期
- 需要纯 Python 脚本独立运行（no_agent=true）

## 三维度映射表

| iFinD MCP 查询 | 对应的 akshare 调用 | 数据时效 |
|----------------|---------------------|----------|
| `get_stock_performance(主力净流入额+占比)` | `stock_individual_fund_flow(stock, market)` | T-1 收盘数据，非实时 |
| `get_stock_performance(融资融券余额)` | `stock_margin_detail_sse(date)` / `stock_margin_detail_szse(date)` | T-1 收盘数据 |
| `get_stock_performance(大宗交易)` | `stock_dzjy_mrtj(start_date, end_date)` | 含当天数据（若已发生） |
| `get_stock_performance(龙虎榜上榜次数+买卖额)` | `stock_lhb_stock_statistic_em(symbol='近一月')` | 近一个月累计 |

## 完整采集代码（可复用）

```python
import akshare as ak
import time
from datetime import datetime, timedelta

stocks = {"600936": "北投科技", "300912": "凯龙高科", "300065": "海兰信"}
today = datetime.now().strftime("%Y%m%d")
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

# ── 维度1: 主力资金净流入 ──
def get_main_flow(stock_code):
    """返回 (net_inflow_yuan, net_inflow_pct) 或 (None, None)"""
    market = "sh" if stock_code.startswith("6") else "sz"
    try:
        df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
        time.sleep(2)  # 防 RemoteDisconnected
        if df is not None and len(df) > 0:
            latest = df.iloc[0]
            net = float(latest.get("净额", 0) or 0)
            pct = float(latest.get("净占比", 0) or 0)
            return net, pct
    except Exception:
        time.sleep(2)
        try:
            df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
            if df is not None and len(df) > 0:
                latest = df.iloc[0]
                net = float(latest.get("净额", 0) or 0)
                pct = float(latest.get("净占比", 0) or 0)
                return net, pct
        except:
            pass
    return None, None

# ── 维度2: 融资融券余额 ──
def get_margin_balance(stock_code, date_str):
    """返回融资融券余额（元）或 None"""
    try:
        if stock_code.startswith("6"):
            df = ak.stock_margin_detail_sse(date=date_str)
            row = df[df["标的证券代码"] == stock_code]
        else:
            df = ak.stock_margin_detail_szse(date=date_str)
            row = df[df["证券代码"] == stock_code]
        if len(row) > 0:
            return float(row.iloc[0].get("融资融券余额", 0))
    except:
        pass
    return None

# ── 维度2续: 大宗交易 ──
def get_block_trades(stock_code, start_date, end_date):
    """返回 (总成交额, 上榜次数)"""
    try:
        df = ak.stock_dzjy_mrtj(start_date=start_date, end_date=end_date)
        if df is not None and len(df) > 0:
            stock_df = df[df["证券代码"] == stock_code]
            if len(stock_df) > 0:
                return float(stock_df["成交金额"].sum()), len(stock_df)
    except:
        pass
    return None, 0

# ── 维度3: 龙虎榜 ──
def get_dragon_tiger(stock_code):
    """返回 (上榜次数, 买入额, 卖出额) — 近一个月"""
    try:
        df = ak.stock_lhb_stock_statistic_em(symbol="近一月")
        if df is not None and len(df) > 0:
            stock_df = df[df["代码"] == stock_code]
            if len(stock_df) > 0:
                row = stock_df.iloc[0]
                count = int(row.get("上榜次数", 0))
                buy = float(row.get("买入额", 0)) if count > 0 else None
                sell = float(row.get("卖出额", 0)) if count > 0 else None
                return count, buy, sell
    except:
        pass
    return 0, None, None
```

## 字段映射

### stock_individual_fund_flow
| 列名 | 含义 | 单位 |
|------|------|------|
| 净额 | 主力净流入额 | 元 |
| 净占比 | 主力净流入占比 | % |

### stock_margin_detail_sse（上海）
| 列名 | 含义 | 单位 |
|------|------|------|
| 标的证券代码 | 股票代码 | — |
| 融资融券余额 | 余额 | 元 |

### stock_margin_detail_szse（深圳）
| 列名 | 含义 | 单位 |
|------|------|------|
| 证券代码 | 股票代码 | — |
| 融资融券余额 | 余额 | 元 |

### stock_dzjy_mrtj
| 列名 | 含义 | 单位 |
|------|------|------|
| 证券代码 | 股票代码 | — |
| 成交金额 | 单笔成交金额 | 元 |

### stock_lhb_stock_statistic_em
| 列名 | 含义 | 单位 |
|------|------|------|
| 代码 | 股票代码 | — |
| 上榜次数 | 近一个月上榜次数 | 次 |
| 买入额 | 龙虎榜买入总额 | 元 |
| 卖出额 | 龙虎榜卖出总额 | 元 |

## ⚠️ 已知坑

1. **`stock_individual_fund_flow` 间歇性 RemoteDisconnected**
   - 每次调用后 `time.sleep(2)` + 重试一次

2. **数据延迟一天** — T-1 收盘数据，盘中无法获取今日实时净流向

3. **融资融券数据发布** — T+1 早上 8:00-9:00 可获取前日数据

4. **大宗交易** — `stock_dzjy_mrtj` 盘中已有当日数据，但查询范围≤7天

5. **龙虎榜近一月 ≠ 近5天** — 需要精确5天需 `stock_lhb_detail_daily_sina` 逐日查

6. **代码市场前缀** — 6xx→sh, 0xx/3xx→sz

## 缓存格式

写入 `~/.hermes/cache/capital_flow.json`，金额一律存元（整数/浮点数）。
