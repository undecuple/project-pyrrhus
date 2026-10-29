#!/usr/bin/env python3
"""Host test for the GitHub workflows and dependabot.yml (public/.github in this repository, .github in the public
tree). Text checks only (standard library, no YAML parser, no network):
  - every `uses:` of a third-party action is pinned to a full 40-hex commit SHA with its version in a comment;
  - every workflow sets top-level `permissions:` and every job its own; no secret other than the run's own token
    (github.token / GITHUB_TOKEN) is read; checkouts keep no credentials;
  - each file names where it was adapted from (Project Helghast);
  - pages.yml: both jobs run only when the repository variable PAGES_ENABLED is "true"; the page's ../assets images
    are staged;
  - release.yml: a tag push or workflow_dispatch only; the tag must be v + installer/VERSION; the draft pre-release
    command is `gh release create TAG --draft --prerelease --verify-tag --title TAG --notes-file`, with no
    --clobber, upload, edit or delete; only the publish job can write and it is skipped on workflow_dispatch;
    SHA256SUMS and .sha256 files; the notes are generated from the tag's CHANGELOG entry (release_notes.py) before
    the build and passed to publish;
  - issue-labels.yml: every rule's heading is the first field label of one issue form and every label it may add is
    one the forms use; with node on PATH the rules block itself is run on sample issues;
  - release-check.yml: a published release or a dispatch only, every permission read-only (its logic is tested by
    test_release_check.py);
  - dependabot.yml covers github-actions.
Adapted from Project Helghast's workflow checks (the Killzone 3 PC port, same author, MIT).

    python3 tools/release/test_workflows.py
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
GH = os.path.join(ROOT, "public", ".github")
if not os.path.isdir(GH):
    GH = os.path.join(ROOT, ".github")          # the public tree ships public/ at its root
WF = os.path.join(GH, "workflows")
FAILS = []
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"\n     {str(detail)[:600]}"))
    if not cond:
        FAILS.append(what)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def jobs(text):
    """-> {job name: its text} for a workflow's top-level `jobs:` block (two-space indented job keys)."""
    m = re.search(r"^jobs:\n", text, re.M)
    if not m:
        return {}
    body, out = text[m.end():], {}
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\s*\n", body, flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        out[parts[i]] = parts[i + 1]
    return out


def test_common(files):
    for p in files:
        name = os.path.relpath(p, GH)
        t = read(p)
        check("adapted from Project Helghast" in "\n".join(t.splitlines()[:12]),
              f"{name}: header names where it was adapted from (Project Helghast)")
        if "/workflows/" not in p.replace(os.sep, "/"):
            continue
        check(re.search(r"^permissions:", t, re.M) is not None, f"{name}: top-level permissions set")
        for line in t.splitlines():
            m = USES.match(line)
            if not m or m.group(1).startswith("./"):
                continue
            ref, rest = m.group(1), m.group(2)
            ok = re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref) is not None and re.search(r"#\s*v\d", rest)
            check(bool(ok), f"{name}: {ref.split('@')[0]} pinned to a commit SHA with its version", line.strip())
        for job, body in jobs(t).items():
            check(re.search(r"^    permissions:", body, re.M) is not None, f"{name}: job {job} sets its own permissions")
        secrets = set(re.findall(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)", t)) - {"GITHUB_TOKEN"}
        check(not secrets, f"{name}: no secret beyond the run's own token", secrets)
        for m in re.finditer(r"uses: actions/checkout@\S+[^\n]*\n((?:\s{8,}[^\n]*\n)*)", t):
            check("persist-credentials: false" in m.group(1), f"{name}: checkout keeps no credentials", m.group(0))
        check("pull_request_target" not in t and "workflow_run" not in t, f"{name}: no privileged trigger")


def test_pages():
    t = read(os.path.join(WF, "pages.yml"))
    js = jobs(t)
    check(set(js) == {"build", "deploy"}, "pages.yml: build and deploy jobs", list(js))
    for job, body in js.items():
        check("if: vars.PAGES_ENABLED == 'true'" in body, f"pages.yml: {job} runs only when PAGES_ENABLED is true")
    check(re.search(r"^permissions: \{\}", t, re.M) is not None, "pages.yml: no default permissions")
    site = read(os.path.join(os.path.dirname(GH), "site", "index.html"))
    for img in sorted(set(re.findall(r'\.\./assets/([\w@.-]+\.png)', site))):
        check(f"assets/{img}" in t, f"pages.yml stages assets/{img} (the page loads it)")
    if "../docs/screenshots/" in site:
        check("cp -a docs/screenshots/. _site/docs/screenshots/" in t and "docs/screenshots/**" in t,
              "pages.yml stages docs/screenshots/ (the page shows the screens) and runs when they change")


def test_release():
    t = read(os.path.join(WF, "release.yml"))
    on = t[t.index("\non:"):t.index("\npermissions:")]
    check('tags: ["v[0-9]+.[0-9]+.[0-9]+"]' in on and "workflow_dispatch:" in on and "branches" not in on
          and "pull_request" not in on, "release.yml: runs on a vX.Y.Z tag or a dispatch only", on)
    check(re.search(r"^permissions:\n  contents: read", t, re.M) is not None, "release.yml: read-only by default")
    check("work/ffmpeg-win/include" in t, "release.yml: the FFmpeg headers reach the installer job (the first run builds against them)")
    js = jobs(t)
    writers = [j for j, b in js.items() if "contents: write" in b]
    check(writers == ["publish"], "release.yml: only the publish job can write", writers)
    pub = js.get("publish", "")
    check("if: github.event_name == 'push' && github.ref_type == 'tag'" in pub and "actions/checkout" not in pub,
          "release.yml: publish runs on tag pushes only and checks out no code")
    check("--check --tag \"$GITHUB_REF_NAME\"" in t and '[ "$GITHUB_REF_NAME" = "v$VERSION" ]' in pub,
          "release.yml: the tag must be v + installer/VERSION (build and publish)")
    cmd = re.search(r"gh release create ((?:[^\n]*\\\n)*[^\n]*)", t)
    c = cmd.group(1) if cmd else ""
    check(cmd is not None and re.match(r'"\$GITHUB_REF_NAME" --draft \$pre --verify-tag --title "\$GITHUB_REF_NAME" '
                                       r"--notes-file ", c) is not None,
          "release.yml: gh release create TAG --draft --prerelease --verify-tag --title TAG --notes-file", c)
    check('0.*) pre="--prerelease"' in t, "release.yml: a 0.x version is a pre-release")
    check(not re.search(r"--clobber|gh release (upload|edit|delete)|git (tag|push)", t),
          "release.yml: no clobber, upload, edit or delete; no tag or push")
    check("> SHA256SUMS" in t and "SHA256SUMS" in c and ".sha256" in c, "release.yml: SHA256SUMS and .sha256 files beside the assets")
    check("Text.UTF8Encoding $false" in t and "`n\"" in t, "release.yml: the setup's .sha256 is LF with no BOM")
    check("gh release view" in pub, "release.yml: an existing release is refused, never touched")
    # the notes come from the tag's CHANGELOG entry (release_notes.py, tested by test_release_notes.py); no hand text
    inst = js.get("installer", "")
    check('release_notes.py --tag "$GITHUB_REF_NAME" --out installer/Output/release-body.md' in inst
          and 'release_notes.py --preview "$VERSION"' in inst, "release.yml: the installer job writes the notes from CHANGELOG.md")
    check(inst.index("release_notes.py") < inst.index("fetch_toolchain.py"), "release.yml: the notes are checked before the build")
    check("installer/Output/release-body.md" in inst[inst.index("upload-artifact"):], "release.yml: the notes travel in the artifact")
    check("--notes-file release-body.md" in c and "test -s release-body.md" in pub and "printf" not in pub,
          "release.yml: publish uses the generated notes, never a hand-written text", c)
    check("release-body.md" not in c.split("--notes-file release-body.md", 1)[-1], "release.yml: the notes are not an asset", c)
    check("fetch_toolchain.py --check --strict" in t and "test_iss_ispp.py" in t,
          "release.yml: pinned manifest and the ISPP line check before the build")


def test_release_check():
    t = read(os.path.join(WF, "release-check.yml"))
    on = t[t.index("\non:"):t.index("\npermissions:")]
    check("release:\n    types: [published]" in on and "workflow_dispatch:" in on and "push:" not in on and
          "pull_request" not in on, "release-check.yml: runs on a published release or a dispatch only", on)
    perms = re.findall(r"^\s*(contents|actions|packages|pages|id-token|issues|pull-requests):\s*(\w+)", t, re.M)
    check(perms and all(v == "read" for _, v in perms), "release-check.yml: every permission is read", perms)


def form_fields():
    """-> {form file: (first field label, labels)} for the issue forms."""
    out = {}
    for p in sorted(glob.glob(os.path.join(GH, "ISSUE_TEMPLATE", "*.yml"))):
        t = read(p)
        first = re.search(r"^\s+label:\s*(.+?)\s*$", t, re.M)
        labels = re.search(r"^labels:\s*\[([^\]]*)\]", t, re.M)
        if first and labels:
            out[os.path.basename(p)] = (first.group(1).strip("'\""), [x.strip() for x in labels.group(1).split(",")])
    return out


def test_issue_labels():
    t = read(os.path.join(WF, "issue-labels.yml"))
    rules = re.search(r"// BEGIN rules[^\n]*\n(.*?)// END rules", t, re.S)
    check(rules is not None, "issue-labels.yml: rules block found")
    if not rules:
        return
    block = rules.group(1)
    forms = form_fields()
    headings = re.findall(r"label: '([\w-]+)', heading: '([^']+)'", block)
    allowed = re.findall(r"'([\w-]+)'", re.search(r"const ALLOWED = \[([^\]]*)\]", block).group(1))
    firsts = {f[0]: f[1] for f in forms.values()}
    for label, heading in headings:
        check(heading in firsts and label in firsts[heading],
              f"issue-labels: '{heading}' is the first field of the form labelled {label}", firsts)
    used = {lab for f in forms.values() for lab in f[1]}
    check(set(allowed) <= used | {"needs-triage"} and set(allowed) >= used,
          "issue-labels: the labels it may add are the forms' labels", (allowed, used))
    node = shutil.which("node")
    if not node:
        print("note issue-labels: node not on PATH; the rules block was not run")
        return
    cases = [[f"### {h}\n\nsome text\n\n### Port build\n\nabc", label] for label, h in headings]
    cases += [["[Bug] crash", "bug"], ["Feature request: widescreen", "enhancement"], ["Question about saves", "feedback"],
              ["Performance: slow", "performance"], ["hello", None], ["A bugfix idea", None]]
    js = block + "\n" + "const cases = " + repr(cases).replace("None", "null") + ";\n" + r"""
let bad = 0;
for (const [x, want] of cases) {
  const got = x.startsWith('###') ? typeLabelFor('x', x) : typeLabelFor(x, '');
  if (got !== want) { bad++; console.log('FAIL', JSON.stringify(x.slice(0, 40)), got, want); }
}
const crlf = typeLabelFor('x', cases[0][0].replace(/\n/g, '\r\n'));
if (crlf !== cases[0][1]) { bad++; console.log('FAIL CRLF body', crlf); }
console.log(bad ? 'FAIL' : 'PASS');
"""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "rules.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([node, p], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0 and r.stdout.strip().endswith("PASS"), "issue-labels: the rules block labels sample issues",
          r.stdout + r.stderr)


def test_dependabot():
    t = read(os.path.join(GH, "dependabot.yml"))
    check("package-ecosystem: github-actions" in t and "version: 2" in t, "dependabot.yml: github-actions updates")


def main():
    files = sorted(glob.glob(os.path.join(WF, "*.yml"))) + [os.path.join(GH, "dependabot.yml")]
    want = {"ci.yml", "codeql.yml", "pages.yml", "release.yml", "issue-labels.yml", "release-check.yml"}
    have = {os.path.basename(p) for p in files}
    check(want <= have, "workflows present: " + ", ".join(sorted(want)), sorted(have))
    test_common([p for p in files if os.path.isfile(p)])
    test_pages()
    test_release()
    test_release_check()
    test_issue_labels()
    test_dependabot()
    print(f"\n{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
