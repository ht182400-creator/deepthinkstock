#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 v4 策略报告 report_v4.html（三阶段样本外 + 全样本 + PM七问）。
数据实时读取 results_v4.json / universe.json。
"""
import json, os

WORK = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(WORK, "results_v4.json"), encoding="utf-8"))
U = json.load(open(os.path.join(WORK, "universe.json"), encoding="utf-8"))


def pct(x):
    return f"{x*100:.1f}%"


def make_chart(curves, title, W=920, H=380):
    padL, padR, padT, padB = 60, 20, 34, 40
    plotW, plotH = W - padL - padR, H - padT - padB
    allv = [v for _, _, _, eq in curves for v in eq]
    ymin, ymax = max(0, min(allv) * 0.98), max(allv) * 1.02
    xmax = max(len(eq) for _, _, _, eq in curves) - 1

    def xp(i):
        return padL + (i / xmax) * plotW

    def yp(v):
        return padT + (1 - (v - ymin) / (ymax - ymin)) * plotH

    grid, yt = "", ""
    for v in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]:
        if ymin <= v <= ymax:
            y = yp(v)
            yt += f'<line x1="{padL}" y1="{y:.1f}" x2="{padL+plotW}" y2="{y:.1f}" stroke="#f0f0f0"/>'
            yt += f'<text x="{padL-8:.1f}" y="{y+4:.1f}" font-size="11" fill="#666" text-anchor="end">{v:.1f}x</text>'
    seen = set()
    xt = ""
    for i, d in enumerate(curves[0][2]):
        y = d[:4]
        if y not in seen:
            seen.add(y)
            xt += f'<line x1="{xp(i):.1f}" y1="{padT}" x2="{xp(i):.1f}" y2="{padT+plotH}" stroke="#eee"/>'
            xt += f'<text x="{xp(i):.1f}" y="{padT+plotH+18:.1f}" font-size="11" fill="#666" text-anchor="middle">{y}</text>'
    polys = ""
    for label, color, dates, eq in curves:
        pts = " ".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(eq))
        polys += f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2"/>'
    lx = padL + 10
    leg = ""
    for label, color, _, _ in curves:
        leg += f'<rect x="{lx}" y="{padT-22}" width="12" height="12" fill="{color}"/>'
        leg += f'<text x="{lx+16}" y="{padT-12}" font-size="11" fill="#333">{label}</text>'
        lx += 30 + len(label) * 7.2
    return (f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica,Arial,sans-serif">'
            f'<rect width="{W}" height="{H}" fill="#fff"/>{grid}{yt}{xt}{polys}{leg}'
            f'<text x="{padL}" y="16" font-size="13" fill="#222" font-weight="bold">{title}</text></svg>')


idx = U["index"]["months"]
idx_dates = [m["date"] for m in idx]
idx_eq = [1.0]
for i in range(1, len(idx_dates)):
    idx_eq.append(idx_eq[-1] * (idx[i]["close"] / idx[i - 1]["close"]))


def slice_idx(a, b):
    i0 = next(i for i, d in enumerate(idx_dates) if d >= a)
    i1 = next((i for i, d in enumerate(idx_dates) if d > b), len(idx_dates))
    return idx_dates[i0:i1], idx_eq[i0:i1]


# 三阶段曲线
ref_main = R["v4_mom_total"]["dates"]
main_curves = [(l, c, R[k].get("dates", ref_main), R[k]["equity_curve"]) for k, l, c in [
    ("v4_mom_total", "v4 纯动量+分红+成本 (21.8%)", "#e4572e"),
    ("passive", "被动质量+红利 (16.3%)", "#17a2b8"),
    ("v4_off", "v4 动量无regime (16.6%)", "#6f42c1"),
    ("v4_binary", "v4 动量+regime全现金 (4.6%)", "#888888"),
    ("v4_mom_only", "v4 纯动量价投 (19.1%)", "#f0a202"),
]]
s0 = next(i for i, d in enumerate(idx_dates) if d >= "2019-01")
main_curves.append(("上证指数 (4.6%)", "#cccccc", idx_dates[s0:], idx_eq[s0:]))
chart_main = make_chart(main_curves, "净值曲线 · 主窗口 2019-01 → 2026-07")

ref_oos = R["oos_mom"]["dates"]
oos_curves = [(l, c, R[k].get("dates", ref_oos), R[k]["equity_curve"]) for k, l, c in [
    ("oos_mom_reg", "动量+regime全现金 (13.2%)", "#f0a202"),
    ("oos_mom", "纯动量(无regime) (4.2%)", "#e4572e"),
    ("passive_oos", "被动质量(价投) (7.5%)", "#17a2b8"),
]]
i0, i1 = slice_idx("2014-01", "2018-12")
oos_curves.append(("上证指数 (5.1%)", "#cccccc", i0, i1))
chart_oos = make_chart(oos_curves, "样本外净值曲线 · 2014-01 → 2018-12")

early_curves = [(l, c, R[k].get("dates", R["early_mom"]["dates"]), R[k]["equity_curve"]) for k, l, c in [
    ("early_reg", "动量+regime全现金 (18.6%)", "#f0a202"),
    ("early_mom", "纯动量(无regime) (10.9%)", "#e4572e"),
    ("passive_early", "被动质量(价投) (4.5%)", "#17a2b8"),
]]
i0, i1 = slice_idx("2006-01", "2014-12")
early_curves.append(("上证指数 (1.6%*)", "#cccccc", i0, i1))
chart_early = make_chart(early_curves, "早期样本外净值曲线 · 2006-01 → 2014-12（*上证全样本）")


def row_html(label, r, hi=False):
    ry = r.get("roll3y", {})
    bg = ' style="background:#fff4ee;"' if hi else ""
    return (f"<tr{bg}><td>{label}</td><td>{pct(r['annualized'])}</td><td>{pct(r['max_drawdown'])}</td>"
            f"<td>{pct(r.get('vol_annual',0))}</td><td>{r.get('sharpe',0):.2f}</td>"
            f"<td>{pct(ry.get('median',0))}</td><td>{ry.get('ge15',0)}/{ry.get('n',0)}</td></tr>")


def table(title, rows_html):
    return (f'<h2>{title}</h2><table><thead><tr><th>配置</th><th>年化</th><th>最大回撤</th>'
            f'<th>年化波动</th><th>夏普</th><th>36月滚动中值</th><th>≥15%窗口</th></tr></thead>'
            f'<tbody>{rows_html}</tbody></table>')


main_rows = ""
for k, label, hi in [
    ("v4_mom_total", "v4 纯动量 + 分红 + 成本 ★", True),
    ("v4_mom_only", "v4 纯动量（价投）", False),
    ("v4_off", "v4 动量无regime", False),
    ("v4_off_N8", "v4 动量无regime N=8", False),
    ("v4_off_6m", "v4 动量6月窗", False),
    ("v4_scaled", "v4 动量+regime缩放0.4", False),
    ("v4_binary", "v4 动量+regime全现金", False),
    ("v4_bin_N8", "v4 动量+regime N=8", False),
    ("v4_A_bin", "v4 近窗(2021-03)regime", False),
    ("v4_total", "v4 总成本(regime)", False),
]:
    main_rows += row_html(label, R[k], hi)
main_rows += row_html("被动质量+红利(25只等权)", R["passive"], False)
main_rows += (f"<tr><td>上证指数</td><td>{pct(R['v4_binary']['idx_annualized'])}</td>"
              f"<td>{pct(R['v4_binary']['idx_max_drawdown'])}</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>")

oos_rows = ""
for k, label, hi in [
    ("oos_mom_reg", "v4 动量+regime全现金 ★(本段最优)", True),
    ("oos_mom", "v4 纯动量(无regime)", False),
    ("oos_mom_n8", "v4 纯动量 N=8", False),
]:
    oos_rows += row_html(label, R[k], hi)
oos_rows += row_html("被动质量+红利(价投)", R["passive_oos"], False)
oos_rows += (f"<tr><td>上证指数</td><td>{pct(R['oos_mom']['idx_annualized'])}</td>"
              f"<td>{pct(R['oos_mom']['idx_max_drawdown'])}</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>")

early_rows = ""
for k, label, hi in [
    ("early_reg", "v4 动量+regime全现金 ★(本段最优)", True),
    ("early_mom", "v4 纯动量(无regime)", False),
]:
    early_rows += row_html(label, R[k], hi)
early_rows += row_html("被动质量+红利(价投)", R["passive_early"], False)
early_rows += (f"<tr><td>上证指数(全样本)</td><td>{pct(R['full_mom']['idx_annualized'])}</td>"
              f"<td>{pct(R['full_mom']['idx_max_drawdown'])}</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>")

full_rows = ""
for k, label, hi in [
    ("full_mom", "全样本 纯动量(价投)", False),
    ("full_regime", "全样本 动量+regime全现金 ★(风险收益最优)", True),
]:
    full_rows += row_html(label, R[k], hi)
full_rows += row_html("被动质量+红利(价投)", R["passive_full"], False)
full_rows += (f"<tr><td>上证指数</td><td>{pct(R['full_mom']['idx_annualized'])}</td>"
              f"<td>{pct(R['full_mom']['idx_max_drawdown'])}</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>")

HTML = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>v4 策略验证报告 · 质量+动量 · 三阶段样本外+全样本</title>
<style>
body{{font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;margin:0;background:#fafafa;color:#222;}}
.wrap{{max-width:1000px;margin:0 auto;padding:32px 24px;}}
h1{{font-size:23px;border-left:5px solid #e4572e;padding-left:12px;margin:0 0 4px;}}
h2{{font-size:18px;margin:30px 0 10px;color:#1a1a1a;border-bottom:2px solid #eee;padding-bottom:6px;}}
.sub{{color:#777;font-size:13px;margin-bottom:18px;}}
table{{border-collapse:collapse;width:100%;font-size:13px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.06);}}
th,td{{border:1px solid #e8e8e8;padding:7px 9px;text-align:right;}}
th{{background:#f2f2f2;font-weight:600;}} td:first-child,th:first-child{{text-align:left;}}
.box{{background:#fff;border:1px solid #e8e8e8;border-radius:8px;padding:18px 20px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,.06);}}
.kpi{{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0;}}
.kpi .c{{flex:1;min-width:150px;background:#f8f8f8;border-radius:8px;padding:14px;text-align:center;}}
.kpi .c .v{{font-size:23px;font-weight:700;}} .kpi .c .l{{font-size:12px;color:#777;margin-top:4px;}}
.warn{{background:#fff8f0;border-left:4px solid #f0a202;padding:12px 16px;margin:14px 0;font-size:13.5px;}}
.good{{background:#f0faf2;border-left:4px solid #2e9e5b;padding:12px 16px;margin:14px 0;font-size:13.5px;}}
.bad{{background:#fdf0f0;border-left:4px solid #d9534f;padding:12px 16px;margin:14px 0;font-size:13.5px;}}
.tag{{display:inline-block;background:#e4572e;color:#fff;border-radius:4px;padding:2px 8px;font-size:12px;margin-right:6px;}}
ul{{line-height:1.7;}} .foot{{color:#999;font-size:12px;margin-top:30px;border-top:1px solid #eee;padding-top:14px;}}
</style></head><body><div class="wrap">

<h1>v4 策略验证报告 · 质量+动量(QMoT) · 三阶段样本外 + 全样本(2006–2026)</h1>
<div class="sub">改造目标：把 v3「买便宜」改为「质量+趋势确认」，验证能否摸到 15–25%。本报告覆盖三段样本外（早期06-14 / 14-18 / 19-26）与 20 年全样本，检验稳健性。数据：universe.json（新浪日线聚合月线，2005 起）。2019-26 含分红/成本；其余窗口用价投（避免以2026股息率套历史）。</div>

<div class="kpi">
<div class="c"><div class="v" style="color:#e4572e">12.3%</div><div class="l">全样本06-26 纯动量(价投)</div></div>
<div class="c"><div class="v" style="color:#2e9e5b">11.1%</div><div class="l">全样本 regime(价投,风险收益最优)</div></div>
<div class="c"><div class="v" style="color:#d9534f">−37%~−46%</div><div class="l">全样本 最大回撤区间</div></div>
<div class="c"><div class="v" style="color:#888">8.4%</div><div class="l">全样本 被动质量(价投)</div></div>
</div>

<div class="bad"><span class="tag">核心结论（修正版）</span><b>经 20 年三阶段验证，15–25% 不是稳健优势，而是时段运气；且与可控回撤不可兼得。</b>
① 全样本 20 年：纯动量 +12.3%、regime +11.1%、被动 +8.4%（价投；含分红各 +~3%/年 → 约 11–15%/年）。<b>无任何机械配置稳健达到 15–25%。</b>
② <b>我此前"regime 永远有害"的判断是被 2019–26 牛市误导</b>：全样本下 regime 收益与纯动量持平（+11.1% vs +12.3%）且回撤更小（−37% vs −46%），是风险收益更优的机械选择。
③ 早期 06–14（含 2008 股灾）：regime +18.6%/−14.8% 大胜纯动量 +10.9%/−45.8%——证明 regime 在崩盘期是盾。
④ 真实可行的"好"结果：regime 过滤的质量动量 ≈ 11–14%/年（含分红），回撤 −37%；远优于上证（+1.6%/−71%），但达不到 15–25%。</div>

<h2>净值曲线 · 主窗口 2019–2026（牛市，纯动量占优）</h2>
<div class="box">{chart_main}</div>
<div class="warn"><b>读图：</b>纯动量（橙/红）在 2019–21 与 2024–25 大幅领先被动（青）；但 regime 全现金（灰）近乎横走——对质量红利组合择时在牛市踏空。这正是上一轮误导我们的片段。</div>

<h2>净值曲线 · 样本外 2014–2018（反转：regime 占优）</h2>
<div class="box">{chart_oos}</div>
<div class="bad"><b>读图：</b>2014–18 纯动量（红）被 2015 股灾与 2018 熊市打爆（−39%）；反是 regime 全现金（橙）+13.2%。同一规则两段优劣反转。</div>

<h2>净值曲线 · 早期样本外 2006–2014（含 2008 股灾，regime 大胜）</h2>
<div class="box">{chart_early}</div>
<div class="good"><b>读图：</b>早期含 2007 疯牛+2008 崩盘+2009 刺激+2011–14 阴跌。regime 全现金（橙）+18.6%、回撤仅 −14.8%，完胜纯动量（红）+10.9%、回撤 −45.8%。崩盘期"转现金"是真正的盾。</div>

{table("情景对比 · 主窗口 2019–2026", main_rows)}
<div class="sub" style="margin-top:6px">注：v4_mom_total/mom_only/passive 含分红近似；regime 系列为择时变体。"≥15%窗口"= 连续36月滚动年化≥15% 的窗口数/总窗口。</div>

{table("情景对比 · 样本外 2014–2018（价投）", oos_rows)}

{table("情景对比 · 早期样本外 2006–2014（价投）", early_rows)}

{table("情景对比 · 全样本 2006–2026 连续（价投）", full_rows)}
<div class="sub" style="margin-top:6px">全样本 20 年：纯动量 +12.3%/−45.8%；regime +11.1%/−37.0%（风险收益最优）；被动 +8.4%/−67.3%；上证 +1.6%/−71.0%。含分红各约 +3%/年。</div>

<h2>PM 七问框架 · 经三阶段样本外修正的结论</h2>
<div class="box"><ol>
<li><b>什么被错误定价了？</b> 质量宇宙内的趋势延续动量溢价——但样本外证明该溢价高度时段依赖（牛市长、崩盘/熊市短甚至为负）。</li>
<li><b>当前价格反映了什么？</b> 2019–26 的强势已部分定价；早期与 14–18 证明该溢价非永续，且有剧烈尾部风险。</li>
<li><b>什么能证明论点？</b> 全样本纯动量 +12.3% > 被动 +8.4% > 上证 +1.6%；regime 在崩盘期显著降回撤。</li>
<li><b>什么能推翻论点？</b> <b>动量崩溃</b>（2008、2015、2018 已实证）；且纯动量最优随时段反转——无稳态 alpha。</li>
<li><b>为什么是现在？</b> 单看 2019–26 曾误导；加 06–14 与 14–18 后结论收敛为"无稳健 15–25%"。</li>
<li><b>什么会改变评级？</b> 若未来再遇动量崩溃且回撤超 −40%，则纯动量降级；regime 因降回撤属性保留为基准机械方案。</li>
<li><b>还缺什么证据？</b> ① 真实 PE/PEG 月度数据；② 更大候选池（当前 25 只幸存者，生存偏差）；③ 把"研究驱动真阿尔法"规则化后做独立回测（见下）。</li>
</ol></div>

<div class="warn"><b>关于"研究驱动真阿尔法 + 多轮回测能否提高稳健性"：</b>
- <b>多轮回测你精选的 3–5 只本身无效</b>——那是后视/幸存者偏差，不能用已知赢家反推策略稳健。
- <b>有效做法是把选股规则前置化、机械化、全历史回溯</b>：例如把"高确信复合股"定义为可量化规则（ROE>20% 持续、FCF/净利>80%、负债率<30%、行业格局稳定、护城河证据），机械应用于全市场全历史（而非你挑的 3–5 只），再回测。若此"基本面质量复合因子"在全样本跑赢动量/被动且回撤更低，才是稳健 alpha——且可检验、非后视。
- 其局限：基本面质量因子峰值收益未必高于动量，优势在<b>更低回撤 + 更稳复利</b>。下一可行步即构建该因子回测。</div>

<h2>10 万账户行动建议（修正版）</h2>
<div class="box"><ul>
<li><b>现实最优机械方案：</b> <b>regime 过滤的质量动量</b>（全样本 +11%/年价投、含分红 ~14%、回撤 −37%）——风险收益优于纯动量，且崩盘期有盾。或<b>被动质量+红利</b>（更简单、零认知负担，全样本 +8.4% 价投）。</li>
<li><b>若坚持 15–25% 且能扛 −46% 回撤：</b> 仅"纯 12 月动量倾斜（无 regime）"，全样本 +12.3% 价投（含分红 ~15%）；须明确接受动量崩溃与「不追高」张力。</li>
<li><b>不建议：</b> 以为 2019–26 的 21.8% 可外推；任何"只看牛市片段"的结论。</li>
<li><b>20–25% 上沿：</b> 须研究驱动真阿尔法，且必须<b>规则化后全历史回测</b>（非精选个例），才可能提高稳健性。</li>
</ul></div>

<div class="foot">本报告由 backtest_v4.py 实时计算生成，数字可追溯至 results_v4.json。数据来源：新浪财经日线聚合月线（价格序列）；tdx-connector 会话中不可用、东方财富被沙箱拦截。<b>重要偏差提示：</b>候选池为 2026 年筛选的优质幸存者（生存偏差），各段天然偏向"活下来且仍优质"的标的，应视为对策略机制的乐观上界检验；早期窗口受数据起点(2005)与 warmup 限制，实际持仓约 2007 起。<b>本报告仅供参考，不构成个人投资建议。</b></div>

</div></body></html>'''

open(os.path.join(WORK, "report_v4.html"), "w", encoding="utf-8").write(HTML)
print("written -> report_v4.html | bytes", len(HTML))
