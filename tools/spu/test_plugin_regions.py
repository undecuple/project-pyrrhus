#!/usr/bin/env python3
"""Host test of the Amadeus plugin lift's script side (lift_spu.py kind "plugin", gen_spu_register.py). No game data.

1. gen_spu_register.merge_segments: at most 8 sorted, disjoint ranges that cover every function range and add
   nothing outside the first start and the last end (random range sets, plus the edge cases).
2. The census tables of both EBOOT versions name six plugin rows, all job-module rows, and the plugin that
   lift_spu.PLUGIN_SEEDS has extra function starts for is one of them in both (the seeds are keyed by fp_span).
3. The seeds lie in the plugin's image at PLUGIN_BASE and are instruction-aligned.
4. lift_spu.py lifts plugins only when asked: the default kinds have no "plugin" unless KZ2_LIFT_PLUGINS=1.
5. lift_spu.plugin_code_end: the first function that decodes to data, only when nothing but data follows it.
6. gen_spu_register.py on a made-up lift (no game bytes: a fake EBOOT and image table): a failed plugin row and one
   whose entry symbol is missing are left out with a warning, never fatal; the generated spu_workloads.c, compiled
   with a C compiler against the patched toolkit's headers and stand-ins for the runtime, registers nothing when
   KZ2_AMADEUS_PLUGINS is unset, empty, 0 or 10, and with =1 registers the good plugin once: its EA, load address,
   span, image id 400 and segment bytes equal to the EBOOT's. The C part SKIPs without a compiler or a patched
   toolkit (KZ2_PATCHED_DIR or work/ps3recomp-patched).

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


def test_default_kinds():
    import subprocess
    code = ("import sys; sys.argv=['x','--ps3recomp','.','--out','.']; import lift_spu, argparse;"
            "orig=argparse.ArgumentParser.parse_args;"
            "argparse.ArgumentParser.parse_args=lambda s,*a: (print(orig(s).kinds), sys.exit(0));"
            "lift_spu.main()")
    for env, want in ((None, "pm,job,elf"), ("0", "pm,job,elf"), ("1", "pm,job,elf,plugin")):
        e = dict(os.environ)
        e.pop("KZ2_LIFT_PLUGINS", None)
        if env is not None:
            e["KZ2_LIFT_PLUGINS"] = env
        r = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=e, capture_output=True, text=True)
        check(r.stdout.strip() == want, f"KZ2_LIFT_PLUGINS={env}: default kinds {r.stdout.strip()!r} {r.stderr[-300:]}")


def test_code_end(lift):
    B = 0x8400
    w = lambda fs: [B + 0x900, 0, fs, False, False]
    res = dict(bounds=[[B + 0x30, B + 0x100], [B + 0x100, B + 0x200], [B + 0x2000, B + 0x2100]], words=[w(B + 0x2000)])
    check(lift.plugin_code_end(res) == B + 0x2000, "code end at the data function")
    res = dict(bounds=res["bounds"] + [[B + 0x3000, B + 0x3010]], words=[w(B + 0x2000)])
    check(lift.plugin_code_end(res) == 0, "a clean function after the data one: no cut")
    check(lift.plugin_code_end(dict(bounds=[[B, B + 8]], words=[])) == 0, "no data: no cut")


def test_generator(gen_ver):
    import json, shutil, subprocess, tempfile
    kz2ver, _lift, gen = load(gen_ver)
    d = tempfile.mkdtemp(prefix="plgreg")
    try:
        eboot = bytes((i * 13 + 5) & 0xFF for i in range(0x4000))
        open(os.path.join(d, "EBOOT.elf"), "wb").write(eboot)
        tsv = os.path.join(d, "census.tsv")
        hdr = "kind\tfile_offset\tea\tsize\tspan\tfp_span\tstandalone\theader\treg_name"
        rows = [f"job\t0x{o:08x}\t0x{o + 0x10000:X}\t512\t512\t0x{o:016X}\t1\t\t(unregistered) Amadeus audio plugin module"
                for o in (0x1000, 0x2000, 0x3000)]
        open(tsv, "w").write(chr(10).join([hdr] + rows) + chr(10))
        kz2ver.EBOOT, kz2ver.TSV = os.path.join(d, "EBOOT.elf"), tsv
        lift = os.path.join(d, "spu")
        os.makedirs(os.path.join(lift, "lift", "plg_00001000"))
        open(os.path.join(lift, "eboot_ver"), "w").write(kz2ver.VER + chr(10))
        open(os.path.join(lift, "lift", "plg_00001000", "spu_recomp.h"), "w").write(
            "void plg_00001000_spu_func_00008430(void* ctx);" + chr(10))
        row = lambda o, ok: dict(name=f"plg_{o:08x}", kind="plugin", ok=ok, file_offset=o, size=512, base=0x8400,
                                 entry_off=0x30, job=f"job_{o:08x}", reg_name="(unregistered) Amadeus audio plugin module",
                                 bounds=[[0x8430, 0x8480], [0x8500, 0x8540]])
        json.dump([row(0x1000, True), row(0x2000, False), row(0x3000, True)], open(os.path.join(lift, "spu_lift.json"), "w"))
        sys.argv = ["gen_spu_register.py", "--lift", lift]
        import contextlib, io
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                gen.main()
            ran = True
        except SystemExit as e:
            ran = False
            check(False, f"gen_spu_register exited on a bad plugin row: {e}")
        if not ran:
            return
        w = err.getvalue()
        check("plg_00002000: lift failed" in w, "a failed plugin row is warned about")
        check("plg_00003000: entry symbol" in w, "a plugin without its entry symbol is warned about")
        src = os.path.join(lift, "lift", "spu_workloads.c")
        c = open(src).read()
        check("plg_00002000" not in c and "plg_00003000_spu_recomp_register" not in c, "bad plugin rows are left out")
        check(c.count("spu_overlay_register_verified_region(") == 1, "one region is generated")
        check("unsigned kz2_spu_image_count = 1u;" in c and "const unsigned kz2_spu_image_names_n = 1u;" in c,
              "the image count and the name table agree")
        pt = os.environ.get("KZ2_PATCHED_DIR") or os.path.join(HERE, "..", "..", "work", "ps3recomp-patched")
        cc = next((x for x in ("cc", "gcc", "clang") if shutil.which(x)), None)
        if not cc or not os.path.isfile(os.path.join(pt, "runtime", "spu", "spu_overlay_residency.h")):
            print("SKIP: the generated file's C part (no C compiler or no patched toolkit)")
            return
        stub = os.path.join(d, "stub.c")
        open(stub, "w").write(chr(10).join([
            "#include <stdint.h>", "#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>",
            "typedef struct { uint32_t lsa, size; const uint8_t* bytes; } seg_t;",
            "static int n_reg, n_begin; static uint32_t r_ea, r_lsa, r_span, r_count; static int r_id; static int bytes_ok = 1;",
            "static const uint8_t* eboot; static size_t eboot_n;",
            "void spu_begin_image(int id) { (void)id; n_begin++; }",
            "void plg_00001000_spu_recomp_register(void) {}",
            "int spu_overlay_register_verified_region(uint32_t ea, uint32_t lsa, uint32_t span, int id, const seg_t* s, unsigned n) {",
            "    n_reg++; r_ea = ea; r_lsa = lsa; r_span = span; r_id = id; r_count = n;",
            "    for (unsigned i = 0; i < n; i++) {",
            "        uint32_t off = 0x1000u + (s[i].lsa - 0x8400u);",
            "        if (off + s[i].size > eboot_n || memcmp(eboot + off, s[i].bytes, s[i].size)) bytes_ok = 0;",
            "    }",
            "    return 1;", "}",
            "void spu_workload_register_img(void) {}", "void spu_overlay_register_sig(void) {}",
            "const char* (*g_kz2_spu_image_name)(int);",
            "/* the generated file registers from a constructor: load the EBOOT copy in an earlier one */",
            "__attribute__((constructor(101))) static void load_first(void) {",
            "    static uint8_t b[0x4000]; FILE* f = fopen(getenv(\"T_EBOOT\"), \"rb\");",
            "    if (f) { eboot_n = fread(b, 1, sizeof b, f); fclose(f); } eboot = b;",
            "}",
            "int main(void) {",
            "    printf(\"%d %X %X %X %d %u %d\" \"\\n\", n_reg, r_ea, r_lsa, r_span, r_id, r_count, bytes_ok);",
            "    return 0;", "}", ""]))
        exe = os.path.join(d, "t.exe" if os.name == "nt" else "t")
        inc = ["-I", os.path.join(pt, "runtime", "spu"), "-I", os.path.join(pt, "include"), "-I", os.path.join(pt, "runtime")]
        b = subprocess.run([cc, "-std=gnu11", "-O1", "-w", "-msse4.1", *inc, "-o", exe, src, stub],
                           capture_output=True, text=True)
        check(b.returncode == 0, "the generated file compiles: " + b.stderr[-600:])
        if b.returncode:
            return
        for val, want in ((None, 0), ("", 0), ("0", 0), ("10", 0), ("1", 1)):
            e = dict(os.environ, T_EBOOT=os.path.join(d, "EBOOT.elf"))
            e.pop("KZ2_AMADEUS_PLUGINS", None)
            if val is not None:
                e["KZ2_AMADEUS_PLUGINS"] = val
            r = subprocess.run([exe], env=e, capture_output=True, text=True)
            f = r.stdout.split()
            check(r.returncode == 0 and f and int(f[0]) == want,
                  f"KZ2_AMADEUS_PLUGINS={val!r}: {f[0] if f else '?'} regions registered, want {want} {r.stderr[-200:]}")
            if want and len(f) == 7:
                check(f[1:6] == ["11000", "8400", "140", "400", "2"], f"the region's EA/load/span/id/count: {f[1:6]}")
                check(f[6] == "1", "the segment bytes are the EBOOT's")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    _k, lift, gen = load("129")
    test_merge(gen)
    for ver in ("129", "101"):
        test_census(ver)
    test_default_kinds()
    test_code_end(lift)
    test_generator("129")
    for f in fails:
        print("FAIL", f)
    print(f"test_plugin_regions: {'FAIL' if fails else 'PASS'} ({len(fails)} failed)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
