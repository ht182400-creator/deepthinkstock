#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_compare_html.py —— 合并对照 HTML：两版 4仓组合并排对比 + 行业集中度（质量 vs 动量）。"""
import json, os, datetime
from collections import Counter

WORK=os.path.dirname(os.path.abspath(__file__))
Q=json.load(open(os.path.join(WORK,'buy_list.json'),encoding='utf-8'))
M=json.load(open(os.path.join(WORK,'buy_list_momentum.json'),encoding='utf-8'))

def pct(x): return f"{x*100:.1f}%"
def num(x): return f"{x:,.0f}"

# ---- 行业集中度 ----
def concentration(d):
    buy=d['buy']
    c=Counter(b['sind'] for b in buy)
    tot=len(buy)
    hhi=sum((n/tot)**2 for n in c.values()) if tot else 0
    top=c.most_common(8)
    return tot, len(c), hhi, top

qt,qn,qh,qtop=concentration(Q)
mt,mn,mh,mtop=concentration(M)

def conc_table(tot,nind,hhi,top):
    rows="".join(f"<tr><td style='text-align:left'>{ind}</td><td>{cnt}</td><td>{pct(cnt/tot)}</td></tr>"
                for ind,cnt in top)
    return (f"<div class='sub'>候选 {tot} 只 · 行业 {nind} 个 · "
            f"<b>HHI={hhi:.3f}</b>（&lt;0.18 视为分散，≥0.18 偏高集中）</div>"
            f"<table><thead><tr><th>行业</th><th>只数</th><th>占比</th></tr></thead><tbody>{rows}</tbody></table>")

# ---- 并排 4仓 ----
def picks_rows(qp, mp):
    out=""
    for i in range(4):
        q=qp[i] if i<len(qp) else {}
        m=mp[i] if i<len(mp) else {}
        out+=("<tr>"
              f"<td>{i+1}</td>"
              f"<td style='text-align:left'>{q.get('code','')} {q.get('name','')}</td><td>{q.get('price')}</td>"
              f"<td>{pct(q.get('weight',0)/100) if q else ''}</td><td>{round(q.get('mom',0),0) if q else ''}%</td>"
              f"<td style='text-align:left'>{m.get('code','')} {m.get('name','')}</td><td>{m.get('price')}</td>"
              f"<td>{pct(m.get('weight',0)/100) if m else ''}</td><td>{round(m.get('mom',0),0) if m else ''}%</td>"
              "</tr>")
    return out

qp=Q['picks']; mp=M['picks']
side_by_side=(f"<table><thead><tr><th>仓</th>"
              f"<th>质量版（防御）</th><th>现价</th><th>权重</th><th>52周动量</th>"
              f"<th>动量版（高弹性）</th><th>现价</th><th>权重</th><th>52周动量</th></tr></thead>"
              f"<tbody>{picks_rows(qp,mp)}</tbody></table>")

# ---- 策略指标对照 ----
metrics=[("总资金", num(Q['capital']), num(M['capital'])),
         ("买候选数", Q['n_buy'], M['n_buy']),
         ("资金可行(≤75)", Q['n_feasible'], M['n_feasible']),
         ("回测年化(2018-26)", "+6.9%", "+12.6%"),
         ("夏普(2018-26)", "0.25", "0.40"),
         ("最大回撤", "−36%", "−43%"),
         ("退出锚", "估值+基本面+趋势", "纯趋势/估值/动量"),
         ("质量门", "ROE≥10%+正FCF", "弃用")]
metr="".join(f"<tr><td style='text-align:left'>{k}</td><td>{a}</td><td>{b}</td></tr>" for k,a,b in metrics)

regime_cls="down" if not Q['regime_up'] else "up"
regime_txt=("⚠ 当前两版 REGIME 均为空头（上证周线低于 56 周均线 3928）— 框架纪律：暂不新建仓，持币观望；"
            "翻多触发位 = 上证收盘 &gt; 3928 后，按下表对应 4 仓执行。") if not Q['regime_up'] else "当前 REGIME = 多头，可执行建仓。"

html=f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>两版策略 4仓组合并排对比 + 行业集中度</title>
<style>
*{{box-sizing:border-box}} body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
background:#f5f6f8;color:#1f2d3d;margin:0;padding:24px;line-height:1.55}}
.wrap{{max-width:1100px;margin:0 auto;background:#fff;border-radius:12px;padding:28px 32px;box-shadow:0 2px 14px rgba(0,0,0,.06)}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:26px 0 10px;padding-left:10px;border-left:4px solid #2c7be5}}
.sub{{color:#7a869a;font-size:13px;margin-bottom:6px}}
.banner{{padding:14px 18px;border-radius:9px;font-weight:600;font-size:15px;margin:16px 0}}
.banner.down{{background:#fdecea;color:#c0392b;border:1px solid #f5c6cb}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:760px){{.grid2{{grid-template-columns:1fr}}}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}
th,td{{padding:7px 9px;border-bottom:1px solid #eef1f5;text-align:right}}
th{{background:#f0f3f8;color:#34495e;font-weight:600}}
td:nth-child(2),th:nth-child(2),td:nth-child(6),th:nth-child(6),td:first-child,th:first-child{{text-align:left}}
tr:hover td{{background:#fafbfd}}
.note{{background:#fff8e6;border:1px solid #f0e0b0;border-radius:8px;padding:12px 16px;font-size:13px;margin:12px 0}}
.qcol{{border-top:3px solid #2c7be5}} .mcol{{border-top:3px solid #e67e22}}
.foot{{margin-top:24px;font-size:11.5px;color:#9aa5b5;border-top:1px solid #eef1f5;padding-top:12px}}
</style></head><body><div class="wrap">

<h1>两版策略 · 4 仓组合并排对比 + 行业集中度</h1>
<div class="sub">周频 质量+动量+Regime（防御） vs 周频 动量+Regime（高弹性）· 宇宙池=沪深+科创+创业宽池 · 信号日 {Q['signal_date']}</div>

<div class="banner {regime_cls}">{regime_txt}</div>

<h2>一、4 仓条件组合并排对比（Regime 翻多后执行）</h2>
<div class="sub">等权约 7500/仓，100 股整手；当前不执行，仅作"条件单"。质量版部署 {num(Q['deployed'])}／动量版部署 {num(M['deployed'])}。</div>
{side_by_side}

<h2>二、策略属性对照</h2>
<table><thead><tr><th>维度</th><th>质量版（防御）</th><th>动量版（高弹性）</th></tr></thead><tbody>{metr}</tbody></table>

<h2>三、行业集中度检查（纯动量是否扎堆赛道）</h2>
<div class="grid2">
<div class="qcol" style="padding-top:6px"><b>质量版候选池</b>{conc_table(qt,qn,qh,qtop)}</div>
<div class="mcol" style="padding-top:6px"><b>动量版候选池</b>{conc_table(mt,mn,mh,mtop)}</div>
</div>
<div class="note">
<b>结论：</b>两版候选池整体均<b>分散</b>（HHI 仅 0.04–0.05，远低于 0.18 警戒线）——171 只动量候选铺在 57 个行业，
不存在单一行业垄断。但动量版确实<b>明显偏向半导体链</b>：半导体单独占 16.4%（28 只），叠加电子化学品/元件/通信设备后
电子链条合计约占三成，印证"纯动量易扎堆热门赛道"的直觉。质量版因有 ROE/FCF 质量门过滤，行业更均衡（半导体仅 11.6%）。
<b>实操提示：</b>动量版建仓时建议对半导体链做行业上限（≤35%），避免在同一个热门赛道过度暴露。
</div>

<h2>四、量能因子评估（OBV 蓄势 + 量能扩张，是否改善？）</h2>
<div class="sub">按用户建议加入"量在价先 / 主力资金进场"因子：OBV 站上 26 周蓄势线（资金流入）+ 周量 &gt; 26 周均量（放量）。
分别以"因子权重"与"硬性门槛"两种方式叠加，回测 2018-26 周频对照。</div>
<table><thead><tr><th>周频配置</th><th>年化</th><th>最大回撤</th><th>夏普</th><th>候选池</th></tr></thead><tbody>
<tr><td style="text-align:left">质量+regime（无量能·基线）</td><td><b>5.9%</b></td><td>−38.2%</td><td><b>0.20</b></td><td>67</td></tr>
<tr><td style="text-align:left">质量+regime 量能因子 w=0.2</td><td>2.5%</td><td>−45.0%</td><td>0.02</td><td>67</td></tr>
<tr><td style="text-align:left">质量+regime 量能门槛</td><td>3.4%</td><td>−41.6%</td><td>0.07</td><td>25</td></tr>
<tr><td style="text-align:left">动量+regime（无量能·基线）</td><td><b>12.6%</b></td><td>−43.2%</td><td><b>0.40</b></td><td>278</td></tr>
<tr><td style="text-align:left">动量+regime 量能因子 w=0.2</td><td>6.1%</td><td>−40.5%</td><td>0.16</td><td>278</td></tr>
<tr><td style="text-align:left">动量+regime 量能门槛</td><td>7.6%</td><td>−42.4%</td><td>0.21</td><td>107</td></tr>
</tbody></table>
<div class="note" style="background:#fdecea;border-color:#f5c6cb;color:#a93226">
<b>结论：量能因子在此框架上<b>没有更好效果，反而更差</b>——所有量能变体的年化与夏普都低于无量和基线。</b>
原因诊断：① OBV 本质是"带符号的累计量≈价格的累积代理"，与价格动量高度冗余却更噪；② 量能门槛把候选池从 278→107、67→25，
主动剔除了许多<b>先价涨后量跟</b>的有效趋势（量在价先≠量必须已确认，确认时往往已过最佳段）；③ 冗余过滤降低分散度、抬高集中。
<b>实操结论：核心策略不加入量能门槛</b>；通达信指标中仅把它作为<b>可视化参考</b>（放量柱高亮），不作为买点硬性条件。
</div>

<div class="foot">
数据来源：日线=新浪 K 线（沪深/科创；北交所不可达已排除）；基本面=东方财富 DMSK 年报；指数=上证(sh000001) 周线。
回测为历史模拟，含成本与 regime 空仓，不代表未来收益。本报告仅供参考，不构成个人投资建议。生成于 {datetime.date.today().isoformat()}。
</div></div></body></html>"""
open(os.path.join(WORK,'buy_list_compare.html'),'w',encoding='utf-8').write(html)
print("written -> buy_list_compare.html (%d bytes)"%len(html))
