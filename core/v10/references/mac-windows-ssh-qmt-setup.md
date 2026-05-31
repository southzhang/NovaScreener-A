# Mac → Windows SSH 连接搭建（QMT远程控制）

## 网络拓扑
- **Mac**: 192.168.110.66（Hermes Agent / iFinD / 选股策略）
- **Windows**: 192.168.110.210（QMT/xtquant，用户名 `south zhang`）
- 同局域网 192.168.110.0/24

## Windows SSH Server 搭建步骤

### 1. 安装 OpenSSH Server
管理员PowerShell执行：
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
```

### 2. 注册服务（Win11常见坑）
安装后 `Get-Service sshd` 可能报"找不到服务"，需要手动注册：
```powershell
# 查找sshd.exe实际路径（通常在WinSxS目录）
Get-ChildItem -Path C:\ -Recurse -Filter "sshd.exe" -ErrorAction SilentlyContinue | Select-Object FullName

# 用实际路径注册服务
New-Service -Name sshd -BinaryPathName "<找到的完整路径>" -DisplayName "OpenSSH SSH Server" -StartupType Automatic

# 启动
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
```

**⚠️ 常见问题**：
- `New-Service` 报"服务已存在" → 用 `sc.exe query sshd` 查状态，直接 `Start-Service sshd`
- `Start-Service` 报"找不到服务" → `Get-Service | Where-Object {$_.DisplayName -like '*ssh*'}` 搜索

### 3. 防火墙放行
```powershell
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

### 4. Mac端配置SSH密钥免密登录
```bash
# Mac上生成密钥（如果没有）
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""

# Windows上添加公钥
# 管理员PowerShell：
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh"
Add-Content "$env:USERPROFILE\.ssh\authorized_keys" "<Mac的公钥内容>"
```

### 5. 测试连接
```bash
ssh -o ConnectTimeout=10 "south zhang@192.168.110.210" "echo OK && whoami && python3 --version"
```

## QMT远程执行架构（规划）

```
Mac (Hermes Agent)                    Windows (QMT)
┌──────────────────┐    SSH命令       ┌──────────────────┐
│ V10选股/策略决策   │ ──────────────→ │ xtquant执行交易   │
│ iFinD MCP/HTTP   │                 │ xtdata拉行情/K线  │
│ 技术分析(tech.py) │ ←────────────── │ 交易结果JSON      │
│ 读取执行结果      │    SSH回传       │                   │
└──────────────────┘                 └──────────────────┘
```

**远程执行命令模板**：
```bash
# 执行交易
ssh "south zhang@192.168.110.210" "cd C:\\QMT && python trade.py --buy 600756 500 16.80"

# 拉取行情
ssh "south zhang@192.168.110.210" "cd C:\\QMT && python query.py --realtime 600756"

# 读取结果
scp "south zhang@192.168.110.210:C:/QMT/result.json" /tmp/qmt_result.json
```

## 依赖安装（QMT开通后）
```powershell
# Windows上安装Python（如果没有）
winget install Python.Python.3.11

# 安装xtquant
pip install xtquant

# 安装其他依赖
pip install numpy pandas
```

## 注意事项
- Windows用户名有空格（`south zhang`），SSH命令中用引号包裹
- Windows路径用反斜杠或双反斜杠
- xtquant只能在Windows上运行（QMT客户端依赖）
- Mac负责策略+数据，Windows负责执行+行情，通过SSH桥接
