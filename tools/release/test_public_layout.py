#!/usr/bin/env python3
"""Host test: the host tests that read public pages pass in the exported layout too. The private tree keeps
README.md, docs/ and .github/ in public/; tools/export-public.sh puts them at the root of the public repository, where
a test that opened public/README.md failed on a clean public clone (the 2026-11-26 gate: 132 of 134).
  - an export-layout fixture (a temporary folder: installer/, tools/release/ and port/kz2/main.cpp from git, and
    every tracked file under public/ at its path without public/, as export-public.sh copies them) runs
    test_recomplauncher.py and test_support_package.py: both PASS;
  - public_layout.public_path: public/<rel> in this tree, <rel> in the fixture; the fixture has no public/ folder
    (negative control: a test that still opened public/... would fail there);
  - no other tools/release test names a "public/" page path directly (they use public_layout or recomp_card.pages_dir).
In the public repository (no public/ folder) it runs the two tests in place. No game data. Exit 0 = PASS.

    python3 tools/release/test_public_layout.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import public_layout  # noqa: E402

fails = []
TESTS = ("test_recomplauncher.py", "test_support_package.py")


def check(ok, msg, detail=""):
    print(("ok   " if ok else "FAIL ") + msg + ("" if ok else f"\n     {str(detail)[:900]}"))
    if not ok:
        fails.append(msg)


def tracked(*paths):
    r = subprocess.run(["git", "-C", REPO, "ls-files", "-z", "--", *paths], capture_output=True, check=True)
    return [p for p in r.stdout.decode("utf-8").split("\0") if p]


env = {k: v for k, v in os.environ.items() if k != "RECOMPLAUNCHER"}
if public_layout.layout(REPO) == "public":
    # run in the public repository itself (it is the export layout): the two tests directly
    check(not os.path.exists(os.path.join(REPO, "public"))
          and public_layout.public_path(REPO, "README.md") == os.path.join(REPO, "README.md"),
          "this tree is the public layout: README.md at the root")
    for t in TESTS:
        r = subprocess.run([sys.executable, os.path.join(HERE, t)], cwd=REPO, env=env,
                           capture_output=True, text=True, timeout=600)
        check(r.returncode == 0, f"public layout: {t} passes", (r.stdout + r.stderr)[-900:])
    print("test_public_layout: PASS" if not fails else f"test_public_layout: FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)

check(public_layout.public_path(REPO, "README.md") == os.path.join(REPO, "public", "README.md"),
      "this tree: public pages in public/")

with tempfile.TemporaryDirectory() as tmp:
    exp = os.path.join(tmp, "project-pyrrhus")
    for f in tracked("installer", "tools/release", "port/kz2/main.cpp"):
        if os.path.isfile(os.path.join(REPO, f)):
            os.makedirs(os.path.dirname(os.path.join(exp, f)), exist_ok=True)
            shutil.copy2(os.path.join(REPO, f), os.path.join(exp, f))
    for f in tracked("public"):
        d = f[len("public/"):]
        if os.path.isfile(os.path.join(REPO, f)):
            os.makedirs(os.path.dirname(os.path.join(exp, d)) or exp, exist_ok=True)
            shutil.copy2(os.path.join(REPO, f), os.path.join(exp, d))
    check(not os.path.exists(os.path.join(exp, "public")) and os.path.isfile(os.path.join(exp, "README.md"))
          and public_layout.layout(exp) == "public"
          and public_layout.public_path(exp, "docs/TROUBLESHOOTING.md") == os.path.join(exp, "docs", "TROUBLESHOOTING.md"),
          "export-layout fixture: README.md and docs/ at the root, no public/ folder")
    for t in TESTS:
        r = subprocess.run([sys.executable, os.path.join(exp, "tools", "release", t)], cwd=exp, env=env,
                           capture_output=True, text=True, timeout=600)
        check(r.returncode == 0, f"export layout: {t} passes", (r.stdout + r.stderr)[-900:])

bad = []
for n in sorted(os.listdir(HERE)):
    if n.startswith("test_") and n.endswith(".py") and n != os.path.basename(__file__):
        src = open(os.path.join(HERE, n), encoding="utf-8").read()
        # a read of this checkout's public pages by their private path (fixtures that build a synthetic repo are fine)
        if re.search(r"""\b(REPO|ROOT)\s*,\s*["']public["']""", src) or re.search(r"""\bread\(["']public/""", src) or \
                re.search(r"""\b(REPO|ROOT)\s*,\s*["']public/""", src):
            bad.append(n)
check(not bad, "no release test opens a public/ page path directly", bad)
print("test_public_layout: PASS" if not fails else f"test_public_layout: FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
