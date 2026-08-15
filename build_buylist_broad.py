#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_buylist_broad.py —— 用周频质量+动量+regime 框架，产出 3万 可执行建仓清单(宽池 沪深+科创+创业)。
- 框架：backtest_weekly.current_candidates('W') 给出 截至最新 的合格候选 + regime 状态。
- 资金约束：3万÷4仓≈7500/仓；100股手数 → 单价≤75 才可整手建仓(feasible)。
- 给出：regime 门控与翻多触发位、条件4股票组合、完整可行候选排名、观察池、退出纪律、操作节奏。
- 名称：fundamentals_broad 缺名的代码从 Sina 实时接口补全(带 Referer)。
"""
import json, os, urllib.request, time
import backtest_weekly as B

WORK = os.path.dirname(os.path.abspath(__file__))
CAPITAL = 30000.0
PER_POS = CAPITAL / 4.0          # 7500
PRICE_CAP_FEASIBLE = PER_POS/100.0  # 75.0

def fetch_names(codes):
    """codes: list of 'sh600186' 前缀字符串；返回 {code6: name}。失败返回空。带重试+小批量。"""
    out={}
    for i in range(0,len(codes),80):
        batch=codes[i:i+80]
        url='https://hq.sinajs.cn/list='+','.join(batch)
        for attempt in range(3):
            try:
                req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'})
                txt=urllib.request.urlopen(req,timeout=20).read().decode('gbk','ignore')
                got=0
                for line in txt.strip().split('\n'):
                    if '=' not in line: continue
                    key,val=line.split('=',1)
                    pfx=key.replace('var hq_str_','').replace('hq_str_','')  # 形如 sz002484
                    parts=val.strip('"').split(',')
                    if parts and parts[0]:
                        out[pfx]=parts[0]; got+=1
                if got>0: break
            except Exception:
                time.sleep(0.6*(attempt+1))
    return out

def main():
    import sys
    MODE = sys.argv[1] if len(sys.argv)>1 else 'qscore'   # 'qscore' 或 'momentum'
    freq='W'
    res = B.current_candidates(freq, mom_window=52, val_window=260, regime_ma=56, price_cap=300.0,
                               score_mode=MODE)
    fund = json.load(open(os.path.join(WORK,'fundamentals_broad.json'),encoding='utf-8'))

    # 补全名称
    need=[r['code'] for r in res['buy']+res['observation'] if not fund.get(r['code'],{}).get('name')]
    prefix={c:('sh' if c.startswith(('6','9')) else 'sz')+c for c in need}
    names=fetch_names(list(prefix.values()))
    name_map={c:names.get(prefix[c],'') for c in need}
    def gname(code):
        return fund.get(code,{}).get('name') or name_map.get(code) or code

    # 组装候选行
    def row(r):
        return dict(code=r['code'], name=gname(r['code']), sind=r.get('sind',''),
                    price=round(r['price'],2), roe=round(r['roe']*100,1), debt=round(r['debt']*100,1),
                    fcfnp=round(r['fcfnp'],2), cv=round(r['cv'],2), mom=round(r['mom']*100,1),
                    score=round(r.get('score',0),4), feasible=r.get('feasible',False),
                    lots=r.get('lots',0))
    buy=[row(r) for r in res['buy']]
    obs=[row(r) for r in res['observation']]

    feasible=[b for b in buy if b['feasible']]
    # 选前4可行 → 等权约7500/仓，取整百股
    picks=[]
    deployed=0.0
    for b in feasible[:4]:
        lot=b['lots']
        amt=lot*b['price']*100
        picks.append(dict(code=b['code'],name=b['name'],sind=b['sind'],price=b['price'],
                          lots=lot,amount=round(amt,0),weight=round(amt/CAPITAL,4),
                          roe=b['roe'],debt=b['debt'],mom=b['mom'],score=b['score']))
        deployed+=amt
    cash=round(CAPITAL-deployed,0)

    # 回测证据（results_weekly.json）
    try:
        ev=json.load(open(os.path.join(WORK,'results_weekly.json'),encoding='utf-8'))
    except Exception:
        ev={}

    data=dict(signal_date=res['signal_date'], regime_up=res['regime_up'],
              idx_now=res['idx_now'], idx_ma=res['idx_ma'],
              regime_trigger=round(res['idx_ma'],1) if res['idx_ma'] else None,
              freq=freq, mode=MODE, capital=CAPITAL, per_pos=PER_POS,
              n_buy=len(buy), n_feasible=len(feasible), n_obs=len(obs),
              picks=picks, deployed=round(deployed,0), cash=cash,
              buy=buy, obs=obs, evidence=ev)
    json.dump(data, open(os.path.join(WORK,f'buy_list_{MODE}.json'),'w',encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"MODE={MODE} signal={res['signal_date']} regime_up={res['regime_up']} idx={res['idx_now']} ma={res['idx_ma']}")
    print(f"buy={len(buy)} feasible={len(feasible)} obs={len(obs)}")
    print(f"picks={[p['code'] for p in picks]} deployed={deployed:.0f} cash={cash}")
    print(f"written -> buy_list_{MODE}.json")

if __name__=="__main__":
    main()
