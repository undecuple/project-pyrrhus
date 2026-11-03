#!/usr/bin/env bash
# Host test for patch 6051 (FSR 1 as an in-game option; from KZ3 patch 2145): live choice, off rule, size pairs, FSR 1
# constants, HLSL assembly, environment fallback. Needs $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh).
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_upscale_live.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched/libs/video"
[[ -f $PT/rsx_upscale.h ]] || { echo "FAIL no $PT/rsx_upscale.h (run tools/ps3recomp-patched.sh)"; exit 1; }
O=work/runtime/test; mkdir -p "$O"
${CC:-cc} -O2 -Wall -Wextra -Werror -I$PT -o $O/test_upscale_live tools/runtime/test_upscale_live.c $PT/rsx_upscale.c $PT/rsx_upscale_fsr1.c -lm \
  || { echo "FAIL build"; exit 1; }
$O/test_upscale_live || exit 1
out=$(env -u RSX_UPSCALE -u RSX_UPSCALE_SHARPNESS $O/test_upscale_live env 2>&1); [[ $out == "0 0.20" ]] || { echo "FAIL env default: $out"; exit 1; }
out=$(RSX_UPSCALE=fsr1 RSX_UPSCALE_SHARPNESS=1.5 $O/test_upscale_live env 2>&1); [[ $out == *"1 1.50" ]] || { echo "FAIL env fsr1: $out"; exit 1; }
echo "test_upscale_live.sh: ok"
