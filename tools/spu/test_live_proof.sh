#!/usr/bin/env bash
# Host test: tools/spu/live_proof.py on made-up disassemblies (no game data). A "job" calls a leaf
# that writes r5 and r6, then calls a job manager API through a pointer (bisl); the job manager saves its link in a save slot, calls
# an inner routine with another link register, reloads the link and returns. Cases: the clean case; a read of r6
# right after the call; the job manager reading r5 (a register the job did not overwrite); r5 spilled to a save slot and
# reloaded then read (taint through the slot); an unresolved indirect branch.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_live_proof.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/${KZ2_OUT:-work}/spu/t_live_proof"; case "$O" in /*) ;; *) O="$ROOT/$O" ;; esac
mkdir -p "$O"
fail=0
mk() {   # FILE then "ADDR MNEMONIC OPERANDS" lines
  local f="$1"; shift
  : > "$f"
  for l in "$@"; do
    set -- $l
    local a="$1"; shift; local mn="$1"; shift
    printf '%08X:  00000000  %-12s %s\n' "$((a))" "$mn" "$*" >> "$f"
  done
}
# job: 0x4000 main: ila r3; brsl r0,leaf; <mid>; bisl r0,r9 (-> pm 0x100); il r3,0; bi r0 (return)
job() {
  mk "$O/job.dis" \
    "0x4000 il \$r9, 0" \
    "0x4004 brsl \$r0, 0x4100" \
    "0x4008 $1" \
    "0x400C bisl \$r0, \$r9" \
    "0x4010 il \$r5, 0" \
    "0x4014 il \$r6, 0" \
    "0x4018 stop 0x0" \
    "0x4100 il \$r5, 1" \
    "0x4104 il \$r6, 2" \
    "0x4108 bi \$r0"
}
pm() {
  mk "$O/pm.dis" \
    "0x100 stqa \$r0, 0x200" \
    "0x104 $1" \
    "0x108 brsl \$r4, 0x140" \
    "0x10C $2" \
    "0x110 ${3:-nop}" \
    "0x114 lqa \$r0, 0x200" \
    "0x118 bi \$r0" \
    "0x140 il \$r7, 0" \
    "0x144 bi \$r4"
}
run() {   # EXPECT(clean|read|unresolved) NAME
  local out
  out=$(python3 "$ROOT/tools/spu/live_proof.py" --job "$O/job.dis" --pm "$O/pm.dis" --call 0x4004 --leaf 0x4100-0x4108 \
        --bisl job:0x400C=pm:0x100 --spill pm:0x200,0x210 --pm-jobcall 0x0 2>&1)
  local res; res=$(grep '^RESULT' <<<"$out")
  case "$1" in
    clean) [[ "$res" == *clean* ]] ;;
    read) [[ "$res" == *reads* ]] && grep -q "^READ $3" <<<"$out" ;;
    unresolved) grep -q '^UNRESOLVED' <<<"$out" ;;
  esac || { echo "FAIL test_live_proof: $2 (want $1 ${3:-}):"; head -12 <<<"$out"; fail=1; }
}
job "il \$r6, 7";  pm "il \$r5, 3" "nop";                       run clean "the clean case"
job "a \$r2, \$r6, \$r6"; pm "il \$r5, 3" "nop";                run read "r6 read after the call" "job:0x4008"
job "il \$r6, 7";  pm "nop" "a \$r8, \$r5, \$r5";               run read "the job manager reads r5" "pm:0x10C"
job "il \$r6, 7";  pm "stqa \$r5, 0x210" "lqa \$r8, 0x210";     run clean "r5 saved, the slot reloaded into r8 unread"
job "il \$r6, 7";  pm "stqa \$r5, 0x210" "lqa \$r8, 0x210" "a \$r9, \$r8, \$r8"; run read "taint through the save slot" "pm:0x110"
job "nop";  pm "il \$r5, 3" "bi \$r12";                         run unresolved "an indirect jump with no target"
[[ $fail == 0 ]] && echo "PASS test_live_proof (6 cases)"
exit $fail
