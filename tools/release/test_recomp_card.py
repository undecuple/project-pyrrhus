#!/usr/bin/env python3
"""Host test for tools/release/recomp_card.py: the current card passes in both layouts, and each check (C1-C7) fails on
a card or page broken on purpose; --write fixes status and the /releases link. Temporary copies only, no game data.

    python3 tools/release/test_recomp_card.py
"""
import contextlib
import io
import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REAL = HERE.parents[1]
sys.path.insert(0, str(HERE))
import recomp_card  # noqa: E402

FAILS = []


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"\n     {str(detail)[:500]}"))
    if not cond:
        FAILS.append(what)


def fixture(base, layout):
    """A minimal repository with the real card and pages; layout 'public' (pages in public/) or 'root' (at the root)."""
    repo = base / layout
    pages = repo / "public" if layout == "public" else repo
    (pages / "docs").mkdir(parents=True)
    src = REAL / "public" if (REAL / "public/README.md").is_file() else REAL
    for rel in (".recomp.json", "README.md", "docs/RELEASE-CRITERIA.md", "docs/SCREENSHOTS.md"):
        shutil.copy2(src / rel, pages / rel)
    if layout == "public":
        (repo / "docs").mkdir()
        (repo / "docs/features.tsv").write_text("area\tfeature\n")   # FEATURES.md is generated from it at export
    else:
        (pages / "docs/FEATURES.md").write_text("# Features\n")
    (repo / "installer").mkdir()
    if (REAL / "installer/kz2.iss").is_file():
        shutil.copy2(REAL / "installer/kz2.iss", repo / "installer/kz2.iss")
    return repo, pages


def load(pages):
    return json.loads((pages / ".recomp.json").read_text(encoding="utf-8"))


def save(pages, card):
    (pages / ".recomp.json").write_text(json.dumps(card, indent=2), encoding="utf-8")


def fails(repo, code):
    return [l for l in recomp_card.check(repo) if l.startswith(code)]


def negative(base, layout):
    repo, pages = fixture(base, layout)
    check(recomp_card.check(repo) == [], f"{layout}: the card as shipped passes", recomp_card.check(repo))

    def broken(code, what, edit):
        shutil.copy2(pages / ".recomp.json", base / "keep.json")
        c = load(pages)
        edit(c)
        save(pages, c)
        got = fails(repo, code)
        check(bool(got), f"{layout}: {what} -> {code}", recomp_card.check(repo))
        shutil.copy2(base / "keep.json", pages / ".recomp.json")

    broken("C1", "an unknown field", lambda c: c.update(banana=1))
    broken("C1", "a version number", lambda c: c.update(version="0.1.1"))
    broken("C1", "an unknown original field", lambda c: c["original"].update(build="x"))
    check(not fails(repo, "C1") and recomp_card.check(repo) == [], f"{layout}: restored")
    broken("C2", "a bad wikidata id", lambda c: c.update(wikidata="Q0"))
    broken("C2", "a wikidata id without Q", lambda c: c.update(wikidata="12345"))
    broken("C3", "an http maintainer link", lambda c: c["maintainers"][0].update(link="http" + ":" + "//github.com/undecuple"))
    broken("C3", "an insecure link", lambda c: c["links"][0].update({"u" + "rl": "http" + ":" + "//example.org/"}))
    broken("C4", "a status outside the schema", lambda c: c.update(status="almost"))
    broken("C4", "released while the README says partly playable", lambda c: c.update(status="released"))
    broken("C4", "playable against the README badge", lambda c: c.update(status="playable"))
    broken("C5", "a link to a missing file", lambda c: c["links"].append(
        {"label": "x", "url": "https://github.com/undecuple/project-pyrrhus/blob/main/docs/NOPE.md"}))
    broken("C6", "another serial", lambda c: c["original"].update(serial="BCES00081"))
    broken("C6", "another revision", lambda c: c["original"].update(revision="1.01"))
    broken("C7", "no releases link", lambda c: c.update(links=[l for l in c["links"] if not l["url"].endswith("/releases")]))
    # the pages side of C4
    crit = pages / "docs/RELEASE-CRITERIA.md"
    keep = crit.read_text(encoding="utf-8")
    crit.write_text(keep.replace("no playable release", "a playable release").replace("waits for every point", "met every point"),
                    encoding="utf-8")
    check(bool(fails(repo, "C4")), f"{layout}: criteria no longer pending while the card says in-progress -> C4")
    c = load(pages)
    c["status"] = "released"
    save(pages, c)
    rd = pages / "README.md"
    rk = rd.read_text(encoding="utf-8")
    rd.write_text(rk.replace("status-partly%20playable", "status-released"), encoding="utf-8")
    check(not fails(repo, "C4"), f"{layout}: released agrees once README and criteria say so", recomp_card.check(repo))
    crit.write_text(keep, encoding="utf-8")
    check(bool(fails(repo, "C4")), f"{layout}: released while the criteria are pending -> C4")
    rd.write_text(rk, encoding="utf-8")
    shutil.copy2(base / "keep.json", pages / ".recomp.json")
    # C1: the card does not parse
    (pages / ".recomp.json").write_text("{not json", encoding="utf-8")
    check(bool(fails(repo, "C1")), f"{layout}: a card that does not parse -> C1")
    shutil.copy2(base / "keep.json", pages / ".recomp.json")
    # C5: FEATURES.md is only excused where its source exists
    if layout == "public":
        (repo / "docs/features.tsv").unlink()
        check(bool(fails(repo, "C5")), f"{layout}: FEATURES.md without docs/features.tsv -> C5")
    # C6: the setup file must name the serial
    iss = repo / "installer/kz2.iss"
    if iss.is_file():
        iss.write_text("; nothing\n", encoding="utf-8")
        check(bool(fails(repo, "C6")), f"{layout}: kz2.iss without the serial -> C6")


def write_mode(base):
    repo, pages = fixture(base, "public")
    c = load(pages)
    c["status"] = "playable"
    c["links"] = [l for l in c["links"] if not l["url"].endswith("/releases")]
    save(pages, c)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = recomp_card.main(["--repo", str(repo), "--write"])
    c = load(pages)
    check(rc == 0 and c["status"] == "in-progress" and c["links"][-1]["url"].endswith("/releases"),
          "--write restores the status from the README badge and adds the /releases link", c)
    before = (pages / ".recomp.json").read_text(encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        recomp_card.main(["--repo", str(repo), "--write"])
    check((pages / ".recomp.json").read_text(encoding="utf-8") == before, "--write twice changes nothing")
    c = load(pages)
    c["wikidata"] = "bad"
    save(pages, c)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = recomp_card.main(["--repo", str(repo), "--write"])
    check(rc == 1 and load(pages)["wikidata"] == "bad", "--write does not paper over a bad wikidata id")


def main():
    real = recomp_card.check(REAL)
    check(real == [], "the card in this tree passes", real)
    with tempfile.TemporaryDirectory() as td:
        for i, layout in enumerate(("public", "root")):
            b = pathlib.Path(td) / str(i)
            b.mkdir()
            negative(b, layout)
        b = pathlib.Path(td) / "w"
        b.mkdir()
        write_mode(b)
    print("FAILED" if FAILS else "PASS test_recomp_card")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
