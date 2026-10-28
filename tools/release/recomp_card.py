#!/usr/bin/env python3
"""Check (and optionally fix) the recomp.fyi card public/.recomp.json against the repository.

    python3 tools/release/recomp_card.py [--write] [--repo DIR]

Written from the spec in the project's recomp metadata notes ("Keeping .recomp.json and releases current by script");
the release-tool conventions (layout mapping, one-line report, exit codes) follow bump_version.py. No network.

Checks (each failure is one line; exit 1 if any):
  C1 the card parses and holds only schema v1 fields (private extensions start with "x-"), no version number;
  C2 "wikidata", when present, matches ^Q[1-9][0-9]*$;
  C3 every maintainers[].link and links[].url starts with https://;
  C4 "status" is a schema value and agrees with the README status badge and docs/RELEASE-CRITERIA.md ("released"
     only when the criteria file no longer says there is no playable release; pre-releases stay in-progress or playable);
  C5 every link into this repository (https://github.com/<owner>/<repo>/blob|tree/<branch>/PATH) names a file that
     exists, in this repository (pages under public/) and in the public repository (pages at the root); docs/FEATURES.md
     is generated at export from docs/features.tsv and counts as present where that file is;
  C6 original.serial and original.revision equal what the setup accepts: firstrun_check.TITLE_ID (also named in
     installer/kz2.iss) and the 1.29 update (firstrun_check.UPDATE_APP_VER);
  C7 a link to <repository>/releases is present (so the card needs no edit per release).
--write fixes what follows from one source: status from the README badge, and the /releases link (added when
missing). Everything else is reported, never rewritten.
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

FIELDS = {"$schema", "game", "wikidata", "system", "type", "original", "project", "status", "targets", "toolchain",
          "approach", "maintainers", "links", "help", "tags", "notes"}
ORIGINAL_FIELDS = {"region", "revision", "serial", "sha1"}
STATUSES = ("exploring", "in-progress", "playable", "released", "complete", "paused", "unknown")
WIKIDATA = re.compile(r"^Q[1-9][0-9]*$")
REPO_LINK = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/(?:blob|tree)/[^/]+/(.+?)(?:#.*)?$")
REPO_ROOT_LINK = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/?$")
# README badge text -> the card status it stands for
BADGES = {"partly playable": "in-progress", "in progress": "in-progress", "early": "in-progress",
          "playable": "playable", "released": "released"}
GENERATED = {"docs/FEATURES.md": "docs/features.tsv"}   # exported page -> its source in the private tree


def pages_dir(repo):
    """(layout, dir of the public pages): the private tree keeps them in public/, the public repository at its root."""
    p = pathlib.Path(repo) / "public"
    return ("public", p) if (p / "README.md").is_file() else ("root", pathlib.Path(repo))


def setup_values(repo):
    import firstrun_check
    app = firstrun_check.UPDATE_APP_VER           # "01.29"
    major, minor = app.split(".")
    return firstrun_check.TITLE_ID, f"{int(major)}.{minor}"


def badge_status(readme):
    m = re.search(r"img\.shields\.io/badge/status-([^-\s)]+)-", readme)
    if not m:
        return None
    return BADGES.get(m.group(1).replace("%20", " ").lower())


def criteria_says_unreleased(text):
    return bool(re.search(r"no playable release|waits for every point", text))


def repo_has(repo, pages, layout, rel):
    """True when the repo path (as written in a public link) exists in this layout."""
    if (pages / rel).exists():
        return True
    src = GENERATED.get(rel)
    return bool(src and layout == "public" and (pathlib.Path(repo) / src).is_file())


def check(repo, card_text=None):
    """List of failure lines for the repository at REPO (empty = card is current)."""
    repo = pathlib.Path(repo)
    layout, pages = pages_dir(repo)
    bad = []
    path = pages / ".recomp.json"
    try:
        card = json.loads(card_text if card_text is not None else path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"C1 {path.name} does not parse: {e}"]
    if not isinstance(card, dict):
        return ["C1 the card is not a JSON object"]
    for k in card:
        if k not in FIELDS and not k.startswith("x-") and k != "$schema":
            bad.append(f"C1 field {k!r} is not in schema v1 (private extensions start with x-)")
    if "version" in card:
        bad.append("C1 the card holds no version (link /releases instead)")
    orig = card.get("original")
    if not isinstance(orig, dict):
        bad.append("C6 original is missing or not an object")
        orig = {}
    for k in orig:
        if k not in ORIGINAL_FIELDS:
            bad.append(f"C1 original.{k} is not in schema v1")
    if "wikidata" in card and not (isinstance(card["wikidata"], str) and WIKIDATA.match(card["wikidata"])):
        bad.append(f"C2 wikidata {card['wikidata']!r} does not match ^Q[1-9][0-9]*$")

    urls = [(f"maintainers[{i}].link", m.get("link")) for i, m in enumerate(card.get("maintainers") or [])
            if isinstance(m, dict) and "link" in m]
    urls += [(f"links[{i}].url", l.get("url")) for i, l in enumerate(card.get("links") or []) if isinstance(l, dict)]
    for where, u in urls:
        if not (isinstance(u, str) and u.startswith("https://")):
            bad.append(f"C3 {where} {u!r} is not an https:// link")

    status = card.get("status")
    readme = (pages / "README.md").read_text(encoding="utf-8") if (pages / "README.md").is_file() else ""
    crit = (pages / "docs/RELEASE-CRITERIA.md")
    crit = crit.read_text(encoding="utf-8") if crit.is_file() else ""
    if status not in STATUSES:
        bad.append(f"C4 status {status!r} is not one of {', '.join(STATUSES)}")
    else:
        want = badge_status(readme)
        if want is None:
            bad.append("C4 README.md has no recognised status badge to compare with")
        elif want != status:
            bad.append(f"C4 status {status!r} but the README badge says {want!r}")
        if status in ("released", "complete") and criteria_says_unreleased(crit):
            bad.append(f"C4 status {status!r} but docs/RELEASE-CRITERIA.md says the criteria are not met")
        if status in ("in-progress", "exploring", "playable") and crit and not criteria_says_unreleased(crit):
            bad.append(f"C4 status {status!r} but docs/RELEASE-CRITERIA.md no longer says the release is pending")

    releases = False
    for where, u in urls:
        if not isinstance(u, str):
            continue
        m = REPO_LINK.match(u)
        if m:
            rel = m.group(3)
            if not repo_has(repo, pages, layout, rel):
                bad.append(f"C5 {where} points at {rel}, which does not exist")
        if re.match(r"^https://github\.com/[^/]+/[^/]+/releases/?$", u):
            releases = True
    if not releases:
        bad.append("C7 no link to <repository>/releases")

    try:
        serial, rev = setup_values(repo)
    except Exception as e:   # noqa: BLE001
        return bad + [f"C6 cannot read the setup's values: {e}"]
    if orig.get("serial") != serial:
        bad.append(f"C6 original.serial {orig.get('serial')!r} but the setup accepts {serial!r}")
    if not str(orig.get("revision", "")).startswith(rev):
        bad.append(f"C6 original.revision {orig.get('revision')!r} does not start with the setup's update {rev!r}")
    iss = repo / "installer/kz2.iss"
    if iss.is_file() and serial not in iss.read_text(encoding="utf-8", errors="replace"):
        bad.append(f"C6 installer/kz2.iss does not name {serial}")
    return bad


def write(repo):
    """Fix status (from the README badge) and the /releases link; return True when the card changed."""
    repo = pathlib.Path(repo)
    _, pages = pages_dir(repo)
    path = pages / ".recomp.json"
    card = json.loads(path.read_text(encoding="utf-8"))
    new = json.loads(json.dumps(card))
    want = badge_status((pages / "README.md").read_text(encoding="utf-8"))
    if want:
        new["status"] = want
    links = new.setdefault("links", [])
    if not any(re.match(r"^https://github\.com/[^/]+/[^/]+/releases/?$", l.get("url", "")) for l in links):
        base = next((REPO_LINK.match(l.get("url", "")) for l in links if REPO_LINK.match(l.get("url", ""))), None)
        if base:
            links.append({"label": "Releases", "url": f"https://github.com/{base.group(1)}/{base.group(2)}/releases"})
    new.pop("version", None)
    if new == card:
        return False
    # one link per line, as the card is laid out by hand
    lines = ",\n".join("    " + json.dumps(l, ensure_ascii=False) for l in new["links"])
    keys = list(new)
    out = ["{"]
    for i, k in enumerate(keys):
        comma = "," if i < len(keys) - 1 else ""
        if k == "links":
            out.append('  "links": [\n' + lines + "\n  ]" + comma)
        elif k == "original":   # the layout of the hand-written card: object on indented lines, the rest on one line
            inner = ",\n".join(f"    {json.dumps(x)}: {json.dumps(y, ensure_ascii=False)}" for x, y in new[k].items())
            out.append('  "original": {\n' + inner + "\n  }" + comma)
        else:
            out.append(f"  {json.dumps(k)}: {json.dumps(new[k], ensure_ascii=False)}{comma}")
    path.write_text("\n".join(out) + "\n}\n", encoding="utf-8")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=str(ROOT), help="repository root (default: this one)")
    ap.add_argument("--write", action="store_true", help="fix status and the /releases link first")
    a = ap.parse_args(argv)
    if a.write:
        try:
            print("recomp_card: card rewritten" if write(a.repo) else "recomp_card: nothing to write")
        except (OSError, ValueError) as e:
            print(f"recomp_card: cannot write: {e}", file=sys.stderr)
            return 1
    bad = check(a.repo)
    for line in bad:
        print("recomp_card: " + line, file=sys.stderr)
    print("recomp_card: " + ("FAIL" if bad else "card is current"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
