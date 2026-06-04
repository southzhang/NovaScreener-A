"""盘中盯盘监控 — 实时行情 + 异动检测 + 飞书通知"""
import time
import threading
from datetime import datetime
from typing import Callable, Optional
from .data import get_realtime_quote, get_stock_history
from .strategies import scan_v10_full, scan_pullback
from .alerts import send_watchlist_alert, send_signal_alert
from .db import get_watchlist, save_alert
import numpy as np


class IntradayMonitor:
    """盘中盯盘监控器"""
    
    def __init__(self, callback: Optional[Callable] = None):
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.callback = callback
        self.alerts_sent = set()  # 避免重复提醒
        self.last_prices = {}  # 上次价格记录
        
    def start(self, interval: int = 30):
        """启动监控（每interval秒刷新）"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, args=(interval,), daemon=True)
        self.thread.start()
        
    def stop(self):
        """停止监控"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
            
    def _monitor_loop(self, interval: int):
        """监控主循环"""
        while self.running:
            try:
                self._check_watchlist()
                self._check_positions()
                self._check_market_anomaly()
            except Exception as e:
                print(f"[监控] 异常: {e}")
            
            time.sleep(interval)
            
    def _check_watchlist(self):
        """检查自选股异动"""
        watchlist = get_watchlist()
        if not watchlist:
            return
        
        for stock in watchlist:
            code = stock["code"]
            name = stock["name"]
            
            try:
                quote = get_realtime_quote(code)
                if not quote:
                    continue
                
                price = quote["price"]
                pct_change = quote["pct_change"]
                
                # 检查涨跌幅异动
                alert_key = f"{code}_{datetime.now().strftime('%Y%m%d')}"
                
                if alert_key not in self.alerts_sent:
                    # 涨停/跌停
                    if pct_change >= 9.9:
                        send_watchlist_alert(code, name, "limit_up", price, pct_change)
                        self.alerts_sent.add(alert_key)
                    elif pct_change <= -9.9:
                        send_watchlist_alert(code, name, "limit_down", price, pct_change)
                        self.alerts_sent.add(alert_key)
                    # 大涨大跌（>5%）
                    elif pct_change > 5:
                        send_watchlist_alert(code, name, "surge", price, pct_change)
                        self.alerts_sent.add(alert_key)
                    elif pct_change < -5:
                        send_watchlist_alert(code, name, "plunge", price, pct_change)
                        self.alerts_sent.add(alert_key)
                
                # 检查价格突破
                last_price = self.last_prices.get(code)
                if last_price:
                    # 突破前高
                    if price > last_price * 1.03:  # 涨超3%
                        if f"{code}_breakout_{datetime.now().strftime('%Y%m%d%H')}" not in self.alerts_sent:
                            send_watchlist_alert(code, name, "breakout", price, pct_change)
                            self.alerts_sent.add(f"{code}_breakout_{datetime.now().strftime('%Y%m%d%H')}")
                
                self.last_prices[code] = price
                
                # 回调给UI
                if self.callback:
                    self.callback({
                        "type": "quote",
                        "code": code,
                        "name": name,
                        "price": price,
                        "pct_change": pct_change,
                    })
                    
            except Exception as e:
                print(f"[监控] {code} 异常: {e}")
                
    def _check_positions(self):
        """检查持仓预警 — 利用portfolio_advisor分析并推送操作建议"""
        from .db import get_positions
        from .portfolio_advisor import analyze_position
        from .alerts import send_position_alert
        
        positions = get_positions()
        if not positions:
            return
        
        for p in positions:
            code = p["code"]
            try:
                quote = get_realtime_quote(code)
                if not quote:
                    continue
                
                current_price = quote["price"]
                
                hist = get_stock_history(code, days=250)
                if hist is None or len(hist) < 50:
                    continue
                
                close_arr = hist["close"].values.astype(np.float64)
                high_arr = hist["high"].values.astype(np.float64)
                low_arr = hist["low"].values.astype(np.float64)
                vol_arr = hist["volume"].values.astype(np.float64)
                open_arr = hist["open"].values.astype(np.float64)
                
                advice = analyze_position(
                    code=code,
                    buy_price=p["buy_price"],
                    current_price=current_price,
                    quantity=p["quantity"],
                    stop_loss=p.get("stop_loss", 0),
                    target_price=p.get("target_price", 0),
                    close=close_arr, high=high_arr, low=low_arr,
                    volume=vol_arr, open_price=open_arr,
                )
                if not advice:
                    continue
                
                # 只在紧急程度>=3（减仓/清仓/离场/加仓）时推送预警
                if advice.urgency < 3:
                    continue
                
                # 每只股票每个操作建议每天最多推送一次
                alert_key = f"pos_{code}_{advice.action}_{datetime.now().strftime('%Y%m%d')}"
                if alert_key in self.alerts_sent:
                    continue
                
                pnl_pct = (current_price - p["buy_price"]) / p["buy_price"] * 100 if p["buy_price"] > 0 else 0
                
                name = quote.get("name", code)
                success = send_position_alert(
                    code=code, name=name, action=advice.action,
                    reason=advice.reason, price=current_price,
                    buy_price=p["buy_price"], pnl_pct=pnl_pct,
                    risk_score=advice.risk_score,
                    dynamic_stop=advice.dynamic_stop,
                    dynamic_target=advice.dynamic_target,
                )
                if success:
                    self.alerts_sent.add(alert_key)
                    
            except Exception as e:
                print(f"[监控-持仓] {code} 异常: {e}")
    
    def _check_market_anomaly(self):
        """检查市场异动（板块异动等）"""
        # 这里可以添加板块异动检测逻辑
        pass
        
    def get_status(self) -> dict:
        """获取监控状态"""
        return {
            "running": self.running,
            "watchlist_count": len(get_watchlist()),
            "alerts_sent": len(self.alerts_sent),
            "last_update": datetime.now().strftime("%H:%M:%S"),
        }


# 全局监控实例
_monitor: Optional[IntradayMonitor] = None


def get_monitor() -> IntradayMonitor:
    """获取全局监控实例"""
    global _monitor
    if _monitor is None:
        _monitor = IntradayMonitor()
    return _monitor


def start_monitoring(interval: int = 30, callback: Optional[Callable] = None):
    """启动监控"""
    monitor = get_monitor()
    if callback:
        monitor.callback = callback
    monitor.start(interval)
    return monitor


def stop_monitoring():
    """停止监控"""
    monitor = get_monitor()
    monitor.stop()
