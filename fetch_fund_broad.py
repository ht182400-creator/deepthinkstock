#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_fund_broad.py —— 给宽池(沪深+科创+创业, daily_broad.json 的 1020 只)补完整基本面。
仅抓取 fundamentals.json(500只 CSI300+500) 中缺失的代码，合并存 fundamentals_broad.json。
复用 fetch_fund.py 的 DMSK 三表逻辑(income/cashflow/balance) → 年报 np/ocf/capex/ta/tl/te。
NOTE: REPORT_DATE 形如 "2016-12-31 00:00:00"，用 [:10] 取日期；仅取 -12-31 年报；NOTICE_DATE 作时点。
"""
import json, subprocess, os, datetime, time

# 名称补全(腾讯行情接口); 缺失时降级跳过, 不影响基本面抓取
try:
    from fetch_names import enrich_names
except Exception:
    def enrich_names(fund):
        return fund

WORK = os.path.dirname(os.path.abspath(__file__))
SLEEP = 0.18
UA = "Mozilla/5.0"

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

def main():
    broad = json.load(open(os.path.join(WORK, "daily_broad.json"), encoding="utf-8"))
    codes_all = list(broad.get("daily", {}).keys())
    existing = json.load(open(os.path.join(WORK, "fundamentals.json"), encoding="utf-8"))
    have = set(existing.keys())
    missing = [c for c in codes_all if c not in have]
    print(f"宽池代码={len(codes_all)} 已有基本面={len(have)} 需补={len(missing)}")

    fund = dict(existing)  # 复制已有，合并新增
    ok, skip = 0, 0
    for i, code in enumerate(missing):
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
        if not annual:
            skip += 1
        else:
            fund[code] = {"name": "", "industry": industry, "annual": annual}
            ok += 1
        if (i + 1) % 25 == 0 or (i + 1) == len(missing):
            print(f"[{i+1}/{len(missing)}] {code} 年报数={len(annual)} | 新增OK={ok} SKIP={skip}")
        time.sleep(SLEEP)

    fund = enrich_names(fund)  # 补全证券名称(腾讯接口)
    json.dump(fund, open(os.path.join(WORK, "fundamentals_broad.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\nwritten -> fundamentals_broad.json (stocks={len(fund)}, 新增={ok}, 跳过={skip})")

if __name__ == "__main__":
    main()
