#!/usr/bin/env bash
# Host test for the Display-page row table: values, ini text, "pc:" commands, the page edit.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_port_rows.sh
# KZ2_MENU_PAGES_DIR=<extracted .../svml/en/kin/menu> also edits the player's own three option pages (sandbox only).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
O=work/runtime/test; mkdir -p "$O"
${CXX:-c++} -std=c++17 -O1 -Wall -Wextra -Werror -Iport/kz2 -o $O/test_port_rows tools/runtime/test_port_rows.cpp || { echo "FAIL build"; exit 1; }
$O/test_port_rows | grep -v "^ok " ; exit "${PIPESTATUS[0]}"
