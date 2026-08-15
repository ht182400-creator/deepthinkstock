#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4 策略回测引擎 —— 质量 + 动量(QMoT) + 绝对动量 regime 过滤。

★ 策略性格改造（相对 v3 的"防御型质量均值回归"）：
  v3 的根因是"买便宜(低分位)入场"——在 2019-21 牛市把高质量股判贵而低配，
  在 2022-26 熊市又因便宜低吸被套。v4 改为进攻型框架：

  ① 入场 = 质量 + 趋势确认（Asness QMJ + UMD 动量组合）：
     候选须在【12月动量>0 且 价格>12月均线】才合格（已处上行趋势、被重估中）；
     合格者按 动量(主) + 低波(质量稳定性,次) 综合打分，取前 N 集中持有。
  ② 绝对动量 regime 过滤（Antonacci 战术资产配置）：
     上证指数 < 其12月均线 → 整体转现金（规避 2022-26 类熊市），熊市不再硬扛。
  ③ 退出 = 趋势破位（价格<12月均线 或 12月动量转负）即出；
     保留估值泡沫(60月估值分位≥85)/面值>¥300/基本面恶化代理 作为护栏。
  ④ 仍是：纯多头、零杠杆、无 -10% 价格止损、行业≤35%、月度再平衡、T月末调仓(无前视)。

数据：universe.json（新浪日线聚合月线，价格收益；with_div 按个股 div_yield 月度近似再投）。
对齐：按日期对齐，各标的长度不一，历史不足者延后具备资格。
输出：results_v4.json + 控制台对比表。
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
    return 100.0 * sum(1 for h in hist if h <= value) / len(hist)


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
    if months <= 0:
        return 0.0
    return (1 + total_ret) ** (12.0 / months) - 1


def run_backtest(universe, N=6, ind_cap=0.35, regime_mode="binary",
                 mom_window=12, val_window=60, bubble_pctl=85.0,
                 mom_w=0.6, vol_w=0.4, warmup=13, no_ma=False,
                 score_mode="momentum", q_vol_w=0.40, q_mdd_w=0.35, q_pos_w=0.25,
                 start_date=None, end_date=None, cost_per_side=0.0, with_div=False):
    """score_mode: 'momentum'(v4 原版，动量为主+低波为辅) / 'quality'(基本面质量复利代理)。
    quality 模式用纯价格可计算的质量代理：低波动(36m)、浅回撤(60m)、正月占比(36m)、分红倾斜；
    入场放宽——只要求趋势确认(价格>12月均线)，不要求 12月动量>0（即允许暂时失宠的优质股）。
    注意：div_yield 为 2026 快照，历史回测套用属前视近似，故质量场景统一 with_div=False（价投口径，与 OOS/全样本动量一致）。"""
    """regime_mode: 'binary'(指数<12月均线→全现金) / 'scaled'(熊市降至0.4敞口) / 'off'。"""
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

    def trailing(code, t, n):
        """最近 n 月收盘价（含 t），不足返回短序列。"""
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

    def momentum_metrics(code, t):
        """返回 (mom12, ma12, close_now) 或 None（历史不足）。"""
        tr = trailing(code, t, mom_window + 1)   # 含 t，共 mom_window+1 点
        if len(tr) < mom_window + 1:
            return None
        close_now = tr[-1]
        close_ago = tr[0]
        mom12 = close_now / close_ago - 1.0
        ma12 = sum(tr[-mom_window:]) / mom_window
        return mom12, ma12, close_now

    # 窗口切片
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
    held_log = []
    held = {}
    prev_w = None

    for t in range(t_start, t_end):
        # ---- 市场 regime（绝对动量，用指数自身收盘价）----
        icloses = [idx_close[idx_dates[i]] for i in range(max(0, t - mom_window), t + 1)]
        idx_now = icloses[-1]
        idx_ma12 = sum(icloses) / len(icloses) if len(icloses) >= mom_window else None
        market_up = (idx_ma12 is not None) and (idx_now >= idx_ma12)

        # ---- 1. 退出规则（基于截至 t 的数据）----
        for code in list(held):
            mm = momentum_metrics(code, t)
            if mm is None:
                del held[code]
                continue
            mom12, ma12, price = mm
            # 趋势破位：质量模式只看价格破12月均线（容忍动量暂负）；动量模式动量转负即出
            if score_mode == "quality":
                trend_break = (price < ma12)
            else:
                trend_break = (mom12 <= 0) or (price < ma12)
            # 估值泡沫（60月估值分位代理）
            wv = trailing(code, t, val_window)
            val_pr = pct_rank(wv[-1], wv) if len(wv) >= 12 else 0.0
            bubble = val_pr >= bubble_pctl
            overcap = price > 300.0
            deteriorate = mom12 <= -0.40
            if trend_break or bubble or overcap or deteriorate:
                del held[code]

        # ---- 2. regime：熊市整体转现金 ----
        if regime_mode == "binary":
            if not market_up:
                held = {}
        elif regime_mode == "scaled":
            pass  # 敞口在权重步缩放

        # ---- 3. 候选评分（动量为主 + 低波为辅），仅合格(趋势确认)者可入 ----
        cands, codes, momL, volL = {}, [], [], []
        for code in stocks:
            if scap[code]:
                continue
            mm = momentum_metrics(code, t)
            if mm is None:
                continue
            mom12, ma12, price = mm
            if price > 300.0:
                continue
            # 趋势确认：动量模式要求 动量>0 且 价格在均线上；质量模式只要求价格在均线上(允许暂失宠)
            if score_mode == "momentum":
                elig = (mom12 > 0) and (no_ma or price > ma12)
            else:
                elig = (no_ma or price > ma12)
            if not elig:
                continue
            wc = trailing(code, t, mom_window)
            rets_m = [wc[i] / wc[i - 1] - 1 for i in range(1, len(wc))]
            vol = stdev(rets_m)
            cands[code] = (price, mom12, vol)
            codes.append(code)
            momL.append(mom12)
            volL.append(vol)
        if codes:
            if score_mode == "quality":
                # 质量代理打分（纯价格可计算）：低波动(36m) + 浅回撤(60m) + 正月占比(36m)；越高越好
                volL2, mddL, posL = [], [], []
                for code in codes:
                    tr60 = trailing(code, t, 60)
                    tr36 = trailing(code, t, 36)
                    r36 = [tr36[i] / tr36[i - 1] - 1 for i in range(1, len(tr36))]
                    vol36 = stdev(r36)
                    mdd60 = max_drawdown(tr60)
                    pos36 = (sum(1 for x in r36 if x > 0) / len(r36)) if r36 else 0.0
                    volL2.append(vol36)
                    mddL.append(mdd60)
                    posL.append(pos36)
                vol_rk = rank_normalize(volL2)
                mdd_rk = rank_normalize(mddL)   # 回撤越浅(越接近0)排名越高
                pos_rk = rank_normalize(posL)
                for i, code in enumerate(codes):
                    cands[code] = (cands[code][0],
                        q_vol_w * (1 - vol_rk[i]) + q_mdd_w * mdd_rk[i] + q_pos_w * pos_rk[i])
            else:
                mom_rk = rank_normalize(momL)
                vol_rk = rank_normalize(volL)
                for i, code in enumerate(codes):
                    # 动量越高越好，波动越低越好（质量稳定）
                    cands[code] = (cands[code][0],
                                   mom_w * mom_rk[i] + vol_w * (1 - vol_rk[i]))

        # ---- 4. 补仓至 N（行业上限约束）----
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

        # ---- 5. 权重（等权；regime 缩放净敞口）----
        if regime_mode == "scaled":
            expo = 0.9 if market_up else 0.4
        elif regime_mode == "binary":
            expo = 0.9 if market_up else 0.0
        else:
            expo = 0.9
        k = len(held)
        w = {c: (1.0 / k) * expo for c in held} if k else {}

        # ---- 6. 当月收益 t->t+1（含分红、扣成本）----
        r = 0.0
        for code, wt in w.items():
            p0, p1 = price_at(code, t), price_at(code, t + 1)
            if p0 and p1:
                r += wt * (p1 / p0 - 1)
                if with_div:
                    dy = stocks[code].get("div_yield", 0.0) or 0.0
                    r += wt * (dy / 12.0)
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
    ry = ({"min": min(roll), "median": sorted(roll)[len(roll) // 2],
           "max": max(roll), "n": len(roll),
           "ge15": sum(1 for x in roll if x >= 0.15)} if roll else
          {"min": 0, "median": 0, "max": 0, "n": 0, "ge15": 0})

    eq_idx = [1.0]
    for t in range(t_start, t_end):
        eq_idx.append(eq_idx[-1] * (idx_close[idx_dates[t + 1]] / idx_close[idx_dates[t]]))
    idx_total = eq_idx[-1] - 1

    # 净值曲线对齐日期：equity[0]=基准(idx_dates[t_start-1])，其后每步对应 idx_dates[t_start+j]
    dates = [idx_dates[t_start - 1]] + [idx_dates[t_start + j] for j in range(months)]

    return {
        "config": {"N": N, "ind_cap": ind_cap, "regime_mode": regime_mode,
                   "mom_window": mom_window, "val_window": val_window,
                   "bubble_pctl": bubble_pctl, "mom_w": mom_w, "vol_w": vol_w,
                   "score_mode": score_mode, "q_vol_w": q_vol_w, "q_mdd_w": q_mdd_w, "q_pos_w": q_pos_w,
                   "warmup": warmup, "start_date": start_date, "end_date": end_date,
                   "cost_per_side": cost_per_side, "with_div": with_div},
        "months": months, "total_return": total, "annualized": ann,
        "vol_annual": vol_a, "sharpe": sharpe, "max_drawdown": mdd,
        "roll3y": ry, "idx_annualized": annualized(idx_total, months),
        "idx_max_drawdown": max_drawdown(eq_idx),
        "equity_curve": equity, "held_log": held_log, "dates": dates,
    }


def passive_equal_weight(universe, start_date=None, end_date=None, with_div=True,
                         cost_per_side=0.0012, warmup=13):
    """被动等权质量池（25只，月度再平衡，含分红+成本）——对照基准。"""
    index = universe["index"]["months"]
    stocks = universe["stocks"]
    idx_dates = [m["date"] for m in index]
    M = len(idx_dates)
    idx_close = {d: m["close"] for d, m in zip(idx_dates, index)}
    sclose, scap = {}, {}
    for c, s in stocks.items():
        sclose[c] = {m["date"]: m["close"] for m in s["months"]}
        scap[c] = s["cap_excluded"]
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
            p0, p1 = sclose[c][idx_dates[t]], sclose[c][idx_dates[t + 1]]
            r += wt * (p1 / p0 - 1)
            if with_div:
                dy = stocks[c].get("div_yield", 0.0) or 0.0
                r += wt * (dy / 12.0)
        if cost_per_side > 0 and prev_w is not None:
            to = 0.0
            for c in set(w) | set(prev_w):
                to += abs(w.get(c, 0.0) - prev_w.get(c, 0.0))
            r -= to * cost_per_side
        prev_w = dict(w)
        equity.append(equity[-1] * (1 + r))
        rets.append(r)
    months = len(rets)
    ann = annualized(equity[-1] - 1, months)
    return {"months": months, "annualized": ann, "max_drawdown": max_drawdown(equity),
            "equity_curve": equity}


def main():
    u = json.load(open(os.path.join(WORK, "universe.json"), encoding="utf-8"))
    B = "2019-01"   # 跨牛熊窗口
    A = "2021-03"   # 近窗口（对照 v3）

    scenarios = {
        # ===== ④ 跨牛熊(2019-2026) 主验证 =====
        "v4_binary": ("④ v4 动量+regime(全现金)", dict(N=6, regime_mode="binary", start_date=B)),
        "v4_scaled": ("④ v4 动量+regime(缩放0.4)", dict(N=6, regime_mode="scaled", start_date=B)),
        "v4_off":    ("④ v4 动量(无regime)",       dict(N=6, regime_mode="off", start_date=B)),
        "v4_off_N8": ("④ v4 动量(无regime) N=8",   dict(N=8, regime_mode="off", start_date=B)),
        "v4_off_6m": ("④ v4 动量6月窗(无regime)",  dict(N=6, regime_mode="off", mom_window=6, start_date=B)),
        "v4_mom_only":("④ v4 纯动量(去均线约束)",  dict(N=6, regime_mode="off", start_date=B,
                                                      mom_window=12, no_ma=True)),
        "v4_mom_total":("④ v4 纯动量+分红+成本",    dict(N=6, regime_mode="off", start_date=B,
                                                      mom_window=12, no_ma=True,
                                                      with_div=True, cost_per_side=0.0012)),
        "v4_bin_N8": ("④ v4 动量+regime N=8",      dict(N=8, regime_mode="binary", start_date=B)),
        # ===== ④ 近窗口(2021-2026) 对照 v3 =====
        "v4_A_bin":  ("④ v4 近窗 动量+regime",     dict(N=6, regime_mode="binary", start_date=A)),
        # 总成本版本（含分红+成本，策略默认）
        "v4_total":  ("④ v4 总成本(分红+0.12%/边)", dict(N=6, regime_mode="binary", start_date=B,
                                                         with_div=True, cost_per_side=0.0012)),
        # ===== 样本外 2014-2018（验证动量倾斜稳健性；价投不含分红，避免用2026股息率套历史）=====
        "oos_mom":   ("样本外14-18 纯动量(无regime)", dict(N=6, regime_mode="off", no_ma=True,
                                                         start_date="2014-01", end_date="2018-12",
                                                         with_div=False, cost_per_side=0.0012)),
        "oos_mom_reg":("样本外14-18 动量+regime全现金", dict(N=6, regime_mode="binary",
                                                         start_date="2014-01", end_date="2018-12",
                                                         with_div=False, cost_per_side=0.0012)),
        "oos_mom_n8": ("样本外14-18 纯动量 N=8",       dict(N=8, regime_mode="off", no_ma=True,
                                                         start_date="2014-01", end_date="2018-12",
                                                         with_div=False, cost_per_side=0.0012)),
        # ===== 早期样本外 2006-2014（受数据起点+warmup限制，实际持仓约2007起）=====
        "early_mom":  ("早期06-14 纯动量(无regime)", dict(N=6, regime_mode="off", no_ma=True,
                                                         start_date="2006-01", end_date="2014-12",
                                                         with_div=False, cost_per_side=0.0012)),
        "early_reg":  ("早期06-14 动量+regime全现金", dict(N=6, regime_mode="binary",
                                                         start_date="2006-01", end_date="2014-12",
                                                         with_div=False, cost_per_side=0.0012)),
        # ===== 全样本 2006-2026 连续（诚实整段数字，价投）=====
        "full_mom":  ("全样本06-26 纯动量(价投)", dict(N=6, regime_mode="off", no_ma=True,
                                                       start_date="2006-01", with_div=False, cost_per_side=0.0012)),
        "full_regime":("全样本06-26 动量+regime全现金", dict(N=6, regime_mode="binary",
                                                       start_date="2006-01", with_div=False, cost_per_side=0.0012)),
        # ===== ⑤ 质量复利代理(score_mode=quality)：低波+浅回撤+正月占比，入场放宽(允许暂失宠优质股) =====
        # 统一价投口径(with_div=False)，与 OOS/全样本动量一致；分红对各策略均匀 +~3%/yr。
        "q_main_off": ("⑤ 质量代理 主窗(无regime)", dict(N=6, regime_mode="off", score_mode="quality",
                                                       start_date=B, with_div=False, cost_per_side=0.0012)),
        "q_main_bin": ("⑤ 质量代理 主窗+regime",   dict(N=6, regime_mode="binary", score_mode="quality",
                                                       start_date=B, with_div=False, cost_per_side=0.0012)),
        "q_oos_off":  ("⑤ 质量代理 14-18(无regime)", dict(N=6, regime_mode="off", score_mode="quality",
                                                       start_date="2014-01", end_date="2018-12",
                                                       with_div=False, cost_per_side=0.0012)),
        "q_oos_bin":  ("⑤ 质量代理 14-18+regime",   dict(N=6, regime_mode="binary", score_mode="quality",
                                                       start_date="2014-01", end_date="2018-12",
                                                       with_div=False, cost_per_side=0.0012)),
        "q_early_off": ("⑤ 质量代理 06-14(无regime)", dict(N=6, regime_mode="off", score_mode="quality",
                                                       start_date="2006-01", end_date="2014-12",
                                                       with_div=False, cost_per_side=0.0012)),
        "q_early_bin": ("⑤ 质量代理 06-14+regime",   dict(N=6, regime_mode="binary", score_mode="quality",
                                                       start_date="2006-01", end_date="2014-12",
                                                       with_div=False, cost_per_side=0.0012)),
        "q_full_off":  ("⑤ 质量代理 06-26(无regime)", dict(N=6, regime_mode="off", score_mode="quality",
                                                       start_date="2006-01", with_div=False, cost_per_side=0.0012)),
        "q_full_bin":  ("⑤ 质量代理 06-26+regime",   dict(N=6, regime_mode="binary", score_mode="quality",
                                                       start_date="2006-01", with_div=False, cost_per_side=0.0012)),
    }
    results = {}
    print(f"{'场景':<30}{'窗口':>10}{'年化':>8}{'最大回撤':>10}{'波动':>8}{'夏普':>7}{'36月滚动中值':>13}{'>=15%窗口':>10}")
    print("-" * 105)
    for key, (label, cfg) in scenarios.items():
        r = run_backtest(u, **cfg)
        results[key] = r
        sd = (cfg.get("start_date", "全") or "全")[:4]
        ed = cfg.get("end_date")
        if ed:
            sd = f"{sd}-{ed[:4]}"
        ry = r["roll3y"]
        print(f"{label:<28}{sd:>10}{r['annualized']*100:>7.1f}%{r['max_drawdown']*100:>9.1f}%"
              f"{r['vol_annual']*100:>7.1f}%{r['sharpe']:>7.2f}{ry['median']*100:>12.1f}%{ry['ge15']:>8}/{ry['n']}")

    # 被动质量+红利 对照（多窗口）
    pas = passive_equal_weight(u, start_date=B, with_div=True, cost_per_side=0.0012)
    results["passive"] = pas
    pas_oos = passive_equal_weight(u, start_date="2014-01", end_date="2018-12",
                                   with_div=False, cost_per_side=0.0012)
    results["passive_oos"] = pas_oos
    pas_early = passive_equal_weight(u, start_date="2006-01", end_date="2014-12",
                                     with_div=False, cost_per_side=0.0012)
    results["passive_early"] = pas_early
    pas_full = passive_equal_weight(u, start_date="2006-01", with_div=False, cost_per_side=0.0012)
    results["passive_full"] = pas_full
    print("-" * 105)
    print(f"{'被动质量+红利(25只等权)':<28}{'2019-26':>10}{pas['annualized']*100:>7.1f}%{pas['max_drawdown']*100:>9.1f}%")
    print(f"{'被动质量+红利(价投)':<28}{'2014-18':>10}{pas_oos['annualized']*100:>7.1f}%{pas_oos['max_drawdown']*100:>9.1f}%")
    print(f"{'被动质量+红利(价投)':<28}{'2006-14':>10}{pas_early['annualized']*100:>7.1f}%{pas_early['max_drawdown']*100:>9.1f}%")
    print(f"{'被动质量+红利(价投)':<28}{'2006-26':>10}{pas_full['annualized']*100:>7.1f}%{pas_full['max_drawdown']*100:>9.1f}%")
    print(f"{'上证指数(全样本06-26)':<28}{'2006-26':>10}{results['full_mom']['idx_annualized']*100:>7.1f}%"
          f"{results['full_mom']['idx_max_drawdown']*100:>9.1f}%")

    json.dump(results, open(os.path.join(WORK, "results_v4.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\nwritten -> results_v4.json")


if __name__ == "__main__":
    main()
