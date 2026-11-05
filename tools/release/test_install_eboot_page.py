#!/usr/bin/env python3
"""Host test (adapted from Project Helghast PR #11, its test_install_eboot_page.py, same author,
MIT): installer/kz2.iss' EBOOT page and failure box. Static checks (no ISCC, no game data):
- the EBOOT page tests the picked file's version from firstrun_check's own table (eboot_sha256.json, shipped as a
  dontcopy file; no size or hash written into the script) and refuses a known EBOOT of another version than the
  release's (the disc's 1.01 one), naming the update's USRDIR folder; an unknown EBOOT passes as before;
- a silent install with /EBOOT= stops on the same test, with the same text (PrepareToInstall: exit code 7);
- the build's failure box shows firstrun.py's REASON lines before the log path, and a check-step failure says the
  next start asks again;
- the table parser (EbootVersionOf + JsonNumber + JsonString), transcribed to Python, reads the shipped table the
  way firstrun_check.EBOOT_ELF_SIZES does, with a negative control (unknown size -> no version).

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
known = {k: v for k, v in table.items() if isinstance(v, dict)}
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
check("V <> '{#EbootTarget}'" in ep and "This is the disc''s {#DiscEboot} EBOOT." in ep and
      "EBOOT.BIN in the update''s USRDIR folder" in ep and "AddBackslash(UpdateDir) + 'USRDIR'" in ep and
      "dev_hdd0\\game\\<your disc''s title id, such as BCUS98116>\\USRDIR" in ep,
      "EbootProblem: another known version refused, names the update's USRDIR and the usual folder")
check("Result := '';" in ep and "if (V <> '') and" in ep, "EbootProblem: an unknown EBOOT passes")
# without an update folder (a silent /EBOOT= alone) the usual folder was named twice (VM kit pre-flight, an earlier change):
# "(usually ...)" only on the branch with an update folder
usual = [ln for ln in ep.splitlines() if "(usually" in ln]
check(len(usual) == 1 and usual[0].strip().startswith("if UpdateDir <> '' then"),
      "EbootProblem: '(usually ...)' only beside a given update folder")
nb = func("NextButtonClick")
check("Problem := EbootProblem(EbootPage.Values[0], UpdatePage.Values[0]);" in nb and "MsgBox(Problem, mbError, MB_OK);" in nb,
      "Next on the EBOOT page refuses with the reason")
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
    p = pos('": {', r)
    while p:
        k = r[:p - 1]
        v = k[k.rfind('"') + 1:]
        s = r[p - 1:]
        e = pos("}", s)
        if e:
            s = s[:e]
        if json_number(s, "size") and int(json_number(s, "size")) == size:
            return v, json_string(s, "sha256")
        r = r[p - 1 + 4:]
        p = pos('": {', r)
    return "", ""


raw = open(fc.HASHES_FILE, encoding="utf-8").read()
for s, v in fc.EBOOT_ELF_SIZES.items():
    check(version_of(raw, s) == (v, known[v]["sha256"]), f"parse: size {s} -> {v} and its SHA-256")
check(version_of(raw, 64) == ("", "") and version_of(raw, 16_381_929) == ("", ""),
      "control: an unknown size has no version")
check(version_of(json.dumps(table, indent=2), 16_381_928)[0] == "1.01", "parse holds for indent 2 as well")

print("test_install_eboot_page:", "PASS" if not bad else f"FAIL ({bad})")
sys.exit(1 if bad else 0)
