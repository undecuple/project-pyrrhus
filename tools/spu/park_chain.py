#!/usr/bin/env python3
"""park_chain.py -- the order of the SPU jobs inside the GCM walker's parks (diagnostic).

For every park of the walker patched by an SPU job (patch 7014's kick inside a job call, as tools/spu/park_rank.py),
grouped by the patching image: per image, when its first and last calls inside the park start and end (ms after the
park start, p50 over the parks), and how many kernels run it. A job that ends just before the patch and runs alone at
the end is on the park's tail; jobs that run beside it only take kernel time.

  park_chain.py LOG [--manifest work/spu/spu/kz2_spu_manifest.json] [--images 201,202,203,204,223]
"""
import argparse, bisect, collections, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from park_rank import K_PARK, K_JOBCALL, K_KICK, names  # noqa: E402


def p50(x):
    s = sorted(x)
    return s[len(s) // 2] / 1e3 if s else float("nan")


def main():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--manifest", default=os.path.join(root, "work/spu/spu/kz2_spu_manifest.json"))
    ap.add_argument("--images", default="201,202,203,204,205,223,224,220")
    a = ap.parse_args()
    nm = names(a.manifest)
    want = [int(x) for x in a.images.split(",")]
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
                if k in (K_PARK, K_JOBCALL, K_KICK):
                    ev[t].append((t0, t0 + d, k, s))
    w = [i for i, n in thr.items() if n == "rsx:frame"][0]
    kern = sorted(i for i, n in thr.items() if re.match(r"spurs-kern\d+:$", n))
    parks = sorted((t0, t1) for t0, t1, k, s in ev[w] if k == K_PARK)
    kicks = sorted((t0, i) for i in ev for t0, t1, k, s in ev[i] if k == K_KICK)
    kt = [k[0] for k in kicks]
    jc = {i: sorted((t0, t1, s & 0xFFFF) for t0, t1, k, s in ev[i] if k == K_JOBCALL) for i in ev}
    jcs = {i: [c[0] for c in v] for i, v in jc.items()}
    grp = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list)))
    tail = collections.defaultdict(collections.Counter)
    idle = collections.defaultdict(list)
    for p0, p1 in parks:
        k0, k1 = bisect.bisect_left(kt, p0), bisect.bisect_right(kt, p1 + 50)
        if k1 <= k0:
            continue
        t, i = kicks[k1 - 1]
        v = jc.get(i, [])
        j = bisect.bisect_right(jcs.get(i, []), t) - 1
        if not (j >= 0 and v[j][0] <= t <= v[j][1] + 5):
            continue
        po = v[j][2]
        g = grp[po]
        g["_"]["len"].append(p1 - p0)
        per = collections.defaultdict(list)
        busy = 0
        for i2 in kern:
            v2 = jc.get(i2, [])
            lo = bisect.bisect_left(jcs[i2], p0 - 50_000)
            for d0, d1, o2 in v2[lo:bisect.bisect_right(jcs[i2], t)]:
                if d1 > p0:
                    per[o2].append((max(d0, p0) - p0, min(d1, t) - p0, i2))
                    busy += min(d1, t) - max(d0, p0)
        idle[po].append(1 - busy / max(1, (t - p0) * len(kern)))
        for o2, iv in per.items():
            g[o2]["first"].append(min(x[0] for x in iv)); g[o2]["last"].append(max(x[1] for x in iv))
            g[o2]["spu"].append(sum(x[1] - x[0] for x in iv)); g[o2]["kern"].append(len({x[2] for x in iv}))
        for o2, iv in per.items():   # which images run in the last 20 % of the park before the patch
            cut = (t - p0) * 0.8
            tail[po][o2] += sum(max(0, x[1] - max(x[0], cut)) for x in iv)
    for po, g in sorted(grp.items(), key=lambda kv: -sum(kv[1]["_"]["len"])):
        n = len(g["_"]["len"])
        print(f"patched by {nm.get(po, po)} ({po}): {n} parks, len p50 {p50(g['_']['len']):.2f} ms, kernels idle"
              f" before the patch {sum(idle[po]) / n * 100:.0f} %")
        print(f"  {'image':30s} {'parks':>5s} {'first':>7s} {'last':>7s} {'SPU ms':>7s} {'kernels':>7s}  (ms after the park start, p50)")
        rows = [o for o in g if o != "_"]
        for o in sorted(rows, key=lambda o: -sum(g[o]["spu"]))[:10]:
            d = g[o]
            print(f"  {nm.get(o, 'ovl%d' % o)[:24] + ' (%d)' % o:30s} {len(d['first']):5d} {p50(d['first']):7.2f}"
                  f" {p50(d['last']):7.2f} {sum(d['spu']) / n / 1e3:7.2f} {sorted(d['kern'])[len(d['kern']) // 2]:7d}")
        tt = sum(tail[po].values()) or 1
        print("  last 20 % of the park, share of kernel time: " +
              ", ".join(f"{nm.get(o, o)} {v / tt * 100:.0f} %" for o, v in tail[po].most_common(5)))


if __name__ == "__main__":
    main()
