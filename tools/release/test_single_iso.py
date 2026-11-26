#!/usr/bin/env python3
"""Host test for the first-run input help of 2026-11-26, change 1: a disc pick that is the folder holding one ISO (no PS3_GAME) is
offered or taken instead of only "pick that file" (a player picked the folder their ISO was in and failed six times).
  - firstrun_check.single_iso: one .iso and no PS3_GAME -> its path; two ISOs, PS3_GAME beside it, no ISO, a file ->
    "" (negative controls);
  - firstrun.py non-interactive (the launcher, RecompLauncher's prepare): takes the ISO and logs it; a folder with two
    ISOs is left as picked (control);
  - the text UI (--interactive): asks "Use it?" once; "y" takes the ISO, "n" keeps the folder (control);
  - the setup's SingleIso (installer/kz2.iss, run through iss_pascal.py): the same rule as single_iso.
Made-up folders and a tiny synthetic ISO only. Exit 0 = PASS.

    python3 tools/release/test_single_iso.py
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from input_check_fixtures import Checks, HERE, fc, fr, make_iso  # noqa: E402
import iss_pascal  # noqa: E402

check = Checks()


def interactive_pick(tmp, folder, answer):
    """The text UI with the disc folder answer and `answer` to "Use it?": -> the dump the check was given."""
    seen = {}

    class A:
        dump = update = eboot = ""
        rpcs3 = ""
        build = os.path.join(tmp, "b-" + answer)
        portable = True

    def fake_check(d, u, e, *target):
        seen["dump"] = d
        return 1, "FAIL D1 synthetic\nfirst-run checks: FAIL\n"

    def ask(q):
        if q.startswith("Disc dump:"):
            return folder
        if "Use it?" in q:
            seen["asked"] = True
            return answer
        if q.startswith("1.29 update folder"):
            return folder
        if q.startswith("Decrypted EBOOT"):
            return os.path.join(folder, "readme.txt")      # any existing file: the fake check does not read it
        if q.startswith("Fix the FAIL lines"):
            raise EOFError
        if q.startswith("RPCS3 folder"):
            return ""
        return "n"
    root = os.path.join(tmp, "iroot-" + answer)
    os.makedirs(root, exist_ok=True)
    fr.interactive(A(), root, os.path.join(tmp, "l.log"), [], ask=ask, out=io.StringIO(), check=fake_check,
                   vcheck=lambda c: {})
    return seen


with tempfile.TemporaryDirectory() as tmp:
    one = os.path.join(tmp, "Games", "KZ2")
    iso = make_iso(tmp, os.path.join(one, "My Disc (Europe).iso"), "BCES00081")
    open(os.path.join(one, "readme.txt"), "w").close()
    two = os.path.join(tmp, "Games", "Two")
    make_iso(tmp, os.path.join(two, "a.iso"))
    open(os.path.join(two, "readme.txt"), "w").close()
    make_iso(tmp, os.path.join(two, "b.iso"))
    both = os.path.join(tmp, "Games", "Both")
    make_iso(tmp, os.path.join(both, "c.iso"))
    os.makedirs(os.path.join(both, "PS3_GAME"))
    none = os.path.join(tmp, "Games", "None")
    os.makedirs(none)

    check(fc.single_iso(one) == iso, "single_iso: one ISO and no PS3_GAME -> the ISO", fc.single_iso(one))
    check(fc.single_iso(two) == "" and fc.single_iso(both) == "" and fc.single_iso(none) == ""
          and fc.single_iso(iso) == "" and fc.single_iso("") == "",
          "negative controls: two ISOs, PS3_GAME beside it, no ISO, the ISO itself, nothing -> ''")

    # non-interactive: the recorded dump is the one the steps see
    def run_main(dump, name):
        rec = os.path.join(tmp, name + ".txt")
        step = fr.Step("x", "X", 1, lambda c: [[sys.executable, "-c", f"open({rec!r}, 'w').write({c.dump!r})"]])
        root = os.path.join(tmp, "root-" + name)
        os.makedirs(root, exist_ok=True)
        out = io.StringIO()
        fr.main(["--dump", dump, "--root", root, "--jobs", "1", "--log-dir", os.path.join(tmp, "dl-" + name)],
                steps=[step], out=out)
        log = "".join(open(os.path.join(tmp, "dl-" + name, n), encoding="utf-8").read()
                      for n in os.listdir(os.path.join(tmp, "dl-" + name)) if n.endswith(".log"))
        return (open(rec).read() if os.path.isfile(rec) else ""), log
    got, log = run_main(one, "one")
    check(got == iso, "non-interactive: the steps get the ISO", got)
    check("the folder holds no PS3_GAME and one ISO, My Disc (Europe).iso: using it" in log, "and the log says so",
          log[-600:])
    got, log = run_main(two, "two")
    check(got == two and "using it" not in log, "control: a folder with two ISOs stays as picked", got)

    # the text UI: one question; yes takes the ISO, no keeps the folder
    s = interactive_pick(tmp, one, "y")
    check(s.get("asked") and s.get("dump") == os.path.abspath(iso), "text UI: 'Use it?' asked, yes -> the ISO", s)
    s = interactive_pick(tmp, one, "n")
    check(s.get("asked") and s.get("dump") == os.path.abspath(one), "control: no keeps the folder", s)
    s = interactive_pick(tmp, two, "y")
    check(not s.get("asked"), "control: two ISOs, nothing asked", s)

    # the setup's SingleIso (Pascal), on the same folders
    iss = open(os.path.join(HERE, "..", "..", "installer", "kz2.iss"), encoding="utf-8-sig").read()

    def h(p):
        return p

    state = {}

    def findfirst(pattern, ref):
        d, pat = os.path.split(pattern)
        # Windows matches *.iso against the 8.3 short name too, so a long name such as "disc.isox" comes back
        names = sorted(n for n in os.listdir(d) if ".iso" in n.lower()) if pat == "*.iso" else []
        recs = [iss_pascal.Record(Name=n, Attributes=0x10 if os.path.isdir(os.path.join(d, n)) else 0) for n in names]
        state["recs"] = recs
        if not recs:
            return False
        ref.set(recs.pop(0))
        return True

    def findnext(ref):
        if not state.get("recs"):
            return False
        ref.set(state["recs"].pop(0))
        return True
    b = {"ExtractFileExt": (lambda x: os.path.splitext(x)[1], ()),
         "CompareText": (lambda x, y: (x.lower() > y.lower()) - (x.lower() < y.lower()), ()),
         "DirExists": (os.path.isdir, ()), "AddBackslash": (lambda p: p if p.endswith(os.sep) else p + os.sep, ()),
         "FindFirst": (findfirst, (1,)), "FindNext": (findnext, (0,)), "FindClose": (lambda r: None, (0,))}
    prog = iss_pascal.Program(iss.replace("'PS3_GAME'", "'PS3_GAME'"), ["SingleIso"], b,
                              {"FILE_ATTRIBUTE_DIRECTORY": 0x10})
    isox = os.path.join(tmp, "Games", "Isox")
    os.makedirs(isox)
    open(os.path.join(isox, "disc.isox"), "w").close()
    got = [prog.call("SingleIso", d) for d in (one, two, both, none, "", isox)]
    check(got == [iso, "", "", "", "", ""] and fc.single_iso(isox) == "",
          "setup SingleIso: the same answers as single_iso; a long name that only short-matches *.iso is no ISO", got)
    pre = iss_pascal.Program(iss.replace(" and (CompareText(ExtractFileExt(R.Name), '.iso') = 0)", ""), ["SingleIso"], b,
                             {"FILE_ATTRIBUTE_DIRECTORY": 0x10})
    check(pre.call("SingleIso", isox) != "", "negative control: without the long-name check disc.isox would be taken")
    nb = iss[iss.index("function NextButtonClick"):]
    check("Iso := SingleIso(DumpPage.Values[0]);" in nb and "'Use it?', mbConfirmation, MB_YESNO" in nb
          and nb.index("SingleIso(") < nb.index("Problem := DumpProblem(DumpPage.Values[0], Id);"),
          "the dump page asks before its check, and a silent install takes it (logged)")

sys.exit(check.end("test_single_iso"))
