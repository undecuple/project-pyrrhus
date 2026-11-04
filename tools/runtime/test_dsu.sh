#!/usr/bin/env bash
# Host test for KZ2 patch 6062 (the DSU (cemuhook) motion client): builds tools/runtime/test_dsu.c
# against the patched toolkit's libs/input/pad_dsu_io.h + pad_motion_stick.h and port/kz2/kz2_motion.h, and runs it: a
# fake DSU server on 127.0.0.1 in the same process (bad packets rejected, good ones become the expected SIXAXIS words,
# by motion mode, and the title port's stick feed stops). Loopback only, no game data.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_dsu.sh
# Needs $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh); work/runtime and work are searched too.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
P=""
for o in ${KZ2_OUT:+"$KZ2_OUT"} work/runtime work; do [[ -f "$o/ps3recomp-patched/libs/input/pad_dsu_io.h" ]] && { P="$o/ps3recomp-patched"; break; }; done
[[ -n "$P" ]] || { echo "SKIP test_dsu: no patched toolkit with patch 6062 here (run tools/ps3recomp-patched.sh)"; exit 0; }
mkdir -p work/runtime/test
${CC:-cc} -O2 -Wall -Wextra -Wno-unused-function -I"$P/include" -I"$P/libs/input" -Iport/kz2 -o work/runtime/test/test_dsu \
    tools/runtime/test_dsu.c -lm || { echo "FAIL test_dsu: build"; exit 1; }
if work/runtime/test/test_dsu; then echo "PASS test_dsu"; else echo "FAIL test_dsu"; exit 1; fi
