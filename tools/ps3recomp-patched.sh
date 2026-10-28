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
python3 - "$NEW" "$PT" <<'PY'
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
