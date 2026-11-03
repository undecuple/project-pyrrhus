#!/usr/bin/env bash
# From Project Helghast tools/spu/test_r112_sched.sh (the patched toolkit is $KZ2_PATCHED_DIR or $KZ2_OUT/ps3recomp-patched,
# default work/). Patches 1136/1140/7012 host test (tools/spu/test_r112_sched.c): the P-core mask choice on synthetic
# topologies (uniform CPU = no restriction), the scope switch, the SPURS name list, KZ2 7012s default list and default-off switch. No game data.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_r112_sched.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/work/spu"; mkdir -p "$O"
P="${KZ2_PATCHED_DIR:-$ROOT/${KZ2_OUT:-work}/ps3recomp-patched}"
if [[ ! -f "$P/runtime/spu/kz3_spu_sched.h" ]]; then echo "SKIP: $P has no patch 1136"; exit 0; fi
gcc -std=gnu17 -O2 -Wall -I "$P/runtime/spu" -o "$O/t_r112_sched" "$ROOT/tools/spu/test_r112_sched.c" && "$O/t_r112_sched"
