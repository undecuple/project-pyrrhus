#!/usr/bin/env bash
# Host test: Anim.Skinning's skinning loop @0x54C0 (slot 80, KZ2_NATIVE_JOB_SKIN, port/kz2/spu/native_skinning.c
# sk_skin_54C0). Checks that the lift has the gate, that the native code leaves the whole local store,
# r0, r1 and r80-r127 as the lifted function does and the interpreter agrees with the lifted run, on synthetic inputs
# (tools/spu/native_diff.py synth --interp: the game's stream layout or others, random or few bones, odd floats a
# quarter of the trials, zero vectors for the unit steps; 1 in 16 declined: an output over what the loop reads or
# unaligned; at least 9/10 must run native). Then tools/spu/loop_dataflow.py on a small hand-written loop (no game
# code): a two-stage software pipeline whose stores must come out with the right iteration's inputs. An earlier change:
# tools/spu/test_native_skin_ops.c, the kernel's own fi(frsqest) and cflts(142) against the helpers on all 2^32 inputs.
# Needs the SPU lift ($KZ2_OUT/spu/lift) with gate 80 and the patched toolkit; no game data in git.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_native_skin.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00d90c00/spu_recomp.c"
T="$OUT/spu/t_native_skin"; mkdir -p "$T"
# loop_dataflow.py: r10 = [r4] * [r4] is loaded one pass ahead; the store of pass k must use pass k's input
cat > "$T/pipe.dis" <<'DIS'
00001000:  34000205  lqd          $r5, 0x0($r4)
00001004:  1C040204  ai           $r4, $r4, 16
00001008:  58C1428A  fm           $r10, $r5, $r5
0000100C:  34000205  lqd          $r5, 0x0($r4)
00001010:  1C040204  ai           $r4, $r4, 16
00001014:  2400018A  stqd         $r10, 0x0($r3)
00001018:  1C080183  ai           $r3, $r3, 32
0000101C:  1CFFC489  ai           $r9, $r9, -1
00001020:  217FFD09  brnz         $r9, 0x1008
00001024:  35000000  bi           $r0
DIS
df=$(python3 "$ROOT/tools/spu/loop_dataflow.py" "$T/pipe.dis" 1000 1028 --ptr r3,r4 --iters 2 2>&1)
echo "$df" | grep -A1 "STORE @00001014 \[r3+0+0\]" | grep -q "w0 = fm(\[r4+0\], \[r4+0\])" &&
  echo "$df" | grep -A1 "STORE @00001014 \[r3+32+0\]" | grep -q "w0 = fm(\[r4+16\], \[r4+16\])" &&
  echo "$df" | grep -A1 "STORE @00001014 \[r3+64+0\]" | grep -q "w0 = fm(\[r4+32\], \[r4+32\])" &&
  echo "$df" | grep -q "final pointers: r3=r3+96 r4=r4+64" ||
  { echo "FAIL test_native_skin: loop_dataflow.py on the pipeline sample"; echo "$df" | head -20; exit 1; }
echo "loop_dataflow: the pipeline sample's three stores and pointers as expected"
# sk_rsq and sk_cflts142 (the kernel's own fi(frsqest) and cflts(142)) against the helpers, every input
P="${KZ2_PATCHED_DIR:-$OUT/ps3recomp-patched}"
if grep -qw fma /proc/cpuinfo && [[ -f "$P/runtime/spu/spu_helpers.h" ]]; then
  gcc -std=gnu17 -O2 -msse4.1 -mfma -w -ffp-contract=off -fno-strict-aliasing -I "$P/runtime/spu" -I "$P/include" \
      -I "$P/runtime" -I "$ROOT/port/kz2/spu" -o "$T/ops" "$ROOT/tools/spu/test_native_skin_ops.c" -lm ||
    { echo "FAIL test_native_skin: test_native_skin_ops.c did not build"; exit 1; }
  "$T/ops" || { echo "FAIL test_native_skin: sk_rsq/sk_cflts142 differ from the helpers"; exit 1; }
  "$T/ops" neg >/dev/null && { echo "FAIL test_native_skin: the ops test's negative control was not caught"; exit 1; }
  echo "ops: sk_rsq and sk_cflts142 equal the helpers on every input (negative control caught)"
else
  echo "SKIP ops: no FMA host or no patched toolkit at $P"
fi
if [[ ! -f "$L" ]]; then echo "SKIP: no Anim.Skinning lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
grep "native gate 80:" "$L" | grep -q "SPU_RET(ctx)" ||
  { echo "FAIL test_native_skin: the lift at $L has no native gate 80 returning to r0 (re-lift)"; exit 1; }
field() { awk -v k="$1" '$0 ~ " T slot=80 " { for (i = 1; i <= NF; i++) { split($i, kv, "="); if (kv[1] == k) print kv[2] } }'; }
out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot 80 --trials "${TRIALS:-300}" --interp 2>&1); rc=$?
echo "$out" | grep -o "T slot=80.*interp_mismatch=[0-9]*" | tail -1
c=$(echo "$out" | field cases); m=$(echo "$out" | field match)
[[ $rc -eq 0 && -n "$m" && "$m" -gt 0 && $((10 * m)) -ge $((9 * c)) ]] &&
  echo "$out" | grep -q " T slot=80 .* mismatch=0 .*broken=0 interp_mismatch=0" ||
  { echo "FAIL test_native_skin (synthetic equality)"; exit 1; }
echo "PASS test_native_skin (slot 80)"
