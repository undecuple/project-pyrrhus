#!/usr/bin/env python3
"""Fake RPCS3 trees for the wizard walk (wizard_test.sh rpcs3 mode). No game data: PARAM.SFOs from the test helpers
of test_rpcs3_import.py, a real-ELF-magic EBOOT.elf, an encrypted-magic (SCE) EBOOT.BIN, a fake save.

    fake_rpcs3.py OUTDIR      writes OUTDIR/{good,noupdate,wrong,manual,manual-eu}/ (noupdate/update-129 = the fix;
                              manual-eu = the manual dump and update as the European disc BCES00081)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import test_rpcs3_import as t  # noqa: E402

SCE = b"SCE\0" + b"\0" * 28


def main():
    out = Path(sys.argv[1])
    root, disc = t.tree(out / "good", name="rpcs3")          # complete; the disc is outside (asked about)
    (root / "dev_hdd0" / "game" / t.T / "USRDIR" / "EBOOT.BIN").write_bytes(SCE)
    t.add_save(root)
    root2, _ = t.tree(out / "noupdate", name="rpcs3", update=None)   # no 1.29 update installed
    t.add_save(root2)
    u = out / "noupdate" / "update-129"      # what the walk copies into root2's dev_hdd0/game/BCUS98116 to fix it
    t.w(u / "PARAM.SFO", t.sfo(TITLE_ID=t.T, APP_VER="01.29", CATEGORY="GD"))
    t.w(u / "USRDIR" / "EBOOT.BIN", SCE)
    t.w(u / "USRDIR" / "EBOOT.elf", t.ELF + b"update")
    (out / "wrong").mkdir(parents=True, exist_ok=True)
    (out / "wrong" / "readme.txt").write_text("not an RPCS3 folder\n")
    # the manual path: dump, update and an EBOOT.BIN that is still encrypted
    m = out / "manual"
    t.w(m / "dump" / "PS3_GAME" / "PARAM.SFO", t.sfo(TITLE_ID=t.T, VERSION="01.01", APP_VER="01.01"))
    t.w(m / "dump" / "PS3_GAME" / "USRDIR" / "data_ps3.psarc", b"PSAR")
    t.w(m / "update" / "PARAM.SFO", t.sfo(TITLE_ID=t.T, APP_VER="01.29", CATEGORY="GD"))
    t.w(m / "update" / "USRDIR" / "EBOOT.BIN", SCE)
    t.w(m / "update" / "USRDIR" / "added_data_ps3.psarc", b"PSAR")
    t.w(m / "update" / "USRDIR" / "EBOOT.elf", t.ELF + b"update")
    t.w(m / "update" / "USRDIR" / "patch_data_ps3" / "readme.txt", b"fixture")   # the update page's folder
    # the same manual set as the European disc (the EBOOT page's untested-region WARN box)
    e = out / "manual-eu"
    t.w(e / "dump" / "PS3_GAME" / "PARAM.SFO", t.sfo(TITLE_ID="BCES00081", VERSION="01.01", APP_VER="01.01"))
    t.w(e / "dump" / "PS3_GAME" / "USRDIR" / "data_ps3.psarc", b"PSAR")
    t.w(e / "update" / "PARAM.SFO", t.sfo(TITLE_ID="BCES00081", APP_VER="01.29", CATEGORY="GD"))
    t.w(e / "update" / "USRDIR" / "EBOOT.BIN", SCE)
    t.w(e / "update" / "USRDIR" / "added_data_ps3.psarc", b"PSAR")
    t.w(e / "update" / "USRDIR" / "patch_data_ps3" / "readme.txt", b"fixture")
    # RPCS3 lists the disc as a ".dec.iso" file. A tiny synthetic decrypted ISO (no game data); its psarc record
    # is patched to 6.1 GiB and the file extended sparsely (no disk used) so the size check of the real ISO reader passes.
    import iso_fixture
    import struct
    import firstrun_check as fc
    iroot, _ = t.tree(out / "iso", name="rpcs3", elf=False, disc=False)
    isof = out / "iso" / "discs" / "Killzone 2 (USA).dec.iso"
    isof.parent.mkdir(parents=True, exist_ok=True)
    iso_fixture.build_iso(str(isof), multi={"PS3_GAME/USRDIR/data_ps3.psarc": 3000}, files={"PS3_DISC.SFB": b".SFB" + b"\0" * 8,
                                      "PS3_GAME/PARAM.SFO": t.sfo(TITLE_ID=t.T, VERSION="01.01", APP_VER="01.01"),
                                      "PS3_GAME/USRDIR/EBOOT.BIN": fc.SELF_MAGIC + b"\0" * 60,
                                      "PS3_GAME/USRDIR/data_ps3.psarc": fc.PSARC_MAGIC + b"\0" * 6000})
    data = bytearray(isof.read_bytes())
    ext = 3_300_000_000          # two extents (an ISO 9660 size is 32 bit): 6.6e9 bytes in all, over the 6 GiB minimum
    i = data.index(b"DATA_PS3.PSARC;1") - 33          # the first directory record; the second follows it
    for _ in range(2):
        data[i + 10:i + 18] = struct.pack("<I", ext) + struct.pack(">I", ext)
        i += data[i]
    big = 2 * ext
    isof.write_bytes(bytes(data))
    with open(isof, "r+b") as f:
        f.truncate(len(data) + big)
    t.w(iroot / "config" / "games.yml", f"{t.T}: {isof}\n")
    ue = out / "iso" / "update-elf"
    t.w(ue / "EBOOT.elf", t.ELF + b"update")     # what the walk copies into the update's USRDIR (the third step)
    print("ok", out)


main()
