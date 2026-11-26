#!/usr/bin/env python3
"""The support package: one zip a player attaches to a bug report. Nothing is sent anywhere.

    launch.py --support-package          (Start menu: "Make a support package")
    support.py --root DIR [--out DIR]    (the same, without the launcher's message boxes)

Adapted from Project Vekta's tools/release/support.py (github.com/gustavomorinaga/project-vekta, commit
fd97c34f5654, main 2026-11-24; MIT, Copyright (c) 2026 Gustavo Morinaga and the Project Vekta contributors; itself after Project
Helghast's support.py, same author as this project, MIT): the idea, the file list's shape, the name filter and the
trimming. Not taken: its symbol pass, its Windows event and kernel log reads and its typed report.

What goes in, text only, every file through firstrun.redactor() (the home folder becomes %USERPROFILE%, other user
folders <user>) and then scrub(): the PC's name becomes <pc> in any letter case, the Windows account name <user> (as a
word, and after USERNAME=, user= and the like), the profile and data folders Windows names in the environment
(USERPROFILE, HOMESHARE, HOMEDRIVE+HOMEPATH, APPDATA, LOCALAPPDATA, OneDrive: on another drive or a network share
too) %NAME%, and any other network path's server and share <server> and <share>:
- the newest GAME_LOGS game logs (build/logs/kz2-*.log) and the newest CRASH_FILES crash reports the game wrote
  (build/logs/crash-*.txt);
- the install's own logs: logs/launcher.log, the newest two first-run logs (logs/*firstrun*.log and the zip's
  Project-Pyrrhus-firstrun.log), logs/firstrun-status.txt and logs/version-check.txt;
- kz2-install.ini, build/build-stamp.json, VERSION.txt, and the settings in the data folder (keybinds.ini,
  display.ini, gameplay.ini);
- facts.txt: the port's version, the system (platform, version, processor, logical CPUs, memory, free space on the
  install's drive) and which of the files above are in the package.
Never: the saves (gamedata), build/paths.json (the folders your files are in), the game files, minidumps or any other
binary. Only .log, .txt, .ini and .json names are read and a game-file name is refused. Over CAP bytes of text, the
oldest lines of the largest files go first. Zip name: Project-Pyrrhus-support-YYYYmmdd-HHMMSS.zip, written to
<install>/logs unless --out says otherwise. Standard library only.
"""
import argparse
import fnmatch
import glob
import os
import re
import platform
import shutil
import socket
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402

CAP = 20 << 20          # bytes of text in the zip (uncompressed); the zip itself is smaller
OK_EXT = (".log", ".txt", ".ini", ".json")
GAME_LOGS = 3           # newest game session logs
CRASH_FILES = 10        # newest crash reports
FIRSTRUN_LOGS = 2
# game-file names (assemble_payload.DENY_NAMES and a few more): never read, whatever their extension says
DENY = ("eboot.*", "eboot*.bin", "param.sfo", "*.psarc", "*.elf", "*.self", "*.sprx", "*.prx", "*.edat", "*.sdat",
        "*.pkg", "*.rap", "*.pup", "*.core", "*.corestream", "*.bik", "*.at3", "*.trp", "paths.json")
MARKER = "[earlier lines removed to keep the package small]\n"
SETTINGS = ("keybinds.ini", "display.ini", "gameplay.ini")
ZIP_FIRSTRUN = "Project-Pyrrhus-firstrun*.log"   # the portable zip's first-run log (run.cmd --log-name), beside run.cmd


def refused(name):
    n = os.path.basename(name).lower()
    return any(fnmatch.fnmatch(n, p) for p in DENY) or not n.endswith(OK_EXT)


def zip_name(stamp):
    return f"Project-Pyrrhus-support-{stamp}.zip"


def newest(pattern, n):
    files = [p for p in glob.glob(pattern) if os.path.isfile(p) and not refused(p)]
    return sorted(files, key=lambda p: (os.path.getmtime(p), p), reverse=True)[:n]


def candidates(root, data):
    """[(name in the zip, path)], in the order facts.txt lists them."""
    logs, glogs = os.path.join(root, "logs"), os.path.join(root, "build", "logs")
    out = [("game/" + os.path.basename(p), p) for p in newest(os.path.join(glogs, "kz2-*.log"), GAME_LOGS)]
    out += [("crash/" + os.path.basename(p), p) for p in newest(os.path.join(glogs, "crash-*.txt"), CRASH_FILES)]
    runs = newest(os.path.join(logs, "*firstrun*.log"), FIRSTRUN_LOGS + 1) + \
        newest(os.path.join(root, ZIP_FIRSTRUN), FIRSTRUN_LOGS)
    runs = sorted(set(runs), key=lambda p: (os.path.getmtime(p), p), reverse=True)[:FIRSTRUN_LOGS]
    out += [("install/" + os.path.basename(p), p) for p in runs]
    out += [("install/" + n, os.path.join(logs, n)) for n in ("launcher.log", "firstrun-status.txt", "version-check.txt")]
    out += [("install/kz2-install.ini", os.path.join(root, "kz2-install.ini")),
            ("install/build-stamp.json", os.path.join(root, "build", "build-stamp.json")),
            ("install/VERSION.txt", os.path.join(root, "VERSION.txt"))]
    out += [("settings/" + n, os.path.join(data, n)) for n in SETTINGS]
    return [(n, p) for n, p in out if os.path.isfile(p) and not refused(p)]


def trim(texts, cap):
    """Drop the oldest lines of the largest entries until the total fits; -> the names of the shortened entries."""
    trimmed = []

    def size():
        return sum(len(t.encode("utf-8")) for t in texts.values())

    while size() > cap:
        n = max(texts, key=lambda k: len(texts[k].encode("utf-8")))
        t = texts[n]
        if len(t) <= len(MARKER):
            break
        cut = max(len(t) // 4, size() - cap)
        nl = t.find("\n", min(cut, len(t) - 1))
        texts[n] = MARKER + (t[nl + 1:] if nl >= 0 else "")
        if n not in trimmed:
            trimmed.append(n)
    return trimmed


def facts(root, names, trimmed, environ):
    try:
        with open(os.path.join(root, "VERSION.txt"), encoding="utf-8") as f:
            version = f.read().strip()
    except OSError:
        version = "(no VERSION.txt)"
    try:
        free = f"{shutil.disk_usage(root).free / (1 << 30):.1f} GiB"
    except OSError:
        free = "(unknown)"
    try:
        ram = f"{fr.available_ram() / (1 << 30):.1f} GiB available"
    except Exception:   # noqa: BLE001  (a fact we cannot read is no reason to stop)
        ram = "(unknown)"
    lines = [f"Project Pyrrhus {version}",
             f"system: {platform.system()} {platform.release()} ({platform.version()})",
             f"processor: {platform.machine()}, {os.cpu_count()} logical CPUs",
             f"memory: {ram}",
             f"free space on the install's drive: {free}",
             f"under RecompLauncher: {'yes' if environ.get('RECOMPLAUNCHER') == '1' else 'no'}",
             "files:"] + [f"  {n}" + (" (shortened)" if n in trimmed else "") for n in names]
    return "\n".join(lines) + "\n"


PROFILE_VARS = ("USERPROFILE", "HOMESHARE", "APPDATA", "LOCALAPPDATA", "OneDrive")
ACCOUNT_KEYS = r"(?:USERNAME|USER|LOGNAME|user|username|account)"
UNC_RX = re.compile(r"(?<![\\\w])(\\\\|\\|//)(?!<server>)[^\\/\s\"'<>|?*]+(\\\\|\\|/)[^\\/\s\"'<>|?*]+")


def _word(v):
    """v as a whole word (no letter or digit on either side), any letter case."""
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def scrub(text, host, environ):
    """What firstrun.redactor() does not cover: the PC name, the account name, profile folders outside C:\\Users and
    network paths (see the module text). Longest folder first; each in plain, doubled-backslash and slash forms."""
    env = {k.upper(): v for k, v in environ.items()}
    folders = [(env.get(k.upper(), ""), "%" + k + "%") for k in PROFILE_VARS]
    if env.get("HOMEDRIVE") and env.get("HOMEPATH"):
        folders.append((env["HOMEDRIVE"] + env["HOMEPATH"], "%HOMEDRIVE%%HOMEPATH%"))
    for v, label in sorted(((v.rstrip("\\/"), lab) for v, lab in folders if v and len(v.rstrip("\\/")) > 3),
                           key=lambda t: -len(t[0])):
        back = v.replace("/", "\\")
        for form in (back.replace("\\", "\\\\"), back, back.replace("\\", "/")):
            text = re.sub(re.escape(form), label.replace("\\", "\\\\"), text, flags=re.IGNORECASE)
    text = UNC_RX.sub(lambda m: m.group(1) + "<server>" + m.group(2) + "<share>", text)
    if host and len(host) > 1:
        text = _word(host).sub("<pc>", text)
    user = env.get("USERNAME") or env.get("USER") or ""
    if user:
        text = re.sub(r"(?i)\b(" + ACCOUNT_KEYS + r")(\s*[=:]\s*)" + re.escape(user) + r"(?![A-Za-z0-9])",
                      lambda m: m.group(1) + m.group(2) + "<user>", text)
        if len(user) > 2:
            text = _word(user).sub("<user>", text)
    return text


def build(root, data, out=None, redact=None, stamp=None, environ=None, cap=CAP):
    """Write the zip; -> its path, or "" when there was nothing to put in it. OSError when it cannot be written."""
    environ = os.environ if environ is None else environ
    redact = redact or fr.redactor()
    host = socket.gethostname()

    def clean(s):
        return scrub(redact(s), host, environ)

    texts = {}
    for name, path in candidates(root, data):
        with open(path, "rb") as f:
            texts[name] = clean(f.read().decode("utf-8", "replace"))
    if not texts:
        return ""
    trimmed = trim(texts, cap - 4096)            # room for facts.txt
    texts["facts.txt"] = clean(facts(root, list(texts), trimmed, environ))
    out = out or os.path.join(root, "logs")
    os.makedirs(out, exist_ok=True)
    dest = os.path.join(out, zip_name(stamp or time.strftime("%Y%m%d-%H%M%S")))
    tmp = dest + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(texts):
            z.writestr(name, texts[name])
    os.replace(tmp, dest)
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True)
    ap.add_argument("--data", default="", help="the data folder (default: the install folder)")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    dest = build(os.path.abspath(a.root), os.path.abspath(a.data or a.root), a.out or None)
    print(dest or "nothing to put in a support package yet")
    return 0 if dest else 1


if __name__ == "__main__":
    sys.exit(main())
