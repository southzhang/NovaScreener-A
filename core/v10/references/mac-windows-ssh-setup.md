# Mac→Windows SSH通道搭建（QMT前置准备）

## 背景
Mac(Hermes Agent)通过SSH远程控制Windows(QMT xtquant)执行A股交易。

## 环境信息（2026-05-14）
- **Mac**: 192.168.110.66 (macOS, Hermes Agent)
- **Windows**: 192.168.110.210 (Win11, 用户名 `South Zhang`)
- **同局域网**: 192.168.110.x/24

## 已踩的坑（按出现顺序）

### 1. OpenSSH Server安装了但sshd服务不存在
**症状**: `Get-Service sshd` 报 "没有找到服务 sshd"
**根因**: `Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0` 显示Installed，但sshd.exe在WinSxS目录而非System32
**解决**:
```powershell
# 找到实际路径
Get-ChildItem -Path C:\ -Recurse -Filter "sshd.exe" -ErrorAction SilentlyContinue | Select-Object FullName
# 输出: C:\Windows\WinSxS\amd64_openssh-server-components-onecore_...\sshd.exe

# 手动注册服务
New-Service -Name sshd -BinaryPathName "<WinSxS路径>\sshd.exe" -DisplayName "OpenSSH SSH Server" -StartupType Automatic
```

### 2. 服务已存在但报"已存在"
**症状**: `New-Service` 报 "指定的服务已存在"，但 `Get-Service sshd` 找不到
**根因**: 服务存在但状态异常（exit code 1077 = 服务不存在于注册表中实际运行的位置）
**解决**: 用 `sc.exe query sshd` 确认状态，用 `Start-Service sshd` 启动

### 3. .ssh目录权限太松导致公钥认证失败
**症状**: 密钥已写入authorized_keys但SSH仍报Permission denied
**根因**: Windows sshd要求严格的文件权限
**解决**:
```powershell
# .ssh目录：只有当前用户+SYSTEM有完全控制
icacls $sshDir /inheritance:r /grant:r "$($env:USERNAME):(F)" /grant:r "SYSTEM:(F)"

# authorized_keys：只有当前用户+SYSTEM有读取权限
icacls $keyFile /inheritance:r /grant:r "$($env:USERNAME):(R)" /grant:r "SYSTEM:(R)"
```

### 4. 用户名大小写敏感
**症状**: `south zhang@192.168.110.210` 密码登录被拒
**根因**: SSH区分大小写，Windows实际用户名是 `South Zhang`（大写S大写Z）
**解决**: 用 `Get-LocalUser | Select-Object Name, Enabled` 查看准确用户名

### 5. Windows密码≠用户以为的密码
**症状**: 用户说密码是123456，实际锁屏解锁用0825
**根因**: 用户可能有多个账户/密码记忆混淆
**解决**: 让用户锁屏再解锁确认实际密码

### 6. 密码认证仍然失败（待解决）
**状态**: 用户确认锁屏密码0825，但SSH密码登录仍被拒
**可能原因**:
- Windows账户可能是Microsoft账户（非本地账户），SSH密码≠锁屏密码
- 需要在Windows设置→账户→登录选项确认"要使用Microsoft账户密码还是本地密码"
- 或者需要在Windows设置中允许"远程桌面"权限

## 待完成
- [ ] 解决SSH密码认证问题
- [ ] 配置SSH密钥免密登录
- [ ] Windows安装Python + xtquant
- [ ] 编写远程交易脚本（SSH执行xtquant下单）
- [ ] 编写信号传递架构（Mac决策→SSH→Windows执行→结果回传）

## 架构规划
```
Mac (Hermes)                    Windows (QMT)
┌──────────────┐  SSH命令  ┌──────────────────┐
│ 选股/V10扫描  │ ───────→ │ xtquant执行交易   │
│ iFinD MCP     │          │ xtdata拉K线       │
│ 策略决策      │ ←─────── │ 执行结果JSON       │
└──────────────┘  回传结果  └──────────────────┘
```
