#!/usr/bin/env bash
# Host test (frame_clock pumps the window's messages on every vblank tick, KZ2_PUMP_TICK; from
# Project Helghast v0.1.4): tools/runtime/test_pump_tick.c, a model of the loop, and a check that
# port/kz2/main.cpp pumps inside the catch-up loop. No game data, no GPU.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_pump_tick.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
O=work/runtime/test; mkdir -p "$O"
"${CC:-cc}" -std=c11 -O1 -Wall -Wextra -Werror -fsanitize=address,undefined tools/runtime/test_pump_tick.c -lm -o "$O/test_pump_tick"
"$O/test_pump_tick"
# Wiring: inside frame_clock's `while (... fired < 240)` loop, after the drain and before next_tick advances, a pump
# guarded by kz2_pump_tick_on(); the outer pump is followed by kz2_pump_note.
python3 - port/kz2/main.cpp <<'PY'
import re, sys
s = open(sys.argv[1]).read()
f = s[s.index("static DWORD WINAPI frame_clock(LPVOID)"):]
inner = f[f.index("fired < 240) {"):f.index("next_tick += 16;")]
ok = "kz2_pump_tick_on()" in inner and "kz2_rsx_pump()" in inner and "kz2_pump_note(fired + 1)" in inner
outer = f[f.index("if (fired >= 240)"):]
ok = ok and re.search(r"kz2_rsx_pump\(\) != 0\) \{.*?\n\s*\}\n\s*kz2_pump_note\(fired\);", outer, re.S) is not None
print("PASS: wiring" if ok else "[FAIL] frame_clock does not pump inside the catch-up loop"); sys.exit(0 if ok else 1)
PY
