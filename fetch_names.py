# -*- coding: utf-8 -*-
"""fetch_names.py —— 用腾讯行情接口(qt.gtimg.cn)补全证券名称。

根因: fetch_fund_broad.py / fetch_fund_bj.py 只从东财 DMSK 三表抓了行业(INDUSTRY_NAME)，
      从未抓证券名称，导致宽池(非沪深300+500)的 name 字段被写死成空串，
      面板解析时发现"名称==代码"就显示成横线"——"。

本脚本:
  - 仅补全 name 为空的条目, 不覆盖已有名称
  - 腾讯接口返回 GBK 编码, 字段2=证券名称, 字段3=代码
  - 北交所代码用 bj 前缀(920xxx/83xxxx/43xxxx/8xxxxx/4xxxxx)

用法: python fetch_names.py
也可被 fetch_fund_broad.py / fetch_fund_bj.py 复用: from fetch_names import enrich_names
"""
import json, subprocess, os, time

WORK = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(WORK, "fundamentals_broad.json")
CHUNK = 150  # 每批请求代码数(腾讯接口单批上限约数百, 取保守值)


def secid(code):
    """纯6位代码 -> 腾讯 secid 前缀。"""
    if code.startswith("6"):
        return "sh" + code          # 沪市(含科创板688/689)
    if code.startswith(("0", "3")):
        return "sz" + code          # 深市(含创业板300/301)
    return "bj" + code              # 北交所 8/4/92 开头


def _query(qs):
    try:
        raw = subprocess.run(
            ["curl", "-s", "--max-time", "30", "https://qt.gtimg.cn/q=" + qs],
            capture_output=True,
        ).stdout
        return raw.decode("gbk", "replace")
    except Exception as e:
        print("  query err:", e)
        return ""


def enrich_names(fund):
    """内存内补全 fund[{code}]['name']，返回同一 dict。"""
    need = [c for c, v in fund.items() if not (v.get("name"))]
    if not need:
        return fund
    print(f"[enrich_names] fund={len(fund)} 待补名称={len(need)}")
    got = {}
    for i in range(0, len(need), CHUNK):
        chunk = need[i : i + CHUNK]
        chunk_set = set(chunk)
        txt = _query(",".join(secid(c) for c in chunk))
        for line in txt.split("\n"):
            line = line.strip()
            if not line or "=" not in line or '"' not in line:
                continue
            try:
                inner = line.split('"', 1)[1].rsplit('"', 1)[0]
                parts = inner.split("~")
                code = parts[2]
                name = parts[1]
            except Exception:
                continue
            if code in chunk_set and name:
                got[code] = name
        time.sleep(0.3)
        print(f"  batch {i // CHUNK + 1}: 累计拿到 {len(got)}/{min(i + CHUNK, len(need))}")
    for c, nm in got.items():
        fund[c]["name"] = nm
    return fund


def fill_names(path=PATH):
    """读文件->补全->写回。返回补全条数。"""
    fund = json.load(open(path, encoding="utf-8"))
    before = sum(1 for v in fund.values() if v.get("name"))
    fund = enrich_names(fund)
    after = sum(1 for v in fund.values() if v.get("name"))
    json.dump(fund, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[fill_names] 名称 {before} -> {after} (共 {len(fund)} 只), 已写回 {os.path.basename(path)}")
    return after - before


if __name__ == "__main__":
    fill_names()
