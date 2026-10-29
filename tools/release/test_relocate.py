#!/usr/bin/env python3
"""Host test (no game data): the portable zip's folder is moved and renamed between runs.
A temp install folder is built to the state a finished first run leaves (CMake cache and build.ninja in build/obj,
markers, paths.json with a dump inside the install, kz2-install.ini [paths], build-stamp.json) and renamed; the next
start must rebase the saved paths, keep the fingerprints (so no re-lift), configure again in an empty obj folder only
when the build needs obj, and leave nothing at the old path. Also an install from before the location record (the
old folder is read from the CMake cache) and a folder name with spaces and a bracket-free unusual name.
Run: python3 tools/release/test_relocate.py"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402
import launch  # noqa: E402

FAILS = []


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("FAIL", what)


def make_install(root, record):
    os.makedirs(os.path.join(root, "port", "kz2"))
    obj = os.path.join(root, "build", "obj")
    os.makedirs(obj)
    with open(os.path.join(obj, "CMakeCache.txt"), "w") as f:
        f.write(f"CMAKE_CACHEFILE_DIR:INTERNAL={obj}\nCMAKE_HOME_DIRECTORY:INTERNAL={os.path.join(root, 'port', 'kz2')}\n"
                f"CMAKE_MAKE_PROGRAM:FILEPATH={root}/toolchain/ninja/ninja\n")
    with open(os.path.join(obj, "build.ninja"), "w") as f:
        f.write(f"build x.o: CXX {root}/port/kz2/x.cpp\n")
    disc = os.path.join(root, "game", "disc")           # an extracted ISO: the dump lives inside the install
    os.makedirs(os.path.join(disc, "PS3_GAME", "USRDIR"))
    elf = os.path.join(disc, "PS3_GAME", "USRDIR", "EBOOT.BIN")
    open(elf, "w").write("x")
    upd = os.path.join(os.path.dirname(root), "update-outside")   # a folder elsewhere stays as it is
    os.makedirs(upd, exist_ok=True)
    open(os.path.join(root, "build", "kz2.exe"), "w").write("exe")
    open(os.path.join(root, "build", fr.AT3_DLL), "w").write("dll")
    with open(os.path.join(root, "build", "paths.json"), "w") as f:
        json.dump({"dump": disc, "iso": "", "update": upd, "eboot": elf, "facts": {"eboot_elf": "abc"}}, f)
    with open(os.path.join(root, "kz2-install.ini"), "w") as f:
        f.write(f"[install]\nportable = 1\n[paths]\ndump = {disc}\nupdate = {upd}\neboot = \nwrong = \n")
    os.makedirs(os.path.join(root, "build", fr.MARKER_DIR))
    ctx = launch.ctx_for(root, json.load(open(os.path.join(root, "build", "paths.json"))))
    with open(os.path.join(root, "build", "build-stamp.json"), "w") as f:
        json.dump({"parts": ctx.parts(), "eboot_stat": fr.eboot_stat(elf)}, f)
    if record:
        fr.relocate_saved(root)
    return ctx.parts()


def tree(path):
    return sorted(os.path.relpath(os.path.join(d, n), path) for d, ds, fs in os.walk(path) for n in ds + fs)


def one(tmp, record, newname):
    top = os.path.join(tmp, "case-record" if record else "case-legacy")
    old = os.path.join(top, "Pyrrhus One")
    os.makedirs(old)
    parts = make_install(old, record)
    new = os.path.join(top, "sub", newname)
    os.makedirs(os.path.dirname(new))
    os.rename(old, new)
    tag = f"[record={record}]"
    check(not os.path.exists(old), f"{tag} moved away")
    # the launcher starts first
    notes = fr.relocate_saved(new)
    check(len(notes) == 1, f"{tag} one note on a move: {notes}")
    p = json.load(open(os.path.join(new, "build", "paths.json")))
    check(p["dump"] == os.path.join(new, "game", "disc") and p["eboot"].startswith(new), f"{tag} paths.json rebased {p}")
    check(p["update"] == os.path.join(top, "update-outside"), f"{tag} a folder outside stays {p['update']}")
    ini = open(os.path.join(new, "kz2-install.ini")).read()
    check(old not in ini and os.path.join(new, "game", "disc") in ini, f"{tag} ini rebased")
    check(fr.relocate_saved(new) == [], f"{tag} second start: nothing more to do")
    rec = json.load(open(os.path.join(new, "build", fr.MARKER_DIR, fr.LOCATION)))
    check(rec["root"] == new, f"{tag} record names the new folder")
    # the finished build still runs, without a rebuild; same fingerprints (no re-lift)
    ctx = launch.ctx_for(new, p)
    check(ctx.parts() == parts, f"{tag} parts unchanged by the move {ctx.parts()} != {parts}")
    action, why = launch.decide(new)
    check(action == "run", f"{tag} decide after the move: {action} {why}")
    # obj holds the old place: compile and configure start from an empty folder
    obj = os.path.join(new, "build", "obj")
    check(not fr.cache_is_here(new, obj), f"{tag} the cache is seen as from another place")
    c = fr.Ctx(root=new, build=os.path.join(new, "build"), dump=p["dump"], eboot=p["eboot"], cmake="cmake", python="python3",
               toolchain="", ninja="", jobs=1)
    marker = os.path.join(obj, "stale.o")
    open(marker, "w").write("x")
    check(fr.prepare_sources(c) == [obj], f"{tag} configure's clean hook empties obj")
    fr.ffmpeg_include = lambda root: os.path.join(root, "ffmpeg", "include")   # configure needs the headers' folder
    fr.cmake_file = lambda c, n: os.path.join(c.root, "port", "cmake", n)
    cmds = fr.cmd_compile(c)
    check(len(cmds) == 2 and "-S" in cmds[0] and cmds[0][cmds[0].index("-S") + 1].startswith(new)
          and "--build" in cmds[1], f"{tag} compile configures first: {cmds}")
    check(not os.path.exists(marker) and not os.path.exists(os.path.join(obj, "build.ninja")), f"{tag} obj emptied")
    check(all(new in " ".join(x) or "cmake" in x[0] for x in cmds), f"{tag} commands name the new folder only")
    check(not any(old in " ".join(x) for x in cmds), f"{tag} nothing names the old folder")
    check(not os.path.exists(old) and "Pyrrhus One" not in " ".join(tree(top)), f"{tag} nothing at the old path: {tree(top)[:3]}")
    # a fresh cache for the new place is accepted
    os.makedirs(obj, exist_ok=True)
    with open(os.path.join(obj, "CMakeCache.txt"), "w") as f:
        f.write(f"CMAKE_CACHEFILE_DIR:INTERNAL={obj}\nCMAKE_HOME_DIRECTORY:INTERNAL={os.path.join(new, 'port', 'kz2')}\n")
    check(fr.cache_is_here(new, obj) and len(fr.cmd_compile(c)) == 1, f"{tag} a cache of this place is reused")
    check(fr.prepare_sources(c) == [], f"{tag} nothing to clean then")


def main():
    tmp = tempfile.mkdtemp(prefix="kz2-relocate-")
    try:
        one(tmp, True, "Renamed Folder")
        one(tmp, False, "other")        # an install from before the location record: the old folder read from the cache
        # same folder, same spelling: nothing changes
        r = os.path.join(tmp, "same")
        os.makedirs(r)
        make_install(r, True)
        check(fr.relocate_saved(r) == [] and fr.cache_is_here(r, os.path.join(r, "build", "obj")), "same folder untouched")
        # first run: no build folder, the record is made and the old path never appears
        f0 = os.path.join(tmp, "fresh")
        os.makedirs(f0)
        check(fr.relocate_saved(f0) == [] and os.path.isfile(os.path.join(f0, "build", fr.MARKER_DIR, fr.LOCATION)),
              "fresh folder gets a record")
        check(fr.cache_is_here(f0, os.path.join(f0, "build", "obj")), "no obj yet counts as here")
        # root_relative: inside is relative, outside unchanged
        check(fr.root_relative("/a/b", "/a/b/game/disc") == "<root>/game/disc" and fr.root_relative("/a/b", "/a/bc/x") == "/a/bc/x"
              and fr.root_relative("/a/b", "") == "", "root_relative")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("FAILED" if FAILS else "OK test_relocate")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
