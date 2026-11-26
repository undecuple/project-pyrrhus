#!/usr/bin/env python3
"""Host test for firstrun.py's low-memory priority (from Project Vekta, MIT): under 8 GiB of free memory when the
build starts, every step runs at a lower priority (Windows BELOW_NORMAL_PRIORITY_CLASS 0x4000 next to
CREATE_NEW_PROCESS_GROUP, elsewhere nice 10); at 8 GiB or more, or when the free memory is unknown, the steps start
exactly as before. Runs one real step through the Runner on this host and reads its niceness back.
Exit 0 = PASS.

    python3 tools/release/test_build_priority.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402

fails = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


G = fr.GIB
check(fr.LOW_MEMORY == 8 * G and fr.BELOW_NORMAL_PRIORITY_CLASS == 0x4000, "8 GiB threshold, BELOW_NORMAL = 0x4000")
check(fr.low_memory(8 * G - 1) and fr.low_memory(2 * G), "under 8 GiB free: low")
check(not fr.low_memory(8 * G) and not fr.low_memory(64 * G), "8 GiB or more: unchanged")
check(not fr.low_memory(None) and not fr.low_memory(0), "free memory unknown: unchanged")
check(fr.priority_kw(False) == {} and fr.priority_kw(False, nt=True) == {}, "not low: no Popen arguments")
check(fr.priority_kw(True, nt=True) == {"creationflags": 0x4000}, "low on Windows: creationflags 0x4000")
kw = fr.priority_kw(True, nt=False)
check(set(kw) == {"preexec_fn"} and callable(kw["preexec_fn"]), "low elsewhere: a preexec_fn (nice 10)")


class Sink:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


def run_step(low):
    """One step that prints its own niceness, through Runner.run_cmd; -> the printed lines."""
    with tempfile.TemporaryDirectory() as t:
        ctx = fr.Ctx(root=t, build=os.path.join(t, "build"), low_priority=low)
        log = fr.Log(os.path.join(t, "fr.log"), lambda x: x)
        out = Sink()
        steps = [fr.Step("probe", "Probe", 1.0, lambda c: [])]
        r = fr.Runner(ctx, steps, log, out, None)
        rc, lines = r.run_cmd(0, [sys.executable, "-c", "import os; print('NICE', os.nice(0))"])
        log.f.close()
        return rc, lines


if os.name != "nt" and hasattr(os, "nice"):
    base = os.nice(0)
    try:
        rc0, l0 = run_step(False)
        rc1, l1 = run_step(True)
        n0 = next((int(x.split()[1]) for x in l0 if x.startswith("NICE")), None)
        n1 = next((int(x.split()[1]) for x in l1 if x.startswith("NICE")), None)
        check(rc0 == 0 and n0 == base, f"not low: the step runs at this process's niceness ({n0} = {base})")
        check(rc1 == 0 and n1 == min(19, base + 10), f"low: the step runs 10 lower ({n1} = {min(19, base + 10)})")
    except Exception as e:   # noqa: BLE001
        check(False, f"a real step through Runner.run_cmd ({type(e).__name__}: {e})")
else:
    print("skip the real-step check: no os.nice here")

src = open(os.path.join(HERE, "firstrun.py"), encoding="utf-8").read()
check("CREATE_NEW_PROCESS_GROUP | pk.get(\"creationflags\", 0)" in src, "Windows keeps CREATE_NEW_PROCESS_GROUP beside it")
check("low_priority=low_memory(avail)" in src, "main() decides it from the free memory at the start")
print("PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
