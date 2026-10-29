#!/usr/bin/env bash
# Native build + run of the log redaction host test (tools/release/test_log_redact.c, pure port/kz2/kz2_log_redact.h;
# an earlier change, issue #16). No game data, no GPU.
#   nix develop --command tools/sandbox.sh -- tools/release/test_log_redact.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
mkdir -p "$OUT/release/test"
${CC:-cc} -std=c11 -O2 -Wall -Wextra -Werror -Iport/kz2 -o "$OUT/release/test/test_log_redact" tools/release/test_log_redact.c
"$OUT/release/test/test_log_redact" | grep -v "^\[PASS\]"
