#!/usr/bin/env python3
"""
QMT行情数据服务 v1.1
Windows端常驻运行，HTTP API供Mac调用。
修复：xtdata延迟连接+错误处理
"""
import sys, os, json, time, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# QMT路径
QMT_LIB = r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages"
QMT_BIN = r"D:\国金QMT交易端模拟\bin.x64"
sys.path.insert(0, QMT_LIB)
sys.path.insert(0, QMT_BIN)

LOG_FILE = r"C:\Users\qmt\data_server.log"

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass

_xtdata = None

def get_xtdata():
    global _xtdata
    if _xtdata is not None:
        return _xtdata
    try:
        from xtquant import xtdata
        # 禁用hello消息
        xtdata.enable_hello = False
        xtdata.connect()
        _xtdata = xtdata
        log("xtdata connected!")
        return _xtdata
    except Exception as e:
        log(f"xtdata connect failed: {e}")
        _xtdata = None
        return None

class DataHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        try:
            if path == "/health":
                xt = get_xtdata()
                self._send_json({"status": "ok", "xtdata": xt is not None})
            
            elif path == "/quote":
                codes_str = params.get("codes", [""])[0]
                if not codes_str:
                    self._send_json({"error": "missing codes"}, 400)
                    return
                
                codes = []
                for c in codes_str.split(","):
                    c = c.strip()
                    if not c: continue
                    if "." not in c:
                        c += ".SH" if c.startswith("6") or c.startswith("5") else ".SZ"
                    codes.append(c)
                
                xt = get_xtdata()
                if not xt:
                    self._send_json({"error": "xtdata not connected"}, 503)
                    return
                
                t0 = time.time()
                ticks = xt.get_full_tick(codes)
                t1 = time.time()
                
                result = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "count": 0, "elapsed_ms": round((t1-t0)*1000), "data": {}}
                for code in codes:
                    if code in ticks and ticks[code]:
                        t = ticks[code]
                        result["data"][code] = {
                            "lastPrice": t.get("lastPrice"),
                            "open": t.get("open"), "high": t.get("high"), "low": t.get("low"),
                            "lastClose": t.get("lastClose"),
                            "volume": t.get("volume"), "amount": t.get("amount"),
                            "bidPrice": t.get("bidPrice", [])[:5], "bidVol": t.get("bidVol", [])[:5],
                            "askPrice": t.get("askPrice", [])[:5], "askVol": t.get("askVol", [])[:5],
                        }
                        try:
                            detail = xt.get_instrument_detail(code)
                            if detail:
                                result["data"][code]["name"] = detail.get("InstrumentName", "")
                        except: pass
                result["count"] = len(result["data"])
                self._send_json(result)
            
            elif path == "/kline":
                code = params.get("code", [""])[0]
                period = params.get("period", ["day"])[0]
                count = int(params.get("count", ["30"])[0])
                log(f"KLINE request: code={code} period={period} count={count}")
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                if "." not in code:
                    code += ".SH" if code.startswith("6") or code.startswith("5") else ".SZ"
                
                xt = get_xtdata()
                if not xt:
                    self._send_json({"error": "xtdata not connected"}, 503)
                    return
                
                # 自动下载历史数据（QMT必需）
                # QMT period映射: day→1d, 1m→1m, 5m→5m, 15m→15m, 30m→30m, 60m→1h
                qmt_period = {"day": "1d", "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "1h", "1h": "1h"}.get(period, "1d")
                log(f"KLINE download: code={code} qmt_period={qmt_period}")
                try:
                    xt.download_history_data(code, period=qmt_period, start_time="", incrementally=True)
                    # 增量下载通常<1秒，首次下载需3秒
                    time.sleep(1.0)
                except Exception as e:
                    log(f"download_history_data warning: {e}")
                
                data = xt.get_market_data_ex(
                    field_list=["time","open","high","low","close","volume","amount"],
                    stock_list=[code], period=qmt_period, count=count
                )
                log(f"KLINE result: code={code} in_data={code in data} rows={len(data[code]) if code in data else 0}")
                result = {"code": code, "period": period, "count": 0, "data": []}
                if code in data:
                    df = data[code]
                    for idx, row in df.iterrows():
                        result["data"].append({
                            "time": str(idx),
                            "open": float(row.get("open",0)), "high": float(row.get("high",0)),
                            "low": float(row.get("low",0)), "close": float(row.get("close",0)),
                            "volume": float(row.get("volume",0)), "amount": float(row.get("amount",0)),
                        })
                    result["count"] = len(result["data"])
                self._send_json(result)
            
            elif path == "/batch_kline":
                """批量获取K线（V10扫描专用，支持多只同时下载）"""
                codes_str = params.get("codes", [""])[0]
                period = params.get("period", ["day"])[0]
                count = int(params.get("count", ["250"])[0])
                if not codes_str:
                    self._send_json({"error": "missing codes"}, 400)
                    return
                
                codes = []
                for c in codes_str.split(","):
                    c = c.strip()
                    if not c: continue
                    if "." not in c:
                        c += ".SH" if c.startswith("6") or c.startswith("5") else ".SZ"
                    codes.append(c)
                
                xt = get_xtdata()
                if not xt:
                    self._send_json({"error": "xtdata not connected"}, 503)
                    return
                
                # 批量下载+获取
                # QMT period映射
                qmt_period = {"day": "1d", "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "1h", "1h": "1h"}.get(period, "1d")
                t0 = time.time()
                for code in codes:
                    try:
                        xt.download_history_data(code, period=qmt_period, start_time="", incrementally=True)
                    except: pass
                time.sleep(0.5)  # 等待批量下载
                
                data = xt.get_market_data_ex(
                    field_list=["time","open","high","low","close","volume","amount"],
                    stock_list=codes, period=qmt_period, count=count
                )
                t1 = time.time()
                
                result = {"count": 0, "elapsed_ms": round((t1-t0)*1000), "data": {}}
                for code in codes:
                    if code in data:
                        df = data[code]
                        bars = []
                        for idx, row in df.iterrows():
                            bars.append({
                                "time": str(idx),
                                "open": float(row.get("open",0)), "high": float(row.get("high",0)),
                                "low": float(row.get("low",0)), "close": float(row.get("close",0)),
                                "volume": float(row.get("volume",0)), "amount": float(row.get("amount",0)),
                            })
                        result["data"][code] = bars
                result["count"] = len(result["data"])
                self._send_json(result)
            
            elif path == "/full_market":
                """全市场行情（V10全扫描专用，一次调完）"""
                xt = get_xtdata()
                if not xt:
                    self._send_json({"error": "xtdata not connected"}, 503)
                    return
                
                t0 = time.time()
                # 1. 获取股票列表（含名称）
                all_codes = xt.get_stock_list_in_sector("沪深A股")
                if not all_codes:
                    self._send_json({"error": "get_stock_list_in_sector failed"}, 500)
                    return
                
                # 过滤科创板+北交所
                qmt_codes = [c for c in all_codes if not c.startswith(("688", "689", "8", "4", "9"))]
                
                # 2. 批量获取名称映射（从get_stock_list_in_sector结果中提取）
                #    注意：get_stock_list_in_sector返回的是带后缀的代码列表
                #    需要用get_instrument_detail获取名称，但可以批量优化
                #    先用空名称，后面用get_market_data_ex拿数据
                name_map = {}
                # 批量获取名称 - 分批处理避免超时
                batch_size = 200
                for i in range(0, len(qmt_codes), batch_size):
                    batch = qmt_codes[i:i+batch_size]
                    for qc in batch:
                        try:
                            detail = xt.get_instrument_detail(qc)
                            if detail:
                                name_map[qc] = detail.get("InstrumentName", "")
                        except:
                            pass
                    if i % 1000 == 0 and i > 0:
                        log(f"  名称获取进度: {i}/{len(qmt_codes)}")
                
                # 3. 批量获取行情数据（一次调用）
                data = xt.get_market_data_ex(
                    field_list=[], stock_list=qmt_codes,
                    period="1d", count=1
                )
                t1 = time.time()
                
                result = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "count": 0, 
                          "elapsed_ms": round((t1-t0)*1000), "data": {}}
                for qmt_code, df in data.items():
                    if df is None or df.empty:
                        continue
                    row = df.iloc[-1]
                    code = qmt_code.split(".")[0]
                    if code[:3] in ("688", "689") or code[0] in ("8", "4", "9"):
                        continue
                    last_close = float(row.get("lastClose", row.get("close", 0)))
                    close_price = float(row.get("close", 0))
                    vol = float(row.get("volume", 0))
                    amt = float(row.get("amount", 0))
                    # QMT返回0表示停牌或未开盘，跳过
                    if close_price <= 0 and last_close <= 0:
                        continue
                    # 涨停价/跌停价（四舍五入到2位）
                    if last_close > 0:
                        limit_up = round(last_close * 1.1, 2) if code[:3] != "300" and code[:3] != "301" else round(last_close * 1.2, 2)
                        limit_down = round(last_close * 0.9, 2) if code[:3] != "300" and code[:3] != "301" else round(last_close * 0.8, 2)
                    else:
                        limit_up = limit_down = 0
                    result["data"][code] = {
                        "name": name_map.get(qmt_code, ""),
                        "lastPrice": close_price if close_price > 0 else last_close,
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "prevClose": last_close,
                        "volume": vol,
                        "amount": amt,
                        "limit_up": limit_up,
                        "limit_down": limit_down,
                    }
                result["count"] = len(result["data"])
                t2 = time.time()
                log(f"FULL_MARKET: {result['count']}只, 名称{t1-t0:.1f}s, 行情{t2-t1:.1f}s, 总{t2-t0:.1f}s")
                self._send_json(result)
            
            else:
                self._send_json({"error": f"unknown: {path}"}, 404)
        
        except Exception as e:
            log(f"Error: {e}\n{traceback.format_exc()}")
            self._send_json({"error": str(e)}, 500)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18888)
    parser.add_argument("--prefetch", action="store_true", help="预下载全市场K线(约3分钟)")
    args = parser.parse_args()
    
    log(f"Starting QMT Data Server on port {args.port}...")
    xt = get_xtdata()
    log(f"xtdata: {'connected' if xt else 'FAILED'}")
    
    if xt and args.prefetch:
        log("预下载全市场日K线...")
        try:
            stocks = xt.get_stock_list_in_sector("沪深A股")
            total = len(stocks) if stocks else 0
            log(f"共{total}只股票")
            t0 = time.time()
            done = 0
            for code in (stocks or []):
                try:
                    xt.download_history_data(code, period="1d", start_time="", incrementally=True)
                    done += 1
                    if done % 500 == 0:
                        log(f"  预下载进度: {done}/{total} ({done/total*100:.0f}%)")
                except:
                    pass
            log(f"预下载完成: {done}只, 耗时{time.time()-t0:.0f}秒")
        except Exception as e:
            log(f"预下载失败: {e}")
    
    server = HTTPServer(("0.0.0.0", args.port), DataHandler)
    log(f"Listening on 0.0.0.0:{args.port}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down")
        server.server_close()
