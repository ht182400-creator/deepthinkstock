# -*- coding: utf-8 -*-
"""
通达信本地 .day 日线解析器
=======================
路径规则(已实测, D:\\new_tdx64):
  D:\\new_tdx64\\vipdoc\\{sh,sz,bj}\\lday\\{前缀}{6位代码}.day
  - 沪市个股/指数  -> sh/lday   (上证000001, 沪深300 000300, 中证500 000905)
  - 深市个股/指数  -> sz/lday   (创业板399006, 深成指399001)
  - 北交所         -> bj/lday   (92开头新代码, 如 920185)
  - ds=扩展大盘 lday; cw=财务.dat; ot=期权(空)

.day 格式: 每根 32 字节, 小端 <iiiiifii
  date(4, YYYYMMDD) | open(4,*100) | high(4,*100) | low(4,*100) | close(4,*100)
  | amount(4, float, 成交额元) | volume(4, 手) | reservation(4)
  => 价格需 /100; amount 为成交额(元); volume 为成交量(手)

前复权由 gbbq 权息实现: 调 read_qfq(code) 直接返回前复权日线(锚定最新交易日, 末根==未复权末收)。
      依赖 decode_gbbq.py 生成的 all_xdxr.csv(优先) / 或运行时解密 gbbq。apply_qfq() 旧钩子保留兼容。
"""
import struct
import os

TDX_ROOT = "D:/new_tdx64/vipdoc"

# 板块归属: 前缀代码(如 sh600519) 或 纯6位代码
def code_to_market(code: str) -> str:
    c = code.lower()
    if c.startswith("sh") or c.startswith("sz") or c.startswith("bj"):
        return c[:2]  # 已带前缀
    # 纯6位代码
    if c.startswith("92") or c.startswith("83") or c.startswith("43") or c.startswith("8") or c.startswith("4"):
        return "bj"   # 北交所 92(新)/83,43(老)/8,4(老三板)
    if c.startswith("688") or c.startswith("6") or (c.startswith("9") and not c.startswith("92")):
        return "sh"   # 科创板688 / 沪市主板6 / 9开头(如900沪B)
    return "sz"       # 000/002/300/301 深市

def _path(code: str):
    mkt = code_to_market(code)
    pure = code[2:] if code[:2] in ("sh","sz","bj") else code
    return f"{TDX_ROOT}/{mkt}/lday/{mkt}{pure}.day", mkt

def read_day(code: str):
    """返回 list[{date,open,high,low,close,amount,volume}] 或 None"""
    f, mkt = _path(code)
    if not os.path.exists(f):
        return None
    data = open(f, "rb").read()
    n = len(data) // 32
    bars = []
    for i in range(n):
        o = i * 32
        d, op, hi, lo, cl, amt, vol, _ = struct.unpack("<iiiiifii", data[o:o+32])
        bars.append({
            "date": d,
            "open": op/100.0, "high": hi/100.0, "low": lo/100.0, "close": cl/100.0,
            "amount": amt, "volume": vol,
        })
    return bars

def read_close_series(code: str):
    """返回 [(date_int, close_float), ...] 未复权"""
    bars = read_day(code)
    if not bars:
        return None
    return [(b["date"], b["close"]) for b in bars]

def apply_qfq(bars, factors):
    """
    前复权钩子(兼容旧接口)。factors: 按日期降序的 (date, factor) 列表, factor=复权价/未复权价。
    新代码请直接用 read_qfq(code) (基于 gbbq 权息, 自动算因子)。
    """
    if not factors:
        return bars
    fac = dict(factors)
    out = []
    for b in bars:
        f = fac.get(b["date"], 1.0)
        nb = dict(b)
        for k in ("open","high","low","close"):
            nb[k] = b[k] * f
        out.append(nb)
    return out

# ---------- 前复权 (基于 gbbq 权息) ----------
def _norm_code(code):
    return "".join(ch for ch in code if ch.isdigit())

# 权息字段合理性上界(按"每10股"语义): 超出者视为 gbbq 中的垃圾/其他语义记录(股本变动类), 直接剔除。
# 茅台 2023 年报每10股派 308.76 仍远低于 2000, 安全; 垃圾累计值(如 167245)远超上界, 必被剔除。
_SANE_MAX = {"f_cash": 2000.0, "f_bonus": 30.0, "f_rights": 30.0, "f_rights_price": 2000.0}

def _sane_ev(ev):
    for k, v in ev.items():
        if k == "date_raw":
            continue
        if not (0 <= v <= _SANE_MAX[k]):
            return False
    return True

def _load_xdxr_map():
    """读 all_xdxr.csv -> {6位代码: [事件(dict)...] 升序}; 退路: 直接解密 gbbq。"""
    import csv as _csv
    here = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(here, "all_xdxr.csv")
    if os.path.exists(csv_path):
        m = {}
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            for r in _csv.DictReader(f):
                p = _norm_code(r.get("code", ""))
                if not p:
                    continue
                rec = {
                    "date_raw": int(r["date_raw"]),
                    "f_cash": float(r["f_cash"] or 0),
                    "f_rights_price": float(r["f_rights_price"] or 0),
                    "f_bonus": float(r["f_bonus"] or 0),
                    "f_rights": float(r["f_rights"] or 0),
                }
                if not _sane_ev(rec):
                    continue
                m.setdefault(p, []).append(rec)
        for p in m:
            m[p].sort(key=lambda x: x["date_raw"])
        return m
    # 退路: 解密 gbbq (需 decode_gbbq.py 同目录)
    try:
        import decode_gbbq as dg
        keys = dg.load_key()
        gbbq = dg.find_default_gbbq()
        with open(gbbq, "rb") as f:
            content = f.read()
        n, recs = dg.decrypt_gbbq(content, keys)
        m = {}
        for r in recs:
            p = _norm_code(r["code"])
            if not p:
                continue
            rec = {
                "date_raw": r["date_raw"], "f_cash": r["f_cash"],
                "f_rights_price": r["f_rights_price"], "f_bonus": r["f_bonus"], "f_rights": r["f_rights"],
            }
            if not _sane_ev(rec):
                continue
            m.setdefault(p, []).append(rec)
        for p in m:
            m[p].sort(key=lambda x: x["date_raw"])
        return m
    except Exception as e:
        print("[warn] 无法加载权息(需 all_xdxr.csv 或 decode_gbbq.py): %s" % e)
        return {}

def read_qfq(code, _xdxr_map=None):
    """前复权读取。

    返回 list[{date,open,high,low,close,amount,volume,close_raw}] (按日期升序)。
    前复权锚定最新交易日: 末根 close 严格等于未复权末收 (自带自校验)。
    复权因子由 gbbq 权息计算: 每只 ex-event 的 AF = 参考价/前收, 历史价 = 未复权价 * AF乘积。

    字段语义(已用茅台分红交叉验证):
      f_cash=每10股派息 → 每股 dg=f_cash/10
      f_bonus=每10股送股(含转增等效, 二者对比例影响相同) → 每股 sg=f_bonus/10
      f_rights=每10股配股 → 每股 rg=f_rights/10; f_rights_price=配股价(元/股)
      参考价 ref = (P_pre - dg + pg*rg) / (1 + sg + rg);  AF = ref / P_pre
    无该股权息 → 退化为未复权 (close==close_raw)。
    """
    bars = read_day(code)
    if not bars:
        return None
    if _xdxr_map is None:
        _xdxr_map = _load_xdxr_map()
    pure = _norm_code(code)
    evs = _xdxr_map.get(pure, [])

    # 同除权日多条记录(分红+配股) → 归并为单事件
    merged = {}
    for ev in evs:
        ex = ev["date_raw"]
        if ex not in merged:
            merged[ex] = {"date_raw": ex, "f_cash": 0.0, "f_rights_price": 0.0,
                          "f_bonus": 0.0, "f_rights": 0.0}
        m = merged[ex]
        m["f_cash"] += ev["f_cash"]
        m["f_bonus"] += ev["f_bonus"]
        m["f_rights"] += ev["f_rights"]
        if ev["f_rights_price"] > 0:
            m["f_rights_price"] = ev["f_rights_price"]
    events = sorted(merged.values(), key=lambda x: x["date_raw"])

    dated = sorted(bars, key=lambda b: b["date"])

    # 计算每只 event 的 AF, 需 ex_date 前一交易日未复权收 P_pre
    af_list = []
    for ev in events:
        ex = ev["date_raw"]
        pre = None
        for b in dated:
            if b["date"] < ex:
                pre = b
            else:
                break
        if pre is None:
            continue
        P_pre = pre["close"]
        if P_pre <= 0:
            continue
        dg_cash = ev["f_cash"] / 10.0
        pg = ev["f_rights_price"]
        sg = ev["f_bonus"] / 10.0
        rg = ev["f_rights"] / 10.0
        denom = 1.0 + sg + rg
        if denom <= 0:
            continue
        ref = (P_pre - dg_cash + pg * rg) / denom
        af = ref / P_pre
        # 防御: 分红/送转只降不升 → AF 必须 ∈ (0,1]; 越界说明字段语义/数据异常, 跳过该事件
        if not (0 < af <= 1.0000001):
            continue
        af_list.append((ex, af))
    af_list.sort(key=lambda x: x[0])

    # 累加因子: factor = ∏ events with ex_date > bar.date
    # 初始 factor = ∏ 全部 AF; 越过 ex_date 时除以该 AF
    total = 1.0
    for (_, af) in af_list:
        total *= af
    factor = total
    ei = 0
    out = []
    for b in dated:
        while ei < len(af_list) and af_list[ei][0] <= b["date"]:
            factor /= af_list[ei][1]
            ei += 1
        nb = dict(b)
        for k in ("open", "high", "low", "close"):
            nb[k] = b[k] * factor
        nb["close_raw"] = b["close"]
        out.append(nb)
    return out

if __name__ == "__main__":
    for code in ["sh000001", "sh600519", "sz002484", "bj920185", "sh000300"]:
        b = read_day(code)
        if b:
            print(f"{code}: {len(b)}根  首 {b[0]['date']} 收{b[0]['close']:.2f} | 末 {b[-1]['date']} 收{b[-1]['close']:.2f}")
        else:
            print(f"{code}: 无数据")
