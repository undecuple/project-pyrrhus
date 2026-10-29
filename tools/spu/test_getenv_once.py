#!/usr/bin/env python3
"""Host test for patch 7003: a hot-path getenv() must stay cached.

Builds the patched toolkit in a scratch dir (tools/ps3recomp-patched.sh with KZ2_PATCHED_DIR), then for every
(file, NAME) that patch 7003 converted to PS3_GETENV_ONCE("NAME") checks that the patched file has no raw
getenv("NAME") left (a per-job / per-task / per-exit / per-file-op / per-FIFO-tick lookup costs the CRT
environment lock and a scan of every variable each time; ps3recomp issue 243). Also checks the macro header
and that the hot SPURS job path (spurs_job.c, spu_lifted_job.h) has no raw getenv at all outside static caches.
Needs no game data and no network."""
import os, re, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PATCH = os.path.join(ROOT, "port", "patches", "7003-getenv-once-hot-paths.patch")


def converted():
    out, cur = set(), None
    for l in open(PATCH, errors="replace"):
        if l.startswith("+++ b/"):
            cur = l[6:].strip()
        elif cur and l.startswith("+") and not l.startswith("+++"):
            for n in re.findall(r'PS3_GETENV_ONCE\("([A-Z0-9_]+)"\)', l):
                out.add((cur, n))
    return out


def main():
    pairs = converted()
    assert len(pairs) >= 40, f"patch 7003 converts too few sites ({len(pairs)})"
    # The scratch tree must be inside the repository: ps3recomp-patched.sh passes it to `git apply --directory` as a
    # relative path, and a path out of the repository (the system temp folder) is refused. A clean checkout (CI) has no
    # work/ yet, so create it.
    scratch = os.path.join(ROOT, "work", "spu")
    os.makedirs(scratch, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as td:
        pt = os.path.join(td, "pt")
        # relative (git apply --directory), with "/": bash reads a Windows "\" as an escape
        env = dict(os.environ, KZ2_PATCHED_DIR=os.path.relpath(pt, ROOT).replace(os.sep, "/"))
        subprocess.run(["bash", os.path.join(ROOT, "tools", "ps3recomp-patched.sh")], cwd=ROOT, env=env, check=True,
                       stdout=subprocess.DEVNULL)
        assert os.path.exists(os.path.join(pt, "include", "ps3emu", "env_once.h")), "env_once.h missing"
        bad = []
        for f, n in sorted(pairs):
            if f.endswith("env_once.h"):
                continue
            txt = open(os.path.join(pt, f), errors="replace").read()
            if any(re.search(r'(?<![A-Z_])getenv\("%s"\)' % n, l) and not re.search(r'<\s*0', l) for l in txt.split("\n")):
                bad.append(f"{f}: raw getenv(\"{n}\")")
        for f in ("runtime/spu/spurs_job.c", "runtime/spu/spu_lifted_job.h"):
            for i, l in enumerate(open(os.path.join(pt, f), errors="replace"), 1):
                if re.search(r'(?<![A-Z_])getenv\(', l) and not re.search(r'<\s*0|== *-', l):
                    bad.append(f"{f}:{i}: uncached getenv on the job path")
        if bad:
            print("\n".join(bad)); sys.exit(1)
    print(f"ok: {len(pairs)} (file, variable) sites stay cached")


main()
