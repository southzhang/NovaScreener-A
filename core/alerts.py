"""飞书预警通知模块 - 通过 Webhook 发送卡片消息"""
import os
import json
import requests
from datetime import datetime
from .db import save_alert


def _get_webhook_url() -> str:
    """获取飞书 Webhook URL"""
    return os.getenv("FEISHU_WEBHOOK_URL", "")


def send_feishu_card(title: str, elements: list[dict]) -> bool:
    """发送飞书卡片消息
    
    Args:
        title: 卡片标题
        elements: 卡片元素列表
    
    Returns:
        是否发送成功
    """
    webhook_url = _get_webhook_url()
    if not webhook_url:
        print("[预警] 飞书 Webhook URL 未配置，跳过发送")
        return False

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": elements,
        },
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            return True
        else:
            print(f"[预警] 飞书发送失败: {result}")
            return False
    except Exception as e:
        print(f"[预警] 飞书发送异常: {e}")
        return False


def send_signal_alert(code: str, name: str, strategy: str, price: float, detail: str) -> bool:
    """发送选股信号预警"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**股票**: {name}（{code}）\n"
                    f"**策略**: {strategy}\n"
                    f"**价格**: ¥{price:.2f}\n"
                    f"**详情**: {detail}\n"
                    f"**时间**: {now}"
                ),
            },
        },
        {"tag": "hr"},
        {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": "📊 量化盯盘选股 - 策略信号"}],
        },
    ]
    success = send_feishu_card(f"🎯 选股信号: {name}", elements)
    if success:
        save_alert(code, "signal", f"{strategy}: {detail}")
    return success


def send_watchlist_alert(code: str, name: str, alert_type: str, price: float, pct_change: float) -> bool:
    """发送自选股异动预警"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if alert_type == "limit_up":
        emoji = "🔴"
        title = f"涨停！{name}"
        color = "red"
    elif alert_type == "limit_down":
        emoji = "🟢"
        title = f"跌停！{name}"
        color = "green"
    elif pct_change > 5:
        emoji = "📈"
        title = f"大涨: {name}"
        color = "red"
    elif pct_change < -5:
        emoji = "📉"
        title = f"大跌: {name}"
        color = "green"
    else:
        emoji = "⚠️"
        title = f"异动: {name}"
        color = "orange"

    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**股票**: {name}（{code}）\n"
                    f"**价格**: ¥{price:.2f}\n"
                    f"**涨跌幅**: {pct_change:+.2f}%\n"
                    f"**时间**: {now}"
                ),
            },
        },
        {"tag": "hr"},
        {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"{emoji} 量化盯盘选股 - 自选股异动"}],
        },
    ]
    success = send_feishu_card(title, elements)
    if success:
        save_alert(code, alert_type, f"价格{price:.2f} 涨跌幅{pct_change:+.2f}%")
    return success


def send_position_alert(
    code: str, name: str, action: str, reason: str,
    price: float, buy_price: float, pnl_pct: float,
    risk_score: int, dynamic_stop: float, dynamic_target: float,
) -> bool:
    """发送持仓操作建议预警"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 根据操作类型选颜色和emoji
    if "清仓" in action:
        header_color = "red"
        emoji = "🔴"
    elif "减仓" in action:
        header_color = "orange"
        emoji = "🟡"
    elif "加仓" in action:
        header_color = "blue"
        emoji = "🔵"
    elif "离场" in action or "止盈" in action:
        header_color = "green"
        emoji = "💰"
    else:
        header_color = "blue"
        emoji = "🟢"

    pnl_color = "#ef4444" if pnl_pct >= 0 else "#22c55e"
    pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"

    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**股票**: {name}（{code}）\n"
                    f"**现价**: ¥{price:.2f}（成本 ¥{buy_price:.2f}）\n"
                    f"**盈亏**: <font color='{pnl_color}'>{pnl_str}</font>\n"
                    f"**建议**: {emoji} {action}\n"
                    f"**理由**: {reason}\n"
                    f"**风险评分**: {risk_score}/100\n"
                    f"**止损**: ¥{dynamic_stop:.2f} | **目标**: ¥{dynamic_target:.2f}\n"
                    f"**时间**: {now}"
                ),
            },
        },
        {"tag": "hr"},
        {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"{emoji} 量化盯盘 - 持仓预警"}],
        },
    ]
    success = send_feishu_card(f"{emoji} 持仓预警: {name} {action}", elements)
    if success:
        save_alert(code, "position", f"{action}: {reason}")
    return success


def send_batch_signals(signals: list[dict]) -> bool:
    """批量发送信号汇总"""
    if not signals:
        return True

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    for s in signals[:20]:  # 最多显示20条
        lines.append(f"• **{s['name']}**（{s['code']}）— {s['strategy']} — ¥{s['price']:.2f}")

    content = "\n".join(lines)
    if len(signals) > 20:
        content += f"\n\n...共 {len(signals)} 条信号"

    elements = [
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": content},
        },
        {"tag": "hr"},
        {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"📊 共 {len(signals)} 条信号 | {now}"}],
        },
    ]
    return send_feishu_card(f"📊 策略扫描结果: {len(signals)} 条信号", elements)
