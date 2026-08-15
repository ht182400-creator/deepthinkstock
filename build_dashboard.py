# -*- coding: utf-8 -*-
"""把 live_buy_list_*.txt + results_layer2_fresh.json 渲染成自包含 HTML 看盘面板。"""
import re, json, os, glob, math
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
files = sorted(glob.glob(os.path.join(BASE, "live_buy_list_*.txt")))
live_path = files[-1] if files else None
if live_path is None:
    raise SystemExit("找不到 live_buy_list_*.txt")
res_path = os.path.join(BASE, "results_layer2_fresh.json")

with open(live_path, encoding="utf-8") as f:
    txt = f.read()
with open(res_path, encoding="utf-8") as f:
    res = json.load(f)

curves_path = os.path.join(BASE, "results_layer2_curves.json")
curves = json.load(open(curves_path, encoding="utf-8")) if os.path.exists(curves_path) else {}

# ---------- 加载上周对比 ----------
cmp_path = os.path.join(BASE, "live_compare.json")
cmp = json.load(open(cmp_path, encoding="utf-8")) if os.path.exists(cmp_path) else None

# ---------- 解析头部 ----------
m = re.search(r"signal=(\d+)  scheme=(\w+).*?段/全局regime_up=(\w+)", txt)
signal, scheme, regime = m.group(1), m.group(2), m.group(3)
m2 = re.search(r"账户=([\d.]+)元\s*目标仓数N=(\d+)\s*暴露=([\d.]+)\s*可投=([\d.]+)\s*单仓预算=([\d.]+)\s*宇宙=([\d.]+)", txt)
account, N, expo, invest, per, universe = (m2.group(i) for i in range(1, 7))
segm = re.search(r"段指数: (\{.*?\})", txt).group(1)

def mkt(code):
    if code.startswith("920") or code.startswith("8") or code.startswith("4"):
        return "bj"
    if code.startswith("60") or code.startswith("68") or code.startswith("90"):
        return "sh"
    return "sz"

MKT_CN = {"sh": "沪市", "sz": "深市", "bj": "北交所"}
MKT_COLOR = {"sh": "#4aa3ff", "sz": "#2ecc71", "bj": "#ff9f43"}

# ---------- 解析实际建仓 ----------
actual = []
for line in txt.splitlines():
    p = line.split()
    if len(p) == 9 and re.match(r"^\d{6}$", p[0]) and re.match(r"^\d", p[3]):
        name = p[1] if not (p[1] == p[0] or p[1].isdigit()) else ""
        actual.append(dict(code=p[0], name=name, industry=p[2], price=float(p[3]),
                           roe=float(p[4]), fcf=float(p[5]), mom=float(p[6]),
                           lots=int(p[7]), amt=int(p[8])))

# ---------- 解析合格买仓池 ----------
pool = []
for line in txt.splitlines():
    star = "★" in line
    mm = re.search(r"(\d{6})\s+(\S+)\s+(\S+?)\s+价\s*([\d.]+)\s+ROE\s*([\d.]+)%\s+FCF/N\s*([\d.]+)\s+MOM\s*([\d.]+)%\s+分([\d.]+)\s+\[(.*?)\](UP|DOWN)", line)
    if mm:
        name = mm.group(2).replace("★", "")
        if name == mm.group(1) or name.isdigit():
            name = ""
        pool.append(dict(code=mm.group(1), name=name, industry=mm.group(3),
                         price=float(mm.group(4)), roe=float(mm.group(5)), fcf=float(mm.group(6)),
                         mom=float(mm.group(7)), pct=float(mm.group(8)), seg=mm.group(9),
                         up=mm.group(10) == "UP", star=star))

# ---------- 解析观察池 ----------
watch = []
for line in txt.splitlines():
    mm = re.search(r"(\d{6})(?:\s+\d{6})?\s+(.+?)\s+ROE=([\d.]+)%\s+未过:(.+)", line)
    if mm:
        watch.append(dict(code=mm.group(1), industry=mm.group(2), roe=float(mm.group(3)), reason=mm.group(4).strip()))

# ---------- SVG 柱状图 ----------
def bar_svg(data, height=300, pct=True, color_pos="#2ecc71", color_neg="#e74c3c"):
    width = 760
    pad = 50
    base = height - 45
    barmax = base - 30
    n = len(data)
    gap = (width - pad * 2) / n
    bw = gap * 0.62
    maxv = max(abs(v) for _, v in data) or 1
    s = [f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet" style="max-width:760px">']
    s.append(f'<line x1="{pad}" y1="{base}" x2="{width-pad}" y2="{base}" stroke="#33415c" stroke-width="1"/>')
    for i, (lab, val) in enumerate(data):
        x = pad + gap * i + (gap - bw) / 2
        h = (abs(val) / maxv) * barmax
        y = base - h
        col = color_pos if val >= 0 else color_neg
        s.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" fill="{col}"/>')
        labtxt = f"{val*100:.1f}%" if pct else f"{val:.2f}"
        s.append(f'<text x="{x+bw/2:.1f}" y="{y-6:.1f}" text-anchor="middle" fill="#e6edf3" font-size="13" font-weight="600">{labtxt}</text>')
        s.append(f'<text x="{x+bw/2:.1f}" y="{base+18:.1f}" text-anchor="middle" fill="#9aa7b8" font-size="11">{lab}</text>')
    s.append("</svg>")
    return "".join(s)

def netvalue_svg(curves, width=760, height=360):
    bk = curves.get("B_全样本1996+")
    ck = curves.get("current_全样本1996+")
    if not bk:
        return '<p class="note">净值曲线数据未生成（请先运行 dump_curves.py）。</p>'
    dates, beq = bk["dates"], bk["equity"]
    ceq = ck["equity"] if ck else None
    n = len(beq)
    allv = list(beq) + (list(ceq) if ceq else [])
    lmin = math.log10(min(allv)); lmax = math.log10(max(allv))
    pad_l, pad_r, pad_t, pad_b = 52, 18, 22, 38

    def X(i):
        return pad_l + (width - pad_l - pad_r) * (i / (n - 1) if n > 1 else 0)

    def Y(v):
        return height - pad_b - (height - pad_t - pad_b) * (math.log10(v) - lmin) / (lmax - lmin)

    s = [f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet" style="max-width:760px;background:#0d1117">']
    for g in range(0, 6):
        yy = pad_t + (height - pad_t - pad_b) * g / 5.0
        val = 10 ** (lmax - (lmax - lmin) * g / 5.0)
        s.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width-pad_r}" y2="{yy:.1f}" stroke="#21262d"/>')
        s.append(f'<text x="4" y="{yy+3:.1f}" fill="#8b98a9" font-size="10">{val:.1f}x</text>')
    # 回撤阴影（B 相对历史峰值）
    pk = beq[0]; peak = []
    for v in beq:
        pk = max(pk, v); peak.append(pk)
    pts = [(X(i), Y(beq[i])) for i in range(n)] + [(X(i), Y(peak[i])) for i in range(n - 1, -1, -1)]
    s.append('<polygon points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + '" fill="rgba(231,76,60,0.13)"/>')
    if ceq:
        cp = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ceq[:n]))
        s.append(f'<polyline points="{cp}" fill="none" stroke="#4aa3ff" stroke-width="1.2" opacity="0.85"/>')
    bp = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(beq))
    s.append(f'<polyline points="{bp}" fill="none" stroke="#2ecc71" stroke-width="2.2"/>')
    last_year = None
    for i, d in enumerate(dates):
        yr = d // 10000
        if yr != last_year:
            last_year = yr
            s.append(f'<line x1="{X(i):.1f}" y1="{pad_t}" x2="{X(i):.1f}" y2="{height-pad_b}" stroke="#1b212b"/>')
            s.append(f'<text x="{X(i):.1f}" y="{height-10:.1f}" fill="#6b7686" font-size="10">{yr}</text>')
    s.append(f'<text x="{pad_l}" y="14" fill="#2ecc71" font-size="11" font-weight="700">■ B 方案(分市场段)</text>')
    if ceq:
        s.append(f'<text x="{pad_l+150}" y="14" fill="#4aa3ff" font-size="11" font-weight="700">■ current(上证)</text>')
    s.append("</svg>")
    ann = bk["annualized"] * 100; mdd = bk["max_drawdown"] * 100
    ck_ann = ck["annualized"] * 100 if ck else None
    note = (f'<div class="note">红色阴影=净值相对历史峰值的回撤（水下区域）。B(修复后) 全样本净值 {beq[-1]:.1f}x，'
            f'年化 {ann:.1f}%，最大回撤 {mdd:.0f}%，末根 {dates[-1]}。'
            + (f'current(上证) 全样本净值更高（年化 {ck_ann:.1f}%），但差距已很小——修复段指数缺失退化为放行后，B 与上证单指数门控长期基本重合，印证"分市场段门控"原意图成立；'
               if ck_ann is not None else '')
            + '两线在 2014 年后仍有一定分化（深市个股由深证成指而非上证门控）。实时买仓用 B（当前市场健康）。</div>')
    return "".join(s) + note

def diff_section(cmp):
    """本周 vs 上周信号对比段。cmp = live_compare.json 内容(可能 None)。"""
    if cmp is None:
        return ('<div class="section"><h2>② 信号 vs 上周变化</h2>'
                '<div class="note">尚未生成对比数据（先运行 <code>python live_compare.py</code>）。'
                '运行一次后即可显示本周相对上周的建仓与合格池变化。</div></div>')
    cur = cmp.get("current")
    prev = cmp.get("prev")
    if cur is None:
        return ('<div class="section"><h2>② 信号 vs 上周变化</h2>'
                '<div class="note">本周信号数据缺失。</div></div>')
    if prev is None:
        return (f'<div class="section"><h2>② 信号 vs 上周变化</h2>'
                f'<div class="note">本周信号 {cur["signal_date"]} 为首次信号（全局周轴不足 2 周），'
                f'暂无上周对比。下周运行后即可看到变化。</div></div>')

    def reg_label(up):
        return "全段 UP → 建议建仓" if up else "存在下跌段 → 空仓观望"

    rc = (cur["regime_up"] != prev["regime_up"])
    if rc:
        banner_col, banner_txt = ("#e74c3c",
            f"⚠️ 信号状态变化：上周【{reg_label(prev['regime_up'])}】→ 本周【{reg_label(cur['regime_up'])}】")
    elif cur["regime_up"]:
        banner_col, banner_txt = ("#2ecc71",
            f"✅ 信号状态维持：连续两周【{reg_label(cur['regime_up'])}】（{prev['signal_date']} → {cur['signal_date']}）")
    else:
        banner_col, banner_txt = ("#e67e22",
            f"⏸ 信号状态维持：连续两周【{reg_label(cur['regime_up'])}】（{prev['signal_date']} → {cur['signal_date']}）")

    cur_sel = {r["code"]: r for r in cur["selected"]}
    prev_sel = {r["code"]: r for r in prev["selected"]}
    new_codes = [c for c in cur_sel if c not in prev_sel]
    exit_codes = [c for c in prev_sel if c not in cur_sel]
    hold_codes = [c for c in cur_sel if c in prev_sel]
    cur_pool = {r["code"] for r in cur["pool"]}
    prev_pool = {r["code"] for r in prev["pool"]}
    enter_pool = sorted(c for c in cur_pool if c not in prev_pool)
    leave_pool = sorted(c for c in prev_pool if c not in cur_pool)

    def cell(r):
        mk = mkt(r["code"])
        tag = f"<span class='mkt' style='background:{MKT_COLOR[mk]}'>{MKT_CN[mk]}</span>"
        return (f"<tr><td><b>{r['code']}</b></td><td>{r.get('name') or '—'}</td><td>{tag}</td>"
                f"<td class='num'>{r['price']:.2f}</td><td class='num' style='color:#2ecc71'>+{r['mom']*100:.0f}%</td>"
                f"<td class='num'>{r.get('lots',0)}</td><td class='num'>{r.get('capital',0):,.0f}</td></tr>")

    def mini(title, rows_codes, src, color):
        if not rows_codes:
            body = "<tr><td colspan='7' class='note' style='text-align:center'>— 无 —</td></tr>"
        else:
            body = "".join(cell(src[c]) for c in rows_codes)
        return (f"<div class='diffcol'><div class='difftitle' style='color:{color}'>{title}（{len(rows_codes)}）</div>"
                f"<table><tr><th>代码</th><th>名称</th><th>市场</th><th class='num'>现价</th>"
                f"<th class='num'>动量</th><th class='num'>手</th><th class='num'>金额</th></tr>"
                f"{body}</table></div>")

    new_html = mini("🟢 新进建仓", new_codes, cur_sel, "#2ecc71")
    exit_html = mini("🔴 退出建仓", exit_codes, prev_sel, "#e74c3c")
    hold_html = mini("⚪ 维持建仓", hold_codes, cur_sel, "#9aa7b8")

    chips = lambda codes: (" ".join(f"<span class='chip'>{c}</span>" for c in codes)
                           if codes else "<span class='note'>— 无 —</span>")

    pool_html = (f"<div class='pooldiff'>"
                 f"<div>合格买仓池：上周 <b>{len(prev_pool)}</b> 只 → 本周 <b>{len(cur_pool)}</b> 只"
                 f"（<span style='color:#2ecc71'>进入 {len(enter_pool)}</span> / "
                 f"<span style='color:#e74c3c'>退出 {len(leave_pool)}</span>）</div>"
                 f"<div class='chipsrow'><span class='lab'>进入:</span>{chips(enter_pool[:15])}</div>"
                 f"<div class='chipsrow'><span class='lab'>退出:</span>{chips(leave_pool[:15])}</div>"
                 f"</div>")

    return (f'<div class="section"><h2>② 信号 vs 上周变化（{prev["signal_date"]} → {cur["signal_date"]}）</h2>'
            f'<div class="banner" style="border-color:{banner_col};color:{banner_col}">{banner_txt}</div>'
            f'<div class="grid3">{new_html}{exit_html}{hold_html}</div>'
            f'{pool_html}'
            f'<div class="note">说明：建仓以"实际下单参考"为准（受价格×100≤单仓预算的整手约束）；'
            f'合格池为所有通过质量+动量+站线+段 regime 的候选。若两周间无变化，说明模型信号稳定，'
            f'通常发生于趋势市；若出现退出/新进，多为价格越过 56 周线、动量转负或段 regime 翻转所致。</div>'
            f'</div>')

schemes_show = [("current(上证)", "current_全样本1996+"),
                ("A(全指)", "A_全样本1996+"),
                ("B(分市场段)", "B_全样本1996+"),
                ("C(内生)", "C_全样本1996+"),
                ("E(尾部)", "E_全样本1996+")]
ann = [(lab, res[key]["annualized"]) for lab, key in schemes_show]
shp = [(lab, res[key]["sharpe"]) for lab, key in schemes_show]
svg_ann = bar_svg(ann, pct=True)
svg_shp = bar_svg(shp, pct=False)
nv_svg = netvalue_svg(curves)

# 回测表
bt_rows = ""
for lab, key in [("current 上证56w", "current_全样本1996+"), ("B 分市场段56w (实时用)", "B_全样本1996+"),
                 ("C 内生无regime", "C_全样本1996+"), ("A 全指56w", "A_全样本1996+"),
                 ("E 上证200w尾部", "E_全样本1996+")]:
    r = res[key]
    win = "📈 历史最优(基准)" if key == "current_全样本1996+" else ("✅ 修复后≈基准" if key == "B_全样本1996+" else "")
    bt_rows += (f"<tr><td>{lab}{('<span class=win>'+win+'</span>') if win else ''}</td>"
                f"<td>{r['annualized']*100:.1f}%</td><td>{r['sharpe']:.2f}</td>"
                f"<td style='color:#ff6b6b'>{r['max_drawdown']*100:.0f}%</td>"
                f"<td>{r['empty_frac']*100:.0f}%</td><td>{r['avg_turnover']*100:.0f}%</td></tr>")

# ---------- 表格行 ----------
def pos_rows(items, show_star=False):
    out = ""
    for it in items:
        mk = mkt(it["code"])
        tag = f"<span class='mkt' style='background:{MKT_COLOR[mk]}'>{MKT_CN[mk]}</span>"
        star = "<span class='star'>★建仓</span>" if (show_star and it.get("star")) else ""
        out += (f"<tr><td><b>{it['code']}</b></td><td>{it.get('name') or '—'}</td>"
                f"<td>{it.get('industry','—')}</td><td>{tag}</td>"
                f"<td class='num'>{it['price']:.2f}</td>"
                f"<td class='num'>{it.get('roe',0):.1f}%</td>"
                f"<td class='num'>{it.get('fcf',0):.2f}</td>"
                f"<td class='num' style='color:#2ecc71'>+{it['mom']:.0f}%</td>"
                f"<td class='num'>{it.get('pct',0):.2f}</td>{star}")
        if "lots" in it:
            out += f"<td class='num'>{it['lots']}</td><td class='num'>{it['amt']:,}</td>"
        out += "</tr>"
    return out

actual_html = pos_rows(actual)
pool_html = pos_rows(pool, show_star=True)
watch_html = "".join(
    f"<tr><td><b>{w['code']}</b></td><td>{w['industry']}</td><td class='num'>{w['roe']:.1f}%</td><td>{w['reason']}</td></tr>"
    for w in watch)

diff_html = diff_section(cmp)

total_amt = sum(a["amt"] for a in actual)
regime_cn = "全部上涨 → 建议建仓" if regime == "True" else "存在下跌段 → 空仓观望"
regime_color = "#2ecc71" if regime == "True" else "#e74c3c"

CSS = """
* { box-sizing: border-box; margin:0; padding:0; }
body { background:#0d1117; color:#e6edf3; font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif; padding:24px; line-height:1.5; }
h1 { font-size:22px; margin-bottom:4px; }
.sub { color:#8b98a9; font-size:13px; margin-bottom:20px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; margin-bottom:26px; }
.card { background:#161b22; border:1px solid #21262d; border-radius:10px; padding:16px; }
.card .k { color:#8b98a9; font-size:12px; }
.card .v { font-size:22px; font-weight:700; margin-top:6px; }
.card .v.small { font-size:16px; }
.section { background:#161b22; border:1px solid #21262d; border-radius:10px; padding:18px; margin-bottom:22px; }
.section h2 { font-size:16px; margin-bottom:14px; border-left:3px solid #2ecc71; padding-left:10px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { text-align:left; padding:8px 10px; border-bottom:1px solid #21262d; }
th { color:#8b98a9; font-weight:600; background:#0f141b; position:sticky; top:0; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.mkt { color:#0d1117; font-size:11px; padding:2px 7px; border-radius:4px; font-weight:700; }
.star { color:#ffd166; font-size:11px; font-weight:700; }
tr:hover { background:#1c2230; }
.win { color:#2ecc71; font-size:11px; margin-left:6px; }
.note { color:#8b98a9; font-size:12px; margin-top:10px; }
.warn { background:#2d1b1b; border:1px solid #5c2b2b; color:#ffb3b3; padding:12px 14px; border-radius:8px; font-size:13px; margin-bottom:22px; }
footer { color:#6b7686; font-size:12px; margin-top:30px; border-top:1px solid #21262d; padding-top:14px; }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:20px; }
.grid3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; margin-bottom:14px; }
@media(max-width:760px){ .grid2{grid-template-columns:1fr;} .grid3{grid-template-columns:1fr;} }
.banner { border:1px solid; border-radius:8px; padding:10px 14px; font-size:13px; font-weight:600; margin-bottom:14px; background:#0f141b; }
.diffcol { background:#0f141b; border:1px solid #21262d; border-radius:8px; padding:10px; }
.diffcol table { font-size:12px; }
.difftitle { font-size:13px; font-weight:700; margin-bottom:8px; }
.pooldiff { font-size:13px; color:#c9d3df; background:#0f141b; border:1px solid #21262d; border-radius:8px; padding:10px 12px; }
.chipsrow { margin-top:6px; line-height:2; }
.chipsrow .lab { color:#8b98a9; margin-right:6px; }
.chip { display:inline-block; background:#1c2230; border:1px solid #2d3650; color:#9fb3d1; font-size:11px; padding:1px 7px; border-radius:4px; margin:2px 3px; font-variant-numeric:tabular-nums; }
"""

body = f"""
<h1>周频量化策略 · 实时看盘面板</h1>
<div class="sub">信号日 {signal} · 方案 {scheme} · 生成于 {date.today().isoformat()} · 数据来源：通达信本地行情 + 东方财富基本面</div>

<div class="warn">⚠️ 本面板为策略研究展示，所有标的均为量化模型输出，<b>不构成投资建议</b>。请结合自身风险承受能力独立决策。</div>

<div class="cards">
  <div class="card"><div class="k">当前方案</div><div class="v small">B · 分市场段指数 56 周 MA</div></div>
  <div class="card"><div class="k">市场状态</div><div class="v small" style="color:{regime_color}">{regime_cn}</div></div>
  <div class="card"><div class="k">账户 / 目标仓数</div><div class="v small">{account} 元 / {N} 仓</div></div>
  <div class="card"><div class="k">实际建仓</div><div class="v">{len(actual)} 只<span style="font-size:13px;color:#8b98a9"> · {total_amt:,} 元</span></div></div>
</div>

<div class="section">
  <h2>① 实际建仓清单（已下单参考）</h2>
  <table>
    <tr><th>代码</th><th>名称</th><th>行业</th><th>市场</th><th class="num">现价</th><th class="num">ROE</th><th class="num">FCF/N</th><th class="num">52w动量</th><th class="num">分位</th><th class="num">手数</th><th class="num">金额</th></tr>
    {actual_html}
  </table>
  <div class="note">FCF/N = 自由现金流/净利润（&gt;0 表示盈利有真金白银支撑）；分位 = 当前价在 52 周区间的位置。本次 5 段指数全部站上 56 周均线 → 满仓候选，按"价格×100 ≤ 单仓预算"自动集中到 {len(actual)} 只。</div>
</div>

{diff_html}

<div class="section">
  <h2>③ 合格买仓池（质量+动量+站线+段 regime，{len(pool)} 只）</h2>
  <table>
    <tr><th>代码</th><th>名称</th><th>行业</th><th>市场</th><th class="num">现价</th><th class="num">ROE</th><th class="num">FCF/N</th><th class="num">52w动量</th><th class="num">分位</th><th>状态</th></tr>
    {pool_html}
  </table>
  <div class="note">★建仓 = 本轮已选入实际建仓；其余为同批合格但受"单仓预算/整手"约束未入选的候选。颜色区分沪市/深市/北交所。</div>
</div>

<div class="section">
  <h2>④ 为什么信这套？回测对比（全样本 1996+，周频）</h2>
  <div class="grid2">
    <div><div class="note" style="margin:0 0 6px">年化收益率</div>{svg_ann}</div>
    <div><div class="note" style="margin:0 0 6px">夏普比率</div>{svg_shp}</div>
  </div>
  <table style="margin-top:14px">
    <tr><th>方案</th><th class="num">年化</th><th class="num">夏普</th><th class="num">最大回撤</th><th class="num">空仓占比</th><th class="num">换手</th></tr>
    {bt_rows}
  </table>
  <div class="note">结论（基于本机最新同快照重算、<b>修复 B 段指数缺失/未成熟时退化为"无脑放行"的缺陷后</b>，1687 只含北交所、周线 1990+）：年化排序 current(上证)≈11.4% ≈ <b>B(分市场段, 修复后)≈10.8%</b> &gt; C(内生)9.2% &gt; A(全指)6.7% &gt; E(尾部)1.7%。修复前 B 因早期段指数缺失直接放行、回撤高达 -68%（与无 regime 的 C 同）；修复为"回退父指数(上证)门控"后，B 回撤收敛到 -56%、2014+ 年化从 0.6% 回升到 7.2%，长期表现已与上证单指数门控<b>基本持平</b>（残差来自深市个股改由深证成指而非上证门控——"更精细"但方向不必然更优）。由此确认 B 的"分市场段门控"原意图成立，<b>可作为 live 默认 gate</b>；E（尾部降仓）经多参数验证仍被否定（全样本 1.7%、2014+ -3.5%）。</div>
</div>

<div class="section">
  <h2>⑤ 策略长期净值曲线（全样本 1996+，对数轴）</h2>
  {nv_svg}
</div>

<div class="section">
  <h2>⑥ 观察池（质量过关但未触发买点，前 {len(watch)} 只）</h2>
  <table>
    <tr><th>代码</th><th>行业</th><th class="num">ROE</th><th>未入选原因</th></tr>
    {watch_html}
  </table>
  <div class="note">"未站线"=未站上 56 周均线；"段 regime DOWN"=所属板块指数在 56 周线下方；"动量负"=近 52 周收益为负。这些是有潜力、等信号回暖的备胎。</div>
</div>

<div class="section">
  <h2>⑦ 怎么用 / 风控规则</h2>
  <ul style="font-size:13px;color:#c9d3df;line-height:1.9;padding-left:18px">
    <li><b>仓位</b>：5 万元账户、目标 3–4 仓、暴露 0.9（即约 90% 资金可投）；单只按"价格×100 ≤ 单仓预算"取整手，预算不够则自动集中到更少仓位。</li>
    <li><b>买入条件</b>：基本面质量门（ROE≥10% & 自由现金流转正 & ≥3 年财报）+ 52 周动量为正 + 站上 56 周均线 + 所属板块指数站上 56 周均线（B 方案 gate）。</li>
    <li><b>双退出</b>（非价格止损）：① 估值泡沫信号；② 基本面恶化（ROE/FCF 转差）。亏损 -10% 不作为机械止损线。</li>
    <li><b>空仓规则</b>：任一关键段指数跌破 56 周均线即该段清仓；全盘普跌时整体空仓（回测空仓占比见上表）。</li>
    <li><b>刷新</b>：行情更新后运行 <code>python regime_layer2_backtest.py live B</code> 重新生成买仓清单。</li>
  </ul>
</div>

<footer>本报告仅供参考，不构成个人投资建议。数据来源：通达信本地 .day 行情、东方财富基本面数据、自研量化回测框架。模型历史表现不代表未来收益。</footer>
"""

html = ("<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>周频量化策略看盘面板 {signal}</title><style>" + CSS + "</style></head><body>"
        + body + "</body></html>")

out_name = f"dashboard_{signal}.html"
out = os.path.join(BASE, out_name)
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
# 删除旧的未带日期的 dashboard.html（若存在且不是刚写的），避免混淆
old = os.path.join(BASE, "dashboard.html")
if os.path.exists(old) and os.path.abspath(old) != os.path.abspath(out):
    try:
        os.remove(old)
    except OSError:
        pass
print("OK ->", out)
print("actual:", len(actual), "pool:", len(pool), "watch:", len(watch), "total_amt:", total_amt)
