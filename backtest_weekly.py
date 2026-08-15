#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_weekly.py —— 质量+动量+regime 框架的 周频 vs 月频 对比（宽池 沪深+科创+创业）。
日线(daily_broad.json)聚合成 周线/月线；基本面(fundamentals_broad.json)做 qscore 质量门(ROE>=10%软底+正FCF+动量确认+站均线)。
regime 指数=上证(sh000001) 周/月线 MA（中证1000 周期性太强会长期空仓，故用 broad market）。时点正确：NOTICE_DATE<=bar日期 才可用。
输出：周/月多配置的年化/回撤/波动/夏普/换手，找最优方案。
"""
import json, math, os, datetime, urllib.request, time

WORK = os.path.dirname(os.path.abspath(__file__))
RF = 0.02
FIN_KW = ["银行", "证券", "保险", "信托", "期货", "租赁", "财富", "金融", "基金"]
INIT = 1.0

def http_get(url, timeout=25, retries=5):
    for i in range(retries):
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8','ignore')
        except Exception:
            time.sleep(0.4*(i+1))
    return None

def fetch_index_daily(symbol='sh000852'):
    url=f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=3000'
    txt=http_get(url)
    if not txt: return []
    try: return [{'d':b['day'],'o':float(b['open']),'h':float(b['high']),
                  'l':float(b['low']),'c':float(b['close']),'v':int(b['volume'])}
                 for b in json.loads(txt)]
    except Exception: return []

# ---------- 日线 → 周线/月线 聚合 ----------
def aggregate(daily_bars, freq):
    # daily_bars: list of {d,o,h,l,c,v}; 返回 sorted list of {date,pkey,open,high,low,close,vol}
    # pkey: 月=YYYY-MM；周=ISO(y,w) 字符串。用于与指数周期键对齐。
    if freq == 'M':
        buckets = {}
        for b in daily_bars:
            key = b['d'][:7]
            if key not in buckets:
                buckets[key] = {'date': b['d'], 'pkey': key, 'open': b['o'], 'high': b['h'], 'low': b['l'], 'close': b['c'], 'vol': b['v']}
            else:
                m = buckets[key]
                m['high'] = max(m['high'], b['h']); m['low'] = min(m['low'], b['l'])
                m['close'] = b['c']; m['vol'] += b['v']; m['date'] = b['d']
        return [buckets[k] for k in sorted(buckets.keys())]
    else:  # 'W' ISO 周
        buckets = {}
        for b in daily_bars:
            y, w, _ = datetime.date.fromisoformat(b['d']).isocalendar()
            key = f"{y}-{w:02d}"
            if key not in buckets:
                buckets[key] = {'date': b['d'], 'pkey': key, 'open': b['o'], 'high': b['h'], 'low': b['l'], 'close': b['c'], 'vol': b['v']}
            else:
                m = buckets[key]
                m['high'] = max(m['high'], b['h']); m['low'] = min(m['low'], b['l'])
                m['close'] = b['c']; m['vol'] += b['v']
                if b['d'] > m['date']: m['date'] = b['d']
        return [buckets[k] for k in sorted(buckets.keys())]

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
    """返回与 vals 等长的 MA(n) 列表；前 n-1 个为 None。"""
    out=[None]*len(vals); s=0.0
    for i,v in enumerate(vals):
        s+=v
        if i>=n: s-=vals[i-n]
        if i>=n-1: out[i]=s/n
    return out

def compute_obv(dates, close_list, vol_list):
    """周线 OBV（能量潮）：价升加量、价贬减量，捕捉主力资金累计流向。返回与 dates 等长。"""
    obv=[0.0]*len(dates)
    for i in range(1,len(dates)):
        if close_list[i]>close_list[i-1]:   obv[i]=obv[i-1]+vol_list[i]
        elif close_list[i]<close_list[i-1]: obv[i]=obv[i-1]-vol_list[i]
        else:                               obv[i]=obv[i-1]
    return obv

def annualized(total_ret, periods, freq):
    py = 52 if freq=='W' else 12
    return (1+total_ret)**(py/periods)-1 if periods>0 else 0.0

def is_financial(industry):
    return any(k in (industry or "") for k in FIN_KW)

def pct_rank_local(value, hist):
    if not hist: return 50.0
    return 100.0*sum(1 for h in hist if h<=value)/len(hist)

def build_universe(freq):
    broad=json.load(open(os.path.join(WORK,'daily_broad.json'),encoding='utf-8'))
    fund=json.load(open(os.path.join(WORK,'fundamentals_broad.json'),encoding='utf-8'))
    # 指数（统一时间轴）；regime 用 broad market 上证，与 prior 月频框架一致
    idx_d=fetch_index_daily('sh000001')
    idx_ag=aggregate(idx_d,freq)
    idx_dates=[b['date'] for b in idx_ag]
    idx_pkeys=[b['pkey'] for b in idx_ag]
    idx_close={b['date']:b['close'] for b in idx_ag}
    idx_sorted=sorted(idx_close.keys())
    # 每只股票按周期键(pkey)向前填充对齐到指数时间轴（消除月末日期碎片化）
    stocks={}
    for code,bars in broad['daily'].items():
        ag=aggregate(bars,freq)
        if len(ag)<60: continue
        spk={b['pkey']:b['close'] for b in ag}
        svk={b['pkey']:b['vol'] for b in ag}
        sdates=[]; sclose={}; svol={}; di={}
        last=None; lastv=None
        for i,pk in enumerate(idx_pkeys):
            c=spk.get(pk)
            if c is not None: last=c
            v=svk.get(pk)
            if v is not None: lastv=v
            if last is None: continue
            sdates.append(idx_dates[i]); sclose[idx_dates[i]]=last
            if lastv is not None: svol[idx_dates[i]]=lastv
            di[idx_dates[i]]=len(sdates)-1
        if len(sdates)<60: continue
        # 量能因子：OBV（能量潮）积累 + 26周量MA + OBV的26周MA（蓄势线）
        vols=[svol[dd] for dd in sdates]
        cls=[sclose[dd] for dd in sdates]
        obv=compute_obv(sdates, cls, vols)
        vma=ma_series(vols, 26)
        obvma=ma_series(obv, 26)
        sind=fund.get(code,{}).get('industry','') or ''
        stocks[code]={'dates':sdates,'close':sclose,'sind':sind,'fund':fund.get(code,{}).get('annual',[]),
                      'di':di,'vol':svol,
                      'obv':{dd:obv[i] for i,dd in enumerate(sdates)},
                      'vma':{dd:vma[i] for i,dd in enumerate(sdates)},
                      'obvma':{dd:obvma[i] for i,dd in enumerate(sdates)}}
    return stocks, idx_close, idx_sorted

def idx_value_on(idx_close, idx_sorted, date):
    # 返回不晚于 date 的最新指数收盘（forward-fill）
    lo,hi=0,len(idx_sorted)-1; ans=None
    while lo<=hi:
        mid=(lo+hi)//2
        if idx_sorted[mid]<=date: ans=idx_sorted[mid]; lo=mid+1
        else: hi=mid-1
    return idx_close[ans] if ans else None

# ---------- 模块级时点基本面 / 动量 辅助（回测与买仓清单共用）----------
def pt_fund(annual, bar_date):
    avail=[r for r in annual if r.get('notice') and r['notice']<=bar_date
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
    # cv=历史ROE波动/均值；均值<=0（历史平均亏损）视为高不确定 → 罚分 CV=3.0；CV 恒>=0
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

def run_backtest(stocks, idx_close, idx_sorted, freq, N=15, mom_window=52, val_window=260,
                 regime_ma=56, regime_mode="binary", score_mode="qscore", combo_q=0.5,
                 ind_cap=0.35, cost_per_side=0.0012, warmup=60, start_date=None, end_date=None,
                 price_cap=300.0, vol_window=26, vol_weight=0.0, vol_gate=False):
    # 预建每只股票的日期索引与收盘序列
    meta={}
    for code,s in stocks.items():
        d=s['dates']; c=s['close']
        meta[code]={'d':d,'c':c,'sind':s['sind'],'fund':s['fund'],
                    'di':{d[i]:i for i in range(len(d))},
                    'v':s['vol'],'obv':s['obv'],'vma':s['vma'],'obvma':s['obvma']}

    # 全局 bar 序列：直接用指数统一时间轴（已与每只股票前向填充对齐，避免碎片化）
    all_dates=list(idx_sorted)
    # 限制起止
    t_start=warmup
    if start_date:
        for i in range(warmup, len(all_dates)):
            if all_dates[i]>=start_date: t_start=i; break
    t_end=len(all_dates)-1
    if end_date:
        for i in range(t_start, len(all_dates)):
            if all_dates[i]>end_date: t_end=i-1; break

    equity=[1.0]; rets=[]; held={}; prev_w=None; turnover_l=[]
    n_pool=[]
    for t in range(t_start, t_end):
        bd=all_dates[t]
        ic=idx_value_on(idx_close, idx_sorted, bd)
        # 指数均线：回看窗必须覆盖 regime_ma（周频=56周；不能用 mom_window，否则周频只剩53点 → idx_ma=None → 永远空仓）
        icl=[idx_value_on(idx_close, idx_sorted, all_dates[i]) for i in range(max(0,t-regime_ma+1), t+1)]
        icl=[x for x in icl if x is not None]
        idx_ma=sum(icl)/len(icl) if len(icl)>=regime_ma else None
        market_up=(idx_ma is not None) and (ic is not None) and (ic>=idx_ma)

        # 退出
        for code in list(held):
            ti=meta[code]['di'].get(bd)
            if ti is None:
                # 该股票此周无数据，保留（不强制退出）
                continue
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

        if regime_mode=="binary" and not market_up:
            held={}

        # 候选
        cands={}; codes=[]; volratio={}
        for code in stocks:
            ti=meta[code]['di'].get(bd)
            if ti is None: continue
            mm=mom_metrics(meta[code]['d'], meta[code]['c'], ti, mom_window)
            if mm is None: continue
            mom12,ma12,price=mm
            if price>price_cap: continue
            if not (price>ma12): continue
            ff=pt_fund(meta[code]['fund'], bd)
            if ff is None: continue
            if is_financial(meta[code]['sind']): continue
            # 量能因子：OBV 蓄势线(obv/obvma>1=资金流入) + 量能扩张(vol/vma>1=活跃放量)
            obv_ratio=1.0; vol_expand=1.0
            if vol_weight>0 or vol_gate:
                vn=meta[code]['v'].get(bd); vm=meta[code]['vma'].get(bd)
                ob=meta[code]['obv'].get(bd); obm=meta[code]['obvma'].get(bd)
                obv_ratio=(ob/obm) if (obm not in (None,0)) else 1.0
                vol_expand=(vn/vm) if (vm not in (None,0)) else 1.0
                if vol_gate and (vol_expand<1.0 or obv_ratio<1.0):
                    continue
                volratio[code]=obv_ratio
            if score_mode=="qscore":
                if ff["roe_now"]<0.10: continue
                if ff["fcfnp"] is None or ff["fcfnp"]<0: continue
                if not (mom12>0): continue
                cands[code]=(price, ff, mom12); codes.append(code)
            elif score_mode=="combo":
                if ff["roe_now"]<0.10: continue
                if ff["fcfnp"] is None or ff["fcfnp"]<0: continue
                if not (mom12>0): continue
                cands[code]=(price, ff, mom12); codes.append(code)
            elif score_mode=="momentum":
                if not (mom12>0): continue
                cands[code]=(price, mom12); codes.append(code)
        if codes:
            if score_mode in ("qscore","combo"):
                roe_rk=rank_normalize([cands[c][1]["roe_now"] for c in codes])
                fcf_rk=rank_normalize([cands[c][1]["fcfnp"] for c in codes])
                cv_rk=rank_normalize([cands[c][1]["cv"] for c in codes])
                debt_rk=rank_normalize([cands[c][1]["debt"] for c in codes])
                mom_rk=rank_normalize([cands[c][2] for c in codes])
                for i,code in enumerate(codes):
                    qs=(roe_rk[i]+fcf_rk[i]+(1-cv_rk[i])+(1-debt_rk[i]))/4.0
                    s=(1-combo_q)*qs+combo_q*mom_rk[i]
                    cands[code]=(cands[code][0], s)
            else:
                momL=[cands[c][1] for c in codes]
                mom_rk=rank_normalize(momL)
                for i,code in enumerate(codes):
                    cands[code]=(cands[code][0], mom_rk[i])
        # 量能因子叠加（OBV 蓄势排名），与质量/动量复合
        if vol_weight>0 and codes:
            vol_rk=rank_normalize([volratio.get(c,1.0) for c in codes])
            for i,code in enumerate(codes):
                old=cands[code][1]
                cands[code]=(cands[code][0], (1-vol_weight)*old + vol_weight*vol_rk[i])
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

        expo=0.9 if (market_up or regime_mode!="binary") else 0.0
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

    periods=len(rets)
    total=equity[-1]-1
    ann=annualized(total, periods, freq)
    vol_a=stdev(rets)*math.sqrt(52 if freq=='W' else 12)
    sharpe=(ann-RF)/vol_a if vol_a>0 else 0.0
    mdd=max_drawdown(equity)
    avg_pool=sum(n_pool)/len(n_pool) if n_pool else 0
    max_pool=max(n_pool) if n_pool else 0
    avg_to=sum(turnover_l)/len(turnover_l) if turnover_l else 0
    return dict(freq=freq, periods=periods, total_return=total, annualized=ann,
                vol_annual=vol_a, sharpe=sharpe, max_drawdown=mdd,
                avg_quality_pool=avg_pool, max_quality_pool=max_pool, avg_turnover=avg_to, equity_curve=equity)

def current_candidates(freq, mom_window=52, val_window=260, regime_ma=56, price_cap=300.0,
                       today=None, score_mode="qscore", vol_window=26, vol_weight=0.0, vol_gate=False):
    """【已废弃 DEPRECATED —— 勿在新流程中调用】

    此版本使用 sina 未复权日线(仅 ~3000 根, 分红跳变污染 52 周动量) + 上证单一 56 周 MA 做 regime,
    存在两大缺陷: (1) 未复权导致除权日动量失真; (2) "以偏带全"——用上证裁决所有股票满/空仓。

    ✅ 替代实现: regime_layer2_backtest.current_candidates(scheme='B')
       - 数据: 通达信本地 .day 全历史 + gbbq 权息前复权(除权日无跳变)
       - regime: B 方案(分市场段指数 56 周 MA, 创业板指/科创50/上证/深成指/北证50 各自裁决)
       - 资金模型: 5万账户 / 3-4仓 / 100股手数, 按可行性自动集中

    返回结构同旧版(signal_date, regime_up, idx_now, idx_ma, candidates, observation), 仅维持兼容。
    """
    import warnings
    warnings.warn(
        "backtest_weekly.current_candidates 已废弃: 使用 sina 未复权日线(仅3000根,分红跳变污染动量)"
        " + 上证单一regime。请改用 regime_layer2_backtest.current_candidates(scheme='B')"
        " (.day全历史+gbbq前复权+分市场B方案+5万/3-4仓可行性集中)。",
        DeprecationWarning, stacklevel=2)
    stocks, idx_close, idx_sorted = build_universe(freq)
    signal_date = today or idx_sorted[-1]
    # regime：上证 regime_ma 均线
    icl=[idx_value_on(idx_close, idx_sorted, d) for d in idx_sorted if d<=signal_date]
    icl=[x for x in icl if x is not None]
    idx_now = idx_value_on(idx_close, idx_sorted, signal_date)
    idx_ma = sum(icl[-regime_ma:])/regime_ma if len(icl)>=regime_ma else None
    regime_up = (idx_ma is not None) and (idx_now is not None) and (idx_now>=idx_ma)
    buy=[]; obs=[]; volratio={}
    for code,s in stocks.items():
        ti=s['di'].get(signal_date)
        if ti is None: continue
        mm=mom_metrics(s['dates'], s['close'], ti, mom_window)
        if mm is None: continue
        mom12,ma12,price=mm
        if price>price_cap: continue
        ff=pt_fund(s['fund'], signal_date)
        if ff is None: continue
        if is_financial(s['sind']): continue
        # 量能：OBV 蓄势 + 量能扩张
        obv_ratio=1.0; vol_expand=1.0
        if vol_weight>0 or vol_gate:
            vn=s['vol'].get(signal_date); vm=s['vma'].get(signal_date)
            ob=s['obv'].get(signal_date); obm=s['obvma'].get(signal_date)
            obv_ratio=(ob/obm) if (obm not in (None,0)) else 1.0
            vol_expand=(vn/vm) if (vm not in (None,0)) else 1.0
            if vol_gate and (vol_expand<1.0 or obv_ratio<1.0):
                continue
            volratio[code]=obv_ratio
        qual_ok = (ff['roe_now']>=0.10) and (ff['fcfnp'] is not None and ff['fcfnp']>0)
        on_line = (price>ma12)
        mom_ok = (mom12>0)
        rec=dict(code=code, price=price, roe=ff['roe_now'], debt=ff['debt'],
                 fcfnp=ff['fcfnp'], cv=ff['cv'], mom=mom12, sind=s['sind'])
        if score_mode=="momentum":
            # 高弹性：弃质量门，仅要求 站线 + 动量正
            if on_line and mom_ok:
                buy.append(rec)
        else:
            if qual_ok and on_line and mom_ok:
                buy.append(rec)
            elif qual_ok:
                rec['fail']=('未站线' if not on_line else '动量负')
                obs.append(rec)
    # 排名：对 buy 池做 rank-normalize（与回测引擎一致）
    if buy:
        mom_rk=rank_normalize([r['mom'] for r in buy])
        if score_mode=="momentum":
            # 高弹性版：纯动量排序（弃质量权重）
            for i,r in enumerate(buy):
                r['score']=round(mom_rk[i],4)
        else:
            roe_rk=rank_normalize([r['roe'] for r in buy])
            fcf_rk=rank_normalize([max(0.0,min(3.0,r['fcfnp'])) for r in buy])
            cv_rk=rank_normalize([r['cv'] for r in buy])
            debt_rk=rank_normalize([r['debt'] for r in buy])
            combo_q=0.5
            for i,r in enumerate(buy):
                qs=(roe_rk[i]+fcf_rk[i]+(1-cv_rk[i])+(1-debt_rk[i]))/4.0
                r['score']=round((1-combo_q)*qs+combo_q*mom_rk[i],4)
    # 量能因子叠加（OBV 蓄势排名）
    if vol_weight>0 and buy:
        vr=[volratio.get(r['code'],1.0) for r in buy]
        vol_rk=rank_normalize(vr)
        for i,r in enumerate(buy):
            r['score']=round((1-vol_weight)*r['score']+vol_weight*vol_rk[i],4)
    # 资金可行性：3万÷4≈7500/仓，100股手数 → 单价≤75 才可整手建仓
    for r in buy:
        r['feasible']=(r['price']*100 <= 7500.0)
        r['lots']=int(7500//(r['price']*100)) if r['feasible'] else 0
    # 可行优先，再按打分；观察池按 ROE 降序
    buy.sort(key=lambda r:(r['feasible'], r.get('score',0)), reverse=True)
    obs.sort(key=lambda r:r.get('roe',0), reverse=True)
    return dict(signal_date=signal_date, regime_up=regime_up, idx_now=idx_now, idx_ma=idx_ma,
                freq=freq, buy=buy, observation=obs)

def main():
    import sys
    freqs = sys.argv[1].split(',') if len(sys.argv)>1 else ['M','W']
    print("聚合宽池日线 →", freqs, "...")
    data={}
    for fq in freqs:
        stocks, idx_close, idx_sorted = build_universe(fq)
        data[fq]=(stocks, idx_close, idx_sorted)
        print(f"  {fq}: 股票数={len(stocks)} 指数周/月数={len(idx_sorted)}")
    windows=[("2014-01","2026-07","2014-26"),("2018-01","2026-07","2018-26")]
    results={}
    print(f"\n{'配置':<34}{'年化':>8}{'回撤':>9}{'波动':>8}{'夏普':>7}{'均池':>7}{'换手':>8}")
    print("-"*81)
    for fq in freqs:
        stocks, idx_close, idx_sorted = data[fq]
        if fq=='M':
            mom_w, val_w, rma = 12, 60, 13
        else:
            mom_w, val_w, rma = 52, 260, 56
        # 对比 4 种配置：qscore+regime / qscore 无regime / momentum+regime / combo+regime
        configs=[
            ("qscore",   "binary", "qscore+regime"),
            ("qscore",   "none",   "qscore 无regime"),
            ("momentum", "binary", "momentum+regime"),
            ("combo",    "binary", "combo+regime"),
        ]
        for (smode, rmode, tag) in configs:
            for (sd,ed,lbl) in windows:
                cfg=dict(N=15, mom_window=mom_w, val_window=val_w, regime_ma=rma,
                         regime_mode=rmode, score_mode=smode, combo_q=0.5,
                         cost_per_side=0.0012, warmup=rma+5, start_date=sd, end_date=ed)
                r=run_backtest(stocks, idx_close, idx_sorted, fq, **cfg)
                key=f"{fq}_{smode}_{rmode}_{lbl.replace('-','')}"
                results[key]=r
                print(f"{fq} {tag:<18}{lbl:<12}{r['annualized']*100:>7.1f}%{r['max_drawdown']*100:>8.1f}%"
                      f"{r['vol_annual']*100:>7.1f}%{r['sharpe']:>7.2f}{r['avg_quality_pool']:>7.1f}{r['max_quality_pool']:>6}{r['avg_turnover']*100:>7.2f}%")
    json.dump({k:{kk:vv for kk,vv in v.items() if kk!='equity_curve'} for k,v in results.items()},
              open(os.path.join(WORK,'results_weekly.json'),'w',encoding='utf-8'), ensure_ascii=False, indent=1)
    print("\nwritten -> results_weekly.json")

if __name__=="__main__":
    main()
