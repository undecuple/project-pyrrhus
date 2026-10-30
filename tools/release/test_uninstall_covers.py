#!/usr/bin/env python3
"""Host test: every file or folder the launcher and the first run write under the install folder {app}, and that Inno
did not install itself, has a matching [UninstallDelete] entry in installer/kz2.iss. Without one, Inno's last
`dirifempty` step leaves the install folder behind after an uninstall. Adapted from Project Helghast (the Killzone 3
PC port, same author, MIT), Project Helghast v0.1.1 test_uninstall_covers.py: KZ3's Windows 10 VM uninstall left the first-run
log, rotated logs and payload folders with __pycache__.

The write paths come from launch.py (FIRSTRUN_LOG, the logs folder), firstrun.py (DEFAULT_LOG_NAME and its rotate(),
run for real on a temp file so a renamed rotation pattern is caught) and assemble_payload.RULES (the payload folders,
where Python writes __pycache__). User data in %APPDATA% (saves) is out of scope by design. Needs no game data.

    python3 tools/release/test_uninstall_covers.py      (exit 0 = PASS, 1 = FAIL)
"""
import fnmatch
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import assemble_payload as ap  # noqa: E402
import firstrun as fr  # noqa: E402
import launch  # noqa: E402

ISS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "installer", "kz2.iss")
bad = 0


def check(ok, msg):
    global bad
    bad += not ok
    print(("ok   " if ok else "FAIL ") + msg)


def uninstall_patterns(text):
    """-> [(type, pattern relative to {app}, lower case)] from [UninstallDelete], #defines expanded."""
    defs = dict(re.findall(r'^#define (\w+) "([^"]*)"', text, re.M))
    sec = re.search(r"^\[UninstallDelete\]\n(.*?)(?=^\[)", text, re.M | re.S).group(1)
    out = []
    for m in re.finditer(r'^Type: (\w+); Name: "([^"]+)"', sec, re.M):
        name = re.sub(r"\{#(\w+)\}", lambda d: defs[d.group(1)], m.group(2))
        if name.startswith("{app}\\"):
            out.append((m.group(1), name[len("{app}\\"):].replace("\\", "/").lower()))
    return out


def covered(rel, pats):
    """A file or folder rel (relative to {app}) goes when a pattern matches it or a folder above it (filesandordirs)."""
    r = rel.lower()
    for typ, p in pats:
        if fnmatch.fnmatchcase(r, p):
            return True
        if typ == "filesandordirs" and r.startswith(p.rstrip("/") + "/"):
            return True
    return False


def rotated(name):
    """The names firstrun.rotate gives an earlier log called `name` (run on a temp file, twice)."""
    with tempfile.TemporaryDirectory() as d:
        out = []
        for _ in range(2):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write("# started 2026-01-01T12:00:00\n")
            out.append(os.path.basename(fr.rotate(os.path.join(d, name))))
        return out


def pascal(text, name):
    """The body of a [Code] function or procedure."""
    m = re.search(r"^(?:function|procedure) " + name + r"\b.*?^end;", text, re.M | re.S)
    return m.group(0) if m else ""


def vfs_places(text):
    """The VFS folders outside the install folder (launch.py alt_vfs_root: %LOCALAPPDATA%\\Project Pyrrhus\\vfs-<key>,
    one per install) are removed by kz2.iss RemoveVfsFolders at usUninstall: the key is computed the same way on both
    sides, the launcher's record is the one the uninstaller reads, links go before any recursive delete."""
    key = pascal(text, "InstallKey")
    n = len(launch.install_key("C:\\x"))
    check("GetSHA256OfUnicodeString(S)" in key and f"Copy(Lowercase(GetSHA256OfUnicodeString(S)), 1, {n})" in key
          and "Lowercase(App)" in key and "StringChangeEx(S, '/', '\\', True)" in key and "Length(S) > 3" in key,
          "kz2.iss InstallKey: SHA-256 of the UTF-16 path, ASCII lower case, '/' -> '\\', trailing '\\' off, "
          f"{n} hex digits (as launch.install_key)")
    check(re.search(r"\\vfs-'\) \+ InstallKey\(ExpandConstant\('\{app\}'\)\)", pascal(text, "RemoveVfsFolders"))
          and launch.ALT_PREFIX == "vfs-", "the uninstaller's second place is launch.ALT_PREFIX + InstallKey({app})")
    src = open(os.path.join(HERE, "launch.py"), encoding="utf-8").read()
    check("GetIniString('vfs', 'alt'" in pascal(text, "RemoveVfsFolders") and 'try_write_ini(root, "vfs", "alt", v' in src,
          "the launcher's [vfs] alt record is the one the uninstaller reads")
    check("IsOwnAltVfs(Rec)" in pascal(text, "RemoveVfsFolders"), "a recorded place is used only inside our own folder")
    rm = pascal(text, "RemoveVfsFolder")
    links = [rm.find(f"RemoveDir(Dir + '\\{x}')") for x in ("PS3_GAME", launch.LINK_TEST, launch.LINK_TEST + "-target")]
    guard = rm.find("if DirExists(Dir + '\\PS3_GAME') or DirExists(Dir + '\\" + launch.LINK_TEST + "')")
    tree = rm.find("DelTree(Dir")
    check(min(links) >= 0 and 0 <= guard < tree and max(links) < guard and "Exit;" in rm[guard:tree],
          "RemoveVfsFolder removes the links first and deletes the folder whole only when no link is left")
    cus = pascal(text, "CurUninstallStepChanged")
    check(re.search(r"usUninstall then begin.*?RemoveVfsFolders;.*?Exit;", cus, re.S) is not None,
          "RemoveVfsFolders runs at usUninstall, before [UninstallDelete] (the links go first)")
    sec = re.search(r"^\[UninstallDelete\]\n(.*?)(?=^\[)", text, re.M | re.S).group(1)
    check(not [ln for ln in sec.splitlines() if ln.startswith("Type:") and "ps3_game" in ln.lower()],
          "no [UninstallDelete] line names a PS3_GAME link")


def main():
    with open(ISS, encoding="utf-8") as f:
        text = f.read()
    pats = uninstall_patterns(text)
    check(len(pats) > 10, f"{len(pats)} {{app}} entries read from [UninstallDelete]")

    files = {
        "first-run log (launch.FIRSTRUN_LOG)": launch.FIRSTRUN_LOG,
        "setup log written here (firstrun.DEFAULT_LOG_NAME)": fr.DEFAULT_LOG_NAME,
        "launcher log": "logs/launcher.log",
        "version check log": "logs/version-check.log",
        "copied first-run logs": "logs/firstrun-20260101-120000.log",
        "install settings": "kz2-install.ini",
        "the menu's version file, portable (launch.VERSION_INI)": launch.VERSION_INI,
        "its temp file (launch.write_version_ini)": launch.VERSION_INI + ".tmp",
        "build output": "build/kz2.exe",
        "build paths": "build/paths.json",
        "build cache": "build/cache/edat/x",
        "game VFS records": "vfs/link.json",
        "game VFS caches": "vfs/psarc-cache/x",
        "portable caches": "cache/x",
        "portable scratch": "scratch/x",
        "files copied out of a decrypted ISO (firstrun.iso_dest)": "game/disc/PS3_GAME/USRDIR/data_ps3.psarc",
    }
    for n in rotated(launch.FIRSTRUN_LOG):
        files[f"first-run log, rotated ({n})"] = n
    for n in rotated(fr.DEFAULT_LOG_NAME):
        files[f"setup log, rotated ({n})"] = n
    for what, rel in files.items():
        check(covered(rel, pats), f"{what}: {rel}")

    # The payload's own folders: Inno removes the files it installed, but Python (kz2-setup, the embedded toolchain
    # python, the toolkit's scripts) writes __pycache__ beside them; the folder must go whole. Folders holding no
    # program are exempt.
    exempt = {"licenses", "fonts", "runtime"}
    tops = {d.split("/")[0] for _, d, kind, _ in ap.RULES if "/" in d or kind == "tree"} | {"toolchain"}
    for t in sorted(tops - exempt):
        check(covered(t + "/__pycache__/x.pyc", pats), f"payload folder {t}/ goes whole (any __pycache__ in it)")
    # and the vfs junction to the player's dump is never recursed into
    check(not covered("vfs/PS3_GAME/USRDIR/data_ps3.psarc", pats), "the dump behind vfs/PS3_GAME is never listed")
    vfs_places(text)
    print("test_uninstall_covers:", "PASS" if not bad else f"FAIL ({bad})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
