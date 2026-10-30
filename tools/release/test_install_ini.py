#!/usr/bin/env python3
"""Host test for install_ini.py (kz2-install.ini read and written line by line; no game data): a comment, a
hand-added key, the key's own case and an unknown section survive a rewrite; a missing key or section is added; the
first of a duplicate key counts; "%" needs no escaping; an ANSI (non-UTF-8) file reads and keeps its encoding; a UTF-8
BOM is read and not written back; a failed read or write raises IniError naming the file. Also launch.py's and
firstrun.py's writers go through it. Exit 0 = PASS, 1 = FAIL."""
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import install_ini as ii  # noqa: E402

FAILS = []


def check(ok, what):
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


SAMPLE = ("; my own note: keep the update check off\r\n"
          "[install]\r\n"
          "portable=0\r\n"
          "\r\n"
          "[online]\r\n"
          "check_updates = 0\r\n"
          "# dismissed is set by the launcher\r\n"
          "MyHandKey = Some Value\r\n"
          "\r\n"
          "[Controls]\r\n"
          "Layout=original\r\n"
          "\r\n"
          "[mine]\r\n"
          "path = C:\\Games\\100%\\kz2\r\n")


def main():
    d = tempfile.mkdtemp(prefix="kz2-ini-test-")
    p = os.path.join(d, ii.NAME)
    with open(p, "wb") as f:
        f.write(SAMPLE.encode("utf-8"))
    ini = ii.read(p)
    check(ini.get("controls", "layout") == "original" and ini.get("CONTROLS", "LAYOUT") == "original",
          "sections and keys match case-insensitively")
    check(ini.get("mine", "path") == "C:\\Games\\100%\\kz2", "a '%' in a value reads as written (no interpolation)")
    check(ini.get("online", "myhandkey") == "Some Value", "a hand-added key reads")

    ii.set_values(p, {("online", "dismissed"): "0.1.5", ("controls", "layout"): "modern",
                      ("display", "mode"): "borderless", ("install", "portable"): "1"})
    raw = open(p, "rb").read()
    text = raw.decode("utf-8")
    check(text.startswith("; my own note: keep the update check off\r\n"), "the leading comment survives")
    check("# dismissed is set by the launcher\r\n" in text, "a comment inside a section survives")
    check("MyHandKey = Some Value\r\n" in text, "a hand-added key keeps its case and value")
    check("[Controls]\r\nLayout=modern\r\n" in text, "a changed key keeps its own case and spacing")
    check("portable=1\r\n" in text, "a value changes in place")
    check("MyHandKey = Some Value\r\ndismissed = 0.1.5\r\n" in text, "a missing key goes after its section's last key")
    check(text.endswith("[display]\r\nmode = borderless\r\n"), "a missing section is added at the end")
    check("[mine]\r\npath = C:\\Games\\100%\\kz2\r\n" in text, "an unknown section survives unchanged")
    check(b"\n" not in raw.replace(b"\r\n", b""), "the file's CRLF line ends are kept")
    check(ii.read(p).get("online", "dismissed") == "0.1.5", "the new key reads back")

    # duplicate key: the first counts, and the first is the one changed
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write("[online]\nlast_check = a\nlast_check = b\n")
    check(ii.read(p).get("online", "last_check") == "a", "duplicate key: the first counts (no error)")
    ii.set_value(p, "online", "last_check", "c")
    check(open(p, encoding="utf-8").read() == "[online]\nlast_check = c\nlast_check = b\n",
          "duplicate key: the first is changed, LF line ends kept")

    # ANSI file (the setup's SetIniString writes the ANSI code page)
    with open(p, "wb") as f:
        f.write("[paths]\r\ndump = D:\\Spiele\\K\xe4fer\r\n".encode("latin-1"))
    check(ii.read(p).get("paths", "dump").endswith("K\xe4fer") or os.name == "nt",
          "an ANSI file with a non-UTF-8 byte reads (no UnicodeDecodeError)")
    ii.set_value(p, "online", "check_updates", "1")
    check(open(p, "rb").read().startswith("[paths]\r\ndump = D:\\Spiele\\K\xe4fer".encode("latin-1")),
          "an ANSI file is written back in its own code page")

    # UTF-8 BOM: read, not written back
    with open(p, "wb") as f:
        f.write(b"\xef\xbb\xbf[install]\nportable = 1\n")
    check(ii.read(p).get("install", "portable") == "1", "a UTF-8 BOM does not hide the first section")
    ii.set_value(p, "install", "portable", "0")
    check(open(p, "rb").read() == b"[install]\nportable = 0\n", "no BOM is written (the setup would misread it)")

    # missing file: empty read, a write creates it
    q = os.path.join(d, "new.ini")
    check(ii.read(q).get("a", "b", "x") == "x", "a missing file reads as empty")
    ii.set_value(q, "controls", "prompts", "auto")
    check(ii.read(q).get("controls", "prompts") == "auto", "a write creates a missing file")

    # failures name the file
    bad = os.path.join(d, "folder.ini")
    os.makedirs(bad)
    try:
        ii.read(bad)
        check(False, "a folder in the file's place raises IniError on read")
    except ii.IniError as e:
        check(bad in str(e), f"a read failure raises IniError naming the file ({e})")
    ro = os.path.join(d, "ro")
    os.makedirs(ro)
    rp = os.path.join(ro, ii.NAME)
    with open(rp, "w") as f:
        f.write("[install]\nportable = 0\n")
    os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
    try:
        if os.access(ro, os.W_OK):
            print("SKIP read-only folder (running as a user who can write anyway)")
        else:
            try:
                ii.set_value(rp, "install", "portable", "1")
                check(False, "a write into a read-only folder raises IniError")
            except ii.IniError as e:
                check(rp in str(e) and open(rp).read() == "[install]\nportable = 0\n",
                      "a write failure raises IniError naming the file and leaves it as it was")
            check([n for n in os.listdir(ro) if n.endswith(".tmp")] == [], "no temporary file left behind")
    finally:
        os.chmod(ro, stat.S_IRWXU)

    # the launcher's and firstrun's writers keep a hand-added key and a comment
    import firstrun as fr
    import launch as L
    root = os.path.join(d, "root")
    os.makedirs(root)
    ip = os.path.join(root, ii.NAME)
    with open(ip, "w", encoding="utf-8") as f:
        f.write("; kept\n[install]\nportable = 0\nMyKey = 1\n")
    L.write_ini(root, "controls", "layout", "modern")
    fr.write_install_ini(root, True, False)
    fr.record_paths(root, "D:\\dump", "D:\\upd", "", wrong=("eboot",))
    t = open(ip, encoding="utf-8").read()
    check(t.startswith("; kept\n[install]\nportable = 1\nMyKey = 1\n"),
          "launch.write_ini, firstrun.write_install_ini and record_paths keep a comment and a hand-added key")
    check(L.read_ini(root)["layout"] == "original" and fr.ini_paths(root).get("wrong") == "eboot",
          "write_install_ini's layout and record_paths' [paths] read back")

    print("FAIL" if FAILS else "PASS", f"({len(FAILS)} failed)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
