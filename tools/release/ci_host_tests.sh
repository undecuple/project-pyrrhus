#!/usr/bin/env bash
# Run the host tests from the repository root: every line of tools/host-tests.txt (each a full command, such as
# `nix develop .#re --command python3 tools/...`), then every tools/release/test_*.py the list does not name yet.
# No game data, no network. One line per test and a summary; exit 1 if any failed.
# Adapted from Project Helghast's tools/run-host-tests.sh (the Killzone 3 PC port, same author, MIT).
#
#   tools/release/ci_host_tests.sh [--gh] [--no-sandbox] [--shell NAME] [--list FILE]
#   --gh          GitHub Actions log groups and ::error lines (CI)
#   --no-sandbox  run a "tools/sandbox.sh -- CMD" line as CMD: a hosted runner has no /run/current-system and may not
#                 allow bubblewrap's user namespace; these tests read no game data, the sandbox only guards a
#                 developer's machine
#   --shell NAME  run the lines written for the default and .#re dev shells in .#NAME (CI: ci, the shell without
#                 RPCS3 and the GPU tools)
#   --list FILE   another list (the tests of this script use it)
# work/ and build/ are created first: tools that write only below work/ (tools/assets/profile_edit.py) expect it, as
# tools/sandbox.sh creates both.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 2
GH=0 NOSB=0 SHELL_NAME= LIST=tools/host-tests.txt
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gh) GH=1 ;;
    --no-sandbox) NOSB=1 ;;
    --shell) SHELL_NAME="${2:?--shell needs a dev shell name}"; shift ;;
    --list) LIST="${2:?--list needs a file}"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
[[ -f "$LIST" ]] || { echo "no $LIST" >&2; exit 2; }
mkdir -p work build
cmds=()
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "${line// }" || "$line" == \#* ]] && continue
  cmds+=("$line")
done < "$LIST"
# release tests not in the list yet (a new one runs before the list names it)
for t in tools/release/test_*.py; do
  [[ -f "$t" ]] || continue
  printf '%s\n' "${cmds[@]}" | grep -qF "$t" || cmds+=("nix develop .#re --command python3 $t")
done
n=0; failed=()
for c in "${cmds[@]}"; do
  (( NOSB )) && c="${c//tools\/sandbox.sh -- /}"
  # --shell NAME: the lines for the default and .#re shells run in .#NAME instead (CI: .#ci, without RPCS3)
  if [[ -n "$SHELL_NAME" ]]; then c="${c//nix develop --command/nix develop .#$SHELL_NAME --command}"; c="${c//nix develop .#re --command/nix develop .#$SHELL_NAME --command}"; fi
  n=$((n + 1))
  if (( GH )); then
    echo "::group::$c"; bash -c "$c"; rc=$?; echo "::endgroup::"
    (( rc )) && echo "::error::host test failed (exit $rc): $c"
  else
    out="$(bash -c "$c" 2>&1)"; rc=$?
    if (( rc )); then echo "FAIL $c"; tail -8 <<<"$out"; else echo "ok   $c"; fi
  fi
  (( rc )) && failed+=("$c")
done
echo "host tests: $((n - ${#failed[@]}))/$n pass"
for f in "${failed[@]+"${failed[@]}"}"; do echo "  failed: $f"; done
(( ${#failed[@]} == 0 ))
