#!/usr/bin/env bash
# From Project Helghast tools/ps3recomp-patched.sh (KZ3_* -> KZ2_*; output under $KZ2_OUT, default work/, so a second worktree can
# write its own copy: KZ2_OUT=work/runtime).
# Make $KZ2_OUT/ps3recomp-patched: a fresh copy of third_party/ps3recomp at its pinned commit with every
# port/patches/*.patch applied. Both the lift (tools/lift.sh) and the Windows build (port/kz2) use it, so
# the submodule itself stays clean.
#
#   nix develop .#re --command tools/sandbox.sh -- tools/ps3recomp-patched.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SUB=third_party/ps3recomp
PT="${KZ2_PATCHED_DIR:-${KZ2_OUT:-work}/ps3recomp-patched}"   # override for tests only

# Scratch listing mode (v0.19.0 bump round): `tools/ps3recomp-patched.sh --list-failures TREE` takes a toolkit tree TREE
# (a checkout of the target ref, under work/), copies it to a scratch tree, applies every port/patches/*.patch in name
# order with the same git apply flags plus --reject (hunks that pass are applied, so later patches see them; a failing
# patch may therefore be half applied, as in a real rebase attempt), and prints one line per failing patch with its failing
# files, then "N of M patches fail". Touches neither third_party/ps3recomp nor $PT; exit 0 when the listing ran.
# Scratch: work/patch-failure-list.scratch (override KZ2_PATCH_LIST_SCRATCH, for tests). Normal mode is untouched.
if [[ "${1:-}" == "--list-failures" ]]; then
  TREE="${2:-}"
  [[ $# -eq 2 && -d "$TREE" ]] || { echo "usage: tools/ps3recomp-patched.sh --list-failures TREE   (TREE: toolkit checkout under work/)" >&2; exit 2; }
  TREE="$(cd "$TREE" && pwd -P)"
  WORKDIR="$(cd work 2>/dev/null && pwd -P)" || { echo "ps3recomp-patched: no work/ directory" >&2; exit 2; }
  case "$TREE/" in "$WORKDIR"/*) ;; *) echo "ps3recomp-patched: TREE must be under $WORKDIR" >&2; exit 2;; esac
  [[ "$TREE" != "$ROOT/$SUB" ]] || { echo "ps3recomp-patched: refusing the submodule as TREE" >&2; exit 2; }
  SCR="${KZ2_PATCH_LIST_SCRATCH:-$WORKDIR/patch-failure-list.scratch}"
  case "$SCR" in "$WORKDIR"/*) ;; *) echo "ps3recomp-patched: scratch must be under $WORKDIR" >&2; exit 2;; esac
  [[ "$TREE" != "$WORKDIR" ]] || { echo "ps3recomp-patched: TREE must be below $WORKDIR, not work/ itself" >&2; exit 2; }
  case "$SCR/" in "$TREE"/*) echo "ps3recomp-patched: TREE must not contain the scratch $SCR" >&2; exit 2;; esac
  if [[ -e "$SCR" ]]; then "$ROOT/tools/safe_rm.sh" "$SCR"; fi
  mkdir -p "$SCR"
  tar -C "$TREE" --exclude=.git -cf - . | tar -C "$SCR" -xmf -
  fail=0; total=0
  for p in port/patches/*.patch; do
    [[ -e "$p" ]] || continue
    total=$((total + 1))
    rc=0
    out="$(git apply --reject --verbose --whitespace=nowarn --directory="${SCR#"$ROOT"/}" "$p" 2>&1)" || rc=$?
    if (( rc == 0 )) && grep -q "^Applied patch .* cleanly" <<<"$out"; then continue; fi
    fail=$((fail + 1))
    # "error: patch failed: PATH:LINE" and "error: PATH: patch does not apply / No such file ..." name the files.
    files="$(sed -n -e 's/^error: patch failed: \(.*\):[0-9]*$/\1/p' -e 's/^error: \([^ ]*\): .*$/\1/p' <<<"$out" | sed "s#^${SCR#"$ROOT"/}/##" | sort -u | paste -sd, -)"
    echo "FAIL $p: ${files:-(no file named; see git apply output)}"
  done
  echo "$fail of $total patches fail"
  "$ROOT/tools/safe_rm.sh" "$SCR"
  exit 0
fi

# Line endings (issue #9): with Git for Windows' default core.autocrlf=true the submodule's files are stored with LF but
# checked out with CRLF, and the patches' LF context then stops applying part-way through the series (patch 1041 was the
# first). The submodule's own .gitattributes come from upstream, so the check is here: count the files whose index copy is
# LF and whose working copy is CRLF, and stop before copying anything. Reads the index only (works with a read-only .git);
# no git or no index: no check.
crlf="$(git -C "$SUB" ls-files --eol 2>/dev/null | awk '$1 == "i/lf" && $2 == "w/crlf" { n++ } END { print n + 0 }')"
if (( crlf > 0 )); then
  cat >&2 <<EOF
ps3recomp-patched: $crlf file(s) in $SUB are checked out with Windows (CRLF) line endings but stored with LF,
so the patches would not apply. This is git's core.autocrlf (on by default in Git for Windows). Turn it off for
this repository and the submodule, then write the submodule's files out again (this discards any edits in it;
a plain checkout skips files git considers unchanged):
  git config core.autocrlf false
  git -C $SUB config core.autocrlf false
  git -C $SUB rm -r -q --cached . && git -C $SUB reset -q --hard
For a new clone: git -c core.autocrlf=false clone --recurse-submodules <url>, then the second line above.
EOF
  exit 1
fi

# Python for the sync step below (issue #9): python3, else python, else the Windows launcher `py -3`. Each candidate has
# to run a Python 3.6+ (the step uses f-strings): on Windows `python3` is often the Microsoft Store alias, which prints a
# message and exits 49, and `python` may be missing or a Python 2. Chosen before anything is copied.
PYTHON=()
for c in "python3" "python" "py -3"; do
  read -r -a cand <<<"$c"
  if command -v "${cand[0]}" >/dev/null 2>&1 &&
     "${cand[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)' >/dev/null 2>&1; then
    PYTHON=("${cand[@]}"); break
  fi
done
if (( ${#PYTHON[@]} == 0 )); then
  echo "ps3recomp-patched: no Python 3.6 or newer found (tried python3, python, py -3); install Python 3 and run again" >&2
  exit 1
fi

# Build the patched tree in a scratch copy, then sync it into $PT replacing only files whose content changed, so
# unchanged files keep their mtimes and the build recompiles only what the patch set really changed
# (re-creating the whole tree forced a ~20 min full rebuild after every regeneration). A reverted or removed patch
# still rebuilds the files it touched, because their content changes back. A plain copy, no git metadata (so this
# works inside the sandbox where .git is read-only).
NEW="$PT.new"
if [[ -e "$NEW" ]]; then "$ROOT/tools/safe_rm.sh" "$NEW"; fi
mkdir -p "$NEW"
tar -C "$SUB" --exclude=.git -cf - . | tar -C "$NEW" -xmf -
for p in port/patches/*.patch; do
  [[ -e "$p" ]] || continue
  # Run from the repo root with --directory: inside the repo, a bare `git apply` in the tree silently skips paths
  # outside the current directory (it resolves them against the repo root). Require git's confirmation.
  out="$(git apply --verbose --whitespace=nowarn --directory="$NEW" "$p" 2>&1)" || { echo "$out" >&2; exit 1; }
  grep -q "^Applied patch .* cleanly" <<<"$out" || { echo "patch $p did not apply: $out" >&2; exit 1; }
  echo "applied $p"
done
mkdir -p "$PT"
"${PYTHON[@]}" - "$NEW" "$PT" <<'PY'
import filecmp, os, shutil, sys
new, pt = sys.argv[1:]
changed = removed = 0
for d, _, files in os.walk(new):
    rel = os.path.relpath(d, new)
    os.makedirs(os.path.join(pt, rel), exist_ok=True)
    for f in files:
        a, b = os.path.join(d, f), os.path.join(pt, rel, f)
        if not os.path.exists(b) or not filecmp.cmp(a, b, shallow=False):
            shutil.copyfile(a, b); shutil.copymode(a, b); changed += 1
for d, _, files in os.walk(pt):
    rel = os.path.relpath(d, pt)
    for f in files:
        if rel == "." and f == ".kz2-patchset":
            continue
        if not os.path.exists(os.path.join(new, rel, f)):
            os.remove(os.path.join(d, f)); removed += 1
print(f"synced: {changed} file(s) changed, {removed} removed")
PY
"$ROOT/tools/safe_rm.sh" "$NEW"
# Stamp the patch set this tree was made from; tools/build-kz2.sh refuses a stale tree (a build run
# directly, without a build's regeneration, silently left patch 3003 out of a 1.14 test).
echo "$(cat port/patches/*.patch | sha256sum | cut -c1-16)-$(git -C third_party/ps3recomp rev-parse --short HEAD)" > "$PT/.kz2-patchset"
