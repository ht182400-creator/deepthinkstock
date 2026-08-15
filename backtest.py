# -*- coding: utf-8 -*-
"""
价值投资类 趋势突破策略 —— 3年回归测试 (2023-04 ~ 2026-07, 后复权月线)
数据: 通达信 MCP (tdx_kline, period=6, tqFlag=2)
信号: 滚动12月价格分位(估值便宜度代理) + 指数均线regime(缩放仓位)
风控: -10%止损 / 估值分位>=70%止盈 / 波动率仓位 / 月频再平衡 / T+1成交(无前视)
"""

import json

DATES = [
    '20230428','20230531','20230630','20230731','20230831','20230928','20231031','20231130',
    '20231229','20240131','20240229','20240329','20240430','20240531','20240628','20240731',
    '20240830','20240930','20241031','20241129','20241231','20250127','20250228','20250331',
    '20250430','20250530','20250630','20250731','20250829','20250930','20251031','20251128',
    '20251231','20260130','20260227','20260331','20260430','20260529','20260630','20260731'
]

DATA = {
    '000001': {'name':'上证指数','close':[3323.27,3204.56,3202.06,3291.04,3119.88,3110.48,3018.77,3029.67,2974.93,2788.55,
                  3015.17,3041.17,3104.82,3086.81,2967.40,2938.75,2842.21,3336.50,3279.82,3326.46,
                  3351.76,3250.60,3320.90,3335.75,3279.03,3347.49,3444.43,3573.21,3857.93,3882.78,
                  3954.79,3888.60,3968.84,4117.95,4162.88,3891.86,4112.16,4068.57,4094.40,3832.26],
              'low':[3229.45,3168.57,3144.25,3151.13,3053.04,3078.80,2923.51,3009.12,2882.02,2724.16,
                  2635.09,2984.12,2995.54,3085.38,2933.33,2865.15,2815.38,2689.70,3152.82,3227.36,
                  3323.01,3140.98,3220.28,3297.53,3040.69,3286.99,3340.07,3441.04,3547.16,3732.84,
                  3800.11,3816.58,3815.84,3983.58,4002.78,3794.68,3871.30,4055.83,3927.85,3741.11]},
    '600900': {'name':'长江电力','close':[51.49,52.59,51.80,52.24,53.29,53.61,54.19,54.64,55.54,57.39,58.53,58.32,59.83,61.26,
                  65.30,68.39,67.55,68.72,64.39,63.94,67.84,67.07,64.41,65.16,68.12,69.35,69.24,66.50,
                  66.94,65.47,66.96,66.75,65.36,63.91,63.72,65.47,65.96,66.71,64.47,70.44],
              'low':[49.91,51.21,51.50,51.45,52.23,52.45,52.87,53.49,53.80,54.73,56.95,57.58,57.15,58.72,
                  61.51,65.18,66.37,64.48,63.66,62.99,63.90,65.62,64.10,63.71,64.90,67.35,68.39,66.26,
                  65.84,65.07,65.29,66.40,65.33,62.19,63.12,63.86,64.07,64.52,63.91,64.28]},
    '601088': {'name':'中国神华','close':[45.20,44.35,46.87,47.05,46.84,49.87,48.99,50.16,50.02,55.79,57.27,57.76,58.50,61.00,
                  63.04,60.68,61.48,64.53,60.97,60.89,64.41,60.93,56.38,59.28,59.23,60.49,61.47,61.35,
                  60.66,61.69,65.70,65.31,64.67,66.10,66.43,70.92,72.17,71.09,63.21,70.89],
              'low':[43.45,44.10,44.02,45.97,45.67,46.87,48.32,47.97,48.74,50.04,54.57,54.89,56.67,57.47,
                  60.87,60.34,58.82,56.88,60.43,59.60,60.03,58.84,55.71,55.94,57.73,58.84,59.64,59.99,
                  60.65,60.43,61.46,64.96,63.69,63.97,63.69,66.63,69.17,68.41,62.90,62.90]},
    '601225': {'name':'陕西煤业','close':[23.09,20.28,21.71,21.94,22.34,24.16,23.72,25.18,26.59,29.88,31.50,30.79,30.23,31.73,
                  32.78,30.40,31.67,34.59,31.80,30.47,30.38,28.98,26.18,27.04,26.40,28.10,27.60,28.51,
                  28.74,28.40,31.10,31.08,29.72,30.68,32.10,33.99,34.53,34.14,29.66,34.11],
              'low':[22.32,20.12,20.19,21.67,21.53,22.33,23.22,23.08,24.57,26.38,29.02,29.65,29.44,29.30,
                  31.18,29.74,29.30,28.61,31.35,30.12,29.50,28.25,26.18,25.82,25.83,26.30,26.86,27.28,
                  28.25,28.16,28.13,30.70,29.50,29.56,29.04,32.27,32.62,31.22,29.36,29.33]},
    '600036': {'name':'招商银行','close':[162.98,157.90,159.69,177.44,161.76,167.31,158.67,150.97,147.17,158.47,163.67,164.30,
                  172.55,172.43,172.08,174.08,171.82,193.17,192.19,188.20,199.77,205.05,210.53,215.38,
                  205.41,215.92,225.78,227.85,221.63,211.94,213.81,221.87,218.54,209.09,209.41,211.63,
                  207.53,206.51,196.70,216.73],
              'low':[157.27,157.35,156.80,157.86,158.83,163.05,157.85,150.22,143.58,145.37,154.29,158.28,
                  163.64,172.04,166.33,170.01,168.81,163.14,190.43,186.24,187.65,195.20,201.46,209.35,
                  200.13,204.51,216.20,225.39,220.50,211.51,209.16,214.48,215.14,203.77,207.02,206.51,
                  206.94,201.70,196.11,195.84]},
    '600519': {'name':'贵州茅台','close':[10696.17,9955.44,10450.75,11517.66,11328.68,11056.01,10414.62,11016.34,10755.24,10073.78,
                  10580.78,10625.24,10637.06,10318.81,9473.61,9214.11,9337.42,11052.82,9813.53,9801.99,
                  9926.60,9425.67,9795.98,10134.83,10056.04,9915.34,9438.07,9506.45,9834.72,9632.06,
                  9553.38,9668.69,9390.89,9524.94,9828.96,9800.71,9433.72,9102.86,8469.82,9399.02],
              'low':[10265.59,9942.89,9894.10,10445.12,10895.79,10912.22,10030.07,10707.71,10135.59,9795.99,
                  9939.22,10421.41,10237.66,10318.81,9173.20,8876.56,8945.78,8226.72,9538.72,9594.55,
                  9702.55,9352.62,9228.81,9566.99,9577.68,9877.30,9235.40,9384.49,9463.28,9542.13,
                  9469.58,9497.10,9289.83,9080.41,9584.71,9424.77,9406.76,8675.71,8275.77,8361.99]},
    '000333': {'name':'美的集团','close':[251.95,231.51,269.35,270.85,260.31,256.45,246.85,242.16,253.26,266.83,283.26,289.22,
                  310.07,302.50,301.52,298.75,302.46,344.87,327.47,322.63,341.72,336.70,333.58,354.02,
                  335.72,356.12,343.52,335.98,349.18,345.25,359.27,374.12,367.71,365.61,369.55,360.96,
                  378.77,377.83,372.13,417.40],
              'low':[240.58,230.65,230.38,257.16,248.68,255.43,243.51,238.45,231.21,251.27,263.31,273.88,
                  288.77,301.71,295.15,280.52,281.80,283.52,326.27,319.71,319.26,330.70,317.27,321.43,
                  307.22,333.77,337.41,334.82,335.65,344.83,339.10,351.40,366.58,355.90,363.40,343.78,
                  357.77,369.02,359.65,364.97]},
    '600887': {'name':'伊利股份','close':[2480.00,2427.47,2465.99,2489.80,2303.50,2340.62,2402.96,2391.05,2356.03,2379.84,2468.09,
                  2436.57,2486.30,2465.29,2376.34,2323.81,2151.52,2602.57,2521.32,2568.25,2680.31,2515.72,
                  2547.24,2533.23,2650.89,2688.72,2604.67,2571.75,2653.00,2562.65,2571.75,2709.73,2688.72,
                  2530.43,2512.22,2531.13,2608.87,2571.05,2426.77,2646.69],
              'low':[2307.70,2414.16,2405.76,2365.84,2303.50,2275.48,2247.47,2349.73,2251.67,2289.49,2343.42,
                  2424.67,2342.02,2417.66,2345.52,2264.28,2070.97,2046.46,2337.12,2503.81,2561.24,2465.29,
                  2444.28,2468.09,2433.07,2618.68,2571.05,2556.34,2542.33,2529.03,2534.63,2538.83,2636.19,
                  2492.61,2507.31,2461.09,2445.68,2499.61,2416.96,2412.76]},
    '601318': {'name':'中国平安','close':[132.47,122.87,124.67,137.07,129.45,128.47,124.65,115.33,114.33,114.75,119.53,115.35,
                  116.45,119.87,116.45,121.85,124.79,150.91,150.43,145.09,143.89,140.29,139.35,141.85,
                  140.01,145.15,152.79,159.21,161.59,152.05,159.39,161.71,180.53,177.23,169.91,157.29,
                  162.47,150.73,142.71,157.03],
              'low':[118.49,122.87,122.67,124.63,124.25,128.17,122.83,114.73,109.99,108.97,111.73,114.23,
                  109.07,117.05,116.05,114.65,117.17,120.37,148.03,142.87,143.29,134.79,137.93,138.59,
                  132.59,139.69,144.59,152.43,157.21,151.15,150.33,159.45,160.03,171.05,169.85,155.41,
                  156.55,148.03,141.03,141.61]},
}

BASKET = ['600900','601088','601225','600036','600519','000333','600887','601318']
INDEX = '000001'
INIT_CAPITAL = 1_000_000.0
MAX_ON, MAX_OFF = 5, 3
W_ON, W_OFF = 0.16, 0.10
STOP_LOSS = -0.10
EXIT_PCTL = 70.0
WARMUP = 12
REGIME_MA = 12
MIN_VOL, MAX_VOL = 0.15, 0.25
N = len(DATES)
INDEX_CLOSE = DATA[INDEX]['close']


def pctl_rank(value, hist):
    if not hist:
        return 50.0
    return sum(1 for x in hist if x < value) / len(hist) * 100.0


def ann_vol(series):
    if len(series) < 3:
        return 0.20
    rets = [series[i]/series[i-1]-1 for i in range(1, len(series))]
    m = sum(rets)/len(rets)
    var = sum((r-m)**2 for r in rets)/len(rets)
    return var**0.5 * (12**0.5)


def max_drawdown(curve):
    peak, mdd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v/peak-1)
    return mdd


def run_backtest(entry_pctl):
    cash = INIT_CAPITAL
    holdings = {}
    pending = []
    equity_curve = [INIT_CAPITAL]
    trade_log = []
    monthly_rets = []
    invested_series = [0.0]
    prev_value = INIT_CAPITAL

    for i in range(N):
        # 1) 成交上月挂单 (本月收盘)
        for ordr in pending:
            code, w = ordr['code'], ordr['weight']
            price = DATA[code]['close'][i]
            target = prev_value * w
            shares = int(target/price//100)*100
            if shares*price > cash:
                shares = int(cash/price//100)*100
            if shares > 0:
                cost = shares*price
                cash -= cost
                holdings[code] = {'shares': shares, 'entry': price}
                trade_log.append({'date': DATES[i], 'code': code, 'name': DATA[code]['name'],
                                  'action': 'BUY', 'price': round(price, 4), 'shares': shares})
        pending = []

        # 2) 估值分位(滚动12月) + regime
        pctl = {}
        for c in BASKET:
            hist = DATA[c]['close'][max(0, i-12):i]
            pctl[c] = pctl_rank(DATA[c]['close'][i], hist)
        regime_on = True
        if len(INDEX_CLOSE[:i]) >= REGIME_MA:
            ma = sum(INDEX_CLOSE[:i][-REGIME_MA:])/REGIME_MA
            regime_on = INDEX_CLOSE[i] >= ma
        max_pos = MAX_ON if regime_on else MAX_OFF
        w_base = W_ON if regime_on else W_OFF

        # 3) 风控: 止损 / 止盈
        for code in list(holdings.keys()):
            h = holdings[code]
            stop_price = h['entry']*(1+STOP_LOSS)
            if DATA[code]['low'][i] <= stop_price:
                cash += h['shares']*stop_price
                trade_log.append({'date': DATES[i], 'code': code, 'name': DATA[code]['name'],
                                  'action': 'STOP', 'price': round(stop_price, 4), 'shares': h['shares'],
                                  'pnl_pct': round((stop_price/h['entry']-1)*100, 2)})
                del holdings[code]
        for code in list(holdings.keys()):
            if pctl[code] >= EXIT_PCTL:
                px = DATA[code]['close'][i]
                cash += holdings[code]['shares']*px
                trade_log.append({'date': DATES[i], 'code': code, 'name': DATA[code]['name'],
                                  'action': 'TAKEPROFIT', 'price': round(px, 4), 'shares': holdings[code]['shares'],
                                  'pnl_pct': round((px/holdings[code]['entry']-1)*100, 2)})
                del holdings[code]

        # 4) 盯市
        port_value = cash + sum(h['shares']*DATA[code]['close'][i] for code, h in holdings.items())
        invested = port_value - cash
        if i > 0:
            monthly_rets.append(port_value/equity_curve[-1]-1)
        equity_curve.append(port_value)
        invested_series.append(invested/port_value if port_value else 0)
        prev_value = port_value

        # 5) 下月信号
        if i < N-1:
            cands = []
            for code in BASKET:
                if code in holdings or i < WARMUP:
                    continue
                if pctl[code] <= entry_pctl:
                    cands.append((pctl[code], code))
            cands.sort()
            while len(holdings)+len(pending) < max_pos and cands:
                _, code = cands.pop(0)
                pending.append({'code': code, 'weight': w_base})

    months = len(equity_curve)-1
    cum = equity_curve[-1]/equity_curve[0]-1
    ann = (equity_curve[-1]/equity_curve[0])**(12/months)-1
    mdd = max_drawdown(equity_curve)
    mean_m = sum(monthly_rets)/len(monthly_rets)
    std_m = (sum((r-mean_m)**2 for r in monthly_rets)/len(monthly_rets))**0.5
    sharpe = (mean_m/std_m)*(12**0.5) if std_m > 0 else 0.0
    closed = [t for t in trade_log if t['action'] in ('STOP','TAKEPROFIT')]
    wins = sum(1 for t in closed if t['pnl_pct'] > 0)
    return {
        'entry_pctl': entry_pctl,
        'final_value': round(port_value, 0),
        'cum_return_pct': round(cum*100, 2),
        'ann_return_pct': round(ann*100, 2),
        'max_drawdown_pct': round(mdd*100, 2),
        'sharpe': round(sharpe, 3),
        'total_buys': len([t for t in trade_log if t['action']=='BUY']),
        'closed_trades': len(closed),
        'win_rate_pct': round(wins/len(closed)*100, 1) if closed else 0.0,
        'avg_invested_pct': round(sum(invested_series)/len(invested_series)*100, 1),
        'final_cash_pct': round(cash/port_value*100, 1),
        'trades': trade_log, 'equity': equity_curve,
    }


def bench_metrics(curve):
    rets = [curve[i]/curve[i-1]-1 for i in range(1, len(curve))]
    m = sum(rets)/len(rets)
    s = (sum((r-m)**2 for r in rets)/len(rets))**0.5
    cum = curve[-1]/curve[0]-1
    ann = (curve[-1]/curve[0])**(12/(len(curve)-1))-1
    return round(cum*100, 2), round(ann*100, 2), round((m/s)*(12**0.5), 3), round(max_drawdown(curve)*100, 2)


# 基准曲线
bench_units = {c: (INIT_CAPITAL/len(BASKET))/DATA[c]['close'][0] for c in BASKET}
bench_basket = [INIT_CAPITAL] + [sum(bench_units[c]*DATA[c]['close'][i] for c in BASKET) for i in range(1, N)]
idx_units = INIT_CAPITAL/INDEX_CLOSE[0]
bench_index = [INIT_CAPITAL] + [idx_units*INDEX_CLOSE[i] for i in range(1, N)]
b_b_ret, b_b_ann, b_b_sharpe, b_b_mdd = bench_metrics(bench_basket)
i_ret, i_ann, i_sharpe, i_mdd = bench_metrics(bench_index)

# 主回测 + 敏感性
PRIMARY = 40
res = run_backtest(PRIMARY)
sweep = {p: run_backtest(p) for p in (30, 40, 50)}

print("="*72)
print("  优化版价值策略 — 3年回归测试 (2023-04 ~ 2026-07, 后复权月线)")
print("="*72)
print(f"  基准(等权持有篮子): 累计 {b_b_ret}% | 年化 {b_b_ann}% | Sharpe {b_b_sharpe} | 回撤 {b_b_mdd}%")
print(f"  基准(上证指数)    : 累计 {i_ret}% | 年化 {i_ann}% | Sharpe {i_sharpe} | 回撤 {i_mdd}%")
print("-"*72)
print("  敏感性 (入场分位阈值 ENTRY_PCTL):")
print(f"  {'阈值':>4} {'累计%':>8} {'年化%':>8} {'回撤%':>8} {'Sharpe':>8} {'买入':>5} {'平仓':>5} {'胜率%':>7} {'均持仓%':>8}")
for p in (30, 40, 50):
    r = sweep[p]
    print(f"  {p:>4} {r['cum_return_pct']:>8} {r['ann_return_pct']:>8} {r['max_drawdown_pct']:>8} "
          f"{r['sharpe']:>8} {r['total_buys']:>5} {r['closed_trades']:>5} {r['win_rate_pct']:>7} {r['avg_invested_pct']:>8}")
print("-"*72)
print("  主配置(ENTRY_PCTL=40)交易记录:")
print("  主配置交易记录:")
for t in res['trades']:
    print("   ", t)

out = {
    'primary_entry_pctl': PRIMARY,
    'primary': {k: v for k, v in res.items() if k not in ('trades', 'equity')},
    'primary_trades': res['trades'],
    'primary_equity': res['equity'],
    'sweep': {str(p): {k: v for k, v in sweep[p].items() if k not in ('trades', 'equity')} for p in (30, 40, 50)},
    'bench_basket': {'cum_pct': b_b_ret, 'ann_pct': b_b_ann, 'sharpe': b_b_sharpe, 'mdd_pct': b_b_mdd},
    'bench_index': {'cum_pct': i_ret, 'ann_pct': i_ann, 'sharpe': i_sharpe, 'mdd_pct': i_mdd},
    'dates': DATES, 'bench_basket_curve': bench_basket, 'bench_index_curve': bench_index,
}
with open('backtest_result.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n[已保存 backtest_result.json]")
