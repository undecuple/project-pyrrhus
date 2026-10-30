#!/usr/bin/env python3
"""Host test for tools/release/website.py on a small fixture (no game data, no work/): the page is generated, --check
passes on a fresh page and fails on a stale page, a missing key feature row, a missing requirements section and a
missing style.css; Markdown in the data is escaped and links become GitHub URLs (requirements links from docs/); the
headline follows the "Full campaign" row; the screens come from the public collection (a missing one fails); the
version and download block follows installer/VERSION and its CHANGELOG entry (released, not released, missing) inside
marker spans; the changelog box and the release news come from the whole CHANGELOG (newest first, capped on the page
only, internal wording skipped, [Unreleased] left out), checked on the real CHANGELOG too; both layouts; the lint
refuses scripts, event handlers and outside resources other than Google Fonts; the forbidden third-party service name
appears nowhere. From Project Helghast tools/release/test_website.py, first and later versions (same author, MIT).
Exit 0 = PASS.

    python3 tools/release/test_website.py
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
import website  # noqa: E402

FORBIDDEN = "rew" + "ired"   # spelled in two parts so that a repo-wide grep for the name stays empty
HEAD = "kind\tarea\tfeature\tdetail\tstatus\tdone\tdays\tlane\tevidence\tnote\n"
REQ = """# Requirements

## What you need from your own copy of the game

| Item | Required | Details |
|---|---|---|
| **Disc** | yes | dump it (D4) |
| **Update** | yes | 1.29 |

## Hardware to play

| | Minimum (estimate) | Recommended (estimate) | Basis |
|---|---|---|---|
| **CPU** | 6 cores | 8 cores | threads |

## Other
"""


CHANGELOG = """# Changelog

## [Unreleased]

### Added
- Not out yet.

## [0.2.0] - 2026-11-02 (pre-release)

### Added
- Newer thing
- Secret, see D56 and /home/x
- """ + "very long line " * 12 + """

### Fixed
- A fix.

## [0.1.0] - 2026-10-28 (tagged, not released)

The first tag.
"""


def fixture(root, playable="not yet", drop_key=None, req=REQ, version="0.2.0", changelog=CHANGELOG, shots=True,
            layout="public"):
    rows = [("ps3", "Campaign", website.PLAYABLE_ROW, "9 levels", playable, "0", "1", "x", "ev", "")]
    for i, k in enumerate(website.KEY_ROWS):
        if k != drop_key and k != website.PLAYABLE_ROW:
            rows.append(("port" if i % 3 == 0 else "ps3", "Campaign" if i % 2 else "Graphics", k,
                         "PS3 does **it** `x` <script>x</script> see [notes](docs/a.md)", "partial", "0.5", "1", "x", "ev", ""))
    rows.append(("port", "Extras", "Mouse aim", "", "not yet", "0", "1", "x", "ev", ""))
    rows.append(("port", "Extras", "Hidden", "", "not yet", "0", "1", "x", "ev", "BACKLOG later"))
    (root / "docs").mkdir(parents=True)
    (root / "docs/features.tsv").write_text("# fixture\n" + HEAD + "".join("\t".join(r) + "\n" for r in rows))
    if req is not None:
        (root / "docs/requirements.md").write_text(req)
    pub = root / "public" if layout == "public" else root
    (pub / "site").mkdir(parents=True)
    (pub / "site/style.css").write_text("body{}\n")
    (pub / "docs/screenshots").mkdir(parents=True)
    for i, (name, _t, _c) in enumerate(website.SHOTS if shots else ()):
        (pub / "docs/screenshots" / f"2026101{i}_{name}.png").write_bytes(b"png")
    (root / "installer").mkdir()
    (root / "installer/VERSION").write_text(version + "\n")
    if changelog is not None:
        (pub / "CHANGELOG.md").write_text(changelog)


def run(*args):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        rc = website.main(list(args))
    return rc, err.getvalue()


def main():
    fails = []

    def expect(cond, what):
        if not cond:
            fails.append(what)

    with tempfile.TemporaryDirectory() as t:
        root = pathlib.Path(t) / "ok"
        fixture(root)
        expect(run("--root", str(root), "--check")[0] == 1, "check passes with no page")
        expect(run("--root", str(root))[0] == 0, "generate fails")
        rc, err = run("--root", str(root), "--check")
        expect(rc == 0, f"check fails on a fresh page: {err}")
        page = (root / website.PAGE).read_text()
        expect("Partly playable" in page, "headline not 'Partly playable' (campaign row not yet, in-level play row partial)")
        expect("<script>" not in page and "&lt;script&gt;" in page, "detail text not escaped")
        expect(f'href="{website.REPO}/blob/main/docs/a.md"' in page, "relative link not a GitHub URL")
        expect("<strong>it</strong>" in page and "<code>x</code>" in page, "inline Markdown not rendered")
        expect('src="../assets/banner.png"' in page and "../assets/banner@2x.png 2x" in page, "banner missing")
        expect("(D4)" not in page and "<td>6 cores</td>" in page and "Basis" not in page, "requirements table wrong")
        expect(page.count("<figure class=\"tile") == len(website.SHOTS) and page.count("lead-tile") == 1
               and page.index(website.SHOTS[-1][1]) < page.index(website.SHOTS[0][1]),
               "screens: one tile each, newest (by file date) first")
        expect('<!-- version --><a href="' + website.REPO + '/releases/tag/v0.2.0">v0.2.0</a><!-- /version -->' in page
               and "<b><!-- version -->v0.2.0<!-- /version --></b>" in page
               and "Download v0.2.0</a><!-- /version -->" in page, "version and download block (marker spans)")
        expect(page.count("<!-- version -->") == page.count("<!-- /version -->") == 3
               and all("\n" not in m for m in page.split("<!-- version -->")[1:] for m in [m.split("<!-- /version -->")[0]]),
               "three one-line marker spans")
        expect("<h2>v0.2.0</h2>" in page and "<h2>v0.1.0</h2>" in page and "The first tag." in page
               and "Not out yet" not in page and "D56" not in page, "release news: dated entries, [Unreleased] and internal lines left out")
        expect(page.index("<h2>v0.2.0</h2>") < page.index("<h2>v0.1.0</h2>"), "release news newest first")
        expect(not re.search(r"\b[Vv]ersion\s+v?\d+\.\d+\.\d+", page), "no 'version X' prose (test_version_agree would read it)")
        expect("Hidden" not in page, "BACKLOG row shown")
        expect(f'href="{website.HELGHAST}"' in page, "Project Helghast link missing")
        expect('class="clog"' in page and 'class="todo"' in page and page.count('class="divider"') == 2,
               "changelog box, objectives box or dividers missing")
        expect(not website.lint(page), f"lint on the generated page: {website.lint(page)}")
        expect(FORBIDDEN not in page.lower(), "page names the forbidden service")
        expect(FORBIDDEN not in open(os.path.join(HERE, "website.py")).read().lower(), "website.py names it")
        (root / website.PAGE).write_text(page + "x")
        expect(run("--root", str(root), "--check")[0] == 1, "stale page passes")
        (root / website.PAGE).write_text(page.replace("<body>", "<body><script>x</script>"))
        expect(run("--root", str(root), "--check")[0] == 1, "injected script passes")
        (root / website.PAGE).write_text(page.replace("<body>", '<body><img src="https://example.com/a.png">'))
        expect(run("--root", str(root), "--check")[0] == 1, "outside resource passes")

        root = pathlib.Path(t) / "playable"
        fixture(root, playable="works")
        run("--root", str(root))
        expect("<strong>Playable</strong>" in (root / website.PAGE).read_text(), "headline ignores the campaign row")

        root = pathlib.Path(t) / "unreleased"
        fixture(root, version="0.1.0")
        expect(run("--root", str(root))[0] == 0, "generate fails for a tagged, unreleased version")
        page = (root / website.PAGE).read_text()
        expect("No release yet" in page and "<!-- version -->" not in page and "Download" not in page,
               "an unreleased version shows no download")
        root = pathlib.Path(t) / "noentry"
        fixture(root, version="0.3.0")
        rc, err = run("--root", str(root))
        expect(rc == 1 and "no entry for installer/VERSION 0.3.0" in err, "a version with no CHANGELOG entry passes")

        root = pathlib.Path(t) / "rootlayout"   # the public repository: public/'s files at the root
        fixture(root, layout="root")
        expect(run("--root", str(root))[0] == 0 and (root / "site/index.html").is_file() and not (root / "public").exists(),
               "root layout: the page is written to site/index.html")
        expect("<h2>v0.2.0</h2>" in (root / "site/index.html").read_text(), "root layout: CHANGELOG.md read at the root")
        expect(run("--root", str(root), "--check")[0] == 0, "root layout: --check passes")

        for name, kw in (("nokey", {"drop_key": website.KEY_ROWS[1]}), ("noreq", {"req": None}),
                         ("badreq", {"req": REQ.replace("## Hardware to play", "## Hardware")})):
            root = pathlib.Path(t) / name
            fixture(root, **kw)
            expect(run("--root", str(root))[0] == 1, f"{name}: generate passes")
        root = pathlib.Path(t) / "nocss"
        fixture(root)
        run("--root", str(root))
        (root / "public/site/style.css").unlink()
        expect(run("--root", str(root), "--check")[0] == 1, "missing style.css passes")

        root = pathlib.Path(t) / "noshot"
        fixture(root, shots=False)
        expect(run("--root", str(root))[0] == 1, "missing screenshot passes")

        # the changelog box: the whole file read, newest first, capped only on the page
        root = pathlib.Path(t) / "ok"
        got = website.changelog(root, 10)
        texts = [x for _, _, x in got]
        expect(got[0] == ("2026-11-02", "0.2.0", "Newer thing") and got[-1] == ("2026-10-28", "0.1.0", "The first tag."),
               f"changelog newest first with section dates and versions: {got}")
        expect(not any("D56" in x or "/home" in x or "Not out yet" in x for x in texts), "internal or unreleased lines shown")
        expect(all(len(x) <= 122 for x in texts) and any(x.endswith("...") for x in texts), "long lines not capped")
        expect(len(website.changelog(root, 2)) == 2 and len(website.changelog(root, None)) == 4, "n caps the box only")
        expect([e["version"] for e in website.entries(root)] == ["Unreleased", "0.2.0", "0.1.0"], "entries() reads every entry")

    # the real CHANGELOG, read whole: every heading is an entry, and the oldest dated entry reaches changelog(None)
    real = pathlib.Path(HERE).parents[1]
    cl = website.pub(real, website.CHANGELOG).read_text(encoding="utf-8")
    heads = re.findall(r"^## \[([^\]]+)\]", cl, re.M)
    es = website.entries(real)
    expect(heads and [e["version"] for e in es] == heads, f"real CHANGELOG: entries() misses headings {heads}")
    dated = [e for e in es if e["date"]]
    expect(dated and website.changelog(real, None)[-1][1] == dated[-1]["version"],
           "real CHANGELOG: the oldest dated entry is in the whole list")
    vf = real / website.VERSION_FILE
    expect(website.release_of(real, vf.read_text().strip()) is not None, "real CHANGELOG has an entry for installer/VERSION")

    for bad in ('<script src="a.js"></script>', '<img src="x.png" onerror="x()">', '<a href="javascript:x()">a</a>',
                '<img src="https://example.com/a.png">', '<link rel="stylesheet" href="https://cdn.example/x.css">',
                '<link href="https://fonts.googleapis.com.evil.example/x">', '<img src="file:///C:/a.png">'):
        expect(website.lint(bad), f"lint misses {bad}")
    for good in ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X">',
                 '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>', '<img src="../assets/a.png">',
                 f'<a href="{website.REPO}/issues">issues</a>'):
        expect(not website.lint(good), f"lint refuses {good}")

    if fails:
        print("FAIL test_website:\n  - " + "\n  - ".join(fails))
        return 1
    print("PASS test_website (generate, check, negative controls, screens, version block, changelog and news, both layouts, 7 lint refusals)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
