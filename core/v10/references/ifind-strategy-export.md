# iFinD量化研究平台策略导出

## 策略文件位置
`~/.hermes/workspace/ifind_v10_strategy.py`

## 使用方法
1. iFinD终端 → 量化研究平台（MindGo/SuperMind）
2. 新建Python策略 → 粘贴文件内容
3. 修改第217行iFinD账号密码
4. 运行回测

## 策略参数（V5.1优化版）
| 参数 | 值 | 说明 |
|------|-----|------|
| EMA隧道 | 144/169 | 维加斯隧道 |
| EMA通道 | 7/26 | 短线通道 |
| MACD | 20/80/9 | 趋势确认 |
| 放量倍数 | 1.5x | V5.1优化 |
| 通道宽度 | 1.5% | V5.1优化 |
| 硬止损 | -6% | 买入价×0.94 |
| 移动止盈 | 涨10%回落3% | 1.10激活/0.97退出 |

## iFinD Python API (iFinDPy) 关键函数
```python
from iFinDPy import *
THS_iFinDLogin('账号', '密码')
THS_HistoryQuotes('代码', 'open;high;low;close;volume', 'period:D,fqdate:1900-01-01', start, end)
THS_Trans2Table(data)  # 转DataFrame
```

## 策略版本

| 版本 | 文件 | 特点 | 适用 |
|------|------|------|------|
| v1 | `ifind_v10_strategy.py` | iFinDPy直接调API，已填入账号 | ⚠️ 账号明文 |
| v2 | `ifind_v10_strategy_v2.py` | 回测验证版，单股 | MindGo回测 |
| v3 | `ifind_v10_strategy_v3.py` | 正式部署版，多股池+多持仓+风控 | MindGo模拟 |
| v4 | `ifind_v10_strategy_v4.py` | **全自动版**，SmartStockPicking动态选股 | MindGo（⚠️see below） |

## ⚠️ MindGo回测环境API限制

MindGo回测沙箱**不支持**以下函数（静默失败）：
- `SmartStockPicking()` — 智能选股
- `THS_DataPool()` — 数据池
- `THS_HistoryQuotes()` — iFinDPy历史数据

**只能用**：`history()`、`order_target_percent()`、`log.info()`、`record()` 等MindGo原生API。

**实测表现**（v4.0，2026-05-13）：SmartStockPicking返回空→走fallback→回测每天只扫40只股票。策略逻辑正确，但选股池受限。

**结论**：MindGo用于**验证策略逻辑**（止损/止盈/信号条件是否正确），全市场选股留到QMT实现。

## 注意事项
- 需要iFinD终端已安装并登录
- iFinDPy库随iFinD终端自带
- 回测区间建议3年以上（EMA200需足够数据）
- 与我们系统的V10策略参数完全一致，可直接对比回测结果
