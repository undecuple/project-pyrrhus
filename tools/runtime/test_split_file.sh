#!/usr/bin/env bash
# Host test for KZ2 patch 6034 (ps3emu/split_file.h: a file a FAT32 copy keeps as <name>.66600, .66601, ... read as
# one file). Takes the header out of the patch itself (no patched toolkit needed), builds
# tools/runtime/test_split_file.c with -Werror as C, checks the header also compiles as C++ (ppu_fs.cpp and
# kz2_menu_pages.cpp include it) and, when a MinGW compiler is on PATH, for Windows; then runs the checks: a single
# file, uneven parts, reads across every edge, positional reads, seeks, 4 threads, a gap and a missing first part
# named, and a 4 GiB - 1 sparse part (64-bit offsets). No game data, no GPU. Exit 1 on any failure.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_split_file.sh
# Adapted from the Killzone 3 PC port's port/vfs/test_splitfile.sh (Project Helghast v0.1.3, same author, MIT).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
P="$ROOT/port/patches/6034-vfs-fat32-split-parts-read-as-one-file.patch"
O="$(mktemp -d "${TMPDIR:-/tmp}/kz2-sf.XXXXXX")"; trap 'rm -rf -- "$O"' EXIT
mkdir -p "$O/run"
awk '/^diff --git a\/include\/ps3emu\/split_file.h /{on=1; next} on && /^diff --git /{exit} on && /^@@/{body=1; next} on && body && /^\+/{print substr($0, 2)}' \
  "$P" > "$O/split_file.h"
[[ -s "$O/split_file.h" ]] || { echo "FAIL: no include/ps3emu/split_file.h in $P"; exit 1; }
CC="${CC:-cc}"; CXX="${CXX:-c++}"
"$CC" -std=gnu17 -O2 -Wall -Wextra -Werror -I"$O" -o "$O/t" "$ROOT/tools/runtime/test_split_file.c" -pthread 2>"$O/err" \
  || { echo "FAIL build (C)"; head -20 "$O/err"; exit 1; }
printf '#include "split_file.h"\nint main(){ return ps3_sf_has_parts("x") ? 1 : 0; }\n' > "$O/cxx.cpp"
"$CXX" -std=c++17 -Wall -Wextra -Werror -I"$O" -fsyntax-only "$O/cxx.cpp" 2>"$O/err" || { echo "FAIL build (C++)"; head -20 "$O/err"; exit 1; }
echo "[ok]   the header compiles as C and C++ with -Werror"
if command -v x86_64-w64-mingw32-gcc >/dev/null; then
  x86_64-w64-mingw32-gcc -std=gnu17 -Wall -Wextra -Werror -I"$O" -fsyntax-only -x c "$O/cxx.cpp" 2>"$O/err" \
    || { echo "FAIL build (MinGW)"; head -20 "$O/err"; exit 1; }
  echo "[ok]   the header compiles for Windows (MinGW, -Werror)"
fi
"$O/t" "$O/run"
