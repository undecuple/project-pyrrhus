#!/usr/bin/env bash
# Host test: the native-gate diff harness's MFC model (tools/spu/harness_mfc.h): a routine's MFC
# writes and reads logged in order, a put's bytes taken from the local store at the command, the synchronous tag
# wait, every kind of difference caught. No game data; test_native_vjvert.sh checks the model end to end on the lift.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_harness_mfc.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/${KZ2_OUT:-work}/spu"; case "$O" in /*) ;; *) O="$ROOT/$O" ;; esac
mkdir -p "$O"; rm -f "$O/t_harness_mfc"
gcc -std=gnu17 -O2 -Wall -Werror -o "$O/t_harness_mfc" "$ROOT/tools/spu/test_harness_mfc.c" 2>&1 | grep -m5 error
"$O/t_harness_mfc" || { echo "FAIL test_harness_mfc"; exit 1; }
