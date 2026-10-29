#!/usr/bin/env python3
"""Host test for tools/release/rpcs3_import.py ("Use my RPCS3 install"; the wizard's Python side, firstrun's text UI)
on fake RPCS3 trees (no game data, no RPCS3). Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_rpcs3_import.py

Cases: the detected root and the paths found (update USRDIR EBOOT first); a disc outside the chosen folder needs a yes
and nothing there is opened before it; a missing update; no decrypted EBOOT (a plain notice, no how-to
instructions, check again); a wrong update version; the save import dry run (counts only), the copy only on a yes,
refusal of an existing save until a second yes; redacted log lines (<RPCS3>/..., <home>/...) and no save contents in
them; the wizard command line (--detect/--resolve/--save-dryrun/--save-copy); firstrun's text UI end to end.
"""
import builtins
import io
import os
import struct
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402
import rpcs3_import as ri  # noqa: E402
import rpcs3_locate as L  # noqa: E402

FAILS = []
T = "BCUS98116"
ELF = b"\x7fELF"


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("FAIL", what)


def sfo(**kv):
    keys, data, ents = b"", b"", b""
    for k, v in kv.items():
        raw = v.encode() + b"\0"
        mx = max(len(raw), 8)
        ents += struct.pack("<HHIII", len(keys), 0x0204, len(raw), mx, len(data))
        keys += k.encode() + b"\0"
        data += raw.ljust(mx, b"\0")
    kt = 20 + len(ents)
    return b"\0PSF" + struct.pack("<IIII", 0x101, kt, kt + len(keys), len(kv)) + ents + keys + data


def w(path, content=b"x"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


def tree(tmp, name="rpcs3", disc_inside=False, update="01.29", elf=True, disc=True):
    root = Path(tmp) / name
    d = root / "games" / "KZ2" if disc_inside else Path(tmp) / "discs" / "KZ2"
    if disc:
        w(d / "PS3_GAME" / "PARAM.SFO", sfo(TITLE_ID=T, VERSION="01.01", APP_VER="01.01"))
        w(d / "PS3_GAME" / "USRDIR" / "EBOOT.elf", ELF+b"disc")
    w(root / "config" / "games.yml", f"{T}: {d}/\n")
    w(root / "config" / "vfs.yml", "/dev_hdd0/: $(EmulatorDir)dev_hdd0/\n/dev_flash/: $(EmulatorDir)dev_flash/\n")
    w(root / "rpcs3.exe")
    g = root / "dev_hdd0" / "game" / T
    if update:
        w(g / "PARAM.SFO", sfo(TITLE_ID=T, APP_VER=update, CATEGORY="GD"))
        w(g / "USRDIR" / "EBOOT.BIN", b"bin")
        if elf:
            w(g / "USRDIR" / "EBOOT.elf", ELF+b"update")
    return root, d


def add_save(root, name="BCUS98116-DATA", files=None):
    p = root / "dev_hdd0" / "home" / "00000001" / "savedata" / name
    for rel, body in (files or {"PARAM.SFO": sfo(TITLE_ID=T), "PROFILE.DAT": b"p" * 100, "SECTION.DAT": b"s" * 50}).items():
        w(p / rel, body)
    return p


def codes(res):
    return [p["code"] for p in res["problems"]]


def main():
    tmp0 = tempfile.mkdtemp(prefix="kz2-rpcs3-test-")
    tmp = os.path.realpath(tmp0)
    home = Path(tmp) / "home"
    patches = [mock.patch.object(L.Path, "home", return_value=home),
               # never the real Documents/Desktop/Downloads or drive roots of the machine running the test
               mock.patch.object(L, "_user_folders", return_value=[], create=True),
               mock.patch.object(L, "_fixed_drives", return_value=[], create=True),
               mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "", "WINEHOMEDIR": "", "USERPROFILE": str(home)})]
    for p in patches:
        p.start()
    try:
        # --- detect: a hint, and the known place under the (fake) home. Linux's known places on any host, so the
        # machine's own %APPDATA%/%LOCALAPPDATA% RPCS3 is never seen and ~/.config/rpcs3 is looked at on Windows too.
        root, disc = tree(tmp)
        with mock.patch.object(L, "_is_windows", return_value=False):
            c = ri.detect(str(root))
            check(c and c[0]["root"] == str(root) and c[0]["source"] == "hint", f"detect hint {c[:1]}")
            check(ri.detect(str(Path(tmp) / "nowhere")) == [], "detect: a bad hint gives nothing")
            homerpcs, _ = tree(tmp, name="home/.config/rpcs3")
            c = ri.detect()
            check(c and c[0]["source"] == "linux-config" and c[0]["root"] == str(homerpcs), f"detect known place {c[:1]}")

        # --- Windows: a portable RPCS3 in Documents/Desktop/Downloads or at a drive root (Windows faked on any host)
        win = Path(tmp) / "win"
        docs, dl, drive = win / "Docs", win / "Downloads", win / "D"
        for d in (docs, dl, drive):
            d.mkdir(parents=True)
        wpatches = [mock.patch.object(L, "_is_windows", return_value=True),
                    mock.patch.object(L, "_user_folders", return_value=[(str(docs), "windows-documents"),
                                                                        (str(dl), "windows-downloads")], create=True),
                    mock.patch.object(L, "_fixed_drives", return_value=[str(drive)], create=True),
                    mock.patch.dict(os.environ, {"LOCALAPPDATA": str(win / "Local"), "APPDATA": str(win / "Roaming")})]
        for p in wpatches:
            p.start()
        try:
            check(ri.detect() == [], "windows: nothing in the known places gives nothing")
            (dl / "RPCS3" / "screenshots").mkdir(parents=True)  # a folder named RPCS3 that is not RPCS3
            check(ri.detect() == [], "windows: an RPCS3 folder without rpcs3.exe/vfs.yml/games.yml is skipped")
            droot, _ = tree(str(drive), name="RPCS3")
            c = ri.detect()
            check([(x["source"], x["root"]) for x in c] == [("windows-drive-root", str(droot))],
                  f"windows: portable RPCS3 at a drive root {c}")
            droot2, _ = tree(str(docs), name="RPCS3")
            c = ri.detect()
            check([x["source"] for x in c] == ["windows-documents", "windows-drive-root"] and c[0]["root"] == str(droot2),
                  f"windows: Documents before the drive root {c}")
            lroot, _ = tree(str(win / "Local"), name="Programs/rpcs3")
            c = ri.detect()
            check(c and c[0]["source"] == "windows-localappdata" and c[0]["root"] == str(lroot),
                  f"windows: the installer's place stays first {c[:1]}")
            r = ri.resolve(str(droot), allow_outside=True)
            check(r["ok"] and r["eboot"] == str(droot / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf"),
                  f"windows: the drive-root RPCS3 resolves ({r['status']})")
        finally:
            for p in reversed(wpatches):
                p.stop()

        # --- a disc outside the chosen folder: asked first, nothing there opened before the yes
        opened = []
        real_open = builtins.open

        def spy(f, *a, **k):
            opened.append(str(f))
            return real_open(f, *a, **k)
        with mock.patch.object(builtins, "open", spy):
            r = ri.resolve(str(root))
        check(r["status"] == "approval" and r["outside"] == [str(disc)], f"outside needs approval {r['status']} {r['outside']}")
        check(not any(o.startswith(str(disc)) for o in opened), "nothing opened in the disc folder before the yes")
        check(not r["dump"] and not r["ok"], "no paths handed out before the yes")
        r = ri.resolve(str(root), allow_outside=True)
        check(r["ok"] and r["status"] == "ok", f"all found {r['status']} {codes(r)}")
        check(r["dump"] == str(disc), "dump = the disc folder (holds PS3_GAME)")
        check(r["update"] == str(root / "dev_hdd0" / "game" / T), "update = dev_hdd0/game/BCUS98116")
        check(r["eboot"] == str(root / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf"), "EBOOT.elf from the update USRDIR first")

        # --- everything inside the chosen folder: no question
        root2, disc2 = tree(tmp, "inside", disc_inside=True)
        r = ri.resolve(str(root2))
        check(r["ok"] and r["outside"] == [], f"inside the folder: no approval ({r['status']})")

        # --- missing update
        root3, _ = tree(tmp, "noupd", disc_inside=True, update=None)
        r = ri.resolve(str(root3))
        check("missing_update" in codes(r) and not r["update"] and not r["eboot"] and not r["ok"], f"missing update {codes(r)}")
        check(ri.HELP_UPDATE in r["help"], "missing update: the help is shown")
        check("wrong_version" not in codes(r) and ri.HELP_VERSION not in r["help"],
             f"no update: only the missing-update problem, not also wrong_version ({codes(r)})")
        sw = ri.soft_wrap("no update folder /data/x/Projects/some-long-folder/work/release/wizard/fx/nothing is here")
        check(ri.BREAK in sw and all(len(x.split(" ")[-1]) <= 40 for x in sw.split(ri.BREAK)) and sw.replace(ri.BREAK, "").startswith("no update folder /data/x/"),
              "soft_wrap breaks long paths after a separator and loses no text")
        check(ri.soft_wrap("short words only") == "short words only", "soft_wrap leaves short text alone")

        # --- no decrypted EBOOT: a plain notice, no decryption how-to
        root4, _ = tree(tmp, "noelf", disc_inside=True, elf=False)
        r = ri.resolve(str(root4))
        check(codes(r) == ["no_decrypted_eboot"] and not r["eboot"] and r["update"], f"no EBOOT.elf {codes(r)}")
        check(r["help"] == [ri.HELP_DECRYPT] and "cannot decrypt it" in r["help"][0]
              and "made from your own copy" in r["help"][0] and "EBOOT.elf" in r["help"][0], "decrypt notice")
        check(not any(x in ri.HELP_DECRYPT.lower() for x in ("key", "http", "www")), "instructions carry no keys or links")
        # an encrypted SELF named EBOOT.elf is not offered; the player is told the port needs a decrypted one
        w(root4 / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf", b"SCE\x00rest")
        r = ri.resolve(str(root4))
        check(not r["eboot"] and "encrypted_eboot" in codes(r) and ri.HELP_ENCRYPTED in r["help"], f"encrypted EBOOT {codes(r)}")
        check(ri.encrypted_eboot(str(root4 / "dev_hdd0/game" / T / "USRDIR/EBOOT.BIN")) is False
              and ri.encrypted_eboot("") is False, "eboot_kind: unknown is not called encrypted")
        # the wizard's manual EBOOT page: --eboot-kind gives the same answer and the same text
        outf = os.path.join(tmp, "kind.txt")
        rc = ri.main(["--eboot-kind", str(root4 / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf"), "--out", outf])
        txt = open(outf, encoding="utf-8-sig").read()
        check(rc == 1 and "status=encrypted" in txt and "help=" + ri.HELP_ENCRYPTED in txt, "--eboot-kind: encrypted")
        w(root4 / "plain.elf", ELF + b"x")
        rc = ri.main(["--eboot-kind", str(root4 / "plain.elf"), "--out", outf])
        check(rc == 0 and open(outf, encoding="utf-8-sig").read().startswith("status=ok"), "--eboot-kind: real ELF is ok")
        os.remove(root4 / "plain.elf")
        os.remove(root4 / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf")
        # the disc's own (1.01) EBOOT.elf is not offered for the 1.29 build
        check(not r["eboot"], "the disc's EBOOT.elf is not used")
        w(root4 / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf", ELF+b"now")
        r = ri.resolve(str(root4))
        check(r["ok"], "check again after decrypting finds it")

        # --- wrong version
        root5, _ = tree(tmp, "oldupd", disc_inside=True, update="01.00")
        r = ri.resolve(str(root5))
        check("wrong_version" in codes(r) and not r["update"] and not r["eboot"] and not r["ok"], f"wrong version {codes(r)}")
        check(ri.HELP_VERSION in r["help"], "wrong version: help")
        for h in (ri.HELP_UPDATE, ri.HELP_VERSION):   # RPCS3 has no per-game "Check for updates": only what exists
            check("install the update in rpcs3 (see its documentation)" in h.lower() and "File >" not in h
                  and "Check for updates" not in h, "update help points to RPCS3's documentation, no menu path")
        check("add the game in rpcs3 (see its documentation)" in ri.HELP_DISC.lower() and "File >" not in ri.HELP_DISC,
              "disc help points to RPCS3's documentation, no menu path")

        # --- not an RPCS3 folder, missing disc
        r = ri.resolve(os.path.join(tmp, "discs"))
        check(r["status"] == "not_found" and codes(r) == ["not_rpcs3"], f"not rpcs3 {r['status']}")
        root6, _ = tree(tmp, "nodisc", disc_inside=True, disc=False)
        r = ri.resolve(str(root6), True)
        check("missing_disc" in codes(r) and ri.HELP_DISC in r["help"], f"missing disc {codes(r)}")

        # --- redacted log lines
        lines = ri.log_lines(ri.resolve(str(root2)))
        txt = "\n".join(lines)
        check("<RPCS3>/dev_hdd0/game/BCUS98116" in txt and str(root2) not in txt, f"log redacts the RPCS3 root: {txt[:200]}")
        w(Path(home) / "Games" / "a.txt")
        res = ri.resolve(str(root), True)
        res["dump"] = str(home / "Games" / "KZ2")
        txt = "\n".join(ri.log_lines(res))
        check("<home>/Games/KZ2" in txt and str(home) not in txt, "log redacts the home folder")

        red = fr.redactor([str(root2)])
        check(red(f"{root2}/dev_hdd0 and {home}/x") == "<RPCS3>/dev_hdd0 and %USERPROFILE%/x", "firstrun log redactor: <RPCS3>")
        check(fr.redactor()(f"{root2}/x") != "" and "<RPCS3>" not in fr.redactor()(f"{root2}/x"), "no RPCS3 root, no label")

        # --- saves: dry run, copy on yes, refusal of an existing save
        sp = add_save(root2)
        res = ri.resolve(str(root2))
        data = Path(tmp) / "install"
        plan = ri.save_dryrun(res, str(data))
        check(len(plan) == 1 and plan[0]["files"] == 3 and plan[0]["size"] == len(sfo(TITLE_ID=T)) + 150
              and not plan[0]["exists"], f"dry run {plan}")
        check(not data.exists(), "the dry run wrote nothing")
        text = "\n".join(ri.dryrun_text(plan))
        check("3 files" in text and "PROFILE.DAT" not in text and "BCUS98116-DATA" in text, f"dry run text: counts only: {text}")
        dst = Path(ri.save_dst(str(data), "BCUS98116-DATA"))
        check(str(dst).endswith(os.path.join("gamedata", "dev_hdd0", "home", "00000001", "savedata", "BCUS98116-DATA")),
              "destination is the port's cellSaveData folder")
        r = ri.save_copy(plan)
        check(r[0]["status"] == "copied" and r[0]["copied"] == 3 and (dst / "PROFILE.DAT").read_bytes() == b"p" * 100,
              f"copied {r}")
        check((sp / "PROFILE.DAT").read_bytes() == b"p" * 100, "RPCS3's own save untouched")
        (dst / "PROFILE.DAT").write_bytes(b"MINE")
        (dst / "extra.dat").write_bytes(b"only-mine")
        plan = ri.save_dryrun(res, str(data))
        check(plan[0]["exists"] and plan[0]["replaces"] == 3 - 0 and plan[0]["stale"] == 1, f"existing: replaces/stale {plan}")
        r = ri.save_copy(plan)
        check(r[0]["status"] == "exists" and (dst / "PROFILE.DAT").read_bytes() == b"MINE", f"existing save refused {r}")
        r = ri.save_copy(plan, overwrite=True)
        check(r[0]["status"] == "copied" and (dst / "PROFILE.DAT").read_bytes() == b"p" * 100
              and (dst / "extra.dat").exists(), "second yes replaces, deletes nothing")
        line = ri.save_log_line(r)
        check("PROFILE" not in line and "BCUS98116" not in line and "copied" in line, f"save log line counts only: {line}")
        # a data folder inside RPCS3 is refused by copy_save itself
        bad = ri.save_dryrun(res, str(root2 / "dev_hdd0"))
        check(ri.save_copy(bad)[0]["status"] == "failed", "destination inside RPCS3 refused")
        # no save in this RPCS3: nothing to offer
        check(ri.save_dryrun(ri.resolve(str(root5)), str(data)) == [], "no save: nothing to offer")

        # an RPCS3 user other than 00000001 still lands in user 00000001 of our install
        root7, _ = tree(tmp, "user2", disc_inside=True)
        w(root7 / "dev_hdd0/home/00000002/savedata/BCUS98116-DATA/PROFILE.DAT", b"u2")
        p7 = ri.save_dryrun(ri.resolve(str(root7)), str(data))
        check(len(p7) == 1 and os.path.join("home", "00000001", "savedata") in p7[0]["dst"], f"user 00000002 -> 00000001 {p7}")

        # --- the wizard command line
        out = os.path.join(tmp, "o.txt")
        rc = ri.main(["--detect", "--rpcs3", str(root2), "--out", out])
        kv = dict(l.split("=", 1) for l in open(out, encoding="utf-8-sig").read().splitlines())
        check(rc == 0 and kv["status"] == "ok" and kv["root"] == str(root2), f"--detect {kv}")
        check(open(out, "rb").read(3) == b"\xef\xbb\xbf", "output has a BOM (Inno)")
        rc = ri.main(["--resolve", "--rpcs3", str(root), "--out", out])
        kv = open(out, encoding="utf-8-sig").read()
        check(rc == 1 and "status=approval" in kv and f"outside={disc}" in kv and "dump=" in kv, f"--resolve approval: {kv}")
        rc = ri.main(["--resolve", "--rpcs3", str(root), "--allow-outside", "--out", out])
        kv = dict(l.split("=", 1) for l in open(out, encoding="utf-8-sig").read().splitlines())
        check(rc == 0 and kv["status"] == "ok" and kv["eboot"].endswith("EBOOT.elf"), f"--resolve ok {kv}")
        rc = ri.main(["--resolve", "--rpcs3", str(root4.parent / "noelf2"), "--out", out])
        check(rc == 1 and "problem=not_rpcs3|" in open(out, encoding="utf-8-sig").read(), "--resolve bad folder")
        rc = ri.main(["--resolve", "--rpcs3", str(root5), "--out", out])
        t = open(out, encoding="utf-8-sig").read()
        check(rc == 1 and "problem=wrong_version|" in t and "help=" in t and str(root5) not in t.split("problem=")[1],
              "--resolve wrong version: problem text redacted")
        data2 = Path(tmp) / "install2"
        rc = ri.main(["--save-dryrun", "--rpcs3", str(root2), "--data-dir", str(data2), "--out", out])
        t = open(out, encoding="utf-8-sig").read()
        check(rc == 0 and "status=ok" in t and "exists=0" in t and "3 files" in t and not data2.exists(), f"--save-dryrun {t}")
        rc = ri.main(["--save-copy", "--rpcs3", str(root2), "--data-dir", str(data2), "--out", out])
        check(rc == 0 and "status=copied" in open(out, encoding="utf-8-sig").read(), "--save-copy")
        rc = ri.main(["--save-copy", "--rpcs3", str(root2), "--data-dir", str(data2), "--out", out])
        check(rc == 1 and "status=exists" in open(out, encoding="utf-8-sig").read(), "--save-copy refuses an existing save")
        rc = ri.main(["--save-copy", "--overwrite", "--rpcs3", str(root2), "--data-dir", str(data2), "--out", out])
        check(rc == 0, "--save-copy --overwrite (the second yes)")

        # --- firstrun's text UI
        class A:
            dump = update = eboot = ""
            rpcs3 = str(root)
            build = None
            portable = True

        def script(answers):
            it = iter(answers)
            asked = []

            def ask(q):
                asked.append(q)
                return next(it)
            return ask, asked
        notes, buf = [], io.StringIO()
        ask, asked = script(["", ""])   # use the detected folder; yes to the folder outside it
        a = A()
        got = fr.rpcs3_step(a, ask, lambda *t: print(*t, file=buf), notes)
        check(got == (str(disc), str(root / "dev_hdd0/game" / T), str(root / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf")),
              f"rpcs3_step returns the three paths {got}")
        check(any("Found RPCS3 at" in q for q in asked) and any("Read it there too" in q for q in asked), "both questions asked")
        check(a.rpcs3_root == str(root) and any("# rpcs3 import: root=<RPCS3>" in n for n in notes), "root kept; notes redacted")
        ask, _ = script(["", "n"])
        a = A()
        check(fr.rpcs3_step(a, ask, lambda *t: None, notes := []) is None and any("declined" in n for n in notes),
              "declining the outside folder falls back to picking folders")
        ask, _ = script(["n", ""])   # not the detected one, no folder typed: pick them myself
        check(fr.rpcs3_step(A(), ask, lambda *t: None, []) is None, "Enter = pick the folders myself")
        # no decrypted EBOOT: instructions, then check again finds it
        a = A()
        a.rpcs3 = str(root4)
        os.remove(root4 / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf")
        buf = io.StringIO()
        n = {"i": 0}

        def ask2(q):
            n["i"] += 1
            if q.startswith("Enter = check again"):
                w(root4 / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf", ELF)
                return ""
            return ""
        got = fr.rpcs3_step(a, ask2, lambda *t: print(*t, file=buf), [])
        check(ri.HELP_DECRYPT in buf.getvalue() and got and got[2].endswith("EBOOT.elf"), "UI: instructions, check again finds it")
        a.rpcs3 = str(root3)
        ask, _ = script(["", "q"])
        check(fr.rpcs3_step(a, ask, lambda *t: None, []) is False, "q quits")

        # interactive(): the three prompts are skipped; the real check still runs (fake check here)
        a = A()
        a.rpcs3 = str(root2)
        a.build = os.path.join(tmp, "bld")
        seen = {}

        def fake_check(d, u, e, *target):
            seen["args"] = (d, u, e)
            return 0, "PASS fake\n"
        answers = iter(["", "n", "n", "", "", "n"])   # RPCS3 yes; version check no; modern no; prompts auto; display default (borderless); build no
        out = io.StringIO()
        notes = []
        os.makedirs(os.path.join(tmp, "iroot"))
        ok = fr.interactive(a, os.path.join(tmp, "iroot"), os.path.join(tmp, "l.log"), notes, ask=lambda q: next(answers),
                            out=out, check=fake_check, vcheck=lambda c: {})
        check(seen.get("args") == (str(disc2), str(root2 / "dev_hdd0/game" / T), str(root2 / "dev_hdd0/game" / T / "USRDIR/EBOOT.elf"))
              and ok is False, f"interactive uses RPCS3's paths and runs the check: {seen}")
        check("Disc dump folder" not in out.getvalue(), "interactive: no folder prompts when RPCS3 filled them")
        check(not hasattr(fr, "RPCS3_UPDATE_GUESSES"), "the old guess of RPCS3's folders is gone")

        # input that ends while a FAIL is left (a closed console, a script out of answers): interactive() returns
        # False with the FAIL lines, never asks again for ever (from Project Helghast PR #17; an alarm guards the
        # old behaviour)
        import signal
        import time

        def fail_check(d, u, e, *target):
            return 1, "FAIL U3 synthetic: the update's data archive is missing\n"
        for ending in (EOFError, StopIteration):
            a = A()
            a.rpcs3 = str(root2)
            a.build = os.path.join(tmp, "bld5b")
            first = iter(["", "n", "n", ""])
            left = {"n": 0, "fix": 0}

            def ask5b(q, ending=ending, first=first, left=left):
                left["n"] += 1
                if q.startswith("Fix the FAIL lines"):
                    left["fix"] += 1
                    raise ending
                if left["n"] > 40:
                    raise RuntimeError("asked more than 40 questions")
                return next(first, "")
            out = io.StringIO()
            notes5b = []
            r5b = os.path.join(tmp, "r5b" + ending.__name__)
            os.makedirs(r5b)
            if hasattr(signal, "SIGALRM"):
                signal.signal(signal.SIGALRM, lambda *x: (_ for _ in ()).throw(TimeoutError("interactive() spun")))
                signal.alarm(10)
            t0 = time.time()
            try:
                go5b = fr.interactive(a, r5b, os.path.join(tmp, "l5b.log"), notes5b, ask=ask5b, out=out,
                                      check=fail_check, vcheck=lambda c: {})
            except BaseException as ex:      # noqa: BLE001 (the old code let the ending escape)
                go5b = ex
            finally:
                if hasattr(signal, "SIGALRM"):
                    signal.alarm(0)
            check(go5b is False and "FAIL U3" in out.getvalue() and "No more input: stopping with the FAIL lines above."
                  in out.getvalue() and left["fix"] == 1 and time.time() - t0 < 5 and
                  "# interactive check stopped: input ended" in notes5b,
                  f"input ends ({ending.__name__}) while a FAIL is left: returns False with the FAIL lines "
                  f"({go5b!r}, {left})")
            check("wrong" in fr.ini_paths(r5b), f"{ending.__name__}: the failed input is asked again next start "
                  f"({fr.ini_paths(r5b)})")

        # save offer after the setup
        a.rpcs3_saves = ri.resolve(str(root2))
        d3 = Path(tmp) / "inst3"
        out = io.StringIO()
        lines = fr.offer_save_import(a, str(d3), lambda q: "n", out)
        check(not d3.exists() and "Import your RPCS3 save for Killzone 2?" in out.getvalue() and "3 files" in out.getvalue()
              and "no" in lines[0], "save offer: dry run shown, no = nothing copied")
        lines = fr.offer_save_import(a, str(d3), lambda q: "y", io.StringIO())
        check((d3 / "gamedata/dev_hdd0/home/00000001/savedata/BCUS98116-DATA/SECTION.DAT").is_file() and "copied" in lines[0],
              "save offer: yes copies")
        (d3 / "gamedata/dev_hdd0/home/00000001/savedata/BCUS98116-DATA/PROFILE.DAT").write_bytes(b"MINE")
        ans = iter(["y", "n"])   # import yes; replace no
        out = io.StringIO()
        lines = fr.offer_save_import(a, str(d3), lambda q: next(ans), out)
        check((d3 / "gamedata/dev_hdd0/home/00000001/savedata/BCUS98116-DATA/PROFILE.DAT").read_bytes() == b"MINE"
              and "kept yours" in out.getvalue() and "exists" in lines[0], "existing save kept unless the second yes")
        ans = iter(["y", "y"])
        fr.offer_save_import(a, str(d3), lambda q: next(ans), io.StringIO())
        check((d3 / "gamedata/dev_hdd0/home/00000001/savedata/BCUS98116-DATA/PROFILE.DAT").read_bytes() == b"p" * 100,
              "second yes replaces")
        a.rpcs3_saves = None
        check(fr.offer_save_import(a, str(d3), lambda q: "y", io.StringIO()) == [], "no RPCS3 import: no save question")
    finally:
        for p in patches:
            p.stop()
        import shutil
        shutil.rmtree(tmp0, ignore_errors=True)
    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
