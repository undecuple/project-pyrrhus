#!/usr/bin/env python3
"""Host test for installer/recomplauncher.json, the file RecompLauncher reads at the top of the release folder (no game
data, no work/, no network). The file is written to RecompLauncher's format 1 (its docs/DEVELOPERS.md and
recomplauncher.schema.json, read as text; nothing of theirs is copied here). Checks:

  shape       "$schema" URL, format 1, repo = the public repo, only the schema's top-level keys and input fields, input ids
              and roles, formats, check keys, Section/Key setting keys
  paths       every {placeholder} is one the launcher fills ({install}, {data}, ... or {input:<declared id>}); an
              optional input only in one "--flag={input:id}" argument (left out whole when not picked); paths stay
              under {install} (the launcher keeps, moves and removes the game as its folder)
  our side    start.program is the payload's launcher (assemble_payload.LAUNCHER); prepare.program is the bundled
              python.exe (toolchain.json's python dest) running the payload's firstrun.py (a RULES destination); every
              prepare flag is one firstrun.py takes, the copy and the update are passed, nothing interactive; done
              names build/kz2.exe and build/build-stamp.json (launch.decide's "built"); the config file is
              install_ini.NAME; portable=1 for new files and check_updates=0 on every start (no self-update under the
              launcher); exit_codes only kz2.exe's fixed codes (main.cpp TerminateProcess); each setting's values are accepted by firstrun's parsers, cover all of them, and its default
              is the parser's value for a missing key
  packaging   assemble_payload copies it to the payload's top folder, pack_zip requires it, the release workflow packs
              that payload into exactly one zip (so the launcher's pick is the portable zip)
  no game     no dumps, keys, shared inputs, long hex strings, decryption words
  schema      with KZ2_RL_SCHEMA=<a local copy of recomplauncher.schema.json> and the jsonschema module: validated
              (skipped otherwise; the test never downloads)

Exit 0 = PASS.

    python3 tools/release/test_recomplauncher.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import public_layout  # noqa: E402  (README.md and .github/ are in public/ here, at the root once exported)
sys.path.insert(0, HERE)
import assemble_payload as ap  # noqa: E402
import firstrun as fr  # noqa: E402
import install_ini as ii  # noqa: E402
import pack_zip as pz  # noqa: E402

MANIFEST = os.path.join(REPO, "installer", "recomplauncher.json")
SCHEMA_URL = "https://recomplauncher.com/schema/recomplauncher.json"
PUBLIC_REPO = "undecuple/project-pyrrhus"
TOP_KEYS = {"inputs", "$schema", "format", "name", "repo", "game", "start", "prepare", "config", "folders", "exit_codes",
            "settings", "groups", "saves", "games", "looks", "mods", "actions", "system"}
INPUT_KEYS = {"id", "label", "role", "optional", "shared", "destination", "formats", "check", "dumps", "contains",
              "into", "name", "extract", "sha256"}
ROLES = {"game", "disc", "dlc", "update", "key", "runtime"}
CHECK_KEYS = {"file", "xdvdfs", "iso9660", "nup_build_id", "ids"}
FILLED = {"install", "data", "documents", "local", "config", "home", "pad", "value"}
TITLE_IDS = {"BCUS98116", "BCES00081", "BCAS20066", "BCJS30032"}   # firstrun_check REGIONS (GETTING-FILES "Regions")

fails = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


with open(MANIFEST, encoding="utf-8") as f:
    raw = f.read()
m = json.loads(raw)

# ---- shape
check(m.get("$schema") == SCHEMA_URL and m.get("format") == 1, "$schema URL and format 1")
check(m.get("repo") == PUBLIC_REPO and PUBLIC_REPO in read(public_layout.public_path(REPO, "README.md")), "repo is the public repo")
check(set(m) <= TOP_KEYS and "game" not in m, f"top-level keys known, no deprecated 'game' ({sorted(set(m) - TOP_KEYS)})")
inputs = m.get("inputs", [])
ids = [i.get("id") for i in inputs]
check(len(ids) == len(set(ids)) and all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", i or "") for i in ids), "input ids unique")
check([i.get("role", "game") for i in inputs].count("game") == 1 and inputs[0]["id"] == "game", "one game input, first")
for i in inputs:
    check(set(i) <= INPUT_KEYS and i.get("role", "game") in ROLES and i.get("label"), f"input {i['id']}: fields, role, label")
    fm = i.get("formats", [])
    check(fm and all(x.get("type") in ("file", "folder") and (x["type"] == "file" or "extensions" not in x) for x in fm),
          f"input {i['id']}: formats (extensions only on files)")
    c = i.get("check", {})
    check(set(c) <= CHECK_KEYS, f"input {i['id']}: check keys")
    if "ids" in c:
        check(set(c["ids"]) == TITLE_IDS, f"input {i['id']}: ids are the four accepted discs' title ids")
game = inputs[0]
check({x["type"] for x in game["formats"]} == {"file", "folder"} and
      any(x.get("extensions") == ["iso"] for x in game["formats"]), "game: a dump folder or a decrypted .iso (firstrun --dump)")
for s in m.get("settings", []):
    keys = set()
    for ch in s.get("choices", []):
        keys |= set(ch.get("set", {}))
    keys |= set(s.get("defaults", {}))
    check(all(re.fullmatch(r"[a-z]+/[a-z_]+", k) for k in keys), f"setting {s['id']}: Section/Key keys")

# ---- paths
declared = set(ids)
optional = {i["id"] for i in inputs if i.get("optional")}
bad = set()
for s in strings(m):
    if s == m["$schema"]:
        continue
    for ph in re.findall(r"\{([^{}]*)\}", s):
        if not (ph in FILLED or (ph.startswith("input:") and ph[6:] in declared)):
            bad.add(ph)
# a "<...>" or "{...}" in a label is text for the player, not a placeholder: labels never carry braces
check(not bad, f"placeholders are ones the launcher fills ({sorted(bad)})")
check(all("{" not in i["label"] for i in inputs), "labels carry no placeholders")
args = m.get("prepare", {}).get("args", []) + m.get("start", {}).get("args", [])
for o in optional:
    uses = [a for a in args if "{input:%s}" % o in a]
    check(uses and all(re.fullmatch(r"--[a-z-]+=\{input:%s\}" % o, a) for a in uses),
          f"optional input {o}: one --flag={{input:{o}}} argument")
paths = list(m.get("saves", [])) + list(m["prepare"].get("done", []))
paths += [p["path"] for c in m.get("config", []) for p in c["file"]]
paths += [p["path"] for v in m.get("folders", {}).values() for p in v]
check(all(p.startswith(("{install}/", "{data}/")) for p in paths), "every path is under {install} or {data}")

# ---- our side
check(m["start"]["program"] == [ap.LAUNCHER] and not m["start"].get("args"),
      "start: the launcher exe (it sets the game's folders and environment), no extra args")
dests = {d for _, d, _, _ in ap.RULES}
tc = json.loads(read("tools/release/toolchain.json"))
py_dest = next(e["dest"] for e in tc["components"] if e.get("name") == "python")
check(m["prepare"]["program"] == [f"toolchain/{py_dest}/python.exe"], "prepare: the bundled python.exe (console, no pythonw)")
pa = m["prepare"]["args"]
check(pa[0] == "{install}/kz2-setup/release/firstrun.py" and "kz2-setup/release/firstrun.py" in dests,
      "prepare: the payload's firstrun.py")
flags = set(re.findall(r'add_argument\("(--[a-z-]+)"', read("tools/release/firstrun.py")))
used = {a.split("=")[0] for a in pa[1:]}
check(used <= flags, f"prepare flags are firstrun.py's ({sorted(used - flags)})")
# --portable acts only with --interactive (firstrun.py's usage); portable saves come from config new install/portable=1
check({"--root", "--dump", "--update"} <= used and not used & {"--interactive", "--bar", "--check-first", "--portable"},
      "prepare: root, copy and update passed; nothing that asks, draws a bar or is ignored without --interactive")
fr_src = open(os.path.join(HERE, "firstrun.py"), encoding="utf-8").read()
check("--portable   with --interactive" in fr_src, "firstrun.py still documents --portable as --interactive only")
check("--root={install}" in pa and "--dump={input:game}" in pa and "--update={input:update}" in pa,
      "prepare: --root/--dump/--update carry {install}, the copy and the update")
launch_src = read("tools/release/launch.py")
check(m["prepare"]["done"] == ["{install}/build/kz2.exe", "{install}/build/build-stamp.json"] and
      '"build-stamp.json"' in launch_src and '"kz2.exe"' in launch_src, "done: build/kz2.exe and build/build-stamp.json")
check(not m["prepare"].get("keeps_copy"), "no keeps_copy: the game reads the dump and the update while it runs")
cfg = m["config"]
check(len(cfg) == 1 and cfg[0]["format"] == "ini" and cfg[0]["file"] == [{"path": "{install}/" + ii.NAME}],
      f"config: {ii.NAME} in the install folder, as INI")
check(cfg[0].get("new") == {"install/portable": "1"}, "config new: portable=1 (saves and settings stay in the folder)")
check(cfg[0].get("always") == {"online/check_updates": "0"}, "config always: check_updates=0 (no self-update)")
parsers = {"display/mode": (fr.display_mode, fr.DISPLAY_MODES), "controls/layout": (fr.pad_layout, fr.PAD_LAYOUTS),
           "controls/prompts": (fr.prompt_set, fr.PROMPT_SETS)}
seen = set()
for s in m["settings"]:
    for key, (parse, allv) in parsers.items():
        vals = [ch["set"][key] for ch in s["choices"] if key in ch.get("set", {})]
        if not vals:
            continue
        seen.add(key)
        check(all(parse(v) == (v, True) for v in vals) and sorted(vals) == sorted(allv),
              f"setting {s['id']}: every value of {key} once, each accepted as is")
        check(s["defaults"].get(key) == parse("")[0], f"setting {s['id']}: default = the value for a missing key")
check(seen == set(parsers), "settings: display, pad layout and prompts")
sv = m.get("saves", [])
check("{install}/gamedata" in sv and "./gamedata" in launch_src, "saves: the game's gamedata folder (portable cwd)")
check(m["folders"]["logs"] == [{"path": "{install}/build/logs"}] and "build\\\\logs" in launch_src,
      "folders.logs: build/logs, where the game writes its .log")

ec = m.get("exit_codes", {})
main_src = read("port/kz2/main.cpp")
ended = set(re.findall(r"TerminateProcess\(GetCurrentProcess\(\), (\d+)\)", main_src))
check(ec.get("0") == "ok" and set(ec) <= ended and "1" not in ec,
      f"exit_codes: only kz2.exe's fixed TerminateProcess codes ({sorted(ended)}), 0 = ok, never the shared 1")
check('return rc' in launch_src, "launch.py returns the game's exit code (the launcher exe passes it on)")

class _Sink:
    def __init__(self):
        self.text = ""

    def write(self, s):
        self.text += s

    def flush(self):
        pass


def _progress_lines(env_value):
    old = os.environ.get("RECOMPLAUNCHER")
    if env_value is None:
        os.environ.pop("RECOMPLAUNCHER", None)
    else:
        os.environ["RECOMPLAUNCHER"] = env_value
    try:
        steps = [fr.Step("a", "Checking your files", 1.0, lambda c: []), fr.Step("b", "Compiling", 3.0, lambda c: [])]
        sink = _Sink()
        r = fr.Runner(fr.Ctx(root="/nonexistent", build="/nonexistent/build"), steps, None, sink, None)
        r.progress(1, 50, 100)
        return sink.text.splitlines()
    finally:
        if old is None:
            os.environ.pop("RECOMPLAUNCHER", None)
        else:
            os.environ["RECOMPLAUNCHER"] = old


on, off = _progress_lines("1"), _progress_lines(None)
check(len(on) == 2 and on[0].startswith("PROGRESS ") and re.fullmatch(r"progress 0\.\d{3} Compiling", on[1])
      and abs(float(on[1].split()[1]) - 0.625) < 0.001, f"RECOMPLAUNCHER=1: a 'progress F label' line after PROGRESS ({on})")
check(len(off) == 1 and off[0].startswith("PROGRESS "), f"without it: only the PROGRESS line ({off})")

# ---- packaging
check(("installer/recomplauncher.json", "recomplauncher.json", "file", {}) in ap.RULES, "payload: copied to the top folder")
check("recomplauncher.json" in pz.REQUIRED, "pack_zip: a zip without it is refused")
check("recomplauncher.json" not in ap.ZIP_ONLY, "installed copies keep it too (manifest check stays whole)")
wf = read(public_layout.public_path(REPO, ".github/workflows/release.yml"))
zips = {re.sub(r"\$\{?VERSION\}?|\*|<version>", "V", z) for z in re.findall(r"Project-Pyrrhus-[^ \"'/]*\.zip(?!\.)", wf)}
check(zips == {"Project-Pyrrhus-V-Windows-x64.zip"} and "pack_zip.py" in wf,
      f"release.yml publishes one zip, packed by pack_zip.py ({sorted(zips)})")

# ---- no game files, keys or decryption
check("dumps" not in raw and "sha256" not in raw and not any(i.get("shared") or i.get("role") == "key" for i in inputs),
      "no dump values, hashes, keys or shared inputs")
check(not re.search(r"[0-9a-fA-F]{24,}", raw), "no long hex strings")
check(not re.search(r"decrypt (it|your|the)|klic|\.rap\b|rif\b|idps|act\.dat", raw, re.I), "no decryption steps or key files")

# ---- schema (optional, local copy only)
sp = os.environ.get("KZ2_RL_SCHEMA", "")
if sp:
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
        print("skip schema: no jsonschema module")
    if jsonschema:
        with open(sp, encoding="utf-8") as f:
            errs = sorted(e.message for e in jsonschema.Draft7Validator(json.load(f)).iter_errors(m))
        check(not errs, f"valid against {os.path.basename(sp)} ({errs[:3]})")
else:
    print("skip schema: KZ2_RL_SCHEMA not set")

print("PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
