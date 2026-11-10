#!/usr/bin/env bash
# Real settings implementation, no game data. Use the shared build lock.
set -euo pipefail
cd "$(dirname "$0")/../.."
out=work/runtime/test/skip-intro
mkdir -p "$out"
"${CXX:-c++}" -std=c++17 -O2 -Wall -Wextra -Werror -pthread -Iport/kz2 \
  port/kz2/kz2_port_settings.cpp tools/runtime/test_skip_intro.cpp -o "$out/test"
env -u KZ2_SKIP_INTRO "$out/test" 0
KZ2_SKIP_INTRO=1 "$out/test" 1
KZ2_SKIP_INTRO=0 "$out/test" 0
KZ2_SKIP_INTRO=on "$out/test" 1
KZ2_SKIP_INTRO=off "$out/test" 0
KZ2_SKIP_INTRO=invalid "$out/test" 0
