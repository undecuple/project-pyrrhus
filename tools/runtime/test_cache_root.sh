#!/usr/bin/env bash
# Host test: port/kz2/kz2_cache_root.h (KZ2_CACHE_ROOT: the game folder read in place, every write under the cache
# root; an earlier change), its wiring in main.cpp and the name tools/release/firstrun.py cache_root_supported looks for.
# No game data, no GPU.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_cache_root.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
O=work/runtime/test; mkdir -p "$O"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined tools/runtime/test_cache_root.c -o "$O/test_cache_root"
"$O/test_cache_root"
grep -q 'KZ2_CACHE_ROOT' port/kz2/kz2_cache_root.h || { echo "[FAIL] kz2_cache_root.h does not name KZ2_CACHE_ROOT"; exit 1; }
grep -q '^#include "kz2_cache_root.h"' port/kz2/main.cpp || { echo "[FAIL] main.cpp does not include kz2_cache_root.h"; exit 1; }
# order: the update dir (an RPCS3 tree sets PS3_HDD0_ROOT) before the split, both before the first guest file open
awk '/^    setup_update_dir\(\);/{u=NR} /^    kz2_split_roots\(\);/{s=NR} /^    ppu_fs_register\(\);/{f=NR} END{exit !(u && s && f && u < s && s < f)}' \
  port/kz2/main.cpp || { echo "[FAIL] main.cpp: setup_update_dir, kz2_split_roots, ppu_fs_register out of order"; exit 1; }
python3 -I -c "import sys; sys.path.insert(0, 'tools/release'); import firstrun as fr; sys.exit(0 if fr.cache_root_supported('.') else 1)" \
  || { echo "[FAIL] firstrun.cache_root_supported does not see the header"; exit 1; }
echo "PASS: wiring"
