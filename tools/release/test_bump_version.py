#!/usr/bin/env python3
"""Host test for tools/release/bump_version.py: runs on temporary copies, never the real tree. No game data.

Adapted from Project Helghast's tools/release/test_bump_version.py (the Killzone 3 PC port, same author, MIT).
Both layouts: this repository (public/ pages) and the public repository (the pages at the root, no public/ folder).
In the public repository the tree is copied as it is found; here a public-layout copy is also made the way the export
lays it out, so the public/-path mapping is tested on every run (the payload assembly once broke on that difference).
Covers, in each layout: a bump to the next patch version (installer/VERSION, CITATION.cff version and date, the
README / BUILDING / site marker spans, [Unreleased] becoming the release with its blank line kept, the site's download
block (regenerated where docs/features.tsv is present), test_version_agree passing on the copy), --check writing nothing, refusing a downgrade, bad syntax and a bad
date, the current version and a second run changing nothing. Unit checks: the heading regex keeps the blank line
(the [ \\t]*$ pitfall), a stub goes above the newest entry when there is no [Unreleased], literal versions in an rc
script, kz2.iss and CMakeLists are moved while the build-time ones are left alone.

    python3 tools/release/test_bump_version.py
"""
import contextlib
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REAL = HERE.parents[1]
sys.path.insert(0, str(HERE))
import bump_version  # noqa: E402
import release_version  # noqa: E402

IGNORE = shutil.ignore_patterns(".git", "third_party", "build", "work", "__pycache__", "Game", "Output")
FAILS = []


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"\n     {str(detail)[:600]}"))
    if not cond:
        FAILS.append(what)


def copy_release_tools(dst):
    (dst / "tools/release").mkdir(parents=True, exist_ok=True)
    for p in (REAL / "tools/release").iterdir():
        if p.is_file() and p.suffix in (".py", ".json", ".sh"):
            shutil.copy2(p, dst / "tools/release" / p.name)


def make_copies(base):
    """{layout: root} of the copies to test."""
    if not (REAL / "public").is_dir():   # the public repository: copy it as it is
        dst = base / "root"
        shutil.copytree(REAL, dst, ignore=IGNORE)
        return {"root (as found)": dst}
    priv = base / "public"
    for rel in ("public", "installer", "docs/features.tsv", "docs/requirements.md", "port/kz2/CMakeLists.txt"):
        src, out = REAL / rel, priv / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree(src, out, ignore=IGNORE) if src.is_dir() else shutil.copy2(src, out))
    copy_release_tools(priv)
    pubr = base / "root"   # as tools/export-public.sh lays it out: public/'s files at the root, no features.tsv
    shutil.copytree(REAL / "installer", pubr / "installer", ignore=IGNORE)
    (pubr / "docs").mkdir(parents=True)
    shutil.copy2(REAL / "docs/requirements.md", pubr / "docs/requirements.md")
    shutil.copytree(REAL / "public", pubr, dirs_exist_ok=True, ignore=IGNORE)
    (pubr / "docs/FEATURES.md").write_text("# Features\n")   # the export generates it from docs/features.tsv
    copy_release_tools(pubr)
    return {"public/": priv, "root (export)": pubr}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


def run(root, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = bump_version.main(["--root", str(root), *args])
    return rc, out.getvalue(), err.getvalue()


def next_patch(v):
    a, b, c = v.split(".")
    return f"{a}.{b}.{int(c) + 1}"


def layout_round(name, root):
    cur = release_version.read(str(root))
    new = next_patch(cur)
    t = lambda rel: bump_version.at(root, rel).read_text(encoding="utf-8")  # noqa: E731
    base = snapshot(root)
    cl0 = t("public/CHANGELOG.md")

    rc, out, _ = run(root, cur, "--date", "2030-01-02")
    check(rc == 0 and snapshot(root) == base, f"{name}: the current version {cur} changes nothing", out)
    rc, out, _ = run(root, new, "--check", "--date", "2030-01-02")
    check(rc == 0 and snapshot(root) == base and "would change installer/VERSION" in out,
          f"{name}: --check lists the changes and writes nothing", out)
    for v, why in (("0.0.1", "downgrade"), ("1.2", "two numbers"), ("v" + new, "a leading v"), ("01.2.3", "a leading 0"),
                   (new + "-rc1", "a suffix"), ("x", "words")):
        rc, _, _ = run(root, v)
        check(rc == 2 and snapshot(root) == base, f"{name}: {why} {v!r} refused, nothing written")
    for d in ("30-01-02", "2030-1-2", "20300102"):
        check(run(root, new, "--date", d)[0] == 2 and snapshot(root) == base, f"{name}: bad --date {d!r} refused")

    rc, out, err = run(root, new, "--date", "2030-01-02")
    check(rc == 0, f"{name}: bump to {new} succeeds", out[-400:] + err[-600:])
    check(t("installer/VERSION") == new + "\n", f"{name}: installer/VERSION")
    cff = t("public/CITATION.cff")
    check(f'\nversion: "{new}"\n' in cff and '\ndate-released: "2030-01-02"\n' in cff, f"{name}: CITATION.cff", cff[:300])
    readme, building = t("public/README.md"), t("public/docs/BUILDING.md")
    rel = f"[v{new}](https://github.com/undecuple/project-pyrrhus/releases/tag/v{new})"
    check(f"<!-- version -->{rel}<!-- /version -->" in readme and cur not in "".join(
        re.findall(r"<!-- version -->(.*?)<!-- /version -->", readme)), f"{name}: README marker span", readme[:0])
    check(f"<!-- version -->{rel}<!-- /version -->" in building, f"{name}: BUILDING marker span")
    cl = t("public/CHANGELOG.md")
    if re.search(r"^## \[Unreleased\]", cl0, re.M):
        check(f"## [{new}] - 2030-01-02 (pre-release)\n\n### " in cl and "## [Unreleased]" not in cl
              and cl.count(f"## [{new}]") == 1, f"{name}: [Unreleased] becomes {new}, blank line kept")
    else:
        check(f"## [{new}] - 2030-01-02 (pre-release)\n\n### Added\n\n## [{cur}]" in cl, f"{name}: stub above the newest entry")
    check(len(cl.splitlines()) >= len(cl0.splitlines()), f"{name}: no CHANGELOG line lost")
    site = t("public/site/index.html")
    spans = re.findall(r"<!-- version -->(.*?)<!-- /version -->", site)
    check(not [x for x in spans if cur in x], f"{name}: every site marker span moved", spans)
    if (root / "docs/features.tsv").is_file():   # here the page is regenerated; the public repository waits for the export
        check(f"<!-- version -->v{new}<!-- /version -->" in site and f"Download v{new}</a><!-- /version -->" in site,
              f"{name}: the site's version and download block")
        check(f"<h2>v{new}</h2>" in site and "2 Jan 2030" in site, f"{name}: the site regenerated with the release news")
    r = subprocess.run([sys.executable, str(root / "tools/release/test_version_agree.py"), "--repo", str(root)],
                       capture_output=True, text=True)
    check(r.returncode == 0, f"{name}: test_version_agree passes on the bumped copy", r.stdout[-800:])

    after = snapshot(root)
    rc, _, _ = run(root, new, "--date", "2031-05-05")
    check(rc == 0 and snapshot(root) == after, f"{name}: a second run with the same version changes nothing")
    check(run(root, cur)[0] == 2, f"{name}: going back to {cur} is refused")


def units():
    for heading in ("## [Unreleased]", "## [Unreleased]  ", "## [Unreleased]\t"):
        text = f"# Changelog\n\n{heading}\n\n### Added\n- A.\n\n## [0.1.0] - 2026-10-28 (tagged, not released)\n"
        got = bump_version.changelog(text, "0.1.1", "2030-01-02")
        check("## [0.1.1] - 2030-01-02 (pre-release)\n\n### Added\n- A.\n" in got, f"heading {heading!r}: blank line kept", got)
    # \s*$ would have taken the newline: the regression this guards
    check(re.sub(r"^## \[Unreleased\]\s*$", "X", "## [Unreleased]\n\nB", count=1, flags=re.M) == "X\nB"
          and bump_version.UNRELEASED.sub("X", "## [Unreleased]\n\nB", count=1) == "X\n\nB",
          "the old \\s*$ heading regex ate the blank line; [ \\t]*$ keeps it")
    text = "# Changelog\n\nIntro.\n\n## [0.1.0] - 2026-10-28 (pre-release)\n\n### Added\n- A.\n"
    got = bump_version.changelog(text, "0.1.1", "2030-01-02")
    check("Intro.\n\n## [0.1.1] - 2030-01-02 (pre-release)\n\n### Added\n\n## [0.1.0]" in got, "stub above the newest entry", got)
    check(bump_version.changelog(got, "0.1.1", "2031-01-01") == got, "an existing entry is left alone")
    lit = ('1 VERSIONINFO\nFILEVERSION 0,1,0,0\nPRODUCTVERSION 0,1,0,0\n  VALUE "FileVersion", "0.1.0"\n'
           '  VALUE "ProductVersion", "0.1.0"\n')
    got = bump_version.rc(lit, "0.2.3")
    check(got.count("0,2,3,0") == 2 and got.count('"0.2.3"') == 2 and "0.1.0" not in got, "literal rc versions move", got)
    for name in ("installer/launcher/launcher.rc", "installer/app.rc.in"):
        p = REAL / name
        if p.is_file():
            s = p.read_text(encoding="utf-8")
            check(bump_version.rc(s, "9.9.9") == s, f"{name}: the build-time version is left alone")
    iss = '#define AppVersion "0.1.0"\nAppVersion={#AppVersion}\n'
    check(bump_version.sub_opt(iss, r'^([ \t]*#define[ \t]+AppVersion[ \t]+")\d+\.\d+\.\d+(")', r"\g<1>0.2.0\2", "x")
          == iss.replace("0.1.0", "0.2.0"), "a literal kz2.iss AppVersion moves")
    with tempfile.TemporaryDirectory() as t:
        root = pathlib.Path(t)
        (root / "installer").mkdir()
        (root / "installer/VERSION").write_text("0.1.0\n")
        (root / "installer/kz2.iss").write_text("#define AppVersion PayloadVersion\n")
        (root / "port/kz2").mkdir(parents=True)
        (root / "port/kz2/CMakeLists.txt").write_text("project(kz2\n    VERSION 0.1.0\n    LANGUAGES C CXX\n)\n")
        (root / "public").mkdir()
        (root / "public/README.md").write_text("Pre-release <!-- version -->v0.1.0<!-- /version --> and 0.1.0 outside.\n")
        (root / "public/CITATION.cff").write_text('cff-version: 1.2.0\ntitle: "X"\ntype: software\n')
        (root / "public/CHANGELOG.md").write_text("# Changelog\n\n## [0.1.0] - 2026-10-28 (pre-release)\n")
        ch = {os.path.relpath(p, root): s for p, s in bump_version.edits(root, "0.1.1", "2030-01-02").items()}
        check("    VERSION 0.1.1\n" in ch.get("port/kz2/CMakeLists.txt", ""), "a CMake project VERSION moves")
        check("installer/kz2.iss" not in ch, "kz2.iss reading the payload's version is left alone")
        check(ch.get("public/README.md", "").endswith("<!-- version -->v0.1.1<!-- /version --> and 0.1.0 outside.\n"),
              "only the marker span moves")
        check(ch.get("public/CITATION.cff", "") == 'cff-version: 1.2.0\ntitle: "X"\nversion: "0.1.1"\n'
              'date-released: "2030-01-02"\ntype: software\n', "CITATION.cff without a version gets one after the title",
              ch.get("public/CITATION.cff"))


def chain_round(name, root):
    """The chain's tail: draft notes kept on request, a broken card fails the bump, an empty entry fails the notes."""
    cur = release_version.read(str(root))
    new = next_patch(next_patch(cur))
    card = bump_version.at(root, "public/.recomp.json")
    good = card.read_text(encoding="utf-8")
    notes = root.parent / (root.name + "-draft-notes.md")   # outside the tree: test_version_agree reads every file in it
    cl = bump_version.at(root, "public/CHANGELOG.md")

    def unreleased_item():
        t0 = cl.read_text(encoding="utf-8")
        at_first = re.search(r"^## \[", t0, re.M).start()
        cl.write_text(t0[:at_first] + "## [Unreleased]\n\n### Added\n\n- A test item.\n\n" + t0[at_first:], encoding="utf-8")

    unreleased_item()
    rc, out, err = run(root, new, "--date", "2030-02-03", "--notes", str(notes))
    check(rc == 0 and "recomp_card: card is current" in out and "release_notes: draft" in out,
          f"{name}: bump prints the notes and card steps", out[-300:] + err[-300:])
    check(notes.is_file() and new in notes.read_text(encoding="utf-8"), f"{name}: --notes keeps the draft for {new}")
    newer = next_patch(new)
    unreleased_item()
    card.write_text(good.replace('"BCUS98116"', '"BCUS00000"'), encoding="utf-8")
    rc, out, err = run(root, newer, "--date", "2030-02-04")
    check(rc == 1 and "C6" in err and "release_notes: draft" in out, f"{name}: a card that disagrees fails the bump (after the notes)",
          out[-200:] + err[-300:])
    card.write_text(good, encoding="utf-8")
    text = cl.read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(newer)}\].*?(?=^## \[)", text, re.M | re.S)
    cl.write_text(text.replace(m.group(0), m.group(0).split("\n", 1)[0] + "\n\n### Added\n\n"), encoding="utf-8")
    rc, out, err = run(root, newer, "--date", "2030-02-04")
    check(rc == 1 and "draft release notes refused" in err, f"{name}: an entry with no items fails at the notes step", err[-300:])


def main():
    real_before = snapshot(REAL / "installer")
    units()
    with tempfile.TemporaryDirectory() as td:
        for name, root in make_copies(pathlib.Path(td)).items():
            layout_round(name, root)
            chain_round(name, root)
    check(snapshot(REAL / "installer") == real_before, "the real tree was not touched")
    print("FAILED" if FAILS else "PASS test_bump_version")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
