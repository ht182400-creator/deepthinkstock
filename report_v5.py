#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_v5.py —— ⑤ 质量复利代理 vs 动量 vs 被动 的稳健性对比（回答"研究驱动真阿尔法能否提升稳健性"）。

读取 results_v4.json，生成 report_v5.html：
  1) 四窗口 × (动量off / 动量regime / 质量off / 质量regime / 被动) 对比表
  2) 全样本 2006-26 净值曲线对比（动量regime / 质量regime / 被动 / 纯动量）
  3) PM 七问框架下的结论与诚实目标重校准
"""
import json, os, math

WORK = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(WORK, "results_v4.json"), encoding="utf-8"))

WINDOWS = [
    ("主窗 2019-26（牛市+回调）", "passive", [
        ("动量 无regime", "v4_off"), ("动量 regime全现金", "v4_binary"),
        ("质量 无regime", "q_main_off"), ("质量 regime", "q_main_bin"),
        ("被动质量+红利", "passive")]),
    ("样本外 2014-18（动量崩塌）", "passive_oos", [
        ("动量 无regime", "oos_mom"), ("动量 regime全现金", "oos_mom_reg"),
        ("质量 无regime", "q_oos_off"), ("质量 regime", "q_oos_bin"),
        ("被动质量+红利", "passive_oos")]),
    ("早期 2006-14（含08崩）", "passive_early", [
        ("动量 无regime", "early_mom"), ("动量 regime全现金", "early_reg"),
        ("质量 无regime", "q_early_off"), ("质量 regime", "q_early_bin"),
        ("被动质量+红利", "passive_early")]),
    ("全样本 2006-26（诚实整段）", "passive_full", [
        ("动量 无regime", "full_mom"), ("动量 regime全现金", "full_regime"),
        ("质量 无reg线", "q_full_off"), ("质量 regime", "q_full_bin"),
        ("被动质量+红利", "passive_full")]),
]


def pct(x):
    return f"{x*100:.1f}%"


def row_html(label, key, is_passive=False):
    r = R[key]
    if is_passive:
        ann = r.get("annualized") or 0
        mdd = r.get("max_drawdown") or 0
        return (f"<tr><td class='l'>{label}</td><td>{pct(ann)}</td><td>{pct(mdd)}</td>"
                f"<td class='m'>—</td></tr>")
    ann = r["annualized"]; mdd = r["max_drawdown"]; sh = r["sharpe"]
    ry = r.get("roll3y", {})
    ge = ry.get("ge15", 0); n = ry.get("n", 0)
    flag = " class='hi'" if ann >= 0.15 else ""
    return (f"<tr{flag}><td class='l'>{label}</td><td>{pct(ann)}</td><td>{pct(mdd)}</td>"
            f"<td class='m'>{sh:.2f}</td>"
            f"<td class='m'>{ge}/{n}</td></tr>")


def window_table(title, passive_key, rows):
    body = "".join(
        row_html(lbl, key, is_passive=(key == passive_key)) for lbl, key in rows)
    return f"""
    <h3>{title}</h3>
    <table>
      <thead><tr><th>策略</th><th>年化(价投)</th><th>最大回撤</th><th>夏普</th><th>36月≥15%窗口</th></tr></thead>
      <tbody>{body}</tbody>
    </table>"""


# ===== 全样本净值曲线图 =====
CW, CH, PAD = 760, 380, 48
curves = [
    ("动量 regime全现金", "full_regime", "#2f7ed8"),
    ("质量 regime", "q_full_bin", "#8b5cf6"),
    ("被动质量+红利", "passive_full", "#6b7280"),
    ("纯动量 无regime", "full_mom", "#e07b39"),
]
ref = R["full_mom"]["dates"]
all_vals = []
for _, key, _ in curves:
    eq = R[key]["equity_curve"]
    all_vals.extend(eq)
ymin = min(all_vals); ymax = max(all_vals)
span = (ymax - ymin) or 1.0
yd = lambda v: PAD + (CH - 2 * PAD) * (1 - (v - ymin) / span)


def poly(key):
    eq = R[key]["equity_curve"]
    n = len(eq)
    pts = []
    for i, v in enumerate(eq):
        x = PAD + (CW - 2 * PAD) * (i / (n - 1))
        y = yd(v)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


legend = "".join(
    f"<span style='color:{c};font-weight:600'>●</span> {name} &nbsp; "
    for name, key, c in curves)
chart = f"""
<svg viewBox='0 0 {CW} {CH}' width='{CW}' height='{CH}' xmlns='http://www.w3.org/2000/svg'>
  <rect x='0' y='0' width='{CW}' height='{CH}' fill='#0e1117'/>
  <line x1='{PAD}' y1='{yd(1.0)}' x2='{CW-PAD}' y2='{yd(1.0)}' stroke='#3a3f4b' stroke-dasharray='4 4'/>
  <text x='{CW-PAD}' y='{yd(1.0)-4}' fill='#9aa0aa' font-size='10' text-anchor='end'>净值=1.0</text>
  {''.join(f"<polyline points='{poly(key)}' fill='none' stroke='{c}' stroke-width='2'/>" for _,key,c in curves)}
  <text x='{PAD}' y='{CH-12}' fill='#9aa0aa' font-size='10'>2006</text>
  <text x='{CW-PAD}' y='{CH-12}' fill='#9aa0aa' font-size='10' text-anchor='end'>2026</text>
  <text x='{CW/2}' y='20' fill='#e6e8eb' font-size='13' text-anchor='middle'>全样本 2006-26 净值曲线（价投，起点=1.0）</text>
</svg>
<div class='legend'>{legend}</div>"""

# ===== 结论 =====
verdict = f"""
<h3>结论：价格代理"质量复利"因子并未击败动量 / 被动</h3>
<table class='cv'>
  <tbody>
    <tr><td class='k'>全样本 06-26</td>
        <td>纯动量 +{pct(R['full_mom']['annualized'])}/{pct(R['full_mom']['max_drawdown'])}；
            动量regime +{pct(R['full_regime']['annualized'])}/{pct(R['full_regime']['max_drawdown'])}；
            质量regime +{pct(R['q_full_bin']['annualized'])}/{pct(R['q_full_bin']['max_drawdown'])}；
            被动 +{pct(R['passive_full']['annualized'])}/{pct(R['passive_full']['max_drawdown'])}</td></tr>
    <tr><td class='k'>主窗 19-26</td>
        <td>质量代理(无regime) 仅 +{pct(R['q_main_off']['annualized'])}，明显跑输动量 +{pct(R['v4_off']['annualized'])} 与被动 +{pct(R['passive']['annualized'])}——"买稳定股"在牛市踏空</td></tr>
    <tr><td class='k'>熊市 06-14</td>
        <td>质量regime +{pct(R['q_early_bin']['annualized'])}/{pct(R['q_early_bin']['max_drawdown'])} 尚可，但动量regime +{pct(R['early_reg']['annualized'])}/{pct(R['early_reg']['max_drawdown'])} 更优（收益与回撤双胜）</td></tr>
  </tbody>
</table>

<h3>对"研究驱动真阿尔法 + 多轮回测能否提升稳健性"的回答</h3>
<ol>
  <li><b>手挑 3–5 只"高确信复合股"回测是无效的</b>——幸存者+后视偏差，且本候选池已是 2026 筛出的优质幸存者，任何窗口都是乐观上界。</li>
  <li><b>把选股规则机械化后回测（本报告的"质量代理"）同样未击败更简单因子</b>——
      纯价格可计算的质量（低波+浅回撤+正月占比）在四窗口中无一稳定超越动量或被动；这反过来印证：真阿尔法若真实存在，需要的是<b>时点基本面数据（ROE/FCF/负债率）</b>，而非价格代理，而本数据集不含该时序。</li>
  <li><b>诚实结论：在"零杠杆、纯多头、月频、流动性质量幸存者"约束下，没有单一机械因子能在牛熊全程稳定给出 15–25%/年</b>。
      全样本最优机械配置是<b>动量+regime过滤 ≈ +11%/年(价投)、+14%/年(含分红)、回撤 −37%</b>；
      仍低于 15% 目标下限，且 −37% 的崩盘回撤对 10 万账户仍是重创。</li>
  <li><b>regime 过滤是唯一的"免费午餐"</b>：跨牛熊把崩盘回撤从 −46%（纯动量）压到 −37%，早期 06-14 甚至从 −46% 压到 −15%，代价仅是牛市少赚——风险收益上它是机械策略的最优拼图。</li>
</ol>

<h3>目标重校准（给 10 万账户的现实预期）</h3>
<table class='cv'>
  <tbody>
    <tr><td class='k'>可实现机械年化</td><td><b>≈ 11–14%/年</b>（含分红，regime 过滤后；纯价投 ≈ 11%，分红 +~3%/年）</td></tr>
    <tr><td class='k'>不可实现</td><td>15–25%/年 的<b>稳定</b>机械收益——需杠杆(禁用)或真基本面阿尔法(数据缺失)；手挑个股回测是幻觉</td></tr>
    <tr><td class='k'>风控底线</td><td>必须带 regime 过滤（指数<12月均线→现金），否则 −46%~−67% 回撤会击穿持仓信心</td></tr>
    <tr><td class='k'>下一步</td><td>落地<b>可执行 10 万建仓清单</b>（regime 动量 或 被动质量+红利二选一），按 100 股手数、月频再平衡、含分红+成本执行</td></tr>
  </tbody>
</table>"""

tables = "".join(window_table(t, pk, rows) for t, pk, rows in WINDOWS)

HTML = f"""<!doctype html><html lang='zh'><head><meta charset='utf-8'>
<style>
 body{{background:#0e1117;color:#e6e8eb;font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;margin:0;padding:28px 34px;}}
 h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;color:#9aa0aa;font-weight:500;margin:0 0 22px}}
 h3{{font-size:15px;margin:26px 0 10px;color:#cdd2da;border-left:3px solid #2f7ed8;padding-left:9px}}
 table{{border-collapse:collapse;width:100%;margin:8px 0 6px;font-size:13px}}
 th,td{{border:1px solid #2a2f3a;padding:6px 9px;text-align:right}}
 th{{background:#161b22;color:#9aa0aa;font-weight:600}} td.l{{text-align:left}}
 td.m{{color:#9aa0aa}} tr.hi td{{color:#7ee787;font-weight:600}}
 table.cv td{{text-align:left;border-color:#2a2f3a}} table.cv td.k{{color:#9aa0aa;width:130px;white-space:nowrap}}
 .legend{{font-size:12px;color:#9aa0aa;margin:6px 0 0}} svg{{background:#0e1117;border:1px solid #2a2f3a;border-radius:6px}}
 footer{{margin-top:30px;color:#6b7280;font-size:11px}}
</style></head><body>
<h1>⑤ 质量复利代理 vs 动量 vs 被动 —— 稳健性对比</h1>
<h2>回答"研究驱动真阿尔法 + 多轮回测能否提升稳健性" · backtest_v4.py · 价投口径(含分红各策略均匀 +~3%/年)</h2>
{tables}
<h3>全样本 2006-26 净值曲线</h3>
{chart}
{verdict}
<footer>数据：universe.json（新浪日线聚合月线，价格收益；div_yield 为 2026 快照）。
质量代理=纯价格可计算（低波36m+浅回撤60m+正月占比36m），非时点基本面。所有窗口含生存偏差（候选为 2026 优质幸存者）。本报告仅供参考，不构成投资建议。</footer>
</body></html>"""

open(os.path.join(WORK, "report_v5.html"), "w", encoding="utf-8").write(HTML)
print("written -> report_v5.html", len(HTML), "bytes")
