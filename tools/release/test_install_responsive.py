#!/usr/bin/env python3
"""Host test: the setup wizard's window keeps answering while a helper runs (issue #22).
Static checks of installer/kz2.iss and the helpers' result files; no game data, no Inno Setup.

    python3 tools/release/test_install_responsive.py

Cases:
  - no Exec(..., ewWaitUntilTerminated, ...) is left in [Code]: the version check (CheckNowClick), the EBOOT check
    (EbootEncrypted) and the RPCS3 import (Rpcs3Import) go through RunHelper; RunBuild keeps its own ewNoWait loop.
  - RunHelper: ewNoWait, a poll loop that processes messages (marquee page Animate) in Sleep slices, a time limit,
    the step's name and time in the log (no arguments: they hold the player's paths), a fresh result file per run.
  - each call site has its own status line and a time limit.
  - the EBOOT version test takes the hash the helper run gave (EbootSha256), not GetSHA256OfFile first.
  - [Files]: the headings font is the first entry and comes from the payload's own fonts folder (stored once, at the
    start of the solid stream: InitializeSetup extracts it before the wizard shows); the vcheck entries come before
    the payload line; MergeDuplicateFiles is not turned off.
  - the helpers write their result whole: rpcs3_import._write and version_check --result-file rename a .part file
    into place (the wizard reads the file as soon as it exists).
Exit 0 = PASS, 1 = FAIL.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
ISS = os.path.join(ROOT, "installer", "kz2.iss")

bad = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        bad.append(msg)


t = open(ISS, encoding="utf-8").read() if os.path.isfile(ISS) else ""
check(bool(t), "installer/kz2.iss found")


def func(name):
    """One [Code] function or procedure: from its header to the first 'end;' at the start of a line."""
    m = re.search(r"^(function|procedure) " + re.escape(name) + r"\b.*?^end;", t, re.M | re.S)
    return m.group(0) if m else ""


def section(name):
    m = re.search(r"^\[" + re.escape(name) + r"\]\s*$(.*?)(?=^\[[A-Za-z]+\]\s*$)", t, re.M | re.S)
    return m.group(1) if m else ""


def code_only(text):
    """Pascal without its { } comments (the comments may name ewWaitUntilTerminated)."""
    return re.sub(r"\{[^}]*\}", "", text)


code = code_only(t[t.find("[Code]"):]) if "[Code]" in t else ""
check(bool(code), "[Code] found")

# 1. no blocking Exec anywhere in [Code]
check("ewWaitUntilTerminated" not in code, "no Exec with ewWaitUntilTerminated is left in [Code]")
for name in ("CheckNowClick", "EbootEncrypted", "Rpcs3Import"):
    f = code_only(func(name))
    check(bool(f) and "RunHelper(" in f and not re.search(r"\bExec\(", f),
          f"{name} runs its helper through RunHelper, not Exec")
execs = re.findall(r"\bExec\((.*?)\)\s*(?:then|;|and)", code, re.S)
check(len(execs) >= 2 and all("ewNoWait" in e for e in execs),
      f"every Exec in [Code] is ewNoWait ({len(execs)} found)")
check(set(n for n in ("RunHelper", "RunBuild") if re.search(r"\bExec\(", code_only(func(n))))
      == {"RunHelper", "RunBuild"}, "Exec is called only from RunHelper and RunBuild")

# 2. RunHelper's wait
rh = code_only(func("RunHelper"))
check(bool(rh), "RunHelper found")
check("ewNoWait" in rh, "RunHelper starts the helper with ewNoWait")
check(re.search(r"repeat.*?\.Animate;.*?Sleep\(\s*\d+\s*\).*?until\s+FileExists\(ResFile\)\s+or\s+\(Ms\s*>=\s*TimeoutSec",
                rh, re.S) is not None,
      "RunHelper polls for the result file in Sleep slices, Animate between them, up to a time limit")
check("CreateOutputMarqueeProgressPage" in rh and ".Hide" in rh and "finally" in rh,
      "RunHelper shows a marquee page and hides it in a finally")
logs = re.findall(r"Log\((.*?)\);", rh, re.S)
check(any("done in" in x for x in logs) and all("Params" not in x and "ResFile" not in x for x in logs),
      "RunHelper logs the step's name and time, never its arguments or files")
check("GetTickCount@kernel32.dll" in t, "the time comes from GetTickCount")
check("HelperSeq := HelperSeq + 1" in code_only(func("HelperResFile")), "a fresh result file name per run")
check(all("HelperResFile(" in code_only(func(n)) for n in ("CheckNowClick", "EbootEncrypted", "Rpcs3Import")),
      "every call site takes a fresh result file")

# 3. call sites: a status line and a time limit each
for name, words in (("CheckNowClick", "Asking GitHub"), ("EbootEncrypted", "Checking your EBOOT"),
                    ("Rpcs3Import", "Looking for")):
    f = func(name)
    m = re.search(r"RunHelper\((.*?)\)\s*(?:then|;)", code_only(f), re.S)
    check(m is not None and words in f and re.search(r",\s*(\d+|Limit)\s*$", m.group(1).strip()) is not None,
          f"{name}: status line '{words}...' and a time limit")
check("var OutFile: String" in func("Rpcs3Import"), "Rpcs3Import hands the fresh result file back to its callers")
check("status=error" in code_only(func("Rpcs3Import")), "Rpcs3Import treats status=error as did not run")
check(code_only(func("VcheckExtracted")).count("ExtractTemporaryFiles") == 1
      and "ExtractTemporaryFiles" not in code_only(func("CheckNowClick") + func("EbootEncrypted")),
      "the vcheck Python is extracted once (VcheckExtracted)")

# 4. the EBOOT hash
ev = code_only(func("EbootVersionOf"))
check("EbootSha256(" in ev and "GetSHA256OfFile" not in ev, "EbootVersionOf takes the hash through EbootSha256")
es = code_only(func("EbootSha256"))
check(es.find("EbootHashValue") >= 0 and es.find("EbootHashValue") < es.find("GetSHA256OfFile"),
      "EbootSha256 uses the helper's hash first, GetSHA256OfFile only as the fallback")
check("--sha256" in func("EbootEncrypted"), "the EBOOT check asks the helper for the hash")

# 5. [Files] order and the font
files = [x for x in section("Files").splitlines() if x.startswith("Source:")]
check(bool(files) and "Rajdhani-Bold.ttf" in files[0] and "{#FontDir}" in files[0], "the headings font is the first [Files] entry")
check(re.search(r'#define FontDir Payload \+ "\\fonts"', t) is not None,
      "FontDir defaults to the payload's own fonts folder (same source as the payload line: stored once)")
payload_i = next((i for i, x in enumerate(files) if x.startswith('Source: "{#Payload}\\*"')), -1)
vcheck_i = [i for i, x in enumerate(files) if "{tmp}\\vcheck" in x]
check(payload_i > 0 and vcheck_i and max(vcheck_i) < payload_i, "the vcheck entries come before the payload line")
check(re.search(r"^MergeDuplicateFiles\s*=\s*no", section("Setup"), re.M | re.I) is None,
      "MergeDuplicateFiles is not turned off")

# 6. the helpers write their result whole
ri = open(os.path.join(HERE, "rpcs3_import.py"), encoding="utf-8").read()
m = re.search(r"^def _write\(.*?(?=^def )", ri, re.M | re.S)
check(m is not None and '".part"' in m.group(0) and "os.replace(" in m.group(0), "rpcs3_import._write renames into place")
vc = open(os.path.join(HERE, "version_check.py"), encoding="utf-8").read()
check(re.search(r'result_file \+ "\.part".*?os\.replace\(a\.result_file \+ "\.part", a\.result_file\)', vc, re.S)
      is not None, "version_check --result-file renames into place")

print("test_install_responsive:", "PASS" if not bad else f"FAIL ({len(bad)})")
sys.exit(1 if bad else 0)
