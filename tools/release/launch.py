#!/usr/bin/env python3
"""Launcher logic behind `Project Pyrrhus.exe`. From Project Helghast tools/release/launch.py (no "Prepare shaders
again": KZ2 has no shader warm-up yet).

The exe (installer/launcher/launcher.c) only starts the bundled `toolchain\\python\\pythonw.exe` on this file with
`--root <its own folder>` and its own arguments; everything it decides is here, so a host test can check it.

    launch.py --root DIR [--print] [--repair] [game arguments...]

What it does, from what is on disk under DIR:
  first-build     never built (no build/paths.json): offer the first-run build (firstrun.py --interactive; with the
                  wizard's folders in kz2-install.ini [paths] it adds --check-first and them, so the console checks
                  them first instead of asking again)
  missing-inputs  the dump, the update folder or the EBOOT named in paths.json is gone (unplugged drive, moved
                  folder): offer to pick them again (firstrun.py --interactive)
  resume          a build was started and did not finish (no build-stamp.json or no build/kz2.exe): offer to go on
                  (firstrun.py --bar with the recorded paths; finished steps are skipped by their markers)
  rebuild         built, but an input changed since: the EBOOT (size/time), the folders or the check's facts, the
                  lift inputs (lift + compile) or the port version (compile only; ninja rebuilds what changed)
  run             start build/kz2.exe <EBOOT> with the player's paths (game_env below)

The build runs in its own console window (python.exe, not pythonw) and the launcher waits for it; when it ends
well the game starts. A "No" starts nothing.

Game environment: PS3_VFS_ROOT=<root>/vfs, a writable folder whose PS3_GAME is a directory junction to
<dump>/PS3_GAME (ensure_vfs; KZ3: its runtime writes a psarc cache and /dev_hdd1 under the VFS root, so a read-only
or untouched dump as the root made every asset open fail); KZ2_UPDATE_DIR=<update>/USRDIR (port/kz2/main.cpp reads it:
the 1.29 update's added_data_ps3.psarc and patch_data_ps3/ are served through it);
PS3_HDD0_ROOT=<...>/dev_hdd0 only when the update folder sits in an RPCS3 dev_hdd0/game/<id> tree;
PS3_EDAT_CACHE=<root>/build/cache/edat (port/patches/5002); VKD3D_SHADER_CACHE_PATH=<data>/cache/vkd3d (Proton's
vkd3d-proton pipeline cache, made first; Windows ignores it). Working folder <data> (where cellSaveData's ./gamedata
lands): the install folder when kz2-install.ini says portable=1, else %APPDATA%/Project Pyrrhus.

Version check (opt-in, kz2-install.ini [online] check_updates=1): at most once a day, version_check.py runs in the
background (no window, 8 s timeout) and leaves its line in <root>/logs/version-check.txt; the next start shows
"a new version is out" once per version (a "No" is remembered in [online] dismissed). When the release has a setup
and its .sha256, the first question is "Update this installation now?": Yes downloads both from the project's release
downloads only (fetch_update), checks the hash, starts the setup with /DIR=<root> and ends the launcher; No (or a
release without them) asks about the release page as before. Nothing else goes online.

--repair: "Verify and rebuild" (Start menu entry): first the install's own files against manifest.json (the
payload's SHA-256 list; a missing or changed file = "reinstall over this folder", nothing is rebuilt from a damaged
install), then firstrun.py --bar with the recorded paths: the check step always runs again (dump, update, EBOOT
hash), and every later step whose inputs fingerprint changed runs again (the others are kept; ninja recompiles what
changed). Never built or inputs gone = the same questions as a normal start. Ends with a message; does not start the game.

launcher.log (<root>/logs): one "start: <action>" line and one "version: X.Y.Z (build stamp: ...)" line per start.

--print: show the decision, the command, the working folder and the variables it sets, as JSON; starts nothing.
"""
import argparse
import configparser
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402

TITLE = "Project Pyrrhus"
# The only page an update notice may open (security review F2, 2026-10-20): the check's reply cannot send the player
# anywhere else.
RELEASES = "https://github.com/undecuple/project-pyrrhus/releases/"
SAVE_FOLDER = "Project Pyrrhus"         # under %APPDATA% when not portable
FIRSTRUN_LOG = "Project-Pyrrhus-firstrun.log"
ISSUES_URL = "https://github.com/undecuple/project-pyrrhus/issues"
# every failure message says where to report it (the log holds no personal folders)
REPORT = f"\n\nTo report a problem, attach this log on the issues page: {ISSUES_URL}"
GAME_VARS = ("KZ2_PAD_LAYOUT", "KZ2_PROMPTS", "KZ2_DISPLAY", "PS3_VFS_ROOT", "KZ2_UPDATE_DIR", "PS3_HDD0_ROOT", "PS3_EDAT_CACHE",
             "VKD3D_SHADER_CACHE_PATH")
VKD3D_CACHE = os.path.join("cache", "vkd3d")   # under the data folder (per user; the uninstaller's cache line removes it)


# ------------------------------------------------------------------------------------------------------- reading
def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_ini(root):
    cp = configparser.ConfigParser()
    cp.read(os.path.join(root, "kz2-install.ini"), encoding="utf-8")
    g = lambda s, k, d="": cp.get(s, k, fallback=d).strip()  # noqa: E731
    return {"portable": g("install", "portable", "0") == "1", "check_updates": g("online", "check_updates", "0") == "1",
            "last_check": g("online", "last_check"), "dismissed": g("online", "dismissed"),
            "layout": fr.pad_layout(g("controls", "layout"))[0],
            "prompts": fr.prompt_set(g("controls", "prompts"))[0],
            "prompts_bad": g("controls", "prompts") if not fr.prompt_set(g("controls", "prompts"))[1] else "",
            "display": fr.display_mode(g("display", "mode"))[0], "display_set": g("display", "mode") != "",
            "display_bad": g("display", "mode") if not fr.display_mode(g("display", "mode"))[1] else "",
            "layout_bad": g("controls", "layout") if not fr.pad_layout(g("controls", "layout"))[1] else ""}


def write_ini(root, section, key, value):
    p = os.path.join(root, "kz2-install.ini")
    cp = configparser.ConfigParser()
    cp.read(p, encoding="utf-8")
    if not cp.has_section(section):
        cp.add_section(section)
    cp.set(section, key, value)
    with open(p, "w", encoding="utf-8") as f:
        cp.write(f)


def version_line(root):
    """"version: <VERSION.txt>", plus what the build recorded in build/build-stamp.json (port version, patch set, build
    time) when that file exists; nothing is invented (from Project Helghast v0.1.3)."""
    stamp = load_json(os.path.join(root, "build", "build-stamp.json")) or {}
    rec = [f"{k} {stamp[k]}" for k in ("version", "patchset", "built") if stamp.get(k)]
    return f"version: {fr.port_version(root)}" + (f" (build stamp: {', '.join(rec)})" if rec else "")


def note(root, text):
    """One line in <root>/logs/launcher.log (what the launcher decided; pythonw has no console). Never fails."""
    try:
        d = os.path.join(root, "logs")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "launcher.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {text}\n")
    except OSError:
        pass


def ctx_for(root, paths):
    """A firstrun Ctx for the recorded paths, so the fingerprint parts are computed the same way as the build's."""
    return fr.Ctx(root=root, build=os.path.join(root, "build"), dump=paths.get("dump", ""),
                  update=paths.get("update", ""), eboot=paths.get("eboot", ""), facts=paths.get("facts") or {})


# ------------------------------------------------------------------------------------------------------ deciding
def decide(root):
    """-> (action, reason); action is one of first-build, missing-inputs, resume, rebuild, run."""
    build = os.path.join(root, "build")
    paths = load_json(os.path.join(build, "paths.json"))
    if not paths or not paths.get("dump"):
        return "first-build", "The port is not built on this computer yet"
    gone = [paths[k] for k in ("dump", "update", "eboot") if paths.get(k) and not os.path.exists(paths[k])]
    if gone:
        return "missing-inputs", "These game folders or files are not found any more: " + ", ".join(gone)
    stamp = load_json(os.path.join(build, "build-stamp.json"))
    if not stamp or not os.path.isfile(os.path.join(build, "kz2.exe")):
        return "resume", "The last build did not finish"
    if not os.path.isfile(os.path.join(build, fr.AT3_DLL)):
        return "resume", f"{fr.AT3_DLL} is missing from the build (the game does not start without it)"
    if paths.get("eboot") and stamp.get("eboot_stat") != fr.eboot_stat(paths["eboot"]):
        return "rebuild", "The EBOOT changed since the port was built (lift and compile again)"
    now, then = ctx_for(root, paths).parts(), stamp.get("parts") or {}
    if now["base"] != then.get("base"):
        return "rebuild", "The game folders changed since the port was built (lift and compile again)"
    if now["lift"] != then.get("lift"):
        return "rebuild", "This version changes the lift (lift and compile again)"
    if now["runtime"] != then.get("runtime"):
        return "rebuild", "The port was updated (compile again; usually minutes)"
    return "run", ""


def rpcs3_hdd0(update):
    """<x>/dev_hdd0 when the update folder is <x>/dev_hdd0/game/<title id> (RPCS3's layout), else ""."""
    parent = os.path.dirname(os.path.normpath(update))
    hdd0 = os.path.dirname(parent)
    if os.path.basename(parent).lower() == "game" and os.path.basename(hdd0).lower() == "dev_hdd0":
        return hdd0
    return ""


def data_dir(root, portable, environ, appdata=None):
    """Where saves, logs and caches of play go: the install folder when portable, else %APPDATA%/Project Pyrrhus."""
    appdata = appdata if appdata is not None else environ.get("APPDATA", "")
    return root if portable or not appdata else os.path.join(appdata, SAVE_FOLDER)


VFS = "vfs"                 # <root>/vfs: the game's writable VFS root
VFS_LINK = "link.json"      # what <root>/vfs/PS3_GAME was made to point at


def vfs_root(root):
    return os.path.join(root, VFS)


def _is_dir_link(p):
    """A symlink or (Windows) a directory junction: removing it never touches its target."""
    if os.path.islink(p):
        return True
    isj = getattr(os.path, "isjunction", None)   # Python 3.12+
    return bool(isj and isj(p))


def _make_dir_link(target, link):
    """Directory junction on Windows (no admin rights or developer mode needed), else a symlink. -> error or ""."""
    errs = []
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(target, link)
            return ""
        except (ImportError, AttributeError, OSError) as e:
            errs.append(f"junction: {e}")
    try:
        os.symlink(target, link, target_is_directory=True)
        return ""
    except (OSError, NotImplementedError) as e:
        errs.append(f"symlink: {e}")
    return "; ".join(errs)


def ensure_vfs(root, dump):
    """Make <root>/vfs with PS3_GAME -> <dump>/PS3_GAME. -> (vfs folder, error text or "").

    The player's dump is read in place and never written: the runtime's writes (psarc-cache, /dev_hdd1 cache) land
    in <root>/vfs. A real folder already named PS3_GAME there is never removed (error instead); a link to another
    dump (the player picked a new folder) is replaced; removing a link leaves its target alone."""
    v = vfs_root(root)
    link = os.path.join(v, "PS3_GAME")
    target = os.path.join(dump, "PS3_GAME")
    rec = os.path.join(v, VFS_LINK)
    os.makedirs(v, exist_ok=True)
    if _is_dir_link(link) or (os.path.isdir(link) and (load_json(rec) or {}).get("link") == link):
        if (load_json(rec) or {}).get("target") == target and os.path.isdir(link):
            return v, ""
        try:
            try:
                os.unlink(link)
            except OSError:
                os.rmdir(link)      # a junction on older Pythons; RemoveDirectory removes the link only
        except OSError as e:
            return v, f"Could not replace the old link {link} ({e})"
    elif os.path.lexists(link):
        return v, f"{link} is a real folder, not a link to the game folder; move it away and start again"
    err = _make_dir_link(target, link)
    if err:
        return v, f"Could not link {target} into {v} ({err})"
    with open(rec, "w", encoding="utf-8") as f:
        json.dump({"link": link, "target": target}, f, indent=1)
    return v, ""


def game_env(root, paths, portable, environ, appdata=None, layout="original", prompts="auto", display=None):
    """-> (argv, cwd, env, added): the game command for the recorded paths."""
    cwd = data_dir(root, portable, environ, appdata)
    # KZ2_PAD_LAYOUT: read by the runtime's SetFunctionButton hook (until the hook is in, no effect)
    added = {"KZ2_PAD_LAYOUT": fr.pad_layout(layout)[0],
             "PS3_VFS_ROOT": vfs_root(root), "PS3_EDAT_CACHE": os.path.join(root, "build", "cache", "edat"),
             # Under Proton/Wine, vkd3d-proton writes its pipeline cache (vkd3d-proton.cache) into the working folder
             # unless this names a folder (it must exist; main() makes it). ENHANCEMENT for Linux players: one per-user
             # place. Native Windows has no vkd3d and ignores the variable. Not a stable vkd3d-proton API: if a later
             # Proton drops it, the cache lands in the working folder (also per user) as before.
             "VKD3D_SHADER_CACHE_PATH": os.path.join(cwd, VKD3D_CACHE)}
    ps = fr.prompt_set(prompts)[0]
    if ps != "auto":   # patch 4011: ps3|ps4|xbox|keyboard win over keybinds.ini [prompts]; auto leaves the variable unset
        added["KZ2_PROMPTS"] = ps
    if display is not None:
        # KZ2_DISPLAY (patch 2095) wins over display.ini for the run and the port then saves nothing, so the launcher's
        # choice is the setting; display.ini (the player's Alt+Enter file) is never written by the launcher. Unset
        # (an older kz2-install.ini without [display]) leaves display.ini in charge.
        added["KZ2_DISPLAY"] = fr.display_mode(display)[0]
    if paths.get("update"):
        added["KZ2_UPDATE_DIR"] = os.path.join(paths["update"], "USRDIR")
        hdd0 = rpcs3_hdd0(paths["update"])
        if hdd0:   # ASSUMPTION (from KZ3): trophies + update resolve; cellSaveData keeps ./gamedata (cwd), not this
            added["PS3_HDD0_ROOT"] = hdd0
    env = dict(environ)
    env.update(added)
    return [os.path.join(root, "build", "kz2.exe"), paths["eboot"]], cwd, env, added


def setup_paths(root):
    """The folders the installer wizard resolved (kz2-install.ini [paths]: dump, update, eboot), or {}. Only a pair of
    dump and update counts: the wizard writes both whenever it writes any (kz2.iss WritePaths)."""
    cp = configparser.ConfigParser()
    cp.read(os.path.join(root, "kz2-install.ini"), encoding="utf-8")
    g = {k: cp.get("paths", k, fallback="").strip() for k in ("dump", "update", "eboot")}
    return g if g["dump"] and g["update"] else {}


def firstrun_cmd(root, action, paths, portable, python):
    """The build command for an action other than run. A first build with the installer's folders in kz2-install.ini
    [paths] starts from them (checks them first; the console asks only after a FAIL or on c; from Project Helghast v0.1.3);
    without them, and for missing-inputs (the recorded folders are gone), the console asks."""
    a = [python, os.path.join(HERE, "firstrun.py"), "--root", root, "--log-dir", root, "--log-name", FIRSTRUN_LOG]
    given = setup_paths(root) if (action == "first-build" and not paths) else {}
    if given:
        a += ["--interactive", "--check-first", "--dump", given["dump"], "--update", given["update"]]
        if given["eboot"]:
            a += ["--eboot", given["eboot"]]
        return a + (["--portable"] if portable else [])
    if action in ("first-build", "missing-inputs") or not paths:
        return a + ["--interactive"] + (["--portable"] if portable else [])
    a += ["--bar", "--dump", paths["dump"]]
    for k in ("update", "eboot"):
        if paths.get(k):
            a += [f"--{k}", paths[k]]
    return a


def verify_install(root):
    """The payload files against <root>/manifest.json (assemble_payload.py): -> (files checked, [problems]).
    No manifest (a source tree, a developer run) -> (0, [])."""
    man = load_json(os.path.join(root, "manifest.json"))
    if not man or not isinstance(man.get("files"), list):
        return 0, []
    import hashlib
    bad, n = [], 0
    zip_only = set(man.get("zip_only", ()))     # the zip's run.cmd: an installed copy has none (kz2.iss Excludes)
    for e in man["files"]:
        p = os.path.join(root, *e["path"].split("/"))
        if e["path"] in zip_only and not os.path.lexists(p):
            continue
        n += 1                                  # only what was checked is counted ("Verified: N install files")
        try:
            if os.path.getsize(p) != e["size"]:
                bad.append(f"{e['path']} (changed)")
                continue
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != e["sha256"]:
                bad.append(f"{e['path']} (changed)")
        except OSError:
            bad.append(f"{e['path']} (missing)")
    return n, bad


def repair(root, action, reason, paths, ini, ui, run):
    """--repair: verify the install, then re-run the checks and rebuild what changed (docstring)."""
    checked, bad = verify_install(root)
    if bad:
        more = f"\n... and {len(bad) - 5} more" if len(bad) > 5 else ""
        ui.info(f"{len(bad)} of the {checked} files of this install are missing or changed:\n" + "\n".join(bad[:5]) +
                more + "\n\nRun the setup again (or unpack the zip again) over this folder; your saves stay.")
        return 1
    if action in ("first-build", "missing-inputs"):
        q = f"{reason}.\n\n{QUESTION[action]}"
    else:
        q = ("Check your game files again and rebuild what changed? Steps whose inputs did not change are kept, "
             "so this takes from a minute to a full build; a console window shows the progress.")
    if not ui.ask(q):
        return 0
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    rc = run(firstrun_cmd(root, "rebuild" if action not in ("first-build", "missing-inputs") else action, paths,
                          ini["portable"], console_python()), creationflags=flags)
    after, _ = decide(root)
    if rc != 0 or after != "run":
        ui.info(f"{did_not_finish(rc, 'The check or the build did not finish')}. {log_note(root)}")
        return rc or 1
    ui.info(f"Verified: {checked} install files intact, your game files pass the checks and the port is up to date.")
    return 0


def check_due(ini, today):
    return ini["check_updates"] and ini["last_check"] != today.isoformat()


def newer_from_result(path, dismissed):
    """(latest, url, setup url, sha256 url) when the last background check found a newer release not dismissed yet,
    else None ("" for an asset the release does not have)."""
    try:
        with open(path, encoding="utf-8") as f:
            line = f.readline().strip()
    except OSError:
        return None
    kv = dict(p.split("=", 1) for p in line.split()[1:] if "=" in p)
    if line.startswith("VERSION ") and kv.get("status") == "newer" and kv.get("latest") not in (None, "-", dismissed):
        return (kv["latest"], kv.get("url", "-"), "" if kv.get("setup", "-") == "-" else kv["setup"],
                "" if kv.get("sha256", "-") == "-" else kv["sha256"])
    return None


# "Update this installation" (opt-in twice: the player ticked the version check, then says Yes to the question): the
# setup and its .sha256 come only from the project's own release downloads, the hash is checked before anything runs,
# and the setup is started for this folder (it keeps the build, saves and settings; ninja rebuilds what changed).
DOWNLOADS = RELEASES + "download/"
SETUP_MAX = 256 << 20


def _get(url, limit, timeout=60):
    """GET url (https only, the project's release downloads) -> bytes, at most `limit`."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "project-pyrrhus-launcher"})
    with urllib.request.urlopen(req, timeout=timeout) as r:     # noqa: S310 (prefix checked by fetch_update)
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"more than {limit:,} bytes")
    return data


def fetch_update(setup_url, sha_url, dest_dir, get=None):
    """Download the release's setup and its .sha256, check the hash. -> (setup path, "") or ("", why)."""
    import hashlib
    import re
    get = get or _get
    for u in (setup_url, sha_url):
        if not u.startswith(DOWNLOADS):
            return "", f"{u} is not one of the project's release downloads"
    name = setup_url.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.exe", name):
        return "", f"unexpected setup name {name!r}"
    try:
        sums = get(sha_url, 4096).decode("utf-8", "replace").split()
        want = sums[0].lower() if sums and re.fullmatch(r"[0-9a-fA-F]{64}", sums[0]) else ""
        if not want or (len(sums) > 1 and sums[1].lstrip("*") != name):
            return "", "the published SHA-256 file does not name this setup"
        data = get(setup_url, SETUP_MAX)
    except (OSError, ValueError) as e:
        return "", f"download failed ({e})"
    if hashlib.sha256(data).hexdigest() != want:
        return "", "the download does not match its published SHA-256 (not started)"
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, name)
    with open(path, "wb") as f:
        f.write(data)
    return path, ""


# ------------------------------------------------------------------------------------------------------- the UI
class UI:
    """Message boxes on Windows (pythonw has no console), the terminal elsewhere (developer runs)."""

    def ask(self, text):
        if os.name == "nt":
            import ctypes
            return ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x4 | 0x20) == 6   # YESNO|QUESTION -> IDYES
        return input(f"{text} [y/N] ").strip().lower().startswith("y")

    def info(self, text):
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x40)
        else:
            print(text)

    def open_url(self, url):
        import webbrowser
        webbrowser.open(url)


CONTROLS_TEXT = ("Pad controls. Original (default) keeps the game's own button layout. Modern changes the pad "
                 "buttons only (the keyboard binds stay as they are).\n\nUse Modern now? Yes = Modern, No = Original."
                 "\n(Currently: {cur}.)")


def set_controls(root, value, ini, ui):
    """The launcher's Controls choice -> [controls] layout in kz2-install.ini (the game reads it at the next start)."""
    if value == "ask":
        value = "modern" if ui.ask(CONTROLS_TEXT.format(cur=ini["layout"])) else "original"
    layout, ok = fr.pad_layout(value)
    if not ok or not value.strip():
        ui.info(f"Unknown layout {value!r}; use original or modern.")
        return 2
    write_ini(root, "controls", "layout", layout)
    note(root, f"controls: {layout}")
    ui.info(f"Controls: {layout.capitalize()}. It applies the next time the game starts.")
    return 0


def set_prompts(root, value, ini, ui):
    """The launcher's Button prompts choice -> [controls] prompts in kz2-install.ini. No value: the next set in the
    cycle Auto, PS3, PS4/PS5, Xbox, Keyboard (the launcher has message boxes only, no list)."""
    if value == "ask":
        cur = fr.PROMPT_SETS.index(ini["prompts"])
        value = fr.PROMPT_SETS[(cur + 1) % len(fr.PROMPT_SETS)]
    sel, ok = fr.prompt_set(value)
    if not ok or not value.strip():
        ui.info(f"Unknown button prompts {value!r}; use auto, ps3, ps4, xbox or keyboard.")
        return 2
    write_ini(root, "controls", "prompts", sel)
    note(root, f"button prompts: {sel}")
    ui.info(f"Button prompts: {fr.PROMPT_LABELS[sel]}. It applies the next time the game starts. "
            "Run this again to move to the next set.")
    return 0


def set_display(root, value, ini, ui):
    """The launcher's Display choice -> [display] mode in kz2-install.ini. No value: the next mode in the cycle
    Windowed, Borderless, Fullscreen (the launcher has message boxes only, no list)."""
    if value == "ask":
        cur = fr.DISPLAY_MODES.index(ini["display"])
        value = fr.DISPLAY_MODES[(cur + 1) % len(fr.DISPLAY_MODES)]
    sel, ok = fr.display_mode(value)
    if not ok or not value.strip():
        ui.info(f"Unknown display mode {value!r}; use windowed, borderless or fullscreen.")
        return 2
    write_ini(root, "display", "mode", sel)
    note(root, f"display: {sel}")
    ui.info(f"Display: {fr.DISPLAY_LABELS[sel]}. It applies the next time the game starts. "
            "Run this again to move to the next mode.")
    return 0


def console_python():
    """python.exe beside pythonw.exe (the build needs a console window), else this interpreter."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(alt):
            return alt
    return exe


def run_wait(argv, **kw):
    return subprocess.call(argv, **kw)


# The first-run console closed with its X button (or Ctrl+Break): STATUS_CONTROL_C_EXIT and DBG_TERMINATE_PROCESS, as
# unsigned and signed exit codes. Adapted from Project Helghast (the Killzone 3 PC port, same author, MIT), KZ3
# Project Helghast v0.1.1: the dialog said "code 3221225786".
CONSOLE_CLOSED = (0xC000013A, 0x40010004, 0xC000013A - 2**32)


def did_not_finish(rc, what):
    """The dialog's first sentence for a first-run or rebuild child that ended with rc != 0."""
    if rc in CONSOLE_CLOSED:
        return what + " (its window was closed before it finished; finished steps are kept, open the program again to continue)"
    return f"{what} (code {rc})"


def log_note(root):
    """The dialog's log sentence: the first-run log's path and how to report it, or, when the window was closed before
    the first check wrote it, that no log exists yet (adapted from Project Helghast v0.1.1)."""
    log = os.path.join(root, FIRSTRUN_LOG)
    if os.path.isfile(log):
        return f"The log is {log}.{REPORT}"
    return "No log was written yet: it starts with the first check."


def spawn(argv, **kw):
    return subprocess.Popen(argv, **kw)


QUESTION = {
    "first-build": "Build it now? The first build lifts and compiles the port from your own game files and takes "
                   "5 to 30 minutes; a console window shows the progress.",
    "missing-inputs": "Pick the folders again and build? (your saves stay where they are)",
    "resume": "Continue the build now? Finished steps are skipped.",
    "rebuild": "Build again now?",
}


def main(argv=None, ui=None, run=run_wait, start=spawn, today=None, environ=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(HERE)))
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--controls", nargs="?", const="ask", metavar="original|modern",
                    help="set the pad layout in kz2-install.ini (no value: ask) and exit; Modern changes pad "
                         "buttons only, the keyboard binds stay")
    ap.add_argument("--prompts", nargs="?", const="ask", metavar="auto|ps3|ps4|xbox|keyboard",
                    help="set the button prompts in kz2-install.ini (no value: the next set in the cycle) and exit")
    ap.add_argument("--display", nargs="?", const="ask", metavar="windowed|borderless|fullscreen",
                    help="set the display mode in kz2-install.ini (no value: the next mode in the cycle) and exit")
    ap.add_argument("--repair", action="store_true",
                    help='"Verify and rebuild": check the install and the game files again, rebuild what changed')
    a, extra = ap.parse_known_args(argv)
    root = os.path.abspath(a.root)
    ui = ui or UI()
    environ = dict(os.environ if environ is None else environ)
    today = today or datetime.date.today()
    ini = read_ini(root)
    if a.controls:
        return set_controls(root, a.controls, ini, ui)
    if a.prompts:
        return set_prompts(root, a.prompts, ini, ui)
    if a.display:
        return set_display(root, a.display, ini, ui)
    action, reason = decide(root)
    paths = load_json(os.path.join(root, "build", "paths.json")) or {}

    if a.print:
        rep = {"action": action, "reason": reason, "portable": ini["portable"], "controls": ini["layout"], "prompts": ini["prompts"],
               "display": ini["display"], "version_check_due": check_due(ini, today)}
        if action == "run":
            gargv, cwd, _, added = game_env(root, paths, ini["portable"], environ, layout=ini["layout"], prompts=ini["prompts"],
                                            display=ini["display"] if ini["display_set"] else None)
            rep.update(argv=gargv + extra, cwd=cwd, env=added)
        else:
            rep["build"] = firstrun_cmd(root, action, paths, ini["portable"], console_python())
        if a.repair:
            checked, bad = verify_install(root)
            rep["repair"] = {"checked": checked, "problems": bad,
                             "build": firstrun_cmd(root, action if action in ("first-build", "missing-inputs")
                                                   else "rebuild", paths, ini["portable"], console_python())}
        print(json.dumps(rep, indent=1))
        return 0

    logs = os.path.join(root, "logs")
    if ini["layout_bad"]:
        note(root, f"kz2-install.ini [controls] layout = {ini['layout_bad']!r} is unknown; using original")
    if ini["display_bad"]:
        note(root, f"kz2-install.ini [display] mode = {ini['display_bad']!r} is unknown; using windowed")
    if ini["prompts_bad"]:
        note(root, f"kz2-install.ini [controls] prompts = {ini['prompts_bad']!r} is unknown; using auto")
    note(root, f"start: {action}" + (f" ({reason})" if reason else ""))
    note(root, version_line(root))
    nv = newer_from_result(os.path.join(logs, "version-check.txt"), ini["dismissed"])
    if nv and nv[2] and nv[3] and ui.ask(
            f"{TITLE} {nv[0]} is out. Update this installation now?\n\nYes downloads its setup from the project's "
            "releases on GitHub, checks it against its published SHA-256 and starts it for this folder. Your build is "
            "kept (only what changed is built again), and your saves and settings stay. No asks about the release page."):
        import tempfile
        path, err = fetch_update(nv[2], nv[3], os.path.join(tempfile.gettempdir(), "Project-Pyrrhus-update"))
        note(root, f"update {nv[0]}: {err or 'setup ' + os.path.basename(path) + ' checked and started'}")
        if not err:
            start([path, f"/DIR={root}"])
            return 0
        ui.info(f"The update could not be used: {err}. Nothing was changed; the game starts as it is.{REPORT}")
    elif nv:
        if ui.ask(f"{TITLE} {nv[0]} is out. Open its release page?"):
            if nv[1].startswith(RELEASES):
                ui.open_url(nv[1])
        else:
            write_ini(root, "online", "dismissed", nv[0])
    if check_due(ini, today):
        os.makedirs(logs, exist_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        start([sys.executable, os.path.join(HERE, "version_check.py"), "--current", fr.port_version(root),
               "--timeout", "8", "--result-file", os.path.join(logs, "version-check.txt"),
               "--log", os.path.join(logs, "version-check.log")], creationflags=flags)
        write_ini(root, "online", "last_check", today.isoformat())

    if a.repair:
        return repair(root, action, reason, paths, ini, ui, run)

    if action != "run":
        if not ui.ask(f"{reason}.\n\n{QUESTION[action]}"):
            return 0
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        rc = run(firstrun_cmd(root, action, paths, ini["portable"], console_python()), creationflags=flags)
        if rc != 0:
            ui.info(f"{did_not_finish(rc, 'The build did not finish')}. {log_note(root)}")
            return rc
        ini = read_ini(root)   # --interactive may have written portable/check_updates
        action, reason = decide(root)
        paths = load_json(os.path.join(root, "build", "paths.json")) or {}
        if action != "run":
            ui.info(f"{reason}. {log_note(root)}")
            return 1

    gargv, cwd, env, added = game_env(root, paths, ini["portable"], environ, layout=ini["layout"], prompts=ini["prompts"],
                                            display=ini["display"] if ini["display_set"] else None)
    try:
        _, err = ensure_vfs(root, paths["dump"])
        note(root, f"vfs: {err or 'ok'}")
        if err:
            ui.info(f"{err}.{REPORT}")
            return 1
        note(root, "game: " + " ".join(gargv + extra) + f" (cwd {cwd}; the game's log is in build\\logs)")
        fr.place_fonts(root, os.path.dirname(gargv[0]))     # the notice fonts next to kz2.exe (KZ3's error notice)
        fr.place_sdl3(root, os.path.dirname(gargv[0]))      # SDL3.dll next to kz2.exe: native pads (patch 4010)
        fr.place_decoders(root, os.path.dirname(gargv[0]))  # FFmpeg DLLs from the payload (at3_standalone.dll comes from the build)
        os.makedirs(cwd, exist_ok=True)
        os.makedirs(added["PS3_EDAT_CACHE"], exist_ok=True)
        os.makedirs(added["VKD3D_SHADER_CACHE_PATH"], exist_ok=True)
    except OSError as e:
        # A read-only install folder (or a full disk): the launcher writes the link to the game files, the notice fonts
        # and DLLs next to kz2.exe and the caches there. Say so instead of ending without a word (pythonw).
        note(root, f"prepare: {e}")
        ui.info(f"Could not prepare the game: {e}.\n\nProject Pyrrhus needs to write in its install folder ({root}) "
                f"and in {cwd}: the build, the link to your game files and the caches live there. Install it in a "
                f"folder your user can write to (the default is fine).{REPORT}")
        return 1
    rc = run(gargv + extra, cwd=cwd, env=env)
    if crashed(rc):
        # The runtime prints its [CRASH] lines to the session log and shows nothing (VM kit pre-flight: no D3D12
        # device = an access violation at start, and the window just vanished): say so, and where the log is.
        logs_dir = os.path.join(os.path.dirname(gargv[0]), "logs")
        note(root, f"game: stopped with code 0x{rc & 0xFFFFFFFF:08X}")
        ui.info(f"The game stopped unexpectedly (code 0x{rc & 0xFFFFFFFF:08X}). Its log is the newest file in "
                f"{logs_dir}.{REPORT}")
    return rc


def crashed(rc):
    """A Windows exception code as the exit code (0xC0000005 access violation, 0xC0000409 and the like): the game
    did not end by itself. Normal ends (0) and the game's own error exits (small numbers, with their own box) are not."""
    return rc is not None and (rc & 0xFFFFFFFF) >= 0xC0000000


if __name__ == "__main__":
    sys.exit(main())
