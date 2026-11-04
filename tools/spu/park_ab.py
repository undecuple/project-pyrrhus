#!/usr/bin/env python3
"""park_ab.py -- the same-run A/B of patch 7014 (KZ2_PARK_WATCH_TOGGLE=<s>): the GCM walker's park and wait time,
the SPU kernels' sleeps and the frame rate per phase.

  park_ab.py LOG [LOG ...] [--from S] [--to S] [--rel] [--md]

--rel: FROM and TO count from each log's control point (the first `AutoSave(` after the level's first user command
`[usercmd] HLE #1`, as tools/runtime/native_ab_drive.py waits for it), in wacct time; the frame plan route's heavy
view is the standing view after its third walk, about control + 60 s to the end of the run.

LOG holds patch 1032's `[wacct]` windows (KZ3_WAIT_ACCT=1000), RSX_PERF=1's per-second `[perf] t=` lines and the
toggle's `[park-watch] t=... phase=N on|off` switch lines (libs/video/cellGcmSys.c, patch 7014; even N = off), or
 a native gate toggle's `[native-toggle] ... phase=N native|lifted` (KZ2_NATIVE_TOGGLE; even N = lifted,
reported as off), or the switch toggle's `[ab-toggle] ... phase=N on|off` (KZ2_AB_TOGGLE,
port/kz2/spu/kz2_ab_toggle.c), with wacct windows of any length (KZ3_WAIT_ACCT=<ms>; window seconds from their headers). A
wacct window or perf line that has a switch line since the previous one is mixed and dropped (log order), as
tools/spu/toggle_ab.py does. Per clean window: flips, the walker's park time (`thr=rsx:frame ... park:0=MS/N`), the
HiPrio SPURS kernels' sleeps (`thr=spurs-kernK: ... ksleep=MS/N`, K = 0..4, the unnamed instance); per perf line:
the walker's fence waits (`gpuwait`), its between-pass sleeps (`usleep gcm`) and its walk time. Per phase the sums
give per-frame values; then every on-phase is paired with the mean of its off neighbours (N-1, N+1) and the median
difference, the count of on-phases that are lower and the two-sided sign-test p are printed per metric. Several logs
are pooled (each its own phases).
"""
import argparse, math, re, statistics, sys
from collections import defaultdict

HDR = re.compile(r"\[wacct\] ---- t=([\d.]+)s window=(\d+)ms flips=(\d+)")
SW = re.compile(r"\[(?:park-watch|native-toggle|ab-toggle)\] t=([\d.]+)s phase=(\d+) (on|off|native|lifted)")
PARK = re.compile(r"\[wacct\] thr=rsx:frame .*park:0=([\d.]+)ms/(\d+)")
KSL = re.compile(r"\[wacct\] thr=spurs-kern\d+: wait=\d+ms ksleep=(\d+)/(\d+)")
PERF = re.compile(r"\[perf\] t=(\d+)s wall=(\d+)ms flips=(\d+) .*?walk n=\d+ ([\d.]+)ms.*?gpuwait ([\d.]+)ms.*?usleep gcm n=\d+ ([\d.]+)ms")


def control_t(path):
    """wacct time of the first AutoSave( after the level's first user command, or None"""
    seen, t = False, None
    with open(path, errors="replace") as f:
        for ln in f:
            m = HDR.search(ln)
            if m: t = float(m[1]); continue
            if "[usercmd] HLE #1" in ln: seen = True
            elif seen and "AutoSave(" in ln: return t
    return None


def phases(path, lo, hi):
    """{phase: {metric: sum}} over the clean windows of one log"""
    acc = defaultdict(lambda: defaultdict(float))
    phase, sw_w, sw_p = None, False, False
    cur = None   # the open wacct window: [t, flips, park_ms, parks, ksleep_n, mixed, phase]

    def close():
        if cur and not cur[5] and cur[6] is not None and lo <= cur[0] <= hi:
            a = acc[cur[6]]
            a["w_secs"] += cur[7]; a["w_flips"] += cur[1]; a["park_ms"] += cur[2]; a["parks"] += cur[3]; a["ksleep"] += cur[4]
    with open(path, errors="replace") as f:
        for ln in f:
            m = SW.search(ln)
            if m:
                phase = int(m[2]); sw_w = sw_p = True
                continue
            m = HDR.search(ln)
            if m:
                close()
                cur = [float(m[1]), int(m[3]), 0.0, 0, 0, sw_w, phase, int(m[2]) / 1000.0]
                sw_w = False
                continue
            if cur:
                m = PARK.search(ln)
                if m: cur[2] += float(m[1]); cur[3] += int(m[2]); continue
                m = KSL.search(ln)
                if m: cur[4] += int(m[2]); continue
            m = PERF.search(ln)
            if m:
                t = int(m[1])
                if not sw_p and phase is not None and lo <= t <= hi:
                    a = acc[phase]
                    a["p_secs"] += 1; a["p_flips"] += int(m[3]); a["walk"] += float(m[4]); a["gpuwait"] += float(m[5])
                    a["usleep"] += float(m[6])
                sw_p = False
    close()
    return acc


METRICS = [  # name, function of a phase's sums, unit, lower is better
    ("fps", lambda a: a["w_flips"] / a["w_secs"] if a["w_secs"] else None, "", False),
    ("park ms/frame", lambda a: a["park_ms"] / a["w_flips"] if a["w_flips"] else None, "ms", True),
    ("parks/frame", lambda a: a["parks"] / a["w_flips"] if a["w_flips"] else None, "", True),
    ("ms per park", lambda a: a["park_ms"] / a["parks"] if a["parks"] else None, "ms", True),
    ("kernel sleeps/frame", lambda a: a["ksleep"] / a["w_flips"] if a["w_flips"] else None, "", True),
    ("walker fence wait ms/frame", lambda a: a["gpuwait"] / a["p_flips"] if a["p_flips"] else None, "ms", True),
    ("walker usleep ms/frame", lambda a: a["usleep"] / a["p_flips"] if a["p_flips"] else None, "ms", True),
    ("walk ms/frame", lambda a: a["walk"] / a["p_flips"] if a["p_flips"] else None, "ms", True),
    ("fps (perf)", lambda a: a["p_flips"] / a["p_secs"] if a["p_secs"] else None, "", False),
]


def sign_p(k, n):
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--from", dest="lo", type=float, default=0)
    ap.add_argument("--to", dest="hi", type=float, default=1e9)
    ap.add_argument("--rel", action="store_true")
    ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    pooled = {False: defaultdict(float), True: defaultdict(float)}
    pairs = defaultdict(list)
    for path in a.logs:
        lo, hi = a.lo, a.hi
        if a.rel:
            c = control_t(path)
            if c is None:
                print(f"{path}: no control point, skipped"); continue
            lo, hi = c + a.lo, c + a.hi
            print(f"{path.split('/')[-1]}: control at t={c:.1f} s, window {lo:.1f}-{hi:.1f}")
        acc = phases(path, lo, hi)
        for ph, s in acc.items():
            for k, v in s.items():
                pooled[bool(ph & 1)][k] += v
        for ph in sorted(acc):
            if not ph & 1 or (ph - 1) not in acc or (ph + 1) not in acc:
                continue
            for name, fn, unit, low in METRICS:
                on, o1, o2 = fn(acc[ph]), fn(acc[ph - 1]), fn(acc[ph + 1])
                if None in (on, o1, o2):
                    continue
                pairs[name].append(on - (o1 + o2) / 2)
    sep = " | " if a.md else "  "
    print(("| metric | off | on | on-off | paired median | on better | sign p |\n|---|---|---|---|---|---|---|") if a.md else
          f"{'metric':28s} {'off':>8s} {'on':>8s} {'on-off':>8s} {'pair med':>9s} {'better':>7s} {'p':>6s}")
    for name, fn, unit, low in METRICS:
        off, on = fn(pooled[False]), fn(pooled[True])
        if off is None or on is None:   # a metric with no samples in this log (e.g. no RSX_PERF lines)
            print(f"{name:28s} {'-':>8s} {'-':>8s}")
            continue
        d = pairs[name]
        better = sum(1 for x in d if (x < 0) == low and x != 0)
        p = sign_p(better, len(d))
        med = statistics.median(d) if d else float("nan")
        if a.md:
            print(f"| {name} | {off:.2f} | {on:.2f} | {on-off:+.2f} | {med:+.2f} | {better}/{len(d)} | {p:.3f} |")
        else:
            print(f"{name:28s} {off:8.2f} {on:8.2f} {on-off:+8.2f} {med:+9.2f} {better:3d}/{len(d):<3d} {p:6.3f}")
    print(f"clean wacct windows: off {pooled[False]['w_secs']:.0f}, on {pooled[True]['w_secs']:.0f}; perf seconds: off"
          f" {pooled[False]['p_secs']:.0f}, on {pooled[True]['p_secs']:.0f}")


if __name__ == "__main__":
    main()
