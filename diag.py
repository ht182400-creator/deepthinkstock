#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分解诊断：v3 主动管理是否优于被动持有？退出规则贡献几何？"""
import json, math, os
from backtest_v3 import run_backtest, max_drawdown, annualized, stdev

WORK = os.path.dirname(os.path.abspath(__file__))
u = json.load(open(os.path.join(WORK, "universe.json"), encoding="utf-8"))
index = u["index"]["months"]
stocks = u["stocks"]
idx_dates = [m["date"] for m in index]
M = len(idx_dates)
idx_close = {d: m["close"] for d, m in zip(idx_dates, index)}
sclose = {c: {m["date"]: m["close"] for m in s["months"]} for c, s in stocks.items()}
cap_excl = {c: s["cap_excluded"] for c, s in stocks.items()}
elig = [c for c in stocks if not cap_excl[c]]
WARM = 12


def metrics(equity, months):
    total = equity[-1] - 1
    rs = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity))]
    return dict(ann=annualized(total, months) * 100, mdd=max_drawdown(equity) * 100,
                vol=stdev(rs) * math.sqrt(12) * 100)


def ew_monthly_rebal():
    eq = [1.0]; months = 0
    for t in range(WARM, M - 1):
        rs = [(sclose[c][idx_dates[t + 1]] / sclose[c][idx_dates[t]] - 1)
              for c in elig if idx_dates[t] in sclose[c] and idx_dates[t + 1] in sclose[c]]
        eq.append(eq[-1] * (1 + sum(rs) / len(rs))); months += 1
    m = metrics(eq, months); m["name"] = "等权被动(全合格,月度再平衡)"; return m


def ew_buyhold():
    eq = [1.0]; months = 0
    for t in range(WARM, M - 1):
        rs = [(sclose[c][idx_dates[t + 1]] / sclose[c][idx_dates[t]] - 1)
              for c in elig if idx_dates[t] in sclose[c] and idx_dates[t + 1] in sclose[c]]
        eq.append(eq[-1] * (1 + sum(rs) / len(rs))); months += 1
    m = metrics(eq, months); m["name"] = "等权被动(买入持有)"; return m


def indiv_dist():
    out = {}
    for c in elig:
        eq = [1.0]; months = 0
        for t in range(WARM, M - 1):
            if idx_dates[t] in sclose[c] and idx_dates[t + 1] in sclose[c]:
                eq.append(eq[-1] * (sclose[c][idx_dates[t + 1]] / sclose[c][idx_dates[t]]))
                months += 1
        out[c] = annualized(eq[-1] - 1, months) * 100
    return out


print("=== 被动基准 ===")
for fn in (ew_monthly_rebal, ew_buyhold):
    m = fn()
    print(f"{m['name']:<28} 年化 {m['ann']:>6.1f}%  回撤 {m['mdd']:>6.1f}%  波动 {m['vol']:>5.1f}%")

print("\n=== 单只买入持有年化分布（价格收益, N=%d）===" % len(elig))
d = indiv_dist()
pos = sum(1 for v in d.values() if v > 0); neg = sum(1 for v in d.values() if v < 0)
print(f"正收益 {pos} / 负收益 {neg}")
for c, v in sorted(d.items(), key=lambda x: x[1]):
    print(f"  {c} {stocks[c]['name']:<6} {v:>7.1f}%  ({stocks[c]['industry']})")

print("\n=== v3 退出规则消融（N=5,行业35%,景气开）===")
for nm, kw in [("全退出(基准v3)", dict()),
               ("关基本面恶化退出", dict(exit_deteriorate=False)),
               ("关估值泡沫退出", dict(exit_bubble=False)),
               ("关全部退出(仅>300)", dict(exit_bubble=False, exit_deteriorate=False))]:
    r = run_backtest(u, N=5, ind_cap=0.35, regime=True, **kw)
    print(f"{nm:<22} 年化 {r['annualized']*100:>6.1f}%  回撤 {r['max_drawdown']*100:>6.1f}%  "
          f"夏普 {r['sharpe']:>5.2f}  36月滚动中值 {r['roll3y']['median']*100:>5.1f}%")
