#!/usr/bin/env bash
# Host test for tools/ps3recomp-patched.sh's line-ending check (issue #9): a submodule checked out with CRLF (git's
# core.autocrlf=true, the Git for Windows default) stops the script before any copy or patch, with the fix in the
# message; after the fix the message names, the same patch applies. Runs the real script on a throw-away repository
# layout under a temporary folder: no game data, no network.
#   nix develop --command tools/sandbox.sh -- tools/test_ps3recomp_patched_crlf.sh
set -euo pipefail
# The script under test writes to ${KZ2_OUT:-work}; the checks look in the throw-away repo's work/, so the caller's output
# folder must not leak in (isolation).
unset KZ2_OUT KZ2_PATCHED_DIR
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf -- "$T"' EXIT
fails=0
check() { if [[ "$1" == 1 ]]; then echo "[PASS] $2"; else echo "[FAIL] $2"; fails=$((fails + 1)); fi; }

R="$T/repo"; S="$R/third_party/ps3recomp"
mkdir -p "$R/tools" "$R/port/patches" "$S"
cp "$ROOT/tools/ps3recomp-patched.sh" "$ROOT/tools/safe_rm.sh" "$R/tools/"
g() { git -C "$S" -c user.name=t -c user.email=t@t "$@"; }
g init -q
g config core.autocrlf false
printf 'one\ntwo\nthree\n' > "$S/a.txt"
g add a.txt && g commit -qm base
printf '%s\n' 'diff --git a/a.txt b/a.txt' '--- a/a.txt' '+++ b/a.txt' '@@ -1,3 +1,3 @@' ' one' '-two' '+TWO' ' three' \
  > "$R/port/patches/0001-a.patch"
renorm() { g rm -r -q --cached . && g reset -q --hard; }
# Count CR bytes with tr, not grep: Git for Windows' grep treats CRLF as a line end and never matches \r.
has_cr() { [[ "$(tr -dc '\r' < "$1" | wc -c)" -gt 0 ]]; }

# 1. CRLF working copy: refused before anything is copied or applied, and the message gives the fix.
g config core.autocrlf true; renorm
if ! has_cr "$S/a.txt"; then
  echo "SKIP test_ps3recomp_patched_crlf: this git did not check a.txt out with CRLF under core.autocrlf=true"; exit 0
fi
set +e; out="$(bash "$R/tools/ps3recomp-patched.sh" 2>"$T/err")"; rc=$?; set -e
err="$(cat "$T/err")"
check "$([[ $rc -ne 0 ]] && echo 1)" "CRLF checkout: the script fails (rc=$rc)"
check "$(grep -q 'checked out with Windows (CRLF) line endings' <<<"$err" && grep -q 'core.autocrlf' <<<"$err" && echo 1)" \
  "CRLF checkout: the message names the cause and core.autocrlf"
check "$(grep -q 'rm -r -q --cached . && git -C third_party/ps3recomp reset -q --hard' <<<"$err" && echo 1)" \
  "CRLF checkout: the message gives the re-checkout command"
check "$([[ "$out" != *applied* && ! -e "$R/work/ps3recomp-patched.new" ]] && echo 1)" \
  "CRLF checkout: nothing copied, no patch attempted"

# 2. The fix the message names (core.autocrlf false + re-checkout) gives LF again, and the patch applies.
g config core.autocrlf false; renorm
check "$(! has_cr "$S/a.txt" && echo 1)" "the message's commands restore LF line endings"
py36='import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)'   # the script's own check
if ! { python3 -c "$py36" || python -c "$py36" || py -3 -c "$py36"; } >/dev/null 2>&1; then
  # No Python 3.6+ under any of the names the script tries (python3, python, py -3): its sync step needs one.
  echo "SKIP (part 2): no Python 3.6 or newer here (tried python3, python, py -3), which the script's sync step runs"
else
  set +e; out="$(bash "$R/tools/ps3recomp-patched.sh" 2>"$T/err")"; rc=$?; set -e
  check "$([[ $rc -eq 0 ]] && grep -q 'applied port/patches/0001-a.patch' <<<"$out" && echo 1)" \
    "LF checkout: the patch applies (rc=$rc)"
  check "$(grep -qx 'TWO' "$R/work/ps3recomp-patched/a.txt" 2>/dev/null && echo 1)" "LF checkout: the patched tree has the change"
fi

if (( fails )); then echo "test_ps3recomp_patched_crlf: FAIL ($fails)"; exit 1; fi
echo "test_ps3recomp_patched_crlf: all ok"
