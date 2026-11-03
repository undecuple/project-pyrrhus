#!/usr/bin/env bash
# Host test: Particles.VertexJob's relight in SSE (slot 81, KZ2_NATIVE_JOB_VJLIGHT, port/kz2/spu/native_particles.c
# vj_vertex_light = the slot-79 emitter with vjf_light_52C0 / vjf_pack and the colour and texture-coordinate floats
# through native_simd.h's wrappers). Checks:
#   1. tools/spu/test_vjlight.c: the SSE relight and packing against the helper form on 20 000 synthetic inputs (the
#      three relight modes, a quarter with zero, denormal, huge, infinity/NaN or random words), all four lanes, the
#      patch-1071 recompute off and on; a negative control (a one-ulp change) must be caught every time;
#   2. the lift has gate 81 on 0x50F8 ahead of gate 79 (the second gate on the same function);
#   3. tools/spu/native_diff.py synth --slot 81 --interp: the whole emitter (local store, r0, r1, r3, r80-r127, the
#      MFC commands, int_enable) against the lifted function and the interpreter; at least 9/10 run native.
# Needs the SPU lift ($KZ2_OUT/spu/lift) with gate 81 and the patched toolkit; no game data in git.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_native_vjlight.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00cd7180/spu_recomp.c"
T="$OUT/spu/t_native_vjlight"; mkdir -p "$T"
P="${KZ2_PATCHED_DIR:-$OUT/ps3recomp-patched}"
if grep -qw fma /proc/cpuinfo && [[ -f "$P/runtime/spu/spu_helpers.h" ]]; then
  gcc -std=gnu17 -O2 -msse4.1 -mfma -w -ffp-contract=off -fno-strict-aliasing -I "$P/runtime/spu" -I "$P/include" \
      -I "$P/runtime" -I "$ROOT/port/kz2/spu" -o "$T/vjl" "$ROOT/tools/spu/test_vjlight.c" -lm ||
    { echo "FAIL test_native_vjlight: test_vjlight.c did not build"; exit 1; }
  o=$("$T/vjl" synth "${TRIALS_OPS:-20000}") || { echo "$o" | tail -5; echo "FAIL test_native_vjlight: SSE relight differs"; exit 1; }
  echo "$o" | grep "^T "
  "$T/vjl" synth 2000 neg | grep -q "2000 of 2000" ||
    { echo "FAIL test_native_vjlight: the negative control was not caught"; exit 1; }
  echo "ops: the SSE relight and packing equal the helper form (negative control caught)"
else
  echo "SKIP ops: no FMA host or no patched toolkit at $P"
fi
if [[ ! -f "$L" ]]; then echo "SKIP: no Particles.VertexJob lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
g81=$(grep -n "native gate 81:" "$L" | grep "SPU_RET(ctx)" | cut -d: -f1)
g79=$(grep -n "native gate 79:" "$L" | grep "SPU_RET(ctx)" | cut -d: -f1)
[[ -n "$g81" && -n "$g79" && "$g81" -lt "$g79" ]] ||
  { echo "FAIL test_native_vjlight: the lift at $L has no gate 81 ahead of gate 79 (re-lift)"; exit 1; }
field() { awk -v k="$1" '$0 ~ " T slot=81 " { for (i = 1; i <= NF; i++) { split($i, kv, "="); if (kv[1] == k) print kv[2] } }'; }
out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot 81 --trials "${TRIALS:-300}" --interp 2>&1); rc=$?
echo "$out" | grep -o "T slot=81.*interp_mismatch=[0-9]*" | tail -1
c=$(echo "$out" | field cases); m=$(echo "$out" | field match)
[[ $rc -eq 0 && -n "$m" && "$m" -gt 0 && $((10 * m)) -ge $((9 * c)) ]] &&
  echo "$out" | grep -q " T slot=81 .* mismatch=0 .*broken=0 interp_mismatch=0" ||
  { echo "FAIL test_native_vjlight (synthetic equality)"; exit 1; }
echo "PASS test_native_vjlight (slot 81)"
