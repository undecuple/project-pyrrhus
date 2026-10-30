#!/usr/bin/env bash
# Spu an earlier change host test: Particles.VertexJob's crt0 .bss clear @0x411C (slot 77), the first "continue at" gate
# (port/kz2/spu/native_particles.c, re/spu/native_gates.tsv column 7). Checks that the lifted gate line hops to 0x407C
# (not SPU_RET) and that the native clear leaves the whole local store and all 128 registers as the lifted loop and
# the SPU interpreter do, on synthetic inputs (tools/spu/native_diff.py synth --interp: the game's own range, random
# lengths, unaligned starts, load offsets that wrap the local store, unsplatted lanes; 1 case in 32 has start >= end,
# which the native code declines, so a fallback is fine while at least 9/10 of the cases ran native). Needs the SPU
# lift ($KZ2_OUT/spu/lift) with the continue-at native gate for slot 77 and the patched toolkit; no game data in git.
#   nix develop .#re --command tools/sandbox.sh -- tools/spu/test_native_vjclear.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00cd7180/spu_recomp.c"
if [[ ! -f "$L" ]]; then echo "SKIP: no Particles.VertexJob lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
grep -q "native gate 77:" "$L" || { echo "FAIL test_native_vjclear: the lift at $L has no native gate 77 (re-lift)"; exit 1; }
grep "native gate 77:" "$L" | grep -q "SPU_HOP(ctx, 0x407C, job_00cd7180_spu_func_0000407C);" ||
  { echo "FAIL test_native_vjclear: gate 77 does not continue at 0x407C"; exit 1; }
grep -q "0x411Cu, vj_bss_411C, \"bss_clear\", 0, 0, 0,\s*$" "$ROOT/port/kz2/spu/native_particles.c" &&
  grep -A1 "vj_bss_411C, \"bss_clear\"" "$ROOT/port/kz2/spu/native_particles.c" | grep -q "0x407Cu" ||
  { echo "FAIL test_native_vjclear: the native entry's continue address is not 0x407C"; exit 1; }
out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot 77 --trials "${TRIALS:-300}" --interp 2>&1); rc=$?
echo "$out" | grep " T slot=" | tail -1
ok=$(echo "$out" | awk '$0 ~ " T slot=77 " { c = m = 0; for (i = 1; i <= NF; i++) { split($i, kv, "=");
       if (kv[1] == "cases") c = kv[2]; if (kv[1] == "match") m = kv[2] }
     if ($0 ~ / mismatch=0 / && $0 ~ / broken=0 interp_mismatch=0/ && m > 0 && 10 * m >= 9 * c) print 1 }')
[[ $rc -eq 0 && "$ok" == 1 ]] || { echo "FAIL test_native_vjclear"; exit 1; }
echo "PASS test_native_vjclear (slot 77, continue at 0x407C)"
