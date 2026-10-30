#!/usr/bin/env python3
"""Same-run A/B of native gates: the per-phase SPU time of a run with KZ2_NATIVE_TOGGLE.

  tools/spu/toggle_ab.py LOG [--from S] [--to S] [--ovl 224,201] [--manifest ...] [--md]

LOG holds patch 1032's `[wacct]` windows (KZ3_WAIT_ACCT=1, KZ2_WACCT_TOPN=40 so small jobs are listed) and the
toggle's `[native-toggle] ... phase=N` switch lines (port/kz2/spu/native_toggle.h; even N = lifted, odd = native).
A wacct header `t=T` opens the report of the window that ended at T; a switch line printed after header k (before
k+1) happened inside window k+1, so window k+1 is mixed and dropped. Every other window belongs to one phase.

Per phase and job (`job:ovlN` sites of the spurs-kern threads): SPU-ms per frame, module loads per frame and ms per
load. Then per job the paired comparison: every native phase (odd N) against the mean of its lifted neighbours (N-1,
N+1) in ms per load, the median of those differences, how many native phases were lower and the two-sided sign-test
p. The pairing takes the scene drift out: neighbours are seconds apart.
"""
import argparse
import json
import math
import os
import re
import statistics
from collections import defaultdict

HDR = re.compile(r"\[wacct\] ---- t=([\d.]+)s window=(\d+)ms flips=(\d+)")
THR = re.compile(r"\[wacct\] thr=(\S+) wait=(\d+)ms(.*?) \|(.*)$")
SITE = re.compile(r" (\w+):(\S+?)=([\d.]+)ms/(\d+)")
TOG = re.compile(r"\[native-toggle\] t=([\d.]+)s phase=(\d+) ")


def names(path):
    try:
        return {e["image_id"]: e.get("label", e["name"]) for e in json.load(open(path))}
    except (OSError, ValueError):
        return {}


def windows(log):
    """[(t, secs, flips, phase, mixed, {ovl: [ms, loads]}, pmrun_ms)] in log order; phase None before the toggle."""
    out = []
    phase, switched = None, False
    cur = None
    with open(log, errors="replace") as f:
        for line in f:
            if "[native-toggle]" in line:
                m = TOG.search(line)
                if m:
                    first = phase is None
                    phase = int(m.group(2))
                    if not first:
                        switched = True
                continue
            if "[wacct]" not in line:
                continue
            m = HDR.search(line)
            if m:
                cur = [float(m.group(1)), int(m.group(2)) / 1000.0, int(m.group(3)), phase, switched,
                       defaultdict(lambda: [0.0, 0]), 0.0]
                switched = False
                out.append(cur)
                continue
            m = THR.search(line)
            if not m or cur is None or not m.group(1).startswith("spurs-kern"):
                continue
            for k, s, ms, n in SITE.findall(" " + m.group(4)):
                if k == "job" and s.startswith("ovl"):
                    e = cur[5][int(s[3:])]
                    e[0] += float(ms)
                    e[1] += int(n)
                elif k == "pmrun":
                    cur[6] += float(ms)
    return out


def sign_p(k, n):
    """Two-sided binomial sign test, p = 0.5."""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--to", dest="t1", type=float, default=1e12)
    ap.add_argument("--ovl", default="224,201", help="jobs (image ids) to compare")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--manifest", default=os.path.join(root, "work/spu/spu/kz2_spu_manifest.json"))
    ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    nm = names(a.manifest)
    ovls = [int(x) for x in a.ovl.split(",") if x]
    ws = [w for w in windows(a.log) if a.t0 <= w[0] <= a.t1 and w[3] is not None]
    pure = [w for w in ws if not w[4] and w[2] > 0]
    if not pure:
        print("no toggled wacct windows with flips in range")
        return 1
    side = {0: defaultdict(float), 1: defaultdict(float)}       # parity -> totals
    blk = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))    # phase -> ovl -> [ms, loads]
    nblk = defaultdict(int)
    for t, secs, flips, ph, _, jobs, pm in pure:
        s = side[ph & 1]
        s["win"] += 1
        s["secs"] += secs
        s["flips"] += flips
        s["pm"] += pm
        nblk[ph] += 1
        for o in ovls:
            ms, n = jobs.get(o, (0.0, 0))
            s[("ms", o)] += ms
            s[("n", o)] += n
            blk[ph][o][0] += ms
            blk[ph][o][1] += n
    print(f"{a.log}: window {a.t0:g}-{a.t1:g} s, {len(ws)} toggled windows, {len(ws) - len(pure)} dropped (switch "
          f"inside or no flips), phases {min(nblk)}-{max(nblk)}")
    for p, lab in ((0, "lifted"), (1, "native")):
        s = side[p]
        if not s["flips"]:
            continue
        print(f"  {lab}: {s['win']:.0f} windows, {s['flips'] / s['secs']:.2f} fps, policy module "
              f"{s['pm'] / s['flips']:.1f} SPU-ms/f")
    if a.md:
        print("| img | job | lifted SPU-ms/f | native SPU-ms/f | lifted ms/load | native ms/load | native/lifted "
              "| paired phases | native lower | median diff ms/load | sign p |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
    for o in ovls:
        r = []
        for p in (0, 1):
            s = side[p]
            ms, n = s[("ms", o)], s[("n", o)]
            r.append((ms / s["flips"] if s["flips"] else 0.0, ms / n if n else 0.0))
        diffs = []
        for ph in sorted(blk):
            if not ph & 1 or not blk[ph][o][1]:
                continue
            nb = [blk[q][o][0] / blk[q][o][1] for q in (ph - 1, ph + 1) if q in blk and blk[q][o][1]]
            if nb:
                diffs.append(blk[ph][o][0] / blk[ph][o][1] - sum(nb) / len(nb))
        k = sum(1 for d in diffs if d < 0)
        med = statistics.median(diffs) if diffs else 0.0
        ratio = r[1][1] / r[0][1] if r[0][1] else 0.0
        p = sign_p(k, len(diffs))
        name = nm.get(o, "?")
        if a.md:
            print(f"| {o} | {name} | {r[0][0]:.3f} | {r[1][0]:.3f} | {r[0][1]:.4f} | {r[1][1]:.4f} | {ratio:.3f} "
                  f"| {len(diffs)} | {k} | {med:+.4f} | {p:.3g} |")
        else:
            print(f"  {o:4d} {name[:28]:28s} SPU-ms/f {r[0][0]:6.3f} -> {r[1][0]:6.3f}  ms/load {r[0][1]:.4f} -> "
                  f"{r[1][1]:.4f} (x{ratio:.3f})  paired {len(diffs)}: native lower {k}, median {med:+.4f}, "
                  f"sign p {p:.3g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
