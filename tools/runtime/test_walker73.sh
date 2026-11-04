#!/usr/bin/env bash
# Host test for KZ2 patches 6063-6067 (the walker's per-draw cost): builds tools/runtime/test_walker73.c
# against code taken from the patched toolkit:
#   - libs/video/rsx_cb_reuse.h (6064, LD_CB_REUSE's decision),
#   - gcm_perf_flush_line (6063) and the GCM_FAST_METHODS block (6065), cut out of libs/video/cellGcmSys.c by their
#     markers into work/runtime/test/walker73_cut.inc, so the test runs the shipped text, not a copy,
#   - gcm_walker_switch (6067) likewise.
# Also checks the per-word loop's routing lines the fast path mirrors are still the ones 6065 was written against.
# No game data, no GPU.   nix develop --command tools/sandbox.sh -- tools/runtime/test_walker73.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
P=""
for d in ${KZ2_PATCHED_DIR:+"$KZ2_PATCHED_DIR"} ${KZ2_OUT:+"$KZ2_OUT/ps3recomp-patched"} work/runtime/ps3recomp-patched work/ps3recomp-patched; do
  [[ -f "$d/libs/video/rsx_cb_reuse.h" ]] && { P="$d"; break; }
done
[[ -n "$P" ]] || { echo "SKIP test_walker73: no patched toolkit with patch 6064 here (run tools/ps3recomp-patched.sh)"; exit 0; }
O=work/runtime/test; mkdir -p "$O"
G="$P/libs/video/cellGcmSys.c"
python3 - "$G" "$O/walker73_cut.inc" <<'PY'
import sys
src = open(sys.argv[1]).read()
def cut(start, end, incl_end=True):
    a = src.index(start); b = src.index(end, a)
    return src[a:b + (len(end) if incl_end else 0)]
out = []
out.append(cut("static void gcm_perf_flush_line(char* fl, size_t n, double tnow, const long long* d, double tk)\n{", "\n}\n"))
out.append(cut("volatile int g_gcm_walker_toggle_phase;", "\n}\n"))      # + gcm_walker_toggle_on, gcm_walker_switch
fast = cut("            if (fastm && count && method != 0 && subch <= 1 &&", "                    continue;\n                }\n            }\n")
out.append("static int fast_block(int fastm, u32 method, u32 count, u32 type, u32 subch, int s1_2d, long long meth_t0)\n{\n"
           "    for (int once = 0; once < 1; once++) {\n" + fast + "        return 0;\n    }\n    return 1;\n}\n")
# the per-word loop's routing the fast path mirrors (6065): fail if it changed
tail = ['if (mfull == 0xEB00u || mfull == 0xEB04u) {', 'cellGcmQueueUserCommand(vm_read32(dea));',
        '} else if (mfull == 0xE920u || mfull == 0xE924u) {', 'cellGcmSetFlipCommand(vm_read32(dea) & 7u);',
        '} else if (subch == 0 || (subch == 1 && !s1_2d && !gcm_subch1_nv0039(m))) {',
        'gcm_3d_method(&s_state, m, vm_read32(dea), legacy_state_live);', 'gcm_2d_method(subch, m, vm_read32(dea));']
for t in tail:
    if t not in src: sys.exit("FAIL test_walker73: per-word routing line changed: " + t)
open(sys.argv[2], "w").write("\n".join(out))
PY
"${CC:-cc}" -std=gnu11 -O1 -Wall -Werror -Wno-unused-function -I"$P/libs/video" -I"$O" tools/runtime/test_walker73.c -o "$O/test_walker73"
"$O/test_walker73"
# tools/runtime/perf/walker_ab.py on a made-up log: 7 phases of 3 seconds, the on-phases' draw time 2 ms/frame lower;
# the first second of each phase carries the switch and must be dropped (its draw time is 1000 ms: it would show).
L="$O/walker73_ab.txt"; : > "$L"; t=100
for ph in 0 1 2 3 4 5 6; do
  echo "[walker-toggle] t=$t.000s phase=$ph $([[ $((ph % 2)) == 1 ]] && echo on || echo off)" >> "$L"
  for s in 0 1 2; do
    dr=$(( ph % 2 ? 380 : 420 )); [[ $s == 0 ]] && dr=1000
    echo "[perf] t=${t}s wall=1000ms flips=20 fifo-flips=0 presents=0 draws=30000 | walk n=100 700.0ms methods=1 | flush n=1 (present 0, ref 0, other 1) 10.0ms gpuwait 9.0ms | x" >> "$L"
    echo "[perf-walk] t=${t}s draw ${dr}.0ms (vtx 200.0, pso 80.0 new 0/0.0ms, const 10.0, tex 50.0 new 1/1.0ms) clear 1 | tex-hash 40.0ms | pso: pre 9.0 units 11.0 key 58.0 find 3.0 memo-hits 1 | cbv copy 10 reuse 5" >> "$L"
    t=$((t + 1))
  done
done
out="$(python3 tools/runtime/perf/walker_ab.py "$L")"
grep -q '^draw ms/frame  *21.00  *19.00  *-2.00  *-2.00    3/3 ' <<<"$out" || { echo "FAIL test_walker73: walker_ab.py: $out" | head -8; exit 1; }
grep -q 'clean seconds: off 8, on 6; pairs 3' <<<"$out" || { echo "FAIL test_walker73: walker_ab.py seconds: $(tail -1 <<<"$out")"; exit 1; }
echo "PASS test_walker73 walker_ab.py (3 pairs, switch seconds dropped)"
