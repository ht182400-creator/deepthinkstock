import re

with open('gbbq_reader_upstream.py', 'r', encoding='utf-8') as f:
    txt = f.read()

m = re.search(r'hexdump_keys\s*=\s*"([0-9A-Fa-f\s]+)"', txt)
assert m, "hexdump_keys not found"
HEXKEYS = m.group(1)
key = bytes.fromhex(HEXKEYS)
print("decoded key length:", len(key), "(uses up to offset 0x1047 = 4168; >=4168 required)")
assert len(key) >= 0x1048, "key too short for algorithm"

TEMPLATE = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decode_gbbq.py  --  通达信 gbbq 权息文件解密器 (stdlib-only, 零依赖)
====================================================================
算法来源: pytdx/reader/gbbq_reader.py (rainx/ifzz fork) 官方 Feistel 解密 + 内置密钥常量。
重要: gbbq 不是标准 3DES, 而是通达信自定义的 8 字节块 Feistel 密码。本脚本逐字节照搬官方算法, 不做任何"改写"。

用法:
  python decode_gbbq.py                                  # 解密默认路径 gbbq, 输出汇总 + 写 all_xdxr.csv
  python decode_gbbq.py --gbbq "D:/new_tdx64/T0002/hq_cache/gbbq"
  python decode_gbbq.py --code sh600519                  # 只看茅台
  python decode_gbbq.py --code 600519 --json             # JSON 输出
  python decode_gbbq.py --code 600519 --out maotai.csv   # 写单票 CSV
  python decode_gbbq.py --selftest                       # 密钥长度 + 日期合理性自检

输出 CSV 列: market, code, date, category, f_cash, f_rights_price, f_bonus, f_rights
字段语义见文件末尾说明 (float 字段需对照已知分红验证, 详见 --test)。
"""

import struct
import sys
import os
import argparse
import csv
import json

# ---- 内置密钥常量 (与 pytdx gbbq_reader.hexdump_keys 逐字节一致) ----
HEXKEYS = """___HEXKEYS___"""


def _u32(x):
    return x & 0xFFFFFFFF


def load_key():
    b = bytes.fromhex(HEXKEYS)
    if len(b) < 0x1048:
        raise RuntimeError("密钥长度不足 (需 >= 4168 字节), 解密必错")
    return b


def decrypt_gbbq(content, bin_keys):
    count = struct.unpack("<I", content[0:4])[0]
    data_offset = 4
    records = []
    for _ in range(count):
        clear = bytearray()
        for _r in range(3):
            eax = struct.unpack("<I", bin_keys[0x44:0x48])[0]
            ebx = struct.unpack("<I", content[data_offset:data_offset + 4])[0]
            num = _u32(eax ^ ebx)
            numold = struct.unpack("<I", content[data_offset + 4:data_offset + 8])[0]
            for j in range(0x40, 0, -4):  # reversed(range(4, 0x40+4, 4))
                ebx = (num & 0xff0000) >> 16
                eax = struct.unpack("<I", bin_keys[ebx * 4 + 0x448: ebx * 4 + 0x448 + 4])[0]
                ebx = num >> 24
                eax_add = struct.unpack("<I", bin_keys[ebx * 4 + 0x48: ebx * 4 + 0x48 + 4])[0]
                eax = _u32(eax + eax_add)
                ebx = (num & 0xff00) >> 8
                eax_xor = struct.unpack("<I", bin_keys[ebx * 4 + 0x848: ebx * 4 + 0x848 + 4])[0]
                eax = _u32(eax ^ eax_xor)
                ebx = num & 0xff
                eax_add = struct.unpack("<I", bin_keys[ebx * 4 + 0xC48: ebx * 4 + 0xC48 + 4])[0]
                eax = _u32(eax + eax_add)
                eax_xor = struct.unpack("<I", bin_keys[j: j + 4])[0]
                eax = _u32(eax ^ eax_xor)
                ebx = num
                num = _u32(numold ^ eax)
                numold = ebx
            numold_op = struct.unpack("<I", bin_keys[0:4])[0]
            numold = _u32(numold ^ numold_op)
            clear.extend(struct.pack("<II", numold, num))
            data_offset += 8
        clear.extend(content[data_offset:data_offset + 5])
        data_offset += 5
        (v1, v2, v3, v4, v5, v6, v7, v8) = struct.unpack("<B7sIBffff", clear)
        code = v2.rstrip(b"\x00").decode("utf-8", "ignore")
        records.append({
            "market": v1,
            "code": code,
            "date_raw": v3,
            "category": v4,
            "f_cash": v5,
            "f_rights_price": v6,
            "f_bonus": v7,
            "f_rights": v8,
        })
    return count, records


def fmt_date(d):
    if isinstance(d, int) and 19000101 <= d <= 20301231:
        s = str(d)
        if len(s) == 8:
            return "%s-%s-%s" % (s[0:4], s[4:6], s[6:8])
    return str(d)


CAT_GUESS = {
    1: "送股",
    2: "配股",
    3: "派息(现金分红)",
    4: "送转(送股+转增)",
    5: "增发",
    6: "回购",
    7: "配股+派息",
}


def normalize_code(arg):
    return "".join(ch for ch in arg if ch.isdigit())


def find_default_gbbq():
    candidates = [
        "D:/new_tdx64/T0002/hq_cache/gbbq",
        "C:/new_tdx/T0002/hq_cache/gbbq",
        "D:/tdx/T0002/hq_cache/gbbq",
        "T0002/hq_cache/gbbq",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def main():
    ap = argparse.ArgumentParser(description="通达信 gbbq 权息文件解密器 (stdlib-only)")
    ap.add_argument("--gbbq", default=None, help="gbbq 文件路径 (默认自动探测常见路径)")
    ap.add_argument("--code", default=None, help="只看某只票, 如 sh600519 或 600519")
    ap.add_argument("--out", default=None, help="输出 CSV 路径 (默认 all_xdxr.csv)")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出到 stdout")
    ap.add_argument("--selftest", action="store_true", help="密钥长度 + 日期合理性自检")
    args = ap.parse_args()

    bin_keys = load_key()

    if args.selftest:
        print("密钥长度: %d 字节 (需 >= 4168) -> %s" % (len(bin_keys), "OK" if len(bin_keys) >= 0x1048 else "FAIL"))
        gbbq = args.gbbq or find_default_gbbq()
        if os.path.exists(gbbq):
            with open(gbbq, "rb") as f:
                content = f.read()
            n, recs = decrypt_gbbq(content, bin_keys)
            plausible = sum(1 for r in recs if 19900101 <= r["date_raw"] <= 20301231)
            pct = 100.0 * plausible / n if n else 0
            print("文件: %s  size=%d  记录数=%d  日期合理占比=%.1f%%" % (gbbq, len(content), n, pct))
            print("格式校验: (记录数*29 + 4) = %d, 文件大小 = %d -> %s" % (
                n * 29 + 4, len(content), "OK" if n * 29 + 4 == len(content) else "FAIL"))
            print("日期合理性: %s" % ("OK (密钥正确)" if pct > 95 else "WARN (密钥可能错误)"))
        else:
            print("未找到 gbbq 文件: %s  (放到该路径或加 --gbbq)" % gbbq)
        return

    gbbq = args.gbbq or find_default_gbbq()
    if not os.path.exists(gbbq):
        print("ERROR: 找不到 gbbq 文件: %s\n请用 --gbbq 指定路径, 例如 --gbbq \"D:/new_tdx64/T0002/hq_cache/gbbq\"" % gbbq)
        sys.exit(2)

    with open(gbbq, "rb") as f:
        content = f.read()
    n, recs = decrypt_gbbq(content, bin_keys)

    # 格式化
    for r in recs:
        r["date"] = fmt_date(r["date_raw"])
        r["category_label"] = CAT_GUESS.get(r["category"], "未知(%d)" % r["category"])

    filt = normalize_code(args.code) if args.code else None
    if filt:
        recs = [r for r in recs if normalize_code(r["code"]) == filt]

    # 按 code 再按 date 排序
    recs.sort(key=lambda r: (r["code"], r["date_raw"]))

    if args.json:
        print(json.dumps(recs, ensure_ascii=False, indent=1))
        return

    if args.out:
        out = args.out
    elif filt:
        out = "xdxr_%s.csv" % filt
    else:
        out = "all_xdxr.csv"

    cols = ["market", "code", "date", "date_raw", "category", "category_label",
            "f_cash", "f_rights_price", "f_bonus", "f_rights"]
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in recs:
            w.writerow(r)
    print("已解密 %d 条记录 -> %s" % (len(recs), out))
    print("字段: market(市场字节) code(6位代码) date(除权日) category(类别) "
          "f_cash(现金红利) f_rights_price(配股价) f_bonus(送股比例) f_rights(配股比例)")
    print("注意: 4 个 float 字段的'每股/每10股'与'是否按总股本归一'需对照已知分红验证 (见 --code 示例)。")


if __name__ == "__main__":
    main()
'''

out = TEMPLATE.replace("___HEXKEYS___", HEXKEYS)
with open('decode_gbbq.py', 'w', encoding='utf-8') as f:
    f.write(out)
print("wrote decode_gbbq.py, size =", len(out))
# re-verify embedded key
import importlib.util
# just re-extract from written file
with open('decode_gbbq.py', 'r', encoding='utf-8') as f:
    written = f.read()
mm = re.search(r'HEXKEYS = """([0-9A-Fa-f\s]+)"""', written)
kb = bytes.fromhex(mm.group(1))
print("embedded key bytes:", len(kb), "->", "OK" if len(kb) == len(key) else "MISMATCH")
