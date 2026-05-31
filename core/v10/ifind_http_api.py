#!/usr/bin/env python3
"""
同花顺iFinD HTTP API封装模块
数据源: quantapi.51ifind.com
认证: access_token (由refresh_token获取，与MCP的JWT不同)

用法:
    from ifind_http_api import iFinD
    
    # 实时行情
    df = iFinD.realtime(["300033.SZ", "600000.SH"], ["latest", "changeRatio", "volume"])
    
    # 分钟K线
    df = iFinD.high_frequency("300033.SZ", "2026-05-13 09:30:00", "2026-05-13 15:00:00")
    
    # 日K线
    df = iFinD.history("300033.SZ", "2026-04-01", "2026-05-13")
    
    # 基本面数据
    df = iFinD.basic_data(["300033.SZ"], ["ths_pe_ratio_stock", "ths_total_market_cap_stock"])
    
    # 智能选股
    results = iFinD.smart_picking("涨跌幅")
    
    # 公告查询
    df = iFinD.announcements("300033.SZ", report_type="901")
    
    # 日期序列（财务趋势）
    data = iFinD.date_serial("300033.SZ", "20230101", "20260513", ["ths_roe_stock", "ths_np_yoy_stock"])
    
    # 财务趋势便捷方法（自动获取ROE/净利润/营收趋势）
    trend = iFinD.financial_trend("300033.SZ", years=3)
    
    # 专题报表（板块成分）
    data = iFinD.data_pool("p03291", {"date": "20260513", "blockname": "001031"})
"""

import requests
import json
import time
import os
import threading
import pandas as pd
from datetime import datetime, timedelta

pd.set_option('float_format', lambda x: '%.2f' % x)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)
pd.set_option('display.max_columns', 20)
pd.set_option('display.width', 500)

# Token缓存文件
TOKEN_CACHE_FILE = os.path.expanduser("~/.hermes/scripts/ifind_token_cache.json")
BASE_URL = "https://quantapi.51ifind.com/api/v1"
GET_TOKEN_URL = f"{BASE_URL}/get_access_token"


class iFinDAPI:
    """同花顺iFinD HTTP API封装"""
    
    def __init__(self, refresh_token=None):
        self.refresh_token = refresh_token or os.environ.get("IFIND_REFRESH_TOKEN", "")
        self.access_token = None
        self.token_expiry = 0
        self._lock = threading.Lock()
        self._load_cached_token()
    
    def _load_cached_token(self):
        """加载缓存的access_token"""
        try:
            if os.path.exists(TOKEN_CACHE_FILE):
                with open(TOKEN_CACHE_FILE, 'r') as f:
                    cache = json.load(f)
                if cache.get('expires_at', 0) > time.time():
                    self.access_token = cache['access_token']
                    self.token_expiry = cache['expires_at']
                    return
        except Exception:
            pass
    
    def _save_token_cache(self):
        """缓存access_token"""
        try:
            os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
            with open(TOKEN_CACHE_FILE, 'w') as f:
                json.dump({
                    'access_token': self.access_token,
                    'expires_at': self.token_expiry,
                    'updated_at': datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"[iFinD] Token缓存保存失败: {e}")
    
    def _refresh_access_token(self):
        """刷新access_token（线程安全）"""
        if not self.refresh_token:
            raise ValueError("refresh_token未设置！请设置环境变量 IFIND_REFRESH_TOKEN 或传入refresh_token参数")
        
        with self._lock:
            # 双重检查：获取锁后再次确认是否需要刷新
            if self.access_token and time.time() < self.token_expiry - 3600:
                return True
            try:
                resp = requests.post(
                    url=GET_TOKEN_URL,
                    headers={
                        "Content-Type": "application/json",
                        "refresh_token": self.refresh_token
                    },
                    timeout=10
                )
                data = json.loads(resp.content)
                if 'data' in data and 'access_token' in data['data']:
                    self.access_token = data['data']['access_token']
                    # access_token默认有效期约24小时，缓存20小时
                    self.token_expiry = time.time() + 20 * 3600
                    self._save_token_cache()
                    print(f"[iFinD] Token刷新成功，有效期至 {datetime.fromtimestamp(self.token_expiry).strftime('%Y-%m-%d %H:%M')}")
                    return True
                else:
                    print(f"[iFinD] Token刷新失败: {data}")
                    return False
            except Exception as e:
                print(f"[iFinD] Token刷新异常: {e}")
                return False
    
    def _get_headers(self):
        """获取请求头，自动刷新token"""
        if not self.access_token or time.time() > self.token_expiry - 3600:
            if not self._refresh_access_token():
                print("[iFinD] ⚠️ Token刷新失败，请求可能返回401")
        return {
            "Content-Type": "application/json",
            "access_token": self.access_token
        }
    
    def _post(self, endpoint, params, timeout=30):
        """通用POST请求"""
        url = f"{BASE_URL}/{endpoint}"
        try:
            resp = requests.post(url=url, json=params, headers=self._get_headers(), timeout=timeout)
            if resp.status_code == 401:
                print(f"[iFinD] ❌ 401未授权，Token可能过期。尝试刷新...")
                self.access_token = None
                resp = requests.post(url=url, json=params, headers=self._get_headers(), timeout=timeout)
            elif resp.status_code != 200:
                print(f"[iFinD] ❌ HTTP {resp.status_code} {endpoint}")
            data = json.loads(resp.content)
            return data
        except Exception as e:
            print(f"[iFinD] 请求失败 {endpoint}: {e}")
            return {"error": str(e)}
    
    # ========== 实时行情 ==========
    def realtime(self, codes, indicators=None):
        """
        获取实时行情数据
        codes: 股票代码列表，如 ["300033.SZ", "600000.SH"]
        indicators: 指标列表，如 ["latest", "changeRatio", "volume", "amount"]
                    常用指标: open,high,low,latest,change,changeRatio,volume,amount,
                    bid1,ask1,bidSize1,askSize1,pe,pb,totalMarketValue,circulationMarketValue
        """
        if indicators is None:
            indicators = ["open", "high", "low", "latest", "changeRatio", "volume", "amount"]
        
        codes_str = ",".join(codes) if isinstance(codes, list) else codes
        params = {
            "codes": codes_str,
            "indicators": ",".join(indicators) if isinstance(indicators, list) else indicators
        }
        
        data = self._post("real_time_quotation", params)
        
        if 'tables' in data:
            try:
                df = pd.json_normalize(data['tables'])
                if 'pricetype' in df.columns:
                    df = df.drop(columns=['pricetype'])
                return df
            except Exception:
                return data
        return data
    
    # ========== 分钟K线 ==========
    def high_frequency(self, code, start_time, end_time, indicators=None):
        """
        获取分钟级K线数据
        code: 单只股票代码，如 "300033.SZ"
        start_time: 开始时间 "2026-05-13 09:30:00"
        end_time: 结束时间 "2026-05-13 15:00:00"
        indicators: 指标，如 "open,high,low,close,volume,amount,changeRatio"
        """
        if indicators is None:
            indicators = "open,high,low,close,volume,amount,changeRatio"
        
        params = {
            "codes": code,
            "indicators": indicators,
            "starttime": start_time,
            "endtime": end_time
        }
        
        data = self._post("high_frequency", params, timeout=60)
        
        if 'tables' in data:
            try:
                df = pd.json_normalize(data['tables'])
                return df
            except Exception:
                return data
        return data
    
    # ========== 历史日K线 ==========
    def history(self, codes, start_date, end_date, indicators=None):
        """
        获取历史日频K线数据
        codes: 股票代码，多只用逗号分隔 "300033.SZ,600000.SH"
        start_date: "2026-04-01"
        end_date: "2026-05-13"
        """
        if indicators is None:
            indicators = "open,high,low,close,volume,amount,changeRatio"
        
        codes_str = ",".join(codes) if isinstance(codes, list) else codes
        params = {
            "codes": codes_str,
            "indicators": indicators,
            "startdate": start_date,
            "enddate": end_date,
            "functionpara": {"Fill": "Blank"}
        }
        
        data = self._post("cmd_history_quotation", params)
        
        if 'tables' in data:
            try:
                dfs = []
                for table in data['tables']:
                    df = pd.json_normalize(table)
                    dfs.append(df)
                return pd.concat(dfs, ignore_index=True) if dfs else data
            except Exception:
                return data
        return data
    
    # ========== 基本面数据 ==========
    def basic_data(self, codes, indicators):
        """
        获取基本面数据（财务指标、估值等）
        codes: 股票代码列表
        indicators: 指标列表，常用:
            - ths_pe_ratio_stock: 市盈率PE
            - ths_pb_ratio_stock: 市净率PB
            - ths_total_market_cap_stock: 总市值
            - ths_circulation_market_cap_stock: 流通市值
            - ths_roe_deducted_stock: 扣非ROE
            - ths_net_profit_yoy_stock: 净利润同比增速
            - ths_revenue_yoy_stock: 营收同比增速
            - ths_total_shares_stock: 总股本
        """
        codes_str = ",".join(codes) if isinstance(codes, list) else codes
        
        # 构建indipara
        indipara = []
        for ind in (indicators if isinstance(indicators, list) else [indicators]):
            indipara.append({"indicator": ind, "indiparams": []})
        
        params = {
            "codes": codes_str,
            "indipara": indipara
        }
        
        data = self._post("basic_data_service", params)
        
        if 'tables' in data:
            try:
                df = pd.json_normalize(data['tables'])
                return df
            except Exception:
                return data
        return data
    
    # ========== 日期序列数据 ==========
    def date_serial(self, codes, start_date, end_date, indicators, interval="Q", fill="Blank"):
        """
        获取多日时间序列基本面数据（财务趋势分析核心）
        codes: "300033.SZ" 或 ["300033.SZ", "600000.SH"]
        start_date/end_date: "20230101" / "20260513" (支持YYYYMMDD/YYYY-MM-DD)
        indicators: 指标列表，可用指标:
            - ths_roe_stock: ROE
            - ths_np_stock: 归母净利润
            - ths_np_yoy_stock: 净利润同比增速(%)
            - ths_revenue_stock: 营业收入
            - ths_basic_eps_stock: 基本每股收益
            - ths_current_ratio_stock: 流动比率
            - ths_equity_multiplier_stock: 权益乘数
            - ths_np_ttm_stock: TTM净利润
        interval: D-日 W-周 M-月 Q-季 S-半年 Y-年（默认Q=季度）
        fill: Blank-空值 Previous-沿用前值（默认Blank）
        """
        codes_str = ",".join(codes) if isinstance(codes, list) else codes
        
        indipara = []
        for ind in (indicators if isinstance(indicators, list) else [indicators]):
            indipara.append({"indicator": ind, "indiparams": [""]})
        
        params = {
            "codes": codes_str,
            "startdate": start_date,
            "enddate": end_date,
            "functionpara": {"Interval": interval, "Fill": fill},
            "indipara": indipara
        }
        
        data = self._post("date_sequence", params)
        return data
    
    # ========== 专题报表(data_pool) ==========
    def data_pool(self, reportname, functionpara=None, outputpara=None):
        """
        获取专题报表数据（板块成分、龙虎榜等）
        reportname: 报表编码，常用:
            - p03291: 板块成分股 (functionpara: date, blockname)
            - p03341: REITs项目一览
        functionpara: dict, 报表参数（每个报表不同）
        outputpara: str, 输出字段如 "p03291_f001:Y,p03291_f002:Y"（必须指定，不能为空）
        
        返回: dict with 'tables', 'outParams', 'descrs'
        """
        if not outputpara:
            print("[iFinD] ⚠️ data_pool: outputpara为空，API将返回-4203错误。请指定输出字段。")
        params = {"reportname": reportname}
        if functionpara:
            params["functionpara"] = functionpara
        if outputpara:
            params["outputpara"] = outputpara
        
        data = self._post("data_pool", params)
        if data.get("errorcode") == -4203:
            print(f"[iFinD] ❌ data_pool(-4203): outputpara缺失或格式错误。reportname={reportname}")
        return data
    
    # ========== 财务趋势（便捷方法） ==========
    def financial_trend(self, code, years=3):
        """
        一键获取股票的财务趋势数据（ROE/净利润/营收/EPS，按季度）
        code: 单只股票代码
        years: 回溯年数（默认3年=12个季度）
        
        返回: dict with keys:
            - roe: list of (date, value) - ROE趋势
            - net_profit: list of (date, value) - 净利润趋势
            - np_yoy: list of (date, value) - 净利润增速趋势
            - revenue: list of (date, value) - 营收趋势
            - eps: list of (date, value) - EPS趋势
            - raw: 原始API返回数据
        """
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=years * 365)
        
        data = self.date_serial(
            code,
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            ["ths_roe_stock", "ths_np_stock", "ths_np_yoy_stock", "ths_revenue_stock", "ths_basic_eps_stock"],
            interval="Q"
        )
        
        result = {"raw": data, "roe": [], "net_profit": [], "np_yoy": [], "revenue": [], "eps": []}
        
        if data.get("errorcode") == 0 and data.get("tables"):
            table = data["tables"][0]
            time_list = table.get("time", [])
            tbl = table.get("table", {})
            
            mapping = {
                "roe": "ths_roe_stock",
                "net_profit": "ths_np_stock",
                "np_yoy": "ths_np_yoy_stock",
                "revenue": "ths_revenue_stock",
                "eps": "ths_basic_eps_stock"
            }
            
            for key, indicator in mapping.items():
                values = tbl.get(indicator, [])
                result[key] = [
                    {"date": t, "value": v}
                    for t, v in zip(time_list, values)
                    if v is not None
                ]
        
        return result

    # ========== 智能选股 ==========
    def smart_picking(self, search_string, search_type="stock"):
        """
        智能选股（按指标名称搜索）
        search_string: 搜索关键词，如 "涨跌幅"、"市盈率"、"ROE"
        search_type: "stock" 或 "fund"
        """
        params = {
            "searchstring": search_string,
            "searchtype": search_type
        }
        
        data = self._post("smart_stock_picking", params)
        return data
    
    # ========== 公告查询 ==========
    def announcements(self, codes, report_type="901", start_date=None, end_date=None):
        """
        查询公告
        codes: 股票代码
        report_type: 公告类型
            - 901: 全部公告
            - 902: 定期报告
            - 903: 临时报告
            - 904: 招股说明书
        """
        codes_str = ",".join(codes) if isinstance(codes, list) else codes
        
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        params = {
            "codes": codes_str,
            "functionpara": {"reportType": report_type},
            "beginrDate": start_date,
            "endrDate": end_date,
            "outputpara": "reportDate:Y,thscode:Y,secName:Y,ctime:Y,reportTitle:Y,pdfURL:Y,seq:Y"
        }
        
        data = self._post("report_query", params)
        
        if 'tables' in data:
            try:
                df = pd.json_normalize(data['tables'])
                return df
            except Exception:
                return data
        return data
    
    # ========== 经济数据库(EDB) ==========
    def edb(self, indicators, start_date, end_date):
        """
        获取宏观经济数据
        indicators: 指标代码，如 "G009035746"
        start_date/end_date: "2026-04-01" / "2026-05-01"
        """
        params = {
            "indicators": indicators,
            "startdate": start_date,
            "enddate": end_date
        }
        
        data = self._post("edb_service", params)
        return data
    
    # ========== 日内快照(tick) ==========
    def snapshot(self, code, start_time, end_time, indicators=None):
        """
        获取日内tick快照数据
        code: 单只股票代码
        """
        if indicators is None:
            indicators = "open,high,low,latest,bid1,ask1,bidSize1,askSize1"
        
        params = {
            "codes": code,
            "indicators": indicators,
            "starttime": start_time,
            "endtime": end_time
        }
        
        data = self._post("snap_shot", params, timeout=60)
        
        if 'tables' in data:
            try:
                df = pd.json_normalize(data['tables'])
                return df
            except Exception:
                return data
        return data
    
    # ========== 交易日查询 ==========
    def trade_dates(self, start_date, market="212001", offset="-10"):
        """
        查询交易日
        market: 212001=沪深, 212002=上交所, 212003=深交所
        offset: 偏移量，如 "-10" 表示往前10个交易日
        """
        params = {
            "marketcode": market,
            "functionpara": {
                "dateType": "0",
                "period": "D",
                "offset": str(offset),
                "dateFormat": "0",
                "output": "sequencedate"
            },
            "startdate": start_date
        }
        
        data = self._post("get_trade_dates", params)
        return data
    
    # ========== 批量股票快照（含基本面字段）==========
    def stock_snapshot_batch(self, codes, extra_indicators=None):
        """
        批量获取股票快照，含行情+基本面常用字段
        适合选股后快速查看候选股的综合信息
        """
        base_indicators = ["open", "high", "low", "latest", "changeRatio", "volume", "amount"]
        if extra_indicators:
            base_indicators.extend(extra_indicators)
        
        codes_str = ",".join(codes) if isinstance(codes, list) else codes
        params = {
            "codes": codes_str,
            "indicators": ",".join(base_indicators)
        }
        
        data = self._post("real_time_quotation", params)
        
        if 'tables' in data:
            try:
                df = pd.json_normalize(data['tables'])
                return df
            except Exception:
                return data
        return data


# 全局实例（自动从环境变量读取refresh_token）
iFinD = iFinDAPI()


if __name__ == "__main__":
    import sys
    print("=== iFinD HTTP API 全量测试 ===")
    
    # 1. 实时行情
    print("\n--- 1. 实时行情 ---")
    df = iFinD.realtime(["300033.SZ"], ["latest", "changeRatio", "volume"])
    print(df)
    
    # 2. 历史K线
    print("\n--- 2. 历史K线 ---")
    df = iFinD.history("300033.SZ", "2026-05-01", "2026-05-13")
    print(df)
    
    # 3. 日期序列（ROE趋势）
    print("\n--- 3. 日期序列: ROE趋势 ---")
    data = iFinD.date_serial("300446.SZ", "20230101", "20260513", ["ths_roe_stock"], interval="Q")
    if data.get("errorcode") == 0 and data.get("tables"):
        t = data["tables"][0]
        for d, v in zip(t["time"], t["table"]["ths_roe_stock"]):
            if v is not None:
                print(f"  {d}: ROE={v:.2f}%")
    
    # 4. 财务趋势（便捷方法）
    print("\n--- 4. 财务趋势(航天电子) ---")
    trend = iFinD.financial_trend("300446.SZ", years=2)
    print(f"  ROE数据点: {len(trend['roe'])}")
    print(f"  净利润数据点: {len(trend['net_profit'])}")
    for item in trend['roe'][-4:]:
        print(f"    {item['date']}: ROE={item['value']:.2f}%")
    
    # 5. 专题报表（板块成分）
    print("\n--- 5. 专题报表: 电子板块成分(前5只) ---")
    data = iFinD.data_pool("p03291",
        {"date": "20260513", "blockname": "001031"},
        "p03291_f001:Y,p03291_f002:Y")
    if data.get("errorcode") == 0 and data.get("tables"):
        tbl = data["tables"][0].get("table", {})
        codes = tbl.get("p03291_f002", [])[:5]
        total = len(tbl.get("p03291_f002", []))
        print(f"  板块成分股总数: {total}")
        for c in codes:
            print(f"  {c}")
    
    print("\n=== 测试完成 ===")
