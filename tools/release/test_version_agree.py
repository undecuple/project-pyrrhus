#!/usr/bin/env python3
"""Host test: every mention of this project's own release version in the public files agrees with installer/VERSION.

    python3 tools/release/test_version_agree.py [--repo DIR]

Works in both layouts: this repository (the public pages live in public/) and the public repository (the same files at
the root, no public/ folder, where installer/VERSION is still at installer/VERSION).

The pattern is narrow on purpose: only places that state the release version are read, so dependency versions (ps3recomp
v0.18.0, toolchain pins, action versions), example tags in the versioning section and the CITATION date-released never
match. A mention counts when it is
  - the CITATION.cff key   version: "X"
  - the launcher / kz2.exe version block   FileVersion, ProductVersion, FILEVERSION, PRODUCTVERSION  (X or X.0, X,0)
  - the installer script   AppVersion = X  (a literal; the script reads the payload's VERSION.txt otherwise)
  - prose   "version X", "release X", "installer X", "launcher X", "Pyrrhus X"  (X with an optional v)
  and the 40 characters before a prose match name no dependency (ps3recomp, Inno Setup, CMake, FFmpeg, ...).
CHANGELOG*, third_party, licenses and binary files are not read.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
X = r"(\d+\.\d+\.\d+)(?![\d.])"
PATTERNS = [
    ("citation", re.compile(r'^version:\s*"?' + X, re.M)),
    ("version block", re.compile(r"(?:FileVersion|ProductVersion)\W{1,4}v?" + X)),
    ("version block", re.compile(r"(?:FILEVERSION|PRODUCTVERSION)\s+(\d+),(\d+),(\d+),\d+")),  # handled apart
    ("iss", re.compile(r"AppVersion\s*[= ]\s*" + X)),
    ("prose", re.compile(r"\b(?:[Vv]ersion|release|installer|launcher|Pyrrhus)\s+[`*\"']{0,2}v?" + X)),
]
DEPENDENCY = re.compile(r"ps3recomp|Inno|CMake|FFmpeg|LLVM|clang|Python|SDL|Proton|RPCS3|toolkit|toolchain|MinGW|Nix",
                        re.I)
TEXT = (".md", ".txt", ".html", ".cff", ".yml", ".yaml", ".iss", ".rc", ".in", ".sh", ".h", ".json")
SKIP_DIRS = {"third_party", "licenses", "licence-texts", ".git", "assets", "__pycache__", "art", "Output"}


def mentions(text):
    """[(line number, what, version)] for each release-version mention in text."""
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        for what, pat in PATTERNS:
            for m in pat.finditer(line):
                if m.re.pattern.startswith("(?:FILEVERSION"):
                    v = ".".join(m.groups())
                elif what == "prose" and DEPENDENCY.search(line[max(0, m.start() - 40):m.start()]):
                    continue
                else:
                    v = m.group(1)
                out.append((no, what, v))
    return out


def layout(repo):
    """('public', dir of the public pages) in this repository, ('root', repo) in the public repository."""
    p = os.path.join(repo, "public")
    return ("public", p) if os.path.isfile(os.path.join(p, "README.md")) else ("root", repo)


def files(repo):
    """The public files to read, as paths: the pages root (top-level files, docs, site, .github, tools/README.md) and
    the installer folder plus build_launcher.sh, which mirror the version."""
    _, pages = layout(repo)
    out = []
    for name in sorted(os.listdir(pages)):
        p = os.path.join(pages, name)
        if os.path.isfile(p):
            out.append(p)
    for sub in ("docs", "site", ".github"):
        out += walk(os.path.join(pages, sub))
    readme = os.path.join(pages, "tools", "README.md")
    if os.path.isfile(readme):
        out.append(readme)
    out += walk(os.path.join(repo, "installer"))
    sh = os.path.join(repo, "tools", "release", "build_launcher.sh")
    if os.path.isfile(sh):
        out.append(sh)
    return [p for p in dict.fromkeys(out)
            if p.lower().endswith(TEXT) or os.path.basename(p) in ("NOTICE", "LICENSE")][:]


def walk(top):
    out = []
    for d, dirs, names in os.walk(top):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        out += [os.path.join(d, n) for n in sorted(names)]
    return out


def stale(repo, version):
    """['relative/path:line: <what> X (VERSION is Y)'] for every disagreeing mention."""
    found = []
    for p in files(repo):
        if os.path.basename(p).upper().startswith("CHANGELOG"):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        for no, what, v in mentions(text):
            if v != version:
                found.append(f"{os.path.relpath(p, repo)}:{no}: {what} {v} (installer/VERSION is {version})")
    return found


def marker_line_starts(repo):
    """['relative/path:line'] for each Markdown line that starts with a version marker. GitHub takes a line that starts
    with an HTML comment as a raw HTML block and leaves the Markdown in it unrendered (the 2026-11-09 README badge)."""
    found = []
    for p in files(repo):
        if not p.lower().endswith(".md"):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        found += [f"{os.path.relpath(p, repo)}:{no}" for no, line in enumerate(text.splitlines(), 1)
                  if line.lstrip().startswith("<!-- version -->")]
    return found


FAILS = []


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"\n     {str(detail)[:600]}"))
    if not cond:
        FAILS.append(what)


def selftest():
    import tempfile
    stale_text = ('version: "0.0.9"\nFrom version 0.0.9 the zip ships it.\nFileVersion 0.0.9, FILEVERSION 0,0,9,0\n'
                  '#define AppVersion 0.0.9\nThe installer v0.0.9 does this.\n')
    check([m[2] for m in mentions(stale_text)] == ["0.0.9"] * 6, "stale mentions are all found", mentions(stale_text))
    ok_text = ('Uses ps3recomp version 0.18.0 and CMake release 3.28.0.\nA fix is `v0.1.1`, a feature `v0.2.0`.\n'
               'date-released: "2026-10-30"\nversion: "0.1.0"\nFILEVERSION 0,1,0,0\nrelease v0.1.0 is out\n')
    got = [(m[1], m[2]) for m in mentions(ok_text)]
    check(sorted(v for _, v in got) == ["0.1.0"] * 3 and not [1 for _, v in got if v != "0.1.0"],
          "dependency versions, example tags and the date are allowed", got)
    for lay in ("public", "root"):
        with tempfile.TemporaryDirectory() as tmp:
            pages = os.path.join(tmp, "public") if lay == "public" else tmp
            for d in (pages, os.path.join(pages, "docs"), os.path.join(tmp, "installer")):
                os.makedirs(d, exist_ok=True)
            open(os.path.join(tmp, "installer", "VERSION"), "w").write("0.2.0\n")
            open(os.path.join(tmp, "installer", "kz2.iss"), "w").write("AppVersion={#AppVersion}\n")
            open(os.path.join(pages, "README.md"), "w").write("ps3recomp v0.18.0\nSince version 0.2.0.\n")
            open(os.path.join(pages, "docs", "A.md"), "w").write("From version 0.1.0 it ships.\n")
            open(os.path.join(pages, "CITATION.cff"), "w").write('version: "0.2.0"\ndate-released: "2026-10-30"\n')
            s = stale(tmp, "0.2.0")
            check(len(s) == 1 and s[0].startswith(os.path.join(*(["public"] if lay == "public" else []), "docs", "A.md")),
                  f"layout {lay}: the one stale mention is found and nothing else", s)
            open(os.path.join(pages, "docs", "B.md"), "w").write("Badges: <!-- version -->v0.2.0<!-- /version -->\n"
                                                              "<!-- version -->[![v](x)](y)<!-- /version -->\n")
            m = marker_line_starts(tmp)
            check(len(m) == 1 and m[0].endswith("B.md:2"), f"layout {lay}: a marker starting a Markdown line is found", m)


def main(argv):
    repo = REPO
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    selftest()
    with open(os.path.join(repo, "installer", "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    scanned = files(repo)
    s = stale(repo, version)
    check(len(scanned) > 3, f"{layout(repo)[0]} layout: {len(scanned)} public files read", scanned[:5])
    check(not s, f"every release-version mention agrees with installer/VERSION ({version})", "\n     ".join(s))
    m = marker_line_starts(repo)
    check(not m, "no Markdown line starts with a version marker (GitHub would show it as raw text)", m)
    print("FAILED" if FAILS else "all ok")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
