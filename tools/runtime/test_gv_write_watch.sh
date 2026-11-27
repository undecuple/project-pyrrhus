#!/usr/bin/env bash
# Host test (KZ2 patch 6086, guest-validate skipped by the write watch, LD_GV_WW): tools/runtime/test_gv_write_watch.c
# against the patched toolkit's libs/video/rsx_tex_ww.h (ld_ww_skip_or_arm on a fake OS write watch, with a random
# run against "hash every time" and a negative control), plus the wiring in libs/video/rsx_live_draw.c.
# No game data, no GPU.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_gv_write_watch.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched"
[[ -f "$PT/libs/video/rsx_tex_ww.h" ]] || { echo "[FAIL] no $PT/libs/video/rsx_tex_ww.h (run tools/ps3recomp-patched.sh)"; exit 1; }
grep -q "ld_ww_skip_or_arm" "$PT/libs/video/rsx_tex_ww.h" || { echo "[FAIL] rsx_tex_ww.h has no ld_ww_skip_or_arm (patch 6086)"; exit 1; }
O=work/runtime/test; mkdir -p "$O"
"${CC:-cc}" -std=gnu11 -O1 -Wall -Wextra -Werror -Wno-unused-function -fsanitize=address,undefined -I"$PT/libs/video" \
  tools/runtime/test_gv_write_watch.c -o "$O/test_gv_write_watch"
"$O/test_gv_write_watch"
PY=()
for c in "python3" "python" "py -3"; do
  read -r -a cand <<<"$c"
  if "${cand[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)' >/dev/null 2>&1; then
    PY=("${cand[@]}"); break
  fi
done
(( ${#PY[@]} )) || { echo "FAIL: no Python 3.6 or newer (tried python3, python, py -3)"; exit 1; }
"${PY[@]}" - "$PT/libs/video/rsx_live_draw.c" <<'PY'
import re, sys
ld = open(sys.argv[1], encoding="utf-8", errors="replace").read()
i = ld.index("static int ld_gv_hash_bands(surface_t* s, u8* changed)"); fn = ld[i:ld.index("\n}\n", i)]
checks = [
  ("the switch is off unless LD_GV_WW=1", "ww = (e && e[0] == '1') ? 1 : 0;" in fn),
  ("only with the texture watch on (mode 1, not verify)", "if (ww && ld_ww_mode() == 1) {" in fn),
  ("new (empty) band hashes disarm the watch before the decision", fn.index("s->gv_ww.seq = 0;") < fn.index("ld_ww_skip_or_arm(")),
  ("the geometry the hashes were made with is part of the decision",
   re.search(r"const int same = s->gv_ww_w == s->w && s->gv_ww_h == s->h && s->gv_ww_pitch == gp && s->gv_ww_texel == texel;", fn) is not None),
  ("a skip reports every band unchanged and counts itself",
   re.search(r"if \(changed\) memset\(changed, 0, bands\);\s*g_gv\.ww_skips\+\+;\s*return 1;", fn) is not None),
  ("the decision comes before the bytes are read", fn.index("ld_ww_skip_or_arm(") < fn.index("ld_gv_band_hash(")),
  ("the geometry is recorded when the pass hashes", fn.index("s->gv_ww_w = s->w;") > fn.index("ld_ww_skip_or_arm(") and fn.index("s->gv_ww_w = s->w;") < fn.index("ld_gv_band_hash(")),
  ("[guest-validate] prints ww-skips", "ww-skips=%llu" in ld and "g_gv.ww_skips);" in ld),
]
bad = 0
for name, ok in checks:
    print(("PASS: " if ok else "[FAIL] ") + name); bad += not ok
sys.exit(1 if bad else 0)
PY
