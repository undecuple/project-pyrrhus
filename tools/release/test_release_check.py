#!/usr/bin/env python3
"""Host test: release_check.py on fixture release JSONs and small fake assets (no network, no game data).

Adapted from Project Helghast's test_release_check.py (the Killzone 3 PC port, same author, MIT). Also checks that
release_check.py's asset list is the one release.yml publishes and that its version is installer/VERSION, and that
release-check.yml stays read-only.

    python3 tools/release/test_release_check.py
"""
import copy
import hashlib
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import release_check as rc  # noqa: E402
import release_version  # noqa: E402

ROOT = release_version.REPO
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import public_layout  # noqa: E402
GH = public_layout.public_path(ROOT, ".github")   # public/.github here, .github in the public repository
V = release_version.read(ROOT)
TAG = "v" + V
GOOD = {"tag_name": TAG, "name": TAG, "draft": False, "prerelease": release_version.is_prerelease(V),
        "body": f"Project Pyrrhus {V}, a pre-release. SHA256SUMS.",
        "assets": [{"name": n} for n in rc.expected_assets(V)]}
fails = []


def expect(label, errs, needle=None):
    ok = (not errs) if needle is None else any(needle in e for e in errs)
    if not ok:
        fails.append(f"{label}: got {errs}")


def variant(**kw):
    r = copy.deepcopy(GOOD)
    r.update(kw)
    return r


expect("good", rc.check_release(GOOD, TAG, V))
expect("missing asset", rc.check_release(variant(assets=GOOD["assets"][:-1]), TAG, V), "missing asset " + rc.SUMS)
expect("extra asset", rc.check_release(variant(assets=GOOD["assets"] + [{"name": "kz2.exe"}]), TAG, V),
       "unexpected asset kz2.exe")
expect("duplicate asset", rc.check_release(variant(assets=GOOD["assets"] + GOOD["assets"][:1]), TAG, V), "duplicate")
expect("wrong tag", rc.check_release(variant(tag_name="v9.9.9"), "v9.9.9", V), "is not v" + V)
expect("tag_name differs", rc.check_release(variant(tag_name="v9.9.9"), TAG, V), "tag_name")
expect("draft", rc.check_release(variant(draft=True), TAG, V), "draft")
expect("prerelease flag flipped", rc.check_release(variant(prerelease=not GOOD["prerelease"]), TAG, V), "prerelease")
old = dict(tag_name="v0.1.13", name="v0.1.13", body="0.1.13", assets=[{"name": n} for n in rc.expected_assets("0.1.13")])
expect("0.1.13 good as a pre-release", rc.check_release(variant(prerelease=True, **old), "v0.1.13", "0.1.13"))
expect("0.1.13 not flagged pre-release", rc.check_release(variant(prerelease=False, **old), "v0.1.13", "0.1.13"), "needs True")
new = dict(tag_name="v0.1.14", name="v0.1.14", body="0.1.14", assets=[{"name": n} for n in rc.expected_assets("0.1.14")])
expect("0.1.14 pre-release flagged (full releases from 0.1.14)",
       rc.check_release(variant(prerelease=True, **new), "v0.1.14", "0.1.14"), "needs False")
expect("0.1.14 good as a full release", rc.check_release(variant(prerelease=False, **new), "v0.1.14", "0.1.14"))
one = dict(tag_name="v1.0.0", name="v1.0.0", body="1.0.0", assets=[{"name": n} for n in rc.expected_assets("1.0.0")])
expect("1.x pre-release flagged", rc.check_release(variant(prerelease=True, **one), "v1.0.0", "1.0.0"), "needs False")
expect("1.x good", rc.check_release(variant(prerelease=False, **one), "v1.0.0", "1.0.0"))
expect("title", rc.check_release(variant(name="Release"), TAG, V), "title")
expect("body", rc.check_release(variant(body="nothing"), TAG, V), "body")

# the asset list is the one release.yml publishes (gh release create ... <files>), not a second hand-kept copy
rel_yml = open(os.path.join(GH, "workflows", "release.yml"), encoding="utf-8").read()
m = re.search(r'gh release create "\$GITHUB_REF_NAME"[^\n]*\\\n\s*([^\n]+)', rel_yml)
zip_def = re.search(r'^\s*zip="([^"]+)"', rel_yml, re.M)
if not m or not zip_def:
    fails.append("release.yml: gh release create file list or zip= not found")
else:
    # release.yml builds the next release, a full one from 0.1.14 on (the older ones are published, never rebuilt)
    VR = rc.release_version.FIRST_FULL_RELEASE if rc.release_version.is_prerelease(V) else V
    zipn = zip_def.group(1).replace("$VERSION", VR)
    files = [f.strip('"').replace("$zip", zipn) for f in m.group(1).split()]
    if files != rc.expected_assets(VR):
        fails.append(f"asset list differs from release.yml: {files} != {rc.expected_assets(VR)}")
iss = open(os.path.join(ROOT, "installer", "kz2.iss"), encoding="utf-8").read()
base = re.search(r'#define SetupBase "([^"]+)"', iss)
if not base or base.group(1) + ".exe" != rc.SETUP:
    fails.append(f"kz2.iss SetupBase {base and base.group(1)!r} is not {rc.SETUP!r} without .exe")
if "Project-Pyrrhus-<version>-Windows-x64.zip" not in open(os.path.join(HERE, "pack_zip.py"), encoding="utf-8").read() \
        or rc.zip_name("1.2.3") != "Project-Pyrrhus-1.2.3-Windows-x64.zip" \
        or rc.zip_name("0.1.14") != "Project-Pyrrhus-0.1.14-Windows-x64.zip" \
        or rc.zip_name("0.1.14") == "Project-Pyrrhus-0.1.14-portable.zip":
    fails.append("zip name differs from pack_zip.py's usage line")
# release-check.yml on an old tag: the asset it expects is the one that release had
for v, want in (("0.1.3", "Project-Pyrrhus-0.1.3-portable.zip"), ("0.1.13", "Project-Pyrrhus-0.1.13-portable.zip"),
                ("0.1.14", "Project-Pyrrhus-0.1.14-Windows-x64.zip"), ("0.2.0", "Project-Pyrrhus-0.2.0-Windows-x64.zip")):
    if rc.zip_name(v) != want or want not in rc.expected_assets(v):
        fails.append(f"zip name for {v}: {rc.zip_name(v)} (expected assets {rc.expected_assets(v)}), want {want}")


def write_assets(d, tamper=None):
    zipn = rc.zip_name(V)
    sums = []
    for n, data in ((rc.SETUP, b"fake setup"), (zipn, b"fake zip")):
        with open(os.path.join(d, n), "wb") as f:
            f.write(data)
        h = hashlib.sha256(data).hexdigest()
        sums.append(f"{h}  {n}\n")
        own = "0" * 64 if tamper == n + ".sha256" else h
        with open(os.path.join(d, n + ".sha256"), "w") as f:
            f.write(f"{own}  {n}\n")
    if tamper == "sums":
        sums[0] = "1" * 64 + f"  {rc.SETUP}\n"
    if tamper == "badline":
        sums.append("not a hash line\n")
    with open(os.path.join(d, rc.SUMS), "w") as f:
        f.writelines(sums)
    if tamper == "file":
        with open(os.path.join(d, zipn), "wb") as f:
            f.write(b"changed")


for label, tamper, needle in (("hashes good", None, None), ("file changed", "file", "file is"),
                              ("SHA256SUMS wrong", "sums", "SHA256SUMS entry"),
                              ("SHA256SUMS bad line", "badline", "bad line"),
                              (".sha256 wrong", rc.zip_name(V) + ".sha256", "disagree")):
    with tempfile.TemporaryDirectory() as d:
        write_assets(d, tamper)
        expect(label, rc.check_hashes(d, V), needle)
with tempfile.TemporaryDirectory() as d:
    expect("assets not downloaded", rc.check_hashes(d, V), "not downloaded")

# links, in the public layout (root) and in this repository's (public/)
for layout in ("", "public"):
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, layout, "site"))
        for p, t in (("README.md", f"[x](https://e.invalid/releases/tag/{TAG})"), ("site/index.html", "no link")):
            with open(os.path.join(d, layout, p), "w") as f:
                f.write(t)
        errs = rc.check_links(d, TAG)
        expect(f"link missing in site ({layout or 'root'})", errs, "site")
        expect(f"README link ok ({layout or 'root'})", [e for e in errs if "README" in e])
# this checkout's own pages link the current version's tag (bump_version keeps them)
expect("this checkout's README and site link releases/tag/" + TAG, rc.check_links(ROOT, TAG))

# the command line: a good release file exits 0, a draft exits 1; the version comes from installer/VERSION at --root
with tempfile.TemporaryDirectory() as d:
    for name, rel in (("good.json", GOOD), ("draft.json", variant(draft=True))):
        with open(os.path.join(d, name), "w") as f:
            json.dump(rel, f)
    if rc.main(["--tag", TAG, "--release", os.path.join(d, "good.json")]) != 0:
        fails.append("cli good release did not exit 0")
    if rc.main(["--tag", TAG, "--release", os.path.join(d, "draft.json")]) != 1:
        fails.append("cli draft release did not exit 1")
    fake = os.path.join(d, "fake")
    os.makedirs(os.path.join(fake, "installer"))
    with open(os.path.join(fake, "installer", "VERSION"), "w") as f:
        f.write("9.9.9\n")
    if rc.main(["--tag", TAG, "--release", os.path.join(d, "good.json"), "--root", fake]) != 1:
        fails.append("cli: a root whose installer/VERSION differs from the tag did not exit 1")
    with open(os.path.join(fake, "installer", "VERSION"), "w") as f:
        f.write("0.1.0-rc1\n")
    if rc.main(["--tag", TAG, "--release", os.path.join(d, "good.json"), "--root", fake]) != 1:
        fails.append("cli: a suffixed installer/VERSION did not exit 1")

# release-check.yml stays read-only (test_workflows.py checks pins, permissions and checkout credentials)
wf = open(os.path.join(GH, "workflows", "release-check.yml"), encoding="utf-8").read()
code = "\n".join(line for line in wf.splitlines() if not line.lstrip().startswith("#"))
if "write" in code:
    fails.append("release-check.yml: a write permission or command")
for bad in ("gh release create", "gh release edit", "gh release upload", "gh release delete", "git push", "git tag",
            "upload-artifact", "--clobber"):
    if bad in code:
        fails.append(f"release-check.yml: {bad}")
if "release_check.py" not in code or "test_version_agree.py" not in code or "sha256sum -c SHA256SUMS" not in code:
    fails.append("release-check.yml: release_check.py, test_version_agree.py and sha256sum -c are run")
if not re.search(r"^on:\n  release:\n    types: \[published\]\n  workflow_dispatch:", wf, re.M):
    fails.append("release-check.yml: runs on a published release or a dispatch only")

if fails:
    print("test_release_check: FAIL\n  " + "\n  ".join(fails))
    sys.exit(1)
print("test_release_check: PASS")
