#!/usr/bin/env python3
"""The GitHub release notes for a tag, written from its CHANGELOG entry, so nobody writes them by hand.

    python3 tools/release/release_notes.py --tag vX.Y.Z [--out FILE] [--root DIR]
    python3 tools/release/release_notes.py --preview X.Y.Z [--out FILE]   # the release workflow's dry run

The shape follows Project Helghast's release notes (the Killzone 3 PC port, same author, MIT), with this project's
wording:
  Project Pyrrhus X.Y.Z, a pre-release: partly playable, see docs/RELEASE-CRITERIA.md.
  New in X.Y.Z: <the CHANGELOG entry's new items, one bullet each>
  Fixed: <its fixes, one bullet each; part of the list above for the first published release>
  If you have an earlier version, install this one over it: ...   (only when an earlier version was published)
  See CHANGELOG.md for the full list.
  <the fixed paragraph: the Windows installer and portable zip, what you need, none of it included>
Links point at the tag's own files. A tag with no CHANGELOG entry, an entry with no items, or an entry that is not a
release (not "(pre-release)" or "(release)", such as "(tagged, not released)" or [Unreleased]) is refused: exit 1.
--preview takes the version's entry or, when it has none or an empty one, the [Unreleased] one, and never refuses for the note
(the dry run builds the same assets without publishing). Exit 0 = notes written, 1 = refused, 2 = usage.
Standard library only; reads CHANGELOG.md in either layout (public/CHANGELOG.md here, CHANGELOG.md in the public
repository).
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import release_version  # noqa: E402

ROOT = HERE.parents[1]
REPO = "https://github.com/undecuple/project-pyrrhus"
STATUS = "partly playable"   # the README's status word (test_release_notes.py checks that the README says it)
HEADING = re.compile(r"## \[([^\]]+)\](?:[ \t]+-[ \t]+(\d{4}-\d\d-\d\d))?[ \t]*(?:\(([^)]*)\))?[ \t]*$")
NEW_SECTIONS = ("Added", "Changed", "Removed", "Deprecated", "Security")


def changelog_path(root):
    root = pathlib.Path(root)
    return root / "public" / "CHANGELOG.md" if (root / "public").is_dir() else root / "CHANGELOG.md"


def entries(text):
    """{version: {date, note, items: [(section, text)]}} for every '## [...]' heading of the whole file."""
    out, cur, section = {}, None, ""
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            cur = {"date": m.group(2), "note": (m.group(3) or "").strip(), "items": []}
            out.setdefault(m.group(1), cur)
            section = ""
        elif cur is None:
            continue
        elif line.startswith("### "):
            section = line[4:].strip()
        elif line.startswith("- "):
            cur["items"].append((section, line[2:].strip()))
        elif line.startswith("  ") and cur["items"] and line.strip():   # a wrapped item line
            s, t = cur["items"][-1]
            cur["items"][-1] = (s, t + " " + line.strip())
    return out


def sentence(t, blob=""):
    """An item as a sentence: a full stop added when missing; relative links point at the tag's files."""
    t = t.strip()
    if blob:
        t = re.sub(r"\]\((?!https?:|#|mailto:)\.?/?([^)\s]+)\)", lambda m: f"]({blob}/{m.group(1)})", t)
    return t if t.rstrip(")\"'").endswith((".", "!", "?")) else t + "."


def first_release(version, es):
    """True when no earlier CHANGELOG entry was published (a dated "(pre-release)" or "(release)" below this version):
    the first published release has no earlier version to install over or to fix."""
    key = lambda v: tuple(int(x) for x in v.split("."))
    return not any(release_version.valid(v) and key(v) < key(version) and e["date"] and e["note"] in ("pre-release", "release")
                   for v, e in es.items())


def carried(version, es):
    """Items of the versions just below `version` that were tagged but never released ("(tagged, not released)"), newest
    first, up to the last published one: their changes reach players only with this release, so its notes list them."""
    key = lambda v: tuple(int(x) for x in v.split("."))
    out = []
    for v in sorted((v for v in es if release_version.valid(v) and key(v) < key(version)), key=key, reverse=True):
        if es[v]["note"] != "tagged, not released":
            break
        out += es[v]["items"]
    return out


def notes(version, entry, first=False):
    blob = f"{REPO}/blob/v{version}"
    new = [sentence(t, blob) for s, t in entry["items"] if s in NEW_SECTIONS or not s]
    fixed = [sentence(t, blob) for s, t in entry["items"] if s == "Fixed"]
    major = int(version.split(".")[0])
    kind = "a pre-release" if major == 0 else "a release"
    # One bullet per item: 0.1.2's dozen items ran into one 6 KB paragraph as prose. The first published release lists
    # its fixes as part of what it does, not as fixes of an unpublished version.
    bullets = lambda items: "\n".join(f"- {t}" for t in items)
    if first:
        lists = [f"New in {version}:\n{bullets(new + fixed)}"]
    else:
        lists = ([f"New in {version}:\n{bullets(new)}"] if new else []) + ([f"Fixed:\n{bullets(fixed)}"] if fixed else [])
    over = [] if first else [
        "If you have an earlier version, install this one over it: run the new setup and pick the same folder. The first "
        "start then translates and builds the game again where this version changes how it is built."]
    return "\n\n".join([
        f"Project Pyrrhus {version}, {kind}: {STATUS}, see [docs/RELEASE-CRITERIA.md]({blob}/docs/RELEASE-CRITERIA.md).",
        *lists,
        *over,
        f"See [CHANGELOG.md]({blob}/CHANGELOG.md) for the full list.",
        "Windows installer (Project-Pyrrhus-setup.exe, recommended) and portable zip. You need your own Killzone 2 disc "
        "dump (US, BCUS98116), the 1.29 update and a decrypted EBOOT made from your own copy; none of them is included "
        f"or downloaded. What each must contain: [docs/GETTING-FILES.md]({blob}/docs/GETTING-FILES.md). SHA-256 sums: "
        "SHA256SUMS (and the .sha256 files). See the README for what it does and what goes online.",
    ]) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tag", help="the release tag, vX.Y.Z")
    g.add_argument("--preview", metavar="X.Y.Z", help="dry run: the version's entry, else [Unreleased]")
    ap.add_argument("--out", help="write the notes here (default: standard output)")
    ap.add_argument("--root", default=str(ROOT), help="repository root (either layout)")
    a = ap.parse_args(argv)
    version = release_version.from_tag(a.tag) if a.tag else (a.preview if release_version.valid(a.preview) else None)
    if version is None:
        print(f"release_notes: {a.tag or a.preview!r} is not {'vX.Y.Z' if a.tag else 'X.Y.Z'}", file=sys.stderr)
        return 2
    p = changelog_path(a.root)
    if not p.is_file():
        print(f"release_notes: no {p.name} at {p.parent}", file=sys.stderr)
        return 1
    es = entries(p.read_text(encoding="utf-8"))
    e = es.get(version)
    if a.preview and (e is None or not e["items"]):
        e = es.get("Unreleased") or e
    if e is None:
        print(f"release_notes: CHANGELOG.md has no entry for {version}; write it (bump_version.py turns [Unreleased] "
              "into the release's entry)", file=sys.stderr)
        return 1
    if a.tag and not (e["date"] and e["note"] in ("pre-release", "release")):
        print(f"release_notes: the CHANGELOG entry for {version} is not a release ({e['note'] or 'no date'})",
              file=sys.stderr)
        return 1
    if not e["items"]:
        print(f"release_notes: the CHANGELOG entry for {version} lists nothing", file=sys.stderr)
        return 1
    body = notes(version, dict(e, items=e["items"] + carried(version, es)), first_release(version, es))
    if a.out:
        out = pathlib.Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
