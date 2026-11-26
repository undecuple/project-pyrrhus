#!/usr/bin/env python3
"""Host test for the first-run input help of 2026-11-26, change 3: the messages name the player's own title id (from the disc's
PARAM.SFO, the ISO, or the one ISO in the picked folder) instead of "such as BCUS98116", the dev_hdd0/game/<id> hint
included (a European disc's player was sent to the US folder).
  - firstrun_check.own_disc_id: a folder dump, an ISO, the folder holding one ISO -> its id; an unknown game's id,
    no disc -> "" (negative controls);
  - the update's reason line: dev_hdd0/game/BCES00081 for a European ISO in a folder; the placeholder
    "<your disc's title id>" without "such as BCUS98116" when the disc is unknown (control);
  - the text UI's update question and help: the own id;
  - the setup's GameDirHint (installer/kz2.iss through iss_pascal.py): the dump's own id; for an ISO (the setup
    does not read the image) it says the build's first check names the id; else firstrun_check's placeholder; no
    "such as BCUS98116" left in the setup's update message.
Made-up folders only. Exit 0 = PASS.

    python3 tools/release/test_own_title_id.py
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from input_check_fixtures import Checks, HERE, check_json, fc, fr, make_dump, make_iso  # noqa: E402
import iss_pascal  # noqa: E402

check = Checks()
s = os.sep

with tempfile.TemporaryDirectory() as tmp:
    eu_dump = make_dump(os.path.join(tmp, "eud"), title_id="BCES00081")
    jp_iso = make_iso(tmp, os.path.join(tmp, "jp", "disc.iso"), "BCJS30032")
    folder = os.path.join(tmp, "Games", "KZ2")
    make_iso(tmp, os.path.join(folder, "Killzone 2.iso"), "BCES00081")
    other = make_dump(os.path.join(tmp, "oth"), title_id="NPUB30001")
    check([fc.own_disc_id(x) for x in (eu_dump, jp_iso, folder)] == ["BCES00081", "BCJS30032", "BCES00081"],
          "own_disc_id: folder dump, ISO, the folder of one ISO")
    check(fc.own_disc_id(other) == "" and fc.own_disc_id(os.path.join(tmp, "nothing")) == "",
          "negative controls: another game's id, no disc -> ''")

    empty_upd = os.path.join(tmp, "upd")
    os.makedirs(empty_upd)
    rc, rs, _ = check_json(["--dump", folder, "--update", empty_upd])
    line = next((r for r in rs if r.startswith("1.29 update failed:")), "")
    check(f"(dev_hdd0{s}game{s}BCES00081)" in line and "such as" not in line,
          "the update's line names dev_hdd0/game/BCES00081 (the ISO in the picked folder)", line)
    rc, rs, _ = check_json(["--dump", os.path.join(tmp, "nothing"), "--update", empty_upd])
    line = next((r for r in rs if r.startswith("1.29 update failed:")), "")
    check(f"(dev_hdd0{s}game{s}<your disc's title id>)" in line and "such as BCUS98116" not in line,
          "control: no disc -> the placeholder, without 'such as BCUS98116'", line)

    # the text UI: the update question and the help name the own id
    asked = []

    class A:
        dump = update = eboot = ""
        rpcs3 = ""
        build = os.path.join(tmp, "bui")
        portable = True

    def ask(q):
        asked.append(q)
        if q.startswith("Disc dump:"):
            return eu_dump
        if q.startswith("1.29 update folder"):
            return empty_upd
        if q.startswith("Decrypted EBOOT"):
            return os.path.join(eu_dump, "PS3_GAME", "PARAM.SFO")
        if q.startswith("Fix the FAIL lines"):
            raise EOFError
        return "n"
    out = io.StringIO()
    root = os.path.join(tmp, "iroot")
    os.makedirs(root)
    fr.interactive(A(), root, os.path.join(tmp, "l.log"), [], ask=ask, out=out,
                   check=lambda d, u, e, *t: (1, "FAIL U1 synthetic\nfirst-run checks: FAIL\n"), vcheck=lambda c: {})
    q = next((x for x in asked if x.startswith("1.29 update folder")), "")
    check("(dev_hdd0/game/BCES00081)" in q and "such as" not in q, "text UI: the update question names BCES00081", q)
    check("dev_hdd0/game/BCES00081" in out.getvalue() and "such as BCUS98116" not in out.getvalue(),
          "text UI: the update help names it too", out.getvalue()[-500:])

    iss = open(os.path.join(HERE, "..", "..", "installer", "kz2.iss"), encoding="utf-8-sig").read()
    def sfo_field(path, key):
        try:
            return str(fc.read_sfo(path).get(key, ""))
        except (OSError, ValueError):
            return ""
    b = {"SfoField": (sfo_field, ()), "FileExists": (os.path.isfile, ()), "DirExists": (os.path.isdir, ()),
         "ExtractFileExt": (lambda x: os.path.splitext(x)[1], ()),
         "CompareText": (lambda x, y: (x.lower() > y.lower()) - (x.lower() < y.lower()), ()),
         "AddBackslash": (lambda x: x if x.endswith(os.sep) else x + os.sep, ()), "Trim": (str.strip, ())}
    prog = iss_pascal.Program(iss.replace("'PS3_GAME\\PARAM.SFO'", "'PS3_GAME" + os.sep + "PARAM.SFO'"),
                              ["KnownDiscId", "IsIsoPick", "DiscSfo", "GameDirHint"], b)
    hints = [prog.call("GameDirHint", x) for x in (eu_dump, jp_iso, os.path.join(tmp, "nothing"), other)]
    check(hints[0] == "dev_hdd0\\game\\BCES00081"
          and hints[1] == "dev_hdd0\\game\\<your disc's title id> (the build's first check reads it from your ISO and names it)"
          and hints[2] == hints[3] == "dev_hdd0\\game\\<your disc's title id>",
          "setup GameDirHint: the dump's own id; for an ISO it says the first check names it; else firstrun's placeholder",
          hints)
    check(fc.game_dir("").endswith("<your disc's title id>"), "the same placeholder as firstrun_check.game_dir")
    nb = iss[iss.index("function NextButtonClick"):]
    check("GameDirHint(DumpPage.Values[0])" in nb and "such as BCUS98116" not in nb,
          "the setup's update message uses it, no 'such as BCUS98116'")

sys.exit(check.end("test_own_title_id"))
