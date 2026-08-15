#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""regime_layer2_backtest.py —— Layer 2：用通达信本地 .day(全历史) + gbbq 前复权 替换 sina 未复权,
重跑 质量+动量 周频策略, 对比 5 个 regime 方案, 让数据定夺"以偏带全"怎么治。

数据来源(本机 D: 盘, 沙箱已挂载):
  - 个股/指数日线: D:/new_tdx64/vipdoc/{sh,sz,bj}/lday/*.day (read_day / read_qfq 前复权)
  - 基本面: fundamentals_broad.json (1438 只, annual 字段做质量门)
  - 权息: all_xdxr.csv (decode_gbbq.py 生成) -> read_qfq() 自动接入

五方案(regime 如何裁决全股池满/空仓):
  当前(current): 上证 sh000001 站上56周MA -> 多; 否则空
  A:          中证全指 sh000985 站上56周MA
  B:          分市场匹配(创业板指/科创50/上证/深成指/北证50) 各自站上56周MA, 每只票用所属段指数
  C:          内生择时(无外部regime, 买卖完全由个股信号 drive)
  E:          分层regime(上证跌破200周MA才强制空仓, 日常靠个股信号)

指标: 年化 / 夏普 / 最大回撤 / 空仓占比 / 平均持仓数 / 换手率。
输出: results_layer2.json + regime_basis_backtest.html
"""
import json, math, os, datetime, sys, re
import tdx_day_reader as T

WORK = os.path.dirname(os.path.abspath(__file__))
RF = 0.02
FIN_KW = ["银行", "证券", "保险", "信托", "期货", "租赁", "财富", "金融", "基金"]
INIT = 1.0

# ---------------- 通用数学/框架辅助(复用 backtest_weekly 逻辑) ----------------
def stdev(xs):
    n=len(xs)
    if n<2: return 0.0
    m=sum(xs)/n
    return math.sqrt(sum((x-m)**2 for x in xs)/(n-1))

def rank_normalize(vals):
    order=sorted(range(len(vals)), key=lambda i: vals[i])
    r=[0.0]*len(vals)
    for rank,i in enumerate(order):
        r[i]=rank/(len(vals)-1) if len(vals)>1 else 0.5
    return r

def max_drawdown(curve):
    peak,mdd=curve[0],0.0
    for v in curve:
        peak=max(peak,v); mdd=min(mdd,v/peak-1)
    return mdd

def ma_series(vals, n):
    out=[None]*len(vals); s=0.0
    for i,v in enumerate(vals):
        s+=v
        if i>=n: s-=vals[i-n]
        if i>=n-1: out[i]=s/n
    return out

def annualized(total_ret, periods, freq):
    py = 52 if freq=='W' else 12
    return (1+total_ret)**(py/periods)-1 if periods>0 else 0.0

def is_financial(industry):
    return any(k in (industry or "") for k in FIN_KW)

def pct_rank_local(value, hist):
    if not hist: return 50.0
    return 100.0*sum(1 for h in hist if h<=value)/len(hist)

def _as_int(x):
    if isinstance(x,str):
        return int(x.replace('-','').replace('/',''))
    return int(x)

def pt_fund(annual, bar_date):
    bd=_as_int(bar_date)
    avail=[r for r in annual if r.get('notice') and _as_int(r['notice'])<=bd
           and r.get('np') and r.get('te') and r.get('ta')
           and r.get('tl') is not None and r.get('ocf') is not None and r.get('capex') is not None]
    if len(avail)<3: return None
    latest=avail[-1]
    roes=[r['np']/r['te'] for r in avail[-3:] if r['te']]
    if len(roes)<3: return None
    roe_now=latest['np']/latest['te']; debt=latest['tl']/latest['ta']
    fcfnp=(latest['ocf']-latest['capex'])/latest['np'] if latest['np'] else None
    allroes=[r['np']/r['te'] for r in avail if r['te']]
    mean=sum(allroes)/len(allroes)
    cv=(stdev(allroes)/mean) if mean>0 else 3.0
    return dict(roe_now=roe_now, roe3=roes, debt=debt, fcfnp=fcfnp, cv=cv, n=len(avail))

def mom_metrics(dates, close, ti, mom_window):
    if ti<mom_window: return None
    tr=[close[dates[i]] for i in range(ti-mom_window, ti+1) if dates[i] in close]
    if len(tr)<mom_window+1: return None
    mom=tr[-1]/tr[0]-1; ma=sum(tr[-mom_window:])/mom_window
    return mom, ma, tr[-1]

def trailing(dates, close, ti, n):
    out=[]
    for i in range(ti, ti-n, -1):
        if i<0: break
        if dates[i] in close: out.append(close[dates[i]])
        else: break
    out.reverse(); return out

# ---------------- Layer 2 数据: .day + read_qfq 全历史 ----------------
def qfq_to_weekly(bars):
    """read_qfq 日线(升序) -> ISO 周线 list[{date,pkey,open,high,low,close,vol}]"""
    buckets={}
    for b in bars:
        dint=b['date']
        y=dint//10000; m=(dint//100)%100; day=dint%100
        yw=datetime.date(y,m,day).isocalendar()
        key=f"{yw[0]}-{yw[1]:02d}"
        if key not in buckets:
            buckets[key]={'date':dint,'pkey':key,'open':b['open'],'high':b['high'],
                          'low':b['low'],'close':b['close'],'vol':b['volume']}
        else:
            m2=buckets[key]
            m2['high']=max(m2['high'],b['high']); m2['low']=min(m2['low'],b['low'])
            m2['close']=b['close']; m2['vol']+=b['volume']
            if dint>m2['date']: m2['date']=dint
    return [buckets[k] for k in sorted(buckets.keys())]

def day_to_weekly(bars):
    """read_day 日线(升序, 指数无分红) -> 周线"""
    return qfq_to_weekly(bars)

def build_index_weekly(symbol, min_weeks=60):
    bars=T.read_day(symbol)
    if not bars: return None
    wk=day_to_weekly(bars)
    if len(wk)<min_weeks: return None
    dates=[b['date'] for b in wk]
    closes=[b['close'] for b in wk]
    return {'dates':dates,'close':closes,'ma56':ma_series(closes,56),'ma200':ma_series(closes,200)}

def idx_ma_on(idx, d, window):
    dates=idx['dates']; lo,hi=0,len(dates)-1; ans=-1
    while lo<=hi:
        mid=(lo+hi)//2
        if dates[mid]<=d: ans=mid; lo=mid+1
        else: hi=mid-1
    if ans<0: return None
    key='ma56' if window==56 else 'ma200'
    return idx[key][ans]

def idx_close_on(idx, d):
    dates=idx['dates']; lo,hi=0,len(dates)-1; ans=-1
    while lo<=hi:
        mid=(lo+hi)//2
        if dates[mid]<=d: ans=mid; lo=mid+1
        else: hi=mid-1
    return idx['close'][ans] if ans>=0 else None

def seg_index_for(code):
    c=code
    if c.startswith('30') or c.startswith('301'): return 'sz399006'   # 创业板指
    if c.startswith('688'): return 'sh000688'                          # 科创50
    if c.startswith('8') or c.startswith('4') or c.startswith('92') or c.startswith('83') or c.startswith('43'): return 'bj899050'  # 北证50
    if c.startswith('6') or c.startswith('9'): return 'sh000001'       # 沪市(上证综指代理)
    return 'sz399001'                                                  # 深市(深证成指)

def build_universe_layer2(min_weeks=60, include_bj=True):
    fund=json.load(open(os.path.join(WORK,'fundamentals_broad.json'),encoding='utf-8'))
    xdxr=T._load_xdxr_map()
    # 全局时间轴 = 上证周线
    idx0=build_index_weekly('sh000001')
    global_dates=idx0['dates']; global_pkeys=[f"{d//10000}-{((datetime.date(d//10000,(d//100)%100,d%100).isocalendar()[1])):02d}" for d in global_dates]
    # 重新用 pkey(与 qfq_to_weekly 同算法)对齐 -> 直接复用 idx0 的 pkey
    global_pkeys=[]
    for d in global_dates:
        y=d//10000; m=(d//100)%100; day=d%100
        yw=datetime.date(y,m,day).isocalendar()
        global_pkeys.append(f"{yw[0]}-{yw[1]:02d}")
    stocks={}
    for code,f in fund.items():
        pure=''.join(ch for ch in code if ch.isdigit())
        bars=T.read_qfq(pure,_xdxr_map=xdxr)
        if not bars or len(bars)<min_weeks*5: continue
        wk=qfq_to_weekly(bars)
        if len(wk)<min_weeks: continue
        spk={b['pkey']:b['close'] for b in wk}
        sdates=[]; sclose={}; di={}; last=None
        for i,pk in enumerate(global_pkeys):
            c=spk.get(pk)
            if c is not None: last=c
            if last is None: continue
            sdates.append(global_dates[i]); sclose[global_dates[i]]=last
            di[global_dates[i]]=len(sdates)-1
        if len(sdates)<min_weeks: continue
        stocks[pure]={'dates':sdates,'close':sclose,
                      'sind':f.get('industry','') or '',
                      'fund':f.get('annual',[]),
                      'name':f.get('name','') or pure,
                      'di':di}
    # 北交所: 扫描 bj/lday/*.day (fundamentals_broad 不含北交所 -> fund=[] -> 质量门自然排除,
    # 但 B 方案的北证50 gate 仍可真实作用)。无基本面者不进 qscore 买仓, 仅可作段regime/动量观察。
    if include_bj:
        bj_dir=os.path.join(T.TDX_ROOT,'bj','lday')
        if os.path.isdir(bj_dir):
            for fn0 in os.listdir(bj_dir):
                if not fn0.endswith('.day'): continue
                pure=fn0[:-4].replace('bj','')
                if pure[:2] in ('81','82','89'): continue  # 北交所指数(89/81/82 开头, 非个股)
                if pure in stocks: continue
                bars=T.read_qfq(pure,_xdxr_map=xdxr)
                if not bars or len(bars)<min_weeks*5: continue
                wk=qfq_to_weekly(bars)
                if len(wk)<min_weeks: continue
                spk={b['pkey']:b['close'] for b in wk}
                sdates=[]; sclose={}; di={}; last=None
                for i,pk in enumerate(global_pkeys):
                    c=spk.get(pk)
                    if c is not None: last=c
                    if last is None: continue
                    sdates.append(global_dates[i]); sclose[global_dates[i]]=last
                    di[global_dates[i]]=len(sdates)-1
                if len(sdates)<min_weeks: continue
                stocks[pure]={'dates':sdates,'close':sclose,'sind':'北交所','fund':[],
                              'name':pure,'di':di}
    return stocks, global_dates, global_pkeys, idx0

# ---------------- regime 方案 ----------------
def make_regime_fn(scheme, indices, e_window=200):
    def fn(code, d):
        if scheme=='C':
            return True
        if scheme=='current':
            idx=indices['sh000001']; return _up(idx,d,56)
        if scheme=='A':
            idx=indices.get('sh000985')
            return _up(idx,d,56) if idx else True
        if scheme.startswith('E'):
            idx=indices['sh000001']
            return _up(idx,d,e_window)  # 尾部开关: 站上 e_window 周MA=True; 跌破=False(尾部风险)
        if scheme=='B':
            sym=seg_index_for(code); idx=indices.get(sym)
            # 段指数缺失或 MA56 尚未成熟(新指数诞生后首~1年) -> 回退父指数(上证, 永远存在且成熟)门控,
            # 不再无脑放行(return True) -> 修复早期年份 B 退化为"永远满仓、无保护"的缺陷。
            if idx is None or idx_ma_on(idx,d,56) is None:
                idx=indices.get('sh000001', idx)
            return _up(idx,d,56)
        return True
    def _up(idx,d,w):
        if idx is None: return True
        ic=idx_close_on(idx,d); ma=idx_ma_on(idx,d,w)
        if ic is None or ma is None: return True
        return ic>=ma
    return fn

# ---------------- 回测引擎(Layer 2, 支持 global / stock 两种 regime 作用域) ----------------
def run_backtest_layer2(stocks, global_dates, scheme, regime_fn, regime_scope,
                        N=15, mom_window=52, val_window=260, cost_per_side=0.0012,
                        tail_expo=0.0, warmup=220, price_cap=300.0, ind_cap=0.35, freq='W',
                        start_date=None, end_date=None):
    meta={}
    for code,s in stocks.items():
        d=s['dates']; c=s['close']
        meta[code]={'d':d,'c':c,'sind':s['sind'],'fund':s['fund'],
                    'di':{d[i]:i for i in range(len(d))}}
    all_dates=list(global_dates)
    sd_int=_as_int(start_date) if start_date else None
    ed_int=_as_int(end_date) if end_date else None
    t_start=warmup
    if sd_int is not None:
        for i in range(warmup,len(all_dates)):
            if all_dates[i]>=sd_int: t_start=i; break
    t_end=len(all_dates)-1
    if ed_int is not None:
        for i in range(t_start,len(all_dates)):
            if all_dates[i]>ed_int: t_end=i-1; break
    equity=[1.0]; rets=[]; held={}; prev_w=None; turnover_l=[]; n_pool=[]; empty_bars=0
    for t in range(t_start, t_end):
        bd=all_dates[t]
        market_up = regime_fn(None, bd) if regime_scope=='global' else True
        # 退出
        for code in list(held):
            ti=meta[code]['di'].get(bd)
            if ti is None: continue
            if regime_scope=='stock' and not regime_fn(code, bd):
                del held[code]; continue
            mm=mom_metrics(meta[code]['d'], meta[code]['c'], ti, mom_window)
            if mm is None:
                del held[code]; continue
            mom12,ma12,price=mm
            trend_break=(price<ma12)
            wv=trailing(meta[code]['d'], meta[code]['c'], ti, val_window)
            val_pr=pct_rank_local(wv[-1], wv) if len(wv)>=12 else 0.0
            overcap=price>price_cap
            deteriorate=mom12<=-0.40
            if trend_break or val_pr>=85.0 or overcap or deteriorate:
                del held[code]
        # 全局 regime 离场: 完全空仓型(tail_expo==0)清空持仓; 部分降仓型(E200H)只降暴露不清仓
        if regime_scope=='global' and (not market_up) and tail_expo==0.0:
            held={}
        # 候选
        cands={}; codes=[]
        for code in stocks:
            ti=meta[code]['di'].get(bd)
            if ti is None: continue
            if regime_scope=='stock' and not regime_fn(code, bd): continue
            mm=mom_metrics(meta[code]['d'], meta[code]['c'], ti, mom_window)
            if mm is None: continue
            mom12,ma12,price=mm
            if price>price_cap: continue
            if not (price>ma12): continue
            ff=pt_fund(meta[code]['fund'], bd)
            if ff is None: continue
            if ff["roe_now"]<0.10: continue
            if ff["fcfnp"] is None or ff["fcfnp"]<0: continue
            if not (mom12>0): continue
            if is_financial(meta[code]['sind']): continue
            cands[code]=(price, ff, mom12); codes.append(code)
        if codes:
            roe_rk=rank_normalize([cands[c][1]["roe_now"] for c in codes])
            fcf_rk=rank_normalize([cands[c][1]["fcfnp"] for c in codes])
            cv_rk=rank_normalize([cands[c][1]["cv"] for c in codes])
            debt_rk=rank_normalize([cands[c][1]["debt"] for c in codes])
            mom_rk=rank_normalize([cands[c][2] for c in codes])
            for i,code in enumerate(codes):
                qs=(roe_rk[i]+fcf_rk[i]+(1-cv_rk[i])+(1-debt_rk[i]))/4.0
                s=0.5*qs+0.5*mom_rk[i]
                cands[code]=(cands[code][0], s)
        n_pool.append(len(codes))
        if len(held)<N:
            order=sorted(cands, key=lambda c:-cands[c][1])
            indc={}
            for c in held: indc[meta[c]['sind']]=indc.get(meta[c]['sind'],0)+1
            capn=int(math.floor(ind_cap*N))
            for code in order:
                if len(held)>=N: break
                if code in held: continue
                ci=meta[code]['sind']
                if indc.get(ci,0)>=capn: continue
                held[code]=1; indc[ci]=indc.get(ci,0)+1
        # 暴露: 分市场(B)始终0.9(个股段gate已过滤); 全局方案 market_up→0.9, 否则→tail_expo(0=空仓, 0.45=半仓)
        if regime_scope=='stock':
            expo=0.9
        elif market_up:
            expo=0.9
        else:
            expo=tail_expo
        k=len(held)
        w={}
        if k:
            for c in held: w[c]=(1.0/k)*expo
        r=0.0
        for code,wt in w.items():
            ti=meta[code]['di'].get(bd); ti2=meta[code]['di'].get(all_dates[t+1]) if t+1<len(all_dates) else None
            if ti is None or ti2 is None: continue
            p0=meta[code]['c'][meta[code]['d'][ti]]; p1=meta[code]['c'][meta[code]['d'][ti2]]
            if p0 and p1: r+=wt*(p1/p0-1)
        if cost_per_side>0 and prev_w is not None:
            to=sum(abs(w.get(c,0.0)-prev_w.get(c,0.0)) for c in set(w)|set(prev_w))
            r-=to*cost_per_side; turnover_l.append(to)
        prev_w=dict(w)
        equity.append(equity[-1]*(1+r)); rets.append(r)
        # 空仓占比 = 组合实际暴露为0的周占比(离场时间), 而非 held 是否为空
        if expo==0.0: empty_bars+=1
    periods=len(rets)
    total=equity[-1]-1
    ann=annualized(total, periods, freq)
    vol_a=stdev(rets)*math.sqrt(52)
    sharpe=(ann-RF)/vol_a if vol_a>0 else 0.0
    mdd=max_drawdown(equity)
    avg_pool=sum(n_pool)/len(n_pool) if n_pool else 0
    avg_to=sum(turnover_l)/len(turnover_l) if turnover_l else 0
    empty_frac=empty_bars/periods if periods else 0
    return dict(freq=freq, periods=periods, total_return=total, annualized=ann,
                vol_annual=vol_a, sharpe=sharpe, max_drawdown=mdd,
                avg_quality_pool=avg_pool, avg_turnover=avg_to,
                empty_frac=empty_frac, equity_curve=equity)

def main():
    print("构建 Layer 2 宇宙(.day + read_qfq 全历史)...")
    stocks, global_dates, global_pkeys, idx0 = build_universe_layer2()
    print(f"  个股数={len(stocks)}  全局周轴={len(global_dates)} (首 {global_dates[0]} 末 {global_dates[-1]})")
    indices={'sh000001':idx0}
    for sym in ['sh000985','sh000688','sz399006','sz399001','bj899050']:
        ix=build_index_weekly(sym)
        if ix: indices[sym]=ix
        else: print(f"  [warn] 指数 {sym} 周线不足, 跳过")
    print(f"  指数: {list(indices.keys())}")

    schemes=[
        ('current','global','当前(上证56w)', 200, 0.0),
        ('A','global','A(中证全指56w)', 200, 0.0),
        ('B','stock','B(分市场56w)', 200, 0.0),
        ('C','global','C(内生无regime)', 200, 0.0),
        ('E','global','E(上证200w尾部)', 200, 0.0),
        ('E150','global','E(上证150w尾部)', 150, 0.0),
        ('E120','global','E(上证120w尾部)', 120, 0.0),
        ('E250','global','E(上证250w尾部)', 250, 0.0),
        ('E200H','global','E(上证200w→半仓)', 200, 0.45),
    ]
    windows=[(None,None,'全样本1996+'),('2014-01-01',None,'2014+')]
    results={}
    print(f"\n{'方案':<18}{'窗口':<14}{'年化':>8}{'夏普':>7}{'回撤':>9}{'空仓%':>8}{'均池':>7}{'换手%':>8}")
    print("-"*79)
    for (sch,scope,label,e_win,tail) in schemes:
        fn=make_regime_fn(sch, indices, e_window=e_win)
        for (sd,ed,wlbl) in windows:
            r=run_backtest_layer2(stocks, global_dates, sch, fn, scope,
                                  N=15, mom_window=52, val_window=260,
                                  cost_per_side=0.0012, tail_expo=tail, warmup=220,
                                  start_date=sd, end_date=ed)
            key=f"{sch}_{wlbl.replace(' ','')}"
            results[key]=r
            print(f"{label:<16}{wlbl:<14}{r['annualized']*100:>7.1f}%{r['sharpe']:>7.2f}"
                  f"{r['max_drawdown']*100:>8.1f}%{r['empty_frac']*100:>7.1f}%"
                  f"{r['avg_quality_pool']:>7.1f}{r['avg_turnover']*100:>7.2f}%")
    json.dump({k:{kk:vv for kk,vv in v.items() if kk!='equity_curve'} for k,v in results.items()},
              open(os.path.join(WORK,'results_layer2.json'),'w',encoding='utf-8'), ensure_ascii=False, indent=1)
    # 写 HTML
    write_html(results, global_dates)
    print("\nwritten -> results_layer2.json + regime_basis_backtest.html")

def write_html(results, global_dates):
    # 只画全样本 5 条权益曲线
    curves={}
    for k,v in results.items():
        if '全样本' in k and k.split('_')[0] in ('current','A','B','C','E'):
            curves[k]=v['equity_curve']
    colors={'current':'#1f77b4','A':'#ff7f0e','B':'#2ca02c','C':'#d62728','E':'#9467bd',
            'E150':'#17becf','E120':'#bcbd22','E250':'#7f7f7f','E200H':'#e377c2'}
    labels={'current':'当前(上证56w)','A':'A(中证全指56w)','B':'B(分市场56w)','C':'C(内生)','E':'E(上证200w)',
            'E150':'E(150w尾部)','E120':'E(120w尾部)','E250':'E(250w尾部)','E200H':'E(200w→半仓)'}
    W,H=900,420; pad=55
    n=max(len(c) for c in curves.values()) if curves else 1
    # y 范围(log)
    import math as _m
    allvals=[v for c in curves.values() for v in c]
    ymin=_m.log10(min(allvals)); ymax=_m.log10(max(allvals))
    def x(i): return pad+(W-2*pad)*(i/(n-1 if n>1 else 1))
    def y(v): return H-pad-(H-2*pad)*((_m.log10(v)-ymin)/(ymax-ymin))
    svg=[f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="11">']
    svg.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fff"/>')
    # 网格 + y 轴标签
    for g in range(0,6):
        yy=pad+(H-2*pad)*g/5.0
        val=10**(ymax-(ymax-ymin)*g/5.0)
        svg.append(f'<line x1="{pad}" y1="{yy:.1f}" x2="{W-pad}" y2="{yy:.1f}" stroke="#eee"/>')
        svg.append(f'<text x="4" y="{yy+3:.1f}" fill="#666">{val:.2f}x</text>')
    for k,curve in curves.items():
        col=colors.get(k.split('_')[0],'#333')
        pts=" ".join(f"{x(i):.1f},{y(v):.1f}" for i,v in enumerate(curve))
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6"/>')
    svg.append('</svg>')
    svg_str="".join(svg)
    # 表格
    rows=[]
    for k,v in results.items():
        sch=k.split('_')[0]
        tag=labels.get(sch,k)
        winlbl='全样本' if '全样本' in k else '2014+'
        rows.append(f"<tr><td>{tag}</td><td>{winlbl}</td><td>{v['annualized']*100:.1f}%</td>"
                    f"<td>{v['sharpe']:.2f}</td><td>{v['max_drawdown']*100:.1f}%</td>"
                    f"<td>{v['empty_frac']*100:.1f}%</td><td>{v['avg_quality_pool']:.1f}</td>"
                    f"<td>{v['avg_turnover']*100:.2f}%</td></tr>")
    legend="".join(f'<span style="color:{colors[s]};font-weight:600">{labels[s]}</span>  ' for s in ['current','A','B','C','E'])
    html=f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>Regime Layer2 五方案回测</title>
<style>body{{font-family:-apple-system,Segoe UI,sans-serif;margin:24px;color:#222}}
h1{{font-size:20px}}table{{border-collapse:collapse;margin-top:12px;font-size:13px}}
th,td{{border:1px solid #ddd;padding:6px 10px;text-align:right}}th{{background:#f5f5f5}}
td:first-child,th:first-child{{text-align:left}}.note{{color:#666;font-size:12px;margin-top:14px;line-height:1.6}}
.legend{{margin:10px 0}}</style></head><body>
<h1>Regime Layer2 —— 五方案回测对比（.day 全历史 + gbbq 前复权）</h1>
<div class="legend">{legend}</div>
{svg_str}
<table><tr><th>方案</th><th>窗口</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>空仓占比</th><th>均质池</th><th>换手率</th></tr>
{''.join(rows)}</table>
<div class="note">
数据：通达信本地 .day（全历史，沙箱挂载 D:\\new_tdx64）+ gbbq 权息前复权（decode_gbbq.py → all_xdxr.csv）；
基本面 fundamentals_broad.json（1438 只）。替代 backtest_weekly.py 的 sina 未复权日线（仅3000根，分红跳变污染动量）。<br>
策略：质量+动量周频（N=15，52周动量，ROE≥10%&正FCF质量门，行业≤35%，单边成本0.12%，锚定56周MA）。<br>
方案：当前=上证56周MA；A=中证全指56周MA；B=分市场段指数56周MA（创业板指/科创50/上证/深成指/北证50）；
C=内生（无外部regime）；E=上证长周期MA尾部风险开关（跌破强制空仓；本次测试120/150/200/250周及200周→半仓变体，见表格 E* 行）。<br>
空仓占比：C/E 因无日常大盘择时，该指标意义不同（C 几乎不空仓；E 仅暴跌期空仓）。指标仅回测统计，不构成投资建议。
</div></body></html>"""
    open(os.path.join(WORK,'regime_basis_backtest.html'),'w',encoding='utf-8').write(html)

# ---------------- 实时买仓清单(替代 backtest_weekly.current_candidates 的上证regime版) ----------------
def _seg_up(sym, indices, d):
    """段指数在 d 周是否站上56周MA; 返回 True/False/None(指数缺失或MA未就绪)。"""
    idx=indices.get(sym)
    if idx is None: return None
    ic=idx_close_on(idx,d); ma=idx_ma_on(idx,d,56)
    if ic is None or ma is None: return None
    return ic>=ma

_UNIV_CACHE = {}
def _get_universe(include_bj=True):
    """构建 Layer2 宇宙（进程内缓存，避免同一进程重复读取全部 .day）。"""
    if include_bj in _UNIV_CACHE:
        return _UNIV_CACHE[include_bj]
    u = build_universe_layer2(include_bj=include_bj)
    _UNIV_CACHE[include_bj] = u
    return u

def current_candidates(scheme='B', N=4, mom_window=52, val_window=260,
                       price_cap=300.0, today=None, cash=50000.0, expo_base=0.9,
                       include_bj=True):
    """实时买仓清单: 通达信 .day 全历史 + gbbq 前复权, regime 用 scheme。
    scheme: 'B'(分市场段指数,默认) / 'current'(上证) / 'A'(中证全指) / 'C'(内生) / 'E*'(尾部)。
    资金模型(默认): 5万账户 / 目标 N=4 仓 / 暴露0.9 / 100股手数;
      按可行性自动集中到 fewer/cheaper 仓位——仅"价格*100<=单仓预算"的票可整手,
      取 score 前 N 只; 若可行票不足 N, 则集中到更少仓位(每只给 可投/实际只数 预算)。
    返回 dict: signal_date, scheme, cash, n_target, investable, per_pos, regime_up,
               seg_indices, n_stocks, buy[](全合格候选, 含 selected 标记), selected[](实际建仓),
               observation[], bj_observe[]。
    """
    stocks, global_dates, global_pkeys, idx0 = _get_universe(include_bj=include_bj)
    indices={'sh000001':idx0}
    for sym in ['sh000985','sh000688','sz399006','sz399001','bj899050']:
        ix=build_index_weekly(sym)
        if ix: indices[sym]=ix
    # E 方案尾部门窗 + 部分降仓
    e_win=200; tail_expo=0.0
    if scheme.startswith('E'):
        m=re.match(r'E(\d+)', scheme)
        if m: e_win=int(m.group(1))
        tail_expo=0.45 if scheme.endswith('H') else 0.0
    fn=make_regime_fn(scheme, indices, e_window=e_win)
    signal_date = today or global_dates[-1]
    si = global_dates.index(signal_date) if signal_date in global_dates else len(global_dates)-1
    bd = global_dates[si]
    market_up = fn(None, bd) if scheme not in ('B','C') else True
    per_pos = cash*expo_base/N
    buy=[]; obs=[]; bj_observe=[]
    for code,s in stocks.items():
        ti=s['di'].get(bd)
        if ti is None: continue
        mm=mom_metrics(s['dates'], s['close'], ti, mom_window)
        if mm is None: continue
        mom12,ma12,price=mm
        if price>price_cap: continue
        ff=pt_fund(s['fund'], bd)
        qual_ok = (ff is not None) and (ff['roe_now']>=0.10) and (ff['fcfnp'] is not None and ff['fcfnp']>0)
        on_line = (price>ma12)
        mom_ok = (mom12>0)
        # 段 regime 判定(必须在 ff None 分支前算好, 否则 NameError)
        if scheme=='B':
            seg=seg_index_for(code); up=_seg_up(seg, indices, bd)
            regime_pass = (up is True)
            seg_label = seg
        elif scheme in ('current','A') or scheme.startswith('E'):
            regime_pass = market_up
            seg_label = ''
        else:  # C 内生
            regime_pass = True
            seg_label = ''
        if ff is None:
            # 无基本面(极少数北交所 DMSK 缺失): 仅动量+站线+段regime, 列观察(质量不可验证)
            if on_line and mom_ok and regime_pass:
                bj_observe.append(dict(code=code, name=s.get('name',code), price=price,
                                       mom=mom12, sind=s.get('sind',''),
                                       seg=(seg_label if scheme=='B' else ''),
                                       regime=('UP' if regime_pass else 'DOWN'),
                                       fail='无基本面(动量+段regime)'))
            continue
        rec=dict(code=code, name=s.get('name',code), price=price,
                 roe=ff['roe_now'], debt=ff['debt'], fcfnp=ff['fcfnp'], cv=ff['cv'],
                 mom=mom12, sind=s.get('sind',''),
                 seg=(seg_label if scheme=='B' else ''),
                 regime=('UP' if regime_pass else 'DOWN'))
        if scheme=='B' and not regime_pass:
            # 段regime压制: 质量过关也不买, 列观察(段DOWN)
            if qual_ok and on_line and mom_ok:
                rec['fail']='段regime DOWN'
                obs.append(rec)
            continue
        if qual_ok and on_line and mom_ok and regime_pass:
            buy.append(rec)
        elif qual_ok:
            rec['fail']=('未站线' if not on_line else ('动量负' if not mom_ok else 'regime DOWN'))
            obs.append(rec)
    # 打分(与回测一致): qscore 复合
    if buy:
        mom_rk=rank_normalize([r['mom'] for r in buy])
        roe_rk=rank_normalize([r['roe'] for r in buy])
        fcf_rk=rank_normalize([max(0.0,min(3.0,r['fcfnp'])) for r in buy])
        cv_rk=rank_normalize([r['cv'] for r in buy])
        debt_rk=rank_normalize([r['debt'] for r in buy])
        combo_q=0.5
        for i,r in enumerate(buy):
            qs=(roe_rk[i]+fcf_rk[i]+(1-cv_rk[i])+(1-debt_rk[i]))/4.0
            r['score']=round((1-combo_q)*qs+combo_q*mom_rk[i],4)
    # ---- 资金可行性集中(5万账户 / N=3-4仓 / 100股手数) ----
    # 单仓预算 per_pos = 可投/目标仓数; 仅"价格*100<=per_pos"的票可整手(可行性门槛, 排除买不起的);
    # 取 score 前 N 只可行票; 若可行票不足 N, 则集中到 fewer 仓位(每只给 可投/实际只数 预算)。
    investable = cash*expo_base
    per_pos = investable / N
    fea = [r for r in buy if r['price']*100 <= per_pos]
    fea_sorted = sorted(fea, key=lambda r:-r.get('score',0))
    pick = fea_sorted[:N]
    if pick and len(pick) < N:
        budget = investable / len(pick)          # 集中: 更少仓位, 单仓更大
    else:
        budget = per_pos
    sel=[]
    for r in pick:
        lots=int(budget // (r['price']*100)) * 100   # 整数百股
        if lots<=0: continue
        r['lots']=lots
        r['capital']=round(r['price']*lots,2)
        r['budget']=round(budget,2)
        r['selected']=True
        sel.append(r)
    selcodes={r['code'] for r in sel}
    for r in buy:
        if r['code'] not in selcodes:
            r['selected']=False; r['lots']=0
    obs.sort(key=lambda r:r.get('roe') or 0, reverse=True)
    return dict(signal_date=bd, scheme=scheme, regime_up=market_up,
                seg_indices={k:('OK' if k in indices else 'MISS') for k in ['sh000985','sh000688','sz399006','sz399001','bj899050']},
                n_stocks=len(stocks), cash=cash, expo_base=expo_base, n_target=N,
                investable=round(investable,2), per_pos=round(per_pos,2),
                buy=buy, selected=sel, observation=obs, bj_observe=bj_observe)

def format_live_report(res):
    """把 current_candidates 的结果渲染成可读文本(与 live B 输出一致)。"""
    L=[]
    L.append("="*82)
    L.append(f"实时买仓清单  signal={res['signal_date']}  scheme={res['scheme']}  段/全局regime_up={res['regime_up']}")
    L.append(f"账户={res['cash']:.0f}元  目标仓数N={res['n_target']}  暴露={res['expo_base']}  "
             f"可投={res['investable']:.0f}  单仓预算={res['per_pos']:.0f}  宇宙={res['n_stocks']}只")
    L.append(f"段指数: {res['seg_indices']}")
    sel=res['selected']
    L.append(f"▶ 实际建仓(可行性集中, {len(sel)} 仓, 合计 {sum(r['capital'] for r in sel):.0f}元):")
    L.append("-"*82)
    L.append(f"{'代码':<8}{'名称':<9}{'行业':<8}{'价':>8}{'ROE%':>7}{'FCF/N':>8}{'52wMOM%':>9}{'手':>5}{'金额':>9}")
    for r in sel:
        roe=(r['roe']*100 if r['roe'] is not None else 0.0)
        fcf=(r['fcfnp'] if r['fcfnp'] is not None else 0.0)
        L.append(f"{r['code']:<8}{r['name'][:7]:<9}{(r['sind'] or '')[:6]:<8}{r['price']:>8.2f}"
                 f"{roe:>6.1f}{fcf:>8.2f}{r['mom']*100:>8.1f}{r['lots']:>5}{r['capital']:>9.0f}")
    if not sel:
        L.append("  (无可行建仓: 合格候选均无法在单仓预算内整手, 或段regime全DOWN)")
    L.append("-"*82)
    buy=res['buy']
    L.append(f"合格买仓池(质量+动量+站线+段regime): {len(buy)} 只 (★=已选入建仓)")
    for r in sorted(buy, key=lambda r:-r.get('score',0))[:30]:
        roe=(r['roe']*100 if r['roe'] is not None else 0.0)
        fcf=(r['fcfnp'] if r['fcfnp'] is not None else 0.0)
        star='★' if r.get('selected') else ' '
        L.append(f" {star}{r['code']} {r['name'][:7]:<8}{(r['sind'] or '')[:6]:<7}价{r['price']:>7.2f} "
                 f"ROE{roe:>5.1f}% FCF/N{fcf:>6.2f} MOM{r['mom']*100:>6.1f}% 分{r.get('score',0):.2f} "
                 f"{'['+r['seg']+']' if r.get('seg') else ''}{r['regime']}")
    L.append("-"*82)
    L.append(f"观察池(质量过关但未站线/动量负/段DOWN, 取前20): {len(res['observation'])} 只")
    for r in res['observation'][:20]:
        roe=(r['roe']*100 if r['roe'] is not None else 0.0)
        L.append(f"  {r['code']} {r['name'][:8]} {(r['sind'] or '')[:6]} ROE={roe:.1f}% 未过:{r.get('fail','-')}")
    if res.get('bj_observe'):
        L.append("-"*82)
        L.append(f"北交所动量观察(无基本面, 仅动量+站线+段regime, 取前15): {len(res['bj_observe'])} 只")
        for r in res['bj_observe'][:15]:
            L.append(f"  {r['code']} {r['name'][:8]} 价={r['price']:.2f} 52wMOM={r['mom']*100:.1f}% 段={r['regime']}")
    L.append("="*82)
    return "\n".join(L)

def live_report(scheme='B', cash=50000.0, n_target=4):
    """打印并落盘实时买仓清单(默认 B 方案)。
    用法: python regime_layer2_backtest.py live [B|current|A|C|E200H] [cash] [N]"""
    res=current_candidates(scheme=scheme, cash=cash, N=n_target)
    txt=format_live_report(res)
    out=os.path.join(WORK, f"live_buy_list_{res['signal_date']}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(txt+"\n")
    print(txt)
    return res

if __name__=="__main__":
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='live':
        scheme=sys.argv[2] if len(sys.argv)>2 else 'B'
        cash=float(sys.argv[3]) if len(sys.argv)>3 else 50000.0
        N=int(sys.argv[4]) if len(sys.argv)>4 else 4
        live_report(scheme, cash, N)
    else:
        main()
