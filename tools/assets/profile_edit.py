#!/usr/bin/env python3
"""Read and edit a Killzone 2 PROFILE.DAT. Method and CLI from Project Helghast
tools/assets/profile_edit.py; the layout is KZ2's own (the RE notes "PROFILE.DAT layout").

PROFILE.DAT is a raw copy of PlayerProfile object bytes [0x24, 0x5B10): 23,276 (0x5AEC) bytes, big-endian. The only load
check is the size 0x5AEC and the first word == the class version 0xC7 (validator @0x81EC8, called at 0x2EA244).
File offset = object offset - 0x24. Same layout in v1.01 and saves written by 1.29.

  profile_edit.py show SRC [--nodes]
  profile_edit.py edit SRC --out work/.../PROFILE.DAT [--complete-levels 1-10 [--difficulty-bits 0xF]]
                   [--music F] [--speech F] [--sfx F] [--gamma F] [--headset F] [--invert-y 0|1] [--invert-x 0|1]
                   [--hints 0|1] [--subtitles 0|1] [--god 0|1|2] [--inf-ammo 0|1] [--clear-setups]
  profile_edit.py stage SRC --template RUN --out work/.../RUNDIR      (stub: needs a port run's savedata tree)

SRC is a PROFILE.DAT or a directory holding exactly one. Writes go only below the repo's work/ (KZ2_WORK_DIR for tests)
and never to SRC. Nothing here needs game data: the layout is numbers. Sixaxis: the profile has no such field (the
Sixaxis* values are engine config, not profile data), so there is no --sixaxis option.
"""
import argparse
import os
import struct
import sys
from pathlib import Path

SIZE = 0x5AEC            # memcpy size at 0x81B1C/0x81B2C (save) and validator 0x81EC8 (cmpwi r4,0x5aec)
VERSION_WORD = 0xC7      # class version: u16 at RTTI record 0xEC57B8+0xC (1.29: 0xED5F58+0xC, same)
RT2FILE = -0x24          # file offset = object offset + RT2FILE (memcpy source = this+0x24)

# Settings (object offset in comment; accessors found through the Lua binding table at 0xEC6A00..)
NAME = 0x28 + RT2FILE        # char[20]  Get/SetPlayerName (0xA4D040 = this+0x28)
STEREO = 0x3C + RT2FILE      # u32
VOL_MUSIC = 0x40 + RT2FILE   # f32 (0xA4BC64)
VOL_SPEECH = 0x44 + RT2FILE  # f32
VOL_SFX = 0x48 + RT2FILE     # f32
GAMMA = 0x4C + RT2FILE       # f32
VOL_HEADSET = 0x50 + RT2FILE  # f32
GODMODE = 0x54 + RT2FILE     # u32
HINTS = 0x58 + RT2FILE       # u8
SUBTITLES = 0x59 + RT2FILE   # u8
INVERT_Y = 0x5A + RT2FILE    # u8
INVERT_X = 0x5B + RT2FILE    # u8
TANK_STEER = 0x5C + RT2FILE  # u32
HOLD_ZOOM = 0x60 + RT2FILE   # u8
CROUCH_TOGGLE = 0x61 + RT2FILE  # u8
BUTTONS = 0x64 + RT2FILE     # u32[55] function -> button (GetFunctionButton 0x81190), to 0x140
AXES = 0x140 + RT2FILE       # u32[8] GetFunctionAxis 0x811D0 (axis map; 0x160 is the heading float, so 8 entries)
HEADING = 0x160 + RT2FILE    # f32 look speed factor (0xA4D29C)
PITCH = 0x164 + RT2FILE      # f32
SCHEME = 0x168 + RT2FILE     # u32 controller scheme (0xA4D334)
BADGE1 = 0x16C + RT2FILE     # i32 primary badge (-1 none)
BADGE2 = 0x170 + RT2FILE
BADGEW = 0x174 + RT2FILE     # i32[2] badge weapon index
SETUP0 = 0x17C + RT2FILE     # custom MP game setup slots, stride 0x174 (0x81F50 SaveCreateGameSetting)
SETUP_STRIDE = 0x174
SETUP_N = 6                  # ASSUMPTION: 6 (slot 6 would overlap the 0xA37 flags)
HUD = 0xA37 + RT2FILE
SCRIPTDBG = 0xA43 + RT2FILE
INFAMMO = 0xA44 + RT2FILE
CROUCHJS = 0xA4C + RT2FILE   # u32
CROSSHAIR = 0xA50 + RT2FILE
MPSCORE = 0xA54 + RT2FILE    # u32 x? (MPScore 0xA54, highest 0xA60, previous 0xA64)
HONOR = 0xA68 + RT2FILE      # u8 honor rank, +1 highest
RIBBONS = 0xA6C + RT2FILE    # ribbon amounts (u32 each; GetRibbonAmount)
MATCHES_WON = 0xACC + RT2FILE
CLAN_MATCHES = 0xAD0 + RT2FILE
CLAN_TAG = 0xAD4 + RT2FILE   # char[]
CLAN_ID = 0xAF4 + RT2FILE
TIMEZONE = 0xAFC + RT2FILE   # char[]
LOCATION = 0xB2E + RT2FILE   # char[]
LOCS_HASH = 0xB70 + RT2FILE
POLICY_HASH = 0xB74 + RT2FILE
JOIN = 0xB78 + RT2FILE       # join-game options 0xB78..0xB94
ADMIN = 0xB94 + RT2FILE
UPLOADED = 0xB95 + RT2FILE
LEVEL0 = 0xBAC + RT2FILE     # level record h at LEVEL0 + h*LEVEL_STRIDE (IsNodeCompleted* 0x82288/0x82310)
LEVEL_STRIDE = 0x188
NLEVELS = 20
NNODES = 32
NODE_STRIDE = 12             # +0 u32 difficulty bits (bit d = completed at difficulty d), +4 least deaths, +8 best time (s)
REWARDS_OFF = 0x180          # u32 bitmask inside a level record (IsRewardPickedUp 0x824C8)
SYMBOLS_OFF = 0x184          # u32 bitmask (IsSymbolDestroyed 0x82550)
SPSTAT = 0x2A4C + RT2FILE    # u32 playtime s, deaths, suicides, buddies offended; then stat table to 0x3A88
NAMETAB = 0x2A88 + RT2FILE   # 32-byte entity-name slots (ISA_M82G_AssaultRifle ...)
GLOBALS = 0x3A88 + RT2FILE   # 256 x {char name[28]; f32 value} (SetGameGlobal 0x826C0)
GLOBALS_N = 256
TAIL = 0x5A88 + RT2FILE      # 0x5A88..0x5B10 (0x88 bytes) not read by any accessor traced
DIFF_BITS = ["bit0 (Easy/Recruit)", "bit1 (Medium/Regular)", "bit2 (Hard/Veteran)", "bit3 (Ultra Hard/Elite)"]
# Nodes present per campaign level in either reference save (level h, 1-based node numbers); levels 0 and 11..19 unused there.
KNOWN_NODES = {1: [1, 2, 3, 4, 5, 6, 7], 2: [1, 2, 3, 4, 5, 6, 8], 3: [1, 2, 3, 4, 7], 4: [1, 2, 3, 4, 5],
               5: [1, 2, 3, 7, 9], 6: [1, 2, 3, 6, 7, 8], 7: [1, 2, 3, 4, 5, 6, 7, 8], 8: [1, 2, 3, 4, 5, 6, 7],
               9: [1, 3, 4], 10: [1, 2, 3, 4]}


def find_profile(src):
    p = Path(src)
    if p.is_file():
        return p
    if p.is_dir():
        hits = sorted(q for q in p.rglob("PROFILE.DAT") if q.is_file())
        if len(hits) == 1:
            return hits[0]
        raise SystemExit(f"{src}: {len(hits)} PROFILE.DAT below it (need exactly one)")
    raise SystemExit(f"{src}: not a file or directory")


def load(src):
    p = find_profile(src)
    data = bytearray(p.read_bytes())
    if len(data) != SIZE:
        raise SystemExit(f"{p}: {len(data)} bytes, the game's validator wants exactly {SIZE} (0x{SIZE:X})")
    v = struct.unpack_from(">I", data, 0)[0]
    if v != VERSION_WORD:
        raise SystemExit(f"{p}: first word 0x{v:X}, the validator wants 0x{VERSION_WORD:X}")
    return p, data


def u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


def f32(d, o):
    return struct.unpack_from(">f", d, o)[0]


def cstr(d, o, n):
    return bytes(d[o:o + n]).split(b"\0")[0].decode("latin-1")


def node(d, h, n):
    """Record of node n (1-based) of level h: (diff_bits, least_deaths, best_time)."""
    return struct.unpack_from(">3I", d, LEVEL0 + h * LEVEL_STRIDE + (n - 1) * NODE_STRIDE)


def show(d, nodes=False):
    print(f"version       0x{u32(d, 0):X}   size {len(d)}")
    print(f"name          {cstr(d, NAME, 20)!r}")
    print(f"audio         music {f32(d, VOL_MUSIC):.3f} speech {f32(d, VOL_SPEECH):.3f} sfx {f32(d, VOL_SFX):.3f} "
          f"headset {f32(d, VOL_HEADSET):.3f} stereo {u32(d, STEREO)}")
    print(f"video         gamma {f32(d, GAMMA):.3f}   hud {d[HUD]} crosshair {d[CROSSHAIR]}")
    print(f"controls      scheme {u32(d, SCHEME)} invertY {d[INVERT_Y]} invertX {d[INVERT_X]} "
          f"look speed heading {f32(d, HEADING):.2f} pitch {f32(d, PITCH):.2f} holdZoom {d[HOLD_ZOOM]} "
          f"crouchToggle {d[CROUCH_TOGGLE]} tankSteer {u32(d, TANK_STEER)}")
    print(f"              buttons {[u32(d, BUTTONS + 4 * i) for i in range(55)]}")
    print(f"              axes {[u32(d, AXES + 4 * i) for i in range(8)]}")
    print(f"options       hints {d[HINTS]} subtitles {d[SUBTITLES]} god {u32(d, GODMODE)} infAmmo {d[INFAMMO]} "
          f"scriptDebug {d[SCRIPTDBG]}")
    sb = [struct.unpack_from(">i", d, BADGE1 + 4 * i)[0] for i in range(4)]
    print(f"badges        primary {sb[0]} secondary {sb[1]} weaponIndex {sb[2:]}")
    print(f"mp            score {u32(d, MPSCORE)} honor {d[HONOR]} (highest {d[HONOR + 1]}) matchesWon {u32(d, MATCHES_WON)} "
          f"clanMatches {u32(d, CLAN_MATCHES)} clanTag {bytes(d[CLAN_TAG:CLAN_TAG + 4]).hex()} timezone {cstr(d, TIMEZONE, 32)!r} "
          f"location {cstr(d, LOCATION, 8)!r}")
    print(f"              ribbons {[u32(d, RIBBONS + 4 * i) for i in range(6)]}")
    used = []
    for i in range(SETUP_N):
        b = SETUP0 + SETUP_STRIDE * i
        if d[b + 0x173] or d[b]:
            blob = cstr(d, b + 0x31, 0xFF)
            used.append(f"[{i}] {cstr(d, b, 0x30)!r} blob {len(blob)} chars, password {'set' if d[b + 0x131] else 'none'}, "
                        f"spectator password {'set' if d[b + 0x152] else 'none'}")
    print(f"mp setups     {len(used)} of {SETUP_N} used" + "".join("\n              " + u for u in used))
    print(f"sp stats      playtime {u32(d, SPSTAT)} s, deaths {u32(d, SPSTAT + 4)}, suicides {u32(d, SPSTAT + 8)}, "
          f"buddies offended {u32(d, SPSTAT + 12)}")
    names = [cstr(d, NAMETAB + 32 * i, 32) for i in range(128)]
    print(f"              entity names {[n for n in names if n][:3]} ... ({sum(1 for n in names if n)} used)")
    g = [(cstr(d, GLOBALS + 32 * i, 28), f32(d, GLOBALS + 32 * i + 28)) for i in range(GLOBALS_N)]
    g = [x for x in g if x[0]]
    print(f"game globals  {len(g)} set" + (f": {g[:6]}" if g else ""))
    print("campaign progress (level h: nodes completed / any bits; per-difficulty counts bit0..bit3)")
    for h in range(NLEVELS):
        recs = [node(d, h, n) for n in range(1, NNODES + 1)]
        done = [n + 1 for n, r in enumerate(recs) if r[0]]
        rw, sy = u32(d, LEVEL0 + h * LEVEL_STRIDE + REWARDS_OFF), u32(d, LEVEL0 + h * LEVEL_STRIDE + SYMBOLS_OFF)
        if not done and not rw and not sy and not nodes:
            continue
        per = [sum(1 for r in recs if r[0] >> b & 1) for b in range(4)]
        print(f"  level {h:2d}: {len(done)} nodes {done}  per-difficulty {per}  best-time sum {sum(r[2] for r in recs)} s  "
              f"deaths {sum(r[1] for r in recs)}  rewards 0x{rw:X} symbols 0x{sy:X}")


def parse_range(s):
    a, _, b = s.partition("-")
    return range(int(a), int(b or a) + 1)


def edit(d, a):
    d = bytearray(d)
    if a.complete_levels:
        bits = int(a.difficulty_bits, 0) & 0xFF
        for h in parse_range(a.complete_levels):
            if h not in KNOWN_NODES:
                raise SystemExit(f"level {h}: no known node list (known: {sorted(KNOWN_NODES)})")
            for n in KNOWN_NODES[h]:
                o = LEVEL0 + h * LEVEL_STRIDE + (n - 1) * NODE_STRIDE
                struct.pack_into(">I", d, o, u32(d, o) | bits)
    for name, off in (("music", VOL_MUSIC), ("speech", VOL_SPEECH), ("sfx", VOL_SFX), ("gamma", GAMMA),
                      ("headset", VOL_HEADSET)):
        v = getattr(a, name)
        if v is not None:
            struct.pack_into(">f", d, off, v)
    for name, off in (("invert_y", INVERT_Y), ("invert_x", INVERT_X), ("hints", HINTS), ("subtitles", SUBTITLES)):
        v = getattr(a, name)
        if v is not None:
            d[off] = v
    if a.god is not None:  # u32 at object 0x54; only 2 (Invulnerable) has a code reader (0xCE7E0), 1 is stored but unused
        struct.pack_into(">I", d, GODMODE, a.god)
    if a.inf_ammo is not None:  # u8 at object 0xA44, read at 0x253EAC (the RE notes "Debug menu and test aids")
        d[INFAMMO] = a.inf_ammo
    if a.clear_setups:
        d[SETUP0:SETUP0 + SETUP_STRIDE * SETUP_N] = bytes(SETUP_STRIDE * SETUP_N)
    assert len(d) == SIZE and u32(d, 0) == VERSION_WORD
    return d


def check_out(out, src):
    o = Path(out).resolve()
    root = Path(os.environ.get("KZ2_WORK_DIR") or Path(__file__).resolve().parents[2] / "work").resolve()
    if not o.is_relative_to(root):
        raise SystemExit(f"{out}: output must be under {root} (never the game's or a run's original)")
    if o == Path(src).resolve():
        raise SystemExit(f"{out}: refusing to write the source in place")
    return o


def stage(*_):
    print("stage: not implemented. It needs the savedata tree from a port run of KZ2 (the directory\n"
          "the HLE cellSaveData writes: <savedata>/<prefix>-KILLZONE2/{PROFILE.DAT,CHECKPNT.DAT,SECTION.DAT}), which does not\n"
          "exist yet. When it does: copy that tree to a new run dir under work/ and replace PROFILE.DAT with this file\n"
          "(23,276 bytes, no PFD needed by the HLE). CHECKPNT/SECTION are 501,008 bytes (see the RE notes).",
          file=sys.stderr)
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("src")
    s.add_argument("--nodes", action="store_true", help="list every level, even empty ones")
    e = sub.add_parser("edit")
    e.add_argument("src")
    e.add_argument("--out", required=True)
    e.add_argument("--complete-levels", metavar="LO-HI", help="mark the known nodes of levels LO..HI (1..10) completed")
    e.add_argument("--difficulty-bits", default="0xF", help="bits OR-ed into each node (default 0xF = all four)")
    for n in ("music", "speech", "sfx", "gamma", "headset"):
        e.add_argument("--" + n, type=float)
    for n in ("invert-y", "invert-x", "hints", "subtitles"):
        e.add_argument("--" + n, type=int, choices=[0, 1])
    e.add_argument("--god", type=int, choices=[0, 1, 2],
                   help="god mode: 2 = Invulnerable (the only value the 1.29 code reads), 1 = On (stored, no reader found)")
    e.add_argument("--inf-ammo", type=int, choices=[0, 1], help="infinite ammo flag (applied to the local players' weapons on section enter)")
    e.add_argument("--clear-setups", action="store_true", help="erase the custom MP game setups")
    g = sub.add_parser("stage")
    g.add_argument("src")
    g.add_argument("--template")
    g.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "stage":
        return stage()
    src, data = load(a.src)
    if a.cmd == "show":
        print(f"file          {src}")
        show(data, a.nodes)
        return 0
    out = check_out(a.out, src)
    new = edit(data, a)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(new))
    print(f"wrote {out} ({len(new)} bytes, {sum(1 for x, y in zip(data, new) if x != y)} bytes changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
