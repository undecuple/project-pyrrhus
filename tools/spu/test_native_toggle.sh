#!/usr/bin/env bash
# Host test: the same-run A/B of native gates. The C half checks native_toggle.h (KZ2_NATIVE_TOGGLE's
# slot list, the phase rule); the Python half feeds tools/spu/toggle_ab.py a made-up log (wacct windows, switch lines
# between and inside them) and checks which windows it drops and its per-phase numbers. kz2_native_jobs.c must install
# the toggle's gate before the flag rule. No game data.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_native_toggle.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/${KZ2_OUT:-work}/spu"; case "$O" in /*) ;; *) O="$ROOT/$O" ;; esac
mkdir -p "$O"; rm -f "$O/t_native_toggle"
gcc -std=gnu17 -O2 -Wall -Werror -I "$ROOT/port/kz2/spu" -o "$O/t_native_toggle" "$ROOT/tools/spu/test_native_toggle.c" 2>&1 | grep -m5 error
"$O/t_native_toggle" || { echo "FAIL test_native_toggle (C)"; exit 1; }
grep -q 's_tog\[e->slot\]' "$ROOT/port/kz2/spu/kz2_native_jobs.c" || { echo "FAIL test_native_toggle: no toggle gate in add()"; exit 1; }
L="$O/t_native_toggle.log"
{
  echo "[native-toggle] t=0.000s phase=0 lifted (start: 1 slots, period 2000 ms)"
  # phase 0: two pure windows, ms/load 1.0
  echo "[wacct] ---- t=1.0s window=1000ms flips=30"
  echo "[wacct] thr=spurs-kern1: wait=1ms x | pmrun:wid9=10.0ms/5 job:ovl224=10.0ms/10"
  echo "[wacct] ---- t=2.0s window=1000ms flips=30"
  echo "[wacct] thr=spurs-kern1: wait=1ms x | pmrun:wid9=10.0ms/5 job:ovl224=10.0ms/10"
  echo "[native-toggle] t=2.010s phase=1 native (ended phase 0 calls lifted/native: s75=5/0)"
  # window ending 3.0 holds the switch: dropped (its 99 ms must not count)
  echo "[wacct] ---- t=3.0s window=1000ms flips=30"
  echo "[wacct] thr=spurs-kern1: wait=1ms x | job:ovl224=99.0ms/10"
  echo "[wacct] ---- t=4.0s window=1000ms flips=30"
  echo "[wacct] thr=spurs-kern1: wait=1ms x | job:ovl224=8.0ms/10"
  echo "[wacct] thr=spurs-kern2: wait=1ms x | job:ovl224=8.0ms/10"
  echo "[native-toggle] t=4.002s phase=2 lifted (ended phase 1 calls lifted/native: s75=0/5)"
  echo "[wacct] ---- t=5.0s window=1000ms flips=30"
  echo "[wacct] thr=spurs-kern1: wait=1ms x | job:ovl224=99.0ms/1"
  echo "[wacct] ---- t=6.0s window=1000ms flips=30"
  echo "[wacct] thr=spurs-kern1: wait=1ms x | job:ovl224=12.0ms/10"
} > "$L"
out=$(python3 "$ROOT/tools/spu/toggle_ab.py" "$L" --ovl 224 --manifest /nonexistent)
echo "$out" | grep -q "6 toggled windows, 2 dropped" || { echo "FAIL test_native_toggle: dropped windows"; echo "$out"; exit 1; }
# lifted: (10+10+12)/30 loads = 1.0667; native 16/20 = 0.8; paired: 0.8 - mean(1.0, 1.2) = -0.3
echo "$out" | grep -q "ms/load 1.0667 -> 0.8000 (x0.750)  paired 1: native lower 1, median -0.3000" ||
  { echo "FAIL test_native_toggle: numbers"; echo "$out"; exit 1; }
echo "test_native_toggle: ok"
