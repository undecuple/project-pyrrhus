#!/usr/bin/env python3
"""park_rank.py -- rank the SPU jobs behind the GCM walker's parks with patch 7014 on.

Reads the [ftr] lines of port/kz2/spu/kz2_frame_trace.c (KZ2_FRAME_TRACE=FROM,TO with KZ3_WAIT_ACCT) and patch
7013's park events (42 = walker stopped on a park, 43 = went past it, 47 = patch 7014's kick: a write changed the
park word, on the writer's thread). For every park of the walker (wacct kind 9 on rsx:frame):
  - the patch: the last 47 event inside the park, its thread, and the job call (kind 33, site & 0xFFFF = image id)
    running on that thread then (a PPU thread: no job);
  - per image id: the summed job-call time over the SPU kernel threads inside parks (SPU ms per park), the union of
    its calls inside parks (wall ms per park), calls per park, and its SPU ms per frame over the whole window.
For the patching calls: park start -> patch, the call's own length and how much of it ran before the park began.

  park_rank.py LOG [--manifest work/spu/spu/kz2_spu_manifest.json] [--top 12]
"""
import argparse, bisect, collections, json, os, re, sys

K_PARK, K_FLIP, K_JOBCALL, K_PBEGIN, K_PEND, K_KICK = 9, 32, 33, 42, 43, 47


def union(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def names(path):
    try:
        return {e["image_id"]: e.get("label", e["name"]) for e in json.load(open(path))}
    except (OSError, ValueError):
        return {}


def q(x):
    if not x:
        return "-"
    s = sorted(x)
    return f"p50 {s[len(s)//2]/1e3:.2f} mean {sum(s)/len(s)/1e3:.2f}"


def main():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--manifest", default=os.path.join(root, "work/spu/spu/kz2_spu_manifest.json"))
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    nm = names(a.manifest)
    thr, ev = {}, collections.defaultdict(list)
    rx = re.compile(r"\[ftr\] (\d+) (\d+) ([0-9A-F]+) (-?\d+) (\d+)")
    with open(a.log, errors="replace") as f:
        for ln in f:
            if "[ftr-thr]" in ln:
                p = ln.split("[ftr-thr]", 1)[1].split(None, 1)
                thr[int(p[0])] = p[1].strip() if len(p) > 1 else "?"
                continue
            m = rx.search(ln)
            if m:
                t, k, s, t0, d = int(m[1]), int(m[2]), int(m[3], 16), int(m[4]), int(m[5])
                if k in (K_PARK, K_FLIP, K_JOBCALL, K_PBEGIN, K_PEND, K_KICK):
                    ev[t].append((t0, t0 + d, k, s))
    walker = [i for i, n in thr.items() if n == "rsx:frame"]
    kern = sorted(i for i, n in thr.items() if re.match(r"spurs-kern\d+:$", n))
    if not walker or not kern:
        sys.exit(f"park_rank: walker {walker} kernels {kern} in {len(thr)} threads")
    w = walker[0]
    parks = sorted((t0, t1) for t0, t1, k, s in ev[w] if k == K_PARK)
    flips = sorted(t0 for i in ev for t0, t1, k, s in ev[i] if k == K_FLIP)
    allt = [e[0] for i in ev for e in ev[i]] + [e[1] for i in ev for e in ev[i]]
    span = (max(allt) - min(allt)) if allt else 0
    begins = sorted((t0, s) for t0, t1, k, s in ev[w] if k == K_PBEGIN)
    kicks = sorted((t0, i) for i in ev for t0, t1, k, s in ev[i] if k == K_KICK)
    kt = [k[0] for k in kicks]
    jc = {i: sorted((t0, t1, s & 0xFFFF) for t0, t1, k, s in ev[i] if k == K_JOBCALL) for i in ev}
    jcs = {i: [c[0] for c in v] for i, v in jc.items()}
    if not parks:
        sys.exit("park_rank: no parks")
    pl = sum(p1 - p0 for p0, p1 in parks)
    print(f"parks {len(parks)} in {span/1e3:.0f} ms, flips {len(flips)}, mean park {pl/len(parks)/1e3:.2f} ms,"
          f" park ms per frame {pl/max(1, len(flips))/1e3:.2f}, kicks {len(kicks)}")

    spu_in = collections.Counter(); wall_in = collections.Counter(); calls_in = collections.Counter()
    spu_all = collections.Counter(); calls_all = collections.Counter()
    for i in kern:
        for c0, c1, o in jc.get(i, []):
            spu_all[o] += c1 - c0; calls_all[o] += 1
    patched = collections.defaultdict(lambda: collections.defaultdict(list))
    nopatch = []
    ahead = collections.defaultdict(collections.Counter); span_ahead = collections.Counter(); lastend = collections.Counter(); gap = []
    for p0, p1 in parks:
        per = collections.defaultdict(list)
        for i in kern:
            v = jc.get(i, [])
            lo = bisect.bisect_left(jcs[i], p0 - 50_000)
            for c0, c1, o in v[lo:bisect.bisect_right(jcs[i], p1)]:
                ov = min(c1, p1) - max(c0, p0)
                if ov > 0:
                    spu_in[o] += ov; calls_in[o] += 1; per[o].append((max(c0, p0), min(c1, p1)))
        for o, iv in per.items():
            wall_in[o] += sum(b - a for a, b in union(iv))
        k0, k1 = bisect.bisect_left(kt, p0), bisect.bisect_right(kt, p1 + 50)
        if k1 <= k0:
            nopatch.append(p1 - p0)
            continue
        t, i = kicks[k1 - 1]
        io = [s for b, s in begins if b <= p0 + 50]
        site = io[-1] & 0xFFFF if io else -1
        v = jc.get(i, [])
        j = bisect.bisect_right(jcs.get(i, []), t) - 1
        if j >= 0 and v[j][0] <= t <= v[j][1] + 5:
            c0, c1, o = v[j]
            span_ahead[o] += max(0, c0 - p0) * len(kern)
            for i2 in kern:   # what ran on the kernels between the park start and the patching call
                v2 = jc.get(i2, [])
                lo = bisect.bisect_left(jcs[i2], p0 - 50_000)
                for d0, d1, o2 in v2[lo:bisect.bisect_right(jcs[i2], c0)]:
                    ov = min(d1, c0) - max(d0, p0)
                    if ov > 0 and (d0, i2) != (c0, i):
                        ahead[o][o2] += ov
            key = f"{nm.get(o, 'ovl%d' % o)} ({o})"
            g = patched[key]
            g["call"].append(c1 - c0); g["before"].append(max(0, p0 - c0)); g["last"].append(t - c0)
        else:
            key = f"{thr.get(i, '?').strip('? ') or 'PPU thread %d' % i} (no job)"
            g = patched[key]
            for i2 in kern:   # the SPU job calls that ended last before the PPU-side patch
                v2 = jc.get(i2, [])
                lo = bisect.bisect_left(jcs[i2], p0 - 50_000)
                ends = [(d1, o2) for d0, d1, o2 in v2[lo:bisect.bisect_right(jcs[i2], t)] if p0 <= d1 <= t]
                if ends:
                    lastend[max(ends)[1]] += 1
                    gap.append(t - max(ends)[0])
        g["len"].append(p1 - p0); g["wait"].append(t - p0); g["wake"].append(p1 - t)
        g["site"].append(site)
    n = len(parks); nf = max(1, len(flips))
    print("\nwho patched the park word (the last 7014 kick in the park):")
    for key, g in sorted(patched.items(), key=lambda kv: -sum(kv[1]["len"])):
        sites = collections.Counter(f"0x{s:04X}" for s in g["site"]).most_common(2)
        line = (f"  {key}: {len(g['len'])} parks, {sum(g['len'])/1e3:.1f} ms; park len {q(g['len'])};"
                f" start->patch {q(g['wait'])}; patch->unpark {q(g['wake'])}; io {sites}")
        if g.get("call"):
            line += (f"\n      patching call: len {q(g['call'])}, ran before the park {q(g['before'])},"
                     f" call start->patch {q(g['last'])} ms")
        print(line)
    for o, c in sorted(ahead.items(), key=lambda kv: -sum(kv[1].values())):
        np_ = len(patched[f"{nm.get(o, 'ovl%d' % o)} ({o})"]["len"])
        busy = sum(c.values()) / max(1, span_ahead[o]) * 100
        print(f"  before {nm.get(o, o)}'s patching call ({span_ahead[o]/len(kern)/np_/1e3:.2f} ms per park, kernels"
              f" {busy:.0f} % in job calls), SPU ms per park by image: "
              + ", ".join(f"{nm.get(x, x)} {v/np_/1e3:.2f}" for x, v in c.most_common(6)))
    if lastend:
        print(f"  PPU-patched parks: the SPU job that ended last before the patch (per kernel): {lastend.most_common(6)};"
              f" its end -> patch {q(gap)} ms")
    if nopatch:
        print(f"  no kick in the park: {len(nopatch)} parks, len {q(nopatch)} ms")
    print(f"\nper image, inside parks (per park, {n} parks) and over the window (per frame, {nf} flips):")
    print(f"  {'image':34s} {'wall/park':>9s} {'SPU/park':>9s} {'calls/park':>10s} {'SPU ms/f':>9s} {'calls/f':>8s} {'ms/call':>8s}")
    for o, _ in sorted(spu_in.items(), key=lambda kv: -kv[1])[:a.top]:
        print(f"  {nm.get(o, 'ovl%d' % o)[:28] + ' (%d)' % o:34s} {wall_in[o]/n/1e3:9.2f} {spu_in[o]/n/1e3:9.2f}"
              f" {calls_in[o]/n:10.1f} {spu_all[o]/nf/1e3:9.2f} {calls_all[o]/nf:8.1f}"
              f" {spu_all[o]/max(1, calls_all[o])/1e3:8.3f}")


if __name__ == "__main__":
    main()
