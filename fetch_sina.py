#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从新浪日线接口拉取候选池 + 上证指数的日线，聚合为月线。
数据源：Sina CN_MarketData.getKLineData (scale=240 日线)。
说明：新浪返回不复权价 -> 本序列为【价格收益】，不含分红（保守下限）。
硬筛选：面值（月线收盘价）> 300 元一律不进入可买集合（F 规则）。
输出：universe.json（workspace）
"""
import sys, json, subprocess, os, datetime

WORK = os.path.dirname(os.path.abspath(__file__))

# code -> (名称, 行业)
CANDIDATES = {
    "000568": ("泸州老窖", "白酒"),
    "600809": ("山西汾酒", "白酒"),
    "000858": ("五粮液", "白酒"),
    "603369": ("今世缘", "白酒"),
    "603198": ("迎驾贡酒", "白酒"),
    "600132": ("重庆啤酒", "啤酒"),
    "605499": ("东鹏饮料", "饮料"),
    "002847": ("盐津铺子", "零食"),
    "002032": ("苏泊尔", "小家电"),
    "002668": ("TCL智家", "家电"),
    "000651": ("格力电器", "家电"),
    "000333": ("美的集团", "家电"),
    "603605": ("珀莱雅", "化妆品"),
    "002027": ("分众传媒", "广告"),
    "002517": ("恺英网络", "游戏"),
    "603444": ("吉比特", "游戏"),
    "300628": ("亿联网络", "通信"),
    "600096": ("云天化", "化工"),
    "600066": ("宇通客车", "客车"),
    "600741": ("华域汽车", "汽配"),
    "601668": ("中国建筑", "建筑"),
    "600887": ("伊利股份", "乳业"),
    "000895": ("双汇发展", "肉制品"),
    "603288": ("海天味业", "调味品"),
    "600298": ("安琪酵母", "酵母"),
}
INDEX_CODE = "000001"  # 上证指数
PRICE_CAP = 300.0      # F 规则：面值上限
DATALEN = 5000         # 回溯日线根数（约 21 年，覆盖 2014-2018 样本外验证）

# 每股股息率（年化，小数）——用于 ③ 含分红回测。
# 说明：本沙箱无法抓取逐笔分红历史（腾讯/新浪分红接口被拦），此处为基于各标的历史
# 分红特征的【近似假设】（2024-2025 滚动股息率量级），仅作"含分红"近似，非精确数据。
DIV_YIELD = {
    "000568": 0.045, "600809": 0.030, "000858": 0.035, "603369": 0.030, "603198": 0.040,
    "600132": 0.020, "605499": 0.015, "002847": 0.010, "002032": 0.035, "002668": 0.030,
    "000651": 0.055, "000333": 0.030, "603605": 0.005, "002027": 0.045, "002517": 0.020,
    "603444": 0.040, "300628": 0.030, "600096": 0.040, "600066": 0.060, "600741": 0.025,
    "601668": 0.045, "600887": 0.040, "000895": 0.055, "603288": 0.015, "600298": 0.015,
}


def sina_symbol(code: str) -> str:
    return ("sh" if code[0] in ("6", "9") else "sz") + code


def fetch_by_symbol(sym: str):
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen={DATALEN}")
    out = subprocess.run(["curl", "-s", "--max-time", "25", url],
                         capture_output=True, text=True)
    raw = out.stdout.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def fetch_daily(code: str):
    return fetch_by_symbol(sina_symbol(code))


def to_monthly(daily):
    """daily: list of {day,open,high,low,close,volume} -> 月线 list"""
    months = {}
    for d in daily:
        ym = d["day"][:7]  # YYYY-MM
        o, h, l, c = float(d["open"]), float(d["high"]), float(d["low"]), float(d["close"])
        if ym not in months:
            months[ym] = {"date": d["day"], "open": o, "high": h, "low": l, "close": c, "vol": float(d["volume"])}
        else:
            m = months[ym]
            m["high"] = max(m["high"], h)
            m["low"] = min(m["low"], l)
            m["close"] = c
            m["vol"] += float(d["volume"])
            m["date"] = d["day"]
    return [months[k] for k in sorted(months.keys())]


def main():
    universe = {"meta": {"source": "Sina daily scale=240 (price-return, ex-div)",
                         "price_cap": PRICE_CAP,
                         "built": datetime.date.today().isoformat()},
                "index": None, "stocks": {}}

    # 指数（上证指数，固定 sh 前缀）
    idx_daily = fetch_by_symbol("sh000001")
    if idx_daily:
        universe["index"] = {"code": INDEX_CODE, "months": to_monthly(idx_daily)}
        print(f"[index] sh{INDEX_CODE} months={len(universe['index']['months'])} "
              f"last={universe['index']['months'][-1]['close']:.2f} @{universe['index']['months'][-1]['date']}")
    else:
        print("[WARN] index fetch failed")

    for code, (name, ind) in CANDIDATES.items():
        daily = fetch_daily(code)
        if not daily:
            print(f"[SKIP] {code} {name} 数据缺失")
            continue
        m = to_monthly(daily)
        last_close = m[-1]["close"]
        cap_excluded = last_close > PRICE_CAP
        universe["stocks"][code] = {
            "name": name, "industry": ind,
            "months": m,
            "last_close": last_close,
            "cap_excluded": cap_excluded,
            "div_yield": DIV_YIELD.get(code, 0.0),
        }
        flag = "CAP>300 EXCL" if cap_excluded else "ok"
        print(f"[{flag}] {code} {name}({ind}) months={len(m)} last={last_close:.2f} @{m[-1]['date']}")

    out_path = os.path.join(WORK, "universe.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(universe, f, ensure_ascii=False, indent=1)
    print(f"\nwritten -> {out_path}")
    n_total = len(universe["stocks"])
    n_excl = sum(1 for s in universe["stocks"].values() if s["cap_excluded"])
    print(f"stocks={n_total} cap_excluded={n_excl}")


if __name__ == "__main__":
    main()
