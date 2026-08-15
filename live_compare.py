# -*- coding: utf-8 -*-
"""生成"本周 vs 上周"信号对比的 JSON（live_compare.json），供 build_dashboard 渲染对比段。
同时落盘 live_buy_list_<信号日>.txt（与 live B 文本一致）。
原理：current_candidates 支持 today= 指定任意历史周信号日；本周取全局周轴末根，
上周取倒数第二根。进程内宇宙缓存(_get_universe)使两次计算只构建一次宇宙。

用法: python live_compare.py [cash] [N] [scheme]
"""
import os, sys, json
from regime_layer2_backtest import (current_candidates, format_live_report,
                                     _get_universe, WORK)

def main():
    cash = float(sys.argv[1]) if len(sys.argv) > 1 else 50000.0
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    scheme = sys.argv[3] if len(sys.argv) > 3 else 'B'

    # 本周：today=None → 全局周轴末根(最新信号)
    cur = current_candidates(scheme=scheme, cash=cash, N=N)
    txt = format_live_report(cur)
    txt_path = os.path.join(WORK, f"live_buy_list_{cur['signal_date']}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt + "\n")

    # 上周：全局周轴倒数第二根
    _, global_dates, _, _ = _get_universe(include_bj=True)
    prev = None
    prev_date = None
    if len(global_dates) >= 2:
        prev_date = global_dates[-2]
        prev = current_candidates(scheme=scheme, cash=cash, N=N, today=prev_date)

    def slim(res):
        if res is None:
            return None
        return dict(
            signal_date=res['signal_date'],
            regime_up=res['regime_up'],
            n_stocks=res['n_stocks'],
            selected=[dict(code=r['code'], name=r.get('name', r['code']), price=r['price'],
                           lots=r.get('lots', 0), capital=r.get('capital', 0),
                           mom=r['mom'], roe=r['roe'], sind=r.get('sind', ''))
                      for r in res['selected']],
            pool=[dict(code=r['code'], name=r.get('name', r['code']), price=r['price'],
                       mom=r['mom'], roe=r['roe'], sind=r.get('sind', ''))
                  for r in res['buy']],
        )

    out = dict(scheme=scheme, cash=cash, N=N,
               current=slim(cur), prev=slim(prev),
               prev_signal_date=prev_date,
               same_data=(prev is not None and prev['signal_date'] == cur['signal_date']))
    json_path = os.path.join(WORK, "live_compare.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # ---------- 控制台摘要 ----------
    print(f"[live_compare] 本周信号={cur['signal_date']} regime_up={cur['regime_up']} "
          f"建仓{len(cur['selected'])}只 合格池{len(cur['buy'])}只")
    if prev:
        cur_sel = {r['code'] for r in cur['selected']}
        prev_sel = {r['code'] for r in prev['selected']}
        cur_pool = {r['code'] for r in cur['buy']}
        prev_pool = {r['code'] for r in prev['buy']}
        print(f"              上周信号={prev['signal_date']} regime_up={prev['regime_up']} "
              f"建仓{len(prev['selected'])}只 合格池{len(prev['buy'])}只")
        print(f"              建仓变化: 新进{len(cur_sel - prev_sel)} "
              f"退出{len(prev_sel - cur_sel)} 维持{len(cur_sel & prev_sel)}")
        print(f"              合格池变化: 进入{len(cur_pool - prev_pool)} "
              f"退出{len(prev_pool - cur_pool)}")
    else:
        print("              无上周数据(全局周轴<2周)，跳过对比")
    print(f"              已写 -> {txt_path}")
    print(f"              已写 -> {json_path}")

if __name__ == "__main__":
    main()
