#!/usr/bin/env python3
"""Host test for firstrun.py's clean build PATH (Ctx.env, clean_path): on Windows with the payload's own compiler the
child PATH holds only our compiler, CMake, Ninja and Python folders and Windows' own folders, and the compiler
variables (CC, CFLAGS, CPATH ...) are gone, so a MinGW or MSYS2 GCC on the player's PATH is never found. Negative
controls: the GCC fallback (no bundled compiler), a toolchain from elsewhere, KZ2_FIRSTRUN_FULL_PATH=1 and a non-Windows
host keep the player's PATH (our folders first) and the variables. A payload without toolchain/cmake or toolchain/ninja:
the folder on the player's PATH holding cmake.exe (ninja.exe) is kept and nothing else; found nowhere, player_tools
names it (main then stops with a REASON); control: with both bundled no player folder is kept. No real Windows
needed. Exit 0 = PASS.

    python3 tools/release/test_clean_path.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402

fails = []


def check(ok, msg, detail=""):
    print(("ok   " if ok else "FAIL ") + msg + ("" if ok else f"\n     {str(detail)[:400]}"))
    if not ok:
        fails.append(msg)


MINGW = r"C:\msys64\mingw64\bin"
STRAWBERRY = r"C:\Strawberry\c\bin"
PLAYER = {"PATH": ";".join([MINGW, r"C:\Windows\System32", STRAWBERRY, r"C:\Users\x\AppData\Local\bin"]),
          "SystemRoot": r"C:\Windows", "CC": "gcc", "CFLAGS": "-O0", "CPATH": r"C:\msys64\mingw64\include",
          "MSYSTEM": "MINGW64", "INCLUDE": r"C:\VS\include", "USERPROFILE": r"C:\Users\x", "TEMP": r"C:\Temp"}

with tempfile.TemporaryDirectory() as root:
    for d in (("toolchain", "llvm-mingw", "bin"), ("toolchain", "cmake", "bin"), ("toolchain", "ninja"),
              ("toolchain", "python")):
        os.makedirs(os.path.join(root, *d))
    tc = os.path.join(root, "toolchain", "llvm-mingw")
    py = os.path.join(root, "toolchain", "python", "python.exe")
    c = fr.Ctx(root=root, build=os.path.join(root, "build"), toolchain=tc, python=py)
    check(c.bundled_compiler(), "the payload's llvm-mingw counts as the bundled compiler")

    e = c.env(dict(PLAYER), nt=True)
    parts = e["PATH"].split(";")
    want = [os.path.join(tc, "bin"), os.path.join(root, "toolchain", "cmake", "bin"), os.path.join(root, "toolchain", "ninja"),
            os.path.join(root, "toolchain", "python")]
    check(parts[:4] == want, "clean PATH: compiler, CMake, Ninja, Python first", parts)
    check(parts[4:] == [r"C:\Windows\System32", r"C:\Windows", r"C:\Windows\System32\Wbem",
                        r"C:\Windows\System32\WindowsPowerShell\v1.0"], "then Windows' own folders only", parts)
    check(MINGW not in e["PATH"] and STRAWBERRY not in e["PATH"] and r"C:\Users" not in e["PATH"],
          "no MinGW, Strawberry or user folder from the player's PATH", e["PATH"])
    check(not any(k in e for k in ("CC", "CFLAGS", "CPATH", "MSYSTEM", "INCLUDE")), "compiler variables dropped",
          sorted(k for k in e if k in fr.COMPILER_VARS))
    check(e.get("USERPROFILE") == r"C:\Users\x" and e.get("TEMP") == r"C:\Temp" and e.get("PYTHONUTF8") == "1",
          "other variables kept (user profile, temp) and ours set")
    e2 = c.env(dict(PLAYER, Path=PLAYER["PATH"], PATH=PLAYER["PATH"]), nt=True)
    check(MINGW not in e2["PATH"] and [k for k in e2 if k.upper() == "PATH"] == ["PATH"],
          "clean even with a second-case Path key (only one PATH left)", e2["PATH"])

    # negative controls: the player's PATH stays
    full = c.env(dict(PLAYER, KZ2_FIRSTRUN_FULL_PATH="1"), nt=True)
    check(MINGW in full["PATH"] and full.get("CC") == "gcc", "KZ2_FIRSTRUN_FULL_PATH=1 keeps the player's PATH", full["PATH"])
    gcc = fr.Ctx(root=root, build=os.path.join(root, "build"), toolchain="", python=py)
    g = gcc.env(dict(PLAYER), nt=True)
    check(not gcc.bundled_compiler() and MINGW in g["PATH"] and g.get("CC") == "gcc",
          "GCC fallback (no bundled compiler): the player's PATH and CC stay", g["PATH"])
    other = fr.Ctx(root=root, build=os.path.join(root, "build"), toolchain=os.path.join(root, "elsewhere"), python=py)
    check(MINGW in other.env(dict(PLAYER), nt=True)["PATH"], "a --toolchain from elsewhere keeps the PATH")
    lin = c.env({"PATH": "/usr/bin:/bin", "CC": "cc"}, nt=False)
    check(lin["PATH"].endswith("/usr/bin:/bin") and lin.get("CC") == "cc", "non-Windows host: PATH kept, ours first",
          lin["PATH"])


    # a payload without its own CMake and Ninja (main: cmake="cmake", ninja="")
    with tempfile.TemporaryDirectory() as other:
        tools = os.path.join(other, "CMake", "bin")
        os.makedirs(tools)
        for n in ("cmake.exe", "ninja.exe"):
            open(os.path.join(tools, n), "w").close()
        bare = fr.Ctx(root=root, build=os.path.join(root, "build"), toolchain=tc, python=py, cmake="cmake", ninja="")
        player = dict(PLAYER, PATH=PLAYER["PATH"] + ";" + tools)
        keep, missing = bare.player_tools(player, nt=True)
        eb = bare.env(player, nt=True)["PATH"].split(";")
        check(keep == [tools] and not missing and tools in eb and MINGW not in eb,
              "no bundled cmake/ninja: their folder on the player's PATH is kept, nothing else", (keep, missing, eb))
        keep2, missing2 = bare.player_tools(dict(PLAYER), nt=True)
        check(keep2 == [] and missing2 == ["cmake", "ninja"], "found nowhere: both named as missing", (keep2, missing2))
        full_ctx = fr.Ctx(root=root, build=os.path.join(root, "build"), toolchain=tc, python=py,
                          cmake=os.path.join(root, "toolchain", "cmake", "bin", "cmake.exe"),
                          ninja=os.path.join(root, "toolchain", "ninja", "ninja.exe"))
        check(full_ctx.player_tools(player, nt=True) == ([], []) and tools not in full_ctx.env(player, nt=True)["PATH"],
              "control: both bundled, no player folder kept")
    src = open(os.path.join(HERE, "firstrun.py"), encoding="utf-8").read()
    check('rc = r.failed("tools"' in src and src.find('r.failed("tools"') < src.find("rc = r.run()"),
          "main stops with a REASON before the build when a tool is missing")

print("PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
