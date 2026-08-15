import struct
import decode_gbbq as dg

bin_keys = dg.load_key()
print("key bytes:", len(bin_keys))


def _u32(x):
    return x & 0xFFFFFFFF


def F(num, bk):
    ebx = (num & 0xff0000) >> 16
    eax = struct.unpack("<I", bk[ebx * 4 + 0x448: ebx * 4 + 0x448 + 4])[0]
    ebx = num >> 24
    eax = _u32(eax + struct.unpack("<I", bk[ebx * 4 + 0x48: ebx * 4 + 0x48 + 4])[0])
    ebx = (num & 0xff00) >> 8
    eax = _u32(eax ^ struct.unpack("<I", bk[ebx * 4 + 0x848: ebx * 4 + 0x848 + 4])[0])
    ebx = num & 0xff
    eax = _u32(eax + struct.unpack("<I", bk[ebx * 4 + 0xC48: ebx * 4 + 0xC48 + 4])[0])
    return eax


def encrypt_block(bk, p_l, p_r):
    W0 = struct.unpack("<I", bk[0x44:0x48])[0]
    Wf = struct.unpack("<I", bk[0:4])[0]
    L = _u32(p_l ^ Wf)
    R = p_r
    for j in range(4, 0x44, 4):  # forward order 4..64
        t = _u32(F(L, bk) ^ struct.unpack("<I", bk[j:j + 4])[0])  # round key included
        new_L = _u32(R ^ t)
        L, R = new_L, L
    c0 = _u32(W0 ^ R)
    c1 = L
    return c0, c1


import random
random.seed(1234)
fails = 0
N = 3000
for _ in range(N):
    # Build a canonical 29-byte clear record (valid floats so pack/unpack is identity)
    market = random.randint(0, 255)
    date = random.randint(19900101, 20301231)
    category = random.randint(0, 255)
    fc = struct.unpack("<f", struct.pack("<f", random.uniform(-100, 100)))[0]
    fp = struct.unpack("<f", struct.pack("<f", random.uniform(-100, 100)))[0]
    fb = struct.unpack("<f", struct.pack("<f", random.uniform(-100, 100)))[0]
    fr = struct.unpack("<f", struct.pack("<f", random.uniform(-100, 100)))[0]
    clear = bytearray(29)
    clear[0] = market
    clear[1:8] = b"600519\0"            # ascii code -> lossless decode
    struct.pack_into("<I", clear, 8, date)
    clear[12] = category
    struct.pack_into("<f", clear, 13, fc)
    struct.pack_into("<f", clear, 17, fp)
    struct.pack_into("<f", clear, 21, fb)
    struct.pack_into("<f", clear, 25, fr)
    # 3 ciphertext blocks from the first 24 bytes
    ct = b""
    for k in range(3):
        pl = struct.unpack("<I", clear[8 * k:8 * k + 4])[0]
        pr = struct.unpack("<I", clear[8 * k + 4:8 * k + 8])[0]
        c0, c1 = encrypt_block(bin_keys, pl, pr)
        ct += struct.pack("<II", c0, c1)
    tail = bytes(clear[24:29])          # last 5 raw bytes (overlaps f_bonus[3]+f_rights)
    content = struct.pack("<I", 1) + ct + tail
    n, recs = dg.decrypt_gbbq(content, bin_keys)
    rec = recs[0]
    got_clear = struct.pack("<B7sIBffff",
                            rec["market"], rec["code"].encode("ascii"), rec["date_raw"], rec["category"],
                            rec["f_cash"], rec["f_rights_price"], rec["f_bonus"], rec["f_rights"])
    if got_clear != bytes(clear):
        fails += 1
        if fails <= 3:
            print("MISMATCH\n exp", bytes(clear).hex(), "\n got", got_clear.hex())

print("round-trip failures:", fails, "/", N)
print("RESULT:", "PASS - Feistel cipher logic is byte-correct" if fails == 0 else "FAIL")
