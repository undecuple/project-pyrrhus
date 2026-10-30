#!/usr/bin/env python3
"""Host test for tools/release/release_notes.py (no game data, no network): the notes for a tag have the fixed shape
(first line, "New in", the upgrade line, the CHANGELOG pointer, the fixed paragraph saying what the player needs and
that none of it is included), the Added/Changed items come before "Fixed:", wrapped items are joined, links (relative ones in items too)
point at the tag's files; a tag with no entry, an entry that is not a release ("(tagged, not released)", [Unreleased]) or an
empty entry is refused; a bad tag is a usage error; --preview falls back to [Unreleased]; both layouts (public/CHANGELOG.md
and CHANGELOG.md at the root) are read; the real CHANGELOG's every entry parses and the README says the status word.
Exit 0 = PASS.

    python3 tools/release/test_release_notes.py
"""
import contextlib
import io
import os
import pathlib
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import release_notes  # noqa: E402

CL = """# Changelog

Intro text.

## [Unreleased]

### Added
- Next thing.

## [0.2.0] - 2030-01-02 (pre-release)

### Added
- A new thing, with a [link](docs/A.md)
- A long item that wraps
  onto a second line.

### Fixed
- A fixed thing.

### Changed
- A changed thing.

## [0.1.1] - 2030-01-01 (pre-release)

## [0.1.0] - 2029-12-31 (tagged, not released)

The tag marks a build.
"""
FAILS = []


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"\n     {str(detail)[:500]}"))
    if not cond:
        FAILS.append(what)


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = release_notes.main(list(args))
        except SystemExit as e:   # argparse usage errors
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


def main():
    for layout in ("public", "root"):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            d = root / "public" if layout == "public" else root
            d.mkdir(exist_ok=True)
            (d / "CHANGELOG.md").write_text(CL, encoding="utf-8")
            # The first published release (only a tagged, never released version below it): no install-over line,
            # and its fixes are part of what it does, not fixes of an unpublished version.
            first = root / "first"
            first.mkdir()
            (first / "CHANGELOG.md").write_text("# Changelog\n\n## [0.1.1] - 2030-01-01 (pre-release)\n\n### Added\n"
                                                "- A new thing.\n\n### Fixed\n- A fixed thing.\n\n"
                                                "## [0.1.0] - 2029-12-31 (tagged, not released)\n\nThe tag marks a build.\n",
                                                encoding="utf-8")
            rc, out, err = run("--tag", "v0.1.1", "--root", str(first))
            fp = out.strip().split("\n\n")
            check(rc == 0 and len(fp) == 4 and "earlier version" not in out and "Fixed:" not in out
                  and fp[1] == "New in 0.1.1:\n- A new thing.\n- A fixed thing.",
                  f"{layout}: the first published release has no install-over line and no Fixed label", (rc, err, fp))
            # A version tagged but never released hands its items to the next release's notes.
            carry = root / "carry"
            carry.mkdir()
            (carry / "CHANGELOG.md").write_text("# Changelog\n\n## [0.1.4] - 2030-01-03 (pre-release)\n\n### Fixed\n"
                                                "- The build fix.\n\n## [0.1.3] - 2030-01-02 (tagged, not released)\n\n"
                                                "### Added\n- A carried thing.\n\n### Fixed\n- A carried fix.\n\n"
                                                "## [0.1.2] - 2030-01-01 (pre-release)\n\n### Added\n- An old thing.\n",
                                                encoding="utf-8")
            rc, out, err = run("--tag", "v0.1.4", "--root", str(carry))
            check(rc == 0 and "- A carried thing." in out and "- A carried fix." in out and "An old thing" not in out
                  and out.index("- The build fix.") < out.index("- A carried fix."),
                  f"{layout}: an unreleased tagged version's items carry into the next release, the released one's do not",
                  (rc, err, out))
            rc, out, err = run("--tag", "v0.2.0", "--root", t)
            paras = out.strip().split("\n\n")
            check(rc == 0 and len(paras) == 6, f"{layout}: v0.2.0 gives six paragraphs", (rc, err, paras))
            if len(paras) == 6:
                check(paras[0] == "Project Pyrrhus 0.2.0, a pre-release: partly playable, see [docs/RELEASE-CRITERIA.md]"
                      "(https://github.com/undecuple/project-pyrrhus/blob/v0.2.0/docs/RELEASE-CRITERIA.md).",
                      f"{layout}: first line", paras[0])
                check(paras[1] == "New in 0.2.0:\n- A new thing, with a [link](https://github.com/undecuple/project-pyrrhus/blob/v0.2.0/docs/A.md).\n- A long item that wraps onto a "
                      "second line.\n- A changed thing.", f"{layout}: one bullet per new item", paras[1])
                check(paras[2] == "Fixed:\n- A fixed thing.", f"{layout}: the fixes as their own list, last", paras[2])
                check(paras[3].startswith("If you have an earlier version, install this one over it: "),
                      f"{layout}: the upgrade line", paras[3])
                check(paras[4] == "See [CHANGELOG.md](https://github.com/undecuple/project-pyrrhus/blob/v0.2.0/"
                      "CHANGELOG.md) for the full list.", f"{layout}: the CHANGELOG pointer", paras[4])
                for want in ("Windows installer", "portable zip", "BCUS98116", "1.29 update",
                             "decrypted EBOOT made from your own copy", "none of them is included or downloaded",
                             "SHA256SUMS", "What goes online: [docs/PRIVACY.md]", "blob/v0.2.0/docs/GETTING-FILES.md"):
                    check(want in paras[5], f"{layout}: the fixed paragraph says {want}", paras[5])
            check(not re.search(r"\b(PM|lanes?|rounds?|D\d\d)\b", out), f"{layout}: public wording only", out)
            out_file = root / "o" / "notes.md"
            rc, _, _ = run("--tag", "v0.2.0", "--root", t, "--out", str(out_file))
            check(rc == 0 and out_file.read_bytes().endswith(b"\n") and b"\r" not in out_file.read_bytes(),
                  f"{layout}: --out writes LF text")
            for tag, why in (("v0.3.0", "no entry"), ("v0.1.0", "tagged, not released"), ("v0.1.1", "empty entry")):
                rc, out, err = run("--tag", tag, "--root", t)
                check(rc == 1 and not out, f"{layout}: {tag} refused ({why})", (rc, err))
            for bad in ("0.2.0", "v0.2", "v0.2.0-rc1", "latest"):
                check(run("--tag", bad, "--root", t)[0] == 2, f"{layout}: tag {bad!r} is a usage error")
            rc, out, _ = run("--preview", "0.3.0", "--root", t)
            check(rc == 0 and "New in 0.3.0:\n- Next thing." in out, f"{layout}: --preview uses [Unreleased]", out)
            rc, out, _ = run("--preview", "0.1.1", "--root", t)
            check(rc == 0 and "Next thing." in out, f"{layout}: --preview of an empty entry uses [Unreleased]", out)
            rc, out, _ = run("--preview", "0.2.0", "--root", t)
            check(rc == 0 and "A changed thing." in out, f"{layout}: --preview prefers the version's own entry", out)

    # the real tree: every entry of the whole CHANGELOG parses, every dated one carries a date and a note
    real = pathlib.Path(HERE).parents[1]
    p = release_notes.changelog_path(real)
    text = p.read_text(encoding="utf-8")
    es = release_notes.entries(text)
    heads = re.findall(r"^## \[([^\]]+)\]", text, re.M)
    check(heads and list(es) == list(dict.fromkeys(heads)), "real CHANGELOG: every heading is an entry", (heads, list(es)))
    for v, e in es.items():
        if v != "Unreleased":
            check(e["date"] and e["note"], f"real CHANGELOG: [{v}] has a date and a note", e)
    readme = p.parent / "README.md"
    check(release_notes.STATUS in readme.read_text(encoding="utf-8").lower(),
          f"the README says '{release_notes.STATUS}' (the notes' status word)")
    print("FAILED" if FAILS else "PASS test_release_notes")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
