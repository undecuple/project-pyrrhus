#!/usr/bin/env python3
"""Where a public page is in this checkout: the private tree keeps the public pages in public/ (README.md,
docs/, .github/ ...); the public repository (tools/export-public.sh) has them at its root. Host tests that read a
public page go through public_path so they pass in both layouts (test_public_layout.py runs them in an
export-layout copy). Standard library only.

    public_path(repo, "README.md") -> <repo>/public/README.md or <repo>/README.md
"""
import os


def layout(repo):
    """'private' when repo/public/README.md exists, else 'public' (the exported repository)."""
    return "private" if os.path.isfile(os.path.join(repo, "public", "README.md")) else "public"


def public_path(repo, rel):
    """The path of the public page rel (relative to the public root, e.g. "docs/TROUBLESHOOTING.md")."""
    return os.path.join(repo, "public", rel) if layout(repo) == "private" else os.path.join(repo, rel)
