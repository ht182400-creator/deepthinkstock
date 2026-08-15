# 通达信权息数据：gbbq 解密与本地复权（2026-08-03 实证修正版）

## ⚠️ 关键修正（本会话已证实）
1. **本机 new_tdx64 的"盘后数据下载"弹窗没有"除权数据"勾选项**（用户已确认）。但日线下载仍会把权息写入 `T0002/hq_cache/gbbq`（加密二进制）。
2. **gbbq 不是标准 3DES**，而是通达信自定义的 **8 字节块 Feistel 密码**（3 轮、带 3224/4176 字节 S-Box 与轮密钥常量）。"3DES"是民间误传。
3. **mootdx 不本地解密 gbbq**：`mootdx.utils.adjust.get_xdxr` 最终走 `Quotes.factory('std').xdxr()` 从通达信服务器在线拉取；`reader.py`/`parse.py` 也都不读本地 gbbq。故不能从 mootdx 拿本地解密器。
4. **真正能本地解密的是 pytdx 的 `gbbq_reader.py`**（rainx/ifzz fork），算法 + 内置 `hexdump_keys` 常量。本项目 `decode_gbbq.py` 已逐字节照搬该算法并去除 pandas/ctypes 依赖。

## 一、gbbq 文件事实（已验证）
- 路径：`D:\new_tdx64\T0002\hq_cache\gbbq`（5,512,005 字节）+ 同目录 `gbbq.map`（未加密 ASCII 索引，可忽略，解码不需要）。
- 结构：4 字节小端 `<I` 记录数（=190069） + `记录数 × 29` 字节记录。
- 校验：`190069 × 29 + 4 = 5,512,005` == 文件大小 ✓。
- 每条记录 29 字节，struct = `<B7sIBffff`：
  - `B` market（市场字节）、`7s` code（6 位代码 + 填充）、`I` date（除权日 YYYYMMDD）、`B` category（类别）
  - `f` f_cash（每10股现金红利·元）、`f` f_rights_price（配股价·元）、`f` f_bonus（每10股送股·股）、`f` f_rights（每10股配股·股）

## 二、float 字段语义（用茅台 600519 已知分红交叉验证过）
- `f_cash` = 每10股现金红利(元)：2024-06-19=308.76、2023-06-30=259.11、2022-06-30=216.75、2021-06-25=192.93 ✓ 全部对上。
- `f_bonus` = 每10股送股(股)：2002-07-25=1.0（10送1）✓。
- `f_rights_price` / `f_rights` = 配股类记录适用；此类记录数值较大，单位/语义还需对照一只**已知配股**的股票再确认后再用于复权。
- `category` 字节含义与在线 xdxr 不完全一致，**不要单独用 category 驱动复权**，一律以 float 字段为准。
- 同一除权日可能在 gbbq 出现多条记录（如 cat1 分红 + cat2 配股），算复权因子时按**除权日归并**。

## 三、解密器用法（decode_gbbq.py，stdlib-only 零依赖）
```
python decode_gbbq.py                         # 解密默认路径, 写 all_xdxr.csv (190069 行)
python decode_gbbq.py --gbbq "D:/new_tdx64/T0002/hq_cache/gbbq"
python decode_gbbq.py --code 600519          # 单票, 写 xdxr_600519.csv
python decode_gbbq.py --code 600519 --json   # JSON 输出
python decode_gbbq.py --selftest              # 密钥长度 + 日期合理性(>95%即密钥正确)
```
验证结果：日期合理占比 100.0% → 密钥与算法对真实文件正确。

## 四、下一步：接入 tdx_day_reader.read_qfq()
拿到全市场权息后，对未复权 `.day` 做前复权：
- 前复权锚定"最新交易日"，每只票最后一根前复权收盘价 == 本地未复权末收（自校验）。
- 复权因子用 f_cash/f_bonus/f_rights + 标准 A 股除权公式，按除权日归并多条记录。
- 先用茅台自验：前复权序列末值应等于未复权末收（约 1350~1700 区间，依时点），且与东财 fqt=1 抓取结果一致（此前已验证茅台=1350.60 吻合）。

## 五、不要再走的死路
- ❌ 东财 `fqt=1` 批量抓取：沙箱与用户本机 urllib 均 `RemoteDisconnected`，放弃。
- ❌ 腾讯 `fqkline`：单请求最多 640 点（从 ~2023-12 起），不足以长历史回测，仅应急。
- ❌ 手写 3DES 解密：算法是 Feistel 而非 3DES，手写必错（本会话已实证）。
- ❌ mootdx 本地解密：mootdx 不读本地 gbbq，只在线拉。

---
*来源：pytdx/reader/gbbq_reader.py（rainx/ifzz fork）逐字节复刻；字段语义以茅台 600519 已知分红交叉验证。*
