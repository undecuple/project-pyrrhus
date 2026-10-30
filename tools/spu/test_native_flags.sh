#!/usr/bin/env bash
# Spu rounds 18-19 host test: the native gates' flag rule (port/kz2/spu/native_flags.h; tools/spu/test_native_flags.c):
# every Gfx.Post flag on by default for the slots with a recorded-in-play equality, a flag's own 0 turns its
# job off (also under KZ2_NATIVE_JOB_POST=1), KZ2_NATIVE_JOB_POST=0 turns every Gfx.Post gate off, the post slots never
# called in a recorded run and the non-post jobs (KZ2_NATIVE_JOB_EDGEANIM) off by default. Also checks that only
# DepthOfField's kernel entries name KZ2_NATIVE_JOB_DOF, that every default-on flag names a table entry, and that every
# recorded slot is a gate of re/spu/native_gates.tsv (EdgeAnim and VertexJob's .bss clear on by default). No game data.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_native_flags.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/${KZ2_OUT:-work}/spu"; case "$O" in /*) ;; *) O="$ROOT/$O" ;; esac
mkdir -p "$O"; rm -f "$O/t_native_flags"
gcc -std=gnu17 -O2 -Wall -I "$ROOT/port/kz2/spu" -o "$O/t_native_flags" "$ROOT/tools/spu/test_native_flags.c" 2>&1 | grep -m5 error
"$O/t_native_flags" || { echo "FAIL test_native_flags"; exit 1; }
# the DOF kernels' flag is used by native_dof.c's three kernel entries (DOF_ENV) and nowhere else
n=$(cat "$ROOT"/port/kz2/spu/*.c | grep -c '"KZ2_NATIVE_JOB_DOF"')
k=$(grep -c '^    { [0-2], DOF_ENV' "$ROOT/port/kz2/spu/native_dof.c")
if [[ $n -ne 1 || $k -ne 3 ]]; then
  echo "FAIL test_native_flags: KZ2_NATIVE_JOB_DOF named $n times, DOF_ENV entries $k (want 1 and 3)"; exit 1; fi
# every default-on flag is some gate's flag in re/spu/native_gates.tsv
flags=$(sed -n '/kz2_native_default_on\[\] = {/,/};/p' "$ROOT/port/kz2/spu/native_flags.h" | grep -o '"KZ2_NATIVE_JOB_[A-Z0-9]*"' | tr -d '"')
for f in $flags; do
  awk -F'\t' -v f="$f" '!/^#/ { n = split($5, a, "|"); for (i = 1; i <= n; i++) if (a[i] == f) found = 1 } END { exit !found }' \
    "$ROOT/re/spu/native_gates.tsv" || { echo "FAIL test_native_flags: default-on $f names no gate"; exit 1; }
done
# every recorded slot is a gate of re/spu/native_gates.tsv (not only Gfx.Post)
slots=$(sed -n '/kz2_native_play_recorded\[\] = {/,/};/p' "$ROOT/port/kz2/spu/native_flags.h" | sed 's/.*{//' | grep -o '[0-9][0-9]*')
for s in $slots; do
  awk -F'\t' -v s="$s" '!/^#/ && $3 == s { found = 1 } END { exit !found }' "$ROOT/re/spu/native_gates.tsv" ||
    { echo "FAIL test_native_flags: recorded slot $s is no gate"; exit 1; }
done
echo "PASS test_native_flags ($(echo $flags | wc -w) default-on flags, $(echo $slots | wc -w) recorded slots, DOF_ENV on slots 0-2 only)"
