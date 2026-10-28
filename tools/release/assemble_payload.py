#!/usr/bin/env python3
"""Assemble the Project Pyrrhus release payload folder from the repository, with an allowlist, a scrub and a
manifest. From Project Helghast tools/release/assemble_payload.py (with the SPU lift tools; no shader warm-up, no net client:
KZ2 has neither yet). Standard library only, Python 3.8+.

    assemble_payload.py --out DIR [--repo DIR] [--replace] [--version [v]X.Y.Z] [--launcher EXE] [--toolchain CACHE]
                        [--fonts DIR]
    assemble_payload.py --dry-run [--repo DIR] [--toolchain CACHE] [--fonts DIR]

What goes in (the allowlist, RULES below; nothing else is ever copied):
  kz2-setup/      tools/release/{firstrun,firstrun_check,version_check,launch,lift_fixups,spu_step,rpcs3_locate,rpcs3_import}.py, eboot_sha256.json, psarc_sha256.json,
                  spu/{lift_spu,gen_spu_register,kz2ver}.py (the SPU lift), and
                  eboot_ver.txt (written here: the EBOOT version the tree is built for, firstrun.tree_eboot_ver of the
                  repository, read from tools/lift.sh's constants; lift.sh itself is a developer tool and not shipped)
  re/             wws_jobs_v129.tsv, wws_jobs_v101.tsv (the SPU image tables, minus the sig16 and first_string columns)
  port/           port/kz2 (no tests) and port/cmake/*.cmake (the cross toolchain files firstrun.py uses)
  ps3recomp/      work/ps3recomp-patched (the patched toolkit, tools/ps3recomp-patched.sh) without
                  fw_spu/ (Sony firmware modules and code lifted from them: never shipped), scratch/, docs/, packaging/,
                  .github/
  licenses/       our LICENSE, ps3recomp's LICENSE, LGPL-2.1.txt (the shared text) and at3_standalone's COPYING.LGPLv2.1
                  (identical; checked), FFmpeg-COPYING.LGPLv2.1.txt, FFmpeg-SOURCE.txt, FFmpeg-LICENSE-build.txt
  runtime/        SDL3.dll, avcodec-63.dll and avutil-61.dll (prebuilt FFmpeg LGPL decoders from --ffmpeg DIR, default
                  <repo>/work/ffmpeg-win = tools/runtime/ffmpeg-lgpl-win.nix's output); first-run copies them beside kz2.exe.
                  at3_standalone.dll is not shipped: the player's build produces it (patch 6022) and first-run checks it.
  fonts/          Rajdhani-Medium.ttf and Rajdhani-Bold.ttf (SIL OFL 1.1) from --fonts DIR (default
                  <repo>/work/release/fonts, filled by installer_art.py --fetch-fonts; never committed), each checked
                  against its SHA-256 pinned in installer/art/art.json, and their OFL text as licenses/Rajdhani-OFL.txt.
                  firstrun.py and the launcher copy them to build/fonts/, next to kz2.exe (KZ3's runtime error notice
                  loads them from <exe dir>/fonts). Missing or changed fonts refuse the payload.
  pso-template.bin  the pipeline template (--pso-template FILE, default <repo>/installer/pso-template.bin, the committed
                  copy of the merged template, as Project Helghast keeps its own; checked with
                  tools/runtime/pso_template.py's reader, numbers only): build/kz2.exe reads ../pso-template.bin (patch
                  2077) and prewarms a first play's pipelines (2071/2120). Required.
  Project Pyrrhus.exe  with --launcher EXE: the launcher built by tools/release/build_launcher.sh
  README.md, NOTICE.md (from public/), run.cmd (installer/run.cmd, the portable zip's entry; the Inno script
                  excludes it)
The toolchain (compiler, CMake, Ninja, embeddable Python) is not in the repository. With --toolchain CACHE (the
folder fetch_toolchain.py filled from tools/release/toolchain.json) each zip entry's unpacked tree goes to
toolchain/<dest>/ (minus its "prune" globs) and the licence texts to licenses/<group>/ (the entry's license_globs
and the group's licence-file entries). Refused: a TO-FILL hash, a cache whose fetched.json does not hold the
manifest's hash for every entry, a group without a licence text. Toolchain files get the game-data name and magic
checks only (third-party binaries are large and their docs may hold example paths). manifest.json then also lists
the components (name, version, URL, SHA-256, licence).

Two payload paths equal under case-folding refuse the payload too (Windows would keep only one of them).

Scrub (any hit refuses the whole payload, nothing is written): game-data names and extensions (EBOOT.*, EBOOT*.BIN,
PARAM.SFO, .psarc .elf .self .sprx .prx .edat .sdat .pkg .rap .pup .core .corestream .bik .at3), game/ELF magics at
the file start (SCE, PSAR, RTTIBin, PSF, ELF, NPD), home paths (Linux home folders, Windows user folders), private hosts,
secrets, binaries over 2 MB and any file over 8 MB. Symlinks inside the copied trees are skipped (never followed).

VERSION.txt holds installer/VERSION (release_version.py; MAJOR.MINOR.PATCH, no suffix): firstrun.py shows it,
the installer takes its AppVersion from it and the version check compares against it. --version (or the release
tag, vX.Y.Z) is only checked against it: a different or suffixed one is refused. port/kz2/app.rc in the payload is
generated from installer/app.rc.in with that version, with installer/art/kz2-launcher.ico as port/kz2/kz2.ico.
manifest.json at the payload root: every file with its size and SHA-256, the count and total size, the repository
commit and the toolkit's patchset id when known. No timestamps: the same sources give the same manifest.

Exit 0 = ok, 1 = scrub refused or a source is missing, 2 = usage.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import release_version  # noqa: E402  (installer/VERSION: the one version)
TOOLKIT = os.path.join("work", "ps3recomp-patched")

# (source relative to the repo, destination in the payload, kind, options)
#   kind "file": one file; "tree": a folder, walked without following symlinks
#   options: include = filename globs (default all), exclude_dirs = folder names skipped anywhere in the tree,
#            skip_tests = drop test_* files and tests/ folders
RULES = [
    ("tools/release/firstrun.py", "kz2-setup/release/firstrun.py", "file", {}),
    ("tools/release/firstrun_check.py", "kz2-setup/release/firstrun_check.py", "file", {}),
    ("tools/release/version_check.py", "kz2-setup/release/version_check.py", "file", {}),
    ("tools/release/launch.py", "kz2-setup/release/launch.py", "file", {}),
    ("tools/release/lift_fixups.py", "kz2-setup/release/lift_fixups.py", "file", {}),
    ("tools/release/eboot_sha256.json", "kz2-setup/release/eboot_sha256.json", "file", {}),
    ("tools/release/psarc_sha256.json", "kz2-setup/release/psarc_sha256.json", "file", {}),   # firstrun_check A1
    ("tools/release/iso9660.py", "kz2-setup/release/iso9660.py", "file", {}),   # a decrypted disc ISO as the dump
    # "Use my RPCS3 install": rpcs3_locate.py is a shared module, vendored unchanged; rpcs3_import.py is our glue
    ("tools/release/rpcs3_locate.py", "kz2-setup/release/rpcs3_locate.py", "file", {}),
    ("tools/release/rpcs3_import.py", "kz2-setup/release/rpcs3_import.py", "file", {}),
    # the SPU lift (firstrun's spu-lift step): the same scripts as tools/spu/lift_spu.sh; the image tables are added
    # by add_census (without their raw-byte columns)
    ("tools/release/spu_step.py", "kz2-setup/release/spu_step.py", "file", {}),
    ("tools/spu/lift_spu.py", "kz2-setup/spu/lift_spu.py", "file", {}),
    ("tools/spu/gen_spu_register.py", "kz2-setup/spu/gen_spu_register.py", "file", {}),
    ("tools/spu/kz2ver.py", "kz2-setup/spu/kz2ver.py", "file", {}),
    ("port/kz2", "port/kz2", "tree", {"skip_tests": True}),
    ("port/cmake", "port/cmake", "tree", {"include": ["*.cmake"]}),
    (TOOLKIT, "ps3recomp", "tree", {"exclude_dirs": ["fw_spu", "scratch", "docs", "packaging", ".github"]}),
    ("public/LICENSE", "licenses/LICENSE.txt", "file", {}),
    (TOOLKIT + "/LICENSE", "licenses/ps3recomp-LICENSE.txt", "file", {}),
    (TOOLKIT + "/third_party/at3_standalone/COPYING.LGPLv2.1", "licenses/at3_standalone-COPYING.LGPLv2.1.txt",
     "file", {}),
    ("public/licenses/LGPL-2.1.txt", "licenses/LGPL-2.1.txt", "file", {}),   # the one LGPL text; NOTICE.md links it
    ("public/README.md", "README.md", "file", {}),
    ("public/NOTICE.md", "NOTICE.md", "file", {}),
    ("installer/run.cmd", "run.cmd", "file", {}),
]
EBOOT_VER = "kz2-setup/eboot_ver.txt"   # written by assemble (tree_ver), read by firstrun.tree_eboot_ver
FONTS = ("Rajdhani-Medium.ttf", "Rajdhani-Bold.ttf")   # KZ3's runtime notice fonts; installer art fonts
FONT_LICENSE = ("OFL-rajdhani.txt", "licenses/Rajdhani-OFL.txt", "fonts/OFL.txt")   # installer_art.py's name -> payload names
                                                                                    # (the second sits next to the .ttf files)
SDL3_DEST = ("runtime/SDL3.dll", "licenses/SDL3-LICENSE.txt")   # payload names: the DLL (firstrun.place_sdl3 copies it next to
SDL3_SRC = ("SDL3.dll", "LICENSE.txt")                          # kz2.exe) and SDL's zlib licence; names inside --sdl3 DIR
SDL3_MAX_BYTES = 16 << 20                                       # a DLL is exempt from the 2 MiB binary cap, not from this one
# FFmpeg's LGPL-only decoders (tools/runtime/ffmpeg-lgpl-win.nix, loaded by kz2.exe at run time for movie pictures and
# AC-3 sound). Shipped prebuilt, with the licence text and the source pointer: (name in --ffmpeg DIR, name in the payload)
FFMPEG_DLLS = (("bin/avcodec-63.dll", "runtime/avcodec-63.dll"), ("bin/avutil-61.dll", "runtime/avutil-61.dll"))
FFMPEG_TEXTS = (("share/ffmpeg-lgpl/COPYING.LGPLv2.1", "licenses/FFmpeg-COPYING.LGPLv2.1.txt"),
                ("share/ffmpeg-lgpl/SOURCE.txt", "licenses/FFmpeg-SOURCE.txt"),
                ("share/ffmpeg-lgpl/LICENSE-build.txt", "licenses/FFmpeg-LICENSE-build.txt"))
SHIPPED_DLLS = {SDL3_DEST[0]} | {d for _, d in FFMPEG_DLLS}   # payload DLLs: PE gate and size cap, not the 2 MiB binary cap
LAUNCHER = "Project Pyrrhus.exe"   # --launcher: built from installer/launcher/launcher.c, scrubbed like the rest
ALWAYS_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "build"}
ALWAYS_SKIP_FILES = ("*.pyc", "*.pyo", ".DS_Store", "*.swp", "*~", ".gitignore", ".gitattributes")
# Files the installed copy does not hold (installer/kz2.iss Excludes): the zip's entry point. manifest.json lists them
# under "zip_only" so launch.py's install check (--repair) does not call an installed copy damaged without them.
ZIP_ONLY = ("run.cmd",)

# ---- scrub ------------------------------------------------------------------------------------------------------
DENY_NAMES = ("eboot.*", "eboot*.bin", "param.sfo", "*.psarc", "*.elf", "*.self", "*.sprx", "*.prx", "*.edat",
              "*.sdat", "*.pkg", "*.rap", "*.pup", "*.core", "*.corestream", "*.bik", "*.at3")
DENY_MAGIC = {b"SCE\0": "SELF (encrypted PS3 executable)", b"PSAR": "PSARC archive", b"RTTIBin": "RTTIBin game data",
              b"\0PSF": "PARAM.SFO", b"\x7fELF": "ELF binary", b"NPD\0": "EDAT/SDAT"}
# Patterns are written so this file never matches them itself (the public export scrubs tools/ with similar rules).
TEXT_DENY = [
    ("home path", re.compile(r"/home/[a-z][a-z0-9_.-]*/")),
    ("home path", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b|<|%|\{|\$)[A-Za-z0-9_. -]+[\\/]", re.I)),
    ("private host", re.compile("discord(app)?\\.com/api/" "webhooks|ntfy\\.sh/")),
    ("secret", re.compile("sk-" "ant-|gh" "p_[A-Za-z0-9]{20}|github_" "pat_|BEGIN [A-Z ]*PRIVATE" " KEY|xox[bp]" "-")),
]
# Optional extra host names to refuse: KZ2_PRIVATE_HOSTS_FILE names a text file with one host per line ('#' comments).
# Unset (the default) means no extra list.
try:
    with open(os.environ["KZ2_PRIVATE_HOSTS_FILE"], encoding="utf-8") as _f:
        _hosts = [h.strip() for h in _f if h.strip() and not h.startswith("#")]
    if _hosts:
        TEXT_DENY.append(("private host", re.compile("|".join(re.escape(h) for h in _hosts), re.I)))
except (KeyError, OSError):
    pass
MAX_BINARY = 2 << 20
TOOLCHAIN_SCHEMES = ("https",)   # URL schemes a toolchain manifest may use (the host test adds file://)
MAX_ANY = 8 << 20


def is_text(data):
    return b"\0" not in data[:8192]


def scrub_file(path, rel):
    """Problems with one source file, as a list of strings (empty = clean)."""
    bad = []
    low = os.path.basename(rel).lower()
    for pat in DENY_NAMES:
        if fnmatch.fnmatch(low, pat):
            bad.append(f"game-data name ({pat})")
            break
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        data = f.read(min(size, MAX_ANY + 1))
    for magic, what in DENY_MAGIC.items():
        if data.startswith(magic):
            bad.append(f"file starts like a {what}")
    text = is_text(data)
    if size > MAX_ANY or (not text and size > MAX_BINARY):
        bad.append(f"too big ({size:,} bytes, {'text' if text else 'binary'})")
    if text:
        s = data.decode("utf-8", "replace")
        for what, rx in TEXT_DENY:
            m = rx.search(s)
            if m:
                line = s.count("\n", 0, m.start()) + 1
                bad.append(f"{what} at line {line}")
    return bad


# ---- collection -------------------------------------------------------------------------------------------------
def skipped(name, opts, is_dir):
    if is_dir:
        if name in ALWAYS_SKIP_DIRS or name in opts.get("exclude_dirs", ()):
            return True
        return bool(opts.get("skip_tests")) and name in ("tests", "test")
    if any(fnmatch.fnmatch(name, p) for p in ALWAYS_SKIP_FILES):
        return True
    if opts.get("skip_tests") and name.startswith("test_"):
        return True
    inc = opts.get("include")
    return bool(inc) and not any(fnmatch.fnmatch(name, p) for p in inc)


def collect(repo):
    """-> (files: list of (dest, src), missing: list of source paths). Destinations are '/'-separated."""
    files, missing = {}, []
    # Both layouts (as installer_art.py): this repo keeps the public files under public/; the public repo, where the
    # release workflow runs, has them at its root.
    flat = not os.path.isdir(os.path.join(repo, "public"))
    for src, dest, kind, opts in RULES:
        if flat and src.startswith("public/"):
            src = src[len("public/"):]
        sp = os.path.join(repo, *src.split("/"))
        if kind == "file":
            if os.path.isfile(sp) and not os.path.islink(sp):
                files[dest] = sp
            else:
                missing.append(src)
            continue
        if not os.path.isdir(sp):
            missing.append(src + "/")
            continue
        for d, dirs, names in os.walk(sp, followlinks=False):
            dirs[:] = sorted(x for x in dirs if not skipped(x, opts, True) and not os.path.islink(os.path.join(d, x)))
            for n in sorted(names):
                p = os.path.join(d, n)
                if os.path.islink(p) or not os.path.isfile(p) or skipped(n, opts, False):
                    continue
                rel = os.path.relpath(p, sp).replace(os.sep, "/")
                files[dest + "/" + rel] = p
    return sorted(files.items()), missing


CMAKE_LISTS = "port/kz2/CMakeLists.txt"


def cmake_sources_missing(repo, files):
    """-> payload destinations that port/kz2/CMakeLists.txt names as ../<dir>/<file> under port/ but the payload lacks
    (KZ3: its first real install failed at configure on a ../net/ source, a folder RULES did not list)."""
    path = os.path.join(repo, *CMAKE_LISTS.split("/"))
    if not os.path.isfile(path):
        return []
    have = {dest for dest, _ in files}
    base = os.path.dirname(CMAKE_LISTS)
    missing = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for tok in sorted(set(re.findall(r"\.\./[\w./-]+\.(?:c|cc|cpp|h|hpp|rc|def)\b", f.read()))):
            dest = os.path.normpath(os.path.join(base, tok)).replace(os.sep, "/")
            if dest.startswith("port/") and dest not in have:
                missing.append(f"{dest} (named in {CMAKE_LISTS} as {tok}; add its folder to RULES)")
    return missing


def is_sdl3(rel):
    return rel in SHIPPED_DLLS


def pe_x64_problem(path):
    """-> "" when the file is a 64-bit Windows DLL (MZ header, PE signature, machine AMD64, DLL flag), else why not."""
    with open(path, "rb") as f:
        head = f.read(4096)
    if head[:2] != b"MZ" or len(head) < 64:
        return "not a Windows executable (no MZ header)"
    off = int.from_bytes(head[60:64], "little")
    if off + 24 > len(head) or head[off:off + 4] != b"PE\0\0":
        return "no PE header"
    if int.from_bytes(head[off + 4:off + 6], "little") != 0x8664:
        return "not a 64-bit (AMD64) PE"
    if not int.from_bytes(head[off + 22:off + 24], "little") & 0x2000:
        return "a PE but not a DLL"
    return ""


def scrub_ship(path, rel):
    """-> problems for one payload file: SDL3.dll gets its own gate, everything else scrub_file."""
    if is_sdl3(rel):
        size = os.path.getsize(path)
        bad = pe_x64_problem(path)
        return ([bad] if bad else []) + ([f"{size} bytes exceeds the DLL cap {SDL3_MAX_BYTES}"] if size > SDL3_MAX_BYTES else [])
    return scrub_file(path, rel)


def collect_fonts(repo, fonts_dir):
    """-> (files [(dest, src)], problems [str]): the two notice fonts, hash-checked against installer/art/art.json's
    fonts_sha256 pins, and the family's OFL text."""
    files, bad = [], []
    try:
        with open(os.path.join(repo, "installer", "art", "art.json"), encoding="utf-8") as f:
            pins = json.load(f).get("fonts_sha256", {})
    except (OSError, ValueError) as e:
        return [], [f"installer/art/art.json: {e}"]
    for fn in FONTS:
        p = os.path.join(fonts_dir, fn)
        if not os.path.isfile(p) or os.path.islink(p):
            bad.append(f"{p} (run tools/release/installer_art.py --fetch-fonts)")
        elif not pins.get(fn):
            bad.append(f"{fn}: no SHA-256 pin in installer/art/art.json")
        elif sha256(p) != pins[fn]:
            bad.append(f"{fn}: SHA-256 differs from the pin in installer/art/art.json")
        else:
            files.append(("fonts/" + fn, p))
    lic = os.path.join(fonts_dir, FONT_LICENSE[0])
    if os.path.isfile(lic) and not os.path.islink(lic):
        files.extend((d, lic) for d in FONT_LICENSE[1:])
    else:
        bad.append(f"{lic} (the fonts' OFL text; run tools/release/installer_art.py --fetch-fonts)")
    return files, bad


def tree_ver(repo):
    """The EBOOT version the repository's tree is built for (firstrun.tree_eboot_ver on the source tree)."""
    sys.path.insert(0, HERE)
    import firstrun
    return firstrun.tree_eboot_ver(firstrun.Ctx(root=repo, build=os.path.join(repo, "build")))


APP_RC_IN = "installer/app.rc.in"        # kz2.exe's version block template (release_version.py's single source)
APP_ICON = "installer/art/kz2-launcher.ico"


def add_app_rc(repo, files, version):
    """-> (files + [port/kz2/app.rc from APP_RC_IN with the version, port/kz2/kz2.ico], missing). kz2.exe then carries
    the release's version and icon (CMakeLists compiles app.rc when it exists); the repository's own port/kz2 has none."""
    import atexit
    import tempfile
    rc_in, ico = os.path.join(repo, *APP_RC_IN.split("/")), os.path.join(repo, *APP_ICON.split("/"))
    missing = [x for x, p in ((APP_RC_IN, rc_in), (APP_ICON, ico)) if not os.path.isfile(p)]
    if missing:
        return files, missing
    d = tempfile.mkdtemp(prefix="kz2-apprc-")
    atexit.register(shutil.rmtree, d, True)
    p = os.path.join(d, "app.rc")
    with open(rc_in, encoding="utf-8") as f:
        text = f.read().replace("@VER_COMMA@", release_version.rc_comma(version)).replace("@VERSION@", version)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    keep = [(dst, src) for dst, src in files if dst not in ("port/kz2/app.rc", "port/kz2/kz2.ico")]
    return sorted(keep + [("port/kz2/app.rc", p), ("port/kz2/kz2.ico", ico)]), []


def add_eboot_ver(repo, files):
    """-> (files + [(EBOOT_VER, a temp file holding tree_ver)], []); the temp file lives until the process ends."""
    import atexit
    import tempfile
    d = tempfile.mkdtemp(prefix="kz2-payload-")
    atexit.register(shutil.rmtree, d, True)
    p = os.path.join(d, "eboot_ver.txt")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(tree_ver(repo) + "\n")
    return sorted(files + [(EBOOT_VER, p)]), []


CENSUS_VERS = ("129", "101")
CENSUS_DROP = ("sig16", "first_string")   # raw game bytes: the public export drops them too; the lift never reads them


def add_census(repo, files):
    """-> (files + [("re/wws_jobs_v<VER>.tsv", a temp file without CENSUS_DROP's columns)], missing). The SPU lift's
    image tables (kind, offset, size, names): firstrun's kz2ver.py reads <root>/re/. Same cut as
    export_public_transforms.census, so the payload carries what the public tree does."""
    import atexit
    import tempfile
    d = tempfile.mkdtemp(prefix="kz2-census-")
    atexit.register(shutil.rmtree, d, True)
    add, missing = [], []
    for v in CENSUS_VERS:
        rel = f"re/wws_jobs_v{v}.tsv"
        sp = os.path.join(repo, *rel.split("/"))
        if not os.path.isfile(sp) or os.path.islink(sp):
            missing.append(rel)
            continue
        with open(sp, encoding="utf-8", newline="") as f:
            rows = [l.split("\t") for l in f.read().splitlines()]
        drop = {rows[0].index(c) for c in CENSUS_DROP if c in rows[0]}
        p = os.path.join(d, f"wws_jobs_v{v}.tsv")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join("\t".join(c for i, c in enumerate(r) if i not in drop) for r in rows) + "\n")
        add.append((rel, p))
    return sorted(files + add), missing


def collect_sdl3(sdl3_dir):
    """-> (files [(dest, src)], problems [str]): SDL3.dll (pads, patch 4010) and SDL's licence from stage_sdl3.py's folder.
    Both are required: a payload without the DLL would silently fall back to XInput on every player's machine."""
    files, bad = [], []
    for want, dest in zip(SDL3_SRC, SDL3_DEST):
        p = os.path.join(sdl3_dir, want)
        if os.path.isfile(p) and not os.path.islink(p):
            files.append((dest, p))
        else:
            bad.append(f"{p} (SDL3 for the pads; run tools/release/stage_sdl3.py in `nix develop .#win`)")
    return files, bad


TEMPLATE_DEST = "pso-template.bin"   # the install root: build\kz2.exe reads <exe dir>\..\pso-template.bin (patch 2077)


def collect_pso_template(path):
    """-> (files [(dest, src)], problems [str]): the pipeline template (tools/runtime/pso_template.py's format: hashes
    and numeric pipeline state only, no shader text or microcode), which prewarms a first play's pipelines while the
    level loads (patches 2071/2077/2120). Required: without it a first play has shader pauses. Checked with the
    runtime tool's own reader (magic, version, key version, record count) and for printable runs: a record carries
    numbers, never names or text."""
    if not (os.path.isfile(path) and not os.path.islink(path)):
        return [], [f"{path} (the pipeline template: installer/pso-template.bin, or --pso-template FILE)"]
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "runtime"))
    try:
        import pso_template as pt
        t = pt.read(path)
    except (ImportError, ValueError, OSError) as e:
        return [], [f"{path}: not a pipeline template ({e})"]
    if not t["recs"] or len(t["recs"]) != t["count"]:
        return [], [f"{path}: {len(t['recs'])} of {t['count']} records readable"]
    text = re.search(rb"[ -~]{12,}", b"".join(t["recs"]))
    if text:
        return [], [f"{path}: a record holds text ({text.group()[:24]!r}...); templates hold numbers only"]
    return [(TEMPLATE_DEST, path)], []


def collect_ffmpeg(ff_dir):
    """-> (files [(dest, src)], problems [str]): the two FFmpeg DLLs and their three text files from the nix build's output
    folder (work/ffmpeg-win). All five are required: LGPL needs the licence text and the source pointer with the binaries."""
    files, bad = [], []
    for want, dest in FFMPEG_DLLS + FFMPEG_TEXTS:
        p = os.path.join(ff_dir, *want.split("/"))
        if os.path.isfile(p) and not os.path.islink(p):
            files.append((dest, p))
        else:
            bad.append(f"{p} (FFmpeg LGPL decoders; build tools/runtime/ffmpeg-lgpl-win.nix, see docs/BUILDING.md)")
    return files, bad


def lgpl_text_problems(files):
    """-> problems when the two LGPL-2.1 texts we ship (the shared licenses/LGPL-2.1.txt and at3_standalone's own copy)
    differ: NOTICE.md links the first for both."""
    d = dict(files)
    a, b = d.get("licenses/LGPL-2.1.txt"), d.get("licenses/at3_standalone-COPYING.LGPLv2.1.txt")
    if a and b and os.path.isfile(a) and os.path.isfile(b) and sha256(a) != sha256(b):
        return ["licenses/at3_standalone-COPYING.LGPLv2.1.txt differs from licenses/LGPL-2.1.txt (NOTICE.md says they are the same text)"]
    return []


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit(repo):
    try:
        r = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def patchset(repo):
    p = os.path.join(repo, TOOLKIT, ".kz2-patchset")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read().strip() or None
    except OSError:
        return None


PATCHES = "port/patches"


def toolkit_stale(repo):
    """-> a message when the toolkit's .kz2-patchset was made from another port/patches set than the repo's, else
    "". The stamp's first field is tools/ps3recomp-patched.sh's sha256 of the patch files in name order (16 hex
    digits). KZ3: a payload from a toolkit two merges old linked its exe against missing runtime symbols."""
    pd = os.path.join(repo, *PATCHES.split("/"))
    stamp = patchset(repo)
    if not os.path.isdir(pd) or not stamp:
        return ""
    h = hashlib.sha256()
    for n in sorted(os.listdir(pd)):
        if n.endswith(".patch"):
            with open(os.path.join(pd, n), "rb") as f:
                h.update(f.read())
    want = h.hexdigest()[:16]
    if stamp.split("-")[0] != want:
        return (f"{TOOLKIT}/.kz2-patchset {stamp} was made from another {PATCHES} set (now {want}-...): "
                "run tools/ps3recomp-patched.sh first")
    return ""


def scrub_toolchain_file(path, rel):
    """Game-data names and magics only: never a PS3 file inside the bundled toolchain."""
    bad = []
    low = os.path.basename(rel).lower()
    if any(fnmatch.fnmatch(low, pat) for pat in DENY_NAMES):
        bad.append("game-data name")
    with open(path, "rb") as f:
        head = f.read(8)
    for magic, what in DENY_MAGIC.items():
        if head.startswith(magic):
            bad.append(f"file starts like a {what}")
    return bad


def collect_toolchain(cache, manifest_path=None):
    """-> (files [(dest, src)], problems [str], components [dict]) for the payload's toolchain/ and licenses/."""
    sys.path.insert(0, HERE)
    import fetch_toolchain as ft
    manifest_path = manifest_path or ft.MANIFEST
    try:
        m = ft.load(manifest_path)
    except (OSError, ValueError) as ex:
        return [], [f"toolchain manifest {manifest_path}: {ex}"], []
    problems = [f"toolchain manifest: {p}" for p in ft.validate(m, TOOLCHAIN_SCHEMES)]
    problems += [f"toolchain: {c.get('name')} sha256 is TO-FILL (fetch_toolchain.py --fill first)"
                 for c in m.get("components", []) if c.get("sha256") == ft.TO_FILL]
    if problems:
        return [], problems, []
    fetched = ft.read_fetched(cache)
    files, comps, lic_groups = {}, [], set()
    for raw in m["components"]:
        e = ft.expand(raw)
        name, tree = e["name"], os.path.join(cache, "trees", e["name"])
        if fetched.get(name, {}).get("sha256") != e["sha256"] or not os.path.isdir(tree):
            problems.append(f"toolchain: {name} not fetched with the manifest's hash (run fetch_toolchain.py)")
            continue
        comps.append({k: e.get(k) for k in ("name", "group", "version", "url", "sha256", "license")})
        if e["archive"] == "file":
            src = os.path.join(tree, e["license_file"])
            if os.path.isfile(src):
                files[f"licenses/{e['group']}/{e['license_file']}"] = src
                lic_groups.add(e["group"])
            else:
                problems.append(f"toolchain: {name}: {e['license_file']} missing in the cache")
            continue
        prune, globs = e.get("prune", []), e.get("license_globs", [])
        for d, dirs, names in os.walk(tree, followlinks=False):
            dirs[:] = sorted(x for x in dirs if not os.path.islink(os.path.join(d, x)))
            for n in sorted(names):
                p = os.path.join(d, n)
                if os.path.islink(p) or not os.path.isfile(p):
                    continue
                rel = os.path.relpath(p, tree).replace(os.sep, "/")
                if any(fnmatch.fnmatchcase(rel, g) for g in globs):
                    files[f"licenses/{e['group']}/{name}-{rel.replace('/', '_')}"] = p
                    lic_groups.add(e["group"])
                if not any(fnmatch.fnmatchcase(rel, g) for g in prune):
                    files[f"toolchain/{e['dest']}/{rel}"] = p
    for g in sorted({c["group"] for c in m["components"]} - lic_groups):
        problems.append(f"toolchain: group {g} has no licence text in the cache (check its license_globs)")
    return sorted(files.items()), problems, comps


def case_clashes(paths):
    """Payload paths that are equal when case is folded (or a file and a folder of the same folded name): Windows file
    systems are case-insensitive, so one would overwrite the other in the install (VM test: llvm-mingw-LICENSE.TXT and
    llvm-mingw-LICENSE.txt). -> ["a  =  b", ...]."""
    seen, out = {}, []
    for p in sorted(paths):
        parts = p.split("/")
        for i in range(1, len(parts) + 1):
            sub = "/".join(parts[:i])
            key = sub.casefold()
            if key in seen and seen[key] != sub:
                out.append(f"{seen[key]}  =  {sub}")
            seen.setdefault(key, sub)
    return sorted(set(out))


def build_manifest(repo, files, version, toolchain=None):
    entries = [{"path": dest, "size": os.path.getsize(src), "sha256": sha256(src)} for dest, src in files]
    m = {"format": 1, "version": version, "repo_commit": git_commit(repo), "ps3recomp_patchset": patchset(repo),
         "count": len(entries), "total_bytes": sum(e["size"] for e in entries),
         "zip_only": [z for z in ZIP_ONLY if any(e["path"] == z for e in entries)], "files": entries}
    if toolchain:
        m["toolchain"] = toolchain
    return m


def write_payload(out, files, manifest, replace, version):
    if os.path.lexists(out):
        if not os.path.isdir(out) or os.path.islink(out):
            raise SystemExit(f"--out {out} exists and is not a folder")
        if os.listdir(out):
            if not (replace and os.path.isfile(os.path.join(out, "manifest.json"))):
                raise SystemExit(f"--out {out} is not empty (--replace replaces an earlier payload, one holding "
                                 "manifest.json)")
    part = out.rstrip("/\\") + ".partial"
    if os.path.lexists(part):
        shutil.rmtree(part)
    os.makedirs(part)
    for dest, src in files:
        d = os.path.join(part, *dest.split("/"))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(src, d)
    with open(os.path.join(part, "VERSION.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(version + "\n")
    with open(os.path.join(part, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    if os.path.lexists(out):
        shutil.rmtree(out)
    os.replace(part, out)


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(HERE)))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--out")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--version", default="", help="default installer/VERSION; a given one (or the tag vX.Y.Z) must equal it")
    ap.add_argument("--launcher", default="", help="the built Project Pyrrhus.exe (tools/release/build_launcher.sh)")
    ap.add_argument("--toolchain", default="", help="fetch_toolchain.py's cache (work/release/toolchain-cache)")
    ap.add_argument("--toolchain-manifest", default="", help=argparse.SUPPRESS)
    ap.add_argument("--sdl3", default="", help="stage_sdl3.py's folder, SDL3.dll + LICENSE.txt (default work/release/sdl3)")
    ap.add_argument("--ffmpeg", default="", help="the FFmpeg LGPL DLL build's output folder (default work/ffmpeg-win)")
    ap.add_argument("--fonts", default="", help="installer_art.py --fetch-fonts' folder (default work/release/fonts)")
    ap.add_argument("--pso-template", default="", help="the pipeline template (default installer/pso-template.bin)")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    try:
        version = release_version.read(repo)
    except ValueError as e:
        print(f"version: {e}", file=out)
        return 2
    if a.version and (a.version[1:] if a.version.startswith("v") else a.version) != version:
        print(f"--version {a.version!r}: not installer/VERSION's {version} (one version: MAJOR.MINOR.PATCH, no "
              "suffix; change installer/VERSION instead)", file=out)
        return 2
    files, missing = collect(repo)
    ffiles, fmissing = collect_fonts(repo, os.path.abspath(a.fonts or os.path.join(repo, "work", "release", "fonts")))
    sfiles, smissing = collect_sdl3(os.path.abspath(a.sdl3 or os.path.join(repo, "work", "release", "sdl3")))
    gfiles, gmissing = collect_ffmpeg(os.path.abspath(a.ffmpeg or os.path.join(repo, "work", "ffmpeg-win")))
    pfiles, pmissing = collect_pso_template(os.path.abspath(a.pso_template or os.path.join(repo, "installer", "pso-template.bin")))
    files = sorted(files + ffiles + sfiles + gfiles + pfiles)
    missing = missing + fmissing + smissing + gmissing + pmissing + lgpl_text_problems(files)
    files, vmissing = add_eboot_ver(repo, files)
    missing += vmissing
    files, cmissing = add_census(repo, files)
    missing += cmissing
    files, rmissing = add_app_rc(repo, files, version)
    missing += rmissing
    if a.launcher:
        if os.path.isfile(a.launcher):
            files = sorted(files + [(LAUNCHER, os.path.abspath(a.launcher))])
        else:
            missing.append(a.launcher)
    missing += cmake_sources_missing(repo, files)
    stale = toolkit_stale(repo)
    if stale:
        missing.append(stale)
    problems = [(dest, why) for dest, src in files for why in scrub_ship(src, dest)]
    components = None
    if a.toolchain:
        tfiles, tprob, components = collect_toolchain(os.path.abspath(a.toolchain), a.toolchain_manifest or None)
        missing += tprob
        problems += [(dest, why) for dest, src in tfiles for why in scrub_toolchain_file(src, dest)]
        files = sorted(dict(files + tfiles).items())
    problems += [(c, "two payload paths differ only by case (one overwrites the other on Windows)")
                 for c in case_clashes(dest for dest, _ in files)]
    total = sum(os.path.getsize(src) for _, src in files)
    if a.dry_run:
        for dest, src in files:
            print(f"{os.path.getsize(src):>10,}  {dest}", file=out)
    for m in missing:
        print(f"MISSING {m}" + ("  (run tools/ps3recomp-patched.sh first)" if m.startswith(TOOLKIT) else ""),
              file=out)
    for dest, why in problems:
        print(f"SCRUB FAIL {dest}: {why}", file=out)
    ok = not missing and not problems
    print(f"payload: {len(files)} files, {total:,} bytes ({total / (1 << 20):.1f} MiB); "
          f"{'scrub clean' if not problems else f'{len(problems)} scrub problem(s)'}"
          f"{'' if not missing else f', {len(missing)} missing source(s)'}", file=out)
    if not ok:
        print("payload refused: fix the sources (or the allowlist in RULES) and re-run", file=out)
        return 1
    if a.dry_run:
        return 0
    manifest = build_manifest(repo, files, version, components)
    write_payload(os.path.abspath(a.out), files, manifest, a.replace, version)
    print(f"wrote {a.out} (manifest.json: {manifest['count']} files, {manifest['total_bytes']:,} bytes)", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
