#!/usr/bin/env bash
# From Project Helghast tools/spu/test_spurs_kern.sh (paths adapted: the patched toolkit under $KZ2_OUT, default work/).
# Patch 1074 host test: tools/spu/test_spurs_kern.c (the per-SPU SPURS kernel's selection rule, poll answer and idle
# wake, runtime/spu/spurs_kern_sched.h). Needs a patched toolkit with patch 1074 ($KZ2_OUT/ps3recomp-patched, or
# KERN_HDR=DIR holding spurs_kern_sched.h); says SKIP without it.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_spurs_kern.sh
#   KZ2_OUT=work/spu ... (a separate build tree)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/${KZ2_OUT:-work}"; mkdir -p "$O"
H="${KERN_HDR:-$O/ps3recomp-patched/runtime/spu}"
[[ -f "$H/spurs_kern_sched.h" ]] || { echo "SKIP: no patched toolkit with patch 1074 at $H"; exit 0; }
gcc -std=gnu17 -O2 -Wall -Wextra -pthread -I "$H" -o "$O/t_spurs_kern" "$ROOT/tools/spu/test_spurs_kern.c" 2>&1 | grep -m5 -E "error|warning"
[[ -x "$O/t_spurs_kern" ]] || { echo "FAIL: build"; exit 1; }
"$O/t_spurs_kern"
