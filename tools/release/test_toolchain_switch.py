#!/usr/bin/env python3
"""Host test for firstrun.py's toolchain choice (public #34, a Linux-host builder's report). No game data, no compiler.
Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_toolchain_switch.py

Cases: 1 pick_toolchain: --toolchain wins, then the payload's llvm-mingw, else the GCC MinGW-w64 fallback with a NOTE
naming --toolchain and the host; 2 toolchain_changed against obj/CMakeCache.txt (no cache, same llvm-mingw, another
llvm-mingw folder, llvm-mingw <-> GCC cross, a Windows-style cache path, a cache with no toolchain file); 3 the
configure/compile/stamp markers depend on the toolchain (another --toolchain is not "done"); prepare_sources empties
obj and cmd_compile configures first after a switch, nothing to clean with the same toolchain; 4 main(): the NOTE in
the output and the log without a toolchain, none with --toolchain.
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firstrun as fr  # noqa: E402

fr.rpcs3_step = lambda *a, **k: None
FAILS = []


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("FAIL", what)


def cache(obj, tc_file, tc_root=None, home=None):
    os.makedirs(obj, exist_ok=True)
    lines = [f"CMAKE_CACHEFILE_DIR:INTERNAL={obj}"]
    if home:
        lines.append(f"CMAKE_HOME_DIRECTORY:INTERNAL={home}")
    if tc_file:
        lines.append(f"CMAKE_TOOLCHAIN_FILE:FILEPATH={tc_file}")
    if tc_root is not None:
        lines.append(f"LLVM_MINGW_ROOT:UNINITIALIZED={tc_root}")
    with open(os.path.join(obj, "CMakeCache.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(obj, "build.ninja"), "w") as f:
        f.write("# stand-in\n")


def ctx(root, toolchain=""):
    c = fr.Ctx(root=root, build=os.path.join(root, "build"), dump=os.path.join(root, "dump"), cmake="cmake",
               python="python3", toolchain=toolchain, ninja="", jobs=1)
    c.cache["lift"] = "0" * 16    # lift_inputs_hash needs a source tree; the toolchain part is what is tested
    c.cache["ver"] = "129"
    return c


def main():
    tmp = tempfile.mkdtemp(prefix="kz2-tc-switch-")
    try:
        root = os.path.join(tmp, "root")
        lm_a, lm_b = os.path.join(tmp, "llvm-mingw-a"), os.path.join(tmp, "llvm-mingw-b")
        for d in (root, lm_a, lm_b, os.path.join(root, "port", "kz2"), os.path.join(root, "port", "cmake"),
                  os.path.join(root, "ffmpeg", "include", "libavcodec")):
            os.makedirs(d, exist_ok=True)
        for n in ("llvm-mingw.cmake", "mingw-w64.cmake"):
            open(os.path.join(root, "port", "cmake", n), "w").close()
        open(os.path.join(root, "ffmpeg", "include", "libavcodec", "avcodec.h"), "w").close()
        home = os.path.join(root, "port", "kz2")
        obj = os.path.join(root, "build", "obj")

        # 1. the choice and the fallback NOTE
        tc, note = fr.pick_toolchain(lm_a, {"llvm_mingw": lm_b}, root, "Linux")
        check(tc == os.path.abspath(lm_a) and note == "", f"1 --toolchain wins: {tc} {note!r}")
        tc, note = fr.pick_toolchain("", {"llvm_mingw": lm_b}, root, "Windows")
        check(tc == lm_b and note == "", "1 the payload's llvm-mingw next")
        tc, note = fr.pick_toolchain("", {}, root, "Linux")
        check(tc == "" and note.startswith("NOTE toolchain:") and "--toolchain" in note and "GCC MinGW-w64" in note
              and "Linux host" in note and "mingw-w64.cmake" in note, f"1 the fallback said: {note!r}")

        # 2. toolchain_changed against the cache
        c_a, c_b, c_x = ctx(root, lm_a), ctx(root, lm_b), ctx(root, "")
        check(not fr.toolchain_changed(c_a) and not fr.toolchain_changed(c_x), "2 no cache: not changed")
        cache(obj, os.path.join(root, "port", "cmake", "llvm-mingw.cmake"), lm_a, home)
        check(not fr.toolchain_changed(c_a), "2 same llvm-mingw: not changed")
        check(fr.toolchain_changed(c_b), "2 another llvm-mingw folder: changed")
        check(fr.toolchain_changed(c_x), "2 llvm-mingw -> GCC cross: changed")
        cache(obj, os.path.join(root, "port", "cmake", "mingw-w64.cmake"), None, home)
        check(not fr.toolchain_changed(c_x), "2 same GCC cross: not changed")
        check(fr.toolchain_changed(c_a), "2 GCC cross -> llvm-mingw: changed")
        cache(obj, "C:\\Games\\Pyrrhus\\port\\cmake\\mingw-w64.cmake", None, home)
        check(not fr.toolchain_changed(c_x), "2 a Windows path to the same file name: not changed")
        cache(obj, "", None, home)
        check(fr.toolchain_changed(c_x) and fr.toolchain_changed(c_a), "2 a cache with no toolchain file: changed")

        # 3. markers and cleaning
        p_a, p_b, p_x = c_a.parts(), c_b.parts(), c_x.parts()
        check(len({p_a["toolchain"], p_b["toolchain"], p_x["toolchain"]}) == 3, "3 three toolchains, three parts")
        check(p_a["base"] == p_x["base"], "3 the base part does not depend on the toolchain (no re-check, no re-lift)")
        names = [s.name for s in fr.STEPS]
        for n in ("configure", "compile", "stamp"):
            check("toolchain" in fr.STEPS[names.index(n)].keys, f"3 {n} keyed on the toolchain")
        for n in ("load", "ppu-lift", "spu-lift"):
            check("toolchain" not in fr.STEPS[names.index(n)].keys, f"3 {n} not keyed on the toolchain")
        i = names.index("configure")
        fr.mark_done(c_a, i, fr.STEPS[i], 1.0)
        check(fr.is_done(c_a, i, fr.STEPS[i]) and not fr.is_done(c_b, i, fr.STEPS[i])
              and not fr.is_done(c_x, i, fr.STEPS[i]), "3 configure done for its own toolchain only")
        cache(obj, os.path.join(root, "port", "cmake", "llvm-mingw.cmake"), lm_a, home)
        check(fr.prepare_sources(c_a) == [], "3 same toolchain: nothing to clean")
        check(len(fr.cmd_compile(c_a)) == 1, "3 same toolchain: compile only")
        check(fr.prepare_sources(c_b) == [c_b.b("obj")], "3 another toolchain: obj cleaned before the configure")
        cmds = fr.cmd_compile(c_x)
        check(len(cmds) == 2 and any("mingw-w64.cmake" in a for a in cmds[0]) and "--build" in cmds[1],
              f"3 compile after a switch configures first: {[x[:3] for x in cmds]}")
        check(not os.path.exists(os.path.join(obj, "CMakeCache.txt")), "3 the old cache is gone (fresh configure)")

        # 4. main(): the NOTE is printed and logged
        os.makedirs(os.path.join(tmp, "dump"), exist_ok=True)
        steps = [fr.Step("a", "A", 1, lambda c: [])]
        for extra, want in (((), True), (("--toolchain", lm_a), False)):
            out, dl = io.StringIO(), os.path.join(tmp, "dl" + str(want))
            rc = fr.main(["--dump", os.path.join(tmp, "dump"), "--root", os.path.join(tmp, "r4"), "--jobs", "1",
                          "--build", os.path.join(tmp, "b4" + str(want)), "--log-dir", dl, *extra], steps=steps, out=out)
            logs = [os.path.join(dl, n) for n in os.listdir(dl)] if os.path.isdir(dl) else []
            logged = any("NOTE toolchain:" in open(p, encoding="utf-8").read() for p in logs if os.path.isfile(p))
            said = "NOTE toolchain:" in out.getvalue()
            check(rc == 0, f"4 rc {rc} {extra}")
            check(said == want and logged == want, f"4 NOTE printed={said} logged={logged}, want {want} {extra}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_toolchain_switch:", "PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
