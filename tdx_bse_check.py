#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通达信 北交所(BSE) 历史K线 可用性自检（本机运行）。

为什么用通达信：新浪(冻2025-09-30)/腾讯(空)/东财(空或2020) 三家免费Web接口
都拿不到新鲜的北交所历史K线。通达信桌面客户端在本机开了一个行情服务
(127.0.0.1:7709)，只要客户端开着且下过北交所数据，pytdx 直接查本地就能拿。

用法：
  1) pip install pytdx
  2) 打开通达信（需登录且已下载北交所日线数据；菜单：系统→盘后数据下载）
  3) python3 tdx_bse_check.py            # 默认查本地 127.0.0.1:7709
     # 或指定公共服务器： python3 tdx_bse_check.py 119.147.212.81 7709

脚本会：对几只北交所标杆股，依次试 market 码 [27,47]，拉日线，打印末根日期+条数，
判断是否有“新鲜(≥2026)”的北交所历史K线。
"""
import sys, datetime

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 7709
    try:
        from pytdx.api import TdxHq_API
    except Exception as e:
        print("缺少 pytdx，请先 `pip install pytdx`：", e); return

    api = TdxHq_API()
    if not api.connect(host, port):
        print(f"连接失败 {host}:{port}（若连本地，请确认通达信已打开且未占用端口）"); return
    print(f"已连接 {host}:{port}\n")

    # 北交所标杆股（代码, 名称）
    test = [("835185","贝特瑞"), ("835368","连城数控"), ("836077","吉林碳谷"), ("834599","同力股份")]
    # 通达信 北交所 market 码候选（不同版本/接口有 27 与 47 两种说法，都试）
    markets = [27, 47, 0, 1]
    CAT_DAY = 9  # pytdx: 9 = 日线

    for code, name in test:
        got = False
        for m in markets:
            try:
                bars = api.get_security_bars(CAT_DAY, m, code, 0, 60)
            except Exception:
                bars = None
            if bars:
                last = bars[-1]
                dt = last.get("datetime") or last.get("date")
                print(f"[{name} {code}] market={m} 命中 | 共{len(bars)}根 | 末根: {dt}")
                # 新鲜度判断
                try:
                    y = int(str(dt)[:4])
                    fresh = y >= 2026
                    print(f"   -> {'新鲜(≥2026)✅' if fresh else '陈旧(<2026)❌'}")
                except Exception:
                    pass
                got = True
                break
        if not got:
            print(f"[{name} {code}] 在所有 market 码下均无数据 ❌")
    api.disconnect()

if __name__ == "__main__":
    main()
