#!/usr/bin/env python3
"""Host test for tools/release/firstrun_check.py (from Project Helghast) on synthetic fixtures (no game data: a temp dir
holds a made-up PARAM.SFO, a 4-byte 'SCE' EBOOT.BIN, a 'PSAR' header and a 64-byte PPC64 ELF header). Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_firstrun_check.py

Cases: a complete dump + update + 1.29-sized ELF passes; wrong TITLE_ID fails; missing PARAM.SFO fails; a dump
whose EBOOT.BIN is already an ELF passes; a v1.01-sized ELF warns; a wrong-machine ELF fails; a truncated psarc
fails; no --update warns; --json has the documented shape; H1 (EBOOT SHA-256): the shipped hashes file
with empty values warns "unknown yet", a matching hash is OK, a mismatch warns with the size and both hashes (exit 0),
an unreadable hashes file warns, a failed E1 gives no H1.
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
        rc, out = run(["--dump", make_dump(os.path.join(tmp, "eu2"), title_id="BCES00081"), "--update", ux_id] + small)
        check("a non-US disc with its own update still fails D1", rc == 1 and levels(out, "D1") == {"FAIL"}, out)

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
        old = os.environ.get("OneDrive")
        os.environ["OneDrive"] = os.path.join(tmp, "hdd0")      # the update folder sits inside the fake OneDrive
        real_attr = fc.file_attributes
        try:
            rc, out = run(["--dump", d, "--update", u] + small)
            check("O3 INFO only when inside OneDrive but local", rc == 0 and levels(out, "O3") == {"OK"}
                  and "INFO" in out and "O2" not in out, out)
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
        check("--root without OneDrive env passes", rc == 0 and "O1" not in out, out)

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
              and "inside the ISO" in out and "A1" not in out, out)
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
        check("ISO: not an ISO is I2, not 'encrypted'", rc == 1 and "FAIL I2" in out and "I1" not in out, out)
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
            check("--skip-archive-hash leaves A1 out", rc == 0 and "A1" not in out and not calls, out)
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
        check("the shipped psarc_sha256.json: the US disc, one copy, WARN on mismatch",
              real_known["discs"] == ["BCUS98116"] and len(real_known["sha256"]) == 64
              and real_known["size"] == 6_998_576_922 and real_known["fail_on_mismatch"] is False, real_known)

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
        check("v1.01 ELF warns, no FAIL", rc == 0 and levels(out, "E1") == {"WARN"} and "1.01" in out, out)
        rc, out = run(["--dump", d, "--update", u100, "--target", "1.01"] + small)
        check("v1.01 ELF on a 1.01 tree (--target 1.01) is OK", rc == 0 and levels(out, "E1") == {"OK"}, out)
        rc, out = run(["--dump", d, "--update", u, "--target", "1.01"] + small)
        check("1.29 ELF on a 1.01 tree warns", rc == 0 and levels(out, "E1") == {"WARN"} and "for the 1.01" in out, out)

        ux = make_update(os.path.join(tmp, "x86"), elf_size=16_455_144)
        write_elf(os.path.join(ux, "USRDIR", "EBOOT.elf"), 16_455_144, machine=0x3E, data=1)
        rc, out = run(["--dump", d, "--update", ux] + small)
        check("wrong-machine ELF fails", rc == 1 and "FAIL E1" in out, out)

        rc, out = run(["--dump", d, "--update", make_update(os.path.join(tmp, "v113"), app_ver="01.13")] + small)
        check("other APP_VER warns", rc == 0 and "WARN U1" in out, out)

        rc, out = run(["--dump", os.path.join(tmp, "missing"), "--update", u] + small)
        check("missing dump dir fails", rc == 1 and "FAIL D0" in out, out)

        # H1: EBOOT SHA-256 against tools/release/eboot_sha256.json (or --hashes)
        with open(fc.HASHES_FILE, encoding="utf-8") as f:
            shipped = json.load(f)
        check("shipped hashes file has 1.29 and 1.01 entries", {"1.29", "1.01"} <= set(shipped)
              and shipped["1.29"]["size"] == 16_455_144, shipped)
        elf = os.path.join(u, "USRDIR", "EBOOT.elf")
        got = fc.file_sha256(elf)
        hf = os.path.join(tmp, "hashes.json")

        def hashes(v):
            with open(hf, "w", encoding="utf-8") as f:
                json.dump({"1.29": {"size": 16_455_144, "sha256": v}}, f)
            return ["--hashes", hf]

        rc, out = run(["--dump", d, "--update", u] + small + hashes(""))
        check("H1 unknown yet warns only", rc == 0 and levels(out, "H1") == {"WARN"} and "unknown yet" in out
              and got in out, out)
        rc, out = run(["--dump", d, "--update", u] + small + hashes(got.upper()))
        check("H1 match is OK", rc == 0 and levels(out, "H1") == {"OK"}, out)
        rc, out = run(["--dump", d, "--update", u] + small + hashes("ab" * 32))
        check("H1 mismatch warns with size and both hashes", rc == 0 and levels(out, "H1") == {"WARN"}
              and got in out and "ab" * 32 in out and "16,455,144" in out, out)
        rc, out = run(["--dump", d, "--update", u, "--json"] + small + hashes(got))
        check("H1 hash in json facts", json.loads(out)["facts"]["eboot_elf"]["sha256"] == got, out)
        rc, out = run(["--dump", d, "--update", u] + small + ["--hashes", os.path.join(tmp, "nohashes.json")])
        check("H1 unreadable hashes file warns", rc == 0 and levels(out, "H1") == {"WARN"}, out)
        rc, out = run(["--dump", d, "--update", ux] + small + hashes(got))
        check("no H1 when E1 failed", "H1" not in out, out)
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
        check("B1 complete build passes", rc == 0 and "build checks: pass" in out, out)
        check("firstrun stamp step runs the B1 check", "--build-dir" in
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "firstrun.py")).read())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"firstrun_check: {'PASS' if not FAILS else 'FAIL ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
