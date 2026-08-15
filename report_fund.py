#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_fund.py —— 真实基本面质量因子 vs 动量 vs 被动 的稳健性对比报告。
读取 results_fund.json，按窗口分组展示年化/回撤/波动/夏普，并用 SVG 画出关键配置净值曲线，
回答"动量+regime 是否最优机械配置"。
"""
import json, os, datetime

WORK = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(WORK, "results_fund.json"), encoding="utf-8"))


def fmt_pct(x):
    return f"{x*100:+.1f}%" if x is not None else "—"


def fmt_pct2(x):
    return f"{x*100:.1f}%" if x is not None else "—"


# 分组：按窗口后缀 201426 / 201826
WINDOWS = [("201426", "2014-06 → 2026 现在（主窗，含 2015/2018/2022 三轮崩盘）"),
           ("201826", "2018-01 → 2026 现在（次窗，含真实 PE 验证段 + 2018/2022 崩盘）")]

# 每个窗口内期望的场景 key（后缀）
SCEN_ORDER = [
    ("mom_off",      "动量 无regime"),
    ("mom_bin",      "动量 +regime"),
    ("mom_vol_off",  "动量 波动加权 无regime"),
    ("mom_vol_bin",  "动量 波动加权 +regime"),
    ("q_strict_off", "质量strict 无regime"),
    ("q_strict_bin", "质量strict +regime"),
    ("q_relax_off",  "质量relax 无regime"),
    ("q_relax_bin",  "质量relax +regime"),
    ("combo_off",    "质量+动量组合 无regime"),
    ("combo_bin",    "质量+动量组合 +regime"),
    ("passive",      "被动等权(同宇宙)"),
]


def rows_for(pre):
    out = []
    for key, label in SCEN_ORDER:
        k = f"{key}_{pre}"
        if k in R:
            r = R[k]
            out.append((label, r))
    return out


def best(rows, metric, highest=True):
    best_v, best_l = (None, None)
    for label, r in rows:
        v = r.get(metric)
        if v is None:
            continue
        if best_v is None or (v > best_v if highest else v < best_v):
            best_v, best_l = v, label
    return best_l, best_v


# ---- SVG 净值曲线（主窗 201426）----
def build_chart(pre, w=900, h=380):
    keys = [("mom_bin", "动量+regime", "#d1495b"),
            ("combo_bin", "质量+动量+regime", "#2e8b57"),
            ("q_strict_bin", "质量strict+regime", "#6a4c93"),
            ("mom_vol_bin", "动量波动加权+regime", "#e09f3e"),
            ("passive", "被动等权", "#888888")]
    series = []
    ref_dates = None
    for key, label, color in keys:
        k = f"{key}_{pre}"
        if k in R:
            r = R[k]
            eq = r["equity_curve"]
            dates = r.get("dates") or ref_dates
            if dates and len(dates) == len(eq):
                ref_dates = dates
                series.append((label, color, eq))
    if not series:
        return ""
    n = max(len(eq) for _, _, eq in series)
    # 对齐到最短公共长度（各序列等长时直接用）
    xs = list(range(n))
    allv = [v for _, _, eq in series for v in eq]
    vmin, vmax = min(allv), max(allv)
    pad = (vmax - vmin) * 0.08 or 0.1
    vmin, vmax = vmin - pad, vmax + pad
    def px(i):
        return 60 + (i / (n - 1)) * (w - 90)
    def py(v):
        return 30 + (1 - (v - vmin) / (vmax - vmin)) * (h - 70)

    polylines = []
    for label, color, eq in series:
        pts = " ".join(f"{px(i):.1f},{py(eq[i]):.1f}" for i in range(len(eq)))
        polylines.append(
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>'
            f'<text x="{px(len(eq)-1)+4:.1f}" y="{py(eq[-1]):.1f}" font-size="11" fill="{color}">{label}</text>')
    # 网格线（y）
    grid = ""
    for gv in [vmin, (vmin+vmax)/2, vmax]:
        if abs(gv - 1.0) < 1e-9:
            grid += f'<line x1="60" y1="{py(1.0):.1f}" x2="{w-30}" y2="{py(1.0):.1f}" stroke="#bbb" stroke-dasharray="4 3"/>' \
                    f'<text x="5" y="{py(1.0)+3:.1f}" font-size="10" fill="#555">1.0x</text>'
    return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" style="max-width:100%">'
            f'{grid}{"".join(polylines)}'
            f'<text x="60" y="18" font-size="12" fill="#333">净值曲线（起点=1.0，价投，月频再平衡，含成本）</text>'
            f'</svg>')


def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    tables = []
    for pre, desc in WINDOWS:
        rows = rows_for(pre)
        if not rows:
            continue
        b_ret = best(rows, "annualized", True)
        b_dd = best(rows, "max_drawdown", False)
        b_shp = best(rows, "sharpe", True)
        tr = ["<tr><th>配置</th><th>年化</th><th>最大回撤</th><th>年化波动</th><th>夏普</th><th>均合格池</th></tr>"]
        for label, r in rows:
            tag = ""
            if label == b_ret[0]:
                tag += " ★收益"
            if label == b_dd[0]:
                tag += " ★低回撤"
            if label == b_shp[0]:
                tag += " ★夏普"
            cls = ' class="best"' if tag else ""
            tr.append(
                f"<tr{cls}><td>{label}{tag}</td>"
                f"<td>{fmt_pct(r['annualized'])}</td>"
                f"<td>{fmt_pct2(r['max_drawdown'])}</td>"
                f"<td>{fmt_pct2(r.get('vol_annual')) if r.get('vol_annual') is not None else '—'}</td>"
                f"<td>{r.get('sharpe')}</td>"
                f"<td>{r.get('avg_quality_pool',0):.1f}</td></tr>")
        chart = build_chart(pre) if pre == "201426" else ""
        tables.append(f"""
<div class="win">
  <h3>{desc}</h3>
  {('<div class="chart">'+chart+'</div>') if chart else ''}
  <table border="1" cellspacing="0" cellpadding="4">{''.join(tr)}</table>
  <p class="note">窗口内最优：收益 <b>{b_ret[0]}</b>（{fmt_pct(b_ret[1]) if b_ret[1] is not None else '—'}）；
  最低回撤 <b>{b_dd[0]}</b>（{fmt_pct2(b_dd[1])}）；最高夏普 <b>{b_shp[0]}</b>（{b_shp[1]:.2f}）。</p>
</div>""")

    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<style>
 body{{font-family:-apple-system,'Segoe UI',sans-serif;margin:24px;color:#222;line-height:1.5}}
 h1{{font-size:22px;border-bottom:3px solid #d1495b;padding-bottom:6px}}
 h3{{font-size:16px;margin-top:28px;color:#1a1a1a}}
 table{{border-collapse:collapse;font-size:13px;margin:8px 0;width:100%}}
 th,td{{border:1px solid #ddd;padding:5px 8px;text-align:center}}
 th{{background:#f4f4f4}}
 tr.best{{background:#fff6e6}}
 .win{{margin-bottom:18px}}
 .chart{{margin:10px 0}}
 .note{{font-size:12px;color:#555}}
 .verdict{{background:#f0f7ff;border-left:4px solid #2e8b57;padding:10px 14px;margin:16px 0;font-size:14px}}
 .caveat{{background:#fff3f3;border-left:4px solid #d1495b;padding:10px 14px;margin:16px 0;font-size:13px}}
 code{{background:#f4f4f4;padding:1px 4px;border-radius:3px}}
</style></head><body>
<h1>研究驱动真阿尔法：真实基本面质量因子回测（{now}）</h1>
<div class="verdict">
<b>核心问题：动量+regime 是否是最优机械配置？</b><br>
本报告在 <b>沪深300+中证500（800只成分股）</b> 真实可投宇宙上，用 <b>东方财富 DMSK 真实年报</b>（时点正确、防前视）
机械复制"高确信复合股"规则（ROE&gt;20%持续3年、FCF/净利∈[80%,300%]、负债率≤30%/50%、非金融），
并叠加 <b>质量+动量组合</b> 与 <b>波动加权</b> 两种改进，与动量/被动对照。结论见末节。
</div>
{''.join(tables)}
<div class="caveat">
<b>方法论与偏差提示：</b><br>
① <b>真实基本面时点正确</b>：每只股票在某月末仅使用 <code>NOTICE_DATE ≤ 月末</code> 的年报，杜绝前视。<br>
② <b>生存偏差缓解（但仍残留）</b>：宇宙取自 CSI300+CSI500 当前成分股（含大量"昔日蓝筹已衰落"名，如万科、TCL），
较原 25 只幸存者池显著更严；但 <b>已退市/归零股仍不在池内</b>，所有结果仍为乐观上界。<br>
③ <b>口径</b>：价格收益（不含分红，与 v4 一致）；+分红约再 +3%/年。月频再平衡、零杠杆、无 -10% 止损、
行业≤35%、regime=市指跌破12月均线全现金。成本按单边 0.12%（双边 0.24%/次）。<br>
④ <b>金融业剔除</b>：银行/保险/券商的 FCF 与负债率结构性失真（如平安银行 FCF/净利=7.3、负债率=91%），已剔除。<br>
⑤ <b>价格回溯深度</b>：新浪日线 DATALEN=3200（≈2013 起），故主窗取 2014-06；基本面年报回溯至 ~1998，可计算质量因子。
</div>
<div class="verdict">
<b>结论（待回填运行结果后定稿）：</b> 见上表 — 若"质量+动量组合 +regime"在收益不降的前提下
把回撤压到低于纯动量、且夏普更高，则 <b>原"动量+regime"并非最优</b>，最优为组合+regime；
若组合并未改善（质量因子被动量主导），则动量+regime 仍是最优机械配置，但需接受 −37% 级回撤，
此时唯一可行改善是 <b>波动加权降回撤</b> 或 <b>接受更低收益换更稳复利</b>。
</div>
<p style="font-size:11px;color:#999">本报告基于公开数据回测与规则设计，不构成个人投资建议。</p>
</body></html>"""
    out = os.path.join(WORK, "report_fund.html")
    open(out, "w", encoding="utf-8").write(html)
    print("written ->", out, "size=", len(html))


if __name__ == "__main__":
    main()
