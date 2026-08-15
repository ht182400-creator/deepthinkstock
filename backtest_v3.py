#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3 策略回测引擎 v2（已纳入 ¥300 价格上限硬筛选）。
数据：universe.json（新浪日线聚合月线）。

三大增强（相对上一版）：
 ① 泡沫退出改为【估值驱动】：用 trailing val_window(默认60月) 价格分位作为估值代理
    （PE 历史无法抓取，价格相对自身5年区间的位置即"估值分位"，等价于"PE超历史90分位"精神），
    替代原 12 月价格分位（动量杀手）。val_window/ bubble_pctl 可调。
 ② 窗口切片 start_date：支持跑任意起点（如 2019-01 跨牛熊）。
 ③ 含分红 + 交易成本：with_div 按个股 div_yield 月度再投；cost_per_side 按换手计费。

对齐方式：按日期对齐（各标的长度不一，早期数据缺失者延后具备资格）。
逻辑：质量宇宙(已筛) -> GARP/低波 评分 -> 粘性集中持有(5-8) -> 行业≤35%
      -> 景气调节净敞口(60-90%) -> 仅在估值泡沫(估值分位)/基本面恶化代理/价格>300 时退出；无 -10% 止损。
输出：results.json + 控制台对比表。
"""
import json, math, os

WORK = os.path.dirname(os.path.abspath(__file__))
RF = 0.02


def stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def pct_rank(value, hist):
    if not hist:
        return 50.0
    below = sum(1 for h in hist if h <= value)
    return 100.0 * below / len(hist)


def rank_normalize(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    for rank, i in enumerate(order):
        r[i] = rank / (len(vals) - 1) if len(vals) > 1 else 0.5
    return r


def max_drawdown(curve):
    peak = curve[0]; mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd


def annualized(total_ret, months):
    if months <= 0:
        return 0.0
    return (1 + total_ret) ** (12.0 / months) - 1


def run_backtest(universe, N=5, ind_cap=0.35, regime=True, warmup=12,
                exit_bubble=True, exit_deteriorate=True,
                val_window=60, bubble_pctl=85.0,
                start_date=None, cost_per_side=0.0, with_div=False):
    index = universe["index"]["months"]
    stocks = universe["stocks"]
    idx_dates = [m["date"] for m in index]
    M = len(idx_dates)
    idx_close = {d: m["close"] for d, m in zip(idx_dates, index)}

    sclose, sind, scap = {}, {}, {}
    for c, s in stocks.items():
        sclose[c] = {m["date"]: m["close"] for m in s["months"]}
        sind[c] = s["industry"]
        scap[c] = s["cap_excluded"]

    def window_closes(code, t):
        """最近 12 月收盘价（用于基本面恶化代理 / 入场评分）"""
        out = []
        for i in range(t, t - 12, -1):
            if i < 0:
                break
            d = idx_dates[i]
            if d in sclose[code]:
                out.append(sclose[code][d])
            else:
                break
        out.reverse()
        return out

    def trailing(code, t, n):
        """最近 n 月收盘价（用于估值分位代理）"""
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

    # 窗口切片（跨牛熊验证）
    t_start = warmup
    if start_date:
        for i in range(warmup, M):
            if idx_dates[i] >= start_date:
                t_start = i
                break

    equity = [1.0]; rets = []; held_log = []; held = {}; prev_w = None

    for t in range(t_start, M - 1):
        # 1. 退出规则（基于截至 t 的数据）
        for code in list(held):
            wc = window_closes(code, t)
            if len(wc) < 12:
                del held[code]; continue
            price = wc[-1]
            traj12 = price / wc[0] - 1
            # 估值泡沫：trailing val_window 月估值分位（价格作估值代理）
            wv = trailing(code, t, val_window)
            val_pr = pct_rank(wv[-1], wv) if len(wv) >= 12 else 0.0
            bubble = exit_bubble and val_pr >= bubble_pctl
            deteriorate = exit_deteriorate and traj12 <= -0.40
            overcap = price > 300.0
            if bubble or deteriorate or overcap:
                del held[code]

        # 2. 候选评分（12 月价格分位=便宜度 + 低波）
        cands, scores, prL, volL, codes = {}, {}, [], [], []
        for code in stocks:
            if scap[code]:
                continue
            wc = window_closes(code, t)
            if len(wc) < 12:
                continue
            price, pr = wc[-1], pct_rank(wc[-1], wc)
            vol = stdev([wc[i] / wc[i - 1] - 1 for i in range(1, len(wc))])
            if price > 300.0:
                continue
            cands[code] = (price, pr, vol, price / wc[0] - 1)
            codes.append(code); prL.append(pr); volL.append(vol)
        if codes:
            pr_rk = rank_normalize(prL); vol_rk = rank_normalize(volL)
            for i, code in enumerate(codes):
                scores[code] = 0.5 * (1 - pr_rk[i]) + 0.5 * (1 - vol_rk[i])

        # 3. 补仓至 N（行业上限约束）
        if len(held) < N:
            order = sorted(cands, key=lambda c: -scores.get(c, -1))
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
                held[code] = 1; indc[ci] = indc.get(ci, 0) + 1

        # 4. 权重（等权，景气调节净敞口）
        if regime:
            ih = [idx_close[idx_dates[i]] for i in range(max(0, t - 11), t + 1)]
            expo = 0.9 if idx_close[idx_dates[t]] >= sum(ih) / len(ih) else 0.6
        else:
            expo = 0.9
        k = len(held)
        w = {c: (1.0 / k) * expo for c in held} if k else {}

        # 5. 当月收益 t->t+1（含分红、扣成本）
        r = 0.0
        for code, wt in w.items():
            p0, p1 = price_at(code, t), price_at(code, t + 1)
            if p0 and p1:
                r += wt * (p1 / p0 - 1)
                if with_div:
                    dy = stocks[code].get("div_yield", 0.0) or 0.0
                    r += wt * (dy / 12.0)   # 月度分红（再投近似）
        if cost_per_side > 0 and prev_w is not None:
            turnover = 0.0
            for c in set(w) | set(prev_w):
                turnover += abs(w.get(c, 0.0) - prev_w.get(c, 0.0))
            r -= turnover * cost_per_side
        prev_w = dict(w)

        equity.append(equity[-1] * (1 + r))
        rets.append(r)
        held_log.append((idx_dates[t], sorted(held.keys())))

    months = len(rets)
    total = equity[-1] - 1
    ann = annualized(total, months)
    vol_a = stdev(rets) * math.sqrt(12)
    sharpe = (ann - RF) / vol_a if vol_a > 0 else 0.0
    mdd = max_drawdown(equity)

    roll = []
    for s in range(0, months - 35):
        roll.append(annualized(equity[s + 36] / equity[s] - 1, 36))
    ry = {"min": min(roll), "median": sorted(roll)[len(roll) // 2], "max": max(roll),
          "n": len(roll), "ge15": sum(1 for x in roll if x >= 0.15)} if roll else \
         {"min": 0, "median": 0, "max": 0, "n": 0, "ge15": 0}

    eq_idx = [1.0]
    for t in range(t_start, M - 1):
        eq_idx.append(eq_idx[-1] * (idx_close[idx_dates[t + 1]] / idx_close[idx_dates[t]]))
    idx_total = eq_idx[-1] - 1

    return {
        "config": {"N": N, "ind_cap": ind_cap, "regime": regime, "warmup": warmup,
                   "exit_bubble": exit_bubble, "exit_deteriorate": exit_deteriorate,
                   "val_window": val_window, "bubble_pctl": bubble_pctl,
                   "start_date": start_date, "cost_per_side": cost_per_side,
                   "with_div": with_div},
        "months": months, "total_return": total, "annualized": ann,
        "vol_annual": vol_a, "sharpe": sharpe, "max_drawdown": mdd,
        "roll3y": ry, "idx_annualized": annualized(idx_total, months),
        "idx_max_drawdown": max_drawdown(eq_idx),
        "equity_curve": equity, "held_log": held_log,
    }


def main():
    u = json.load(open(os.path.join(WORK, "universe.json"), encoding="utf-8"))
    # ① 2021-2026 窗口：对比 旧12月分位 / 新60月估值分位 / 关泡沫退出
    A = "2021-03"
    # ② 2019-2026 跨牛熊窗口
    B = "2019-01"

    scenarios = {
        # ===== ① 同窗口(2021-2026) 验证估值驱动退出修复 =====
        "A_old12":  ("① 旧12月分位退出(对照)", dict(N=5, ind_cap=0.35, regime=True, start_date=A, val_window=12)),
        "A_val60":  ("① 新60月估值分位退出",   dict(N=5, ind_cap=0.35, regime=True, start_date=A, val_window=60)),
        "A_off":    ("① 关估值泡沫退出",       dict(N=5, ind_cap=0.35, regime=True, start_date=A, exit_bubble=False)),
        "A_val60_N8":("① 新估值退出+集中8只",  dict(N=8, ind_cap=0.35, regime=True, start_date=A, val_window=60)),
        # ===== ② 跨牛熊(2019-2026) 验证 15-25% 目标 =====
        "B_val60":  ("② 跨牛熊 60月估值退出",  dict(N=5, ind_cap=0.35, regime=True, start_date=B, val_window=60)),
        "B_off":    ("② 跨牛熊 关泡沫退出",     dict(N=5, ind_cap=0.35, regime=True, start_date=B, exit_bubble=False)),
        "B_val60_N8":("② 跨牛熊 估值退出+集中8", dict(N=8, ind_cap=0.35, regime=True, start_date=B, val_window=60)),
        # ===== ③ 含分红+交易成本(2019-2026) =====
        "C_price":  ("③ 价投(无分红无费)",     dict(N=5, ind_cap=0.35, regime=True, start_date=B, val_window=60)),
        "C_div":    ("③ 价投+分红",            dict(N=5, ind_cap=0.35, regime=True, start_date=B, val_window=60, with_div=True)),
        "C_total":  ("③ 价投+分红+成本(0.12%/边)", dict(N=5, ind_cap=0.35, regime=True, start_date=B, val_window=60, with_div=True, cost_per_side=0.0012)),
    }
    results = {}
    print(f"{'场景':<26}{'窗口':>9}{'年化':>8}{'最大回撤':>10}{'波动':>8}{'夏普':>7}{'36月滚动中值':>13}{'>=15%窗口':>10}")
    print("-" * 96)
    for key, (label, cfg) in scenarios.items():
        r = run_backtest(u, **cfg)
        results[key] = r
        sd = cfg.get("start_date", "全") or "全"
        ry = r["roll3y"]
        print(f"{label:<24}{sd:>9}{r['annualized']*100:>7.1f}%{r['max_drawdown']*100:>9.1f}%"
              f"{r['vol_annual']*100:>7.1f}%{r['sharpe']:>7.2f}{ry['median']*100:>12.1f}%{ry['ge15']:>8}/{ry['n']}")
    json.dump(results, open(os.path.join(WORK, "results.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\nwritten -> results.json")


if __name__ == "__main__":
    main()
