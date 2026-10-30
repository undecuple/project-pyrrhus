#!/usr/bin/env python3
"""Whole-program scratch-register liveness after a gated SPU call, across a job image and the WWS job manager
(the proof that no code reads what VertexJob's memcpy @0x7F00 leaves in its scratch registers).

  tools/spu/live_proof.py --job JOB.dis --pm JOBMANAGER.dis --call 0x525C [--call ...] --leaf 0x7F00-0x80A0
      [--edge IMG:PC=T1,T2 ...] [--bisl IMG:PC=IMG2:T ...] [--ret IMG:PC=REG ...] [--kcall IMG:PC=exit|select ...]

post_kernels.py --live walks one image and stops at indirect calls and jumps. This walker follows the job, its calls
into the policy module (the job manager, --pm) and the job manager's own code, with a call stack:
- U (the registers that may still hold the leaf's values) starts as every register the leaf writes on any path of
  --leaf, minus r0, r1 and r3 (the leaf returns its destination in r3, as the native code leaves it).
- Every instruction that reads a register in U is reported (READ); a write removes it from U.
- `brsl $rL, T` / `bisl $rL` push (L, pc + 4) and go to the target; `bi $rL` (or a --ret jump) returns to the most
  recent stack entry with link L, dropping the entries above it (tail calls). With no such entry it falls back to
  every `brsl $rL` site + 4 of the image (and, for $r0 in the job manager, to every job `bisl` continuation; for $r0 in the
  job, to the job manager's job-call continuation): an over-approximation, counted as FALLBACK.
- `ila $rX, A` within five instructions before `bi $rX` resolves to A; --edge IMG:PC=T1,... gives the targets of table
  jumps; --bisl IMG:PC=IMG2:T sends an indirect call into the other image; --kcall models the SPURS kernel's two
  entries (exitToKernel, selectWorkload) as the runtime implements them (runtime/spu/spurs_policy.c).
- The job manager's job call (`bisl $r0,$r5` at --pm-jobcall) is a call into another job: it reads r3-r10 (the ABI's argument
  registers; a compiled job's entry reads at most those) and returns to pc + 4.
- `iret` ends a path (the SPU interrupt handler restores what it saved; it is not entered by a branch).
- An unresolved indirect branch is UNRESOLVED and counted as a read of every register in U.
A clean RESULT means: on every path the walker can see (a superset of the feasible ones, given the stated edges),
no register the leaf writes is read before it is written again.
Output derives from the game's code: write it under work/, never commit it.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import post_kernels as pk  # noqa: E402

COND_IND = {"biz", "binz", "bihz", "bihnz"}
MAX_STACK = 8
MAX_VALS = 16


def parse_pc(s):
    return int(s, 16)


def key_pc(s):
    i, pc = s.split(":")
    return (i, int(pc, 16))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--pm", required=True)
    ap.add_argument("--call", action="append", required=True, type=parse_pc)
    ap.add_argument("--leaf", required=True, help="LO-HI of the leaf's code (its writes start U)")
    ap.add_argument("--edge", action="append", default=[])
    ap.add_argument("--bisl", action="append", default=[])
    ap.add_argument("--ret", action="append", default=[])
    ap.add_argument("--kcall", action="append", default=[])
    ap.add_argument("--setreg", action="append", default=[], metavar="IMG:PC=REG:A1,A2",
                    help="after the instruction at PC, REG holds one of these code addresses (a table load; the path "
                         "forks per value)")
    ap.add_argument("--spill", action="append", default=[], metavar="IMG:A1,A2",
                    help="LS words used as a save area (`stqa $rX,A` ... `lqa $rX,A`): the store is not a read; the "
                         "load puts rX back in U when it was in U at the store")
    ap.add_argument("--pm-jobcall", type=parse_pc, default=0x32BC, help="the job manager's `bisl` into the job")
    ap.add_argument("--entry", type=parse_pc, default=0xA00, help="the job manager's entry")
    ap.add_argument("--stack", action="append", default=[], metavar="IMG:RET,IMG:RET,...",
                    help="seed call stack (return addresses through $r0, outermost first); one per alternative")
    ap.add_argument("--max-states", type=int, default=300000,
                    help="cap on (pc, call stack) states; past it the result is INCOMPLETE (memory bound: an "
                         "unjoined version held 22 GB)")
    ap.add_argument("--trace", type=parse_pc, action="append", default=[], help="print how this PC was reached")
    a = ap.parse_args()

    img = {}
    for name, path in (("job", a.job), ("pm", a.pm)):
        ins = pk.load(path)
        img[name] = (ins, {x[0]: i for i, x in enumerate(ins)})

    lo, hi = (int(x, 16) for x in a.leaf.split("-"))
    U0 = set()
    for adr, _, mn, op in img["job"][0]:
        if lo <= adr < hi:
            rs = pk.regs(op)
            if rs and mn not in pk.ALL_SRC and mn not in ("bisl", "bi"):
                U0.add(rs[0])
    U0 = frozenset(U0 - {0, 1, 3})

    edges = {key_pc(k): [(key_pc(k)[0], int(t, 16)) for t in v.split(",")]
             for k, v in (e.split("=") for e in a.edge)}
    bisl = {key_pc(k): key_pc(v) for k, v in (e.split("=") for e in a.bisl)}
    rets = {key_pc(k): int(v) for k, v in (e.split("=") for e in a.ret)}
    kcall = {key_pc(k): v for k, v in (e.split("=") for e in a.kcall)}
    setreg = {}
    for e in a.setreg:
        k, v = e.split("=")
        r, vals = v.split(":")
        setreg[key_pc(k)] = (int(r), [int(x, 16) for x in vals.split(",")])
    spill = set()
    for e in a.spill:
        i, addrs = e.split(":")
        spill |= {(i, int(x, 16)) for x in addrs.split(",")}

    links = {}   # (image, link reg) -> every continuation (the fallback)
    for name, (ins, _) in img.items():
        for adr, _, mn, op in ins:
            if mn == "brsl":
                links.setdefault((name, pk.regs(op)[0]), []).append((name, adr + 4))
    links.setdefault(("pm", 0), []).extend(("job", pc + 4) for (i, pc) in bisl if i == "job")
    links.setdefault(("job", 0), []).append(("pm", a.pm_jobcall + 4))

    issues, unresolved, fallback = {}, set(), set()
    seen = {}       # (image, pc, stack) -> (U, consts, spilled): joined, so the state stays bounded
    parent = {}
    track = set()   # registers used as indirect branch targets: their `ila`/`brsl` constants ride in the state
    for name, (ins, _) in img.items():
        for adr, _, mn, op in ins:
            rs = pk.regs(op)
            if mn == "bi" and rs:
                track.add(rs[0])
            elif mn in COND_IND or mn == "bisl":
                track.add(rs[1])

    def join(old, new):
        """Least upper bound: U and spill taint by union; a register's constant set by union (unknown when
        either side does not know it, or past MAX_VALS values)."""
        (u0, c0, s0), (u1, c1, s1) = old, new
        c = {}
        for r in c0.keys() & c1.keys():
            v = c0[r] | c1[r]
            if len(v) <= MAX_VALS:
                c[r] = v
        s = {}
        for A in s0.keys() | s1.keys():
            t0, v0 = s0.get(A, (False, None))
            t1, v1 = s1.get(A, (False, None))
            v = v0 | v1 if (v0 is not None and v1 is not None and len(v0 | v1) <= MAX_VALS) else None
            s[A] = (t0 or t1, v)
        return (u0 | u1, c, s)

    seeds = [()]
    if a.stack:   # the frames above the call: each --stack is one alternative, outermost first
        seeds = [tuple((0, key_pc(f)) for f in alt.split(",")) for alt in a.stack]
    work = [(("job", c + 4), sd, (U0, {}, {}), None) for c in a.call for sd in seeds]
    steps = 0
    while work:
        loc, stack, state, frm = work.pop()
        name, pc = loc
        steps += 1
        k = (name, pc, stack)
        old = seen.get(k)
        if old is not None:
            state = join(old, state)
            if state == old:
                continue
        else:
            parent[k] = frm
        if len(seen) >= a.max_states and old is None:
            unresolved.add((name, pc, f"state cap {a.max_states} reached: INCOMPLETE"))
            continue
        seen[k] = state
        u, cmap, spilled = state
        ins, idx = img[name]
        if pc not in idx:
            unresolved.add((name, pc, "outside code"))
            continue
        _, _, mn, op = ins[idx[pc]]
        rs = pk.regs(op)
        if mn in pk.ALL_SRC:
            src, dst = rs, []
        elif mn in pk.RT_ALSO_SRC:
            src, dst = rs, rs[:1]
        else:
            src, dst = rs[1:], rs[:1]
        tgt = re.findall(r"0x([0-9A-F]+)\s*$", op)
        nxt = []   # (loc, stack)
        sp2 = spilled
        load_const = None
        if mn in ("stqa", "lqa") and tgt and (name, int(tgt[0], 16)) in spill:
            A = int(tgt[0], 16)
            if mn == "stqa":   # the value moves to the slot: not a read; its taint and constants go with it
                src = []
                sp2 = dict(spilled)
                sp2[A] = (rs[0] in u, cmap.get(rs[0]))
            elif A in spilled:
                taint, vals = spilled[A]
                if taint:
                    u = u | {rs[0]}
                    dst = []
                load_const = vals

        def ret_to(L, st, use_const=True):
            if use_const and L in cmap:
                out = []
                for t in sorted(cmap[L]):
                    for j in range(len(st) - 1, -1, -1):
                        if st[j][1] == t:
                            out.append((t, st[:j]))
                            break
                    else:
                        out.append((t, st))
                return out
            for j in range(len(st) - 1, -1, -1):
                if st[j][0] == L:
                    return [(st[j][1], st[:j])]
            fallback.add((name, pc, L))
            return [(c, ()) for c in links.get((name, L), [])]

        if loc in kcall:
            if kcall[loc] == "exit":
                u = u - {0, 1, 3, 4, 5}
                nxt = [(("pm", a.entry), ())]
            else:
                dst = [3]
                nxt = [((name, pc + 4), stack)]
        elif loc in edges:
            nxt = [(t, stack) for t in edges[loc]]
            if mn in COND_IND:
                nxt.append(((name, pc + 4), stack))
        elif loc in rets:
            nxt = ret_to(rets[loc], stack, use_const=False)
        elif mn == "brsl":
            st = (stack + ((rs[0], (name, pc + 4)),))[-MAX_STACK:]
            nxt = [((name, int(tgt[0], 16)), st)]
        elif mn == "bisl":
            if loc in bisl:
                st = (stack + ((rs[0], (name, pc + 4)),))[-MAX_STACK:]
                nxt = [(bisl[loc], st)]
            elif name == "pm" and pc == a.pm_jobcall:
                src = src + list(range(3, 11))
                nxt = [((name, pc + 4), stack)]
            else:
                unresolved.add((name, pc, "bisl"))
                src = src + sorted(u)
        elif mn == "bi" or mn in COND_IND:
            r = rs[0] if mn == "bi" else rs[1]
            t = pk.ila_target(ins, idx, pc, r)
            if t is not None:
                nxt = [((name, t), stack)]
            elif r in cmap or (name, r) in links:
                nxt = ret_to(r, stack)
            else:
                unresolved.add((name, pc, mn))
                src = src + sorted(u)
            if mn in COND_IND:
                nxt.append(((name, pc + 4), stack))
        elif mn == "iret":
            src = []
        elif mn in ("stop", "stopd"):
            nxt = []
        elif mn == "br":
            nxt = [((name, int(tgt[0], 16)), stack)]
        elif mn in pk.COND:
            nxt = [((name, int(tgt[0], 16)), stack), ((name, pc + 4), stack)]
        else:
            nxt = [((name, pc + 4), stack)]
        for r in src:
            if r in u:
                issues.setdefault((name, pc, mn), set()).add(r)
        u2 = u - set(dst)
        if not u2 and not any(t for t, _ in sp2.values()):
            continue   # nothing of the leaf's is left in a register or a save slot: this path is done
        c2 = {r: v for r, v in cmap.items() if r not in dst and not (mn == "lqa" and rs and r == rs[0])}
        if load_const is not None and rs[0] in track:
            c2[rs[0]] = load_const
        if mn in ("brsl", "bisl") and rs and rs[0] in track:
            c2[rs[0]] = frozenset({(name, pc + 4)})
        elif mn == "ila" and rs and rs[0] in track:
            v = re.findall(r"(-?0x[0-9A-F]+|-?\d+)\s*$", op)
            if v:
                c2[rs[0]] = frozenset({(name, int(v[0], 0) & 0x3FFFF)})
        if loc in setreg:
            r, vals = setreg[loc]
            c2[r] = frozenset((name, v) for v in vals)
        for n, st in nxt:
            work.append((n, st, (u2, c2, sp2), k))

    pcs = {(n, p) for n, p, _ in seen}
    print(f"leaf {lo:X}-{hi:X} writes {len(U0)} registers: " + " ".join(f"r{r}" for r in sorted(U0)))
    print(f"visited {len(pcs)} instructions ({sum(1 for k in pcs if k[0] == 'pm')} in the job manager), "
          f"{len(seen)} contexts, {steps} steps")
    for (name, pc, L) in sorted(fallback):
        print(f"FALLBACK {name}:0x{pc:X} bi $r{L} with no matching call on the stack")
    for (name, pc, w) in sorted(unresolved):
        print(f"UNRESOLVED {name}:0x{pc:X} {w}")
    for (name, pc, mn), rr in sorted(issues.items()):
        print(f"READ {name}:0x{pc:X} {mn} " + " ".join(f"r{r}" for r in sorted(rr)))
    for t in a.trace:
        ks = [k for k in seen if k[1] == t]
        if ks:
            k, path = ks[0], []
            while k in parent and len(path) < 60:
                path.append(f"{k[0]}:{k[1]:X}")
                k = parent[k]
            print(f"TRACE 0x{t:X}: " + " <- ".join(path))
    print("RESULT " + ("clean: no register the leaf writes is read on any path"
                       if not issues and not unresolved else f"{len(issues)} reads, {len(unresolved)} unresolved"))


if __name__ == "__main__":
    main()
