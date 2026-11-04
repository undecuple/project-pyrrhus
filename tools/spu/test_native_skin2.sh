#!/usr/bin/env bash
# Host test: Anim.Skinning's two other hot leaves (port/kz2/spu/native_skinning.c): the two-stream
# skinning loop @0x50C0 (slot 83, KZ2_NATIVE_JOB_SKIN2) and the vertex-stream decompression @0x5B10 (slot 84,
# KZ2_NATIVE_JOB_SKINUNPACK). Checks that the lift has both gates returning to r0, and that on synthetic inputs
# (tools/spu/native_diff.py synth --interp; the harness's synth_skin2 / synth_skinunpack: the game's layouts or others,
# odd floats a quarter of the trials, 1 in 16 declined on purpose) the native code leaves the whole local store, r0,
# r1, r80-r127 and the registers the caller reads (83: r2-r6, r9; 84: r2-r6) as the lifted function does, the
# interpreter agrees with the lifted run, and at least 9/10 of the cases run native. Needs the SPU lift
# ($KZ2_OUT/spu/lift) with gates 83 and 84 and the patched toolkit; no game data in git.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_native_skin2.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00d90c00/spu_recomp.c"
if [[ ! -f "$L" ]]; then echo "SKIP: no Anim.Skinning lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
for s in 83 84; do
  grep "native gate $s:" "$L" | grep -q "SPU_RET(ctx)" ||
    { echo "FAIL test_native_skin2: the lift at $L has no native gate $s returning to r0 (re-lift)"; exit 1; }
  field() { awk -v k="$1" -v s="$s" '$0 ~ " T slot=" s " " { for (i = 1; i <= NF; i++) { split($i, kv, "="); if (kv[1] == k) print kv[2] } }'; }
  out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot "$s" --trials "${TRIALS:-300}" --interp 2>&1); rc=$?
  echo "$out" | grep -o "T slot=$s.*interp_mismatch=[0-9]*" | tail -1
  c=$(echo "$out" | field cases); m=$(echo "$out" | field match)
  [[ $rc -eq 0 && -n "$m" && "$m" -gt 0 && $((10 * m)) -ge $((9 * c)) ]] &&
    echo "$out" | grep -q " T slot=$s .* mismatch=0 .*broken=0 interp_mismatch=0" ||
    { echo "FAIL test_native_skin2 (slot $s, synthetic equality)"; exit 1; }
done
echo "PASS test_native_skin2 (slots 83, 84)"
