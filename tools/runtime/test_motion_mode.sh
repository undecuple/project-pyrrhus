#!/usr/bin/env bash
# Host test for the valves' and charges' stick tilt (port/kz2/kz2_motion.h) and gameplay.ini motion = auto|on|off.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_motion_mode.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
O=work/runtime/test; mkdir -p "$O"
${CC:-cc} -O2 -Wall -Wextra -Werror -Iport/kz2 -o $O/test_motion_mode port/kz2/kz2_gameplay.c tools/runtime/test_motion_mode.c -lm || { echo "FAIL build"; exit 1; }
$O/test_motion_mode || exit 1
echo "test_motion_mode.sh: ok"
