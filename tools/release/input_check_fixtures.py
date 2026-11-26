#!/usr/bin/env python3
"""Shared helpers for the first-run input help host tests (2026-11-26) (test_single_iso.py, test_region_line.py,
test_own_title_id.py, test_repeat_guide.py, test_encrypted_eboot.py, test_launcher_result.py,
test_update_diagnosis.py): synthetic fixtures only (made-up folders, a tiny ISO from iso_fixture.py, a stand-in EBOOT
table), no game data. Not a test itself."""
import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402
import firstrun_check as fc  # noqa: E402
from iso_fixture import build_iso  # noqa: E402
from test_firstrun_check import make_dump, make_update, write_elf, write_sfo  # noqa: E402,F401

SMALL = ["--min-psarc-bytes", "1024", "--skip-archive-hash", "--json"]


class Checks:
    def __init__(self):
        self.fails = []

    def __call__(self, ok, msg, detail=""):
        print(("ok   " if ok else "FAIL ") + msg + ("" if ok else f"\n     {str(detail)[:900]}"))
        if not ok:
            self.fails.append(msg)

    def end(self, name):
        print(f"{name}: PASS" if not self.fails else f"{name}: FAIL ({len(self.fails)})")
        return 1 if self.fails else 0


def sfo_bytes(tmp, **kw):
    f = {"APP_VER": "01.01", "CATEGORY": "DG", "TITLE": "Synthetic", "TITLE_ID": "BCUS98116", "VERSION": "01.01"}
    f.update(kw)
    p = os.path.join(tmp, "p.sfo")
    write_sfo(p, f)
    with open(p, "rb") as fh:
        return fh.read()


def make_iso(tmp, path, title_id="BCUS98116"):
    files = {"PS3_DISC.SFB": b".SFB" + b"\0" * 8, "PS3_GAME/PARAM.SFO": sfo_bytes(tmp, TITLE_ID=title_id),
             "PS3_GAME/USRDIR/EBOOT.BIN": fc.SELF_MAGIC + b"\0" * 60,
             "PS3_GAME/USRDIR/data_ps3.psarc": fc.PSARC_MAGIC + b"\0" * 6000}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return build_iso(path, files)


def check_json(args):
    """firstrun_check in-process with --json: -> (rc, reasons, json)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fc.main(args + SMALL)
    j = json.loads(buf.getvalue())
    return rc, j["facts"].get("reasons", []), j


def check_step(extra=()):
    """A check step for firstrun.main(steps=...): the real firstrun_check with the small-fixture options."""
    def cmds(c):
        a = [sys.executable, os.path.join(HERE, "firstrun_check.py"), "--dump", c.dump, *SMALL, *extra]
        if c.update:
            a += ["--update", c.update]
        if c.eboot:
            a += ["--eboot", c.eboot]
        return [a]
    return fr.Step("check", "Checking your game files", 1, cmds, always=True)


def eboot_table(tmp, entries):
    """A stand-in shared EBOOT id table: entries = [(path of a synthetic ELF, title_id, region, app_ver, status)]."""
    rows = [{"title_id": t, "region": g, "app_ver": v, "size": os.path.getsize(p), "sha256": fc.file_sha256(p),
             "status": s} for p, t, g, v, s in entries]
    path = os.path.join(tmp, "eboot_table.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"entries": rows}, f)
    return path
