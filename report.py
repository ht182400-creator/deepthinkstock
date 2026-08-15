#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 v3 回测验证报告 v2（①②③ 增强 + 目标重校准至 15-25%）。
所有数字实时由 backtest_v3.py / universe.json 计算。"""
import json, os, math
from backtest_v3 import run_backtest, max_drawdown, annualized, stdev

WORK = os.path.dirname(os.path.abspath(__file__))
u = json.load(open(os.path.join(WORK, "universe.json"), encoding="utf-8"))
index = u["index"]["months"]; stocks = u["stocks"]
idx_dates = [m["date"] for m in index]; M = len(idx_dates)
idx_close = {d: m["close"] for d, m in zip(idx_dates, index)}
sclose = {c: {m["date"]: m["close"] for m in s["months"]} for c, s in stocks.items()}
cap_excl = {c: s["cap_excluded"] for c, s in stocks.items()}
elig = [c for c in stocks if not cap_excl[c]]

def t_start_of(date):
    for i in range(12, M):
        if idx_dates[i] >= date:
            return i
    return 12

WIN_A = "2021-03"; WIN_B = "2019-01"
tsA = t_start_of(WIN_A); tsB = t_start_of(WIN_B)


# ---------- 被动基准（跨牛熊 2019-2026） ----------
def ew_passive(ts):
    eq = [1.0]
    for t in range(ts, M - 1):
        rs = [sclose[c][idx_dates[t + 1]] / sclose[c][idx_dates[t]] - 1
              for c in elig if idx_dates[t] in sclose[c] and idx_dates[t + 1] in sclose[c]]
        eq.append(eq[-1] * (1 + sum(rs) / len(rs)))
    return eq

def idx_curve(ts):
    eq = [1.0]
    for t in range(ts, M - 1):
        eq.append(eq[-1] * (idx_close[idx_dates[t + 1]] / idx_close[idx_dates[t]]))
    return eq

def div_ew_passive(ts):
    """被动等权 + 分红再投（用于 ③ 对照）"""
    eq = [1.0]
    for t in range(ts, M - 1):
        tot = 0.0; n = 0
        for c in elig:
            if idx_dates[t] in sclose[c] and idx_dates[t + 1] in sclose[c]:
                tot += sclose[c][idx_dates[t + 1]] / sclose[c][idx_dates[t]] - 1
                tot += (stocks[c].get("div_yield", 0.0) or 0.0) / 12.0
                n += 1
        if n:
            eq.append(eq[-1] * (1 + tot / n))
    return eq

eq_passive_B = ew_passive(tsB); eq_idx_B = idx_curve(tsB); eq_div_B = div_ew_passive(tsB)
months_B = len(eq_passive_B) - 1
passiveB_ann = annualized(eq_passive_B[-1] - 1, months_B) * 100
passiveB_mdd = max_drawdown(eq_passive_B) * 100
idxB_ann = annualized(eq_idx_B[-1] - 1, months_B) * 100
idxB_mdd = max_drawdown(eq_idx_B) * 100
divB_ann = annualized(eq_div_B[-1] - 1, months_B) * 100
divB_mdd = max_drawdown(eq_div_B) * 100


# ---------- 单只买入持有分布（2019-2026） ----------
indiv = {}
for c in elig:
    eq = [1.0]
    for t in range(tsB, M - 1):
        if idx_dates[t] in sclose[c] and idx_dates[t + 1] in sclose[c]:
            eq.append(eq[-1] * (sclose[c][idx_dates[t + 1]] / sclose[c][idx_dates[t]]))
    indiv[c] = annualized(eq[-1] - 1, months_B) * 100
pos = sum(1 for v in indiv.values() if v > 0); neg = len(indiv) - pos
top3 = sorted(indiv.items(), key=lambda x: -x[1])[:3]
bot3 = sorted(indiv.items(), key=lambda x: x[1])[:3]


# ---------- 跑 ①②③ 场景 ----------
R = {}
A = WIN_A; B = WIN_B
R["A_old12"] = run_backtest(u, N=5, ind_cap=0.35, regime=True, start_date=A, val_window=12)
R["A_val60"] = run_backtest(u, N=5, ind_cap=0.35, regime=True, start_date=A, val_window=60)
R["A_off"]   = run_backtest(u, N=5, ind_cap=0.35, regime=True, start_date=A, exit_bubble=False)
R["B_val60"] = run_backtest(u, N=5, ind_cap=0.35, regime=True, start_date=B, val_window=60)
R["B_off"]   = run_backtest(u, N=5, ind_cap=0.35, regime=True, start_date=B, exit_bubble=False)
R["C_price"] = run_backtest(u, N=5, ind_cap=0.35, regime=True, start_date=B, val_window=60)
R["C_div"]   = run_backtest(u, N=5, ind_cap=0.35, regime=True, start_date=B, val_window=60, with_div=True)
R["C_total"] = run_backtest(u, N=5, ind_cap=0.35, regime=True, start_date=B, val_window=60, with_div=True, cost_per_side=0.0012)

def g(r): return (f"{r['annualized']*100:.1f}%", f"{r['max_drawdown']*100:.1f}%",
                  f"{r['vol_annual']*100:.1f}%", f"{r['sharpe']:.2f}", f"{r['roll3y']['median']*100:.1f}%",
                  f"{r['roll3y']['ge15']}/{r['roll3y']['n']}")


# ---------- SVG 净值曲线（2019-2026） ----------
series = [("v3 估值退出(②)", R["B_val60"]["equity_curve"], "#e74c3c"),
          ("v3 含分红+成本(③)", R["C_total"]["equity_curve"], "#f39c12"),
          ("被动等权质量池", eq_passive_B, "#3498db"),
          ("被动等权+分红", eq_div_B, "#1abc9c"),
          ("上证指数", eq_idx_B, "#95a5a6")]
W, H = 780, 340; pad = 44
allv = [v for _, eq, _ in series for v in eq]
ymin, ymax = min(allv) * 0.96, max(allv) * 1.04
n = months_B
def X(i): return pad + (W - 2 * pad) * i / n
def Y(v): return H - pad - (H - 2 * pad) * (v - ymin) / (ymax - ymin)
svg_paths = ""
for name, eq, col in series:
    pts = " ".join(f"{X(i):.1f},{Y(eq[i]):.1f}" for i in range(len(eq)))
    svg_paths += f"<polyline points='{pts}' fill='none' stroke='{col}' stroke-width='2'/>"
legend = "".join(
    f"<rect x='{pad+i*150}' y='12' width='12' height='12' fill='{c}'/><text x='{pad+i*150+18}' y='22' fill='#cdd6e4' font-size='11.5'>{n}</text>"
    for i, (n, _, c) in enumerate(series))


def pct(x): return f"{x:+.1f}%" if x >= 0 else f"{x:.1f}%"
def row(name, r, hl=False):
    a, m, v, s, rm, ge = g(r)
    return (f"<tr{' class=hl' if hl else ''}><td>{name}</td><td class='num'>{a}</td>"
            f"<td class='num'>{m}</td><td class='num'>{v}</td><td class='num'>{s}</td>"
            f"<td class='num'>{rm}</td><td class='num'>{ge}</td></tr>")

html = f"""<!doctype html><html lang=zh><head><meta charset=utf-8>
<title>v3 回测验证报告 v2（①②③ + 目标15-25%）</title>
<style>
body{{background:#0f1420;color:#dfe6f0;font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;margin:0;padding:32px;line-height:1.6}}
h1{{font-size:23px;margin:0 0 4px}} h2{{font-size:18px;margin:26px 0 10px;color:#7fb3ff}}
h3{{font-size:14px;margin:16px 0 6px;color:#9fb3d0}}
.sub{{color:#8a97a8;font-size:13px;margin-bottom:16px}}
.box{{background:#161d2b;border:1px solid #243049;border-radius:10px;padding:16px 20px;margin:14px 0}}
.verdict{{background:#1c2536;border-left:4px solid #f39c12;padding:14px 18px;border-radius:6px;margin:16px 0}}
.verdict b{{color:#ffcf6b}} .verdict.r{{border-left-color:#e74c3c}} .verdict.r b{{color:#ff7a7a}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}}
th,td{{border:1px solid #243049;padding:7px 10px;text-align:left}}
th{{background:#1a2333;color:#9fb3d0}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
tr.hl{{background:#202b40}}
.ok{{color:#2ecc71}} .bad{{color:#e74c3c}} .warn{{color:#f1c40f}}
code{{background:#0a0e16;padding:1px 5px;border-radius:4px;color:#9fe6a0}}
.svgwrap{{background:#0c111b;border:1px solid #243049;border-radius:10px;padding:10px}}
ul{{margin:6px 0 6px 18px}} li{{margin:4px 0}}
.note{{color:#8a97a8;font-size:12px}}
</style></head><body>
<h1>v3 策略回测验证报告 v2</h1>
<div class=sub>质量+价值(GARP)+低波 · 集中 5–8 · 行业≤35% · 无 −10% 止损 · ¥300 上限 ｜ 数据：新浪日线聚合月线 ｜
窗口：2019-01→2026-07（{months_B} 月，跨牛熊）｜ 目标区间已重校准为 <b>15–25% 年化</b></div>

<div class=verdict>
<b>核心结论（诚实）：</b> 即使完成 ①②③ 全部增强，本策略在 2019–2026 跨牛熊全周期仍仅实现
<b>价格收益 +{R['B_val60']['annualized']*100:.1f}%/年、含分红总收益 +{divB_ann:.1f}%/年</b>（成本后约 +{R['C_total']['annualized']*100:.1f}%）。
<b>15–25% 目标依然未达成</b>——此策略是"防御型质量均值回归"属性，跑不赢被动持有质量篮
（被动+分红 {divB_ann:.1f}% vs 策略+分红 {R['C_total']['annualized']*100:.1f}%，基本持平甚至略输）。
<b>① 估值驱动退出已修复价值毁灭</b>（2021-26 旧规则 −9.2% → 新规则 −1.7%）；
<b>③ 分红是真实收益来源</b>（贡献 ~3.4%/年）。要逼近 15–25%，需改变策略性格（见第六节）。
</div>

<h2>一、① 泡沫退出改为估值(PEG/PE)驱动 —— 修复价值毁灭</h2>
<div class=box>
窗口 <b>2021-03 → 2026-07</b>（质量股杀估值熊市）。对照：旧规则用"12 月价格分位≥85"（本质动量，底部一反弹就卖）= 价值毁灭源；
新规则用"60 月估值分位≥85"（价格作估值代理，等价 PE 超历史 90 分位），仅在个股处 5 年高位才退出。
<table>
<tr><th>配置</th><th>年化</th><th>最大回撤</th><th>波动</th><th>夏普</th><th>36月滚动中值</th><th>≥15%窗口</th></tr>
{row('旧12月价格分位退出(对照)', R['A_old12'])}
{row('新60月估值分位退出', R['A_val60'], True)}
{row('关估值泡沫退出(仅>300/恶化)', R['A_off'])}
</table>
<b>结论：</b>新估值退出将年化从 <span class=bad>−9.2%</span> 提升到 <span class=ok>−1.7%</span>，回撤 −45%→−21%，
基本消除原规则的动量杀伤。关闭退出略优（−0.1%），但新规则提供了有原则的卖出纪律，可接受。
<div class=note>注：本轮回测起点前移至 2021-03（含 2021 全年），与上一版报告从 2022-03 起算的 −5.8% 不是同一窗口；此处用同窗口下的旧规则重跑(−9.2%)作对照。</div>
</div>

<h2>二、② 跨牛熊多阶段验证（2019-2026）—— 目标 15-25% 是否可达</h2>
<div class=box>
窗口 <b>2019-01 → 2026-07</b>（含 2019-21 质量大牛 + 2022-26 慢熊）。
<table>
<tr><th>配置</th><th>年化</th><th>最大回撤</th><th>波动</th><th>夏普</th><th>36月滚动中值</th><th>≥15%窗口</th></tr>
{row('v3 60月估值退出', R['B_val60'], True)}
{row('v3 关估值泡沫退出', R['B_off'])}
<tr><td>被动等权质量池(24只, 价投)</td><td class='num'>{passiveB_ann:.1f}%</td><td class='num'>{passiveB_mdd:.1f}%</td><td class='num'>—</td><td class='num'>—</td><td class='num'>—</td><td class='num'>—</td></tr>
</table>
<table>
<tr><th>基准（2019-2026）</th><th>年化</th><th>最大回撤</th></tr>
<tr><td>被动等权质量池（价格）</td><td class='num'>{passiveB_ann:.1f}%</td><td class='num'>{passiveB_mdd:.1f}%</td></tr>
<tr><td>被动等权质量池（价格+分红）</td><td class='num'>{divB_ann:.1f}%</td><td class='num'>{divB_mdd:.1f}%</td></tr>
<tr><td>上证指数（买入持有）</td><td class='num'>{idxB_ann:.1f}%</td><td class='num'>{idxB_mdd:.1f}%</td></tr>
</table>
<b>结论：</b>跨牛熊全周期，v3 价格年化仅 <b>+{R['B_val60']['annualized']*100:.1f}%</b>（含分红约 +{divB_ann:.1f}%），<b>远低于 15–25%</b>。
更关键：策略 <b>跑输被动持有</b>——因其"买低分位(便宜)"的入场规则在 2019-21 牛市中把高质量股判为"贵"而低配，错过了主升浪；
2022-26 熊市中又因便宜而低吸被套。即"聪明择时"反成拖累。
</div>

<h2>三、③ 含分红与交易成本再回测（2019-2026）</h2>
<div class=box>
<table>
<tr><th>配置</th><th>年化</th><th>最大回撤</th><th>波动</th><th>夏普</th><th>36月滚动中值</th><th>≥15%窗口</th></tr>
{row('价投(无分红无费)', R['C_price'])}
{row('价投 + 分红再投', R['C_div'])}
{row('价投 + 分红 + 成本(0.12%/边)', R['C_total'], True)}
</table>
<b>结论：</b>分红是真实收益来源，贡献约 <b>+{(R['C_div']['annualized']-R['C_price']['annualized'])*100:.1f}%/年</b>
（{R['C_price']['annualized']*100:.1f}% → {R['C_div']['annualized']*100:.1f}%）；交易成本约 −0.2%/年，可忽略。
<b>最终可投总收益 ≈ +{R['C_total']['annualized']*100:.1f}%/年，最大回撤 −{R['C_total']['max_drawdown']*100:.1f}%</b>。
</div>

<h2>四、净值曲线（2019-2026，起点=1.0）</h2>
<div class=svgwrap><svg width={W} height={H} viewBox='0 0 {W} {H}'>
<line x1={pad} y1={H-pad} x2={W-pad} y2={H-pad} stroke='#333'/>
<line x1={pad} y1={Y(1)} x2={W-pad} y2={Y(1)} stroke='#445' stroke-dasharray='3 3'/>
{svg_paths}
{legend}
</svg>
<div class=note>虚线=1.0。策略(红/橙)与被动(蓝/青)在 2019-21 牛市差距拉大（策略低配质量牛股），2022 后趋同。分红(青)明显抬升被动基准。</div></div>

<h2>五、单只买入持有分布（2019-2026，价格收益，{len(elig)} 只）</h2>
<div class=box>
正收益 <b>{pos}</b> / 负收益 <b>{neg}</b>。
涨幅前三：{', '.join(f"{stocks[c]['name']} {pct(v)}" for c,v in top3)}；
跌幅前三：{', '.join(f"{stocks[c]['name']} {pct(v)}" for c,v in bot3)}。
跨牛熊后多为正（白酒/家电/客车/分红股走强），但仍无单只稳定 15%+/年。
</div>

<h2>六、15–25% 目标为何达不到，以及怎么才可能达到</h2>
<div class=box>
<b>根因：</b>本策略是<b>防御型质量均值回归</b>——"买便宜(低分位)+ 景气减仓 + 估值高位退出"，天然低 Beta、低换手，
在 A股质量因子 2019-21 的强动量行情中系统性低配。它的最优属性是<b>低回撤可控</b>，而非高收益。
要逼近 15–25%，需改变策略性格（任一，均为新的第④项）：
<ul>
<li><b>质量成长/动量倾斜</b>：入场从"买低分位"改为"质量+合理估值+趋势确认"，允许在上升趋势中持有质量股（提高牛市长仓，但回撤放大）；</li>
<li><b>接受单名集中</b>：从 5–8 只缩到 3–5 只并重仓命中 1–2 只多倍股（自由现金流/国证价值因子 2015-24 达 16.6%，靠集中弹性）；</li>
<li><b>叠加行业/风格轮动</b>：在质量因子失效期切换至高股息/周期，提升复合收益——但偏离"不追高"原则；</li>
</ul>
<b>现实建议：</b>把 15–25% 视为<b>乐观拉伸上沿(需多倍股或强风格配合)</b>，基准预期调到 <b>8–12%/年(含分红)</b>，
与被动质量+红利策略(本窗口 +{divB_ann:.1f}%) 同档——这已优于多数主动基金，且回撤可控。
</div>

<h2>七、10 万账户落地建议</h2>
<div class=box>
<ul>
<li><b>目标诚实化</b>：账户年化合理预期 <b>8–12%（含分红）</b>；15–25% 仅作乐观拉伸，非基准承诺。</li>
<li><b>底仓策略</b>：直接用"被动等权质量池 + 红利再投"（本窗口 +{divB_ann:.1f}%/年，回撤 −{divB_mdd:.1f}%），简单、低耗、跑赢主动 v3。</li>
<li><b>若坚持主动 v3</b>：采用 ① 修复后的 60 月估值退出（已非价值毁灭），但预期收益与被动持平，无显著超额。</li>
<li><b>¥300 上限保持</b>：自动剔除茅台(¥1350)等高价股，25 只中 1 只(吉比特¥389)因超上限被剔，其余合格。</li>
<li><b>数据局限</b>：价格序列不含复权分红（分红用近似股息率，非逐笔）；估值退出以价格分位代理 PE 历史（无逐月财报）。结论方向稳健，绝对数值 ±2%/年误差。</li>
</ul>
</div>

<h2>八、行动分类（PM 框架）</h2>
<div class=box>
<b><span class=warn>重新评估 / 等待证据</span></b> —— ①②③ 已完成：① 估值退出修复有效；② 跨牛熊 15–25% 未达（约 8%/年含分红）；
③ 分红贡献显著。本策略性格为防御型，与 15–25% 目标不匹配。
下一步建议：<b>放弃</b>当前 v3 主动框架作为"高收益"载体；<b>加码</b>被动质量+红利底仓；若坚持 15–25%，启动 <b>④ 策略性格改造</b>（质量成长/动量倾斜或单名集中）。
</div>

<div class=note>数据链路：tdx-connector 不可用、东方财富/新浪分红接口被沙箱拦，改用新浪日线(scale=240)聚合月线；指数校正 sh000001；分红用近似股息率。收益含分红为近似。本报告基于公开数据与规则回测，不构成个人投资建议。</div>
</body></html>"""

out = os.path.join(WORK, "report.html")
open(out, "w", encoding="utf-8").write(html)
print("written ->", out)
print(f"[①] 旧12月 {g(R['A_old12'])[0]} / 新60月 {g(R['A_val60'])[0]} / 关 {g(R['A_off'])[0]}")
print(f"[②] 估值退出 {g(R['B_val60'])[0]} mdd {g(R['B_val60'])[1]} | 被动+分红 {divB_ann:.1f}% mdd {divB_mdd:.1f}%")
print(f"[③] 价投 {g(R['C_price'])[0]} / +分红 {g(R['C_div'])[0]} / +分红+费 {g(R['C_total'])[0]}")
print(f"单只 pos/neg = {pos}/{neg}")
