# 数据源自检审计模式 (2026-05-13)

## 审计清单

当用户说"自检一下"或"检查数据源"时，按以下清单逐项检查：

### 1. Cron任务一致性
```bash
python3 -c "
import json
with open('/Users/southzhang/.hermes/cron/jobs.json') as f:
    data = json.load(f)
for job in data.get('jobs', []):
    if not job.get('enabled', True): continue
    prompt = job.get('prompt', '')
    script = job.get('script', '')
    # 检查是否引用了过期的脚本名或数据源
    print(f'{job[\"name\"]}: script={script or \"none\"}')
"
```

### 2. 脚本编译检查
```bash
cd ~/.hermes/workspace
python3 -c "
import py_compile
for f in ['v10_realtime_scan.py', 'v10_intraday_monitor.py', 
          'v10_auto_trade.py', 'tech_analysis.py',
          'intraday_holdings_monitor.py']:
    py_compile.compile(f, doraise=True)
    print(f'✅ {f}')
"
```

### 3. 常见问题模式

| 问题 | 检查方式 | 修复 |
|------|----------|------|
| 硬编码日期 | grep搜索日期字符串如`20260513` | 改为`datetime.now().strftime()` |
| SSL context残留 | grep `ctx = ssl` / `import ssl` | 删除或改用HTTP |
| 旧脚本引用 | cron prompt中grep旧脚本名 | 更新prompt |
| Token硬编码 | grep API key/token字符串 | 改为环境变量+.env fallback |
| 持仓列表不同步 | 对比脚本持仓和实际持仓 | 更新脚本 |
| 两版脚本共存 | ls检查scripts/和workspace/ | 统一指向新版 |
| Hermes版本缓存过期 | hermes version显示behind但git pull是latest | 删除~/.hermes/.update_check |

### 4. 运行时验证
```bash
# iFinD MCP连接
python3 ~/.hermes/scripts/ifind_refresh_token.py

# 腾讯行情
python3 -c "
import urllib.request
url = 'https://qt.gtimg.cn/q=sh600000'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=10)
print('OK' if resp.status == 200 else 'FAIL')
"
```

## 自检发现记录 (2026-05-13)

1. v10_realtime_scan.py 板块排名日期硬编码 20260513 → 修复为 datetime.now()
2. 实盘盯盘cron指向旧版 scripts/ 脚本 → 更新为 workspace/ 版
3. v10_intraday_monitor.py 两版共存(scripts/旧版17K, workspace/新版22K) → cron统一指向workspace版
4. hermes version缓存(.update_check)过期 → 显示489 behind但实际已最新，清缓存修复
