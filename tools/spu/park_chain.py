#!/usr/bin/env python3
"""park_chain.py -- the order of the SPU jobs inside the GCM walker's parks (diagnostic).

For every park of the walker patched by an SPU job (patch 7014's kick inside a job call, as tools/spu/park_rank.py),
grouped by the patching image: per image, when its first and last calls inside the park start and end (ms after the
park start, p50 over the parks), and how many kernels run it. A job that ends just before the patch and runs alone at
the end is on the park's tail; jobs that run beside it only take kernel time.

Also reports observed park -> patching-call -> kick -> unpark stages, including
non-SPU writers and unattributed parks. Workload ready-count changes are sampled
proxies, not job-specific submission events. Job brackets measure elapsed time,
not CPU service time; an unsampled head cannot be classified as producer delay
or scheduler/wake latency. Kernel utilization means time inside job brackets.

  park_chain.py LOG [--manifest work/spu/spu/kz2_spu_manifest.json] [--images 201,202,203,204,223]
"""
import argparse, bisect, collections, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from park_rank import K_PARK, K_JOBCALL, K_KICK, names, union  # noqa: E402

K_POLICY, K_INST = 5, 40


def overlap_index(calls):
    """Index sorted call starts and monotonic prefix-max ends once per thread."""
    starts, max_ends = [], []
    for a, b, image in calls:
        starts.append(a)
        max_ends.append(max(b, max_ends[-1]) if max_ends else b)
    return starts, max_ends


def overlaps(calls, start, end, index=None):
    """Yield clipped positive overlaps, including arbitrarily old active calls."""
    if end <= start:
        return
    if index is None:
        lo, hi = 0, len(calls)
    else:
        starts, max_ends = index
        # Prefix maxima are monotonic even when calls are nested. Every earlier
        # call ends <= start; every later call starts >= end. No time cutoff.
        lo = bisect.bisect_right(max_ends, start)
        hi = bisect.bisect_left(starts, end)
    for i in range(lo, hi):
        a, b, image = calls[i]
        if a >= end:
            break
        lo, hi = max(a, start), min(b, end)
        if hi > lo:
            yield lo, hi, image


def workload_observation(samples, wid, park_start, call_start):
    """Sampled workload readiness proxy, never a job-specific enqueue time.

    Kind 40 is emitted on changes, so an unchanged positive sample before the
    park still matters. A first positive sample without a preceding zero does
    not establish a transition. Multiple samplers cannot be joined safely.
    """
    before = [(t, ready) for t, w, ready in samples if w == wid and t <= park_start]
    after = [(t, ready) for t, w, ready in samples if w == wid and park_start < t <= call_start]
    if before and before[-1][1] > 0:
        return "positive at park start", None
    last_zero = before[-1][0] if before and before[-1][1] == 0 else None
    for t, ready in after:
        if ready == 0:
            last_zero = t
        elif last_zero is not None:
            return "observed zero-to-positive", (max(park_start, last_zero), t)
        else:
            return "positive, transition unknown", None
    return "no positive observation", None


def dependencies(thr, ev):
    """Return park records and coverage; last kick is a proxy, not causality."""
    walkers = [i for i, n in thr.items() if n == "rsx:frame"]
    kernels = {i for i, n in thr.items() if re.fullmatch(r"spurs-kern\d+:", n)}
    if len(walkers) != 1 or not kernels:
        raise ValueError(f"expected one walker and kernels; walkers={walkers}, kernels={sorted(kernels)}")
    parks = sorted((a, b) for a, b, k, s in ev.get(walkers[0], []) if k == K_PARK)
    kicks = sorted((a, i) for i, entries in ev.items() for a, b, k, s in entries if k == K_KICK)
    kt = [t for t, i in kicks]
    calls = {i: sorted((a, b, s & 0xFFFF) for a, b, k, s in entries if k == K_JOBCALL)
             for i, entries in ev.items()}
    starts = {i: [a for a, b, s in entries] for i, entries in calls.items()}
    indexes = {i: overlap_index(entries) for i, entries in calls.items()}
    samplers = [i for i, n in thr.items() if n.startswith("ftr-inst")]
    samples = sorted((a, s >> 16, (s >> 8) & 255)
                     for i in samplers for a, b, k, s in ev.get(i, []) if k == K_INST)
    records, coverage = [], collections.Counter(parks=len(parks))
    for p0, p1 in parks:
        # Never borrow a kick after this park: it may belong to the next one.
        lo, hi = bisect.bisect_left(kt, p0), bisect.bisect_right(kt, p1)
        if hi <= lo:
            coverage["no kick"] += 1
            continue
        t, writer = kicks[hi - 1]
        v = calls.get(writer, [])
        j = bisect.bisect_right(starts.get(writer, []), t) - 1
        call = v[j] if writer in kernels and j >= 0 and v[j][0] <= t <= v[j][1] else None
        r = dict(start=p0, end=p1, kick=t, writer=writer, call=call,
                 image=call[2] if call else None, readiness="unknown", transition=None,
                 policy_start=None, pre_call_busy=None)
        if call:
            c0, c1, image = call
            runs = [(a, b, s) for a, b, k, s in ev.get(writer, [])
                    if k == K_POLICY and a <= c0 < b]
            if len(runs) == 1:
                a, b, wid = runs[0]
                r["policy_start"] = a
                if len(samplers) == 1:
                    r["readiness"], r["transition"] = workload_observation(samples, wid, p0, c0)
            head_end = min(c0, t)
            if head_end > p0:
                busy = sum(sum(b - a for a, b in union([(a, b) for a, b, image in
                           overlaps(calls.get(i, []), p0, head_end, indexes.get(i))])) for i in kernels)
                r["pre_call_busy"] = busy / ((head_end - p0) * len(kernels))
            coverage["SPU job writer"] += 1
        else:
            coverage["writer without SPU job"] += 1
        records.append(r)
    return records, coverage


def report_dependencies(thr, ev, nm):
    records, coverage = dependencies(thr, ev)
    print("dependency coverage: " + ", ".join(f"{key}={value}" for key, value in coverage.items()))
    print("  Last in-park kick is an attribution proxy. Trace has no job-specific enqueue event;"
          " ready-count samples are workload-wide. Unobserved time is not proven wake delay.")
    grouped = collections.defaultdict(list)
    for r in records:
        key = f"{nm.get(r['image'], r['image'])} ({r['image']})" if r['call'] else \
              f"{thr.get(r['writer'], '?')} (no SPU job)"
        grouped[key].append(r)
    for key, rows in sorted(grouped.items(), key=lambda kv: -sum(r['end'] - r['start'] for r in kv[1])):
        print(f"  {key}: {len(rows)} parks; kick->unpark p50 "
              f"{p50([r['end'] - r['kick'] for r in rows]):.3f} ms")
        jobs = [r for r in rows if r['call']]
        if not jobs:
            continue
        print(f"    park->patching-call p50 {p50([max(0, r['call'][0] - r['start']) for r in jobs]):.3f} ms; "
              f"call-in-park->kick p50 {p50([r['kick'] - max(r['start'], r['call'][0]) for r in jobs]):.3f} ms")
        busy = [r['pre_call_busy'] for r in jobs if r['pre_call_busy'] is not None]
        if busy:
            print(f"    kernels in job calls before patching call: mean {100 * sum(busy) / len(busy):.1f}% (n={len(busy)})")
        print("    workload readiness proxy: " + ", ".join(f"{k}={v}" for k, v in
              collections.Counter(r['readiness'] for r in jobs).items()))
        transitions = [r for r in jobs if r['transition']]
        if transitions:
            print(f"    observed zero->positive upper bound after park p50 "
                  f"{p50([r['transition'][1] - r['start'] for r in transitions]):.3f} ms; "
                  f"sampling bracket p50 {p50([r['transition'][1] - r['transition'][0] for r in transitions]):.3f} ms "
                  f"(n={len(transitions)}; not exact submission time)")
    return records


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
                if k in (K_PARK, K_JOBCALL, K_KICK, K_POLICY, K_INST):
                    ev[t].append((t0, t0 + d, k, s))
    try:
        report_dependencies(thr, ev, nm)
    except ValueError as exc:
        ap.error(str(exc))
    w = [i for i, n in thr.items() if n == "rsx:frame"][0]
    kern = sorted(i for i, n in thr.items() if re.match(r"spurs-kern\d+:$", n))
    parks = sorted((t0, t1) for t0, t1, k, s in ev[w] if k == K_PARK)
    kicks = sorted((t0, i) for i in ev for t0, t1, k, s in ev[i] if k == K_KICK)
    kt = [k[0] for k in kicks]
    jc = {i: sorted((t0, t1, s & 0xFFFF) for t0, t1, k, s in ev[i] if k == K_JOBCALL) for i in ev}
    jcs = {i: [c[0] for c in v] for i, v in jc.items()}
    indexes = {i: overlap_index(v) for i, v in jc.items()}
    grp = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list)))
    tail = collections.defaultdict(collections.Counter)
    idle = collections.defaultdict(list)
    for p0, p1 in parks:
        k0, k1 = bisect.bisect_left(kt, p0), bisect.bisect_right(kt, p1)
        if k1 <= k0:
            continue
        t, i = kicks[k1 - 1]
        v = jc.get(i, [])
        j = bisect.bisect_right(jcs.get(i, []), t) - 1
        if not (i in kern and j >= 0 and v[j][0] <= t <= v[j][1]):
            continue
        po = v[j][2]
        g = grp[po]
        g["_"]["len"].append(p1 - p0)
        per = collections.defaultdict(list)
        busy = 0
        for i2 in kern:
            v2 = jc.get(i2, [])
            intervals = []
            for d0, d1, o2 in overlaps(v2, p0, t, indexes.get(i2)):
                per[o2].append((d0 - p0, d1 - p0, i2))
                intervals.append((d0, d1))
            busy += sum(b - a for a, b in union(intervals))
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
        rows = [o for o in g if o != "_" and o in want]
        for o in sorted(rows, key=lambda o: -sum(g[o]["spu"]))[:10]:
            d = g[o]
            print(f"  {nm.get(o, 'ovl%d' % o)[:24] + ' (%d)' % o:30s} {len(d['first']):5d} {p50(d['first']):7.2f}"
                  f" {p50(d['last']):7.2f} {sum(d['spu']) / n / 1e3:7.2f} {sorted(d['kern'])[len(d['kern']) // 2]:7d}")
        tt = sum(tail[po].values()) or 1
        print("  last 20 % of the park, share of kernel time: " +
              ", ".join(f"{nm.get(o, o)} {v / tt * 100:.0f} %" for o, v in tail[po].most_common(5)))


if __name__ == "__main__":
    main()
