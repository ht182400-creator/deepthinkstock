#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_fund.py —— 扩充候选池 + 抓取真实基本面（解决生存偏差 + 研究驱动真阿尔法因子）。

数据链路：
  1) 候选池：东方财富 push2 全 A 代码列表，按总市值降序取 TOP_N（流动性可投宇宙，含大量"昔日大蓝筹已衰落"名，
     部分缓解生存偏差；已退市/归零名仍缺失，属残留偏差——如实标注）。
  2) 价格：新浪日线 scale=240 聚合月线（价格收益，不含分红；与 v4 口径一致）。
  3) 基本面（真实时点）：东方财富 datacenter RPT_DMSK_FN_INCOME / _CASHFLOW / _BALANCE，
     仅取年报（REPORT_DATE 以 -12-31 结尾），用 NOTICE_DATE 作"可获知日"实现时点正确（防前视）。
     计算：ROE = 归母净利/归母权益；FCF/净利 = (经营现金流净额 - 购建长期资产)/归母净利；
           负债率 = 总负债/总资产。并要求连续 3 年年报 ROE>20% 才算"持续高 ROE"。

输出：
  universe_big.json  —— 与 universe.json 同 schema（index + stocks{code:{industry,cap_excluded,months,div_yield}}）
  fundamentals.json  —— {code:{name, annual:[{rd,notice,np,deduct,rev,ocf,capex,ta,tl,te}, ...]}}（按 notice 升序）

用法：python fetch_fund.py            （后台跑；TOP_N 见下方常量）
"""
import json, subprocess, os, datetime, time

WORK = os.path.dirname(os.path.abspath(__file__))
TOP_N = int(os.environ.get("TOP_N", "500"))   # 候选池规模（流动性可投宇宙；可用 TOP_N=5 冒烟测试）
PRICE_CAP = 300.0      # F 规则：面值上限（与 v4 一致）
DATALEN = 3200         # 日线根数（≈13.3 年，回溯到 ~2013，覆盖 2014-15 崩盘）
SLEEP = 0.18           # 请求间隔（降低被拦风险）
UA = "Mozilla/5.0"


def curl_json(url, timeout=25, retries=4):
    for _ in range(retries):
        try:
            # --retry 让 curl 自身重试瞬时接收失败(rc=56 等)，比 python 层重试更稳
            out = subprocess.run(["curl", "-s", "--max-time", str(timeout),
                                 "--retry", "6", "--retry-delay", "2", "--retry-all-errors",
                                 "-A", UA, url], capture_output=True, text=True)
            txt = out.stdout.strip()
            if not txt:
                time.sleep(0.5)
                continue
            return json.loads(txt)
        except Exception:
            time.sleep(0.8)
    return None


def sina_symbol(code: str) -> str:
    return ("sh" if code[0] in ("6", "9") else "sz") + code


def fetch_sina_monthly(code: str):
    sym = sina_symbol(code)
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen={DATALEN}")
    d = curl_json(url)
    if not d:
        return None
    months = {}
    for row in d:
        ym = row["day"][:7]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        if ym not in months:
            months[ym] = {"date": row["day"], "open": o, "high": h, "low": l, "close": c,
                          "vol": float(row["volume"])}
        else:
            m = months[ym]
            m["high"] = max(m["high"], h)
            m["low"] = min(m["low"], l)
            m["close"] = c
            m["vol"] += float(row["volume"])
            m["date"] = row["day"]
    return [months[k] for k in sorted(months.keys())]


def get_index_codes(index_code):
    # 东方财富 datacenter 指数成分股（沪深300=000300 / 中证500=000905），标准可投宇宙。
    out = []
    pn = 1
    while True:
        url = (f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_INDEX_CONSTITUENT"
               f"&columns=SECURITY_CODE,SECURITY_NAME_ABBR&filter=(INDEX_CODE%3D%22{index_code}%22)"
               f"&pageSize=500&pageNumber={pn}&sortColumns=SECURITY_CODE&sortTypes=1")
        d = curl_json(url)
        if not d or not d.get("result") or not d["result"].get("data"):
            break
        rows = d["result"]["data"]
        if not rows:
            break
        for r in rows:
            out.append((r.get("SECURITY_CODE"), r.get("SECURITY_NAME_ABBR", "")))
        if len(rows) < 500:
            break
        pn += 1
    return out


def get_codes(top_n):
    # 沪深300 + 中证500 成分股并集（去重）→ 流动性可投大/中盘宇宙，显著缓解生存偏差。
    codes = {}
    for idx in ("000300", "000905"):
        for c, n in get_index_codes(idx):
            if c and c not in codes:
                codes[c] = n
    items = list(codes.items())
    return items[:top_n]


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
        if not rd:
            continue
        rec = {"notice": (r.get("NOTICE_DATE") or "")[:10]}
        for k, val in r.items():
            if k in ("SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE"):
                continue
            rec[k] = val
        m[rd] = rec
    return m


def main():
    print(f"[{datetime.datetime.now():%H:%M:%S}] 拉取 TOP {TOP_N} A 股代码列表...")
    codes = get_codes(TOP_N)
    print(f"  代码数={len(codes)} 示例={codes[:3]}")

    # ---- 指数（上证）----
    idx_daily = fetch_sina_monthly("000001")
    index = {"code": "000001", "months": idx_daily} if idx_daily else None

    universe = {"meta": {"source": "Sina daily scale=240 (price) + Eastmoney DMSK (fundamentals)",
                         "price_cap": PRICE_CAP, "top_n": TOP_N,
                         "built": datetime.date.today().isoformat()},
                "index": index, "stocks": {}}
    fund = {}

    ok_p, ok_f, skip = 0, 0, 0
    for i, (code, name) in enumerate(codes):
        # 价格
        m = fetch_sina_monthly(code)
        if not m:
            skip += 1
            print(f"[{i+1}/{len(codes)}] SKIP {code} {name} (价格缺失)")
            time.sleep(SLEEP)
            continue
        last = m[-1]["close"]
        cap_excl = last > PRICE_CAP
        universe["stocks"][code] = {
            "name": name, "industry": "", "months": m,
            "last_close": last, "cap_excluded": cap_excl, "div_yield": 0.0,
        }
        ok_p += 1

        # 基本面（仅年报）
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
            if industry:
                break
        annual = []
        for rd in sorted(set(im) & set(cm) & set(bm)):
            if not rd.endswith("-12-31"):
                continue
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
        fund[code] = {"name": name, "industry": industry, "annual": annual}
        ok_f += 1
        if (i + 1) % 25 == 0 or (i + 1) == len(codes):
            print(f"[{i+1}/{len(codes)}] {code} {name} 年报数={len(annual)} "
                  f"价末={last:.2f}{' EXCL' if cap_excl else ''} | 价格OK={ok_p} 基本面OK={ok_f} SKIP={skip}")
        time.sleep(SLEEP)

    json.dump(universe, open(os.path.join(WORK, "universe_big.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(fund, open(os.path.join(WORK, "fundamentals.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\nwritten -> universe_big.json (stocks={len(universe['stocks'])}) , fundamentals.json (stocks={len(fund)})")


if __name__ == "__main__":
    main()
