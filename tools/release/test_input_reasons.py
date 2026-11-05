#!/usr/bin/env python3
"""Host test for firstrun_check.py's input reasons and its imports under an isolated Python (the bundled embeddable
Python's ._pth puts only its own folders on sys.path). Adapted from Project Helghast PR #14 (the Killzone 3 PC port,
same author, MIT): KZ2's update (1.29, added_data_ps3.psarc and patch_data_ps3), EBOOT sizes and title id. Synthetic
fixtures only (the helpers of test_firstrun_check.py and iso_fixture.py), no game data. Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_input_reasons.py

Cases: a passing run has no reasons (control); a drive-root-like folder as the dump names what it holds, the
accepted forms, and the update and EBOOT as passed, without the redundant D1-D3 messages; PS3_GAME one folder down
and an ISO file beside are named; a missing path; PS3_GAME without the archive keeps D3; picks of PS3_GAME and
PS3_GAME/USRDIR pass with a D0 INFO line; the update: empty, a disc dump, PARAM.SFO only, the folder above it, its
USRDIR (passes); the EBOOT: missing (GETTING-FILES link), the disc's 1.01 one (E1 kept); drive roots for both inputs
(two levels searched; the same folders as plain folders: one level, control); roles swapped both ways; a folder
with only the update's data (added_data_ps3.psarc or patch_data_ps3) as the disc; the disc's PS3_GAME as the update
(U1 FAIL, category DG; the GD update passes U1, control); every line labelled; an earlier change's rules unchanged: a
decrypted ISO with another title id names the file and keeps D1, a Trilogy disc (02.00) passes with no reasons,
another game's folder dump keeps D1's id; a mixed region set names both regions in the update's line. Isolated import: `python3 -I firstrun_check.py --dump x.iso` from another
folder imports iso9660; a copy without the sys.path line fails the same way (negative control).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun_check as fc  # noqa: E402
from test_firstrun_check import make_dump, make_update, write_elf, write_sfo  # noqa: E402

FAILS = []
SMALL = ["--min-psarc-bytes", "1024", "--skip-archive-hash", "--json"]


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"\n     {str(detail)[:1500]}"))
    if not cond:
        FAILS.append(name)


def run(args):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fc.main(args + SMALL)
    j = json.loads(buf.getvalue())
    return rc, j["facts"].get("reasons", []), j


def main():
    tmp = tempfile.mkdtemp(prefix="kz2-reasons-")
    try:
        d = make_dump(tmp)
        u = make_update(tmp)
        elf = os.path.join(u, "USRDIR", "EBOOT.elf")
        s = os.sep
        rc, rs, _ = run(["--dump", d, "--update", u])
        check("control: a passing run has no reasons", rc == 0 and rs == [], rs)

        # the disc: a drive-root-like folder (E:\ given as the dump: D1-D3 failed and read as an EBOOT problem)
        root = os.path.join(tmp, "drive")
        for n in ("Games", "Music", "System Volume Information"):
            os.makedirs(os.path.join(root, n))
        open(os.path.join(root, "notes.txt"), "w").close()
        rc, rs, _ = run(["--dump", root, "--update", u])
        check("drive root: one disc line naming what is there", rc == 1 and len(rs) == 2 and rs[0].startswith(
            f"Disc dump failed: {root} holds no PS3_GAME folder (3 folders, 1 files). It must be the folder that "
            f"holds PS3_GAME (with PS3_GAME{s}PARAM.SFO"), rs)
        check("drive root: the accepted forms", "the PS3_GAME folder itself, or a decrypted .iso file picked as a file"
              in rs[0], rs)
        check("drive root: no redundant D1-D3 text", "no PARAM.SFO at" not in rs[0] and "Found:" not in rs[0], rs)
        check("drive root: update and EBOOT passed", rs[-1] == "Passed: the 1.29 update and the decrypted EBOOT.", rs)
        up = os.path.join(tmp, "up")
        os.makedirs(up)
        shutil.copytree(d, os.path.join(up, "KZ2"))
        rc, rs, _ = run(["--dump", up, "--update", u])
        check("PS3_GAME one folder down is named", rc == 1 and f"one folder down, the disc dump looks like "
              f"{os.path.join(up, 'KZ2')}: pick that folder" in rs[0], rs)
        isod = os.path.join(tmp, "isod")
        os.makedirs(isod)
        open(os.path.join(isod, "Killzone 2.iso"), "w").close()
        rc, rs, _ = run(["--dump", isod, "--update", u])
        check("an ISO file beside is named", rc == 1 and "it holds the ISO file Killzone 2.iso: pick that file" in rs[0], rs)
        rc, rs, _ = run(["--dump", os.path.join(tmp, "nowhere"), "--update", u])
        check("missing dump path: nothing is there", rc == 1 and "nothing is there" in rs[0], rs)
        os.remove(os.path.join(d, "PS3_GAME", "USRDIR", "data_ps3.psarc"))
        rc, rs, _ = run(["--dump", d, "--update", u])
        check("PS3_GAME without the archive: names it and keeps D3", rc == 1 and
              f"holds PS3_GAME, but not PS3_GAME{s}USRDIR{s}data_ps3.psarc" in rs[0] and "Found: disc dump: no PS3_GAME"
              in rs[0], rs)
        d = make_dump(os.path.join(tmp, "d2"))
        for pick in (os.path.join(d, "PS3_GAME"), os.path.join(d, "PS3_GAME", "USRDIR")):
            rc, rs, j = run(["--dump", pick, "--update", u])
            check(f"a pick of {os.path.relpath(pick, d)} passes", rc == 0 and rs == [] and any(
                "using the folder that holds PS3_GAME" in c["message"] for c in j["checks"]), (rs, j["checks"][:3]))

        # the update
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        rc, rs, _ = run(["--dump", d, "--update", empty, "--eboot", elf])
        check("empty update folder", rc == 1 and rs[0].startswith(f"1.29 update failed: {empty} holds none of these "
              f"files (the folder is empty). It must be the installed 1.29 update folder (dev_hdd0{s}game{s}BCUS98116)")
              and f"PARAM.SFO and USRDIR{s}EBOOT.BIN, with USRDIR{s}{fc.UPDATE_DATA}" in rs[0], rs)
        check("empty update: disc and EBOOT passed", rs[-1] == "Passed: the disc dump and the decrypted EBOOT.", rs)
        rc, rs, _ = run(["--dump", d, "--update", d, "--eboot", elf])
        check("a disc dump given as the update", rc == 1 and
              "so it looks like the disc dump, not the update: give it as the disc dump" in rs[0], rs)
        half = os.path.join(tmp, "half")
        write_sfo(os.path.join(half, "PARAM.SFO"), {"APP_VER": "01.29", "CATEGORY": "GD", "TITLE_ID": "BCUS98116"})
        rc, rs, _ = run(["--dump", d, "--update", half, "--eboot", elf])
        check("update with PARAM.SFO only: says what it holds and keeps U2", rc == 1 and f"{half} holds PARAM.SFO." in
              rs[0] and "Found: 1.29 update: no USRDIR/EBOOT.BIN" in rs[0], rs)
        rc, rs, _ = run(["--dump", d, "--update", os.path.dirname(u), "--eboot", elf])
        check("the folder above the update", rc == 1 and
              f"one folder down, the 1.29 update looks like {u}: pick that folder" in rs[0], rs)
        rc, rs, _ = run(["--dump", d, "--update", os.path.join(u, "USRDIR")])
        check("a pick of the update's USRDIR passes", rc == 0 and rs == [], rs)

        # the EBOOT
        rc, rs, _ = run(["--dump", d, "--update", u, "--eboot", os.path.join(tmp, "EBOOT.elf")])
        check("missing EBOOT: EBOOT.elf is missing + GETTING-FILES", rc == 1 and rs[0].startswith(
            f"EBOOT failed: no file at {os.path.join(tmp, 'EBOOT.elf')}: EBOOT.elf is missing.") and
            fc.GETTING_FILES in rs[0] and rs[-1] == "Passed: the disc dump and the 1.29 update.", rs)
        old = os.path.join(tmp, "old", "EBOOT.elf")
        write_elf(old, 16_381_928)
        rc, rs, _ = run(["--dump", d, "--update", u, "--eboot", old])
        check("the disc's 1.01 EBOOT: E1's message kept", rc == 1 and "Found: this EBOOT is the disc's 1.01 one" in rs[0], rs)
        for r in rs:
            check("reason fits a REASON line (firstrun.REASON_MAX 900)", len(r) <= 900, r)

        # drive roots as both inputs (E:\ and F:\): two levels searched on a root, one elsewhere
        e, f2 = os.path.join(tmp, "e"), os.path.join(tmp, "f")
        shutil.copytree(d, os.path.join(e, "Games", "KZ2"))
        shutil.copytree(u, os.path.join(f2, "Backup", "BCUS98116"))
        shutil.copytree(u, os.path.join(e, "PS3", "BCUS98116"))
        real_root = fc.is_drive_root
        fc.is_drive_root = lambda p: os.path.abspath(p) in (e, f2)
        try:
            rc, rs, _ = run(["--dump", e, "--update", f2, "--eboot", elf])
        finally:
            fc.is_drive_root = real_root
        disc_l = next((x for x in rs if x.startswith("Disc dump failed:")), "")
        upd_l = next((x for x in rs if x.startswith("1.29 update failed:")), "")
        check("drive roots: the disc line names the disc and the update on the drive", rc == 1 and
              f"{e} is a drive root; on this drive, the disc dump looks like {os.path.join(e, 'Games', 'KZ2')}: pick "
              f"that folder; the 1.29 update looks like {os.path.join(e, 'PS3', 'BCUS98116')} (give it as the update)"
              in disc_l, rs)
        check("drive roots: the update line names the update on its drive", f"{f2} is a drive root; on this drive, the "
              f"1.29 update looks like {os.path.join(f2, 'Backup', 'BCUS98116')}: pick that folder" in upd_l, rs)
        check("drive roots: EBOOT passed", rs[-1] == "Passed: the decrypted EBOOT.", rs)
        rc, rs, _ = run(["--dump", e, "--update", f2, "--eboot", elf])
        check("control: the same folders, not drive roots, are searched one level only", rc == 1 and
              "looks like" not in " ".join(rs) and "(2 folders, 0 files)" in rs[0], rs)
        # Project Helghast PR #17: other games' dumps on a drive root are not candidates; ISOs are named beside
        # folder hints; a PARAM.SFO inside the update's USRDIR does not block the step up to the update folder
        g = os.path.join(tmp, "g")
        for n, tid in (("Katamari", "BCUS98001"), ("GT5", "BCES00569"), ("OtherEU", "BCES01070")):
            shutil.copytree(make_dump(os.path.join(tmp, "o" + n), title_id=tid), os.path.join(g, n + "_dump"))
        shutil.copytree(os.path.join(tmp, "oKatamari", "dump"), os.path.join(g, "KatamariFlat"))
        kf = os.path.join(g, "KatamariFlat")
        check("looks_like_disc: another title id is no disc", not fc.looks_like_disc(kf) and fc.has_ps3_game(kf) and
              fc.disc_title_id(kf) == "BCUS98001", fc.disc_title_id(kf))
        check("looks_like_disc: every accepted id is a disc, the Trilogy's 02.00 too", all(
            fc.looks_like_disc(make_dump(os.path.join(tmp, "id" + i), title_id=i)) for i in fc.TITLE_IDS) and
            fc.looks_like_disc(make_dump(os.path.join(tmp, "tri67"), version=fc.TRILOGY_DISC_VERSION)))
        check("looks_like_disc: no PARAM.SFO is no disc", not fc.looks_like_disc(e) and fc.disc_title_id(e) == "")
        fc.is_drive_root = lambda p: os.path.abspath(p) == g
        try:
            check("candidates: only other games' dumps give none", fc.candidates(g, 2) == ([], []), fc.candidates(g, 2))
            shutil.copytree(d, os.path.join(g, "Games", "KZ2"))
            check("candidates: the Killzone 2 dump among them is the only one",
                  fc.candidates(g, 2)[0] == [os.path.join(g, "Games", "KZ2")], fc.candidates(g, 2))
            open(os.path.join(g, "game.iso"), "wb").write(b"x")
            os.makedirs(os.path.join(g, "Isos"))
            open(os.path.join(g, "Isos", "kz2.iso"), "wb").write(b"x")
            rc, rs, _ = run(["--dump", g, "--update", u, "--eboot", elf])
            isos_root = fc._isos(g)
        finally:
            fc.is_drive_root = real_root
        check("hint: the folder hint and both ISO files named together, no other game", rc == 1 and
              f"looks like {os.path.join(g, 'Games', 'KZ2')}: pick that folder" in rs[0] and "Katamari" not in rs[0]
              and "GT5" not in rs[0] and "OtherEU" not in rs[0] and "game.iso" in rs[0] and
              os.path.join(g, "Isos", "kz2.iso") in rs[0] and "pick that file" in rs[0], rs)
        check("_isos: names in the root, full paths one level down", isos_root == ["game.iso",
              os.path.join(g, "Isos", "kz2.iso")], isos_root)
        check("control: not a drive root, _isos looks in the folder only", fc._isos(g) == ["game.iso"], fc._isos(g))
        many = os.path.join(tmp, "many")
        os.makedirs(many)
        for i in range(5):
            open(os.path.join(many, f"d{i}.iso"), "wb").write(b"x")
        check("_isos: at most 3", len(fc._isos(many)) == 3, fc._isos(many))
        p2 = os.path.join(tmp, "p2")
        os.makedirs(os.path.join(p2, "dump"))
        shutil.copytree(d, os.path.join(p2, "KZ2"))
        open(os.path.join(p2, "a.iso"), "wb").write(b"x")
        txt, _ = fc.disc_found(p2)
        check("hint: an ISO is named beside the folder hint (not a drive root)", "pick that folder" in txt and
              "the ISO file a.iso: pick that file" in txt, txt)
        u2 = os.path.join(tmp, "u2")
        shutil.copytree(u, u2)
        shutil.copy(os.path.join(u2, "PARAM.SFO"), os.path.join(u2, "USRDIR", "PARAM.SFO"))
        check("resolve_update: a USRDIR holding a PARAM.SFO still resolves to its parent",
              fc.resolve_update(os.path.join(u2, "USRDIR")) == u2 and
              fc.resolve_update(os.path.join(u2, "USRDIR") + os.sep) == u2, fc.resolve_update(os.path.join(u2, "USRDIR")))
        check("resolve_update: the update folder and other folders are unchanged",
              fc.resolve_update(u2) == u2 and fc.resolve_update(tmp) == tmp)
        check("resolve_update: a USRDIR whose parent has no PARAM.SFO is unchanged",
              fc.resolve_update(os.path.join(tmp, "only_x", "USRDIR")) == os.path.join(tmp, "only_x", "USRDIR"))
        rc, rs, _ = run(["--dump", d, "--update", os.path.join(u2, "USRDIR"), "--eboot", elf])
        check("a USRDIR with a PARAM.SFO given as the update passes", rc == 0 and rs == [], rs)
        rc, rs, _ = run(["--dump", d, "--update", kf, "--eboot", elf])
        check("another game's dump given as the update: named as a disc dump", rc == 1 and
              "so it looks like the disc dump, not the update" in rs[1 if rs[0].startswith("Disc") else 0], rs)

        # roles swapped or mixed up
        rc, rs, _ = run(["--dump", u, "--update", d, "--eboot", elf])
        check("swapped: the update given as the disc", rc == 1 and rs[0].startswith(
              f"Disc dump failed: {u} looks like the 1.29 update") and "give it as the 1.29 update" in rs[0], rs)
        check("swapped: the disc given as the update", len(rs) > 1 and rs[1].startswith(
              f"1.29 update failed: {d} holds PS3_GAME, so it looks like the disc dump"), rs)
        for mark in (fc.UPDATE_DATA, fc.UPDATE_PATCH_DIR):
            only = os.path.join(tmp, "only_" + mark)
            os.makedirs(os.path.join(only, "USRDIR"))
            src = os.path.join(u, "USRDIR", mark)
            (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(only, "USRDIR", mark))
            rc, rs, _ = run(["--dump", only, "--update", u])
            check(f"a folder with only the update's {mark}, as the disc", rc == 1 and
                  "looks like the 1.29 update" in rs[0] and mark in rs[0], rs)
        rc, rs, j = run(["--dump", d, "--update", os.path.join(d, "PS3_GAME"), "--eboot", elf])
        check("the disc's PS3_GAME as the update fails U1 and says so", rc == 1 and any(
            c["code"] == "U1" and c["level"] == "FAIL" and "category DG" in c["message"] for c in j["checks"]) and
            "looks like the disc's PS3_GAME folder" in rs[0], rs)
        check("control: the update with category GD passes U1", not any(
            c["code"] == "U1" and c["level"] == "FAIL" for c in run(["--dump", d, "--update", u])[2]["checks"]))
        labels = ("Disc dump failed: ", "1.29 update failed: ", "EBOOT failed: ", "Passed: ")
        rc, rs, _ = run(["--dump", e, "--update", f2, "--eboot", os.path.join(tmp, "none.elf")])
        check("every line is labelled", rc == 1 and len(rs) == 3 and all(x.startswith(labels) for x in rs), rs)

        # an earlier change's rules keep working: ISO source, Trilogy, region
        from iso_fixture import build_iso
        sfo = os.path.join(tmp, "p.sfo")

        def sfo_of(**kw):
            f = {"APP_VER": "01.01", "CATEGORY": "DG", "TITLE": "Synthetic", "TITLE_ID": "BCUS98116", "VERSION": "01.01"}
            f.update(kw)
            write_sfo(sfo, f)
            return open(sfo, "rb").read()
        files = {"PS3_DISC.SFB": b".SFB" + b"\0" * 8, "PS3_GAME/PARAM.SFO": sfo_of(),
                 "PS3_GAME/USRDIR/EBOOT.BIN": fc.SELF_MAGIC + b"\0" * 60,
                 "PS3_GAME/USRDIR/data_ps3.psarc": fc.PSARC_MAGIC + b"\0" * 6000}
        iso = build_iso(os.path.join(tmp, "game.iso"), files)
        rc, rs, _ = run(["--dump", iso, "--update", u])
        check("ISO: a good decrypted ISO passes with no reasons", rc == 0 and rs == [], rs)
        oiso = build_iso(os.path.join(tmp, "o.iso"), dict(files, **{"PS3_GAME/PARAM.SFO": sfo_of(TITLE_ID="NPUB30001",
                                                                                                    TITLE="Other")}))
        rc, rs, _ = run(["--dump", oiso, "--update", u])
        check("ISO: another title id names the file and keeps D1", rc == 1 and rs[0].startswith(
            "Disc dump failed: the file o.iso, read as a disc ISO.") and "NPUB30001 (Other)" in rs[0], rs)
        tri = make_dump(os.path.join(tmp, "tri"), version="02.00")
        rc, rs, j = run(["--dump", tri, "--update", u])
        check("Trilogy disc (02.00): passes with its D1 WARN and no reasons", rc == 0 and rs == [] and any(
            c["code"] == "D1" and c["level"] == "WARN" for c in j["checks"]), rs)
        eu = make_dump(os.path.join(tmp, "eu"), title_id="BCES01070")
        rc, rs, _ = run(["--dump", eu, "--update", u])
        check("another game's folder dump keeps D1's id", rc == 1 and rs[0].startswith(
            f"Disc dump failed: {eu} holds PS3_GAME with PARAM.SFO") and "Found: disc dump: this is BCES01070" in rs[0], rs)
        # D53: a European disc with the US update is a mixed set: the update's line names both and the right folder
        eu = make_dump(os.path.join(tmp, "eu53"), title_id="BCES00081")
        rc, rs, _ = run(["--dump", eu, "--update", u])
        s = os.sep
        check("mixed set: the update's reason names both regions and dev_hdd0/game/<the disc's id>", rc == 1
              and len(rs) == 2 and rs[0].startswith(f"1.29 update failed: {u} holds PARAM.SFO")
              and f"(dev_hdd0{s}game{s}BCES00081)" in rs[0]
              and "this is the US update (BCUS98116), but the disc dump is the European disc (BCES00081)" in rs[0]
              and rs[1].startswith("Passed: the disc dump"), rs)

        # text output: the reasons follow "first-run checks: FAIL", indented (firstrun.text_reasons reads them)
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fc.main(["--dump", root, "--update", u, "--min-psarc-bytes", "1024", "--skip-archive-hash"])
        tl = buf.getvalue().splitlines()
        i = tl.index("first-run checks: FAIL")
        check("text: the reasons follow the FAIL line, indented", tl[i + 1].startswith("  Disc dump failed: ") and
              tl[i + 2] == "  Passed: the 1.29 update and the decrypted EBOOT.", tl[i:])

        # isolated Python (the embeddable package's ._pth): the script's folder is not on sys.path
        if sys.version_info < (3, 11):
            print("SKIP isolated import (needs Python 3.11+ for -I to drop the script folder)")
        else:
            cwd = os.path.join(tmp, "elsewhere")
            os.makedirs(cwd)
            p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "firstrun_check.py"), "--dump", iso, "--json"],
                               cwd=cwd, capture_output=True, text=True)
            check("isolated: firstrun_check imports iso9660 by full path", "ModuleNotFoundError" not in p.stderr and
                  '"checks"' in p.stdout, p.stderr[-600:])
            ctl = os.path.join(tmp, "ctl")
            os.makedirs(ctl)
            src = open(os.path.join(HERE, "firstrun_check.py")).read()
            line = "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
            open(os.path.join(ctl, "firstrun_check.py"), "w").write(src.replace(line, "", 1))
            shutil.copy(os.path.join(HERE, "iso9660.py"), ctl)
            p = subprocess.run([sys.executable, "-I", os.path.join(ctl, "firstrun_check.py"), "--dump", iso, "--json"],
                               cwd=cwd, capture_output=True, text=True)
            check("isolated control: without the sys.path line the import fails", line in src and
                  "ModuleNotFoundError" in p.stderr and "iso9660" in p.stderr, p.stderr[-600:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"input_reasons: {'PASS' if not FAILS else 'FAIL ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
