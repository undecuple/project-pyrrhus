#!/usr/bin/env python3
"""ab_phase_logs.py -- split a same-run toggle log into its clean on and off phases.

  ab_phase_logs.py LOG OUT_PREFIX [--from S] [--to S]

LOG has switch lines (`[ab-toggle] t=... phase=N on|off`, port/kz2/spu/kz2_ab_toggle.c; also 7014's `[park-watch]`
and the native gates' `[native-toggle]`, even N = off), patch 1032's `[wacct]` windows (KZ3_WAIT_ACCT=1000) and
RSX_PERF=1's per-second `[perf...]` lines. Writes OUT_PREFIX.on.txt and OUT_PREFIX.off.txt, each holding only the wacct
windows and perf seconds that ran wholly in one phase, so tools/runtime/perf/frame_split.py gives that phase's ms per
frame. As tools/spu/park_ab.py: a wacct window (its `---- t=` header is printed at the window's end, its rows follow)
or a perf second (`[perf] t=`, then its `[perf-*]` rows) with a switch line since the previous one is mixed and
dropped. --from/--to select by the wacct header's t and the perf line's t. Prints the kept windows per phase.
"""
import argparse
import re
import sys

SW = re.compile(r"\[(?:ab-toggle|park-watch|native-toggle)\] t=([\d.]+)s phase=(\d+) (on|off|native|lifted)")
HDR = re.compile(r"^\[wacct\] ---- t=([\d.]+)s")
PERF = re.compile(r"^\[perf\] t=(\d+)s")


def split(lines, lo=0.0, hi=1e9):
    """{'on': [lines], 'off': [lines]}, and {'on': (wacct windows, perf seconds), 'off': ...}"""
    out = {"on": [], "off": []}
    kept = {"on": [0, 0], "off": [0, 0]}
    phase = None
    sw_w = sw_p = False
    wsink = psink = None
    for ln in lines:
        m = SW.search(ln)
        if m:
            phase = "on" if int(m[2]) & 1 else "off"
            sw_w = sw_p = True
            wsink = psink = None
            continue
        m = HDR.search(ln)
        if m:
            wsink = None
            if not sw_w and phase and lo <= float(m[1]) <= hi:
                wsink = phase
                kept[phase][0] += 1
            sw_w = False
            if wsink: out[wsink].append(ln)
            continue
        if ln.startswith("[wacct] "):
            if wsink: out[wsink].append(ln)
            continue
        m = PERF.search(ln)
        if m:
            psink = None
            if not sw_p and phase and lo <= int(m[1]) <= hi:
                psink = phase
                kept[phase][1] += 1
            sw_p = False
            if psink: out[psink].append(ln)
            continue
        if ln.startswith("[perf-"):
            if psink: out[psink].append(ln)
    return out, kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("prefix")
    ap.add_argument("--from", dest="lo", type=float, default=0.0)
    ap.add_argument("--to", dest="hi", type=float, default=1e9)
    a = ap.parse_args()
    with open(a.log, errors="replace") as f:
        out, kept = split(f, a.lo, a.hi)
    for ph in ("on", "off"):
        with open(f"{a.prefix}.{ph}.txt", "w") as f:
            f.writelines(out[ph])
        print(f"{ph}: {kept[ph][0]} wacct windows, {kept[ph][1]} perf seconds -> {a.prefix}.{ph}.txt")
    if not kept["on"][0] or not kept["off"][0]:
        print("ab_phase_logs: a phase has no clean wacct window", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
