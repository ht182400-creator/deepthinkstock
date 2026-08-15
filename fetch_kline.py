#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从东方财富公开行情接口拉取 A 股月线（后复权）数据。
用法: fetch_kline.py <code> [months] [fqt]
  code   : 6 位股票代码，如 000651 / 600519
  months : 回溯月数（默认 60）
  fqt    : 0 不复权 / 1 前复权 / 2 后复权（默认 2）
输出: JSON 数组，每项 {date, open, close, high, low, vol}
"""
import sys
import json
import urllib.request
import urllib.parse

EM_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def market_of(code: str) -> str:
    # 沪市 6/9 开头 -> 1；深市 0/3 开头 -> 0
    if code[0] in ("6", "9"):
        return "1"
    return "0"


def fetch(code: str, months: int = 60, fqt: int = 2):
    secid = f"{market_of(code)}.{code}"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3",
        "fields2": "f1,f2,f3,f4,f5,f6",
        "klt": "101",          # 101 = 月线
        "fqt": str(fqt),
        "beg": f"-{months}",   # 负数为相对回溯
        "end": "20500101",
    }
    url = EM_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    if obj.get("rc") != 0 or not obj.get("data"):
        return []
    out = []
    for k in obj["data"].get("klines", []):
        date, o, c, h, l, v = k.split(",")
        out.append({
            "date": date,
            "open": float(o),
            "close": float(c),
            "high": float(h),
            "low": float(l),
            "vol": float(v),
        })
    return out


if __name__ == "__main__":
    code = sys.argv[1]
    months = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    fqt = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    data = fetch(code, months, fqt)
    print(json.dumps(data, ensure_ascii=False))
