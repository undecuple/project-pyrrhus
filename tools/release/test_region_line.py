#!/usr/bin/env python3
"""Host test for the first-run input help of 2026-11-26, change 2: the disc, the update and the EBOOT are compared by title id (US
BCUS98116, Europe BCES00081, Asia BCAS20066, Japan BCJS30032) and a mismatch is said plainly first ("Your disc is
the European version (BCES00081), but this EBOOT is from the US release (BCUS98116). ...").
  - a European disc (a synthetic ISO) with a stand-in US 1.01 EBOOT (matched through a stand-in id table): the EBOOT
    part; with the US update too: both parts in one sentence;
  - a European disc and a European update: no region line (negative control); a 1.29 EBOOT matched for all four
    releases (the real 1.29 EBOOT is one file for every region) is never another region's (control);
  - an unknown disc id: no region line (control).
Made-up folders only. Exit 0 = PASS.

    python3 tools/release/test_region_line.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from input_check_fixtures import Checks, check_json, eboot_table, fc, make_iso, make_update, write_elf  # noqa: E402

check = Checks()
WANT = "Your disc is the European version (BCES00081), but "

with tempfile.TemporaryDirectory() as tmp:
    iso = make_iso(tmp, os.path.join(tmp, "disc", "eu.iso"), "BCES00081")
    u_us = make_update(os.path.join(tmp, "us"))
    u_eu = make_update(os.path.join(tmp, "eu"), title_id="BCES00081")
    e101 = os.path.join(tmp, "e101", "EBOOT.elf")
    write_elf(e101, 16_381_928)                     # the US disc's decrypted 1.01 EBOOT's size, synthetic bytes
    e129 = os.path.join(tmp, "e129", "EBOOT.elf")
    write_elf(e129, 16_455_144)
    with open(e129, "ab") as f:
        f.write(b"x")
    tbl = eboot_table(tmp, [(e101, "BCUS98116", "US", "01.01", "tested")]
                      + [(e129, t, g, "01.29", "tested") for t, g in
                         (("BCUS98116", "US"), ("BCES00081", "Europe"), ("BCAS20066", "Asia"), ("BCJS30032", "Japan"))])

    rc, rs, _ = check_json(["--dump", iso, "--update", u_eu, "--eboot", e101, "--hashes", tbl])
    check(rc == 1 and rs and rs[0] == WANT + "this EBOOT is from the US release (BCUS98116). The disc, the update and "
          "the EBOOT must all come from the same release.", "EU disc + US 1.01 EBOOT: the EBOOT part, first", rs)
    rc, rs, _ = check_json(["--dump", iso, "--update", u_us, "--eboot", e101, "--hashes", tbl])
    check(rc == 1 and rs and rs[0].startswith(WANT + "this update is from the US release (BCUS98116) and this EBOOT is "
                                              "from the US release (BCUS98116)."), "EU disc + US update + US EBOOT: both",
          rs)
    rc, rs, _ = check_json(["--dump", iso, "--update", u_eu, "--eboot", e129, "--hashes", tbl])
    check(not any(r.startswith("Your disc is") for r in rs), "control: EU disc, EU update, the all-region 1.29 EBOOT: "
          "no region line", rs)

    class R:      # a bare report: facts only
        facts = {"disc": {"TITLE_ID": "NPUB30001"}, "update": {"TITLE_ID": "BCUS98116"}}
    check(fc.region_line(R()) == "", "control: an unknown disc id gives no region line")
    R.facts = {"disc": {"TITLE_ID": "BCJS30032"}, "update": {"TITLE_ID": "BCJS30032"},
               "eboot_elf": {"match": {"title_ids": ["BCUS98116"]}}}
    check(fc.region_line(R()) == "Your disc is the Japanese version (BCJS30032), but this EBOOT is from the US release "
          "(BCUS98116). The disc, the update and the EBOOT must all come from the same release.",
          "the sentence names the player's release and the EBOOT's", fc.region_line(R()))

sys.exit(check.end("test_region_line"))
