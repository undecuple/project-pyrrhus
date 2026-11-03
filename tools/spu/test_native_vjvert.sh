#!/usr/bin/env bash
# Host test: Particles.VertexJob's vertex emitter @0x50F8 (slot 79, KZ2_NATIVE_JOB_VJVERT, port/kz2/spu/
# native_particles.c vj_vertex_50F8). Checks that the lift has the gate, that the native code leaves
# the whole local store, r0, r1, r3, r80-r127, the MFC commands it issues (the put of a full ring buffer with its
# bytes, the tag wait: tools/spu/harness_mfc.h) and int_enable as the lifted function does, and the interpreter
# agrees with the lifted run (registers, LS, MFC log), on synthetic inputs (tools/spu/native_diff.py synth --interp:
# every format-bit combination, the three relight modes, ring fill offsets near the end of a buffer; 1 in 32
# declined: a misaligned stack pointer or a ring state out of range; at least 9/10 must run native and some must
# put). Then the harness's own MFC compare end to end: HARNESS_MFC_MUTATE=ea|tag|data|drop|order changes the native
# side's log after its run, and every put case must then mismatch. Needs the SPU lift ($KZ2_OUT/spu/lift) with gate
# 79 and the patched toolkit; no game data in git.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_native_vjvert.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00cd7180/spu_recomp.c"
if [[ ! -f "$L" ]]; then echo "SKIP: no Particles.VertexJob lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
grep "native gate 79:" "$L" | grep -q "SPU_RET(ctx)" ||
  { echo "FAIL test_native_vjvert: the lift at $L has no native gate 79 returning to r0 (re-lift)"; exit 1; }
field() { awk -v k="$1" '$0 ~ " T slot=79 " { for (i = 1; i <= NF; i++) { split($i, kv, "="); if (kv[1] == k) print kv[2] } }'; }
out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot 79 --trials "${TRIALS:-300}" --interp 2>&1); rc=$?
echo "$out" | grep -o "T slot=79.*interp_mismatch=[0-9]* mfc_puts=[0-9]*" | tail -1
c=$(echo "$out" | field cases); m=$(echo "$out" | field match); p=$(echo "$out" | field mfc_puts)
[[ $rc -eq 0 && -n "$m" && "$m" -gt 0 && $((10 * m)) -ge $((9 * c)) && "$p" -gt 0 ]] &&
  echo "$out" | grep -q " T slot=79 .* mismatch=0 .*broken=0 interp_mismatch=0" ||
  { echo "FAIL test_native_vjvert (synthetic equality)"; exit 1; }
for mu in ea tag data drop order; do
  o=$(HARNESS_MFC_MUTATE=$mu python3 "$ROOT/tools/spu/native_diff.py" synth --slot 79 --trials 60 2>&1)
  mm=$(echo "$o" | field mismatch); pp=$(echo "$o" | field mfc_puts)
  [[ -n "$mm" && "$pp" -gt 0 && "$mm" -ge "$pp" ]] ||
    { echo "FAIL test_native_vjvert: HARNESS_MFC_MUTATE=$mu not caught (mismatch=$mm, puts=$pp)"; exit 1; }
  echo "mutation $mu: $mm of $pp put cases caught"
done
echo "PASS test_native_vjvert (slot 79)"
