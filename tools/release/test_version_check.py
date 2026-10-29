#!/usr/bin/env python3
"""Host test for tools/release/version_check.py. Never touches the network: a local HTTP server on 127.0.0.1 serves a
fake GitHub releases list, and a closed loopback port stands in for being offline. Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_version_check.py

Cases: version ordering (MAJOR.MINOR.PATCH only); the newest release of the list by version (drafts and suffixed tags
skipped, pre-releases counted); a suffixed --current refused; a newer release gives status=newer, exit
1, the release page and the setup asset; the same version gives current/0; the request carries only User-Agent and
Accept (no cookie, no auth) and no query string; offline gives status=offline, exit 3 and exactly one log line;
an HTTP error and a non-JSON answer are handled without a traceback; --result-file holds the VERSION line; the URL
rule refuses plain http off the loopback.
"""
import contextlib
import http.server
import io
import json
import os
import pathlib
import shutil
import socket
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import version_check as vc  # noqa: E402

FAILS = []
SEEN = []
ANSWERS = {}


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"  {detail}"[:600]))
    if not cond:
        FAILS.append(what)


class Fake(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
        code, body = ANSWERS.get(self.path, (404, b"{}"))
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def run(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            rc = vc.main(args, out=buf)
        except SystemExit as e:
            rc = e.code
    return rc, buf.getvalue()


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    for k in [k for k in os.environ if k.lower() in ("http_proxy", "https_proxy", "all_proxy")]:
        del os.environ[k]                     # the loopback server must be reached directly
    check(vc.newer("v1.2.0", "1.1.9") and not vc.newer("0.1.0", "0.1.0") and vc.newer("0.10.0", "0.9.9")
          and not vc.newer("v0.9.0", "1.0.0") and not vc.newer("garbage", "1.0.0") and vc.newer("1.0.0", "garbage")
          and vc.parse_version("1.0.0-rc1") is None and vc.parse_version("1.1") is None
          and vc.parse_version("v0.1.0") == (0, 1, 0), "version ordering (MAJOR.MINOR.PATCH only, no suffixes)")
    check(vc.allowed_url(vc.DEFAULT_URL) and vc.allowed_url("http://127.0.0.1:9/x")
          and not vc.allowed_url("http://example.com/x") and not vc.allowed_url("ftp://x/y"), "URL rule")
    check(vc.DEFAULT_URL == "https://api.github.com/repos/undecuple/project-pyrrhus/releases?per_page=30",
          "default URL: the releases list (releases/latest never returns a pre-release)")
    lst = [{"tag_name": "v0.3.0", "draft": True, "prerelease": True},
           {"tag_name": "v0.2.1-rc1", "prerelease": True},
           {"tag_name": "v0.1.1", "prerelease": True, "html_url": "u011"},
           {"tag_name": "v0.2.0", "prerelease": True, "html_url": "u020"},
           {"tag_name": "nightly", "prerelease": True},
           {"tag_name": "v0.1.0", "prerelease": False}]
    pick = vc.pick_release(lst)
    check(pick is not None and pick["tag_name"] == "v0.2.0", "newest by version: drafts, suffixed and odd tags "
          "skipped, pre-releases counted, list order ignored", pick)
    check(vc.pick_release([]) is None and vc.pick_release([{"tag_name": "v1.0.0", "draft": True}]) is None
          and vc.pick_release({"tag_name": "v0.1.0"})["tag_name"] == "v0.1.0", "empty, drafts only, single object")

    rel = {"tag_name": "v0.2.0", "prerelease": True,
           "html_url": "https://github.com/undecuple/project-pyrrhus/releases/tag/v0.2.0",
           "assets": [{"name": "Project-Pyrrhus-setup.exe", "browser_download_url": "https://dl/x/Project-Pyrrhus-setup.exe"},
                      {"name": "Project-Pyrrhus-setup.exe.sha256", "browser_download_url": "https://dl/x/s.sha256"},
                      {"name": "Project-Pyrrhus-portable.zip", "browser_download_url": "https://dl/x/p.zip"}]}
    ANSWERS["/latest"] = (200, json.dumps([{"tag_name": "v0.3.0", "draft": True}, rel,
                                           {"tag_name": "v0.1.0", "html_url": "old"}]).encode())
    ANSWERS["/broken"] = (200, b"<html>not json</html>")
    ANSWERS["/notag"] = (200, b'{"message": "Not Found"}')
    ANSWERS["/ratelimited"] = (403, b'{"message": "API rate limit exceeded"}')
    srv = http.server.HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    tmp = tempfile.mkdtemp(prefix="kz2-vcheck-")
    try:
        log = os.path.join(tmp, "setup.log")
        res = os.path.join(tmp, "result.txt")
        rc, out = run(["--current", "0.1.0", "--url", base + "/latest", "--result-file", res, "--log", log])
        check(rc == 1 and "status=newer" in out and "latest=v0.2.0" in out and rel["html_url"] in out
              and "setup=https://dl/x/Project-Pyrrhus-setup.exe" in out, "newer release found", out)
        with open(res, encoding="utf-8") as f:
            check(f.read().strip() == out.strip(), "result file holds the VERSION line")
        path, hdr = SEEN[-1]
        extra = set(hdr) - {"user-agent", "accept", "host", "accept-encoding", "connection"}
        check(path == "/latest" and hdr.get("user-agent") == vc.USER_AGENT and not extra
              and "cookie" not in hdr and "authorization" not in hdr, "request sends nothing but UA/Accept", hdr)

        rc, out = run(["--current", "0.2.0", "--url", base + "/latest", "--json"])
        j = json.loads(out)
        check(rc == 0 and j["status"] == "current" and j["sha256_url"] == "https://dl/x/s.sha256", "up to date", out)

        open(log, "w").close()
        rc, out = run(["--current", "0.1.0", "--url", f"http://127.0.0.1:{closed_port()}/latest", "--log", log,
                       "--timeout", "3"])
        with open(log, encoding="utf-8") as f:
            lines = f.read().splitlines()
        check(rc == 3 and "status=offline" in out and len(lines) == 1 and "status=offline" in lines[0],
              "offline = exit 3 and one log line", f"{out} {lines}")

        rc, out = run(["--current", "0.1.0", "--url", base + "/ratelimited"])
        check(rc == 3 and "status=offline" in out, "HTTP error handled", out)
        rc, out = run(["--current", "0.1.0", "--url", base + "/broken"])
        check(rc == 3 and "status=error" in out, "non-JSON answer handled", out)
        rc, out = run(["--current", "0.1.0", "--url", base + "/notag"])
        check(rc == 3 and "status=error" in out, "answer without tag handled", out)

        saved = os.path.join(tmp, "latest.json")
        with open(saved, "w", encoding="utf-8") as f:
            json.dump(rel, f)
        rc, out = run(["--current", "0.3.0", "--url", pathlib.Path(saved).as_uri()])
        check(rc == 0 and "status=current" in out, "file:// saved answer, older release = current", out)

        rc, out = run(["--current", "0.1.0-dev", "--url", base + "/latest"])
        check(rc == 2, "a suffixed --current is refused (usage)", out)
        n = len(SEEN)
        rc, out = run(["--current", "0.1.0", "--url", "http://example.com/latest"])
        check(rc == 2 and len(SEEN) == n, "plain http off the loopback is refused before any request", out)
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"version_check: {'PASS' if not FAILS else 'FAIL ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
