#!/usr/bin/env python3
"""Host test for tools/release/vm_test.py (the Windows VM kit's steps): the parts that do not need Windows, on fake
trees with no game data: 02-verify (kit hashes, game file presence, dump fingerprint), 10-leftovers (user data versus
caches, the dump fingerprint), 08-readonly's deny (file creation on the install folder only, removed after, the launch
still run), the RESULT line and exit codes, a crash turned into a FAIL, a cp1252 console; an earlier change's steps
11-21 and 23 on a fake install (this tools/release, this Python with -I as the embeddable one) with synthetic game
files (headers, zeros, a sparse archive), the setup stood in by its log lines for 11 and 12, controls that fail, and
the run order (ORDER, COMMANDS.md, vm_kit.sh).

    python3 tools/release/test_vm_test.py
"""
import contextlib
import hashlib
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vm_test as vt  # noqa: E402

FAILS = []


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"\n     {str(detail)[:600]}"))
    if not cond:
        FAILS.append(what)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def step(base, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = vt.main([*args, "--base", base])
    return rc, buf.getvalue()


def make_base(tmp):
    base = os.path.join(tmp, "kz2")
    kit = os.path.join(base, "kit")
    write(os.path.join(kit, vt.SETUP), b"setup")
    write(os.path.join(kit, "vm_test.py"), b"script")
    with open(os.path.join(kit, "SHA256SUMS.txt"), "w") as f:
        for n in (vt.SETUP, "vm_test.py"):
            f.write(f"{hashlib.sha256(open(os.path.join(kit, n), 'rb').read()).hexdigest()}  {n}\n")
    dump, update, eboot = vt.game_paths(base)
    for p in (os.path.join(dump, "PS3_GAME", "PARAM.SFO"), os.path.join(dump, "PS3_GAME", "USRDIR", "data_ps3.psarc"),
              os.path.join(update, "PARAM.SFO"), os.path.join(update, "USRDIR", "EBOOT.BIN"),
              os.path.join(update, "USRDIR", "added_data_ps3.psarc"), eboot):
        write(p)
    os.makedirs(os.path.join(update, "USRDIR", "patch_data_ps3"))
    return base


def fake_install(tmp):
    """An install folder whose kz2-setup/release is this tools/release and whose toolchain python.exe runs this
    Python with -I (as the embeddable Python's ._pth: the script's folder is not on sys.path)."""
    inst = os.path.join(tmp, "inst-r30")
    os.makedirs(os.path.join(inst, "kz2-setup"))
    os.symlink(HERE, os.path.join(inst, "kz2-setup", "release"))
    py = vt.py_of(inst)
    os.makedirs(os.path.dirname(py))
    if os.name == "nt":
        # Windows cannot run a #!/bin/sh stand-in. CPython's own venv launcher runs this Python (home in the pyvenv.cfg
        # beside it); round30 sets PYTHONSAFEPATH=1 for what -I gives below: the script's folder is not on sys.path.
        home = os.path.dirname(sys._base_executable)
        launcher = os.path.join(home, "Lib", "venv", "scripts", "nt", "python.exe")
        if not os.path.isfile(launcher):
            return None
        shutil.copy2(launcher, py)
        with open(os.path.join(os.path.dirname(py), "pyvenv.cfg"), "w") as f:
            f.write(f"home = {home}\ninclude-system-site-packages = false\n")
    else:
        with open(py, "w") as f:
            f.write(f"#!/bin/sh\nexec '{sys.executable}' -I \"$@\"\n")
        os.chmod(py, 0o755)
    with open(os.path.join(inst, "kz2-install.ini"), "w") as f:
        f.write("[install]\nportable = 0\n\n[controls]\nlayout = original\n")
    return inst


def synthetic_game(base):
    """game\\dump (synthetic PARAM.SFO, a sparse 6.6 GB archive), game\\update (the 1.29 update's files) and the
    1.29-sized EBOOT.elf, all made of zeros and headers (no game data)."""
    dump, update, eboot = vt.game_paths(base)
    vt.write_sfo(os.path.join(dump, "PS3_GAME", "PARAM.SFO"), dict(vt.SYNTH_SFO))
    write(os.path.join(dump, "PS3_GAME", "USRDIR", "EBOOT.BIN"), b"SCE\0" + b"\0" * 60)
    with open(os.path.join(dump, "PS3_GAME", "USRDIR", "data_ps3.psarc"), "wb") as f:
        f.write(b"PSAR")
        f.truncate(6_998_576_922)
    vt.write_sfo(os.path.join(update, "PARAM.SFO"), {"APP_VER": "01.29", "CATEGORY": "GD", "TITLE": "Synthetic",
                                                     "TITLE_ID": "BCUS98116"})
    write(os.path.join(update, "USRDIR", "EBOOT.BIN"), b"SCE\0" + b"\0" * 60)
    write(os.path.join(update, "USRDIR", "added_data_ps3.psarc"), b"PSAR" + b"\0" * 60)
    os.makedirs(os.path.join(update, "USRDIR", "patch_data_ps3"), exist_ok=True)
    h = bytearray(64)
    h[:7] = b"\x7fELF\x02\x02\x01"
    h[18:20] = (0x15).to_bytes(2, "big")
    os.makedirs(os.path.dirname(eboot), exist_ok=True)
    with open(eboot, "wb") as f:
        f.write(bytes(h))
        f.truncate(16_455_144)


def round30(tmp):
    """Release an earlier change's steps 11-21 and 23 on a fake install with synthetic game files (22 needs Windows)."""
    base = os.path.join(tmp, "r30")
    os.makedirs(os.path.join(base, "kit"))
    for n in ("vm_test.py", "iso_fixture.py"):
        write(os.path.join(base, "kit", n), open(os.path.join(HERE, n), "rb").read())
    synthetic_game(base)
    inst = fake_install(tmp)
    if inst is None:
        print("SKIP steps 11-21 and 23 on a fake install: this Windows Python has no venv launcher "
              "(Lib/venv/scripts/nt/python.exe) to stand in for the bundled python.exe")
        return
    os.makedirs(os.path.join(base, "out"), exist_ok=True)
    with open(os.path.join(base, "out", "state.json"), "w") as f:
        vt.json.dump({"inst": inst}, f)
    ini0 = open(os.path.join(inst, "kz2-install.ini")).read()
    real = (vt.reg_install_dir, vt.drive_roots, vt.run)
    vt.reg_install_dir = lambda: ""
    env0 = {k: os.environ.get(k) for k in (*vt.ONEDRIVE_VARS, "PYTHONSAFEPATH")}
    for k in vt.ONEDRIVE_VARS:
        os.environ.pop(k, None)
    if os.name == "nt":
        os.environ["PYTHONSAFEPATH"] = "1"   # the venv launcher stand-in's -I (fake_install)
    try:
        for name in ("13-bundled-python", "15-empty-folder", "17-swapped", "18-disc-id", "19-iso", "20-eboot-101",
                     "21-ask-again", "23-uninstall-cover"):
            rc, text = step(base, name)
            check(rc == 0 and f"RESULT {name} PASS" in text, f"{name} passes on a fake install", text[-3000:])
            check(" NOT " not in text, f"{name}: every expectation met", [x for x in text.splitlines() if "NOT" in x])
        check(open(os.path.join(inst, "kz2-install.ini")).read() == ini0, "20 and 21 put kz2-install.ini back")
        check(os.path.isfile(os.path.join(inst, "game", "disc", "PS3_GAME", "PARAM.SFO")), "23 plants game\\disc")
        rc, text = step(base, "14-onedrive-check")
        check(rc == 0 and "RESULT 14-onedrive-check SKIP no OneDrive on this machine" in text and " NOT " not in text,
              "14 without OneDrive: the stand-in is refused, SKIP", text[-2000:])
        os.environ["OneDrive"] = os.path.join(tmp, "MyOneDrive")
        rc, text = step(base, "14-onedrive-check")
        check(rc == 0 and "RESULT 14-onedrive-check PASS" in text and "MyOneDrive" in text, "14 with OneDrive: PASS",
              text[-2000:])
        os.environ.pop("OneDrive")
        # 16 on a stand-in root folder (the host's / is never scanned); test_input_reasons covers real roots' text
        fake_root = os.path.join(tmp, "fake-root")
        os.makedirs(os.path.join(fake_root, "Windows"))
        vt.drive_roots = lambda a: [fake_root]
        rc, text = step(base, "16-drive-root")
        check(rc == 0 and "RESULT 16-drive-root PASS" in text, "16 names a root given as disc and as update", text[-2000:])
        # negative control: an install whose firstrun_check gives no reasons fails 15
        bad = os.path.join(tmp, "bad-release")
        os.makedirs(bad)
        with open(os.path.join(bad, "firstrun_check.py"), "w") as f:
            f.write("print('first-run checks: pass')\n")
        os.remove(os.path.join(inst, "kz2-setup", "release"))
        os.symlink(bad, os.path.join(inst, "kz2-setup", "release"))
        rc, text = step(base, "15-empty-folder")
        check(rc == 1 and "RESULT 15-empty-folder FAIL" in text, "control: 15 fails without the reason lines", text[-800:])
        os.remove(os.path.join(inst, "kz2-setup", "release"))
        os.symlink(HERE, os.path.join(inst, "kz2-setup", "release"))
        # 11 and 12 with the setup stood in by its log lines (exit 7 and the refusal text)
        def fake_setup(text_line, code, slog=None):
            def run(st_, argv, *x, **k):
                log = next(a[5:] for a in argv if a.startswith("/LOG="))
                write(log, text_line.encode())
                if slog:
                    with open(slog, "a") as f:
                        f.write("Silent install stopped: x: This is the disc's 1.01 EBOOT. ... USRDIR ...\n")
                return code, 0.1, ""
            return run
        vt.run = fake_setup("Log: install folder refused: The folder X is inside OneDrive, which syncs\n", 7)
        rc, text = step(base, "11-setup-onedrive")
        check(rc == 0 and "RESULT 11-setup-onedrive SKIP no OneDrive on this machine" in text, "11: stand-in refused, SKIP",
              text[-1500:])
        vt.run = fake_setup("", 0)
        rc, text = step(base, "11-setup-onedrive")
        check(rc == 1 and "RESULT 11-setup-onedrive FAIL" in text, "control: 11 fails when the setup installs", text[-800:])
        vt.run = fake_setup("", 7, os.path.join(base, "kit", vt.SETUP_LOG))
        rc, text = step(base, "12-setup-eboot101")
        check(rc == 0 and "RESULT 12-setup-eboot101 PASS" in text, "12: exit 7 with the 1.01 reason passes", text[-1500:])
        vt.run = fake_setup("", 0)
        rc, text = step(base, "12-setup-eboot101")
        check(rc == 1 and "RESULT 12-setup-eboot101 FAIL" in text, "control: 12 fails without the refusal", text[-800:])
        vt.reg_install_dir = lambda: inst
        rc, text = step(base, "11-setup-onedrive")
        check(rc == 0 and "SKIP an install is present" in text, "11 skips once installed (it runs before 03)", text[-500:])
    finally:
        vt.reg_install_dir, vt.drive_roots, vt.run = real
        for k, v in env0.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
    # 22's dialog pick: the failure dialog, not the first question (which also says "did not finish")
    q = "The last build did not finish.\n\nContinue the build now? Finished steps are skipped."
    f = "The build did not finish (code 1):\n\n- Disc dump failed: X"
    check(vt.failure_dialog([q, f]) == f and vt.failure_dialog([q]) == "", "22 judges the failure dialog, not the question")
    # the order the tester runs: every step once; vm_kit.sh's preflight reads it; COMMANDS.md follows it
    check(sorted(vt.ORDER) == sorted(vt.ALL_STEPS) and len(set(vt.ORDER)) == len(vt.ORDER),
          "ORDER holds every step once", vt.ORDER)
    check(vt.ORDER.index("11-setup-onedrive") < vt.ORDER.index("03-install") and
          vt.ORDER.index("22-launcher-dialog") < vt.ORDER.index("06-build") and
          vt.ORDER.index("23-uninstall-cover") == vt.ORDER.index("09-uninstall") - 1, "ORDER: refusals before the "
          "install, the dialog before the build, 23 just before the uninstall", vt.ORDER)
    cmds = open(os.path.join(HERE, "vm_kit", "COMMANDS.md"), encoding="utf-8").read()
    pos = [cmds.find(f"vm_test.py {n}") for n in vt.ORDER]
    check(all(p >= 0 for p in pos) and pos == sorted(pos), "COMMANDS.md runs every step in ORDER", pos)
    kit = open(os.path.join(HERE, "vm_kit.sh"), encoding="utf-8").read()
    check("vm_test.ORDER" in kit and "tools/release/iso_fixture.py" in kit, "vm_kit.sh: preflight order from ORDER, "
          "iso_fixture.py staged")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = make_base(tmp)
        out = os.path.join(base, "out")
        # 02-verify: the free-space floor is 6 GiB; the test filesystem may have less, so lower it via disk_usage
        real_du = vt.shutil.disk_usage
        vt.shutil.disk_usage = lambda p: real_du(p)._replace(free=100 * 2**30)
        try:
            rc, text = step(base, "02-verify")
            check(rc == 0 and "RESULT 02-verify PASS 2 kit files ok" in text, "02-verify passes on a full fake kit", text)
            check(os.path.isfile(os.path.join(out, "02-verify.txt")), "the step writes out\\02-verify.txt")
            st = vt.json.load(open(os.path.join(out, "state.json")))
            check(st.get("dump_fp", [0])[0] == 2, "the dump fingerprint counts the dump's files", st)
            write(os.path.join(base, "kit", "vm_test.py"), b"changed")
            os.remove(vt.game_paths(base)[2])
            rc, text = step(base, "02-verify")
            check(rc == 1 and "1 kit file(s) differ, 1 game file(s) missing" in text, "02-verify fails on a changed "
                  "kit file and a missing EBOOT", text)
            vt.shutil.disk_usage = lambda p: real_du(p)._replace(free=1 * 2**30)
            write(os.path.join(base, "kit", "vm_test.py"), b"script")
            write(vt.game_paths(base)[2])
            rc, text = step(base, "02-verify")
            check(rc == 1 and "GiB free" in text, "02-verify fails on too little disk", text)
        finally:
            vt.shutil.disk_usage = real_du

        # 10-leftovers: a fake APPDATA with saves and settings passes; a cache left behind fails; a changed dump fails
        appdata = os.path.join(tmp, "Roaming")
        os.environ.update(APPDATA=appdata, LOCALAPPDATA=os.path.join(tmp, "Local"), USERPROFILE=tmp)
        data = os.path.join(appdata, vt.APP)
        write(os.path.join(data, "gamedata", "BCUS98116-SAVE", "SYS-DATA"))
        write(os.path.join(data, "keybinds.ini"))
        st["dump_fp"] = vt.fingerprint(vt.game_paths(base)[0])
        st.pop("inst", None)
        vt.json.dump(st, open(os.path.join(out, "state.json"), "w"))
        real_reg = vt.reg_install_dir
        vt.reg_install_dir = lambda: ""   # never the uninstall key of a Project Pyrrhus installed on the test machine
        rc, text = step(base, "10-leftovers")
        check(rc == 0 and "only user data left" in text, "10-leftovers passes with saves and .ini only", text)
        write(os.path.join(data, "scratch", "rsx_shader_cache_v3", "a.bin"))
        write(os.path.join(tmp, "Local", "Programs", vt.APP, "build", "kz2.exe"))
        rc, text = step(base, "10-leftovers")
        check(rc == 1 and "not user data left in the data folder: scratch" in text and "install folder not empty" in text,
              "10-leftovers names a cache and an install folder left behind", text)
        write(os.path.join(vt.game_paths(base)[0], "PS3_GAME", "NEW.TXT"))
        rc, text = step(base, "10-leftovers")
        check(rc == 1 and "the dump changed" in text, "10-leftovers notices a changed dump", text)
        vt.reg_install_dir = real_reg

        # 08-readonly: icacls denies only "create files" on the install folder itself (no (OI)/(CI) inheritance, no
        # write or delete rights), the launch still runs, and the deny is removed even when the launch raises
        inst = os.path.join(tmp, "inst")
        os.makedirs(os.path.join(inst, "logs"))
        st = vt.json.load(open(os.path.join(out, "state.json")))
        st["inst"] = inst
        vt.json.dump(st, open(os.path.join(out, "state.json"), "w"))
        calls, launched = [], []
        real = (vt.shutil.which, vt.run, vt.launch_once, vt.reg_install_dir)
        vt.shutil.which = lambda n: "icacls" if n == "icacls" else real[0](n)
        vt.run = lambda st_, argv, *x, **k: (calls.append(list(argv)), (0, 0.0, ""))[1]
        vt.reg_install_dir = lambda: ""
        os.environ["USERNAME"] = "tester"
        try:
            vt.launch_once = lambda st_, i, w, tag: (launched.append((i, tag)), (True, 0))[1]
            rc, text = step(base, "08-readonly")
            deny = [c for c in calls if "/deny" in c]
            check(rc == 0 and "RESULT 08-readonly PASS" in text, "08-readonly passes when kz2.exe starts", text)
            check(deny == [["icacls", inst, "/deny", "tester:(WD)"]], "08 denies only file creation, not inherited", calls)
            check(not any(x in str(deny) for x in ("(OI)", "(CI)", "W,", "(W)", ",D")), "08's deny has no write, delete "
                  "or inheritance flags", deny)
            check(launched == [(inst, "08")], "08 still runs the launch", launched)
            check(calls[-1] == ["icacls", inst, "/remove:d", "tester"], "08 removes the deny after the launch", calls)
            calls.clear()
            vt.launch_once = lambda *x: (False, 1)
            rc, text = step(base, "08-readonly")
            check(rc == 1 and "RESULT 08-readonly FAIL" in text, "08 fails when kz2.exe does not start", text)
            calls.clear()
            vt.launch_once = lambda *x: 1 / 0
            rc, text = step(base, "08-readonly")
            check(rc == 1 and calls and calls[-1][2] == "/remove:d", "08 removes the deny when the launch crashes", calls)
        finally:
            vt.shutil.which, vt.run, vt.launch_once, vt.reg_install_dir = real

        round30(tmp)

        # A cp1252 console (cmd.exe over ssh) cannot encode U+FFFD: after safe_console() printing it does not raise
        real_out = sys.stdout
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        try:
            vt.safe_console()
            print("tool output with \ufffd and \u2192")
            sys.stdout.flush()
            ok = True
        except UnicodeEncodeError:
            ok = False
        finally:
            sys.stdout = real_out
        check(ok, "a cp1252 console gets U+FFFD without a UnicodeEncodeError")

        # A crash is a FAIL with its reason
        real = vt.FUNCS["05-checks"]
        vt.FUNCS["05-checks"] = lambda st, a: 1 / 0
        try:
            rc, text = step(base, "05-checks")
        finally:
            vt.FUNCS["05-checks"] = real
        check(rc == 1 and "RESULT 05-checks FAIL vm_test crashed: ZeroDivisionError" in text, "a crash ends in FAIL", text)
    print(f"\n{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
