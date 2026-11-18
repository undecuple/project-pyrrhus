#!/usr/bin/env bash
# Guarded recursive delete. Only removes paths inside $KZ2_ROOT/work or $KZ2_ROOT/build.
#   tools/safe_rm.sh <path>...
# A symlink argument is only unlinked, never followed (an earlier version resolved it and deleted the link's target;
# Project Helghast fixed the same flaw). A path whose folders pass through a symlink is refused.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
for p in "$@"; do
  : "${p:?empty path}"
  p="${p%/}"
  dir="$(dirname -- "$p")" leaf="$(basename -- "$p")"
  [[ "$leaf" == "." || "$leaf" == ".." ]] && { echo "safe_rm: refusing '$p' (no . or ..)" >&2; exit 1; }
  logical="$(realpath -s -- "$dir")" physical="$(cd -- "$dir" 2>/dev/null && pwd -P)" || {
    echo "safe_rm: refusing '$p' (its folder does not exist)" >&2; exit 1; }
  [[ "$logical" == "$physical" ]] || { echo "safe_rm: refusing '$p' (its folder passes through a symlink: $physical)" >&2; exit 1; }
  target="$physical/$leaf"
  case "$target" in
    "$ROOT/work/"?*|"$ROOT/build/"?*) ;;
    *) echo "safe_rm: refusing '$p' (resolves to '$target', outside work/ and build/)" >&2; exit 1 ;;
  esac
  if [[ -L "$target" ]]; then rm -f -- "$target"; else rm -rf -- "$target"; fi
done
