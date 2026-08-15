# fetch_kechuang.py
# 科创板日线 + 基本面筛选（收益为正：最新年报归母净利>0）
# 数据源：成分股=东方财富 datacenter RPT_INDEX_CONSTITUENT(科创50=000688, 科创100=000689)
#        日线=新浪 K线 scale=240 datalen=2000(~2018-2026)
#        基本面=东方财富 datacenter RPT_DMSK_FN_INCOME
import json, urllib.request, time, threading
from concurrent.futures import ThreadPoolExecutor

OUT='daily_kc.json'

def http_get(url, timeout=25, retries=4):
    for i in range(retries):
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8','ignore')
        except Exception:
            time.sleep(0.4*(i+1))
    return None

# 1) 成分股代码
codes=set()
for idx in ['000688','000689']:
    url=(f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_INDEX_CONSTITUENT'
         f'&columns=SECURITY_CODE,SECURITY_NAME_ABBR&filter=(INDEX_CODE%3D%22{idx}%22)'
         f'&pageSize=500&pageNumber=1&sortColumns=SECURITY_CODE&sortTypes=1')
    txt=http_get(url)
    if txt:
        try:
            for r in json.loads(txt).get('result',{}).get('data',[]):
                codes.add(r['SECURITY_CODE'])
        except Exception as e:
            print('codes parse err', e)
print('raw 科创板 codes:', len(codes))
codes=list(codes)

# 2) 日线
def fetch_daily(code):
    url=f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh{code}&scale=240&ma=no&datalen=2000'
    txt=http_get(url)
    if not txt: return code, None
    try:
        bars=json.loads(txt)
        if not isinstance(bars,list) or not bars: return code, None
        out=[{'d':b['day'],'o':float(b['open']),'h':float(b['high']),'l':float(b['low']),'c':float(b['close']),'v':int(b['volume'])} for b in bars]
        return code, out
    except Exception:
        return code, None

# 3) 基本面：最新年报归母净利>0
INC='SECURITY_CODE,REPORT_DATE,NOTICE_DATE,PARENT_NETPROFIT,TOTAL_OPERATE_INCOME'
def fetch_fund(code):
    url=(f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DMSK_FN_INCOME'
         f'&columns={INC}&filter=(SECURITY_CODE%3D%22{code}%22)'
         f'&pageSize=500&sortColumns=REPORT_DATE&sortTypes=1')
    txt=http_get(url)
    if not txt: return code, None
    try:
        data=json.loads(txt).get('result',{}).get('data',[])
        an=[r for r in data if str(r.get('REPORT_DATE','')).endswith('-12-31')]
        an.sort(key=lambda r:r['REPORT_DATE'])
        if not an: return code, None
        npv=an[-1].get('PARENT_NETPROFIT')
        rev=an[-1].get('TOTAL_OPERATE_INCOME')
        revp=an[-2].get('TOTAL_OPERATE_INCOME') if len(an)>=2 else None
        growth=(rev is not None and revp is not None and rev>revp)
        return code, {'np':npv,'rev':rev,'rev_prev':revp,'growth':growth,'n_annual':len(an)}
    except Exception:
        return code, None

daily={}; fund={}
with ThreadPoolExecutor(max_workers=12) as ex:
    for c,b in ex.map(fetch_daily, codes):
        if b: daily[c]=b
with ThreadPoolExecutor(max_workers=8) as ex:
    for c,f in ex.map(fetch_fund, codes):
        fund[c]=f

# 筛选：最新年报归母净利>0（收益为正）；抓取失败按未知保留
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
print('daily ok:',len(daily),'fund ok:',sum(1 for v in fund.values() if v),
      'defaulted:',defaulted,'loss_excluded:',loss,'eligible:',len(eligible))

out={'meta':{
        'source':'Sina daily scale=240 + Eastmoney DMSK income',
        'universe':'科创50(000688)+科创100(000689)',
        'screen':'latest annual PARENT_NETPROFIT>0; fetch-fail kept as unknown',
        'initial_capital':20000,'lot':100,'price_cap':None,
        'raw_codes':len(codes),'eligible':len(eligible),'defaulted':defaulted,'loss_excluded':loss,
        'built':time.strftime('%Y-%m-%d')},
     'fund':{c:fund[c] for c in eligible},
     'daily':{c:daily[c] for c in eligible if c in daily}}
json.dump(out, open(OUT,'w'))
print('SAVED', OUT, 'eligible_with_daily:', sum(1 for c in eligible if c in daily))
