#!/usr/bin/env bash
# Host test: Physics.Raycast's MOPP ray machine at its loop head @0xCA40 (slot 82, KZ2_NATIVE_JOB_RAYCAST,
# port/kz2/spu/native_raycast.c rc_vm_CA40), the first computed-continuation gate (native_gates.tsv
# column 7 "pc": the native code sets ctx->pc, the gate line hops there with SPU_IB_HOP).
# 1. tools/spu/vm_live.py on a small hand-written loop (no game code): a head that dispatches through a two-entry
#    table, one handler that writes a scratch register and goes back to the head, one that reads another and returns.
# 2. The lift has gate 82 with the computed hop; synthetic equality (tools/spu/native_diff.py synth: random MOPP
#    programs, short and long rays, odd floats a quarter of the trials, a code cache half hit; 1 in 32 declined on
#    purpose, r1 misaligned): the whole local store, r0, r1, the head's r2-r9 and r14, r80, r86, r89, r91, r93-r96 and
#    r98-r127 as the lifted run leaves them at the native exit; at least 9/10 run native, 0 mismatches.
# 3. The harness's own check: HARNESS_PC_MUTATE=1 stops the lifted run one loop head late; that must not pass.
# Needs the SPU lift ($KZ2_OUT/spu/lift) with gate 82 and the patched toolkit; no game data in git.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_native_raycast.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00cef700/spu_recomp.c"
T="$OUT/spu/t_native_raycast"; mkdir -p "$T"
# vm_live.py: head 0x1000 reads r80, dispatches through the table at 0x1100 (0x1020, 0x1030); 0x1020 writes r20 and
# r81 and goes back; 0x1030 reads r81 (written by 0x1020 only: live at the head) and returns
cat > "$T/vm.dis" <<'DIS'
00001000:  34002803  lqd          $r3, 0x0($r80)
00001004:  1C002802  ai           $r2, $r80, 0
00001008:  35000100  bi           $r2
00001020:  1C004A14  ai           $r20, $r20, 1
00001024:  1C0042D1  ai           $r81, $r5, 1
00001028:  327FFB00  br           0x1000
00001030:  1C0040C3  ai           $r3, $r81, 1
00001034:  35000000  bi           $r0
00001100:  00001020  stop         0x1020
00001104:  00001030  stop         0x1030
DIS
lv=$(python3 "$ROOT/tools/spu/vm_live.py" "$T/vm.dis" 1000-1038 --table 1008=1100,2 --at 1000 --at 1020 --at 1030 2>&1)
echo "$lv" | grep -q "^0x01000 live-in .*: r0 r1 r5 r20 r80 r81$" && echo "$lv" | grep -q "^0x01020 live-in .*: r0 r1 r5 r20 r80$" &&
  echo "$lv" | grep -q "^0x01030 live-in .*: r0 r1 r81$" ||
  { echo "FAIL test_native_raycast: vm_live.py on the sample"; echo "$lv"; exit 1; }
echo "vm_live: the sample's live-in sets as expected"
if [[ ! -f "$L" ]]; then echo "SKIP: no Physics.Raycast lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
grep "native gate 82:" "$L" | grep -q "SPU_IB_HOP(ctx, ctx->pc)" ||
  { echo "FAIL test_native_raycast: the lift at $L has no native gate 82 with the computed hop (re-lift)"; exit 1; }
field() { awk -v k="$1" '$0 ~ " T slot=82 " { for (i = 1; i <= NF; i++) { split($i, kv, "="); if (kv[1] == k) print kv[2] } }'; }
out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot 82 --trials "${TRIALS:-400}" 2>&1); rc=$?
echo "$out" | grep -o "T slot=82.*interp_mismatch=[0-9]*" | tail -1
c=$(echo "$out" | field cases); m=$(echo "$out" | field match)
[[ $rc -eq 0 && -n "$m" && "$m" -gt 0 && $((10 * m)) -ge $((9 * c)) ]] &&
  echo "$out" | grep -q " T slot=82 .* mismatch=0 .*broken=0" ||
  { echo "FAIL test_native_raycast (synthetic equality)"; echo "$out" | grep -v " ok " | head -5; exit 1; }
mut=$(HARNESS_PC_MUTATE=1 python3 "$ROOT/tools/spu/native_diff.py" synth --slot 82 --trials 60 2>&1)
echo "$mut" | grep -q " T slot=82 .* mismatch=0 .*broken=0" &&
  { echo "FAIL test_native_raycast: the late stop (HARNESS_PC_MUTATE=1) was not caught"; exit 1; }
echo "late stop caught: $(echo "$mut" | grep -o 'match=[0-9]* mismatch=[0-9]* fallback=[0-9]* broken=[0-9]*' | tail -1)"
echo "PASS test_native_raycast (slot 82)"
