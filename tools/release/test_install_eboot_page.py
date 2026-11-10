#!/usr/bin/env python3
"""Host test (adapted from Project Helghast PR #11, its test_install_eboot_page.py, same author,
MIT): installer/kz2.iss' EBOOT page and failure box. Static checks (no ISCC, no game data):
- the EBOOT page asks the helper (rpcs3_import --eboot-kind --identify) for the first-run check's own E1/H1 verdict
  on the picked file (shared EBOOT id table): a FAIL refuses with its text, a WARN asks whether
  to use the file; the helper's verdict equals firstrun_check.check_eboot_elf's for every outcome (tested, untested,
  unsupported, unknown status, wrong region, another app_ver, segments only, unknown or modified; an encrypted SELF
  gets the encrypted answer); the vcheck folder holds every module the helper imports and the table;
- without the helper's verdict, the page tests the file's version from firstrun_check's own table
  (eboot_sha256.json, shipped as a dontcopy file; no size or hash written into the script) and refuses a known EBOOT
  of another version (the disc's 1.01 one) with E1's text, no path and no how-to; an unknown EBOOT passes;
- a silent install with /EBOOT= stops on the same test, with the same text (PrepareToInstall: exit code 7);
- the build's failure box shows firstrun.py's REASON lines before the log path, and a check-step failure says the
  next start asks again;
- the table parser (EbootVersionOf + JsonNumber + JsonString), transcribed to Python, reads the shipped table (the
  shared per-build list) the way firstrun_check.EBOOT_ELF_SIZES does, and an old-form table
  ("1.29": {size, sha256}) as well, with negative controls (unknown size -> no version).

    python3 tools/release/test_install_eboot_page.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ISS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "installer", "kz2.iss")
if not os.path.isfile(ISS):
    print("SKIP: installer/kz2.iss not in this tree")
    sys.exit(0)
import firstrun as fr  # noqa: E402
import firstrun_check as fc  # noqa: E402

t = open(ISS, encoding="utf-8").read()
code = t[t.find("[Code]"):]
bad = 0


def check(ok, msg):
    global bad
    bad += not ok
    print(("ok   " if ok else "FAIL ") + msg)


def func(name):
    m = re.search(r"(?:function|procedure) " + name + r"\b.*?\nend;", code, re.S)
    return m.group(0) if m else ""


table = json.load(open(fc.HASHES_FILE, encoding="utf-8"))
known = fc.load_eboot_table(fc.HASHES_FILE)        # the per-build list, keyed by version ('1.29')
# 0. the shipped table's entries: the disc's 1.01 EBOOT and the 1.29 update's, each with a size and a SHA-256
check(set(known) == {"1.01", "1.29"} and all(v.get("size") and len(v.get("sha256", "")) == 64 for v in known.values()),
      f"eboot_sha256.json holds 1.01 and 1.29 with size and SHA-256: {sorted(known)}")
# 1. the table is reused, not copied
check(re.search(r'Source: "\{#Payload\}\\kz2-setup\\release\\eboot_sha256\.json"; Flags: dontcopy', t) is not None,
      "eboot_sha256.json ships as a dontcopy file for the wizard")
check("ExtractTemporaryFile('eboot_sha256.json')" in func("EbootTable"), "EbootTable extracts the shipped table")
nums = {str(v["size"]) for v in known.values()} | {v["sha256"] for v in known.values() if v.get("sha256")}
check(not [n for n in nums if n in t], "no known EBOOT size or SHA-256 written into kz2.iss")
check({str(v["size"]): k for k, v in known.items()} == {str(s): v for s, v in fc.EBOOT_ELF_SIZES.items()},
      "table sizes = firstrun_check.EBOOT_ELF_SIZES")
target = fr.EBOOT_VERS[fr.DEFAULT_VER]["check"]
check(f'#define EbootTarget "{target}"' in t, f"the page's EBOOT target is firstrun.py's default tree ({target})")
check('#define DiscEboot "1.01"' in t and "1.01" in known, "the disc's EBOOT version is named from the table's keys")

# 2. the page refuses; the silent install uses the same test
ep = func("EbootProblem")
check(ep.find("EbootVerdictPath") >= 0 and ep.find("EbootVerdictPath") < ep.find("EbootTested")
      and "if EbootVerdictLevel = 'FAIL' then Result := EbootVerdictText;" in ep,
      "EbootProblem: the helper's fresh verdict first (its FAIL text), before the once-per-name cache")
check("V <> '{#EbootTarget}'" in ep and "Result := 'This EBOOT is ' + BuildName(V, '');" in ep and
      "Result := Result + ', the disc''s own version';" in ep and
      "Result := Result + '. This release needs ' + BuildName('{#EbootTarget}', Id) + '.';" in ep,
      "EbootProblem fallback: another known version refused with firstrun_check's E1 text (size-only form)")
check("USRDIR" not in ep.split("begin", 1)[1] and "decrypt" not in ep.split("begin", 1)[1].lower(),
      "EbootProblem: no path, no how-to, no word on decrypting (shared EBOOT id table, an earlier change)")
check("Result := '';" in ep and "if (V <> '') and" in ep, "EbootProblem: an unknown EBOOT passes")
bn = func("BuildName")
names = dict(re.findall(r"Id = '(\w+)' then R := '(\w+)'", bn))
check(names == {t: g["region"] for t, g in fc.REGIONS.items()}, f"BuildName: the region names of REGIONS {names}")
check(fc.build_name("1.29", "BCAS20066") == "Killzone 2 1.29 (BCAS20066, Asia)" and fc.build_name("1.01") ==
      "Killzone 2 1.01" and "'Killzone 2 ' + V + ' (' + Id + ', ' + R + ')'" in bn,
      "BuildName and firstrun_check.build_name give the same text")
ew = func("EbootWarning")
check("EbootVerdictLevel = 'WARN'" in ew and "Result := EbootVerdictText" in ew, "EbootWarning: the helper's WARN text")
nb = func("NextButtonClick")
check("Problem := EbootProblem(EbootPage.Values[0], UpdatePage.Values[0]);" in nb and "MsgBox(Problem, mbError, MB_OK);" in nb,
      "Next on the EBOOT page refuses with the reason")
check("EbootWarning(EbootPage.Values[0]) + #13#10 + #13#10 + 'Use this file anyway?'" in nb and "MB_YESNO" in nb,
      "Next on the EBOOT page: a WARN (untested, wrong region, unknown or modified) asks whether to use the file")
ee = func("EbootEncrypted")
check("' --identify --target {#EbootTarget}'" in ee and "' --title ' + Id" in ee and "KnownDiscId(Id)" in ee
      and "Pos('level=', Lines[I]) = 1" in ee and "Pos('text=', Lines[I]) = 1" in ee,
      "EbootEncrypted asks the helper for the verdict (with the disc's title id) and reads level= and text=")
check(ee.find("EbootVerdictPath := '';") < ee.find("RunHelper("), "the old verdict is cleared before the helper runs")
# the helper runs from {tmp}\vcheck: every module it imports (and theirs) and the table must be there too (since
# D53 rpcs3_import imports firstrun_check, which was missing: the page's helper stopped at its import; an earlier change)
vfiles = set(re.findall(r'Source: "\{#Payload\}\\kz2-setup\\release\\([\w.]+)"; DestDir: "\{tmp\}\\vcheck"', t))
local = {f[:-3] for f in os.listdir(HERE) if f.endswith(".py")}
need, todo = set(), ["rpcs3_import"]
while todo:
    m = todo.pop()
    if m in need:
        continue
    need.add(m)
    src = open(os.path.join(HERE, m + ".py"), encoding="utf-8").read()
    todo += [x for x in re.findall(r"^import (\w+)", src, re.M) if x in local]
check({m + ".py" for m in need} <= vfiles and "eboot_sha256.json" in vfiles,
      f"vcheck holds the helper's module-level imports and the table: need {sorted(need)}, have {sorted(vfiles)}")
pti = func("PrepareToInstall")
check("WizardSilent" in pti and "{param:EBOOT|}" in pti and "EbootProblem(E, " in pti
      and "'Silent install stopped: ' + E + ': '" in pti and "SaveStringToFile(InstallLogPath('')" in pti,
      "a silent install with /EBOOT= stops with the same text, logged next to setup.exe")
check(code.find("function EbootProblem") < code.find("function PrepareToInstall") and
      code.find("function ResolveUpdate") < code.find("function PrepareToInstall"),
      "PrepareToInstall comes after the functions it calls (Pascal Script declares before use)")
eb = t[t.find("EbootPage := CreateInputFilePage"):]
eb = eb[:eb.find("EbootPage.Add(")]
check("1.29 update''s USRDIR" in eb and "Not the disc''s PS3_GAME\\USRDIR\\EBOOT" in eb,
      "page text: the 1.29 update's USRDIR, not the disc's")

# 3. the failure box carries the reason
rb = func("RunBuild")
check("Pos('REASON ', Lines[I]) = 1" in rb and "BuildFailStep := Field(L, 'step');" in rb,
      "RunBuild reads the REASON lines after RESULT")
sb = func("ShowBuildError")
check("Why + 'The log is at:'" in sb and "BuildFailStep = 'check'" in sb and "asks again only for the" in sb,
      "ShowBuildError: reason first, then the log; a check failure says the next start asks again")
check(not [ln for ln in code.splitlines() if re.match(r"\s*#\d", ln)], "no [Code] line starts with a #NN constant")


# 3b. the helper's verdict (rpcs3_import --eboot-kind --identify) is the first-run check's own, for every outcome
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import struct  # noqa: E402
import tempfile  # noqa: E402
import rpcs3_import as ri  # noqa: E402


def mini_elf(path, payload, size=16_455_144):
    """One PT_LOAD of payload after the headers, p_paddr != p_filesz; truncated or padded to size."""
    h = bytearray(64)
    h[:4], h[4], h[5], h[6] = fc.ELF_MAGIC, 2, 2, 1
    h[18:20] = struct.pack(">H", fc.EM_PPC64)
    struct.pack_into(">Q", h, 0x20, 64)
    struct.pack_into(">HH", h, 0x36, 56, 1)
    ph = struct.pack(">IIQQQQQQ", 1, 5, 120, 0x10000, 0x4444, len(payload), len(payload) + 64, 0x10000)
    with open(path, "wb") as f:
        f.write(bytes(h) + ph + payload)
        f.truncate(size)


with tempfile.TemporaryDirectory(prefix="kz2-ebootpage-") as tmp:
    elf = os.path.join(tmp, "EBOOT.elf")
    mini_elf(elf, b"\x5a" * 999)
    sha, seg = fc.file_sha256(elf), fc.segment_sha256(elf)
    tbl = os.path.join(tmp, "t.json")
    cases = {"tested": ({}, "OK"), "untested": ({"status": "untested"}, "WARN"),
             "unsupported": ({"status": "unsupported"}, "FAIL"), "unknown status": ({"status": "new"}, "FAIL"),
             "wrong region": ({"title_id": "BCES00081", "region": "EU"}, "WARN"),
             "another app_ver": ({"app_ver": "01.01"}, "FAIL"),
             "segments only": ({"sha256": "ab" * 32}, "OK"),
             "unknown or modified": ({"sha256": "ab" * 32, "segment_sha256": "cd" * 32}, "WARN")}
    old_file = fc.HASHES_FILE
    for name, (kw, level) in cases.items():
        e = dict({"title_id": "BCUS98116", "region": "US", "app_ver": "01.29", "size": 16_455_144, "sha256": sha,
                  "status": "tested", "segment_sha256": seg}, **kw)
        json.dump({"entries": [e]}, open(tbl, "w", encoding="utf-8"))
        fc.HASHES_FILE = tbl                     # the helper reads the table next to firstrun_check (vcheck)
        try:
            out = os.path.join(tmp, "res.txt")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = ri.main(["--eboot-kind", elf, "--identify", "--target", "1.29", "--title", "BCUS98116",
                              "--out", out])
            got = dict(ln.split("=", 1) for ln in open(out, encoding="utf-8-sig").read().splitlines())
            rep = fc.Report()
            rep.facts["disc"] = {"TITLE_ID": "BCUS98116"}
            fc.check_eboot_elf(rep, elf, "1.29", None, tbl)
        finally:
            fc.HASHES_FILE = old_file
        worst = [c for c in rep.checks if c["level"] == level]
        check(rc == 0 and got.get("level") == level and got.get("sha256") == sha and
              (level == "OK" and "text" not in got or worst and got.get("text") == worst[0]["message"]),
              f"helper --identify, {name}: level {got.get('level')} (want {level}), the check's own text")
    enc = os.path.join(tmp, "enc.elf")
    open(enc, "wb").write(fc.SELF_MAGIC + b"\0" * 60)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = ri.main(["--eboot-kind", enc, "--identify", "--out", os.path.join(tmp, "r2.txt")])
    got = open(os.path.join(tmp, "r2.txt"), encoding="utf-8-sig").read()
    check(rc == 1 and "status=encrypted" in got and "level=" not in got,
          "helper --identify on an encrypted SELF: the encrypted answer only (the page's own box)")

# 4. EbootVersionOf's parse, transcribed (Pos is 1-based, 0 = not found)
def pos(sub, s):
    return s.find(sub) + 1


def json_number(text, key):
    p = pos('"' + key + '": ', text)
    if not p:
        return ""
    i, r = p + len(key) + 4, ""
    while i <= len(text) and text[i - 1].isdigit():
        r += text[i - 1]
        i += 1
    return r


def json_string(text, key):
    p = pos('"' + key + '": "', text)
    if not p:
        return ""
    r = text[p + len(key) + 5 - 1:]     # Copy(Text, P + Length(Key) + 5, MaxInt)
    q = pos('"', r)
    return r[:q - 1] if q else ""


def version_of(text, size):
    r = text
    e = pos("}", r)
    while e:
        k = r[:e - 1]
        p = k.rfind("{") + 1                 # 0 = none
        s = k[p - 1:] if p else ""
        if p and json_number(s, "size") and int(json_number(s, "size")) == size:
            v = json_string(s, "app_ver")
            if v:
                if len(v) > 2 and v[0] == "0" and v[1] != ".":
                    v = v[1:]
            else:                            # old form: the quoted key before the object
                k = k[:p - 1]
                k = k[:k.rfind('"')]
                v = k[k.rfind('"') + 1:]
            return v, json_string(s, "sha256")
        r = r[e:]
        e = pos("}", r)
    return "", ""


raw = open(fc.HASHES_FILE, encoding="utf-8").read()
for s, v in fc.EBOOT_ELF_SIZES.items():
    check(version_of(raw, s) == (v, known[v]["sha256"]), f"parse: size {s} -> {v} and its SHA-256")
check(version_of(raw, 64) == ("", "") and version_of(raw, 16_381_929) == ("", ""),
      "control: an unknown size has no version")
check(version_of(json.dumps(table, indent=2), 16_381_928)[0] == "1.01", "parse holds for indent 2 as well")
check(not [x for x in table.get("comment", "") if x in "{}"], "the table's comment holds no brace (the parser splits on them)")
old_form = json.dumps({"comment": "old", "1.29": {"size": 16_455_144, "sha256": "ab" * 32},
                       "1.01": {"size": 16_381_928, "sha256": ""}}, indent=1)
check(version_of(old_form, 16_455_144) == ("1.29", "ab" * 32) and version_of(old_form, 16_381_928) == ("1.01", ""),
      "parse: an old-form table (a version key per object) still reads")
check(version_of(old_form, 64) == ("", ""), "control: old form, unknown size has no version")

print("test_install_eboot_page:", "PASS" if not bad else f"FAIL ({bad})")
sys.exit(1 if bad else 0)
