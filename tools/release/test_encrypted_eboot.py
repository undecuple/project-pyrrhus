#!/usr/bin/env python3
"""Host test for the first-run input help of 2026-11-26, change 5: an EBOOT pick that starts with the SCE header (the encrypted
EBOOT.BIN, not the decrypted ELF) gets one plain line pointing to GETTING-FILES.md ("This is the encrypted EBOOT.BIN;
the port needs the decrypted EBOOT.elf ..."), and that line reaches RecompLauncher's short log (its prepare step
shows the last 10 lines printed, progress lines left out) (a player: "it can't read EBOOT.BIN or EBOOT.ELF").
  - firstrun_check E1 on an SCE file: the line, first in E1's message; on a PS3 ELF and on a non-PS3 file: not
    (negative controls);
  - firstrun.py under RECOMPLAUNCHER=1 with the real check step: the line is in the last 10 non-progress stdout lines.
Made-up files only. Exit 0 = PASS.

    python3 tools/release/test_encrypted_eboot.py
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from input_check_fixtures import Checks, check_json, check_step, fc, fr, make_dump, make_update, write_elf  # noqa: E402

check = Checks()
LINE = "This is the encrypted EBOOT.BIN; the port needs the decrypted EBOOT.elf (see "

with tempfile.TemporaryDirectory() as tmp:
    d, u = make_dump(tmp), make_update(tmp)
    sce = os.path.join(tmp, "picked", "EBOOT.BIN")
    os.makedirs(os.path.dirname(sce))
    with open(sce, "wb") as f:
        f.write(fc.SELF_MAGIC + b"\0" * 4000)
    elf = os.path.join(tmp, "elf", "EBOOT.elf")
    write_elf(elf, 16_381_928)
    junk = os.path.join(tmp, "junk.bin")
    with open(junk, "wb") as f:
        f.write(b"MZ" + b"\0" * 100)

    def e1(path):
        _, _, j = check_json(["--dump", d, "--update", u, "--eboot", path])
        return next((c["message"] for c in j["checks"] if c["code"] == "E1"), "")
    m = e1(sce)
    check(m.startswith(LINE) and "docs/GETTING-FILES.md" in m, "SCE header: one plain line with the GETTING-FILES link",
          m)
    check(LINE not in e1(elf) and LINE not in e1(junk), "negative controls: a PS3 ELF, a non-PS3 file -> not this line")

    out = io.StringIO()
    old = os.environ.get("RECOMPLAUNCHER")
    os.environ["RECOMPLAUNCHER"] = "1"
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root)
        rc = fr.main(["--dump", d, "--update", u, "--eboot", sce, "--root", root, "--jobs", "1",
                      "--log-dir", os.path.join(tmp, "dl")], steps=[check_step()], out=out)
    finally:
        if old is None:
            os.environ.pop("RECOMPLAUNCHER", None)
        else:
            os.environ["RECOMPLAUNCHER"] = old
    shown = [ln for ln in out.getvalue().splitlines() if ln.strip() and not ln.startswith("progress ")][-10:]
    check(rc == 1 and any(LINE in ln for ln in shown), "under RecompLauncher: the line is in its last 10 lines", shown)

sys.exit(check.end("test_encrypted_eboot"))
