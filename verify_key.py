import re

# Verify the hexdump_keys constant in the canonical upstream source decodes to exactly 3224 bytes.
with open('gbbq_reader_upstream.py', 'r', encoding='utf-8') as f:
    txt = f.read()

m = re.search(r'hexdump_keys\s*=\s*"([0-9A-Fa-f\s]+)"', txt)
assert m, "hexdump_keys not found in upstream file"
hexstr = m.group(1)
key = bytes.fromhex(hexstr)
print("hex string length (chars):", len(hexstr))
print("decoded key length (bytes):", len(key))
assert len(key) == 3224, f"EXPECTED 3224, GOT {len(key)}"
print("OK: key is exactly 3224 bytes -> matches format spec (0x000-0x1047 S-boxes + round keys)")
