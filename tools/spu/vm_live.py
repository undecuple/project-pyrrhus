#!/usr/bin/env python3
"""Register liveness inside one SPU function with a jump table (Physics.Raycast's MOPP ray virtual
machine @0xC9C8, its dispatch `bi $r2` @0xCA68 over the 108-entry table at 0xCA6C). Diagnostic; its output derives
from the game's code: write it under work/, never commit it.

  tools/spu/vm_live.py DIS LO-HI --table BI_PC=TABLE,N[,DEFAULT] [--at PC ...] [--ret-reads R,...] [--call-reads R,...]

A standard backward may-liveness over [LO, HI): register granularity (a partial write such as a cwd/shufb insert
reads the old value through its operands; the RT_ALSO_SRC forms read their target), every branch out of
the range reads every register, `brsl`/`bisl` read --call-reads (default r3-r10) plus their target register and kill
--call-kills (default nothing: a value may pass through a call), the function's `bi $r0` reads --ret-reads (default r1, r3)
and the registers the epilogue does not reload, `stop`/`stopd` end a path. The table jump goes to every table entry
(N words at TABLE; DEFAULT also, the `brnz` taken above the table's range). Prints, per --at PC, the live-in set.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import post_kernels as pk  # noqa: E402


def rng(s):
    out = set()
    for part in s.split(","):
        a, _, b = part.partition("-")
        a = int(a.lstrip("r"))
        out |= set(range(a, int(b.lstrip("r")) + 1)) if b else {a}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dis")
    ap.add_argument("range")
    ap.add_argument("--table", action="append", default=[])
    ap.add_argument("--at", action="append", default=[])
    ap.add_argument("--ret-reads", default="1,3")
    ap.add_argument("--call-reads", default="3-10")
    ap.add_argument("--call-kills", default="", help="registers a call leaves undefined (the ABI's volatile r2-r79: "
                    "compiled code does not read them after a call expecting the value from before it)")
    a = ap.parse_args()
    lo, hi = (int(x, 16) for x in a.range.split("-"))
    ins = pk.load(a.dis)
    words = {x[0]: x[1] for x in ins}
    code = {x[0]: x for x in ins if lo <= x[0] < hi}
    tables = {}
    for t in a.table:
        pc, _, rest = t.partition("=")
        f = rest.split(",")
        base, n = int(f[0], 16), int(f[1])
        tg = {words[base + 4 * i] & 0x3FFFF for i in range(n)}
        if len(f) > 2:
            tg.add(int(f[2], 16))
        tables[int(pc, 16)] = sorted(tg)
    ALL = set(range(128))
    ret_reads, call_reads = rng(a.ret_reads), rng(a.call_reads)
    call_kills = rng(a.call_kills) if a.call_kills else set()

    def info(pc):
        _, w, mn, op = code[pc]
        rs = pk.regs(op)
        tgt = re.findall(r"0x([0-9A-F]+)\s*$", op)
        if mn in pk.ALL_SRC:
            use, dst = set(rs), set()
        elif mn in pk.RT_ALSO_SRC:
            use, dst = set(rs), set(rs[:1])
        else:
            use, dst = set(rs[1:]), set(rs[:1])
        if mn in ("fma", "fms", "fnms", "mpya", "selb", "shufb"):   # RRR forms: rt first, sources after it
            use, dst = set(rs[1:]), set(rs[:1])
        succ, extra = [], set()
        if mn in ("brsl",):
            use |= call_reads
            dst = ({rs[0]} if rs else set()) | call_kills
            succ = [pc + 4]
        elif mn in ("bisl",):
            use |= call_reads | set(rs[1:])
            dst = {rs[0]} | call_kills
            succ = [pc + 4]
        elif mn == "bi" and rs == [0]:
            use |= ret_reads | {0}
            succ = []
        elif mn == "bi":
            if pc in tables:
                succ = list(tables[pc])
            else:
                use |= ALL
        elif mn in ("biz", "binz", "bihz", "bihnz"):
            use |= ALL
            succ = [pc + 4]
        elif mn in ("stop", "stopd"):
            succ = []
        elif mn == "br":
            succ = [int(tgt[0], 16)]
        elif mn in pk.COND:
            succ = [int(tgt[0], 16), pc + 4]
        else:
            succ = [pc + 4]
        for s in succ:
            if s not in code:
                extra |= ALL
        return use | extra, dst, [s for s in succ if s in code]

    I = {pc: info(pc) for pc in code}
    live = {pc: set() for pc in code}
    changed = True
    while changed:
        changed = False
        for pc in sorted(code, reverse=True):
            use, dst, succ = I[pc]
            out = set()
            for s in succ:
                out |= live[s]
            new = use | (out - dst)
            if new != live[pc]:
                live[pc] = new
                changed = True
    for at in a.at:
        pc = int(at, 16)
        print(f"0x{pc:05X} live-in ({len(live[pc])}): " + " ".join(f"r{r}" for r in sorted(live[pc])))


if __name__ == "__main__":
    main()
