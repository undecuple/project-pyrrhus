#!/usr/bin/env python3
"""Host test (an earlier changeb): updating a junction install to a payload whose runtime reads KZ2_CACHE_ROOT keeps the
player's saves, settings and caches. Drives tools/release/launch.py's own functions (link_free, drop_link, game_env)
on a fake install (a symlink stands in for the junction) and resolves the runtime's paths with the rules of
port/kz2/kz2_cache_root.h (kz2_cache_root_plan; compiled and tested in C by test_cache_root.sh) and ppu_fs.cpp host_path.
No game data, no GPU.   nix develop --command tools/sandbox.sh -- python3 -I tools/runtime/test_cache_root_update.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "release"))
import launch as la  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print(("PASS: " if ok else "[FAIL] ") + what)
    fails += 0 if ok else 1


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def host_path(guest, vfs, env):
    """ppu_fs.cpp host_path for the mounts Killzone 2 uses (PS3_HDD0_ROOT / PS3_HDD1_ROOT, else <vfs>/<rest>)."""
    for dev, var in (("/dev_hdd0/", "PS3_HDD0_ROOT"), ("/dev_hdd1/", "PS3_HDD1_ROOT")):
        if guest.startswith(dev) and env.get(var):
            return os.path.join(env[var], guest[len(dev):])
    for m in ("/dev_bdvd/", "/app_home/", "/dev_hdd0/", "/dev_hdd1/"):
        if guest.startswith(m):
            return os.path.join(vfs, guest[len(m):])
    return os.path.join(vfs, guest.lstrip("/"))


def runtime_env(env):
    """main.cpp kz2_split_roots on the launcher's environment (kz2_cache_root.h rules)."""
    e = dict(env)
    c = e.get("KZ2_CACHE_ROOT", "")
    if c:
        if not e.get("PS3_HDD1_ROOT"):
            e["PS3_HDD1_ROOT"] = c
        if not e.get("PS3_HDD0_ROOT"):
            e["PS3_HDD0_ROOT"] = os.path.join(e.get("PS3_GAMEDATA_ROOT") or "gamedata", "dev_hdd0")
    return e


FIOS = "/dev_hdd1/cache/BCUS98116/fios/cache.idx"
SAVE = os.path.join("gamedata", "dev_hdd0", "home", "00000001", "savedata", "BCUS98116-KILLZONE2", "PROFILE.DAT")

with tempfile.TemporaryDirectory() as tmp:
    root, dump, appdata = (os.path.join(tmp, n) for n in ("Project Pyrrhus", "dump", "AppData"))
    write(os.path.join(dump, "PS3_GAME", "PARAM.SFO"), "sfo")
    write(os.path.join(dump, "PS3_GAME", "USRDIR", "data_ps3.psarc"), "psarc")
    v = la.vfs_root(root)
    os.makedirs(v)
    os.symlink(os.path.join(dump, "PS3_GAME"), os.path.join(v, "PS3_GAME"), target_is_directory=True)
    write(os.path.join(v, la.VFS_LINK), json.dumps({"link": os.path.join(v, "PS3_GAME")}))
    write(os.path.join(root, "build", "build-stamp.json"), json.dumps({"cache_root": False}))
    environ = {"APPDATA": appdata, "PATH": "/bin"}
    paths = {"dump": dump, "update": os.path.join(tmp, "update"), "eboot": os.path.join(root, "build", "EBOOT.elf")}

    # before the update: junction layout, the runtime writes under <root>/vfs
    check(not la.link_free(root), "an old payload: the link path")
    _, cwd0, env0, _ = la.game_env(root, paths, False, environ)
    env0 = runtime_env(env0)
    fios0 = host_path(FIOS, env0["PS3_VFS_ROOT"], env0)
    write(fios0, "fios")
    write(os.path.join(fios0[:-len("cache.idx")], "kz2_cache_stamp.txt"), "stamp")
    write(os.path.join(cwd0, SAVE), "save")
    write(os.path.join(cwd0, "display.ini"), "[display]\nupscale = fsr1\n")
    check("KZ2_CACHE_ROOT" not in env0 and env0["PS3_VFS_ROOT"] == v, "old payload: VFS root <root>/vfs, no cache root")

    # the update: a payload with port/kz2/kz2_cache_root.h, the build stamps cache_root
    write(os.path.join(root, "build", "build-stamp.json"), json.dumps({"cache_root": True}))
    check(la.link_free(root), "new payload: link-free")
    _, cwd1, env1, _ = la.game_env(root, paths, False, environ)
    err = la.drop_link(root)
    env1 = runtime_env(env1)
    check(err == "" and not os.path.lexists(os.path.join(v, "PS3_GAME")) and not os.path.exists(os.path.join(v, la.VFS_LINK)),
          "the old link and its record are removed")
    check(os.path.isfile(os.path.join(dump, "PS3_GAME", "PARAM.SFO")) and
          os.path.isfile(os.path.join(dump, "PS3_GAME", "USRDIR", "data_ps3.psarc")), "the dump (the link's target) is kept")
    check(env1["PS3_VFS_ROOT"] == dump and env1["KZ2_CACHE_ROOT"] == v, "the dump is the VFS root, <root>/vfs the cache root")
    fios1 = host_path(FIOS, env1["PS3_VFS_ROOT"], env1)
    check(os.path.normpath(fios1) == os.path.normpath(fios0) and os.path.isfile(fios1),
          "the FIOS cache resolves to the same file under the cache root")
    check(cwd1 == cwd0 and os.path.isfile(os.path.join(cwd1, SAVE)) and os.path.isfile(os.path.join(cwd1, "display.ini")),
          "saves and settings stay in the working folder")
    save_dir = os.path.join(cwd1, env1["PS3_HDD0_ROOT"], "home")
    check(os.path.isdir(save_dir), "/dev_hdd0 is the saves' and trophies' tree (gamedata/dev_hdd0 under the working folder)")
    for g in ("/dev_hdd1/cache/BCUS98116/fios/cache.dat", "/dev_hdd0/home/00000001/trophy/x"):
        h = os.path.abspath(os.path.join(cwd1, host_path(g, env1["PS3_VFS_ROOT"], env1)))
        check(not h.startswith(os.path.abspath(dump) + os.sep), f"{g}: no write path into the dump ({h})")
    check(host_path("/dev_bdvd/PS3_GAME/USRDIR/data_ps3.psarc", env1["PS3_VFS_ROOT"], env1)
          == os.path.join(dump, "PS3_GAME/USRDIR/data_ps3.psarc"), "disc reads come from the dump in place")
    # a second start: nothing left to drop, same answer
    check(la.drop_link(root) == "" and os.path.isfile(fios1), "a second start changes nothing")

print("FAIL: %d" % fails if fails else "PASS: junction install updated to link-free")
sys.exit(1 if fails else 0)
