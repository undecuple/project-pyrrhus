#!/usr/bin/env python3
"""Host test for the first-run input help of 2026-11-26, change 7: when the update check fails, the reason says what the folder holds
(a French player: "the game is recognised but the update isn't; I tried several and none is accepted").
  - a .pkg file: "an update package that is not installed yet" and the GETTING-FILES.md link (no decryption steps);
  - another region's update: both title ids named (U1);
  - another version: the APP_VER from PARAM.SFO named ("APP_VER 01.27, the 1.27 update, not 1.29");
  - dev_hdd0/game with several title-id folders: the disc's own folder named; firstrun.py non-interactive takes it
    and logs it, the text UI asks once; a parent without the disc's id says which releases it holds (control);
  - control: the disc's own 1.29 update passes with no reasons.
Made-up folders only. Exit 0 = PASS.

    python3 tools/release/test_update_diagnosis.py
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from input_check_fixtures import Checks, check_json, fr, make_dump, make_update  # noqa: E402

check = Checks()


def upd_line(rs):
    return next((r for r in rs if r.startswith("1.29 update failed:")), "")


with tempfile.TemporaryDirectory() as tmp:
    d = make_dump(os.path.join(tmp, "fr"), title_id="BCES00081")
    own = make_update(os.path.join(tmp, "own"), title_id="BCES00081")
    rc, rs, _ = check_json(["--dump", d, "--update", own])
    check(rc == 0 and rs == [], "control: the disc's own 1.29 update passes", rs)

    pkg = os.path.join(tmp, "pkgdir")
    os.makedirs(pkg)
    open(os.path.join(pkg, "EP9000-BCES00081_00-KZ2PATCH0129.pkg"), "wb").close()
    line = upd_line(check_json(["--dump", d, "--update", pkg])[1])
    check("an update package that is not installed yet" in line and "docs/GETTING-FILES.md" in line,
          "a .pkg: not installed yet, with the GETTING-FILES link", line)
    check("decrypt" not in line.lower().replace("decrypted", ""), "and no decryption step", line)

    us = make_update(os.path.join(tmp, "us"))
    rc, rs, _ = check_json(["--dump", d, "--update", us])
    line = upd_line(rs)
    check("BCUS98116" in line and "BCES00081" in line, "another region: both ids named", line)

    old = make_update(os.path.join(tmp, "old"), app_ver="01.27", title_id="BCES00081")
    os.remove(os.path.join(old, "USRDIR", "added_data_ps3.psarc"))
    line = upd_line(check_json(["--dump", d, "--update", old])[1])
    check("its PARAM.SFO says APP_VER 01.27, the 1.27 update, not 1.29" in line, "another version: its APP_VER named",
          line)

    game = os.path.join(tmp, "hdd", "dev_hdd0", "game")
    for t in ("BCUS98116", "NPEB00001"):
        make_update(os.path.join(tmp, "p-" + t), title_id=t)
        os.renames(os.path.join(tmp, "p-" + t, "hdd0", "game", t), os.path.join(game, t))
    os.renames(own, os.path.join(game, "BCES00081"))
    mine = os.path.join(game, "BCES00081")
    line = upd_line(check_json(["--dump", d, "--update", game])[1])
    check(f"the one for your disc (BCES00081) is {mine}: pick that folder" in line, "dev_hdd0/game: the disc's folder",
          line)
    check(fr.parent_update(game, d) == mine and fr.parent_update(mine, d) == "", "parent_update: the parent only")

    rec = os.path.join(tmp, "rec.txt")
    step = fr.Step("x", "X", 1, lambda c: [[sys.executable, "-c", f"open({rec!r}, 'w').write({c.update!r})"]])
    root = os.path.join(tmp, "root")
    os.makedirs(root)
    fr.main(["--dump", d, "--update", game, "--root", root, "--jobs", "1", "--log-dir", os.path.join(tmp, "dl")],
            steps=[step], out=io.StringIO())
    logs = "".join(open(os.path.join(tmp, "dl", n), encoding="utf-8").read() for n in os.listdir(os.path.join(tmp, "dl")))
    check(open(rec).read() == mine and "using BCES00081, the disc's" in logs, "non-interactive: takes it and logs it")

    asked = []

    class A:
        dump = update = eboot = ""
        rpcs3 = ""
        build = os.path.join(tmp, "ib")
        portable = True
    seen = {}

    def ask(q):
        asked.append(q)
        if q.startswith("Disc dump:"):
            return d
        if q.startswith("1.29 update folder"):
            return game
        if "Use it?" in q:
            return "y"
        if q.startswith("Decrypted EBOOT"):
            return os.path.join(mine, "PARAM.SFO")
        if q.startswith("Fix the FAIL lines"):
            raise EOFError
        return "n"

    def fake(dd, u, e, *t):
        seen["u"] = u
        return 1, "FAIL D1: synthetic\nfirst-run checks: FAIL\n"
    iroot = os.path.join(tmp, "iroot")
    os.makedirs(iroot)
    fr.interactive(A(), iroot, os.path.join(tmp, "l.log"), [], ask=ask, out=io.StringIO(), check=fake,
                   vcheck=lambda c: {})
    check(any("is your disc's. Use it?" in q for q in asked) and seen.get("u") == mine,
          "text UI: asks once and takes the disc's folder", seen)

    os.renames(mine, os.path.join(tmp, "moved"))
    line = upd_line(check_json(["--dump", d, "--update", game])[1])
    check("the update folder of the US version (BCUS98116), but none for your disc, the European version (BCES00081)"
          in line and "NPEB00001" not in line, "control: no folder for the disc -> which releases it holds", line)

sys.exit(check.end("test_update_diagnosis"))
