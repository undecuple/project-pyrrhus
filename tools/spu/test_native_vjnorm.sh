#!/usr/bin/env bash
# Spu an earlier change host test: Particles.VertexJob's main-loop corner block @0x6918-0x6C1C (slot 85, KZ2_NATIVE_JOB_VJNORM,
# port/kz2/spu/native_particles.c vj_norm_6918), a "continue at" gate to 0x6C1C. Checks:
#   1. the lift has gate 85 and it hops to 0x6C1C (the lifter splits a function there for the continue address);
#   2. tools/spu/native_diff.py synth --slot 85 --interp: the whole local store, all 128 registers and the pc against
#      the lifted block and the SPU interpreter on synthetic quads (zero-length corners, odd words in a quarter of the
#      trials, an unaligned frame, the state quadword inside the frame's stores); every case must run native and match;
#   3. negative controls: three mutated copies of the native source (KZ2_NATIVE_SRC) must each be caught (the second
#      normalise's Newton step, the blend factor's word, the order of a store and the state reload).
# Needs the SPU lift ($KZ2_OUT/spu/lift) with gate 85 and the patched toolkit; no game data in git.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_native_vjnorm.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00cd7180/spu_recomp.c"
if [[ ! -f "$L" ]]; then echo "SKIP: no Particles.VertexJob lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
grep "native gate 85:" "$L" | grep -q "SPU_HOP(ctx, 0x6C1C, job_00cd7180_spu_func_00006C1C);" ||
  { echo "FAIL test_native_vjnorm: the lift at $L has no gate 85 continuing at 0x6C1C (re-lift)"; exit 1; }
field() { awk -v k="$1" '$0 ~ " T slot=85 " { for (i = 1; i <= NF; i++) { split($i, kv, "="); if (kv[1] == k) print kv[2] } }'; }
out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot 85 --trials "${TRIALS:-400}" --interp 2>&1); rc=$?
echo "$out" | grep -o "T slot=85.*speedup=[0-9.]*" | tail -1
c=$(echo "$out" | field cases); m=$(echo "$out" | field match)
echo "$out" | grep -q " T slot=85 .* mismatch=0 fallback=0 broken=0 interp_mismatch=0" && [[ $rc -eq 0 && "$m" == "$c" && "$c" -gt 0 ]] ||
  { echo "$out" | grep -m5 "MISMATCH\|broken\|did not"; echo "FAIL test_native_vjnorm: slot 85 differs"; exit 1; }
T="$OUT/spu/t_native_vjnorm"; mkdir -p "$T"
src="$ROOT/port/kz2/spu/native_particles.c"
muts=('s/    r3 = FNMS(r72, r7, r21);/    r3 = FNMS(r72, r7, r22);/'
      's/    r6 = spu_rotqbyi(r12, 8);/    r6 = spu_rotqbyi(r12, 4);/'
      's/    r9 = ldq(ls, st);/    r9 = ldq(ls, st + 16);/')
k=0
for mu in "${muts[@]}"; do
  k=$((k + 1)); d="$T/m$k"; rm -rf "$d"; mkdir -p "$d"; cp "$ROOT"/port/kz2/spu/*.c "$ROOT"/port/kz2/spu/*.h "$d/"
  sed -i "$mu" "$d/native_particles.c"
  cmp -s "$src" "$d/native_particles.c" && { echo "FAIL test_native_vjnorm: mutation $k did not apply"; exit 1; }
  mo=$(KZ2_NATIVE_SRC="$d" python3 "$ROOT/tools/spu/native_diff.py" synth --slot 85 --trials 200 2>&1)
  mm=$(echo "$mo" | field mismatch)
  [[ -n "$mm" && "$mm" -gt 0 ]] || { echo "FAIL test_native_vjnorm: mutation $k not caught"; exit 1; }
  echo "mutation $k caught: $mm of 200 differ"
done
echo "PASS test_native_vjnorm (slot 85, continue at 0x6C1C)"
