#!/usr/bin/env python3
"""One-shot, opt-in check for a newer release of the port. From Project Helghast tools/release/version_check.py. Standard library only,
Python 3.8+, Windows and Linux.

    version_check.py --current X.Y.Z [--url URL] [--timeout S] [--json] [--result-file FILE] [--log FILE]

It makes one anonymous HTTPS GET of the repository's releases list (DEFAULT_URL; releases/latest skips pre-releases,
and every release is one until v1.0.0) and takes the newest vMAJOR.MINOR.PATCH tag that is not a draft, by version,
with only a User-Agent and an Accept header: no cookies, no token, nothing about the player, the machine or the game. It runs only when the player
asked for it (the installer's "Check now" button, the portable zip's question, or the launcher when the player ticked
"Check for new versions"); nothing is downloaded here: a newer release is reported with its page, and the download
starts only from the player's click on that page (or a later, separate download step).

Output, one line (also written to --result-file, which the Inno wizard reads):
  VERSION status=newer|current|offline|error current=<x> latest=<tag or -> url=<release page or -> setup=<asset url or ->
          sha256=<the setup's .sha256 asset url or -> (the launcher's "Update this installation" uses the last two)
Offline or blocked = status=offline, one line in --log (appended), no error dialog anywhere.
Exit 0 = up to date, 1 = a newer release exists, 2 = usage (also a --current that is not MAJOR.MINOR.PATCH),
3 = offline or an unusable answer.

--url accepts https:// (any host), and http:// only on the loopback (the host test's local server) or file:// (a
saved answer); the tests never touch the network.
"""
import argparse
import datetime
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# The releases list, not releases/latest: GitHub's "latest" never returns a pre-release, and every release is a
# pre-release until v1.0.0. Newest first by creation date; the newest by version is picked here.
DEFAULT_URL = "https://api.github.com/repos/undecuple/project-pyrrhus/releases?per_page=30"
USER_AGENT = "project-pyrrhus-version-check"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
STRICT = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def parse_version(s):
    """'v1.2.3' / '1.2.3' -> (1, 2, 3); anything else (a suffix, missing parts, garbage) -> None. Tags are
    vMAJOR.MINOR.PATCH with no suffix, so a suffixed tag is not a release of ours."""
    s = (s or "").strip()
    m = STRICT.fullmatch(s[1:] if s[:1] in ("v", "V") else s)
    return tuple(int(x) for x in m.groups()) if m else None


def newer(latest, current):
    lv, cv = parse_version(latest), parse_version(current)
    if lv is None:
        return False
    return cv is None or lv > cv


def pick_release(answer):
    """The newest usable release of a releases-list answer (a single release object is taken as a list of one):
    drafts and tags that are not vMAJOR.MINOR.PATCH are skipped, pre-releases count. -> release dict or None."""
    items = answer if isinstance(answer, list) else [answer] if isinstance(answer, dict) else []
    best = None
    for r in items:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        v = parse_version(r.get("tag_name"))
        if v is not None and (best is None or v > best[0]):
            best = (v, r)
    return best[1] if best else None


def allowed_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme == "https" and u.hostname:
        return True
    if u.scheme == "http" and u.hostname in LOOPBACK:
        return True
    return u.scheme == "file"


def fetch(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    # A plain opener: no cookie jar, no auth handler, proxies from the system settings only.
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(1 << 20).decode("utf-8"))


def pick_setup(assets):
    """The installer asset (…setup….exe) and its checksum file, if the release has them."""
    exe = next((a for a in assets if re.search(r"setup.*\.exe$", a.get("name", ""), re.I)), None)
    if not exe:
        return None, None
    sha = next((a for a in assets if a.get("name", "").lower() in
                (exe["name"].lower() + ".sha256", exe["name"].lower().rsplit(".", 1)[0] + ".sha256")), None)
    return exe.get("browser_download_url"), (sha or {}).get("browser_download_url")


def check(current, url=DEFAULT_URL, timeout=10.0):
    """-> dict(status, current, latest, url, setup, sha256_url, detail)."""
    res = {"status": "error", "current": current, "latest": None, "url": None, "setup": None, "sha256_url": None,
           "detail": ""}
    try:
        j = fetch(url, timeout)
    except urllib.error.HTTPError as e:
        res["status"], res["detail"] = "offline", f"HTTP {e.code}"
        return res
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        res["status"], res["detail"] = "offline", str(getattr(e, "reason", e))
        return res
    except ValueError as e:
        res["detail"] = f"not JSON ({e})"
        return res
    j = pick_release(j)
    if j is None:
        res["detail"] = "no release with a vMAJOR.MINOR.PATCH tag in the answer"
        return res
    tag = j["tag_name"]
    res["latest"], res["url"] = tag, j.get("html_url")
    res["setup"], res["sha256_url"] = pick_setup(j.get("assets") or [])
    res["status"] = "newer" if newer(tag, current) else "current"
    return res


def line(r):
    return (f"VERSION status={r['status']} current={r['current']} latest={r['latest'] or '-'} "
            f"url={r['url'] or '-'} setup={r['setup'] or '-'} sha256={r['sha256_url'] or '-'}")


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--current", required=True)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--result-file", default="")
    ap.add_argument("--log", default="")
    a = ap.parse_args(argv)
    if parse_version(a.current) is None:
        print(f"--current {a.current!r}: expected MAJOR.MINOR.PATCH with no suffix", file=sys.stderr)
        return 2
    if not allowed_url(a.url):
        print(f"refusing --url {a.url}: https, loopback http or file only", file=sys.stderr)
        return 2
    r = check(a.current, a.url, a.timeout)
    text = line(r)
    print(json.dumps(r, indent=1) if a.json else text, file=out)
    if a.result_file:
        with open(a.result_file, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    if a.log:
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        detail = f" ({r['detail']})" if r["detail"] else ""
        with open(a.log, "a", encoding="utf-8") as f:
            f.write(f"# {stamp} version check: {text}{detail}\n")
    return {"current": 0, "newer": 1}.get(r["status"], 3)


if __name__ == "__main__":
    sys.exit(main())
