#!/usr/bin/env bash
# Host test (KZ2 patch 6085, KZ2_WALKER_POLL_US: the frame thread's sleep ends when the title's put has moved or the
# armed park word has changed): the wiring in the patched toolkit's libs/video/cellGcmSys.c and port/kz2/main.cpp, and
# the decision rule (gcm_walker_work_pending, compiled from the patched source's own text into a model) on its cases,
# with negative controls. No game data, no GPU.
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_walker_wait_poll.sh
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
g, m = open(sys.argv[1], encoding="utf-8", errors="replace").read(), open(sys.argv[2], encoding="utf-8", errors="replace").read()
bad = 0
def check(name, ok):
    global bad
    print(("PASS: " if ok else "[FAIL] ") + name); bad += not ok
def fn(src, sig):
    if sig not in src: return ""
    i = src.index(sig); j = src.index("\n}\n", i); return src[i:j]
pend = fn(g, "static int gcm_walker_work_pending(void)")
wait = fn(g, "int cellGcm_walker_wait(unsigned ms)")
drain = fn(g, "static void gcm_rsx_process_fifo_unlocked(void)" + chr(10) + "{")   # the definition, not its prototype
us = fn(g, "static int gcm_walker_poll_us(void)")
check("the pending rule exists", bool(pend))
check("the switch is off when KZ2_WALKER_POLL_US is unset or empty", "(e && *e) ? atoi(e) : -1" in us)
check("the drain records the put it starts from, right after it reads it",
      re.search(r"u32 put = vm_read32\(GCM_CONTROL_GUEST_ADDR \+ 0\);\s*__atomic_store_n\(&s_wp_seen_put, put, __ATOMIC_RELAXED\);", drain) is not None)
check("the poll is entered only with the switch on", "if (gcm_walker_poll_us() >= 0 && s_walker_wake) {" in wait)
if wait and "gcm_walker_poll_us() >= 0" in wait:
    poll = wait[wait.index("gcm_walker_poll_us() >= 0"):]
    off = wait[:wait.index("gcm_walker_poll_us() >= 0")]
    check("6082's acquire check still comes first", "s_acq_wait_la" not in g or "vm_read32(wla) ==" in off)
    check("the poll tests for work before it looks at the clock", poll.index("gcm_walker_work_pending()") < poll.index("t.QuadPart >= deadline"))
    check("a pending pass returns 2", re.search(r"if \(pend\) \{[^}]*return 2; \}", poll) is not None)
    check("the poll gives up at the deadline (returns 0)", "if (t.QuadPart >= deadline) return 0;" in poll)
    check("the wake event still ends the wait in both slice forms",
          "WaitForSingleObject(s_walker_wake, 0) == WAIT_OBJECT_0) return 1;" in poll and "WaitForMultipleObjects(2, h, FALSE, ms + 1) == WAIT_OBJECT_0) return 1;" in poll)
    check("the acquire label (6082) is checked each slice", "s_acq_wait_la" not in g or poll.count("vm_read32(wla) ==") >= 1)
    # the unchanged path after the poll block: the flat sleep and the event wait of 6038/6082
    check("with the switch off the wait is as before (flat Sleep, or the event)",
          re.search(r"Sleep\(ms\);\s*return 0;\s*\}\s*return WaitForSingleObject\(s_walker_wake, ms\) == WAIT_OBJECT_0;", wait) is not None)
else:
    check("the wait has the poll block", False)
check("the port prints [walker-poll] from the counters", "cellGcm_walker_poll_counts(&np, &nk);" in m and "[walker-poll]" in m)

# The decision rule, taken from the source text: put first, then the park word, else nothing.
rule = re.search(r"if \(vm_read32\(GCM_CONTROL_GUEST_ADDR \+ 0\) != __atomic_load_n\(&s_wp_seen_put, __ATOMIC_RELAXED\)\) return 1;\s*"
                 r"const u32 pe = __atomic_load_n\(&s_park_wake_ea, __ATOMIC_ACQUIRE\);\s*"
                 r"if \(pe && vm_read32\(pe\) != __atomic_load_n\(&s_park_watch_w, __ATOMIC_RELAXED\)\) return 2;\s*return 0;", pend)
check("the rule's text is the one modelled below", rule is not None)
def pending(put, seen, park_ea, park_word, watch_word):
    if put != seen: return 1
    if park_ea and park_word != watch_word: return 2
    return 0
JUMP_SELF, PATCHED = 0x20006580, 0x20006590
cases = [
  ("put unchanged, no park: sleep on", (0x100, 0x100, 0, 0, 0), 0),
  ("the title wrote more during the pass: run again", (0x140, 0x100, 0, 0, 0), 1),
  ("put wrapped to a lower offset: run again", (0x040, 0x7F00, 0, 0, 0), 1),
  ("parked, word unchanged: sleep on", (0x100, 0x100, 0x30006580, JUMP_SELF, JUMP_SELF), 0),
  ("parked, word patched: run again", (0x100, 0x100, 0x30006580, PATCHED, JUMP_SELF), 2),
  ("no park armed, a stale watch word differs: sleep on", (0x100, 0x100, 0, PATCHED, JUMP_SELF), 0),
  ("both moved: the put is reported", (0x140, 0x100, 0x30006580, PATCHED, JUMP_SELF), 1),
]
for name, args, want in cases:
    check(name, pending(*args) == want)
# negative controls: a rule without the put test, and one that ignores whether a park is armed, each fail a case
no_put = lambda put, seen, pe, w, ww: 2 if (pe and w != ww) else 0
no_arm = lambda put, seen, pe, w, ww: 1 if put != seen else (2 if w != ww else 0)
check("control: a rule without the put test misses the title's new commands", no_put(0x140, 0x100, 0, 0, 0) != 1)
check("control: a rule that ignores the arm wakes on a stale word", no_arm(0x100, 0x100, 0, PATCHED, JUMP_SELF) != 0)
sys.exit(1 if bad else 0)
PY
