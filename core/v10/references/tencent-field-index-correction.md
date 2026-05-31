# 腾讯行情API字段索引映射（修正版 2026-05-27）

## 关键：field编号 vs Python索引
腾讯API返回的字段编号是**1-based**，Python split('~')后的parts[]是**0-based**。

**公式：field[N] = parts[N-1]**

## 常用字段映射

| field编号 | 含义 | Python索引 | 说明 |
|-----------|------|------------|------|
| field[1] | 名称 | parts[0] | |
| field[2] | 代码 | parts[1] | |
| field[3] | 最新价 | parts[2] | |
| field[4] | 昨收 | parts[3] | |
| field[5] | 今开 | parts[4] | |
| field[6] | 成交量(手) | parts[5] | |
| field[31] | 涨跌额 | parts[30] | |
| field[32] | 涨跌幅% | parts[31] | |
| field[33] | 最高 | parts[32] | |
| field[34] | 最低 | parts[33] | |
| field[37] | 成交额(万) | parts[36] | |
| field[38] | 换手率% | parts[37] | |
| field[43] | 振幅% | parts[42] | |
| field[49] | 量比 | parts[48] | |
| **field[50]** | **主力净流入(万)** | **parts[49]** | ⚠️曾错用parts[50] |

## 血泪教训
v10_tail_prefetch.py曾用`safe_float(50)`读主力净流入，实际读的是field[51]。
与refresh_capital_flow.py的`parts[49]`不一致，导致两个脚本数据矛盾。
修复：safe_float(50) → safe_float(49)
