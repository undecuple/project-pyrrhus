#!/usr/bin/env bash
# Host test for KZ2 patch 6036 (lv2 sys_fs_open, syscall 801, decodes the console's CELL_FS_O_* values; one header,
# include/ps3emu/cell_fs_flags.h, shared with cellFs). Builds tools/runtime/test_sys_fs_flags.c
# against the patched toolkit's runtime/syscalls/sys_fs.c and runs it on a scratch tree: the defines, create with
# 0x41/0x42/0x241, no truncation with 0x41, append with 0x401/0x441, CELL_EEXIST with 0xC1 on an existing file,
# CELL_ENOENT without O_CREAT on a missing file, read-only unchanged. No game data, no GPU. Exit 1 on any failure.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_sys_fs_flags.sh
# KZ2_PATCHED_DIR=<tree> names the toolkit directly (the negative control: a tree without 6036 fails); else $KZ2_OUT,
# work/runtime and work are searched.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
P=""
for d in ${KZ2_PATCHED_DIR:+"$KZ2_PATCHED_DIR"} ${KZ2_OUT:+"$KZ2_OUT/ps3recomp-patched"} work/runtime/ps3recomp-patched work/ps3recomp-patched; do
  [[ -f "$d/runtime/syscalls/sys_fs.c" ]] && { P="$d"; break; }
done
[[ -n "$P" ]] || { echo "SKIP test_sys_fs_flags: no patched toolkit here (run tools/ps3recomp-patched.sh)"; exit 0; }
[[ -f "$P/include/ps3emu/cell_fs_flags.h" ]] \
  || echo "note: $P has no include/ps3emu/cell_fs_flags.h (no patch 6036; rerun tools/ps3recomp-patched.sh): expect FAIL"
CC="${CC:-cc}"
O="$ROOT/work/runtime/test"; mkdir -p "$O"
T="$(mktemp -d "$O/sysfsflags.XXXXXX")"
trap '"$ROOT/tools/safe_rm.sh" "$T" >/dev/null 2>&1 || true' EXIT
inc=(); for d in runtime/syscalls include libs runtime runtime/ppu runtime/memory .; do inc+=(-I"$P/$d"); done
printf '%s\n' '#include "filesystem/cellFs.h"' \
  'const unsigned CFS_CREAT = CELL_FS_O_CREAT, CFS_EXCL = CELL_FS_O_EXCL, CFS_TRUNC = CELL_FS_O_TRUNC,' \
  '               CFS_APPEND = CELL_FS_O_APPEND;' > "$T/cellfs_vals.c"
"$CC" -std=gnu17 -O1 -w "${inc[@]}" -o "$T/t" tools/runtime/test_sys_fs_flags.c "$T/cellfs_vals.c" -pthread 2>"$T/err" \
  || { head -20 "$T/err"; echo "[FAIL] test_sys_fs_flags: build"; exit 1; }
mkdir -p "$T/root"
out="$("$T/t" "$T/root" 2>"$T/stderr")"; rc=$?
echo "$out" | grep "^\[FAIL\]" | head -20
echo "$out" | tail -1
if [[ $rc -ne 0 ]]; then echo "[FAIL] test_sys_fs_flags"; exit 1; fi
grep -q "^\[sys_fs\] open -> EEXIST (flags 0xc1)" "$T/stderr" || { echo "[FAIL] test_sys_fs_flags: no EEXIST log line"; exit 1; }
echo "[PASS] test_sys_fs_flags"
