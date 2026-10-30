#!/usr/bin/env python3
"""Use my RPCS3 install: fill the disc dump, the 1.29 update and the decrypted EBOOT from the player's RPCS3 folder,
and (optional, asked separately) copy their RPCS3 save. Called by firstrun.py --interactive (portable zip, first run)
and by installer/kz2.iss (the wizard runs the command line below; the Inno page holds no logic of its own).

Built on rpcs3_locate.py (the shared RPCS3 helper, vendored unchanged; its fixes are made upstream of this copy). Rules:
  - everything is read in place; the only write is the save copy into our own save folder, only on a yes;
  - the module never opens *.rap, act.dat, exdata/ or RPCS3's cache/ (rpcs3_locate's read funnel);
  - nothing outside the folder the player chose is read before they say yes (disc or dev_hdd0 that RPCS3's own
    settings put elsewhere are listed and asked about first);
  - no keys, no decryption: a missing EBOOT.elf gets a plain notice that the port needs the player's own decrypted one;
  - validity is firstrun_check's job (hashes in eboot_sha256.json), never ours;
  - log text goes through redact(): <RPCS3>/..., <home>/...; save contents never reach a log (counts only).

Command line (the wizard; results are `key=value` lines in --out, UTF-8 with BOM so Inno reads them):
  --detect [--rpcs3 DIR]                     root=, source= (first RPCS3 folder found; hint first)
  --resolve --rpcs3 DIR [--allow-outside]    status=ok|problems|approval|not_found, dump=, update=, eboot=,
                                             outside= (one per line), problem=code|text, help=text, saves=N
  --eboot-kind PATH [--sha256]               status=encrypted|ok, help= (the wizard's manual EBOOT page; no RPCS3 folder);
                                             --sha256 adds size= and sha256= for a file that is not encrypted
  Any unexpected error writes status=error (the wizard polls for --out instead of waiting for the process, issue #22).
  --save-dryrun --rpcs3 DIR --data-dir D     line= text for the question, exists=0|1, status=
  --save-copy --rpcs3 DIR --data-dir D [--overwrite]   status=copied|exists|failed, line=
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rpcs3_locate as loc  # noqa: E402  (the shared RPCS3 helper, vendored unchanged)

TITLE = "BCUS98116"
WANT_UPDATE = "01.29"
WANTS = {TITLE: WANT_UPDATE}
SAVE_USER = "00000001"   # cellSaveData's user folder (ps3recomp cellSaveData.c: gamedata/dev_hdd0/home/00000001/savedata)

# ---- user-facing texts (public prose: gated by the maintainer)
HELP_DECRYPT = ("No decrypted EBOOT.elf was found in the update's USRDIR folder. The port cannot decrypt it. It needs "
                "a decrypted EBOOT.elf, made from your own copy, in that folder. This project ships no decryption "
                "tools or instructions.")
HELP_ENCRYPTED = ("This EBOOT is still encrypted. The port cannot decrypt it. It needs a decrypted EBOOT.elf, made "
                  "from your own copy, in the same folder.")
# RPCS3 steps are named, never spelt out as menu paths: "install the update in RPCS3 (see its documentation)",
# "add the game in RPCS3 (see its documentation)".
HELP_UPDATE = ("RPCS3 has no Killzone 2 update 1.29 installed. Install the update in RPCS3 (see its documentation) "
               "from the 1.29 package, then check again.")
HELP_VERSION = ("The update RPCS3 has for Killzone 2 is not 1.29. Install the update in RPCS3 (see its "
                "documentation) from the 1.29 package, then check again.")
HELP_DISC = ("RPCS3 does not list the Killzone 2 disc (BCUS98116), or its folder is gone. Add the game in RPCS3 (see "
             "its documentation) from the disc dump, or pick the folders yourself.")
HELP_DISC_LAYOUT = ("RPCS3 lists Killzone 2, but not as a disc dump (no PS3_GAME folder). The port needs the disc "
                    "dump; pick the folders yourself.")
HELP_BY_CODE = {"no_decrypted_eboot": HELP_DECRYPT, "missing_update": HELP_UPDATE, "wrong_version": HELP_VERSION,
                "missing_disc": HELP_DISC, "encrypted_eboot": HELP_ENCRYPTED, "not_disc_layout": HELP_DISC_LAYOUT}


BREAK = "\x1f"   # line-break marker in problem= text; kz2.iss turns it into CR LF (the wizard's box clips long words)


def soft_wrap(text, width=38):
    """Break words longer than width after a path separator (BREAK marks each break); other text is unchanged."""
    out = []
    for word in re.split(r"(\s+)", text):
        while len(word) > width and not word.isspace():
            cut = max(word.rfind("/", 0, width), word.rfind("\\", 0, width))
            cut = cut + 1 if cut > 0 else width
            out.append(word[:cut] + BREAK)
            word = word[cut:]
        out.append(word)
    return "".join(out)


def _nc(p):
    return os.path.normcase(os.path.abspath(p))


def _inside(path, base):
    p, b = _nc(path), _nc(base)
    return p == b or p.startswith(b.rstrip(os.sep) + os.sep)


def detect(hint=None):
    """RPCS3 folders worth offering: the hint first, then the known places. Only folders that look like RPCS3."""
    return [c for c in loc.find_rpcs3(hint or None) if c.get("root") and not c.get("code")]


def pick_candidate(root):
    """The candidate for the folder the player chose (or None)."""
    for c in loc.find_rpcs3(root):
        if c.get("source") == "hint" and c.get("root"):
            return c
    return None


def encrypted_eboot(path):
    """True when the file is an encrypted SELF (rpcs3_locate.eboot_kind reads 4 bytes): tell the player the port needs a decrypted one."""
    return bool(path) and loc.eboot_kind(path).get("kind") == "self"


def outside_paths(cand):
    """Folders RPCS3's own settings put outside the chosen folder (the disc, dev_hdd0). Reads only games.yml (which
    lives in the chosen folder); the disc's own files are not opened until the player has said yes."""
    out = []
    disc = ""
    try:
        with open(os.path.join(cand["config_dir"], "games.yml"), encoding="utf-8", errors="replace") as f:
            disc = loc.parse_kv(f.read()).get(TITLE, "")
    except OSError:
        pass
    disc = disc.replace("$(EmulatorDir)", cand["root"].rstrip("/\\") + os.sep).rstrip("/\\")
    if disc and not _inside(disc, cand["root"]):
        out.append(os.path.normpath(disc))
    if not _inside(cand["dev_hdd0"], cand["root"]):
        out.append(cand["dev_hdd0"])
    return out


def resolve(root, allow_outside=False):
    """-> {ok, status, root, dump, update, eboot, outside, problems:[{code,text}], help:[text], saves:{...}}.

    status: ok | problems | approval (paths outside the chosen folder need a yes first; nothing more was read)
    | not_found. The paths are only what the player's own RPCS3 has; firstrun_check decides whether they are valid."""
    res = {"ok": False, "status": "not_found", "root": root, "dump": "", "update": "", "eboot": "", "outside": [],
           "problems": [], "help": [], "saves": {}}
    cand = pick_candidate(root)
    if cand is None:
        res["problems"].append({"code": "not_rpcs3", "text": f"{loc.redact(root)} is not an RPCS3 folder "
                                "(no rpcs3.exe, vfs.yml or games.yml)"})
        return res
    res["root"] = cand["root"]
    res["outside"] = outside_paths(cand)
    if res["outside"] and not allow_outside:
        res["status"] = "approval"
        return res
    r = loc.locate(cand["root"], WANTS)
    if not r.get("ok"):
        res["problems"] += r.get("problems", [])
        return res
    t = r["titles"][TITLE]
    probs = list(t["problems"])
    disc, upd = t["disc"], t["update"] or {}
    bad_upd = ""
    if disc.get("ok"):
        if disc.get("has_ps3_game"):
            res["dump"] = disc["disc_dir"]
        else:
            probs.append({"code": "not_disc_layout", "text": f"{loc.redact(disc['disc_dir'], [cand])} has no PS3_GAME"})
    if upd.get("ok"):
        res["update"] = upd["path"]
    elif upd.get("code") == "wrong_version":
        bad_upd = upd.get("path", "")
    eb = t["decrypted_eboot"]
    if res["update"]:   # only an EBOOT.elf from the 1.29 update folder fits the 1.29 build
        for f in eb.get("found", []):
            if _inside(f["path"], res["update"]):
                res["eboot"] = f["path"]
                break
        if not res["eboot"] and not any(p["code"] == "no_decrypted_eboot" for p in probs):
            probs.append({"code": "no_decrypted_eboot", "text": "no EBOOT.elf in the update's USRDIR"})
        if not res["eboot"] and encrypted_eboot(os.path.join(res["update"], "USRDIR", "EBOOT.elf")):
            probs.append({"code": "encrypted_eboot", "text": "USRDIR/EBOOT.elf is still encrypted"})
    else:
        probs = [p for p in probs if p["code"] != "no_decrypted_eboot"]
    if bad_upd:
        res["eboot"] = ""
    res["problems"] = probs
    res["help"] = [HELP_BY_CODE[c] for c in dict.fromkeys(p["code"] for p in probs) if c in HELP_BY_CODE]
    res["saves"] = t["saves"]
    res["ok"] = bool(res["dump"] and res["update"] and res["eboot"]) and not probs
    res["status"] = "ok" if res["ok"] else "problems"
    return res


def log_lines(res):
    """Install-log lines for a resolve() result: RPCS3 paths as <RPCS3>/..., home as <home>/... (rpcs3_locate.redact)."""
    roots = [res["root"]]

    def r(p):
        return loc.redact(p, roots) if p else "-"
    lines = [f"# rpcs3 import: root={r(res['root'])} status={res['status']}"]
    for k in ("dump", "update", "eboot"):
        lines.append(f"# rpcs3 import: {k}={r(res[k])}")
    for p in res["outside"]:
        lines.append(f"# rpcs3 import: outside the chosen folder: {r(p)}")
    for p in res["problems"]:
        lines.append(f"# rpcs3 import: problem {p['code']}")
    return lines


# ------------------------------------------------------------------------------------------------ saves
def pick_saves(res):
    """The saves of one RPCS3 user (user 00000001 if there, else the first): [{name, path, user}]."""
    users = (res.get("saves") or {}).get("users") or {}
    if not users:
        return []
    uid = SAVE_USER if SAVE_USER in users else sorted(users)[0]
    return [{"name": e["name"], "path": e["path"], "user": uid} for e in users[uid]]


def save_dst(data_dir, name):
    """Where the port's cellSaveData looks: <data>/gamedata/dev_hdd0/home/00000001/savedata/<name>."""
    return os.path.join(data_dir, "gamedata", "dev_hdd0", "home", SAVE_USER, "savedata", name)


def human(n):
    for u in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n} {u}" if u == "bytes" else f"{n:.1f} {u}"
        n /= 1024


def save_dryrun(res, data_dir):
    """Dry run of the copy for every save found -> [{name, src, dst, files, size, replaces, stale, exists, error}].
    Nothing is written. overwrite=True only widens the dry run so existing destinations report replaces/stale."""
    out = []
    for s in pick_saves(res):
        dst = save_dst(data_dir, s["name"])
        d = loc.copy_save(s["path"], dst, overwrite=True, dry_run=True)
        e = {"name": s["name"], "src": s["path"], "dst": dst, "exists": os.path.isdir(dst), "error": ""}
        if d.get("ok"):
            e.update(files=len(d["files"]), size=sum(f["size"] for f in d["files"]), replaces=len(d["replaces"]),
                     stale=len(d["stale"]))
        else:
            e.update(files=0, size=0, replaces=0, stale=0, error=d.get("code", "error"))
        out.append(e)
    return out


def dryrun_text(plan):
    """The dry run as plain lines for the question (counts only: no file names, no contents)."""
    lines = []
    for e in plan:
        if e["error"]:
            lines.append(f"  {e['name']}: cannot import ({e['error']})")
            continue
        s = f"  {e['name']}: {e['files']} files, {human(e['size'])}"
        if e["exists"]:
            s += (f"; you already have this save: {e['replaces']} of its files would be replaced"
                  f", {e['stale']} files only in yours would stay")
        lines.append(s)
    return lines


def save_copy(plan, overwrite=False):
    """Copy every non-error entry of the plan. An existing destination is refused unless overwrite=True (the caller
    got a second explicit yes). -> [{name, status: copied|exists|failed, copied}]; never raises, never logs contents."""
    out = []
    for e in plan:
        if e["error"]:
            out.append({"name": e["name"], "status": "failed", "copied": 0})
            continue
        r = loc.copy_save(e["src"], e["dst"], overwrite=overwrite, dry_run=False)
        if r.get("ok"):
            out.append({"name": e["name"], "status": "copied", "copied": r["copied"]})
        else:
            out.append({"name": e["name"], "status": "exists" if r.get("code") == "exists" else "failed", "copied": 0})
    return out


def save_log_line(results):
    """One redaction-free log line: counts only."""
    return "# rpcs3 save import: " + ", ".join(
        f"{i + 1}: {r['status']} ({r['copied']} files)" for i, r in enumerate(results)) if results else \
        "# rpcs3 save import: nothing to import"


# ------------------------------------------------------------------------------------------------ command line
def _write(path, pairs):
    """The result file, whole or not at all: written beside it and renamed over it as the last act, because the
    wizard no longer waits for this process to end (issue #22) but polls for the file and reads it once it is there."""
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8-sig", newline="\r\n") as f:
        for k, v in pairs:
            f.write(f"{k}={str(v).replace(chr(13), ' ').replace(chr(10), ' ')}\n")
    os.replace(tmp, path)


def _out_arg(argv):
    """The --out value from a raw argument list ('' when absent), for the error result."""
    for i, x in enumerate(argv):
        if x == "--out" and i + 1 < len(argv):
            return argv[i + 1]
        if x.startswith("--out="):
            return x[6:]
    return ""


def main(argv=None):
    """_main, but an unexpected error still leaves a result (status=error) for the wizard, which waits for the file
    with a time limit rather than for this process (issue #22): it says "did not run" at once instead of at the limit."""
    try:
        return _main(argv)
    except Exception as e:  # noqa: BLE001  (the traceback still goes to stderr)
        out = _out_arg(sys.argv[1:] if argv is None else list(argv))
        if out:
            try:
                _write(out, [("status", "error"), ("error", type(e).__name__)])
            except OSError:
                pass
        import traceback
        traceback.print_exc()
        return 3


def _main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    for n in ("detect", "resolve", "save-dryrun", "save-copy"):
        g.add_argument("--" + n, action="store_true")
    g.add_argument("--eboot-kind", metavar="PATH")
    ap.add_argument("--sha256", action="store_true",
                    help="with --eboot-kind: also size= and sha256= of a decrypted EBOOT (the wizard asks only when "
                         "the size is a known EBOOT's; one read, off the wizard's window thread)")
    ap.add_argument("--rpcs3", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-outside", action="store_true")
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(argv)
    pairs = []
    if a.eboot_kind is not None:   # the wizard's manual EBOOT page (same test as the text UI)
        enc = encrypted_eboot(a.eboot_kind)
        pairs = [("status", "encrypted" if enc else "ok")] + ([("help", HELP_ENCRYPTED)] if enc else [])
        if a.sha256 and not enc:
            h = loc.sha256(a.eboot_kind)
            if h.get("ok"):
                pairs += [("size", h["size"]), ("sha256", h["sha256"])]
        _write(a.out, pairs)
        return 1 if enc else 0
    if a.detect:
        c = detect(a.rpcs3)
        if c:
            pairs += [("status", "ok"), ("root", c[0]["root"]), ("source", c[0]["source"])]
        else:
            pairs.append(("status", "not_found"))
        _write(a.out, pairs)
        return 0 if c else 1
    res = resolve(a.rpcs3, a.allow_outside)
    if a.resolve:
        pairs = [("status", res["status"])] + [(k, res[k]) for k in ("dump", "update", "eboot")]
        pairs += [("outside", p) for p in res["outside"]]
        pairs += [("problem", f"{p['code']}|{soft_wrap(loc.redact(p['text'], [res['root']]))}") for p in res["problems"]]
        pairs += [("help", h) for h in res["help"]]
        pairs.append(("saves", len(pick_saves(res))))
        _write(a.out, pairs)
        return 0 if res["ok"] else 1
    if not a.data_dir or res["status"] not in ("ok", "problems"):
        _write(a.out, [("status", "failed")])
        return 2
    plan = save_dryrun(res, a.data_dir)
    if a.save_dryrun:
        pairs = [("status", "ok" if plan else "none"), ("exists", int(any(e["exists"] for e in plan)))]
        pairs += [("line", t) for t in dryrun_text(plan)]
        _write(a.out, pairs)
        return 0
    results = save_copy(plan, overwrite=a.overwrite)
    pairs = [("status", "copied" if results and all(r["status"] == "copied" for r in results) else
              ("exists" if any(r["status"] == "exists" for r in results) else "failed")),
             ("line", save_log_line(results))]
    _write(a.out, pairs)
    return 0 if pairs[0][1] == "copied" else 1


if __name__ == "__main__":
    sys.exit(main())
