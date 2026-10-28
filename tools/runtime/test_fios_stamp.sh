#!/usr/bin/env bash
# Host test: port/kz2/kz2_fios_stamp.h (FIOS disk cache stamp, patch 6035's pre-open hook) and the
# hook's wiring in the patched toolkit's cellFsOpen. No game data, no GPU.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_fios_stamp.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
O=work/runtime/test; mkdir -p "$O"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined tools/runtime/test_fios_stamp.c -o "$O/test_fios_stamp"
"$O/test_fios_stamp" "$ROOT/$O"
grep -q 'g_ps3_fs_preopen_hook(gpath, hpath);   /\* KZ2 patch 6035 \*/' port/patches/6035-cellfs-preopen-hook.patch \
  || { echo "[FAIL] patch 6035 does not call the pre-open hook in cellFsOpen"; exit 1; }
grep -q '^#include "kz2_fios_stamp.h"' port/kz2/main.cpp || { echo "[FAIL] main.cpp does not include kz2_fios_stamp.h"; exit 1; }
echo "PASS: wiring"
