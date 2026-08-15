# -*- coding: utf-8 -*-
"""由 backtest_result.json 生成可视化 HTML 报告(含 SVG 权益曲线)."""
import json
from math import floor, ceil

with open('backtest_result.json', encoding='utf-8') as f:
    D = json.load(f)

dates = D['dates']
strat = D['primary_equity']
basket = D['bench_basket_curve']
index = D['bench_index_curve']

# 归一化到起点=1000, 便于同图比较
def norm(c):
    base = c[0]
    return [v/base*1000 for v in c]

S, B, I = norm(strat), norm(basket), norm(index)
allv = S + B + I
ymin, ymax = min(allv), max(allv)
ymin, ymax = floor(ymin), ceil(ymax)
ymin = min(ymin, 950); ymax = max(ymax, 1050)

W, H = 820, 380
PAD_L, PAD_R, PAD_T, PAD_B = 60, 30, 30, 40
x0, x1 = PAD_L, W-PAD_R
y0, y1 = H-PAD_B, PAD_T

def sx(i):
    return x0 + (x1-x0)*i/(len(dates)-1)

def sy(v):
    return y0 + (y1-y0)*(v-ymin)/(ymax-ymin)

def poly(c):
    return ' '.join(f"{sx(i):.1f},{sy(c[i]):.1f}" for i in range(len(c)))

# 网格横线
grid = ''
for g in range(0, 5):
    v = ymin + (ymax-ymin)*g/4
    yy = sy(v)
    grid += f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="#e5e7eb"/>'
    grid += f'<text x="{x0-8}" y="{yy+4:.1f}" text-anchor="end" font-size="11" fill="#6b7280">{v:.0f}</text>'

# X 轴标签(每年初)
xticks = ''
yrs = ['2023','2024','2025','2026']
for yi, yr in enumerate(yrs):
    # 找该年第一个月的索引
    idx = next((i for i, d in enumerate(dates) if d.startswith(yr)), None)
    if idx is not None:
        xx = sx(idx)
        xticks += f'<text x="{xx:.1f}" y="{y0+22:.1f}" text-anchor="middle" font-size="11" fill="#6b7280">{yr}</text>'

# 主配置指标
p = D['primary']
bb = D['bench_basket']; bi = D['bench_index']

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>优化版价值策略 · 3年回测</title>
<style>
 body{{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:28px;}}
 .wrap{{max-width:920px;margin:0 auto;}}
 h1{{font-size:22px;margin:0 0 4px;}} .sub{{color:#94a3b8;font-size:13px;margin-bottom:20px;}}
 .card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px;margin-bottom:18px;}}
 table{{width:100%;border-collapse:collapse;font-size:13px;}}
 th,td{{padding:8px 10px;border-bottom:1px solid #334155;text-align:right;}}
 th:first-child,td:first-child{{text-align:left;}}
 th{{color:#93c5fd;font-weight:600;}}
 .pos{{color:#4ade80;}} .neg{{color:#f87171;}}
 .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px;}}
 .kpi{{background:#0f172a;border-radius:8px;padding:10px 12px;}}
 .kpi .v{{font-size:20px;font-weight:700;}} .kpi .l{{font-size:11px;color:#94a3b8;}}
 .legend{{display:flex;gap:18px;font-size:12px;margin-top:8px;}}
 .dot{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:middle;}}
 .note{{font-size:12px;color:#94a3b8;line-height:1.7;}}
 code{{background:#0f172a;padding:1px 5px;border-radius:4px;color:#fbbf24;}}
</style></head><body><div class="wrap">
<h1>优化版价值投资策略 · 3年回归测试</h1>
<div class="sub">2023-04-28 ~ 2026-07-31 · 后复权月线 · 初始 ¥1,000,000 · 数据：通达信 MCP</div>

<div class="card">
 <div class="legend">
  <span><span class="dot" style="background:#22d3ee"></span>策略(估值分位+均线regime)</span>
  <span><span class="dot" style="background:#a78bfa"></span>等权持有篮子(基准)</span>
  <span><span class="dot" style="background:#f59e0b"></span>上证指数(基准)</span>
 </div>
 <svg viewBox="0 0 {W} {H}" width="100%" style="background:#0f172a;border-radius:8px;">
  {grid}
  {xticks}
  <polyline fill="none" stroke="#a78bfa" stroke-width="2" points="{poly(B)}"/>
  <polyline fill="none" stroke="#f59e0b" stroke-width="2" points="{poly(I)}"/>
  <polyline fill="none" stroke="#22d3ee" stroke-width="2.5" points="{poly(S)}"/>
 </svg>
</div>

<div class="card grid2">
 <div class="kpi"><div class="v">{p['cum_return_pct']}%</div><div class="l">策略累计收益</div></div>
 <div class="kpi"><div class="v">{p['max_drawdown_pct']}%</div><div class="l">策略最大回撤</div></div>
 <div class="kpi"><div class="v">{p['sharpe']}</div><div class="l">策略 Sharpe</div></div>
 <div class="kpi"><div class="v">{p['avg_invested_pct']}%</div><div class="l">平均持仓占比</div></div>
</div>

<div class="card">
 <table>
  <tr><th>指标</th><th>策略(主配置)</th><th>等权篮子</th><th>上证指数</th></tr>
  <tr><td>累计收益</td><td class="pos">{p['cum_return_pct']}%</td><td class="pos">{bb['cum_pct']}%</td><td class="pos">{bi['cum_pct']}%</td></tr>
  <tr><td>年化收益</td><td>{p['ann_return_pct']}%</td><td>{bb['ann_pct']}%</td><td>{bi['ann_pct']}%</td></tr>
  <tr><td>最大回撤</td><td class="pos">{p['max_drawdown_pct']}%</td><td>{bb['mdd_pct']}%</td><td>{bi['mdd_pct']}%</td></tr>
  <tr><td>Sharpe</td><td>{p['sharpe']}</td><td>{bb['sharpe']}</td><td>{bi['sharpe']}</td></tr>
  <tr><td>胜率</td><td>{p['win_rate_pct']}%</td><td>—</td><td>—</td></tr>
 </table>
</div>

<div class="card">
 <div style="font-size:14px;color:#93c5fd;margin-bottom:8px;">入场阈值敏感性 (ENTRY_PCTL)</div>
 <table>
  <tr><th>阈值</th><th>累计%</th><th>年化%</th><th>回撤%</th><th>Sharpe</th><th>买入</th><th>平仓</th><th>胜率%</th><th>均持仓%</th></tr>
"""
for thr in ('30','40','50'):
    s = D['sweep'][thr]
    mark = ' style="background:#0f172a"' if thr == '40' else ''
    html += (f"  <tr{mark}><td>{thr}</td><td>{s['cum_return_pct']}%</td><td>{s['ann_return_pct']}%</td>"
             f"<td>{s['max_drawdown_pct']}%</td><td>{s['sharpe']}</td><td>{s['total_buys']}</td>"
             f"<td>{s['closed_trades']}</td><td>{s['win_rate_pct']}%</td><td>{s['avg_invested_pct']}%</td></tr>\n")

html += """ </table>
</div>

<div class="card">
 <div style="font-size:14px;color:#93c5fd;margin-bottom:8px;">交易明细 (主配置 ENTRY_PCTL=40)</div>
 <table>
  <tr><th>日期</th><th>标的</th><th>动作</th><th>价格</th><th>股数</th><th>盈亏%</th></tr>
"""
for t in D['primary_trades']:
    cls = 'pos' if t.get('pnl_pct', 0) > 0 else ('neg' if t.get('pnl_pct', 0) < 0 else '')
    pnl = f"{t['pnl_pct']}%" if 'pnl_pct' in t else '—'
    act = {'BUY':'买入','STOP':'止损','TAKEPROFIT':'止盈'}[t['action']]
    html += (f"  <tr><td>{t['date']}</td><td>{t['name']}</td><td>{act}</td>"
             f"<td>{t['price']}</td><td>{t['shares']}</td><td class='{cls}'>{pnl}</td></tr>\n")

html += f""" </table>
</div>

<div class="card note">
 <b>核心结论：</b>本策略是<b>资本保全机器</b>而非 alpha 发生器。在 2023–2026 质量股慢牛中，
 8 只价值股多数时间处于自身历史高位，"便宜"极少出现 → 长期 70–90% 空仓；最大回撤仅
 {p['max_drawdown_pct']}%（篮子 {bb['mdd_pct']}%、指数 {bi['mdd_pct']}%），但绝对收益
 {p['cum_return_pct']}% 远落后于满仓篮子 {bb['cum_pct']}%。Sharpe {p['sharpe']} 跑赢指数
 ({bi['sharpe']})、低于满仓篮子 ({bb['sharpe']})。100股手数约束自然剔除了茅台/伊利等高价股。
 <br><br><b>局限：</b>估值用价格分位代理（非逐股PE）；月度颗粒度；未计成本与分红再投资；样本为质量股强势期。
 <br><b>行动分类：</b><code>观察名单 / 等待证据</code> —— 建议在震荡/下行市补充样本外验证，再定主用或辅用。
 <br><br><i>本报告基于历史数据回测，不构成投资建议。</i>
</div>
</div></body></html>"""

with open('report.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("[已生成 report.html]")
