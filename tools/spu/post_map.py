#!/usr/bin/env python3
"""post_map.py LOG [--bin FILE] [--frames N] [--json OUT] -- read KZ2_POST_MAP's [pmap] lines (port/kz2/spu/kz2_post_map.c) and print the SPU post chain's data flow:

  1. the post jobs (WWS job calls of images 206-222) per frame and their DMA: merged GET and PUT ranges per image;
  2. per input page (post GETs of >= 512 bytes): who wrote it last before the GET (walker write-back of a GPU
     surface, a post job's PUT, another SPU image's PUT, a store by a thread without a hook seen by the watch, or
     nobody in the window);
  3. per output page (post PUTs of >= 512 bytes): who read it after the PUT, until the next write: post GETs
     (chain-internal), other SPU images' GETs, walker texture binds, watch faults by threads without a hook (a CPU
     reader) or by the walker outside a bind;
  4. the sync timeline of a few frames: user commands, guest sync points, write-backs, the first/last post job, parks.

The DMA events exist only in the sampled frame pairs (KZ2_POST_MAP_EVERY): the page analysis (2, 3) runs per sampled
window (consecutive frames that have DMA events), each from a clean state; --bin reads KZ2_POST_MAP_OUT's binary file
(the thread lines still come from LOG).

Kinds (kz2_post_map.c): 1 GET, 2 PUT, 10 first GPU write, 11 write-back, 12 texture bind, 13 flip, 14 sync point,
20+k patch 1085 kind k (32 flip, 33 job call, 34/35 user command queued/delivered, 3 label wait, 41-44 park), 90 fault.
"""
import argparse, bisect, collections, json, re, struct, sys

POST = {206: 'Zero', 207: 'GrainWeight', 208: 'Downsample', 209: 'Upsample', 210: 'Add', 211: 'Modulate', 212: 'Blend',
        213: 'HBlur', 214: 'VBlur', 215: 'BloomCapture', 216: 'BloomIntegrate', 217: 'ILR', 218: 'Vignette',
        219: 'MotionBlur', 220: 'DepthOfField', 221: 'DepthToFuzzy', 222: 'Unlock'}
MIN = 128
WT = 20


def load(path, binf=None):
    thr, ev = {}, []
    rx = re.compile(r'\[pmap\] (\d+) (\d+) (\d+) ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+) ([0-9a-f]+)')
    rt = re.compile(r'\[pmap-thr\] (\d+) (\d+) wacct=(\S+) ppu=(\S+) hook=(\d+)')
    with open(path, errors='replace') as f:
        for line in f:
            if '[pmap' not in line:
                continue
            m = rx.search(line)
            if m and not binf:
                ev.append((int(m[2]), int(m[1]), int(m[3])) + tuple(int(m[i], 16) for i in range(4, 9)))
                continue
            m = rt.search(line)
            if m:
                n = m[3] if m[3] != '-' else ('ppu:' + m[4]) if m[4] != '-' else '-'
                thr[int(m[1])] = (n, int(m[5]))
    if binf:
        with open(binf, 'rb') as f:
            h = f.read(64)
            if h[:8] != b'KZ2PMAP1':
                sys.exit('%s: not a KZ2_POST_MAP_OUT file' % binf)
            n = struct.unpack_from('<q', h, 8)[0]
            data = f.read(32 * n)
        for t, a, b, c, d, e, k, ti in struct.iter_unpack('<QIIIIIHH', data[:32 * (len(data) // 32)]):
            ev.append((t, k, ti, a, b, c, d, e))
    ev.sort(key=lambda e: e[0])
    return thr, ev


def job_of(c):
    """POST image id, or a negative id for other SPU code (-img; the policy module with another overlay -1000-ovl)."""
    img, ovl = c & 511, (c >> 9) & 511
    if img in POST:
        return img
    if img == 2:
        return ovl if ovl in POST else -(1000 + ovl)
    return -img


def who_spu(j):
    if j in POST:
        return 'post:' + POST[j]
    return 'spu:pm+ovl%d' % (-j - 1000) if j <= -1000 else 'spu:img%d' % -j


def merge(rs):
    out = []
    for a, b in sorted(rs):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def tname(thr, ti):
    n, h = thr.get(ti, ('?', 0))
    return n if n != '-' else ('walker' if h == 2 else 'spu' if h == 1 else 'tid%d' % ti)


def analyse(thr, ev, frames=3, out=sys.stdout):
    p = lambda *x: print(*x, file=out)
    walker = {ti for ti, (n, h) in thr.items() if h == 2}
    flips = [e[0] for e in ev if e[1] == 13] or [e[0] for e in ev if e[1] == WT + 32]
    nf = max(1, len(flips) - 1)
    # sampled windows: runs of frames with DMA events
    dmaf = collections.Counter(bisect.bisect_right(flips, e[0]) for e in ev if e[1] in (1, 2))
    wins, cur = [], None
    for fi in sorted(dmaf):
        if cur and fi == cur[1] + 1:
            cur[1] = fi
        else:
            cur = [fi, fi]
            wins.append(cur)
    def win_of(t):
        fi = bisect.bisect_right(flips, t)
        for w, (a0, a1) in enumerate(wins):
            if a0 <= fi <= a1:
                return w
        return -1
    nfs = max(1, sum(a1 - a0 + 1 for a0, a1 in wins))
    p('events %d, threads %d, flips %d, window %.2f s, sampled windows %d (%d frames with DMA)' % (
        len(ev), len(thr), len(flips), ev[-1][0] / 1e6, len(wins), nfs))

    rng = collections.defaultdict(lambda: {'get': [], 'put': [], 'small': collections.Counter()})
    calls, busy = collections.Counter(), collections.Counter()
    for t, k, ti, a, b, c, d, e in ev:
        if k in (1, 2):
            j = job_of(c)
            if j in POST:
                if b < MIN:
                    rng[j]['small'][('G' if k == 1 else 'P', a & ~0xF)] += 1
                else:
                    rng[j]['get' if k == 1 else 'put'].append((a, a + b))
        elif k == WT + 33 and (a & 0xFFFF) in POST:
            calls[a & 0xFFFF] += 1
            busy[a & 0xFFFF] += b
    p('\n1. post jobs: calls and SPU-ms per frame, merged DMA ranges of >= %d B (EA), small DMAs' % MIN)
    for j in sorted(set(rng) | set(calls)):
        r = rng[j]
        g, q = merge(r['get']), merge(r['put'])
        p('  %3d %-14s calls/f %5.1f  SPU-ms/f %5.2f  in %2d ranges %8d B  out %2d ranges %8d B  small(<%d) %d' % (
            j, POST[j], calls[j] / nf, busy[j] / 1e3 / nf, len(g), sum(y - x for x, y in g), len(q),
            sum(y - x for x, y in q), MIN, sum(r['small'].values())))
        for x, y in g[:8]:
            p('        in  0x%08X..0x%08X %8d' % (x, y, y - x))
        for x, y in q[:8]:
            p('        out 0x%08X..0x%08X %8d' % (x, y, y - x))
        for (op, ea), n in r['small'].most_common(3):
            p('        small %s 0x%08X x%d' % (op, ea, n))

    pages = collections.defaultdict(list)

    def add(t, ea, sz, op, who):
        w = win_of(t)
        if w < 0:
            return
        for pg in range(ea >> 12, ((ea + max(sz, 1) - 1) >> 12) + 1):
            pages[(w, pg)].append((t, op, who))

    for t, k, ti, a, b, c, d, e in ev:
        if k in (1, 2):
            j = job_of(c)
            if j in POST and b < MIN:
                continue
            add(t, a, b, 'R' if k == 1 else 'W', who_spu(j))
        elif k == 11:
            add(t, a, b, 'W', 'walker:writeback')
        elif k == 12:
            add(t, a, b, 'R', 'walker:texbind')
        elif k == 90:
            h = thr.get(ti, ('', 0))[1]
            kind = 'walker:fault' if ti in walker else 'spu:fault' if h == 1 else 'cpu:' + tname(thr, ti)
            add(t, a, 1, 'W' if d == 1 else 'R', kind)

    out_pages, in_pages = set(), set()
    for r in rng.values():
        for x, y in r['put']:
            out_pages.update(range(x >> 12, ((y - 1) >> 12) + 1))
        for x, y in r['get']:
            in_pages.update(range(x >> 12, ((y - 1) >> 12) + 1))
    keys = sorted(pages)

    p('\n2. inputs: last writer of a page before each post GET of it')
    wr = collections.defaultdict(collections.Counter)
    for key in keys:
        if key[1] not in in_pages:
            continue
        last = None
        for t, op, who in pages[key]:
            if op == 'W':
                last = who
            elif who.startswith('post:'):
                wr[who][last or 'none-in-window'] += 1
    for reader in sorted(wr):
        p('  %-22s %s' % (reader, ', '.join('%s %d' % kv for kv in wr[reader].most_common())))

    p('\n3. outputs: readers of a page after a post PUT of it (until the next write)')
    rd = collections.defaultdict(collections.Counter)
    cpu = collections.Counter()
    for key in keys:
        if key[1] not in out_pages:
            continue
        writer = None
        for t, op, who in pages[key]:
            if op == 'W':
                writer = who if who.startswith('post:') else None
            elif writer:
                rd[writer][who] += 1
                if who.startswith(('cpu:', 'walker:fault')):
                    cpu[(who, key[1] << 12, writer)] += 1
    for w in sorted(rd):
        p('  %-22s %s' % (w, ', '.join('%s %d' % kv for kv in rd[w].most_common())))
    p('  readers other than SPU DMA and texture binds: %d page reads' % sum(cpu.values()))
    for (who, ea, w), n in cpu.most_common(12):
        p('    %s page 0x%08X (written by %s) x%d' % (who, ea, w, n))
    faults = collections.Counter()
    rips = collections.Counter()
    for t, k, ti, a, b, c, d, e in ev:
        if k == 90:
            key = (tname(thr, ti), 'W' if d == 1 else 'R', (a >> 12) in out_pages, (a >> 12) in in_pages)
            faults[key] += 1
            if ti not in walker and thr.get(ti, ('', 0))[1] != 1:
                rips[(tname(thr, ti), b, c)] += 1
    p('  watch faults (thread, R/W, on an output page, on an input page):')
    for kk, n in faults.most_common(16):
        p('    %-18s %s out=%d in=%d  %d' % (kk[0], kk[1], kk[2], kk[3], n))
    for (n, rip, rs), c in rips.most_common(8):
        p('    no-hook thread %s rip exe+0x%x [rsp] exe+0x%x x%d' % (n, rip, rs, c))

    p("\n4. timeline (ms after the frame's walker flip)")
    names = {32: 'flip(wt)', 34: 'ucmd-queued', 35: 'ucmd-delivered', 3: 'label-wait', 41: 'park-put', 42: 'park',
             43: 'unpark', 44: 'park-word'}
    sel = [fi for a0, a1 in wins for fi in range(a0, a1 + 1)][:frames] or list(range(len(flips) // 2, len(flips) // 2 + frames))
    for fi in sel:
        if fi < 1 or fi >= len(flips):
            continue
        f0, f1 = flips[fi - 1], flips[fi]
        p('  frame %d: %.2f ms' % (fi, (f1 - f0) / 1e3))
        posts = [(t, a & 0xFFFF, b) for t, k, ti, a, b, *_ in ev if k == WT + 33 and f0 <= t < f1 and (a & 0xFFFF) in POST]
        if posts:
            last = max(posts, key=lambda x: x[0] + x[2])
            p('    post jobs: %d calls, %.2f SPU-ms, first at %.2f (%s), last end %.2f (%s)' % (
                len(posts), sum(x[2] for x in posts) / 1e3, (posts[0][0] - f0) / 1e3, POST[posts[0][1]],
                (last[0] + last[2] - f0) / 1e3, POST[last[1]]))
        seen = collections.Counter()
        for t, k, ti, a, b, c, d, e in ev:
            if not (f0 <= t < f1):
                continue
            lab = None
            if k == 14:
                lab = 'sync-point caller exe+0x%x' % a
            elif k == 11:
                lab = 'write-back 0x%08X %dx%d' % (a, c & 0xFFFF, c >> 16)
            elif k == 10:
                lab = 'gpu-write 0x%08X %dx%d' % (a, c & 0xFFFF, c >> 16)
            elif k == 12:
                lab = 'texbind 0x%08X %dx%d' % (a, c & 0xFFFF, c >> 16)
            elif k - WT in names:
                lab = '%s site 0x%x dur %d us (%s)' % (names[k - WT], a, b, tname(thr, ti))
            if lab:
                key = lab.split(' ')[0]
                seen[key] += 1
                if seen[key] <= 8:
                    p('    %8.2f %s' % ((t - f0) / 1e3, lab))
        p('    counts: ' + ', '.join('%s %d' % kv for kv in sorted(seen.items())))
    return {'inputs': {k: dict(v) for k, v in wr.items()}, 'outputs': {k: dict(v) for k, v in rd.items()},
            'other_readers': sum(cpu.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log')
    ap.add_argument('--bin', help="KZ2_POST_MAP_OUT's binary event file")
    ap.add_argument('--frames', type=int, default=3, help='frames to print in the timeline')
    ap.add_argument('--json')
    a = ap.parse_args()
    thr, ev = load(a.log, a.bin)
    if not ev:
        sys.exit('no [pmap] events')
    res = analyse(thr, ev, a.frames)
    if a.json:
        with open(a.json, 'w') as f:
            json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
