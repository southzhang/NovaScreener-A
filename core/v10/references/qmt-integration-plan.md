# QMT Integration Plan (2026-05-14 更新)

## Status
- **券商：国金证券**（非银河，之前记错了）
- 入金2万即可开通miniQMT
- 用户有Windows电脑 ✅
- **Mac ↔ Windows SSH通道**：搭建中

## 网络环境（已确认）
- Mac: `192.168.110.66` (macOS)
- Windows: `192.168.110.210` (Win11)
- 用户名: `south zhang`（含空格，SSH连接时需引号）
- 同局域网，ping延迟~5ms
- SSH状态：**待开通**（ping通但端口22未开）
- QMT状态：**未开通**（待入金2万）

## SSH开通步骤（Windows管理员PowerShell）
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

## SSH连接方式（Mac→Windows）
```bash
ssh "south zhang@192.168.110.210"   # 用户名含空格需引号
```

## Architecture: Mac signals + Windows execution
```
Mac (V10 scan + iFinD data) → SSH → Windows (QMT + xtquant)
```

## QMT Data: xtdata replaces Tencent, iFinD unchanged
- ✅ Real-time quotes, K-lines, tick data (free with QMT account)
- ❌ Fundamentals, smart screening, announcements (still need iFinD)

## Risk Controls (hardcoded, non-negotiable)
1. Single stock ≤15% total assets
2. Total position ≤70%
3. Hard stop loss -6%
4. Daily max loss -3% → circuit breaker
5. Max 10 trades/day
6. Signal loss → auto-stop
7. User override → immediate halt

## User Pain Point: Can't Hold Winners
- 中韩半导体ETF: 3.886→3.8(割肉)→6(+58%)
- 鹏鼎控股: 46→70/66(卖)→87(+89%)
- Solution: Position protection period (system-enforced)
  - Days 1-3: hold unless fundamentals change
  - Profit >5%: trailing stop to +2%
  - Stop loss by logic, not P&L

## 国金 vs 银河 QMT 对比
| | 国金 | 银河 |
|--|------|------|
| 门槛 | 2万 | 10万-300万 |
| miniQMT | 直接可用 | 需单独申请 |
| 第三方库 | 自由安装 | 需白名单 |
| 本地运行 | ✅ | ❌（可能需券商机房） |
| PTrade | 同时支持 | 不支持 |

## 实际持仓（05-14收盘，11只+南风已清仓）
北投600936(3.303,500股)/航天300455(28.025,200股)/创力603012(9.943,1500股)/
金道301279(24.735,200股)/安彩600207(6.175,700股)/凯龙300912(29.98,100股)/
海兰信300065(25.005,1000股,止损22.0)/翰宇300199(23.01,500股)/
君禾603617(8.198,600股)/保变600550(16.779,600股,计划止损)/
新疆火炬603080(22.843,400股)
南风300004已清仓(+303元)
