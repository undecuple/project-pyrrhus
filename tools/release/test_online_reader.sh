#!/usr/bin/env bash
# Native build + run of the online settings reader's host test (tools/release/test_online_reader.cpp, which includes
# port/kz2/kz2_online.cpp with KZ2_ONLINE_TEST; an earlier change, D56). No game data, no GPU, no network.
# Then the reader's game build compiled for syntax against the patched toolkit (net_policy.h), when it is there.
#   nix develop --command tools/sandbox.sh -- tools/release/test_online_reader.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
T="$OUT/release/test"; mkdir -p "$T"
TMP="$(mktemp -d "$T/online-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
${CXX:-c++} -std=c++17 -O1 -Wall -Wextra -Werror -o "$T/test_online_reader" tools/release/test_online_reader.cpp
"$T/test_online_reader" "$TMP" | grep -v '^ok ' || true
"$T/test_online_reader" "$TMP" >/dev/null
python3 -I tools/release/test_online_ini.py --reader "$T/test_online_reader"
PATCHED="$ROOT/work/ps3recomp-patched"
if [ -f "$PATCHED/libs/network/net_policy.h" ]; then
    ${CXX:-c++} -std=c++17 -fsyntax-only -Wall -Wextra -Werror -I"$PATCHED/runtime/ppu" -Iport/kz2 port/kz2/kz2_online.cpp
    echo "game build of kz2_online.cpp: syntax ok (patched toolkit)"
else
    echo "SKIP game build syntax check: no work/ps3recomp-patched"
fi
