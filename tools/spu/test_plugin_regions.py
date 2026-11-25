#!/usr/bin/env python3
"""Host test of the Amadeus plugin lift's script side (lift_spu.py kind "plugin", gen_spu_register.py). No game data.

1. gen_spu_register.merge_segments: at most 8 sorted, disjoint ranges that cover every function range and add
   nothing outside the first start and the last end (random range sets, plus the edge cases).
2. The census tables of both EBOOT versions name six plugin rows, all job-module rows, and the plugin that
   lift_spu.PLUGIN_SEEDS has extra function starts for is one of them in both (the seeds are keyed by fp_span).
3. The seeds lie in the plugin's image at PLUGIN_BASE and are instruction-aligned.

    python3 tools/spu/test_plugin_regions.py
"""
import importlib
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
fails = []


def check(ok, msg):
    if not ok:
        fails.append(msg)


def load(ver):
    os.environ["KZ2_EBOOT_VER"] = ver
    for m in ("kz2ver", "lift_spu", "gen_spu_register"):
        sys.modules.pop(m, None)
    return importlib.import_module("kz2ver"), importlib.import_module("lift_spu"), importlib.import_module(
        "gen_spu_register")


def test_merge(gen):
    check(gen.merge_segments([]) == [], "empty")
    check(gen.merge_segments([(8, 8), (4, 2)]) == [], "empty ranges are dropped")
    check(gen.merge_segments([(0x10, 0x20), (0x20, 0x30), (0x28, 0x40)]) == [(0x10, 0x40)], "touching/overlapping join")
    check(gen.merge_segments([(0, 4), (100, 104), (8, 12)], limit=2) == [(0, 12), (100, 104)], "smallest gap first")
    rng = random.Random(7023)
    for _ in range(2000):
        n = rng.randrange(1, 60)
        b = []
        for _ in range(n):
            s = rng.randrange(0x8400, 0x20000) & ~3
            b.append((s, s + 4 * rng.randrange(1, 400)))
        limit = rng.choice([1, 2, 8])
        segs = gen.merge_segments(b, limit)
        ok = 0 < len(segs) <= limit
        ok = ok and all(s < e for s, e in segs) and all(segs[i][1] < segs[i + 1][0] for i in range(len(segs) - 1))
        ok = ok and all(any(s <= bs and be <= e for s, e in segs) for bs, be in b)
        ok = ok and segs[0][0] == min(s for s, _ in b) and segs[-1][1] == max(e for _, e in b)
        if not ok:
            check(False, f"merge_segments({b}, {limit}) = {segs}")
            break
    check(gen.MAX_SEGMENTS == 8, "MAX_SEGMENTS is the runtime's SPU_OVERLAY_CODE_SEGMENTS (8)")


def test_census(ver):
    kz2ver, lift, _gen = load(ver)
    rows = kz2ver.rows()
    plug = [r for r in rows if lift.PLUGIN_MARK in r.get("reg_name", "")]
    check(len(plug) == 6, f"{ver}: {len(plug)} plugin rows, want 6")
    check(all(r["kind"] == "job" for r in plug), f"{ver}: a plugin row is not a job-module row")
    fps = {r.get("fp_span", ""): r for r in plug}
    for fp, seeds in lift.PLUGIN_SEEDS.items():
        check(fp in fps, f"{ver}: no plugin row with fp_span {fp}")
        if fp in fps:
            end = lift.PLUGIN_BASE + fps[fp]["size"]
            bad = [hex(s) for s in seeds if not (lift.PLUGIN_BASE + 0x30 <= s < end) or s & 3]
            check(not bad, f"{ver}: seeds outside the image or unaligned: {bad}")
    check(lift.PLUGIN_BASE == 0x8400, "PLUGIN_BASE")


def main():
    _k, _l, gen = load("129")
    test_merge(gen)
    for ver in ("129", "101"):
        test_census(ver)
    for f in fails:
        print("FAIL", f)
    print(f"test_plugin_regions: {'FAIL' if fails else 'PASS'} ({len(fails)} failed)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
