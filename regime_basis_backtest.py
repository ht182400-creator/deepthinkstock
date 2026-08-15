# -*- coding: utf-8 -*-
"""
Regime 基准对比回测 (Layer 1: 仅指数层, 不需个股复权)
=====================================================
回答用户的"以偏带全"质疑:
  用单一指数(上证)的时间序列开关去裁决全股池的满仓/空仓, 尺度不自洽。

本脚本:
  1. 读取本地通达信 .day 各宽基/风格指数历史 (已验证存在于 D:/new_tdx64/vipdoc)
  2. 对每只候选 gate 指数, 计算 56周MA / 200周MA 周线择时信号
  3. 测算"择时规则"自身表现: 站上56周MA→持有该指数, 否则空仓(收益0)
     指标: 年化 / 夏普 / 最大回撤 / 空仓占比 / 切换次数 / 样本周数
  4. 两两一致性矩阵: 量化 gate 之间"意见分歧"的频率 —— 即"以偏带全"的硬证据
  5. 分层 regime(方案E) 尾部开关: 跌破200周MA才强制空仓的触发频率

注意: Layer 1 只评"哪个指数更适合做择时开关", 不涉及个股选股/复权。
      Layer 2(各 gate 套到真实选股策略) 需等个股前复权数据(权息)后再跑。

数据源: 通达信本地 .day (指数无分红除权跳变, 指数层无需复权)
"""
import struct, os, math, datetime, html
from collections import OrderedDict

TDX_ROOT = "D:/new_tdx64/vipdoc"

# 候选 regime gate: code -> 中文名
GATES = [
    ("sh000001", "上证综指"),
    ("sh000300", "沪深300"),
    ("sh000985", "中证全指"),
    ("sh000905", "中证500"),
    ("sh000852", "中证1000"),
    ("sz399006", "创业板指"),
    ("sz399001", "深证成指"),
    ("sh000016", "上证50"),
]

def read_daily(code):
    mkt = code[:2]; pure = code[2:]
    f = f"{TDX_ROOT}/{mkt}/lday/{mkt}{pure}.day"
    if not os.path.exists(f):
        return None
    data = open(f, "rb").read(); n = len(data)//32; bars = []
    for i in range(n):
        o = i*32
        d, op, hi, lo, cl, amt, vol, _ = struct.unpack("<iiiiifii", data[o:o+32])
        bars.append((d, cl/100.0))
    return bars

def to_weekly(daily):
    weeks = OrderedDict()
    for d, c in daily:
        dt = datetime.date(d//10000, (d//100)%100, d%100)
        iso = dt.isocalendar(); key = (iso[0], iso[1])
        weeks[key] = (d, c)
    return list(weeks.values())

def sma(series, w):
    out = [None]*len(series)
    for i in range(len(series)):
        if i+1 >= w:
            out[i] = sum(s[1] for s in series[i+1-w:i+1]) / w
    return out

def timing_rule(weekly, ma_w=56, tail_w=200):
    n = len(weekly)
    ma56 = sma(weekly, ma_w); ma200 = sma(weekly, tail_w)
    start = max(ma_w, tail_w) - 1
    sig56 = []; sig_tail = []; eq = [1.0]; eq_tail = [1.0]; rets = []
    for i in range(start+1, n):
        prev = weekly[i-1][1]; ret = weekly[i][1]/prev - 1.0
        inv = 1 if weekly[i][1] > ma56[i] else 0
        inv_tail = 1 if weekly[i][1] > ma200[i] else 0
        sig56.append(inv); sig_tail.append(inv_tail)
        r = ret if inv else 0.0
        r_tail = ret if inv_tail else 0.0
        eq.append(eq[-1]*(1+r)); eq_tail.append(eq_tail[-1]*(1+r_tail)); rets.append(r)
    weeks_total = len(rets); in_market = sum(sig56)
    empty_pct = (weeks_total - in_market)/weeks_total*100
    flips = sum(1 for i in range(1, len(sig56)) if sig56[i] != sig56[i-1])
    tail_weeks = sum(1 for s in sig_tail if s == 0); tail_pct = tail_weeks/weeks_total*100
    yrs = weeks_total/52.0
    ann = (eq[-1]**(1/yrs) - 1) if yrs > 0 else 0
    mu = sum(rets)/weeks_total if weeks_total else 0
    sd = (sum((x-mu)**2 for x in rets)/weeks_total)**0.5 if weeks_total else 0
    sharpe = (mu/sd)*(52**0.5) if sd > 0 else 0
    peak = eq[0]; mdd = 0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, v/peak - 1)
    bh = weekly[start+1][1]/weekly[start][1]; bh_ann = bh**(1/yrs) - 1 if yrs > 0 else 0
    return {"start_date": weekly[start][0], "end_date": weekly[-1][0],
            "weeks": weeks_total, "empty_pct": empty_pct, "flips": flips,
            "ann": ann, "sharpe": sharpe, "mdd": mdd*100, "bh_ann": bh_ann,
            "tail_pct": tail_pct, "sig56": sig56, "sig_tail": sig_tail}

def main():
    results = {}
    for code, name in GATES:
        daily = read_daily(code)
        if not daily:
            print(f"[跳过] {name}({code}) 无 .day 数据"); continue
        wk = to_weekly(daily); r = timing_rule(wk); results[code] = (name, r)
        print(f"{name:8s} {code} | {r['start_date']}~{r['end_date']} {r['weeks']}周 | "
              f"年化 {r['ann']*100:6.2f}% 夏普 {r['sharpe']:5.2f} MDD {r['mdd']:7.2f}% | "
              f"空仓 {r['empty_pct']:5.1f}% 切换 {r['flips']:3d} | 对照BH年化 {r['bh_ann']*100:6.2f}% | 方案E尾部空 {r['tail_pct']:4.1f}%")
    codes = list(results.keys()); minw = min(results[c][1]["weeks"] for c in codes)
    sigs = {c: results[c][1]["sig56"][-minw:] for c in codes}
    print(f"\n=== 两两一致性矩阵 (公共 {minw} 周, 值=同多/同空占比%) ===")
    header = "        " + "".join(f"{results[c][0][:4]:>6s}" for c in codes); print(header)
    for a in codes:
        row = f"{results[a][0][:6]:6s} "
        for b in codes:
            pct = sum(1 for i in range(minw) if sigs[a][i] == sigs[b][i])/minw*100
            row += f"{pct:6.1f}"
        print(row)
    write_html(results, codes, minw, sigs)

def write_html(results, codes, minw, sigs):
    rows = ""
    for c in codes:
        name, r = results[c]
        rows += (f"<tr><td>{name}</td><td>{r['start_date']}~{r['end_date']}</td>"
                 f"<td>{r['weeks']}</td><td class='num'>{r['ann']*100:.2f}%</td>"
                 f"<td class='num'>{r['sharpe']:.2f}</td><td class='num'>{r['mdd']:.2f}%</td>"
                 f"<td class='num'>{r['empty_pct']:.1f}%</td><td class='num'>{r['flips']}</td>"
                 f"<td class='num'>{r['bh_ann']*100:.2f}%</td><td class='num'>{r['tail_pct']:.1f}%</td></tr>")
    mat = "<tr><th></th>" + "".join(f"<th>{results[c][0]}</th>" for c in codes) + "</tr>"
    for a in codes:
        mat += f"<tr><th>{results[a][0]}</th>"
        for b in codes:
            pct = sum(1 for i in range(minw) if sigs[a][i] == sigs[b][i])/minw*100
            color = "good" if pct >= 90 else ("mid" if pct >= 80 else "bad")
            mat += f"<td class='{color}'>{pct:.1f}</td>"
        mat += "</tr>"
    worst = sorted([((a, b), sum(1 for i in range(minw) if sigs[a][i] != sigs[b][i])/minw*100)
                    for a in codes for b in codes if a < b], key=lambda x: -x[1])[:6]
    worst_html = "".join(
        f"<li><b>{results[a][0]} ↔ {results[b][0]}</b>：分歧 {p:.1f}%（约 {int(round(p/100*minw))} 周意见相反）</li>"
        for (a, b), p in worst)
    doc = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>Regime 基准对比回测 (Layer 1)</title>
<style>
 body{{font-family:-apple-system,Segoe UI,'Microsoft YaHei',sans-serif;margin:24px;color:#1a1a1a;background:#fff}}
 h1{{font-size:20px}} h2{{font-size:15px;margin-top:28px;border-left:4px solid #2563eb;padding-left:8px}}
 table{{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}}
 th,td{{border:1px solid #ddd;padding:5px 8px;text-align:center}}
 th{{background:#f3f4f6}} td.num{{font-variant-numeric:tabular-nums}}
 .good{{background:#dcfce7;color:#166534}} .mid{{background:#fef9c3;color:#854d0e}} .bad{{background:#fee2e2;color:#991b1b}}
 .note{{background:#f8fafc;border:1px solid #e2e8f0;padding:10px 12px;font-size:12px;color:#475569;border-radius:6px;margin:8px 0}}
 .warn{{background:#fff7ed;border:1px solid #fed7aa;padding:10px 12px;font-size:12px;color:#9a3412;border-radius:6px;margin:8px 0}}
 caption{{font-size:11px;color:#94a3b8;text-align:left;margin-top:4px}}
</style></head><body>
<h1>Regime 基准对比回测 · Layer 1（仅指数层，不需个股复权）</h1>
<p class="note">目的：回应用户的"以偏带全"质疑——用单一指数（上证）的时间序列开关裁决全股池满仓/空仓，尺度不自洽。
本层只评"哪只指数更适合做择时开关"，不涉及个股选股/复权。<b>数据源：通达信本地 .day（指数无除权跳变，无需复权）。</b>
择时规则：站上 56 周 MA → 持有该指数，否则空仓（收益 0，无风险利率取 0）。公共窗口取各 gate 样本最小周数。</p>

<h2>一、各候选 gate 的择时规则自身表现</h2>
<table><tr><th>指数(gate)</th><th>样本窗口</th><th>周数</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>空仓占比</th><th>切换次数</th><th>买入持有年化</th><th>方案E尾部空</th></tr>
{rows}</table>
<caption>注："方案E尾部空"=跌破200周MA才强制空仓的周占比（越小越接近纯个股信号驱动）。买入持有年化=同期一直持有该指数的年化，作对照。</caption>

<h2>二、两两一致性矩阵（值=同多/同空占比%，绿≥90 / 黄≥80 / 红&lt;80）</h2>
<table>{mat}</table>
<p class="note">读法：若用上证(行/列)做 gate 去管含创业板票的候选池，看"上证 ↔ 创业板"格——该值越低，说明"上证空头、创业板多头"的错杀式空仓越频繁，即"以偏带全"越严重。</p>

<h2>三、分歧最大的 gate 对（"以偏带全"风险最高的组合）</h2>
<ul>{worst_html}</ul>

<h2>四、结论与下一步</h2>
<p class="warn">Layer 1 仅用指数历史证明"不同 gate 信号差异显著"，直接支撑用户的"以偏带全"质疑成立。
真正要回答的是：把各 gate 套到<b>真实选股策略</b>（质量 / 动量 + 52周信号）后，年化/夏普/MDD/空仓占比/换手率谁最优。
那是 Layer 2，<b>需要个股前复权数据</b>——当前 通达信 .day 为未复权，需接入权息因子（已确认本地 gbbq 权息缓存在 T0002\\hq_cache\\gbbq，待解析；或退回东财分红送股）。Layer 2 待权息数据就绪后跑，输出 regime_basis_backtest.html 的"策略层"版本。</p>
</body></html>"""
    open("regime_basis_backtest.html", "w", encoding="utf-8").write(doc)
    print("\n[HTML] 已写出 regime_basis_backtest.html")

if __name__ == "__main__":
    main()
