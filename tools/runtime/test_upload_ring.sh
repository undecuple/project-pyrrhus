#!/usr/bin/env bash
# Host test for the upload ring placement (patch 6048: a texture level that does not fit submits the list first).
# Needs $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh).
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_upload_ring.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched"
[[ -f $PT/libs/video/rsx_upload_ring.h ]] || { echo "FAIL no $PT/libs/video/rsx_upload_ring.h (run tools/ps3recomp-patched.sh)"; exit 1; }
O=work/runtime/test; mkdir -p "$O"
${CC:-cc} -O2 -Wall -Wextra -Werror -I$PT/libs/video -o $O/test_upload_ring tools/runtime/test_upload_ring.c || { echo "FAIL build"; exit 1; }
$O/test_upload_ring || exit 1
echo "test_upload_ring.sh: ok"
