# fetch_fund_kc.py  —— 补抓科创板基本面(低并发防限流)，并重筛"收益为正"
import json, urllib.request, time
from concurrent.futures import ThreadPoolExecutor

SRC='daily_kc.json'
def http_get(url, timeout=25, retries=5):
    for i in range(retries):
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8','ignore')
        except Exception:
            time.sleep(0.5*(i+1))
    return None

INC='SECURITY_CODE,REPORT_DATE,NOTICE_DATE,PARENT_NETPROFIT,TOTAL_OPERATE_INCOME'
def fetch_fund(code):
    url=(f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DMSK_FN_INCOME'
         f'&columns={INC}&filter=(SECURITY_CODE%3D%22{code}%22)'
         f'&pageSize=500&sortColumns=REPORT_DATE&sortTypes=1')
    txt=http_get(url)
    if not txt: return code, None
    try:
        data=json.loads(txt).get('result',{})
        if not data: return code, None
        an=[r for r in data.get('data',[]) if str(r.get('REPORT_DATE',''))[:10].endswith('-12-31')]
        an.sort(key=lambda r:r['REPORT_DATE'])
        if not an: return code, None
        npv=an[-1].get('PARENT_NETPROFIT')
        rev=an[-1].get('TOTAL_OPERATE_INCOME')
        revp=an[-2].get('TOTAL_OPERATE_INCOME') if len(an)>=2 else None
        growth=(rev is not None and revp is not None and rev>revp)
        return code, {'np':npv,'rev':rev,'rev_prev':revp,'growth':growth,'n_annual':len(an)}
    except Exception:
        return code, None

d=json.load(open(SRC))
daily=d['daily']
codes=list(daily.keys())
fund={}
# 顺序抓取：东方财富对并发请求限流，单线程才稳定
for c in codes:
    fc,f=fetch_fund(c)
    fund[fc]=f
    time.sleep(0.08)

eligible=[]; defaulted=0; loss=0
for c in codes:
    f=fund.get(c)
    if f is None:
        defaulted+=1; eligible.append(c); continue
    npv=f.get('np')
    if npv is not None and npv>0:
        eligible.append(c)
    else:
        loss+=1
print('fund ok:',sum(1 for v in fund.values() if v),'defaulted:',defaulted,
      'loss_excluded:',loss,'eligible:',len(eligible))
# 统计合格池成长特征
gr=[fund[c]['growth'] for c in eligible if fund.get(c) and fund[c].get('growth') is not None]
print('eligible 中可计算营收增长且为正的占比:', round(sum(gr)/len(gr),3) if gr else 'n/a', '样本', len(gr))

out={'meta':{**d['meta'],
        'screen':'latest annual PARENT_NETPROFIT>0 (low-concurrency refetch)',
        'eligible':len(eligible),'defaulted':defaulted,'loss_excluded':loss,
        'built':time.strftime('%Y-%m-%d')},
     'fund':{c:fund[c] for c in eligible},
     'daily':{c:daily[c] for c in eligible if c in daily}}
json.dump(out, open(SRC,'w'))
print('RESAVED', SRC, 'eligible_with_daily:', sum(1 for c in eligible if c in daily))
