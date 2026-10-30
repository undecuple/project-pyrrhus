#!/usr/bin/env bash
# Host test for the mouse look: pad_mouse.h from patch 6046 (script, clip, in-play) and the [mouse] settings
# and arithmetic in port/kz2/kz2_gameplay.[ch]. Needs $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh).
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_mouse_look.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched"
[[ -f $PT/libs/input/pad_mouse.h ]] || { echo "FAIL no $PT/libs/input/pad_mouse.h (run tools/ps3recomp-patched.sh)"; exit 1; }
O=work/runtime/test; mkdir -p "$O"
${CC:-cc} -O2 -Wall -Wextra -Werror -Iport/kz2 -I$PT/libs/input -o $O/test_mouse_look port/kz2/kz2_gameplay.c \
  $PT/libs/input/pad_mouse.c tools/runtime/test_mouse_look.c -lm || { echo "FAIL build"; exit 1; }
$O/test_mouse_look || exit 1
out=$(env -u KZ2_MOUSE_LOOK -u KZ2_MOUSE_SENS -u KZ2_MOUSE_ZOOM_SENS -u KZ2_MOUSE_YAW -u KZ2_MOUSE_INVERT $O/test_mouse_look get 2>&1)
[[ $out == *"mouse_look 1 (sensitivity 2.5 x 0.022 deg/count, zoom x1, invert_y 0)"* ]] || { echo "FAIL get defaults: $out"; exit 1; }
out=$(KZ2_MOUSE_LOOK=0 KZ2_MOUSE_SENS=3 KZ2_MOUSE_INVERT=1 $O/test_mouse_look get 2>&1)
[[ $out == *"mouse_look 0 (sensitivity 3 x 0.022 deg/count, zoom x1, invert_y 1)"* ]] || { echo "FAIL get env: $out"; exit 1; }
echo "test_mouse_look.sh: ok"
