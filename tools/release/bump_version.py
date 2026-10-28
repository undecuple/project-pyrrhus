#!/usr/bin/env python3
"""Bump the release version everywhere in one go.

    python3 tools/release/bump_version.py [--check] [--date YYYY-MM-DD] [--root DIR] NEW_VERSION

Adapted from Project Helghast's tools/release/bump_version.py (the Killzone 3 PC port, same author, MIT).

installer/VERSION is the single source (release_version.py). This edits it and every place that writes the version as
a literal (test_version_agree.py is the list of places that state it):
  - installer/VERSION;
  - installer/launcher/launcher.rc and installer/app.rc.in: FILEVERSION / PRODUCTVERSION and the FileVersion /
    ProductVersion strings, only where they are literals (today both take the version at build time from
    installer/VERSION, through launcher_version.h and assemble_payload.py, and are left alone);
  - installer/kz2.iss: `#define AppVersion "X"` only when it is a literal (today it reads the payload's VERSION.txt);
  - public/CITATION.cff: version and date-released (added after the title when missing), on a change of version;
  - port/kz2/CMakeLists.txt: a project VERSION X.Y.Z line, when there is one (today there is none);
  - every one-line marker span `<!-- version -->...<!-- /version -->` in the public Markdown and HTML pages: each
    X.Y.Z inside a span becomes the new version, so a span may hold a whole release link;
  - public/CHANGELOG.md: "## [Unreleased]" becomes "## [X.Y.Z] - DATE (pre-release)"; with no Unreleased section an
    empty stub with "### Added" goes above the newest entry; left alone when X.Y.Z already has a section.
Then it regenerates the site (website.py; only where its data, docs/features.tsv, is present: the public repository
has only the generated page, where the marker spans move and the rest waits for the next export), then runs the
release chain's checks in order: test_version_agree.py; the draft release notes (release_notes.py --tag vX.Y.Z from the
CHANGELOG entry just made; --notes FILE keeps the text, otherwise it is only checked); and last recomp_card.py, the
public/.recomp.json card check. Exit 1 when any of them fails (the files are already written; fix and run again, a
second run with the same version changes nothing). Running it with the current version changes nothing. It refuses a version that is not X.Y.Z or is older than
installer/VERSION. --check lists what would change and writes nothing.

Public layout: the public repository has public/'s files at its root (no public/ folder); `at()` maps every public/
path there, as test_version_agree.py does. Local tool: no network, no git, no push.
"""
import argparse
import datetime
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import release_version  # noqa: E402

MARKER = re.compile(r"(<!-- version -->)(.*?)(<!-- /version -->)")
SEMVER = re.compile(r"\d+\.\d+\.\d+")
# Keep a Changelog headings. [ \t]*$, never \s*$: with re.M, \s* runs over the newline and swallows the blank line
# after the heading (Project Helghast's first bump lost it).
UNRELEASED = re.compile(r"^## \[Unreleased\][ \t]*$", re.M)
MARKER_SUFFIXES = (".md", ".html")
MARKER_SKIP = {"licenses", "assets", ".git", "__pycache__", "screenshots"}


def public_layout(root):
    """True in the public repository: public/'s files sit at the root (same rule as test_version_agree.layout)."""
    return not (pathlib.Path(root) / "public" / "README.md").is_file()


def at(root, rel):
    """The file for a repository path; public/... resolves at the root in the public layout."""
    root = pathlib.Path(root)
    if rel.startswith("public/") and public_layout(root):
        return root / rel[len("public/"):]
    return root / rel


def parse(v):
    return tuple(int(x) for x in v.split(".")) if release_version.valid(v) else None


def fill_markers(text, version):
    return MARKER.sub(lambda m: m.group(1) + SEMVER.sub(version, m.group(2)) + m.group(3), text)


def sub_opt(text, pattern, repl, what):
    """Replace at most one literal; two are an error (which one would be the version?)."""
    new, n = re.subn(pattern, repl, text, flags=re.M)
    if n > 1:
        raise SystemExit(f"bump_version: expected at most one {what}, found {n}")
    return new


def changelog(text, version, date):
    if re.search(rf"^## \[{re.escape(version)}\]", text, re.M):
        return text
    heading = f"## [{version}] - {date} (pre-release)"
    if UNRELEASED.search(text):   # Keep a Changelog: the release takes the unreleased entries
        return UNRELEASED.sub(heading, text, count=1)
    m = re.search(r"^## \[", text, re.M)
    if not m:
        raise SystemExit("bump_version: no '## [' entry in CHANGELOG.md to put the stub above")
    return text[:m.start()] + heading + "\n\n### Added\n\n" + text[m.start():]


def citation(text, version, date):
    """version and date-released; the date moves only with the version (a re-run keeps it)."""
    lines = text.splitlines()
    cur = next((re.sub(r'^version:\s*"?([^"\s]*)"?\s*$', r"\1", l) for l in lines if l.startswith("version:")), None)
    if cur == version:
        return text
    want = {"version": f'version: "{version}"', "date-released": f'date-released: "{date}"'}
    keys = {l.split(":", 1)[0] for l in lines}
    out = []
    for line in lines:
        key = line.split(":", 1)[0]
        out.append(want.get(key, line))
        if key == "title":
            out += [want[k] for k in ("version", "date-released") if k not in keys]
    return "\n".join(out) + "\n"


def rc(text, version):
    nums = release_version.rc_comma(version)
    text = sub_opt(text, r"^(FILEVERSION[ \t]+)\d+,\d+,\d+,\d+[ \t]*$", rf"\g<1>{nums}", "FILEVERSION")
    text = sub_opt(text, r"^(PRODUCTVERSION[ \t]+)\d+,\d+,\d+,\d+[ \t]*$", rf"\g<1>{nums}", "PRODUCTVERSION")
    text = sub_opt(text, r'(VALUE "FileVersion", ")\d+\.\d+\.\d+(")', rf"\g<1>{version}\2", "FileVersion")
    return sub_opt(text, r'(VALUE "ProductVersion", ")\d+\.\d+\.\d+(")', rf"\g<1>{version}\2", "ProductVersion")


def marker_files(root):
    """Public Markdown and HTML pages (CHANGELOG aside): the places a marker span may sit."""
    pages = at(root, "public/README.md").parent
    out = []
    for d, dirs, names in os.walk(pages):
        rel = os.path.relpath(d, pages)
        top = rel.split(os.sep)[0]
        # in the public layout the root also holds the code; only the pages' own folders are read there
        if public_layout(root) and rel != "." and top not in ("docs", "site", "tools", ".github"):
            dirs[:] = []
            continue
        dirs[:] = sorted(x for x in dirs if x not in MARKER_SKIP and not (rel == "." and x in ("installer", "port",
                                                                                             "third_party", "work", "build")))
        for n in sorted(names):
            if n.endswith(MARKER_SUFFIXES) and not n.upper().startswith("CHANGELOG"):
                out.append(pathlib.Path(d) / n)
    return out


def edits(root, version, date):
    """{path: new text} for every file whose text changes."""
    root = pathlib.Path(root)
    out = {}

    def edit(p, fn):
        if not p.is_file():
            return
        old = p.read_text(encoding="utf-8")
        new = fn(old)
        if new != old:
            out[p] = new

    edit(root / "installer/VERSION", lambda t: version + "\n")
    edit(root / "installer/launcher/launcher.rc", lambda t: rc(t, version))
    edit(root / "installer/app.rc.in", lambda t: rc(t, version))
    edit(root / "installer/kz2.iss",
         lambda t: sub_opt(t, r'^([ \t]*#define[ \t]+AppVersion[ \t]+")\d+\.\d+\.\d+(")', rf"\g<1>{version}\2", "AppVersion"))
    if version != release_version.read(str(root)):   # the current version: CITATION.cff is left as it is
        edit(at(root, "public/CITATION.cff"), lambda t: citation(t, version, date))
    edit(root / "port/kz2/CMakeLists.txt",
         lambda t: sub_opt(t, r"^([ \t]*VERSION[ \t]+)\d+\.\d+\.\d+([ \t]*)$", rf"\g<1>{version}\2", "project VERSION"))
    for p in marker_files(root):
        edit(p, lambda t: fill_markers(t, version))
    edit(at(root, "public/CHANGELOG.md"), lambda t: changelog(t, version, date))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("version", help="the new version, X.Y.Z, not older than installer/VERSION")
    ap.add_argument("--check", action="store_true", help="list what would change; write nothing")
    ap.add_argument("--date", default=datetime.date.today().isoformat(), help="CHANGELOG/CITATION date (default today)")
    ap.add_argument("--notes", metavar="FILE", help="keep the draft release notes here (default: checked, not written)")
    ap.add_argument("--root", default=str(ROOT), help="repository root (the tests use a copy)")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root)
    new = parse(a.version)
    if new is None:
        print(f"bump_version: {a.version!r} is not MAJOR.MINOR.PATCH", file=sys.stderr)
        return 2
    try:
        date = datetime.date.fromisoformat(a.date).isoformat()
    except ValueError:
        date = None
    if date != a.date:
        print(f"bump_version: --date {a.date!r} is not YYYY-MM-DD", file=sys.stderr)
        return 2
    try:
        cur = release_version.read(str(root))
    except ValueError as e:
        print(f"bump_version: {e}", file=sys.stderr)
        return 2
    if new < parse(cur):
        print(f"bump_version: {a.version} is older than the current {cur}", file=sys.stderr)
        return 2
    changed = edits(root, a.version, a.date)
    for p in sorted(changed):
        print(("would change " if a.check else "changed ") + os.path.relpath(p, root))
    if not changed:
        print(f"bump_version: nothing to change (already {a.version})")
    if a.check:
        if changed and (root / "docs/features.tsv").is_file():
            print("would regenerate public/site/index.html (website.py)")
        return 0
    for p, text in changed.items():
        p.write_text(text, encoding="utf-8")
    site = root / "tools/release/website.py"
    if changed and (root / "docs/features.tsv").is_file() and site.is_file():
        r = subprocess.run([sys.executable, str(site), "--root", str(root), "-q"])
        if r.returncode:
            print("bump_version: website.py failed", file=sys.stderr)
            return 1
    r = subprocess.run([sys.executable, str(root / "tools/release/test_version_agree.py"), "--repo", str(root)],
                       capture_output=True, text=True)
    tail = r.stdout.strip().splitlines()[-1:] or [""]
    print("test_version_agree: " + tail[0])
    if r.returncode:
        print(r.stdout[-2000:], file=sys.stderr)
        return 1
    return chain_checks(root, a.version, a.notes)


def chain_checks(root, version, notes_out):
    """The draft notes, then the card check. 1 on the first that fails."""
    tools = pathlib.Path(root) / "tools/release"
    if (tools / "release_notes.py").is_file():
        cmd = [sys.executable, str(tools / "release_notes.py"), "--tag", "v" + version, "--root", str(root)]
        if notes_out:
            cmd += ["--out", notes_out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print("bump_version: draft release notes refused: " + (r.stderr or r.stdout)[-600:], file=sys.stderr)
            return 1
        print("release_notes: draft for v" + version + (f" kept in {notes_out}" if notes_out else " checked"))
    if (tools / "recomp_card.py").is_file():
        r = subprocess.run([sys.executable, str(tools / "recomp_card.py"), "--repo", str(root)],
                           capture_output=True, text=True)
        print((r.stdout.strip().splitlines() or ["recomp_card: no output"])[-1])
        if r.returncode:
            print(r.stderr[-1500:], file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
