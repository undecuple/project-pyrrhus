#!/usr/bin/env python3
"""Symbolic dataflow of a straight-line SPU function with one counted loop.

  tools/spu/loop_dataflow.py DIS START END --ptr r3,r4,... [--iters N] [--const-lo A --const-hi B]

DIS is a disassembly from tools/spu/disasm_image.py (derived from the game binary: keep it and this tool's output under
work/). The code from START up to END (exclusive) is executed symbolically: the registers named by --ptr are pointers
(`ai` moves them, quadword loads from them are inputs `name+offset`), constants loaded with lqr come from the
disassembly's own words, every other register starts as the symbol `rN`. A backward `brnz` to an address inside the
range is taken N times (--iters, default 3) and then falls through; the loop counter is never compared. Every `stqd`
prints the four word expressions it stores, as a DAG with shared nodes named once. A software-pipelined loop shows
up as stores whose inputs carry the previous iteration's offsets, so the output gives each vertex's formula with the
operand order of every float operation (which bit-exact native code must keep).

Covered: lqd lqr stqd ai andi il ilhu iohl or and selb shufb (constant masks) shlqby/rotqmby/or as an unaligned
16-byte load from a pointer, shlqbyi, mpya, xsbh, xshw, csflt cuflt cflts, fm fa fs fma, frsqest, fi, rotm, fsm (a
constant), nop lnop hbrr. Anything else stops with an error.
"""
import argparse
import re
import sys

LINE = re.compile(r"^([0-9A-F]{8}):\s+([0-9A-F]{8})\s+(\S+)\s*(.*)$")


class N:
    """A hash-consed 32-bit word expression."""
    tab = {}

    def __new__(cls, op, *args):
        k = (op,) + args
        n = N.tab.get(k)
        if n is None:
            n = object.__new__(cls)
            n.op, n.args, n.id = op, args, len(N.tab)
            N.tab[k] = n
        return n


def C(v):
    return N("c", v & 0xFFFFFFFF)


def cval(n):
    return n.args[0] if n.op == "c" else None


class Reg:
    """16 byte slots, each (word node, byte index 0..3 big-endian) or ('cb', byte) for a constant byte."""

    def __init__(self, slots, tag=None):
        self.s = list(slots)
        self.tag = tag   # ('shl'|'rqm', ptrname, offset) for the unaligned-load pattern

    @staticmethod
    def words(ws):
        s = []
        for w in ws:
            v = cval(w)
            if v is not None:
                s += [("cb", (v >> (24 - 8 * i)) & 0xFF) for i in range(4)]
            else:
                s += [(w, i) for i in range(4)]
        return Reg(s)

    def word(self, i):
        sl = self.s[4 * i:4 * i + 4]
        if all(x[0] == "cb" for x in sl):
            return C(sl[0][1] << 24 | sl[1][1] << 16 | sl[2][1] << 8 | sl[3][1])
        if all(x[0] is sl[0][0] and x[1] == j for j, x in enumerate(sl)):
            return sl[0][0]
        return N("bytes", tuple(sl))


def lanewise(f, *regs):
    return Reg.words([f(*[r.word(i) for r in regs]) for i in range(4)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dis")
    ap.add_argument("start", type=lambda x: int(x, 16))
    ap.add_argument("end", type=lambda x: int(x, 16))
    ap.add_argument("--ptr", default="")
    ap.add_argument("--iters", type=int, default=3)
    a = ap.parse_args()

    code, words = {}, {}
    for ln in open(a.dis):
        m = LINE.match(ln)
        if not m:
            continue
        pc = int(m.group(1), 16)
        words[pc] = int(m.group(2), 16)
        code[pc] = (m.group(3), [x.strip() for x in m.group(4).split(",")] if m.group(4).strip() else [])

    R = {}
    ptrs = {p.strip(): 0 for p in a.ptr.split(",") if p.strip()}

    def get(r):
        if r not in R:
            if r in ptrs:
                R[r] = Reg.words([N("ptr", r, 0)] + [N("sym", r, i) for i in range(1, 4)])
            else:
                R[r] = Reg.words([N("sym", r, i) for i in range(4)])
        return R[r]

    def reg(t):
        return t.lstrip("$")

    def imm(t):
        return int(t, 0)

    def ptr_of(n):
        if n.op == "ptr":
            return n.args
        return None

    def load(base, off):
        p = ptr_of(base)
        if p is not None:
            name, o = p
            return Reg.words([N("in", name, o + off + 4 * i) for i in range(4)])
        return Reg.words([N("ld", base, off + 4 * i) for i in range(4)])

    stores = []
    trips = {}
    pc = a.start
    steps = 0
    while a.start <= pc < a.end:
        steps += 1
        if steps > 100000:
            sys.exit("too many steps")
        mn, ops = code[pc]
        nxt = pc + 4
        if mn in ("nop", "lnop", "hbrr", "hbr", "hbra"):
            pass
        elif mn == "lqr":
            ad = imm(ops[1]) & ~15
            R[reg(ops[0])] = Reg.words([C(words[ad + 4 * i]) for i in range(4)])
        elif mn == "lqd":
            m = re.match(r"(-?0x[0-9A-Fa-f]+|-?\d+)\((\$r\d+)\)", ops[1])
            off, b = int(m.group(1), 0), reg(m.group(2))
            R[reg(ops[0])] = load(get(b).word(0), off)
        elif mn == "stqd":
            m = re.match(r"(-?0x[0-9A-Fa-f]+|-?\d+)\((\$r\d+)\)", ops[1])
            off, b = int(m.group(1), 0), reg(m.group(2))
            stores.append((pc, get(b).word(0), off, [get(reg(ops[0])).word(i) for i in range(4)]))
        elif mn == "ai":
            v = imm(ops[2])

            def f(w, v=v):
                p = ptr_of(w)
                if p is not None:
                    return N("ptr", p[0], p[1] + v)
                c = cval(w)
                return C(c + v) if c is not None else N("ai", w, v)
            R[reg(ops[0])] = lanewise(f, get(reg(ops[1])))
        elif mn == "andi":
            v = imm(ops[2])

            def f(w, v=v):
                p = ptr_of(w)
                if p is not None and v == 15:
                    return N("al", p[0], p[1])
                c = cval(w)
                return C(c & v) if c is not None else N("andi", w, v & 0xFFFFFFFF)
            R[reg(ops[0])] = lanewise(f, get(reg(ops[1])))
        elif mn == "il":
            R[reg(ops[0])] = Reg.words([C(imm(ops[1]))] * 4)
        elif mn == "ilhu":
            R[reg(ops[0])] = Reg.words([C(imm(ops[1]) << 16)] * 4)
        elif mn == "iohl":
            R[reg(ops[0])] = lanewise(lambda w, v=imm(ops[1]): C(cval(w) | v) if cval(w) is not None else N("iohl", w, v),
                                      get(reg(ops[0])))
        elif mn in ("shlqby", "rotqmby"):
            src, sh = get(reg(ops[1])), get(reg(ops[2])).word(0)
            if sh.op == "ai" and sh.args[0].op == "al":
                sh = N("alm", sh.args[0].args[0], sh.args[0].args[1], sh.args[1])
            w0 = src.word(0)
            if w0.op != "in":
                sys.exit("%08X: %s of a non-input" % (pc, mn))
            R[reg(ops[0])] = Reg(src.s, ("shl" if mn == "shlqby" else "rqm", sh, w0.args[0], w0.args[1]))
        elif mn == "or":
            x, y = get(reg(ops[1])), get(reg(ops[2]))
            if x.tag and y.tag and {x.tag[0], y.tag[0]} == {"shl", "rqm"}:
                shl = x if x.tag[0] == "shl" else y
                al = shl.tag[1]
                if al.op != "al" or al.args[0] != shl.tag[2]:
                    sys.exit("%08X: unaligned pattern not understood" % pc)
                name, o = al.args
                R[reg(ops[0])] = Reg([(N("u8", name, o + i), 3) for i in range(16)])
            else:
                R[reg(ops[0])] = lanewise(lambda p, q: N("or", p, q), x, y)
        elif mn == "and":
            R[reg(ops[0])] = lanewise(lambda p, q: N("and", p, q), get(reg(ops[1])), get(reg(ops[2])))
        elif mn == "selb":
            R[reg(ops[0])] = lanewise(lambda p, q, m: N("selb", p, q, m), get(reg(ops[1])), get(reg(ops[2])),
                                      get(reg(ops[3])))
        elif mn == "shufb":
            A, B, M = get(reg(ops[1])), get(reg(ops[2])), get(reg(ops[3]))
            out = []
            for i in range(16):
                mw = M.word(i // 4)
                if cval(mw) is None:
                    sys.exit("%08X: shufb with a non-constant mask" % pc)
                c = (cval(mw) >> (24 - 8 * (i % 4))) & 0xFF
                if c & 0xC0 == 0x80:
                    out.append(("cb", 0))
                elif c & 0xE0 == 0xC0:
                    out.append(("cb", 0xFF))
                elif c & 0xE0 == 0xE0:
                    out.append(("cb", 0x80))
                else:
                    out.append((A if c < 16 else B).s[c & 15])
            R[reg(ops[0])] = Reg(out)
        elif mn == "shlqbyi":
            n = imm(ops[2]) & 31
            src = get(reg(ops[1]))
            R[reg(ops[0])] = Reg([src.s[i + n] if i + n < 16 else ("cb", 0) for i in range(16)])
        elif mn == "mpya":
            R[reg(ops[0])] = lanewise(lambda p, q, r: N("mpya", p, q, r), get(reg(ops[1])), get(reg(ops[2])),
                                      get(reg(ops[3])))
        elif mn in ("xsbh", "xshw", "frsqest"):
            R[reg(ops[0])] = lanewise(lambda p, mn=mn: N(mn, p), get(reg(ops[1])))
        elif mn in ("csflt", "cuflt", "cflts", "cfltu"):
            R[reg(ops[0])] = lanewise(lambda p, mn=mn, v=imm(ops[2]): N(mn, p, v), get(reg(ops[1])))
        elif mn in ("fm", "fa", "fs", "fi", "rotm"):
            R[reg(ops[0])] = lanewise(lambda p, q, mn=mn: N(mn, p, q), get(reg(ops[1])), get(reg(ops[2])))
        elif mn == "fma":
            R[reg(ops[0])] = lanewise(lambda p, q, r: N("fma", p, q, r), get(reg(ops[1])), get(reg(ops[2])),
                                      get(reg(ops[3])))
        elif mn == "fsm":
            v = cval(get(reg(ops[1])).word(0))
            if v is None:
                sys.exit("%08X: fsm of a non-constant" % pc)
            R[reg(ops[0])] = Reg.words([C(0xFFFFFFFF if v >> (3 - i) & 1 else 0) for i in range(4)])
        elif mn == "brnz":
            t = imm(ops[1])
            if a.start <= t < pc:
                trips[pc] = trips.get(pc, 0) + 1
                if trips[pc] <= a.iters:
                    print("; iteration %d ends at %08X" % (trips[pc], pc))
                    nxt = t
        elif mn == "bi":
            break
        else:
            sys.exit("%08X: %s not covered" % (pc, mn))
        pc = nxt

    # print the DAG of the stores
    named = {}
    uses = {}

    def count(n):
        uses[n] = uses.get(n, 0) + 1
        if uses[n] > 1:
            return
        for x in n.args:
            if isinstance(x, N):
                count(x)
            elif isinstance(x, tuple):
                for y in x:
                    if isinstance(y, tuple) and isinstance(y[0], N):
                        count(y[0])

    for _, b, _, ws in stores:
        for w in ws:
            count(w)
    lines = []

    def show(n, top=False):
        if n.op == "c":
            return "0x%08X" % n.args[0]
        if n.op == "sym":
            return "%s.%d" % n.args
        if n.op == "ptr":
            return "%s%+d" % n.args
        if n.op == "in":
            return "[%s%+d]" % n.args
        if n.op == "u8":
            return "u8[%s%+d]" % n.args
        if n in named:
            return named[n]
        parts = []
        for x in n.args:
            if isinstance(x, N):
                parts.append(show(x))
            elif isinstance(x, tuple):
                parts.append("{" + " ".join("%02X" % y[1] if y[0] == "cb" else "%s.b%d" % (show(y[0]), y[1])
                                           for y in x) + "}")
            else:
                parts.append(str(x))
        s = "%s(%s)" % (n.op, ", ".join(parts))
        if uses.get(n, 0) > 1 and not top:
            nm = "t%d" % len(named)
            named[n] = nm
            lines.append("%s = %s" % (nm, s))
            return nm
        return s

    for pc_, b, off, ws in stores:
        outs = [show(w, True) for w in ws]
        lines.append("STORE @%08X [%s%+d]:" % (pc_, show(b), off))
        for i, o in enumerate(outs):
            lines.append("   w%d = %s" % (i, o))
    print("\n".join(lines))
    print("; final pointers: " + " ".join("%s=%s" % (r, show(get(r).word(0))) for r in sorted(ptrs)))


if __name__ == "__main__":
    main()
