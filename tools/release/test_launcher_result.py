#!/usr/bin/env python3
"""Host test for the first-run input help of 2026-11-26, change 6: the first run's check result reaches <install>/logs/launcher.log
(a player's launcher.log held only five "start: first-build" lines): one "first-run: RESULT ok=0 step=check ...
fails=E1,U1,..." line with the FAIL ids and no paths; under RECOMPLAUNCHER=1 the ids are also the last stdout line
(the launcher's short log ends on them).
  - a failed check: the line, its ids, no install or game path in it; RECOMPLAUNCHER=1: the last stdout line names
    the ids;
  - negative controls: without RECOMPLAUNCHER no such stdout line; a passing run logs RESULT ok=1 with no fails=.
Made-up folders only. Exit 0 = PASS.

    python3 tools/release/test_launcher_result.py
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from input_check_fixtures import Checks, check_step, fr, make_dump, make_update  # noqa: E402

check = Checks()

with tempfile.TemporaryDirectory() as tmp:
    d, u = make_dump(tmp), make_update(tmp)
    empty = os.path.join(tmp, "empty-update")
    os.makedirs(empty)
    root = os.path.join(tmp, "Install Folder")
    os.makedirs(root)
    log = os.path.join(root, "logs", "launcher.log")

    def run(update, env):
        out = io.StringIO()
        old = os.environ.get("RECOMPLAUNCHER")
        if env:
            os.environ["RECOMPLAUNCHER"] = "1"
        else:
            os.environ.pop("RECOMPLAUNCHER", None)
        try:
            rc = fr.main(["--dump", d, "--update", update, "--root", root, "--jobs", "1",
                          "--log-dir", os.path.join(tmp, "dl")], steps=[check_step()], out=out)
        finally:
            os.environ.pop("RECOMPLAUNCHER", None)
            if old is not None:
                os.environ["RECOMPLAUNCHER"] = old
        lines = open(log, encoding="utf-8").read().splitlines() if os.path.isfile(log) else []
        return rc, out.getvalue().splitlines(), lines[-1] if lines else ""

    rc, out, last = run(empty, True)
    check(rc == 1 and " first-run: RESULT ok=0 step=check " in last and "fails=E1,U1,U2,U3" in last,
          "a failed check: launcher.log gets the RESULT line and the FAIL ids", last)
    check(tmp not in last and "Install Folder" not in last, "no path in that line", last)
    check(out and out[-1].startswith("The check stopped the setup: E1, U1, U2, U3."),
          "RECOMPLAUNCHER=1: the ids are the last stdout line", out[-3:])
    rc, out, last = run(empty, False)
    check(rc == 1 and "fails=E1,U1,U2,U3" in last and not any(ln.startswith("The check stopped") for ln in out),
          "negative control: without RecompLauncher no such stdout line (the log line stays)", out[-3:])
    rc, out, last = run(u, True)
    check(rc == 0 and " first-run: RESULT ok=1 step=" in last and "fails=" not in last
          and not any(ln.startswith("The check stopped") for ln in out), "control: a passing run, ok=1 and no ids", last)

sys.exit(check.end("test_launcher_result"))
