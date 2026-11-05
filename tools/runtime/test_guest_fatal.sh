#!/usr/bin/env bash
# Host test for the game's fatal paths (port/kz2/kz2_guest_fatal.h; an earlier change, public #49).
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_guest_fatal.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
O=work/runtime/test; mkdir -p "$O"
${CXX:-c++} -std=c++17 -O2 -Wall -Wextra -Werror -Iport/kz2 -o $O/test_guest_fatal tools/runtime/test_guest_fatal.cpp || { echo "FAIL build"; exit 1; }
$O/test_guest_fatal || exit 1
echo "test_guest_fatal.sh: ok"
