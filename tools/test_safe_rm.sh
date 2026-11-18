#!/usr/bin/env bash
# Host test for tools/safe_rm.sh: a symlink argument is unlinked and its target kept; a path through a symlinked folder
# and a path outside work/ and build/ are refused; a plain folder in work/ is deleted.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
T="$ROOT/work/test-safe-rm.$$"; OUT="$(mktemp -d)"
trap 'rm -rf -- "$T" "$OUT"' EXIT
mkdir -p "$T/real/sub" "$OUT/keep"; echo x > "$T/real/sub/f"; echo y > "$OUT/keep/f"
ln -s "$T/real" "$T/link-in"; ln -s "$OUT/keep" "$T/link-out"
fail=0; ok() { echo "ok   $1"; }; bad() { echo "FAIL $1"; fail=1; }
tools/safe_rm.sh "$T/link-in" && [[ ! -e "$T/link-in" && -f "$T/real/sub/f" ]] && ok "link in work/ unlinked, target kept" || bad "link in work/"
tools/safe_rm.sh "$T/link-out" && [[ ! -L "$T/link-out" && -f "$OUT/keep/f" ]] && ok "link to outside unlinked, target kept" || bad "link to outside"
ln -s "$T/real" "$T/link-dir"
! tools/safe_rm.sh "$T/link-dir/sub" 2>/dev/null && [[ -f "$T/real/sub/f" ]] && ok "path through a symlinked folder refused" || bad "through symlink"
! tools/safe_rm.sh "$OUT/keep" 2>/dev/null && [[ -f "$OUT/keep/f" ]] && ok "outside work/ refused" || bad "outside"
! tools/safe_rm.sh "$ROOT/work" 2>/dev/null && ok "work/ itself refused" || bad "work itself"
tools/safe_rm.sh "$T/real" && [[ ! -e "$T/real" ]] && ok "plain folder deleted" || bad "plain folder"
(( fail == 0 )) && echo "PASS test_safe_rm" || { echo "FAIL test_safe_rm"; exit 1; }
