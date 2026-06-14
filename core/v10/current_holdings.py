#!/usr/bin/env python3
"""当前实盘持仓 — 标记为"实盘"账户，供各脚本统一读取"""
import json

ACCOUNT_NAME = "实盘"
PORTFOLIO_VALUE = 56000.0

HOLDINGS = [
    {"code": "603399", "name": "永杉锂业", "shares": 500, "cost": 20.17, "date": "2026-06-12", "signal": "★★☆强庄买", "vibe": "+4"},
]


def get_holdings():
    return list(HOLDINGS)


def get_portfolio_value():
    return PORTFOLIO_VALUE


def get_cash():
    """计算剩余可用资金"""
    total_cost = sum(h["shares"] * h["cost"] for h in HOLDINGS)
    return PORTFOLIO_VALUE - total_cost


def get_account_info():
    return {
        "account": ACCOUNT_NAME,
        "holdings": HOLDINGS,
        "portfolio_value": PORTFOLIO_VALUE,
        "cash": get_cash(),
    }


if __name__ == '__main__':
    print(json.dumps(get_account_info(), ensure_ascii=False, indent=2))
