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
or untouched dump as the root made every asset open fail; reading the dump in place is no fallback: every mount,
/dev_hdd0 and /dev_usb included, maps under the VFS root, so the game would write into the dump). Before any build the
launcher makes and removes a test link there (probe_link), so a drive that cannot hold one is named within seconds; a
failed junction leaves no folder behind. When <root>/vfs cannot hold the link, the VFS root is
%LOCALAPPDATA%/Project Pyrrhus/vfs-<6 hex digits of the install folder's path> instead (alt_vfs_root, one per
install; issue #20), recorded in kz2-install.ini [vfs] alt for the uninstaller, and stays there; the one shared
%LOCALAPPDATA%/Project Pyrrhus/vfs of an earlier unreleased build is moved into it (migrate_alt). Link-free (link_free; the
main path once the runtime reads KZ2_CACHE_ROOT, Project Helghast's design): PS3_VFS_ROOT=<dump>, KZ2_CACHE_ROOT=
<root>/vfs, no link at all; the link is then the path for builds from older payloads only. KZ2_UPDATE_DIR=<update>/USRDIR (port/kz2/main.cpp reads it:
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

A first run or rebuild that ends with rc != 0: the dialog shows firstrun.py's REASON lines from
<root>/logs/firstrun-status.txt (--status-file; only when this run wrote it), then where the log is (failure_text).

version.ini (for the game's menu; the game side that draws it is not in yet): at each game start, written whole into
the player's data folder (the working folder above, where keybinds.ini, display.ini and gameplay.ini live) as
[version] current=<this port's version>, plus newer=<version> and page=<release page> only while [online]
check_updates=1 and the last check's result names a release newer than current (write_version_ini). The game never
connects. A failure is logged and the start goes on.

launcher.log (<root>/logs): one "start: <action>" line and one "version: X.Y.Z (build stamp: ...)" line per start.

kz2-install.ini is read and written through install_ini (comments, key case and keys the launcher does not know stay);
a file that cannot be read or written (locked, read-only, a folder in its place) is logged and shown once per start,
and the start goes on with the defaults. Any other unexpected error is logged with its traceback and shown
(guarded_main): pythonw has no console, so nothing ends without a word.

--print: show the decision, the command, the working folder and the variables it sets, as JSON; starts nothing.
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402
import firstrun_check as fc  # noqa: E402
import install_ini as ii  # noqa: E402

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
             "VKD3D_SHADER_CACHE_PATH", "KZ2_CACHE_ROOT")
# firstrun.py --status-file: its last RESULT line and, after RESULT ok=0, the REASON lines (why it stopped), shown in
# the launcher's dialog (after Project Helghast PR #11 did the same for its setup's box)
FIRSTRUN_STATUS = os.path.join("logs", "firstrun-status.txt")
VKD3D_CACHE = os.path.join("cache", "vkd3d")   # under the data folder (per user; the uninstaller's cache line removes it)


# ------------------------------------------------------------------------------------------------------- reading
def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_ini(root):
    """kz2-install.ini's settings (install_ini: comments, key case and unknown keys are the player's). A file that
    cannot be read (locked, a folder in its place) gives the defaults and its reason in "error", which main() logs and
    shows: under pythonw an exception would end the launcher without a word."""
    try:
        cp, err = ii.read(os.path.join(root, ii.NAME)), ""
    except ii.IniError as e:
        cp, err = ii.Ini(), str(e)
    g = lambda s, k, d="": cp.get(s, k, d).strip()  # noqa: E731
    return {"portable": g("install", "portable", "0") == "1", "check_updates": g("online", "check_updates", "0") == "1",
            "last_check": g("online", "last_check"), "dismissed": g("online", "dismissed"),
            "layout": fr.pad_layout(g("controls", "layout"))[0],
            "prompts": fr.prompt_set(g("controls", "prompts"))[0],
            "prompts_bad": g("controls", "prompts") if not fr.prompt_set(g("controls", "prompts"))[1] else "",
            "display": fr.display_mode(g("display", "mode"))[0], "display_set": g("display", "mode") != "",
            "display_bad": g("display", "mode") if not fr.display_mode(g("display", "mode"))[1] else "",
            "layout_bad": g("controls", "layout") if not fr.pad_layout(g("controls", "layout"))[1] else "",
            "vfs_alt": g("vfs", "alt"), "error": err}


def write_ini(root, section, key, value):
    """One key in kz2-install.ini; every other line stays (install_ini.set_value). Raises install_ini.IniError."""
    ii.set_value(os.path.join(root, ii.NAME), section, key, value)


def ini_trouble(root, ui, err, shown=None):
    """Log an ini read or write failure and say it once per start (shown: a set the caller keeps). -> 1."""
    note(root, f"settings: {err}")
    if shown is None or not shown:
        ui.info(f"Project Pyrrhus could not use its settings file: {err}.\n\nThis start uses the default settings "
                "where the file could not be read, and a change could not be saved. Close any program that has the "
                "file open, make sure it is not read-only, and start again.")
        if shown is not None:
            shown.add(1)
    return 1


def try_write_ini(root, section, key, value, ui, shown=None):
    """write_ini that logs and shows a failure instead of raising. -> True when written."""
    try:
        write_ini(root, section, key, value)
        return True
    except ii.IniError as e:
        ini_trouble(root, ui, str(e), shown)
        return False


def version_line(root):
    """"version: <VERSION.txt>", plus what the build recorded in build/build-stamp.json (port version, patch set, build
    time) when that file exists; nothing is invented (from Project Helghast v0.1.3)."""
    stamp = load_json(os.path.join(root, "build", "build-stamp.json")) or {}
    rec = [f"{k} {stamp[k]}" for k in ("version", "patchset", "built") if stamp.get(k)]
    return f"version: {fr.port_version(root)}" + (f" (build stamp: {', '.join(rec)})" if rec else "")


def note(root, text):
    """One line in <root>/logs/launcher.log (what the launcher decided; pythonw has no console). Never fails. The user's
    home folder becomes %USERPROFILE% (firstrun.redactor; issue #16: logs get attached to public
    issues, and a vfs/prepare error can name a path)."""
    try:
        text = fr.redactor()(text)
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


def _junction_api():
    if os.name != "nt":
        return None
    try:
        import _winapi
        return _winapi.CreateJunction
    except (ImportError, AttributeError):
        return None


# The link makers, module-level so a host test can stand in for Windows (a junction that fails half-way).
create_junction = _junction_api()
make_symlink = os.symlink


def _remove_empty_dir(p):
    """os.rmdir only: it refuses a folder with anything in it, and on a link or junction it removes the link and never
    its target. So this can never delete a player's files. -> True when p is gone."""
    if _is_dir_link(p):
        try:
            os.unlink(p)            # a symlink (POSIX rmdir refuses one); Windows removes the link only
            return True
        except OSError:
            pass
    try:
        os.rmdir(p)
        return True
    except OSError:
        return False


def _make_dir_link(target, link):
    """Directory junction on Windows (no admin rights or developer mode needed), else a symlink. -> error or "".

    _winapi.CreateJunction makes the folder first and then sets its reparse point; when the second step fails (seen as
    WinError 1392 on a player's drive) the empty folder stayed behind, the symlink then failed with WinError 183 and
    every later start refused it as a real folder. A failed attempt now removes what it made (only a folder that did
    not exist before that attempt, and only when empty or a link). Same rule as Project Helghast's _undo_link (KZ3
    tools/release/launch.py, same author, MIT)."""
    errs = []
    if create_junction is not None:
        existed = os.path.lexists(link)
        try:
            create_junction(target, link)
            return ""
        except OSError as e:
            errs.append(f"junction: {e}")
            if not existed and os.path.lexists(link):
                _remove_empty_dir(link)
    existed = os.path.lexists(link)
    try:
        make_symlink(target, link, target_is_directory=True)
        return ""
    except (OSError, NotImplementedError) as e:
        errs.append(f"symlink: {e}")
        if not existed and os.path.lexists(link):
            _remove_empty_dir(link)
    return "; ".join(errs)


CACHE_ROOT_HEADER = ("port", "kz2", "kz2_cache_root.h")   # the runtime's cache-root support (KZ2_CACHE_ROOT)


def link_free(root, build=None):
    """True when the installed kz2.exe takes the game folder and the writable folder apart (build-stamp.json
    "cache_root", set by firstrun.after_stamp when the payload has port/kz2/kz2_cache_root.h naming KZ2_CACHE_ROOT):
    PS3_VFS_ROOT = the dump, read in place, and KZ2_CACHE_ROOT = <root>/vfs takes every write, so no folder link is
    made. The design is Project Helghast's (KZ3 tools/release/launch.py link_free, kz3.ini cache_root, same author,
    MIT); its reason: a native Windows install could not open anything through the junction. Until the runtime
    reads KZ2_CACHE_ROOT (requested), every build stamps False and the link below stays the path."""
    stamp = load_json(os.path.join(build or os.path.join(root, "build"), "build-stamp.json")) or {}
    return bool(stamp.get("cache_root"))


def drop_link(root):
    """Link-free start: remove the PS3_GAME link an older start left in <root>/vfs (the link only, never its target;
    a real folder is left alone) and its record. -> error text or ""."""
    v = vfs_root(root)
    link = os.path.join(v, "PS3_GAME")
    if _is_dir_link(link):
        try:
            try:
                os.unlink(link)
            except OSError:
                os.rmdir(link)
        except OSError as e:
            return f"Could not remove the old link {link} ({e})"
        with contextlib.suppress(OSError):
            os.remove(os.path.join(v, VFS_LINK))
    os.makedirs(v, exist_ok=True)
    return ""


ALT_PREFIX = "vfs-"          # %LOCALAPPDATA%\Project Pyrrhus\vfs-<install_key>: one second place per install


def install_key(root, absolute=os.path.abspath):
    """Six hex digits naming one install folder: SHA-256 of its path as UTF-16LE, after these steps (kz2.iss
    InstallKey does the same, so the uninstaller finds the folder without the launcher): absolute, "/" -> "\\", A-Z
    lower-cased (ASCII only, as Inno's Lowercase), trailing "\\" removed except after a drive letter."""
    s = absolute(root).replace("/", "\\")
    s = "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)
    while len(s) > 3 and s.endswith("\\"):
        s = s[:-1]
    return hashlib.sha256(s.encode("utf-16-le")).hexdigest()[:6]


def alt_vfs_root(environ, root):
    """The second place for the VFS root when the install folder's drive cannot hold the link: %LOCALAPPDATA%\\Project
    Pyrrhus\\vfs-<install_key> (the Windows drive, which is NTFS), one per install folder, so two installs never share
    a link or its record. "" without LOCALAPPDATA (Linux host tests, odd setups)."""
    la = (environ or {}).get("LOCALAPPDATA", "")
    return os.path.join(la, SAVE_FOLDER, ALT_PREFIX + install_key(root)) if la else ""


def legacy_alt(alt):
    """%LOCALAPPDATA%\\Project Pyrrhus\\vfs: the one second place shared by every install (an unreleased build of the
    launcher, before the per-install folders)."""
    return os.path.join(os.path.dirname(alt), VFS) if alt else ""


def migrate_alt(root, dump, alt):
    """The shared second place (legacy_alt) holding the link to this install's game folder becomes this install's
    own (renamed, same drive, so the caches stay; its record is rewritten), once. A link to another game folder is
    left for its own install; a rename that fails leaves it too (a fresh link is made). -> note text or ""."""
    old = legacy_alt(alt)
    target = os.path.join(dump, "PS3_GAME")
    if not old or os.path.lexists(alt) or not _linked(old, target):
        return ""
    try:
        os.rename(old, alt)
    except OSError as e:
        return f"vfs: the shared folder {old} stays where it is ({e}); a new link is made in {alt}"
    try:
        with open(os.path.join(alt, VFS_LINK), "w", encoding="utf-8") as f:
            json.dump({"link": os.path.join(alt, "PS3_GAME"), "target": target}, f, indent=1)
    except OSError:
        pass        # _linked also accepts the link itself
    return f"vfs: moved the shared folder {old} to this install's own {alt}"


def drive_systems(root, dump):
    """'install, game files D:\\ NTFS' (one entry per drive) for the log and the link error, or "" (fr.file_systems)."""
    return fr.file_systems([("install", root), ("game files", dump)])


def link_help(places, detail, fs="", dump=""):
    """The player's text for a folder link that could not be made in any of places (vfs folders). The 1392 sentence
    is Project Helghast's gated wording (KZ3 tools/release/launch.py _link_error_words, same author, MIT): possible
    causes, never damage as the cause."""
    where = " or in ".join(places)
    why = (" WinError 1392: the drive's file system may not support folder junctions, or it may be damaged; the safe "
           "step is an install folder on an NTFS drive such as C:." if "1392" in detail else
           " Folder links need a drive whose file system supports them, such as NTFS (FAT32 and exFAT, common on USB drives and SD cards, cannot hold them); the "
           "safe step is an install folder on an NTFS drive such as C:.")
    return (f"Project Pyrrhus could not link your game folder into {where}. The game reads your game folder through "
            f"that link and writes its caches in the install folder, never into your game folder.{why} Your game "
            f"folder can stay where it is." + (f" Drives: {fs}." if fs else "") + f" (Details: {detail})")


LINK_TEST = "link-test"     # <vfs>/link-test(-target): the early link check's own folders


def _probe_in(v):
    t = os.path.join(v, LINK_TEST + "-target")
    lk = os.path.join(v, LINK_TEST)
    os.makedirs(t, exist_ok=True)
    if _is_dir_link(lk) or os.path.isdir(lk):
        _remove_empty_dir(lk)       # a test link left by a stopped start (never anything with files in it)
    err = _make_dir_link(t, lk)
    if not err:
        _remove_empty_dir(lk)
    _remove_empty_dir(t)
    return err


def probe_link(root, alt="", fs_of=None, dump=""):
    """Make and remove a test link in <root>/vfs (else in alt), before a long build, so a drive that cannot hold the
    game's link is named within seconds instead of after the build. -> player text or "" (one of them works)."""
    v = vfs_root(root)
    try:
        err = _probe_in(v)
    except OSError as e:
        err = f"could not write in {v} ({e})"
    if not err:
        return ""
    if alt and os.path.normcase(alt) != os.path.normcase(v):
        try:
            err2 = _probe_in(alt)
        except OSError as e:
            err2 = f"could not write in {alt} ({e})"
        if not err2:
            note(root, f"vfs: link check: no link possible in {v} ({err}); the game's VFS folder will be {alt}")
            return ""
        return link_help([v, alt], f"{err}; {alt}: {err2}", (fs_of or drive_systems)(root, dump))
    return link_help([v], err, (fs_of or drive_systems)(root, dump))


def _linked(v, target):
    """v/PS3_GAME is the recorded link to target."""
    link = os.path.join(v, "PS3_GAME")
    rec = load_json(os.path.join(v, VFS_LINK)) or {}
    return (rec.get("target") == target and os.path.isdir(link)
            and (_is_dir_link(link) or rec.get("link") == link))


def _link_in(v, target):
    """Make v/PS3_GAME -> target (v made first). -> error text or ""."""
    link = os.path.join(v, "PS3_GAME")
    rec = os.path.join(v, VFS_LINK)
    try:
        os.makedirs(v, exist_ok=True)
    except OSError as e:
        return f"could not write in {v} ({e})"
    if _is_dir_link(link) or (os.path.isdir(link) and (load_json(rec) or {}).get("link") == link):
        if (load_json(rec) or {}).get("target") == target and os.path.isdir(link):
            return ""
        try:
            try:
                os.unlink(link)
            except OSError:
                os.rmdir(link)      # a junction on older Pythons; RemoveDirectory removes the link only
        except OSError as e:
            return f"Could not replace the old link {link} ({e})."
    elif os.path.lexists(link) and not _remove_empty_dir(link):
        return f"{link} is a real folder with files in it, not a link to the game folder; move it away and start again."
    err = _make_dir_link(target, link)
    if err:
        return f"linking {target}: {err}"
    try:
        with open(rec, "w", encoding="utf-8") as f:
            json.dump({"link": link, "target": target}, f, indent=1)
    except OSError as e:
        return f"could not write {rec} ({e})"
    return ""


def _inside(path, folder):
    a, b = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def current_vfs(root, dump, alt=""):
    """The VFS root the game uses now: alt when only alt holds the link (sticky, so caches and trophies stay put)."""
    target = os.path.join(dump, "PS3_GAME") if dump else ""
    if alt and target and _linked(alt, target) and not _linked(vfs_root(root), target):
        return alt
    return vfs_root(root)


def ensure_vfs(root, dump, alt="", fs_of=None):
    """Make a VFS root with PS3_GAME -> <dump>/PS3_GAME. -> (vfs folder, error text or "").

    The player's dump is read in place and never written: the runtime's writes (psarc-cache, /dev_hdd1 cache, trophies)
    land in the VFS folder, <root>/vfs, or alt (%LOCALAPPDATA%\\Project Pyrrhus\\vfs) when <root>/vfs cannot hold the
    link (a drive without junctions; issue #20) and alt can; once alt is used it stays in use. Reading the dump in
    place without a link is no fallback: ps3recomp maps every mount (/dev_hdd0 without PS3_HDD0_ROOT, /dev_usb*,
    /host_root, any path with "USRDIR/" in the sys_fs layer) and cellGame's content root under the VFS root, so the
    game would write into the dump. A real folder already named PS3_GAME is never removed while it holds anything; an
    empty one (what a failed junction left in launcher 0.1.2 and earlier) is removed and the link made again. A link to
    another dump is replaced; removing a link leaves its target alone. An install folder inside the dump's PS3_GAME
    is refused (the link would contain itself and the game would write into the dump)."""
    v = vfs_root(root)
    target = os.path.join(dump, "PS3_GAME")
    if _inside(v, target):
        return v, (f"The install folder {root} is inside the game's own PS3_GAME folder ({target}); the game would "
                   "write into your game files. Install Project Pyrrhus in a folder outside PS3_GAME and start again.")
    other = alt if alt and os.path.normcase(alt) != os.path.normcase(v) else ""
    if other:
        moved = migrate_alt(root, dump, other)
        if moved:
            note(root, moved)
    if other and current_vfs(root, dump, other) == other:
        return other, ""
    err = _link_in(v, target)
    if not err:
        return v, ""
    if other:
        err2 = _link_in(other, target)
        if not err2:
            note(root, f"vfs: no link possible in {v} ({err}); using {other}")
            return other, ""
        return v, link_help([v, other], f"{err}; {other}: {err2}", (fs_of or drive_systems)(root, dump))
    return v, link_help([v], err, (fs_of or drive_systems)(root, dump))


def game_env(root, paths, portable, environ, appdata=None, layout="original", prompts="auto", display=None):
    """-> (argv, cwd, env, added): the game command for the recorded paths."""
    cwd = data_dir(root, portable, environ, appdata)
    # KZ2_PAD_LAYOUT: read by the runtime's SetFunctionButton hook (until the hook is in, no effect)
    added = {"KZ2_PAD_LAYOUT": fr.pad_layout(layout)[0],
             "PS3_VFS_ROOT": current_vfs(root, paths.get("dump", ""), alt_vfs_root(environ, root)), "PS3_EDAT_CACHE": os.path.join(root, "build", "cache", "edat"),
             # Under Proton/Wine, vkd3d-proton writes its pipeline cache (vkd3d-proton.cache) into the working folder
             # unless this names a folder (it must exist; main() makes it). ENHANCEMENT for Linux players: one per-user
             # place. Native Windows has no vkd3d and ignores the variable. Not a stable vkd3d-proton API: if a later
             # Proton drops it, the cache lands in the working folder (also per user) as before.
             "VKD3D_SHADER_CACHE_PATH": os.path.join(cwd, VKD3D_CACHE)}
    if link_free(root) and paths.get("dump"):   # the dump read in place, every write under <root>/vfs (no link)
        added["PS3_VFS_ROOT"] = paths["dump"]
        added["KZ2_CACHE_ROOT"] = vfs_root(root)
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
    try:
        cp = ii.read(os.path.join(root, ii.NAME))
    except ii.IniError:
        return {}       # read_ini already logged and showed it
    g = {k: cp.get("paths", k).strip() for k in ("dump", "update", "eboot")}
    return g if g["dump"] and g["update"] else {}


def firstrun_cmd(root, action, paths, portable, python):
    """The build command for an action other than run. A first build with the installer's folders in kz2-install.ini
    [paths] starts from them (checks them first; the console asks only after a FAIL or on c; from Project Helghast v0.1.3);
    without them, and for missing-inputs (the recorded folders are gone), the console asks."""
    a = [python, os.path.join(HERE, "firstrun.py"), "--root", root, "--log-dir", root, "--log-name", FIRSTRUN_LOG,
         "--status-file", os.path.join(root, FIRSTRUN_STATUS)]
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
    since = time.time()
    rc = run(firstrun_cmd(root, "rebuild" if action not in ("first-build", "missing-inputs") else action, paths,
                          ini["portable"], console_python()), creationflags=flags)
    after, _ = decide(root)
    if rc != 0 or after != "run":
        ui.info(failure_text(root, rc, "The check or the build did not finish", since))
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


# ------------------------------------------------------------------------------------------------ version.ini
# The version block in the game's menu: the launcher writes what the game's menu version block will show, so the
# game itself never connects. Written whole at each start (a fresh small file, not the line writer: the launcher owns
# every line, and a stale newer= goes with the rest).
VERSION_INI = "version.ini"
_PLAIN = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def _plain(v):
    """"v0.1.4" or "0.1.4" -> (0, 1, 4); anything else -> None."""
    m = _PLAIN.fullmatch((v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def version_info(root, check_updates, result=None):
    """-> [(key, value)] for version.ini: current always; newer and page only when the player turned the version check
    on and the last check (logs/version-check.txt) named a release newer than this one. A "No" to the start's question
    (dismissed) does not hide it: the menu line is passive. page only when it is one of the project's release pages
    (the rule the start's question follows)."""
    cur = fr.port_version(root)
    out = [("current", cur)]
    if not check_updates:
        return out
    try:
        with open(result or os.path.join(root, "logs", "version-check.txt"), encoding="utf-8") as f:
            line = f.readline().strip()
    except (OSError, ValueError):
        return out
    kv = dict(p.split("=", 1) for p in line.split()[1:] if "=" in p)
    latest, mine = _plain(kv.get("latest")), _plain(cur)
    if not line.startswith("VERSION ") or kv.get("status") != "newer" or not latest or not mine or latest <= mine:
        return out
    out.append(("newer", "%d.%d.%d" % latest))
    if kv.get("url", "").startswith(RELEASES) and kv["url"].isascii():
        out.append(("page", kv["url"]))
    return out


def write_version_ini(folder, info):
    """Write <folder>/version.ini from version_info's pairs (temp file + replace: the game never reads half a file).
    -> "" or the reason it could not be written; never raises."""
    path = os.path.join(folder, VERSION_INI)
    tmp = path + ".tmp"
    text = ("; Written by the Project Pyrrhus launcher at each start for the game's menu; changes here are replaced.\n"
            "[version]\n" + "".join(f"{k}={v}\n" for k, v in info))
    try:
        os.makedirs(folder, exist_ok=True)
        with open(tmp, "w", encoding="ascii", newline="\r\n") as f:
            f.write(text)
        os.replace(tmp, path)
        return ""
    except (OSError, ValueError) as e:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return f"could not write {path} ({e})"


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


def set_controls(root, value, ini, ui, shown=None):
    """The launcher's Controls choice -> [controls] layout in kz2-install.ini (the game reads it at the next start)."""
    if value == "ask":
        value = "modern" if ui.ask(CONTROLS_TEXT.format(cur=ini["layout"])) else "original"
    layout, ok = fr.pad_layout(value)
    if not ok or not value.strip():
        ui.info(f"Unknown layout {value!r}; use original or modern.")
        return 2
    if not try_write_ini(root, "controls", "layout", layout, ui, shown):
        return 1
    note(root, f"controls: {layout}")
    ui.info(f"Controls: {layout.capitalize()}. It applies the next time the game starts.")
    return 0


def set_prompts(root, value, ini, ui, shown=None):
    """The launcher's Button prompts choice -> [controls] prompts in kz2-install.ini. No value: the next set in the
    cycle Auto, PS3, PS4/PS5, Xbox, Keyboard (the launcher has message boxes only, no list)."""
    if value == "ask":
        cur = fr.PROMPT_SETS.index(ini["prompts"])
        value = fr.PROMPT_SETS[(cur + 1) % len(fr.PROMPT_SETS)]
    sel, ok = fr.prompt_set(value)
    if not ok or not value.strip():
        ui.info(f"Unknown button prompts {value!r}; use auto, ps3, ps4, xbox or keyboard.")
        return 2
    if not try_write_ini(root, "controls", "prompts", sel, ui, shown):
        return 1
    note(root, f"button prompts: {sel}")
    ui.info(f"Button prompts: {fr.PROMPT_LABELS[sel]}. It applies the next time the game starts. "
            "Run this again to move to the next set.")
    return 0


def set_display(root, value, ini, ui, shown=None):
    """The launcher's Display choice -> [display] mode in kz2-install.ini. No value: the next mode in the cycle
    Windowed, Borderless, Fullscreen (the launcher has message boxes only, no list)."""
    if value == "ask":
        cur = fr.DISPLAY_MODES.index(ini["display"])
        value = fr.DISPLAY_MODES[(cur + 1) % len(fr.DISPLAY_MODES)]
    sel, ok = fr.display_mode(value)
    if not ok or not value.strip():
        ui.info(f"Unknown display mode {value!r}; use windowed, borderless or fullscreen.")
        return 2
    if not try_write_ini(root, "display", "mode", sel, ui, shown):
        return 1
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


def stop_reasons(root, since):
    """(step, [reasons]) from firstrun.py's status file when this run wrote it (not older than `since`, a time.time()
    taken before the run), else ("", [])."""
    p = os.path.join(root, FIRSTRUN_STATUS)
    try:
        if os.path.getmtime(p) < since - 2:
            return "", []
        with open(p, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return "", []
    res = next((ln for ln in lines if ln.startswith("RESULT ok=0 ")), "")
    step = dict(x.split("=", 1) for x in res.split()[1:] if "=" in x).get("step", "")
    return step, [ln[len("REASON "):] for ln in lines if ln.startswith("REASON ")]


def failure_text(root, rc, what, since):
    """The dialog after a first-run or rebuild child ended with rc != 0: the reason firstrun.py gave (the same text as
    its log), then where the log is. A failed or quit check says that the next start asks again for what was wrong."""
    step, why = stop_reasons(root, since)
    if step == "quit":
        head = "Your game files did not pass the check, so nothing was built"
    else:
        head = did_not_finish(rc, what)
    if not why:
        return f"{head}. {log_note(root)}"
    body = "\n".join(f"- {r}" for r in why)
    again = ("\n\nFix this, then open Project Pyrrhus again: it checks your game files first and asks again only for "
             "the ones that are wrong." if step in ("check", "quit") else "")
    return f"{head}:\n\n{body}{again}\n\n{log_note(root)}"


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
    shown = set()       # an ini problem is shown once per start
    if ini["error"] and not a.print:
        ini_trouble(root, ui, ini["error"], shown)
    if a.controls:
        return set_controls(root, a.controls, ini, ui, shown)
    if a.prompts:
        return set_prompts(root, a.prompts, ini, ui, shown)
    if a.display:
        return set_display(root, a.display, ini, ui, shown)
    if not a.print:
        fr.relocate_saved(root)     # a moved or renamed install folder: saved paths inside it follow (never the old folder)
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
        note(root, f"kz2-install.ini [display] mode = {ini['display_bad']!r} is unknown; using borderless")
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
            try_write_ini(root, "online", "dismissed", nv[0], ui, shown)
    if check_due(ini, today):
        os.makedirs(logs, exist_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        start([sys.executable, os.path.join(HERE, "version_check.py"), "--current", fr.port_version(root),
               "--timeout", "8", "--result-file", os.path.join(logs, "version-check.txt"),
               "--log", os.path.join(logs, "version-check.log")], creationflags=flags)
        try_write_ini(root, "online", "last_check", today.isoformat(), ui, shown)

    if a.repair:
        return repair(root, action, reason, paths, ini, ui, run)

    if action != "run":
        # The game needs a folder link in <root>/vfs; check the drive can hold one now, not after a long build.
        try:
            perr = "" if fr.cache_root_supported(root) else \
                probe_link(root, alt_vfs_root(environ, root), dump=paths.get("dump") or setup_paths(root).get("dump", ""))
        except OSError as e:
            perr = f"Could not write in {vfs_root(root)} ({e})."
        if perr:
            note(root, f"vfs: link check: {perr}")
            ui.info(f"{perr}{REPORT}")
            return 1
        if not ui.ask(f"{reason}.\n\n{QUESTION[action]}"):
            return 0
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        since = time.time()
        rc = run(firstrun_cmd(root, action, paths, ini["portable"], console_python()), creationflags=flags)
        if rc != 0:
            ui.info(failure_text(root, rc, "The build did not finish", since))
            return rc
        ini = read_ini(root)   # --interactive may have written portable/check_updates
        action, reason = decide(root)
        paths = load_json(os.path.join(root, "build", "paths.json")) or {}
        if action != "run":
            ui.info(f"{reason}. {log_note(root)}")
            return 1

    gargv, cwd, env, added = game_env(root, paths, ini["portable"], environ, layout=ini["layout"], prompts=ini["prompts"],
                                            display=ini["display"] if ini["display_set"] else None)
    up = update_problem(paths)
    if up:
        note(root, f"update: {up}")
        ui.info(f"{up}.{REPORT}")
        return 1
    try:
        if link_free(root):
            err = drop_link(root)
            note(root, f"vfs: {err or 'no link (game folder read in place, writes under ' + vfs_root(root) + ')'}")
        else:
            v, err = ensure_vfs(root, paths["dump"], alt_vfs_root(environ, root))
            note(root, f"vfs: {err or 'ok (' + v + ')'}")
            if not err and v != vfs_root(root) and ini["vfs_alt"] != v:
                # the uninstaller removes this folder by its record too (kz2.iss RemoveVfsFolders)
                try_write_ini(root, "vfs", "alt", v, ui, shown)
            env["PS3_VFS_ROOT"] = added["PS3_VFS_ROOT"] = v
        if err:
            ui.info(f"{err}{REPORT}")
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
    info = version_info(root, ini["check_updates"])
    verr = write_version_ini(cwd, info)
    note(root, "version.ini: " + (verr or ", ".join(f"{k} {v}" for k, v in info)))
    rc = run(gargv + extra, cwd=cwd, env=env)
    if crashed(rc):
        # The runtime prints its [CRASH] lines to the session log and shows nothing (VM kit pre-flight: no D3D12
        # device = an access violation at start, and the window just vanished): say so, and where the log is.
        logs_dir = os.path.join(os.path.dirname(gargv[0]), "logs")
        note(root, f"game: stopped with code 0x{rc & 0xFFFFFFFF:08X}")
        ui.info(f"The game stopped unexpectedly (code 0x{rc & 0xFFFFFFFF:08X}). Its log is the newest file in "
                f"{logs_dir}.{REPORT}")
    return rc


def update_problem(paths):
    """-> "" when the recorded 1.29 update folder still holds what the game reads from it, else the message (issue
    #16: a 1.29 build run without the update's data stops at the main menu with exit code 1 and no message: a
    test run without the update data reproduced the reported NULL call from 0x003F2984). The same files as firstrun_check U2/U3."""
    upd = paths.get("update") or ""
    if not upd:
        return ""
    u = os.path.join(upd, "USRDIR")
    gone = [n for n, isdir in (("EBOOT.BIN", False), (fc.UPDATE_DATA, False), (fc.UPDATE_PATCH_DIR, True))
            if not (os.path.isdir if isdir else os.path.isfile)(os.path.join(u, n))]
    if not gone:
        return ""
    return (f"The 1.29 update folder {upd} no longer holds USRDIR\\" + ", USRDIR\\".join(gone) + ". The game reads "
            "the update's data from there and stops at the main menu without it. Put the update back in that folder, "
            "or run the setup again and choose the update folder (the one that holds PARAM.SFO and USRDIR)")


def crashed(rc):
    """A Windows exception code as the exit code (0xC0000005 access violation, 0xC0000409 and the like): the game
    did not end by itself. Normal ends (0) and the game's own error exits (small numbers, with their own box) are not."""
    return rc is not None and (rc & 0xFFFFFFFF) >= 0xC0000000


def guarded_main(argv=None):
    """main() for pythonw: an unexpected error is logged with its traceback and shown, never a silent end."""
    try:
        return main(argv)
    except SystemExit:
        raise
    except Exception as e:     # noqa: BLE001 (the last line of defence; the details go to launcher.log)
        import traceback
        ap = argparse.ArgumentParser(add_help=False)
        ap.add_argument("--root", default=os.path.dirname(os.path.dirname(HERE)))
        root = os.path.abspath(ap.parse_known_args(argv)[0].root)
        note(root, "error: " + " | ".join(traceback.format_exc().strip().splitlines()[-6:]))
        UI().info(f"Project Pyrrhus stopped on an unexpected error: {type(e).__name__}: {e}\n\nThe details are in "
                  f"{os.path.join(root, 'logs', 'launcher.log')}.{REPORT}")
        return 1


if __name__ == "__main__":
    sys.exit(guarded_main())
