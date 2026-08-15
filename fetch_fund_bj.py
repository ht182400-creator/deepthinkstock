#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_fund_bj.py —— 给北交所(920xxx)补基本面, 合并进 fundamentals_broad.json,
让 regime_layer2_backtest 的 B 方案(北证50 bj899050 段 gate) 真正作用到个股买仓。

数据链路(复用 fetch_fund_broad.py 的 DMSK 三表):
  东方财富 datacenter-web.eastmoney.com 的 RPT_DMSK_FN_INCOME / _CASHFLOW / _BALANCE
  仅取年报(REPORT_DATE 以 -12-31 结尾), NOTICE_DATE 作可获知日(防前视)。
  北交所代码用 920xxx 格式(830xxx 老三板格式在东财 DMSK 返回空)。

输出: 原地更新 fundamentals_broad.json, 新增北交所条目
  {code: {name:"", industry:行业, annual:[{rd,notice,np,deduct,rev,ocf,capex,ta,tl,te}, ...]}}
  与现有沪深条目 schema 完全一致(pt_fund 可直接用)。

断点续跑: 已存在于 fundamentals_broad 且 annual 非空的代码跳过。
用法: python fetch_fund_bj.py            (后台跑; 可选 CODELIST=file 指定清单)
"""
import json, subprocess, os, datetime, time, sys

# 名称补全(腾讯行情接口); 缺失时降级跳过, 不影响基本面抓取
try:
    from fetch_names import enrich_names
except Exception:
    def enrich_names(fund):
        return fund

WORK = os.path.dirname(os.path.abspath(__file__))
SLEEP = 0.20
UA = "Mozilla/5.0"
CODELIST = os.environ.get("CODELIST", os.path.join(WORK, "bj_stock_codes.txt"))

def curl_json(url, timeout=25, retries=4):
    for _ in range(retries):
        try:
            out = subprocess.run(["curl", "-s", "--max-time", str(timeout),
                                 "--retry", "6", "--retry-delay", "2", "--retry-all-errors",
                                 "-A", UA, url], capture_output=True, text=True)
            txt = out.stdout.strip()
            if not txt:
                time.sleep(0.5); continue
            return json.loads(txt)
        except Exception:
            time.sleep(0.8)
    return None

def fetch_dmsk(code, report, cols):
    url = (f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName={report}"
           f"&columns={cols}&filter=(SECURITY_CODE%3D%22{code}%22)"
           f"&pageSize=500&sortColumns=REPORT_DATE&sortTypes=1")
    d = curl_json(url)
    if not d or not d.get("result"):
        return []
    return d["result"].get("data", [])

def dmsk_index(rows):
    m = {}
    for r in rows:
        rd = (r.get("REPORT_DATE") or "")[:10]
        if not rd: continue
        rec = {"notice": (r.get("NOTICE_DATE") or "")[:10]}
        for k, val in r.items():
            if k in ("SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE"): continue
            rec[k] = val
        m[rd] = rec
    return m

def fetch_one(code):
    inc = fetch_dmsk(code, "RPT_DMSK_FN_INCOME",
                     "SECURITY_CODE,REPORT_DATE,NOTICE_DATE,INDUSTRY_NAME,PARENT_NETPROFIT,DEDUCT_PARENT_NETPROFIT,TOTAL_OPERATE_INCOME")
    cf = fetch_dmsk(code, "RPT_DMSK_FN_CASHFLOW",
                    "SECURITY_CODE,REPORT_DATE,NOTICE_DATE,NETCASH_OPERATE,CONSTRUCT_LONG_ASSET")
    bal = fetch_dmsk(code, "RPT_DMSK_FN_BALANCE",
                     "SECURITY_CODE,REPORT_DATE,NOTICE_DATE,TOTAL_ASSETS,TOTAL_LIABILITIES,TOTAL_EQUITY")
    im, cm, bm = dmsk_index(inc), dmsk_index(cf), dmsk_index(bal)
    industry = ""
    for rd0 in im:
        industry = im[rd0].get("INDUSTRY_NAME") or ""
        if industry: break
    annual = []
    for rd in sorted(set(im) & set(cm) & set(bm)):
        if not rd.endswith("-12-31"): continue
        annual.append({
            "rd": rd, "notice": im[rd]["notice"],
            "np": im[rd].get("PARENT_NETPROFIT"),
            "deduct": im[rd].get("DEDUCT_PARENT_NETPROFIT"),
            "rev": im[rd].get("TOTAL_OPERATE_INCOME"),
            "ocf": cm[rd].get("NETCASH_OPERATE"),
            "capex": cm[rd].get("CONSTRUCT_LONG_ASSET"),
            "ta": bm[rd].get("TOTAL_ASSETS"),
            "tl": bm[rd].get("TOTAL_LIABILITIES"),
            "te": bm[rd].get("TOTAL_EQUITY"),
        })
    return industry, annual

def main():
    codes = [c.strip() for c in open(CODELIST, encoding="utf-8") if c.strip()]
    fund = json.load(open(os.path.join(WORK, "fundamentals_broad.json"), encoding="utf-8"))
    # 断点续跑: 已有且 annual 非空跳过
    todo = [c for c in codes if not (c in fund and fund[c].get("annual"))]
    print(f"清单={len(codes)} 已有基本面={len(codes)-len(todo)} 需补={len(todo)}")
    ok, skip = 0, 0
    t0 = time.time()
    for i, code in enumerate(todo):
        industry, annual = fetch_one(code)
        if not annual:
            skip += 1
        else:
            fund[code] = {"name": "", "industry": industry, "annual": annual}
            ok += 1
        if (i + 1) % 25 == 0 or (i + 1) == len(todo):
            print(f"[{i+1}/{len(todo)}] {code} 年报数={len(annual)} | 新增OK={ok} SKIP={skip} 用时{time.time()-t0:.0f}s")
        time.sleep(SLEEP)
    fund = enrich_names(fund)  # 补全证券名称(腾讯接口)
    json.dump(fund, open(os.path.join(WORK, "fundamentals_broad.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\nwritten -> fundamentals_broad.json (总 stocks={len(fund)}, 本次新增={ok}, 跳过={skip})")

if __name__ == "__main__":
    main()
