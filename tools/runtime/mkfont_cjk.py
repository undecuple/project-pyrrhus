#!/usr/bin/env python3
"""Make the bundled CJK face for patch 6061 (D53): NotoSansCJK-Regular.ttc, Noto Sans CJK cut down to the
characters Killzone 2's own text uses.

    mkfont_cjk.py [--src NotoSansCJK-VF.otf.ttc] [--list tools/runtime/cjk-codepoints.txt] OUT.ttc [--stats]

Source: nixpkgs' noto-fonts-cjk-sans 2.004 (SIL OFL 1.1, Adobe + Google; Reserved Font Name "Source", which no name
here uses), the variable CFF2 collection NotoSansCJK-VF.otf.ttc (32.7 MB, pinned by SRC_SHA256; found like
mkfont_noto.py finds noto-fonts: the flake's locked nixpkgs, nix eval offline, or $KZ2_NOTO_CJK_SRC).
cellFont's reader (stb_truetype) reads neither CFF2 nor variations, so for each kept glyph this draws the outline at
wght 400 (Regular; fontTools' glyph set applies avar and the CFF2 blend), converts the cubics to TrueType quadratics
(cu2qu, 1 font unit tolerance, contours reversed to TrueType's clockwise order) and writes a plain glyf font.
Outlines and advances are the font's own, untouched otherwise. Tables: OS/2 cmap glyf head hhea hmtx loca maxp name
post (version 3); no layout tables (the game asks for one code point at a time).

The output is a collection of five faces with one shared glyph set, differing only in cmap and name: 0 JP, 1 KR,
2 SC, 3 TC, 4 HK, the source's own order. Han characters are drawn differently by language (the source maps a code point
to a JP, KR, SC, TC or HK glyph per face); the glyph set is the union of what the five faces map for the listed code
points, so each face keeps its own shapes. Patch 6061 picks the face index per language.

The code point list (numbers only, made by tools/runtime/cjk_codepoints.py from the game's text in all four regions'
archives and updates) is committed; the font file is never committed: the build (tools/build-kz2.sh) and the release
payload make it with this script, and its SHA-256 is pinned (OUT_SHA256 here; assemble_payload.py).

Needs fontTools FONTTOOLS_VERSION (MIT; a build tool, not shipped): an importable one, else $KZ2_FONTTOOLS (its
site-packages dir), else the flake's locked nixpkgs python3Packages.fonttools if it is in the store. cu2qu is loaded
from its .py source even when fontTools was built with Cython, so the bytes do not depend on how fontTools was built.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import mkfont_noto   # noqa: E402  (nar_source_path)

SRC_SHA256 = "d3d8256cdec8dbcb3552284bc6b20c734dd60c2ee9df83b5758e34807c4bac32"   # noto-fonts-cjk-sans 2.004 NotoSansCJK-VF.otf.ttc
OUT_SHA256 = "6dcb72425101f53db0f9e5071c5102509fa30d58d6974c60d2d2e1704685b6c5"   # tools/runtime/cjk-codepoints.txt (4,751 code points)
FONTTOOLS_VERSION = "4.63.0"
FACES = ("JP", "KR", "SC", "TC", "HK")
WGHT = 400.0
TOLERANCE = 1.0        # font units (unitsPerEm 1000)
LIST = os.path.join(HERE, "cjk-codepoints.txt")


def locked_attr(attr):
    lk = json.load(open(os.path.join(ROOT, "flake.lock")))["nodes"]["nixpkgs"]["locked"]
    tree = mkfont_noto.nar_source_path(lk["narHash"])
    if not os.path.isdir(tree):
        raise OSError(f"the locked nixpkgs ({tree}) is not in the store")
    expr = f'(import {tree} {{ system = "x86_64-linux"; }}).{attr}.outPath'
    out = subprocess.run(["nix", "--extra-experimental-features", "nix-command flakes", "eval", "--offline", "--raw",
                          "--impure", "--expr", expr], capture_output=True, text=True, timeout=600)
    if out.returncode != 0 or not out.stdout.startswith("/nix/store/"):
        raise OSError("nix eval failed: " + out.stderr.strip()[-300:])
    return out.stdout.strip()


def load_fonttools():
    try:
        import fontTools  # noqa: F401
    except ImportError:
        p = os.environ.get("KZ2_FONTTOOLS")
        if not p:
            try:
                base = locked_attr("python3Packages.fonttools")
            except (OSError, KeyError, ValueError, subprocess.TimeoutExpired) as ex:
                sys.exit(f"mkfont_cjk: no fontTools ({ex}); set KZ2_FONTTOOLS to a fontTools {FONTTOOLS_VERSION} site-packages dir")
            libs = os.path.join(base, "lib")
            pys = [d for d in (os.listdir(libs) if os.path.isdir(libs) else []) if d.startswith("python")]
            if not pys:
                sys.exit(f"mkfont_cjk: {base} is not in the store; realise it (nix build) or set KZ2_FONTTOOLS")
            p = os.path.join(libs, pys[0], "site-packages")
        sys.path.insert(0, p)
        import fontTools  # noqa: F401
    import fontTools
    if fontTools.version != FONTTOOLS_VERSION:
        sys.exit(f"mkfont_cjk: fontTools {fontTools.version}, want {FONTTOOLS_VERSION} (the output pin depends on it)")
    src = os.path.join(os.path.dirname(fontTools.__file__), "cu2qu", "cu2qu.py")
    import fontTools.cu2qu  # noqa: F401  (the parent package, for cu2qu.py's relative imports)
    spec = importlib.util.spec_from_file_location("fontTools.cu2qu.kz2_cu2qu_py", src)
    cu2qu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cu2qu)
    if getattr(cu2qu, "COMPILED", False):
        sys.exit("mkfont_cjk: cu2qu loaded compiled; want its Python source")
    return cu2qu


def cjk_src():
    e = os.environ.get("KZ2_NOTO_CJK_SRC")
    if e:
        return e
    try:
        base = locked_attr("noto-fonts-cjk-sans")
    except (OSError, KeyError, ValueError, subprocess.TimeoutExpired) as ex:
        sys.exit(f"mkfont_cjk: cannot find noto-fonts-cjk-sans ({ex}); set KZ2_NOTO_CJK_SRC")
    return os.path.join(base, "share", "fonts", "opentype", "noto-cjk", "NotoSansCJK-VF.otf.ttc")


def read_list(path):
    cps = set()
    for line in open(path):
        line = line.split("#")[0].strip()
        if not line:
            continue
        a, _, b = line.partition("-")
        cps.update(range(int(a, 16), int(b or a, 16) + 1))
    return cps


class QuadPen:
    """Segment pen: cubics -> quadratics with the pure-Python cu2qu, into a TTGlyphPen."""
    def __init__(self, out, cu2qu):
        self.out, self.cu2qu, self.cur = out, cu2qu, None

    def moveTo(self, p):
        self.out.moveTo(p); self.cur = p

    def lineTo(self, p):
        self.out.lineTo(p); self.cur = p

    def curveTo(self, *pts):
        if len(pts) != 3:
            raise ValueError("only plain cubics expected from CFF2")
        q = self.cu2qu.curve_to_quadratic((self.cur,) + pts, TOLERANCE)
        self.out.qCurveTo(*q[1:]); self.cur = pts[-1]

    def qCurveTo(self, *pts):
        self.out.qCurveTo(*pts); self.cur = pts[-1]

    def closePath(self):
        self.out.closePath()

    def endPath(self):
        self.out.endPath()


def make(src, cps, cu2qu):
    from fontTools.ttLib import TTCollection, newTable
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.pens.reverseContourPen import ReverseContourPen
    from fontTools.fontBuilder import FontBuilder
    import copy
    coll = TTCollection(src, lazy=True)
    faces = coll.fonts
    if len(faces) < len(FACES):
        raise ValueError("source has fewer faces than expected")
    for i, tag in enumerate(FACES):
        fam = faces[i]["name"].getDebugName(1)
        if not fam.endswith(" " + tag):
            raise ValueError(f"face {i} is {fam!r}, expected Noto Sans CJK {tag}")
    # The faces share every table but cmap and name (same offsets in the file); fontTools names glyphs from each
    # face's own cmap (post version 3), so the names differ while the glyph ids are one set: work in glyph ids.
    for t in ("CFF2", "hmtx", "HVAR", "maxp"):
        if len({f.reader.tables[t].offset for f in faces[:len(FACES)]}) != 1:
            raise ValueError(f"the faces do not share one {t} table")
    order = faces[0].getGlyphOrder()
    cmaps = []
    for i in range(len(FACES)):
        rev = faces[i].getReverseGlyphMap()
        cmaps.append({c: order[rev[g]] for c, g in faces[i].getBestCmap().items()})
    gid = {g: i for i, g in enumerate(order)}
    want = {".notdef"}
    for cm in cmaps:
        want.update(cm[c] for c in cps if c in cm)
    names = sorted(want, key=lambda g: gid[g])
    gs = faces[0].getGlyphSet(location={"wght": WGHT})
    glyphs, metrics = {}, {}
    for g in names:
        tp = TTGlyphPen(None)
        gs[g].draw(QuadPen(ReverseContourPen(tp), cu2qu))
        gl = tp.glyph()
        gl.recalcBounds(None)
        glyphs[g] = gl
        metrics[g] = (int(round(gs[g].width)), getattr(gl, "xMin", 0) if gl.numberOfContours else 0)
    src0 = faces[0]
    out = []
    for i, tag in enumerate(FACES):
        fb = FontBuilder(src0["head"].unitsPerEm, isTTF=True)
        fb.setupGlyphOrder(names)
        fb.setupCharacterMap({c: cmaps[i][c] for c in sorted(cps) if c in cmaps[i]})
        fb.setupGlyf(copy.deepcopy(glyphs) if i else glyphs)
        fb.setupHorizontalMetrics(metrics)
        hh = src0["hhea"]
        fb.setupHorizontalHeader(ascent=hh.ascent, descent=hh.descent)
        nm = faces[i]["name"]
        fam = nm.getDebugName(1)
        ver = nm.getDebugName(5) or "Version 2.004"
        fb.setupNameTable({
            "copyright": nm.getDebugName(0), "familyName": fam, "styleName": "Regular",
            "uniqueFontIdentifier": f"{ver};{fam.replace(' ', '')}-Regular;kz2-subset",
            "fullName": fam + " Regular", "version": ver, "psName": fam.replace(" ", "") + "-Regular",
            "trademark": nm.getDebugName(7) or "", "manufacturer": nm.getDebugName(8) or "",
            "designer": nm.getDebugName(9) or "",
            "description": "Static Regular instance of Noto Sans CJK, TrueType outlines, cut to the characters of "
                           "Killzone 2's text for its PC port (patch 6061).",
            "vendorURL": nm.getDebugName(11) or "", "designerURL": nm.getDebugName(12) or "",
            "licenseDescription": nm.getDebugName(13) or "", "licenseInfoURL": nm.getDebugName(14) or "",
        }, mac=False)
        os2 = src0["OS/2"]
        fb.setupOS2(sTypoAscender=os2.sTypoAscender, sTypoDescender=os2.sTypoDescender, sTypoLineGap=os2.sTypoLineGap,
                    usWinAscent=os2.usWinAscent, usWinDescent=os2.usWinDescent, usWeightClass=400,
                    achVendID=os2.achVendID, fsType=0, sxHeight=getattr(os2, "sxHeight", 0),
                    sCapHeight=getattr(os2, "sCapHeight", 0))
        fb.setupPost(keepGlyphNames=False)
        fb.font["head"].fontRevision = src0["head"].fontRevision
        fb.font["head"].created = fb.font["head"].modified = src0["head"].created   # no build time in the bytes
        fb.font["head"].flags = src0["head"].flags & ~(1 << 13) | 3
        out.append(fb.font)
    c = TTCollection()
    c.fonts = out
    return c, glyphs


def record_bytes(gl):
    """Patch 6061's guest record for this glyph: 0x40 + 9 per point + 2 per contour (points from the converter add the
    implied on-curve midpoints the game makes itself, so this is the upper bound for the file's own points)."""
    n = len(gl.coordinates) if gl.numberOfContours > 0 else 0
    return 0x40 + 9 * n + 2 * max(gl.numberOfContours, 0) + 1, n


def main(argv):
    args, src, lst, stats = list(argv), None, LIST, False
    while args and args[0].startswith("--"):
        if args[0] == "--src":
            src = args[1]; args = args[2:]
        elif args[0] == "--list":
            lst = args[1]; args = args[2:]
        elif args[0] == "--stats":
            stats = True; args = args[1:]
        else:
            break
    if len(args) != 1:
        sys.exit("usage: mkfont_cjk.py [--src NotoSansCJK-VF.otf.ttc] [--list FILE] [--stats] OUT.ttc")
    cu2qu = load_fonttools()
    src = src or cjk_src()
    try:
        h = hashlib.sha256(open(src, "rb").read()).hexdigest()
    except OSError as ex:
        sys.exit(f"mkfont_cjk: cannot read {src}: {ex}")
    if SRC_SHA256 and h != SRC_SHA256:
        sys.exit(f"mkfont_cjk: {src} sha256 {h[:8]}..., pinned {SRC_SHA256[:8]}...: a different noto-fonts-cjk-sans; "
                 "update SRC_SHA256 (and the output pin) on purpose")
    cps = read_list(lst)
    coll, glyphs = make(src, cps, cu2qu)
    out = args[0]
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    tmp = out + ".tmp"
    coll.save(tmp, shareTables=True)
    os.replace(tmp, out)
    oh = hashlib.sha256(open(out, "rb").read()).hexdigest()
    print(f"mkfont_cjk: {out}: {os.path.getsize(out)} bytes, sha256 {oh[:8]}..., {len(glyphs)} glyphs, "
          f"{len(cps)} listed code points, source sha256 {h[:8]}...")
    if stats:
        rb = sorted((record_bytes(g)[0], record_bytes(g)[1], n) for n, g in glyphs.items())
        print(f"  largest guest records: {rb[-3:]} (bytes, points, glyph); pool 0x40000 = {0x40000}")
    if OUT_SHA256 and oh != OUT_SHA256:
        sys.exit(f"mkfont_cjk: output sha256 {oh[:8]}... differs from the pin {OUT_SHA256[:8]}...")


if __name__ == "__main__":
    main(sys.argv[1:])
