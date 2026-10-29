#!/usr/bin/env bash
# Host test for tools/ps3recomp-patched.sh's Python choice (issue #9): python3, else python, else `py -3`, each only if it
# runs a Python 3.6+. Stand-ins named python3/python/py, first on PATH, shadow the real ones: a broken one exits 49 like
# the Windows Store alias, a working one runs the real Python found below and notes its name. Runs the real script on a
# throw-away repository layout under a temporary folder: no game data, no network.
#   nix develop --command tools/sandbox.sh -- tools/test_ps3recomp_patched_python.sh
set -euo pipefail
# The script under test writes to ${KZ2_OUT:-work}; the checks look in the throw-away repo's work/, so the caller's output
# folder must not leak in (isolation).
unset KZ2_OUT KZ2_PATCHED_DIR
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf -- "$T"' EXIT
fails=0
check() { if [[ "$1" == 1 ]]; then echo "[PASS] $2"; else echo "[FAIL] $2"; fails=$((fails + 1)); fi; }

# A real Python 3 to stand behind the working stand-ins.
REAL=""
for c in "python3" "python" "py -3"; do
  read -r -a cand <<<"$c"
  if command -v "${cand[0]}" >/dev/null 2>&1 &&
     "${cand[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)' >/dev/null 2>&1; then
    REAL="$(command -v "${cand[0]}")${cand[1]:+ ${cand[1]}}"; break
  fi
done
[[ -n "$REAL" ]] || { echo "SKIP test_ps3recomp_patched_python: no Python 3.6+ on this machine to stand behind the stand-ins"; exit 0; }

R="$T/repo"; S="$R/third_party/ps3recomp"; B="$T/bin"
mkdir -p "$R/tools" "$R/port/patches" "$S" "$B"
cp "$ROOT/tools/ps3recomp-patched.sh" "$ROOT/tools/safe_rm.sh" "$R/tools/"
g() { git -C "$S" -c user.name=t -c user.email=t@t "$@"; }
g init -q
g config core.autocrlf false
printf 'one\ntwo\nthree\n' > "$S/a.txt"
g add a.txt && g commit -qm base
printf '%s\n' 'diff --git a/a.txt b/a.txt' '--- a/a.txt' '+++ b/a.txt' '@@ -1,3 +1,3 @@' ' one' '-two' '+TWO' ' three' \
  > "$R/port/patches/0001-a.patch"

# stand-ins: ok NAME (runs the real Python, writes NAME to $T/used) or broken NAME (the Store alias: message, exit 49).
# py takes the version switch first (`py -3 ...`) and only runs with it.
ok() {
  if [[ "$1" == py ]]; then
    printf '#!/bin/sh\n[ "$1" = "-3" ] || exit 2\nshift\necho py >> "%s/used"\nexec %s "$@"\n' "$T" "$REAL" > "$B/$1"
  else
    printf '#!/bin/sh\necho %s >> "%s/used"\nexec %s "$@"\n' "$1" "$T" "$REAL" > "$B/$1"
  fi
  chmod +x "$B/$1"
}
broken() { printf '#!/bin/sh\necho "Python was not found; run without arguments to install from the Microsoft Store" >&2\nexit 49\n' > "$B/$1"; chmod +x "$B/$1"; }
run() {
  rm -f "$T/used"; rm -rf "$R/work"
  set +e; out="$(PATH="$B:$PATH" bash "$R/tools/ps3recomp-patched.sh" 2>"$T/err")"; rc=$?; set -e
  used="$(if [[ -f "$T/used" ]]; then sort -u "$T/used" | tr '\n' ' '; fi)"
}
applied() { [[ $rc -eq 0 ]] && grep -q 'applied port/patches/0001-a.patch' <<<"$out" && grep -q '^synced: ' <<<"$out" &&
            grep -qx 'TWO' "$R/work/ps3recomp-patched/a.txt" 2>/dev/null; }

ok python3; ok python; ok py; run
check "$(applied && [[ "$used" == "python3 " ]] && echo 1)" "python3 works: python3 is used (rc=$rc, used: $used)"

broken python3; ok python; ok py; run
check "$(applied && [[ "$used" == "python " ]] && echo 1)" "python3 is the Store alias: python is used (rc=$rc, used: $used)"

broken python3; broken python; ok py; run
check "$(applied && [[ "$used" == "py " ]] && echo 1)" "python3 and python broken: py -3 is used (rc=$rc, used: $used)"

broken python3; broken python; broken py; run
check "$(! grep -q applied <<<"$out" && [[ $rc -ne 0 && ! -e "$R/work/ps3recomp-patched.new" ]] &&
        grep -q 'no Python 3.6 or newer found (tried python3, python, py -3)' "$T/err" && echo 1)" \
  "no working Python: stops before copying, and says what it tried (rc=$rc)"

if (( fails )); then echo "test_ps3recomp_patched_python: FAIL ($fails)"; exit 1; fi
echo "test_ps3recomp_patched_python: all ok"
