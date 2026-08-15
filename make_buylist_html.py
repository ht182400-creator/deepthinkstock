#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_buylist_html.py —— 由 buy_list_{MODE}.json + results_weekly.json 渲染 3万可执行建仓清单 HTML。
MODE='qscore'  (质量+动量+regime，防御) | MODE='momentum' (纯动量+regime，高弹性对照版)。
"""
import json, os, sys, datetime

WORK=os.path.dirname(os.path.abspath(__file__))
MODE = sys.argv[1] if len(sys.argv)>1 else 'qscore'
d=json.load(open(os.path.join(WORK,f'buy_list_{MODE}.json'),encoding='utf-8'))
ev=json.load(open(os.path.join(WORK,'results_weekly.json'),encoding='utf-8'))

def pct(x): return f"{x*100:.1f}%"
def num(x): return f"{x:,.0f}" if isinstance(x,(int,float)) else str(x)

# ---- 回测证据表 ----
def ev_row(key):
    r=ev.get(key)
    if not r: return None
    return dict(cfg=key, ann=r['annualized'], mdd=r['max_drawdown'], vol=r['vol_annual'],
                sharpe=r['sharpe'], pool=r['avg_quality_pool'], to=r['avg_turnover'])
rows=[]
for k in ["M_qscore_binary_201426","M_qscore_binary_201826",
          "W_qscore_binary_201426","W_qscore_binary_201826",
          "W_momentum_binary_201426","W_momentum_binary_201826"]:
    rr=ev_row(k)
    if rr: rows.append(rr)
def cfg_label(k):
    m={'M':'月频','W':'周频'}.get(k[0],k[0])
    rest=k[2:]
    sm,rm,lbl=rest.split('_')
    sm={'qscore':'质量','momentum':'动量','combo':'混合'}.get(sm,sm)
    rm={'binary':'+regime','none':'无regime'}.get(rm,rm)
    return f"{m} {sm}{rm} {lbl[:4]}-{lbl[4:]}"
ev_html="".join(
    f"<tr><td style='text-align:left'>{cfg_label(r['cfg'])}</td><td>{pct(r['ann'])}</td>"
    f"<td style='color:#c0392b'>{pct(r['mdd'])}</td><td>{pct(r['vol'])}</td>"
    f"<td>{r['sharpe']:.2f}</td><td>{r['pool']:.0f}</td><td>{pct(r['to'])}</td></tr>"
    for r in rows)

def stock_table(rows, cols):
    head="".join(f"<th>{c}</th>" for c in cols)
    body=""
    for r in rows:
        tds="".join(f"<td>{r.get(c,'')}</td>" for c in cols)
        body+=f"<tr>{tds}</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

picks=d['picks']
picks_cols=['code','name','sind','price','lots','amount','weight','roe','debt','mom','score']
picks_disp=[{**p,'price':f"{p['price']:.2f}",'amount':num(p['amount']),
             'weight':pct(p['weight']),'roe':pct(p['roe']/100),'debt':pct(p['debt']/100),
             'mom':pct(p['mom']/100),'score':f"{p['score']:.3f}"} for p in picks]

feasible=[b for b in d['buy'] if b['feasible']]
feas_cols=['code','name','sind','price','roe','debt','fcfnp','mom','cv','score','lots']
feas_disp=[{**b,'price':f"{b['price']:.2f}",'roe':pct(b['roe']/100),'debt':pct(b['debt']/100),
            'mom':pct(b['mom']/100),'score':f"{b['score']:.3f}",'lots':b['lots']} for b in feasible]

obs=d['obs'][:20]
obs_cols=['code','name','sind','price','roe','debt','mom','fail']
obs_disp=[{**b,'price':f"{b['price']:.2f}",'roe':pct(b['roe']/100),'debt':pct(b['debt']/100),
           'mom':pct(b['mom']/100)} for b in obs]

# ---- 模式相关文案 ----
if MODE=='momentum':
    TITLE="3 万可执行建仓清单（高弹性对照版）"
    TAGLINE="周频 动量+Regime 框架 · 弃用质量门 · 宇宙池=沪深+科创+创业宽池"
    MODE_LABEL="周频 动量+Regime（高弹性）"
    CONCL=f"""<b>变异认知（对照）：</b>与质量版不同，本版<b>弃用 ROE≥10%+正FCF 质量门</b>，
仅要求"站上 52 周均线 + 52 周动量为正"，按动量排序。回测显示这是宽池上<b>最佳风险调整</b>配置：
<b>周频动量+regime 2018-26 年化 +12.6% / 夏普 0.40</b>，但代价是最大回撤 <b>−43%</b>（质量版 −36%），
且<b>无基本面安全垫</b>——下跌时只能靠趋势破位离场，没有"好公司"托底。
<b>最优频率：</b>同前，周频 ≥ 月频；此版即周频动量门。
<b>为什么是现在 / 为什么不：</b>当前 Regime = 空头（上证 3832 &lt; 56周MA 3928），纪律同样要求持币；
翻多触发位 = 上证收盘 &gt; <b>{d['regime_trigger']}</b>。
<b>行动分类：</b><span class="tag">等待证据</span> —— 翻多后按下表 4 仓执行；此版更适合能承受 −43% 回撤、追求弹性的资金。
<b>还缺什么：</b>2026 中报未全披露；名单需每周刷新（动量衰减快，换手更高）。"""
    EXIT_BULL="<li><b>本版本无质量门</b>，不依赖基本面退出；卖出纯靠：趋势破位 / 估值分位≥85% / 动量≤−40% / 单价&gt;300</li>"
    EXIT_QUAL_HIDE=True
else:
    TITLE="3 万可执行建仓清单"
    TAGLINE="周频 质量(ROE≥10%+正FCF) + 动量(52周) + Regime(上证56周MA) 框架 · 宇宙池=沪深+科创+创业宽池"
    MODE_LABEL="周频 质量+动量+Regime（防御）"
    CONCL=f"""<b>变异认知：</b>在真实可投宽池（1438 只完整基本面）上，月/周频"质量+动量+regime"框架的实证年化仅约
<b>4–7%（质量门）</b>或 <b>7–13%（动量门）</b>，远低于此前窄池测试的 13–17%——此前高数字是窄基本面子集 + 幸存者偏差的假象。
<b>最优频率：</b>同一方法论下<b>周频 ≥ 月频</b>（周频质量门 2018-26 年化 6.9% / 夏普 0.25 vs 月频 4.7% / 0.13）；
若追求弹性，<b>周频动量+regime</b> 为最佳风险调整（2018-26 年化 12.6% / 夏普 0.40，但回撤 −43%）。
<b>为什么是现在 / 为什么不：</b>当前 Regime = 空头（上证 3832 &lt; 56周MA 3928），框架纪律要求持币。
<b>行动分类：</b><span class="tag">等待证据</span> —— 翻多触发位 = 上证收盘 &gt; <b>{d['regime_trigger']}</b> 后，按下表 4 仓执行；
在此之前仅作观察名单，或 ≤1 仓小仓试水。
<b>还缺什么：</b>2026 中报（截至信号日尚未全部披露）将更新 ROE/FCF，名单需每周刷新。"""
    EXIT_BULL=""
    EXIT_QUAL_HIDE=False

regime_cls="down" if not d['regime_up'] else "up"
regime_txt=("⚠ 当前 REGIME = 空头（上证周线低于 56 周均线）— 框架纪律：暂不新建仓，持币观望；"
            "仅可在翻多触发位下方小仓试水。") if not d['regime_up'] else "当前 REGIME = 多头（上证站上 56 周均线），可执行建仓。"

obs_section = (f"<h2>四、观察池 TOP 20（质量过关，但未站线 / 动量负）</h2>"
    f"<div class='sub'>这些股票基本面过关，只差\"价格站上 52 周均线\"或\"动量转正\"，纳入翻多后的补仓候选。</div>"
    f"{stock_table(obs_disp, obs_cols)}") if obs else (
    "<h2>四、观察池</h2><div class='note'>本版本（动量+regime）已<b>弃用质量门</b>，故无\"质量过关但没站线\"的观察池；"
    "所有站线+动量为正的标的已直接计入买候选池。</div>")

html=f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{TITLE} · {MODE_LABEL}</title>
<style>
*{{box-sizing:border-box}} body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
background:#f5f6f8;color:#1f2d3d;margin:0;padding:24px;line-height:1.55}}
.wrap{{max-width:1080px;margin:0 auto;background:#fff;border-radius:12px;padding:28px 32px;
box-shadow:0 2px 14px rgba(0,0,0,.06)}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:26px 0 10px;padding-left:10px;
border-left:4px solid #2c7be5}} .sub{{color:#7a869a;font-size:13px;margin-bottom:6px}}
.banner{{padding:14px 18px;border-radius:9px;font-weight:600;font-size:15px;margin:16px 0}}
.banner.down{{background:#fdecea;color:#c0392b;border:1px solid #f5c6cb}}
.banner.up{{background:#e8f6ef;color:#1e8e5a;border:1px solid #b7e4c7}}
.kpis{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}}
.kpi{{flex:1;min-width:130px;background:#f7f9fc;border:1px solid #e6ebf2;border-radius:8px;padding:12px 14px}}
.kpi .v{{font-size:20px;font-weight:700}} .kpi .l{{font-size:12px;color:#7a869a}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}
th,td{{padding:7px 9px;border-bottom:1px solid #eef1f5;text-align:right}}
th{{background:#f0f3f8;color:#34495e;font-weight:600;text-align:right}}
th:first-child,td:first-child,td:nth-child(2),th:nth-child(2){{text-align:left}}
tr:hover td{{background:#fafbfd}}
.note{{background:#fff8e6;border:1px solid #f0e0b0;border-radius:8px;padding:12px 16px;
font-size:13px;margin:12px 0}}
.note.blue{{background:#eef3fb;border-color:#cfe0f5;color:#2c5aa0}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:760px){{.grid2{{grid-template-columns:1fr}}}}
ul{{margin:6px 0 6px 18px;padding:0}} li{{margin:3px 0;font-size:13.5px}}
.foot{{margin-top:24px;font-size:11.5px;color:#9aa5b5;border-top:1px solid #eef1f5;padding-top:12px}}
.tag{{display:inline-block;background:#eef3fb;color:#2c7be5;border-radius:4px;padding:1px 7px;font-size:11px;margin-left:6px}}
</style></head><body><div class="wrap">

<h1>{TITLE}</h1>
<div class="sub">{TAGLINE} · 信号日 {d['signal_date']} · 模式：{MODE_LABEL}</div>

<div class="banner {regime_cls}">{regime_txt}</div>

<div class="kpis">
  <div class="kpi"><div class="v">{num(d['capital'])}</div><div class="l">总资金（元）</div></div>
  <div class="kpi"><div class="v">4 仓</div><div class="l">等权 ≈ {num(d['per_pos'])}/仓</div></div>
  <div class="kpi"><div class="v">{d['n_buy']}</div><div class="l">买候选（站线+动量正）</div></div>
  <div class="kpi"><div class="v">{d['n_feasible']}</div><div class="l">资金可行（单价≤75）</div></div>
  <div class="kpi"><div class="v">{d['n_obs']}</div><div class="l">观察池（仅质量版）</div></div>
  <div class="kpi"><div class="v">{d['idx_now']:.0f}</div><div class="l">上证现指 / MA {d['idx_ma']:.0f}</div></div>
</div>

<h2>一、结论与行动（PM 七问浓缩）</h2>
<div class="note">{CONCL}</div>

<h2>二、4 股票条件组合（Regime 翻多后执行）</h2>
<div class="sub">等权约 7500/仓，100 股整手；当前不执行，仅作"条件单"。部署 {num(d['deployed'])}，留现金 {num(d['cash'])} 作缓冲。</div>
{stock_table(picks_disp, picks_cols)}

<h2>三、完整资金可行候选（{d['n_feasible']} 只 · 单价≤75 · 周频评分排名）</h2>
<div class="sub">score：{'纯动量池内排序值（0-1）' if MODE=='momentum' else '质量(ROE+FCF+低波动+低负债) 50% + 动量 50% 的池内排序值'}；feasible 已按单价≤75 过滤。</div>
{stock_table(feas_disp, feas_cols)}

{obs_section}

<h2>五、退出纪律（估值泡沫 + 趋势破位，非价格止损）</h2>
<div class="grid2">
<div>
<b>卖出触发（任一即减/清仓）：</b>
<ul>
<li>估值泡沫：该股估值分位 ≥ 85%（周频 5 年分位）</li>
{EXIT_BULL if not EXIT_QUAL_HIDE else ''}
<li>趋势破位：收盘价跌破 52 周均线（周频）</li>
<li>动量崩溃：52 周动量 ≤ −40%</li>
<li>价格异常：单价 &gt; 300（脱离小资金可投区间）</li>
</ul>
</div>
<div>
<b>不做的：</b>
<ul>
<li>不设 −10% 刚性价格止损（用户纪律）</li>
<li>不追高买入（动量极端 &gt;200% 视为泡沫预警，谨慎追）</li>
<li>不杠杆、不融资融券、不期权</li>
<li>单行业暴露 ≤ 35%（分散）</li>
</ul>
<b>操作节奏：</b>
<ul>
<li>每周五：重算 Regime + 刷新候选 + 检查持仓趋势线</li>
<li>财报季：{'质量版复核 ROE/FCF，剔除退化标的' if not EXIT_QUAL_HIDE else '动量版无需基本面复核，但关注趋势/动量衰减'}</li>
</ul>
</div>
</div>

<h2>六、回测证据（宽池 1438 只完整基本面 · 周 vs 月）</h2>
<div class="sub">N=15 仓上限，成本 0.12%/边，regime=上证56周(月13月)MA 二值。月频数字已从窄池 500 只校正到宽池。</div>
<table><thead><tr><th>配置</th><th>年化</th><th>最大回撤</th><th>年化波动</th><th>夏普</th><th>均质池</th><th>换手/期</th></tr></thead>
<tbody>{ev_html}</tbody></table>
<div class="note blue">
<b>诚实校准：</b>无杠杆下，质量版合理预期年化约 <b>6–7%</b>（回撤 −36%），动量版约 <b>7–13%</b>（回撤 −43%）——
均非 30% 拉伸目标。30% 需杠杆或集中押注，与用户"不杠杆"约束冲突。本清单以<b>风险可控 + 纪律可执行</b>为第一优先级。
两版对照：质量版<strong>更稳更抗跌</strong>，动量版<strong>弹性更高但回撤更大、无基本面安全垫</strong>。
</div>

<div class="foot">
数据来源：日线=新浪 K 线（沪深/科创；北交所数据在本环境不可达，已排除）；基本面=东方财富 DMSK 年报（REPORT_DATE 取 −12−31，NOTICE_DATE 作时点防前视）；
指数=上证(sh000001) 周/月线。回测为历史模拟，含交易成本和 regime 空仓，不代表未来收益。
本报告仅供参考，不构成个人投资建议。生成于 {datetime.date.today().isoformat()}。
</div>
</div></body></html>"""

open(os.path.join(WORK,f'buy_list_{MODE}.html'),'w',encoding='utf-8').write(html)
print(f"written -> buy_list_{MODE}.html  ({len(html)} bytes)")
