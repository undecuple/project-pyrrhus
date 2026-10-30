#!/usr/bin/env bash
# Host test for the PSO key file header and its shader translator check (patch 6047). Needs
# $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh).
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_pso_keys_hdr.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched"
[[ -f $PT/libs/video/rsx_pso_keys_hdr.h ]] || { echo "FAIL no $PT/libs/video/rsx_pso_keys_hdr.h (run tools/ps3recomp-patched.sh)"; exit 1; }
O=work/runtime/test; mkdir -p "$O"
${CC:-cc} -O2 -Wall -Wextra -Werror -I$PT/libs/video -o $O/test_pso_keys_hdr tools/runtime/test_pso_keys_hdr.c || { echo "FAIL build"; exit 1; }
$O/test_pso_keys_hdr || exit 1
echo "test_pso_keys_hdr.sh: ok"
