#!/usr/bin/env python3
"""Symbolic trace of an SPU subroutine: the dataflow behind a software-pipelined loop, per stored quadword.

  tools/spu/spu_symtrace.py IMAGE.dis --image IMAGE.elf --entry 0x5F80 --reg r3=0x20000 --reg r6=2 \
      --sym r4=A@0x30000 --sym r5=B@0x31000 [--branch 0x57EC=0] [--mem 0x30000=00ff..] [--max-steps N] [--show N]

Executes the disassembly (tools/spu/disasm_image.py output) from --entry until the `bi $r0` that returns to the
start link. Integer work on concrete values is computed exactly (addresses, counters, constants read from the
image's own bytes); everything that depends on input data stays symbolic: a quadword loaded from a --sym buffer
is `A[off]`, and every operation on a symbolic value is an expression node (`fa(x, y)`, `shufb(a, b, mask)`, ...).
Each store prints its address and the expression it stores, with shared subexpressions named once, so the
per-iteration formula of a pipelined loop can be read off in program order (the native DepthOfField
kernels). A branch on a symbolic value needs --branch PC=0|1 (taken or not); otherwise the trace stops there.

Output is derived from the game's code: keep it under work/, never commit it.
"""
import argparse
import re
import struct
import sys

M32 = 0xFFFFFFFF


class Sym:
    __slots__ = ("op", "args", "imm", "id", "h")
    tab = {}
    n = 0

    def __new__(cls, op, args=(), imm=None):
        key = (op, tuple(id(a) if isinstance(a, Sym) else a for a in args), imm)
        o = Sym.tab.get(key)
        if o is not None:
            return o
        o = object.__new__(cls)
        o.op, o.args, o.imm = op, tuple(args), imm
        Sym.n += 1
        o.id = Sym.n
        Sym.tab[key] = o
        return o


def is_c(v):
    return isinstance(v, bytes)


def W(v):
    return list(struct.unpack(">4I", v))


def pW(x):
    return struct.pack(">4I", *[e & M32 for e in x])


def H(v):
    return list(struct.unpack(">8H", v))


def pH(x):
    return struct.pack(">8H", *[e & 0xFFFF for e in x])


def sx(v, n):
    v &= (1 << n) - 1
    return v - (1 << n) if v >> (n - 1) else v


def shufb(a, b, c):
    ab = a + b
    out = []
    for x in c:
        if x & 0x80:
            out.append(0x00 if (x & 0xC0) == 0x80 else (0xFF if (x & 0xE0) == 0xC0 else 0x80))
        else:
            out.append(ab[x & 0x1F])
    return bytes(out)


def splat(x):
    return pW([x] * 4)


# concrete integer semantics (enough for addresses, counters and masks)
def c_rr(mn, a, b):
    A, B = W(a), W(b)
    if mn == "a":
        return pW([x + y for x, y in zip(A, B)])
    if mn == "sf":
        return pW([y - x for x, y in zip(A, B)])
    if mn == "and":
        return pW([x & y for x, y in zip(A, B)])
    if mn == "or":
        return pW([x | y for x, y in zip(A, B)])
    if mn == "xor":
        return pW([x ^ y for x, y in zip(A, B)])
    if mn == "cgt":
        return pW([M32 if sx(x, 32) > sx(y, 32) else 0 for x, y in zip(A, B)])
    if mn == "clgt":
        return pW([M32 if x > y else 0 for x, y in zip(A, B)])
    if mn == "ceq":
        return pW([M32 if x == y else 0 for x, y in zip(A, B)])
    if mn in ("mpyu", "mpy", "mpyh", "mpys"):
        r = []
        for x, y in zip(A, B):
            if mn == "mpyu":
                r.append((x & 0xFFFF) * (y & 0xFFFF))
            elif mn == "mpy":
                r.append(sx(x, 16) * sx(y, 16))
            elif mn == "mpyh":
                r.append(((x >> 16) * (y & 0xFFFF)) << 16)
            else:
                r.append((sx(x, 16) * sx(y, 16)) >> 16)
        return pW(r)
    if mn == "cg":
        return pW([1 if x + y > M32 else 0 for x, y in zip(A, B)])
    if mn in ("mpyhhu", "mpyhh"):
        return pW([((x >> 16) * (y >> 16)) if mn == "mpyhhu" else sx(x >> 16, 16) * sx(y >> 16, 16)
                   for x, y in zip(A, B)])
    if mn in ("ceqh", "cgth"):
        h1, h2 = H(a), H(b)
        return pH([0xFFFF if (x == y if mn == "ceqh" else sx(x, 16) > sx(y, 16)) else 0 for x, y in zip(h1, h2)])
    if mn == "rotqby":
        n = B[0] & 15
        return a[n:] + a[:n]
    if mn in ("xsbh", "xshw", "xswd"):   # an earlier change (Vignette, BloomIntegrate): the disassembler lists a second $r0
        if mn == "xsbh":
            return pH([sx(x & 0xFF, 8) for x in H(a)])
        if mn == "xshw":
            return pW([sx(x & 0xFFFF, 16) for x in A])
        q = struct.unpack(">2Q", a)
        return struct.pack(">2q", *[sx(x & M32, 32) for x in q])
    if mn == "shlqby":
        n = B[0] & 31
        return (a + bytes(32))[n:n + 16] if n < 16 else bytes(16)
    return None


def c_ri(mn, a, imm):
    A = W(a)
    if mn == "ai":
        return pW([x + imm for x in A])
    if mn == "andi":
        return pW([x & (imm & M32) for x in A])
    if mn == "ori":
        return pW([x | (imm & M32) for x in A])
    if mn == "xori":
        return pW([x ^ (imm & M32) for x in A])
    if mn == "ceqi":
        return pW([M32 if x == (imm & M32) else 0 for x in A])
    if mn == "cgti":
        return pW([M32 if sx(x, 32) > imm else 0 for x in A])
    if mn == "clgti":
        return pW([M32 if x > (imm & M32) else 0 for x in A])
    if mn == "shli":
        n = imm & 0x3F
        return pW([(x << n) if n < 32 else 0 for x in A])
    if mn == "rotmi":
        n = (-imm) & 0x3F
        return pW([(x >> n) if n < 32 else 0 for x in A])
    if mn == "rotmai":
        n = (-imm) & 0x3F
        return pW([(sx(x, 32) >> min(n, 31)) for x in A])
    if mn == "rothmi":
        n = (-imm) & 0x1F
        return pH([(x >> n) if n < 16 else 0 for x in H(a)])
    if mn == "rotqbyi":
        n = imm & 15
        return a[n:] + a[:n]
    if mn == "shlqbyi":
        n = imm & 31
        return (a + bytes(32))[n:n + 16] if n < 16 else bytes(16)
    if mn == "rotqbii":
        n = imm & 7
        v = int.from_bytes(a, "big")
        v = ((v << n) | (v >> (128 - n))) & ((1 << 128) - 1)
        return v.to_bytes(16, "big")
    if mn in ("cbd", "chd", "cwd", "cdd"):   # insertion masks from a concrete address
        sz = {"cbd": 1, "chd": 2, "cwd": 4, "cdd": 8}[mn]
        t = (A[0] + imm) & 0xF & ~(sz - 1)
        m = bytearray(range(0x10, 0x20))
        for i in range(sz):
            m[t + i] = (4 - sz if sz < 4 else 0) + i if sz < 4 else i
        if sz == 1:
            m[t] = 3
        elif sz == 2:
            m[t], m[t + 1] = 2, 3
        return bytes(m)
    if mn in ("ceqbi", "cgtbi", "clgtbi"):   # an earlier change
        v = imm & 0xFF
        return bytes(0xFF if (x == v if mn == "ceqbi" else (sx(x, 8) > sx(v, 8) if mn == "cgtbi" else x > v)) else 0
                     for x in a)
    if mn in ("ceqhi", "cgthi"):
        return pH([0xFFFF if (x == (imm & 0xFFFF) if mn == "ceqhi" else sx(x, 16) > imm) else 0 for x in H(a)])
    if mn == "sfi":
        return pW([imm - x for x in A])
    if mn == "mpyui":
        return pW([(x & 0xFFFF) * (imm & 0xFFFF) for x in A])
    if mn == "mpyi":
        return pW([sx(x, 16) * imm for x in A])
    return None


# An earlier change (--cfloat): concrete single-precision float ops, approximate SPU semantics (denormals flushed, frest + fi
# as an exact reciprocal, no extended range). Only for reading formulas whose addresses depend on float math (ILR's
# ray taps); the diff test against the lifted code is the exactness check, never this.
CFLOAT = [False]


def f32(u):
    return struct.unpack(">f", struct.pack(">I", u & M32))[0]


def u32f(x):
    try:
        b = struct.pack(">f", x)
    except OverflowError:
        b = struct.pack(">f", float("inf") if x > 0 else float("-inf"))
    u = struct.unpack(">I", b)[0]
    return u & 0x80000000 if (u & 0x7F800000) == 0 else u   # flush denormals (sign kept)


def fl(a):
    return [f32(x) if (x & 0x7F800000) else 0.0 for x in W(a)]


def c_float(mn, src, imm):
    if not CFLOAT[0]:
        return None
    try:
        if mn in ("fm", "fa", "fs") and len(src) >= 2:
            A, B = fl(src[0]), fl(src[1])
            return pW([u32f(x * y if mn == "fm" else x + y if mn == "fa" else x - y) for x, y in zip(A, B)])
        if mn in ("fma", "fnms", "fms") and len(src) == 3:
            A, B, C = fl(src[0]), fl(src[1]), fl(src[2])
            return pW([u32f(x * y + z if mn == "fma" else z - x * y if mn == "fnms" else x * y - z)
                       for x, y, z in zip(A, B, C)])
        if mn == "frest":
            return pW([u32f(1.0 / x) if x else 0x7F7FFFFF for x in fl(src[0])])
        if mn == "frsqest":
            return pW([u32f(abs(x) ** -0.5) if x else 0x7F7FFFFF for x in fl(src[0])])
        if mn == "fi":
            return src[1]
        if mn in ("fcgt", "fceq", "fcmgt", "fcmeq"):
            A, B = fl(src[0]), fl(src[1])
            if mn in ("fcmgt", "fcmeq"):
                A, B = [abs(x) for x in A], [abs(x) for x in B]
            return pW([M32 if (x > y if mn in ("fcgt", "fcmgt") else x == y) else 0 for x, y in zip(A, B)])
        if mn in ("cflts", "cfltu") and imm is not None:
            sc = 2.0 ** (173 - imm)
            r = []
            for x in fl(src[0]):
                v = x * sc
                v = int(v) if v == v and abs(v) != float("inf") else (0 if v != v else (1 << 40) * (1 if v > 0 else -1))
                r.append(max(-(1 << 31), min((1 << 31) - 1, v)) if mn == "cflts" else max(0, min(M32, v)))
            return pW(r)
        if mn in ("csflt", "cuflt") and imm is not None:
            sc = 2.0 ** (imm - 155)
            return pW([u32f((sx(x, 32) if mn == "csflt" else x) * sc) for x in W(src[0])])
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    return None


class Tr:
    def __init__(self, insns, ls):
        self.ins = insns
        self.ls = ls                 # bytearray 256 KB, concrete image/data
        self.mem = {}                # line addr -> Sym (symbolic quadword)
        self.r = [bytes(16)] * 128
        self.stores = []
        self.branch = {}
        self.steps = 0
        self.nostore = []
        self.dump = set()

    def ld(self, ea):
        if not is_c(ea):
            return Sym("ldx", (ea,))
        a = W(ea)[0] & 0x3FFF0
        if a in self.mem:
            return self.mem[a]
        return bytes(self.ls[a:a + 16])

    def st(self, ea, v, pc):
        if not is_c(ea):
            self.stores.append((pc, ea, v))
            return
        a = W(ea)[0] & 0x3FFF0
        self.stores.append((pc, a, v))
        if any(lo <= a < hi for lo, hi in self.nostore):
            return
        if is_c(v):
            self.mem.pop(a, None)
            self.ls[a:a + 16] = v
        else:
            self.mem[a] = v

    def run(self, pc, max_steps):
        ret = W(self.r[0])[0] & 0x3FFFC
        while self.steps < max_steps:
            self.steps += 1
            if pc not in self.ins:
                print(f"; pc 0x{pc:05X} not in the disassembly", file=sys.stderr)
                return
            mn, ops = self.ins[pc]
            nxt = pc + 4
            if pc in self.dump:   # --dump PC prints the registers the first time PC is reached
                self.dump.discard(pc)
                print(f"; regs at 0x{pc:05X} (step {self.steps}):")
                for i, v in enumerate(self.r):
                    print(f";   r{i} = {v.hex().upper() if is_c(v) else 'sym ' + str(getattr(v, 'op', '?'))}")
            regs = [int(x[2:]) for x in ops if x.startswith("$r")]
            imms = [x for x in ops if not x.startswith("$r")]
            g = self.r
            if mn in ("nop", "lnop", "hbr", "hbrr", "hbra"):
                pass
            elif mn == "bi":
                t = g[regs[0]]
                if not is_c(t):
                    print(f"; symbolic bi at 0x{pc:05X}", file=sys.stderr)
                    return
                tt = W(t)[0] & 0x3FFFC
                if tt == ret and regs[0] == 0:
                    return
                nxt = tt
            elif mn in ("binz", "biz", "bihnz", "bihz"):   # Modulate's 8-byte pass returns by binz $r0
                v, t = g[regs[0]], g[regs[1]]
                if not is_c(v) or not is_c(t):
                    print(f"; symbolic {mn} at 0x{pc:05X}", file=sys.stderr)
                    return
                w = W(v)[0] & (0xFFFF if mn.startswith("bih") else M32)
                if (w != 0) == mn.endswith("nz"):
                    tt = W(t)[0] & 0x3FFFC
                    if tt == ret and regs[1] == 0:
                        return
                    nxt = tt
            elif mn in ("br", "brsl", "bra"):
                t = int(imms[-1], 16)
                if mn == "brsl":
                    g[regs[0]] = splat(pc + 4)
                nxt = t
            elif mn in ("brnz", "brz", "brhnz", "brhz"):
                v = g[regs[0]]
                if is_c(v):
                    w = W(v)[0]
                    if mn.startswith("brh"):
                        w &= 0xFFFF
                    take = (w != 0) == mn.endswith("nz")
                elif pc in self.branch:
                    take = self.branch[pc]
                else:
                    print(f"; symbolic {mn} at 0x{pc:05X}: give --branch 0x{pc:X}=0|1", file=sys.stderr)
                    return
                if take:
                    nxt = int(imms[-1], 16)
            elif mn in ("lqd", "lqx", "lqr", "lqa"):
                if mn == "lqd":
                    ea = self.addr(g[regs[1]], int(imms[0], 16) if imms else 0)
                elif mn == "lqx":
                    ea = self.addx(g[regs[1]], g[regs[2]])
                else:
                    ea = splat(int(imms[0], 16))
                g[regs[0]] = self.ld(ea)
            elif mn in ("stqd", "stqx", "stqr", "stqa"):
                if mn == "stqd":
                    ea = self.addr(g[regs[1]], int(imms[0], 16) if imms else 0)
                elif mn == "stqx":
                    ea = self.addx(g[regs[1]], g[regs[2]])
                else:
                    ea = splat(int(imms[0], 16))
                self.st(ea, g[regs[0]], pc)
            elif mn in ("il", "ila", "ilh", "ilhu", "iohl", "fsmbi"):
                v = int(imms[0], 0)
                if mn == "il":
                    g[regs[0]] = splat(v)
                elif mn == "ila":
                    g[regs[0]] = splat(v & 0x3FFFF)
                elif mn == "ilh":
                    g[regs[0]] = pH([v] * 8)
                elif mn == "ilhu":
                    g[regs[0]] = splat((v & 0xFFFF) << 16)
                elif mn == "iohl":
                    old = g[regs[0]]
                    g[regs[0]] = pW([x | (v & 0xFFFF) for x in W(old)]) if is_c(old) else Sym("iohl", (old,), v)
                else:
                    g[regs[0]] = bytes(0xFF if (v >> (15 - i)) & 1 else 0 for i in range(16))
            else:
                self.alu(mn, regs, imms)
            pc = nxt
        print("; step limit", file=sys.stderr)

    def addr(self, base, off):
        if is_c(base):
            return splat((W(base)[0] + off) & 0x3FFF0)
        return Sym("+", (base,), off)

    def addx(self, a, b):
        if is_c(a) and is_c(b):
            return splat((W(a)[0] + W(b)[0]) & 0x3FFF0)
        return Sym("+x", (a, b))

    def alu(self, mn, regs, imms):
        g = self.r
        rt = regs[0]
        src = [g[x] for x in regs[1:]]
        if mn in ("addx", "sfx") and all(is_c(x) for x in src + [g[rt]]):
            A, B, T = W(src[0]), W(src[1]), W(g[rt])
            g[rt] = pW([(x + y + (z & 1)) if mn == "addx" else (y - x - (1 - (z & 1))) for x, y, z in zip(A, B, T)])
            return
        if mn in ("addx", "sfx"):
            src = src + [g[rt]]
        imm = None
        if imms:
            s = imms[0]
            imm = int(s, 16) if s.startswith("0x") or s.startswith("-0x") else int(s)
        if all(is_c(x) for x in src):
            res = None
            if mn in ("fm", "fa", "fs", "fma", "fnms", "fms", "frest", "frsqest", "fi", "fcgt", "fceq", "fcmgt",
                      "fcmeq", "cflts", "cfltu", "csflt", "cuflt"):
                res = c_float(mn, src, imm)
            elif mn in ("fsm", "fsmh", "fsmb") and imm is None:   # an earlier change (the disassembler may list a second $r0)
                v = W(src[0])[0]
                if mn == "fsm":
                    res = pW([M32 if (v >> (3 - i)) & 1 else 0 for i in range(4)])
                elif mn == "fsmh":
                    res = pH([0xFFFF if (v >> (7 - i)) & 1 else 0 for i in range(8)])
                else:
                    res = bytes(0xFF if (v >> (15 - i)) & 1 else 0 for i in range(16))
            elif len(src) == 2 and imm is None:
                res = c_rr(mn, *src)
            elif len(src) == 1 and imm is not None:
                res = c_ri(mn, src[0], imm)
            elif mn == "shufb":
                res = shufb(*src)
            elif mn == "selb":
                a, b, c = src
                res = bytes((x & ~m | y & m) & 0xFF for x, y, m in zip(a, b, c))
            elif mn in ("fm", "fa", "fs", "fma", "fnms", "fms", "frest", "frsqest", "fi", "fcgt", "fceq", "fcmgt",
                        "fcmeq", "cflts", "cfltu", "csflt", "cuflt"):
                res = c_float(mn, src, imm)
            elif mn == "mpya" and len(src) == 3:   # s16(a) * s16(b) + c
                res = pW([sx(x, 16) * sx(y, 16) + z for x, y, z in zip(W(src[0]), W(src[1]), W(src[2]))])
            elif mn == "gb":
                res = splat(sum(((w & 1) << (3 - i)) for i, w in enumerate(W(src[0]))))
            if res is not None:
                g[rt] = res
                return
        # symbolic: name the shuffle masks by their bytes, they are constant
        g[rt] = Sym(mn, tuple(src), imm)


def parse_dis(path):
    ins = {}
    for line in open(path):
        m = re.match(r"([0-9A-F]{8}):\s+[0-9A-F]{8}\s+(\S+)\s*(.*)$", line)
        if not m:
            continue
        ops = [o.strip() for o in m.group(3).replace("(", ",").replace(")", "").split(",") if o.strip()]
        ins[int(m.group(1), 16)] = (m.group(2), ops)
    return ins


def load_elf(path, ls):
    b = open(path, "rb").read()
    phoff, = struct.unpack_from(">I", b, 0x1C)
    phentsize, phnum = struct.unpack_from(">HH", b, 0x2A)
    for i in range(phnum):
        p_type, p_off, p_vaddr, _, p_filesz, _, _, _ = struct.unpack_from(">8I", b, phoff + i * phentsize)
        if p_type == 1:
            ls[p_vaddr:p_vaddr + p_filesz] = b[p_off:p_off + p_filesz]


def fmt_c(v):
    w = W(v)
    if w[0] == w[1] == w[2] == w[3]:
        return f"#{w[0]:08X}"
    return "#" + v.hex().upper()


class Printer:
    def __init__(self, names):
        self.names = names   # Sym id -> name for symbolic inputs
        self.done = {}
        self.lines = []
        self.k = 0

    def ref(self, v):
        if is_c(v):
            return fmt_c(v)
        if v.id in self.done:
            return self.done[v.id]
        if v.op == "in":
            return v.imm
        args = [self.ref(a) for a in v.args]
        if v.op == "+":
            s = f"{args[0]}+0x{v.imm & 0x3FFFF:X}" if v.imm >= 0 else f"{args[0]}-0x{-v.imm:X}"
            self.done[v.id] = s
            return s
        if v.op == "ldx":
            s = f"LS[{args[0]}]"
        else:
            s = f"{v.op}({', '.join(args)}{'' if v.imm is None else ', ' + str(v.imm)})"
        self.k += 1
        nm = f"t{self.k}"
        self.lines.append(f"  {nm} = {s}")
        self.done[v.id] = nm
        return nm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dis")
    ap.add_argument("--image", required=True)
    ap.add_argument("--entry", required=True)
    ap.add_argument("--reg", action="append", default=[], help="rN=VALUE (splat)")
    ap.add_argument("--sym", action="append", default=[],
                    help="rN=NAME@ADDR: rN = ADDR, and the quadwords from ADDR up are symbolic NAME[off]; "
                         "rN=NAME: rN itself is symbolic")
    ap.add_argument("--symbuf", action="append", default=[], help="NAME@ADDR+SIZE: symbolic buffer only")
    ap.add_argument("--branch", action="append", default=[])
    ap.add_argument("--max-steps", type=int, default=2000000)
    ap.add_argument("--show", type=int, default=16, help="stores to print (from --skip)")
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--range", default="", help="only stores into LO-HI (hex)")
    ap.add_argument("--nostore", action="append", default=[],
                    help="LO-HI (hex): stores there are logged but do not change memory (keeps an input symbolic)")
    ap.add_argument("--regfile", help="start registers from a --dump listing")
    ap.add_argument("--dump", action="append", default=[], help="PC: print the registers when it is first reached")
    ap.add_argument("--state", help="start from a KZ2_NATIVE_REC record: its local store and registers")
    ap.add_argument("--cfloat", action="store_true",
                    help="evaluate float ops on concrete values (approximate SPU semantics; an earlier change)")
    ap.add_argument("--mem", action="append", default=[],
                    help="ADDR=HEX: concrete big-endian bytes at ADDR (parameter blocks)")
    a = ap.parse_args()
    CFLOAT[0] = a.cfloat
    ls = bytearray(0x40000)
    load_elf(a.image, ls)
    for s in a.mem:
        ad, hx = s.split("=")
        b = bytes.fromhex(hx)
        ls[int(ad, 0):int(ad, 0) + len(b)] = b
    st_regs = None
    if a.state:   # a KZ2_NATIVE_REC record (port/kz2/spu/kz2_native_jobs.h layout): its LS and registers
        rec = open(a.state, "rb").read()
        assert rec[:8] == b"KZ2NJ001", "not a KZ2_NATIVE_REC record"
        st_regs = [struct.pack(">4I", *struct.unpack_from("<4I", rec, 24 + 16 * i)) for i in range(128)]
        ls[:] = rec[24 + 2048:24 + 2048 + 0x40000]
    t = Tr(parse_dis(a.dis), ls)
    t.r[0] = splat(0x3FF00)
    t.r[1] = splat(0x3F000)
    if st_regs:
        t.r = list(st_regs)
    if a.regfile:   # full quadwords, lines "rN = HEX" as --dump prints them (after a '; ')
        for line in open(a.regfile):
            m = re.match(r"[;\s]*r(\d+) = ([0-9A-F]{32})\s*$", line)
            if m:
                t.r[int(m.group(1))] = bytes.fromhex(m.group(2))
    for s in a.reg:
        k, v = s.split("=")
        t.r[int(k[1:])] = splat(int(v, 0))
    bufs = []
    for s in a.sym:
        k, v = s.split("=")
        if "@" in v:
            nm, ad = v.split("@")
            t.r[int(k[1:])] = splat(int(ad, 0))
            bufs.append((nm, int(ad, 0), 0x8000))
        else:
            t.r[int(k[1:])] = Sym("in", (), v)
    for s in a.symbuf:
        nm, rest = s.split("@")
        ad, sz = rest.split("+")
        bufs.append((nm, int(ad, 0), int(sz, 0)))
    for nm, ad, sz in bufs:
        for off in range(0, sz, 16):
            t.mem[(ad + off) & 0x3FFF0] = Sym("in", (), f"{nm}[0x{off:X}]")
    t.nostore = [tuple(int(x, 16) for x in s.split("-")) for s in a.nostore]
    t.dump = {int(x, 16) for x in a.dump}
    for s in a.branch:
        k, v = s.split("=")
        t.branch[int(k, 16)] = v == "1"
    t.run(int(a.entry, 16), a.max_steps)
    lo, hi = (int(x, 16) for x in a.range.split("-")) if a.range else (0, 1 << 20)
    st = [s for s in t.stores if not isinstance(s[1], int) or lo <= s[1] < hi]
    print(f"; {t.steps} steps, {len(t.stores)} stores ({len(st)} in range), {Sym.n} nodes")
    p = Printer({})
    for pc, ea, v in st[a.skip:a.skip + a.show]:
        r = p.ref(v)
        where = f"0x{ea:05X}" if isinstance(ea, int) else p.ref(ea)
        for l in p.lines:
            print(l)
        p.lines = []
        print(f"ST @0x{pc:05X} [{where}] = {r}")
    for i, v in enumerate(t.r):
        if not is_c(v) and i in (3,):
            pass


if __name__ == "__main__":
    main()
