#!/usr/bin/env python3
"""The one rule for user folders in public text, shared by the export scrub (tools/export-public.sh runs
`user_folders.py --check EXPORT`) and the pre-push check (tools/release/gate_check.py imports USER_FOLDERS).
Standard library only. The three patterns are adapted from jsp-vs-ex tools/ci/repo_checks.py
(github.com/Tsamiuy/jsp-vs-ex, v0.7.0; MIT, Copyright (c) 2026 Tsamiuy, Copyright (c) 2026 undecuple); the placeholder
convention is this port's.

A user folder is C:\\Users\\<name>, a home folder <drive>:\\home\\<name> or \\\\server\\home\\<name>, or /Users/<name>.
Its <name> must be one of the placeholders, never a name that could be a person's:
  - a name that begins with "example" (any case): "example", "Example User", "Example José", "EXAMPLE.DOE", "examplep".
    This is the convention for test fixtures and docs: a fixture that needs spaces, non-ASCII letters, a UNC home or
    any other shape writes it after "Example" ("C:\\Users\\Example José\\...", "\\\\fs01\\home\\example.doe");
  - the system folders: Public, Default, All Users (C:\\Users), Shared (/Users), and Proton's steamuser;
  - a written placeholder: <name>, %USERNAME%, $USER, {home} (begins with <, %, $ or {);
  - a single character ("C:\\Users\\a"): no one is named by it, and it keeps the short-folder fixtures (a label such as
    %USERPROFILE% longer than the folder it replaces).
Anything else ("C:\\Users\\Alice", "Z:\\home\\jdoe") is a finding in both checks.

    python3 tools/release/user_folders.py --check DIR    # every text file below DIR; one line per hit, exit 1 on any
"""
import os
import re
import sys

# a system name or a single character ends the folder name ("C:\\Users\\a)" in a comment is still one letter)
PLACEHOLDER = (r"(?!(?i:example)|(?:Public|Default|All Users|Shared|steamuser)(?![\w.-])|[<%$\{]"
               r"|\w(?![\w.-]))")
# The rule's own files hold the real-looking names that must fail (the negative cases of its tests): both checks skip
# them for this rule only (as the export scrub exempts AGENTS.md from its tool-name rule).
RULE_FILES = ("tools/release/user_folders.py", "tools/release/test_user_folders.py", "tools/release/test_gate_check.py")
SEP = r"(?:\\{1,2}|/)+"
USER_FOLDERS = [
    ("private path C:\\Users\\<name>", r"(?i:\b[A-Z]:" + SEP + r"Users" + SEP + r")" + PLACEHOLDER + r"[^\\/\s\"'`<>|]+"),
    ("private path Z:\\home\\<name>",
     r"(?i:(?:\b[A-Z]:|\\\\[\w.-]+)" + SEP + r"home" + SEP + r")" + PLACEHOLDER + r"[A-Za-z_][\w.-]*"),
    ("private path /Users/<name>", r"(?<![\w/:])/Users/" + PLACEHOLDER + r"[A-Za-z][\w.-]*/"),
]
COMPILED = [(n, re.compile(p)) for n, p in USER_FOLDERS]


def hits(text):
    """[(name, matched text)] for every user folder in text whose name is not a placeholder."""
    return [(n, m.group(0)) for n, p in COMPILED for m in p.finditer(text)]


def check_tree(root):
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            p = os.path.join(d, f)
            if os.path.relpath(p, root).replace(os.sep, "/") in RULE_FILES:
                continue
            try:
                with open(p, "rb") as fh:
                    raw = fh.read()
            except OSError:
                continue
            if b"\0" in raw[:8192]:
                continue
            text = raw.decode("utf-8", "replace")
            for n, h in hits(text):
                out.append(f"{os.path.relpath(p, root)}: {n}: {h}")
    return out


def main(argv):
    if len(argv) != 2 or argv[0] != "--check":
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    found = check_tree(argv[1])
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
