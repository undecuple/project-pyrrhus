#!/usr/bin/env python3
"""Host test (from Project Helghast) for tools/release/launch.py (the logic behind `Project Pyrrhus.exe`) and firstrun.py's per-step
fingerprints, on a synthetic install tree in a temp folder (no game data, no toolchain, no network, no Windows).
Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_launch.py

Cases: first-build without paths.json; missing-inputs when the dump is gone; resume without a stamp or kz2.exe; run
after a stamp written by firstrun's own after_stamp; --print JSON (game argv, cwd portable vs %APPDATA%, the four
variables, PS3_HDD0_ROOT only for an RPCS3 dev_hdd0/game/<id> update); rebuild reasons for a changed EBOOT, a lift
input (ppu_overrides.txt), the port version (VERSION.txt); firstrun markers: a lift-input change invalidates the lift
steps' markers but not load's; main(): "No" starts nothing, "Yes" runs the interactive build in a new console then
the game with its environment; resume uses --bar with the recorded paths; a failed build stops; the daily opt-in
version check (due once a day, off by default, never with check_updates=0); a newer result is asked once and a "No"
is remembered; --repair verifies the install against manifest.json (missing / changed file stops with a
message), then runs firstrun --bar with the recorded paths and never starts the game; "No" does nothing; a failed
repair returns 1; never built = the first-build question.
"""
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firstrun as fr  # noqa: E402
import launch as la  # noqa: E402

FAILS = []


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("FAIL", what)


def write(p, text="x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


class FakeUI:
    def __init__(self, answers):
        self.answers, self.asked, self.infos, self.urls = list(answers), [], [], []

    def ask(self, text):
        self.asked.append(text)
        return self.answers.pop(0) if self.answers else False

    def info(self, text):
        self.infos.append(text)

    def open_url(self, url):
        self.urls.append(url)


def make_tree(tmp):
    root = os.path.join(tmp, "Project Pyrrhus")
    hdd0 = os.path.join(tmp, "rpcs3", "dev_hdd0")
    dump, update = os.path.join(tmp, "dump"), os.path.join(hdd0, "game", "BCUS98116")
    eboot = os.path.join(update, "USRDIR", "EBOOT.elf")
    write(os.path.join(dump, "PS3_GAME", "PARAM.SFO"))
    write(eboot, "fake elf")
    for n in ("EBOOT.BIN", "added_data_ps3.psarc", os.path.join("patch_data_ps3", "x.pspatch")):   # update_problem
        write(os.path.join(update, "USRDIR", n), "x")
    write(os.path.join(root, "port", "kz2", "ppu_overrides.txt"), "a\n")
    write(os.path.join(root, "VERSION.txt"), "0.1.0")
    os.makedirs(os.path.join(root, "ps3recomp", "tools"))
    return root, dump, update, eboot, hdd0


def record(root, dump, update, eboot):
    c = fr.Ctx(root=root, build=os.path.join(root, "build"), dump=dump, update=update, eboot=eboot,
               facts={"eboot_elf": {"size": 8}})
    fr.after_record(c)
    return c


def stamp(c):
    write(c.b("obj", "kz2.exe"), "MZ")
    write(c.b("obj", "at3_standalone.dll"), "at3")
    fr.after_stamp(c)


def printed(root, extra=(), **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        la.main(["--root", root, "--print", *extra], ui=FakeUI([]), **kw)
    return json.loads(buf.getvalue())


class FakeKernel32:
    """GetVolumePathNameW / GetVolumeInformationW stand-ins: fill the ctypes buffers as Windows would."""
    def __init__(self, drives, fail_info=False):
        self.drives, self.fail_info = drives, fail_info   # {"D:": "exFAT"} by the path's first two characters

    def GetVolumePathNameW(self, path, buf, n):
        m = re.search(r"([A-Z]:)[\\/]", path)   # (os.path.abspath on Linux puts the cwd in front)
        d = m.group(1) if m else ""
        if d not in self.drives:
            return 0
        buf.value = d + "\\"
        return 1

    def GetVolumeInformationW(self, vol, name, nn, serial, maxlen, flags, fsbuf, n):
        if self.fail_info:
            return 0
        fsbuf.value = self.drives[vol[:2]]
        return 1


def fs_tests():
    """12a. The drives' file systems for the first-run log and the link error (issue #20), the call mocked."""
    k = FakeKernel32({"D:": "exFAT", "E:": "NTFS"})
    check(fr.volume_fs("D:\\Killzone 2\\Project Pyrrhus", k) == ("D:\\", "exFAT"), "12a volume_fs with a mocked kernel32")
    check(fr.file_systems([("install", "D:\\Killzone 2\\Project Pyrrhus"), ("game files", "D:\\Killzone 2"),
                           ("update", "E:\\upd")], k) == "install, game files D:\\ exFAT; update E:\\ NTFS",
          f"12a one entry per drive: {fr.file_systems([('install', 'D:/x'), ('game files', 'E:/y')], k)}")
    check(fr.file_systems([("install", "D:\\x")], FakeKernel32({"D:": ""}, fail_info=True)) == "install D:\\ (file system unknown)",
          "12a the name missing: the drive is still named")
    check(fr.file_systems([("install", "Q:\\x")], k) == "", "12a an unknown drive: nothing")

    class Boom:
        def __getattr__(self, n):
            raise OSError("no kernel32")
    check(fr.volume_fs("D:\\x", Boom()) == ("", ""), "12a a failing call never raises")
    check(fr.file_systems([("install", "/tmp")]) == "" if os.name != "nt" else True, "12a Linux: nothing, no failure")


def link_tests(tmp):
    """12. The vfs link on a drive that cannot hold one (issue #20, launcher 0.1.2: CreateJunction made the folder,
    failed with WinError 1392 setting the link, the symlink then failed with 183, and every later start said "is a real
    folder"; the install was inside the dump folder). Windows is stood in for by the module's link makers."""
    fs_tests()
    junction, symlink = la.create_junction, la.make_symlink
    made = []
    bad_dirs = []       # folders whose drive cannot hold links (empty: none)

    def half_junction(target, link):     # _winapi.CreateJunction: the folder first, then the reparse point fails
        os.mkdir(link)
        made.append(link)
        if any(link.startswith(b) for b in bad_dirs) or not bad_dirs:
            raise OSError(22, "[WinError 1392] The file or directory is corrupted and unreadable")
        os.rmdir(link)
        os.symlink(target, link, target_is_directory=True)

    def no_symlink(target, link, target_is_directory=False):
        if os.path.lexists(link):
            raise FileExistsError(17, "[WinError 183] Cannot create a file when that file already exists")
        raise OSError(1314, "[WinError 1314] A required privilege is not held by the client")
    fs = lambda r, d: "install, game files D:\\ exFAT"   # noqa: E731
    try:
        # the reporter's layout: the install folder inside the dump folder (D:\Killzone 2\Project Pyrrhus)
        base = os.path.join(tmp, "t12")
        dump = os.path.join(base, "Killzone 2")
        root, _, update, eboot, _ = make_tree(os.path.join(tmp, "t12x"))
        shutil.move(root, os.path.join(dump, "Project Pyrrhus"))
        root = os.path.join(dump, "Project Pyrrhus")
        write(os.path.join(dump, "PS3_GAME", "PARAM.SFO"))
        vl = os.path.join(root, "vfs", "PS3_GAME")
        la.create_junction, la.make_symlink = half_junction, no_symlink
        v, err = la.ensure_vfs(root, dump, fs_of=fs)
        check(made == [vl] and not os.path.lexists(vl) and os.path.isdir(v), f"12 a half-made junction is removed {made}")
        check("NTFS" in err and "Drives: install, game files D:\\ exFAT" in err and "1392" in err and "may be damaged" in err
              and "may not support" in err and "183" not in err and "1314" in err,
              f"12 the error names NTFS, the drives' file systems, the 1392 hint and both real errors, not 183: {err}")
        check(sorted(os.listdir(os.path.join(dump, "PS3_GAME"))) == ["PARAM.SFO"], "12 the dump is untouched")

        def junction_with_files(target, link):  # never seen; proves a folder with anything in it is never removed
            write(os.path.join(link, "keep.txt"), "mine")
            raise OSError(22, "[WinError 1392] x")
        la.create_junction = junction_with_files
        la._make_dir_link(os.path.join(dump, "PS3_GAME"), vl)
        check(os.path.isfile(os.path.join(vl, "keep.txt")), "12 a failed junction's folder with files in it stays")
        shutil.rmtree(vl)
        os.mkdir(vl)
        la.create_junction = half_junction
        check(la._make_dir_link(os.path.join(dump, "PS3_GAME"), vl) and os.path.isdir(vl),
              "12 a folder that was there before the attempt is not removed by it")
        os.rmdir(vl)

        # The stuck second start: launcher 0.1.2 left an empty real PS3_GAME and no link.json
        la.create_junction, la.make_symlink = junction, symlink
        os.mkdir(vl)
        v, err = la.ensure_vfs(root, dump)
        check(err == "" and v == os.path.join(root, "vfs") and la._is_dir_link(vl) and os.path.isfile(os.path.join(vl, "PARAM.SFO")),
              f"12 an empty real PS3_GAME left by a failed junction is replaced by the link, install inside the dump ({err})")
        os.unlink(vl)
        os.remove(os.path.join(root, "vfs", "link.json"))   # (a recorded path is taken as the link: older Pythons)
        write(os.path.join(vl, "keep.txt"), "mine")
        v, err = la.ensure_vfs(root, dump)
        check("files in it" in err and os.path.isfile(os.path.join(vl, "keep.txt")),
              f"12 a PS3_GAME with files is never removed ({err})")
        shutil.rmtree(vl)
        inner = os.path.join(dump, "PS3_GAME", "Project Pyrrhus")
        v, err = la.ensure_vfs(inner, dump)
        check("inside the game's own PS3_GAME" in err and not os.path.exists(os.path.join(inner, "vfs")),
              f"12 an install inside PS3_GAME is refused, nothing written there ({err})")

        # The second place: %LOCALAPPDATA%\Project Pyrrhus\vfs when the install drive cannot hold the link
        local = os.path.join(tmp, "local")
        alt = la.alt_vfs_root({"LOCALAPPDATA": local})
        check(alt == os.path.join(local, "Project Pyrrhus", "vfs") and la.alt_vfs_root({}) == "", f"12 alt place {alt}")
        la.create_junction, la.make_symlink = half_junction, no_symlink
        bad_dirs[:] = [os.path.join(root, "vfs")]
        v, err = la.ensure_vfs(root, dump, alt, fs_of=fs)
        check(err == "" and v == alt and la._is_dir_link(os.path.join(alt, "PS3_GAME"))
              and not os.path.lexists(vl), f"12 no link in the install: the game's VFS folder is the alt one ({v}, {err})")
        log = open(os.path.join(root, "logs", "launcher.log"), encoding="utf-8").read()
        check("using " + alt in log, "12 the move is in launcher.log")
        la.create_junction, la.make_symlink = junction, symlink
        check(la.ensure_vfs(root, dump, alt) == (alt, "") and not os.path.lexists(vl)
              and la.current_vfs(root, dump, alt) == alt, "12 the alt folder stays in use (caches and trophies stay put)")
        la.create_junction, la.make_symlink = half_junction, no_symlink
        bad_dirs[:] = [os.path.join(root, "vfs"), alt]
        shutil.rmtree(os.path.join(local))
        v, err = la.ensure_vfs(root, dump, alt, fs_of=fs)
        check(v == os.path.join(root, "vfs") and root in err and alt in err and "NTFS" in err,
              f"12 neither place: both named ({err})")
        check(la.probe_link(root, alt, fs_of=fs) and os.listdir(os.path.join(root, "vfs")) == []
              and os.listdir(alt) == [], "12 the link check fails in both places and leaves nothing")
        bad_dirs[:] = [os.path.join(root, "vfs")]
        check(la.probe_link(root, alt, fs_of=fs) == "" and os.listdir(alt) == [], "12 the link check passes on the alt place")
        shutil.rmtree(local)

        # Path length: the second place is shorter than the default install's own VFS folder
        # (%LOCALAPPDATA%\Programs\Project Pyrrhus\vfs), so no game path gets longer than a default install's.
        check(len(la.alt_vfs_root({"LOCALAPPDATA": "C:\\Users\\a-long-user-name\\AppData\\Local"}))
              < len(la.vfs_root("C:\\Users\\a-long-user-name\\AppData\\Local\\Programs\\Project Pyrrhus")),
              "12 the alt VFS folder's path is shorter than the default install's")
        # Where the runtime's writes land: a model of ps3recomp's guest-to-host mapping (runtime/ppu/ppu_fs.cpp host_path
        # and runtime/syscalls/sys_fs.c, with no PS3_HDD0_ROOT/PS3_HDD1_ROOT/PS3_USRDIR_BASE: mount prefix stripped, any
        # "USRDIR/" path flattened to <root>/USRDIR in sys_fs) for the writable places the game uses. With either VFS
        # folder of ours nothing lands in the dump; with the dump itself as the VFS root (read in place) every one does,
        # which is why that is not offered.
        def host(vroot, guest):
            u = guest.find("USRDIR/")
            if u >= 0:
                return os.path.join(vroot, guest[u:])
            for m in ("/dev_bdvd/", "/app_home/", "/dev_hdd0/", "/dev_hdd1/", "/host_root/", "/dev_usb000/", "/dev_usb/"):
                if guest.startswith(m):
                    return os.path.join(vroot, guest[len(m):])
            return os.path.join(vroot, guest.lstrip("/"))
        writes = ("/dev_hdd1/cache/BCUS98116/fios/cache.dat", "/dev_hdd0/home/00000001/trophy/x", "/dev_usb000/x",
                  "/dev_hdd0/game/BCUS98116/USRDIR/new.dat", "/host_root/x", "psarc-cache/a")
        for vroot in (os.path.join(root, "vfs"), alt):
            check(not any(la._inside(host(vroot, g), os.path.join(dump, "PS3_GAME")) for g in writes),
                  f"12 writes stay out of the dump's PS3_GAME with VFS root {vroot}")
        inplace = [g for g in writes if la._inside(host(dump, g), dump)]
        check(inplace == list(writes), f"12 control: the dump as VFS root takes every write {inplace}")

        # A moved install folder (relocate_saved): the link inside it still points at the dump; the stale record's
        # "link" path does not matter, and the next start keeps (or remakes) the link, never a refusal
        la.create_junction, la.make_symlink = junction, symlink
        la.ensure_vfs(root, dump)
        moved = os.path.join(dump, "Project Pyrrhus moved")
        shutil.move(root, moved)
        v, err = la.ensure_vfs(moved, dump)
        check(err == "" and la._is_dir_link(os.path.join(moved, "vfs", "PS3_GAME"))
              and os.path.isfile(os.path.join(moved, "vfs", "PS3_GAME", "PARAM.SFO")), f"12 a moved install keeps its link ({err})")
        shutil.move(moved, root)
        os.unlink(vl)
        os.remove(os.path.join(root, "vfs", "link.json"))

        # The early check: before the build, within seconds; nothing left behind either way
        la.create_junction, la.make_symlink = junction, symlink
        check(la.probe_link(root) == "" and os.listdir(os.path.join(root, "vfs")) == [],
              f"12 the link check passes and leaves nothing {os.listdir(os.path.join(root, 'vfs'))}")
        la.create_junction, la.make_symlink = half_junction, no_symlink
        bad_dirs[:] = []
        perr = la.probe_link(root, fs_of=fs)
        check("NTFS" in perr and "exFAT" in perr and os.listdir(os.path.join(root, "vfs")) == [],
              f"12 a failed link check names the cause and leaves nothing: {perr}")
        ui, runs = FakeUI([True]), []
        rc = la.main(["--root", root], ui=ui, run=lambda a, **k: runs.append(a) or 0, environ={"PATH": "/bin"})
        log = open(os.path.join(root, "logs", "launcher.log"), encoding="utf-8").read()
        check(rc == 1 and not runs and not ui.asked and ui.infos and "NTFS" in ui.infos[-1],
              f"12 first build: the link check stops before the build is offered {rc} {runs} {ui.asked} {ui.infos}")
        check("vfs: link check:" in log, "12 the link check is in launcher.log")
        # A built install on such a drive: the game is not started and the dialog says why
        c = record(root, dump, update, eboot)
        stamp(c)
        ui, runs = FakeUI([]), []
        rc = la.main(["--root", root], ui=ui, run=lambda a, **k: runs.append(a) or 0, environ={"PATH": "/bin"})
        check(rc == 1 and not runs and ui.infos and "NTFS" in ui.infos[-1] and not os.path.lexists(vl),
              f"12 run: no game start, the NTFS text, no half-made folder {rc} {runs} {ui.infos}")
        # ... with %LOCALAPPDATA%: the game starts with the alt VFS root
        bad_dirs[:] = [os.path.join(root, "vfs")]
        ui, runs = FakeUI([]), []
        envl = {"PATH": "/bin", "LOCALAPPDATA": local}
        calls = []
        rc = la.main(["--root", root], ui=ui, run=lambda a, **k: calls.append((a, k)) or 0, environ=envl)
        check(rc == 0 and len(calls) == 1 and calls[0][1]["env"]["PS3_VFS_ROOT"] == alt,
              f"12 run with the alt VFS root {rc} {ui.infos} {[c[1].get('env', {}).get('PS3_VFS_ROOT') for c in calls]}")
        check(printed(root, environ=envl)["env"]["PS3_VFS_ROOT"] == alt, "12 --print shows the alt VFS root")
        # Link-free (Project Helghast's design): a runtime that reads KZ2_CACHE_ROOT gets the dump as its VFS root and
        # <root>/vfs for every write; no link is made even where links fail, and an old one is dropped (target kept)
        hdr = os.path.join(root, "port", "kz2", "kz2_cache_root.h")
        check(not fr.cache_root_supported(root) and not la.link_free(root), "12b no runtime support: the link path")
        write(hdr, "/* KZ2_CACHE_ROOT */")
        la.create_junction, la.make_symlink = junction, symlink
        la.ensure_vfs(root, dump)                          # an old start's link, to be dropped
        la.create_junction, la.make_symlink = half_junction, no_symlink
        bad_dirs[:] = []
        stamp(c)
        check(la.link_free(root), "12b the stamp records the runtime's cache-root support")
        calls = []
        ui = FakeUI([])
        rc = la.main(["--root", root], ui=ui, run=lambda a, **k: calls.append((a, k)) or 0, environ=envl)
        e = calls[0][1]["env"] if calls else {}
        check(rc == 0 and e.get("PS3_VFS_ROOT") == dump and e.get("KZ2_CACHE_ROOT") == os.path.join(root, "vfs")
              and not os.path.lexists(vl) and os.path.isfile(os.path.join(dump, "PS3_GAME", "PARAM.SFO")),
              f"12b link-free run: dump read in place, writes under vfs, old link dropped {rc} {ui.infos} "
              f"{ {k: e.get(k) for k in ('PS3_VFS_ROOT', 'KZ2_CACHE_ROOT')} }")
        os.remove(os.path.join(root, "build", "build-stamp.json"))
        ui, runs = FakeUI([False]), []
        la.main(["--root", root], ui=ui, run=lambda a, **k: runs.append(a) or 0, environ={"PATH": "/bin"})
        check(ui.asked and not any("NTFS" in t for t in ui.infos), f"12b link-free payload: no link check before the build {ui.infos}")
        os.remove(hdr)
        stamp(c)
        la.create_junction, la.make_symlink = junction, symlink
        shutil.rmtree(local)
        ui, runs = FakeUI([]), []
        rc = la.main(["--root", root], ui=ui, run=lambda a, **k: runs.append(a) or 0, environ={"PATH": "/bin"})
        check(rc == 0 and len(runs) == 1 and la._is_dir_link(vl), f"12 the next start on a good drive runs {rc} {ui.infos}")
    finally:
        la.create_junction, la.make_symlink = junction, symlink

def main():
    tmp = tempfile.mkdtemp(prefix="kz2-launch-")
    try:
        root, dump, update, eboot, hdd0 = make_tree(tmp)
        env = {"APPDATA": os.path.join(tmp, "AppData"), "PATH": "/bin"}
        check(la.decide(root)[0] == "first-build", "1 no paths.json -> first-build")
        p = printed(root, environ=env)
        check(p["action"] == "first-build" and "--interactive" in p["build"] and "--portable" not in p["build"],
              f"1 print first-build {p}")

        # 1b. the installer's folders in kz2-install.ini [paths]: the first build starts from them and checks first
        ini_p = os.path.join(root, "kz2-install.ini")
        write(ini_p, "[install]\nportable = 1\n[paths]\ndump = %s\nupdate = %s\neboot = %s\n" % (dump, update, eboot))
        fb = printed(root, environ=env)["build"]
        check("--check-first" in fb and "--interactive" in fb and fb[fb.index("--dump") + 1] == dump
              and fb[fb.index("--update") + 1] == update and fb[fb.index("--eboot") + 1] == eboot and "--portable" in fb,
              f"1b first-build with ini [paths] carries the folders {fb}")
        write(ini_p, "[paths]\ndump = \nupdate = %s\n" % update)
        check("--check-first" not in printed(root, environ=env)["build"], "1b ini without a dump -> plain --interactive")
        write(ini_p, "[paths]\ndump = %s\nupdate = %s\n" % (dump, update))
        fb = printed(root, environ=env)["build"]
        check("--check-first" in fb and "--eboot" not in fb, f"1b no eboot in the ini: the check finds it {fb}")
        os.remove(ini_p)
        check("--check-first" not in printed(root, environ=env)["build"], "1b no ini -> plain --interactive")

        c = record(root, dump, update, eboot)
        os.rename(dump, dump + ".moved")
        a, why = la.decide(root)
        check(a == "missing-inputs" and dump in why, f"2 missing dump {a} {why}")
        write(ini_p, "[paths]\ndump = %s\nupdate = %s\n" % (dump, update))
        mi = la.firstrun_cmd(root, "missing-inputs", {"dump": dump, "update": update}, False, "py")
        check("--check-first" not in mi and "--interactive" in mi and "--dump" not in mi, f"2 missing-inputs still asks {mi}")
        os.remove(ini_p)
        os.rename(dump + ".moved", dump)

        check(la.decide(root)[0] == "resume", "3 no stamp -> resume")
        p = printed(root, environ=env)
        b = p["build"]
        check("--bar" in b and b[b.index("--dump") + 1] == dump and b[b.index("--eboot") + 1] == eboot
              and "--interactive" not in b, f"3 resume command {b}")

        stamp(c)
        os.remove(c.b("kz2.exe"))
        check(la.decide(root)[0] == "resume", "4 stamp without kz2.exe -> resume")
        stamp(c)
        check(la.decide(root) == ("run", ""), f"4 built -> run {la.decide(root)}")
        p = printed(root, environ=env)
        check(p["argv"] == [os.path.join(root, "build", "kz2.exe"), eboot], f"5 argv {p.get('argv')}")
        check(p["cwd"] == os.path.join(env["APPDATA"], "Project Pyrrhus"), f"5 cwd appdata {p.get('cwd')}")
        e = p["env"]
        check(e.get("PS3_VFS_ROOT") == os.path.join(root, "vfs") and e.get("KZ2_UPDATE_DIR") == os.path.join(update, "USRDIR")
              and e.get("PS3_HDD0_ROOT") == hdd0
              and e.get("PS3_EDAT_CACHE") == os.path.join(root, "build", "cache", "edat")
              and e.get("VKD3D_SHADER_CACHE_PATH") == os.path.join(env["APPDATA"], "Project Pyrrhus", "cache", "vkd3d"),
              f"5 env {e}")
        check(la.rpcs3_hdd0(os.path.join(tmp, "elsewhere", "BCUS98116")) == "", "5 no hdd0 outside RPCS3 layout")
        fr.write_install_ini(root, True, False)
        p = printed(root, environ=env)
        check(p["cwd"] == root and p["portable"]
              and p["env"]["VKD3D_SHADER_CACHE_PATH"] == os.path.join(root, "cache", "vkd3d"),
              f"5 portable cwd and vkd3d cache {p.get('cwd')}")

        # 5b. [controls] layout: default original, modern, unknown -> original + one log line
        ini_p = os.path.join(root, "kz2-install.ini")
        os.remove(ini_p)
        check(la.read_ini(root)["layout"] == "original" and not la.read_ini(root)["layout_bad"], "5b missing ini")
        p = printed(root, environ=dict(env, KZ2_PAD_LAYOUT="modern"))
        check(p["env"]["KZ2_PAD_LAYOUT"] == "original" and p["controls"] == "original", f"5b default env {p.get('env')}")
        fr.write_install_ini(root, True, False)
        check(la.read_ini(root)["layout"] == "original" and "layout = original" in open(ini_p).read(), "5b installer default")
        write(ini_p, "[controls]\nlayout = Modern\n")
        p = printed(root, environ=env)
        check(la.read_ini(root)["layout"] == "modern" and p["env"]["KZ2_PAD_LAYOUT"] == "modern", "5b modern env")
        write(ini_p, "[controls]\nlayout = bogus\n")
        ini5 = la.read_ini(root)
        check(ini5["layout"] == "original" and ini5["layout_bad"] == "bogus", "5b bad value -> original")
        la.main(["--root", root, "--print"], ui=FakeUI([]), environ=env)
        la.note(root, "x")
        la.main(["--root", root], ui=FakeUI([True]), run=lambda a, **k: 0, start=lambda *a, **k: None, environ=env)
        lg = open(os.path.join(root, "logs", "launcher.log")).read()
        check(lg.count("'bogus' is unknown") == 1, "5b bad value logged once")
        lines = [ln.split(" ", 1)[1] for ln in lg.splitlines()]
        k = next(i for i, ln in enumerate(lines) if ln.startswith("start: "))
        st = json.load(open(os.path.join(root, "build", "build-stamp.json")))
        check(lines[k + 1] == f"version: 0.1.0 (build stamp: version {st['version']}, built {st['built']})",
              f"5b launcher.log: the version line with the build stamp follows start ({lines[k:k + 2]})")
        os.rename(os.path.join(root, "build", "build-stamp.json"), os.path.join(root, "build", "bs.json"))
        check(la.version_line(root) == "version: 0.1.0", "5b version line without a build stamp invents nothing")
        os.rename(os.path.join(root, "build", "bs.json"), os.path.join(root, "build", "build-stamp.json"))
        seen = {}
        la.main(["--root", root], ui=FakeUI([]), run=lambda a, **k: seen.update(k) or 0, start=lambda *a, **k: None,
                environ=env)
        check(seen.get("env", {}).get("KZ2_PAD_LAYOUT") == "original", "5b run passes original for bad value")
        # 5c. A game that dies with a Windows exception code gets one message with the log folder; normal ends and
        # the game's own error exits (small codes, with their own box) get none
        for code, boxes in ((0xC0000005, 1), (0, 0), (2, 0)):
            ui = FakeUI([])
            rc = la.main(["--root", root], ui=ui, run=lambda a, **k: code, start=lambda *a, **k: None, environ=env)
            check(rc == code and len(ui.infos) == boxes
                  and (not boxes or ("0xC0000005" in ui.infos[0] and os.path.join("build", "logs") in ui.infos[0]
                                     and "issues" in ui.infos[0])), f"5c exit code {code:#x}: {boxes} message(s)")
        check(la.crashed(-1073741819) and la.crashed(0xC0000409) and not la.crashed(1) and not la.crashed(None),
              "5c crash codes, signed or not")
        # 5c. A folder the launcher cannot write (here: a file where the vkd3d cache folder goes) = one message, no game
        blocker = os.path.join(env["APPDATA"], "Project Pyrrhus", "cache")
        shutil.rmtree(blocker, ignore_errors=True)
        write(blocker, "not a folder")
        ui, ran = FakeUI([]), []
        rc = la.main(["--root", root], ui=ui, run=lambda a, **k: ran.append(a) or 0, start=lambda *a, **k: None,
                     environ=env)
        check(rc == 1 and not ran and len(ui.infos) == 1 and "Could not prepare the game" in ui.infos[0]
              and "write" in ui.infos[0], f"5c unwritable folder: a message, no game {ui.infos}")
        os.remove(blocker)
        ui = FakeUI([True])
        check(la.main(["--root", root, "--controls"], ui=ui, environ=env) == 0 and la.read_ini(root)["layout"] == "modern"
              and "Original (default)" in ui.asked[0] and "keyboard" in ui.asked[0], "5b launcher choice Modern")
        check(la.main(["--root", root, "--controls", "original"], ui=FakeUI([]), environ=env) == 0
              and la.read_ini(root)["layout"] == "original", "5b --controls original")
        check(la.main(["--root", root, "--controls", "x"], ui=FakeUI([]), environ=env) == 2
              and la.read_ini(root)["layout"] == "original", "5b --controls bad rejected")
        fr.write_install_ini(root, True, False)
        # 5c. [controls] prompts: default auto, each name reaches KZ2_PROMPTS, ps5 = ps4, unknown -> auto + one log line
        write(ini_p, "[controls]\nlayout = original\n")
        p = printed(root, environ=env)
        check("KZ2_PROMPTS" not in p["env"] and p["controls"] == "original", f"5c default auto leaves it unset {p.get('env')}")
        for name in ("auto", "ps3", "ps4", "xbox", "keyboard"):
            write(ini_p, f"[controls]\nprompts = {name.upper()}\n")
            pe = printed(root, environ=env)["env"]
            check(pe.get("KZ2_PROMPTS", "auto") == name and (name == "auto") == ("KZ2_PROMPTS" not in pe), f"5c {name}")
        write(ini_p, "[controls]\nprompts = PS5\n")
        check(printed(root, environ=env)["env"]["KZ2_PROMPTS"] == "ps4", "5c ps5 -> ps4")
        write(ini_p, "[controls]\nprompts = bogus\n")
        check("KZ2_PROMPTS" not in printed(root, environ=env)["env"], "5c bad value leaves it unset")
        check(la.read_ini(root)["prompts_bad"] == "bogus" and la.read_ini(root)["prompts"] == "auto", "5c bad -> auto")
        la.main(["--root", root], ui=FakeUI([]), run=lambda a, **k: 0, start=lambda *a, **k: None, environ=env)
        la.main(["--root", root], ui=FakeUI([]), run=lambda a, **k: 0, start=lambda *a, **k: None, environ=env)
        lg = open(os.path.join(root, "logs", "launcher.log")).read()
        check("prompts = 'bogus' is unknown" in lg, "5c bad value logged")
        check(la.main(["--root", root, "--prompts", "xbox"], ui=FakeUI([]), environ=env) == 0
              and la.read_ini(root)["prompts"] == "xbox", "5c --prompts xbox")
        check(la.main(["--root", root, "--prompts"], ui=FakeUI([]), environ=env) == 0
              and la.read_ini(root)["prompts"] == "keyboard", "5c --prompts cycles to the next set")
        check(la.main(["--root", root, "--prompts"], ui=FakeUI([]), environ=env) == 0
              and la.read_ini(root)["prompts"] == "auto", "5c cycle wraps to auto")
        check(la.main(["--root", root, "--prompts", "x"], ui=FakeUI([]), environ=env) == 2
              and la.read_ini(root)["prompts"] == "auto", "5c --prompts bad rejected")
        write(ini_p, "[controls]\nlayout = modern\nprompts = ps3\n")
        la.main(["--root", root, "--prompts", "xbox"], ui=FakeUI([]), environ=env)
        check(la.read_ini(root)["layout"] == "modern", "5c prompts change keeps layout")
        os.remove(ini_p)
        fr.write_install_ini(root, True, False)
        check(la.read_ini(root)["prompts"] == "auto" and "prompts = auto" in open(ini_p).read(), "5c installer default auto")
        fr.write_install_ini(root, True, False, prompts="keyboard")
        fr.write_install_ini(root, True, False)
        check(la.read_ini(root)["prompts"] == "keyboard", "5c rewrite without prompts keeps the choice")
        fr.write_install_ini(root, True, False, prompts="auto")
        # 5d. [display] mode: unset leaves KZ2_DISPLAY out (display.ini decides), each mode reaches KZ2_DISPLAY,
        # window/exclusive aliases, unknown -> windowed + one log line, --display sets/cycles, installer default borderless
        write(ini_p, "[controls]\nlayout = original\n")
        p = printed(root, environ=env)
        check("KZ2_DISPLAY" not in p["env"] and p["display"] == "borderless", f"5d unset leaves it unset {p.get('env')}")
        for name in ("windowed", "borderless", "fullscreen"):
            write(ini_p, f"[display]\nmode = {name.upper()}\n")
            check(printed(root, environ=env)["env"].get("KZ2_DISPLAY") == name, f"5d {name}")
        write(ini_p, "[display]\nmode = exclusive\n")
        check(printed(root, environ=env)["env"]["KZ2_DISPLAY"] == "fullscreen", "5d exclusive = fullscreen")
        write(ini_p, "[display]\nmode = bogus\n")
        check(printed(root, environ=env)["env"]["KZ2_DISPLAY"] == "borderless" and la.read_ini(root)["display_bad"] == "bogus",
              "5d bad -> borderless")
        la.main(["--root", root], ui=FakeUI([]), run=lambda a, **k: 0, start=lambda *a, **k: None, environ=env)
        check("mode = 'bogus' is unknown" in open(os.path.join(root, "logs", "launcher.log")).read(), "5d bad value logged")
        # 5f (issue #16): an update folder that lost its data stops the start with the reason, not a menu crash
        check(la.update_problem({"update": update}) == "", "5f the full update folder passes")
        os.rename(os.path.join(update, "USRDIR", "added_data_ps3.psarc"), os.path.join(update, "USRDIR", "a.bak"))
        up = la.update_problem({"update": update})
        check("added_data_ps3.psarc" in up and "main menu" in up and "EBOOT.BIN" not in up, f"5f missing data named: {up}")
        os.rename(os.path.join(update, "USRDIR", "a.bak"), os.path.join(update, "USRDIR", "added_data_ps3.psarc"))
        home = os.path.expanduser("~")
        la.note(root, f"vfs: cannot link {os.path.join(home, 'Games', 'KZ2', 'PS3_GAME')}")
        lg = open(os.path.join(root, "logs", "launcher.log")).read().splitlines()[-1]
        check(home not in lg and "%USERPROFILE%" in lg, f"5e launcher.log: the home folder is %USERPROFILE% (issue #16): {lg}")
        seen = {}
        write(ini_p, "[display]\nmode = borderless\n")
        la.main(["--root", root], ui=FakeUI([]), run=lambda a, **k: seen.update(k) or 0, start=lambda *a, **k: None,
                environ=dict(env, KZ2_DISPLAY="fullscreen"))
        check(seen.get("env", {}).get("KZ2_DISPLAY") == "borderless", "5d run passes the launcher's mode")
        check(la.main(["--root", root, "--display", "fullscreen"], ui=FakeUI([]), environ=env) == 0
              and la.read_ini(root)["display"] == "fullscreen", "5d --display fullscreen")
        check(la.main(["--root", root, "--display"], ui=FakeUI([]), environ=env) == 0
              and la.read_ini(root)["display"] == "windowed", "5d --display cycles and wraps")
        check(la.main(["--root", root, "--display"], ui=FakeUI([]), environ=env) == 0
              and la.read_ini(root)["display"] == "borderless", "5d cycle to borderless")
        check(la.main(["--root", root, "--display", "x"], ui=FakeUI([]), environ=env) == 2
              and la.read_ini(root)["display"] == "borderless", "5d --display bad rejected")
        write(ini_p, "[controls]\nlayout = modern\n[display]\nmode = fullscreen\n")
        la.main(["--root", root, "--display", "windowed"], ui=FakeUI([]), environ=env)
        check(la.read_ini(root)["layout"] == "modern", "5d display change keeps layout")
        os.remove(ini_p)
        fr.write_install_ini(root, True, False)
        check(la.read_ini(root)["display"] == "borderless" and "mode = borderless" in open(ini_p).read(), "5d installer default borderless")
        fr.write_install_ini(root, True, False, display="fullscreen")
        fr.write_install_ini(root, True, False)
        check(la.read_ini(root)["display"] == "fullscreen", "5d rewrite without display keeps the choice")
        fr.write_install_ini(root, True, False, display="windowed")

        # 6. rebuild reasons
        st = os.stat(eboot)
        os.utime(eboot, (st.st_atime, st.st_mtime + 10))
        a, why = la.decide(root)
        check(a == "rebuild" and "EBOOT" in why, f"6 EBOOT touched {a} {why}")
        os.utime(eboot, (st.st_atime, st.st_mtime))
        check(la.decide(root)[0] == "run", "6 EBOOT restored -> run")
        write(os.path.join(root, "VERSION.txt"), "0.1.1")
        a, why = la.decide(root)
        check(a == "rebuild" and "updated" in why, f"6 version {a} {why}")
        write(os.path.join(root, "VERSION.txt"), "0.1.0")
        write(os.path.join(root, "port", "kz2", "ppu_overrides.txt"), "b\n")
        a, why = la.decide(root)
        check(a == "rebuild" and why == "This version changes the lift (lift and compile again)", f"6 lift input {a} {why}")
        write(os.path.join(root, "port", "kz2", "ppu_overrides.txt"), "a\n")
        check(la.decide(root)[0] == "run", "6 override table restored -> run")
        for t in ("ppu_lift_fixups-129.txt", "ppu_overrides-101.txt"):   # an upgrade that adds or changes a lift table
            write(os.path.join(root, "port", "kz2", t), "end 0x1 0x2\n")
            a, why = la.decide(root)
            check(a == "rebuild" and "changes the lift" in why, f"6 an upgrade adding {t} relifts: {a} {why}")
            os.remove(os.path.join(root, "port", "kz2", t))
        write(os.path.join(root, "port", "kz2", "ppu_overrides.txt"), "b\n")

        # 7. firstrun markers follow their keys
        c2 = fr.Ctx(root=root, build=c.build, dump=dump, update=update, eboot=eboot, facts=c.facts)
        steps = {s.name: (i, s) for i, s in enumerate(fr.STEPS)}
        for n in ("load", "ppu-lift", "compile"):
            fr.mark_done(c2, *steps[n], 1.0)
        write(os.path.join(root, "port", "kz2", "ppu_lift_fixups-101.txt"), "end 0x1 0x2\n")
        c3 = fr.Ctx(root=root, build=c.build, dump=dump, update=update, eboot=eboot, facts=c.facts)
        check(fr.is_done(c3, *steps["load"]) and not fr.is_done(c3, *steps["ppu-lift"])
              and not fr.is_done(c3, *steps["compile"]), "7 lift change: load kept, lift + compile re-run")
        os.remove(os.path.join(root, "port", "kz2", "ppu_lift_fixups-101.txt"))
        write(os.path.join(root, "VERSION.txt"), "0.2.0")
        c4 = fr.Ctx(root=root, build=c.build, dump=dump, update=update, eboot=eboot, facts=c.facts)
        check(fr.is_done(c4, *steps["ppu-lift"]) and not fr.is_done(c4, *steps["compile"]),
              "7 version change: lift kept, compile re-runs")
        write(os.path.join(root, "VERSION.txt"), "0.1.0")
        write(os.path.join(root, "port", "kz2", "ppu_overrides.txt"), "a\n")
        check(la.decide(root)[0] == "run", "7 inputs restored -> run")

        # 8. main(): game start, build offers; the notice fonts go next to kz2.exe (KZ3 error notice)
        write(os.path.join(root, "fonts", "Rajdhani-Medium.ttf"), "medium")
        write(os.path.join(root, "fonts", "Rajdhani-Bold.ttf"), "bold")
        write(os.path.join(root, "fonts", "OFL.txt"), "licence")
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            return 0
        rc = la.main(["--root", root, "-x"], ui=FakeUI([]), run=run, environ=env)
        check(rc == 0 and calls and calls[0][0] == [os.path.join(root, "build", "kz2.exe"), eboot, "-x"]
              and calls[0][1]["cwd"] == root and calls[0][1]["env"]["PS3_VFS_ROOT"] == os.path.join(root, "vfs")
              and calls[0][1]["env"]["PATH"] == "/bin", f"8 run game {calls[:1]}")
        vl = os.path.join(root, "vfs", "PS3_GAME")
        check(la._is_dir_link(vl) and os.path.realpath(vl) == os.path.realpath(os.path.join(dump, "PS3_GAME"))
              and os.path.isfile(os.path.join(vl, "PARAM.SFO")), "8 vfs/PS3_GAME links to the dump's PS3_GAME")
        check(la.ensure_vfs(root, dump) == (os.path.join(root, "vfs"), "") and la._is_dir_link(vl),
              "8 vfs link kept on the next start")
        dump2 = os.path.join(tmp, "dump2")
        write(os.path.join(dump2, "PS3_GAME", "PARAM.SFO"), "two")
        check(la.ensure_vfs(root, dump2)[1] == "" and open(os.path.join(vl, "PARAM.SFO")).read() == "two"
              and os.path.isfile(os.path.join(dump, "PS3_GAME", "PARAM.SFO")),
              "8 a new dump relinks; the old dump's files stay")
        la.ensure_vfs(root, dump)
        os.unlink(vl)
        write(os.path.join(vl, "keep.txt"), "mine")
        v, err = la.ensure_vfs(root, dump2)
        check(err and os.path.isfile(os.path.join(vl, "keep.txt"))
              and os.path.isfile(os.path.join(dump2, "PS3_GAME", "PARAM.SFO")),
              f"8 a real PS3_GAME folder in vfs is never removed ({err})")
        os.remove(os.path.join(root, "vfs", "link.json"))
        v, err = la.ensure_vfs(root, dump)
        check("real folder" in err and os.path.isfile(os.path.join(vl, "keep.txt")),
              f"8 a real PS3_GAME folder in vfs is never removed ({err})")
        shutil.rmtree(vl)
        la.ensure_vfs(root, dump)
        check(os.path.isdir(os.path.join(root, "build", "cache", "edat")), "8 edat cache made")
        bf = os.path.join(root, "build", "fonts")
        check(sorted(os.listdir(bf)) == ["OFL.txt", "Rajdhani-Bold.ttf", "Rajdhani-Medium.ttf"]
              and open(os.path.join(bf, "Rajdhani-Bold.ttf")).read() == "bold", "8 notice fonts placed in build/fonts")
        check(open(os.path.join(bf, "OFL.txt")).read() == "licence", "8 OFL.txt placed beside the fonts")
        check(fr.place_fonts(root, os.path.join(root, "build")) == [], "8 fonts already in place: nothing copied")
        write(os.path.join(root, "fonts", "Rajdhani-Bold.ttf"), "bold v2")
        check(fr.place_fonts(root, os.path.join(root, "build")) == ["Rajdhani-Bold.ttf"], "8 a changed font is copied again")
        # SDL3.dll next to kz2.exe (patch 4010): placed from the payload, left alone when identical, replaced when changed
        sd = os.path.join(root, "runtime", "SDL3.dll")
        check(not fr.place_sdl3(root, os.path.join(root, "build")) and not os.path.exists(os.path.join(root, "build", "SDL3.dll")),
              "8 an old payload without runtime/SDL3.dll: nothing placed, no error")
        write(sd, "dll v1")
        check(fr.place_sdl3(root, os.path.join(root, "build")) is True
              and open(os.path.join(root, "build", "SDL3.dll")).read() == "dll v1", "8 SDL3.dll placed in build/")
        check(fr.place_sdl3(root, os.path.join(root, "build")) is False, "8 SDL3.dll already in place: not copied")
        write(sd, "dll v2")
        check(fr.place_sdl3(root, os.path.join(root, "build")) is True
              and open(os.path.join(root, "build", "SDL3.dll")).read() == "dll v2", "8 a changed SDL3.dll (same size) is copied again")
        # decoder DLLs: at3_standalone.dll from the build, FFmpeg's two from the payload's runtime/
        bd = os.path.join(root, "build")
        check(open(os.path.join(bd, "at3_standalone.dll")).read() == "at3", "8 at3_standalone.dll placed beside kz2.exe by the stamp")
        check(fr.place_decoders(root, bd) == [], "8 no FFmpeg DLLs in the payload: nothing placed, no error")
        write(os.path.join(root, "runtime", "avcodec-63.dll"), "av1")
        write(os.path.join(root, "runtime", "avutil-61.dll"), "ut1")
        check(sorted(fr.place_decoders(root, bd)) == ["avcodec-63.dll", "avutil-61.dll"]
              and open(os.path.join(bd, "avcodec-63.dll")).read() == "av1", "8 FFmpeg DLLs placed beside kz2.exe")
        check(fr.place_decoders(root, bd) == [], "8 FFmpeg DLLs already in place: not copied")
        write(os.path.join(root, "runtime", "avutil-61.dll"), "ut2")
        check(fr.place_decoders(root, bd) == ["avutil-61.dll"], "8 a changed FFmpeg DLL is copied again")
        os.remove(os.path.join(bd, "at3_standalone.dll"))
        a, why = la.decide(root)
        check(a == "resume" and "at3_standalone.dll" in why, f"8 a build without at3_standalone.dll resumes {a} {why}")
        write(os.path.join(bd, "at3_standalone.dll"), "at3")
        os.remove(os.path.join(root, "build", "build-stamp.json"))
        calls.clear()
        ui = FakeUI([False])
        rc = la.main(["--root", root], ui=ui, run=run, environ=env)
        check(rc == 0 and not calls and len(ui.asked) == 1 and "did not finish" in ui.asked[0], "8 No starts nothing")

        def run_build(argv, **kw):
            calls.append((argv, kw))
            if "--bar" in argv:
                stamp(c)
            return 0
        calls.clear()
        ui = FakeUI([True])
        rc = la.main(["--root", root], ui=ui, run=run_build, environ=env)
        check(rc == 0 and len(calls) == 2 and "--bar" in calls[0][0] and calls[1][0][0].endswith("kz2.exe"),
              f"8 Yes: build then game {[x[0][:3] for x in calls]} {ui.infos}")
        os.remove(os.path.join(root, "build", "build-stamp.json"))
        calls.clear()
        ui = FakeUI([True])
        rc = la.main(["--root", root], ui=ui, run=lambda argv, **kw: calls.append(argv) or 1, environ=env)
        check(rc == 1 and len(calls) == 1 and ui.infos and "did not finish" in ui.infos[0], "8 failed build stops")
        shutil.rmtree(os.path.join(root, "build"))
        calls.clear()
        rc = la.main(["--root", root], ui=FakeUI([True]), run=run, environ=env)
        check(rc == 1 and "--interactive" in calls[0][0] and "--portable" in calls[0][0],
              f"8 first build interactive portable, nothing built -> 1 ({rc})")

        # 9. version check
        c = record(root, dump, update, eboot)
        stamp(c)
        started = []
        day = datetime.date(2026, 10, 11)
        la.main(["--root", root], ui=FakeUI([]), run=run, start=lambda a, **k: started.append(a), today=day,
                environ=env)
        check(not started, "9 check_updates=0: no check")
        fr.write_install_ini(root, True, True)
        la.main(["--root", root], ui=FakeUI([]), run=run, start=lambda a, **k: started.append(a), today=day,
                environ=env)
        check(len(started) == 1 and "--current" in started[0] and "0.1.0" in started[0]
              and la.read_ini(root)["last_check"] == "2026-10-11", f"9 due check started {started}")
        la.main(["--root", root], ui=FakeUI([]), run=run, start=lambda a, **k: started.append(a), today=day,
                environ=env)
        check(len(started) == 1, "9 once a day")
        write(os.path.join(root, "logs", "version-check.txt"),
              "VERSION status=newer current=0.1.0 latest=v0.2.0 url=https://example.invalid/r setup=-\n")
        ui = FakeUI([False])
        la.main(["--root", root], ui=ui, run=run, today=day, environ=env)
        check(len(ui.asked) == 1 and "v0.2.0" in ui.asked[0] and la.read_ini(root)["dismissed"] == "v0.2.0",
              "9 newer asked, No remembered")
        ui = FakeUI([True])
        la.main(["--root", root], ui=ui, run=run, today=day, environ=env)
        check(not ui.asked, "9 dismissed version not asked again")
        write(os.path.join(root, "logs", "version-check.txt"),
              "VERSION status=newer current=0.1.0 latest=v0.3.0 url=https://example.invalid/r3 setup=-\n")
        ui = FakeUI([True])
        la.main(["--root", root], ui=ui, run=run, today=day, environ=env)
        check(ui.urls == [], f"9 a page outside the project's releases is never opened {ui.urls}")
        rel = la.RELEASES + "tag/v0.4.0"
        write(os.path.join(root, "logs", "version-check.txt"),
              f"VERSION status=newer current=0.1.0 latest=v0.4.0 url={rel} setup=-\n")
        ui = FakeUI([True])
        la.main(["--root", root], ui=ui, run=run, today=day, environ=env)
        check(ui.urls == [rel], f"9 Yes opens the page {ui.urls}")

        # 9b. "Update this installation": setup + .sha256 from the project's release downloads only, hash checked,
        # setup started with /DIR=<root> and no game; a bad hash or a foreign URL changes nothing and the game starts
        setup_bytes = b"MZ fake setup"
        good_sha = hashlib.sha256(setup_bytes).hexdigest()
        dl = la.DOWNLOADS + "v0.5.0/"
        served = {dl + "Project-Pyrrhus-setup.exe": setup_bytes,
                  dl + "Project-Pyrrhus-setup.exe.sha256": f"{good_sha}  Project-Pyrrhus-setup.exe\n".encode()}
        real_get = la._get
        la._get = lambda url, limit, timeout=60: served[url]
        try:
            line = (f"VERSION status=newer current=0.1.0 latest=v0.5.0 url={la.RELEASES}tag/v0.5.0 "
                    f"setup={dl}Project-Pyrrhus-setup.exe sha256={dl}Project-Pyrrhus-setup.exe.sha256\n")
            write(os.path.join(root, "logs", "version-check.txt"), line)
            ui, started, ran = FakeUI([True]), [], []
            rc = la.main(["--root", root], ui=ui, run=lambda a, **k: ran.append(a) or 0,
                         start=lambda a, **k: started.append(a), today=day, environ=env)
            check(rc == 0 and not ran and len(started) == 1 and started[0][1] == f"/DIR={root}"
                  and open(started[0][0], "rb").read() == setup_bytes and "Update this installation" in ui.asked[0],
                  f"9b Yes: checked setup started for this folder, no game {started}")
            served[dl + "Project-Pyrrhus-setup.exe"] = b"MZ tampered"
            ui, started, ran = FakeUI([True]), [], []
            rc = la.main(["--root", root], ui=ui, run=lambda a, **k: ran.append(a) or 0,
                         start=lambda a, **k: started.append(a), today=day, environ=env)
            check(not started and len(ran) == 1 and ui.infos and "does not match its published SHA-256" in ui.infos[0],
                  f"9b a bad hash: nothing started, the game runs {ui.infos}")
            other = la.DOWNLOADS.replace("/undecuple/", "/someone-else/") + "v0.5.0/Project-Pyrrhus-setup.exe"
            check(la.fetch_update(other, dl + "x.sha256", root)[1].endswith(
                  "is not one of the project's release downloads"), "9b another repository's download is refused")
            ui, started = FakeUI([False, False]), []
            la.main(["--root", root], ui=ui, run=lambda a, **k: 0, start=lambda a, **k: started.append(a), today=day,
                    environ=env)
            check(not started and len(ui.asked) == 2 and "release page" in ui.asked[1]
                  and la.read_ini(root)["dismissed"] == "v0.5.0", "9b No, No: page question, then remembered")
        finally:
            la._get = real_get

        # 10. --repair ("Verify and rebuild"): never reaches the game; checks, then firstrun --bar
        os.remove(os.path.join(root, "logs", "version-check.txt"))
        fr.write_install_ini(root, True, False)   # no background version check from here on (never a real request)
        calls = []

        def run_repair(argv, **kw):
            calls.append(argv)
            stamp(c)
            return 0
        ui = FakeUI([True])
        rc = la.main(["--root", root, "--repair"], ui=ui, run=run_repair, environ=env)
        check(rc == 0 and len(calls) == 1 and "--bar" in calls[0] and calls[0][calls[0].index("--dump") + 1] == dump
              and not any(x.endswith("kz2.exe") or x == "--repair" for x in calls[0])
              and ui.infos and "Verified" in ui.infos[-1], f"10 repair: firstrun --bar, no game {calls} {ui.infos}")
        calls.clear()
        ui = FakeUI([False])
        rc = la.main(["--root", root, "--repair"], ui=ui, run=run_repair, environ=env)
        check(rc == 0 and not calls and len(ui.asked) == 1 and "rebuild what changed" in ui.asked[0], "10 No = nothing")
        good = os.path.join(root, "VERSION.txt")
        with open(good, "rb") as f:
            gh = hashlib.sha256(f.read()).hexdigest()
        man = {"format": 1, "zip_only": ["run.cmd"],
               "files": [{"path": "VERSION.txt", "size": os.path.getsize(good), "sha256": gh},
                         {"path": "kz2-setup/release/gone.py", "size": 1, "sha256": "0" * 64},
                         {"path": "run.cmd", "size": 1, "sha256": "0" * 64}]}
        write(os.path.join(root, "manifest.json"), json.dumps(man))
        check(la.verify_install(root) == (2, ["kz2-setup/release/gone.py (missing)"]),
              "10 verify: one missing; the zip-only run.cmd absent from an install is fine and not counted")
        man["files"] = man["files"][:2]
        write(os.path.join(root, "manifest.json"), json.dumps(man))
        write(good, "0.1.9")
        check(la.verify_install(root)[1][0] == "VERSION.txt (changed)", "10 verify: one changed")
        ui = FakeUI([True])
        rc = la.main(["--root", root, "--repair"], ui=ui, run=run_repair, environ=env)
        check(rc == 1 and not calls and not ui.asked and "2 of the 2 files" in ui.infos[0], "10 damaged install stops")
        p = printed(root, environ=env, extra=["--repair"])
        check(len(p["repair"]["problems"]) == 2 and "--bar" in p["repair"]["build"], f"10 print {p.get('repair')}")
        write(good, "0.1.0")
        os.remove(os.path.join(root, "manifest.json"))
        fails = []
        rc = la.main(["--root", root, "--repair"], ui=FakeUI([True]), run=lambda a, **k: fails.append(a) or 1,
                     environ=env)
        check(rc == 1 and len(fails) == 1, "10 failed repair -> 1")
        # a console closed with its X before the first check wrote a log (adapted from Project Helghast v0.1.1)
        check("window was closed" in la.did_not_finish(0xC000013A, "The build did not finish")
              and "code" not in la.did_not_finish(0xC000013A - 2**32, "x")
              and "(code 1)" in la.did_not_finish(1, "The build did not finish"), "10 console closed: its own wording")
        nl = os.path.join(tmp, "lognote")
        os.makedirs(nl, exist_ok=True)
        check("No log was written yet" in la.log_note(nl) and nl not in la.log_note(nl),
              "10 no first-run log yet: the dialog says so, no path")
        open(os.path.join(nl, la.FIRSTRUN_LOG), "w").close()
        check(la.FIRSTRUN_LOG in la.log_note(nl) and "issues" in la.log_note(nl), "10 first-run log present: path and report line")
        ui = FakeUI([True])
        rc = la.main(["--root", root, "--repair"], ui=ui, run=lambda a, **k: 0xC000013A, environ=env)
        has_log = os.path.isfile(os.path.join(root, la.FIRSTRUN_LOG))
        check(rc == 0xC000013A and "window was closed" in ui.infos[-1]
              and (("No log was written yet" in ui.infos[-1]) != has_log), f"10 closed repair console: {ui.infos}")
        shutil.rmtree(os.path.join(root, "build"))
        calls.clear()
        ui = FakeUI([True])
        la.main(["--root", root, "--repair"], ui=ui, run=lambda a, **k: calls.append(a) or 0, environ=env)
        check(calls and "--interactive" in calls[0] and "not built" in ui.asked[0], "10 never built -> first build")

        # 11 (after Project Helghast PR #11): the dialog after a failed first run shows firstrun.py's
        # REASON lines from its status file (logs/firstrun-status.txt, passed with --status-file); a stale file is not used
        check(calls and calls[0][calls[0].index("--status-file") + 1] == os.path.join(root, la.FIRSTRUN_STATUS),
              f"11 the first-run command passes the status file {calls[:1]}")
        why = "this EBOOT is the disc's 1.01 one (16,381,928 bytes); this release needs the EBOOT of the 1.29 update"

        def failing(step, reasons):
            def run11(argv, **kw):
                sf = argv[argv.index("--status-file") + 1]
                os.makedirs(os.path.dirname(sf), exist_ok=True)
                with open(sf, "w", encoding="utf-8") as f:
                    f.write("LOG path=x\n" + f"RESULT ok=0 step={step} elapsed=1\n" +
                            "".join(f"REASON {r}\n" for r in reasons))
                return 1
            return run11
        ui = FakeUI([True])
        rc = la.main(["--root", root], ui=ui, run=failing("check", [why]), environ=env)
        check(rc == 1 and ui.infos and why in ui.infos[-1] and "asks again only for" in ui.infos[-1]
              and ui.infos[-1].index(why) < ui.infos[-1].index("log"), f"11 the reason in the dialog, before the log: {ui.infos}")
        ui = FakeUI([True])
        la.main(["--root", root], ui=ui, run=failing("quit", [why]), environ=env)
        check(ui.infos and ui.infos[-1].startswith("Your game files did not pass the check") and why in ui.infos[-1],
              f"11 quit at a failed check: its own first line {ui.infos}")
        ui = FakeUI([True])
        la.main(["--root", root], ui=ui, run=failing("compile", ['the step "Compiling" failed (exit 1): a.c:1: error: x']),
                environ=env)
        check(ui.infos and "error: x" in ui.infos[-1] and "asks again" not in ui.infos[-1],
              f"11 a compile failure: the reason, no ask-again line {ui.infos}")
        st = os.path.join(root, la.FIRSTRUN_STATUS)
        os.utime(st, (time.time() - 3600, time.time() - 3600))
        ui = FakeUI([True])
        la.main(["--root", root], ui=ui, run=lambda a, **k: 1, environ=env)
        check(ui.infos and "error: x" not in ui.infos[-1] and "(code 1)" in ui.infos[-1],
              f"11 control: an older status file is not shown {ui.infos}")
        link_tests(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_launch:", "FAIL" if FAILS else "PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
