#!/usr/bin/env bash
# Spu an earlier change host test (slot 76 too): Anim.EdgeAnim's bit-packed decoder @0x13100 (slot 75) and keyframe
# sampler @0x12438 (slot 76) as native host code (port/kz2/spu/native_edgeanim.c) against the lifted code and the SPU
# interpreter on synthetic inputs (tools/spu/native_diff.py synth --interp:
# random packing specs with fixed-point, small-float, wide-mantissa and zero-width fields, random streams, index tables
# with repeats). Every case must leave the whole local store and the preserved registers equal; the generator plants
# index tables at offsets that are not a multiple of 8 in 1 case of 4 (their outputs may land on the inputs: declined),
# so a fallback is fine while at least 9/10 of the cases ran native. Needs the SPU lift ($KZ2_OUT/spu/lift) with the
# round-19 gates and the patched toolkit; no game data in git.
#   nix develop .#re --command tools/sandbox.sh -- tools/spu/test_native_edgeanim.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00d95d80/spu_recomp.c"
if [[ ! -f "$L" ]]; then echo "SKIP: no Anim.EdgeAnim lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
grep -q "native gate 75:" "$L" || { echo "FAIL test_native_edgeanim: the lift at $L has no round-19 gates (re-lift)"; exit 1; }
fail=0
for slot in 75 76; do
  out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot $slot --trials "${TRIALS:-200}" --interp 2>&1); rc=$?
  echo "$out" | grep " T slot=" | tail -1
  ok=$(echo "$out" | awk -v s=$slot '$0 ~ " T slot=" s " " { c = m = 0; for (i = 1; i <= NF; i++) { split($i, kv, "=");
         if (kv[1] == "cases") c = kv[2]; if (kv[1] == "match") m = kv[2] }
       if ($0 ~ / mismatch=0 / && $0 ~ / broken=0 interp_mismatch=0/ && m > 0 && 10 * m >= 9 * c) print 1 }')
  [[ $rc -eq 0 && "$ok" == 1 ]] || { echo "FAIL test_native_edgeanim (slot $slot)"; fail=1; }
done
[[ $fail == 0 ]] && echo "PASS test_native_edgeanim (slots 75, 76)" || exit 1
