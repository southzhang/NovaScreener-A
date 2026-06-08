#!/usr/bin/env python3
"""
V10信号反馈统计脚本
读取信号日志，按信号级别统计胜率、平均持仓天数、最大回撤等指标
"""

import json
import os
import sys
from datetime import datetime
from collections import defaultdict
import math

# 信号级别定义
SIGNAL_LEVELS = {
    "全买入": {"name": "全买入", "description": "最强信号，所有条件满足"},
    "强庄买": {"name": "强庄买", "description": "庄家控盘信号强烈"},
    "基础买": {"name": "基础买", "description": "基础买入信号"}
}

def load_signal_log(log_path):
    """加载信号日志文件"""
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("records", [])
    except FileNotFoundError:
        print(f"错误: 信号日志文件不存在: {log_path}")
        return []
    except json.JSONDecodeError:
        print(f"错误: 信号日志文件格式错误: {log_path}")
        return []

def calculate_win_rate(records):
    """计算胜率"""
    total = len(records)
    if total == 0:
        return 0.0
    
    wins = sum(1 for r in records if r.get("result") == "win")
    return wins / total * 100

def calculate_avg_hold_days(records):
    """计算平均持仓天数"""
    hold_days = [r.get("hold_days", 0) for r in records if r.get("hold_days") is not None]
    if not hold_days:
        return 0.0
    return sum(hold_days) / len(hold_days)

def calculate_max_drawdown(records):
    """计算最大回撤"""
    # 按日期排序
    sorted_records = sorted(records, key=lambda x: x.get("date", ""))
    if not sorted_records:
        return 0.0
    
    # 计算累计收益曲线
    cumulative = [1.0]  # 初始净值为1
    for record in sorted_records:
        pnl = record.get("pnl_pct", 0)
        if pnl is not None:
            cumulative.append(cumulative[-1] * (1 + pnl / 100))
        else:
            cumulative.append(cumulative[-1])
    
    # 计算最大回撤
    peak = cumulative[0]
    max_drawdown = 0
    
    for value in cumulative:
        if value > peak:
            peak = value
        
        drawdown = (peak - value) / peak * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    return max_drawdown

def calculate_avg_pnl(records):
    """计算平均盈亏"""
    pnls = [r.get("pnl_pct", 0) for r in records if r.get("pnl_pct") is not None]
    if not pnls:
        return 0.0
    return sum(pnls) / len(pnls)

def analyze_by_signal_level(records):
    """按信号级别统计分析"""
    results = {}
    
    # 按信号级别分组
    grouped = defaultdict(list)
    for record in records:
        signal_level = record.get("signal_level", "未知")
        grouped[signal_level].append(record)
    
    # 统计每个级别
    for level, level_records in grouped.items():
        if level not in SIGNAL_LEVELS:
            level_name = level
        else:
            level_name = SIGNAL_LEVELS[level]["name"]
        
        results[level_name] = {
            "count": len(level_records),
            "win_rate": calculate_win_rate(level_records),
            "avg_hold_days": calculate_avg_hold_days(level_records),
            "max_drawdown": calculate_max_drawdown(level_records),
            "avg_pnl": calculate_avg_pnl(level_records)
        }
    
    return results

def find_best_hold_days(records):
    """找出最佳持仓天数区间"""
    if not records:
        return 0
    
    # 按持仓天数分组
    grouped = defaultdict(list)
    for record in records:
        hold_days = record.get("hold_days")
        if hold_days is not None:
            # 将持仓天数分组到区间
            if hold_days <= 3:
                group = "1-3天"
            elif hold_days <= 7:
                group = "4-7天"
            elif hold_days <= 14:
                group = "8-14天"
            else:
                group = "15天以上"
            
            grouped[group].append(record)
    
    # 计算每组的胜率
    best_group = None
    best_win_rate = -1
    
    for group, group_records in grouped.items():
        win_rate = calculate_win_rate(group_records)
        if win_rate > best_win_rate:
            best_win_rate = win_rate
            best_group = group
    
    return best_group

def find_worst_signal_type(analysis):
    """找出最差信号类型"""
    worst_type = None
    worst_win_rate = 100.0
    
    for level, stats in analysis.items():
        if stats["win_rate"] < worst_win_rate:
            worst_win_rate = stats["win_rate"]
            worst_type = level
    
    return worst_type, worst_win_rate

def print_statistics(analysis, records):
    """打印统计结果"""
    print("=" * 60)
    print("V10信号反馈系统 - 统计报告")
    print("=" * 60)
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"总信号数量: {len(records)}")
    print()
    
    # 各级别统计
    print("【按信号级别统计】")
    print("-" * 60)
    print(f"{'信号级别':<10} {'数量':<8} {'胜率%':<10} {'平均持仓天数':<12} {'最大回撤%':<12} {'平均盈亏%':<10}")
    print("-" * 60)
    
    for level, stats in analysis.items():
        print(f"{level:<10} {stats['count']:<8} {stats['win_rate']:<10.2f} {stats['avg_hold_days']:<12.1f} {stats['max_drawdown']:<12.2f} {stats['avg_pnl']:<10.2f}")
    
    print()
    
    # 总体统计
    total_win_rate = calculate_win_rate(records)
    total_avg_hold = calculate_avg_hold_days(records)
    total_max_drawdown = calculate_max_drawdown(records)
    total_avg_pnl = calculate_avg_pnl(records)
    best_hold_days = find_best_hold_days(records)
    worst_type, worst_rate = find_worst_signal_type(analysis)
    
    print("【总体统计】")
    print("-" * 40)
    print(f"总体胜率: {total_win_rate:.2f}%")
    print(f"平均持仓天数: {total_avg_hold:.1f}天")
    print(f"最大回撤: {total_max_drawdown:.2f}%")
    print(f"平均盈亏: {total_avg_pnl:.2f}%")
    print(f"最佳持仓天数区间: {best_hold_days}")
    print(f"最差信号类型: {worst_type} (胜率: {worst_rate:.2f}%)")
    print()
    
    # 信号质量评估
    print("【信号质量评估】")
    print("-" * 40)
    if total_win_rate >= 70:
        print("✓ 信号质量优秀，胜率超过70%")
    elif total_win_rate >= 60:
        print("✓ 信号质量良好，胜率在60%-70%")
    elif total_win_rate >= 50:
        print("△ 信号质量一般，胜率在50%-60%，建议优化")
    else:
        print("✗ 信号质量较差，胜率低于50%，需要改进")
    
    if total_max_drawdown < 10:
        print("✓ 风险控制良好，最大回撤低于10%")
    elif total_max_drawdown < 20:
        print("△ 风险控制一般，最大回撤在10%-20%")
    else:
        print("✗ 风险控制较差，最大回撤超过20%，需要加强止损")
    
    print()
    print("=" * 60)

def main():
    """主函数"""
    # 默认日志路径
    log_path = os.path.expanduser("~/.hermes/workspace/v10_signal_log.json")
    
    # 支持命令行参数指定路径
    if len(sys.argv) > 1:
        log_path = sys.argv[1]
    
    # 加载数据
    records = load_signal_log(log_path)
    
    if not records:
        print("没有找到信号记录，请先添加信号数据。")
        print(f"日志文件路径: {log_path}")
        return
    
    # 统计分析
    analysis = analyze_by_signal_level(records)
    
    # 输出结果
    print_statistics(analysis, records)

if __name__ == "__main__":
    main()
