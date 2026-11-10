#!/usr/bin/env bash
# CPU-only synthetic helper test; regenerate toolkit first with ps3recomp-patched.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched"
O="${KZ2_OUT:-work}/runtime/test"
[[ -f "$PT/libs/video/rsx_program_memo.h" ]] || { echo "FAIL: regenerate patched toolkit (6071 header missing)"; exit 1; }
mkdir -p "$O"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror -I"$PT/libs/video" tools/runtime/test_shader_program_memo.c -o "$O/test_shader_program_memo"
"$O/test_shader_program_memo"
