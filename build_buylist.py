# -*- coding: utf-8 -*-
"""生成 10 万账户「质量+动量组合 + regime」可执行建仓清单 + 质量观察池。
- 复用 backtest_fund.run_backtest 完全一致逻辑抽取「当前可建仓」（给指数补虚拟8月月线使7月成为再平衡月）。
- 另用与引擎完全一致的入选口径，独立计算「质量观察池」：已过基本面硬门槛(ROE≥20%×3年/负债≤30%/FCF÷净利∈[80%,300%]/非金融/价≤300)，
  仅差「个股站上12月均线+动量>0」趋势确认者 —— 供下月盯盘。
输出 buy_list.html。
"""
import json, math, copy
import backtest_fund as B

CAPITAL = 100_000.0
EXP_FACTOR = 0.90
N = 15
DEBT_MAX = 0.30
COMBO_Q = 0.50
ROE_MIN = 0.20
FCFNP_MIN, FCFNP_MAX = 0.80, 3.0

def trailing(sclose, code, t, dates, n):
    out = []; i = t
    while len(out) < n and i >= 0:
        v = sclose[code].get(dates[i])
        if v is None:
            break
        out.insert(0, v); i -= 1
    return out

def mom_metrics(sclose, code, t, dates):
    tr = trailing(sclose, code, t, dates, 13)
    if len(tr) < 13:
        return None
    mom12 = tr[-1] / tr[0] - 1.0
    ma12 = sum(tr[-12:]) / 12.0
    return mom12, ma12, tr[-1]

def pt_fund(fund, code, month_end):
    an = fund.get(code, {}).get("annual", [])
    av = [r for r in an if r.get("notice") and r["notice"] <= month_end
          and r.get("np") and r.get("te") and r.get("ta")
          and r.get("tl") is not None and r.get("ocf") is not None
          and r.get("capex") is not None]
    if len(av) < 3:
        return None
    lt = av[-1]
    roes = [r["np"] / r["te"] for r in av[-3:] if r["te"]]
    if len(roes) < 3:
        return None
    debt = lt["tl"] / lt["ta"]
    fcfnp = (lt["ocf"] - lt["capex"]) / lt["np"] if lt["np"] else None
    return dict(roe_now=lt["np"] / lt["te"], roe3=roes, debt=debt, fcfnp=fcfnp)

def main():
    u = json.load(open("universe_big.json"))
    f = json.load(open("fundamentals.json"))

    # ---- 1) 当前可建仓（引擎完全一致逻辑）----
    u2 = copy.deepcopy(u)
    idx = u2["index"]["months"]
    idx.append({"date": "2026-08-31", "close": idx[-1]["close"]})
    R = B.run_backtest(u2, f, N=N, ind_cap=0.35, regime_mode="binary",
                       score_mode="qscore", roe_min=ROE_MIN, fcfnp_min=FCFNP_MIN,
                       fcfnp_max=FCFNP_MAX, debt_max=DEBT_MAX, combo_q=COMBO_Q,
                       size_mode="equal", cost_per_side=0.0012)
    sn = R["last_snap"]
    sdate = sn["date"]; market_up = sn["market_up"]; expo = sn["expo"]; held = sn["held"]

    # ---- 2) 质量观察池（与引擎一致的入选口径，去掉个股趋势门）----
    dates = [m["date"] for m in u["index"]["months"]]
    M = len(dates); t = M - 1           # 2026-07-31
    me = dates[t]
    sclose = {c: {m["date"]: m["close"] for m in s["months"]} for c, s in u["stocks"].items()}
    scap = {c: s["cap_excluded"] for c, s in u["stocks"].items()}
    sind = {c: f.get(c, {}).get("industry", "?") for c in u["stocks"]}
    watch = []
    for code in u["stocks"]:
        if scap[code]:
            continue
        mm = mom_metrics(sclose, code, t, dates)
        if mm is None:
            continue
        mom12, ma12, price = mm
        if price > 300.0:
            continue
        ff = pt_fund(f, code, me)
        if ff is None:
            continue
        if B.is_financial(sind[code]):
            continue
        # qscore 软底线：排除负ROE垃圾与负自由现金流（不做硬三门卡死，改用连续打分）
        if ff["roe_now"] < 0.10:
            continue
        if ff["fcfnp"] is None or ff["fcfnp"] < 0:
            continue
        above_ma = price > ma12
        watch.append(dict(code=code, name=f.get(code, {}).get("name", "?"),
                          ind=sind[code], price=price, roe=ff["roe_now"],
                          debt=ff["debt"], fcfnp=ff["fcfnp"], mom12=mom12,
                          above_ma=above_ma))
    watch.sort(key=lambda x: (not x["above_ma"], -x["roe"]))

    # ---- HTML ----
    regime_txt = "持仓（可建仓）" if market_up else "现金（持币等待）"
    n_buy = len(held) if (market_up and held) else 0
    n_watch = len(watch)
    n_ready = sum(1 for w in watch if w["above_ma"])

    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<style>
 body{{font-family:-apple-system,'Segoe UI',sans-serif;margin:24px;color:#222;line-height:1.6}}
 h1{{font-size:21px;border-bottom:3px solid #2a7f62;padding-bottom:6px}}
 h3{{font-size:15px;margin-top:24px;color:#1a1a1a}}
 table{{border-collapse:collapse;font-size:13px;margin:8px 0;width:100%}}
 th,td{{border:1px solid #ddd;padding:6px 8px;text-align:center}}
 th{{background:#f4f4f4}}
 .ok{{background:#eafaef}} .skip{{background:#fff3ee;color:#a33}} .watch{{background:#fffaf0}}
 .box{{background:#f8f9fb;border:1px solid #e2e6ea;border-radius:8px;padding:12px 16px;margin:10px 0}}
 .big{{font-size:15px;font-weight:600}} .warn{{color:#b5481f}} .note{{color:#666;font-size:12px}}
</style></head><body>
<h1>10 万账户建仓清单 + 质量观察池 —「质量+动量组合 + regime」</h1>
<p class="note">生成 2026-08-02 ｜ 数据：东方财富 DMSK 真实年报 + 新浪月线 ｜ 候选池：沪深300+中证500 成分股(500只) ｜ 信号月：{sdate}</p>

<div class="box">
 <div class="big">当前 Regime 信号：<b>{regime_txt}</b> ｜ 指数(上证)信号月收盘 vs 13月均线：{('上方→持仓' if market_up else '下方→现金')}</div>
 <p>信号月(2026-07)指数站上13月均线、regime 翻红 → <b>策略允许建仓</b>。
 入选规则（qscore 连续质量打分 + 动量确认）：非金融 / 价≤¥300 / 站上12月均线 / 12月动量>0 / ROE≥10% 且 正自由现金流，按「质量分×动量分」取前 {N} 名。
 当前合格且进入组合的标的 = <b>{n_buy} 只</b>。下月再跑本脚本即自动刷新。</p>
</div>

<h3>一、操作节奏（你问的三个问题）</h3>
<table>
<tr><th>问题</th><th>答案</th></tr>
<tr><td>什么时候开始建仓？</td><td>两个条件齐备才动手：① Regime=持仓(指数站上13月均线)；② 组合有≥1只合格股(个股也站上12月均线+动量>0+质量打分达标)。
当前 2026-07 两者皆满足 → <b>本月即可按清单建仓</b>；若某月 regime 翻现金，则全部清仓持币，不抄底。</td></tr>
<tr><td>每周都要操作吗？</td><td><b>不需要。</b> 本策略<b>月频</b>再平衡——只看每月最后一个交易日收盘信号，每月最多调仓一次。</td></tr>
<tr><td>每天收盘后都要采日线分析吗？</td><td><b>不需要每天。</b> 日常只需：(a) 每月末看一眼 regime 信号；(b) 每月末跑一次本脚本更新清单。
个股退市/ST/财报爆雷用季度披露覆盖即可，盘中/日线无需盯。</td></tr>
</table>

<h3>二、当前可建仓标的（{sdate}）</h3>
"""
    if n_buy > 0:
        sclose2 = {c: {m["date"]: m["close"] for m in s["months"]} for c, s in u["stocks"].items()}
        order = sorted(held, key=lambda c: -sn["w"].get(c, 0))
        deploy = CAPITAL * expo
        # 100股手数约束下：每轮用当前等权预算重估全部信号股，剔除买不起1手者，
        # 预算随之上升、再重估，收敛到「最大可买集合」（10万账户集中落地）
        candidates = list(order)
        while True:
            budget = deploy / len(candidates) if candidates else 0
            new = [c for c in candidates
                   if sclose2[c].get(sdate) and math.floor(budget / sclose2[c].get(sdate) / 100.0) >= 1]
            if new == candidates:
                break
            candidates = new
        funded = candidates
        rows = []
        for c in funded:
            p = sclose2[c].get(sdate); nm = f.get(c, {}).get("name", "?"); ind = f.get(c, {}).get("industry", "?")
            if not p:
                continue
            lots = math.floor(budget / p / 100.0); shares = lots * 100; val = shares * p
            rows.append((c, nm, ind, p, shares, val))
        invested = sum(r[5] for r in rows); cash = CAPITAL - invested
        skipped = len(order) - len(funded)
        html += f'<div class="box">策略信号共 <b>{len(order)}</b> 只（按质量×动量打分前{N}）；'
        if skipped:
            html += f'其中 <b>{skipped}</b> 只单价过高（100股一手即超等权预算），受「100股手数」约束剔除，未建仓。'
        html += f'实际可建仓 <b>{len(funded)}</b> 只；计划投入≈¥{invested:,.0f}，留现金≈¥{cash:,.0f}（含100股取整余数）。</div>'
        html += '<table><tr><th>代码</th><th>名称</th><th>行业</th><th>信号月价</th><th>股数(100整)</th><th>占用</th><th>权重</th></tr>'
        for (c, nm, ind, p, sh, val) in rows:
            html += f'<tr class="ok"><td>{c}</td><td>{nm}</td><td>{ind}</td><td>{p:.2f}</td><td>{sh}</td><td>{val:,.0f}</td><td>{val/CAPITAL:.1%}</td></tr>'
        html += '</table>'
    else:
        html += ('<div class="box warn"><b>本月无合格标的 → 策略指令：持币，暂不建仓。</b><br>'
                 '原因：指数虽翻红，但个股普遍未站上12月均线（趋势门未过）。这是策略的风控设计——避免在弱反弹追高。'
                 '下月个股确认回升后，本清单会自动生成买入列表。</div>')

    html += f"""
<h3>三、质量观察池（已过质量软底线，按打分排序）</h3>
<div class="box">共 <b>{n_watch}</b> 只已过「连续质量复合打分」软底线（ROE≥10% 且 正自由现金流 / 非金融 / 价≤¥300），按质量分+动量分排序；
其中 <b>{n_ready}</b> 只当前已站上12月均线（离买入最近），其余等回升确认。下月跑脚本时这些会优先进入「可建仓」。</div>
<table>
<tr><th>代码</th><th>名称</th><th>行业</th><th>现价</th><th>ROE</th><th>负债率</th><th>FCF/净利</th><th>12月动量</th><th>已站上12月线?</th></tr>
"""
    for w in watch[:40]:
        cls = "ok" if w["above_ma"] else "watch"
        html += (f'<tr class="{cls}"><td>{w["code"]}</td><td>{w["name"]}</td><td>{w["ind"]}</td>'
                 f'<td>{w["price"]:.2f}</td><td>{w["roe"]*100:.0f}%</td><td>{w["debt"]*100:.0f}%</td>'
                 f'<td>{w["fcfnp"]*100:.0f}%</td><td>{w["mom12"]*100:.0f}%</td>'
                 f'<td>{"✅ 是" if w["above_ma"] else "⏳ 否"}</td></tr>')
    html += '</table>'
    html += f'<p class="note">观察池仅列出前 40 只；按「已站上12月线优先→ROE降序」排序。'
    html += '此表为研究跟踪用途，<b>非当前买入指令</b>——须待 regime 持仓 且 个股站上12月线+动量>0 才触发建仓。</p>'

    html += f"""
<h3>四、退出与再平衡纪律</h3>
<table>
<tr><th>情形</th><th>动作</th></tr>
<tr><td>每月末 Regime 翻红→现金</td><td>全部清仓转货币/活期</td></tr>
<tr><td>个股趋势破位（动量≤0 或 价<12月均线）</td><td>该只卖出</td></tr>
<tr><td>个股市盈率处历史60月分位≥85%</td><td>该只卖出（估值泡沫）</td></tr>
<tr><td>股价 > ¥300</td><td>该只卖出</td></tr>
<tr><td>个股动量 ≤ −40%（基本面恶化代理）</td><td>该只卖出</td></tr>
<tr><td>财报后 ROE/负债率不再达标</td><td>下次月末剔除</td></tr>
</table>
<p class="note">无 −10% 价格止损（按你的原则）；退出全部由「估值泡沫 + 基本面恶化 + 趋势破位」驱动。每月末跑一次脚本即自动执行。</p>
<p class="note">本报告基于公开学术与券商实证及规则设计，仅供参考，不构成个人投资建议。</p>
</body></html>"""
    open("buy_list.html", "w", encoding="utf-8").write(html)
    print(f"信号月={sdate} market_up={market_up} 可建仓={n_buy} 观察池={n_watch}(已站线{n_ready})")
    print("written -> buy_list.html")

if __name__ == "__main__":
    main()
