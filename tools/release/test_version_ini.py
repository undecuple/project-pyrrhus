#!/usr/bin/env python3
"""Host test for version.ini, the file the launcher writes at each game start for the version block in the game's menu
(tools/release/launch.py version_info / write_version_ini). Synthetic folders in a temp directory:
no game data, no network, no Windows. Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_version_ini.py

Cases: the option off (current only, even with a newer result on disk); the option on with no check yet; on with a
newer version (newer + page, the leading v dropped); a page outside the project's releases (newer, no page); a stale
newer removed when the option is turned off; the installed version caught up (equal and older latest); a garbled or
offline result; an unwritable folder (a folder named version.ini; a file in the folder's place): a reason, no
exception, no temp file left. The start itself (written into the working folder; a failure logged and the game still
started) is test_launch.py case 9a.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import launch as la  # noqa: E402

FAILS = []


def check(cond, what):
    if not cond:
        FAILS.append(what)


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def keys(folder):
    """The [version] keys of <folder>/version.ini, or None when it is not there."""
    p = os.path.join(folder, la.VERSION_INI)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        raw = f.read()
    out, sec = {}, ""
    for line in raw.decode("ascii").split("\r\n"):
        if line.startswith("["):
            sec = line.strip("[]")
        elif "=" in line and not line.startswith(";") and sec == "version":
            k, v = line.split("=", 1)
            out[k] = v
    return out


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root, data = os.path.join(tmp, "Project Pyrrhus"), os.path.join(tmp, "AppData", "Project Pyrrhus")
        write(os.path.join(root, "VERSION.txt"), "0.1.3\n")
        result = os.path.join(root, "logs", "version-check.txt")
        page = la.RELEASES + "tag/v0.1.4"

        def start(check_updates):
            return la.write_version_ini(data, la.version_info(root, check_updates))

        # 1. option off: current only (also with a newer result left by an earlier check)
        check(start(False) == "" and keys(data) == {"current": "0.1.3"}, f"1 option off {keys(data)}")
        with open(os.path.join(data, la.VERSION_INI), "rb") as f:
            raw = f.read()
        check(raw.startswith(b"; ") and b"\r\n[version]\r\n" in raw and raw.endswith(b"\r\n") and b"\n" not in raw.replace(b"\r\n", b""),
              "1 ASCII, CRLF lines, one comment line first")
        # 2. option on, no check made yet
        check(start(True) == "" and keys(data) == {"current": "0.1.3"}, f"2 on, no check yet {keys(data)}")
        # 3. option on, a newer version found
        write(result, f"VERSION status=newer current=0.1.3 latest=v0.1.4 url={page} setup=- sha256=-\n")
        check(start(True) == "" and keys(data) == {"current": "0.1.3", "newer": "0.1.4", "page": page},
              f"3 newer + page {keys(data)}")
        write(result, "VERSION status=newer current=0.1.3 latest=v0.2.0 url=elsewhere/r setup=-\n")
        check(start(True) == "" and keys(data) == {"current": "0.1.3", "newer": "0.2.0"},
              f"3b a page outside the project's releases is left out {keys(data)}")
        # 4. a stale newer removed when the option is turned off
        write(result, f"VERSION status=newer current=0.1.3 latest=v0.1.4 url={page} setup=-\n")
        start(True)
        check(start(False) == "" and keys(data) == {"current": "0.1.3"}, f"4 option off removes newer {keys(data)}")
        # 5. the installed version caught up (the result is from before the update)
        write(os.path.join(root, "VERSION.txt"), "0.1.4\n")
        check(start(True) == "" and keys(data) == {"current": "0.1.4"}, f"5 caught up (equal) {keys(data)}")
        write(os.path.join(root, "VERSION.txt"), "0.2.0\n")
        check(start(True) == "" and keys(data) == {"current": "0.2.0"}, f"5 past it (older latest) {keys(data)}")
        write(os.path.join(root, "VERSION.txt"), "0.1.3\n")
        # 6. garbled or offline results: current only
        for bad in ("VERSION status=offline current=0.1.3 latest=- url=-\n", "garbage\n", "",
                    "VERSION status=newer current=0.1.3 latest=v0.1.x url=-\n", "\xff\xfe junk\n"):
            write(result, bad)
            check(start(True) == "" and keys(data) == {"current": "0.1.3"}, f"6 result {bad!r} -> current only {keys(data)}")
        # 7. an unwritable folder: a reason, never an exception, no temp file left
        blocked = os.path.join(tmp, "blocked")
        os.makedirs(os.path.join(blocked, la.VERSION_INI))
        err = la.write_version_ini(blocked, la.version_info(root, False))
        check(err.startswith("could not write") and not os.path.exists(os.path.join(blocked, la.VERSION_INI + ".tmp")),
              f"7 a folder named version.ini: {err!r}")
        notdir = os.path.join(tmp, "a-file")
        write(notdir, "x")
        err = la.write_version_ini(notdir, la.version_info(root, False))
        check(err.startswith("could not write"), f"7 a file in the folder's place: {err!r}")
    if FAILS:
        print("test_version_ini: FAIL\n  " + "\n  ".join(FAILS))
        return 1
    print("test_version_ini: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
