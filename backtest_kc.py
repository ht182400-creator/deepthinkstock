# backtest_kc.py  —— 科创板日线突破，多配置对比（regime窗口/出场均线/持仓上限）
import json, datetime, statistics, urllib.request, time

SRC='daily_kc.json'
INIT=20000; LOT=100
BUY_COST=0.0008; SELL_COST=0.0018
BRK=20; VOLW=20; TREND_MA=60; VOL_MULT=1.5

def http_get(url, timeout=25, retries=5):
    for i in range(retries):
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8','ignore')
        except Exception:
            time.sleep(0.4*(i+1))
    return None

def fetch_index(symbol='sh000688'):
    url=f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=2000'
    txt=http_get(url)
    if not txt: return {}
    try: return {b['day']:float(b['close']) for b in json.loads(txt)}
    except Exception: return {}

d=json.load(open(SRC)); meta=d['meta']; daily=d['daily']
print('池子:',meta.get('universe'),'合格',len(daily))

# 全局交易日
all_dates=set()
for bars in daily.values():
    if len(bars)<TREND_MA+5: continue
    all_dates.update(b['d'] for b in bars)
global_dates=sorted(all_dates); gidx={dt:i for i,dt in enumerate(global_dates)}

bars_map={}; entry_map={}; close_g={}; prefix_g={}; traded_latest={}
for code,bars in daily.items():
    n=len(bars)
    if n<TREND_MA+5: continue
    dates=[b['d'] for b in bars]; close=[b['c'] for b in bars]; high=[b['h'] for b in bars]; vol=[b['v'] for b in bars]
    pc=[0.0]*(n+1); pv=[0.0]*(n+1)
    for i in range(n): pc[i+1]=pc[i]+close[i]; pv[i+1]=pv[i]+vol[i]
    bm={dates[i]:bars[i] for i in range(n)}
    sm={}
    for i in range(n):
        entry=False; vr=0.0
        if i>=TREND_MA:
            ma60=(pc[i+1]-pc[i+1-TREND_MA])/TREND_MA
            if i>=VOLW:
                vma=(pv[i+1]-pv[i+1-VOLW])/VOLW
                if i>=BRK and vma>0:
                    hh=max(high[i-BRK:i]); vr=vol[i]/vma
                    if close[i]>hh and vr>=VOL_MULT and close[i]>ma60: entry=True
        sm[dates[i]]={'entry':entry,'vol_ratio':vr}
    cg=[0.0]*len(global_dates); last=None
    for i,dt in enumerate(dates): cg[gidx[dt]]=close[i]
    for i in range(len(cg)):
        if cg[i]==0 and last is not None: cg[i]=last
        elif cg[i]!=0: last=cg[i]
    pre=[0.0]*(len(cg)+1)
    for i,v in enumerate(cg): pre[i+1]=pre[i]+v
    bars_map[code]=bm; entry_map[code]=sm; close_g[code]=cg; prefix_g[code]=pre
    traded_latest[code]=close[-1]

eligible=[(c,entry_map[c]) for c in entry_map]
print('合格股',len(eligible),'交易日',len(global_dates),global_dates[0],'->',global_dates[-1])

# 价格分布（回答：2万能否撑3-4只）
print('\n=== 合格股价格分布(最新收盘) ===')
for t in [30,40,50,60,80,100,150]:
    print(f'  ≤{t}元: {sum(1 for v in traded_latest.values() if v<=t)} 只')

idx=fetch_index('sh000688')

def simulate(reg_win, exit_ma, maxpos, use_regime):
    idx_arr=[]; last=None
    for dt in global_dates:
        c=idx.get(dt); c=c if c is not None else last
        if c is not None: last=c
        idx_arr.append(c if c is not None else 0)
    pre_i=[0.0]*(len(idx_arr)+1)
    for i,v in enumerate(idx_arr): pre_i[i+1]=pre_i[i]+v
    regime_hold=[True]*len(global_dates)
    if use_regime:
        for i in range(reg_win, len(global_dates)):
            ma=(pre_i[i+1]-pre_i[i+1-reg_win])/reg_win
            regime_hold[i]= idx_arr[i]>ma
    positions={}; cash=INIT; buy_cands=[]; sell_list=[]; last_close={}; values=[]; trades=[]; traded=set()
    for gi,dt in enumerate(global_dates):
        rh=regime_hold[gi]
        if not rh:
            for code in list(positions):
                b=bars_map[code].get(dt)
                if b:
                    p=b['o']; sh=positions[code]['shares']; cash+=sh*p*(1-SELL_COST)
                    trades.append({'ret':p/positions[code]['entry_price']-1,'hold':gi-positions[code]['gi']})
                    del positions[code]
            sell_list=[]; buy_cands=[]
        else:
            for code in sell_list:
                if code in positions:
                    b=bars_map[code].get(dt)
                    if b:
                        p=b['o']; sh=positions[code]['shares']; cash+=sh*p*(1-SELL_COST)
                        trades.append({'ret':p/positions[code]['entry_price']-1,'hold':gi-positions[code]['gi']})
                        del positions[code]
            sell_list=[]
            for vr,code in sorted(buy_cands, reverse=True):
                if len(positions)>=maxpos: break
                if code in positions: continue
                b=bars_map[code].get(dt)
                if not b: continue
                price=b['o']; slots=maxpos-len(positions); alloc=cash/slots
                sh=int(alloc//(price*LOT))*LOT
                if sh<LOT: sh=int(cash//(price*LOT))*LOT
                if sh<LOT: continue
                cost=sh*price*(1+BUY_COST)
                if cost>cash: sh=int(cash//(price*(1+BUY_COST))//LOT)*LOT
                if sh<LOT: continue
                cost=sh*price*(1+BUY_COST); cash-=cost
                positions[code]={'shares':sh,'entry_price':price,'gi':gi}; traded.add(code)
            buy_cands=[]
        val=cash
        for code,pos in positions.items():
            b=bars_map[code].get(dt)
            if b: last_close[code]=b['c']
            val+=pos['shares']*last_close.get(code,0)
        values.append(val)
        for code,sm in eligible:
            sig=sm.get(dt)
            if sig is None: continue
            exit_=False
            if gi>=exit_ma-1:
                ma=(prefix_g[code][gi+1]-prefix_g[code][gi+1-exit_ma])/exit_ma
                if close_g[code][gi]<ma: exit_=True
            if sig['entry'] and code not in positions and len(positions)<maxpos and rh:
                buy_cands.append((sig['vol_ratio'],code))
            if exit_ and code in positions:
                sell_list.append(code)
    return values, trades, traded

def metrics(values, trades, label):
    final=values[-1]; total=final/INIT-1
    d0=datetime.date.fromisoformat(global_dates[0]); d1=datetime.date.fromisoformat(global_dates[-1])
    years=(d1-d0).days/365.25; cagr=(final/INIT)**(1/years)-1 if final>0 else -1
    peak=values[0]; mdd=0.0
    for v in values:
        if v>peak: peak=v
        dd=v/peak-1
        if dd<mdd: mdd=dd
    wk=[]; last=len(values)-1
    for k in range(1, last//5 + 1): wk.append(values[k*5]/values[(k-1)*5]-1)
    if len(values)>1: wk.append(values[-1]/values[(last//5)*5]-1)
    wk_mean=sum(wk)/len(wk) if wk else 0
    n=len(trades); wins=[t for t in trades if t['ret']>0]; losses=[t for t in trades if t['ret']<=0]
    wr=len(wins)/n if n else 0
    aw=sum(t['ret'] for t in wins)/len(wins) if wins else 0
    al=sum(t['ret'] for t in losses)/len(losses) if losses else 0
    gw=sum(t['ret'] for t in wins); gl=abs(sum(t['ret'] for t in losses)); pf=gw/gl if gl>0 else float('inf')
    ah=sum(t['hold'] for t in trades)/n if n else 0
    dr=[values[i]/values[i-1]-1 for i in range(1,len(values)) if values[i-1]>0]
    vol=statistics.pstdev(dr)*(252**0.5) if len(dr)>1 else 0
    sharpe=cagr/vol if vol>0 else 0
    return {'label':label,'final':round(final,2),'cagr':round(cagr,4),'mdd':round(mdd,4),
            'vol_ann':round(vol,4),'sharpe':round(sharpe,3),'wk_mean':round(wk_mean,4),
            'n_trades':n,'win_rate':round(wr,4),'avg_win':round(aw,4),'avg_loss':round(al,4),
            'profit_factor':round(pf,3) if pf!=float('inf') else 'inf','avg_hold':round(ah,1)}

configs=[
 ('B 无regime',      dict(reg_win=273,exit_ma=10,maxpos=2,use_regime=False)),
 ('A regime13m',     dict(reg_win=273,exit_ma=10,maxpos=2,use_regime=True)),
 ('C1 快regime+紧出场',dict(reg_win=200,exit_ma=7, maxpos=2,use_regime=True)),
 ('C3 同上+4只',      dict(reg_win=200,exit_ma=7, maxpos=4,use_regime=True)),
]
results={}
for name,cfg in configs:
    v,t,tr=simulate(**cfg)
    m=metrics(v,t,name); m['n_stocks']=len(tr)
    results[name]=m
    print(f"\n=== {name} ===  traded_stocks={len(tr)}")
    print(json.dumps(m,ensure_ascii=False))

# 对比HTML
colors={'B 无regime':'#c0392b','A regime13m':'#2980b9','C1 快regime+紧出场':'#27ae60','C3 同上+4只':'#e67e22'}
def svg_multi(curves):
    W,H=860,360;
    allv=[v for _,v in curves]; mx=max(max(allv) for allv in allv_l if False) if False else max(max(v) for _,v in curves)
    mn=min(min(v) for _,v in curves); rng=(mx-mn) or 1
    def pts(vals,color):
        n=len(vals); pl=[]
        for i,vv in enumerate(vals):
            x=40+(i/(n-1) if n>1 else 0)*(W-60); y=(H-30)-((vv-mn)/rng)*(H-60); pl.append(f'{x:.1f},{y:.1f}')
        return f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(pl)}"/>'
    svg='<svg width="%d" height="%d"><line x1="40" y1="%d" x2="%d" y2="%d" stroke="#888"/>'%(W,H,H-30,W-20,H-30)
    ty=14
    for name,v in curves:
        svg+=pts(v,colors[name])+f'<text x="44" y="{ty}" fill="{colors[name]}">{name}</text>'; ty+=16
    return svg+'</svg>'

# 重跑取净值序列用于画图
vals={}
for name,cfg in configs:
    v,t,tr=simulate(**cfg); vals[name]=v
curves=[(name,vals[name]) for name in colors]
cmp_rows=''.join(f'<tr><td>{k}</td>'+''.join(f'<td>{results[n][k]}</td>' for n in colors)+'</tr>' for k in ['final','cagr','mdd','vol_ann','sharpe','wk_mean','n_trades','win_rate','profit_factor','n_stocks'])
hdr='<tr><th>指标</th>'+''.join(f'<th>{n}</th>' for n in colors)+'</tr>'
open('report_kc_multicmp.html','w').write(f'''<html><head><meta charset="utf-8"><title>科创板日线突破 多配置对比</title>
<style>body{{font-family:sans-serif;margin:24px}} table{{border-collapse:collapse}} td,th{{border:1px solid #ccc;padding:4px 8px}} h2{{color:#c0392b}}</style></head>
<body><h2>科创板日线突破：多配置对比（2万初始, 100股手数, 盈利复投）</h2>
{svg_multi(curves)}
<table>{hdr}{cmp_rows}</table>
<p style="color:#888">B=无regime; A=科创50 13月线regime; C1=A的快regime(200日)+紧出场(7日线),仍≤2只; C3=同C1但持仓放宽到4只(仅能买≤~50元便宜票)。含生存偏差。仅供参考，不构成投资建议。</p></body></html>''')
print('\nSAVED report_kc_multicmp.html')
