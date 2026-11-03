#!/usr/bin/env bash
# Host test for patch 6050 (keys keep their action under any pad layout): tools/runtime/test_kb_roles.c.
#   nix develop --command tools/sandbox.sh -- env KZ2_OUT=work/runtime tools/runtime/test_kb_roles.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
P=""
for o in ${KZ2_OUT:+"$KZ2_OUT"} work/runtime work; do [[ -f "$o/ps3recomp-patched/libs/input/pad_kb_roles.h" ]] && { P="$o/ps3recomp-patched"; break; }; done
[[ -n "$P" ]] || { echo "SKIP test_kb_roles: no patched toolkit with patch 6050 here (run tools/ps3recomp-patched.sh)"; exit 0; }
O=work/runtime/test; mkdir -p "$O"
${CC:-cc} -O2 -Wall -Wextra -Werror -Iport/kz2 -I"$P/libs/input" -o $O/test_kb_roles port/kz2/kz2_pad_layout.c tools/runtime/test_kb_roles.c || { echo "FAIL build"; exit 1; }
$O/test_kb_roles
