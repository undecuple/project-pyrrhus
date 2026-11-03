#!/usr/bin/env bash
# Host test (KZ2 patch 6037, input-to-present latency probe): tools/runtime/test_input_latency.c
# against the patched toolkit's include/ps3emu/input_latency.h, plus a check that each hook is wired where the
# probe's stages are defined. No game data, no GPU.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_input_latency.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched"
[[ -f "$PT/include/ps3emu/input_latency.h" ]] || { echo "[FAIL] no $PT/include/ps3emu/input_latency.h (run tools/ps3recomp-patched.sh)"; exit 1; }
O=work/runtime/test; mkdir -p "$O"
"${CC:-cc}" -std=gnu11 -O1 -Wall -Wextra -Werror -Wno-unused-function -fsanitize=address,undefined -I"$PT/include" \
  tools/runtime/test_input_latency.c -lm -o "$O/test_input_latency"
"$O/test_input_latency"
python3 - "$PT" <<'PY'
import re, sys
pt = sys.argv[1]
def src(p): return open(f"{pt}/{p}").read()
pad, gcm, ld = src("libs/input/cellPad.c"), src("libs/video/cellGcmSys.c"), src("libs/video/rsx_live_draw.c")
checks = [
  ("cellPad: the press ORed in before the len decision", pad.index("ps3_lat_pad_mask()") < pad.index("nothing new: end the drain")),
  ("cellPad: the read stamped after it", pad.index("ps3_lat_pad_read(") > pad.index("nothing new: end the drain")),
  ("gcm: guest flip request", re.search(r"PS3_FT_FLIP_REQ.*?\n\s*ps3_lat_flip_req\(!in_fifo\);", gcm, re.S) is not None),
  ("gcm: FIFO flip marker", re.search(r"s_flip_request_count\+\+;\n\s*ps3_lat_flip_fifo\(\);", gcm) is not None),
  ("live draw: present start", re.search(r"void rsx_live_draw_present\(u32 buffer_id\)\n\{\n\s*ps3_lat_present\(PS3_LAT_PRES\);", ld) is not None),
  ("live draw: Present bracketed", re.search(r"ps3_lat_present\(PS3_LAT_CALL\);.*?(->Present\(g\.swap|ld_present_swap\(\)).*?ps3_lat_present\(PS3_LAT_RET\);", ld, re.S) is not None),
]
bad = 0
for name, ok in checks:
    print(("PASS: " if ok else "[FAIL] ") + name); bad += not ok
sys.exit(1 if bad else 0)
PY
