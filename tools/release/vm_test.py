#!/usr/bin/env python3
"""Windows VM test of the Project Pyrrhus installer, one step per command. Standard library only,
Python 3.8+; runs on the guest's own Python (3.12 in the test VM) and, for the pre-flight, on the bundled embeddable
Python under Wine/Proton (tools/release/vm_kit.sh preflight).

    "C:\\Program Files\\Python312\\python.exe" vm_test.py STEP [--base C:\\kz2] [--jobs 2] [--wait 60]

Folders under --base: kit\\ (setup exe, this script, SHA256SUMS.txt), game\\dump\\PS3_GAME, game\\update\\BCUS98116,
game\\eboot\\EBOOT.elf (the tester's own files) and out\\, where every step writes out\\NN-name.txt (all it prints)
plus its tool logs, and out\\state.json carries facts between steps. The last line of each step is
"RESULT NN-name PASS|FAIL|SKIP <why>"; the exit code is 0 for PASS and SKIP, 1 for FAIL.

Steps (in order; each can be re-run):
  02-verify     kit hashes against SHA256SUMS.txt, the game files present, machine facts, a fingerprint of the dump
  03-install    setup /VERYSILENT /SUPPRESSMSGBOXES /MERGETASKS="!buildnow" (per-user, default folder); the
                uninstall key and the main files present
  04-layout     the installed files against the payload's manifest.json (launch.py --print --repair), the shortcuts,
                kz2-install.ini, VERSION.txt
  05-checks     the first-run file checks (installed firstrun_check.py on the installed Python)
  06-build      the first-run build (installed firstrun.py, --jobs N, default 2 for an 8 GB guest); kz2.exe and the
                build stamp present; the launcher's decision is "run" afterwards
  07-launch     the launcher once ("Project Pyrrhus.exe"): processes and window titles for --wait seconds, then the
                started tree is ended by process id; the launcher's notes and the game's log tails. A game that stops
                at D3D12 device creation (no GPU in the guest) is expected here and still a PASS if kz2.exe started.
  08-readonly   the same start with the install folder's top level refusing new files for this user (icacls deny
                "create files" on the folder itself, no inheritance; restored after), as an install under Program
                Files would: the launcher and kz2.exe still start (logs\\ and build\\ stay writable); the step records
                which writes fail and that nothing (such as a vkd3d-proton cache) tried to land in the install folder.
                Facts only (SKIP where icacls is missing). A deny of all writes, inherited, also stopped the launch
                (VM run 2026-10-27), so it showed nothing about the cache.
  09-uninstall  unins000.exe /VERYSILENT /SUPPRESSMSGBOXES; waits until the uninstall key is gone
  10-leftovers  the install folder, the shortcuts and the key gone; what is left in %APPDATA%\\Project Pyrrhus is
                user data only (saves and settings, not caches); the dump unchanged (same fingerprint as 02)

First-contact steps (v0.1.2: what players touch first; wrong inputs that need no game data, made in <base>\\t\\). Each
step shows the text the player would see and what was expected ("ok" / "NOT"). Run order: ORDER below.
  11-setup-onedrive   before 03: silent setup with /DIR= inside OneDrive (this machine's, else a stand-in OneDrive
                      variable given to the setup only: then SKIP when refused) -> exit 7, the reason, nothing installed
  12-setup-eboot101   before 03: silent setup with /EBOOT= a stand-in of the disc's 1.01 EBOOT (an ELF header and zeros
                      of its size) -> exit 7, "This is the disc's 1.01 EBOOT" in the log next to setup.exe
  13-bundled-python   the installed embeddable Python keeps a script's folder off sys.path (control), and
                      firstrun_check.py started by full path still imports iso9660 (an .iso as the disc: I2, no traceback)
  14-onedrive-check   the first-run check with --root/--build inside OneDrive (or the stand-in) -> FAIL O1 and the reason
  15-empty-folder     an empty folder as the disc, then as the update -> "Disc dump failed: <path> ... (the folder is
                      empty)", "1.29 update failed: ...", "Passed: ..."
  16-drive-root       the system drive's root (and the kit's drive root) as the disc, then as the update
  17-swapped          the update as the disc and the disc as the update; PS3_GAME as the update; picks one level too
                      deep resolved (INFO D0/U0)
  18-disc-id          the real dump's D1 (BCUS98116); synthetic PARAM.SFO files: another id (FAIL D1 names it), the
                      Trilogy disc (VERSION 02.00: WARN D1 "untested")
  19-iso              a synthetic decrypted ISO (kit's iso_fixture.py) passes; a scrambled one is "encrypted" (I1)
  20-eboot-101        the check refuses the 1.01 stand-in (E1); the console asks for the EBOOT alone, takes a folder
                      answer ("using ..."), refuses again, q records [paths] wrong=eboot (kz2-install.ini put back)
  21-ask-again        a quit after a failed check records wrong=dump; the launcher's next command checks those answers
                      first; the next console start asks only the disc dump again (kz2-install.ini put back)
  22-launcher-dialog  before 06: the real launcher with build\\paths.json naming an empty disc folder: "Continue the
                      build now?" -> Yes, the console's check stops, the dialog lists the stop reasons (dialog texts
                      read from the window; SKIP without a desktop session)
  23-uninstall-cover  just before 09: lists what the first run wrote into the install folder and plants what it may
                      leave (game\\disc from an ISO, a rotated first-run log, the status file); 10-leftovers judges
"""
import argparse
import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time

APP = "Project Pyrrhus"
APP_ID = "{5C5D4C2E-8AE0-4446-BEC0-560BC45B6E20}"   # installer/kz2.iss AppId (never changes)
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + APP_ID + "_is1"
SETUP = "Project-Pyrrhus-setup.exe"
LAUNCHER = APP + ".exe"
# What the uninstaller may leave in %APPDATA%\Project Pyrrhus: the player's saves and settings (cellSaveData's
# gamedata, the .ini files). Caches (cache\, scratch\, vkd3d-proton.cache*) and logs are not user data.
USER_DATA = ("gamedata",)
USER_DATA_EXT = (".ini",)
STEPS = ("02-verify", "03-install", "04-layout", "05-checks", "06-build", "07-launch", "08-readonly",
         "09-uninstall", "10-leftovers")


class Step:
    def __init__(self, base, name):
        self.base, self.name = base, name
        self.out = os.path.join(base, "out")
        os.makedirs(self.out, exist_ok=True)
        self.f = open(os.path.join(self.out, name + ".txt"), "w", encoding="utf-8", newline="\r\n")
        self.state_path = os.path.join(self.out, "state.json")
        try:
            with open(self.state_path, encoding="utf-8") as f:
                self.state = json.load(f)
        except (OSError, ValueError):
            self.state = {}
        self.say(f"# {name} {datetime.datetime.now().isoformat(timespec='seconds')} base={base} "
                 f"python={sys.version.split()[0]}")

    def say(self, text=""):
        for line in str(text).splitlines() or [""]:
            print(line)
            self.f.write(line + "\n")
        self.f.flush()

    def save(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1)

    def end(self, verdict, why=""):
        self.say(f"RESULT {self.name} {verdict} {why}".rstrip())
        self.f.close()
        return 1 if verdict == "FAIL" else 0


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(st, argv, timeout, log_name=None, cwd=None, tail=40, env=None, stdin_text=None):
    """Run argv, keep its output in out\\<log_name> (and its last lines in the step file). -> (rc, seconds, text).
    env: the whole environment of the child; stdin_text: its standard input (the console's answers), else none."""
    st.say("$ " + subprocess.list2cmdline(argv) + (f"   (answers on stdin: {stdin_text!r})" if stdin_text else ""))
    t0 = time.time()
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, cwd=cwd, env=env,
                           input=stdin_text.encode("utf-8") if stdin_text is not None else None)
        rc, text = p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        rc, text = "timeout", (e.stdout or b"").decode("utf-8", "replace")
    except OSError as e:
        rc, text = f"oserror {e}", ""
    secs = round(time.time() - t0, 1)
    if log_name:
        with open(os.path.join(st.out, log_name), "w", encoding="utf-8") as f:
            f.write(text)
    lines = text.splitlines()
    for line in lines[-tail:]:
        st.say("  " + line[:300])
    st.say(f"rc={rc} after {secs} s" + (f" (full output: out\\{log_name})" if log_name else ""))
    return rc, secs, text


def reg_install_dir():
    """The install folder from the per-user uninstall key, or ""."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "InstallLocation")[0].rstrip("\\")
    except (ImportError, OSError):
        return ""


def default_install_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", APP)


def inst_dir(st):
    return reg_install_dir() or st.state.get("inst") or default_install_dir()


def data_dir():
    return os.path.join(os.environ.get("APPDATA", ""), APP)


def start_menu_dir():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", APP)


def game_paths(base):
    g = os.path.join(base, "game")
    return (os.path.join(g, "dump"), os.path.join(g, "update", "BCUS98116"), os.path.join(g, "eboot", "EBOOT.elf"))


def fingerprint(root):
    """(files, bytes, newest mtime) of a tree; read-only (names, sizes and times only)."""
    n = b = 0
    newest = 0.0
    for d, _, files in os.walk(root):
        for f in files:
            try:
                s = os.stat(os.path.join(d, f))
            except OSError:
                continue
            n, b, newest = n + 1, b + s.st_size, max(newest, s.st_mtime)
    return [n, b, int(newest)]


def listing(st, root, limit=60, depth=2):
    """Relative paths under root down to `depth` levels, with sizes of files; at most `limit` lines."""
    if not os.path.isdir(root):
        st.say(f"  (no folder {root})")
        return []
    seen = []
    for d, dirs, files in os.walk(root):
        rel = os.path.relpath(d, root)
        lvl = 0 if rel == "." else rel.count(os.sep) + 1
        if lvl >= depth:
            dirs[:] = []
        for x in sorted(dirs):
            seen.append(os.path.join(rel, x).lstrip(".\\/") + "\\")
        for x in sorted(files):
            p = os.path.join(d, x)
            try:
                size = os.path.getsize(p)
            except OSError:
                size = -1
            seen.append(f"{os.path.join(rel, x).lstrip('.' + os.sep)}  {size:,}")
    for line in seen[:limit]:
        st.say("  " + line)
    if len(seen) > limit:
        st.say(f"  ... {len(seen) - limit} more")
    return seen


def mem_facts():
    """(total, available) RAM in bytes via GlobalMemoryStatusEx, or (0, 0)."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullTotalPhys, m.ullAvailPhys
    except (ImportError, AttributeError, OSError):
        return 0, 0


def processes():
    """{pid: (parent pid, exe name)} via a Toolhelp32 snapshot (works on Windows and under Wine)."""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    out = {}
    e = PE()
    e.dwSize = ctypes.sizeof(PE)
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def descendants(root_pid, procs):
    kids, todo = [], [root_pid]
    while todo:
        p = todo.pop()
        for pid, (ppid, _) in procs.items():
            if ppid == p and pid not in kids and pid != root_pid:
                kids.append(pid)
                todo.append(pid)
    return kids


def window_titles(pids):
    """Visible top-level window titles of the given processes: [(pid, title)]."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32")
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(hwnd, buf, 512)
            if buf.value:
                found.append((pid.value, buf.value))
        return True
    u32.EnumWindows(proto(cb), 0)
    return found


def end_tree(st, pids):
    """End the given processes by id (children first)."""
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    for pid in reversed(pids):
        h = k32.OpenProcess(0x0001, False, pid)        # PROCESS_TERMINATE
        if h:
            k32.TerminateProcess(h, 1)
            k32.CloseHandle(h)
            st.say(f"  ended pid {pid}")


def tail_file(st, path, n=40, label=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as e:
        st.say(f"  (cannot read {path}: {e})")
        return []
    st.say(f"--- {label or path}: last {min(n, len(lines))} of {len(lines)} lines")
    for line in lines[-n:]:
        st.say("  " + line[:300])
    return lines


def newest(folder, pattern_ext=(".log", ".txt")):
    try:
        fs = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(pattern_ext)]
    except OSError:
        return []
    return sorted(fs, key=os.path.getmtime)


def py_of(inst):
    return os.path.join(inst, "toolchain", "python", "python.exe")


# ---------------------------------------------------------------------------------------------------- the steps
def s_verify(st, a):
    kit = os.path.join(a.base, "kit")
    sums = os.path.join(kit, "SHA256SUMS.txt")
    bad = []
    try:
        lines = [x.split(None, 1) for x in open(sums, encoding="utf-8").read().splitlines() if x.strip()]
    except OSError as e:
        return st.end("FAIL", f"no {sums}: {e}")
    for h, name in lines:
        p = os.path.join(kit, name.strip().lstrip("*").replace("/", os.sep))
        got = sha256(p) if os.path.isfile(p) else "missing"
        st.say(f"  {'ok ' if got == h else 'BAD'} {name.strip()}  {os.path.getsize(p) if os.path.isfile(p) else 0:,}")
        if got != h:
            bad.append(name.strip())
    total, avail = mem_facts()
    du = shutil.disk_usage(a.base)
    st.say(f"windows {platform.version()} {platform.machine()}; cores {os.cpu_count()}; RAM {total / 2**30:.1f} GiB "
           f"(available {avail / 2**30:.1f}); free on {os.path.splitdrive(a.base)[0] or a.base}: {du.free / 2**30:.1f} GiB")
    dump, update, eboot = game_paths(a.base)
    need = [os.path.join(dump, "PS3_GAME", "PARAM.SFO"), os.path.join(dump, "PS3_GAME", "USRDIR", "data_ps3.psarc"),
            os.path.join(update, "PARAM.SFO"), os.path.join(update, "USRDIR", "EBOOT.BIN"),
            os.path.join(update, "USRDIR", "added_data_ps3.psarc"), eboot]
    missing = [p for p in need if not os.path.isfile(p)]
    for p in need:
        st.say(f"  {'ok ' if p not in missing else 'MISSING'} {os.path.relpath(p, a.base)}"
               + (f"  {os.path.getsize(p):,}" if p not in missing else ""))
    pd = os.path.join(update, "USRDIR", "patch_data_ps3")
    st.say(f"  update patch_data_ps3: {len(os.listdir(pd)) if os.path.isdir(pd) else 'MISSING'} entries")
    st.state["dump_fp"] = fingerprint(dump)
    st.say(f"dump fingerprint (files, bytes, newest mtime): {st.state['dump_fp']}")
    st.save()
    if bad or missing:
        return st.end("FAIL", f"{len(bad)} kit file(s) differ, {len(missing)} game file(s) missing")
    if du.free < 6 * 2**30:
        return st.end("FAIL", f"only {du.free / 2**30:.1f} GiB free (install + build need about 6)")
    return st.end("PASS", f"{len(lines)} kit files ok, game files present")


def s_install(st, a):
    setup = os.path.join(a.base, "kit", SETUP)
    log = os.path.join(st.out, "03-inno-install.log")
    argv = [setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log}", "/MERGETASKS=!buildnow"]
    if a.dir:
        argv.append(f"/DIR={a.dir}")
    rc, secs, _ = run(st, argv, 1800)
    inst = reg_install_dir()
    st.say(f"uninstall key HKCU\\{UNINSTALL_KEY}: {'present, InstallLocation ' + inst if inst else 'MISSING'}")
    inst = inst or a.dir or default_install_dir()
    st.state.update(inst=inst, install_s=secs)
    st.save()
    have = {f: os.path.isfile(os.path.join(inst, f)) for f in (LAUNCHER, "unins000.exe", "manifest.json",
                                                                 "VERSION.txt", "kz2-install.ini")}
    for f, ok in have.items():
        st.say(f"  {'ok ' if ok else 'MISSING'} {f}")
    if rc != 0 or not all(have.values()) or not reg_install_dir():
        return st.end("FAIL", f"setup rc={rc}; see out\\03-inno-install.log")
    return st.end("PASS", f"installed in {secs} s to {inst}")


def s_layout(st, a):
    inst = inst_dir(st)
    rc, _, text = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "launch.py"), "--root", inst,
                           "--print", "--repair"], 600, "04-launch-print.json", tail=0)
    try:
        rep = json.loads(text)
    except ValueError:
        return st.end("FAIL", "launch.py --print gave no JSON")
    chk = rep.get("repair", {})
    st.say(f"manifest check: {chk.get('checked')} files, {len(chk.get('problems', []))} problem(s); "
           f"launcher decision: {rep.get('action')} ({rep.get('reason')})")
    for p in chk.get("problems", [])[:20]:
        st.say("  " + p)
    st.say("top-level layout:")
    listing(st, inst, limit=40, depth=1)
    try:
        st.say("VERSION.txt: " + open(os.path.join(inst, "VERSION.txt"), encoding="utf-8").read().strip())
        st.say("kz2-install.ini:\n" + open(os.path.join(inst, "kz2-install.ini"), encoding="utf-8").read().strip())
    except OSError as e:
        st.say(f"  {e}")
    sm = start_menu_dir()
    st.say("start menu:")
    links = listing(st, sm, limit=20, depth=1)
    desk = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", APP + ".lnk")
    st.say(f"desktop shortcut: {'present' if os.path.isfile(desk) else 'missing'}")
    if rc != 0 or not chk.get("checked") or chk.get("problems") or not links:
        return st.end("FAIL", "install differs from manifest.json or no Start menu entries")
    return st.end("PASS", f"{chk['checked']} files match manifest.json; {len(links)} Start menu entries")


def s_checks(st, a):
    inst = inst_dir(st)
    dump, update, eboot = game_paths(a.base)
    rc, _, _ = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "firstrun_check.py"),
                        "--dump", dump, "--update", update, "--eboot", eboot], 600, "05-firstrun-check.txt")
    return st.end("PASS" if rc == 0 else "FAIL", "no FAIL line" if rc == 0 else "a check failed (see above)")


def s_build(st, a):
    inst = inst_dir(st)
    dump, update, eboot = game_paths(a.base)
    total, avail = mem_facts()
    st.say(f"RAM {total / 2**30:.1f} GiB, available {avail / 2**30:.1f} GiB; jobs {a.jobs}")
    rc, secs, _ = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "firstrun.py"), "--root", inst,
                           "--dump", dump, "--update", update, "--eboot", eboot,
                           "--toolchain", os.path.join(inst, "toolchain", "llvm-mingw"), "--jobs", str(a.jobs),
                           "--log-dir", st.out, "--log-name", "06-firstrun.log",
                           "--status-file", os.path.join(st.out, "06-status.txt")], a.build_timeout,
                      "06-firstrun-stdout.txt", tail=25)
    st.state["build_s"] = secs
    st.save()
    exe = os.path.join(inst, "build", "kz2.exe")
    stamp = os.path.join(inst, "build", "build-stamp.json")
    st.say(f"kz2.exe: {os.path.getsize(exe):,} bytes" if os.path.isfile(exe) else "kz2.exe: MISSING")
    st.say(f"build-stamp.json: {'present' if os.path.isfile(stamp) else 'MISSING'}")
    tail_file(st, os.path.join(st.out, "06-firstrun.log"), 30, "out\\06-firstrun.log")
    _, _, text = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "launch.py"), "--root", inst,
                          "--print"], 300, "06-launch-print.json", tail=0)
    try:
        action = json.loads(text).get("action")
    except ValueError:
        action = None
    st.say(f"launcher decision after the build: {action}")
    try:
        st.say(f"build folder: {fingerprint(os.path.join(inst, 'build'))[1] / 2**30:.2f} GiB")
    except OSError:
        pass
    if rc != 0 or not os.path.isfile(exe) or not os.path.isfile(stamp) or action != "run":
        return st.end("FAIL", f"firstrun rc={rc} after {secs} s")
    return st.end("PASS", f"built in {secs / 60:.1f} min with {a.jobs} jobs")


def launch_once(st, inst, wait, tag):
    """Start the launcher, watch its process tree for `wait` seconds, end it. -> (saw kz2.exe, launcher rc)."""
    logs, glogs = os.path.join(inst, "logs"), os.path.join(inst, "build", "logs")
    before = set(newest(glogs))
    _, _, text = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "launch.py"), "--root", inst,
                          "--print"], 300, f"{tag}-launch-print.json", tail=0)
    try:
        rep = json.loads(text)
        st.say(f"decision {rep.get('action')}; cwd {rep.get('cwd')}; game variables: "
               + ", ".join(f"{k}={v}" for k, v in sorted(rep.get("env", {}).items())))
    except ValueError:
        st.say("launch.py --print gave no JSON")
    p = subprocess.Popen([os.path.join(inst, LAUNCHER)], cwd=inst)
    st.say(f"started {LAUNCHER} pid {p.pid}")
    saw, kz2_pids, t0, last = False, set(), time.time(), ""
    tree = []
    while time.time() - t0 < wait:
        time.sleep(1)
        procs = processes()
        tree = descendants(p.pid, procs)
        names = sorted({procs[x][1] for x in tree if x in procs})
        for x in tree:
            if procs.get(x, (0, ""))[1].lower() == "kz2.exe":
                saw = True
                kz2_pids.add(x)
        titles = window_titles(set(tree) | {p.pid})
        line = f"{names} windows {[t for _, t in titles]}"
        if line != last:
            st.say(f"  t={time.time() - t0:5.1f} s  processes {line}")
            last = line
        if p.poll() is not None:
            st.say(f"  launcher ended with code {p.returncode} (0x{p.returncode & 0xFFFFFFFF:08X}) at "
                   f"t={time.time() - t0:.1f} s")
            break
    procs = processes()
    tree = [x for x in descendants(p.pid, procs)]
    if p.poll() is None:
        end_tree(st, tree + [p.pid])
    else:
        end_tree(st, tree)
    try:
        p.wait(20)
    except subprocess.TimeoutExpired:
        pass
    for f in newest(logs)[-2:]:
        tail_file(st, f, 15, "install logs\\" + os.path.basename(f))
    new = [f for f in newest(glogs) if f not in before]
    if new:
        saw = True      # kz2.exe writes this log itself: it started even if it ended before a process sample
        lines = tail_file(st, new[-1], 40, "build\\logs\\" + os.path.basename(new[-1]))
        dev = [x for x in lines if "D3D12" in x or "device" in x.lower() or "WARP" in x or "[CRASH]" in x]
        for x in dev[:10]:
            st.say("  device line: " + x[:300])
    else:
        st.say(f"no new game log in {glogs}")
    st.say(f"data folder {data_dir()}:")
    listing(st, data_dir(), limit=30, depth=2)
    return saw, p.returncode


def s_launch(st, a):
    inst = inst_dir(st)
    saw, rc = launch_once(st, inst, a.wait, "07")
    if not saw:
        return st.end("FAIL", "the launcher did not start kz2.exe")
    return st.end("PASS", "kz2.exe started (a stop at D3D12 device creation without a GPU is expected)")


# 08: deny only "create files / write data" (WD) on the install folder itself. No (OI)/(CI): the ACE is not inherited,
# so existing files and every subfolder (logs\, build\, build\logs\) keep their rights and the launch runs.
READONLY_ACE = "(WD)"


def s_readonly(st, a):
    inst = inst_dir(st)
    user = os.environ.get("USERNAME", "")
    icacls = shutil.which("icacls")
    if not icacls or not user:
        return st.end("SKIP", "no icacls or USERNAME here")
    before = set(os.listdir(inst)) if os.path.isdir(inst) else set()
    rc, _, _ = run(st, [icacls, inst, "/deny", f"{user}:{READONLY_ACE}"], 300, tail=5)
    if rc != 0:
        return st.end("FAIL", "icacls could not deny file creation")
    try:
        for where, folder in (("install folder", inst), ("logs\\ below it", os.path.join(inst, "logs"))):
            probe = os.path.join(folder, "write-probe.txt")
            try:
                os.makedirs(folder, exist_ok=True)
                open(probe, "w").close()
                os.remove(probe)
                st.say(f"write probe, {where}: a new file can be created")
            except OSError as e:
                st.say(f"write probe, {where}: no new file ({e.__class__.__name__})")
        saw, rc2 = launch_once(st, inst, a.wait, "08")
    finally:
        run(st, [icacls, inst, "/remove:d", user], 300, tail=3)
    after = set(os.listdir(inst)) if os.path.isdir(inst) else set()
    new = sorted(after - before - {"write-probe.txt"})
    st.say(f"new entries in the install folder during the start: {new or 'none'}")
    if not saw:
        return st.end("FAIL", "the launcher did not start kz2.exe with the install folder closed to new files")
    return st.end("PASS", "kz2.exe started with the install folder closed to new files (facts above)")


def s_uninstall(st, a):
    inst = inst_dir(st)
    unins = os.path.join(inst, "unins000.exe")
    if not os.path.isfile(unins):
        return st.end("FAIL", f"no {unins}")
    run(st, [unins, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             "/LOG=" + os.path.join(st.out, "09-inno-uninstall.log")], 900)
    t0 = time.time()
    while reg_install_dir() and time.time() - t0 < 600:     # the uninstaller re-starts itself from %TEMP%
        time.sleep(2)
    while os.path.isfile(unins) and time.time() - t0 < 600:
        time.sleep(2)
    gone = not reg_install_dir()
    st.say(f"uninstall key: {'gone' if gone else 'STILL PRESENT'} after {time.time() - t0:.0f} s of waiting")
    return st.end("PASS" if gone else "FAIL", "uninstalled" if gone else "the uninstall key stayed")


def s_leftovers(st, a):
    inst = st.state.get("inst") or default_install_dir()
    problems = []
    st.say(f"install folder {inst}:")
    left = listing(st, inst, limit=40, depth=3)
    if left:
        problems.append(f"install folder not empty ({len(left)} entries)")
    if os.path.isdir(start_menu_dir()):
        problems.append("Start menu folder still there")
    if os.path.isfile(os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", APP + ".lnk")):
        problems.append("desktop shortcut still there")
    if reg_install_dir():
        problems.append("uninstall key still there")
    st.say(f"data folder {data_dir()} (user data may stay; caches and logs should not):")
    listing(st, data_dir(), limit=40, depth=2)
    if os.path.isdir(data_dir()):
        for x in os.listdir(data_dir()):
            p = os.path.join(data_dir(), x)
            if x in USER_DATA or (os.path.isfile(p) and x.lower().endswith(USER_DATA_EXT)):
                continue
            problems.append(f"not user data left in the data folder: {x}")
    dump = game_paths(a.base)[0]
    fp = fingerprint(dump)
    st.say(f"dump fingerprint now {fp}, at 02-verify {st.state.get('dump_fp')}")
    if st.state.get("dump_fp") and fp != st.state["dump_fp"]:
        problems.append("the dump changed")
    for p in problems:
        st.say("  PROBLEM " + p)
    return st.end("FAIL" if problems else "PASS", "; ".join(problems) or "only user data left (or nothing)")


# ------------------------------------------------------------------- first contact: what players touch first
# v0.1.2's first-contact changes on the guest's Windows: the setup's silent refusals, the first-run
# check's per-input reasons on wrong inputs, the bundled Python, the console's questions, the launcher's dialog and the
# uninstaller's coverage. The wrong inputs need no game data: empty folders, a drive root, the update given as the
# disc, a stand-in of the disc's 1.01 EBOOT (an ELF header and zeros of its size), synthetic PARAM.SFO files and a
# synthetic ISO. They are made in <base>\t\ by the steps; the game files under game\ are only read.
EBOOT_101_SIZE = 16_381_928          # firstrun_check.EBOOT_ELF_SIZES: the disc's decrypted 1.01 EBOOT
ONEDRIVE_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")    # firstrun_check / kz2.iss InOneDrive
SETUP_LOG = "Project-Pyrrhus-setup.log"                                    # kz2.iss LogName: next to setup.exe
FIRSTRUN_STATUS = os.path.join("logs", "firstrun-status.txt")             # launch.FIRSTRUN_STATUS
FIRSTRUN_LOG = "Project-Pyrrhus-firstrun.log"                             # launch.FIRSTRUN_LOG
SYNTH_SFO = {"APP_VER": "01.01", "CATEGORY": "DG", "TITLE": "Synthetic test disc", "TITLE_ID": "BCUS98116",
             "VERSION": "01.01"}


class Expect:
    """Collects the checks of a step: each prints 'ok' or 'NOT' with what was expected."""

    def __init__(self, st):
        self.st, self.problems = st, []

    def __call__(self, cond, what):
        self.st.say(("  ok   " if cond else "  NOT  ") + what)
        if not cond:
            self.problems.append(what)
        return bool(cond)

    def end(self, why_pass, verdict="PASS"):
        if self.problems:
            return self.st.end("FAIL", "; ".join(self.problems)[:400])
        return self.st.end(verdict, why_pass)


def tdir(a, *parts):
    p = os.path.join(a.base, "t", *parts)
    os.makedirs(p, exist_ok=True)
    return p


def write_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def write_sfo(path, fields):
    """A minimal PARAM.SFO (0x204 utf-8 strings), the inverse of firstrun_check.read_sfo (as test_firstrun_check)."""
    import struct
    keys = b"".join(k.encode() + b"\0" for k in fields)
    data, idx, doff, koff = b"", b"", 0, 0
    for k, v in fields.items():
        raw = v.encode() + b"\0"
        padded = raw + b"\0" * ((4 - len(raw) % 4) % 4)
        idx += struct.pack("<HHIII", koff, 0x204, len(raw), len(padded), doff)
        koff += len(k) + 1
        data += padded
        doff += len(padded)
    kt = 20 + len(idx)
    dt = kt + len(keys)
    dt += (4 - dt % 4) % 4
    blob = struct.pack("<4sIIII", b"\0PSF", 0x101, kt, dt, len(fields)) + idx + keys
    return write_file(path, blob + b"\0" * (dt - len(blob)) + data)


def standin_101(a):
    """<base>\\t\\eboot101\\EBOOT.elf: a 64-bit big-endian PPC64 ELF header and zeros, the size of the disc's 1.01
    EBOOT (no game data; the setup and the check tell EBOOT versions apart by size first)."""
    p = os.path.join(tdir(a, "eboot101"), "EBOOT.elf")
    if not (os.path.isfile(p) and os.path.getsize(p) == EBOOT_101_SIZE):
        h = bytearray(64)
        h[:7] = b"\x7fELF\x02\x02\x01"
        h[18:20] = (0x15).to_bytes(2, "big")          # EM_PPC64
        with open(p, "wb") as f:
            f.write(bytes(h))
            f.truncate(EBOOT_101_SIZE)
    return p


def synth_dump(a, name, **fields):
    """A dump folder with a synthetic PARAM.SFO (SYNTH_SFO + fields), an EBOOT.BIN and a data_ps3.psarc of a few
    bytes with the right magics; checked with --min-psarc-bytes 4096 so only the PARAM.SFO lines differ."""
    d = tdir(a, name)
    write_sfo(os.path.join(d, "PS3_GAME", "PARAM.SFO"), dict(SYNTH_SFO, **fields))
    write_file(os.path.join(d, "PS3_GAME", "USRDIR", "EBOOT.BIN"), b"SCE\0" + b"\0" * 60)
    write_file(os.path.join(d, "PS3_GAME", "USRDIR", "data_ps3.psarc"), b"PSAR" + b"\0" * 6000)
    return d


def empty_dir(a, name="empty"):
    d = tdir(a, name)
    for x in os.listdir(d):
        p = os.path.join(d, x)
        if os.path.isfile(p):
            os.remove(p)
    return d


def onedrive_env(a):
    """-> (environment for the child, OneDrive folder, real): the machine's OneDrive variable, else a stand-in
    OneDrive=<base>\\t\\OneDrive given to the child only (the rule reads the variables, as kz2.iss and the check do)."""
    for v in ONEDRIVE_VARS:
        val = os.environ.get(v, "").strip().strip('"')
        if val:
            return dict(os.environ), val, True
    fake = tdir(a, "OneDrive")
    return dict(os.environ, OneDrive=fake), fake, False


def fc_path(inst):
    return os.path.join(inst, "kz2-setup", "release", "firstrun_check.py")


def fr_path(inst):
    return os.path.join(inst, "kz2-setup", "release", "firstrun.py")


def need_install(st):
    inst = inst_dir(st)
    return inst if os.path.isfile(fc_path(inst)) and os.path.isfile(py_of(inst)) else ""


def fcheck(st, tag, dump, update, eboot, extra=(), env=None, cwd=None):
    """The installed firstrun_check.py on the installed Python (as firstrun.py starts it: by full path), A1 left out
    (the archive hash, minutes). -> (rc, text); the text is what the console shows."""
    inst = inst_dir(st)
    argv = [py_of(inst), fc_path(inst), "--dump", dump] + (["--update", update] if update else []) + \
        (["--eboot", eboot] if eboot else []) + ["--skip-archive-hash"] + list(extra)
    rc, _, text = run(st, argv, 900, tag + ".txt", cwd=cwd, env=env, tail=60)
    return rc, text


def reasons_of(text):
    """The per-input reason lines (indented after 'first-run checks: FAIL'), as the setup, launcher and console show."""
    lines = text.splitlines()
    try:
        i = next(n for n, x in enumerate(lines) if x.startswith("first-run checks: FAIL"))
    except StopIteration:
        return []
    return [x.strip() for x in lines[i + 1:] if x.startswith("  ")]


def has_reason(text, start, *parts):
    return any(r.startswith(start) and all(p in r for p in parts) for r in reasons_of(text))


def read_text(path, offset=0):
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


class KeepIni:
    """kz2-install.ini as it was before a step that lets firstrun.py record [paths] (wrong=...): put back after."""

    def __init__(self, inst):
        self.path = os.path.join(inst, "kz2-install.ini")
        self.data = read_text(self.path) if os.path.isfile(self.path) else None

    def paths(self):
        import configparser
        cp = configparser.ConfigParser()
        cp.read(self.path, encoding="utf-8")
        return {k: cp.get("paths", k, fallback="") for k in ("dump", "update", "eboot", "wrong")}

    def restore(self, st):
        if self.data is not None:
            with open(self.path, "w", encoding="utf-8", newline="") as f:
                f.write(self.data)
            st.say("kz2-install.ini put back as it was before this step")


def setup_run(st, tag, extra, env=None):
    """The kit's setup, silent, with its own /LOG. -> (rc, Inno log text)."""
    setup = os.path.join(st.base, "kit", SETUP)
    log = os.path.join(st.out, tag + "-inno.log")
    rc, _, _ = run(st, [setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log}",
                        "/MERGETASKS=!buildnow"] + extra, 900, env=env)
    return rc, read_text(log)


def s_setup_onedrive(st, a):
    if reg_install_dir():
        return st.end("SKIP", "an install is present: run this step before 03-install")
    env, od, real = onedrive_env(a)
    st.say(f"OneDrive folder: {od} ({'this machine' if real else 'stand-in: no OneDrive variable here, OneDrive=' + od + ' given to the setup only'})")
    target = os.path.join(od, APP + " vm-test")
    rc, log = setup_run(st, "11", [f"/DIR={target}"], env)
    why = [x.split("install folder refused: ", 1)[1] for x in log.splitlines() if "install folder refused: " in x]
    st.say("The text the player would see (the folder page's box says the same; silent: the setup's log):")
    st.say("  " + (why[0] if why else "(no 'install folder refused' line in the setup log)"))
    ex = Expect(st)
    ex(rc == 7, f"setup ended with exit code 7 (refused before installing), got {rc}")
    ex(why and "inside OneDrive" in why[0], "the reason names OneDrive")
    ex(not reg_install_dir(), "no uninstall key")
    ex(not (os.path.isdir(target) and os.listdir(target)), f"nothing written to {target}")
    if real or ex.problems:
        return ex.end("the setup refused an install folder inside OneDrive")
    return ex.end("no OneDrive on this machine; the setup refused a folder under a stand-in OneDrive variable", "SKIP")


def s_setup_eboot(st, a):
    if reg_install_dir():
        return st.end("SKIP", "an install is present: run this step before 03-install")
    e = standin_101(a)
    slog = os.path.join(a.base, "kit", SETUP_LOG)
    off = os.path.getsize(slog) if os.path.isfile(slog) else 0
    st.say(f"stand-in of the disc's 1.01 EBOOT: {e} ({os.path.getsize(e):,} bytes: an ELF header and zeros)")
    rc, _ = setup_run(st, "12", [f"/EBOOT={e}"])
    said = read_text(slog, off).strip()
    st.say(f"The text the player would see (the EBOOT page's box says the same; silent: {SETUP_LOG} next to the setup):")
    st.say("  " + (said or "(nothing new in it)"))
    ex = Expect(st)
    ex(rc == 7, f"setup ended with exit code 7 (refused before installing), got {rc}")
    ex("Silent install stopped:" in said and "disc's 1.01 EBOOT" in said, "the reason says it is the disc's 1.01 EBOOT")
    ex("USRDIR" in said, "the reason names the update's USRDIR")
    ex(not reg_install_dir(), "no uninstall key")
    ex(not os.path.isfile(os.path.join(default_install_dir(), LAUNCHER)), "nothing installed")
    return ex.end("the silent setup refused the 1.01 EBOOT before installing")


def s_bundled_python(st, a):
    inst = need_install(st)
    if not inst:
        return st.end("FAIL", "not installed (run 03-install first)")
    py = py_of(inst)
    pth = [f for f in os.listdir(os.path.dirname(py)) if f.lower().endswith("._pth")]
    st.say(f"bundled Python {py}; ._pth files: {pth or 'none'}")
    for f in pth[:1]:
        st.say("  " + " | ".join(read_text(os.path.join(os.path.dirname(py), f)).splitlines()[:8]))
    probe = tdir(a, "pathprobe")
    write_file(os.path.join(probe, "sibling.py"), b"NAME = 'sibling'\n")
    write_file(os.path.join(probe, "probe.py"), b"import sibling\nprint('imported', sibling.NAME)\n")
    root = os.path.splitdrive(os.path.abspath(a.base))[0] + os.sep
    st.say("Control: a script that imports a module beside it, started by full path from " + root)
    _, _, text = run(st, [py, os.path.join(probe, "probe.py")], 120, "13-probe.txt", cwd=root, tail=6)
    keeps_off = "ModuleNotFoundError" in text
    st.say("  this Python " + ("keeps the script's folder off sys.path (the case the fix is for)" if keeps_off
                               else "puts the script's folder on sys.path itself"))
    notiso = write_file(os.path.join(tdir(a, "iso"), "not-an-image.iso"), b"not a disc image\n" * 4096)
    st.say("firstrun_check.py by full path with an .iso as the disc (it imports iso9660 from its own folder):")
    rc, text = fcheck(st, "13-firstrun-check", notiso, "", "", cwd=root)
    ex = Expect(st)
    ex("ModuleNotFoundError" not in text and "Traceback" not in text, "no ModuleNotFoundError, no traceback")
    ex("dump: decrypted ISO not-an-image.iso" in text, "the ISO reader ran (INFO D0 names the image)")
    ex("FAIL I2" in text, "the image is refused as unreadable (I2), not as encrypted")
    if not keeps_off and not ex.problems:
        return ex.end("the check ran, but this Python adds the script's folder itself: the fix is not exercised", "SKIP")
    return ex.end("firstrun_check imports its own modules under the bundled Python")


def s_onedrive_check(st, a):
    if not need_install(st):
        return st.end("FAIL", "not installed (run 03-install first)")
    env, od, real = onedrive_env(a)
    dump, update, eboot = game_paths(a.base)
    root = os.path.join(od, APP)
    st.say(f"install folder given to the check: {root} ({'this machine' if real else 'stand-in OneDrive variable'})")
    rc, text = fcheck(st, "14-firstrun-check", dump, update, eboot, ["--root", root, "--build", os.path.join(root, "build")],
                      env=env)
    ex = Expect(st)
    ex(rc == 1 and "FAIL O1" in text, "FAIL O1 (install folder inside OneDrive)")
    ex(any("inside OneDrive" in r for r in reasons_of(text)), "the stop reason names OneDrive")
    ex(any(r.startswith("Passed:") for r in reasons_of(text)), "the game files are named as passed")
    if real or ex.problems:
        return ex.end("the first-run check refuses an install inside OneDrive")
    return ex.end("no OneDrive on this machine; a folder under a stand-in OneDrive variable was refused", "SKIP")


def s_empty_folder(st, a):
    if not need_install(st):
        return st.end("FAIL", "not installed (run 03-install first)")
    dump, update, eboot = game_paths(a.base)
    empty = empty_dir(a)
    ex = Expect(st)
    st.say("Disc dump = an empty folder:")
    rc, text = fcheck(st, "15-disc-empty", empty, update, eboot)
    ex(rc == 1 and has_reason(text, "Disc dump failed: " + empty, "(the folder is empty)"),
       "'Disc dump failed: <path> ... (the folder is empty)'")
    ex(has_reason(text, "Passed:", "1.29 update", "EBOOT"), "'Passed: ...' names the update and the EBOOT")
    st.say("1.29 update = an empty folder:")
    rc, text = fcheck(st, "15-update-empty", dump, empty, eboot)
    ex(rc == 1 and has_reason(text, "1.29 update failed: " + empty, "(the folder is empty)"),
       "'1.29 update failed: <path> ... (the folder is empty)'")
    ex(has_reason(text, "Passed:", "disc dump", "EBOOT"), "'Passed: ...' names the disc dump and the EBOOT")
    return ex.end("each empty input is named with its path and what it must hold")


def drive_roots(a):
    roots = [os.environ.get("SystemDrive", "C:").rstrip("\\") + "\\"] if os.name == "nt" else []
    d = os.path.splitdrive(os.path.abspath(a.base))[0]
    r = d + "\\" if d else os.sep
    return roots + [r] if r.lower() not in [x.lower() for x in roots] else roots


def s_drive_root(st, a):
    if not need_install(st):
        return st.end("FAIL", "not installed (run 03-install first)")
    dump, update, eboot = game_paths(a.base)
    ex = Expect(st)
    for i, root in enumerate(drive_roots(a)):
        st.say(f"Disc dump = the drive root {root}:")
        rc, text = fcheck(st, f"16-disc-root{i}", root, update, eboot)
        ex(rc == 1 and has_reason(text, f"Disc dump failed: {root} "), f"'Disc dump failed: {root} ...'")
        ex(has_reason(text, "Passed:", "1.29 update", "EBOOT"), "the update and the EBOOT passed")
        st.say(f"1.29 update = the drive root {root}:")
        rc, text = fcheck(st, f"16-update-root{i}", dump, root, eboot)
        ex(rc == 1 and has_reason(text, f"1.29 update failed: {root} "), f"'1.29 update failed: {root} ...'")
        ex(has_reason(text, "Passed:", "disc dump", "EBOOT"), "the disc dump and the EBOOT passed")
    return ex.end("a drive root given as the disc or the update is named as such")


def s_swapped(st, a):
    if not need_install(st):
        return st.end("FAIL", "not installed (run 03-install first)")
    dump, update, eboot = game_paths(a.base)
    ex = Expect(st)
    st.say("The update folder given as the disc, the disc dump as the update:")
    rc, text = fcheck(st, "17-swapped", update, dump, eboot)
    ex(rc == 1 and has_reason(text, "Disc dump failed:", "looks like the 1.29 update"),
       "the disc input 'looks like the 1.29 update'")
    ex(has_reason(text, "1.29 update failed:", "looks like the disc dump, not the update"),
       "the update input 'looks like the disc dump, not the update'")
    st.say("The disc's PS3_GAME folder given as the update:")
    rc, text = fcheck(st, "17-ps3game-as-update", dump, os.path.join(dump, "PS3_GAME"), eboot)
    ex(rc == 1 and has_reason(text, "1.29 update failed:", "looks like the disc's PS3_GAME folder"),
       "the update input 'looks like the disc's PS3_GAME folder'")
    st.say("Picks one level too deep (PS3_GAME as the disc, the update's USRDIR as the update) are taken up a level:")
    rc, text = fcheck(st, "17-picks", os.path.join(dump, "PS3_GAME"), os.path.join(update, "USRDIR"), eboot)
    ex(rc == 0 and "using the folder that holds PS3_GAME" in text and "using the update folder" in text,
       "both picks resolved (INFO D0, U0) and the check passes")
    return ex.end("swapped and too-deep picks are named or resolved")


def s_disc_id(st, a):
    if not need_install(st):
        return st.end("FAIL", "not installed (run 03-install first)")
    dump, update, eboot = game_paths(a.base)
    small = ["--min-psarc-bytes", "4096"]
    ex = Expect(st)
    st.say("This machine's disc dump:")
    rc, text = fcheck(st, "18-real", dump, update, eboot)
    ex(rc == 0 and "D1: disc dump: TITLE_ID BCUS98116" in text, "OK D1 names BCUS98116")
    st.say("A synthetic PARAM.SFO of another game (TITLE_ID NPUB30001):")
    rc, text = fcheck(st, "18-other-id", synth_dump(a, "disc-other", TITLE_ID="NPUB30001", TITLE="Synthetic other game"),
                      update, eboot, small)
    ex(rc == 1 and "FAIL D1: disc dump: this is NPUB30001 (Synthetic other game), not Killzone 2" in text,
       "FAIL D1 names the id and the title found")
    st.say("A synthetic PARAM.SFO of the Trilogy disc (BCUS98116, disc VERSION 02.00):")
    rc, text = fcheck(st, "18-trilogy", synth_dump(a, "disc-trilogy", VERSION="02.00"), update, eboot, small)
    ex(rc == 0 and "WARN D1" in text and "Killzone Trilogy disc" in text and "Untested" in text,
       "WARN D1 names the Trilogy disc as untested, and the check passes")
    return ex.end("the disc's title id is named; another id fails; the Trilogy note shows")


def s_iso(st, a):
    if not need_install(st):
        return st.end("FAIL", "not installed (run 03-install first)")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # the kit's iso_fixture.py (a test helper)
    try:
        from iso_fixture import build_iso
    except ImportError:
        return st.end("SKIP", "iso_fixture.py is not beside vm_test.py in the kit")
    _, update, eboot = game_paths(a.base)
    d = tdir(a, "iso")
    sfo = write_sfo(os.path.join(d, "PARAM.SFO"), SYNTH_SFO)
    with open(sfo, "rb") as f:
        sfo_bytes = f.read()
    files = {"PS3_DISC.SFB": b".SFB" + b"\0" * 8, "PS3_GAME/PARAM.SFO": sfo_bytes,
             "PS3_GAME/USRDIR/EBOOT.BIN": b"SCE\0" + b"\0" * 60,
             "PS3_GAME/USRDIR/data_ps3.psarc": b"PSAR" + b"\0" * 6000}
    small = ["--min-psarc-bytes", "4096"]
    ex = Expect(st)
    st.say("A synthetic decrypted ISO (iso_fixture.py; PARAM.SFO, EBOOT.BIN and a small archive):")
    good = build_iso(os.path.join(d, "synthetic.iso"), files, multi={"PS3_GAME/USRDIR/data_ps3.psarc": 2048})
    rc, text = fcheck(st, "19-decrypted", good, update, eboot, small)
    ex(rc == 0 and "dump: decrypted ISO synthetic.iso" in text and "inside the ISO" in text and "OK   D3" in text,
       "read from inside the image (D1-D3 OK) and the check passes")
    st.say("The same image with an unreadable (scrambled) archive, as an encrypted ISO reads:")
    bad = build_iso(os.path.join(d, "scrambled.iso"),
                    dict(files, **{"PS3_GAME/USRDIR/data_ps3.psarc": bytes(range(200)) * 30}))
    rc, text = fcheck(st, "19-encrypted", bad, update, eboot, small)
    ex(rc == 1 and "FAIL I1: this ISO is encrypted; use a decrypted dump" in text, "FAIL I1 'this ISO is encrypted'")
    ex(has_reason(text, "Disc dump failed:"), "the stop reason is labelled 'Disc dump failed:'")
    return ex.end("a decrypted ISO is read as the disc; an encrypted one is refused")


def console_run(st, tag, args, answers):
    """The installed firstrun.py's console (the zip's run.cmd and the launcher's console window) with the answers on
    stdin, a scratch build folder and a stop file already present (it never builds here). -> (rc, text, status)."""
    inst = inst_dir(st)
    a_build = os.path.join(st.base, "t", "build-" + tag)
    stop = write_file(os.path.join(st.base, "t", "stop-" + tag), b"stop\n")
    status = os.path.join(st.out, tag + "-status.txt")
    argv = [py_of(inst), fr_path(inst), "--root", inst, "--build", a_build, "--interactive"] + args + \
        ["--log-dir", st.out, "--log-name", tag + "-firstrun.log", "--status-file", status, "--stop-file", stop]
    rc, _, text = run(st, argv, 900, tag + "-console.txt", tail=80, stdin_text=answers)
    return rc, text, read_text(status)


def s_eboot_101(st, a):
    inst = need_install(st)
    if not inst:
        return st.end("FAIL", "not installed (run 03-install first)")
    dump, update, eboot = game_paths(a.base)
    e = standin_101(a)
    ex = Expect(st)
    st.say(f"The check with a stand-in of the disc's 1.01 EBOOT ({e}):")
    rc, text = fcheck(st, "20-check", dump, update, e)
    ex(rc == 1 and "FAIL E1: this EBOOT is the disc's 1.01 one" in text, "FAIL E1 'this EBOOT is the disc's 1.01 one'")
    ex(has_reason(text, "EBOOT failed:", "USRDIR"), "the stop reason is labelled 'EBOOT failed:' and names USRDIR")
    ex(has_reason(text, "Passed:", "disc dump", "1.29 update"), "the disc dump and the update passed")
    ini = KeepIni(inst)
    try:
        st.say("The console: the same EBOOT, then its folder as the answer (folder answer), then q:")
        rc, text, status = console_run(st, "20", ["--check-first", "--dump", dump, "--update", update, "--eboot", e],
                                       f"{os.path.dirname(e)}\nq\n")
        ex("The EBOOT must be the 1.29 update's one, not the disc's" in text, "the console asks for the EBOOT alone")
        ex(f"using {e}" in text, "a folder answer is taken as the EBOOT.elf in it ('using ...')")
        ex(text.count("FAIL E1") >= 2, "checked again, refused again")
        ex("Disc dump: the folder holding PS3_GAME" not in text, "the disc dump was not asked")
        ex("Nothing was built. The next start checks your game files again." in text, "q ends the console's start")
        ex("RESULT ok=0 step=quit" in status and "REASON EBOOT failed:" in status,
           "the status file (the launcher's dialog) has RESULT ok=0 step=quit and 'REASON EBOOT failed:'")
        ex(ini.paths().get("wrong") == "eboot", "kz2-install.ini [paths] wrong = eboot (the next start asks for it)")
    finally:
        ini.restore(st)
    return ex.end("the 1.01 EBOOT is refused in the check and the console, with a folder answer taken")


def s_ask_again(st, a):
    inst = need_install(st)
    if not inst:
        return st.end("FAIL", "not installed (run 03-install first)")
    dump, update, eboot = game_paths(a.base)
    empty = empty_dir(a)
    ex = Expect(st)
    ini = KeepIni(inst)
    try:
        st.say("Start 1: the setup's folders (--check-first) with an empty folder as the disc; the player quits (q):")
        rc, text, status = console_run(st, "21a", ["--check-first", "--dump", empty, "--update", update, "--eboot", eboot],
                                       "q\n")
        ex("Nothing was built. The next start checks your game files again." in text, "q ends the console's start")
        ex("RESULT ok=0 step=quit" in status and "REASON Disc dump failed:" in status and "REASON Passed:" in status,
           "the status file has 'REASON Disc dump failed:' and 'REASON Passed: ...'")
        p = ini.paths()
        ex(p.get("wrong") == "dump" and p.get("dump") == empty, "kz2-install.ini [paths] wrong = dump, with the answers")
        _, _, j = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "launch.py"), "--root", inst,
                           "--print"], 300, "21-launch-print.json", tail=0)
        try:
            cmd = json.loads(j).get("build") or []
        except ValueError:
            cmd = []
        st.say("the launcher's next build command: " + " ".join(cmd[1:])[:400])
        ex("--check-first" in cmd and empty in cmd, "the launcher would check those answers first")
        st.say("Start 2: no folders given (as the zip's run.cmd); c = change, the empty folder again, then q:")
        rc, text, status = console_run(st, "21b", [], f"c\n{empty}\nq\n")
        asked = [q for q in ("Disc dump: the folder holding PS3_GAME", "1.29 update folder (", "Decrypted EBOOT:")
                 if q in text]
        st.say(f"questions asked after c: {asked}")
        ex(text.count("first-run checks: FAIL") >= 2, "the recorded answers were checked first, then again")
        ex(asked == ["Disc dump: the folder holding PS3_GAME"], "only the disc dump was asked again")
        ex("Nothing was built." in text and "RESULT ok=0 step=quit" in status, "q ends the start")
    finally:
        ini.restore(st)
    return ex.end("the next start checks the last answers first and asks only for the wrong input")


def dialogs(pids):
    """Visible dialog boxes (window class #32770: MessageBox) of the given processes: [(hwnd, text, {button: id})]."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32")
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u32.GetDlgCtrlID.argtypes = [wintypes.HWND]
    u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u32.EnumChildWindows.argtypes = [wintypes.HWND, proto, wintypes.LPARAM]
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u32.IsWindowVisible.argtypes = [wintypes.HWND]

    def cls(h):
        b = ctypes.create_unicode_buffer(80)
        u32.GetClassNameW(h, b, 80)
        return b.value

    def text(h):
        n = u32.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 2)
        u32.GetWindowTextW(h, b, n + 2)
        return b.value
    found = []

    def top(h, _):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u32.IsWindowVisible(h) and cls(h) == "#32770":
            parts, buttons = [], {}

            def child(c, _):
                k, t = cls(c).lower(), text(c)
                if k == "button":
                    buttons[t.replace("&", "")] = u32.GetDlgCtrlID(c)
                elif t:
                    parts.append(t)
                return True
            u32.EnumChildWindows(h, proto(child), 0)
            found.append((h, "\n".join(parts), buttons))
        return True
    u32.EnumWindows(proto(top), 0)
    return found


def press(hwnd, button_id):
    import ctypes
    from ctypes import wintypes
    post = ctypes.WinDLL("user32").PostMessageW
    post.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    post(hwnd, 0x0111, button_id, 0)      # WM_COMMAND with the button's id: as a click on it


BUILD_QUESTIONS = ("Continue the build now?", "Build it now?", "Build again now?")


def failure_dialog(seen):
    """The last dialog text that is not a build question (the first one also says "did not finish": "The last build
    did not finish. Continue the build now?"; pre-flight 2026-10-28), else ""."""
    rest = [b for b in seen if not any(q in b for q in BUILD_QUESTIONS)]
    return rest[-1] if rest else ""


def s_launcher_dialog(st, a):
    inst = need_install(st)
    if not inst:
        return st.end("FAIL", "not installed (run 03-install first)")
    build = os.path.join(inst, "build")
    pj = os.path.join(build, "paths.json")
    if os.path.isfile(pj) or os.path.isfile(os.path.join(build, "kz2.exe")):
        return st.end("SKIP", "a build is present: run this step before 06-build")
    _, update, eboot = game_paths(a.base)
    empty = empty_dir(a)
    os.makedirs(build, exist_ok=True)
    with open(pj, "w", encoding="utf-8") as f:
        json.dump({"dump": empty, "update": update, "eboot": eboot}, f)
    st.say(f"build\\paths.json names an empty folder as the disc ({empty}): the launcher offers to continue a build "
           "that did not finish, its console's check stops, and its dialog says why")
    ini = KeepIni(inst)
    ex = Expect(st)
    seen = []
    try:
        p = subprocess.Popen([os.path.join(inst, LAUNCHER)], cwd=inst)
        st.say(f"started {LAUNCHER} pid {p.pid}")
        answered, t0, deadline = set(), time.time(), max(a.wait, 60) * 4
        while time.time() - t0 < deadline and p.poll() is None:
            time.sleep(1)
            procs = processes()
            tree = set(descendants(p.pid, procs)) | {p.pid}
            for h, body, buttons in dialogs(tree):
                if h in answered:
                    continue
                time.sleep(0.5)
                again = [x for x in dialogs(tree) if x[0] == h]
                body, buttons = (again[0][1], again[0][2]) if again else (body, buttons)
                if any(q in body for q in BUILD_QUESTIONS):
                    pick = ("Yes", buttons.get("Yes", 6))
                elif "Yes" in buttons:
                    pick = ("No", buttons.get("No", 7))
                else:
                    pick = ("OK", buttons.get("OK", 1))
                st.say(f"--- dialog at t={time.time() - t0:.0f} s (buttons {sorted(buttons)}; pressing {pick[0]}):")
                for line in body.splitlines():
                    st.say("  | " + line)
                seen.append(body)
                answered.add(h)
                press(h, pick[1])
        if p.poll() is None:
            st.say("the launcher was still running at the deadline")
            end_tree(st, descendants(p.pid, processes()) + [p.pid])
        else:
            st.say(f"launcher ended with code {p.returncode}")
        tail_file(st, os.path.join(inst, FIRSTRUN_STATUS), 20, "logs\\firstrun-status.txt")
        tail_file(st, os.path.join(inst, "logs", "launcher.log"), 6, "logs\\launcher.log")
        if seen:
            ex(any("Continue the build now?" in b for b in seen), "the launcher asked 'Continue the build now?'")
            last = failure_dialog(seen)
            ex("Disc dump failed:" in last and empty in last, "its dialog names the disc dump, its path and why")
            ex("asks again only for the ones that are wrong" in last, "and says the next start asks only for those")
            ex("The log is" in last, "and where the log is")
    finally:
        if os.path.isfile(pj):
            os.remove(pj)
        ini.restore(st)
    if not seen:
        return st.end("SKIP", "no dialog was seen: run this step from the desktop session, not over ssh")
    return ex.end("the launcher's dialog shows the first run's stop reasons")


def s_uninstall_cover(st, a):
    inst = need_install(st)
    if not inst:
        return st.end("FAIL", "not installed (run 03-install first)")
    st.say("What the first run and the launcher wrote into the install folder (the uninstaller must remove it):")
    for rel in ("logs", FIRSTRUN_LOG, "kz2-install.ini", "build", "vfs", "cache", "game"):
        p = os.path.join(inst, rel)
        st.say(f"  {rel}: " + (f"folder, {fingerprint(p)[0]} files" if os.path.isdir(p) else
                               "file" if os.path.isfile(p) else "not there"))
    for x in sorted(os.listdir(inst)):
        if x.lower().startswith("project-pyrrhus-firstrun-"):
            st.say(f"  {x}: rotated first-run log")
    planted = [write_sfo(os.path.join(inst, "game", "disc", "PS3_GAME", "PARAM.SFO"), SYNTH_SFO),
               write_file(os.path.join(inst, "Project-Pyrrhus-firstrun-20261028-120000.log"), b"stand-in rotation\n"),
               write_file(os.path.join(inst, FIRSTRUN_STATUS), b"RESULT ok=0 step=quit elapsed=0\n")
               if not os.path.isfile(os.path.join(inst, FIRSTRUN_STATUS)) else os.path.join(inst, FIRSTRUN_STATUS)]
    st.say("Planted as the first run leaves them (the ISO copy game\\disc, a rotated log, the status file):")
    for p in planted:
        st.say("  " + os.path.relpath(p, inst))
    st.state["planted"] = [os.path.relpath(p, inst) for p in planted]
    st.save()
    return st.end("PASS", "first-run files in place; 09-uninstall then 10-leftovers show whether they go")


NEW_STEPS = ("11-setup-onedrive", "12-setup-eboot101", "13-bundled-python", "14-onedrive-check", "15-empty-folder",
             "16-drive-root", "17-swapped", "18-disc-id", "19-iso", "20-eboot-101", "21-ask-again",
             "22-launcher-dialog", "23-uninstall-cover")
NEW_FUNCS = (s_setup_onedrive, s_setup_eboot, s_bundled_python, s_onedrive_check, s_empty_folder, s_drive_root,
             s_swapped, s_disc_id, s_iso, s_eboot_101, s_ask_again, s_launcher_dialog, s_uninstall_cover)
# The order on the VM (COMMANDS.md, vm_kit.sh preflight): the setup's refusals before anything is installed; the
# check, console and launcher steps on the fresh install before the build (22 needs no build yet); 23 just before
# the uninstall, so 10-leftovers shows whether the uninstaller takes what the first run leaves.
ORDER = ("02-verify", "11-setup-onedrive", "12-setup-eboot101", "03-install", "04-layout", "05-checks",
         "13-bundled-python", "14-onedrive-check", "15-empty-folder", "16-drive-root", "17-swapped", "18-disc-id",
         "19-iso", "20-eboot-101", "21-ask-again", "22-launcher-dialog", "06-build", "07-launch", "08-readonly",
         "23-uninstall-cover", "09-uninstall", "10-leftovers")


FUNCS = dict(zip(STEPS, (s_verify, s_install, s_layout, s_checks, s_build, s_launch, s_readonly, s_uninstall,
                         s_leftovers)))
FUNCS.update(zip(NEW_STEPS, NEW_FUNCS))
ALL_STEPS = STEPS + NEW_STEPS


def safe_console():
    """The console may be cp1252 (cmd.exe over ssh): a character it cannot show (U+FFFD from a tool's output) crashed
    a step there (VM run). Print UTF-8 where the stream allows it, else replace; the out\\ files stay UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            try:
                stream.reconfigure(errors="replace")
            except (AttributeError, ValueError, OSError):
                pass


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("step", choices=ALL_STEPS)
    ap.add_argument("--base", default="C:\\kz2")
    ap.add_argument("--dir", default="", help="install folder for 03-install (default: setup's per-user default)")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--wait", type=int, default=60, help="seconds to watch the launcher in 07/08")
    ap.add_argument("--build-timeout", type=int, default=4 * 3600)
    a = ap.parse_args(argv)
    st = Step(a.base, a.step)
    try:
        return FUNCS[a.step](st, a)
    except Exception as e:   # noqa: BLE001 (a crash is a FAIL with its reason, never a silent stop)
        import traceback
        st.say(traceback.format_exc())
        return st.end("FAIL", f"vm_test crashed: {e.__class__.__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())
