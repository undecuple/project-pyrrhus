#!/usr/bin/env python3
"""Host test for the first-run input help of 2026-11-26, change 4: when the same check fails twice in a row with the same unchanged
inputs, a short numbered guide pointing to docs/GETTING-FILES.md follows the specific lines (a player saw the same
block six times and quit). The specific diagnosis and the update help are never left out (review fix).
  - the text UI: the first FAIL shows the block; the same inputs again show the block, the update help, then
    "Still failing: ..." and steps 1-4; other inputs show the block with no guide (negative control);
  - firstrun.py non-interactive (the wizard, the launcher, RecompLauncher): the first failed run's REASON lines are
    the input lines; a second run with the same inputs gives the same lines and then the guide; a run with other
    inputs, the same inputs with a file changed inside (same codes), or a recorded failure over an hour old give no
    guide (controls); a passing run forgets it;
  - the guide: numbered, the player's own title id in step 2, the public GETTING-FILES.md link, no decryption steps;
    the build folder keeps only a 16-digit hash (no paths).
Made-up folders only. Exit 0 = PASS.

    python3 tools/release/test_repeat_guide.py
"""
import io
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from input_check_fixtures import Checks, check_step, fc, fr, make_dump, make_update  # noqa: E402

check = Checks()

lines = fc.repeat_guide("BCES00081", ["D1", "U2"])
check(lines[0].startswith("Still failing: D1, U2. The same check failed again with the same files.")
      and "https://github.com/undecuple/project-pyrrhus/blob/main/docs/GETTING-FILES.md" in lines[0]
      and [ln[:3] for ln in lines[1:]] == ["1. ", "2. ", "3. ", "4. "], "the guide: what failed, the link, steps 1-4",
      lines)
check(f"dev_hdd0{os.sep}game{os.sep}BCES00081" in lines[2], "step 2 names the player's own update folder", lines[2])
text = " ".join(lines).lower()
check(not re.search(r"\b(decrypt (it|the|your)|key|klic|rap|rpcs3 --decrypt|unself|scetool)\b", text),
      "no decryption steps in the guide (public wording)", text)

with tempfile.TemporaryDirectory() as tmp:
    d = make_dump(tmp)
    empty = os.path.join(tmp, "empty")
    os.makedirs(empty)
    other = os.path.join(tmp, "other")
    os.makedirs(other)

    # the text UI
    def ui(answers, build, code="D1"):
        it = iter(answers)
        shown = io.StringIO()

        class A:
            dump = update = eboot = ""
            rpcs3 = ""
            portable = True
        A.build = build

        def ask(q):
            if q.startswith("Disc dump:"):
                return next(it)
            if q.startswith("1.29 update folder"):
                return empty
            if q.startswith("Decrypted EBOOT"):
                return os.path.join(d, "PS3_GAME", "PARAM.SFO")
            if q.startswith("Fix the FAIL lines"):
                r = next(it, None)
                if r is None:
                    raise EOFError
                return r
            return "n"
        root = build + "-root"      # its own install folder: no answers saved by an earlier run
        os.makedirs(root, exist_ok=True)
        fr.interactive(A(), root, os.path.join(tmp, "l.log"), [], ask=ask, out=shown,
                       check=lambda dd, u, e, *t: (1, f"FAIL {code}: synthetic, no PARAM.SFO\nfirst-run checks: FAIL\n"
                                                   "  1.29 update failed: the block\n"), vcheck=lambda c: {})
        return shown.getvalue()
    out = ui([d, ""], os.path.join(tmp, "b1"))           # check, then Enter = check again (same inputs)
    check(out.count("1.29 update failed: the block") == 2 and "Still failing: D1." in out and "\n1. Disc:" in out
          and out.rindex("1.29 update failed: the block") < out.index("Still failing: D1."),
          "text UI: the same inputs again -> the block again, then the guide", out[-800:])
    out = ui([d, ""], os.path.join(tmp, "b3"), code="U1")
    check(out.count(fr.UPDATE_HELP.splitlines()[0]) == 2 and out.rindex(fr.UPDATE_HELP.splitlines()[0])
          < out.index("Still failing: U1."), "text UI: the update help is never left out, the guide comes after it",
          out[-900:])
    out = ui([d, "c", other], os.path.join(tmp, "b2"))   # check, c = change the disc (checked again), then input ends
    check(out.count("1.29 update failed: the block") == 2 and "Still failing" not in out,
          "negative control: other inputs -> the block again, no guide", out[-800:])

    # non-interactive: three runs of firstrun.main with the real check step
    root = os.path.join(tmp, "root")
    os.makedirs(root)

    def run(dump, update):
        out = io.StringIO()
        rc = fr.main(["--dump", dump, "--update", update, "--root", root, "--jobs", "1",
                      "--log-dir", os.path.join(tmp, "dl")], steps=[check_step()], out=out)
        return rc, [ln[7:] for ln in out.getvalue().splitlines() if ln.startswith("REASON ")]
    rc1, r1 = run(d, empty)
    rc2, r2 = run(d, empty)
    rc3, r3 = run(d, other)
    check(rc1 == 1 and r1 and r1[0].startswith("1.29 update failed:"), "first failed run: the input lines", r1)
    gi = next((i for i, x in enumerate(r2) if x.startswith("Still failing: E1, U1, U2, U3.")), -1)
    check(rc2 == 1 and r2 and r2[:gi] == r1 and gi > 0 and r2[gi + 1].startswith("1. Disc:"),
          "the same inputs again: the guide as the REASON lines", r2)
    check(rc3 == 1 and r3 and r3[0].startswith("1.29 update failed:") and not any("Still failing" in x for x in r3),
          "control: other inputs, the input lines, no guide", r3)
    run(d, empty)                                   # recorded: d + empty
    open(os.path.join(empty, "notes.txt"), "w").close()     # the player put a file in the same folder: same codes
    rc5, r5 = run(d, empty)
    check(rc5 == 1 and not any("Still failing" in x for x in r5), "control: same codes, changed content -> no guide", r5)
    kp = os.path.join(root, "build", fr.CHECK_FAIL_KEY)
    k, t = open(kp, encoding="utf-8").read().split()
    with open(kp, "w", encoding="utf-8") as f:
        f.write(f"{k} {int(t) - fr.FAIL_KEY_MAX_AGE - 60}\n")      # the same failure, recorded over an hour ago
    rc6, r6 = run(d, empty)
    check(rc6 == 1 and not any("Still failing" in x for x in r6), "control: an old recorded failure -> no guide", r6)
    rc7, r7 = run(d, empty)
    check(any("Still failing" in x for x in r7), "and the next one, within the hour, gets the guide again", r7)
    key = open(os.path.join(root, "build", fr.CHECK_FAIL_KEY), encoding="utf-8").read().strip()
    check(re.fullmatch(r"[0-9a-f]{16} [0-9]+", key) is not None, "the build folder keeps a 16-digit hash and a time only",
          key)
    u = make_update(tmp)
    rc4, _ = run(d, u)
    check(rc4 == 0 and not os.path.exists(os.path.join(root, "build", fr.CHECK_FAIL_KEY)),
          "a passing run forgets the last failure", rc4)

sys.exit(check.end("test_repeat_guide"))
