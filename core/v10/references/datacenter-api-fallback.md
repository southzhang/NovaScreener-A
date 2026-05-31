# datacenter-web.eastmoney.com API 备用数据源 (2026-05-19更新)

当 iFinD MCP 不可用时，datacenter-web API 可获取**部分**资金面数据。

## 当前可用/不可用报表 (2026-05-19)

| 报表名 | 功能 | 关键字段 | 状态 |
|--------|------|----------|------|
| `RPT_DAILYBILLBOARD_DETAILSNEW` | 龙虎榜 | `BILLBOARD_BUY_AMT`, `BILLBOARD_SELL_AMT`, `BILLBOARD_NET_AMT`, `TRADE_DATE` | ✅ 可用 |
| `RPT_RZRQ_SECURITIES` | 融资融券余额 | `RZRQYE`, `RZRQYE_CHANGE_RATIO` | ✅ 可用 |
| `RPTA_WEB_RZRQ_GGMX` | 融资融券明细 | `RZRQYE`, `DATE` | ✅ 可用 |
| `RPT_BLOCKTRADE_DETAILSNEW` | 大宗交易 | — | ❌ 已报废("报表配置不存在") |
| `RPT_BLOCK_TRADE_INFO` | 大宗交易 | — | ❌ 已报废 |
| `RPT_BLOCK_TRADE_DETAILS` | 大宗交易 | — | ❌ 已报废 |
| `RPT_MUTUAL_DEAL_STOCK_EM_DETAILS` | 大宗交易 | — | ❌ 已报废 |
| `RPT_MONEY_FLOW_STOCK` | 主力资金 | — | ❌ 已报废 |
| `RPTA_WEB_MONEY_FLOW` | 主力资金 | — | ❌ 已报废 |
| `RPT_MONEY_FLOW_STOCK_NEW` | 主力资金 | — | ❌ 已报废 |
| `RPT_LHBSCTJ` | 龙虎榜统计 | — | ❌ 已知永久失效 |
| `RPT_STOCK_MONEYFLOW` | 资金流 | — | ❌ 返回空 |
| `RPT_STOCK_ZJLX` | 资金流 | — | ❌ "报表配置不存在" |

**铁律**：如果需要主力净流入+大宗交易数据，且MCP不可用且push2被VPN拦截 → **无法获取**。只能标记null。

详见 `references/datacenter-report-status-20260519.md`

## 通用调用模板

```python
import json, urllib.request

def fetch_datacenter(report_name, filter_code, page_size=50):
    url = (
        f"https://datacenter-web.eastmoney.com/api/data/v1/get?"
        f"reportName={report_name}&columns=ALL"
        f"&filter=(SECURITY_CODE=%22{filter_code}%22)"
        f"&pageSize={page_size}&sortColumns=TRADE_DATE&sortTypes=-1"
        f"&source=WEB&client=WEB"
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://data.eastmoney.com/"
    })
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read().decode("utf-8"))
    if data.get("result") and data["result"].get("data"):
        return data["result"]["data"]
    return []
```

## 日期过滤（必须）

所有报表返回全量历史数据，必须客户端过滤：

```python
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
recent = [r for r in rows if (r.get("TRADE_DATE") or "")[:10] >= cutoff]
```

## push2.eastmoney.com 资金流向

批量接口（Python urllib可能断连，curl更稳定）：

```bash
curl -s --max-time 10 \
  "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=1.600936,0.300455&fields=f12,f14,f62,f184&ut=fa5fd1943c7b386f172d6893dbbd4848" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://data.eastmoney.com/"
```

字段：`f62`=主力净流入额（元），`f184`=主力净流入占比（%）

**⚠️ 必须加 `fltt=2`**，否则 f62 返回 flag 值（1）而非实际金额。

## 融资融券特殊处理

`RPTA_WEB_RZRQ_GGMX` 的 `SCODE` 字段用的是股票代码（不含市场前缀），如 `600936`。
中小盘股可能不在融资融券标的范围，返回空是正常的。
