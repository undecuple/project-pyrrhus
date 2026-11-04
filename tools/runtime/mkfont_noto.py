#!/usr/bin/env python3
"""Make the bundled system-fontset face (patch 6061, issue #39): NotoSans-Regular.ttf from nixpkgs' noto-fonts.

Noto Sans (SIL OFL 1.1, notofonts/latin-greek-cyrillic) is the Latin + Greek + Cyrillic family, so its character set is
already the one KZ2 needs. nixpkgs ships it as the variable font NotoSans.ttf (wdth/wght axes, 1.5 MB, most of it
gvar). This keeps the default instance (Regular, normal width, i.e. the glyf outlines as stored) and drops the variation
and layout tables, which the cellFont HLE (stb_truetype) never reads: fvar, gvar, avar, HVAR, MVAR, STAT, GDEF, GPOS,
GSUB; post becomes version 3 (no glyph names). Glyph ids, outlines, metrics, cmap and name are unchanged. About 350 KB.
The font file is never committed: the build (tools/build-kz2.sh) and the release payload make it with this script.

  mkfont_noto.py [--src NotoSans.ttf] OUT.ttf

--src default: $KZ2_NOTO_SRC, else <noto-fonts>/share/fonts/noto/NotoSans.ttf with <noto-fonts> from the flake's locked
nixpkgs (flake.lock, nix eval offline; the store path must already be present). The source's sha256 is pinned (SRC_SHA256): a
different noto-fonts release is refused until the pin is updated, so the shipped bytes only change on purpose.
"""
import base64
import hashlib
import json
import os
import struct
import subprocess
import sys

SRC_SHA256 = "511cc04b442ffcc3b24d65c2cc780bdffaf482b20ba0aebdc8f27b37017ff0f5"   # noto-fonts 2026.10.01 NotoSans.ttf
KEEP = ("OS/2", "cmap", "gasp", "glyf", "head", "hhea", "hmtx", "loca", "maxp", "name", "post")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def noto_src():
    e = os.environ.get("KZ2_NOTO_SRC")
    if e:
        return e
    try:
        lk = json.load(open(os.path.join(ROOT, "flake.lock")))["nodes"]["nixpkgs"]["locked"]
        src_tree = nar_source_path(lk["narHash"])
    except (OSError, KeyError, ValueError) as ex:
        sys.exit(f"mkfont_noto: cannot read flake.lock's nixpkgs ({ex}); set KZ2_NOTO_SRC to NotoSans.ttf")
    if not os.path.isdir(src_tree):
        sys.exit(f"mkfont_noto: the locked nixpkgs ({src_tree}) is not in the store; set KZ2_NOTO_SRC to NotoSans.ttf")
    expr = f'(import {src_tree} {{ system = "x86_64-linux"; }}).noto-fonts.outPath'
    try:
        out = subprocess.run(["nix", "--extra-experimental-features", "nix-command flakes", "eval", "--offline",
                              "--raw", "--impure", "--expr", expr], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as ex:
        sys.exit(f"mkfont_noto: cannot run nix eval ({ex}); set KZ2_NOTO_SRC to NotoSans.ttf")
    if out.returncode != 0 or not out.stdout.startswith("/nix/store/"):
        sys.exit("mkfont_noto: nix eval of noto-fonts failed: " + out.stderr.strip()[-300:])
    return os.path.join(out.stdout.strip(), "share", "fonts", "noto", "NotoSans.ttf")


def nar_source_path(nar_hash):
    """The store path of a locked flake input (a "source" path named by its NAR sha256, as builtins.fetchTree makes
    it), so nix can import it offline without its fetcher cache (not visible inside tools/sandbox.sh)."""
    if not nar_hash.startswith("sha256-"):
        raise ValueError("narHash is not sha256")
    h = base64.b64decode(nar_hash[7:])
    d = hashlib.sha256(("source:sha256:%s:/nix/store:source" % h.hex()).encode()).digest()
    c = bytearray(20)
    for i, b in enumerate(d):
        c[i % 20] ^= b
    alpha, out = "0123456789abcdfghijklmnpqrsvwxyz", ""
    for n in range(31, -1, -1):
        i, j = divmod(n * 5, 8)
        out += alpha[((c[i] >> j) | ((c[i + 1] << (8 - j)) if i + 1 < 20 else 0)) & 31]
    return "/nix/store/%s-source" % out


def checksum(b):
    b = b + b"\0" * (-len(b) % 4)
    return sum(struct.unpack(">%dI" % (len(b) // 4), b)) & 0xFFFFFFFF


def make(src_bytes):
    if src_bytes[:4] != b"\0\1\0\0":
        raise ValueError("not a TrueType font")
    n = struct.unpack(">H", src_bytes[4:6])[0]
    tables = {}
    for i in range(n):
        tag, _cs, off, ln = struct.unpack(">4sIII", src_bytes[12 + 16 * i:28 + 16 * i])
        tables[tag.decode("latin1")] = src_bytes[off:off + ln]
    missing = [t for t in KEEP if t not in tables]
    if missing:
        raise ValueError("source lacks " + ", ".join(missing))
    out = {t: tables[t] for t in KEEP}
    out["post"] = struct.pack(">I", 0x00030000) + tables["post"][4:32]          # version 3: no glyph names
    head = bytearray(tables["head"]); head[8:12] = b"\0\0\0\0"                    # checksumAdjustment, set below
    out["head"] = bytes(head)
    tags = sorted(out)
    nt = len(tags)
    es = max(i for i in range(16) if (1 << i) <= nt)
    hdr = struct.pack(">IHHHH", 0x00010000, nt, 16 << es, es, nt * 16 - (16 << es))
    pos = 12 + 16 * nt
    dirs, body = b"", b""
    for t in tags:
        d = out[t]
        dirs += t.encode("latin1") + struct.pack(">III", checksum(d), pos + len(body), len(d))
        body += d + b"\0" * (-len(d) % 4)
    font = bytearray(hdr + dirs + body)
    hoff = None
    for i in range(nt):
        tag, _c, off, _l = struct.unpack(">4sIII", bytes(font[12 + 16 * i:28 + 16 * i]))
        if tag == b"head":
            hoff = off
    font[hoff + 8:hoff + 12] = struct.pack(">I", (0xB1B0AFBA - checksum(bytes(font))) & 0xFFFFFFFF)
    return bytes(font)


def main(argv):
    args = list(argv)
    src = None
    if len(args) >= 2 and args[0] == "--src":
        src = args[1]; args = args[2:]
    if len(args) != 1:
        sys.exit("usage: mkfont_noto.py [--src NotoSans.ttf] OUT.ttf")
    src = src or noto_src()
    try:
        data = open(src, "rb").read()
    except OSError as ex:
        sys.exit(f"mkfont_noto: cannot read {src}: {ex}")
    h = hashlib.sha256(data).hexdigest()
    if h != SRC_SHA256 and os.environ.get("KZ2_NOTO_ANY") != "1":
        sys.exit(f"mkfont_noto: {src} has sha256 {h[:16]}, pinned {SRC_SHA256[:16]} (a new noto-fonts: check it and "
                 "update SRC_SHA256; KZ2_NOTO_ANY=1 for a test font)")
    font = make(data)
    os.makedirs(os.path.dirname(os.path.abspath(args[0])) or ".", exist_ok=True)
    tmp = args[0] + ".tmp"
    with open(tmp, "wb") as f:
        f.write(font)
    os.replace(tmp, args[0])
    print(f"mkfont_noto: {args[0]} ({len(font)} bytes, sha256 {hashlib.sha256(font).hexdigest()[:16]}) from {src}")


if __name__ == "__main__":
    main(sys.argv[1:])
