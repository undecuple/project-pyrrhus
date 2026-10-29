#!/usr/bin/env bash
# Host test (KZ2 patch 6038, the frame thread woken by the SPU put that patches its FIFO park):
# the wiring in the patched toolkit's libs/video/cellGcmSys.c and port/kz2/main.cpp, and the park-overlap rule of
# the SPU write hook on its edge cases. No game data, no GPU.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_walker_park_wake.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched"
# python3, else python, else py -3: on Windows python3 is often the Microsoft Store alias (issue #9)
PY=()
for c in "python3" "python" "py -3"; do
  read -r -a cand <<<"$c"
  if "${cand[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)' >/dev/null 2>&1; then
    PY=("${cand[@]}"); break
  fi
done
(( ${#PY[@]} )) || { echo "FAIL: no Python 3.6 or newer (tried python3, python, py -3)"; exit 1; }
"${PY[@]}" - "$PT/libs/video/cellGcmSys.c" port/kz2/main.cpp <<'PY'
import re, sys
g, m = open(sys.argv[1]).read(), open(sys.argv[2]).read()
def fn(src, sig):
    i = src.index(sig); j = src.index("\n}\n", i); return src[i:j]
arm = fn(g, "static void gcm_park_wake_arm(u32 io, u32 w)")
hook = fn(g, "static void gcm_spu_note_pages_ea(uint32_t ea, uint32_t size)")
wait = fn(g, "int cellGcm_walker_wait(unsigned ms)")
fc = m[m.index("static DWORD WINAPI frame_clock(LPVOID)"):]
fc = fc[:fc.index("fired = 0;") if "fired = 0;" in fc else fc.index("int fired")]
checks = [
  ("both park-wait stops arm the wake", len(re.findall(r'why = "park-wait"; s_park_pass = 1;\s*gcm_park_wake_arm\(s_fifo_getoff, w\); break;', g)) == 2),
  ("passing the park disarms", re.search(r"s_park_off = 0xFFFFFFFFu;\s*__atomic_store_n\(&s_park_wake_ea, 0u, __ATOMIC_RELEASE\);\s*/\* patch 6038: past the park \*/", g) is not None),
  ("giving up on the park disarms", "/* patch 6038: given up on */" in g),
  ("arm publishes the EA (seq_cst) before it re-reads the word", arm.index("__ATOMIC_SEQ_CST") < arm.index("vm_read32(ea) != w") and "gcm_walker_kick()" in arm),
  ("the SPU put hook fences, then checks the park EA and kicks", hook.index("__atomic_thread_fence(__ATOMIC_SEQ_CST)") < hook.index("s_park_wake_ea") < hook.index("gcm_walker_kick()")),
  ("the put check runs before the page notes", hook.index("gcm_walker_kick()") < hook.index("cellGcm_note_guest_write_pages_ea")),
  ("the wait sleeps when unarmed or KZ2_PARK_WAKE=0", re.search(r"!gcm_park_wake_on\(\) \|\| !__atomic_load_n\(&s_park_wake_ea, __ATOMIC_ACQUIRE\)\) \{\s*Sleep\(ms\);", wait) is not None),
  ("the wait is on the auto-reset event otherwise", "WaitForSingleObject(s_walker_wake, ms)" in wait and "CreateEventA(NULL, FALSE, FALSE, NULL)" in wait),
  ("frame_clock sleeps through cellGcm_walker_wait(4), no bare Sleep(4)", "cellGcm_walker_wait(4);" in fc and "Sleep(4)" not in fc),
]
bad = 0
for name, ok in checks:
    print(("PASS: " if ok else "[FAIL] ") + name); bad += not ok
# the hook's overlap rule, (u32)(ea - pe) < 4 || (u32)(pe - ea) < size: the put [ea, ea + size) meets the park word [pe, pe + 4)
expr = re.search(r"if \(pe && \(\(u32\)\(ea - pe\) < 4u \|\| \(u32\)\(pe - ea\) < size\)\) gcm_walker_kick\(\);", hook)
print(("PASS: " if expr else "[FAIL] ") + "overlap expression present"); bad += not expr
M = 0xFFFFFFFF
def hit(pe, ea, size): return pe != 0 and (((ea - pe) & M) < 4 or ((pe - ea) & M) < size)
cases = [((0x1000, 0x1000, 4), True), ((0x1000, 0x0F80, 0x100), True), ((0x1000, 0x1004, 4), False),
         ((0x1000, 0x0FFC, 4), False), ((0x1000, 0x0FFE, 4), True), ((0x1000, 0x1003, 1), True), ((0x1000, 0x0FFE, 2), False), ((0, 0, 16), False)]
for (pe, ea, size), want in cases:
    ok = hit(pe, ea, size) == want
    print(("PASS: " if ok else "[FAIL] ") + f"park 0x{pe:X}, put 0x{ea:X}+{size}: {'wake' if want else 'no wake'}"); bad += not ok
sys.exit(1 if bad else 0)
PY
