# Mac→Win11 SSH通道（QMT集成前置）

## 概述
Mac（Hermes Agent）通过SSH远程控制Windows（QMT/xtquant），实现选股决策→自动交易的闭环。

## 当前状态（2026-05-14）
- Windows IP: `192.168.110.210`（DHCP，可能变化）
- Windows用户名: `south zhang`（含空格）
- SSH服务: ✅ 已安装并运行
- SSH密钥认证: ⚠️ 待完成（密码认证未测试）
- QMT: ❌ 未开通（等入金2万到国金证券）

## Win11 OpenSSH Server安装步骤

### 1. 安装OpenSSH Server
```powershell
# 管理员PowerShell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
```

### 2. 启动服务
```powershell
# 如果Get-Service sshd报"找不到服务"，需要手动注册：
# 先找sshd.exe路径（可能在WinSxS而非System32）
Get-ChildItem -Path C:\ -Recurse -Filter "sshd.exe" -ErrorAction SilentlyContinue | Select-Object FullName

# 注册服务
New-Service -Name sshd -BinaryPathName "<找到的完整路径>" -DisplayName "OpenSSH SSH Server" -StartupType Automatic

# 启动
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
```

**⚠️ 常见坑**：
- `Start-Service sshd`报"找不到服务"→ 服务没注册，需要`New-Service`手动注册
- `sshd.exe`不在`C:\Windows\System32\OpenSSH\`→ 可能在`C:\Windows\WinSxS\amd64_openssh-server-components-onecore_*`目录
- `New-Service`报"服务已存在"→ 用`sc.exe query sshd`确认状态，可能只是STOPPED

### 3. 防火墙放行
```powershell
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

### 4. SSH密钥认证配置

**Mac端**：
```bash
# 生成密钥（如果没有）
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

**Windows端**：
```powershell
# 创建.ssh目录
mkdir "$env:USERPROFILE\.ssh"

# 写入公钥（注意：Join-Path处理空格路径）
$key = "ssh-ed25519 AAAA... southzhang@Mac-mini.local"
Set-Content -Path (Join-Path $env:USERPROFILE ".ssh\authorized_keys") -Value $key -Encoding ascii

# 修复权限（⚠️ 必须！ssh对权限极严）
$sshDir = Join-Path $env:USERPROFILE ".ssh"
$keyFile = Join-Path $env:USERPROFILE ".ssh\authorized_keys"
icacls $sshDir /inheritance:r /grant:r "$($env:USERNAME):(F)" /grant:r "SYSTEM:(F)"
icacls $keyFile /inheritance:r /grant:r "$($env:USERNAME):(R)" /grant:r "SYSTEM:(R)"

# 重启sshd
Restart-Service sshd
```

**⚠️ SSH密钥认证权限坑**：
- `.ssh`目录权限太宽（有Administrators/其他用户）→ ssh拒绝读取authorized_keys
- `authorized_keys`编码必须ASCII/UTF-8无BOM
- `$env:USERNAME`在icacls中要用`$($env:USERNAME)`包裹
- Windows用户名含空格时，路径必须用`Join-Path`或双引号包裹

### 5. 测试
```bash
# Mac端
ssh -o ConnectTimeout=10 "south zhang@192.168.110.210" "whoami"
```

## QMT集成规划（待QMT开通后实施）

```
Mac (Hermes Agent)                    Windows (QMT)
┌─────────────────┐                  ┌──────────────────┐
│ 选股/V10扫描     │   SSH命令        │ xtquant执行交易   │
│ iFinD MCP        │ ──────────────→ │ xtdata拉K线       │
│ 策略决策          │                  │                   │
│                  │ ←────────────── │ 执行结果JSON       │
│ 读取交易结果      │  SSH回传         │                   │
└─────────────────┘                  └──────────────────┘
```

**工作流**：
1. Mac选股决策 → 写入交易指令JSON
2. SSH到Windows执行 `python trade.py --buy 600756 500 16.80`
3. xtquant下单 → 结果写JSON
4. Mac读取结果确认成交

**待安装**：
- Python 3.10+（Windows）
- xtquant SDK（随QMT开通）
- numpy（V10计算用）
