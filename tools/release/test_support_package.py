#!/usr/bin/env python3
"""Host test for tools/release/support.py and launch.py --support-package (no game data, no network): a fake install
with planted user paths (this machine's home folder, a Windows C:\\Users\\<name> folder in both slash styles and
doubled backslashes) and the PC's name; the zip must hold them scrubbed, text only, the newest 3 game logs and at
most 10 crash reports, never the saves, build/paths.json, a minidump or a game-file name, and stay under 20 MB of
text with a 26 MB log (oldest lines cut, marked); launch.py's REPORT names the Start menu entry, kz2.iss has it,
TROUBLESHOOTING.md explains it, and launch.py --support-package writes the zip and opens its folder.
Exit 0 = PASS.

    python3 tools/release/test_support_package.py
"""
import os
import socket
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import public_layout  # noqa: E402  (docs/ is in public/ here, at the root once exported)
sys.path.insert(0, HERE)
import launch  # noqa: E402
import support  # noqa: E402

fails = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def put(root, rel, data, age=0):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
    t = time.time() - age
    os.utime(p, (t, t))
    return p


HOME = os.path.expanduser("~")
HOST = socket.gethostname()
PLANT = (f"dump at {HOME}/Games/KZ2/PS3_GAME\n"
         "update at C:\\Users\\Example Alice\\AppData\\Roaming\\rpcs3\\dev_hdd0\\game\\BCUS98116\n"
         "json form C:\\\\Users\\\\Example Alice\\\\Documents\\\\x\n"
         "forward C:/Users/Example Alice/Desktop/kz2\n"
         f"pc name {HOST} here, lower {HOST.lower()}\n")


class FakeUI:
    def __init__(self):
        self.said = []

    def info(self, text):
        self.said.append(text)

    def ask(self, text):
        self.said.append(text)
        return False


with tempfile.TemporaryDirectory() as t:
    root = os.path.join(t, "Project Pyrrhus")
    for i in range(5):
        put(root, f"build/logs/kz2-2026112{i}-120000.log", f"session {i}\n" + PLANT, age=1000 - i)
    for i in range(12):
        put(root, f"build/logs/crash-{i:02d}.txt", f"crash {i}\n" + PLANT, age=2000 - i)
    put(root, "build/logs/crash-00.dmp", b"MDMP\0\0" + bytes(100))
    put(root, "build/logs/EBOOT.elf.log", "not a log\n")
    put(root, "build/paths.json", '{"dump": "C:\\\\Users\\\\Example Alice\\\\kz2"}')
    put(root, "build/build-stamp.json", '{"port": "0.1.14"}')
    put(root, "gamedata/BCUS98116-SAVE/SYS-DATA", b"\0save")
    put(root, "logs/launcher.log", "start: run\n" + PLANT)
    put(root, "logs/Project-Pyrrhus-setup.log", "x\n")
    put(root, "logs/firstrun-status.txt", "RESULT ok=1\n")
    put(root, "Project-Pyrrhus-firstrun.log", "first run\n" + PLANT)
    put(root, "kz2-install.ini", "[install]\nportable=1\n")
    put(root, "VERSION.txt", "0.1.14\n")
    put(root, "keybinds.ini", "[keys]\nfire=Mouse Left\n")
    big = "".join(f"line {i:08d} {HOME}/x\n" for i in range(26 << 20 >> 5))
    put(root, "build/logs/kz2-20260130-000000.log", big, age=500)      # the newest log, about 26 MB

    dest = support.build(root, root, out=os.path.join(t, "out"), stamp="20261125-120000", environ={})
    check(os.path.basename(dest) == "Project-Pyrrhus-support-20261125-120000.zip", "zip name")
    with zipfile.ZipFile(dest) as z:
        names = z.namelist()
        texts = {n: z.read(n).decode("utf-8") for n in names}
    check(len([n for n in names if n.startswith("game/")]) == 3, "the newest 3 game logs")
    crash = [n for n in names if n.startswith("crash/")]
    check(len(crash) == 10 and "crash/crash-11.txt" in crash and "crash/crash-00.txt" not in crash,
          "the newest 10 crash reports, no more")
    check(all(n.endswith((".log", ".txt", ".ini", ".json")) for n in names), "text files only")
    check(not any(x in n for n in names for x in ("paths.json", ".dmp", "EBOOT", "gamedata", "SYS-DATA")),
          "no saves, paths.json, minidump or game-file name")
    check({"install/launcher.log", "install/Project-Pyrrhus-firstrun.log", "install/kz2-install.ini",
           "install/build-stamp.json", "settings/keybinds.ini", "facts.txt"} <= set(names), "install logs, settings, facts")
    alltext = "\n".join(texts.values())
    check("Alice" not in alltext and "<user>" in alltext, "planted Windows user folders are scrubbed (all three forms)")
    check(HOME not in alltext and "%USERPROFILE%" in alltext, "this machine's home folder is scrubbed")
    check(len(HOST) <= 2 or (HOST.lower() not in alltext.lower() and "<pc>" in alltext), "the PC's name is left out, any case")
    total = sum(len(v.encode("utf-8")) for v in texts.values())
    check(total <= support.CAP and support.CAP == 20 << 20, f"under 20 MB of text ({total:,} bytes)")
    check(any(v.startswith(support.MARKER) for v in texts.values()) and "(shortened)" in texts["facts.txt"],
          "the big log lost its oldest lines, marked, and facts.txt says so")
    check("Project Pyrrhus 0.1.14" in texts["facts.txt"] and "logical CPUs" in texts["facts.txt"], "facts: version and system")

    empty = os.path.join(t, "empty")
    os.makedirs(empty)
    check(support.build(empty, empty, out=os.path.join(t, "o2")) == "", "nothing to pack -> no zip")

    ui, opened = FakeUI(), []
    rc = launch.support_package(root, root, ui, opener=opened.append)
    made = [n for n in os.listdir(os.path.join(root, "logs")) if n.startswith("Project-Pyrrhus-support-")]
    check(rc == 0 and len(made) == 1 and opened == [os.path.join(root, "logs")] and "Nothing was sent" in ui.said[-1],
          "launch.support_package: zip in <install>/logs, message, folder opened")
    ui2 = FakeUI()
    check(launch.support_package(empty, empty, ui2, opener=opened.append) == 1 and "Nothing to put" in ui2.said[-1],
          "launch.support_package: an empty install says so")

check(launch.SUPPORT_ENTRY in launch.REPORT and "--support-package" in launch.REPORT, "REPORT names the support package")
with open(os.path.join(REPO, "installer", "kz2.iss"), encoding="utf-8") as f:
    iss = f.read()
check(f'Name: "{{group}}\\{launch.SUPPORT_ENTRY}"; Filename: "{{app}}\\{{#LauncherExe}}"; Parameters: "--support-package"'
      in iss, "kz2.iss: the Start menu entry")
with open(public_layout.public_path(REPO, "docs/TROUBLESHOOTING.md"), encoding="utf-8") as f:
    check(launch.SUPPORT_ENTRY in f.read(), "TROUBLESHOOTING.md explains it")

# scrub(): what the redactor does not cover (review 2026-11-26)
ENV = {"USERNAME": "exampledoe", "USERPROFILE": r"D:\Profiles\exampledoe", "APPDATA": r"\\fs01\home\exampledoe\AppData",
       "HOMEDRIVE": "H:", "HOMEPATH": r"\Home\exampledoe"}
RAW = ("USERNAME=exampledoe user: exampledoe owner exampledoe here\n"
       r"profile D:\Profiles\exampledoe\x, json D:\\Profiles\\exampledoe\\x, slash d:/profiles/EXAMPLEDOE/y" "\n"
       r"roaming \\fs01\home\exampledoe\AppData\k, home H:\Home\exampledoe\z, other \\nas\share\f" "\n"
       "pc exampledoe-pc8 and EXAMPLEDOE-PC8 and Exampledoe-Pc8.local\n")
out = support.scrub(RAW, "EXAMPLEDOE-PC8", ENV)
check("exampledoe" not in out.lower() and "fs01" not in out and "nas\\share" not in out and "profiles" not in out.lower(),
      "scrub: account name, profile on another drive, network profile and share, any case: " + out.replace("\n", " | "))
check(out.count("<pc>") == 3 and "%USERPROFILE%" in out and "%APPDATA%" in out and "%HOMEDRIVE%%HOMEPATH%" in out
      and "USERNAME=<user>" in out and "user: <user>" in out, "scrub: the labels say what was there")
# negative control: the redactor alone (the old clean()) leaves these
old = support.fr.redactor()(RAW).replace("EXAMPLEDOE-PC8", "<pc>")   # the clean() before scrub()
check("exampledoe" in old.lower() and "fs01" in old, "negative control: without scrub() the names stay")
check(support.scrub("user=ab owner ab", "x", {"USERNAME": "ab"}) == "user=<user> owner ab",
      "a two-letter account name is scrubbed only after user=, not as a word")

print("PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
