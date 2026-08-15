# -*- coding: utf-8 -*-
"""用本机最新数据(同快照)重算回测汇总指标 + 净值曲线，落盘给 dashboard。
避免和旧的 results_layer2.json(不同数据快照) 打架，保证面板内部自洽。"""
import os, json
import regime_layer2_backtest as R

print("build universe (.day + qfq)...")
stocks, global_dates, global_pkeys, idx0 = R.build_universe_layer2()
print("  stocks=%d weeks=%d" % (len(stocks), len(global_dates)))

indices = {'sh000001': idx0}
for sym in ['sh000985', 'sh000688', 'sz399006', 'sz399001', 'bj899050']:
    ix = R.build_index_weekly(sym)
    if ix:
        indices[sym] = ix

def run(sch, scope, sd):
    fn = R.make_regime_fn(sch, indices)
    return R.run_backtest_layer2(stocks, global_dates, sch, fn, scope,
                                 N=15, mom_window=52, val_window=260,
                                 cost_per_side=0.0012, warmup=220,
                                 start_date=sd, end_date=None)

def slice_dates(sd):
    sd_int = int(sd.replace('-', '')) if sd else None
    t_start = 220
    if sd_int:
        for i in range(220, len(global_dates)):
            if global_dates[i] >= sd_int:
                t_start = i
                break
    t_end = len(global_dates) - 1
    return t_start, t_end

SCHEMES = [('current', 'global'), ('A', 'global'), ('B', 'stock'), ('C', 'global'), ('E', 'global')]
WINDOWS = [(None, '全样本1996+'), ('2014-01-01', '2014+')]

stats = {}
curves = {}
for sch, scope in SCHEMES:
    for sd, wlbl in WINDOWS:
        r = run(sch, scope, sd)
        key = f"{sch}_{wlbl}"
        stats[key] = {
            'annualized': r['annualized'], 'sharpe': r['sharpe'],
            'max_drawdown': r['max_drawdown'], 'empty_frac': r['empty_frac'],
            'avg_turnover': r['avg_turnover'], 'avg_quality_pool': r['avg_quality_pool'],
            'periods': r['periods'],
        }
        # 曲线：B / current 两个方案都存（full + 2014+）
        if sch in ('B', 'current'):
            eq = r['equity_curve']
            t_start, t_end = slice_dates(sd)
            dates = global_dates[t_start: t_end + 1]
            n = min(len(eq), len(dates))
            curves[key] = {'dates': dates[:n], 'equity': eq[:n],
                           'annualized': r['annualized'], 'sharpe': r['sharpe'],
                           'max_drawdown': r['max_drawdown']}
        print("  %-18s ann=%5.1f%% sharpe=%4.2f mdd=%5.1f%%" %
              (key, r['annualized'] * 100, r['sharpe'], r['max_drawdown'] * 100))

json.dump(stats, open(os.path.join(R.WORK, 'results_layer2_fresh.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
json.dump(curves, open(os.path.join(R.WORK, 'results_layer2_curves.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print("written -> results_layer2_fresh.json + results_layer2_curves.json")
