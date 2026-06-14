#!/usr/bin/env python3
"""快速V10信号计算（腾讯日K qfqday修复版）"""
import json, urllib.request, re, time, os, sys
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

def get_tx_klines(code):
    code = str(code).strip()
    secid = f"sz{code}" if code.startswith('00') else f"sh{code}" if code.startswith('60') else f"sz{code}"
    all_bars = []
    page = 1
    while True:
        url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={secid},day,,,{page},qfq"
        try:
            resp = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"}), timeout=10)
            resp_text = resp.read().decode('utf-8', errors='ignore')
            json_str = resp_text.split('=', 1)[1] if '=' in resp_text else resp_text
            raw = json.loads(json_str)
            if not isinstance(raw, dict):
                break
            data = raw.get('data', {})
            if not isinstance(data, dict):
                break
        except: break
        
        sz = data.get(secid, {})
        if not isinstance(sz, dict):
            break
        # qfqday可能是dict或list
        qfqday = sz.get('qfqday', {})
        if isinstance(qfqday, dict):
            # 格式: {"2026-05-06": ...} 
            bars = []
            for date_str, vals in qfqday.items():
                if isinstance(vals, list) and len(vals) >= 6:
                    bars.append([date_str] + [float(v) for v in vals])
            bars.sort(key=lambda x: x[0])
        elif isinstance(qfqday, list):
            bars = qfqday
        else:
            # 尝试klines
            klines = sz.get('klines', [])
            if isinstance(klines, list):
                bars = [k.split(',') if isinstance(k, str) else k for k in klines]
            else:
                bars = []
        
        if not bars:
            break
        all_bars = bars + all_bars
        page += 1
        if len(bars) < 100:
            break
        time.sleep(0.02)
    
    if len(all_bars) < 250:
        return None
    return all_bars

def calc_v10_signal(code, name, klines):
    records = []
    for bar in klines:
        d = bar[0] if isinstance(bar[0], str) else str(bar[0])
        records.append({
            '日期': d, '开盘': float(bar[1]), '收盘': float(bar[2]),
            '最高': float(bar[3]), '最低': float(bar[4]), '成交量': float(bar[5]),
        })
    df = pd.DataFrame(records).sort_values('日期').reset_index(drop=True)
    if len(df) < 60: return None
    
    c = df['收盘']; h = df['最高']; l_ = df['最低']; o = df['开盘']
    
    def ema(s, n): return s.ewm(span=n, adjust=False).mean()
    
    df['E20'] = ema(c, 20); df['E40'] = ema(c, 40)
    df['E60'] = ema(c, 60); df['E200'] = ema(c, 200)
    
    ef = ema(c, 20); es = ema(c, 80)
    df['DIF'] = ef - es
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['BAR'] = 2 * (df['DIF'] - df['DEA'])
    
    tr = pd.concat([h-l_, (h-c.shift(1)).abs(), (l_-c.shift(1)).abs()], axis=1).max(axis=1)
    df['ATR'] = tr.ewm(span=14, adjust=False).mean()
    df['VOL_MA5'] = df['成交量'].rolling(5).mean()
    
    t = df.iloc[-1]; y = df.iloc[-2]
    
    e20_60 = bool(t['E20'] > t['E60'])
    ov200 = bool(t['收盘'] > t['E200'])
    ov40 = bool(t['收盘'] > t['E40'])
    
    gc = bool(t['E20'] > t['E40'] and y['E20'] < y['E40'])
    dc = bool(t['E20'] < t['E40'] and y['E20'] > y['E40'])
    
    gdays = 0
    for i in range(len(df)-1, -1, -1):
        if df.iloc[i]['E20'] > df.iloc[i]['E40']: gdays += 1
        else: break
    
    perf = bool(t['E20'] > t['E40'] > t['E60'] > t['E200'])
    mturn = bool(t['DIF'] > y['DIF'])
    mbar = bool(t['BAR'] > 0)
    vol = bool(t['成交量'] > t['VOL_MA5'] * 1.05) if t['VOL_MA5'] > 0 else False
    
    atr_s = round(t['收盘'] - 2.5 * t['ATR'], 2)
    pct = (t['收盘'] - y['收盘']) / y['收盘'] * 100 if y['收盘'] > 0 else 0
    
    # 强庄
    w = (2*c + o + h + l_) * 100
    we4 = ema(w, 4)
    v1 = (w / we4 - 1) * 100
    v1h = v1.abs().rolling(20, min_periods=5).max()
    vn = v1.iloc[-1]; vh = v1h.iloc[-1]; v5 = v1.iloc[-min(6,len(v1))]
    sz = bool(abs(vn) == vh and vn > 0 and vn > v5)
    
    # 信号
    sig = "不满足"; sc = 0
    if gc and ov200 and mturn and mbar and sz and vol:
        sig = "★买+强庄"; sc = 100
    elif gc and ov200 and mturn and mbar:
        sig = "★买"; sc = 95
    elif e20_60 and ov200 and ov40 and mturn and sz:
        sig = "持仓+强庄"; sc = 85
    elif e20_60 and ov200 and ov40 and mturn:
        sig = "持仓"; sc = 70
    elif (dc and not ov40) or (not ov40 and y['收盘'] >= y['E40']):
        sig = "⚠清仓"; sc = -50
    elif sz:
        sig = "★强庄"; sc = 60 if ov200 else 45
    
    bonus = 0
    if perf: bonus += 5
    if vol: bonus += 2
    if mbar: bonus += 2
    if ov200: bonus += 3
    if gdays >= 20: bonus += 3
    if sz and ov200: bonus += 5
    sc = min(max(sc + bonus, -100), 100)
    
    if perf: td = "完美多头"
    elif ov40 and e20_60 and ov200: td = "趋势多头"
    elif ov40 and e20_60: td = "多头年线下"
    elif ov40: td = "E40支撑"
    elif ov200: td = "年线支撑"
    else: td = "弱势"
    
    sell = []
    if dc: sell.append("死叉")
    if not ov40 and y['收盘'] >= y['E40']: sell.append("破E40")
    
    return {'代码':code,'名称':name,'收盘':round(t['收盘'],2),'涨幅%':round(pct,2),
            'EMA20':round(t['E20'],2),'EMA40':round(t['E40'],2),'EMA60':round(t['E60'],2),
            'EMA200':round(t['E200'],2),'ATR止损':atr_s,'金叉天数':gdays,
            '年线':'Y' if ov200 else 'N','完美多头':'Y' if perf else 'N',
            '强庄':'Y' if sz else 'N','排列':td,
            '信号':sig,'评分':sc}

def main():
    today = "2026-05-06"
    print(f"[INFO] V10信号快速计算 — {today}\n")
    
    # 读取尾盘候选股
    weipan = []
    weipan_path = '/tmp/tail_xuangu_v4_result.csv'
    if os.path.exists(weipan_path):
        df_wp = pd.read_csv(weipan_path)
        weipan = [(str(c).strip(), str(n).strip()) for c,n in zip(df_wp['代码'], df_wp['名称'])]
        print(f"[INFO] 尾盘候选: {len(weipan)}只")
    
    # 读取新浪基础池也查
    print("[INFO] 获取今天全市场...")
    all_s = []
    for p in range(1, 100):
        url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeDataSimple?page={p}&num=100&sort=changepercent&asc=0&node=hs_a"
        req = urllib.request.Request(url, headers={"Referer":"https://finance.sina.com.cn","User-Agent":"Mozilla/5.0"})
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode('utf-8'))
            if not data: break
            all_s.extend(data)
            if len(data) < 100: break
        except: break
    
    base = []
    for s in all_s:
        try:
            code = str(s.get('code',''))
            name = str(s.get('name',''))
            zdf = float(s.get('changepercent',0)) if s.get('changepercent') is not None else 0
            if not (code.startswith('60') or code.startswith('00')): continue
            if 'ST' in name or '退' in name: continue
            if not (0 <= zdf <= 8): continue
            base.append((code, name))
        except: continue
    print(f"[INFO] 基础池: {len(base)}只")
    
    # 合并去重
    all_codes = list(set(weipan + base))
    print(f"[INFO] 总分析: {len(all_codes)}只\n")
    
    results = []
    for i, (cd, nm) in enumerate(all_codes):
        if i % 20 == 0:
            print(f"  进度 {i}/{len(all_codes)}", end='\r')
        klines = get_tx_klines(cd)
        if klines is None: continue
        r = calc_v10_signal(cd, nm, klines)
        if r and r['信号'] not in ('不满足',''):
            results.append(r)
    
    print(f"\n[INFO] 完成, 有效V10信号: {len(results)}只")
    
    if results:
        out = pd.DataFrame(results)
        pri = {'★买+强庄':0,'★买':1,'持仓+强庄':2,'持仓':3,'★强庄':4}
        out['_r'] = out['信号'].map(pri).fillna(9)
        out = out.sort_values(['_r','评分'], ascending=[True,False]).drop(columns=['_r'])
        out.to_csv('/tmp/v10_quick_results.csv', index=False, encoding='utf-8-sig')
        
        print(f"\n{'='*70}")
        print("📊 V10 选股报告 — 2026-05-06")
        print(f"{'='*70}")
        for sig in ['★买+强庄','★买','持仓+强庄','持仓','★强庄']:
            part = out[out['信号'] == sig]
            if len(part) == 0: continue
            emoji = {'★买+强庄':'🏰','★买':'🎯','持仓+强庄':'💎','持仓':'📈','★强庄':'👀'}
            print(f"\n{emoji.get(sig,'')} {sig}: {len(part)}只")
            for _, r in part.head(8).iterrows():
                sz = " [强庄]" if r['强庄']=='Y' else ""
                perf = " | 完美多头" if r['完美多头']=='Y' else ""
                print(f" {r['代码']} {r['名称']:　<6s} 涨{r['涨幅%']:.1f}% 评分{r['评分']} 金叉{r['金叉天数']}天{sz}{perf} 止损{r['ATR止损']}")
    
    print("\n[INFO] 尾盘抢筹单独报告:")
    print(f"{'代码':<8} {'名称':<10} {'涨幅%':<7} {'V10信号':<10} {'ATR止损':<9}")
    print("-"*50)
    for cd, nm in all_codes:
        r = next((x for x in results if x['代码']==cd), None)
        if r:
            sig = r['信号']
            atr = r['ATR止损']
            pct = r['涨幅%']
            print(f"{cd:<8} {nm:<10} {pct:<7.1f} {sig:<10} {atr:<9}")

if __name__ == '__main__':
    main()
