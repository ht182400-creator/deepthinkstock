# fetch_broad.py
# 扩展宇宙池：科创50(000688)+科创100(000689)+创业板指(399006)+中证1000(000852)
#   = 科创 + 创业 + 沪深中小盘成长；北交(8/4开头)因数据源不可达，明确排除。
# 日线=Sina scale=240 datalen=2000；基本面=Eastmoney RPT_DMSK_FN_INCOME(最新年报归母净利>0)
# 注意：REPORT_DATE 形如 "2016-12-31 00:00:00"，必须用 [:10].endswith('-12-31')，否则全部漏匹配。
import json, urllib.request, time
from concurrent.futures import ThreadPoolExecutor

OUT='daily_broad.json'
INDICES={'科创50':'000688','科创100':'000689','创业板指':'399006','中证1000':'000852'}

def http_get(url, timeout=25, retries=4):
    for i in range(retries):
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8','ignore')
        except Exception:
            time.sleep(0.4*(i+1))
    return None

# 1) 成分股（自动翻页，东方财富该接口硬上限500/页）
def get_constituents(idx):
    out=[]; page=1
    while True:
        url=(f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_INDEX_CONSTITUENT'
             f'&columns=SECURITY_CODE,SECURITY_NAME_ABBR&filter=(INDEX_CODE%3D%22{idx}%22)'
             f'&pageSize=500&pageNumber={page}&sortColumns=SECURITY_CODE&sortTypes=1')
        txt=http_get(url)
        if not txt: break
        try:
            rows=json.loads(txt).get('result',{}).get('data',[])
        except Exception:
            break
        if not rows: break
        out.extend(r['SECURITY_CODE'] for r in rows)
        if len(rows)<500: break
        page+=1
    return out

codes=set(); idx_meta={}
for name,idx in INDICES.items():
    cs=get_constituents(idx)
    for c in cs: codes.add(c)
    idx_meta[name]=len(cs)
    print(f'  {name}({idx}): {len(cs)} 只')
print('raw codes:', len(codes))

# 北交排除（数据源不可达）
bj=[c for c in codes if c[:1] in ('8','4')]
codes={c for c in codes if c[:1] not in ('8','4')}
print('剔除北交(8/4开头):', len(bj), '剩余:', len(codes))

def prefix(code):
    if code[:1]=='6': return 'sh'+code      # 沪主+科创
    if code[:1] in ('0','3'): return 'sz'+code  # 深主+创业
    return None

# 2) 日线
def fetch_daily(code):
    sym=prefix(code)
    if not sym: return code, None
    url=f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=2000'
    txt=http_get(url)
    if not txt: return code, None
    try:
        bars=json.loads(txt)
        if not isinstance(bars,list) or not bars: return code, None
        # Sina 北交数据陈旧(末根~2025)，这里已排除；其余应到 2026
        out=[{'d':b['day'],'o':float(b['open']),'h':float(b['high']),'l':float(b['low']),
              'c':float(b['close']),'v':int(b['volume'])} for b in bars]
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
        an=[r for r in data if str(r.get('REPORT_DATE',''))[:10].endswith('-12-31')]
        an.sort(key=lambda r:r['REPORT_DATE'])
        if not an: return code, None
        npv=an[-1].get('PARENT_NETPROFIT'); rev=an[-1].get('TOTAL_OPERATE_INCOME')
        revp=an[-2].get('TOTAL_OPERATE_INCOME') if len(an)>=2 else None
        growth=(rev is not None and revp is not None and rev>revp)
        return code, {'np':npv,'rev':rev,'rev_prev':revp,'growth':growth,'n_annual':len(an)}
    except Exception:
        return code, None

daily={}; fund={}
with ThreadPoolExecutor(max_workers=12) as ex:
    for c,b in ex.map(fetch_daily, codes):
        if b: daily[c]=b
with ThreadPoolExecutor(max_workers=4) as ex:   # DMSK 低并发，避免被限流
    for c,f in ex.map(fetch_fund, codes):
        fund[c]=f

eligible=[]; defaulted=0; loss=0; growth_n=0
for c in codes:
    f=fund.get(c)
    if f is None:
        defaulted+=1; eligible.append(c); continue
    npv=f.get('np')
    if npv is not None and npv>0:
        eligible.append(c)
        if f.get('growth'): growth_n+=1
    else:
        loss+=1
print('daily ok:',len(daily),'fund ok:',sum(1 for v in fund.values() if v),
      'defaulted:',defaulted,'loss_excluded:',loss,'eligible:',len(eligible),'of which growth:',growth_n)

out={'meta':{
        'source':'Sina daily scale=240 + Eastmoney DMSK income',
        'universe':'科创50(000688)+科创100(000689)+创业板指(399006)+中证1000(000852)',
        'excluded':'北交(8/4开头) — Sina数据陈旧到2025、东方财富/腾讯接口在本环境不可达',
        'screen':'latest annual PARENT_NETPROFIT>0; fetch-fail kept as unknown',
        'initial_capital':20000,'lot':100,
        'idx_meta':idx_meta,'raw_codes':len(codes)+len(bj),'bj_excluded':len(bj),
        'eligible':len(eligible),'defaulted':defaulted,'loss_excluded':loss,'growth':growth_n,
        'constructed':time.strftime('%Y-%m-%d')},
     'fund':{c:fund[c] for c in eligible},
     'daily':{c:daily[c] for c in eligible if c in daily}}
json.dump(out, open(OUT,'w'))
print('SAVED', OUT, 'eligible_with_daily:', sum(1 for c in eligible if c in daily))
