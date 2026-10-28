#!/usr/bin/env python3
"""First-run build pipeline for the Project Pyrrhus installer and portable zip (Killzone 2 PC port).
From Project Helghast tools/release/firstrun.py (Project Helghast), adapted to Killzone 2: an SPU lift step from
tools/spu (spu_step.py), no shader warm-up step (KZ3-only for now; see the release notes).

Runs the checks, then lifts and compiles the port on the player's machine, as a table of steps (name, weight, command
builder, done-marker). Standard library only, Python 3.11+, Windows and Linux.

    firstrun.py --dump DIR|ISO --update DIR [--eboot FILE] [--root DIR] [--build DIR] [--jobs N] [--toolchain DIR]
                [--log-dir DIR] [--log-name NAME] [--dry-run]
    firstrun.py --interactive [--portable] [same options; --dump/--update/--eboot become the defaults it offers]

  --dump       the decrypted disc dump folder (holds PS3_GAME; a pick of PS3_GAME or PS3_GAME/USRDIR is taken as the
               folder above), or a decrypted disc ISO file (adapted from Project Helghast v0.1.2). For an ISO the
               check step checks the image (firstrun_check.py), then copies PS3_DISC.SFB and everything under PS3_GAME
               out of it into <root>/game/disc, hashing the disc archive on the way (A1 without a second read), and the
               rest of the build uses that folder as the dump; the ISO is only read. Files already extracted with the
               same size are kept; too little free disk space (the missing bytes + 1 GiB) stops with a message before
               anything is written.
  --root       the install (or source tree) holding the toolkit and our tools; default: two folders above this script
  --build      where everything generated goes; default <root>/build (the dump is never written to)
  --jobs       compile/lift job count; default from free RAM: (available - 8 GB) / 1.5 GB, clamped 1..8 (build-kz2.sh)
  --toolchain  an llvm-mingw folder (bin/x86_64-w64-mingw32-clang[.exe]), built with port/cmake/llvm-mingw.cmake;
               default: the payload's <root>/toolchain/llvm-mingw when present, else port/cmake/mingw-w64.cmake
               (NixOS cross).
               The payload's toolchain/cmake, toolchain/ninja and (Windows) toolchain/python are used when present.
  --log-dir    folder the setup.exe / zip was started from (Inno passes {src}); not writable -> the temp folder
  --log-name   default Project-Pyrrhus-setup.log; an earlier log of the same name is renamed with its start time
  --status-file  also keep the LOG line and the latest PROGRESS/RESULT line in this file (for the Inno wizard)
  --stop-file    stop when this file appears (the wizard's Stop button): the running tool's process tree ends,
                 its step leaves no marker, RESULT step=cancelled, exit 130; the next start resumes there
  --dry-run    print the plan (steps, weights, done or pending, commands) and the log location; runs and writes nothing
  --interactive  the portable zip's text UI (run.cmd): asks for the dump, update and EBOOT
               (defaults: the arguments, else the last run's build/paths.json, else RPCS3's usual folder), runs the
               check until it passes (or the player quits), offers the one-shot version check (opt-in, asks first),
               writes kz2-install.ini, then builds with one console progress bar instead of the raw lines
  --portable   with --interactive: saves and settings stay in the install folder (kz2-install.ini portable=1)
  --bar        the console progress bar without the questions (the launcher's resume/rebuild in a console window)
  --check-first  with --interactive and --dump/--update (the folders the installer wizard wrote to kz2-install.ini
               [paths]): check them first and ask for folders only after a FAIL or when c is pressed; the wizard's
               other answers (version check, pad layout, prompts, display) are kept, not asked again

Machine-readable lines on stdout, for the Inno wizard's output page and the zip's console:
  LOG path=<file>
  PROGRESS step=N/M name=<step> done=X total=Y elapsed=S pct=P      (P = whole pipeline, weights applied)
  RESULT ok=1|0 step=<failed step or -> elapsed=S
The compile step's done/total come from Ninja's "[x/y]" status lines. Every other line is the step's own output.

Resume: each finished step writes <build>/.firstrun/<NN>-<name>.done (JSON: the inputs fingerprint, duration). A
cancel (Ctrl+C, the wizard's Cancel = terminate) writes nothing for the running step, so the next start resumes at
the first unfinished step. The check step (firstrun_check.py) always runs first; if its facts change (another EBOOT,
other folders) every later marker is stale and the build starts over.

A step whose command builder raises StepFailed (a lift table missing from the install, port files dated in the
future) stops there with its plain message and RESULT ok=0; --dry-run prints it as STOP.

Exit 0 = built, 1 = a step failed, 2 = usage, 130 = cancelled.
KZ3's runner ran every step on the payload's Windows Python under Proton; this KZ2 copy has run only in the host
test (synthetic steps). Weights: ASSUMPTION (from the developer build's Linux timings) until a KZ2 first run is timed.
"""
import argparse
import dataclasses
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG_NAME = "Project-Pyrrhus-setup.log"
MARKER_DIR = ".firstrun"
KEEP_LOG_COPIES = 5                      # the install's logs\ keeps the last five
NINJA_RE = re.compile(r"^\[(\d+)/(\d+)\]")

# Lift constants per EBOOT version (tools/lift.sh). The tree decides which one (tree_eboot_ver): its runtime glue
# (port/kz2) is written for one EBOOT's addresses, so a lift of another EBOOT would build but not boot.
# 1.01 = the disc EBOOT (tools/lift.sh's defaults: end of the last executable section, r2 of the entry descriptor).
# 1.29 = the port's target: code end 0xBD0D0C, TOC 0xEC3038;
# chosen once tools/lift.sh's defaults are these.
# Lift constants and the PPU override list per EBOOT version, as in tools/lift.sh's version table
EBOOT_VERS = {"101": {"code_end": "0xbba45c", "toc": "0xeb2958", "check": "1.01", "overrides": "ppu_overrides-101.txt"},
              "129": {"code_end": "0xbd0d0c", "toc": "0xec3038", "check": "1.29", "overrides": "ppu_overrides.txt"}}
DEFAULT_VER = "129"     # no lift.sh, or nothing in it matches: the version main builds (lift.sh's default since 1.29)
GIB = 1 << 30
# Release without debug info, at KZ3's verified build's optimisation level: the dev builds are RelWithDebInfo
# (-O2 -g); CMake's Release default is -O3, untried on the lifted chunks (more compile memory and time, ASSUMPTION).
RELEASE_FLAGS = "-O2 -DNDEBUG"
# tools/lift.sh's chunk count: 64 chunks, ~1.5 GB per compile job (KZ3's measurement) instead of 4.4-6.7 GB for
# the lifter's default 8.
LIFT_CHUNKS = 64
# The lift's worker count is capped: KZ3 measured it at -j4 (PPU lift 30 s, its main process 2.3 GB); more workers
# were never measured and gain little on a step this short.
LIFT_JOBS_MAX = 4


# ---------------------------------------------------------------------------------------------------------- context
@dataclass
class Ctx:
    root: str
    build: str
    dump: str = ""
    iso: str = ""                   # the decrypted ISO the player picked, until the check step has extracted it
    progress: Callable | None = field(default=None, repr=False)   # (done, total) -> PROGRESS line, set by the Runner
    say: Callable | None = field(default=None, repr=False)        # line -> the run's output and log, set by the Runner
    update: str = ""
    eboot: str = ""
    jobs: int = 1
    toolchain: str = ""
    python: str = sys.executable
    cmake: str = "cmake"
    ninja: str = ""
    facts: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict, repr=False)

    def tool(self, *rel):
        """Our tools: <root>/kz2-setup/... in the release, <root>/tools/... in the source tree."""
        for base in ("kz2-setup", "tools"):
            p = os.path.join(self.root, base, *rel)
            if os.path.exists(p):
                return p
        return os.path.join(self.root, "tools", *rel)

    @property
    def ps3recomp(self):
        """The patched toolkit: <root>/ps3recomp in the release, work/ps3recomp-patched in the source tree."""
        for rel in ("ps3recomp", os.path.join("work", "ps3recomp-patched")):
            p = os.path.join(self.root, rel)
            if os.path.isdir(p):
                return p
        return os.path.join(self.root, "ps3recomp")

    @property
    def py(self):
        """The Python command for the steps' scripts: UTF-8 mode (KZ3: Windows Python's default text encoding is
        the ANSI code page, so the PPU lifter wrote its comments' em dashes as cp1252 0x97 where the Linux lift
        writes UTF-8; the C was otherwise identical). PYTHONUTF8 in env() as well; -X works in the embeddable
        Python's isolated mode, where environment variables may be ignored."""
        return [self.python, "-X", "utf8"]

    @property
    def ver(self):
        """The EBOOT version this tree is built for ("101" or "129"): tree_eboot_ver, read once."""
        if "ver" not in self.cache:
            self.cache["ver"] = tree_eboot_ver(self)
        return self.cache["ver"]

    def b(self, *rel):
        return os.path.join(self.build, *rel)

    def env(self):
        """Child environment: the bundled compiler, CMake and Ninja first on PATH (release layout)."""
        extra = [os.path.join(self.toolchain, "bin")] if self.toolchain else []
        extra += [os.path.join(self.root, "toolchain", *d) for d in (("cmake", "bin"), ("ninja",))]
        e = dict(os.environ)
        e["PATH"] = os.pathsep.join([d for d in extra if os.path.isdir(d)] + [e.get("PATH", "")])
        e["PYTHONIOENCODING"] = "utf-8"
        e["PYTHONUTF8"] = "1"
        e["KZ2_EBOOT_VER"] = self.ver                                # the tree's EBOOT version
        e["KZ2_EBOOT_ELF"] = self.eboot
        e["KZ2_ANALYSIS_DIR"] = self.b("analysis")
        if fixups_file(self):
            e["PPU_JT_HINTS"] = self.b("analysis", "jt_hints.txt")    # written by lift_fixups.py before the lift
        return e

    def parts(self):
        """The build's inputs as three hashes: `base` = the folders and the EBOOT's identity from
        the check; `lift` = what the lifts read besides the EBOOT (lift_inputs_hash); `runtime` = the port version
        (VERSION.txt). A new release that changes only the runtime glue recompiles without lifting again."""
        key = {"dump": self.dump, "update": self.update, "eboot": self.eboot,
               "eboot_elf": self.facts.get("eboot_elf"), "update_sfo": self.facts.get("update")}
        if "lift" not in self.cache:
            self.cache["lift"] = lift_inputs_hash(self)
        return {"base": _h16(json.dumps(key, sort_keys=True)), "lift": self.cache["lift"],
                "runtime": _h16(port_version(self.root))}

    def fingerprint(self, keys=()):
        """One hash of `base` plus the named extra parts ("lift", "runtime"); a step's marker stores the one for
        its Step.keys, so a lift-input change re-runs the lifts but not the load and inventory steps."""
        p = self.parts()
        return p["base"] if not keys else _h16("|".join([p["base"]] + [p[k] for k in keys]))


@dataclass
class Step:
    name: str                                   # short id, also the marker file name
    label: str                                  # what the wizard shows ("Lifting PPU code")
    weight: float                               # share of the whole bar (normalised over the table)
    commands: Callable[[Ctx], list]             # -> list of argv lists, run in order
    always: bool = False                        # run even when its marker exists (the check)
    ninja: bool = False                         # parse "[x/y]" for progress
    clean: Callable[[Ctx], list] = lambda c: []  # folders under <build> removed before a (re)run
    after: Callable[[Ctx], None] | None = None  # in-process work after the commands (record, stamp)
    keys: tuple = ()                            # extra fingerprint parts its marker depends on (Ctx.parts)
    optional: bool = False                      # a failure is logged, the result stays ok (the port is built)


class StepFailed(Exception):
    """A step that cannot run, with the plain message for the player (from Project Helghast v0.1.2 and v0.1.3)."""


def _h16(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


LIFT_INPUTS = [   # (base: "root" | "tools" | "toolkit", glob) : what the PPU lift reads besides the EBOOT
    ("root", "port/kz2/ppu_overrides*.txt"), ("root", "port/kz2/ppu_lift_fixups-*.txt"),
    ("tools", "lift.sh"), ("tools", "release/lift_fixups.py"),
    ("tools", "release/spu_step.py"), ("tools", "spu/lift_spu.py"), ("tools", "spu/gen_spu_register.py"),
    ("tools", "spu/kz2ver.py"), ("root", "re/wws_jobs_v*.tsv"),      # the SPU lift's scripts and image tables
    ("toolkit", "tools/*.py"), ("toolkit", ".kz2-patchset"),
]


def lift_inputs_hash(c):
    """SHA-256 (16 hex) over the lift inputs' relative names and contents; a missing file counts as missing."""
    import glob
    tools = os.path.dirname(os.path.dirname(c.tool("release", "firstrun.py")))
    bases = {"root": c.root, "tools": tools, "toolkit": c.ps3recomp}
    h = hashlib.sha256()
    for base, pat in LIFT_INPUTS:
        hits = sorted(glob.glob(os.path.join(glob.escape(bases[base]), pat)))
        h.update(f"{base}:{pat}:{len(hits)}\n".encode())
        for p in hits:
            h.update(os.path.relpath(p, bases[base]).replace(os.sep, "/").encode() + b"\0")
            with open(p, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()[:16]


# ------------------------------------------------------------------------------------------------- the step table
def cmd_check(c):
    # --build: A1 caches the disc archive's SHA-256 there; --root/--build: O1 refuses them inside OneDrive (adapted
    # from Project Helghast v0.1.2); --progress: ARCHIVE-HASH lines (Runner.run_cmd's bar)
    a = [*c.py, c.tool("release", "firstrun_check.py"), "--dump", c.dump, "--json",
         "--target", EBOOT_VERS[c.ver]["check"], "--build", c.build, "--root", c.root, "--progress"]
    if c.update:
        a += ["--update", c.update]
    if c.eboot:
        a += ["--eboot", c.eboot]
    return [a]


def cmd_load(c):
    pt, an = c.ps3recomp, c.b("analysis")
    return [[*c.py, os.path.join(pt, "tools", "ppu_loader.py"), c.eboot, "-o", an + os.sep],
            [*c.py, os.path.join(pt, "tools", "find_functions.py"), c.eboot,
             "--seed-json", os.path.join(an, eboot_stem(c) + ".functions.json"), "--output", os.path.join(an, "functions.json")]]


def eboot_stem(c):
    """ppu_loader.py names its outputs after the ELF's file name (EBOOT-129.elf -> EBOOT-129.imports.json, as
    tools/lift.sh's STEM): the player's file need not be called EBOOT.elf."""
    return os.path.splitext(os.path.basename(c.eboot or "EBOOT.elf"))[0]


LIFT_CONST_RE = re.compile(r'^(CODE_END|TOC)="\$\{KZ2_\1:-(0x[0-9a-fA-F]+)\}"', re.M)
# lift.sh since the 1.29 move: VER="${KZ2_EBOOT_VER:-129}" picks a row of its version table
LIFT_VER_RE = re.compile(r'^VER="\$\{KZ2_EBOOT_VER:-(\d+)\}"', re.M)


def tree_eboot_ver(c):
    """The EBOOT version the tree's glue is written for: the entry of EBOOT_VERS whose code end and TOC are
    tools/lift.sh's default: `VER="${KZ2_EBOOT_VER:-129}"` (its version table, since the 1.29 move), else the older
    `CODE_END="${KZ2_CODE_END:-0x...}"` / `TOC=...` defaults, else DEFAULT_VER. A payload has no lift.sh:
    kz2-setup/eboot_ver.txt (assemble_payload.py) holds the answer for its tree. (The VM kit pre-flight found a
    payload stamped 1.01 because only the older form was read.)"""
    try:   # the payload: assemble_payload.py wrote the source tree's answer
        with open(os.path.join(c.root, "kz2-setup", "eboot_ver.txt"), encoding="utf-8") as f:
            v = f.read().strip()
        if v in EBOOT_VERS:
            return v
    except OSError:
        pass
    try:
        with open(c.tool("lift.sh"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return DEFAULT_VER
    m = LIFT_VER_RE.search(text)
    if m and m.group(1) in EBOOT_VERS:
        return m.group(1)
    got = {k: v.lower() for k, v in LIFT_CONST_RE.findall(text)}
    for ver, e in EBOOT_VERS.items():
        if e["code_end"] and got.get("CODE_END") == e["code_end"] and got.get("TOC") == e["toc"]:
            return ver
    return DEFAULT_VER


def overrides_file(c):
    """The PPU override table for this tree's EBOOT version (EBOOT_VERS, as tools/lift.sh picks it): ppu_overrides.txt
    for 1.29, ppu_overrides-101.txt for 1.01. The tables hold function addresses, so another version's table would
    replace the wrong functions (KZ3 issue 3, 88aa92c: its 1.14 lift was given the 1.00 table); a missing table stops
    the lift instead of falling back to the other one."""
    name = EBOOT_VERS[c.ver]["overrides"]
    p = os.path.join(c.root, "port", "kz2", name)
    if not os.path.isfile(p):
        raise StepFailed(f"the {EBOOT_VERS[c.ver]['check']} PPU override table (port/kz2/{name}) is missing from this "
                         "install; reinstall Project Pyrrhus")
    return p


def fixups_file(c):
    """port/kz2/ppu_lift_fixups-<ver>.txt (KZ3 had one for its update EBOOT), or "" when this tree has none."""
    p = os.path.join(c.root, "port", "kz2", f"ppu_lift_fixups-{c.ver}.txt")
    return p if os.path.isfile(p) else ""


def cmd_ppu_lift(c):
    # The lift fixups (KZ3's for its update EBOOT; KZ2 has none yet): lift_fixups.py writes functions.fixed.json
    # and jt_hints.txt (the lifter reads the hints through PPU_JT_HINTS, set in Ctx.env); without a fixups file the list is lifted as is.
    an = c.b("analysis")
    funcs, cmds = os.path.join(an, "functions.json"), []
    if fixups_file(c):
        cmds.append([*c.py, c.tool("release", "lift_fixups.py"), "--fixups", fixups_file(c), "--functions", funcs,
                     "--out", os.path.join(an, "functions.fixed.json"), "--jt-hints", os.path.join(an, "jt_hints.txt")])
        funcs = os.path.join(an, "functions.fixed.json")
    return cmds + [[*c.py, os.path.join(c.ps3recomp, "tools", "ppu_lifter.py"), c.eboot,
                    "--functions", funcs,
                    "--hle-stubs", os.path.join(an, eboot_stem(c) + ".imports.json"), "--toc", EBOOT_VERS[c.ver]["toc"],
                    "--code-end", EBOOT_VERS[c.ver]["code_end"],
                    "--overrides", overrides_file(c),
                    "-j", str(min(c.jobs, LIFT_JOBS_MAX)), "--chunks", str(LIFT_CHUNKS), "--output", c.b("recomp")]]


def cmd_spu_lift(c):
    """The SPU lift (step 3b of public/docs/BUILDING.md): tools/spu/lift_spu.py then gen_spu_register.py through
    spu_step.py, on the same EBOOT and version (KZ2_EBOOT_VER = the tree's, set in Ctx.env). -> <build>/spu/lift."""
    return [[*c.py, c.tool("release", "spu_step.py"), "--ps3recomp", c.ps3recomp, "--out", c.b("spu"),
             "--eboot", c.eboot, "-j", str(min(c.jobs, LIFT_JOBS_MAX))]]


def payload_tools(root):
    """The release's bundled tools that exist (<root>/toolchain/...; fetched by fetch_toolchain.py and copied
    by assemble_payload.py --toolchain): llvm_mingw (folder), cmake, ninja, python (Windows only: python.exe)."""
    exe = ".exe" if os.name == "nt" else ""
    t = os.path.join(root, "toolchain")
    found = {}
    lm = os.path.join(t, "llvm-mingw")
    if os.path.isfile(os.path.join(lm, "bin", "x86_64-w64-mingw32-clang" + exe)):
        found["llvm_mingw"] = lm
    for k, p in (("cmake", os.path.join(t, "cmake", "bin", "cmake" + exe)), ("ninja", os.path.join(t, "ninja", "ninja" + exe)),
                 ("python", os.path.join(t, "python", "python.exe"))):
        if os.path.isfile(p) and (k != "python" or os.name == "nt"):
            found[k] = p
    return found


def cm_path(p, sep=os.sep):
    """A path for a CMake -D value: forward slashes on Windows. A backslash in a -D value that a CMake file later
    expands inside a string (LLVM_MINGW_ROOT -> CMAKE_C_COMPILER, RECOMP_DIR) can be read as an escape
    (ASSUMPTION, from KZ3: not seen yet); forward slashes work on every Windows CMake.
    A no-op on Linux."""
    return p.replace("\\", "/") if sep == "\\" else p


def cmake_file(c, name):
    """port/cmake/<name> in the source tree and the payload (assemble_payload copies port/), else <root>/cmake."""
    p = os.path.join(c.root, "port", "cmake", name)
    return p if os.path.isfile(p) else os.path.join(c.root, "cmake", name)


def cmd_configure(c):
    refuse_future_files(c)
    a = [c.cmake, "-S", os.path.join(c.root, "port", "kz2"), "-B", c.b("obj"), "-G", "Ninja",
         "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_C_FLAGS_RELEASE={RELEASE_FLAGS}",
         f"-DCMAKE_CXX_FLAGS_RELEASE={RELEASE_FLAGS}", f"-DPS3RECOMP_DIR={cm_path(c.ps3recomp)}",
         f"-DRECOMP_DIR={cm_path(c.b('recomp'))}", f"-DSPU_DIR={cm_path(c.b('spu', 'lift'))}",
         f"-DPython3_EXECUTABLE={cm_path(c.python)}"]
    if c.ninja:
        a.append(f"-DCMAKE_MAKE_PROGRAM={cm_path(c.ninja)}")
    if c.toolchain:     # llvm-mingw: the release's compiler
        a += [f"-DCMAKE_TOOLCHAIN_FILE={cm_path(cmake_file(c, 'llvm-mingw.cmake'))}",
              f"-DLLVM_MINGW_ROOT={cm_path(c.toolchain)}"]
    else:
        a += [f"-DCMAKE_TOOLCHAIN_FILE={cm_path(cmake_file(c, 'mingw-w64.cmake'))}"]
    return [a]


SOURCES_RECORD = ("_firstrun_sources.json",)   # under <build>: the payload hashes of the last finished build


def payload_hashes(root):
    """{path: sha256} of the payload's own files from <root>/manifest.json (assemble_payload.py); {} for a source
    tree (no manifest)."""
    try:
        with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
            return {e["path"]: e["sha256"] for e in json.load(f).get("files", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def prepare_sources(c):
    """configure's clean hook (from KZ3). Installing over an earlier version keeps each payload file's own time
    stamp (Inno), so a source that changed can be older than the object built from the old one and ninja skips it
    (KZ3 under Proton: a changed main.cpp, "ninja: no work to do"). So, against the hashes
    recorded by the last finished build: every changed payload file gets the current time (ninja then rebuilds what
    depends on it), and a changed toolchain/ file empties obj/ (ninja does not track the compiler binary).
    No record (first build, a source tree) touches nothing. -> folders to clean."""
    cur = payload_hashes(c.root)
    try:
        with open(c.b(*SOURCES_RECORD), encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        return []
    if not cur or not isinstance(prev, dict):
        return []
    now, touched, tool = time.time(), [], False
    for path, h in sorted(cur.items()):
        if prev.get(path) == h:
            continue
        if path.startswith("toolchain/"):
            tool = True
            continue
        f = os.path.join(c.root, *path.split("/"))
        if os.path.isfile(f):
            os.utime(f, (now, now))
            touched.append(path)
    c.touched = touched
    return [c.b("obj")] if tool else []


def record_sources(c):
    cur = payload_hashes(c.root)
    if cur:
        with open(c.b(*SOURCES_RECORD), "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=0, sort_keys=True)


FUTURE_SLACK_S = 120   # a file this far past the clock counts as future-dated


def future_files(c, now=None):
    """Port files dated in the future (by more than FUTURE_SLACK_S): ninja regenerates build.ninja forever when a CMake
    input is newer than anything it writes ("manifest 'build.ninja' still dirty after 100 tries"). KZ3 saw it on
    2026-10-28 (3068397) with an installer that kept the UTC build machine's file times as local times (fixed here
    too: kz2.iss TimeStampsInUTC=yes); an install made by such an older installer still carries those times. Scans the
    installed sources (port, kz2-setup, re, the toolkit; not build/, the toolchain or the game) and the EBOOT the
    build reads. -> (count, newest path)."""
    now = time.time() if now is None else now
    n, worst, worst_t = 0, None, 0.0
    paths = []
    tops = [os.path.join(c.root, t) for t in ("port", "kz2-setup", "re")]
    tk = getattr(c, "ps3recomp", "")
    if tk and os.path.abspath(tk) not in map(os.path.abspath, tops):
        tops.append(tk)
    for top in tops:
        for d, dirs, files in os.walk(top):
            paths += [os.path.join(d, f) for f in files]
    if getattr(c, "eboot", ""):
        paths.append(c.eboot)
    for p in paths:
        try:
            t = os.stat(p).st_mtime
        except OSError:
            continue
        if t > now + FUTURE_SLACK_S:
            n += 1
            if t > worst_t:
                worst, worst_t = p, t
    return n, worst


def refuse_future_files(c):
    n, worst = future_files(c)
    if n:
        raise StepFailed(
            f"{n} file(s) of the port are dated in the future (newest: {worst}), so the build cannot settle. Check that "
            "the PC's date, time and time zone are right; then reinstall with the current installer, or wait until "
            "that time has passed and run the setup again.")


def cmd_compile(c):
    refuse_future_files(c)
    return [[c.cmake, "--build", c.b("obj"), "-j", str(c.jobs)]]


def after_record(c):
    """Write paths.json (the launcher reads it): the three paths and the check's facts (and the ISO they came from)."""
    os.makedirs(c.build, exist_ok=True)
    with open(c.b("paths.json"), "w", encoding="utf-8") as f:
        json.dump({"dump": c.dump, "iso": c.iso, "update": c.update, "eboot": c.eboot, "facts": c.facts}, f, indent=2)


# A decrypted disc ISO as the game source (adapted from Project Helghast, the Killzone 3 PC port, same author, MIT,
# Project Helghast v0.1.2). The ISO must already be decrypted by the player; nothing here decrypts anything.
ISO_NAMES = {n.lower(): n for n in ("PS3_DISC.SFB", "PS3_GAME/PARAM.SFO", "PS3_GAME/USRDIR/EBOOT.BIN",
                                     "PS3_GAME/USRDIR/data_ps3.psarc")}   # the disc's own spelling
ISO_MARGIN = 1 << 30           # free space kept beyond the bytes still to copy out of the ISO
ISO_CHECK_WEIGHT = 8           # the check step also copies ~6.5 GiB out of an ISO: a bigger share of the bar


def steps_for(iso, steps=None):
    """The step table; for an ISO the check step (which also copies the files out) weighs ISO_CHECK_WEIGHT."""
    return [dataclasses.replace(s, weight=max(s.weight, ISO_CHECK_WEIGHT)) if iso and s.name == "check" else s
            for s in (STEPS if steps is None else steps)]


def iso_dest(c):
    """Where an ISO's files go (the uninstaller removes it; the ISO itself stays where it is)."""
    return os.path.join(c.root, "game", "disc")


def iso_extract(c, say=print, progress=None, free=None):
    """Copy PS3_DISC.SFB and every file under PS3_GAME out of the decrypted ISO c.iso into iso_dest(c), then point
    c.dump there. Files already there with the size the ISO says are kept (a half copy resumes; a copy is written as
    <name>.part and renamed). -> the SHA-256 of data_ps3.psarc when it was copied in this run (hashed on the way),
    else None. Raises StepFailed with a plain message."""
    import iso9660
    dest = iso_dest(c)
    sha = None
    try:
        with iso9660.Iso(c.iso) as im:
            files = [("PS3_DISC.SFB", e) for e in [im.lookup("PS3_DISC.SFB")] if e is not None and not e.is_dir]
            files += [("PS3_GAME/" + rel, e) for rel, e in im.walk("PS3_GAME")]
            if not any(r.lower() == "ps3_game/param.sfo" for r, _ in files):
                raise StepFailed("the ISO holds no PS3_GAME/PARAM.SFO")
            for _, e in files:
                if not im.in_image(e):
                    raise StepFailed("the ISO is truncated (a file reaches past the end of the image); copy it again")
            total = sum(e.size for _, e in files)

            def target(rel):      # the runtime opens these by their disc names; ISO 9660 stores upper case
                rel = ISO_NAMES.get(rel.lower(), rel)
                return os.path.join(dest, *rel.split("/"))

            def have(rel, e):
                p = target(rel)
                return os.path.isfile(p) and os.path.getsize(p) == e.size
            todo = [(r, e) for r, e in files if not have(r, e)]
            need = sum(e.size for _, e in todo)
            if need:
                os.makedirs(dest, exist_ok=True)
                avail = (free or shutil.disk_usage)(dest).free
                if avail < need + ISO_MARGIN:
                    raise StepFailed(
                        f"Not enough free disk space to copy the game files out of the ISO: {(need + ISO_MARGIN) / GIB:.1f} GiB "
                        f"are needed (the copy is {need / GIB:.1f} GiB) and {avail / GIB:.1f} GiB are free on the drive of "
                        f"{dest}. Free some space, or install into a folder on a drive with more room, and run the setup again")
            say(f"iso: {len(files)} files, {total / GIB:.2f} GiB from {os.path.basename(c.iso)}; "
                f"{len(files) - len(todo)} already extracted, {need / GIB:.2f} GiB to copy into {dest}")
            done = total - need
            for rel, e in todo:
                p = target(rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                base = done

                def cb(d, t, base=base):
                    if progress:
                        progress(base + d, total)
                h = hashlib.sha256() if rel.lower() == ISO_NAMES_PSARC else None
                im.copy(rel, p, cb, sink=h.update if h else None)
                if h:
                    sha = h.hexdigest()
                done += e.size
            if progress:
                progress(total, total)
    except iso9660.IsoEncrypted as e:
        raise StepFailed(str(e))
    except iso9660.IsoError as e:
        raise StepFailed(f"cannot read the ISO: {e}")
    except OSError as e:
        raise StepFailed(f"copying out of the ISO failed: {e.strerror or e} ({e.filename or dest})")
    c.dump = dest
    say(f"iso: extracted; the dump is now {dest}")
    return sha


ISO_NAMES_PSARC = "ps3_game/usrdir/data_ps3.psarc"


def after_check(c):
    """After the check: an ISO is extracted (and its archive checked, A1), then paths.json is written."""
    if c.iso and c.dump == c.iso:
        say = c.say or (lambda s: print(s, flush=True))
        sha = iso_extract(c, say=say, progress=c.progress)
        fc = _fc()
        rep = fc.Report()
        fc.check_psarc_hash(rep, os.path.join(c.dump, "PS3_GAME", "USRDIR", fc.PSARC_NAME),
                            (c.facts.get("disc") or {}).get("TITLE_ID"), cache_dir=c.build, known_sha=sha,
                            progress=None if sha else c.progress)   # resumed copy: one read (then cached)
        for ch in rep.checks:
            say(f"{ch['level']:4} {ch['code']}: {ch['message']}")
        c.facts.setdefault("psarc", {})["sha256"] = (rep.facts.get("psarc") or {}).get("sha256", "")
        if not rep.passed:
            raise StepFailed("the disc archive copied out of the ISO failed the archive check (A1): copy or dump the "
                             "disc again")
    after_record(c)


def eboot_stat(path):
    """[size, whole-second mtime] of the EBOOT, or None: the launcher's cheap "did it change since the build"."""
    try:
        st = os.stat(path)
        return [st.st_size, int(st.st_mtime)]
    except OSError:
        return None


NOTICE_FONTS = ("Rajdhani-Medium.ttf", "Rajdhani-Bold.ttf", "OFL.txt")   # the licence travels with the fonts


def place_fonts(root, build):
    """Copy <root>/fonts/Rajdhani-*.ttf and OFL.txt (shipped in the payload, assemble_payload FONTS) to <build>/fonts/, next to
    kz2.exe: KZ3's runtime error notice loads them privately from <exe dir>\\fonts (ASSUMPTION: KZ2's runtime takes
    over that notice; until then the copy is unused and harmless). Copies only a missing or different-size file; -> names copied. Called after
    every build and by the launcher before each start (an install from before the fonts shipped gets them too)."""
    done = []
    for fn in NOTICE_FONTS:
        src, dst = os.path.join(root, "fonts", fn), os.path.join(build, "fonts", fn)
        if not os.path.isfile(src):
            continue
        if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        done.append(fn)
    return done


def file_sha256(path):
    """-> the file's SHA-256 (hex), or "" (no file). From Project Helghast."""
    if not path or not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


SDL3_PAYLOAD = "runtime/SDL3.dll"
AT3_DLL = "at3_standalone.dll"
FFMPEG_DLLS = ("avcodec-63.dll", "avutil-61.dll")


def place_sdl3(root, build):
    """Copy <root>/runtime/SDL3.dll (shipped in the payload, assemble_payload SDL3_DEST) next to <build>/kz2.exe: the game
    loads it from its own folder for native pads (patch 4010; without it pads fall back to XInput). Copies only a missing
    or different file (size, then hash); -> True when it copied. Called after every build and by the launcher."""
    src, dst = os.path.join(root, *SDL3_PAYLOAD.split("/")), os.path.join(build, "SDL3.dll")
    if not os.path.isfile(src):
        return False
    if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src) and file_sha256(dst) == file_sha256(src):
        return False
    os.makedirs(build, exist_ok=True)
    shutil.copyfile(src, dst)
    return True


def place_decoders(root, build, obj=None):
    """The decoder DLLs beside <build>/kz2.exe. at3_standalone.dll comes from the build (<obj>, where kz2.exe was linked;
    kz2.exe imports it and does not start without it); avcodec-63.dll and avutil-61.dll are LGPL FFmpeg binaries shipped
    prebuilt in the payload (runtime/, assemble_payload FFMPEG_DLLS), loaded at run time for movie pictures and AC-3 sound.
    Copies only a missing or different file; -> the names copied."""
    srcs = [(os.path.join(obj, AT3_DLL) if obj else "", AT3_DLL)]
    srcs += [(os.path.join(root, "runtime", n), n) for n in FFMPEG_DLLS]
    done = []
    for src, name in srcs:
        dst = os.path.join(build, name)
        if not src or not os.path.isfile(src):
            continue
        if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src) and file_sha256(dst) == file_sha256(src):
            continue
        os.makedirs(build, exist_ok=True)
        shutil.copyfile(src, dst)
        done.append(name)
    return done


def cmd_stamp(c):
    """Fail the last step, with a message in the log, when the build left no at3_standalone.dll (firstrun_check B1)."""
    return [[*c.py, c.tool("release", "firstrun_check.py"), "--build-dir", c.b("obj")]]


def after_stamp(c):
    exe = c.b("obj", "kz2.exe")
    if os.path.isfile(exe):
        shutil.copy2(exe, c.b("kz2.exe"))
    place_decoders(c.root, c.build, c.b("obj"))
    place_fonts(c.root, c.build)
    place_sdl3(c.root, c.build)
    record_sources(c)
    stamp = {"inputs": c.fingerprint(("lift", "runtime")), "parts": c.parts(), "version": port_version(c.root),
             "eboot_stat": eboot_stat(c.eboot), "facts": c.facts, "jobs": c.jobs,
             "toolchain": c.toolchain or "cross", "built": datetime.datetime.now().isoformat(timespec="seconds")}
    pf = os.path.join(c.ps3recomp, ".kz2-patchset")
    if os.path.isfile(pf):
        with open(pf, encoding="utf-8", errors="replace") as f:
            stamp["patchset"] = f.read().strip()
    with open(c.b("build-stamp.json"), "w", encoding="utf-8") as f:
        json.dump(stamp, f, indent=2)


STEPS = [   # weights (ASSUMPTION): from the developer build on Linux (-j4: lifts ~1 min, SPU lift ~30 s, compile ~18 min)
    Step("check", "Checking the game files", 1, cmd_check, always=True, after=after_check),
    Step("load", "Loading the EBOOT", 4, cmd_load, clean=lambda c: [c.b("analysis")]),
    Step("ppu-lift", "Lifting PPU code", 8, cmd_ppu_lift, clean=lambda c: [c.b("recomp")], keys=("lift",)),
    # configure re-runs in place (no clean of obj\): a runtime-only update then recompiles only what changed
    # (ninja, with prepare_sources' touch of the changed payload files); a changed toolchain empties obj\.
    Step("spu-lift", "Lifting SPU code", 3, cmd_spu_lift, clean=lambda c: [c.b("spu")], keys=("lift",)),
    Step("configure", "Configuring the build", 1, cmd_configure, clean=prepare_sources, keys=("lift", "runtime")),
    Step("compile", "Compiling", 82, cmd_compile, ninja=True, keys=("lift", "runtime")),
    Step("stamp", "Finishing", 1, cmd_stamp, after=after_stamp, keys=("lift", "runtime")),
]


# ----------------------------------------------------------------------------------------------------- helpers
def available_ram():
    """Available RAM in bytes, or None. /proc/meminfo on Linux, GlobalMemoryStatusEx on Windows."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
            m = MS()
            m.len = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.avail
            return None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, AttributeError):
        pass
    return None


def jobs_for(avail, clang=False, cores=None):
    """Compile jobs from available RAM (KZ3's measurements; KZ2's lift is smaller, so these are on the safe side).
    GCC (the source tree's mingw-w64 cross build): the 64-chunk rule, (available - 8 GB) / 1.5 GB, 1..8 (GCC peak
    1.32 GB per job). llvm-mingw clang (the release's compiler, from measured peaks: 785 MB per job Linux-hosted, 738 / 741 MB per job Windows-hosted under Proton in
    stages A and B; the lift's largest process 2.3 GB; Wine's own processes ~0.6 GB): (available - 3 GiB) / 1 GiB,
    1..min(cores, 16). The 3 GiB covers the lift (one process, before the compile) and the link; 1 GiB per job is
    the measured 0.74 GB plus ~35 %."""
    if not avail:
        return 1
    if clang:
        return max(1, min(cores or 8, 16, int((avail - 3 * GIB) / GIB)))
    return max(1, min(8, int((avail - 8 * GIB) / (1.5 * GIB))))


def redactor(rpcs3_roots=()):
    """Replace the user's home folder in log text with %USERPROFILE% (both slash styles, any case on Windows), and the
    RPCS3 folder the player chose (rpcs3_import) with <RPCS3>; the longer prefix wins."""
    homes = {h for h in (os.environ.get("USERPROFILE"), os.path.expanduser("~")) if h and len(h) > 3}
    subs = [(h, "%USERPROFILE%") for h in homes] + [(r, "<RPCS3>") for r in rpcs3_roots if r and len(r) > 3]
    pats = {}
    for h, label in sorted(subs, key=lambda t: -len(t[0])):
        h = h.rstrip("\\/")
        for v in {h, h.replace("\\", "/"), h.replace("/", "\\")}:
            pats.setdefault(v.lower() if os.name == "nt" else v, (re.escape(v), label))
    if not pats:
        return lambda s: s
    rx = re.compile("|".join(f"(?P<g{i}>{p})" for i, (p, _) in enumerate(pats.values())),
                    re.IGNORECASE if os.name == "nt" else 0)
    labels = [lab for _, lab in pats.values()]
    return lambda s: rx.sub(lambda m: labels[int(m.lastgroup[1:])], s)


def writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, prefix=".kz2w", delete=True):
            pass
        return True
    except OSError:
        return False


def would_write(d):
    """writable() without creating anything (for --dry-run): the folder, or its nearest existing parent."""
    d = os.path.abspath(d)
    while not os.path.exists(d) and os.path.dirname(d) != d:
        d = os.path.dirname(d)
    return os.path.isdir(d) and os.access(d, os.W_OK)


def pick_log(log_dir, name, probe=None):
    """The log file: <log_dir>/<name>, else <temp>/<name> (TEMP on Windows, TMPDIR on Linux)."""
    if log_dir and (probe or writable)(log_dir):
        return os.path.join(log_dir, name), False
    # fallback flag only when a folder was asked for (without --log-dir the header would claim "not writable")
    return os.path.join(tempfile.gettempdir(), name), bool(log_dir)


def started_at(path):
    """Start time of an earlier log: its '# started <iso>' first line, else its mtime."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            m = re.match(r"# started (\S+)", f.readline())
        if m:
            return datetime.datetime.fromisoformat(m.group(1))
    except (OSError, ValueError):
        pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def rotate(path):
    """Rename an earlier log to <stem>-<YYYYmmdd-HHMMSS><ext> (its start time), so each run keeps one file."""
    if not os.path.exists(path):
        return None
    stem, ext = os.path.splitext(path)
    new = f"{stem}-{started_at(path):%Y%m%d-%H%M%S}{ext}"
    n = 1
    while os.path.exists(new):
        new = f"{stem}-{started_at(path):%Y%m%d-%H%M%S}-{n}{ext}"
        n += 1
    os.replace(path, new)
    return new


class Log:
    def __init__(self, path, redact):
        self.path, self.redact = path, redact
        self.f = open(path, "w", encoding="utf-8", newline="\n")

    def write(self, line):
        self.f.write(self.redact(line.rstrip("\r\n")) + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


def copy_to_install_logs(log_path, logs_dir):
    """A copy in <install>/logs, keeping the last KEEP_LOG_COPIES firstrun-*.log."""
    try:
        os.makedirs(logs_dir, exist_ok=True)
        dst = os.path.join(logs_dir, f"firstrun-{datetime.datetime.now():%Y%m%d-%H%M%S}.log")
        shutil.copy2(log_path, dst)
        old = sorted(n for n in os.listdir(logs_dir) if n.startswith("firstrun-") and n.endswith(".log"))
        for n in old[:-KEEP_LOG_COPIES]:
            os.remove(os.path.join(logs_dir, n))
    except OSError:
        pass


def marker_path(ctx, i, step):
    return ctx.b(MARKER_DIR, f"{i + 1:02d}-{step.name}.done")


def is_done(ctx, i, step):
    try:
        with open(marker_path(ctx, i, step), encoding="utf-8") as f:
            return json.load(f).get("inputs") == ctx.fingerprint(step.keys)
    except (OSError, ValueError):
        return False


def mark_done(ctx, i, step, secs):
    p = marker_path(ctx, i, step)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"inputs": ctx.fingerprint(step.keys), "seconds": round(secs, 1)}, f)


def safe_clean(ctx, d):
    """Remove a step's old outputs, only inside <build> (never the dump or anything else)."""
    b = os.path.realpath(ctx.build)
    r = os.path.realpath(d)
    if r != b and r.startswith(b + os.sep) and os.path.isdir(r):
        shutil.rmtree(r)


# ------------------------------------------------------------------------------------------------------ runner
class Cancelled(Exception):
    pass


class Runner:
    def __init__(self, ctx, steps, log, out=sys.stdout, status_file=None):
        self.ctx, self.steps, self.log, self.out = ctx, steps, log, out
        self.status_file, self.status_head = status_file, ""
        self.t0 = time.monotonic()
        tot = sum(s.weight for s in steps) or 1.0
        self.frac = [s.weight / tot for s in steps]
        self.proc = None
        self.stop_requested = False

    def watch_stop(self, path, poll=0.25):
        """--stop-file: a daemon thread that ends the running tool once the file appears; run_cmd then raises
        Cancelled (reading the child's pipe cannot be interrupted, so the child has to go first)."""
        def loop():
            while not os.path.exists(path):
                time.sleep(poll)
            self.stop_requested = True
            self.stop_child()
        threading.Thread(target=loop, name="stop-file", daemon=True).start()

    def emit(self, line, to_log=True):
        print(line, file=self.out, flush=True)
        if to_log and self.log:
            self.log.write(line)
        if self.status_file and line.startswith(("LOG ", "PROGRESS ", "RESULT ")):
            self.status(line)

    def status(self, line):
        """--status-file: the LOG line plus the latest PROGRESS/RESULT line, replaced atomically (the Inno wizard
        polls it; a reader holding it open only costs one update)."""
        if line.startswith("LOG "):
            self.status_head = line
        tmp = self.status_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(self.status_head + "\n" + (line if line != self.status_head else "") + "\n")
            os.replace(tmp, self.status_file)
        except OSError:
            pass

    def progress(self, i, done, total):
        part = (done / total) if total else 0.0
        pct = 100.0 * (sum(self.frac[:i]) + self.frac[i] * min(1.0, part))
        self.emit(f"PROGRESS step={i + 1}/{len(self.steps)} name={self.steps[i].name} done={done} total={total} "
                  f"elapsed={int(time.monotonic() - self.t0)} pct={pct:.1f}")

    def progress_due(self, done, total):
        """At most one archive-hash PROGRESS line per 0.5 %, and the last one (from Project Helghast v0.1.3)."""
        v = int(200 * done / total)
        if v != getattr(self, "_hash_v", -1) or done >= total:
            self._hash_v = v
            return True
        return False

    def run_cmd(self, i, argv):
        step = self.steps[i]
        self.log.write(f"$ {subprocess.list2cmdline(argv)}")
        t = time.monotonic()
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
        captured = []
        try:
            self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding="utf-8", errors="replace", bufsize=1, env=self.ctx.env(), **kw)
        except OSError as e:
            self.emit(f"cannot start {argv[0]}: {e}")
            return 127, captured
        try:
            for line in self.proc.stdout:
                line = line.rstrip("\r\n")
                captured.append(line)
                if line.startswith("ARCHIVE-HASH "):   # firstrun_check A1: the archive's SHA-256, on the check's permille
                    m = re.match(r"ARCHIVE-HASH done=(\d+) total=(\d+)", line)
                    if m and int(m.group(2)) and self.progress_due(int(m.group(1)), int(m.group(2))):
                        self.progress(i, int(999 * int(m.group(1)) / int(m.group(2))), 1000)
                    continue
                self.emit(line)
                m = NINJA_RE.match(line) if step.ninja else None
                if m:
                    self.progress(i, int(m.group(1)), int(m.group(2)))
            rc = self.proc.wait()
            if self.stop_requested:
                raise Cancelled()
        except KeyboardInterrupt:
            self.stop_child()
            raise Cancelled()
        finally:
            self.proc = None
        self.log.write(f"# exit {rc} after {time.monotonic() - t:.1f} s")
        return rc, captured

    def stop_child(self):
        p = self.proc
        if p and p.poll() is None:
            if os.name == "nt":   # the whole tree: cmake -> ninja -> clang would outlive a terminate()
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()

    def run(self):
        ctx, n = self.ctx, len(self.steps)
        try:
            for i, step in enumerate(self.steps):
                if self.stop_requested:
                    raise Cancelled()
                if not step.always and is_done(ctx, i, step):
                    self.log.write(f"## step {i + 1}/{n} {step.name}: done earlier, skipped")
                    self.progress(i, 1, 1)
                    continue
                self.log.write(f"## step {i + 1}/{n} {step.name}: {step.label}")
                t = time.monotonic()
                for d in step.clean(ctx):
                    safe_clean(ctx, d)
                try:
                    cmds = step.commands(ctx)
                except StepFailed as e:     # a missing lift table, future-dated files: the plain message, no marker
                    self.emit(str(e))
                    return self.result(False, step.name)
                units = 1000 if step.name == "check" else (len(cmds) or 1)   # check: permille (the archive hash)
                iso_copy = step.name == "check" and bool(ctx.iso) and ctx.dump == ctx.iso   # 10 = checked, then the copy
                ctx.say = self.emit
                ctx.progress = self.iso_progress(i)
                self.progress(i, 0, units)
                failed = False
                for k, argv in enumerate(cmds):
                    rc, out = self.run_cmd(i, argv)
                    if rc != 0 and step.optional:
                        self.emit(f"step {step.name} did not finish (exit {rc}); optional, the port is built")
                        failed = True
                        break
                    if rc != 0:
                        self.emit(f"step {step.name} failed: exit {rc}")
                        return self.result(False, step.name)
                    if step.name == "check":
                        self.take_check(out)
                        bad = self.version_mismatch()
                        if bad:
                            self.emit(bad)
                            return self.result(False, step.name)
                    if not step.ninja:
                        self.progress(i, (10 if iso_copy else 1000) if step.name == "check" else k + 1, units)
                if step.after and not failed:
                    try:
                        step.after(ctx)
                    except StepFailed as e:     # the ISO copy (space, truncated, encrypted) or its A1: no marker
                        self.emit(str(e))
                        return self.result(False, step.name)
                if not cmds or step.ninja or failed:
                    self.progress(i, 1, 1)
                if failed:
                    continue
                self.log.write(f"## step {step.name} done in {time.monotonic() - t:.1f} s")
                mark_done(ctx, i, step, time.monotonic() - t)
            return self.result(True, "-")
        except (Cancelled, KeyboardInterrupt):
            self.stop_child()
            self.log.write("## cancelled: the running step left no marker, the next start resumes here")
            self.emit(f"RESULT ok=0 step=cancelled elapsed={int(time.monotonic() - self.t0)}")
            return 130

    def iso_progress(self, i):
        """(done, total) bytes of the ISO copy -> PROGRESS lines on the check step's permille scale (10..1000), at most
        one per 0.5 %; a Stop request ends the copy (from Project Helghast v0.1.2)."""
        last = [-1]

        def cb(done, total):
            if self.stop_requested:
                raise Cancelled()
            v = 10 + int(990 * done / total) if total else 1000
            if v - last[0] >= 5 or v >= 1000:
                last[0] = v
                self.progress(i, v, 1000)
        return cb

    def take_check(self, out):
        """Keep the check's facts (EBOOT size/hash) so a changed input invalidates the later markers."""
        try:
            j = json.loads("\n".join(ln for ln in out if not ln.startswith("ARCHIVE-HASH ")))
            self.ctx.facts = j.get("facts", {})
            if not self.ctx.eboot:   # the checker picked it (update's EBOOT.elf, else the dump's)
                self.ctx.eboot = self.ctx.facts.get("eboot_elf", {}).get("path", "")
        except (ValueError, AttributeError):
            pass

    def version_mismatch(self):
        """A message when the decrypted EBOOT is another version than the one this release is built for:
        the lift would succeed and the game would not start. "" when it matches or the check did not say."""
        got = (self.ctx.facts.get("eboot_elf") or {}).get("version")
        want = EBOOT_VERS[self.ctx.ver]["check"]
        if not got or got == want:
            return ""
        return (f"the decrypted EBOOT is the {got} one, this release is built for the {want} EBOOT: "
                f"choose the {want} EBOOT.elf (the port cannot decrypt it; it needs your own decrypted one)")

    def result(self, ok, step):
        self.emit(f"RESULT ok={int(ok)} step={step} elapsed={int(time.monotonic() - self.t0)}")
        return 0 if ok else 1


def header(ctx, log_path, fallback):
    du = shutil.disk_usage(ctx.build if os.path.isdir(ctx.build) else ctx.root)
    ram = available_ram()
    return [f"# started {datetime.datetime.now().isoformat(timespec='seconds')}",
            f"# firstrun.py, Python {platform.python_version()}, {platform.platform()}",
            f"# cores {os.cpu_count()}, available RAM {ram / GIB:.1f} GiB" if ram else f"# cores {os.cpu_count()}",
            f"# free disk {du.free / GIB:.1f} GiB on the build drive, jobs {ctx.jobs}",
            f"# root {ctx.root}", f"# build {ctx.build}",
            f"# toolchain {ctx.toolchain or 'port/cmake/mingw-w64.cmake (cross)'}, cmake {ctx.cmake}, "
            f"ninja {ctx.ninja or '(PATH)'}, python {ctx.python}",
            f"# dump {ctx.dump}" + (f" (decrypted ISO; its files are copied to {iso_dest(ctx)})"
                                  if ctx.iso and ctx.dump == ctx.iso else ""),
            f"# update {ctx.update}", f"# eboot {ctx.eboot or '(auto)'}",
            f"# tree built for the {EBOOT_VERS[ctx.ver]['check']} EBOOT; PPU overrides "
            f"port/kz2/{EBOOT_VERS[ctx.ver]['overrides']}, lift fixups "
            f"{os.path.relpath(fixups_file(ctx), ctx.root).replace(os.sep, '/') if fixups_file(ctx) else 'none'}"] + \
        ([f"# log folder not writable, using {os.path.dirname(log_path)}"] if fallback else [])


def dry_run(ctx, steps, log_path, fallback, out=sys.stdout):
    tot = sum(s.weight for s in steps) or 1.0
    if not ctx.eboot:
        ctx.eboot = "<EBOOT.elf the check picks>"
    print(f"LOG path={log_path}{' (fallback)' if fallback else ''}", file=out)
    for i, s in enumerate(steps):
        state = "always" if s.always else ("done" if is_done(ctx, i, s) else "pending")
        print(f"{i + 1}/{len(steps)} {s.name:10} {100 * s.weight / tot:5.1f}%  {state:7} {s.label}", file=out)
        try:
            cmds = s.commands(ctx)
        except StepFailed as e:     # the real run stops at this step with the same text
            print(f"    STOP: {e}", file=out)
            continue
        for argv in cmds:
            print("    " + subprocess.list2cmdline(argv), file=out)
    return 0


# ------------------------------------------------------------------------------------- portable zip: text UI
NOTICE_TEXT = """Project Pyrrhus (Killzone 2 PC): first run
This checks your own Killzone 2 disc dump (BCUS98116), the 1.29 update and the decrypted EBOOT, then lifts and
compiles the game on this computer (5-30 minutes; Ctrl+C stops it, the next start resumes). Nothing is downloaded
and nothing of the game is copied; the files it generates are your own and must not be shared."""
UPDATE_HELP = """The 1.29 update is required. Install it on your PS3 (then copy dev_hdd0/game/BCUS98116)
or install the 1.29 update in RPCS3 (see its documentation). The port cannot decrypt the EBOOT: it needs
a decrypted EBOOT.elf, made from your own copy, in the update's USRDIR folder. This project ships no decryption tools
or instructions."""
def _rpcs3():
    sys.path.insert(0, HERE)
    import rpcs3_import
    return rpcs3_import


RPCS3_CONFIRM = ("Setup reads it in place (never changed, never copied) and looks only at Killzone 2 "
                 "(BCUS98116) in it.")


def rpcs3_step(a, ask, say, notes):
    """"Use my RPCS3 install" (portable zip text UI, first run): -> (dump, update, eboot) or None (the player picks the
    folders themselves) or False (quit). Reads nothing but RPCS3's two settings files until the player says yes to a
    folder; a disc or dev_hdd0 that RPCS3 keeps outside it is asked about separately. firstrun_check still does the
    hash checks on whatever this returns."""
    ri = _rpcs3()

    def yes(q, default):
        r = ask(f"{q} [{'Y/n' if default else 'y/N'}] ").strip().lower()
        return default if not r else r.startswith("y")
    found = ri.detect(getattr(a, "rpcs3", "") or None)
    root = ""
    if found and yes(f"Found RPCS3 at {found[0]['root']}. Use my RPCS3 install for the game files?", True):
        root = found[0]["root"]
    else:
        r = ask("RPCS3 folder to use (the one with rpcs3.exe or config; Enter = pick the game folders myself): ")
        root = os.path.expanduser(r.strip().strip('"'))
    if not root:
        notes.append("# rpcs3 import: not used")
        return None
    say("  " + RPCS3_CONFIRM)
    allow = False
    while True:
        res = ri.resolve(root, allow)
        notes.extend(ri.log_lines(res))
        if res["status"] == "approval":
            say("RPCS3's own settings keep some of Killzone 2 outside that folder:")
            for p in res["outside"]:
                say("  " + p)
            if yes("Read it there too? (Setup looks only at Killzone 2 (BCUS98116) in them.)", True):
                allow = True
                continue
            notes.append("# rpcs3 import: the player declined the folders outside the RPCS3 folder")
            return None
        if res["ok"]:
            say("From RPCS3: the disc dump, the 1.29 update and the decrypted EBOOT were found.")
            a.rpcs3_root = res["root"]
            a.rpcs3_saves = res
            return res["dump"], res["update"], res["eboot"]
        for p in res["problems"]:
            say("  " + p["text"])
        for h in res["help"]:
            say("")
            say(h)
        if res["status"] == "not_found":
            return None
        r = ask("Enter = check again, c = pick the folders myself, q = quit: ").strip().lower()
        if r.startswith("q"):
            return False
        if r.startswith("c"):
            return None


def offer_save_import(a, data_dir, ask, out):
    """After a successful setup: "Import your RPCS3 save for Killzone 2?" with the copy's dry run; copies only on a yes,
    and replaces an existing save only on a second yes. -> the install-log lines (counts only, no save contents)."""
    ri = _rpcs3()
    res = getattr(a, "rpcs3_saves", None)
    plan = ri.save_dryrun(res, data_dir) if res else []
    if not plan:
        return []

    def say(*t):
        print(*t, file=out, flush=True)

    def yes(q):
        return ask(f"{q} [y/N] ").strip().lower().startswith("y")
    say("")
    say("Import your RPCS3 save for Killzone 2? (optional; it is copied unchanged, RPCS3's own copy is never touched)")
    for t in ri.dryrun_text(plan):
        say(t)
    if not yes("Import it?"):
        return ["# rpcs3 save import: the player said no"]
    results = ri.save_copy(plan, overwrite=False)
    for i, (e, r) in enumerate(zip(plan, results)):
        if r["status"] == "exists" and yes(f"  {e['name']}: you already have this save here. Replace it with the "
                                           "RPCS3 one? (Files only in yours stay.)"):
            results[i] = ri.save_copy([e], overwrite=True)[0]
    for r in results:
        say(f"  {r['name']}: " + {"copied": f"copied ({r['copied']} files)", "exists": "kept yours (not replaced)"}.get(
            r["status"], "could not be copied"))
    return [ri.save_log_line(results)]


def port_version(root):
    """The payload's VERSION.txt (assemble_payload.py, from installer/VERSION), else a source tree's installer/VERSION,
    else 0.0.0. Always MAJOR.MINOR.PATCH: version_check.py refuses anything else."""
    for rel in ("VERSION.txt", os.path.join("installer", "VERSION")):
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                v = f.read().strip()
            if re.fullmatch(r"\d+\.\d+\.\d+", v):
                return v
        except OSError:
            pass
    return "0.0.0"


PAD_LAYOUTS = ("original", "modern")


def pad_layout(value):
    """-> (layout, ok): [controls] layout; missing/empty -> original, ok; unknown -> original, not ok."""
    v = (value or "").strip().lower()
    if v in PAD_LAYOUTS:
        return v, True
    return "original", v == ""


# Button prompt sets, the names port/kz2/kz2_prompts.cpp and patch 4011 read (KZ2_PROMPTS, keybinds.ini [prompts]):
# auto = follow the pad in use. Labels are what the launcher and the wizard show.
PROMPT_SETS = ("auto", "ps3", "ps4", "xbox", "keyboard")
PROMPT_LABELS = {"auto": "Auto (follows the pad in use)", "ps3": "PS3", "ps4": "PS4 / PS5", "xbox": "Xbox",
                 "keyboard": "Keyboard"}


def prompt_set(value):
    """-> (set, ok): [controls] prompts; missing/empty -> auto, ok; ps5 = ps4; unknown -> auto, not ok."""
    v = (value or "").strip().lower()
    v = {"ps5": "ps4", "ps4-ps5": "ps4", "ps4/ps5": "ps4"}.get(v, v)
    if v in PROMPT_SETS:
        return v, True
    return "auto", v == ""


# Display modes, the names the port reads (KZ2_DISPLAY, display.ini [display] mode; patch 2095, rsx_display_mode.h).
DISPLAY_MODES = ("windowed", "borderless", "fullscreen")
DISPLAY_LABELS = {"windowed": "Windowed", "borderless": "Borderless window", "fullscreen": "Fullscreen"}


def display_mode(value):
    """-> (mode, ok): [display] mode; missing/empty -> windowed, ok; window = windowed, exclusive = fullscreen;
    unknown -> windowed, not ok."""
    v = (value or "").strip().lower()
    v = {"window": "windowed", "exclusive": "fullscreen", "borderless window": "borderless"}.get(v, v)
    if v in DISPLAY_MODES:
        return v, True
    return "windowed", v == ""


def write_install_ini(root, portable, check_updates, layout="original", prompts=None, display=None):
    """kz2-install.ini, the same keys the Inno script writes ([install] portable, [online] check_updates,
    [controls] layout = original | modern; the game's own pad controls are the default)."""
    import configparser
    cp = configparser.ConfigParser()
    p = os.path.join(root, "kz2-install.ini")
    cp.read(p, encoding="utf-8")
    for sec in ("install", "online", "controls"):
        if not cp.has_section(sec):
            cp.add_section(sec)
    cp.set("install", "portable", "1" if portable else "0")
    cp.set("online", "check_updates", "1" if check_updates else "0")
    cp.set("controls", "layout", pad_layout(layout)[0])
    if prompts is not None or not cp.has_option("controls", "prompts"):
        cp.set("controls", "prompts", prompt_set(prompts)[0])
    if display is not None or not cp.has_option("display", "mode"):
        if not cp.has_section("display"):
            cp.add_section("display")
        cp.set("display", "mode", display_mode(display)[0])
    with open(p, "w", encoding="utf-8") as f:
        cp.write(f)
    return p


def _check_files(dump, update, eboot):
    """Run firstrun_check in-process; -> (exit code, its text lines)."""
    import contextlib
    import io
    sys.path.insert(0, HERE)
    import firstrun_check
    buf = io.StringIO()
    # A1 (the disc archive's SHA-256) is left to the build's check step, which caches it and shows a bar
    args = ["--dump", dump, "--skip-archive-hash"] + (["--update", update] if update else []) + (["--eboot", eboot] if eboot else [])
    with contextlib.redirect_stdout(buf):
        rc = firstrun_check.main(args)
    return rc, buf.getvalue()


def _version_check(current):
    sys.path.insert(0, HERE)
    import version_check
    return version_check.check(current)


def _fc():
    """firstrun_check, imported from this script's folder (resolve_dump, resolve_update)."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import firstrun_check
    return firstrun_check


def interactive(a, root, log_path, notes, ask=input, out=sys.stdout, check=_check_files, vcheck=_version_check):
    """Fill a.dump/a.update/a.eboot from the player's answers; True = build now, False = quit. Lines for the install
    log go to `notes` (main writes them, redacted, after the log header)."""
    def say(*t):
        print(*t, file=out, flush=True)

    def yes(q, default):
        r = ask(f"{q} [{'Y/n' if default else 'y/N'}] ").strip().lower()
        return default if not r else r.startswith("y")

    def folder(q, default, need_dir=True, inside=(), resolve=None, iso=False):
        """A folder (need_dir) or a file. For a file, a folder answer is searched for the `inside` names (relative
        paths, in order): players give the folder that holds EBOOT.elf as often as the file itself (adapted from
        Project Helghast v0.1.4). `resolve` maps a folder answer one or two levels too deep to the right one."""
        while True:
            r = ask(f"{q}" + (f" [{default}]" if default else "") + ": ").strip().strip('"')
            r = os.path.expanduser(r or default or "")
            if not r and not need_dir:
                return ""
            if r and need_dir and iso and os.path.isfile(r) and r.lower().endswith(".iso"):
                return os.path.abspath(r)      # a decrypted disc ISO (firstrun_check reads inside it)
            if r and (os.path.isdir(r) if need_dir else os.path.isfile(r)):
                if resolve and resolve(r) != r:
                    say(f"  using {os.path.abspath(resolve(r))}")
                    return os.path.abspath(resolve(r))
                return os.path.abspath(r)
            if r and not need_dir and os.path.isdir(r):
                hit = next((os.path.join(r, n) for n in inside if os.path.isfile(os.path.join(r, n))), "")
                if hit:
                    say(f"  using {os.path.abspath(hit)}")
                    return os.path.abspath(hit)
                say(f"  not found: {r} is a folder without " + " or ".join(n.replace("/", os.sep) for n in inside)
                    + "; give the file itself, or press Enter for the path in brackets")
                continue
            say(f"  not found: {r or '(empty)'}" + ("" if need_dir else " (no such file)"))

    prev = {}
    try:
        with open(os.path.join(os.path.abspath(a.build or os.path.join(root, "build")), "paths.json"),
                  encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        pass
    say(NOTICE_TEXT)
    say(f"Log: {log_path}")
    say("")
    dump, upd, elf = a.dump or prev.get("dump", ""), a.update or prev.get("update", ""), a.eboot or ""
    # --check-first: the folders the installer wizard wrote to kz2-install.ini [paths] (launch.py passes them) are
    # checked before any question; the prompts come back only after a FAIL and c (from Project Helghast v0.1.3)
    given = bool(getattr(a, "check_first", False) and a.dump and a.update)
    if given:
        dump, upd = os.path.abspath(a.dump), os.path.abspath(a.update)
        elf = os.path.abspath(a.eboot) if a.eboot else ""
        notes.append("# folders from setup: checked first")
    skip = given
    got = None if (a.dump or a.update or a.eboot) else rpcs3_step(a, ask, say, notes)
    if got is False:
        return False
    if got:
        dump, upd, elf = got
        say("")
    while True:
        if not got and not skip:   # from RPCS3 or setup: the paths are filled in; a failed check falls back to asking
            dump = folder("Disc dump: the folder holding PS3_GAME, or a decrypted .iso file", dump,
                          resolve=_fc().resolve_dump, iso=True)
            upd = folder("1.29 update folder (dev_hdd0/game/BCUS98116)", upd, resolve=_fc().resolve_update)
            auto = os.path.join(upd, "USRDIR", "EBOOT.elf")
            elf = elf or (prev.get("eboot", "") if prev.get("update") == upd else "") or \
                (auto if os.path.isfile(auto) else "")
            elf = folder("Decrypted EBOOT: the EBOOT.elf file or the folder holding it (Enter = the path in brackets, "
                         "or find it)", elf, need_dir=False, inside=("EBOOT.elf", "USRDIR/EBOOT.elf"))
            if _rpcs3().encrypted_eboot(elf):
                say("  " + _rpcs3().HELP_ENCRYPTED)
        got = None
        while True:
            rc, text = check(dump, upd, elf)
            say(text.rstrip())
            notes.append("# interactive check")
            notes.extend(text.rstrip().splitlines())
            if rc == 0:
                break
            if "U0" in text or "U1" in text or "U2" in text or "E1" in text:
                say("")
                say(UPDATE_HELP)
            r = ask("Fix the FAIL lines, then Enter = check again, c = change the folders, q = quit: ").strip().lower()
            if r.startswith("q"):
                return False
            if r.startswith("c"):
                skip = False       # change the folders: the prompts come back, starting from these answers
                break
        if rc == 0:
            break
    a.dump, a.update, a.eboot = dump, upd, elf
    say("")
    if given:   # the wizard already asked the rest and wrote kz2-install.ini; the launcher asked "Build it now?"
        notes.append("# setup's answers kept (kz2-install.ini)")
        return True
    online = False
    if yes("Check GitHub for a newer version of the port now? (one anonymous request; nothing about you or the game "
           "is sent)", False):
        r = vcheck(port_version(root))
        notes.append(f"# version check (player asked): status={r['status']} current={r['current']} "
                     f"latest={r['latest'] or '-'} url={r['url'] or '-'} {r.get('detail', '')}".rstrip())
        say({"newer": f"  A newer version {r['latest']} is out: {r['url']} (download it there if you want it)",
             "current": f"  This is the latest version ({r['current']})."}.get(
            r["status"], "  Could not reach GitHub; carrying on (one line in the log)."))
        online = yes("Check like this at every start (at most once a day)?", False)
    say("Pad controls: the game's original layout, or the Modern preset (pad buttons only; keyboard binds stay).")
    modern = yes("Use the Modern pad layout? (No = Original, the default; the launcher can change it later)", False)
    say("Button prompts on screen: " + ", ".join(PROMPT_LABELS[k] for k in PROMPT_SETS) + ".")
    pr = ask("Button prompts [auto/ps3/ps4/xbox/keyboard, Enter = auto]: ").strip()
    sel, ok = prompt_set(pr)
    if not ok:
        say(f"  unknown {pr!r}; using auto (the launcher can change it later)")
    say("Display: " + ", ".join(DISPLAY_LABELS[k] for k in DISPLAY_MODES) + ". Alt+Enter in the game switches for that session.")
    dm = ask("Display [windowed/borderless/fullscreen, Enter = windowed]: ").strip()
    dsel, dok = display_mode(dm)
    if not dok:
        say(f"  unknown {dm!r}; using windowed (the launcher can change it later)")
    write_install_ini(root, a.portable, online, "modern" if modern else "original", sel, dsel)
    say("Saves and settings stay in this folder (portable)." if a.portable else "")
    return yes("Start the build now? (20-90 minutes)", True)


class ConsoleBar:
    """File-like sink for the runner's lines (portable zip): PROGRESS lines become one bar with the step's label,
    the count for the compile and the elapsed time; RESULT ends it; the steps' own output goes only to the log."""
    WIDTH = 30

    def __init__(self, out=sys.stdout, steps=None, tty=None):
        self.out, self.buf, self.last, self.step = out, "", "", None
        self.labels = {s.name: s.label for s in (steps or STEPS)}
        self.tty = out.isatty() if tty is None else tty
        self.shown_pct = -10.0

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.line(line)
        return len(s)

    def flush(self):
        self.out.flush()

    def line(self, ln):
        kv = dict(x.split("=", 1) for x in ln.split()[1:] if "=" in x)
        if ln.startswith("LOG "):
            self.out.write(f"Log: {kv.get('path', '')}\n")
        elif ln.startswith("PROGRESS "):
            pct, name = float(kv.get("pct", 0)), kv.get("name", "")
            el = int(kv.get("elapsed", 0))
            label = self.labels.get(name, name)
            if name == "compile" and kv.get("total", "1") not in ("0", "1"):
                label += f" {int(kv['done']):,} / {int(kv['total']):,}"
            fill = int(self.WIDTH * pct / 100)
            text = f"[{'#' * fill}{'.' * (self.WIDTH - fill)}] {pct:5.1f}%  {label}  {el // 60}:{el % 60:02d}"
            if self.tty:
                self.out.write("\r" + text.ljust(len(self.last)))
            elif name != self.step or pct - self.shown_pct >= 5 or pct >= 100:
                self.out.write(text + "\n")
                self.shown_pct = pct
            self.last, self.step = text, name
        elif ln.startswith("RESULT "):
            el = int(kv.get("elapsed", 0))
            end = "\n" if self.tty and self.last else ""
            if kv.get("ok") == "1":
                self.out.write(f"{end}Done in {el // 60}:{el % 60:02d}: the port is built.\n")
            elif kv.get("step") == "cancelled":
                self.out.write(f"{end}Stopped. Run it again to resume where it stopped.\n")
            else:
                self.out.write(f"{end}The build stopped at step '{kv.get('step')}'. The log has the details; attach "
                               "it to an issue: https://github.com/undecuple/project-pyrrhus/issues\n")
        self.out.flush()


def _interrupt(*_):
    raise KeyboardInterrupt()


def main(argv=None, steps=None, out=sys.stdout, ask=input):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dump", default="")
    ap.add_argument("--update", default="")
    ap.add_argument("--eboot", default="")
    ap.add_argument("--rpcs3", default="", help="RPCS3 folder to offer first in --interactive (else the known places)")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(HERE)))
    ap.add_argument("--build")
    ap.add_argument("--jobs", type=int)
    ap.add_argument("--toolchain", default="")
    ap.add_argument("--log-dir", default="")
    ap.add_argument("--log-name", default=DEFAULT_LOG_NAME)
    ap.add_argument("--status-file", default="")
    ap.add_argument("--stop-file", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--check-first", action="store_true",
                    help="with --interactive and --dump/--update (the folders from setup): check them first and ask "
                         "for folders only after a FAIL or when c is pressed")
    ap.add_argument("--portable", action="store_true")
    ap.add_argument("--bar", action="store_true")
    a = ap.parse_args(argv)
    if not a.dump and not a.interactive:
        ap.error("--dump is required (or --interactive)")
    root = os.path.abspath(a.root)
    notes, quit_early = [], False
    if a.interactive and not a.dry_run:
        if not interactive(a, root, pick_log(a.log_dir or None, a.log_name)[0], notes, ask=ask, out=out):
            quit_early = True
    is_iso = bool(a.dump) and os.path.isfile(a.dump)      # a decrypted disc ISO instead of a dump folder
    if steps is None:
        steps = steps_for(is_iso)
    out0 = out
    if (a.interactive or a.bar) and not a.dry_run:
        out = ConsoleBar(out, steps)
    bundled = payload_tools(root)
    toolchain = os.path.abspath(a.toolchain) if a.toolchain else bundled.get("llvm_mingw", "")
    # a pick of PS3_GAME, PS3_GAME/USRDIR or the update's USRDIR names the folder above (as the check and the wizard)
    a.dump, a.update = _fc().resolve_dump(a.dump), _fc().resolve_update(a.update) if a.update else a.update
    ctx = Ctx(root=root, build=os.path.abspath(a.build or os.path.join(root, "build")),
              dump=os.path.abspath(a.dump), iso=os.path.abspath(a.dump) if is_iso else "",
              update=os.path.abspath(a.update) if a.update else "",
              eboot=os.path.abspath(a.eboot) if a.eboot else "",
              jobs=a.jobs or jobs_for(available_ram(), clang=bool(toolchain), cores=os.cpu_count()),
              toolchain=toolchain,
              python=bundled.get("python", sys.executable), cmake=bundled.get("cmake", "cmake"),
              ninja=bundled.get("ninja", ""))
    try:   # facts of the last check, so --dry-run and resume see the same fingerprint before the check re-runs
        with open(ctx.b("paths.json"), encoding="utf-8") as f:
            p = json.load(f)
        if (p.get("dump"), p.get("update")) == (ctx.dump, ctx.update) and (not ctx.eboot or ctx.eboot == p.get("eboot")):
            ctx.facts, ctx.eboot = p.get("facts", {}), p.get("eboot", "")
    except (OSError, ValueError):
        pass
    log_path, fallback = pick_log(a.log_dir or None, a.log_name, would_write if a.dry_run else None)
    if a.dry_run:
        return dry_run(ctx, steps, log_path, fallback, out)
    rotate(log_path)
    log = Log(log_path, redactor([getattr(a, "rpcs3_root", "") or a.rpcs3]))
    r = Runner(ctx, steps, log, out, a.status_file or None)
    r.emit(f"LOG path={log_path}", to_log=False)
    if a.stop_file:
        r.watch_stop(a.stop_file)
    for line in header(ctx, log_path, fallback) + notes:
        log.write(line)
    if quit_early:
        log.write("# the player quit before the build")
        log.close()
        return 1
    if os.name != "nt":
        signal.signal(signal.SIGTERM, _interrupt)
    try:
        rc = r.run()
    except Exception as e:   # always end with a RESULT line: the Inno wizard waits for one
        r.emit(f"internal error: {e!r}")
        rc = r.result(False, "internal")
    if rc == 0 and a.interactive and getattr(a, "rpcs3_saves", None):   # optional, asked separately, after the setup
        try:
            import launch
            for line in offer_save_import(a, launch.data_dir(root, a.portable, os.environ), ask, out0):
                log.write(line)
        except Exception as e:   # the save import never fails the setup
            log.write(f"# rpcs3 save import: error {type(e).__name__}")
    log.close()
    copy_to_install_logs(log_path, os.path.join(root, "logs"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
