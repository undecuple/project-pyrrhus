#!/usr/bin/env python3
"""Lift Killzone 2's SPU programs with ps3recomp's spu_lifter: the WWS job-manager policy module, the WWS job modules
and the SPU ELFs. From Project Helghast tools/spu/lift_spu.py (kz3ver -> kz2ver; inputs from the re-data census).

    lift_spu.py --ps3recomp work/spu/ps3recomp-patched --out work/spu/spu [-j N] [--only NAME,...] [--kinds pm,job,elf]

Run it through tools/spu/lift_spu.sh (sandboxed, patched ps3recomp copy). Input (read-only): the EBOOT of
KZ2_EBOOT_VER (129 default: work/bin/EBOOT-129.elf; 101: the disc EBOOT) and re/wws_jobs_v<VER>.tsv (
23 ELFs, 36 job modules, 1 PM, by file offset). Every image is carved from the EBOOT.

Job modules are raw local-store images, not ELF. Header (KZ3's notes, the same in KZ2: 36/36 have 0xC0DEC0DE at +0x20):
  +0x00 four `ila` (a 16-byte signature)   +0x10 entry offset   +0x14 LS footprint (code+data+bss)
  +0x18, +0x1C two more sizes              +0x20 0xC0DEC0DE     +0x24 ?   +0x28 LS base (0x4000 or 0)
  +0x2C flags (5 / 0x80000005)             +0x30 first instruction
KZ2's census offsets are the true module starts (no -0xC as KZ3's jobmods.py). The initialised image is
min(footprint, distance to the next image of any kind): Anim.Skinning's footprint runs over the policy module (1.29 0xD90C00 +
0xCA00 > PM 0xD92C80). Each module is wrapped as a one-segment SPU ELF at its LS base (0x4000 when the header says 0)
with entry base+entry_off and lifted with --auto-functions plus the extra seeds of ps3recomp's lift_jobmods.py.

Output: <out>/lift/<name>/spu_recomp.{c,h} + lift.log, <out>/spu_lift.json, <out>/eboot_ver.
"""
import argparse, json, os, struct, sys, io, contextlib, traceback
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kz2ver  # noqa: E402

# Images without section headers whose code/rodata boundary was found by hand (name -> LS address).
CODE_END = {}
# SPURS policy module: raw LS image the SPURS kernel loads at LS 0xA00 and enters at 0xA00 (cellSpursModuleEntry).
# 0xA2C is its interrupt handler (the entry stores `bra 0xA2C` at LS 0; nothing branches there).
PM_BASE = 0xA00
PM_SEEDS = [0xA2C]


def keep_seeds(name, seeds, lo, hi, ce, dropped):
    """Seeds inside [lo, ce or hi); the rest are recorded in `dropped` (name -> [hex])."""
    end = ce or hi
    ok = [s for s in seeds if lo <= s < end and not s & 3]
    bad = [hex(s) for s in seeds if s not in ok]
    if bad:
        dropped[name] = bad
    return ok


def census():
    d = open(kz2ver.EBOOT, "rb").read()
    return d, kz2ver.rows()


def audio_elfs(rows):
    """File offsets of ELFs that wrap a job module (the Snd payloads: job start within 0x200 after the ELF)."""
    elfs = [r["file_offset"] for r in rows if r["kind"] == "elf"]
    return {e for e in elfs for r in rows if r["kind"] == "job" and 0 < r["file_offset"] - e < 0x200}


def job_modules(d, rows):
    """Carve the job modules. Returns [(name, raw_bytes, base, entry_off, meta)]."""
    starts = sorted(r["file_offset"] for r in rows)
    aud = audio_elfs(rows)
    out = []
    for r in rows:
        if r["kind"] != "job":
            continue
        s = r["file_offset"]
        assert d[s + 0x20:s + 0x24] == b"\xc0\xde\xc0\xde", hex(s)
        ent, foot, w3, w4 = struct.unpack(">4I", d[s + 0x10:s + 0x20])
        w9, base, flags = struct.unpack(">3I", d[s + 0x24:s + 0x30])
        nxt = min([x for x in starts if x > s] or [s + foot])
        n = min(foot, nxt - s)
        raw = d[s:s + n]
        inside = any(0 < s - e < 0x200 for e in aud)
        meta = dict(file_offset=s, entry_off=ent, footprint=foot, w3=w3, w4=w4, w9=w9, hdr_base=base,
                    flags=flags, inside_elf=inside, reg_name=r.get("reg_name", ""))
        out.append((r["name"], raw, base or 0x4000, ent, meta))
    return out


def policy_modules(d, rows):
    """Carve the SPURS policy module(s). Returns [(name, raw_bytes, seeds)]."""
    return [(r["name"], d[r["file_offset"]:r["file_offset"] + r["size"]], PM_SEEDS) for r in rows if r["kind"] == "pm"]


def elf_code_end(elf):
    """End of code for SDK-built ELFs: the start of .rodata when it lies inside the executable segment."""
    from find_spu_functions import parse_elf
    p = parse_elf(elf)
    for sh in p["shs"]:
        if sh["name"] == ".rodata" and sh["addr"]:
            return sh["addr"]
    return 0


# SPU branch opcodes (9-bit, ISA "Branch Instructions"): relative ones add I16<<2 to the pc, absolute ones are I16<<2.
REL_BRANCH = {0x066, 0x064, 0x042, 0x040, 0x046, 0x044}  # brsl br brnz brz brhnz brhz
ABS_BRANCH = {0x062, 0x060}                            # brasl bra


def exec_segments(elf):
    """Executable PT_LOAD segments of an SPU ELF: [(file_off, vaddr, filesz)] in program-header order."""
    phoff, = struct.unpack(">I", elf[0x1C:0x20])
    n, = struct.unpack(">H", elf[0x2C:0x2E])
    out = []
    for i in range(n):
        t, o, v, _pa, fs, _ms, fl, _al = struct.unpack(">8I", elf[phoff + 32 * i:phoff + 32 * i + 32])
        if t == 1 and fl & 1:
            out.append((o, v, fs))
    return out


def cross_segment_targets(elf, segs, k):
    """Branch targets in exec segment k reached from the other exec segments (function entries the lift of
    segment k alone cannot see). Example: elf_00fd7280 `brsl` at 0x2324C into .text_init 0x3CC08."""
    _o, v, fs = segs[k]
    tg = set()
    for j, (so, sv, sf) in enumerate(segs):
        if j == k:
            continue
        for a in range(0, sf - 3, 4):
            w, = struct.unpack(">I", elf[so + a:so + a + 4])
            op9, i16 = w >> 23, (w >> 7) & 0xFFFF
            i16 -= 0x10000 if i16 & 0x8000 else 0
            if op9 in REL_BRANCH:
                t = (sv + a + (i16 << 2)) & 0x3FFFF
            elif op9 in ABS_BRANCH:
                t = (i16 << 2) & 0x3FFFF
            else:
                continue
            if v <= t < v + fs:
                tg.add(t)
    return sorted(tg)


def _after_return(elf, so, sv, t):
    """True when LS address t (in the segment at file offset so / vaddr sv) follows `bi`/`br`/`bra`, optionally
    padded by one `nop`/`lnop`: where a function that nothing branches to directly starts."""
    def word(a):
        return struct.unpack(">I", elf[so + a - sv:so + a - sv + 4])[0] if a - sv >= 0 else 0
    # Skip alignment padding: `nop`/`lnop`, and zero words, up to 32 of them. job_011e1180's 0xCA80,
    # called through a pointer from 0x86D4 about a thousand times a second in the level, follows 16 zero bytes.
    a = t - 4
    p = word(a)
    n = 0
    while (p >> 21 in (0x001, 0x201) or p == 0) and a - 4 >= sv and n < 32:
        a -= 4
        p = word(a)
        n += 1
    return p >> 21 == 0x1A8 or p >> 23 in (0x064, 0x060)  # bi / br / bra


def pointer_targets(elf, segs, k, end=0):
    """Function entries in exec segment k whose address some exec segment builds with `ila` (function pointers:
    the .text_init segments fill vtables with main-segment entries, and the main segment builds pointers to the
    .text_init fill functions, e.g. elf_00f89300 0x3158 `ila $r9,0x3C188`). Only addresses below the code end that
    follow a return/branch count, so `ila` of .rodata strings and of mid-function labels is not seeded."""
    so, v, fs = segs[k]
    end = end or v + fs
    tg = set()
    for (o, _sv, sf) in segs:
        for a in range(0, sf - 3, 4):
            w, = struct.unpack(">I", elf[o + a:o + a + 4])
            if w >> 25 != 0x21:  # ila
                continue
            t = (w >> 7) & 0x3FFFF
            if v + 4 <= t < end and not t & 3 and _after_return(elf, so, v, t):
                tg.add(t)
    return sorted(tg)


def load_segments(elf):
    """All PT_LOAD segments of an SPU ELF (code and data): [(file_off, vaddr, filesz)]."""
    phoff, = struct.unpack(">I", elf[0x1C:0x20])
    n, = struct.unpack(">H", elf[0x2C:0x2E])
    out = []
    for i in range(n):
        t, o, v, _pa, fs, _ms, _fl, _al = struct.unpack(">8I", elf[phoff + 32 * i:phoff + 32 * i + 32])
        if t == 1 and fs:
            out.append((o, v, fs))
    return out


def table_targets(blobs, code, end):
    """Function entries reached only through a pointer TABLE in data: a 4-aligned 32-bit word anywhere
    in the image whose value is a code address below `end` that follows a return/branch (`_after_return`).
    Example: job_011f4800 (WWS overlay image 260) keeps 0x14E88 at LS 0x1FA58; nothing branches to 0x14E88 or
    builds it with `ila`, so the lift had no function there and every call through the table ran interpreted.
    blobs: [(bytes, vaddr)] to scan; code: (bytes, vaddr) of the segment the targets must lie in."""
    cb, cv = code
    tg = set()
    for (b, bv) in blobs:
        for a in range(0, len(b) - 3, 4):
            t, = struct.unpack(">I", b[a:a + 4])
            if cv + 4 <= t < end and not t & 3 and _after_return(cb, 0, cv, t):
                tg.add(t)
    return sorted(tg)


def ila_targets(code, end):
    """`ila` immediates in a raw module that land on a function start (same filter as pointer_targets)."""
    cb, cv = code
    tg = set()
    for a in range(0, len(cb) - 3, 4):
        w, = struct.unpack(">I", cb[a:a + 4])
        if w >> 25 == 0x21:
            t = (w >> 7) & 0x3FFFF
            if cv + 4 <= t < end and not t & 3 and _after_return(cb, 0, cv, t):
                tg.add(t)
    return sorted(tg)


TERMINATORS = {"br", "bra", "bi", "iret", "stop", "stopd"}


def reachable(insns, lifter, starts):
    """Addresses reachable from the function starts by fall-through and direct branches.

    A `.word` that is reachable sits in the straight-line path of something the lifter treats as code
    (a real gap, or a bogus function start); an unreachable one follows a terminator and is data."""
    by = {i.addr: i for i in insns}
    seen, work = set(), [s for s in starts if s in by]
    while work:
        a = work.pop()
        while a in by and a not in seen:
            seen.add(a)
            i = by[a]
            t = lifter._branch_target(i)
            if t is not None and t not in seen:
                work.append(t)
            if i.mnemonic in TERMINATORS or i.mnemonic == ".word":
                break
            a += 4
    return seen


def data_refs(insns):
    """LS addresses the code loads from or builds as pointers: lqa/lqr/stqa/stqr targets and `ila` values."""
    refs = set()
    for i in insns:
        if i.mnemonic in ("lqa", "lqr", "stqa", "stqr", "ila"):
            tok = i.operands.split(",")[-1].strip()
            if tok.startswith("0x"):
                refs.add(int(tok, 16) & ~0xF)
    return sorted(refs)


def debase_includes(sub):
    """Rewrite the lifter's `#include "../../runtime/spu/X.h"` to `#include "X.h"` (resolved with
    -I<ps3recomp>/runtime/spu), so the lifted tree builds from any directory (same as ps3recomp's
    build_spu_workloads.py)."""
    import re
    for fn in ("spu_recomp.c", "spu_recomp.h"):
        p = os.path.join(sub, fn)
        if os.path.exists(p):
            t = open(p).read()
            n = re.sub(r'#include\s+"(?:\.\./)+runtime/spu/([A-Za-z0-9_]+\.h)"', r'#include "\1"', t)
            if n != t:
                open(p, "w").write(n)


def lift_one(job):
    """Run spu_lifter.main() in-process for one image and collect what it lifted."""
    name, kind, elf_path, argv_extra, meta, pt, outdir = job
    sys.path.insert(0, os.path.join(pt, "tools"))
    import spu_lifter
    hist, words, inst = {}, [], {}
    orig_lift, orig_init = spu_lifter.SPULifter.lift_function, spu_lifter.SPULifter.__init__

    def init(self, *a, **k):
        orig_init(self, *a, **k)
        inst["l"] = self

    def lift(self, insns, start, end):
        if "reach" not in inst:
            inst["reach"] = reachable(insns, self, starts_of[0])
            inst["refs"] = data_refs(insns)
        for i in insns:
            if start <= i.addr < end:
                hist[i.mnemonic] = hist.get(i.mnemonic, 0) + 1
                if i.mnemonic == ".word":
                    words.append((i.addr, i.raw, start, i.addr in inst["reach"],
                                  any(r <= i.addr < r + 0x200 for r in inst["refs"])))
        return orig_lift(self, insns, start, end)

    starts_of = [None]
    orig_cbr = spu_lifter.compute_bi_r0_jumps

    def cbr(insns, bounds):  # called once by main() with the final function bounds
        starts_of[0] = sorted(s for s, _ in bounds)
        return orig_cbr(insns, bounds)

    spu_lifter.compute_bi_r0_jumps = cbr
    spu_lifter.SPULifter.lift_function, spu_lifter.SPULifter.__init__ = lift, init
    sub = os.path.join(outdir, "lift", name)
    os.makedirs(sub, exist_ok=True)
    sys.argv = ["spu_lifter.py", "--auto-functions", elf_path, "--symbol-prefix", f"{name}_", "-o", sub] + argv_extra
    buf = io.StringIO()
    ok = True
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            spu_lifter.main()
    except BaseException:
        ok = False
        buf.write(traceback.format_exc())
    debase_includes(sub)
    open(os.path.join(sub, "lift.log"), "w").write(" ".join(sys.argv[1:]) + "\n" + buf.getvalue())
    l = inst.get("l")
    res = dict(name=name, kind=kind, ok=ok, argv=argv_extra, **meta)
    if l is not None:
        res.update(functions=len(l.functions), unsupported=dict(l.unsupported),
                   insns=sum(hist.values()), hist=hist,
                   words=[list(w) for w in words])
    for line in buf.getvalue().splitlines():
        if line.startswith("Text segment:"):
            res["text"] = line
        if line.startswith("Function coverage:"):
            res["coverage"] = line
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ps3recomp", required=True, help="patched ps3recomp copy (tools/ inside)")
    ap.add_argument("--out", required=True)
    ap.add_argument("-j", type=int, default=os.cpu_count())
    ap.add_argument("--only", default="", help="comma list of image names")
    ap.add_argument("--kinds", default="pm,job,elf", help="comma list of image kinds to lift (pm, job, elf)")
    ap.add_argument("--no-code-end", action="store_true", help="ELF: do not stop at .rodata (audit baseline)")
    a = ap.parse_args()
    pt = os.path.abspath(a.ps3recomp)
    out = os.path.abspath(a.out)
    sys.path.insert(0, os.path.join(pt, "tools"))
    from wrap_spu_elf import wrap
    from lift_jobmods import manual_link_targets, switch_table_targets

    cov = {}  # no RPCS3 coverage seeds for KZ2 yet (KZ3 re/data/spu_coverage_seeds.tsv)
    kinds = set(a.kinds.split(","))
    d, rows = census()
    AUDIO_ELFS = audio_elfs(rows)
    dropped = {}
    jobs = []
    tmp = os.path.join(out, "elf_in")
    os.makedirs(tmp, exist_ok=True)
    for r in rows:
        if r["kind"] != "elf":
            continue
        off = r["file_offset"]
        elf = d[off:off + r["size"]]
        p = os.path.join(tmp, f"spu_{off:08x}.elf")
        open(p, "wb").write(elf)
        extra = []
        ce = 0 if a.no_code_end else (elf_code_end(elf) or CODE_END.get(f"elf_{off:08x}", 0))
        if ce:
            extra += ["--code-end", hex(ce)]
        meta = dict(file_offset=off, size=len(elf), code_end=ce, wraps_jobmod=off in AUDIO_ELFS)
        # The extra segments call back into the main one (elf_00f89300 .text_init 0x3C264 `brsl` -> 0x154A8, a
        # function nothing in the main segment calls directly): seed those entries too.
        segs = exec_segments(elf)
        back = cross_segment_targets(elf, segs, 0) if len(segs) > 1 else []
        back = sorted(set(back) | set(pointer_targets(elf, segs, 0, ce)))
        if segs and f"elf_{off:08x}" in cov:
            _o, v0, f0 = segs[0]
            back = sorted(set(back) | set(keep_seeds(f"elf_{off:08x}", cov[f"elf_{off:08x}"], v0, v0 + f0, ce, dropped)))
        if segs:
            so0, sv0, sf0 = segs[0]
            blobs = [(elf[o:o + f], v) for (o, v, f) in load_segments(elf)]
            back = sorted(set(back) | set(table_targets(blobs, (elf[so0:so0 + sf0], sv0), ce or sv0 + sf0)))
        if back:
            extra += ["--extra-funcs", ",".join(hex(x) for x in back)]
            meta["seeds"] = [hex(x) for x in back]
        jobs.append((f"elf_{off:08x}", "elf", p, extra, meta, pt, out))
        # ps3recomp's find_spu_functions.pick_text lifts only the FIRST executable PT_LOAD. The four Tt* images
        # carry a second one (.text_init past .bss, e.g. elf_00fd7280 0x3CA00..0x3CCE0) that the main segment
        # calls; lift each extra segment on its own and register it under the parent's image id
        # (gen_spu_register.py, kind "elfseg").
        for k in range(1, len(segs)):
            so, sv, sf = segs[k]
            sp = os.path.join(tmp, f"elf_{off:08x}_x{sv:05x}.elf")
            open(sp, "wb").write(wrap(elf[so:so + sf], base=sv, entry=sv))
            seeds = sorted(set(cross_segment_targets(elf, segs, k)) | set(pointer_targets(elf, segs, k)))
            smeta = dict(file_offset=off, size=sf, base=sv, parent=f"elf_{off:08x}", seeds=[hex(x) for x in seeds])
            sx = ["--extra-funcs", ",".join(hex(x) for x in seeds)] if seeds else []
            jobs.append((f"elf_{off:08x}_x{sv:05x}", "elfseg", sp, sx, smeta, pt, out))
    elf_ce = {j[4]["file_offset"]: j[4]["code_end"] for j in jobs if j[1] == "elf"}
    for name, raw, base, ent, meta in job_modules(d, rows):
        p = os.path.join(tmp, name + ".elf")
        open(p, "wb").write(wrap(raw, base=base, entry=base + ent))
        seeds = [base + 0x30] + manual_link_targets(raw, base) + switch_table_targets(raw, base)
        # Entries reached only through data pointer tables or `ila`-built pointers.
        jce = meta.get("code_end") or 0
        wrapper0 = [e for e in AUDIO_ELFS if 0 < meta["file_offset"] - e < 0x200]
        if wrapper0 and elf_ce.get(wrapper0[0]) and not a.no_code_end:
            jce = elf_ce[wrapper0[0]]
        jend = jce or base + len(raw)
        seeds += table_targets([(raw, base)], (raw, base), jend) + ila_targets((raw, base), jend)
        seeds += keep_seeds(name, cov.get(name, []), base, base + len(raw), jce, dropped)
        seeds = sorted({s for s in seeds if base <= s < base + len(raw)})
        meta = dict(meta, size=len(raw), base=base)
        extra = ["--extra-funcs", ",".join(hex(s) for s in seeds)]
        # A module that is also the payload of an audio ELF gets that ELF's .rodata boundary (same LS addresses).
        wrapper = [e for e in AUDIO_ELFS if 0 < meta["file_offset"] - e < 0x200]
        if wrapper and elf_ce.get(wrapper[0]) and not a.no_code_end:
            extra += ["--code-end", hex(elf_ce[wrapper[0]])]
            meta["code_end"] = elf_ce[wrapper[0]]
        jobs.append((name, "job", p, extra, meta, pt, out))
    for name, raw, seeds in policy_modules(d, rows):
        p = os.path.join(tmp, name + ".elf")
        open(p, "wb").write(wrap(raw, base=PM_BASE, entry=PM_BASE))
        meta = dict(file_offset=int(name[3:], 16), size=len(raw), base=PM_BASE, entry_off=0)
        jobs.append((name, "pm", p, ["--extra-funcs", ",".join(hex(x) for x in seeds)], meta, pt, out))
    jobs = [j for j in jobs if j[1].replace("elfseg", "elf") in kinds]
    if a.only:
        keep = set(a.only.split(","))
        jobs = [j for j in jobs if j[0] in keep]

    with ProcessPoolExecutor(max_workers=a.j) as ex:
        results = list(ex.map(lift_one, jobs))
    results.sort(key=lambda r: (r["kind"], r["file_offset"]))
    json.dump(results, open(os.path.join(out, "spu_lift.json"), "w"), indent=1)
    open(os.path.join(out, "eboot_ver"), "w").write(kz2ver.VER + "\n")
    bad = [r["name"] for r in results if not r["ok"]]
    tot_f = sum(r.get("functions", 0) for r in results)
    tot_u = {}
    for r in results:
        for k, v in r.get("unsupported", {}).items():
            tot_u[k] = tot_u.get(k, 0) + v
    print(f"coverage seeds: {sum(len(v) for v in cov.values())} rows, dropped (outside code) {dropped}")
    print(f"images {len(results)}  failed {len(bad)} {bad}")
    print(f"functions {tot_f}  instructions {sum(r.get('insns', 0) for r in results)}")
    print("unsupported:", ", ".join(f"{k} {v}" for k, v in sorted(tot_u.items(), key=lambda kv: -kv[1])) or "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
