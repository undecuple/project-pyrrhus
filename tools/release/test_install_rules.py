#!/usr/bin/env python3
"""Host test for installer/kz2.iss rules that a compile does not catch (adapted from Project Helghast, the Killzone 3
PC port, same author, MIT: Project Helghast v0.1.2 test_install_dir_rule.py, b1a6262 / 3d692df test_install_dump_page.py).
Runs without game data and without Inno Setup.

    python3 tools/release/test_install_rules.py

Cases:
  - TimeStampsInUTC=yes: the payload's file times are converted to the player's time zone (Inno's default keeps the
    build machine's local times, which put a UTC-built release hours in the future west of UTC).
  - ArchiveProblem: the dump page takes USRDIR\\data_ps3.psarc or its FAT32 parts .66600, .66601, ... and names the
    missing file; a transcription of the Pascal agrees with firstrun_check.split_parts on the folder-pick cases (one
    file, all parts, a gap, no first part, the first part only, nothing, an unrelated suffix).
  - WritePaths: the wizard's folders go to kz2-install.ini [paths] (dump, update, eboot) from [Code] at ssPostInstall,
    whether or not "Build now" is ticked; never an [INI] entry (Inno's setup log prints [INI] values).
  - OneDrive (Project Helghast v0.1.2): InOneDrive/InstallDirProblem refuse an install folder inside OneDrive, on the folder page
    and in PrepareToInstall (silent /DIR=); a transcription agrees with firstrun_check.onedrive_root_of.
  - Dump and update pages (Project Helghast v0.1.2): PS3_GAME / USRDIR picks resolved (wizard and silent), the TITLE_ID read
    by SfoField (a transcription agrees with firstrun_check.read_sfo) and named, only BCUS98116 accepted, the Trilogy
    disc named, the update's id must be the disc's; the EBOOT page takes a folder (Project Helghast v0.1.4); Inno pitfalls.
Exit 0 = PASS, 1 = FAIL.
"""
import os
import re
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import firstrun_check as fc  # noqa: E402

bad = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        bad.append(msg)


def find_iss():
    for rel in (("installer", "kz2.iss"),):
        p = os.path.join(ROOT, *rel)
        if os.path.isfile(p):
            return p
    return ""


ISS = find_iss()
t = open(ISS, encoding="utf-8").read() if ISS else ""
check(bool(t), "installer/kz2.iss found")


def func(name):
    """The text of one [Code] function or procedure: from its header to the first 'end;' at the start of a line."""
    m = re.search(r"^(function|procedure) " + re.escape(name) + r"\b.*?^end;", t, re.M | re.S)
    return m.group(0) if m else ""


def section(name):
    m = re.search(r"^\[" + re.escape(name) + r"\]\s*$(.*?)(?=^\[[A-Za-z]+\]\s*$)", t, re.M | re.S)
    return m.group(1) if m else ""


# file times
setup = section("Setup")
check(re.search(r"^TimeStampsInUTC=yes\s*$", setup, re.M) is not None,
      "TimeStampsInUTC=yes in [Setup] (file times converted to the player's time zone, not future-dated)")

# split disc archive on the dump page
f = func("ArchiveProblem")
check("'data_ps3.psarc'" in f and "66600" in f and "FileExists(Usr + 'data_ps3.psarc.' + IntToStr(N))" in f
      and "66601 to 66640" in f and "data_ps3.psarc.66600 is missing" in f and "data_ps3.psarc is missing" in f,
      "ArchiveProblem takes the file or consecutive parts from .66600 and names the missing file")
nb = func("NextButtonClick")
check("ArchiveProblem(AddBackslash(Dir) + 'PS3_GAME\\USRDIR\\')" in func("DumpProblem") and "DumpProblem(" in nb,
      "the dump page asks ArchiveProblem (through DumpProblem)")
check("FileExists(D + 'PS3_GAME\\USRDIR\\data_ps3.psarc')" not in nb,
      "no single-file-only archive check is left on the dump page")


def archive_problem(usr):
    """ArchiveProblem transcribed: -> the name of the missing file, '' when the archive is there."""
    ex = lambda n: os.path.isfile(os.path.join(usr, "data_ps3.psarc" + n))  # noqa: E731
    if ex(""):
        return ""
    n = 66600
    while ex("." + str(n)):
        n += 1
    if n > 66600:
        return "data_ps3.psarc." + str(n) if any(ex("." + str(k)) for k in range(n + 1, n + 41)) else ""
    if any(ex("." + str(k)) for k in range(66601, 66641)):
        return "data_ps3.psarc.66600"
    return "data_ps3.psarc"


with tempfile.TemporaryDirectory() as tmp:
    cases = {"single": [""], "all": [".66600", ".66601", ".66602"], "gap": [".66600", ".66601", ".66603"],
             "no first": [".66601", ".66602"], "first only": [".66600"], "none": [], "other": [".bak"]}
    want = {"single": "", "all": "", "gap": "data_ps3.psarc.66602", "no first": "data_ps3.psarc.66600",
            "first only": "", "none": "data_ps3.psarc", "other": "data_ps3.psarc"}
    for name, sufs in cases.items():
        usr = os.path.join(tmp, name.replace(" ", "_"))
        os.makedirs(usr)
        for s in sufs:
            open(os.path.join(usr, "data_ps3.psarc" + s), "wb").write(b"x")
        parts, missing = fc.split_parts(os.path.join(usr, "data_ps3.psarc"))
        check(archive_problem(usr) == missing == want[name],
              f"ArchiveProblem and firstrun_check.split_parts agree: {name} ({missing!r})")

# the wizard's folders, given once
f = func("WritePaths")
check(all(("SetIniString('paths', '%s'" % k) in f for k in ("dump", "update", "eboot")) and "kz2-install.ini" in f
      and "DumpDir" in f and "UpdateDir" in f and "EbootFile" in f,
      "WritePaths writes the wizard's folders to kz2-install.ini [paths]")
check("(DumpDir = '') or (UpdateDir = '') then Exit" in f, "WritePaths writes nothing without a dump and an update")
f = func("CurStepChanged")
line = next((ln for ln in f.splitlines() if "WritePaths" in ln), "")
check("CurStep = ssPostInstall" in line and "buildnow" not in line,
      "WritePaths runs at ssPostInstall whether or not buildnow is ticked")
check(f.find("RunBuild") < f.find("WritePaths"), "WritePaths runs after RunBuild (the RPCS3 lookup fills the folders)")
check('Section: "paths"' not in section("INI"), "no [INI] entry for [paths] (the setup log would show it)")

# OneDrive (adapted from Project Helghast v0.1.2): the install folder inside OneDrive is refused, silent too
f = func("InOneDrive")
check(all(v in f for v in ("'OneDrive'", "'OneDriveConsumer'", "'OneDriveCommercial'")) and "GetEnv(" in f
      and "Lowercase(" in f and "Pos(B + '\\', D) = 1" in f,
      "InOneDrive reads the three OneDrive env vars, case-insensitive whole-component prefix match")
f = func("InstallDirProblem")
check("InOneDrive(D)" in f and "inside OneDrive" in f and "outside OneDrive" in f and "%LOCALAPPDATA%" in f,
      "InstallDirProblem refuses OneDrive with the plain message")
f = func("PrepareToInstall")
check("InstallDirProblem(ExpandConstant('{app}'))" in f, "PrepareToInstall applies it before any file is written (/DIR=)")
check("InstallDirProblem(WizardDirValue)" in func("NextButtonClick"), "the folder page says it on Next")


def onedrive(path, env):
    """InOneDrive transcribed, against firstrun_check.onedrive_root_of (the O1 rule)."""
    d = path.rstrip("\\").lower()
    return any(b and (d == b or d.startswith(b + "\\"))
               for b in ((env.get(v) or "").rstrip("\\").lower() for v in fc.ONEDRIVE_VARS))


env = {"OneDrive": "C:\\Users\\a\\OneDrive", "OneDriveCommercial": "D:\\W\\OneDrive - Corp"}
for pth in ("C:\\Users\\a\\OneDrive\\Project Pyrrhus", "c:\\users\\A\\onedrive", "C:\\Users\\a\\OneDrive2\\x",
            "D:\\W\\OneDrive - Corp\\x\\Project Pyrrhus", "C:\\Users\\a\\AppData\\Local\\Programs\\Project Pyrrhus"):
    check(onedrive(pth, env) == bool(fc.onedrive_root_of(pth, env)), f"InOneDrive and firstrun_check O1 agree: {pth}")

# Dump and update pages (adapted from Project Helghast v0.1.2)
f = func("ResolveDump")
check("'PS3_GAME\\PARAM.SFO'" in f and "EndsWithName(D, 'USRDIR')" in f and "EndsWithName(D, 'PS3_GAME')" in f
      and "ExtractFileDir" in f, "ResolveDump walks up from PS3_GAME and PS3_GAME\\USRDIR")
f = func("ResolveUpdate")
check("'USRDIR'" in f and "PARAM.SFO" in f and "ExtractFileDir" in f, "ResolveUpdate takes USRDIR to the update folder")
f = func("SfoField")
check("LoadStringFromFile" in f and "SfoInt(S, 8, 4)" in f and "SfoInt(S, 12, 4)" in f and "SfoInt(S, 16, 4)" in f
      and "20 + 16 * I" in f and "SfoInt(S, E, 2)" in f and "SfoInt(S, E + 4, 4)" in f and "SfoInt(S, E + 12, 4)" in f,
      "SfoField reads the header and the 16-byte entries like read_sfo")
f = func("DumpProblem")
check("Id <> 'BCUS98116'" in f and "'This is ' + Id" in f and "not Killzone 2" in f and "ArchiveProblem(" in f,
      "DumpProblem accepts only BCUS98116, names any other id and title, and asks ArchiveProblem")
check("'02.00'" in func("IsTrilogy"), "the Trilogy disc (VERSION 02.00) is recognised")
f = func("UpdateIdProblem")
check("Id <> DiscId" in f and "'TITLE_ID'" in f, "UpdateIdProblem: the update carries the disc's TITLE_ID")
nb = func("NextButtonClick")
check("DumpPage.Values[0] := ResolveDump(DumpPage.Values[0])" in nb
      and "UpdatePage.Values[0] := ResolveUpdate(UpdatePage.Values[0])" in nb and "DumpProblem(" in nb
      and "UpdateIdProblem(" in nb and "Killzone Trilogy disc" in nb,
      "NextButtonClick resolves both pages in place, names the Trilogy disc, checks the update's id")
check("'USRDIR\\EBOOT.elf'" in nb and "DirExists(EbootPage.Values[0])" in nb,
      "the EBOOT page takes a folder: its EBOOT.elf or USRDIR\\EBOOT.elf, else says where it looked")
rb = func("RunBuild")
check("ResolveDump(ExpandConstant('{param:DUMP|}'))" in rb and "ResolveUpdate(ExpandConstant('{param:UPDATE|}'))" in rb,
      "silent /DUMP= /UPDATE= are resolved the same way")
check("DumpEditChange" in func("InitializeWizard") and "Found: " in func("DumpEditChange"),
      "the dump page names what it found under the edit")
# a decrypted disc ISO as the dump (Project Helghast v0.1.2): picked by name, opened by the first build step
f = func("IsIsoPick")
check("'.iso'" in f and "FileExists(Path)" in f and "not DirExists(Path)" in f, "IsIsoPick: an existing .iso file")
check("if IsIsoPick(D) then Exit;" in func("ResolveDump"), "ResolveDump leaves an ISO pick alone")
f = func("DumpProblem")
check("if IsIsoPick(Dir) then Exit" in f and "was not found" in f and "decrypted .iso file" in f,
      "DumpProblem accepts an ISO pick and names a missing one")
check("GetOpenFileName(" in func("DumpIsoClick") and "@DumpIsoClick" in func("InitializeWizard"),
      "the dump page has a Browse button for an ISO file")
check("IsIsoPick(" in nb and "GetSpaceOnDisk64(" in nb, "the dump page logs an ISO and asks when the drive is short")
check("IsIsoPick(" in func("UpdateReadyMemo") and "IsIsoPick(" in func("DumpEditChange"), "the ready memo and the page "
      "say an ISO's files are copied")
check('Name: "{app}\\game"' in section("UninstallDelete"), "the files copied out of an ISO go with the port")

code = t[t.find("[Code]"):]
braced = [c for c in re.findall(r"\{[^}]*\}", code) if "{" in c[1:] and not c.startswith("{#")]
check(not braced, "no '{' inside a { } comment in [Code]")
check(not [ln for ln in code.splitlines() if re.match(r"\s*#\d", ln)], "no [Code] line starts with a #NN constant")


def sfo_field(d, key):
    """SfoField transcribed."""
    if len(d) < 20 or d[:4] != b"\0PSF":
        return ""

    def i(p, n):
        return int.from_bytes(d[p:p + n], "little") if p >= 0 and p + n <= len(d) else 0

    def s(p, mx):
        out = b""
        for k in range(p, min(len(d), p + mx)):
            if d[k] == 0:
                break
            out += d[k:k + 1]
        return out.decode()
    kt, dt, n = i(8, 4), i(12, 4), min(i(16, 4), 200)
    for k in range(n):
        e = 20 + 16 * k
        if s(kt + i(e, 2), 32) == key:
            return s(dt + i(e + 12, 4), i(e + 4, 4))
    return ""


def make_sfo(fields):
    keys, data, ents = b"", b"", b""
    for k, v in fields.items():
        ents += struct.pack("<HHIII", len(keys), 0x204, len(v) + 1, 16, len(data))
        keys += k.encode() + b"\0"
        data += v.encode() + b"\0" + b"\0" * (15 - len(v))
    kt = 20 + 16 * len(fields)
    return struct.pack("<4sIIII", b"\0PSF", 0x101, kt, kt + len(keys), len(fields)) + ents + keys + data


with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "PARAM.SFO")
    for tid, ver in (("BCUS98116", "01.01"), ("BCUS98116", "02.00"), ("BCES00081", "01.00")):
        open(p, "wb").write(make_sfo({"APP_VER": "01.01", "TITLE_ID": tid, "VERSION": ver}))
        raw = open(p, "rb").read()
        check(sfo_field(raw, "TITLE_ID") == tid == fc.read_sfo(p)["TITLE_ID"] and sfo_field(raw, "VERSION") == ver
              and sfo_field(raw, "NOPE") == "", f"SFO reader algorithm agrees with read_sfo: {tid} {ver}")

print("test_install_rules:", "PASS" if not bad else f"FAIL ({len(bad)})")
sys.exit(1 if bad else 0)
