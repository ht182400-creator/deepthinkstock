#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_fund.py —— 真实基本面质量复利因子（研究驱动真阿尔法，规则化+全历史回测）。

时点正确（防前视）：每只股票在某月末 t 只使用 NOTICE_DATE<=月末 的年报；
用最近年报算当期 ROE=归母净利/归母权益、负债率=总负债/总资产、
FCF/净利=(经营现金流-购建长期资产)/归母净利；并要求连续 3 年年报 ROE>阈值（持续高 ROE）。

质量因子硬门槛（按用户定义，可 strict/relaxed）：
  ROE 当期 >= roe_min(0.20)；近 3 年年报 ROE 均 >= roe_min；
  FCF/净利 在 [fcfnp_min(0.80), fcfnp_max(3.0)]（>3 视为非经营现金流失真，剔除金融业）；
  负债率 <= debt_max（strict 0.30 / relaxed 0.50）；
  非金融（行业含 银行/证券/保险/信托/期货/租赁/财富/金融 剔除）；
  趋势确认 价格>12月均线；面值<=¥300。
评分（合格者内排序取前 N）：ROE 秩 + FCF/净利 秩 + (1-ROE波动CV) 秩 + (1-负债率) 秩。

对照：同宇宙下 动量(无regime)/动量+regime/被动等权。

数据：universe_big.json（价格，新浪月线）+ fundamentals.json（真实年报，东方财富 DMSK）。
口径：价格收益（with_div=False），月频再平衡，零杠杆，无 -10% 止损，行业<=35%，regime 可选。
"""
import json, math, os

WORK = os.path.dirname(os.path.abspath(__file__))
RF = 0.02
FIN_KW = ["银行", "证券", "保险", "信托", "期货", "租赁", "财富", "金融", "基金"]


def stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def rank_normalize(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    for rank, i in enumerate(order):
        r[i] = rank / (len(vals) - 1) if len(vals) > 1 else 0.5
    return r


def max_drawdown(curve):
    peak, mdd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd


def annualized(total_ret, months):
    return (1 + total_ret) ** (12.0 / months) - 1 if months > 0 else 0.0


def is_financial(industry):
    return any(k in (industry or "") for k in FIN_KW)


def run_backtest(universe, fund, N=15, ind_cap=0.35, regime_mode="binary",
                 score_mode="quality", roe_min=0.20, fcfnp_min=0.80, fcfnp_max=3.0,
                 debt_max=0.30, mom_window=12, val_window=60, bubble_pctl=85.0,
                 warmup=13, start_date=None, end_date=None, cost_per_side=0.0,
                 size_mode="equal", combo_q=0.5):
    index = universe["index"]["months"]
    stocks = universe["stocks"]
    idx_dates = [m["date"] for m in index]
    M = len(idx_dates)
    idx_close = {d: m["close"] for d, m in zip(idx_dates, index)}
    sclose, sind, scap = {}, {}, {}
    for c, s in stocks.items():
        sclose[c] = {m["date"]: m["close"] for m in s["months"]}
        sind[c] = s.get("industry", "") or (fund.get(c, {}).get("industry", "") or "")
        scap[c] = s["cap_excluded"]

    def trailing(code, t, n):
        out = []
        for i in range(t, t - n, -1):
            if i < 0:
                break
            d = idx_dates[i]
            if d in sclose[code]:
                out.append(sclose[code][d])
            else:
                break
        out.reverse()
        return out

    def price_at(code, t):
        return sclose[code].get(idx_dates[t])

    def mom_metrics(code, t):
        tr = trailing(code, t, mom_window + 1)
        if len(tr) < mom_window + 1:
            return None
        close_now, close_ago = tr[-1], tr[0]
        mom12 = close_now / close_ago - 1.0
        ma12 = sum(tr[-mom_window:]) / mom_window
        return mom12, ma12, close_now

    def pt_fund(code, month_end):
        an = fund.get(code, {}).get("annual", [])
        avail = [r for r in an if r.get("notice") and r["notice"] <= month_end
                 and r.get("np") and r.get("te") and r.get("ta")
                 and r.get("tl") is not None and r.get("ocf") is not None
                 and r.get("capex") is not None]
        if len(avail) < 3:
            return None
        latest = avail[-1]
        roes = [r["np"] / r["te"] for r in avail[-3:] if r["te"]]
        if len(roes) < 3:
            return None
        roe_now = latest["np"] / latest["te"]
        debt = latest["tl"] / latest["ta"]
        fcfnp = (latest["ocf"] - latest["capex"]) / latest["np"] if latest["np"] else None
        allroes = [r["np"] / r["te"] for r in avail if r["te"]]
        mean = sum(allroes) / len(allroes)
        cv = (stdev(allroes) / mean) if mean else 9.0
        return dict(roe_now=roe_now, roe3=roes, debt=debt, fcfnp=fcfnp, cv=cv, n=len(avail))

    t_start = warmup
    if start_date:
        for i in range(warmup, M):
            if idx_dates[i] >= start_date:
                t_start = i
                break
    t_end = M - 1
    if end_date:
        for i in range(t_start, M):
            if idx_dates[i] > end_date:
                t_end = i - 1
                break

    equity = [1.0]
    rets = []
    held = {}
    prev_w = None
    n_quality_pool = []

    for t in range(t_start, t_end):
        icloses = [idx_close[idx_dates[i]] for i in range(max(0, t - mom_window), t + 1)]
        idx_now = icloses[-1]
        idx_ma12 = sum(icloses) / len(icloses) if len(icloses) >= mom_window else None
        market_up = (idx_ma12 is not None) and (idx_now >= idx_ma12)

        # 退出
        for code in list(held):
            mm = mom_metrics(code, t)
            if mm is None:
                del held[code]
                continue
            mom12, ma12, price = mm
            if score_mode == "quality":
                trend_break = (price < ma12)
            else:
                trend_break = (mom12 <= 0) or (price < ma12)
            wv = trailing(code, t, val_window)
            val_pr = pct_rank_local(wv[-1], wv) if len(wv) >= 12 else 0.0
            overcap = price > 300.0
            deteriorate = mom12 <= -0.40
            if trend_break or val_pr >= bubble_pctl or overcap or deteriorate:
                del held[code]

        if regime_mode == "binary" and not market_up:
            held = {}

        # 候选
        cands, codes = {}, []
        if score_mode == "momentum":
            momL, volL = [], []
            for code in stocks:
                if scap[code]:
                    continue
                mm = mom_metrics(code, t)
                if mm is None:
                    continue
                mom12, ma12, price = mm
                if price > 300.0:
                    continue
                if not (mom12 > 0 and price > ma12):
                    continue
                wc = trailing(code, t, mom_window)
                vol = stdev([wc[i] / wc[i - 1] - 1 for i in range(1, len(wc))])
                cands[code] = (price, mom12, vol)
                codes.append(code)
                momL.append(mom12)
                volL.append(vol)
            if codes:
                mom_rk = rank_normalize(momL)
                vol_rk = rank_normalize(volL)
                for i, code in enumerate(codes):
                    cands[code] = (cands[code][0], 0.6 * mom_rk[i] + 0.4 * (1 - vol_rk[i]))
        else:  # quality 或 combo
            for code in stocks:
                if scap[code]:
                    continue
                mm = mom_metrics(code, t)
                if mm is None:
                    continue
                mom12, ma12, price = mm
                if price > 300.0:
                    continue
                if not (price > ma12):
                    continue
                ff = pt_fund(code, idx_dates[t])
                if ff is None:
                    continue
                if is_financial(sind[code]):
                    continue
                if score_mode == "qscore":
                    # 连续质量复合打分：仅软底线（排除负ROE垃圾/负自由现金流），不做硬三门卡死
                    if ff["roe_now"] < 0.10:
                        continue
                    if ff["fcfnp"] is None or ff["fcfnp"] < 0:
                        continue
                else:
                    if ff["roe_now"] < roe_min or any(r < roe_min for r in ff["roe3"]):
                        continue
                    if ff["fcfnp"] is None or ff["fcfnp"] < fcfnp_min or ff["fcfnp"] > fcfnp_max:
                        continue
                    if ff["debt"] > debt_max:
                        continue
                if score_mode in ("combo", "qscore"):
                    if not (mom12 > 0):   # 动量确认
                        continue
                    cands[code] = (price, ff, mom12)
                else:
                    cands[code] = (price, ff, None)
                codes.append(code)
            if codes:
                roe_rk = rank_normalize([cands[c][1]["roe_now"] for c in codes])
                fcf_rk = rank_normalize([cands[c][1]["fcfnp"] for c in codes])
                cv_rk = rank_normalize([cands[c][1]["cv"] for c in codes])
                debt_rk = rank_normalize([cands[c][1]["debt"] for c in codes])
                if score_mode in ("combo", "qscore"):
                    mom_rk = rank_normalize([cands[c][2] for c in codes])
                    for i, code in enumerate(codes):
                        qs = (roe_rk[i] + fcf_rk[i] + (1 - cv_rk[i]) + (1 - debt_rk[i])) / 4.0
                        s = (1 - combo_q) * qs + combo_q * mom_rk[i]
                        cands[code] = (cands[code][0], s)
                else:
                    for i, code in enumerate(codes):
                        s = (roe_rk[i] + fcf_rk[i] + (1 - cv_rk[i]) + (1 - debt_rk[i])) / 4.0
                        cands[code] = (cands[code][0], s)
            if score_mode == "quality":
                n_quality_pool.append(len(codes))

        if len(held) < N:
            order = sorted(cands, key=lambda c: -cands[c][1])
            indc = {}
            for c in held:
                indc[sind[c]] = indc.get(sind[c], 0) + 1
            capn = int(math.floor(ind_cap * N))
            for code in order:
                if len(held) >= N:
                    break
                if code in held:
                    continue
                ci = sind[code]
                if indc.get(ci, 0) >= capn:
                    continue
                held[code] = 1
                indc[ci] = indc.get(ci, 0) + 1

        expo = 0.9 if market_up or regime_mode != "binary" else 0.0
        if regime_mode == "scaled":
            expo = 0.9 if market_up else 0.4
        k = len(held)
        if k:
            if size_mode == "vol":
                vols = {}
                for c in held:
                    wc = trailing(c, t, mom_window)
                    if len(wc) >= 2:
                        vols[c] = stdev([wc[i] / wc[i - 1] - 1 for i in range(1, len(wc))]) or 1e-9
                    else:
                        vols[c] = 1e-9
                inv = {c: 1.0 / (vols[c] + 1e-9) for c in held}
                tot = sum(inv.values())
                w = {c: (inv[c] / tot) * expo for c in held}
            else:
                w = {c: (1.0 / k) * expo for c in held}
        else:
            w = {}

        r = 0.0
        for code, wt in w.items():
            p0, p1 = price_at(code, t), price_at(code, t + 1)
            if p0 and p1:
                r += wt * (p1 / p0 - 1)
        if cost_per_side > 0 and prev_w is not None:
            to = sum(abs(w.get(c, 0.0) - prev_w.get(c, 0.0)) for c in set(w) | set(prev_w))
            r -= to * cost_per_side
        prev_w = dict(w)
        equity.append(equity[-1] * (1 + r))
        rets.append(r)
        # 末月持仓快照（用于生成建仓清单）
        last_snap = {"t": t, "date": idx_dates[t], "held": dict(held),
                     "market_up": market_up, "expo": expo, "w": dict(w)}

    months = len(rets)
    total = equity[-1] - 1
    ann = annualized(total, months)
    vol_a = stdev(rets) * math.sqrt(12)
    sharpe = (ann - RF) / vol_a if vol_a > 0 else 0.0
    mdd = max_drawdown(equity)
    avg_pool = sum(n_quality_pool) / len(n_quality_pool) if n_quality_pool else 0
    dates = [idx_dates[t_start - 1]] + [idx_dates[t_start + j] for j in range(months)]
    return {"config": {"N": N, "regime_mode": regime_mode, "score_mode": score_mode,
                        "roe_min": roe_min, "fcfnp_min": fcfnp_min, "fcfnp_max": fcfnp_max,
                        "debt_max": debt_max, "start_date": start_date, "end_date": end_date,
                        "cost_per_side": cost_per_side, "size_mode": size_mode,
                        "combo_q": combo_q},
            "months": months, "total_return": total, "annualized": ann,
            "vol_annual": vol_a, "sharpe": sharpe, "max_drawdown": mdd,
            "avg_quality_pool": avg_pool, "equity_curve": equity, "dates": dates,
            "last_snap": last_snap}


def pct_rank_local(value, hist):
    if not hist:
        return 50.0
    return 100.0 * sum(1 for h in hist if h <= value) / len(hist)


def passive_equal_weight(universe, start_date=None, end_date=None, cost_per_side=0.0012, warmup=13):
    index = universe["index"]["months"]
    stocks = universe["stocks"]
    idx_dates = [m["date"] for m in index]
    M = len(idx_dates)
    sclose = {c: {m["date"]: m["close"] for m in s["months"]} for c, s in stocks.items()}
    scap = {c: s["cap_excluded"] for c, s in stocks.items()}
    eligible = [c for c in stocks if not scap[c]]
    t_start = warmup
    if start_date:
        for i in range(warmup, M):
            if idx_dates[i] >= start_date:
                t_start = i
                break
    t_end = M - 1
    if end_date:
        for i in range(t_start, M):
            if idx_dates[i] > end_date:
                t_end = i - 1
                break
    equity = [1.0]
    rets = []
    prev_w = None
    for t in range(t_start, t_end):
        ok = [c for c in eligible if idx_dates[t] in sclose[c] and idx_dates[t + 1] in sclose[c]]
        k = len(ok)
        w = {c: 1.0 / k for c in ok} if k else {}
        r = 0.0
        for c, wt in w.items():
            r += wt * (sclose[c][idx_dates[t + 1]] / sclose[c][idx_dates[t]] - 1)
        if cost_per_side > 0 and prev_w is not None:
            to = sum(abs(w.get(c, 0.0) - prev_w.get(c, 0.0)) for c in set(w) | set(prev_w))
            r -= to * cost_per_side
        prev_w = dict(w)
        equity.append(equity[-1] * (1 + r))
        rets.append(r)
    months = len(rets)
    return {"months": months, "annualized": annualized(equity[-1] - 1, months),
            "max_drawdown": max_drawdown(equity), "equity_curve": equity}


def main():
    u = json.load(open(os.path.join(WORK, "universe_big.json"), encoding="utf-8"))
    f = json.load(open(os.path.join(WORK, "fundamentals.json"), encoding="utf-8"))
    WIN1 = ("2014-06", None, "2014-26")
    WIN2 = ("2018-01", None, "2018-26")

    scenarios = {}
    for (sd, ed, lbl) in [WIN1, WIN2]:
        pre = lbl.replace("-", "")
        scenarios[f"q_strict_off_{pre}"] = (f"质量strict(债≤30%) 无regime {lbl}",
            dict(N=15, regime_mode="off", score_mode="quality", debt_max=0.30,
                 start_date=sd, end_date=ed, cost_per_side=0.0012))
        scenarios[f"q_strict_bin_{pre}"] = (f"质量strict(债≤30%) regime {lbl}",
            dict(N=15, regime_mode="binary", score_mode="quality", debt_max=0.30,
                 start_date=sd, end_date=ed, cost_per_side=0.0012))
        scenarios[f"q_relax_off_{pre}"] = (f"质量relax(债≤50%) 无regime {lbl}",
            dict(N=15, regime_mode="off", score_mode="quality", debt_max=0.50,
                 start_date=sd, end_date=ed, cost_per_side=0.0012))
        scenarios[f"q_relax_bin_{pre}"] = (f"质量relax(债≤50%) regime {lbl}",
            dict(N=15, regime_mode="binary", score_mode="quality", debt_max=0.50,
                 start_date=sd, end_date=ed, cost_per_side=0.0012))
        scenarios[f"mom_off_{pre}"] = (f"动量 无regime {lbl}",
            dict(N=15, regime_mode="off", score_mode="momentum", start_date=sd, end_date=ed, cost_per_side=0.0012))
        scenarios[f"mom_bin_{pre}"] = (f"动量 regime {lbl}",
            dict(N=15, regime_mode="binary", score_mode="momentum", start_date=sd, end_date=ed, cost_per_side=0.0012))
        scenarios[f"mom_vol_off_{pre}"] = (f"动量 波动加权 无regime {lbl}",
            dict(N=15, regime_mode="off", score_mode="momentum", size_mode="vol", start_date=sd, end_date=ed, cost_per_side=0.0012))
        scenarios[f"mom_vol_bin_{pre}"] = (f"动量 波动加权 regime {lbl}",
            dict(N=15, regime_mode="binary", score_mode="momentum", size_mode="vol", start_date=sd, end_date=ed, cost_per_side=0.0012))
        scenarios[f"combo_off_{pre}"] = (f"质量+动量组合 无regime {lbl}",
            dict(N=15, regime_mode="off", score_mode="combo", combo_q=0.5, start_date=sd, end_date=ed, cost_per_side=0.0012))
        scenarios[f"combo_bin_{pre}"] = (f"质量+动量组合 regime {lbl}",
            dict(N=15, regime_mode="binary", score_mode="combo", combo_q=0.5, start_date=sd, end_date=ed, cost_per_side=0.0012))

    results = {}
    print(f"{'场景':<34}{'年化':>8}{'最大回撤':>10}{'波动':>8}{'夏普':>7}{'均合格池':>9}")
    print("-" * 78)
    for key, (label, cfg) in scenarios.items():
        r = run_backtest(u, f, **cfg)
        results[key] = r
        print(f"{label:<32}{r['annualized']*100:>7.1f}%{r['max_drawdown']*100:>9.1f}%"
              f"{r['vol_annual']*100:>7.1f}%{r['sharpe']:>7.2f}{r['avg_quality_pool']:>9.1f}")

    for (sd, ed, lbl) in [WIN1, WIN2]:
        pre = lbl.replace("-", "")
        pas = passive_equal_weight(u, start_date=sd, end_date=ed, cost_per_side=0.0012)
        results[f"passive_{pre}"] = pas
        print(f"{'被动等权(同宇宙) '+lbl:<32}{pas['annualized']*100:>7.1f}%{pas['max_drawdown']*100:>9.1f}%")

    json.dump(results, open(os.path.join(WORK, "results_fund.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\nwritten -> results_fund.json")


if __name__ == "__main__":
    main()
