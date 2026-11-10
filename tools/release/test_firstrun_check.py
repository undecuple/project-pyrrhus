#!/usr/bin/env python3
"""Host test for tools/release/firstrun_check.py (from Project Helghast) on synthetic fixtures (no game data: a temp dir
holds a made-up PARAM.SFO, a 4-byte 'SCE' EBOOT.BIN, a 'PSAR' header and a 64-byte PPC64 ELF header). Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_firstrun_check.py

Cases: a complete dump + update + 1.29-sized ELF passes; wrong TITLE_ID fails; missing PARAM.SFO fails; a dump
whose EBOOT.BIN is already an ELF passes; a v1.01-sized ELF fails E1 on the 1.29 build (naming the update's USRDIR); a wrong-machine ELF fails; a truncated psarc
fails; no --update warns; --json has the documented shape; H1 (EBOOT SHA-256): the shipped hashes file
with empty values warns "unknown yet", a matching hash is OK, a mismatch warns with the size and both hashes (exit 0),
an unreadable hashes file warns, a failed E1 gives no H1; an earlier change: the shipped file is the shared per-build list
(1.29 entry naming all four discs), its match is OK, a mismatch warns, a build not listed warns "unknown yet", a
build not known-good is no match, each malformed entry (and a list mixed with old keys, or a duplicate app_ver) is
refused with a message naming builds[i] and the fault, and the old {"1.29": {...}} form still loads. D53: the European, Asian and Japanese discs pass with a D1
WARN "untested", each region's disc VERSION and disc EBOOT size, every mixed region pair fails U1 naming both,
the shipped psarc_sha256.json has one entry per disc, A1 per disc (another disc's archive = a mixed dump, FAIL).
"""
import json
import os
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firstrun_check as fc  # noqa: E402

FAILS = []


def write_sfo(path, fields):
    """Minimal PARAM.SFO writer (format 0x204 utf8 strings, 0x404 ints), the inverse of fc.read_sfo."""
    keys = b"".join(k.encode() + b"\0" for k in fields)
    data, idx, doff = b"", b"", 0
    koff = 0
    for k, v in fields.items():
        if isinstance(v, int):
            raw, fmt, ln = struct.pack("<I", v), 0x404, 4
        else:
            raw = v.encode() + b"\0"
            fmt, ln = 0x204, len(raw)
        padded = raw + b"\0" * ((4 - len(raw) % 4) % 4)
        idx += struct.pack("<HHIII", koff, fmt, ln, len(padded), doff)
        koff += len(k) + 1
        data += padded
        doff += len(padded)
    kt = 20 + len(idx)
    dt = kt + len(keys)
    dt += (4 - dt % 4) % 4
    hdr = struct.pack("<4sIIII", b"\0PSF", 0x101, kt, dt, len(fields))
    blob = hdr + idx + keys
    blob += b"\0" * (dt - len(blob)) + data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(blob)


def write_elf(path, size, machine=fc.EM_PPC64, cls=2, data=2):
    h = bytearray(64)
    h[:4] = fc.ELF_MAGIC
    h[4], h[5], h[6] = cls, data, 1
    h[18:20] = struct.pack(">H" if data == 2 else "<H", machine)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(h)
        f.truncate(size)


def seg_elf(path, segs, gap=16, tail=b"", size=None):
    """A 64-bit big-endian PPC64 ELF with program headers: segs = [(p_type, p_vaddr, p_paddr, data, p_memsz)], the
    data laid out after the headers with gap bytes before each; tail appended; then truncated or padded to size."""
    phoff, n = 64, len(segs)
    off = phoff + 56 * n
    body, phs = b"", b""
    for typ, va, pa, data, mem in segs:
        off += gap
        body += b"\0" * gap + data
        phs += struct.pack(">IIQQQQQQ", typ, 5, off, va, pa, len(data), mem, 0x10000)
        off += len(data)
    h = bytearray(64)
    h[:4] = fc.ELF_MAGIC
    h[4], h[5], h[6] = 2, 2, 1
    h[18:20] = struct.pack(">H", fc.EM_PPC64)
    struct.pack_into(">Q", h, 0x20, phoff)
    struct.pack_into(">HH", h, 0x36, 56, n)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(h) + phs + body + tail)
        if size is not None:
            f.truncate(size)


def make_dump(root, title_id="BCUS98116", eboot_magic=fc.SELF_MAGIC, psarc_bytes=4096, version="01.01"):
    d = os.path.join(root, "dump")
    write_sfo(os.path.join(d, "PS3_GAME", "PARAM.SFO"),
              {"APP_VER": "01.01", "CATEGORY": "DG", "TITLE": "Synthetic", "TITLE_ID": title_id, "VERSION": version})
    os.makedirs(os.path.join(d, "PS3_GAME", "USRDIR"))
    if eboot_magic == fc.ELF_MAGIC:
        write_elf(os.path.join(d, "PS3_GAME", "USRDIR", "EBOOT.BIN"), 64)
    else:
        open(os.path.join(d, "PS3_GAME", "USRDIR", "EBOOT.BIN"), "wb").write(eboot_magic + b"\0" * 60)
    with open(os.path.join(d, "PS3_GAME", "USRDIR", "data_ps3.psarc"), "wb") as f:
        f.write(fc.PSARC_MAGIC)
        f.truncate(psarc_bytes)
    return d


def make_update(root, app_ver="01.29", elf_size=16_455_144, title_id="BCUS98116"):
    u = os.path.join(root, "hdd0", "game", title_id)
    write_sfo(os.path.join(u, "PARAM.SFO"),
              {"APP_VER": app_ver, "CATEGORY": "GD", "TITLE": "Synthetic", "TITLE_ID": title_id})
    os.makedirs(os.path.join(u, "USRDIR"))
    open(os.path.join(u, "USRDIR", "EBOOT.BIN"), "wb").write(fc.SELF_MAGIC + b"\0" * 60)
    open(os.path.join(u, "USRDIR", fc.UPDATE_DATA), "wb").write(fc.PSARC_MAGIC + b"\0" * 60)
    os.makedirs(os.path.join(u, "USRDIR", fc.UPDATE_PATCH_DIR), exist_ok=True)
    write_elf(os.path.join(u, "USRDIR", "EBOOT.elf"), elf_size)
    return u


def run(args):
    """Run main() with captured stdout; returns (exit code, stdout)."""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fc.main(args)
    return rc, buf.getvalue()


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name} {detail}")
        FAILS.append(name)


def levels(out, code):
    return {ln.split()[0] for ln in out.splitlines() if ln.split()[1:2] == [code + ":"]}


def main():
    tmp = tempfile.mkdtemp(prefix="kz2-firstrun-")
    try:
        small = ["--min-psarc-bytes", "1024"]
        d = make_dump(tmp)
        u = make_update(tmp)
        rc, out = run(["--dump", d, "--update", u] + small)
        check("complete set passes", rc == 0 and "FAIL" not in out, out)
        check("1.29 ELF recognised", "1.29" in out and levels(out, "E1") == {"OK"}, out)
        check("update APP_VER ok", levels(out, "U1") == {"OK"}, out)
        # U3 FAILs since issue #16 ( the 1.29 EBOOT without the update's data stops at the main menu)
        ud = os.path.join(u, "USRDIR", fc.UPDATE_DATA)
        os.rename(ud, ud + ".bak")
        rc, out = run(["--dump", d, "--update", u] + small)
        check("U3 no update data archive fails", rc == 1 and "FAIL" in out and levels(out, "U3") == {"FAIL"}
              and "main menu" in out, out)
        os.rename(ud + ".bak", ud)
        pd = os.path.join(u, "USRDIR", fc.UPDATE_PATCH_DIR)
        os.rename(pd, pd + ".bak")
        rc, out = run(["--dump", d, "--update", u] + small)
        check("U3 no patch_data_ps3 fails", rc == 1 and levels(out, "U3") >= {"FAIL"}, out)
        os.rename(pd + ".bak", pd)

        rc, out = run(["--dump", d, "--update", u, "--json"] + small)
        j = json.loads(out)
        check("json shape", j["ok"] is True and {"code", "level", "message"} <= set(j["checks"][0])
              and j["facts"]["eboot_elf"]["version"] == "1.29" and j["facts"]["disc"]["TITLE_ID"] == "BCUS98116", out)

        rc, out = run(["--dump", d] + small)
        check("no --update warns", "WARN U0" in out, out)
        check("default ELF falls back to the dump (missing -> FAIL E1)", rc == 1 and "FAIL E1" in out, out)

        rc, out = run(["--dump", d, "--update", u, "--eboot", os.path.join(tmp, "nope.elf")] + small)
        check("missing --eboot fails", rc == 1 and "FAIL E1" in out, out)

        rc, out = run(["--dump", make_dump(os.path.join(tmp, "eu"), title_id="BCES01070"), "--update", u] + small)
        check("wrong TITLE_ID fails", rc == 1 and "FAIL D1" in out, out)
        check("wrong TITLE_ID is named with its title (Project Helghast v0.1.2)",
              "this is BCES01070 (Synthetic), not Killzone 2" in out and "BCUS98116" in out, out)

        # disc VERSION: 01.01 is the known disc; 02.00 = the Killzone Trilogy disc (KZ2 inside, untested): WARN only
        tri = make_dump(os.path.join(tmp, "tri"), version="02.00")
        rc, out = run(["--dump", tri, "--update", u] + small)
        check("Trilogy disc (VERSION 02.00) warns, named, no FAIL", rc == 0 and levels(out, "D1") == {"OK", "WARN"}
              and "Killzone Trilogy disc" in out and "Untested" in out, out)
        rc, out = run(["--dump", make_dump(os.path.join(tmp, "v102"), version="01.02"), "--update", u] + small)
        check("another disc VERSION warns", rc == 0 and "another printing?" in out, out)
        check("the known disc VERSION gives no version note",
              "VERSION" not in run(["--dump", d, "--update", u] + small)[1])

        # the update must carry the disc's title id
        ux_id = make_update(os.path.join(tmp, "uid"), title_id="BCES00081")
        rc, out = run(["--dump", d, "--update", ux_id] + small)
        check("update of another title fails U1 naming it", rc == 1 and "FAIL" in levels(out, "U1")
              and "BCES00081" in out, out)
        check("a mixed set names both regions and the disc's own update folder",
              "this is the European update (BCES00081), but the disc dump is the US disc (BCUS98116)" in out
              and os.path.join("dev_hdd0", "game", "BCUS98116") in out, out)
        # D53: the European, Asian and Japanese discs are accepted as untested, each with its own region's update
        for tid, g in fc.REGIONS.items():
            if g["tested"]:
                continue
            rd = make_dump(os.path.join(tmp, "r" + tid), title_id=tid, version=g["version"])
            ru = make_update(os.path.join(tmp, "ru" + tid), title_id=tid)
            rc, out = run(["--dump", rd, "--update", ru, "--eboot", os.path.join(ru, "USRDIR", "EBOOT.elf")] + small)
            check(f"{g['region']} disc {tid} with its own update passes with a D1 WARN 'untested'", rc == 0
                  and levels(out, "D1") == {"OK", "WARN"} and levels(out, "U1") == {"OK"} and "untested" in out
                  and f"the {g['adj']} disc ({tid})" in out and "another printing?" not in out, out)
            rc, out = run(["--dump", make_dump(os.path.join(tmp, "rv" + tid), title_id=tid, version="09.99"),
                           "--update", ru] + small)
            check(f"{g['region']} disc: another VERSION than {g['version']} warns", rc == 0
                  and f"the known {g['adj']} disc is {g['version']} (another printing?)" in out, out)
        j = json.loads(run(["--dump", make_dump(os.path.join(tmp, "rj"), title_id="BCJS30032", version="01.00"),
                            "--update", make_update(os.path.join(tmp, "ruj"), title_id="BCJS30032"), "--json"] + small)[1])
        check("--json: the disc's region and untested flag", j["facts"]["disc"].get("region") == "Japan"
              and j["facts"]["disc"].get("untested") is True, j["facts"]["disc"])
        j = json.loads(run(["--dump", d, "--update", u, "--json"] + small)[1])
        check("--json: the US disc is tested (no untested flag)", j["facts"]["disc"].get("region") == "US"
              and "untested" not in j["facts"]["disc"]
              and not any("untested" in c["message"] for c in j["checks"]), j["facts"]["disc"])
        # every mixed pair (disc of one region, update of another) fails U1 naming both
        mixed_ok = []
        for dt in fc.REGIONS:
            for ut in fc.REGIONS:
                if dt == ut:
                    continue
                rep = fc.Report()
                fc.check_update(rep, make_update(os.path.join(tmp, f"mx{dt}{ut}"), title_id=ut), dt)
                u1 = [c for c in rep.checks if c["code"] == "U1" and c["level"] == "FAIL"]
                mixed_ok.append(bool(u1) and fc.REGIONS[ut]["adj"] + " update" in u1[0]["message"]
                                and fc.disc_label(dt) in u1[0]["message"])
        check("all 12 mixed region pairs fail U1 naming both", len(mixed_ok) == 12 and all(mixed_ok), mixed_ok)
        # D2: each region's disc EBOOT.BIN size (Japan's differs)
        for tid, size, warn in (("BCJS30032", 16_385_320, False), ("BCJS30032", 16_384_360, True),
                                ("BCAS20066", 16_384_360, False), (None, 16_384_360, False)):
            rep = fc.Report()
            fc.check_disc_eboot(rep, (size, fc.SELF_MAGIC), tid)
            check(f"D2 disc EBOOT size {size:,} on {tid}: {'WARN' if warn else 'no WARN'}",
                  any(c["level"] == "WARN" for c in rep.checks) == warn, rep.checks)
        check("ACCEPTED_TEXT names the four discs", fc.ACCEPTED_TEXT == "BCUS98116 (US), BCES00081 (Europe), "
              "BCAS20066 (Asia) or BCJS30032 (Japan)", fc.ACCEPTED_TEXT)

        # folder picks one or two levels too deep (Project Helghast v0.1.2)
        for sub in (("PS3_GAME",), ("PS3_GAME", "USRDIR"), ("ps3_game", "usrdir")):
            pick = os.path.join(d, *[s if os.path.isdir(os.path.join(d, *sub[:i], s)) else s.upper()
                                     for i, s in enumerate(sub)])
            check(f"resolve_dump: {'/'.join(sub)} -> the folder above PS3_GAME", fc.resolve_dump(pick) == d,
                  fc.resolve_dump(pick))
        check("resolve_dump leaves the right folder and unknown ones alone",
              fc.resolve_dump(d) == d and fc.resolve_dump(tmp) == tmp and fc.resolve_dump("") == "")
        check("resolve_update: USRDIR -> the update folder", fc.resolve_update(os.path.join(u, "USRDIR")) == u
              and fc.resolve_update(u) == u)
        rc, out = run(["--dump", os.path.join(d, "PS3_GAME", "USRDIR"), "--update", os.path.join(u, "USRDIR")] + small)
        check("a check given PS3_GAME/USRDIR and the update's USRDIR passes", rc == 0 and "FAIL" not in out, out)

        # OneDrive (adapted from Project Helghast v0.1.2): O1 install/build folder, O2 online-only files, O3 INFO
        env = {"OneDrive": "C:\\Users\\someone\\OneDrive", "OneDriveCommercial": "D:\\Work\\OneDrive - Corp"}
        check("O1 prefix match, case-insensitive",
              fc.onedrive_root_of("c:\\users\\SOMEONE\\onedrive\\Desktop\\Project Pyrrhus", env) == env["OneDrive"]
              and fc.onedrive_root_of("D:/Work/OneDrive - Corp/x", env) == env["OneDriveCommercial"])
        check("O1 whole components only, empty env is nothing",
              fc.onedrive_root_of("C:\\Users\\someone\\OneDrive2\\x", env) == ""
              and fc.onedrive_root_of("C:\\Users\\someone\\Programs", {}) == "")
        r = fc.Report()
        fc.check_onedrive_tree(r, "C:\\Users\\someone\\OneDrive\\Desktop\\Project Pyrrhus", "C:\\b\\build", env)
        check("O1 fails for a root inside OneDrive only", [(c["code"], c["level"]) for c in r.checks] == [("O1", "FAIL")]
              and "outside OneDrive" in r.checks[0]["message"] and "Project Pyrrhus" in r.checks[0]["message"], r.checks)
        r = fc.Report()
        fc.check_onedrive_tree(r, "C:\\ok\\Project Pyrrhus", "D:\\Work\\OneDrive - Corp\\build", env)
        check("O1 fails for a build dir inside OneDrive", len(r.checks) == 1 and "build folder" in r.checks[0]["message"])
        # P1 (the same failure reported on Project Helghast (#20)): '[', ']' or ';' in the path
        for bad in ("D:\\games\\recomp[\\Project Pyrrhus", "D:\\games\\x]y", "D:\\a;b\\Project Pyrrhus"):
            r = fc.Report()
            fc.check_path_chars(r, bad, "C:\\b\\build")
            check(f"P1 fails for the install folder {bad}", [(c["code"], c["level"]) for c in r.checks] == [("P1", "FAIL")]
                  and "cannot handle" in r.checks[0]["message"] and "Programs" in r.checks[0]["message"], r.checks)
        r = fc.Report()
        fc.check_path_chars(r, "C:\\Games\\Project Pyrrhus (copy) #2", "D:\\b[1]\\build")
        check("P1: parentheses and # are fine; a build folder with [ fails", [c["code"] for c in r.checks] == ["P1"]
              and "build folder" in r.checks[0]["message"] and "'[' and ']'" in r.checks[0]["message"], r.checks)
        rc, out = run(["--dump", d, "--update", u, "--root", os.path.join(tmp, "inst[1]")] + small)
        check("P1 from the command line: --root with [ fails", rc == 1 and "P1" in out and "cannot handle" in out, out)
        old = os.environ.get("OneDrive")
        os.environ["OneDrive"] = os.path.join(tmp, "hdd0")      # the update folder sits inside the fake OneDrive
        real_attr = fc.file_attributes
        try:
            rc, out = run(["--dump", d, "--update", u] + small)
            check("O3 INFO only when inside OneDrive but local", rc == 0 and levels(out, "O3") == {"OK"}
                  and "INFO" in out and "O2:" not in out, out)
            fc.file_attributes = lambda p: 0x400000 if p.endswith("data_ps3.psarc") else 0
            rc, out = run(["--dump", d, "--update", u, "--json"] + small)
            j = json.loads(out)
            o2 = [c for c in j["checks"] if c["code"] == "O2"]
            check("O2 fails for an online-only psarc, with the fix, and reads nothing else",
                  rc == 1 and not j["ok"] and len(o2) == 1 and o2[0]["level"] == "FAIL"
                  and "Always keep on this device" in o2[0]["message"] and "data_ps3.psarc" in o2[0]["message"]
                  and not any(c["code"] in ("D1", "D3", "A1", "E1") for c in j["checks"]), out)
            for bit in (0x40000, 0x1000):
                fc.file_attributes = lambda p, b=bit: b if p.endswith("PARAM.SFO") else 0
                rc, out = run(["--dump", d, "--update", u] + small)
                check(f"O2 fails for attribute 0x{bit:x}", rc == 1 and levels(out, "O2") == {"FAIL"}, out)
        finally:
            fc.file_attributes = real_attr
            if old is None:
                del os.environ["OneDrive"]
            else:
                os.environ["OneDrive"] = old
        sp = make_dump(os.path.join(tmp, "od-split"))
        pp = os.path.join(sp, "PS3_GAME", "USRDIR", "data_ps3.psarc")
        os.replace(pp, pp + ".66600")
        open(pp + ".66601", "wb").write(b"\0" * 16)
        check("O2 looks at every split part of the archive",
              [os.path.basename(x) for x in fc.game_files(sp, "", "")][2:] == ["data_ps3.psarc.66600", "data_ps3.psarc.66601"])
        rc, out = run(["--dump", d, "--update", u] + small + ["--root", "/x/OneDrive/p", "--build", os.path.join(tmp, "bx")])
        check("--root without OneDrive env passes", rc == 0 and "O1:" not in out, out)

        # decrypted ISO as --dump (adapted from Project Helghast v0.1.2; iso_fixture.py builds tiny images): the same D-codes
        # from inside the image; I1 = encrypted, I2 = unreadable; no A1 here (firstrun.py hashes while copying)
        from iso_fixture import build_iso
        i = os.path.join(tmp, "iso")
        os.makedirs(i)
        sfo = os.path.join(i, "p.sfo")

        def sfo_of(**kw):
            f = {"APP_VER": "01.01", "CATEGORY": "DG", "TITLE": "Synthetic", "TITLE_ID": "BCUS98116", "VERSION": "01.01"}
            f.update(kw)
            write_sfo(sfo, f)
            return open(sfo, "rb").read()
        files = {"PS3_DISC.SFB": b".SFB" + b"\0" * 8, "PS3_GAME/PARAM.SFO": sfo_of(),
                 "PS3_GAME/USRDIR/EBOOT.BIN": fc.SELF_MAGIC + b"\0" * 60,
                 "PS3_GAME/USRDIR/data_ps3.psarc": fc.PSARC_MAGIC + b"\0" * 6000}
        iso = build_iso(os.path.join(i, "game.iso"), files, multi={"PS3_GAME/USRDIR/data_ps3.psarc": 2048})
        rc, out = run(["--dump", iso, "--update", u] + small)
        check("ISO: complete decrypted ISO passes", rc == 0 and "OK   D1:" in out and "OK   D3:" in out
              and "inside the ISO" in out and "A1:" not in out, out)
        check("ISO: INFO line names the image", "dump: decrypted ISO game.iso" in out, out)
        rc, out = run(["--dump", iso, "--update", u, "--json"] + small)
        j = json.loads(out)
        check("ISO: facts read from inside", j["facts"]["disc"]["TITLE_ID"] == "BCUS98116"
              and j["facts"]["psarc"]["size"] == 6004 and j["facts"]["iso"] == os.path.abspath(iso), out)
        rc, out = run(["--dump", iso, "--update", u, "--min-psarc-bytes", "99999"])
        check("ISO: small psarc fails D3", rc == 1 and "FAIL D3" in out, out)
        tri = dict(files, **{"PS3_GAME/PARAM.SFO": sfo_of(VERSION="02.00")})
        rc, out = run(["--dump", build_iso(os.path.join(i, "tri.iso"), tri), "--update", u] + small)
        check("ISO: Trilogy disc warns D1", rc == 0 and "WARN D1" in out and "Killzone Trilogy disc" in out, out)
        other = dict(files, **{"PS3_GAME/PARAM.SFO": sfo_of(TITLE_ID="NPUB30001", TITLE="Other")})
        rc, out = run(["--dump", build_iso(os.path.join(i, "o.iso"), other)] + small)
        check("ISO: another title id fails D1 naming it", rc == 1 and "FAIL D1" in out and "NPUB30001 (Other)" in out, out)
        nofile = {k: v for k, v in files.items() if "psarc" not in k}
        rc, out = run(["--dump", build_iso(os.path.join(i, "n.iso"), nofile)] + small)
        check("ISO: no psarc fails D3", rc == 1 and "FAIL D3" in out and "no PS3_GAME/USRDIR/data_ps3.psarc" in out, out)
        rc, out = run(["--dump", build_iso(os.path.join(i, "e.iso"), {"PS3_DISC.SFB": b"x"})] + small)
        check("ISO: no PARAM.SFO fails D1", rc == 1 and "FAIL D1" in out, out)
        scrambled = dict(files, **{"PS3_GAME/USRDIR/data_ps3.psarc": bytes(range(200)) * 30})
        rc, out = run(["--dump", build_iso(os.path.join(i, "s.iso"), scrambled)] + small)
        check("ISO: unreadable files are 'encrypted' (I1)",
              rc == 1 and "FAIL I1: this ISO is encrypted; use a decrypted dump" in out, out)
        scrambled = dict(files, **{"PS3_GAME/PARAM.SFO": bytes(range(100))})
        rc, out = run(["--dump", build_iso(os.path.join(i, "s2.iso"), scrambled)] + small)
        check("ISO: unreadable PARAM.SFO is 'encrypted' (I1)", rc == 1 and "FAIL I1" in out, out)
        reg = bytearray(2048 * 40)
        reg[0:4] = struct.pack(">I", 2)
        reg[8:24] = struct.pack(">IIII", 0, 15, 16, 30)
        open(os.path.join(i, "r.iso"), "wb").write(bytes(reg))
        rc, out = run(["--dump", os.path.join(i, "r.iso")] + small)
        check("ISO: region table image is I1", rc == 1 and "FAIL I1" in out, out)
        open(os.path.join(i, "x.iso"), "wb").write(b"hello" * 100000)
        rc, out = run(["--dump", os.path.join(i, "x.iso")] + small)
        check("ISO: not an ISO is I2, not 'encrypted'", rc == 1 and "FAIL I2" in out and "FAIL I1" not in out, out)   # not bare "I1": a random temp path can hold it (nix-shell.NZASI1)
        data = open(iso, "rb").read()
        open(os.path.join(i, "t.iso"), "wb").write(data[:len(data) - 3000])
        rc, out = run(["--dump", os.path.join(i, "t.iso")] + small)
        check("ISO: truncated image fails D3", rc == 1 and "FAIL D3" in out and "truncated" in out, out)
        old = os.environ.get("OneDrive")
        os.environ["OneDrive"] = i
        real_attr = fc.file_attributes
        fc.file_attributes = lambda p: 0x400000 if p.endswith(".iso") else 0
        try:
            rc, out = run(["--dump", iso, "--update", u] + small)
            check("ISO: an online-only ISO fails O2 before it is opened", rc == 1 and "FAIL O2" in out
                  and "decrypted ISO" not in out, out)
        finally:
            fc.file_attributes = real_attr
            if old is None:
                del os.environ["OneDrive"]
            else:
                os.environ["OneDrive"] = old
        rc, out = run(["--dump", d, "--update", u] + small)
        check("folder dump: no ISO line", "decrypted ISO" not in out, out)

        # A1: the archive's SHA-256 against a known one (psarc_sha256.json format), injected with --psarc-hashes
        import hashlib

        def psarc_of(dump):
            return os.path.join(dump, "PS3_GAME", "USRDIR", "data_ps3.psarc")

        def known_file(name, **kw):
            p = os.path.join(tmp, name)
            with open(p, "w") as f:
                json.dump(dict({"sha256": hashlib.sha256(open(psarc_of(d), "rb").read()).hexdigest(), "size": 4096,
                                "discs": ["BCUS98116"], "fail_on_mismatch": False}, **kw), f)
            return p
        known = known_file("known.json")
        hard = known_file("known-hard.json", fail_on_mismatch=True)
        a1 = ["--min-psarc-bytes", "1024", "--psarc-hashes", known, "--update", u]
        rc, out = run(["--dump", d] + a1)
        check("A1 match is OK", rc == 0 and "OK   A1: data_ps3.psarc matches the known disc archive" in out, out)
        dmg = make_dump(os.path.join(tmp, "dmg"))
        with open(psarc_of(dmg), "r+b") as f:
            f.seek(100)
            f.write(b"x")
        rc, out = run(["--dump", dmg] + a1)
        check("A1 mismatch on the US disc (one copy checked) is a WARN with both details",
              rc == 0 and "WARN A1: data_ps3.psarc differs from the known disc archive (4,096 bytes, SHA-256 " in out
              and "copy or dump the disc again" in out, out)
        rc, out = run(["--dump", dmg, "--psarc-hashes", hard, "--update", u, "--min-psarc-bytes", "1024"])
        check("A1 mismatch with fail_on_mismatch is a FAIL",
              rc == 1 and "FAIL A1: data_ps3.psarc differs from the known disc archive (damaged or modified copy)" in out, out)
        short = make_dump(os.path.join(tmp, "short"), psarc_bytes=8192)
        calls = []
        real = fc.hash_file
        fc.hash_file = lambda p, progress=None: (calls.append(p), real(p, progress))[1]
        try:
            rc, out = run(["--dump", short, "--psarc-hashes", hard, "--update", u, "--min-psarc-bytes", "1024"])
            check("A1 a different size is a mismatch without reading the file",
                  rc == 1 and "FAIL A1" in out and "the known archive is 4,096 bytes" in out and not calls, out)
            rc, out = run(["--dump", dmg, "--skip-archive-hash"] + a1)
            check("--skip-archive-hash leaves A1 out", rc == 0 and "A1:" not in out and not calls, out)
            cdir = os.path.join(tmp, "cachedir")
            for n in (1, 2):
                rep = fc.Report()
                fc.check_psarc_hash(rep, psarc_of(d), "BCUS98116", known, cdir)
                check(f"A1 run {n} is OK", [c["level"] for c in rep.checks] == ["OK"], rep.checks)
            check("A1 cache hit: the file was read once", len(calls) == 1 and "cached" in rep.checks[0]["message"], calls)
            os.utime(psarc_of(d), ns=(1_000_000_000, 1_000_000_000))
            fc.check_psarc_hash(fc.Report(), psarc_of(d), "BCUS98116", known, cdir)
            check("A1 changed mtime: read again", len(calls) == 2, calls)
            seen = []
            fc.check_psarc_hash(fc.Report(), psarc_of(dmg), "BCUS98116", known, None, lambda dn, t: seen.append((dn, t)))
            check("A1 progress reports done/total up to the end", seen and seen[-1] == (4096, 4096), seen)
        finally:
            fc.hash_file = real
        rc, out = run(["--dump", d, "--progress", "--build", os.path.join(tmp, "b-prog")] + a1)
        check("--progress prints ARCHIVE-HASH lines; --build holds the cache",
              "ARCHIVE-HASH done=4096 total=4096" in out
              and os.path.isfile(os.path.join(tmp, "b-prog", fc.PSARC_CACHE_NAME)), out)
        rep = fc.Report()
        fc.check_psarc_hash(rep, psarc_of(d), "BCUS98116", os.path.join(tmp, "absent.json"))
        check("an unreadable known-hash file only warns", [c["level"] for c in rep.checks] == ["WARN"]
              and "not readable" in rep.checks[0]["message"], rep.checks)
        rep = fc.Report()
        fc.check_psarc_hash(rep, psarc_of(dmg), "BCES00081", hard)
        check("A1 on a disc not listed only warns", [c["level"] for c in rep.checks] == ["WARN"]
              and "not a known archive" in rep.checks[0]["message"], rep.checks)
        real_known = json.load(open(fc.PSARC_HASHES_FILE))
        arch = {e["discs"][0]: e for e in real_known["archives"]}
        check("the shipped psarc_sha256.json: one entry per disc, WARN on mismatch",
              [e["discs"] for e in real_known["archives"]] == [[t] for t in fc.REGIONS]
              and all(len(e["sha256"]) == 64 and e["fail_on_mismatch"] is False for e in arch.values())
              and arch["BCUS98116"]["size"] == 6_998_576_922
              and arch["BCES00081"]["sha256"] == arch["BCUS98116"]["sha256"] == "063d3f157ec4d5b130808f70c22086bb0edaf0070a5aba407d20c200ee8a59e9"
              and (arch["BCAS20066"]["size"], arch["BCAS20066"]["sha256"][:8]) == (7_023_155_305, "b0bfa59f")
              and (arch["BCJS30032"]["size"], arch["BCJS30032"]["sha256"][:8]) == (7_120_891_686, "bf880e05"),
              real_known)
        # per-disc archives: the disc's own archive is OK, another disc's archive is a FAIL (a mixed dump)
        other = make_dump(os.path.join(tmp, "a1asia"), title_id="BCAS20066", psarc_bytes=4096)
        with open(psarc_of(other), "r+b") as f:
            f.seek(200)
            f.write(b"asia")
        sha_us = hashlib.sha256(open(psarc_of(d), "rb").read()).hexdigest()
        sha_as = hashlib.sha256(open(psarc_of(other), "rb").read()).hexdigest()
        multi = os.path.join(tmp, "multi.json")
        with open(multi, "w") as f:
            json.dump({"archives": [{"discs": ["BCUS98116"], "sha256": sha_us, "size": 4096},
                                    {"discs": ["BCES00081"], "sha256": sha_us, "size": 4096},
                                    {"discs": ["BCAS20066"], "sha256": sha_as, "size": 4096, "fail_on_mismatch": True},
                                    {"discs": ["BCJS30032"], "sha256": "0" * 64, "size": 9999}]}, f)
        for name, path, tid, want, text in (
                ("US archive on the US disc", psarc_of(d), "BCUS98116", "OK", "matches the known disc archive"),
                ("US archive on the European disc (identical archives)", psarc_of(d), "BCES00081", "OK", "matches"),
                ("Asian archive on the Asian disc", psarc_of(other), "BCAS20066", "OK", "matches"),
                ("Asian archive with the US PARAM.SFO", psarc_of(other), "BCUS98116", "FAIL",
                 "is the archive of the Asian disc (BCAS20066), but PARAM.SFO is the US disc (BCUS98116): the dump mixes two discs"),
                ("US archive with the Asian PARAM.SFO", psarc_of(d), "BCAS20066", "FAIL", "the dump mixes two discs"),
                ("damaged archive on the Asian disc (fail_on_mismatch)", psarc_of(dmg), "BCAS20066", "FAIL",
                 "differs from the known disc archive (damaged or modified copy)"),
                ("damaged archive on the Japanese disc (WARN entry)", psarc_of(dmg), "BCJS30032", "WARN",
                 "differs from the known disc archive (4,096 bytes, SHA-256 ")):
            rep = fc.Report()
            fc.check_psarc_hash(rep, path, tid, multi)
            check(f"A1 per disc: {name} -> {want}", [c["level"] for c in rep.checks] == [want]
                  and text in rep.checks[0]["message"], rep.checks)

        # FAT32 split parts: data_ps3.psarc.66600, .66601, ... instead of data_ps3.psarc
        def split_dump(name, sizes, skip=()):
            sd = make_dump(os.path.join(tmp, name))
            data = open(psarc_of(d), "rb").read()
            os.remove(psarc_of(sd))
            off = 0
            for i, n in enumerate(sizes):
                if i not in skip:
                    with open(f"{psarc_of(sd)}.{66600 + i}", "wb") as f:
                        f.write(data[off:off + n])
                off += n
            return sd
        sp = split_dump("split4", [1024, 1024, 1024, 1024])
        rc, out = run(["--dump", sp, "--json"] + a1)
        j = json.loads(out)
        check("split parts: facts list the parts in order", j["facts"]["psarc"]["parts"]
              == [f"data_ps3.psarc.{66600 + i}" for i in range(4)] and j["facts"]["psarc"]["size"] == 4096, out)
        rc, out = run(["--dump", sp] + a1)
        check("split parts: D3 OK with the total size, A1 matches the hash of the joined parts",
              rc == 0 and "OK   D3: data_ps3.psarc present" in out and "4 split parts" in out
              and "OK   A1: data_ps3.psarc matches the known disc archive" in out, out)
        sp2 = split_dump("split3", [2000, 2000, 96])        # uneven part sizes: nothing assumes a part size
        rc, out = run(["--dump", sp2] + a1)
        check("split parts of uneven sizes: A1 OK", rc == 0 and "OK   A1: data_ps3.psarc matches" in out, out)
        cdir2 = os.path.join(tmp, "splitcache")
        calls2 = []
        real2 = fc.hash_file
        fc.hash_file = lambda p, progress=None: (calls2.append(p), real2(p, progress))[1]
        try:
            for n in (1, 2):
                rep = fc.Report()
                fc.check_psarc_hash(rep, psarc_of(sp), "BCUS98116", known, cdir2)
                check(f"split parts: A1 run {n} OK", [c["level"] for c in rep.checks] == ["OK"], rep.checks)
            check("split parts: cache hit, the parts were read once as one list",
                  len(calls2) == 1 and isinstance(calls2[0], list) and len(calls2[0]) == 4, calls2)
            os.utime(f"{psarc_of(sp)}.66602", ns=(1_000_000_000, 1_000_000_000))      # any one part's mtime
            fc.check_psarc_hash(fc.Report(), psarc_of(sp), "BCUS98116", known, cdir2)
            check("split parts: one part's changed mtime reads again", len(calls2) == 2, calls2)
        finally:
            fc.hash_file = real2
        seen = []
        fc.check_psarc_hash(fc.Report(), psarc_of(sp), "BCUS98116", known, None, lambda dn, t: seen.append((dn, t)))
        check("split parts: progress runs over the total", seen and seen[-1] == (4096, 4096), seen[-1:])
        with open(f"{psarc_of(sp)}.66601", "r+b") as f:
            f.seek(5)
            f.write(b"x")
        rep = fc.Report()
        fc.check_psarc_hash(rep, psarc_of(sp), "BCUS98116", hard, None)
        check("split parts: a damaged middle part fails A1", [c["level"] for c in rep.checks] == ["FAIL"], rep.checks)
        gap = split_dump("splitgap", [1024, 1024, 1024, 1024], skip=(2,))
        rc, out = run(["--dump", gap] + a1)
        check("split parts with a gap name the missing part",
              rc == 1 and "FAIL D3" in out and "data_ps3.psarc.66602 is missing" in out and "A1" not in out, out)
        late = split_dump("splitlate", [1024, 1024, 1024, 1024], skip=(0,))
        rc, out = run(["--dump", late] + a1)
        check("split parts without .66600 name it", rc == 1 and "data_ps3.psarc.66600 is missing" in out, out)
        short2 = split_dump("splitshort", [1024, 1024])
        rc, out = run(["--dump", short2, "--min-psarc-bytes", "4096", "--update", u, "--skip-archive-hash"])
        check("split parts too small in total fail D3 on the total", rc == 1 and "FAIL D3" in out and "2,048 bytes" in out, out)
        nothing = make_dump(os.path.join(tmp, "nopsarc"))
        os.remove(psarc_of(nothing))
        rc, out = run(["--dump", nothing] + a1)
        check("neither file nor parts: D3 names data_ps3.psarc", rc == 1 and "no PS3_GAME/USRDIR/data_ps3.psarc" in out, out)
        upper = split_dump("splitcase", [2048, 2048])
        for i in range(2):
            os.rename(f"{psarc_of(upper)}.{66600 + i}", os.path.join(os.path.dirname(psarc_of(upper)), f"DATA_PS3.PSARC.{66600 + i}"))
        rc, out = run(["--dump", upper] + a1)
        check("split parts named in upper case (a FAT32 copy) are found", rc == 0 and "2 split parts" in out, out)

        bad = make_dump(os.path.join(tmp, "nosfo"))
        os.remove(os.path.join(bad, "PS3_GAME", "PARAM.SFO"))
        rc, out = run(["--dump", bad, "--update", u] + small)
        check("missing PARAM.SFO fails", rc == 1 and "FAIL D1" in out, out)

        dec = make_dump(os.path.join(tmp, "dec"), eboot_magic=fc.ELF_MAGIC)
        rc, out = run(["--dump", dec, "--update", u] + small)
        check("already-decrypted disc EBOOT passes", rc == 0 and "already a decrypted ELF" in out, out)
        rc, out = run(["--dump", dec] + small)
        check("decrypted EBOOT.BIN serves as the ELF when no EBOOT.elf exists", "FAIL E1" not in out
              and levels(out, "E1") == {"WARN"}, out)

        rc, out = run(["--dump", make_dump(os.path.join(tmp, "trunc"), psarc_bytes=512), "--update", u] + small)
        check("truncated psarc fails", rc == 1 and "FAIL D3" in out and "truncated" in out, out)

        u100 = make_update(os.path.join(tmp, "v100"), elf_size=16_381_928)
        rc, out = run(["--dump", d, "--update", u100] + small)
        check("v1.01 ELF (by size) on the 1.29 build fails E1 naming the needed build (Project Helghast PR #11; "
              "an earlier change: no path, no how-to)", rc == 1 and levels(out, "E1") == {"FAIL"} and "FAIL E1: This EBOOT is "
              "Killzone 2 1.01, the disc's own version. This release needs Killzone 2 1.29 (BCUS98116, US)." in out, out)
        rc, out = run(["--dump", d, "--eboot", os.path.join(u100, "USRDIR", "EBOOT.elf")] + small)
        check("E1 without --update: the same text", rc == 1 and "the disc's own version" in out, out)
        rc, out = run(["--dump", d, "--update", u100, "--target", "1.01"] + small)
        check("v1.01 ELF on a 1.01 tree (--target 1.01) is OK", rc == 0 and levels(out, "E1") == {"OK"}, out)
        rc, out = run(["--dump", d, "--update", u, "--target", "1.01"] + small)
        check("1.29 ELF on a 1.01 tree fails", rc == 1 and levels(out, "E1") == {"FAIL"}
              and "needs Killzone 2 1.01 (BCUS98116, US)" in out, out)

        ux = make_update(os.path.join(tmp, "x86"), elf_size=16_455_144)
        write_elf(os.path.join(ux, "USRDIR", "EBOOT.elf"), 16_455_144, machine=0x3E, data=1)
        rc, out = run(["--dump", d, "--update", ux] + small)
        check("wrong-machine ELF fails", rc == 1 and "FAIL E1" in out, out)

        rc, out = run(["--dump", d, "--update", make_update(os.path.join(tmp, "v113"), app_ver="01.13")] + small)
        check("other APP_VER warns", rc == 0 and "WARN U1" in out, out)

        rc, out = run(["--dump", os.path.join(tmp, "missing"), "--update", u] + small)
        check("missing dump dir fails", rc == 1 and "FAIL D0" in out, out)

        # H1 and E1 against the shared EBOOT id table (tools/release/eboot_sha256.json or --hashes)
        with open(fc.HASHES_FILE, encoding="utf-8") as f:
            shipped = json.load(f)
        rows = fc.load_eboot_entries(fc.HASHES_FILE)
        r129 = [x for x in rows if x["version"] == "1.29"]
        check("shipped table: an entries list, one title id per entry, four 1.29 rows and the US 1.01 row",
              isinstance(shipped.get("entries"), list) and "builds" not in shipped
              and all(isinstance(e["title_id"], str) for e in shipped["entries"])
              and [(x["title_id"], x["region"]) for x in r129] == list(zip(fc.REGIONS, ("US", "EU", "Asia", "JP")))
              and [(x["title_id"], x["version"]) for x in rows if x["version"] == "1.01"] == [("BCUS98116", "1.01")],
              shipped)
        check("shipped table: 1.29 rows share size, sha256 and segment_sha256; self_sha256 per region",
              len({(x["size"], x["sha256"], x["segment_sha256"]) for x in r129}) == 1
              and all(len(x["sha256"]) == 64 and len(x["segment_sha256"]) == 64 for x in rows)
              and len({x["self_sha256"] for x in r129}) == 4, rows)
        check("shipped table: statuses tested (US 1.29), untested (the other 1.29), unsupported (1.01)",
              [x["status"] for x in rows] == ["tested", "untested", "untested", "untested", "unsupported"], rows)
        check("shipped table: sizes = EBOOT_ELF_SIZES", {x["size"]: x["version"] for x in rows} ==
              fc.EBOOT_ELF_SIZES, rows)
        check("shipped table: the comment holds no brace (the installer's parser)",
              not [c for c in shipped["comment"] if c in "{}"])

        # segment_sha256 on a fixture: p_paddr differs from p_filesz (a wrong-offset read fails), a PT_NOTE and an
        # empty PT_LOAD are skipped, a PT_LOAD with p_filesz 0 but p_memsz set counts (header only)
        segs = [(fc.PT_LOAD, 0x10000, 0x7777, b"\x11" * 300, 0x400), (4, 0x20000, 0x5555, b"\x22" * 40, 40),
                (fc.PT_LOAD, 0x30000, 0x9999, b"", 0), (fc.PT_LOAD, 0x40000, 0x1234, b"", 0x800),
                (fc.PT_LOAD, 0x50000, 0xabcd, b"\x33" * 123, 0x200)]
        fx = os.path.join(tmp, "seg", "a.elf")
        seg_elf(fx, segs, gap=16)
        want = hashlib.sha256()
        for typ, va, pa, data, mem in segs:
            if typ == fc.PT_LOAD and (data or mem):
                want.update(struct.pack(">QQQ", va, len(data), mem) + data)
        check("segment_sha256: the spec's definition on a fixture with p_paddr != p_filesz",
              fc.segment_sha256(fx) == want.hexdigest() and all(pa != len(d) for _t, _v, pa, d, _m in segs))
        fx2 = os.path.join(tmp, "seg", "b.elf")
        seg_elf(fx2, segs, gap=4096, tail=b"\0" * 999)
        check("segment_sha256: another layout (padding, trailing bytes) keeps the value, the whole hash changes",
              fc.segment_sha256(fx2) == fc.segment_sha256(fx) and fc.file_sha256(fx2) != fc.file_sha256(fx))
        fx3 = os.path.join(tmp, "seg", "c.elf")
        seg_elf(fx3, [(t, v, len(d), d, m) for t, v, _p, d, m in segs], gap=16)
        check("segment_sha256: p_paddr is not used (the same segments with p_paddr = p_filesz hash the same)",
              fc.segment_sha256(fx3) == fc.segment_sha256(fx))
        seg_elf(fx3, [(t, v, p, d.replace(b"\x33", b"\x34"), m) for t, v, p, d, m in segs], gap=16)
        check("control: one changed segment byte changes segment_sha256", fc.segment_sha256(fx3) != fc.segment_sha256(fx))
        cut = os.path.join(tmp, "seg", "cut.elf")
        open(cut, "wb").write(open(fx, "rb").read()[:-50])
        try:
            fc.segment_sha256(cut)
            check("segment_sha256: a segment past the end of the file is refused", False)
        except ValueError as e:
            check("segment_sha256: a segment past the end of the file is refused", "past the end" in str(e), e)

        # the outcomes, on a fixture of the 1.29 size (E1's version by size) and on padded copies
        e129 = os.path.join(tmp, "seg", "EBOOT.elf")
        seg_elf(e129, segs, gap=16, size=16_455_144)
        pad = os.path.join(tmp, "seg", "padded.elf")
        seg_elf(pad, segs, gap=4096, size=16_455_144 + 8192)
        sha, seg = fc.file_sha256(e129), fc.segment_sha256(e129)
        hf = os.path.join(tmp, "hashes.json")

        def entry(sha256=sha, segment=seg, tid="BCUS98116", region="US", app_ver="01.29", size=16_455_144,
                  status="tested", **kw):
            return dict({"title_id": tid, "region": region, "app_ver": app_ver, "size": size, "sha256": sha256,
                         "status": status, "self_sha256": "", "segment_sha256": segment}, **kw)

        def table(*entries, key="entries", extra=None):
            with open(hf, "w", encoding="utf-8") as f:
                json.dump(dict({"comment": "test", key: list(entries)}, **(extra or {})), f)
            return hf

        def verdict(elf, tbl, disc="BCUS98116", target="1.29"):
            rep = fc.Report()
            if disc:
                rep.facts["disc"] = {"TITLE_ID": disc}
            fc.check_eboot_elf(rep, elf, target, None, tbl)
            return {c["code"]: (c["level"], c["message"]) for c in rep.checks}, rep.facts.get("eboot_elf", {})

        v, facts = verdict(e129, table(entry()))
        check("whole-file match, tested: E1 OK and H1 OK by SHA-256", v["E1"][0] == "OK" and v["H1"][0] == "OK"
              and "by SHA-256" in v["H1"][1] and facts["sha256"] == sha and facts["segment_sha256"] == seg
              and facts["match"] == {"by": "sha256", "title_id": "BCUS98116", "app_ver": "01.29", "status": "tested"}, v)
        v, facts = verdict(e129, table(entry(sha256="ab" * 32)))
        check("segment fallback: the whole hash differs, the segments match: OK by its segments",
              v["E1"][0] == "OK" and v["H1"] == ("OK", "EBOOT matches the known build Killzone 2 1.29 (BCUS98116, US), "
                                                        "by its segments"), v)
        v, facts = verdict(pad, table(entry()))
        check("segment fallback: a padded copy (another size, another whole hash) is the 1.29 build",
              fc.file_sha256(pad) != sha and v["E1"][0] == "OK" and v["H1"][0] == "OK" and facts["version"] == "1.29"
              and facts["match"]["by"] == "segments", v)
        v, _ = verdict(e129, table(entry(status="untested", tid="BCES00081", region="EU")), disc="BCES00081")
        check("untested build: H1 WARN", v["E1"][0] == "OK" and v["H1"] == (
            "WARN", "This EBOOT is Killzone 2 1.29 (BCES00081, Europe): untested on this port."), v)
        v, _ = verdict(e129, table(entry(status="unsupported")))
        check("unsupported build: H1 FAIL", v["H1"] == ("FAIL", "This EBOOT is Killzone 2 1.29 (BCUS98116, US), a "
                                                        "build this port does not run. This release needs Killzone 2 "
                                                        "1.29 (BCUS98116, US)."), v)
        v, _ = verdict(e129, table(entry(status="withdrawn")))
        check("a status this reader does not know FAILs on a match (fail closed)", v["H1"][0] == "FAIL"
              and "'withdrawn'" in v["H1"][1], v)
        v, _ = verdict(e129, table(entry(status="withdrawn", sha256="ab" * 32, segment="cd" * 32), entry(
            sha256="ef" * 32, segment="", tid="BCES00081", region="EU")))
        check("control: an unknown status on a row that does not match is no FAIL", v["H1"][0] == "WARN", v)
        v, _ = verdict(e129, table(entry(tid="BCES00081", region="EU")))
        check("another region's title id: H1 WARN wrong region", v["H1"] == (
            "WARN", "Wrong region: this EBOOT is Killzone 2 1.29 (BCES00081, Europe), but the disc is BCUS98116 (US). "
                    "This release needs Killzone 2 1.29 (BCUS98116, US)."), v)
        v, facts = verdict(e129, table(entry(tid="BCES00081", region="EU", status="untested"), entry()), disc="BCES00081")
        check("several rows match: the disc's own row decides (European disc: untested)",
              v["H1"][0] == "WARN" and "untested" in v["H1"][1] and facts["match"]["title_id"] == "BCES00081", v)
        v, _ = verdict(e129, table(entry(), entry(tid="BCES00081", region="EU", status="untested")), disc="")
        check("no disc known: the first matching row (US, tested)", v["H1"][0] == "OK", v)
        v, _ = verdict(e129, table(entry(app_ver="01.01")))
        check("same title, another app_ver: E1 FAIL (the hash is certain), no H1", v.get("E1") == (
            "FAIL", "This EBOOT is Killzone 2 1.01 (BCUS98116, US), the disc's own version. This release needs "
                    "Killzone 2 1.29 (BCUS98116, US).") and "H1" not in v, v)
        v, _ = verdict(e129, table(entry(sha256="ab" * 32, segment="cd" * 32)))
        check("unknown or modified (the 1.29 size, no match): H1 WARN with the unknown-or-modified text", v["E1"][0] == "OK" and v["H1"] == (
            "WARN", "Your EBOOT is the 1.29 size but its contents differ from a clean copy. It may be patched or "
                    "damaged. Make it again from your own 1.29 update's EBOOT.BIN, without patches, and pick the new "
                    "file."), v)
        v, _ = verdict(pad, table(entry(sha256="ab" * 32, segment="cd" * 32)))
        check("unknown size, no match: E1 WARN and H1 WARN naming the needed build", v["E1"][0] == "WARN"
              and v["H1"] == ("WARN", f"This EBOOT ({16_455_144 + 8192:,} bytes) matches no known Killzone 2 build. "
                                      "This release needs Killzone 2 1.29 (BCUS98116, US)."), v)
        v, _ = verdict(e129, table(entry(sha256="", segment="")))
        check("no reference recorded (empty sha256): H1 WARN unknown yet", v["H1"][0] == "WARN"
              and "unknown yet" in v["H1"][1], v)
        enc = os.path.join(tmp, "seg", "self.elf")
        open(enc, "wb").write(fc.SELF_MAGIC + b"\0" * 200)
        v, _ = verdict(enc, table(entry()), disc="BCJS30032")
        check("encrypted SELF: E1 FAIL naming the needed build of the disc's region", v == {"E1": (
            "FAIL", "This EBOOT is an encrypted SELF, not an ELF. This release needs Killzone 2 1.29 (BCJS30032, Japan) "
                    "as an ELF file.")}, v)
        junk = os.path.join(tmp, "seg", "junk.elf")
        open(junk, "wb").write(b"MZ" + b"\0" * 200)
        v, _ = verdict(junk, table(entry()))
        check("not a PS3 executable: E1 FAIL", v == {"E1": (
            "FAIL", "This file is not a PS3 executable (a 64-bit big-endian PowerPC ELF). This release needs "
                    "Killzone 2 1.29 (BCUS98116, US).")}, v)
        x86 = os.path.join(tmp, "seg", "x86.elf")
        write_elf(x86, 4096, machine=0x3E, data=1)
        v, _ = verdict(x86, table(entry()))
        check("a little-endian x86 ELF is not a PS3 executable either", v["E1"][0] == "FAIL"
              and "not a PS3 executable" in v["E1"][1], v)
        msgs = [m for c in (verdict(e129, table(t))[0] for t in (entry(status="unsupported"), entry(app_ver="01.01"),
                entry(tid="BCES00081", region="EU"))) for _l, m in c.values()]
        check("the player texts carry no path and no word on decrypting or dumping",
              not [m for m in msgs if tmp in m or "decrypt" in m.lower() or "dump" in m.lower()], msgs)

        # the older formats still load: an earlier change's builds list (lists of ids, known-good) and the per-version form
        v, _ = verdict(e129, table({"title_id": ["BCUS98116", "BCES00081"], "region": ["US", "Europe"],
                                    "app_ver": "01.29", "size": 16_455_144, "sha256": sha, "status": "known-good"},
                                   key="builds"))
        check("round-100 builds list still reads (known-good = tested)", v["H1"][0] == "OK", v)
        v, facts = verdict(e129, table({"title_id": ["BCUS98116", "BCES00081"], "region": ["US", "Europe"],
                                        "app_ver": "01.29", "size": 16_455_144, "sha256": sha,
                                        "status": "known-good"}, key="builds"), disc="BCES00081")
        check("round-100 builds list: its title id list expands pairwise", v["H1"][0] == "OK"
              and facts["match"]["title_id"] == "BCES00081", v)
        with open(hf, "w", encoding="utf-8") as f:
            json.dump({"1.29": {"size": 16_455_144, "sha256": sha.upper()}}, f)
        v, _ = verdict(e129, hf)
        check("the old per-version form still reads (US, tested)", v["H1"][0] == "OK", v)
        with open(hf, "w", encoding="utf-8") as f:
            json.dump({"1.29": {"size": 16_455_144, "sha256": ""}}, f)
        v, _ = verdict(e129, hf)
        check("old form, empty value: unknown yet", v["H1"][0] == "WARN" and "unknown yet" in v["H1"][1], v)
        for bad, why in ((entry(sha256="xyz"), "entries[1].sha256 must be 64 hex digits"),
                         ({k: x for k, x in entry().items() if k != "status"}, "entries[1] lacks status"),
                         (entry(app_ver="1.29"), "entries[1].app_ver must look like PARAM.SFO's APP_VER"),
                         (entry(size="16455144"), "entries[1].size must be a positive whole number"),
                         (entry(tid=["BCUS98116"], region=["US"]), "entries[1].title_id must be a non-empty string"),
                         (entry(segment="12"), "entries[1].segment_sha256 must be 64 hex digits"),
                         (entry(colour="red"), "entries[1] has unknown keys colour"),
                         ("1.29", "entries[1] is not an object")):
            v, _ = verdict(e129, table(entry(app_ver="01.01", size=16_381_928, sha256="ab" * 32), bad))
            check(f"malformed entry refused: {why}", v["H1"][0] == "WARN" and why in v["H1"][1]
                  and "not identified" in v["H1"][1], v)
        v, _ = verdict(e129, table(entry(), entry()))
        check("two entries for one title id and app_ver refused", "a second entry for BCUS98116" in v["H1"][1], v)
        v, _ = verdict(e129, table(entry(), extra={"builds": []}))
        check("an entries and a builds list together refused", "keep one" in v["H1"][1], v)
        v, _ = verdict(e129, table(entry(), extra={"1.29": {"size": 1, "sha256": sha}}))
        check("an entries list and old keys together refused", "old per-version keys" in v["H1"][1], v)
        v, _ = verdict(e129, os.path.join(tmp, "nohashes.json"))
        check("unreadable table: H1 WARN", v["E1"][0] == "OK" and v["H1"][0] == "WARN", v)
        rc, out = run(["--dump", d, "--update", u, "--json", "--eboot", e129, "--hashes", table(entry())] + small)
        j = json.loads(out)
        check("CLI: --hashes reaches the check; facts carry both hashes and the match", rc == 0
              and j["facts"]["eboot_elf"]["segment_sha256"] == seg and j["facts"]["eboot_elf"]["match"]["by"] == "sha256",
              out)
        rc, out = run(["--dump", d, "--update", ux] + small + ["--hashes", table(entry())])
        check("no H1 when E1 failed", "H1:" not in out, out)
        # B1: the finished build must hold kz2.exe and at3_standalone.dll (kz2.exe imports it)
        ob = os.path.join(tmp, "obj")
        os.makedirs(ob)
        rc, out = run(["--build-dir", ob])
        check("B1 empty build folder fails", rc == 1 and "kz2.exe was not built" in out and "at3_standalone.dll is missing" in out, out)
        open(os.path.join(ob, "kz2.exe"), "wb").write(b"MZ")
        rc, out = run(["--build-dir", ob])
        check("B1 missing at3_standalone.dll fails clearly", rc == 1 and "at3_standalone.dll is missing" in out
              and "will not start" in out and "kz2.exe was not built" not in out, out)
        open(os.path.join(ob, "at3_standalone.dll"), "wb").write(b"")
        rc, out = run(["--build-dir", ob])
        check("B1 empty DLL fails", rc == 1 and "is empty" in out, out)
        open(os.path.join(ob, "at3_standalone.dll"), "wb").write(b"MZ")
        rc, out = run(["--build-dir", ob])
        check("B2 kz2.exe without the FFmpeg loader fails (issue #16)", rc == 1 and "FAIL B2:" in out
              and "avcodec-63.dll, avutil-61.dll" in out and "FAIL B1" not in out, out)
        # the loader's names straddling the 4 MiB read boundary are still found
        exe = b"MZ" + bytes((1 << 22) - 8) + b"avcodec-63.dll" + bytes(100) + b"avutil-61.dll\0"
        open(os.path.join(ob, "kz2.exe"), "wb").write(exe)
        rc, out = run(["--build-dir", ob])
        check("B1 + B2 complete build passes", rc == 0 and "build checks: pass" in out, out)
        open(os.path.join(ob, "kz2.exe"), "wb").write(b"MZ avcodec-62.dll avutil-61.dll")
        rc, out = run(["--build-dir", ob])
        check("B2 a loader for another avcodec major fails", rc == 1 and "FAIL B2:" in out and "avcodec-63.dll" in out
              and "avutil-61.dll," not in out, out)
        check("firstrun stamp step runs the B1 check", "--build-dir" in
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "firstrun.py")).read())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"firstrun_check: {'PASS' if not FAILS else 'FAIL ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
