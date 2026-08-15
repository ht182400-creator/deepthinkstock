# -*- coding: utf-8 -*-
"""
抓取东财"前复权"日线, 作为 Layer 2 策略回测的复权价源
=====================================================
为什么用东财前复权:
  - 本地通达信 .day 是【未复权】, 且无可读权息文件 (T0002/hq_cache/gbbq 经实测为
    压缩/加密二进制, 不可直接解析)。
  - 东财 push2his kline 接口 (fqt=1) 直接返回前复权日线, 一键到位, 无需自己算复权因子。
  - 自校验: 前复权锚定在"最新交易日", 故每只股票最后一根前复权收盘价 == 本地未复权
    最后收盘价。脚本用本地 .day 末收做硬核对, 偏差 >1% 即告警。两源一致 = 可信。

运行: 本脚本需在本机(可访问 eastmoney)跑, 沙箱网络不通东财。
  python fetch_qfq_prices.py            # 全量抓取(支持断点续跑)
  python fetch_qfq_prices.py --dry      # 只枚举本地股票+本地末收, 不联网, 验证脚本逻辑

输出: qfq_prices/{sh,sz,bj}/{6位代码}.csv  (date,open,close,high,low,volume)
依赖: 仅标准库 (urllib/json/csv/struct) —— 无需 pip 安装。
注: 北交所(bj)东财覆盖可能不全, 抓取失败会跳过并计入 fail, 不影响沪深。
"""
import struct, os, json, csv, time, sys, urllib.request

TDX_ROOT = "D:/new_tdx64/vipdoc"
OUT_DIR = "qfq_prices"
EM_BASE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# 已知指数代码 (跳过, 不抓前复权)
SH_INDEX = {"000001","000300","000905","000985","000852","000016","000688",
            "000698","000015","000010","000009","000300"}
SZ_INDEX_PREFIX = "399"  # 深证/创业板指数

def local_last_close(code):
    mkt = code[:2]; pure = code[2:]
    f = f"{TDX_ROOT}/{mkt}/lday/{mkt}{pure}.day"
    if not os.path.exists(f):
        return None
    data = open(f, "rb").read(); n = len(data)//32
    if n == 0:
        return None
    d, _, _, _, cl, _, _, _ = struct.unpack("<iiiiifii", data[(n-1)*32:(n-1)*32+32])
    return d, cl/100.0

def is_index(code):
    mkt, pure = code[:2], code[2:]
    if mkt == "sz" and pure.startswith(SZ_INDEX_PREFIX):
        return True
    if mkt == "sh" and pure in SH_INDEX:
        return True
    return False

def secid(code):
    if code.startswith("sh"):
        return "1." + code[2:]
    if code.startswith("sz"):
        return "0." + code[2:]
    if code.startswith("bj"):
        return "0." + code[2:]   # 北交所 best-effort
    return None

def fetch_qfq(code):
    sid = secid(code)
    if not sid:
        return None
    url = (f"{EM_BASE}?secid={sid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=0&end=20500101")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    if not obj.get("data") or not obj["data"].get("klines"):
        return None
    rows = []
    for k in obj["data"]["klines"]:
        p = k.split(",")
        date = p[0].replace("-", "")
        o, c, h, l, v = float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])
        rows.append((date, o, c, h, l, v))
    return rows

def enumerate_stocks():
    stocks = []
    for mkt in ["sh", "sz", "bj"]:
        d = os.path.join(TDX_ROOT, mkt, "lday")
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.endswith(".day") and fn.startswith(mkt):
                code = mkt + fn[2:-4]
                if is_index(code):
                    continue
                stocks.append(code)
    return stocks

def main():
    dry = "--dry" in sys.argv
    stocks = enumerate_stocks()
    print(f"本地 .day 个股数(去指数): {len(stocks)}")
    if dry:
        for code in stocks[:5]:
            print(code, "本地末收", local_last_close(code))
        print("[dry] 仅验证枚举逻辑, 不联网。")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    ok = skip = fail = warn = 0
    for code in stocks:
        mkt = code[:2]; pure = code[2:]
        outd = os.path.join(OUT_DIR, mkt)
        outf = os.path.join(outd, pure + ".csv")
        if os.path.exists(outf):   # 断点续跑
            ok += 1; continue
        local = local_last_close(code)
        try:
            rows = fetch_qfq(code)
        except Exception as e:
            print(f"[ERR] {code}: {e}"); fail += 1; time.sleep(0.1); continue
        if not rows:
            skip += 1; continue
        # 自校验: 找与本地末收同日期的前复权收盘价对比
        if local:
            ld, lc = local
            match = next((r for r in rows if r[0] == str(ld)), None)
            if match:
                diff = abs(match[2] - lc) / lc if lc else 0
                if diff > 0.01:
                    print(f"[WARN] {code}: 前复权({match[0]})={match[2]} vs 本地未复权={lc} 差{diff*100:.2f}%")
                    warn += 1
            else:
                # 本地日期不在东财范围内(本地更新), 跳过核对
                pass
        os.makedirs(outd, exist_ok=True)
        with open(outf, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "close", "high", "low", "volume"])
            for r in rows:
                w.writerow(r)
        ok += 1
        if ok % 200 == 0:
            print(f"  已成功 {ok} / 告警 {warn} / 跳过 {skip} / 失败 {fail}")
        time.sleep(0.03)   # 限速, 避免被封
    print(f"\n完成: 成功 {ok}, 跳过(无数据) {skip}, 失败 {fail}, 校验告警 {warn}")
    print(f"输出目录: {OUT_DIR}/")

if __name__ == "__main__":
    main()
