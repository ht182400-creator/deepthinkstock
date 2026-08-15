#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""read_qfq() 验证:
1) 末根自校验: 前复权末收 == 未复权末收
2) 连续性: 除权日前后前复权价无缝(未复权有跳变缺口)
3) 含送转的票交叉验证(找 f_bonus 最大的票)
"""
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tdx_day_reader as T

PY = "C:/Users/ht182/.workbuddy/binaries/python/versions/3.13.12/python.exe"

def find_bonus_stock():
    """从已过滤(剔除垃圾记录)的权息 map 里挑 f_bonus 最大的干净送转股"""
    m = T._load_xdxr_map()
    best = None
    for code, evs in m.items():
        for e in evs:
            b = e["f_bonus"]
            if b > 0:
                if best is None or b > best[1]:
                    best = (code, b, e["date_raw"])
    return best

def continuity(bars, ex_date):
    """返回除权日附近的 raw/adj 连续性信息"""
    # 找 ex_date 那根及其前一根、后一根
    idx = None
    for i, b in enumerate(bars):
        if b["date"] >= ex_date:
            idx = i
            break
    if idx is None:
        return None
    lo = max(0, idx - 1); hi = min(len(bars) - 1, idx + 1)
    seg = bars[lo:hi + 1]
    info = []
    prev_adj = None
    for b in seg:
        raw_gap = ""
        adj_gap = ""
        if prev_adj is not None:
            raw_gap = "rawΔ=%.2f%%" % ((b["close_raw"] / prev_raw - 1) * 100)
            adj_gap = "adjΔ=%.3f%%" % ((b["close"] / prev_adj - 1) * 100)
        info.append("  %d raw=%.2f adj=%.2f %s %s" % (b["date"], b["close_raw"], b["close"], raw_gap, adj_gap))
        prev_adj = b["close"]; prev_raw = b["close_raw"]
    return "\n".join(info)

print("=== 1) 茅台 600519 末根自校验 ===")
bars = T.read_qfq("sh600519")
last = bars[-1]
print("末根 date=%d  未复权收=%.4f  前复权收=%.4f  偏差=%.6f%%" % (
    last["date"], last["close_raw"], last["close"], (last["close"] / last["close_raw"] - 1) * 100))
assert abs(last["close"] - last["close_raw"]) < 1e-6, "末根自校验失败!"
print("  -> 通过 (末根前复权==未复权)")

# 茅台已知 ex-date: 2024-06-19 (2023年报 10派308.76)
print("\n=== 2) 茅台 除权日 2024-06-19 连续性 ===")
print(continuity(bars, 20240619))

print("\n=== 3) 含送转票交叉验证 ===")
code, bonus, ex = find_bonus_stock()
print("f_bonus 最大: code=%s 每10股送%.2f 股 除权日=%d" % (code, bonus, ex))
bars2 = T.read_qfq(code)
if bars2:
    last2 = bars2[-1]
    print("末根自校验: date=%d raw=%.2f adj=%.2f 偏差=%.6f%%" % (
        last2["date"], last2["close_raw"], last2["close"], (last2["close"] / last2["close_raw"] - 1) * 100))
    assert abs(last2["close"] - last2["close_raw"]) < 1e-6
    print("末根自校验 -> 通过")
    print("除权日 %d 附近连续性:" % ex)
    print(continuity(bars2, ex))
else:
    print("该码 .day 缺失, 跳过")

print("\nALL CHECKS DONE")
