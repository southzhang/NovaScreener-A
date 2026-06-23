#!/usr/bin/env python3
"""
V10 统一数据读取层 — 供Streamlit页面调用
封装所有缓存文件读取，容错设计（文件不存在/解析失败返回空/None）。
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

CACHE_DIR = os.path.expanduser("~/.hermes/cache")

# 项目根目录：优先通过 __file__ 推算，降级到硬编码路径
_hered = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.exists(os.path.join(_hered, "app.py")):
    PROJECT_DIR = _hered
else:
    # Streamlit 热加载可能改变 __file__，用 app.py 定位根目录
    _candidates = [
        os.path.abspath(os.path.join(os.getcwd())),
        "/Users/southzhang/projects/quant-watchdog",
        "/Users/southzhang/Projects/quant-watchdog",
    ]
    PROJECT_DIR = next((c for c in _candidates if os.path.exists(os.path.join(c, "app.py"))), _candidates[-1])

# 缓存文件路径
WATCHLIST_PATH = os.path.join(CACHE_DIR, "v10_watchlist.json")
PREFETCH_PATH = os.path.join(CACHE_DIR, "v10_tail_prefetch.json")
SUMMARY_PATH = os.path.join(CACHE_DIR, "v10_tail_summary.txt")
TRACKER_PATH = os.path.join(CACHE_DIR, "tail_rec_tracker.json")
TAIL_RESULTS_PATH = os.path.join(CACHE_DIR, "v10_tail_results.json")
RECOMMEND_PATH = os.path.join(CACHE_DIR, "v10_tail_recommend.json")

# V10脚本路径
PREFETCH_SCRIPT = os.path.join(PROJECT_DIR, "core", "v10", "v10_tail_prefetch.py")
SUMMARY_SCRIPT = os.path.join(PROJECT_DIR, "core", "v10", "v10_tail_summary.py")
SCAN_SCRIPT = os.path.join(PROJECT_DIR, "core", "v10", "v10_realtime_scan.py")


def _safe_read_json(filepath: str, default=None):
    """安全读取JSON文件，文件不存在或解析失败返回default"""
    try:
        if not os.path.exists(filepath):
            return default
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError, OSError):
        return default


def _safe_read_text(filepath: str, default="") -> str:
    """安全读取文本文件，文件不存在返回default"""
    try:
        if not os.path.exists(filepath):
            return default
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except (IOError, OSError):
        return default


# ===== 读取函数 =====

def get_watchlist() -> dict:
    """
    读取v10_watchlist.json，按信号等级分组返回。
    
    Returns:
        {
            "full_buy": [...],    # 全买入信号股
            "strong_buy": [...],  # 强庄买信号股
            "base_buy": [...],    # 基础买信号股
            "scan_time": str,     # 扫描时间
            "count": int,         # 总信号数
            "_raw": {...}         # 原始数据（可选）
        }
    """
    raw = _safe_read_json(WATCHLIST_PATH, default=None)
    if raw is None:
        return {"full_buy": [], "strong_buy": [], "base_buy": [], "scan_time": "", "count": 0, "from_today": False}

    stocks = raw.get("stocks", [])
    
    # 检查数据时效性：scan_time必须是今天
    scan_time = raw.get("scan_time", "")
    today_str = datetime.now().strftime("%Y-%m-%d")
    from_today = scan_time.startswith(today_str)
    
    result = {
        "full_buy": [s for s in stocks if s.get("signal") == "全买入"],
        "strong_buy": [s for s in stocks if s.get("signal") == "强庄买"],
        "base_buy": [s for s in stocks if s.get("signal") == "基础买"],
        "scan_time": scan_time,
        "count": raw.get("count", len(stocks)),
        "from_today": from_today,
    }
    return result


def get_prefetch() -> dict:
    """
    读取v10_tail_prefetch.json，返回候选股详情 + 板块 + 指数。
    
    Returns:
        {
            "candidates": {code: {...}},  # 候选股详情
            "sectors": {...},             # 板块数据
            "index": {...},               # 四大指数
            "signals": {...},             # 信号分组
            "market_breadth": {...},       # 市场宽度（涨跌家数）
            "prefetch_time": str,         # 预取时间
            "_fetch_failed": bool,        # 降级标记
        }
    """
    raw = _safe_read_json(PREFETCH_PATH, default=None)
    if raw is None:
        return {
            "candidates": {},
            "sectors": {"trending_sectors": [], "concepts": []},
            "index": {},
            "signals": {"full_buy": [], "strong_buy": [], "base_buy": []},
            "prefetch_time": "",
            "_fetch_failed": False,
        }
    return raw


def get_summary() -> str:
    """
    读取v10_tail_summary.txt，返回推荐摘要文本。
    
    Returns:
        str: 摘要文本，文件不存在返回空字符串
    """
    return _safe_read_text(SUMMARY_PATH, default="")


def get_recommend() -> dict:
    """
    读取v10_tail_recommend.json，返回结构化推荐数据。
    
    Returns:
        {
            "update_time": str,
            "scan_time": str,
            "recommend": [{code, name, signal, action, entry_price, stop_loss, ...}],
            "observe": [...],
            "excluded": [...],
            "summary": {...},
        }
    """
    raw = _safe_read_json(RECOMMEND_PATH, default=None)
    if raw is None:
        return {
            "update_time": "",
            "scan_time": "",
            "recommend": [],
            "observe": [],
            "excluded": [],
            "summary": {"recommend_count": 0, "observe_count": 0, "excluded_count": 0, "in_cooldown": False},
        }
    return raw


def get_tracker() -> list:
    """
    读取tail_rec_tracker.json，转换为页面友好的格式。
    
    原始格式:
        {"recommendations": [{date, stocks: [...], validated, next_day: {key: {...}}, three_day: {key: {...}}}], ...}
    
    Returns:
        list: [{date, recommendations: [{code, name, signal, price, status, 
               next_day_open, next_day_close, next_day_pct, day3_close, day3_pct, stop_loss}]}]
    """
    raw = _safe_read_json(TRACKER_PATH, default=None)
    if raw is None:
        return []
    
    # 兼容已经是转换后格式的list
    if isinstance(raw, list):
        return raw
    
    recs = raw.get("recommendations", [])
    result = []
    for rec in recs:
        date_str = rec.get("date", "")
        stocks = rec.get("stocks", [])
        validated = rec.get("validated", False)
        next_day = rec.get("next_day", {})
        three_day = rec.get("three_day", {})
        
        items = []
        for s in stocks:
            code = s.get("code", "")
            buy_price = s.get("price", 0) or 0
            key = f"{date_str}_{code}"
            
            nd = next_day.get(key, {})
            td = three_day.get(key, {})
            
            items.append({
                "code": code,
                "name": s.get("name", ""),
                "signal": s.get("signal", ""),
                "price": buy_price,
                "status": "validated" if (validated or nd) else "pending",
                "next_day_open": nd.get("high") if nd else None,
                "next_day_close": nd.get("close") if nd else None,
                "next_day_pct": nd.get("pnl_pct") if nd else None,
                "day3_close": td.get("close") if td else None,
                "day3_pct": td.get("pnl_pct") if td else None,
                "stop_loss": s.get("stop_loss") or (round(buy_price * 0.95, 2) if buy_price else None),
            })
        
        result.append({
            "date": date_str,
            "recommendations": items,
        })
    
    return result


def add_recommendations(stocks: list, date_str: str = None) -> dict:
    """
    手动向追踪器添加推荐记录。
    
    Args:
        stocks: [{"code", "name", "price", "signal", "score", "stop_loss"}, ...]
        date_str: 日期字符串，默认今天
    
    Returns:
        {"success": bool, "added": int, "skipped": int, "message": str}
    """
    if not stocks:
        return {"success": False, "added": 0, "skipped": 0, "message": "无推荐数据"}
    
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 读取现有 tracker
    tracker = _safe_read_json(TRACKER_PATH, default=None)
    if tracker is None:
        tracker = {"recommendations": [], "cooldown_until": None, "stats": {}}
    
    recs = tracker.get("recommendations", [])
    
    # 同日去重
    existing_codes = set()
    for rec in recs:
        if rec.get("date") == date_str:
            for s in rec.get("stocks", []):
                existing_codes.add(s.get("code"))
    
    new_codes = [s["code"] for s in stocks if s.get("code") not in existing_codes]
    skipped = len(stocks) - len(new_codes)
    
    if not new_codes:
        return {"success": True, "added": 0, "skipped": skipped, "message": f"{date_str} 已有推荐记录，跳过重复"}
    
    # 追加
    recs.append({
        "date": date_str,
        "stocks": stocks,
        "validated": False,
        "next_day": {},
        "three_day": {},
        "source": "manual",
    })
    tracker["recommendations"] = recs[-30:]  # 只保留最近30条
    
    # 写入
    os.makedirs(os.path.dirname(TRACKER_PATH), exist_ok=True)
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)
    
    return {"success": True, "added": len(new_codes), "skipped": skipped, "message": f"已添加{len(new_codes)}只推荐到{date_str}"}


def get_index_data() -> list:
    """
    调用core.data.get_market_indices()获取大盘指数。
    
    Returns:
        list[dict]: 指数行情列表，失败返回空列表
    """
    try:
        from core.data import get_market_indices
        return get_market_indices()
    except Exception as e:
        print(f"[data_service] 获取大盘指数失败: {e}", file=sys.stderr)
        return []


# ===== 时效性检查 =====

def check_freshness(filepath: str, max_minutes: int = 10) -> dict:
    """
    检查文件时效性。
    
    Args:
        filepath: 文件路径
        max_minutes: 最大允许的文件年龄（分钟）
    
    Returns:
        {
            "exists": bool,           # 文件是否存在
            "fresh": bool,            # 是否新鲜
            "age_minutes": float|None,# 文件年龄（分钟）
            "mtime": str|None,        # 修改时间
        }
    """
    result = {"exists": False, "fresh": False, "age_minutes": None, "mtime": None}
    try:
        p = Path(filepath)
        if not p.exists():
            return result
        result["exists"] = True
        mtime_ts = p.stat().st_mtime
        mtime_dt = datetime.fromtimestamp(mtime_ts)
        result["mtime"] = mtime_dt.strftime("%Y-%m-%d %H:%M:%S")
        age = (datetime.now() - mtime_dt).total_seconds() / 60
        result["age_minutes"] = round(age, 1)
        result["fresh"] = age <= max_minutes
    except OSError:
        pass
    return result


# ===== 手动触发函数 =====


def get_tail_recommendations() -> dict:
    """
    读取V10扫描结果，应用尾盘专属策略评分。
    返回: {stocks: [TailEndSignal dicts], stats: {}}
    仅14:20-15:00有实际意义，其他时段数据不足。
    """
    result = {"stocks": [], "stats": {}, "error": ""}
    
    # 1. 读取V10 watchlist（扫描结果）
    watchlist = get_watchlist()
    scan_time = watchlist.get("scan_time", "")
    from_today = watchlist.get("from_today", False)
    
    # 时效性检查：非今天的信号不用于尾盘判断
    if not from_today and scan_time:
        result["error"] = f"V10信号数据来自 {scan_time}（非今日），请先点击下方「尾盘选股扫描」按钮获取今日信号"
        return result
    if not scan_time:
        result["error"] = "暂无V10信号数据，请先点击下方「尾盘选股扫描」按钮"
        return result
    
    all_candidates = []
    
    # 从所有信号组中收集候选股
    for key in ["full_buy", "strong_buy", "base_buy"]:
        for s in watchlist.get(key, []):
            if isinstance(s, dict):
                all_candidates.append(s)
            elif isinstance(s, str):
                all_candidates.append({"code": s, "name": s, "signal": key})
    
    if not all_candidates:
        # 也尝试从prefetch中获取（仅当天数据）
        prefetch = get_prefetch()
        _pf_scan_time = prefetch.get("scan_time", "") or prefetch.get("update_time", "")
        _pf_fresh = _pf_scan_time.startswith(today_str) if _pf_scan_time else False
        if not _pf_fresh:
            result["error"] = "今日无V10信号且预取数据也过期，请点击下方「尾盘选股扫描」按钮"
            return result
        for code, c in prefetch.get("candidates", {}).items():
            sig = c.get("signal", "")
            if sig:
                all_candidates.append({
                    "code": code,
                    "name": c.get("name", code),
                    "signal": sig,
                    "signal_type": sig,
                    "score": c.get("score", 60),
                })
    
    if not all_candidates:
        result["error"] = "无V10信号候选股，请先运行尾盘扫描"
        return result
    
    # 2. 对每个候选股获取实时行情 + 执行尾盘评分
    from core.tail_strategy import score_tail_end_candidate
    from core.data import get_realtime_quote, get_realtime_quotes_batch
    
    codes = [s.get("code", "") for s in all_candidates if s.get("code")]
    quotes = get_realtime_quotes_batch(codes)
    quote_map = {q["code"]: q for q in quotes}
    
    tail_results = []
    for s in all_candidates:
        code = s.get("code", "")
        q = quote_map.get(code, {})
        if not q or not q.get("price", 0):
            continue
        
        price = q.get("price", 0)
        pct = q.get("pct_change", 0)
        vol = q.get("volume", 0)  # 手
        amount = q.get("amount", 0)  # 万元
        
        # 尾盘专属评分
        ts = score_tail_end_candidate(
            code=code,
            name=s.get("name", code),
            signal_type=s.get("signal_type", s.get("signal", "")),
            v10_score=s.get("score", 60),
            current_price=price,
            pct_change=pct,
            day_open=q.get("open", 0),
            day_high=q.get("high", 0),
            day_low=q.get("low", 0),
            day_volume=vol,
            day_amount=amount,
            # 尾盘时段无法直接获取分钟数据，用以下近似
            last_30min_volume=vol * 0.25,  # 估计尾盘30分钟占全天25%
            last_15min_volume=vol * 0.12,  # 估计尾盘15分钟占全天12%
            price_30min_ago=price * (1 - pct / 100 * 0.3),  # 按涨跌幅估算30分钟前价格
            price_15min_ago=price * (1 - pct / 100 * 0.1),
            price_5min_ago=price * (1 - pct / 100 * 0.02),
            ema20=q.get("pre_close", price * 0.98),  # 近似EMA20=昨收附近
            limit_up=q.get("limit_up", 0),
            limit_down=q.get("limit_down", 0),
        )
        
        if ts:
            tail_results.append(ts)
    
    # 3. 排序：可进场优先，再按总分降序
    action_order = {"可进场": 0, "观察": 1, "放弃": 2}
    tail_results.sort(key=lambda x: (
        action_order.get(x.tail_action, 3),
        -x.total_tail_score
    ))
    
    # 4. 保存结果
    try:
        os.makedirs(os.path.dirname(TAIL_RESULTS_PATH), exist_ok=True)
        _now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_data = []
        for ts in tail_results:
            save_data.append({
                "code": ts.code, "name": ts.name,
                "signal_type": ts.signal_type,
                "v10_score": ts.v10_score,
                "tail_score": ts.total_tail_score,
                "tail_action": ts.tail_action,
                "tail_reason": ts.tail_reason,
                "details": ts.tail_detail or {},
            })
        with open(TAIL_RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "update_time": _now,
                "count": len(tail_results),
                "stocks": save_data,
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    
    # 5. 统计
    buy_count = sum(1 for t in tail_results if t.tail_action == "可进场")
    watch_count = sum(1 for t in tail_results if t.tail_action == "观察")
    
    result["stocks"] = tail_results
    result["stats"] = {
        "total": len(tail_results),
        "buy": buy_count,
        "watch": watch_count,
        "v10_candidates": len(all_candidates),
    }
    
    return result


def _run_script(script_path: str, description: str, extra_args: list | None = None, timeout: int = 120) -> dict:
    """
    通用脚本执行器，subprocess调用Python脚本。
    
    Returns:
        {"success": bool, "returncode": int, "description": str}
    """
    if not os.path.exists(script_path):
        return {"success": False, "returncode": -1, "description": f"{description}脚本不存在: {script_path}"}
    try:
        cmd = [sys.executable, script_path]
        if extra_args:
            cmd.extend(extra_args)
        env = os.environ.copy()
        env["PYTHONPATH"] = PROJECT_DIR
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_DIR,
            env=env,
        )
        ok = result.returncode == 0
        desc = f"{description}{'成功' if ok else '失败'}"
        if not ok and result.stderr:
            desc += f": {result.stderr[-200:]}"
        return {
            "success": ok,
            "returncode": result.returncode,
            "description": desc,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "returncode": -1, "description": f"{description}超时(120s)"}
    except Exception as e:
        return {"success": False, "returncode": -1, "description": f"{description}异常: {e}"}


def run_prefetch() -> dict:
    """手动触发v10_tail_prefetch.py预取（--force跳过交易时间检查）"""
    return _run_script(PREFETCH_SCRIPT, "尾盘预取", extra_args=["--force"])


def run_summary() -> dict:
    """手动触发v10_tail_summary.py生成摘要"""
    return _run_script(SUMMARY_SCRIPT, "尾盘摘要")


def run_scan() -> dict:
    """手动触发v10_realtime_scan.py全市场扫描（--force跳过交易时间检查）"""
    return _run_script(SCAN_SCRIPT, "V10扫描", extra_args=["--force"], timeout=300)


# ===== 便捷组合函数 =====

def get_dashboard_data() -> dict:
    """
    一次性获取Dashboard所需的全部数据。
    
    Returns:
        {
            "watchlist": {...},
            "prefetch": {...},
            "summary": str,
            "recommend": dict,
            "tracker": list,
            "indices": list,
            "freshness": {...},  # 各文件时效性
        }
    """
    watchlist = get_watchlist()
    prefetch = get_prefetch()
    summary = get_summary()
    recommend = get_recommend()
    tracker = get_tracker()
    indices = get_index_data()

    # 检查核心文件时效性
    freshness = {
        "watchlist": check_freshness(WATCHLIST_PATH, max_minutes=30),
        "prefetch": check_freshness(PREFETCH_PATH, max_minutes=10),
        "summary": check_freshness(SUMMARY_PATH, max_minutes=10),
        "tracker": check_freshness(TRACKER_PATH, max_minutes=60),
    }

    return {
        "watchlist": watchlist,
        "prefetch": prefetch,
        "summary": summary,
        "recommend": recommend,
        "tracker": tracker,
        "indices": indices,
        "freshness": freshness,
    }
