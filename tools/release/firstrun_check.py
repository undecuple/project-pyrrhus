#!/usr/bin/env python3
"""First-run checks for the release installer and the portable zip: is the player's own Killzone 2 dump, 1.29 update
and decrypted EBOOT what the port can lift and build from? From Project Helghast tools/release/firstrun_check.py.
Standard library only, Python 3.8+, runs on the bundled Windows Python and on Linux; reads nothing of the game beyond PARAM.SFO, the first bytes of each file (magic),
file sizes and the hashes (H1: the decrypted EBOOT; A1: the disc archive, unless --skip-archive-hash).

    firstrun_check.py --dump DIR [--update DIR] [--eboot FILE] [--json] [--min-psarc-bytes N] [--hashes FILE]
                      [--psarc-hashes FILE] [--root DIR] [--build DIR] [--progress] [--skip-archive-hash]

  --dump    the decrypted disc dump folder (holds PS3_GAME/PARAM.SFO), or a decrypted disc ISO file (adapted from
            Project Helghast v0.1.2): PARAM.SFO, EBOOT.BIN and data_ps3.psarc are then read from inside the image
            (iso9660.py) with the same D1-D3 checks and an INFO line "dump: decrypted ISO <name>". I1 FAIL: the ISO is
            encrypted ("this ISO is encrypted; use a decrypted dump"); I2 FAIL: the ISO cannot be read (not an ISO,
            damaged, truncated). No A1 here: firstrun.py hashes the archive while copying it out of the image.
  --update  the installed 1.29 update folder, where a PS3 or RPCS3 keeps it: .../dev_hdd0/game/<the disc's title id>,
            such as BCUS98116 (the update installs under the disc's own title id; holds PARAM.SFO and USRDIR/EBOOT.BIN)
  --eboot   the decrypted EBOOT (an ELF); default: <update>/USRDIR/EBOOT.elf, else <dump>/PS3_GAME/USRDIR/EBOOT.elf
            (next to EBOOT.BIN), else an EBOOT.BIN that is already an ELF. E1: FAIL for an encrypted SELF, a file
            that is not a PS3 executable, or a known EBOOT of another version than --target (the disc's 1.01 one on
            the 1.29 build; from Project Helghast PR #11); an unknown size only warns
  --hashes  the shared EBOOT id table (default eboot_sha256.json next to this script; the format the
            Killzone ports share): {"entries": [{title_id, region, app_ver, size, sha256,
            status, self_sha256, segment_sha256}]}, load_eboot_entries; the earlier {"builds": [...]} and the old
            {"1.29": {size, sha256}} form still load. The EBOOT is matched by its whole SHA-256, else by
            segment_sha256 (its PT_LOAD segments: survives another tool's padding), else unknown. H1: tested = OK,
            untested = WARN, unsupported or a status this check does not know = FAIL, another region's title id =
            WARN "wrong region", unknown or modified = WARN, no reference recorded = WARN "unknown yet"; a malformed
            table = WARN naming entries[i] and what is wrong. Player texts name what is wrong and the needed title,
            version and region; no paths, no how-to
  --psarc-hashes  the known disc archive (default psarc_sha256.json next to this script). A1: SHA-256 of the whole
            data_ps3.psarc (read in 8 MiB pieces) against it. OK = matches; a mismatch on a disc listed there is a FAIL
            when the file says fail_on_mismatch, else a WARN (one copy checked so far); any other disc = WARN. A
            different size is a mismatch without reading the file. Cached in <build>/psarc-sha256-cache.json by path,
            size and mtime of every part (no cache without --build). --progress prints "ARCHIVE-HASH done=X total=Y"
            lines (firstrun.py turns them into PROGRESS lines); --skip-archive-hash leaves A1 out (from Project Helghast v0.1.3).

  --root / --build  the install and build folders: O1 FAIL when either is inside OneDrive (env OneDrive,
            OneDriveConsumer, OneDriveCommercial). O2 FAIL: a game file is an online-only OneDrive placeholder (file
            attributes 0x400000, 0x40000 or 0x1000); checked before any file is read, so nothing downloads. O3 (OK,
            INFO): the dump or update is inside OneDrive but fully local. Adapted from Project Helghast (the Killzone 3
            PC port, same author, MIT), Project Helghast v0.1.2.

Folder picks (adapted from Project Helghast v0.1.2): --dump may name PS3_GAME or PS3_GAME/USRDIR and --update
its USRDIR (resolve_dump, resolve_update step up to the right folder). D1 names the TITLE_ID found: the four
Killzone 2 discs of REGIONS are accepted (US BCUS98116, tested; Europe BCES00081, Asia BCAS20066 and Japan BCJS30032,
D53: accepted as untested, a D1 WARN says so), anything else is refused by name and title; a disc VERSION other than
the region's warns (02.00 on BCUS98116 = the Killzone Trilogy disc, whose PS3_GAME is Killzone 2 itself: untested).
U1 fails when the update's TITLE_ID is not the disc's, naming both regions (a mixed set: each disc takes its own
region's update; the Asian and Japanese updates carry their own added_data_ps3.psarc and patch files).

Split archives (from Project Helghast v0.1.3): a dump copied to a FAT32 drive stores a file over 4 GiB as parts
<name>.66600, .66601, ... (data_ps3.psarc is 6.5 GiB). D3 accepts the parts in place of data_ps3.psarc (sizes added
up, magic from the first part) and names the first missing part when the numbering has a gap; A1 hashes the parts in
order as one stream.

Input reasons (adapted from Project Helghast PR #14): after a FAIL, one line per failing input, labelled "Disc dump",
"1.29 update" or "EBOOT": "<label> failed: <path>: <what is there>. <what it must hold>." (plus "Found: <its FAIL
messages>." unless the input is the wrong thing altogether), then the other FAIL messages (O1, O2), then "Passed: A,
B and C." for the inputs that passed. Swapped roles are named: the update folder given as the disc ("looks like the
1.29 update"), a disc dump given as the update, the disc's PS3_GAME given as the update (also a U1 FAIL: category
DG); a drive root is searched two levels down for the disc and the update, another folder one level. In --json
they are facts.reasons; in text they follow "first-run checks: FAIL", indented by two spaces. The codes are unchanged.

One line per check: OK / WARN / FAIL <code>: <message>. Exit 0 = no FAIL, 1 = at least one FAIL, 2 = usage.
--json prints {"ok": bool, "checks": [{"code", "level", "message"}], "facts": {...}} instead. Numbers come from
the RE notes and a disc dump with the 1.29 update; no game content is embedded.
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys

# the bundled embeddable Python (a python3XX._pth file) puts only its own folders on sys.path, never the script's:
# firstrun.py starts this file by full path, so `import iso9660` (an ISO dump) failed there (from Project Helghast
# PR #14)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TITLE_ID = "BCUS98116"                 # US disc (the RE notes), the tested one
TITLE = "Killzone 2"
DISC_VERSION = "01.01"                 # PARAM.SFO VERSION of the US disc we checked (the RE notes)
DISC_EBOOT_BIN_SIZE = 16_384_360       # PS3_GAME/USRDIR/EBOOT.BIN on the disc, encrypted SELF (the RE notes)
# The Killzone 2 discs (D53, 2026-11-04/05, read from the discs in the sandbox): title id -> region, its PARAM.SFO
# VERSION, the size of its disc EBOOT.BIN (an encrypted SELF, never used: the port is built on the 1.29 update's
# EBOOT, which is byte-identical for all four regions) and whether anyone has played it through on the port. Each
# region's 1.29 update installs to dev_hdd0/game/<its id> (APP_VER 01.29). The European disc's data_ps3.psarc is the US
# one; the Asian and Japanese ones differ (psarc_sha256.json), and so do their updates' added_data_ps3.psarc and
# patch_data_ps3 files. Every disc also ships PS3_UPDATE/PS3UPDAT.PUP (a console firmware update): never read.
REGIONS = {
    TITLE_ID:    {"region": "US", "adj": "US", "version": DISC_VERSION, "disc_eboot": DISC_EBOOT_BIN_SIZE,
                  "tested": True},
    "BCES00081": {"region": "Europe", "adj": "European", "version": "01.01", "disc_eboot": 16_384_360,
                  "tested": False, "note": "its data archive is the US one; PARAM.SFO and the pictures differ"},
    "BCAS20066": {"region": "Asia", "adj": "Asian", "version": "01.02", "disc_eboot": 16_384_360, "tested": False,
                  "note": "its data archive and its 1.29 update's data differ from the US ones"},
    "BCJS30032": {"region": "Japan", "adj": "Japanese", "version": "01.00", "disc_eboot": 16_385_320,
                  "tested": False, "note": "its data archive, intro movie and 1.29 update's data differ from the US ones"},
}
ACCEPTED_TEXT = ", ".join(f"{t} ({v['region']})" for t, v in list(REGIONS.items())[:-1]) + \
    " or " + "{} ({})".format(*[(t, v["region"]) for t, v in REGIONS.items()][-1])


def region_of(tid):
    """The REGIONS entry of a title id, or None for any other id."""
    return REGIONS.get(tid)


def disc_label(tid):
    """'the European disc (BCES00081)', or 'BCxx (not a Killzone 2 disc)' for another id."""
    g = REGIONS.get(tid)
    return f"the {g['adj']} disc ({tid})" if g else f"{tid or 'no title id'} (not a Killzone 2 disc)"


def untested_text(tid):
    """D1's WARN for a disc accepted as untested, else ""."""
    g = REGIONS.get(tid)
    if not g or g["tested"]:
        return ""
    return (f"disc dump: {disc_label(tid)}: untested. The port's code is the same for every region (the 1.29 EBOOT is "
            f"identical), but the disc's data is its own ({g['note']}) and no one has played it through on the port "
            "yet; setup goes on")
# ASSUMPTION (KZ3's read-only survey of the Trilogy disc, BCUS99075, 2026-10-26; not checked on our own copy): its
# PS3_GAME is Killzone 2 itself, TITLE_ID BCUS98116 with disc VERSION 02.00. Untested here (re-data 23 compares it).
TRILOGY_DISC_VERSION = "02.00"
# The title ids a folder hint may offer as the disc dump (looks_like_disc): the four Killzone 2 discs. The Trilogy's
# PS3_GAME carries the US id (VERSION 02.00 above), so it is offered too; other games' dumps never are.
TITLE_IDS = tuple(REGIONS)
ONEDRIVE_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
# st_file_attributes bits of a OneDrive "files on demand" placeholder (an online-only file)
ATTR_OFFLINE = 0x1000
ATTR_RECALL_ON_OPEN = 0x40000
ATTR_RECALL_ON_DATA_ACCESS = 0x400000
ONLINE_ONLY_MASK = ATTR_OFFLINE | ATTR_RECALL_ON_OPEN | ATTR_RECALL_ON_DATA_ACCESS
DEFAULT_INSTALL = "%LOCALAPPDATA%\\Programs\\Project Pyrrhus"
EBOOT_ELF_SIZES = {                    # decrypted EBOOTs (of a disc dump and the 1.29 update)
    16_381_928: "1.01",
    16_455_144: "1.29",
}
UPDATE_APP_VER = "01.29"               # the 1.29 update's PARAM.SFO APP_VER (read 2026-10-12; its VERSION is 01.00)
UPDATE_DATA = "added_data_ps3.psarc"   # the 1.29 update's data archive, a plain PSARC (15,725,397 bytes)
UPDATE_PATCH_DIR = "patch_data_ps3"     # the 1.29 update's *.pspatch files (folder)
MIN_PSARC_BYTES = 6 << 30              # data_ps3.psarc is 6,998,576,922 bytes on disc; smaller = truncated dump
PSARC_MAGIC = b"PSAR"
SELF_MAGIC = b"SCE\0"
ELF_MAGIC = b"\x7fELF"
EM_PPC64 = 0x15
HASHES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eboot_sha256.json")
PSARC_HASHES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psarc_sha256.json")
PSARC_CACHE_NAME = "psarc-sha256-cache.json"
HASH_CHUNK = 8 << 20
SPLIT_FIRST = 66600                    # a FAT32 dump cuts a file over 4 GiB into <name>.66600, .66601, ...
PSARC_NAME = "data_ps3.psarc"


def read_sfo(path):
    """PARAM.SFO -> dict (same decoder as tools/disc_info.py)."""
    with open(path, "rb") as f:
        return parse_sfo(f.read())


def parse_sfo(d):
    """The bytes of a PARAM.SFO -> dict (a folder's file or one read from inside an ISO)."""
    if d[:4] != b"\0PSF":
        raise ValueError("not a PARAM.SFO (bad magic)")
    _, _, kt, dt, n = struct.unpack("<4sIIII", d[:20])
    out = {}
    for i in range(n):
        ko, fmt, ln, _, do = struct.unpack("<HHIII", d[20 + 16 * i:36 + 16 * i])
        k = d[kt + ko:d.index(b"\0", kt + ko)].decode()
        v = d[dt + do:dt + do + ln]
        out[k] = struct.unpack("<I", v)[0] if fmt == 0x404 else v.rstrip(b"\0").decode(errors="replace")
    return out


def head(path, n):
    with open(path, "rb") as f:
        return f.read(n)


def _is_name(path, name):
    return os.path.basename(os.path.normpath(path)).lower() == name.lower()


def resolve_dump(path):
    """A pick of PS3_GAME or PS3_GAME/USRDIR (one or two levels too deep) -> the folder that holds PS3_GAME; any other
    path is returned as given. The same rule as installer/kz2.iss ResolveDump (from Project Helghast v0.1.2)."""
    if not path or os.path.isfile(os.path.join(path, "PS3_GAME", "PARAM.SFO")):
        return path
    d = os.path.normpath(path)
    if _is_name(d, "USRDIR") and _is_name(os.path.dirname(d), "PS3_GAME"):
        d = os.path.dirname(d)
    if _is_name(d, "PS3_GAME") and os.path.isfile(os.path.join(os.path.dirname(d), "PS3_GAME", "PARAM.SFO")):
        return os.path.dirname(d)
    return path


def resolve_update(path):
    """A pick of the update's USRDIR -> the update folder (the one with PARAM.SFO); else the path as given. A PARAM.SFO
    inside USRDIR itself (put there by hand or a tool) does not stop the step up (Project Helghast PR #17 found
    that bug in its copy; this one never returned early on it, test_input_reasons.py checks both)."""
    if path and _is_name(path, "USRDIR"):
        up = os.path.dirname(os.path.normpath(path))
        if os.path.isfile(os.path.join(up, "PARAM.SFO")):
            return up
    return path


def _norm(p):
    return os.path.abspath(p).replace("/", "\\").rstrip("\\").lower()


def onedrive_root_of(path, env=None):
    """The OneDrive folder (from OneDrive, OneDriveConsumer, OneDriveCommercial) that holds `path`, else ''.
    Prefix match on whole path components, case-insensitive; the same rule as installer/kz2.iss InOneDrive."""
    env = os.environ if env is None else env
    p = _norm(path)
    for var in ONEDRIVE_VARS:
        base = (env.get(var) or "").strip().strip('"')
        if not base:
            continue
        b = _norm(base)
        if b and (p == b or p.startswith(b + "\\")):
            return base
    return ""


def file_attributes(path):
    """Windows st_file_attributes of `path` (0 elsewhere or when unreadable). Reads no file content."""
    try:
        return getattr(os.stat(path), "st_file_attributes", 0)
    except OSError:
        return 0


def check_onedrive_tree(r, root, build, env=None):
    """O1 (FAIL): the install folder or the build folder is inside OneDrive, which syncs the build's thousands of files
    while the compiler writes them (locked files, a churning build). Silent when fine."""
    for what, path in (("install folder", root), ("build folder", build)):
        od = onedrive_root_of(path, env) if path else ""
        if od:
            r.fail("O1", f"the {what} {path} is inside OneDrive ({od}), which syncs the build's thousands of files "
                         "while it runs and locks them. Choose a folder outside OneDrive (for the installer the "
                         f"default, {DEFAULT_INSTALL}, is fine) and run the setup again")


# P1: the same failure reported on Project Helghast (#20). The build's CMake joins paths into
# ';'-separated lists: a ';' in a path splits it, and an unbalanced '[' or ']' changes how CMake splits the whole
# list (bracket rule of CMake's list arguments: no split inside [...]). KZ3 reproduced it on Windows 10 (2026-10-29):
# the bundled CMake installed under a '[' folder (our toolchain/cmake under the install folder) fails its own compiler
# detection (CMakeCompilerIdDetection.cmake joins its module list with ';'); ';' fails on Linux too
# (tools/release/test_cmake_path_chars.py). The trigger is CMake's own location, so quoting our configure call cannot
# avoid it: the folder is refused before anything is built (Project Helghast's design).
PATH_BAD_CHARS = "[];"


def path_bad_chars(path):
    """-> the characters of PATH_BAD_CHARS found in path, in order ("" when none)."""
    return "".join(ch for ch in PATH_BAD_CHARS if ch in (path or ""))


def check_path_chars(r, root, build):
    """P1 (FAIL): the install folder or the build folder has '[', ']' or ';' in its path. Silent when fine."""
    for what, path in (("install folder", root), ("build folder", build)):
        bad = path_bad_chars(path)
        if bad:
            r.fail("P1", f"the {what} {path} has {' and '.join(repr(c) for c in bad)} in its path, which the build's "
                         "CMake cannot handle (it splits the compiler's paths there). Choose a folder whose path has no "
                         f"'[', ']' or ';' (for the installer the default, {DEFAULT_INSTALL}, is fine) and run the "
                         "setup again")


def game_files(dump, update, eboot):
    """The game files the build reads (the disc archive as one file or its FAT32 parts)."""
    f = []
    if dump and os.path.isfile(dump):    # a decrypted disc ISO
        f.append(dump)
    elif dump:
        u = os.path.join(dump, "PS3_GAME", "USRDIR")
        f += [os.path.join(dump, "PS3_GAME", "PARAM.SFO"), os.path.join(u, "EBOOT.BIN")]
        f += split_parts(os.path.join(u, PSARC_NAME))[0]
    if update:
        f += [os.path.join(update, "PARAM.SFO"), os.path.join(update, "USRDIR", "EBOOT.BIN"),
              os.path.join(update, "USRDIR", UPDATE_DATA), os.path.join(update, "USRDIR", "EBOOT.elf")]
    if eboot:
        f.append(eboot)
    return f


def check_online_only(r, dump, update, eboot, env=None, attrs=None):
    """O2 (FAIL): a game file is a OneDrive online-only placeholder (RECALL_ON_DATA_ACCESS, RECALL_ON_OPEN or OFFLINE):
    reading the 6.5 GiB archive would download it or fail with a cloud-provider error. O3 (OK, an INFO line): a folder
    inside OneDrive whose files are all local. Runs before any content is read; True when O2 failed."""
    attrs = attrs or file_attributes
    online = [p for p in game_files(dump, update, eboot) if os.path.exists(p) and attrs(p) & ONLINE_ONLY_MASK]
    if online:
        names = ", ".join(os.path.basename(p) for p in online[:4]) + (" ..." if len(online) > 4 else "")
        r.fail("O2", f"{len(online)} game file(s) exist only online in OneDrive ({names}; first: {online[0]}). "
                     "Right-click the game folder (the disc dump, the update and the EBOOT's folder), choose "
                     "\"Always keep on this device\", wait until OneDrive has downloaded it, then run the setup again")
        return True
    for what, path in (("disc dump", dump), ("1.29 update", update)):
        od = onedrive_root_of(path, env) if path else ""
        if od:
            r.ok("O3", f"INFO: the {what} folder is inside OneDrive ({od}) but its files are on this device")
    return False


class Report:
    def __init__(self):
        self.checks = []
        self.facts = {}

    def add(self, level, code, msg):
        self.checks.append({"code": code, "level": level, "message": msg})

    def ok(self, code, msg):
        self.add("OK", code, msg)

    def warn(self, code, msg):
        self.add("WARN", code, msg)

    def fail(self, code, msg):
        self.add("FAIL", code, msg)

    @property
    def passed(self):
        return not any(c["level"] == "FAIL" for c in self.checks)


def check_sfo(r, path, code, what, expect=None):
    """Shared PARAM.SFO check for the dump and the update. Returns the fields or None. A TITLE_ID outside REGIONS is a
    FAIL naming the id and title found; `expect` (the disc's id, for the update) must match too."""
    if not os.path.isfile(path):
        r.fail(code, f"{what}: no PARAM.SFO at {path}")
        return None
    try:
        sfo = read_sfo(path)
    except (ValueError, struct.error, IndexError) as e:
        r.fail(code, f"{what}: PARAM.SFO unreadable ({e})")
        return None
    return sfo_report(r, sfo, code, what, expect)


def sfo_report(r, sfo, code, what, expect=None):
    """The TITLE_ID verdict on parsed PARAM.SFO fields (check_sfo, and the ISO's own PARAM.SFO). -> the fields."""
    tid = sfo.get("TITLE_ID")
    if not tid:
        r.fail(code, f"{what}: PARAM.SFO has no TITLE_ID, so this is not a game folder")
    elif tid not in REGIONS:
        r.fail(code, f"{what}: this is {tid} ({sfo.get('TITLE', '?')}), not {TITLE}: the port needs a {TITLE} disc, "
                     f"{ACCEPTED_TEXT} (other releases are not supported)")
    elif expect and tid != expect:
        r.fail(code, mixed_text(what, tid, expect))
    else:
        r.ok(code, f"{what}: TITLE_ID {tid} ({sfo.get('TITLE', '?')}; {REGIONS[tid]['region']})")
    return sfo


def mixed_text(what, upd_id, disc_id):
    """U1's FAIL for an update of another release than the disc: a mixed set. A PS3 applies an update only to
    the disc with its title id, and the Asian and Japanese updates carry their own data and patch files, made for
    their own disc's archive; the European and US updates differ only in PARAM.SFO and the encrypted EBOOT.BIN, but
    the game asks for dev_hdd0/game/<the disc's id>, so a mixed pair is refused too (one rule for every region)."""
    if disc_id not in REGIONS:
        return f"{what}: TITLE_ID {upd_id} differs from the disc's {disc_id}: use the update of the same release"
    g, d = REGIONS[upd_id], REGIONS[disc_id]
    return (f"{what}: this is the {g['adj']} update ({upd_id}), but the disc dump is {disc_label(disc_id)}: each disc "
            f"needs the 1.29 update of its own region. Use the {d['adj']} update (dev_hdd0{os.sep}game{os.sep}"
            f"{disc_id}), or the {g['adj']} disc with this update")


def split_parts(path):
    """The pieces of a file as a FAT32 dump stores it. -> (parts, missing): parts = [path] when the file exists, else
    the consecutive <path>.66600, .66601, ... that exist (stops at the first gap); missing = the file name to ask the
    player for ("" when nothing is missing): <name> when neither the file nor any part exists, <name>.666NN for the
    first gap in the numbering (also when later parts exist but .66600 does not). Names compare case-blind."""
    if os.path.isfile(path):
        return [path], ""
    d, name = os.path.split(path)
    pre = name.lower() + "."
    nums = {}
    try:
        for n in os.listdir(d or "."):
            tail = n[len(pre):]
            if n.lower().startswith(pre) and tail.isdigit() and int(tail) >= SPLIT_FIRST \
                    and os.path.isfile(os.path.join(d, n)):
                nums[int(tail)] = os.path.join(d, n)
    except OSError:
        pass
    parts, i = [], SPLIT_FIRST
    while i in nums:
        parts.append(nums[i])
        i += 1
    if not nums:
        return [], name
    if max(nums) >= i:                    # a part past the gap exists: the numbering has a hole
        return parts, f"{name}.{i}"
    return parts, ""


def psarc_info(path):
    """-> (parts, missing, total size, first four bytes) of data_ps3.psarc as one file or as FAT32 split parts."""
    parts, missing = split_parts(path)
    if not parts or missing:
        return parts, missing, 0, b""
    return parts, "", sum(os.path.getsize(p) for p in parts), head(parts[0], 4)


def check_dump(r, dump, min_psarc):
    sfo = check_sfo(r, os.path.join(dump, "PS3_GAME", "PARAM.SFO"), "D1", "disc dump")
    disc_facts(r, sfo)
    eboot = os.path.join(dump, "PS3_GAME", "USRDIR", "EBOOT.BIN")
    check_disc_eboot(r, (os.path.getsize(eboot), head(eboot, 4)) if os.path.isfile(eboot) else None,
                     (sfo or {}).get("TITLE_ID"))
    psarc = os.path.join(dump, "PS3_GAME", "USRDIR", PSARC_NAME)
    parts, missing, size, magic = psarc_info(psarc)
    if missing and missing != PSARC_NAME:
        r.fail("D3", f"disc dump: PS3_GAME/USRDIR/{missing} is missing: data_ps3.psarc is split into parts "
                     "(data_ps3.psarc.66600, .66601, ...) and the numbering has a gap (dump incomplete)")
    elif not parts:
        r.fail("D3", "disc dump: no PS3_GAME/USRDIR/data_ps3.psarc (the game's data archive)")
    else:
        r.facts["psarc"] = {"size": size}
        if len(parts) > 1 or parts[0] != psarc:
            r.facts["psarc"]["parts"] = [os.path.basename(p) for p in parts]
        check_psarc_head(r, size, magic, min_psarc,
                         f", {len(parts)} split parts .66600 ...)" if parts[0] != psarc else ")")


def disc_facts(r, sfo):
    """D1 facts and notes of the disc's PARAM.SFO (folder or ISO): CATEGORY, disc VERSION (Trilogy)."""
    if sfo:
        r.facts["disc"] = {k: sfo.get(k) for k in ("TITLE_ID", "TITLE", "VERSION", "APP_VER", "CATEGORY")}
        if sfo.get("CATEGORY") != "DG":
            r.warn("D1", f"disc dump: CATEGORY {sfo.get('CATEGORY')!r}, a disc game is 'DG' (an installed copy?)")
        ver, tid = sfo.get("VERSION"), sfo.get("TITLE_ID")
        g = REGIONS.get(tid)
        if tid == TITLE_ID and ver == TRILOGY_DISC_VERSION:
            r.warn("D1", f"disc dump: disc VERSION {ver}: the Killzone Trilogy disc, whose PS3_GAME is {TITLE} "
                         f"({TITLE_ID}). Untested: the port is built on the stand-alone disc (VERSION {DISC_VERSION}); "
                         "A1 says whether its archive is the same")
        elif g and ver != g["version"]:
            r.warn("D1", f"disc dump: disc VERSION {ver!r}, the known {g['adj']} disc is {g['version']} (another printing?)")
        if untested_text(tid):
            r.warn("D1", untested_text(tid))
            r.facts["disc"]["untested"] = True
        if g:
            r.facts["disc"]["region"] = g["region"]


def check_disc_eboot(r, eboot, tid=None):
    """D2 from (size, first four bytes) of the disc's EBOOT.BIN, or None when it is absent; tid = the disc's title id
    (its region's size; the US one otherwise)."""
    if eboot is None:
        r.fail("D2", "disc dump: no PS3_GAME/USRDIR/EBOOT.BIN (dump incomplete)")
        return
    size, magic = eboot
    r.facts["disc_eboot_bin"] = {"size": size, "magic": magic.hex()}
    if magic == SELF_MAGIC:
        r.ok("D2", f"disc EBOOT.BIN is an encrypted SELF ({size:,} bytes; expected: the disc one is never used directly)")
    elif magic == ELF_MAGIC:
        r.ok("D2", f"disc EBOOT.BIN is already a decrypted ELF ({size:,} bytes)")
    else:
        r.fail("D2", f"disc EBOOT.BIN has magic {magic!r}: neither SELF nor ELF (bad dump)")
    g = REGIONS.get(tid) or REGIONS[TITLE_ID]
    if magic == SELF_MAGIC and size != g["disc_eboot"]:
        r.warn("D2", f"disc EBOOT.BIN is {size:,} bytes, the {g['adj']} disc's is {g['disc_eboot']:,} (another version?)")


def check_psarc_head(r, size, magic, min_psarc, tail=")"):
    """D3 verdict from the archive's total size and first four bytes."""
    if magic != PSARC_MAGIC:
        r.fail("D3", f"data_ps3.psarc does not start with PSAR (magic {magic!r}): not a PSARC, or still encrypted")
    elif size < min_psarc:
        r.fail("D3", f"data_ps3.psarc is {size:,} bytes, less than {min_psarc:,}: the dump looks truncated")
    else:
        r.ok("D3", f"data_ps3.psarc present ({size / 2**30:.2f} GiB" + tail)


ISO_ENCRYPTED = "this ISO is encrypted; use a decrypted dump"


def check_dump_iso(r, path, min_psarc):
    """D1-D3 from inside a decrypted disc ISO (iso9660.py; adapted from Project Helghast v0.1.2). I1 FAIL = the
    ISO is encrypted (no file table behind a region table, or a file whose first bytes are not its format's magic);
    I2 FAIL = the image cannot be read (not an ISO, damaged, truncated). A1 is not run here: firstrun.py hashes the
    archive while it copies it out of the image."""
    import iso9660
    r.ok("D0", f"INFO: dump: decrypted ISO {os.path.basename(path)}")
    r.facts["iso"] = os.path.abspath(path)
    try:
        with iso9660.Iso(path) as im:
            sfo = None
            se = im.lookup("PS3_GAME/PARAM.SFO")
            if se is None or se.is_dir or not im.in_image(se):
                r.fail("D1", "disc dump: no PS3_GAME/PARAM.SFO inside the ISO")
            else:
                im.check_magic("PS3_GAME/PARAM.SFO", b"\0PSF")
                try:
                    sfo = sfo_report(r, parse_sfo(im.read("PS3_GAME/PARAM.SFO")), "D1", "disc dump")
                except (ValueError, struct.error, IndexError) as e:
                    r.fail("D1", f"disc dump: PARAM.SFO unreadable ({e})")
            disc_facts(r, sfo)
            info, cut = {}, False
            for key, rel in (("eboot", "PS3_GAME/USRDIR/EBOOT.BIN"), ("psarc", "PS3_GAME/USRDIR/" + PSARC_NAME)):
                e = im.lookup(rel)
                if e is None or e.is_dir:
                    info[key] = None
                    continue
                inside = im.in_image(e)
                if key == "psarc":
                    cut = not inside
                info[key] = (e.size, im.read(rel, 4) if inside else b"")
                if inside and info[key][1] not in ((SELF_MAGIC, ELF_MAGIC) if key == "eboot" else (PSARC_MAGIC,)):
                    raise iso9660.IsoEncrypted(ISO_ENCRYPTED)
            check_disc_eboot(r, info.get("eboot"), (sfo or {}).get("TITLE_ID"))
            if info.get("psarc") is None:
                r.fail("D3", "disc dump: no PS3_GAME/USRDIR/data_ps3.psarc inside the ISO (the game's data archive)")
            else:
                size, magic = info["psarc"]
                r.facts["psarc"] = {"size": size}
                if cut:
                    r.fail("D3", f"data_ps3.psarc ({size:,} bytes) reaches past the end of the ISO file: the ISO "
                                 "looks truncated (copy it again)")
                else:
                    check_psarc_head(r, size, magic, min_psarc, ", inside the ISO)")
    except iso9660.IsoEncrypted:
        r.fail("I1", ISO_ENCRYPTED)
    except iso9660.IsoError as e:
        r.fail("I2", f"disc ISO unreadable: {e}")


def hash_file(path, progress=None):
    """-> the SHA-256 (hex) of a file, or of a list of split parts joined in list order, read in HASH_CHUNK pieces;
    progress(done, total) after each piece, over the total size."""
    h = hashlib.sha256()
    paths = [path] if isinstance(path, str) else list(path)
    total = sum(os.path.getsize(p) for p in paths)
    done = 0
    for p in paths:
        with open(p, "rb") as f:
            while True:
                b = f.read(HASH_CHUNK)
                if not b:
                    break
                h.update(b)
                done += len(b)
                if progress:
                    progress(done, total)
    return h.hexdigest()


def load_archives(known):
    """psarc_sha256.json -> [{sha256, size, discs, fail_on_mismatch}]: the "archives" list (one entry per disc, D53),
    or the older single-archive form ({sha256, size, discs, fail_on_mismatch} at the top). Raises on a bad file."""
    ents = known["archives"] if "archives" in known else [known]
    out = []
    for e in ents:
        out.append({"sha256": e["sha256"].strip().lower(), "size": int(e["size"]),
                    "discs": [str(d) for d in e.get("discs", [])], "fail_on_mismatch": bool(e.get("fail_on_mismatch", False))})
    if not out:
        raise ValueError("no archives listed")
    return out


def check_psarc_hash(r, psarc, title_id, hashes_file=PSARC_HASHES_FILE, cache_dir=None, progress=None, known_sha=None):
    """A1: data_ps3.psarc (one file or its split parts) against the known disc archives (psarc_sha256.json: one entry
    per disc, each sha256, size, discs, fail_on_mismatch). The disc's own entry decides: a match is OK; a mismatch is
    a FAIL when it says fail_on_mismatch, else a WARN. An archive that is another known disc's (PARAM.SFO of one
    region, the archive of another: a mixed dump) is a FAIL. A size no known archive has is a mismatch without
    reading the file. The hash is cached in <cache_dir>/psarc-sha256-cache.json keyed by the path, the total size and
    every part's path, size and mtime. known_sha: the archive's SHA-256 already computed (firstrun.py hashes it while
    copying it out of an ISO): used and cached instead of a second read."""
    try:
        with open(hashes_file, encoding="utf-8") as f:
            archives = load_archives(json.load(f))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        r.warn("A1", f"known archive hash not readable ({hashes_file}: {e}); data_ps3.psarc not checked")
        return
    own = [e for e in archives if title_id and title_id in e["discs"]]
    parts, missing = split_parts(psarc)
    if not parts or missing:
        r.warn("A1", f"data_ps3.psarc not complete ({missing or 'not found'} is missing); archive not hashed")
        return
    size = sum(os.path.getsize(p) for p in parts)
    sig = [[os.path.abspath(p), os.path.getsize(p), os.stat(p).st_mtime_ns] for p in parts]
    key = os.path.abspath(psarc)
    cache_path = os.path.join(cache_dir, PSARC_CACHE_NAME) if cache_dir else None
    cache = {}
    if cache_path:
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            if not isinstance(cache, dict):
                cache = {}
        except (OSError, ValueError):
            cache = {}
    got, cached = None, False
    ent = cache.get(key)
    if isinstance(ent, dict) and ent.get("size") == size and ent.get("parts") == sig and ent.get("sha256"):
        got, cached = ent["sha256"], True
    elif any(size == e["size"] for e in archives):
        got = known_sha or hash_file(parts[0] if len(parts) == 1 else parts, progress)
        if cache_path:
            cache[key] = {"size": size, "parts": sig, "sha256": got}
            try:
                os.makedirs(cache_dir, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(cache, f, indent=1)
            except OSError:
                pass
    r.facts.setdefault("psarc", {})["sha256"] = got or ""
    sizes = f"{own[0]['size']:,}" if own else " or ".join(sorted({f"{e['size']:,}" for e in archives}))
    detail = f"{size:,} bytes" + (f", SHA-256 {got}" if got else f"; the known archive is {sizes} bytes")
    hit = [e for e in archives if got and got == e["sha256"]]
    if hit and any(e in own for e in hit):
        r.ok("A1", "data_ps3.psarc matches the known disc archive" + (" (hash cached from an earlier run)" if cached else ""))
    elif hit and own:
        other = [d for e in hit for d in e["discs"]]
        r.fail("A1", f"data_ps3.psarc is the archive of {disc_label(other[0])}, but PARAM.SFO is {disc_label(title_id)}"
                     ": the dump mixes two discs. Copy or dump one disc again, all of it")
    elif hit:
        r.warn("A1", f"data_ps3.psarc is the archive of {disc_label(hit[0]['discs'][0])}, but the disc's title id is "
                     f"{title_id or 'not known'}")
    elif own and own[0]["fail_on_mismatch"]:
        r.fail("A1", f"data_ps3.psarc differs from the known disc archive (damaged or modified copy): copy or dump the "
                     f"disc again ({detail})")
    elif own:
        r.warn("A1", f"data_ps3.psarc differs from the known disc archive ({detail}): a damaged or modified copy, or a "
                     "disc printing not seen yet. If the game does not start or stops loading, copy or dump the disc again")
    else:
        r.warn("A1", f"data_ps3.psarc is not a known archive ({title_id or 'no title id'}; {detail})")


def check_update(r, upd, disc_id=None):
    sfo = check_sfo(r, os.path.join(upd, "PARAM.SFO"), "U1", "1.29 update", disc_id)
    if sfo and sfo.get("CATEGORY") == "DG":       # from Project Helghast PR #14
        r.fail("U1", "1.29 update: this PARAM.SFO is the disc's (category DG), not an update's: the disc's PS3_GAME "
                     "folder was given as the update")
    if sfo:
        ver = sfo.get("APP_VER")
        r.facts["update"] = {k: sfo.get(k) for k in ("TITLE_ID", "APP_VER", "VERSION", "CATEGORY")}
        if ver != UPDATE_APP_VER:
            r.warn("U1", f"update APP_VER is {ver!r}, the port is built on {UPDATE_APP_VER}")
        else:
            r.ok("U1", f"update APP_VER {ver}")
    eb = os.path.join(upd, "USRDIR", "EBOOT.BIN")
    if not os.path.isfile(eb):
        r.fail("U2", "1.29 update: no USRDIR/EBOOT.BIN (update not installed here)")
    else:
        r.ok("U2", f"update EBOOT.BIN present ({os.path.getsize(eb):,} bytes, {'SELF' if head(eb, 4) == SELF_MAGIC else 'ELF'})")
    # U3 FAILs (issue #16; WARN before): the 1.29 EBOOT run on the disc's data alone stops at the
    # main menu (mainmenu.jsp served without the 1.29 patch, NULL call from 0x003F2984, sys_process_exit(1); kz2-r33-noupd).
    data = os.path.join(upd, "USRDIR", UPDATE_DATA)
    if not os.path.isfile(data):
        r.fail("U3", f"1.29 update: no USRDIR/{UPDATE_DATA}; without the update's data the game stops at the main menu")
    elif head(data, 4) != PSARC_MAGIC:
        r.fail("U3", f"1.29 update: USRDIR/{UPDATE_DATA} does not start with PSAR (still encrypted, or damaged)")
    else:
        r.ok("U3", f"update data archive present ({os.path.getsize(data):,} bytes)")
    if not os.path.isdir(os.path.join(upd, "USRDIR", UPDATE_PATCH_DIR)):
        r.fail("U3", f"1.29 update: no USRDIR/{UPDATE_PATCH_DIR}/ (the update's patch files); without them the game "
                     "stops at the main menu")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def segment_sha256(path):
    """SHA-256 of the loadable segments of a 64-bit big-endian ELF, as the shared EBOOT id table defines it
    (the same definition as Project Helghast's segment_sha256): walk the
    program headers in order; for each PT_LOAD with p_filesz or p_memsz non-zero, hash BE64 p_vaddr, BE64 p_filesz,
    BE64 p_memsz, then the p_filesz bytes at p_offset. Nothing else (no ELF or section headers, no padding, no trailing
    bytes), so it survives another tool's layout. p_paddr is not used. Raises ValueError for a file that is not such
    an ELF or whose headers point past its end, OSError when unreadable."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        eh = f.read(64)
        if len(eh) < 64 or eh[:4] != ELF_MAGIC or eh[4] != 2 or eh[5] != 2:
            raise ValueError("not a 64-bit big-endian ELF")
        phoff = struct.unpack_from(">Q", eh, 0x20)[0]
        phentsize, phnum = struct.unpack_from(">HH", eh, 0x36)
        if phnum and phentsize < 56:
            raise ValueError(f"program header entry size {phentsize} < 56")
        for i in range(phnum):
            f.seek(phoff + i * phentsize)
            ph = f.read(56)
            if len(ph) < 56:
                raise ValueError(f"program header {i} past the end of the file")
            p_type = struct.unpack_from(">I", ph, 0)[0]
            p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz = struct.unpack_from(">QQQQQ", ph, 8)
            if p_type != PT_LOAD or not (p_filesz or p_memsz):
                continue
            h.update(struct.pack(">QQQ", p_vaddr, p_filesz, p_memsz))
            f.seek(p_offset)
            left = p_filesz
            while left:
                b = f.read(min(left, 1 << 20))
                if not b:
                    raise ValueError(f"segment {i} past the end of the file")
                h.update(b)
                left -= len(b)
    return h.hexdigest()


# The shared EBOOT id table (the format the Killzone ports share, 2026-11-09): {"entries": [{title_id, region, app_ver, size, sha256, status[, self_sha256,
# segment_sha256]}]}, one entry per title id and version.
EBOOT_ENTRY_KEYS = ("title_id", "region", "app_ver", "size", "sha256", "status")
EBOOT_ENTRY_OPTIONAL = ("self_sha256", "segment_sha256")      # empty or left out = not recorded
# The level of a match per status: tested = the port was built and run on it; untested = identified only;
# unsupported = a known build this port does not run (added for ports built from one region only). Any other status FAILs on a match (fail closed).
EBOOT_STATUSES = {"tested": "OK", "untested": "WARN", "unsupported": "FAIL"}
OLD_STATUS = {"known-good": "tested"}                         # the earlier "builds" list's only status
DISC_EBOOT_VER = "1.01"                                       # the disc's own decrypted EBOOT (EBOOT_ELF_SIZES)
PT_LOAD = 1
UNKNOWN_EBOOT_TEXT = ("Your EBOOT is the {ver} size but its contents differ from a clean copy. It may be patched or "
                      "damaged. Make it again from your own {ver} update's EBOOT.BIN, without patches, and pick the "
                      "new file.")
_SHA_RE = re.compile(r"[0-9a-fA-F]{64}")
_APP_VER_RE = re.compile(r"(\d{2})\.(\d{2})")


def eboot_version_of_app_ver(app_ver):
    """'01.29' (PARAM.SFO APP_VER) -> '1.29' (the version names of EBOOT_ELF_SIZES and the old file's keys)."""
    m = _APP_VER_RE.fullmatch(app_ver)
    return f"{int(m.group(1))}.{m.group(2)}" if m else None


def _check_entry(where, b, lists=False):
    """Raise ValueError naming the entry (entries[i] or builds[i]) and what is wrong with it; return its rows (one
    per title id: an earlier "builds" entry may list several, pairwise with its regions, when lists is True)."""
    if not isinstance(b, dict):
        raise ValueError(f"{where} is not an object")
    missing = [k for k in EBOOT_ENTRY_KEYS if k not in b]
    if missing:
        raise ValueError(f"{where} lacks {', '.join(missing)}")
    extra = sorted(set(b) - set(EBOOT_ENTRY_KEYS) - set(EBOOT_ENTRY_OPTIONAL))
    if extra:
        raise ValueError(f"{where} has unknown keys {', '.join(extra)}")
    for k in ("title_id", "region"):
        v = b[k]
        vs = v if (lists and isinstance(v, list)) else [v]
        if not vs or not all(isinstance(x, str) and x.strip() for x in vs):
            raise ValueError(f"{where}.{k} must be a non-empty string" + (" or a list of them" if lists else ""))
    if isinstance(b["title_id"], list) != isinstance(b["region"], list) or \
            (isinstance(b["title_id"], list) and len(b["title_id"]) != len(b["region"])):
        raise ValueError(f"{where}: title_id and region must be both strings or lists of the same length")
    ver = eboot_version_of_app_ver(b["app_ver"]) if isinstance(b["app_ver"], str) else None
    if not ver:
        raise ValueError(f"{where}.app_ver must look like PARAM.SFO's APP_VER, such as \"01.29\": {b['app_ver']!r}")
    if not isinstance(b["size"], int) or isinstance(b["size"], bool) or b["size"] <= 0:
        raise ValueError(f"{where}.size must be a positive whole number of bytes: {b['size']!r}")
    for k in ("sha256",) + EBOOT_ENTRY_OPTIONAL:
        if k in b and not (isinstance(b[k], str) and (not b[k] or _SHA_RE.fullmatch(b[k]))):
            raise ValueError(f"{where}.{k} must be 64 hex digits, or empty when not recorded: {b[k]!r}")
    if not isinstance(b["status"], str) or not b["status"].strip():
        raise ValueError(f"{where}.status must be a non-empty string, such as \"tested\"")
    tids = b["title_id"] if isinstance(b["title_id"], list) else [b["title_id"]]
    regs = b["region"] if isinstance(b["region"], list) else [b["region"]]
    status = b["status"].strip()
    if lists:
        status = OLD_STATUS.get(status, status)
    return [{"title_id": t.strip(), "region": g.strip(), "app_ver": b["app_ver"], "version": ver, "size": b["size"],
             "sha256": b["sha256"].strip().lower(), "status": status,
             **{k: b.get(k, "").strip().lower() for k in EBOOT_ENTRY_OPTIONAL}} for t, g in zip(tids, regs)]


def load_eboot_entries(path):
    """eboot_sha256.json -> a list of rows, one per title id and version: {title_id, region, app_ver, version ('1.29'),
    size, sha256, status, self_sha256, segment_sha256} (hashes lower case, '' = not recorded).

    Reads the shared format ({"entries": [...]}, one title id per entry), the round-100 list ({"builds": [...]},
    title_id and region a string or lists of the same length; its status "known-good" reads as "tested") and the old
    per-version form ({"1.29": {"size", "sha256"}}, read as US entries, tested). Raises OSError (unreadable) or
    ValueError (not JSON, or a malformed entry, named in the message). The status is not checked here: a status this
    reader does not know FAILs on a match (check_eboot_elf), so the table may carry other ports' statuses."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("the top level is not an object")
    lists = [k for k in ("entries", "builds") if k in data]
    old = {k: v for k, v in data.items() if k not in ("comment", "entries", "builds")}
    if len(lists) > 1:
        raise ValueError("both an entries list and a builds list; keep one")
    if lists and old:
        raise ValueError(f"both a {lists[0]} list and old per-version keys ({', '.join(sorted(old))}); keep one")
    rows = []
    if lists:
        key = lists[0]
        if not isinstance(data[key], list):
            raise ValueError(f"{key} is not a list")
        for i, b in enumerate(data[key]):
            rows += _check_entry(f"{key}[{i}]", b, lists=key == "builds")
    else:
        for k, v in old.items():           # old format: "1.29": {"size": N, "sha256": "..."}
            if not isinstance(v, dict) or not isinstance(v.get("sha256", ""), str) or not eboot_version_of_app_ver(
                    "0" + k if len(k) == 4 else k):
                raise ValueError(f"\"{k}\" is not a version with an object holding a sha256 string")
            sha = v.get("sha256", "").strip().lower()
            if sha and not _SHA_RE.fullmatch(sha):
                raise ValueError(f"\"{k}\".sha256 must be 64 hex digits, or empty: {sha!r}")
            rows.append({"title_id": TITLE_ID, "region": "US", "app_ver": "0" + k if len(k) == 4 else k, "version": k,
                         "size": v.get("size", 0), "sha256": sha, "status": v.get("status", "tested"),
                         "self_sha256": "", "segment_sha256": ""})
    seen = set()
    for x in rows:
        if (x["title_id"], x["version"]) in seen:
            raise ValueError(f"a second entry for {x['title_id']} app_ver {x['app_ver']}")
        seen.add((x["title_id"], x["version"]))
    return rows


def load_eboot_table(path):
    """eboot_sha256.json -> {version: its first row} ('1.29' -> the row of the first title id listed for it); the
    rows of one version share size and hashes here (the decrypted 1.29 EBOOT is byte-identical on every disc, D53)."""
    out = {}
    for x in load_eboot_entries(path):
        out.setdefault(x["version"], x)
    return out


def identify_eboot(rows, sha, seg):
    """The shared table's matching order: rows whose whole-file sha256 is sha, else rows whose segment_sha256 is seg,
    else none. -> (how, rows): how is "sha256", "segments" or None."""
    m = [x for x in rows if sha and x["sha256"] == sha]
    if m:
        return "sha256", m
    m = [x for x in rows if seg and x["segment_sha256"] == seg]
    return ("segments", m) if m else (None, [])


def region_name(tid, fallback=""):
    g = REGIONS.get(tid)
    return g["region"] if g else fallback


def build_name(ver, tid=None, region=""):
    """'Killzone 2 1.29 (BCUS98116, US)', or 'Killzone 2 1.29' when the title id is not known."""
    return f"Killzone 2 {ver} ({tid}, {region_name(tid, region)})" if tid else f"Killzone 2 {ver}"


def needed_eboot(target, disc=None):
    """The EBOOT this release needs, for the player texts: the target version for the disc's title id (US when the
    disc is not known)."""
    return build_name(target, disc if disc in REGIONS else TITLE_ID)


def check_eboot_elf(r, elf, target="1.29", update=None, hashes_file=None):
    """E1 (the file: present, a PS3 executable, which version) and H1 (which build: tested, untested, unsupported,
    another region's, unknown or modified), from the shared EBOOT id table. Matching: the whole file's SHA-256, else segment_sha256, else unknown. The version comes from
    the matched entry, else from the size (EBOOT_ELF_SIZES). Player texts name what is wrong and the needed title,
    version and region; no paths, no how-to. update is unused (kept for callers)."""
    hashes_file = hashes_file or HASHES_FILE
    disc = (r.facts.get("disc") or {}).get("TITLE_ID")
    need = needed_eboot(target, disc)
    if not os.path.isfile(elf):
        r.fail("E1", f"no decrypted EBOOT at {elf}: the port cannot decrypt it; it needs a decrypted EBOOT.elf, made from your own copy, there")
        return
    h, size = head(elf, 64), os.path.getsize(elf)
    r.facts["eboot_elf"] = {"path": elf, "size": size}
    if h[:4] == SELF_MAGIC:
        r.fail("E1", f"This EBOOT is an encrypted SELF, not an ELF. This release needs {need} as an ELF file.")
        return
    if len(h) < 64 or h[:4] != ELF_MAGIC or h[4] != 2 or h[5] != 2 or struct.unpack(">H", h[18:20])[0] != EM_PPC64:
        r.fail("E1", f"This file is not a PS3 executable (a 64-bit big-endian PowerPC ELF). This release needs {need}.")
        return
    info = r.facts["eboot_elf"]
    rows, table_err = None, ""
    try:
        rows = load_eboot_entries(hashes_file)
    except (OSError, ValueError) as e:
        table_err = str(e)
    got = seg = ""
    try:
        got = file_sha256(elf)
        info["sha256"] = got
    except OSError as e:
        table_err = table_err or f"could not read the file to hash it: {e}"
    try:
        seg = segment_sha256(elf) if got else ""
    except (OSError, ValueError) as e:
        info["segment_error"] = str(e)
    info["segment_sha256"] = seg
    how, match = identify_eboot(rows or [], got, seg)
    pick = next((m for m in match if m["title_id"] == disc), match[0]) if match else None
    ver = pick["version"] if pick else EBOOT_ELF_SIZES.get(size)
    info["version"] = ver
    if pick:
        info["match"] = {"by": how, "title_id": pick["title_id"], "app_ver": pick["app_ver"], "status": pick["status"]}
    # E1: the version
    if ver == target:
        r.ok("E1", f"the EBOOT is the {ver} one ({size:,} bytes)")
    elif ver:
        what = build_name(ver, pick["title_id"], pick["region"]) if pick else build_name(ver)
        disc_note = ", the disc's own version" if ver == DISC_EBOOT_VER else ""
        r.fail("E1", f"This EBOOT is {what}{disc_note}. This release needs {need}.")
        return
    else:
        r.warn("E1", f"The EBOOT has an unknown size ({size:,} bytes), neither 1.01 nor 1.29.")
    # H1: the build
    if rows is None or not got:
        r.warn("H1", f"EBOOT not identified ({table_err}); SHA-256 {got or 'not read'}")
        return
    if pick:
        status, by = pick["status"], "by SHA-256" if how == "sha256" else "by its segments"
        what = build_name(pick["version"], pick["title_id"], pick["region"])
        if status not in EBOOT_STATUSES:
            r.fail("H1", f"This EBOOT is {what}, listed with a status this check does not know ({status!r}). "
                         f"This release needs {need}.")
        elif EBOOT_STATUSES[status] == "FAIL":
            r.fail("H1", f"This EBOOT is {what}, a build this port does not run. This release needs {need}.")
        elif disc in REGIONS and pick["title_id"] != disc:
            r.warn("H1", f"Wrong region: this EBOOT is {what}, but the disc is {disc} ({REGIONS[disc]['region']}). "
                         f"This release needs {need}.")
        elif EBOOT_STATUSES[status] == "WARN":
            r.warn("H1", f"This EBOOT is {what}: untested on this port.")
        else:
            r.ok("H1", f"EBOOT matches the known build {what}, {by}")
        return
    refs = [x for x in rows if x["version"] == target and x["sha256"]]
    if not refs:
        r.warn("H1", f"expected SHA-256 of the {target} EBOOT is unknown yet (empty in {os.path.basename(hashes_file)}); "
                     f"this one is {got} ({size:,} bytes), not checked")
    elif any(x["size"] == size for x in refs):
        r.warn("H1", UNKNOWN_EBOOT_TEXT.format(ver=target))
    else:
        r.warn("H1", f"This EBOOT ({size:,} bytes) matches no known Killzone 2 build. This release needs {need}.")


# ------------------------------------------------------------------------------ input reasons (Project Helghast PR #14)
# Adapted from Project Helghast PR #14 (the Killzone 3 PC port, same author, MIT): each failing input gets one line
# naming the input, the path, what is there and what it must hold; swapped disc and update folders and drive roots
# are recognised; a last line says which inputs passed. The check codes (D, I, A, U, E, H, O) are unchanged.
GETTING_FILES = "https://github.com/undecuple/project-pyrrhus/blob/main/docs/GETTING-FILES.md"
INPUT_CODES = {"disc": ("D", "I", "A"), "update": ("U",), "eboot": ("E", "H")}   # check code letters per input
INPUT_NAMES = {"disc": "the disc dump", "update": "the 1.29 update", "eboot": "the decrypted EBOOT"}
INPUT_LABELS = {"disc": "Disc dump", "update": "1.29 update", "eboot": "EBOOT"}   # each failure line's label
MAX_LIST = 400            # folder entries looked at when describing what a wrong folder holds (a drive root can be big)


def _is(d, *rel):
    return os.path.isfile(os.path.join(d, *rel))


def _entries(d):
    """-> (folders, files) names in d, sorted, at most MAX_LIST together; ([], []) when unreadable."""
    try:
        names = sorted(os.listdir(d))[:MAX_LIST]
    except OSError:
        return [], []
    dirs = [n for n in names if os.path.isdir(os.path.join(d, n))]
    return dirs, [n for n in names if n not in dirs]


def _find(names, want):
    """The entry of names equal to want ignoring case (Windows), else ""."""
    return next((n for n in names if n.lower() == want.lower()), "")


def _sfo_kind(path):
    """-> (TITLE_ID, CATEGORY) of a PARAM.SFO, or None when it is missing or unreadable."""
    if not os.path.isfile(path):
        return None
    try:
        sfo = read_sfo(path)
    except (OSError, ValueError, struct.error, IndexError):
        return None
    return sfo.get("TITLE_ID"), sfo.get("CATEGORY")


def is_drive_root(path):
    r"""E:\ or / (the folder is its own parent): two levels are searched there, one elsewhere."""
    p = os.path.abspath(path)
    return os.path.dirname(p) == p


def update_marks(d):
    """The update-only files found in d: USRDIR/added_data_ps3.psarc and the USRDIR/patch_data_ps3 folder (the 1.01
    disc has neither: the RE notes, 1.29 update layout)."""
    out = []
    if _is(d, "USRDIR", UPDATE_DATA):
        out.append(os.path.join("USRDIR", UPDATE_DATA))
    if os.path.isdir(os.path.join(d, "USRDIR", UPDATE_PATCH_DIR)):
        out.append(os.path.join("USRDIR", UPDATE_PATCH_DIR))
    return out


def disc_title_id(d):
    """The TITLE_ID of d/PS3_GAME/PARAM.SFO, or "" when there is none or it is unreadable (from Project Helghast
    PR #17)."""
    kind = _sfo_kind(os.path.join(d, "PS3_GAME", "PARAM.SFO")) if _is(d, "PS3_GAME", "PARAM.SFO") else None
    return (kind[0] or "") if kind else ""


def has_ps3_game(d):
    """A folder holding PS3_GAME/PARAM.SFO, of any game."""
    return _is(d, "PS3_GAME", "PARAM.SFO")


def looks_like_disc(d):
    """A folder holding PS3_GAME/PARAM.SFO whose TITLE_ID is an accepted Killzone 2 id (TITLE_IDS): other games'
    dumps on a drive root are not offered as the disc dump (from Project Helghast PR #17)."""
    return disc_title_id(d) in TITLE_IDS


def looks_like_update(d):
    """A folder that is an installed update: PARAM.SFO of a non-disc category plus USRDIR/EBOOT.BIN, or the update's
    own data (USRDIR/added_data_ps3.psarc or USRDIR/patch_data_ps3) without the disc archive data_ps3.psarc."""
    if update_marks(d) and not psarc_info(os.path.join(d, "USRDIR", PSARC_NAME))[0]:
        return True
    kind = _sfo_kind(os.path.join(d, "PARAM.SFO"))
    return bool(kind and kind[1] != "DG" and _is(d, "USRDIR", "EBOOT.BIN"))


def looks_like_ps3_game(d):
    """The disc's PS3_GAME folder itself (perhaps renamed): a disc-category PARAM.SFO directly in it."""
    kind = _sfo_kind(os.path.join(d, "PARAM.SFO"))
    return bool(kind and kind[1] == "DG")


def candidates(top, depth):
    """-> (disc folders, update folders) among the subfolders of top, `depth` levels down (1 or 2; never deeper:
    a drive root can be large). At most MAX_LIST entries per folder, three of each kind."""
    discs, updates, level = [], [], [top]
    for _ in range(depth):
        nxt = []
        for d in level:
            for n in _entries(d)[0]:
                sub = os.path.join(d, n)
                if looks_like_disc(sub):
                    discs.append(sub)
                elif has_ps3_game(sub):
                    pass          # another game's dump: never a candidate, and not descended into either
                elif looks_like_update(sub):
                    updates.append(sub)
                else:
                    nxt.append(sub)
        level = nxt[:MAX_LIST]
    return discs[:3], updates[:3]


def _hint(path, want):
    """Where the wanted input (disc or update) and the other one seem to be, below path (two levels on a drive root,
    one elsewhere): '; on this drive, the disc dump looks like X: pick that folder; the 1.29 update looks like Y
    (give it as the update)' or ''."""
    root = is_drive_root(path)
    discs, updates = candidates(path, 2 if root else 1)
    if not discs and not updates:
        return ""
    where = "on this drive" if root else "one folder down"
    first, second = (discs, updates) if want == "disc" else (updates, discs)
    other = "update" if want == "disc" else "disc"
    parts = []
    if first:
        parts.append(f"{INPUT_NAMES[want]} looks like {' or '.join(first)}: pick that folder")
    if second:
        parts.append(f"{INPUT_NAMES[other]} looks like {' or '.join(second)} (give it as the {other})")
    return f"; {path} is a drive root" * root + f"; {where}, " + "; ".join(parts)


def _isos(path):
    """.iso files in path, and one level down when path is a drive root: names for the ones in path, full paths for
    the ones in a subfolder (at most 3; from Project Helghast PR #17)."""
    dirs, files = _entries(path)
    out = [n for n in files if n.lower().endswith(".iso")]
    if is_drive_root(path):
        for d in dirs:
            out += [os.path.join(path, d, n) for n in _entries(os.path.join(path, d))[1] if n.lower().endswith(".iso")]
    return out[:3]


def disc_found(path):
    """-> (what the disc input path holds, structural): structural = the input is the wrong thing altogether, so
    the D1-D3 messages add nothing."""
    if not path or not os.path.exists(path):
        return f"nothing is there (no such file or folder: {path})", True
    if os.path.isfile(path):
        return f"the file {os.path.basename(path)}, read as a disc ISO", False
    dirs, files = _entries(path)
    if _find(dirs, "PS3_GAME"):
        need = [os.path.join("PS3_GAME", "PARAM.SFO"), os.path.join("PS3_GAME", "USRDIR", "EBOOT.BIN"),
                os.path.join("PS3_GAME", "USRDIR", PSARC_NAME)]
        miss = [n for n in need[:2] if not _is(path, n)]
        parts, missing = psarc_info(os.path.join(path, need[2]))[:2]
        if not parts or missing:
            miss.append(need[2])
        if miss:
            return f"{path} holds PS3_GAME, but not " + " or ".join(miss), False
        return f"{path} holds PS3_GAME with PARAM.SFO, EBOOT.BIN and {PSARC_NAME}", False
    if looks_like_update(path):       # the update folder given as the disc
        have = [n for n in ("PARAM.SFO", os.path.join("USRDIR", "EBOOT.BIN")) if _is(path, n)] + update_marks(path)
        return (f"{path} looks like the 1.29 update ({', '.join(have)}), not the disc dump: give it as the 1.29 "
                "update, and the folder that holds PS3_GAME as the disc dump"), True
    what = f"{path} holds no PS3_GAME folder"
    if looks_like_ps3_game(path):
        return what + "; it holds a disc PARAM.SFO directly, so it looks like the PS3_GAME folder under another name", True
    hint = _hint(path, "disc")
    isos = _isos(path)       # named beside the folder hints, not only without them (Project Helghast PR #17)
    if hint:
        what += hint
    if isos:
        what += "; " + ("it holds the ISO file " if len(isos) == 1 else "it holds the ISO files ") + \
            ", ".join(isos) + ": pick that file"
    if hint or isos:
        pass
    elif not dirs and not files:
        what += " (the folder is empty)"
    else:
        what += f" ({len(dirs)} folders, {len(files)} files)"
    return what, True


def update_found(path):
    """-> (what the update input path holds, structural), as disc_found."""
    if not path or not os.path.exists(path):
        return f"nothing is there (no such folder: {path})", True
    if os.path.isfile(path):
        return f"{path} is a file, not a folder" + (
            " (an update package, not an installed update)" if path.lower().endswith(".pkg") else ""), True
    dirs, files = _entries(path)
    if has_ps3_game(path) or _find(dirs, "PS3_GAME"):     # the disc (any game's) given as the update
        return (f"{path} holds PS3_GAME, so it looks like the disc dump, not the update: give it as the disc dump, "
                "and the installed update folder as the 1.29 update"), True
    if looks_like_ps3_game(path):
        return (f"{path} holds the disc's PARAM.SFO (category DG), so it looks like the disc's PS3_GAME folder, not "
                "the update: give the folder above it as the disc dump, and the installed update folder as the 1.29 "
                "update"), True
    have = [n for n in ("PARAM.SFO", os.path.join("USRDIR", "EBOOT.BIN")) if _is(path, n)] + update_marks(path)
    if not have:
        what = f"{path} holds none of these files"
        hint = _hint(path, "update")
        pkgs = [n for n in files if n.lower().endswith(".pkg")]
        if hint:
            what += hint
        elif pkgs:
            what += f"; it holds the package {pkgs[0]}, which is not an installed update"
        elif not dirs and not files:
            what += " (the folder is empty)"
        else:
            what += f" ({len(dirs)} folders, {len(files)} files)"
        return what, True
    return f"{path} holds " + ", ".join(have), False


def eboot_found(path):
    """-> (what the EBOOT input path is, structural), as disc_found."""
    if not path or not os.path.exists(path):
        return f"no file at {path}: EBOOT.elf is missing", True
    if os.path.isdir(path):
        return f"{path} is a folder, not the EBOOT.elf file", True
    return f"the file {path} ({os.path.getsize(path):,} bytes)", False


DISC_NEED = ("It must be the folder that holds PS3_GAME (with PS3_GAME{s}PARAM.SFO, PS3_GAME{s}USRDIR{s}EBOOT.BIN and "
             "PS3_GAME{s}USRDIR{s}" + PSARC_NAME + "), the PS3_GAME folder itself, or a decrypted .iso file picked "
             "as a file")
UPDATE_NEED = ("It must be the installed 1.29 update folder (dev_hdd0{s}game{s}{tid}), holding PARAM.SFO "
               "and USRDIR{s}EBOOT.BIN, with USRDIR{s}" + UPDATE_DATA + " and USRDIR{s}" + UPDATE_PATCH_DIR)
EBOOT_NEED = "It must be EBOOT.elf, the decrypted 1.29 EBOOT of your own copy (see " + GETTING_FILES + ")"


def update_id(r):
    """The title id the update folder must carry: the disc's (r.facts), else a placeholder naming the US one (the
    disc's region is not known)."""
    tid = (r.facts.get("disc") or {}).get("TITLE_ID")
    return tid if tid in REGIONS else "<your disc's title id, such as " + TITLE_ID + ">"


def input_reasons(r, dump, update, eboot):
    """One line per failing input (its label, the path, what is there, what it must hold, and its FAIL messages
    unless the input is the wrong thing altogether), the other checks' FAIL messages (O1, O2), and which inputs
    passed. -> r.facts["reasons"]; firstrun.py shows them as REASON lines (the setup's box, the launcher's dialog,
    the console). Adapted from Project Helghast PR #14."""
    fails = [c for c in r.checks if c["level"] == "FAIL"]
    if not fails:
        return []
    of = {k: [c for c in r.checks if c["code"][:1] in v] for k, v in INPUT_CODES.items()}
    found = {"disc": lambda: disc_found(dump), "update": lambda: update_found(update),
             "eboot": lambda: eboot_found(eboot)}
    need = {"disc": DISC_NEED, "update": UPDATE_NEED, "eboot": EBOOT_NEED}
    lines, passed = [], []
    for k in ("disc", "update", "eboot"):
        bad = [c["message"] for c in of[k] if c["level"] == "FAIL"]
        if not bad:
            if of[k] and (k != "update" or update):
                passed.append(INPUT_NAMES[k])
            continue
        what, structural = found[k]()
        line = f"{INPUT_LABELS[k]} failed: {what}. " + need[k].format(s=os.sep, tid=update_id(r)) + "."
        if not structural:
            line += " Found: " + "; ".join(b.rstrip(".") for b in bad) + "."   # the E1/H1 texts are sentences
        lines.append(line)
    codes = tuple(x for v in INPUT_CODES.values() for x in v)
    lines += [c["message"] for c in fails if not c["code"].startswith(codes)]
    if passed:
        lines.append("Passed: " + (", ".join(passed[:-1]) + " and " if len(passed) > 1 else "") + passed[-1] + ".")
    return lines


BUILD_DLL = "at3_standalone.dll"   # built beside kz2.exe (patch 6022, PS3RECOMP_AT3_SHARED); kz2.exe imports it


def check_build(obj_dir):
    """-> problems for the finished build folder (where kz2.exe was linked): kz2.exe imports at3_standalone.dll, so
    without it the game does not start at all (Windows: 'the code execution cannot proceed because
    at3_standalone.dll was not found'). The FFmpeg DLLs are not checked here: they ship prebuilt in the payload."""
    bad = []
    if not os.path.isfile(os.path.join(obj_dir, "kz2.exe")):
        bad.append(f"kz2.exe was not built in {obj_dir}")
    dll = os.path.join(obj_dir, BUILD_DLL)
    if not os.path.isfile(dll):
        bad.append(f"{BUILD_DLL} is missing from {obj_dir}: the build did not produce it, and kz2.exe will not start "
                   f"without it (rebuild; the compile step must finish without errors)")
    elif os.path.getsize(dll) == 0:
        bad.append(f"{dll} is empty")
    return bad


# B2 (issue #16): kz2.exe must hold the run-time FFmpeg loader. ps3recomp's libs/codec/ffmpeg_runtime.c
# is compiled only with PS3RECOMP_FFMPEG_RUNTIME (port/kz2/CMakeLists.txt, FFmpeg's headers given); it names the two
# DLLs it loads, from the headers' version majors, so both names in the exe = the loader is in and looks for the DLLs
# the payload ships beside it (firstrun.FFMPEG_DLLS). v0.1.2 built every player's kz2.exe without it: black movies,
# silent AC-3, no "[ffmpeg]" line in the log.
FFMPEG_DLL_NAMES = (b"avcodec-63.dll", b"avutil-61.dll")


def exe_strings_missing(path, names, chunk=1 << 22):
    """-> the byte strings of `names` that `path` does not contain (read in chunks; a name split over two chunks is
    still found)."""
    left, keep, tail = set(names), max(len(n) for n in names) - 1, b""
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            buf = tail + block
            left = {n for n in left if n not in buf}
            if not left:
                break
            tail = buf[-keep:] if keep else b""
    return [n for n in names if n in left]


def check_ffmpeg(obj_dir):
    """-> B2 problems: kz2.exe was built without the FFmpeg loader (or for other DLL names)."""
    exe = os.path.join(obj_dir, "kz2.exe")
    if not os.path.isfile(exe):
        return []          # B1 says so
    gone = exe_strings_missing(exe, FFMPEG_DLL_NAMES)
    if not gone:
        return []
    return [f"kz2.exe was built without movie decoding (it never loads {', '.join(n.decode() for n in gone)}): the "
            f"intro and cutscenes would be black and silent. The build was configured without FFmpeg's headers "
            f"(ffmpeg{os.sep}include in the install); repair or reinstall with the current installer"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--build-dir", help="check the finished build folder (B1: kz2.exe + at3_standalone.dll; B2: kz2.exe has the FFmpeg loader) instead of the game files")
    ap.add_argument("--dump")
    ap.add_argument("--update")
    ap.add_argument("--eboot")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-psarc-bytes", type=int, default=MIN_PSARC_BYTES)
    ap.add_argument("--hashes", default=HASHES_FILE)
    ap.add_argument("--psarc-hashes", default=PSARC_HASHES_FILE)
    ap.add_argument("--build", help="the build folder: A1 caches the archive's SHA-256 there; refused (O1) inside OneDrive")
    ap.add_argument("--root", help="the install folder; refused (O1) when inside OneDrive")
    ap.add_argument("--progress", action="store_true", help="print ARCHIVE-HASH progress lines while A1 hashes")
    ap.add_argument("--skip-archive-hash", action="store_true", help="leave A1 (the archive's SHA-256) out")
    ap.add_argument("--target", choices=("1.01", "1.29"), default="1.29",
                    help="the EBOOT version the build is for (firstrun.py passes its tree's)")
    a = ap.parse_args(argv)
    if a.build_dir:
        bad = check_build(a.build_dir)
        for b in bad:
            print(f"FAIL B1: {b}")
        b2 = check_ffmpeg(a.build_dir)
        for b in b2:
            print(f"FAIL B2: {b}")
        bad += b2
        print("build checks:", "FAIL" if bad else "pass")
        return 1 if bad else 0
    if not a.dump:
        ap.error("--dump is required")
    r = Report()
    dump = resolve_dump(a.dump)
    if dump != a.dump:
        r.ok("D0", f"INFO: {a.dump} is inside the dump; using the folder that holds PS3_GAME: {dump}")
    upd = resolve_update(a.update) if a.update else a.update
    if upd != a.update:
        r.ok("U0", f"INFO: {a.update} is the update's USRDIR; using the update folder: {upd}")
    a.dump, a.update = dump, upd
    check_onedrive_tree(r, a.root, a.build)
    check_path_chars(r, a.root, a.build)
    iso = os.path.isfile(a.dump)       # a decrypted disc ISO instead of a folder
    # before anything is read: opening an online-only placeholder would start a download of the 6.5 GiB archive
    if check_online_only(r, a.dump if os.path.exists(a.dump) else "",
                         a.update if a.update and os.path.isdir(a.update) else "", a.eboot or ""):
        r.facts["reasons"] = input_reasons(r, a.dump, a.update, a.eboot or "")
        return finish(r, a)
    if iso:
        check_dump_iso(r, a.dump, a.min_psarc_bytes)
    elif not os.path.isdir(a.dump):
        r.fail("D0", f"dump folder not found: {a.dump}")
    else:
        check_dump(r, a.dump, a.min_psarc_bytes)
        psarc = os.path.join(a.dump, "PS3_GAME", "USRDIR", PSARC_NAME)
        if not a.skip_archive_hash and not any(c["code"] == "D3" and c["level"] == "FAIL" for c in r.checks) \
                and "psarc" in r.facts:
            def prog(done, total):
                print(f"ARCHIVE-HASH done={done} total={total}", flush=True)
            check_psarc_hash(r, psarc, (r.facts.get("disc") or {}).get("TITLE_ID"), a.psarc_hashes, a.build,
                             prog if a.progress else None)
    if a.update:
        if not os.path.isdir(a.update):
            r.fail("U0", f"update folder not found: {a.update}")
        else:
            check_update(r, a.update, (r.facts.get("disc") or {}).get("TITLE_ID"))
    else:
        r.warn("U0", "no --update given: the 1.29 update is required (the port is built on its EBOOT)")
    elf = a.eboot
    if not elf:
        # EBOOT.elf sits next to EBOOT.BIN; a dump may also hold an ELF as EBOOT.BIN.
        cand = [os.path.join(a.update, "USRDIR", n) for n in ("EBOOT.elf", "EBOOT.BIN")] if a.update else []
        if not iso:
            cand += [os.path.join(a.dump, "PS3_GAME", "USRDIR", n) for n in ("EBOOT.elf", "EBOOT.BIN")]
        cand = cand or [os.path.join(os.path.dirname(os.path.abspath(a.dump)), "EBOOT.elf")]
        elf = next((c for c in cand if os.path.isfile(c) and head(c, 4) == ELF_MAGIC), cand[0])
    check_eboot_elf(r, elf, a.target, a.update, a.hashes)
    r.facts["reasons"] = input_reasons(r, a.dump, a.update, elf)
    return finish(r, a)


def finish(r, a):
    if a.json:
        print(json.dumps({"ok": r.passed, "checks": r.checks, "facts": r.facts}, indent=2))
    else:
        for c in r.checks:
            print(f"{c['level']:4} {c['code']}: {c['message']}")
        print("first-run checks:", "pass" if r.passed else "FAIL")
        for ln in r.facts.get("reasons", []):    # firstrun.py's console reads these back (text_reasons)
            print(f"  {ln}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
