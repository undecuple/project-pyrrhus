#!/usr/bin/env python3
"""KZ2 patch 7022, lifter half: compute_ib_guesses (tools/spu_lifter.py of the patched tree) on the
real encodings of Gfx.Particles.UpdateJob's interrupt-window idiom (0xF87C: brsl $r2,0xF880 ; ai $r2,$r2,8 ; bid $r2 ;
il $r9,0) and its `bihz $rC, $r2` form, relocated to a test address.

  test_spu_pcguess.py PATCHED_TOOLS_DIR

Checks: the bi site gets the guess link + 8 and it is marked as a link-register guess (site, target); without
pc_guesses (callers before the patch) there is no guess; a target that is not a function start is not guessed; an
`ila` guess (patch 1098) is unchanged and not marked."""
import struct
import sys

sys.path.insert(0, sys.argv[1])
from spu_disasm import disassemble_spu  # noqa: E402
import spu_lifter  # noqa: E402

B = 0x8000
# brsl $r2,.+4 ; ai $r2,$r2,8 ; bid $r2 ; il $r9,0 ; brsl $r2,.+4 ; ai $r2,$r2,8 ; bihz $r16,$r2 ; il $r9,0
# ; ila $r5,0x8000 ; bi $r5
WORDS = [0x33000082, 0x1C020102, 0x35080100, 0x40800009, 0x33000082, 0x1C020102, 0x25440110, 0x40800009,
         0x42000005 | ((B & 0x3FFFF) << 7), 0x35000280]
code = b"".join(struct.pack(">I", w) for w in WORDS)
insns = disassemble_spu(code, B)
mn = [(i.addr, i.mnemonic, i.operands) for i in insns]
sites = {i.addr for i in insns if spu_lifter._bi_target_reg(i) is not None}
fails = []
if sites != {B + 8, B + 0x18, B + 0x24}:
    fails.append(f"sites {sorted(hex(s) for s in sites)}; decode {mn}")
starts = {B, B + 0xC, B + 0x1C}
pcg = set()
g = spu_lifter.compute_ib_guesses(insns, starts, sites, pc_guesses=pcg)
if g.get(B + 8) != [B + 0xC]:
    fails.append(f"bid site: {g.get(B + 8)}")
if g.get(B + 0x18) != [B + 0x1C]:
    fails.append(f"bihz site: {g.get(B + 0x18)}")
if g.get(B + 0x24) != [B]:
    fails.append(f"ila site: {g.get(B + 0x24)}")
if pcg != {(B + 8, B + 0xC), (B + 0x18, B + 0x1C)}:
    fails.append(f"pc set {pcg}")
g0 = spu_lifter.compute_ib_guesses(insns, starts, sites)
if g0 != {B + 0x24: [B]}:
    fails.append(f"without pc_guesses: {g0}")
g1 = spu_lifter.compute_ib_guesses(insns, {B}, sites, pc_guesses=set())
if B + 8 in g1 or B + 0x18 in g1:
    fails.append(f"not a function start but guessed: {g1}")
print(("FAIL " + "; ".join(fails)) if fails else
      "PASS test_spu_pcguess.py: bid and bihz idiom guessed (link + 8, marked), ila unchanged, none without the switch")
sys.exit(1 if fails else 0)
