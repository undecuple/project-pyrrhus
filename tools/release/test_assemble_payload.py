#!/usr/bin/env python3
"""Host test (from Project Helghast) for tools/release/assemble_payload.py on a fake repository tree in a temp folder (no game data, no git
needed). Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_assemble_payload.py

Cases: a clean fake tree assembles; only allowlisted files land in the payload (work/ outputs other than the toolkit,
Game/, tests, fw_spu/, scratch/ and caches stay out); the manifest lists every file with the right size and SHA-256
and the total; the same tree gives the same manifest twice; --dry-run lists and writes nothing; a missing toolkit is
refused; kz2-setup/eboot_ver.txt holds the tree's EBOOT version from tools/lift.sh (not shipped).
Completeness (from KZ3's misses: psarc_sha256.json and a lift table were read by first run but not shipped):
player_reads() scans the real firstrun.py, firstrun_check.py and launch.py (and the sibling modules they import, in
turn) for the files they read at the player's end: sibling files next to the script, c.tool(...) scripts, imports,
root-relative paths, the per-version PPU override tables (EBOOT_VERS) and the lift inputs (LIFT_INPUTS); every one
must land in a payload assembled from a tree that has them, and dropping one rule must fail the check.
Negative controls, each refused with nothing written: a planted PSARC-headed file, an EBOOT.elf, a .prx, a
Linux home path, a Windows user path, a secret, an oversized binary. A symlink in a copied tree is not followed.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import re
import struct
import sys
import tempfile
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assemble_payload as ap  # noqa: E402

FAILS = []
# Built from pieces so this file never matches the export scrub itself.
HOME_LINUX = "/" + "home" + "/someone/Projects/kz2"
HOME_WIN = "C:" + "\\Users\\someone\\Documents"
SECRET = "gh" + "p_" + "A" * 24


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"  {detail}"[:600]))
    if not cond:
        FAILS.append(what)


def put(root, rel, data=b"x\n"):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())
    return p


PSO_HDR = struct.Struct("<6I")
CENSUS = "kind\tfile_offset\tsig16\tsize\tfirst_string\treg_name\nelf\t0x10\t7f454c46\t{0}\tSECRETBYTES\tPhysics.X\n"


RELEASE_DIR = os.path.dirname(os.path.abspath(__file__))
REAL_ROOT = os.path.dirname(os.path.dirname(RELEASE_DIR))
PLAYER_SCRIPTS = ("firstrun.py", "firstrun_check.py", "launch.py")
# read at the player's end when present, deliberately not shipped (the reason)
NOT_SHIPPED = {"tools/lift.sh": "a developer tool; kz2-setup/eboot_ver.txt answers tree_eboot_ver in the payload"}
# root-relative names the player's machine writes, or that other rules and tests own (not payload files to check here)
PLAYER_SIDE = {"build", "logs", "kz2-install.ini", "toolchain", "vfs", "ps3recomp", "game", "cache"}
GENERATED = {"kz2-setup/eboot_ver.txt", "manifest.json", "VERSION.txt"}   # written by assemble_payload itself


def payload_path(src):
    """Where a repo file lands in the payload (RULES' naming): tools/release and tools/spu go under kz2-setup/."""
    for pre in ("tools/release/", "tools/spu/"):
        if src.startswith(pre):
            return "kz2-setup/" + src[len("tools/"):]
    return src


def player_reads():
    """-> {repo-relative source or generated payload path} that the player's scripts read, found in their text."""
    import firstrun as fr
    lit = r'((?:"[^"]+",\s*)*"[^"]+")'
    seen, todo, out = set(), list(PLAYER_SCRIPTS), set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        out.add("tools/release/" + name)
        with open(os.path.join(RELEASE_DIR, name), encoding="utf-8") as f:
            text = f.read()
        for m in re.finditer(r'os\.path\.join\((?:HERE|os\.path\.dirname\(os\.path\.abspath\(__file__\)\)), "([^"]+)"', text):
            out.add("tools/release/" + m.group(1))          # a file next to the script
            if m.group(1).endswith(".py"):
                todo.append(m.group(1))
        for m in re.finditer(r'\.tool\(' + lit + r'\)', text):           # c.tool("release", "x.py"): kz2-setup/ or tools/
            out.add("tools/" + "/".join(re.findall(r'"([^"]+)"', m.group(1))))
        for m in re.finditer(r'^\s*(?:import|from)\s+(\w+)', text, re.M):  # sibling modules, scanned in turn
            if os.path.isfile(os.path.join(RELEASE_DIR, m.group(1) + ".py")):
                todo.append(m.group(1) + ".py")
        for m in re.finditer(r'os\.path\.join\((?:c\.|self\.|ctx\.)?root, ' + lit + r'\)', text):
            rel = "/".join(re.findall(r'"([^"]+)"', m.group(1)))
            if rel.split("/")[0] not in PLAYER_SIDE:
                out.add(rel)
    for v in fr.EBOOT_VERS.values():                       # the per-version PPU override tables (overrides_file)
        out.add("port/kz2/" + v["overrides"])
    for base, pat in fr.LIFT_INPUTS:                       # what the lift fingerprint and the lifts read
        if base == "toolkit":
            continue                                       # the toolkit tree is copied whole (its own cases)
        pat = pat if base == "root" else "tools/" + pat
        hits = [os.path.relpath(h, REAL_ROOT).replace(os.sep, "/") for h in glob.glob(os.path.join(REAL_ROOT, pat))]
        out.update(hits or ([pat] if "*" not in pat else []))
    return out


def fake_repo(root):
    for rel in ("tools/release/firstrun.py", "tools/release/firstrun_check.py", "tools/release/version_check.py",
                "tools/release/launch.py", "tools/release/lift_fixups.py",
                "tools/release/eboot_sha256.json", "tools/release/psarc_sha256.json", "tools/release/test_firstrun.py", "tools/release/spu_step.py",
                "tools/release/iso9660.py",
                "tools/release/rpcs3_locate.py", "tools/release/rpcs3_import.py",
                "tools/spu/lift_spu.py", "tools/spu/gen_spu_register.py", "tools/spu/kz2ver.py", "tools/spu/test_x.c",
                "tools/release/assemble_payload.py", "tools/elf_info.py", "tools/psarc.py",
                "port/kz2/CMakeLists.txt", "port/kz2/main.cpp", "port/kz2/ppu_overrides.txt", "port/kz2/test_x.c",
                "port/kz2/__pycache__/x.pyc", "port/cmake/mingw-w64.cmake", "port/cmake/notes.txt",
                "port/patches-notes.txt",
                "public/LICENSE", "public/README.md", "public/NOTICE.md", "installer/run.cmd",
                "work/ps3recomp-patched/LICENSE", "work/ps3recomp-patched/CMakeLists.txt",
                "work/ps3recomp-patched/.kz2-patchset", "work/ps3recomp-patched/tools/ppu_lifter.py",
                "work/ps3recomp-patched/runtime/a.c", "work/ps3recomp-patched/tests/sync/CMakeLists.txt",
                "work/ps3recomp-patched/third_party/at3_standalone/COPYING.LGPLv2.1",
                "work/ps3recomp-patched/fw_spu/spu_libsre/lifted/x.c", "work/ps3recomp-patched/scratch/junk.cpp",
                "work/ps3recomp-patched/docs/a.md", "work/ps3recomp-patched/.gitignore",
                "work/ps3recomp-patched/tests/.gitignore", "work/recomp/ppu_0001.c", "work/analysis/functions.json",
                "build/kz2-win/kz2.exe", "Game/PS3_GAME/PARAM.SFO", "docs/notes/private.md"):
        put(root, rel, f"// {rel}\n")
    put(root, "work/ps3recomp-patched/.kz2-patchset", "abc123-def\n")
    put(root, "re/wws_jobs_v129.tsv", CENSUS.format(129))
    put(root, "re/wws_jobs_v101.tsv", CENSUS.format(101))
    put(root, "tools/lift.sh", 'CODE_END="${KZ2_CODE_END:-0xbba45c}"\nTOC="${KZ2_TOC:-0xeb2958}"\n')
    # the pipeline template: pso_template.py's header (magic, version, rec_size, key version, flags, count) + 2 records
    put(root, "installer/pso-template.bin", PSO_HDR.pack(0x54505A4B, 1, 16, 1, 8, 2) + bytes(range(16)) + bytes(range(16, 32)))
    # the one version and kz2.exe's resource template + icon
    put(root, "installer/VERSION", "0.1.0\n")
    put(root, "installer/app.rc.in", 'FILEVERSION @VER_COMMA@\nVALUE "FileVersion", "@VERSION@"\n')
    put(root, "installer/art/kz2-launcher.ico", b"\0\0\1\0" + bytes(32))
    # sources the glue's CMakeLists names outside port/kz2 (KZ3: the payload must carry every one of them)
    put(root, "port/kz2/CMakeLists.txt", "target_sources(kz2 PRIVATE main.cpp ../cmake/mingw-w64.cmake)\n")
    # the notice fonts (installer_art.py --fetch-fonts' folder) and their pins in installer/art/art.json
    pins = {}
    for fn in ("Rajdhani-Medium.ttf", "Rajdhani-Bold.ttf"):
        data = b"\0\1\0\0" + fn.encode() + bytes(64)
        put(root, "work/release/fonts/" + fn, data)
        pins[fn] = hashlib.sha256(data).hexdigest()
    put(root, "work/release/fonts/OFL-rajdhani.txt", "SIL OPEN FONT LICENSE Version 1.1\n")
    put(root, "work/release/sdl3/SDL3.dll", fake_dll(3 << 20))   # over the 2 MiB binary cap on purpose
    put(root, "work/release/sdl3/LICENSE.txt", "Copyright (C) 1997-2026 Sam Lantinga\n")
    lgpl = "GNU LESSER GENERAL PUBLIC LICENSE Version 2.1\n"
    put(root, "public/licenses/LGPL-2.1.txt", lgpl)
    put(root, "work/ps3recomp-patched/third_party/at3_standalone/COPYING.LGPLv2.1", lgpl)
    put(root, "work/ffmpeg-win/bin/avcodec-63.dll", fake_dll(3 << 20))
    put(root, "work/ffmpeg-win/bin/avutil-61.dll", fake_dll(2000))
    put(root, "work/ffmpeg-win/share/ffmpeg-lgpl/COPYING.LGPLv2.1", lgpl)
    put(root, "work/ffmpeg-win/share/ffmpeg-lgpl/SOURCE.txt", "FFmpeg n9.0.1 source: https://ffmpeg.org/\n")
    put(root, "work/ffmpeg-win/share/ffmpeg-lgpl/LICENSE-build.txt", "LGPL version 2.1 or later, CONFIG_GPL 0\n")
    put(root, "installer/art/art.json", json.dumps({"format": 1, "fonts_sha256": pins}))


def fake_dll(size, machine=0x8664, flags=0x2000):
    """A minimal PE header: MZ, e_lfanew = 64, PE signature, machine, characteristics (0x2000 = DLL)."""
    head = bytearray(64) + b"PE\0\0" + machine.to_bytes(2, "little") + bytes(16) + flags.to_bytes(2, "little")
    head[:2] = b"MZ"
    head[60:64] = (64).to_bytes(4, "little")
    return bytes(head) + bytes(size - len(head))


def run(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = ap.main(args, out=buf)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
            print(e, file=buf)
    return rc, buf.getvalue()


def listing(d):
    out = set()
    for dd, _, names in os.walk(d):
        for n in names:
            out.add(os.path.relpath(os.path.join(dd, n), d).replace(os.sep, "/"))
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="kz2-payload-")
    try:
        repo = os.path.join(tmp, "repo")
        fake_repo(repo)
        out = os.path.join(tmp, "payload")
        rc, txt = run(["--repo", repo, "--out", out, "--version", "0.1.0"])
        check(rc == 0 and "scrub clean" in txt, "clean fake tree assembles", txt)
        got = listing(out)
        want = {"kz2-setup/release/firstrun.py", "kz2-setup/release/firstrun_check.py",
                "kz2-setup/release/version_check.py", "kz2-setup/release/eboot_sha256.json",
                "kz2-setup/release/psarc_sha256.json", "kz2-setup/release/iso9660.py",
                "kz2-setup/release/launch.py", "kz2-setup/release/lift_fixups.py", "kz2-setup/eboot_ver.txt",
                "kz2-setup/release/spu_step.py", "kz2-setup/release/rpcs3_locate.py",
                "kz2-setup/release/rpcs3_import.py", "kz2-setup/spu/lift_spu.py", "kz2-setup/spu/gen_spu_register.py",
                "kz2-setup/spu/kz2ver.py", "re/wws_jobs_v129.tsv", "re/wws_jobs_v101.tsv",
                "port/kz2/CMakeLists.txt", "port/kz2/main.cpp", "port/kz2/ppu_overrides.txt",
                "port/kz2/app.rc", "port/kz2/kz2.ico", "port/cmake/mingw-w64.cmake", "pso-template.bin",
                "ps3recomp/LICENSE", "ps3recomp/CMakeLists.txt", "ps3recomp/.kz2-patchset",
                "ps3recomp/tools/ppu_lifter.py", "ps3recomp/runtime/a.c", "ps3recomp/tests/sync/CMakeLists.txt",
                "ps3recomp/third_party/at3_standalone/COPYING.LGPLv2.1", "licenses/LICENSE.txt",
                "licenses/ps3recomp-LICENSE.txt", "licenses/at3_standalone-COPYING.LGPLv2.1.txt",
                "README.md", "NOTICE.md", "run.cmd", "manifest.json", "VERSION.txt",
                "fonts/Rajdhani-Medium.ttf", "fonts/Rajdhani-Bold.ttf", "fonts/OFL.txt", "licenses/Rajdhani-OFL.txt",
                "runtime/SDL3.dll", "licenses/SDL3-LICENSE.txt",
                "runtime/avcodec-63.dll", "runtime/avutil-61.dll", "licenses/LGPL-2.1.txt",
                "licenses/FFmpeg-COPYING.LGPLv2.1.txt", "licenses/FFmpeg-SOURCE.txt", "licenses/FFmpeg-LICENSE-build.txt"}
        check(got == want, "payload holds exactly the allowlisted files",
              f"extra {sorted(got - want)} missing {sorted(want - got)}")
        # The public repo's layout (the release workflow): public/ files at the root, no public/ folder.
        flat = os.path.join(tmp, "flat")
        shutil.copytree(repo, flat)
        for n in os.listdir(os.path.join(flat, "public")):
            shutil.move(os.path.join(flat, "public", n), os.path.join(flat, n))
        os.rmdir(os.path.join(flat, "public"))
        rc, txt = run(["--repo", flat, "--out", os.path.join(tmp, "payload-flat"), "--version", "0.1.0"])
        check(rc == 0 and listing(os.path.join(tmp, "payload-flat")) == want,
              "the public repo's layout (no public/ folder) assembles the same payload", txt)
        check(open(os.path.join(out, "kz2-setup", "eboot_ver.txt")).read() == "101\n",
              "eboot_ver.txt: the tree's EBOOT version from tools/lift.sh (1.01 constants)")

        cen = open(os.path.join(out, "re", "wws_jobs_v129.tsv")).read()
        check(cen == "kind\tfile_offset\tsize\treg_name\nelf\t0x10\t129\tPhysics.X\n",
              "census tables ship without the sig16 and first_string columns", cen)

        with open(os.path.join(out, "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
        ok = man["count"] == len(want) - 2 and man["ps3recomp_patchset"] == "abc123-def" and man["version"] == "0.1.0"
        ok &= open(os.path.join(out, "VERSION.txt")).read() == "0.1.0\n"
        tot = 0
        for e in man["files"]:
            p = os.path.join(out, *e["path"].split("/"))
            with open(p, "rb") as f:
                b = f.read()
            ok &= len(b) == e["size"] and hashlib.sha256(b).hexdigest() == e["sha256"]
            tot += e["size"]
        check(ok and tot == man["total_bytes"], "manifest sizes, SHA-256 and total match the files", man)
        check(man.get("zip_only") == ["run.cmd"] and not any(e["path"].endswith(".gitignore") for e in man["files"]),
              "manifest marks run.cmd zip-only; .gitignore files are not shipped", man.get("zip_only"))

        os.rename(os.path.join(repo, "re", "wws_jobs_v101.tsv"), os.path.join(repo, "re", "x.tsv"))
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 1 and "MISSING re/wws_jobs_v101.tsv" in txt, "a missing image table refuses the payload", txt)
        os.rename(os.path.join(repo, "re", "x.tsv"), os.path.join(repo, "re", "wws_jobs_v101.tsv"))

        rc, txt = run(["--repo", repo, "--out", out])
        check(rc != 0 and "not empty" in txt, "existing payload is not overwritten without --replace", txt)
        rc, txt = run(["--repo", repo, "--out", out, "--replace", "--version", "0.1.0"])
        with open(os.path.join(out, "manifest.json"), encoding="utf-8") as f:
            man2 = json.load(f)
        check(rc == 0 and man2 == man, "same sources give the same manifest (--replace)", txt)

        # two destinations equal under case-folding (VM test: llvm-mingw-LICENSE.TXT / .txt): refused, nothing written
        put(repo, "port/kz2/MAIN.cpp", "// clash\n")
        rc, txt = run(["--repo", repo, "--out", os.path.join(tmp, "cs")])
        check(rc == 1 and "port/kz2/MAIN.cpp  =  port/kz2/main.cpp" in txt and "only by case" in txt
              and not os.path.exists(os.path.join(tmp, "cs")), "paths differing only by case are refused", txt)
        os.remove(os.path.join(repo, "port", "kz2", "MAIN.cpp"))
        check(ap.case_clashes(["a/B/c.txt", "a/b/d.txt"]) == ["a/B  =  a/b"]
              and ap.case_clashes(["x/Y.txt", "x/z.txt"]) == [], "folders differing only by case are found too")
        rc, txt = run(["--repo", repo, "--out", os.path.join(tmp, "v"), "--version", "1.0; rm"])
        check(rc == 2 and not os.path.exists(os.path.join(tmp, "v")), "bad --version refused", txt)
        for bad in ("0.1.0-rc1", "0.2.0", "0.1"):
            rc, txt = run(["--repo", repo, "--out", os.path.join(tmp, "v"), "--version", bad])
            check(rc == 2 and "not installer/VERSION" in txt and not os.path.exists(os.path.join(tmp, "v")),
                  f"--version {bad} (suffixed or not installer/VERSION) refused")
        rc, txt = run(["--repo", repo, "--dry-run", "--version", "v0.1.0"])
        check(rc == 0, "the release tag v0.1.0 matches installer/VERSION", txt)
        rc_text = open(os.path.join(out, "port", "kz2", "app.rc"), encoding="utf-8").read()
        check(rc_text == 'FILEVERSION 0,1,0,0\nVALUE "FileVersion", "0.1.0"\n', "app.rc gets the version", rc_text)
        tpl = os.path.join(repo, "installer", "pso-template.bin")
        good_tpl = open(tpl, "rb").read()
        for bad, why in ((good_tpl[:24] + b"Some/Readable/Name.ext".ljust(32, b"\0"), "holds text"),
                         (b"XXXX" + good_tpl[4:], "not a pipeline template"), (None, "the pipeline template")):
            if bad is None:
                os.remove(tpl)
            else:
                open(tpl, "wb").write(bad)
            rc, txt = run(["--repo", repo, "--dry-run"])
            check(rc == 1 and why in txt, f"pipeline template refused: {why}", txt)
        open(tpl, "wb").write(good_tpl)
        put(repo, "installer/VERSION", "0.1.0-dev\n")
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 2 and "no suffix" in txt, "a suffixed installer/VERSION is refused", txt)
        put(repo, "installer/VERSION", "0.1.0\n")
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 0 and "kz2-setup/release/firstrun.py" in txt and "fw_spu" not in txt
              and not os.path.exists(os.path.join(tmp, "repo", "payload")), "--dry-run lists and writes nothing", txt)

        # completeness: every file the player's scripts read is in a payload assembled from a tree that has them
        reads = player_reads()
        check({"tools/release/psarc_sha256.json", "tools/release/eboot_sha256.json", "tools/release/rpcs3_locate.py",
               "tools/release/version_check.py", "tools/release/lift_fixups.py", "port/kz2/ppu_overrides.txt",
               "port/kz2/ppu_overrides-101.txt", "kz2-setup/eboot_ver.txt"} <= reads,
              "player_reads finds the sibling files, imports (in turn), tables and generated files", sorted(reads))
        full = os.path.join(tmp, "repo-full")
        shutil.copytree(repo, full, symlinks=True)
        for src in sorted(reads - GENERATED - set(NOT_SHIPPED)):
            if not os.path.exists(os.path.join(full, *src.split("/"))) and "." in os.path.basename(src):
                put(full, src, "x\n" if not src.endswith(".tsv") else CENSUS.format(1))

        def missing_from(payload):
            files = listing(payload)
            return sorted(r for r in reads - set(NOT_SHIPPED)
                          if (payload_path(r) if r not in GENERATED else r) not in files
                          and not any(f.startswith(payload_path(r) + "/") for f in files))
        rc, txt = run(["--repo", full, "--out", os.path.join(tmp, "pl-full"), "--version", "0.1.0"])
        gone = missing_from(os.path.join(tmp, "pl-full")) if rc == 0 else ["(assemble failed)"]
        check(rc == 0 and not gone, "every file firstrun/firstrun_check/launch read at the player's end is in the payload",
              f"missing {gone} {txt[-300:]}")
        saved = list(ap.RULES)
        try:
            ap.RULES[:] = [r for r in saved if r[0] != "tools/release/psarc_sha256.json"]
            rc, txt = run(["--repo", full, "--out", os.path.join(tmp, "pl-drop"), "--version", "0.1.0"])
            check(rc == 0 and "tools/release/psarc_sha256.json" in missing_from(os.path.join(tmp, "pl-drop")),
                  "negative control: a payload without psarc_sha256.json fails the completeness check", txt[-300:])
        finally:
            ap.RULES[:] = saved

        # a symlink inside a copied tree is skipped, never followed
        target = put(tmp, "outside/secret_data.c", "outside\n")
        try:
            os.symlink(target, os.path.join(repo, "port", "kz2", "link.c"))
            rc, txt = run(["--repo", repo, "--dry-run"])
            check(rc == 0 and "link.c" not in txt, "symlinks in trees are not followed", txt)
            os.remove(os.path.join(repo, "port", "kz2", "link.c"))
        except (OSError, NotImplementedError):
            print("skip symlink case (no symlink support)")

        # a source CMakeLists names outside port/kz2 that no rule carries is refused (KZ3: a ../net/ source)
        cm = os.path.join(repo, "port", "kz2", "CMakeLists.txt")
        with open(cm, encoding="utf-8") as f:
            cm_text = f.read()
        put(repo, "port/kz2/CMakeLists.txt", cm_text + "target_sources(kz2 PRIVATE ../elsewhere/extra.c)\n")
        put(repo, "port/elsewhere/extra.c", "// extra\n")
        rc, txt = run(["--repo", repo, "--out", os.path.join(tmp, "cm"), "--version", "0.1.0"])
        check(rc == 1 and "MISSING port/elsewhere/extra.c" in txt and not os.path.exists(os.path.join(tmp, "cm")),
              "a CMakeLists source outside the rules is refused", txt)
        put(repo, "port/kz2/CMakeLists.txt", cm_text)
        shutil.rmtree(os.path.join(repo, "port", "elsewhere"))

        # a toolkit patched from another port/patches set is refused; the matching stamp passes
        put(repo, "port/patches/0001-a.patch", "--- a\n+++ b\n")
        put(repo, "port/patches/0002-b.patch", "--- c\n+++ d\n")
        rc, txt = run(["--repo", repo, "--out", os.path.join(tmp, "st"), "--version", "0.1.0"])
        check(rc == 1 and "was made from another port/patches set" in txt
              and not os.path.exists(os.path.join(tmp, "st")), "a stale toolkit (patchset stamp) is refused", txt)
        want = hashlib.sha256(b"--- a\n+++ b\n--- c\n+++ d\n").hexdigest()[:16]
        put(repo, "work/ps3recomp-patched/.kz2-patchset", want + "-def\n")
        rc, txt = run(["--repo", repo, "--out", os.path.join(tmp, "st"), "--version", "0.1.0"])
        check(rc == 0 and "scrub clean" in txt, "the matching patchset stamp passes", txt)
        shutil.rmtree(os.path.join(repo, "port", "patches"))
        put(repo, "work/ps3recomp-patched/.kz2-patchset", "abc123-def\n")

        # negative controls: each planted file refuses the payload and nothing is written
        planted = [
            ("port/kz2/data_ps3.dat", b"PSAR\0\1\0\4zlib" + b"\0" * 64, "PSARC"),
            ("port/kz2/EBOOT.elf", b"\x7fELF\2\2\1" + b"\0" * 64, "game-data name"),
            ("work/ps3recomp-patched/libs/libsre.prx", b"\x7fELF\2\2\1" + b"\0" * 64, "game-data name"),
            ("port/kz2/paths.c", f'const char *p = "{HOME_LINUX}/Game";\n', "home path"),
            ("port/kz2/win.txt", f"log at {HOME_WIN}\\x.log\n", "home path"),
            ("port/cmake/token.cmake", f"set(T {SECRET})\n", "secret"),
            ("port/kz2/blob.bin", b"\0" * (ap.MAX_BINARY + 1), "too big"),
        ]
        for rel, data, why in planted:
            p = put(repo, rel, data)
            o2 = os.path.join(tmp, "refused")
            rc, txt = run(["--repo", repo, "--out", o2])
            check(rc == 1 and why in txt and rel.split("/")[-1] in txt and not os.path.exists(o2)
                  and not os.path.exists(o2 + ".partial"), f"refused: {rel} ({why})", txt)
            os.remove(p)
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 0, "clean again after removing the planted files", txt)

        exe = os.path.join(tmp, "Project Pyrrhus.exe")
        with open(exe, "wb") as f:
            f.write(b"MZ" + b"\0" * 4000)
        out2 = os.path.join(tmp, "payload2")
        rc, txt = run(["--repo", repo, "--out", out2, "--launcher", exe])
        with open(os.path.join(out2, "manifest.json"), encoding="utf-8") as f:
            names = [e["path"] for e in json.load(f)["files"]]
        check(rc == 0 and "Project Pyrrhus.exe" in names, "--launcher adds the launcher exe to the payload", txt)
        rc, txt = run(["--repo", repo, "--dry-run", "--launcher", exe + ".missing"])
        check(rc == 1 and "MISSING" in txt, "a missing --launcher is refused", txt)

        # the notice fonts: hash-checked against art.json, both required, --fonts picks another folder
        fdir = os.path.join(repo, "work", "release", "fonts")
        medium = os.path.join(fdir, "Rajdhani-Medium.ttf")
        with open(medium, "rb") as f:
            orig = f.read()
        with open(medium, "wb") as f:
            f.write(orig + b"x")
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 1 and "Rajdhani-Medium.ttf: SHA-256 differs" in txt, "a font that differs from its pin is refused",
              txt)
        os.remove(medium)
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 1 and "MISSING" in txt and "--fetch-fonts" in txt, "a missing font is refused with the fix", txt)
        alt = os.path.join(tmp, "fonts-alt")
        shutil.copytree(fdir, alt)
        with open(os.path.join(alt, "Rajdhani-Medium.ttf"), "wb") as f:
            f.write(orig)
        rc, txt = run(["--repo", repo, "--dry-run", "--fonts", alt])
        check(rc == 0, "--fonts DIR is used instead of work/release/fonts", txt)
        os.remove(os.path.join(alt, "OFL-rajdhani.txt"))
        rc, txt = run(["--repo", repo, "--dry-run", "--fonts", alt])
        check(rc == 1 and "OFL text" in txt, "fonts without their OFL text are refused", txt)
        with open(medium, "wb") as f:
            f.write(orig)

        # SDL3.dll (pads, patch 4010): required, 64-bit PE DLL, own size cap, its licence text beside it
        sdir = os.path.join(repo, "work", "release", "sdl3")
        dll = os.path.join(sdir, "SDL3.dll")
        with open(dll, "rb") as f:
            good = f.read()
        os.remove(dll)
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 1 and "MISSING" in txt and "SDL3.dll" in txt and "stage_sdl3.py" in txt,
              "a payload without SDL3.dll is refused with the fix", txt)
        for what, blob in (("32-bit", fake_dll(1000, machine=0x14c)), ("not a DLL", fake_dll(1000, flags=0x0002)),
                           ("not a PE", b"\x7fELF" + bytes(100)), ("too big", fake_dll(ap.SDL3_MAX_BYTES + 1))):
            with open(dll, "wb") as f:
                f.write(blob)
            rc, txt = run(["--repo", repo, "--dry-run"])
            check(rc == 1 and "SCRUB FAIL runtime/SDL3.dll" in txt, f"a {what} SDL3.dll is refused", txt)
        with open(dll, "wb") as f:
            f.write(good)
        os.remove(os.path.join(sdir, "LICENSE.txt"))
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 1 and "LICENSE.txt" in txt, "SDL3.dll without its licence text is refused", txt)
        put(repo, "work/release/sdl3/LICENSE.txt", "Copyright (C) 1997-2026 Sam Lantinga\n")
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 0, "SDL3.dll + licence restored: payload assembles again", txt)

        # FFmpeg LGPL DLLs: both DLLs and all three texts are required; PE gate applies; the LGPL texts must agree
        fdir = os.path.join(repo, "work", "ffmpeg-win")
        for rel in ("bin/avcodec-63.dll", "bin/avutil-61.dll", "share/ffmpeg-lgpl/SOURCE.txt",
                    "share/ffmpeg-lgpl/LICENSE-build.txt", "share/ffmpeg-lgpl/COPYING.LGPLv2.1"):
            fp = os.path.join(fdir, *rel.split("/"))
            with open(fp, "rb") as f:
                keep = f.read()
            os.remove(fp)
            rc, txt = run(["--repo", repo, "--dry-run"])
            check(rc == 1 and "MISSING" in txt and rel in txt.replace(os.sep, "/") and "ffmpeg-lgpl-win.nix" in txt,
                  f"a payload without {rel} is refused", txt)
            with open(fp, "wb") as f:
                f.write(keep)
        fp = os.path.join(fdir, "bin", "avutil-61.dll")
        with open(fp, "wb") as f:
            f.write(fake_dll(1000, machine=0x14c))
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 1 and "SCRUB FAIL runtime/avutil-61.dll" in txt, "a 32-bit avutil-61.dll is refused", txt)
        with open(fp, "wb") as f:
            f.write(fake_dll(2000))
        put(repo, "public/licenses/LGPL-2.1.txt", "another text\n")
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 1 and "differs from licenses/LGPL-2.1.txt" in txt, "differing LGPL texts are refused", txt)
        put(repo, "public/licenses/LGPL-2.1.txt", "GNU LESSER GENERAL PUBLIC LICENSE Version 2.1\n")
        rc, txt = run(["--repo", repo, "--dry-run", "--ffmpeg", os.path.join(repo, "nowhere")])
        check(rc == 1 and "MISSING" in txt, "--ffmpeg DIR is honoured (an empty one refuses)", txt)
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 0, "FFmpeg files restored: payload assembles again", txt)

        put(repo, "port/kz2/notes.txt", "see %USERPROFILE%\\logs and C:\\Users\\<name>\\x, /home/ is fine\n")
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 0, "placeholders (%USERPROFILE%, <name>, bare /home/) are not home paths", txt)

        shutil.rmtree(os.path.join(repo, "work", "ps3recomp-patched"))
        rc, txt = run(["--repo", repo, "--dry-run"])
        check(rc == 1 and "MISSING work/ps3recomp-patched" in txt and "ps3recomp-patched.sh" in txt,
              "missing toolkit is refused with the fix", txt)

        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "assemble_payload.py"), encoding="utf-8") as f:
            own = f.read()
        check(not [w for w, rx in ap.TEXT_DENY if rx.search(own)], "assemble_payload.py does not trip its own scrub")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"assemble_payload: {'PASS' if not FAILS else 'FAIL ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
