#!/usr/bin/env python3
"""Host test (issue #16): port/kz2/CMakeLists.txt's FFmpeg-headers block, configured on its own.

v0.1.2's first-run build passed no FFmpeg headers, and CMake only warned: every player's kz2.exe was built without the
run-time FFmpeg loader (black movies, silent AC-3). The block between "# BEGIN ffmpeg-headers" and "# END
ffmpeg-headers" now stops without headers unless KZ2_ALLOW_NO_FFMPEG=ON. This test copies that block into a scratch
project and runs CMake on it:
  - no headers, no option          -> configure fails, naming KZ2_FFMPEG_INCLUDE_DIR and KZ2_ALLOW_NO_FFMPEG
  - KZ2_ALLOW_NO_FFMPEG=ON          -> configure passes with a warning, PS3RECOMP_FFMPEG_RUNTIME=OFF
  - KZ2_FFMPEG_INCLUDE_DIR=<headers> -> PS3RECOMP_FFMPEG_RUNTIME=ON, PS3RECOMP_FFMPEG_INCLUDE_DIR set
  - a folder without avcodec.h      -> configure fails
  - firstrun.py's own configure arguments for a payload holding ffmpeg/include -> PS3RECOMP_FFMPEG_RUNTIME=ON
Needs cmake on PATH (`nix develop .#win`); without it the test says SKIP and passes. No game data, no network.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"\n     {str(detail)[-900:]}"))
    if not cond:
        FAILS.append(name)


def block():
    with open(os.path.join(REPO, "port", "kz2", "CMakeLists.txt"), encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^# BEGIN ffmpeg-headers.*?$(.*?)^# END ffmpeg-headers$", text, re.M | re.S)
    return m.group(1) if m else None


def configure(src, build, args):
    r = subprocess.run(["cmake", "-S", src, "-B", build] + args, capture_output=True, text=True, timeout=120)
    cache = ""
    try:
        with open(os.path.join(build, "CMakeCache.txt"), encoding="utf-8") as f:
            cache = f.read()
    except OSError:
        pass
    return r.returncode, " ".join((r.stdout + r.stderr).split()), cache   # CMake wraps long messages


def cached(cache, name):
    m = re.search(rf"^{name}:[A-Z]+=(.*)$", cache, re.M)
    return m.group(1) if m else None


def main():
    body = block()
    check("CMakeLists.txt has the ffmpeg-headers block", body is not None and "FATAL_ERROR" in body
          and "KZ2_ALLOW_NO_FFMPEG" in body)
    if body is None:
        return 1
    if not shutil.which("cmake"):
        print("test_ffmpeg_cmake: SKIP (no cmake on PATH; run in `nix develop .#win`)")
        return 0
    tmp = tempfile.mkdtemp(prefix="kz2-ffcmake-")
    try:
        src = os.path.join(tmp, "port", "kz2")      # ../../work/ffmpeg-headers resolves inside tmp (absent)
        os.makedirs(src)
        with open(os.path.join(src, "CMakeLists.txt"), "w", encoding="utf-8") as f:
            f.write("cmake_minimum_required(VERSION 3.20)\nproject(kz2_ffmpeg_block NONE)\n" + body)
        inc = os.path.join(tmp, "ffmpeg", "include")
        os.makedirs(os.path.join(inc, "libavcodec"))
        open(os.path.join(inc, "libavcodec", "avcodec.h"), "w").close()

        rc, out, _ = configure(src, os.path.join(tmp, "b1"), [])
        check("no headers, no option: configure stops", rc != 0 and "No KZ2_FFMPEG_INCLUDE_DIR" in out
              and "KZ2_ALLOW_NO_FFMPEG=ON" in out, out)
        rc, out, cache = configure(src, os.path.join(tmp, "b2"), ["-DKZ2_ALLOW_NO_FFMPEG=ON"])
        check("KZ2_ALLOW_NO_FFMPEG=ON: a developer build goes on with a warning", rc == 0 and "CMake Warning" in out
              and cached(cache, "PS3RECOMP_FFMPEG_RUNTIME") == "OFF", out)
        rc, out, cache = configure(src, os.path.join(tmp, "b3"), [f"-DKZ2_FFMPEG_INCLUDE_DIR={inc}"])
        check("headers given: the FFmpeg loader is built", rc == 0 and cached(cache, "PS3RECOMP_FFMPEG_RUNTIME") == "ON"
              and cached(cache, "PS3RECOMP_FFMPEG_INCLUDE_DIR") == inc, out)
        rc, out, _ = configure(src, os.path.join(tmp, "b4"), [f"-DKZ2_FFMPEG_INCLUDE_DIR={tmp}"])
        check("a folder without libavcodec/avcodec.h stops", rc != 0 and "has no libavcodec/avcodec.h" in out, out)

        import firstrun as fr
        c = fr.Ctx(root=tmp, build=os.path.join(tmp, "build"))
        args = [a for a in fr.cmd_configure(c)[0] if a.startswith("-DKZ2_FFMPEG")]
        rc, out, cache = configure(src, os.path.join(tmp, "b5"), args)
        check("firstrun.py's configure arguments build the loader from the payload's ffmpeg/include",
              args and rc == 0 and cached(cache, "PS3RECOMP_FFMPEG_RUNTIME") == "ON"
              and cached(cache, "PS3RECOMP_FFMPEG_INCLUDE_DIR") == inc, f"{args}\n{out}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"test_ffmpeg_cmake: {'PASS' if not FAILS else 'FAIL ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
