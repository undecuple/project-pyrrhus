#!/usr/bin/env bash
# Host test: Particles.VertexJob's memcpy @0x7F00 (slot 78, KZ2_NATIVE_JOB_VJCOPY,
# port/kz2/spu/native_particles.c vj_memcpy_7F00). Checks that the lift has the gate and that the native copy leaves
# the whole local store and the preserved registers as the lifted function and the SPU interpreter do, on synthetic
# inputs (tools/spu/native_diff.py synth --interp: every alignment pair, 0-4 KB, single-quadword merges, unsplatted
# lanes; 1 in 16 overlapping and 1 in 32 near the end of the local store, which the native code declines, so a
# fallback is fine while at least 4/5 of the cases ran native). Needs the SPU lift ($KZ2_OUT/spu/lift) with the
# native gate 78 and the patched toolkit; no game data in git.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_native_vjcopy.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00cd7180/spu_recomp.c"
if [[ ! -f "$L" ]]; then echo "SKIP: no Particles.VertexJob lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
grep "native gate 78:" "$L" | grep -q "SPU_RET(ctx)" ||
  { echo "FAIL test_native_vjcopy: the lift at $L has no native gate 78 returning to r0 (re-lift)"; exit 1; }
out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot 78 --trials "${TRIALS:-300}" --interp 2>&1); rc=$?
echo "$out" | grep " T slot=" | tail -1
ok=$(echo "$out" | awk '$0 ~ " T slot=78 " { c = m = 0; for (i = 1; i <= NF; i++) { split($i, kv, "=");
       if (kv[1] == "cases") c = kv[2]; if (kv[1] == "match") m = kv[2] }
     if ($0 ~ / mismatch=0 / && $0 ~ / broken=0 interp_mismatch=0/ && m > 0 && 5 * m >= 4 * c) print 1 }')
[[ $rc -eq 0 && "$ok" == 1 ]] || { echo "FAIL test_native_vjcopy"; exit 1; }
echo "PASS test_native_vjcopy (slot 78)"
