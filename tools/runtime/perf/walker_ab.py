#!/usr/bin/env python3
"""walker_ab.py -- the same-run A/B of the GCM walker's switches (KZ2 patch 6067, KZ2_WALKER_TOGGLE=<s>; runtime 73).

  walker_ab.py LOG [LOG ...] [--from S] [--to S] [--md]

LOG holds RSX_PERF=1's per-second blocks ([perf] t=Ns ..., then [perf-walk], [perf-walk2], [perf-flush], [perf-gpu] of
the same second) and the toggle's switch lines `[walker-toggle] t=... phase=N on|off` (even N = off). A second whose
block has a switch line since the previous block is mixed and dropped (log order). --from/--to are in the [perf]
lines' own t (seconds). FPS uses the sum of each accepted block's wall milliseconds.
Every on-phase is paired with the mean of its off neighbours (N-1, N+1).
Phase contrasts share off neighbours and may be autocorrelated: all summaries are
DESCRIPTIVE, with no phase-level significance test. Each log contributes at most one
median phase contrast to the run summary. Separate log files do not establish
independent runs or comparable scenes; verify provenance and use inverted-order and
no-change controls before drawing performance conclusions.
"""
import argparse, re, statistics, sys
from collections import defaultdict

SW = re.compile(r"\[walker-toggle\] t=([\d.]+)s phase=(\d+) (on|off)")
PERF = re.compile(r"^\[perf\] t=(\d+)s wall=(\d+)ms flips=(\d+) .*?draws=(\d+).*?walk n=\d+ ([\d.]+)ms.*?gpuwait ([\d.]+)ms")
NUM = r"([\d.]+)"
FIELDS = {   # line tag: [(metric, regex)]
    "perf-walk": [("draw", r"draw " + NUM + "ms"), ("vtx", r"\(vtx " + NUM), ("pso", r", pso " + NUM),
                  ("const", r"const " + NUM), ("tex", r", tex " + NUM), ("tex-hash", r"tex-hash " + NUM),
                  ("pso key", r"key " + NUM), ("pso find", r"find " + NUM), ("gpuwait rb", r"gpuwait rb " + NUM),
                  ("cbv reuse n", r"reuse (\d+)")],
    "perf-walk2": [("meth", r"meth " + NUM + "ms"), ("texloop", r"texloop " + NUM), ("desc", r"desc " + NUM),
                   ("rec", r" rec " + NUM), ("post", r" post " + NUM)],
    "perf-flush": [("descring flush", r"descring \d+/" + NUM + "ms"), ("readback flush", r"readback \d+/" + NUM + "ms"),
                   ("wraps srv n", r"wraps srv (\d+)")],
    "perf-gpu": [("gpu busy", r"busy " + NUM)],
}
SUB = re.compile(r"^\[(perf-walk2|perf-walk|perf-flush|perf-gpu)\] t=(\d+)s")


def phases(path, lo, hi):
    """{phase: {metric: sum}} over accepted reporting blocks of one log."""
    acc = defaultdict(lambda: defaultdict(float))
    phase, switched, cur_t, cur_ok, cur_phase = None, False, None, False, None
    with open(path, errors="replace") as f:
        for ln in f:
            m = SW.search(ln)
            if m:
                phase = int(m[2]); switched = True
                continue
            m = PERF.search(ln)
            if m:
                cur_t = int(m[1])
                wall_ms = int(m[2])
                cur_ok = not switched and phase is not None and lo <= cur_t <= hi and wall_ms > 0
                switched = False
                cur_phase = phase
                if cur_ok:
                    a = acc[phase]
                    a["secs"] += wall_ms / 1000.0
                    a["blocks"] += 1; a["flips"] += int(m[3]); a["draws"] += int(m[4])
                    a["walk"] += float(m[5]); a["gpuwait"] += float(m[6])
                continue
            m = SUB.search(ln)
            if m and cur_ok and int(m[2]) == cur_t:
                for name, rx in FIELDS[m[1]]:
                    v = re.search(rx, ln)
                    if v: acc[cur_phase][name] += float(v[1])
    return acc


def per_frame(k):
    return lambda a: a[k] / a["flips"] if a["flips"] else None


METRICS = [("fps", lambda a: a["flips"] / a["secs"] if a["secs"] else None, False),
           ("draws/frame", per_frame("draws"), None),
           ("walk ms/frame", per_frame("walk"), True),
           ("draw ms/frame", per_frame("draw"), True),
           ("draw us/draw", lambda a: 1000 * a["draw"] / a["draws"] if a["draws"] else None, True),
           ("meth ms/frame", per_frame("meth"), True),
           ("meth-draw ms/frame", lambda a: (a["meth"] - a["draw"]) / a["flips"] if a["flips"] else None, True),
           ("gpuwait ms/frame", per_frame("gpuwait"), True)] + \
          [(f"{n} ms/frame", per_frame(n), True) for n in
           ("vtx", "pso", "pso key", "pso find", "const", "tex", "tex-hash", "texloop", "desc", "rec", "post",
            "descring flush", "readback flush", "gpu busy")] + \
          [("cbv reuse/frame", per_frame("cbv reuse n"), None), ("srv wraps/frame", per_frame("wraps srv n"), None)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--from", dest="lo", type=float, default=0)
    ap.add_argument("--to", dest="hi", type=float, default=1e9)
    ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    pooled = {False: defaultdict(float), True: defaultdict(float)}
    pairs = defaultdict(list)
    run_contrasts = defaultdict(list)
    for path in a.logs:
        acc = phases(path, a.lo, a.hi)
        for ph, s in acc.items():
            for k, v in s.items():
                pooled[bool(ph & 1)][k] += v
        run_pairs = defaultdict(list)
        for ph in sorted(acc):
            if not ph & 1 or (ph - 1) not in acc or (ph + 1) not in acc:
                continue
            for name, fn, low in METRICS:
                on, o1, o2 = fn(acc[ph]), fn(acc[ph - 1]), fn(acc[ph + 1])
                if None not in (on, o1, o2):
                    delta = on - (o1 + o2) / 2
                    pairs[name].append(delta)
                    run_pairs[name].append(delta)
        for name, contrasts in run_pairs.items():
            run_contrasts[name].append(statistics.median(contrasts))
    if not pooled[False]["secs"] or not pooled[True]["secs"]:
        print("walker_ab: no clean off and on seconds in the window"); return 1
    print("| metric | off | on | on-off | phase median | phases better | run median | runs better |\n|---|---|---|---|---|---|---|---|" if a.md else
          f"{'metric':24s} {'off':>8s} {'on':>8s} {'on-off':>8s} {'p.median':>9s} better  {'run median':>10s} runs better")
    for name, fn, low in METRICS:
        off, on = fn(pooled[False]), fn(pooled[True])
        d = pairs.get(name, [])
        if off is None or on is None:
            continue
        med = f"{statistics.median(d):+.2f}" if d else "n/a"
        better = sum(1 for x in d if (x < 0 if low else x > 0)) if low is not None else 0
        rd = run_contrasts.get(name, [])
        rmed = f"{statistics.median(rd):+.2f}" if rd else "n/a"
        rbetter = sum(1 for x in rd if (x < 0 if low else x > 0)) if low is not None else 0
        rcount = f"{rbetter}/{len(rd)}" if low is not None else "-"
        if a.md:
            print(f"| {name} | {off:.2f} | {on:.2f} | {on-off:+.2f} | {med} | "
                  f"{(str(better) + '/' + str(len(d))) if low is not None else '-'} | {rmed} | {rcount} |")
        else:
            print(f"{name:24s} {off:8.2f} {on:8.2f} {on-off:+8.2f} {med:>9s} "
                  f"{(str(better) + '/' + str(len(d))) if low is not None else '-':>6s} {rmed:>10s} {rcount:>11s}")
    print(f"clean seconds: off {pooled[False]['secs']:.6g}, on {pooled[True]['secs']:.6g}; pairs {len(pairs.get('fps', []))}")
    print("Descriptive only: phase contrasts share off neighbours; run medians give each log one contribution. "
          "No significance test; log count does not prove independent runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
