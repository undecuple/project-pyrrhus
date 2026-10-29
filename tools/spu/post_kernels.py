#!/usr/bin/env python3
"""Find SPU subroutines that are the same code in several job images (the shared Gfx.Post kernels).

  tools/spu/post_kernels.py DIS... [--hot FILE] [--min 8]

DIS are disassemblies from tools/spu/disasm_image.py (one per job image). A subroutine is a `brsl $r0` target; it
extends to the last `bi $r0` before the next target. Each instruction is normalised so code that sits at another
address compares equal: a PC-relative branch or hint keeps its target as an offset from the subroutine start when
the target is inside it (else `ext`), and a PC-relative load (lqr) is replaced by the 16 bytes it loads from the
image (the constant itself, so two kernels with different constants do not match). Absolute immediates (il, ila,
...) are kept as they are: an LS address in one image and another address in a second image is a difference.
Prints every group of two or more images whose subroutines normalise to the same sequence, with their addresses and
sizes. --hot FILE (tools/runtime/perf/prof_resolve.py --job output, any number of `-- ovlN` sections) also maps each
hot lifted function (`<image>_spu_func_<addr>`) to its enclosing subroutine and that subroutine's group.

Output derives from the game's code: write it under work/, never commit it.
"""
import argparse
import bisect
import hashlib
import os
import re
import struct
from collections import defaultdict

LINE = re.compile(r"^([0-9A-F]{8}):\s+([0-9A-F]{8})\s+(\S+)\s*(.*)$")
PCREL_BR = {"br", "brz", "brnz", "brhz", "brhnz", "brsl"}
PCREL_HINT = {"hbrr"}
PCREL_LD = {"lqr", "stqr"}


def load(path):
    ins = []
    for line in open(path):
        m = LINE.match(line)
        if m:
            ins.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3), m.group(4).strip()))
    return ins


def subs(ins):
    words = {a: w for a, w, _, _ in ins}
    targets = sorted({int(op.split(",")[-1].strip(), 16) for a, w, mn, op in ins
                      if mn == "brsl" and op.startswith("$r0,")})
    out = {}
    idx = {a: i for i, (a, _, _, _) in enumerate(ins)}
    for k, t in enumerate(targets):
        nxt = targets[k + 1] if k + 1 < len(targets) else ins[-1][0] + 4
        if t not in idx:
            continue
        end = None
        for a, w, mn, op in ins[idx[t]:]:
            if a >= nxt:
                break
            if mn == "bi" and op.startswith("$r0"):
                end = a + 4
        if end:
            out[t] = (t, end)
    return out, words


def norm(ins_range, s, e, words):
    toks = []
    for a, w, mn, op in ins_range:
        if mn in PCREL_BR or mn in PCREL_LD or mn in PCREL_HINT:
            parts = [p.strip() for p in op.split(",")]
            vals = []
            for p in parts:
                if re.fullmatch(r"0x[0-9A-F]+", p):
                    v = int(p, 16)
                    if mn in PCREL_LD:
                        q = v & ~15
                        vals.append("C" + "".join(f"{words.get(q + 4 * i, 0):08X}" for i in range(4)))
                    elif s <= v < e:
                        vals.append(f"+{v - s:X}")
                    else:
                        vals.append(f"ext{v:X}" if mn == "brsl" else "ext")
                else:
                    vals.append(p)
            toks.append(mn + " " + ",".join(vals))
        else:
            toks.append(f"{w:08X}")
    return toks


ALL_SRC = {"stqd", "stqx", "stqa", "stqr", "brz", "brnz", "brhz", "brhnz", "biz", "binz", "bihz", "bihnz", "bi", "wrch",
           "hbr", "heq", "heqi", "hgt", "hgti", "hlgt", "hlgti"}
RT_ALSO_SRC = {"iohl", "addx", "sfx", "cgx", "bgx", "mpyhha", "mpyhhau", "dfma", "dfms", "dfnma", "dfnms"}
COND = {"brz", "brnz", "brhz", "brhnz"}
SCRATCH = set(range(2, 80))


def regs(op):
    return [int(x) for x in re.findall(r"\$r(\d+)", op)]


def ila_target(ins, idx, pc, r):
    """`ila $rX, ADDR` shortly before `bi $rX` (the lifted code's constant indirect jump): ADDR, else None."""
    i = idx[pc]
    for k in range(i - 1, max(i - 6, -1), -1):
        _, _, mn, op = ins[k]
        rs = regs(op)
        if rs[:1] == [r]:
            m = re.match(r"ila\s*$", mn) and re.search(r"0x([0-9A-F]+)\s*$", op)
            return int(m.group(1), 16) if m else None
    return None


class Flow:
    """Inter-procedural scratch-register liveness over one image's disassembly."""

    def __init__(self, ins, idx):
        self.ins, self.idx = ins, idx
        self.callers = defaultdict(list)
        for a, _, mn, op in ins:
            if mn == "brsl" and op.startswith("$r0,"):
                self.callers[int(op.split(",")[-1], 16)].append(a)
        self.starts = sorted(self.callers)
        self.summ = {}

    def enclosing(self, pc):
        k = bisect.bisect_right(self.starts, pc) - 1
        return self.starts[k] if k >= 0 else None

    def reads(self, t):
        """Scratch registers a subroutine may read before writing them (its arguments), callees included."""
        if t in self.summ:
            return self.summ[t]
        self.summ[t] = set(range(3, 11))   # recursion guard: the ABI's argument registers
        iss = self.walk(t, frozenset(SCRATCH), inter=False)
        self.summ[t] = {r for r, _, _ in iss if r >= 0}
        return self.summ[t]

    def walk(self, start, u0, inter=True, max_steps=200000):
        ins, idx = self.ins, self.idx
        unw = {}
        work = [(start, u0)]
        issues = set()
        steps = 0
        while work and steps < max_steps:
            pc, u = work.pop()
            steps += 1
            old = unw.get(pc)
            if old is not None and u <= old:
                continue
            u = u | old if old is not None else u
            unw[pc] = u
            if pc not in idx:
                issues.add((-1, pc, "outside code"))
                continue
            _, _, mn, op = ins[idx[pc]]
            rs = regs(op)
            if mn in ALL_SRC:
                src, dst = rs, []
            elif mn in RT_ALSO_SRC:
                src, dst = rs, rs[:1]
            else:
                src, dst = rs[1:], rs[:1]
            tgt = re.findall(r"0x([0-9A-F]+)\s*$", op)
            nxt = []
            if mn == "brsl" and op.startswith("$r0,"):
                src = src + sorted(self.reads(int(tgt[0], 16)))
                nxt = [pc + 4]   # the callee's writes are not credited (conservative)
            elif mn == "bisl":
                src = src + list(range(3, 11))
                issues.add((-2, pc, "indirect call"))
                nxt = [pc + 4]
            elif mn == "bi" and rs == [0]:
                callers = self.callers.get(self.enclosing(pc), []) if inter else []
                if inter and not callers:
                    src = src + [3]
                nxt = [c + 4 for c in callers]
            elif mn == "bi":
                t = ila_target(ins, idx, pc, rs[0])
                if t is None:
                    issues.add((-2, pc, "indirect bi"))
                else:
                    nxt = [t]
            elif mn in ("biz", "binz", "bihz", "bihnz"):
                issues.add((-2, pc, "indirect " + mn))
                nxt = [pc + 4]
            elif mn in ("stop", "stopd", "brsl"):
                nxt = []
            elif mn == "br":
                nxt = [int(tgt[0], 16)]
            elif mn in COND:
                nxt = [int(tgt[0], 16), pc + 4]
            else:
                nxt = [pc + 4]
            for r in src:
                if r in u:
                    issues.add((r, pc, mn))
            u2 = u - set(dst)
            for n in nxt:
                work.append((n, u2))
        if work:
            issues.add((-3, start, "step limit"))
        return issues


def live_after(ins, idx, call_at, flow=None):
    """Scratch registers (r2-r79) the code may read after the call at call_at before writing them: a gated leaf that
    leaves its scratch registers different from the SPU code's is safe only when this is empty. Follows the caller,
    its returns into its own callers (every brsl site of the enclosing subroutine), and the subroutines it calls
    (by their own argument reads); a return from a subroutine nobody calls (the job entry) reads r3. Indirect calls
    and jumps that are not the lifted code's `ila`+`bi` pairs are reported. Returns a sorted list of (reg, pc, why)."""
    flow = flow or Flow(ins, idx)
    return sorted(flow.walk(call_at + 4, frozenset(SCRATCH)))


def image_bytes(elf):
    b = open(elf, "rb").read()
    phoff, = struct.unpack_from(">I", b, 0x1C)
    _, off, va, _, fs, _, _, _ = struct.unpack_from(">8I", b, phoff)
    return va, b[off:off + fs]


def pool_hash(img, va, lo, hi):
    """64-bit FNV-1a over little-endian 8-byte words of LS lo..hi (port/kz2/spu/native_common.c computes the same)."""
    h = 0xcbf29ce484222325
    for x in range(lo, hi, 8):
        v, = struct.unpack_from("<Q", img, x - va)
        h = ((h ^ v) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def emit_table(a, groups, gid, loaded):
    """Native gate rows for re/spu/native_gates.tsv and port/kz2/spu (C initialisers): one per (image, subroutine) of
    each family, with the constant pool its lqr loads read (LS range and hash: the gate checks the pool before the
    native code runs, so a different image or rewritten constants run the lifted code)."""
    import json
    man = {m["name"]: m for m in json.load(open(a.manifest))}
    skip = {(x.split("@")[0], int(x.split("@")[1], 16)) for x in a.skip}
    slot = a.slot0
    tsv, c = [], []
    for fam in a.table.split(","):
        name, what = fam.split("=")
        if what in gid.values():
            h = next(k for k, v in gid.items() if v == what)
            mem = sorted((i, s, e) for i, s, e in groups[h])
        else:
            i, s = what.split("@")
            s = int(s, 16)
            mem = [(i, s, next(e for (ii, ss, e) in sum(groups.values(), []) if ii == i and ss == s))]
        for img, s, e in mem:
            if (img, s) in skip:
                continue
            ins, idx = loaded[img]
            lq = [int(re.search(r"0x([0-9A-F]+)\s*$", op).group(1), 16) & ~15
                  for ad, _, mn, op in ins[idx[s]:idx[s] + (e - s) // 4] if mn == "lqr"]
            va, data = image_bytes(os.path.join(a.elf_dir, img + ".elf"))
            lo, hi = (min(lq), max(lq) + 16) if lq else (0, 0)
            ph = pool_hash(data, va, lo, hi) if lq else 0
            job = man[img]["label"] if img in man else img
            tsv.append(f"{img}\t0x{s:X}\t{slot}\t{job}\t{name}")
            c.append(f'    {{ {slot}, "{img}", 0x{s:X}u, 0x{lo:X}u, 0x{hi:X}u, 0x{ph:016x}ull }},   /* {job} */')
            slot += 1
    print("\n".join(tsv))
    print("\n".join(c))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dis", nargs="+")
    ap.add_argument("--hot")
    ap.add_argument("--min", type=int, default=8, help="smallest subroutine (instructions) to report")
    ap.add_argument("--table", metavar="SPEC", help="emit native gate rows: comma list of FAMILY=GROUP_OR_IMAGE@ADDR "
                    "(e.g. blend=K1,addb=K2,upsample4=job_00d51f00@0x56F0); slots from --slot0")
    ap.add_argument("--slot0", type=int, default=0)
    ap.add_argument("--elf-dir", default="work/spu/spu/elf_in")
    ap.add_argument("--manifest", default="work/spu/spu/kz2_spu_manifest.json")
    ap.add_argument("--skip", action="append", default=[], metavar="IMAGE@0xADDR", help="already gated: no row")
    ap.add_argument("--live", action="append", default=[], metavar="IMAGE@0xADDR",
                    help="check every call site of this subroutine (and of its whole group) for scratch registers read "
                         "after the call; 'K1' etc. names a group")
    a = ap.parse_args()
    groups = defaultdict(list)
    where = {}
    for p in a.dis:
        img = os.path.basename(p).split(".")[0]
        ins = load(p)
        idx = {x[0]: i for i, x in enumerate(ins)}
        ss, words = subs(ins)
        for t, (s, e) in ss.items():
            rng = ins[idx[s]:idx[s] + (e - s) // 4]
            toks = norm(rng, s, e, words)
            # a call out to another subroutine compares by that callee's own hash (computed below), not its address
            h = hashlib.sha1("\n".join(re.sub(r"ext[0-9A-F]+", "ext", x) for x in toks).encode()).hexdigest()[:12]
            groups[h].append((img, s, e))
            where[(img, s)] = (h, e)
    gid = {}
    for h, mem in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len({m[0] for m in mem}) < 2 or (mem[0][2] - mem[0][1]) // 4 < a.min:
            continue
        gid[h] = f"K{len(gid) + 1}"
        print(f"{gid[h]} {h} {(mem[0][2] - mem[0][1]) // 4} insns, {len({m[0] for m in mem})} images: " +
              " ".join(f"{i}@0x{s:X}" for i, s, _ in sorted(mem)))
    loaded = {}
    for p in a.dis:
        img = os.path.basename(p).split(".")[0]
        ins = load(p)
        loaded[img] = (ins, {x[0]: i for i, x in enumerate(ins)})
    for spec in a.live:
        if spec in gid.values():
            h = next(k for k, v in gid.items() if v == spec)
            targets = [(i, s) for i, s, _ in groups[h]]
        else:
            i, s = spec.split("@")
            targets = [(i, int(s, 16))]
        for img, t in targets:
            ins, idx = loaded[img]
            sites = [x[0] for x in ins if x[2] == "brsl" and x[3].startswith("$r0,") and
                     int(x[3].split(",")[-1], 16) == t]
            flow = Flow(ins, idx)
            for c in sites:
                iss = live_after(ins, idx, c, flow)
                print(f"live {img}@0x{t:X} call 0x{c:X}: " + ("ok" if not iss else
                      " ".join(f"r{r}@0x{pc:X}({w})" if r >= 0 else f"{w}@0x{pc:X}" for r, pc, w in iss[:12])))
            if not sites:
                print(f"live {img}@0x{t:X}: no brsl call site")
    if a.table:
        emit_table(a, groups, gid, loaded)
    if a.hot:
        cur = None
        for line in open(a.hot):
            m = re.match(r"-- (ovl\d+)", line)
            if m:
                cur = m.group(1)
                print(f"-- {cur}")
                continue
            m = re.match(r"\s*(\d+)\s+([\d.]+)%\s+(\w+?)_spu_func_([0-9A-F]+)\b", line)
            if not m:
                continue
            img, addr = m.group(3), int(m.group(4), 16)
            enc = [(s, v) for (i, s), v in where.items() if i == img and s <= addr < v[1]]
            if enc:
                s, (h, e) = max(enc)
                print(f"   {m.group(1):>6} {m.group(2):>5}%  {img} 0x{addr:X} in sub 0x{s:X}-0x{e:X} "
                      f"{gid.get(h, 'own')}")
            else:
                print(f"   {m.group(1):>6} {m.group(2):>5}%  {img} 0x{addr:X} (job body, not a brsl subroutine)")


if __name__ == "__main__":
    main()
