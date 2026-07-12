#!/usr/bin/env python3
"""当前实盘持仓 — 标记为"实盘"账户，供各脚本统一读取
v2: 增加卖出→回归观察池功能（止损出局的票不放弃，V10信号归来时可再进）"""
import json
import os
from datetime import datetime, timedelta

ACCOUNT_NAME = "实盘"
PORTFOLIO_VALUE = 70742.40 + 6059.20 + 19067  # 06-29上午更新: 清仓3只(通富+912/润泽-813/紫光-479, 净-380) + 新开2只(太极27.184/华灿18.817) + 深科技加仓100股, 现金5576.17→19067

# 新策略 v2 (06-23): 分层止损+补仓+延长锁仓
# 止损三层: soft_stop(-8%观察) / hard_stop(-12%决策) / abs_stop(-15%强制建议卖)
# 止盈: 长线15%+启动trailing 8% / 短线10%+启动trailing 5%
# 补仓: 长线票-8%第一笔/-12%第二笔, 短线票不补仓
# 盯盘降频: 每天2次(11:30+14:55), 浮亏8%以内静默

HOLDINGS = [
    {
        "code": "600584", "name": "长电科技", "shares": 200, "cost": 92.354, "date": "2026-06-22",
        "category": "长线", "vibe": "长线(目标100才卖)",
        "soft_stop": 84.97, "hard_stop": 81.27, "abs_stop": 78.50,  # -8%/-12%/-15% 基于92.354
        "stop": 81.27,  # backward compat = hard_stop
        "tp_trigger": 15, "tp_trailing": 8,
        "dca": [{"trigger_pct": -8, "price": 84.97, "shares": 100}, {"trigger_pct": -12, "price": 81.27, "shares": 100}],
        "note": "06-29上午T降本1.298元(93.652→92.354), 形态高开105.8砸到92.4未在最高位T出",
    },
    {
        "code": "600667", "name": "太极实业", "shares": 500, "cost": 27.184, "date": "2026-06-29",
        "category": "短线", "vibe": "中短线(半导体封测/算力服务器)",
        "soft_stop": 25.01, "hard_stop": 23.92, "abs_stop": 23.11,  # -8%/-12%/-15% 基于27.184
        "stop": 23.92,
        "tp_trigger": 10, "tp_trailing": 5,
        "dca": [],
        "note": "06-29上午新开仓500股, 半导体封测题材(同日深科技+7%)",
    },
    {
        "code": "000021", "name": "深科技", "shares": 200, "cost": 56.825, "date": "2026-06-25",
        "category": "短线", "vibe": "短线(半导体封测)",
        "soft_stop": 52.28, "hard_stop": 50.01, "abs_stop": 48.30,  # -8%/-12%/-15% 基于56.825
        "stop": 50.01,
        "tp_trigger": 10, "tp_trailing": 5,
        "dca": [],
        "note": "06-29上午加仓100股, 成本54→56.825(追高+5.2%), 今日+7.03%放量",
    },
    {
        "code": "300975", "name": "商络电子", "shares": 200, "cost": 46.000, "date": "2026-06-25",
        "category": "短线", "vibe": "短线(违规回归)",
        "lock_until": "2026-06-28",
        "soft_stop": 42.32, "hard_stop": 40.48, "abs_stop": 39.10,  # -8%/-12%/-15% 基于46.000
        "stop": 40.48,
        "tp_trigger": 10, "tp_trailing": 5,
        "dca": [],
        "note": "06-29上午T降本0.46元(46.462→46.000), 现价41.09已破hard_stop必须止损",
    },
    {
        "code": "002056", "name": "横店东磁", "shares": 300, "cost": 24.465, "date": "2026-06-18",
        "category": "短线", "vibe": "短线",
        "lock_until": "2026-06-27",
        "soft_stop": 22.51, "hard_stop": 21.53, "abs_stop": 20.80,  # -8%/-12%/-15% 基于24.465
        "stop": 21.53,
        "tp_trigger": 10, "tp_trailing": 5,
        "dca": [],
        "note": "06-29上午减仓200股(500→300), 成本26.636→24.465(降本-8.1%), 浮盈+16.2%安全垫厚",
    },
    {
        "code": "300323", "name": "华灿光电", "shares": 300, "cost": 18.817, "date": "2026-06-29",
        "category": "短线", "vibe": "短线(LED/半导体)",
        "soft_stop": 17.31, "hard_stop": 16.56, "abs_stop": 16.00,  # -8%/-12%/-15% 基于18.817
        "stop": 16.56,
        "tp_trigger": 10, "tp_trailing": 5,
        "dca": [],
        "note": "06-29上午新开仓300股, 半导体/LED题材",
    },
    {
        "code": "600531", "name": "豫光金铅", "shares": 300, "cost": 17.100, "date": "2026-06-25",
        "category": "短线", "vibe": "短线(黄金/白银有色)",
        "lock_until": "2026-06-28",
        "soft_stop": 15.73, "hard_stop": 15.05, "abs_stop": 14.54,  # -8%/-12%/-15% 基于17.100
        "stop": 15.05,
        "tp_trigger": 10, "tp_trailing": 5,
        "dca": [],
        "note": "06-29上午无操作, 成本基本没变, 浮亏-8.5%已破soft_stop",
    },
]

# ETF持仓（不参与个股止损/止盈/补仓逻辑，单独记录）
ETF_HOLDINGS = [
    {"code": "512480", "name": "半导体ETF国联安", "shares": 400, "cost": 2.578, "date": "2026-06-24", "category": "ETF"},
    {"code": "588000", "name": "科创50ETF华夏", "shares": 2400, "cost": 2.095, "date": "2026-06-24", "category": "ETF"},
]

# 回归观察池路径
RETURN_WATCHLIST = os.path.expanduser("~/.hermes/cache/watchlist_return.json")
# 回归冷静期（交易日天数）
RETURN_COOLDOWN_DAYS = 3
# 回归观察期（自然日天数，过期自动移出）
RETURN_OBSERVE_DAYS = 60


def get_holdings():
    return list(HOLDINGS)


def get_stop_tiers(holding):
    """获取分层止损: soft(-8%观察)/hard(-12%决策)/abs(-15%强制)"""
    return {
        'soft_stop': holding.get('soft_stop', holding.get('stop', 0)),
        'hard_stop': holding.get('hard_stop', holding.get('stop', 0)),
        'abs_stop': holding.get('abs_stop', holding.get('stop', 0)),
    }


def get_dca_plan(holding):
    """获取补仓计划（长线票才有，短线票返回空列表）"""
    return holding.get('dca', [])


def get_category(holding):
    """获取持仓类别: 长线/短线"""
    return holding.get('category', '短线')


def get_tp_config(holding):
    """获取止盈配置: (触发涨幅%, 回撤止盈%)"""
    return holding.get('tp_trigger', 15), holding.get('tp_trailing', 8)


def get_portfolio_value():
    return PORTFOLIO_VALUE


def get_cash():
    """计算剩余可用资金（含ETF持仓成本）"""
    total_cost = sum(h["shares"] * h["cost"] for h in HOLDINGS)
    etf_cost = sum(e["shares"] * e["cost"] for e in ETF_HOLDINGS)
    return PORTFOLIO_VALUE - total_cost - etf_cost


def get_portfolio_value_auto():
    """自动校验PORTFOLIO_VALUE是否合理（检测硬编码值是否过期）
    用法: python current_holdings.py check_value
    如果个股成本+ETF成本+cash < 0 或 远低于实际，说明PORTFOLIO_VALUE需要更新
    """
    total_cost = sum(h["shares"] * h["cost"] for h in HOLDINGS)
    etf_cost = sum(e["shares"] * e["cost"] for e in ETF_HOLDINGS)
    cash = get_cash()
    print(f"个股成本: ¥{total_cost:,.2f}")
    print(f"ETF成本:   ¥{etf_cost:,.2f}")
    print(f"现金(计算): ¥{cash:,.2f}")
    print(f"总资产:   ¥{PORTFOLIO_VALUE:,.2f}")
    if cash < 0:
        print(f"⚠️ 现金为负！PORTFOLIO_VALUE(¥{PORTFOLIO_VALUE:,.2f})可能需要更新")
        print(f"   建议更新: PORTFOLIO_VALUE = 实际个股成本 + ETF成本 + 实际现金")
    elif cash < PORTFOLIO_VALUE * 0.01:
        print(f"⚠️ 现金不足总资产1%，PORTFOLIO_VALUE可能需要更新")
    else:
        print(f"✅ 现金占比{cash/PORTFOLIO_VALUE*100:.1f}%，合理")


def get_account_info():
    return {
        "account": ACCOUNT_NAME,
        "holdings": HOLDINGS,
        "etf_holdings": ETF_HOLDINGS,
        "portfolio_value": PORTFOLIO_VALUE,
        "cash": get_cash(),
    }


def sell_to_return_pool(code, sell_price, sell_date=None):
    """卖出持仓并将股票加入回归观察池
    
    回归规则：
    - 止损线=割肉价（最差平出，不亏两次）
    - 冷静期3个交易日后才可回归
    - 观察期60个自然日，过期自动移出
    - V10重新触发★★☆+放量突破前高+七关全通过→可回归买入
    """
    if sell_date is None:
        sell_date = datetime.now().strftime("%Y-%m-%d")
    
    # 找到持仓
    holding = None
    for h in HOLDINGS:
        if h["code"] == code:
            holding = h.copy()
            break
    
    if not holding:
        return {"error": f"未找到持仓 {code}"}
    
    # 计算盈亏
    pnl = (sell_price - holding["cost"]) * holding["shares"]
    pnl_pct = (sell_price / holding["cost"] - 1) * 100
    
    # 从持仓移除
    HOLDINGS[:] = [h for h in HOLDINGS if h["code"] != code]
    
    # 加入回归观察池
    return_entry = {
        "code": code,
        "name": holding["name"],
        "sell_price": sell_price,           # 割肉价=回归止损线
        "sell_date": sell_date,             # 卖出日期
        "sell_pnl_pct": round(pnl_pct, 2), # 卖出时盈亏%
        "prev_cost": holding["cost"],       # 原始成本（参考用）
        "prev_shares": holding["shares"],   # 原始股数（参考用）
        "return_stop": sell_price,          # 回归止损线=割肉价
        "cooldown_until": _add_trading_days(sell_date, RETURN_COOLDOWN_DAYS),
        "expire_date": _add_calendar_days(sell_date, RETURN_OBSERVE_DAYS),
        "signal": holding.get("signal", ""),  # 原始V10信号
        "vibe": holding.get("vibe", ""),      # 原始Vibe
        "status": "cooling",  # cooling=冷静期, watching=观察中, expired=过期
    }
    
    # 读取现有观察池
    pool = _load_return_pool()
    
    # 如果已存在，更新
    existing = [s for s in pool["stocks"] if s["code"] == code]
    if existing:
        pool["stocks"] = [s for s in pool["stocks"] if s["code"] != code]
    
    pool["stocks"].append(return_entry)
    pool["updated"] = datetime.now().strftime("%Y-%m-%d")
    
    _save_return_pool(pool)
    
    return {
        "action": "sold_to_return_pool",
        "code": code,
        "name": holding["name"],
        "sell_price": sell_price,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "return_stop": sell_price,
        "cooldown_until": return_entry["cooldown_until"],
        "expire_date": return_entry["expire_date"],
        "pool_count": len(pool["stocks"]),
    }


def get_return_pool():
    """获取当前有效的回归观察池（冷静期+未过期）"""
    pool = _load_return_pool()
    today = datetime.now().strftime("%Y-%m-%d")
    
    active = []
    for s in pool["stocks"]:
        # 检查过期
        if s.get("expire_date", "") < today:
            s["status"] = "expired"
            continue
        
        # 检查冷静期
        if s.get("cooldown_until", "") > today:
            s["status"] = "cooling"
        else:
            s["status"] = "watching"
        
        active.append(s)
    
    # 更新池（移除过期的）
    pool["stocks"] = [s for s in pool["stocks"] if s.get("expire_date", "") >= today]
    _save_return_pool(pool)
    
    return active


def remove_from_return_pool(code):
    """从回归观察池移除（已回归买入或手动移除）"""
    pool = _load_return_pool()
    before = len(pool["stocks"])
    pool["stocks"] = [s for s in pool["stocks"] if s["code"] != code]
    pool["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_return_pool(pool)
    return {"removed": code, "before": before, "after": len(pool["stocks"])}


def _load_return_pool():
    """读取回归观察池"""
    if not os.path.exists(RETURN_WATCHLIST):
        return {"description": "回归观察池", "updated": "", "stocks": []}
    try:
        with open(RETURN_WATCHLIST, "r") as f:
            return json.load(f)
    except:
        return {"description": "回归观察池", "updated": "", "stocks": []}


def _save_return_pool(pool):
    """保存回归观察池"""
    os.makedirs(os.path.dirname(RETURN_WATCHLIST), exist_ok=True)
    with open(RETURN_WATCHLIST, "w") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


def _add_trading_days(start_date_str, days):
    """加N个交易日（简化：跳过周末，不考虑节假日）"""
    dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    added = 0
    while added < days:
        dt += timedelta(days=1)
        if dt.weekday() < 5:  # 周一到周五
            added += 1
    return dt.strftime("%Y-%m-%d")


def _add_calendar_days(start_date_str, days):
    """加N个自然日"""
    dt = datetime.strptime(start_date_str, "%Y-%m-%d") + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "pool":
            # 查看回归观察池
            active = get_return_pool()
            if active:
                print(f"📋 回归观察池 ({len(active)}只):")
                for s in active:
                    status_icon = "🧊" if s["status"] == "cooling" else "👁️"
                    print(f"  {status_icon} {s['name']}({s['code']}) | 割肉¥{s['sell_price']:.2f}({s['sell_pnl_pct']:+.1f}%) | "
                          f"回归止损¥{s['return_stop']:.2f} | 冷静至{s['cooldown_until']} | 过期{s['expire_date']}")
            else:
                print("📋 回归观察池: 空")
        elif cmd == "sell" and len(sys.argv) >= 4:
            # 卖出并加入回归池: python current_holdings.py sell 603399 19.50
            code = sys.argv[2]
            sell_price = float(sys.argv[3])
            sell_date = sys.argv[4] if len(sys.argv) > 4 else None
            result = sell_to_return_pool(code, sell_price, sell_date)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif cmd == "remove" and len(sys.argv) >= 3:
            # 从回归池移除: python current_holdings.py remove 603399
            code = sys.argv[2]
            result = remove_from_return_pool(code)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif cmd == "check_value":
            get_portfolio_value_auto()
        else:
            print("用法: current_holdings.py [pool|sell CODE PRICE [DATE]|remove CODE|check_value]")
    else:
        print(json.dumps(get_account_info(), ensure_ascii=False, indent=2))
