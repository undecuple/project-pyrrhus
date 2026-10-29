#!/usr/bin/env bash
# Host test (KZ2_NATIVE_ZLIB, the Edge zlib job on the host): port/kz2/kz2_edge_zlib.c
# on synthetic raw-deflate streams made here with Python's zlib (stored, fixed, dynamic, multi-block, empty, a full
# 64 KiB block), with the decoder the Windows build uses today (stb_image from the toolkit) and, when the host has
# zlib, with zlib too; plus checks that the override is wired (both EBOOTs' lists, the sources in CMake). No game data.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_edge_zlib.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
STB="third_party/ps3recomp/libs/codec"
[[ -f "$STB/stb_image.h" ]] || { echo "[FAIL] no $STB/stb_image.h"; exit 1; }
O=work/runtime/test/edge_zlib; mkdir -p "$O"
python3 - "$O" <<'PY'
import os, random, sys, zlib
o = sys.argv[1]
rnd = random.Random(56)
text = b"".join(b"Helghast %d Corinth River %d " % (i, i * i % 97) for i in range(2500))[:60000]
noise = bytes(rnd.getrandbits(8) for _ in range(5000))
def raw(data, level=6, strategy=zlib.Z_DEFAULT_STRATEGY, chunks=None):
    c = zlib.compressobj(level, zlib.DEFLATED, -15, 9, strategy)
    if chunks:   # Z_FULL_FLUSH between parts: several blocks, the last one final
        out = b"".join(c.compress(part) + c.flush(zlib.Z_FULL_FLUSH) for part in chunks)
        return out + c.flush()
    return c.compress(data) + c.flush()
vec = {
    "stored": (noise, raw(noise, level=0)),
    "fixed": (text[:3000], raw(text[:3000], strategy=zlib.Z_FIXED)),
    "dynamic": (text, raw(text, level=9)),
    "multi": (text[:20000] + noise + text[:9000], raw(None, chunks=[text[:20000], noise, text[:9000]])),
    "empty": (b"", raw(b"")),
    "full64k": ((text + noise + text)[:65536], raw((text + noise + text)[:65536])),
}
for k, (plain, z) in vec.items():
    assert zlib.decompress(z, -15) == plain, k
    open(f"{o}/{k}.plain", "wb").write(plain)
    open(f"{o}/{k}.deflate", "wb").write(z)
# the block types are what the names say: BTYPE of the first block header
for k, want in (("stored", 0), ("fixed", 1), ("dynamic", 2)):
    got = (vec[k][1][0] >> 1) & 3
    assert got == want, (k, got)
print("vectors: " + ", ".join(f"{k} {len(p)}/{len(z)}" for k, (p, z) in vec.items()))
PY
cat > "$O/stb_impl.c" <<'C'
#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_NO_STDIO
#include "stb_image.h"
C
FL=(-std=gnu11 -O1 -Wall -Wextra -Werror -fsanitize=address,undefined -Iport/kz2)
"${CC:-cc}" "${FL[@]}" -Wno-unused-function -I"$STB" tools/runtime/test_edge_zlib.c port/kz2/kz2_edge_zlib.c "$O/stb_impl.c" -lm \
  -o "$O/test_edge_zlib_stb"
"$O/test_edge_zlib_stb" "$O"
if printf '#include <zlib.h>\nint main(void){return 0;}\n' | "${CC:-cc}" -x c - -lz -o "$O/zprobe" 2>/dev/null; then
  "${CC:-cc}" "${FL[@]}" -DKZ2_HAVE_ZLIB tools/runtime/test_edge_zlib.c port/kz2/kz2_edge_zlib.c -lz -o "$O/test_edge_zlib_z"
  "$O/test_edge_zlib_z" "$O"
else
  echo "SKIP: no host zlib headers (the zlib build of kz2_edge_zlib.c is not tested here)"
fi
python3 - <<'PY'
import re, sys
src = open("port/kz2/kz2_ppu_overrides.cpp").read()
cm = open("port/kz2/CMakeLists.txt").read()
l129 = open("port/kz2/ppu_overrides.txt").read()
l101 = open("port/kz2/ppu_overrides-101.txt").read()
checks = [
    ("1.29 list has 0x3C8BA0", re.search(r"^003C8BA0\b", l129, re.M) is not None),
    ("v1.01 list has 0x3BCAA0", re.search(r"^003BCAA0\b", l101, re.M) is not None),
    ("1.29 override defined", "void func_003C8BA0(ppu_context* ctx) { kz2_edge_add(ctx, func_003C8BA0__lifted); }" in src),
    ("v1.01 override defined", "void func_003BCAA0(ppu_context* ctx) { kz2_edge_add(ctx, func_003BCAA0__lifted); }" in src),
    ("default on: the lifted push only when KZ2_NATIVE_ZLIB starts with 0", "g_kz2_zlib_mode = (e && *e == '0') ? 0 : 1;" in src),
    ("stack args: eventFlag +0x74, bits +0x7E, mode +0x84",
     all(s in src for s in ("vm_read32(sp + 0x74)", "vm_read16(sp + 0x7E)", "vm_read32(sp + 0x84)"))),
    ("fallback calls the lifted push", re.search(r"else lifted\(ctx\);\n\s*kz2_zlib_tick\(\+\+s\.lifted\);", src) is not None),
    ("sources in CMake", "kz2_edge_zlib.c" in cm and "kz2_edge_guest.c" in cm),
]
bad = 0
for name, ok in checks:
    print(("PASS: " if ok else "[FAIL] ") + name); bad += not ok
sys.exit(1 if bad else 0)
PY
