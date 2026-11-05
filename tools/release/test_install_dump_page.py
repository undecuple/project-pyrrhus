#!/usr/bin/env python3
"""Host test (adapted from Project Helghast PR #14, its test_install_dump_page.py, same author,
MIT): installer/kz2.iss' disc and update pages say what a wrong folder holds. Static checks (no ISCC, no game data):
- DumpProblem: a folder without PS3_GAME names the path and what it holds (FolderSummary), "PS3_GAME is one folder
  down: pick X" (SubDisc: our title ids only), "It looks like the 1.29 update folder: give it as the update, and the disc dump here" for
  an update folder (PARAM.SFO + USRDIR\\EBOOT.BIN, or USRDIR\\added_data_ps3.psarc), in that order, before the
  accepted forms; the TITLE_ID, Trilogy and ISO branches are kept;
- UpdateOK holds the three files of the page's quick check; UpdateProblem names the path, "that is a disc dump" for
  PS3_GAME, the disc's PARAM.SFO (category DG), the missing files, FolderSummary and "PARAM.SFO is one folder down";
  the update page's box and the EBOOT page's missing-file box use them (the path, GETTING-FILES);
- the update-folder rule agrees with firstrun_check.looks_like_update on synthetic trees (the update, the disc dump,
  a folder with only added_data_ps3.psarc, an empty folder; negative controls included).

    python3 tools/release/test_install_dump_page.py
"""
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ISS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "installer", "kz2.iss")
if not os.path.isfile(ISS):
    print("SKIP: installer/kz2.iss not in this tree")
    sys.exit(0)
import firstrun_check as fc  # noqa: E402
from test_firstrun_check import make_dump, make_update  # noqa: E402

t = open(ISS, encoding="utf-8").read()
code = t[t.find("[Code]"):]
bad = 0


def check(ok, msg):
    global bad
    bad += not ok
    print(("ok   " if ok else "FAIL ") + msg)


def func(name):
    m = re.search(r"(?:function|procedure) " + name + r"\b.*?\nend;", code, re.S)
    return m.group(0) if m else ""


fs, sw = func("FolderSummary"), func("SubWith")
check("'it is empty'" in fs and "' folders and '" in fs and "'there is no such folder'" in fs and
      "FILE_ATTRIBUTE_DIRECTORY" in fs, "FolderSummary counts folders and files, says empty or missing")
check("FindFirst" in sw and "FileExists(AddBackslash(Dir) + FR.Name + '\\' + Rel)" in sw,
      "SubWith finds the first subfolder holding Rel")
g = func("DumpProblem")
check("' holds no PS3_GAME folder (' + FolderSummary(Dir)" in g and "Sub := SubDisc(Dir)" in g and
      "PS3_GAME is one folder down: pick " in g, "DumpProblem names what is there and PS3_GAME one folder down")
# Project Helghast PR #17: the one-folder-down hint offers only our title ids, never another game's dump
sd, kd = func("SubDisc"), func("KnownDiscId")
check("SubWith(Dir, 'PS3_GAME" not in g, "DumpProblem's one-folder-down hint comes from SubDisc, not any PS3_GAME")
check("FindFirst" in sd and "KnownDiscId(SfoField(DiscSfo(AddBackslash(Dir) + FR.Name), 'TITLE_ID'))" in sd and
      "FILE_ATTRIBUTE_DIRECTORY" in sd, "SubDisc offers only subfolders whose PS3_GAME has one of our title ids")
ids = re.findall(r"'([A-Z]{4}\d{5})'", kd)
check(ids == list(fc.TITLE_IDS) == ["BCUS98116", "BCES00081", "BCAS20066", "BCJS30032"],
      f"KnownDiscId accepts exactly firstrun_check.TITLE_IDS: {ids}")
check(code.index("function SfoField") < code.index("function DiscSfo") < code.index("function KnownDiscId") <
      code.index("function SubDisc") < code.index("function DumpProblem"),
      "SubDisc sits after SfoField, DiscSfo and KnownDiscId, before DumpProblem (Pascal Script order)")
check("It looks like the 1.29 update folder: give it as the update, and the disc dump here" in g and
      "FileExists(AddBackslash(Dir) + 'USRDIR\\EBOOT.BIN')" in g and
      "FileExists(AddBackslash(Dir) + 'USRDIR\\added_data_ps3.psarc')" in g,
      "DumpProblem names an update folder given as the dump")
check(g.index("one folder down") < g.index("It looks like the 1.29 update folder") < g.index("Select the folder"),
      "the update hint sits after the one-folder-down hint and before the accepted forms")
check(g.index("IsIsoPick(Dir)") < g.index("holds no PS3_GAME") and "not KnownDiscId(Id)" in g and "ArchiveProblem" in g,
      "the ISO, TITLE_ID and archive branches are kept (ISO first)")
ok_, up = func("UpdateOK"), func("UpdateProblem")
check(all(f"'{n}'" in ok_ for n in ("PARAM.SFO", "USRDIR\\EBOOT.BIN", "USRDIR\\added_data_ps3.psarc")),
      "UpdateOK checks PARAM.SFO, USRDIR\\EBOOT.BIN and USRDIR\\added_data_ps3.psarc")
check("that is a disc dump, not the update" in up and "'CATEGORY') = 'DG'" in up and "' does not hold ' + Miss" in up
      and "FolderSummary(Dir)" in up and "PARAM.SFO is one folder down: pick " in up and
      "there is no such folder" in up, "UpdateProblem names the disc dump, the disc's PS3_GAME, the missing files")
nb = func("NextButtonClick")
check("not UpdateOK(UpdatePage.Values[0])" in nb and "UpdateProblem(UpdatePage.Values[0])" in nb,
      "the update page's box says what is wrong at the path")
check("'No file at ' + EbootPage.Values[0] + ': EBOOT.elf is missing." in nb and
      "project-pyrrhus/blob/main/docs/GETTING-FILES.md" in nb, "the EBOOT page names the missing path and GETTING-FILES")
check("helghast" not in (fs + sw + up + ok_).lower().replace("project helghast pr #14", ""),
      "no Project Helghast paths or names beyond the credit")


def iss_update_like(d):
    """DumpProblem's update rule, transcribed."""
    j = lambda *p: os.path.isfile(os.path.join(d, *p))  # noqa: E731
    return (j("PARAM.SFO") and j("USRDIR", "EBOOT.BIN")) or j("USRDIR", "added_data_ps3.psarc")


tmp = tempfile.mkdtemp(prefix="kz2-dumppage-")
try:
    d, u = make_dump(tmp), make_update(tmp)
    only = os.path.join(tmp, "only", "USRDIR")
    os.makedirs(only)
    shutil.copy(os.path.join(u, "USRDIR", fc.UPDATE_DATA), only)
    empty = os.path.join(tmp, "empty")
    os.makedirs(empty)
    for name, p, want in (("update", u, True), ("added_data only", os.path.dirname(only), True),
                          ("disc dump (control)", d, False), ("empty (control)", empty, False)):
        check(iss_update_like(p) == want == fc.looks_like_update(p),
              f"update rule agrees with firstrun_check: {name} -> {want}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("test_install_dump_page:", "PASS" if not bad else f"FAIL ({bad})")
sys.exit(1 if bad else 0)
