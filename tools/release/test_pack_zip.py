#!/usr/bin/env python3
"""Host test for tools/release/pack_zip.py on a synthetic payload in a temp folder (no game data, no work/, no
network). Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_pack_zip.py

Cases: a clean payload packs; two packs give the same bytes; entries sorted under the top folder with fixed dates and
the same contents; the .sha256 sidecar matches; an existing zip needs --replace; refused with nothing written: a
changed file (SHA-256), a file not in manifest.json, a listed file missing, run.cmd missing, a game-data name, an
ELF magic, a home path; toolchain/ is not scrubbed (third-party binaries) but must still match the manifest.
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pack_zip as pz  # noqa: E402

FAILS = []


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"  {detail}"[:600]))
    if not cond:
        FAILS.append(what)


def put(root, rel, data):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


def manifest(root):
    entries = []
    for rel, p in pz.walk(root):
        if rel not in pz.NOT_LISTED:
            with open(p, "rb") as f:
                d = f.read()
            entries.append({"path": rel, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()})
    m = {"format": 1, "version": "0.1.0", "count": len(entries), "total_bytes": sum(e["size"] for e in entries),
         "files": entries}
    put(root, "manifest.json", json.dumps(m, indent=1) + "\n")


def payload(tmp):
    root = os.path.join(tmp, "payload")
    put(root, "run.cmd", "@echo off\r\n")
    put(root, "VERSION.txt", "0.1.0\n")
    put(root, "kz2-setup/release/firstrun.py", "print('x')\n")
    put(root, "port/kz2/main.cpp", "int main(){}\n")
    put(root, "toolchain/bin/clang.exe", b"MZ" + bytes(3 << 20))     # binary > 2 MB: allowed under toolchain/
    put(root, "Project Pyrrhus.exe", b"MZ" + bytes(1000))
    put(root, "fonts/Rajdhani-Medium.ttf", b"\0\1\0\0" + bytes(500))
    put(root, "fonts/Rajdhani-Bold.ttf", b"\0\1\0\0" + bytes(600))
    put(root, "licenses/Rajdhani-OFL.txt", "SIL OPEN FONT LICENSE Version 1.1\n")
    put(root, "fonts/OFL.txt", "SIL OPEN FONT LICENSE Version 1.1\n")
    pe = bytearray(64) + b"PE\0\0" + (0x8664).to_bytes(2, "little") + bytes(16) + (0x2000).to_bytes(2, "little")
    pe[:2], pe[60:64] = b"MZ", (64).to_bytes(4, "little")      # a minimal 64-bit PE DLL header (assemble_payload.pe_x64_problem)
    put(root, "runtime/SDL3.dll", bytes(pe) + bytes(3 << 20))  # a real SDL3.dll is ~5 MB: over the 2 MiB binary cap
    put(root, "licenses/SDL3-LICENSE.txt", "Copyright (C) 1997-2026 Sam Lantinga\n")
    put(root, "runtime/avcodec-63.dll", bytes(pe) + bytes(3 << 20))
    put(root, "runtime/avutil-61.dll", bytes(pe) + bytes(1000))
    for n in ("licenses/LGPL-2.1.txt", "licenses/FFmpeg-COPYING.LGPLv2.1.txt", "licenses/FFmpeg-SOURCE.txt",
              "licenses/FFmpeg-LICENSE-build.txt"):
        put(root, n, "GNU LESSER GENERAL PUBLIC LICENSE Version 2.1\n")
    manifest(root)
    return root


def run(args):
    buf = io.StringIO()
    rc = pz.main(args, out=buf)
    return rc, buf.getvalue()


def case_sensitive(d):
    """False on a case-insensitive file system (Windows, macOS by default): there MAIN.cpp and main.cpp are one file,
    so a clash cannot be made on disk."""
    p = os.path.join(d, "case-probe")
    open(p, "w").close()
    try:
        return not os.path.exists(os.path.join(d, "CASE-PROBE"))
    finally:
        os.remove(p)


def main():
    tmp = tempfile.mkdtemp(prefix="kz2-zip-")
    try:
        root = payload(tmp)
        z1, z2 = os.path.join(tmp, "a", "kz2.zip"), os.path.join(tmp, "b", "kz2.zip")
        rc, txt = run(["--payload", root, "--out", z1])
        check(rc == 0 and os.path.isfile(z1), "clean payload packs", txt)
        rc2, _ = run(["--payload", root, "--out", z2])
        with open(z1, "rb") as f1, open(z2, "rb") as f2:
            b1, b2 = f1.read(), f2.read()
        check(rc2 == 0 and b1 == b2, "two packs give the same bytes")
        with zipfile.ZipFile(z1) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            same = all(z.read(f"Project Pyrrhus/{rel}") == open(p, "rb").read() for rel, p in pz.walk(root))
        check(names == sorted(names) and all(n.startswith("Project Pyrrhus/") for n in names)
              and len(names) == 19 and "Project Pyrrhus/manifest.json" in names, "sorted entries under the top folder",
              names)
        check({"Project Pyrrhus/runtime/SDL3.dll", "Project Pyrrhus/licenses/SDL3-LICENSE.txt"} <= set(names),
              "SDL3.dll and its licence are in the zip", names)
        check({"Project Pyrrhus/fonts/Rajdhani-Medium.ttf", "Project Pyrrhus/fonts/Rajdhani-Bold.ttf",
               "Project Pyrrhus/fonts/OFL.txt", "Project Pyrrhus/licenses/Rajdhani-OFL.txt"} <= set(names), "the notice fonts and their OFL text are in the zip",
              names)
        check(all(i.date_time == pz.FIXED_DATE for i in infos) and same, "fixed dates, same contents")
        with open(z1 + ".sha256", encoding="utf-8") as f:
            side = f.read()
        check(side == f"{hashlib.sha256(b1).hexdigest()}  kz2.zip\n", ".sha256 sidecar", side)
        rc, txt = run(["--payload", root, "--out", z1])
        check(rc == 1 and "--replace" in txt, "existing zip needs --replace", txt)
        rc, txt = run(["--payload", root, "--out", z1, "--replace"])
        check(rc == 0, "--replace overwrites", txt)

        bad = os.path.join(tmp, "bad.zip")

        def refused(what, mutate, expect, remanifest=False):
            r = payload(os.path.join(tmp, what.replace(" ", "_")))
            mutate(r)
            if remanifest:
                manifest(r)
            rc, txt = run(["--payload", r, "--out", bad])
            check(rc == 1 and expect in txt and not os.path.exists(bad) and not os.path.exists(bad + ".partial"),
                  f"refused: {what}", txt)

        refused("changed file", lambda r: put(r, "port/kz2/main.cpp", "int main(){return 1;}\n"), "SHA-256 differs")
        refused("unlisted file", lambda r: put(r, "port/kz2/extra.c", "x\n"), "not in manifest.json")
        if case_sensitive(tmp):
            refused("paths differing only by case", lambda r: put(r, "port/kz2/MAIN.cpp", "x\n"),
                    "two paths differ only by case", remanifest=True)
        else:   # MAIN.cpp would overwrite main.cpp, so nothing clashes and the zip gets written
            print("SKIP paths differing only by case: this file system ignores case, so the clash cannot be made")
        refused("listed file missing", lambda r: os.remove(os.path.join(r, "port", "kz2", "main.cpp")),
                "missing on disk")
        refused("no run.cmd", lambda r: os.remove(os.path.join(r, "run.cmd")), "run.cmd: missing", remanifest=True)
        refused("no notice font", lambda r: os.remove(os.path.join(r, "fonts", "Rajdhani-Medium.ttf")),
                "fonts/Rajdhani-Medium.ttf: missing", remanifest=True)
        refused("no avcodec-63.dll", lambda r: os.remove(os.path.join(r, "runtime", "avcodec-63.dll")),
                "runtime/avcodec-63.dll: missing", remanifest=True)
        refused("no FFmpeg source pointer", lambda r: os.remove(os.path.join(r, "licenses", "FFmpeg-SOURCE.txt")),
                "licenses/FFmpeg-SOURCE.txt: missing", remanifest=True)
        refused("no SDL3.dll", lambda r: os.remove(os.path.join(r, "runtime", "SDL3.dll")),
                "runtime/SDL3.dll: missing", remanifest=True)
        refused("no font licence", lambda r: os.remove(os.path.join(r, "licenses", "Rajdhani-OFL.txt")),
                "licenses/Rajdhani-OFL.txt: missing", remanifest=True)
        refused("no licence beside the fonts", lambda r: os.remove(os.path.join(r, "fonts", "OFL.txt")),
                "fonts/OFL.txt: missing", remanifest=True)
        refused("game name", lambda r: put(r, "port/EBOOT.BIN", "x\n"), "game-data name", remanifest=True)
        refused("ELF magic", lambda r: put(r, "port/blob.bin", b"\x7fELF" + bytes(10)), "ELF binary",
                remanifest=True)
        refused("home path", lambda r: put(r, "port/n.txt", "see /home/" "someone/x\n"), "home path",
                remanifest=True)
        refused("changed toolchain file", lambda r: put(r, "toolchain/bin/clang.exe", b"MZ" + bytes(10)),
                "SHA-256 differs")
        rc, txt = run(["--payload", root, "--out", os.path.join(tmp, "x.tar")])
        check(rc == 2, "--out must be a .zip", txt)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"test_pack_zip: {'PASS' if not FAILS else 'FAIL ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
