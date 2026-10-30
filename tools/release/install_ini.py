#!/usr/bin/env python3
"""kz2-install.ini, read and written line by line (the setup's [INI] section, the launcher and firstrun.py share it).

configparser rewrote the whole file on every change: it dropped the player's comments, lower-cased every key and
raised on a duplicate key, a "%" in a path (interpolation) or a file saved in the Windows ANSI code page, which under
pythonw ended the launcher without a word. This module:

  read(path)            -> Ini: get(section, key, default); sections and keys match case-insensitively, the first
                           occurrence counts (as Windows' GetPrivateProfileString, which the setup's SetIniString
                           uses); no interpolation; a missing file is an empty Ini.
  set_values(path, {(section, key): value, ...})
                        -> changes only the value part of the lines it owns: every other line (comments, blank lines,
                           unknown keys, the key's own spelling, the spaces around "=") stays as it was. A key not in
                           the file is added at the end of its section (after the section's last key), a section not
                           in the file at the end. Written to a temporary file beside it and moved over it, so a full
                           disk or a stopped start never leaves half a file.

The text is UTF-8 (with or without BOM), UTF-16 with BOM (a file Windows' profile API made Unicode), else the ANSI
code page ("mbcs" on Windows, Latin-1 elsewhere: an ANSI file never fails to read). It is written back in the
encoding it was read in, without adding a BOM (the setup's SetIniString would read a UTF-8 BOM as part of the first
section's name); an ANSI file that has to take a character outside its code page becomes UTF-8.

Any read or write failure (a locked or read-only file, a folder where the file should be) raises IniError with the
path and the reason; the callers log it and show it (launch.py) instead of ending silently.

The decode order (UTF-8 BOM, UTF-8, then the ANSI code page) is the one in Project Helghast's _ini_text (KZ3
tools/release/launch.py, Killzone 3 PC port, same author, MIT); the line-preserving writer is new here.
"""
import os
import tempfile

NAME = "kz2-install.ini"


class IniError(Exception):
    """A read or write failure of an ini file; str() names the file and the reason."""


def _ansi():
    return "mbcs" if os.name == "nt" else "latin-1"


def decode(raw):
    """-> (text, encoding to write back in)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace"), "utf-8"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace"), "utf-16"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode(_ansi(), "replace"), _ansi()


def _load(path):
    """-> (lines without line ends, encoding, newline); a missing file is empty."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return [], "utf-8", ("\r\n" if os.name == "nt" else "\n")
    except OSError as e:
        raise IniError(f"could not read {path} ({e.strerror or e})") from e
    text, enc = decode(raw)
    nl = "\r\n" if "\r\n" in text else ("\n" if "\n" in text else ("\r\n" if os.name == "nt" else "\n"))
    return text.splitlines(), enc, nl


def _section(line):
    s = line.strip()
    if s.startswith("[") and "]" in s:
        return s[1:s.index("]")].strip().lower()
    return None


def _key(line):
    """The key of a key=value line (lower case), else None (comments, blank lines, section headers, junk)."""
    s = line.strip()
    if not s or s[0] in ";#[" or "=" not in s:
        return None
    k = s.split("=", 1)[0].strip()
    return k.lower() if k else None


def _value(line):
    v = line.split("=", 1)[1].strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1]         # GetPrivateProfileString strips one pair of quotes
    return v


class Ini:
    def __init__(self, lines=()):
        self.data = {}
        sec = ""
        for line in lines:
            s = _section(line)
            if s is not None:
                sec = s
                self.data.setdefault(sec, {})
                continue
            k = _key(line)
            if k is not None:
                self.data.setdefault(sec, {}).setdefault(k, _value(line))

    def get(self, section, key, default=""):
        return self.data.get(section.lower(), {}).get(key.lower(), default)

    def has(self, section, key):
        return key.lower() in self.data.get(section.lower(), {})

    def has_section(self, section):
        return section.lower() in self.data


def read(path):
    """-> Ini (empty for a missing file); IniError when the file is there and cannot be read."""
    return Ini(_load(path)[0])


def _apply(lines, updates):
    """lines with updates {(section, key): value} applied (see the module text). -> new list."""
    out = list(lines)
    todo, names = {}, {}
    for (s, k), v in updates.items():
        names.setdefault(s.lower(), s)
        todo.setdefault(s.lower(), {})[k.lower()] = (k, str(v))
    # where each section starts and its last key line ends (first occurrence of a section only)
    first, last_key, sec, seen = {}, {}, None, set()
    done = set()
    for i, line in enumerate(out):
        s = _section(line)
        if s is not None:
            sec = s if s not in first else None    # a repeated section: its keys are not the ones read
            if sec is not None:
                first[sec] = i
                last_key[sec] = i
            continue
        if sec is None:
            continue
        k = _key(line)
        if k is None:
            continue
        last_key[sec] = i
        if sec in todo and k in todo[sec] and (sec, k) not in seen:
            seen.add((sec, k))
            eq = line.index("=")
            rest = line[eq + 1:]
            pad = rest[:len(rest) - len(rest.lstrip())]
            out[i] = line[:eq + 1] + pad + todo[sec][k][1]
            done.add((sec, k))
    # keys missing from a section that exists: after its last key, in the order given (from the end, so the
    # indexes found above stay right)
    adds = []
    for s, keys in todo.items():
        miss = [f"{k} = {v}" for lk, (k, v) in keys.items() if (s, lk) not in done]
        if miss and s in first:
            adds.append((last_key[s] + 1, miss))
    for at, miss in sorted(adds, reverse=True):
        out[at:at] = miss
    for s, keys in todo.items():
        if s in first:
            continue
        if out and out[-1].strip():
            out.append("")
        out.append(f"[{names[s]}]")
        out += [f"{k} = {v}" for k, v in keys.values()]
    return out


def set_values(path, updates):
    """Set {(section, key): value} in the ini at path, keeping every other line. IniError on failure."""
    lines, enc, nl = _load(path)
    text = nl.join(_apply(lines, updates)) + nl
    try:
        data = text.encode(enc)
    except UnicodeEncodeError:
        data = text.encode("utf-8")     # an ANSI file and a character outside its code page
    d = os.path.dirname(os.path.abspath(path))
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".kz2-install-", suffix=".tmp", dir=d)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        tmp = None
    except OSError as e:
        raise IniError(f"could not write {path} ({e.strerror or e})") from e
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def set_value(path, section, key, value):
    set_values(path, {(section, key): value})
