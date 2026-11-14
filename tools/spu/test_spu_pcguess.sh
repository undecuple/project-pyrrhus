#!/usr/bin/env bash
# KZ2 patch 7022 host test: computed hops with a link-register guess (tools/spu/test_spu_pcguess.c),
# then the same test against a copy of spu_context.h whose SPU_IB_GUESS_PC ignores KZ2_SPU_PCGUESS (negative control:
# must fail), then the lifter half (tools/spu/test_spu_pcguess.py: compute_ib_guesses on the idiom's real encodings).
#   nix develop --command tools/sandbox.sh -- tools/spu/test_spu_pcguess.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
P="${KZ2_PATCHED_DIR:-$ROOT/${KZ2_OUT:-work}/ps3recomp-patched}"
if ! grep -q "SPU_IB_GUESS_PC" "$P/runtime/spu/spu_context.h" 2>/dev/null; then echo "SKIP: $P has no SPU_IB_GUESS_PC (patch 7022)"; exit 0; fi
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FL=(-std=gnu17 -O2 -msse4.1 -w -fno-strict-aliasing -I "$P/runtime/spu" -I "$P/include" -I "$P/runtime")
gcc "${FL[@]}" -o "$T/t" "$ROOT/tools/spu/test_spu_pcguess.c" -lm 2>&1 | grep -m5 -i "error\|undefined"
out="$("$T/t")"; rc=$?; echo "$out"
(( rc == 0 )) || { echo "FAIL test_spu_pcguess"; exit 1; }
mkdir -p "$T/m"; cp "$P/runtime/spu/spu_context.h" "$T/m/"
sed -i 's/^#define SPU_IB_GUESS_PC(ctx, G, F) if (g_kz2_pcguess > 0) { SPU_IB_GUESS(ctx, G, F) }$/#define SPU_IB_GUESS_PC(ctx, G, F) SPU_IB_GUESS(ctx, G, F)/' "$T/m/spu_context.h"
grep -q '^#define SPU_IB_GUESS_PC(ctx, G, F) SPU_IB_GUESS(ctx, G, F)$' "$T/m/spu_context.h" || { echo "FAIL: mutation did not apply"; exit 1; }
gcc -std=gnu17 -O2 -msse4.1 -w -fno-strict-aliasing -I "$T/m" -I "$P/runtime/spu" -I "$P/include" -I "$P/runtime" -o "$T/b" "$ROOT/tools/spu/test_spu_pcguess.c" -lm 2>&1 | grep -m5 -i "error\|undefined"
if bout="$("$T/b")"; then echo "$bout"; echo "FAIL test_spu_pcguess: negative control passed"; exit 1; fi
echo "negative control (switch ignored): $(echo "$bout" | grep -m1 FAIL)"
python3 "$ROOT/tools/spu/test_spu_pcguess.py" "$P/tools" || { echo "FAIL test_spu_pcguess (lifter)"; exit 1; }
echo "PASS test_spu_pcguess"
