#!/usr/bin/env python3
"""Host test for tools/spu/ab_phase_logs.py and park_ab.py's `[ab-toggle]` switch lines: a synthetic log
with two off and two on phases, a mixed wacct window and a mixed perf second after each switch, must keep only the
clean windows of each phase, and park_ab must read the same phases."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ab_phase_logs, park_ab

def win(t, flips, park):
    return [f"[wacct] ---- t={t:.1f}s window=1000ms flips={flips}\n",
            f"[wacct] thr=rsx:frame wait=10ms | park:0={park:.1f}ms/{flips}\n"]

def perf(t, flips):
    return [f"[perf] t={t}s wall=1000ms flips={flips} fifo-flips=0 presents={flips} draws=1 | walk n=1 5.0ms methods=1 | "
            f"flush n=1 (present 1, ref 0, other 0) 1.0ms gpuwait 2.0ms | present 0.0ms usleep gcm n=1 3.0ms\n",
            f"[perf-walk] t={t}s draw 1.0ms\n"]

L = []
t = 0
for ph in range(4):
    L.append(f"[ab-toggle] t={t + 0.5:.3f}s phase={ph} {'on' if ph & 1 else 'off'} post_wb_skipped=0\n")
    for k in range(3):   # the first window and second after the switch are mixed
        t += 1
        flips = 30 if ph & 1 else 20
        L += win(t, flips, 50.0 if ph & 1 else 100.0) + perf(t, flips)
with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
    f.writelines(L)
out, kept = ab_phase_logs.split(L)
ok = True
def check(c, msg):
    global ok
    print(("PASS " if c else "FAIL ") + msg)
    ok &= bool(c)
check(kept["on"] == [4, 4] and kept["off"] == [4, 4], f"2 clean windows and perf seconds per phase kept (got {kept})")
check(all("flips=30" in ln for ln in out["on"] if ln.startswith("[wacct] ----")), "on log holds only on windows")
check(all("flips=20" in ln for ln in out["off"] if ln.startswith("[wacct] ----")), "off log holds only off windows")
check(sum(ln.startswith("[perf-walk]") for ln in out["on"]) == 4, "perf rows follow their kept second")
check(sum(ln.startswith("[wacct] thr=") for ln in out["off"]) == 4, "wacct rows follow their kept window")
acc = park_ab.phases(f.name, 0, 1e9)
os.unlink(f.name)
check(sorted(acc) == [0, 1, 2, 3], f"park_ab reads the [ab-toggle] phases (got {sorted(acc)})")
check(abs(acc[1]["park_ms"] / acc[1]["w_flips"] - 50 / 30) < 1e-9, "park_ab: on phase park ms/frame")
print("test_ab_phase:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
