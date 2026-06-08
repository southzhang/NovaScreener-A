#!/usr/bin/env python3
"""
V10 尾盘预取脚本 (14:25)
从V10 watchlist读取信号股，用腾讯行情API获取实时行情+资金面，
写入 ~/.hermes/cache/v10_tail_prefetch.json 供14:30 agent消费。

no_agent模式运行，不调LLM，纯机械数据采集。
"""
import json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime

# 不使用代理（腾讯行情是国内API，直接访问）
PROXIES = {}

CACHE_DIR = os.path.expanduser("~/.hermes/cache")
WATCHLIST_PATH = os.path.join(CACHE_DIR, "v10_watchlist.json")
OUTPUT_PATH = os.path.join(CACHE_DIR, "v10_tail_prefetch.json")
def is_trading_time():
    """检查是否在交易时段（14:20-15:00给预取用）"""
    now = datetime.now()
    h, m = now.hour, now.minute
    # 宽松窗口：14:20-15:00
    if h == 14 and 20 <= m <= 59:
        return True
    if h == 15 and m == 0:
        return True
    return False

def batch_get_sectors(codes, max_retries=2):
    """
    批量查股票板块归属（东方财富datacenter-web API）
    返回 {code: [sector1, sector2, ...]} 格式
    不受VPN限制，每只股票约0.3秒
    """
    result = {}
    total = len(codes)
    for idx, code in enumerate(codes):
        for retry in range(max_retries):
            try:
                url = (
                    "https://datacenter-web.eastmoney.com/api/data/v1/get"
                    f"?reportName=RPT_F10_CORETHEME_BOARDTYPE"
                    f"&columns=SECURITY_CODE,BOARD_NAME,BOARD_RANK,IS_PRECISE,BOARD_CODE"
                    f"&filter=(SECURITY_CODE=%22{code}%22)"
                    f"&pageSize=10&sortColumns=BOARD_RANK&sortTypes=1"
                    f"&source=HSF10&client=PC"
                )
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                })
                resp = urllib.request.urlopen(req, timeout=4)
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("result") and data["result"].get("data"):
                    sectors = [item["BOARD_NAME"] for item in data["result"]["data"]]
                    if sectors:
                        result[code] = sectors[:5]  # 最多取5个
                        break  # 成功，跳出重试
            except Exception as e:
                if retry < max_retries - 1:
                    time.sleep(0.2)
                else:
                    print(f"⚠️ {code}板块查询失败: {e}", file=sys.stderr)
        # 每10个打印一次进度
        if (idx + 1) % 10 == 0:
            print(f"  板块查询: {idx+1}/{total}", file=sys.stderr)
    return result


def fetch_hot_sectors(top_n=15):
    """
    获取今日热点行业板块TOP N（同花顺行业板块排行）
    返回 [(排名, 板块名, 涨跌幅%, 主力净流入万), ...]
    不受VPN限制
    """
    try:
        url = "https://q.10jqka.com.cn/thshy/"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
        })
        resp = urllib.request.urlopen(req, timeout=6)
        raw = resp.read()
        # 尝试gbk解码
        try:
            text = raw.decode("gbk")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")

        # 解析表格行
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.DOTALL)
        hot = []
        for row in rows[1:]:  # 跳过表头行
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if len(cells) >= 6:
                rank = cells[0]
                name = cells[1]
                change_pct = cells[2]
                main_inflow = cells[5] if len(cells) > 5 else "N/A"
                try:
                    hot.append((int(rank), name, float(change_pct), main_inflow))
                except ValueError:
                    hot.append((len(hot)+1, name, change_pct, main_inflow))
        return hot[:top_n]
    except Exception as e:
        print(f"⚠️ 热点板块查询失败: {e}", file=sys.stderr)
        return []


def tencent_batch_quote(codes):
    """批量获取腾讯实时行情，codes是股票代码列表(如['600203','300410'])"""
    if not codes:
        return {}
    
    # 构建secid列表
    secids = []
    for c in codes:
        if c.startswith('6'):
            secids.append(f"sh{c}")
        else:
            secids.append(f"sz{c}")
    
    # 加上三大指数
    secids.extend(['sh000001', 'sz399001', 'sz399006'])
    
    # 批量查询（每批最多80个）
    results = {}
    for i in range(0, len(secids), 80):
        batch = secids[i:i+80]
        qs = ",".join(batch)
        url = f"https://qt.gtimg.cn/q={qs}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            txt = resp.read().decode('gbk', errors='ignore')
            results.update(parse_tencent_batch(txt))
        except Exception as e:
            print(f"⚠️ 腾讯行情批次{i//80}失败: {e}", file=sys.stderr)
    
    return results

def parse_tencent_batch(output):
    """解析腾讯qt.gtimg.cn批量返回"""
    stocks = {}
    for line in output.strip().split('\n'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        try:
            # 格式: v_sh600203="1~福日电子~600203~...~";
            m = re.search(r'v_(\w+)="(.+)"', line)
            if not m:
                continue
            secid = m.group(1)
            parts = m.group(2).split('~')
            if len(parts) < 50:
                continue
            
            code = parts[2]
            name = parts[1]
            
            def safe_float(idx, default=0):
                try:
                    return float(parts[idx]) if parts[idx] else default
                except (ValueError, IndexError):
                    return default
            
            def safe_int(idx, default=0):
                try:
                    return int(float(parts[idx])) if parts[idx] else default
                except (ValueError, IndexError):
                    return default
            
            # 判断是指数还是个股
            is_index = code in ['000001', '399001', '399006']
            
            stocks[code] = {
                "secid": secid,
                "name": name,
                "code": code,
                "current_price": safe_float(3),
                "yesterday_close": safe_float(4),
                "open_price": safe_float(5),
                "volume": safe_int(36),  # 成交量(手)
                "buy_volume": safe_int(7),  # 外盘(手)
                "sell_volume": safe_int(8),  # 内盘(手)
                "change": safe_float(31),
                "change_pct": safe_float(32),
                "high": safe_float(33),
                "low": safe_float(34),
                "amount": safe_float(37),  # 万元
                "turnover_rate": safe_float(38),
                "pe_dynamic": safe_float(39) if not is_index else 0,
                "circ_market_cap": safe_float(44),  # 流通市值(亿)
                "total_market_cap": safe_float(45),  # 总市值(亿)
                "limit_up": safe_float(47),  # 涨停价
                "limit_down": safe_float(48),  # 跌停价
                "amplitude": safe_float(43),
                "main_inflow": safe_float(50) if len(parts) > 50 else 0,  # 主力净流入(万元)
                "is_index": is_index,
            }
            
            # 计算振幅（如果字段43为0则手动算）
            if stocks[code]["amplitude"] == 0 and stocks[code]["yesterday_close"] > 0:
                h, l = stocks[code]["high"], stocks[code]["low"]
                if h > 0 and l > 0:
                    stocks[code]["amplitude"] = round((h - l) / stocks[code]["yesterday_close"] * 100, 2)
            
        except Exception:
            continue
    
    return stocks

def main():
    force = "--force" in sys.argv

    # 交易时间检查（--force 跳过）
    if not is_trading_time() and not force:
        print("⛔ 非交易时间（14:20-15:00），跳过预取。使用 --force 强制执行", file=sys.stderr)
        write_empty_cache("非交易时间")
        return
    if not is_trading_time() and force:
        print("⚠️ 非交易时间，但 --force 强制执行", file=sys.stderr)
    
    # Step 1: 读取watchlist
    if not os.path.exists(WATCHLIST_PATH):
        print("⛔ watchlist.json不存在", file=sys.stderr)
        # 写空缓存
        write_empty_cache("watchlist不存在")
        return
    
    with open(WATCHLIST_PATH) as f:
        watchlist = json.load(f)
    
    stocks = watchlist.get("stocks", [])
    scan_time = watchlist.get("scan_time", "")
    count = watchlist.get("count", 0)
    
    # ⏰ 时效性校验：watchlist必须在最近10分钟内扫描的才有效
    if scan_time:
        try:
            st = datetime.strptime(scan_time, "%Y-%m-%d %H:%M:%S")
            age_minutes = (datetime.now() - st).total_seconds() / 60
            if age_minutes > 10:
                print(f"⏰ watchlist数据过期({age_minutes:.0f}分钟前)，跳过预取", file=sys.stderr)
                write_empty_cache(f"watchlist过期({int(age_minutes)}min前)")
                return
            print(f"📅 watchlist时效性OK: {age_minutes:.0f}分钟前")
        except ValueError:
            print(f"⚠️ 无法解析scan_time: {scan_time}，继续")
    
    if count == 0:
        print("今日无V10信号，写入空缓存")
        write_empty_cache("今日无V10信号", scan_date=scan_time)
        return
    
    # 只取全买入和强庄买
    candidates_list = [s for s in stocks if s.get("signal") in ["全买入", "强庄买"]]
    
    # 如果没有全买入/强庄买，也包含基础买（但标注）
    if not candidates_list:
        candidates_list = stocks  # 全部纳入
        print(f"⚠️ 无全买入/强庄买信号，纳入全部{len(candidates_list)}只基础买", file=sys.stderr)
    
    codes = [s["code"] for s in candidates_list]
    print(f"📊 候选股: {len(codes)}只 - {', '.join(codes[:10])}")
    
    # Step 2: 腾讯行情批量获取（无重试，单次+硬超时，失败即降级）
    print("⏳ 获取腾讯实时行情...")
    quotes = tencent_batch_quote(codes)
    fetch_failed = False
    if not quotes:
        fetch_failed = True
        print("❌ 腾讯行情API返回空数据，写入带降级标记的缓存", file=sys.stderr)
    print(f"✅ 获取到{len(quotes)}只股票行情")
    
    # Step 2.5: 批量查板块行业归属（东方财富datacenter-web API，不受VPN限制）
    sector_info = {}
    if codes:
        print("⏳ 查板块行业归属...")
        sector_info = batch_get_sectors(codes)
        print(f"✅ 查出{len(sector_info)}只股票的板块归属")
    
    # Step 2.6: 获取今日热点行业板块TOP15
    print("⏳ 获取热点板块排行...")
    hot_sectors = fetch_hot_sectors(15)
    if hot_sectors:
        print(f"✅ 获取到{len(hot_sectors)}个热点板块 (TOP1: {hot_sectors[0][1]})")
    else:
        print("⚠️ 热点板块数据为空")
    
    # 提取指数数据
    index_data = {}
    for idx_code in ['000001', '399001', '399006']:
        if idx_code in quotes:
            q = quotes[idx_code]
            index_data[f"{'sh' if idx_code.startswith('0') else 'sz'}{idx_code}"] = {
                "name": q["name"],
                "price": q["current_price"],
                "change_pct": q["change_pct"],
                "amount": q["amount"],
            }
    
    # Step 3: 组装candidates
    candidates = {}
    for s in candidates_list:
        code = s["code"]
        q = quotes.get(code, {})
        
        # 构建real_time_quote
        rt_quote = {
            "name": q.get("name", s.get("name", "")),
            "code": code,
            "current_price": q.get("current_price", s.get("price", 0)),
            "yesterday_close": q.get("yesterday_close", 0),
            "open_price": q.get("open_price", 0),
            "change_pct": q.get("change_pct", 0),
            "change": q.get("change", 0),
            "high": q.get("high", 0),
            "low": q.get("low", 0),
            "volume": q.get("volume", 0),
            "amount": q.get("amount", 0),
            "turnover_rate": q.get("turnover_rate", 0),
            "amplitude": q.get("amplitude", 0),
            "buy_volume": q.get("buy_volume", 0),
            "sell_volume": q.get("sell_volume", 0),
            "pe_dynamic": q.get("pe_dynamic", 0),
        }
        
        # 判断尾盘走势
        if q.get("current_price", 0) > 0 and q.get("high", 0) > 0:
            price_pos = (q["current_price"] - q.get("low", 0)) / (q["high"] - q.get("low", 0)) if q["high"] != q.get("low", 0) else 0.5
            if price_pos > 0.8:
                rt_quote["latest_change"] = "尾盘运行在日内高位"
            elif price_pos > 0.5:
                rt_quote["latest_change"] = "尾盘运行在日内中高位"
            elif price_pos > 0.3:
                rt_quote["latest_change"] = "尾盘运行在日内中位"
            else:
                rt_quote["latest_change"] = "尾盘运行在日内低位"
        
        candidates[code] = {
            "code": code,
            "name": s.get("name", q.get("name", "")),
            "signal": s.get("signal", ""),
            "real_time_quote": rt_quote,
            "sector_info": {
                "source": "datacenter-web",
                "raw_content": "; ".join(sector_info.get(code, [])),
                "sectors": sector_info.get(code, []),
            },
            "capital_flow": {
                "source": "腾讯field[50]",
                "value": q.get("main_inflow", 0),
                "has_data": q.get("main_inflow", 0) != 0,
            },
            "key_levels": s.get("key_levels", {}),
        }
    
    # Step 4: 写入缓存
    output = {
        "prefetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan_date": scan_time,
        "_fetch_failed": fetch_failed,
        "_note": "腾讯行情API返回空数据，行情字段不可信" if fetch_failed else "",
        "signals": {
            "full_buy": [s["code"] for s in candidates_list if s.get("signal") == "全买入"],
            "strong_buy": [s["code"] for s in candidates_list if s.get("signal") == "强庄买"],
            "base_buy": [s["code"] for s in candidates_list if s.get("signal") == "基础买"],
        },
        "candidates": candidates,
        "sectors": {
            "trending_sectors": [
                {"rank": r, "name": n, "change_pct": c, "main_inflow": mi}
                for r, n, c, mi in hot_sectors
            ] if hot_sectors else [],
            "source": "10jqka-thshy",
        },
        "index": index_data,
    }
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 预取完成: {len(candidates)}只候选股，写入 {OUTPUT_PATH}")
    print(f"📊 大盘: {index_data.get('sh000001', {}).get('price', 'N/A')} ({index_data.get('sh000001', {}).get('change_pct', 'N/A')}%)")

def write_empty_cache(reason="", scan_date=""):
    """写入空缓存（0信号场景）"""
    output = {
        "prefetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan_date": scan_date,
        "signals": {"full_buy": [], "strong_buy": [], "base_buy": []},
        "candidates": {},
        "sectors": {"trending_sectors": [], "concepts": []},
        "index": {},
        "_note": reason,
    }
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"写入空缓存: {reason}")

if __name__ == "__main__":
    main()
