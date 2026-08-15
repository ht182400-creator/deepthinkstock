#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量候选池 新浪↔腾讯 交叉对账。
比对每只候选在两家最新共同交易日的收盘价；并标注腾讯是否比新浪更新。
输出 audit_full.json（summary + detail）。"""
import urllib.request, json, time, os

WORK=os.path.dirname(os.path.abspath(__file__))
TOL=0.3  # 允许偏差(%)

def get(url, ref=None, gbk=False, retries=3):
    h={"User-Agent":"Mozilla/5.0"}
    if ref: h["Referer"]=ref
    last=None
    for _ in range(retries):
        try:
            req=urllib.request.Request(url, headers=h)
            raw=urllib.request.urlopen(req, timeout=20).read()
            return raw.decode("gbk" if gbk else "utf-8")
        except Exception as e:
            last=e; time.sleep(0.3)
    raise last

def prefix(code):
    return ("sh" if code[:1]=="6" else "sz")+code

def sina_series(sym):
    u=f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=30"
    try:
        return {r["day"]: float(r["close"]) for r in json.loads(get(u))}
    except Exception:
        return {}

def tx_series(sym):
    u=f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,30,qfq"
    try:
        j=json.loads(get(u)); node=j["data"].get(sym)
        if not node: return {}
        key="qfqday" if "qfqday" in node else ("day" if "day" in node else None)
        if not key: return {}
        return {r[0]: float(r[2]) for r in node[key]}
    except Exception:
        return {}

# 收集唯一代码
codes=set()
for fn in ("buy_list.json","buy_list_momentum.json"):
    bl=json.load(open(os.path.join(WORK,fn),encoding="utf-8"))
    for g in ("buy","obs","picks"):
        for it in bl.get(g,[]):
            c=it.get("code")
            if c: codes.add(str(c))
codes=sorted(codes)
print(f"候选唯一代码数: {len(codes)}", flush=True)

res=[]; agree=0; disagree=0; missing=0; tx_newer=0
for c in codes:
    sym=prefix(c)
    s=sina_series(sym); t=tx_series(sym)
    time.sleep(0.02)
    if not s or not t:
        missing+=1; res.append([c,"MISSING","","",""]); continue
    common=set(s)&set(t)
    if not common:
        missing+=1; res.append([c,"NO_COMMON_DATE","","",""]); continue
    d=max(common); sc=s[d]; tc=t[d]
    diff=round((tc-sc)/sc*100,3) if sc else 0.0
    s_last=max(s); t_last=max(t)
    newer = (t_last > s_last)
    if newer: tx_newer+=1
    if abs(diff)<=TOL: agree+=1
    else: disagree+=1
    res.append([c,diff,d,s_last,t_last])

maxd=max((abs(r[1]) for r in res if isinstance(r[1],(int,float))), default=0.0)
summary={"n":len(codes),"agree_within_0.3pct":agree,"disagree":disagree,
         "missing_or_nodate":missing,"tx_newer_count":tx_newer,"max_abs_diff_pct":round(maxd,3)}
out={"summary":summary,"detail":res}
json.dump(out, open(os.path.join(WORK,"audit_full.json"),"w"), ensure_ascii=False, indent=1)
print("SUMMARY:", json.dumps(summary, ensure_ascii=False))
print("--- 偏差>0.3% 或缺失 ---")
for r in res:
    if not isinstance(r[1],(int,float)) or abs(r[1])>TOL:
        print(" ", r)
