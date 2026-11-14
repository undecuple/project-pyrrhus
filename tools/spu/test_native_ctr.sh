#!/usr/bin/env bash
# an earlier change: the native gates' per-context call counters (port/kz2/spu/native_ctr.c). Runs tools/spu/test_native_ctr.c
# against the real native_ctr.c, then against a copy whose claim hands every context row 0 (no key written, so all
# threads share one row with a plain load and store): that build must FAIL (lost counts), or the test proves nothing.
# Host only; needs the patched ps3recomp tree for spu_context.h ($KZ2_OUT/ps3recomp-patched).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PT="${KZ2_PATCHED_DIR:-$ROOT/${KZ2_OUT:-work}/ps3recomp-patched}"
[[ -f "$PT/runtime/spu/spu_context.h" ]] || { echo "SKIP test_native_ctr: no $PT (tools/ps3recomp-patched.sh)"; exit 0; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
CC="${CC:-cc}"
FL=(-O2 -std=gnu11 -msse4.1 -pthread -I"$ROOT/port/kz2/spu" -I"$PT/runtime/spu" -I"$PT/runtime" -I"$PT/include")
"$CC" "${FL[@]}" -o "$T/t" "$ROOT/tools/spu/test_native_ctr.c" "$ROOT/port/kz2/spu/native_ctr.c"
out="$("$T/t")" || { echo "$out"; echo "FAIL test_native_ctr"; exit 1; }
echo "$out"
sed 's/^    const unsigned h = kz2_native_home(ctx);$/    (void)ctx; return 0; const unsigned h = 0;/' "$ROOT/port/kz2/spu/native_ctr.c" > "$T/broken.c"
grep -q 'return 0; const unsigned h = 0;' "$T/broken.c" || { echo "FAIL test_native_ctr: mutation did not apply"; exit 1; }
"$CC" "${FL[@]}" -I"$ROOT/port/kz2/spu" -o "$T/b" "$ROOT/tools/spu/test_native_ctr.c" "$T/broken.c"
if bout="$("$T/b")"; then echo "$bout"; echo "FAIL test_native_ctr: the broken claim passed (negative control)"; exit 1; fi
echo "negative control (all contexts on one row): $(echo "$bout" | grep -m1 FAIL)"
echo "PASS test_native_ctr"
