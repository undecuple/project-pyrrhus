#!/usr/bin/env python3
"""Installer artwork and GitHub cover images for Project Pyrrhus, drawn from the project site's look.

From Project Helghast tools/release/installer_art.py (Project Helghast), with Killzone 2's palette (warm
black and rust, orange for Helghast eyes and fire, arc-tower lightning blue as the second accent) and the Project
Pyrrhus wordmark. Everything is drawn here from shapes, stripes and text: the plain wordmark "PROJECT PYRRHUS" and the
line "KILLZONE 2 PC" set in Rajdhani Bold, small text in Rajdhani (both SIL OFL 1.1, from Google Fonts' own
repository github.com/google/fonts, ofl/; the fonts are not committed or shipped, only these images, which NOTICE.md
lists), the project URL, a jagged "arc lightning" line, and the site's palette (public/site/style.css). No game logo,
symbol or game art. Needs Pillow (the .#re shell).

    python3 tools/release/installer_art.py --fetch-fonts   # download the .ttf files + OFL.txt into --fonts (network;
                                                          # refuses fonts whose SHA-256 differs from art.json's)
    python3 tools/release/installer_art.py                 # render installer/art/* + art.json (needs the fonts)
    python3 tools/release/installer_art.py --check         # exit 1 when an image is missing, changed or stale
    python3 tools/release/installer_art.py --preview F.png # also write a contact sheet of every image (not shipped)
    python3 tools/release/installer_art.py --stand-in-fonts --out DIR --public-out DIR2   # Pillow's built-in font
                                                     # instead (host test; never into installer/art or public/assets)

Outputs (installer/art/): wizard-{100,125,150,200}.bmp (Welcome/Finish panel, 24-bit), header-{...}.bmp (the small
top-right image), kz2-setup.ico, kz2-launcher.ico, kz2-uninstall.ico (16/24/32/48/64 as 32-bit DIB, 256 as PNG)
and art.json (SHA-256 of every file, of this script and of the fonts; Pillow and FreeType versions).
Outputs (public/assets/, exported to the public repo, art.json key "public_files"): social-preview.png (1280x640,
GitHub's repository social preview: under 1 MB, every mark inside a 40 px safe margin) and banner.png (1280x320) +
banner@2x.png (2560x640), the README banner: an opaque dark panel with transparent chamfers, so it reads the same on
GitHub's light and dark page. --public-out DIR moves them (tests); stand-in fonts never write into public/assets.
--check: with the fonts present it renders again and compares bytes; without them it checks the files against
art.json and that art.json was made by this exact script (an edited generator = stale). The palette must still be
in style.css (the site and the installer move together). Deterministic: same script + fonts + Pillow = same bytes.
ASSUMPTION: Inno 6's documented image sizes for 100/125/150/200 % (164x314 ... 328x604, 55x55 ... 110x106; the
help's WizardImageFile topic); Inno picks the closest one per DPI. Checked when the installer is compiled.
"""
import argparse
import hashlib
import io
import json
import pathlib
import re
import struct
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "installer" / "art"
# Both layouts: this repo keeps the public files under public/; the public repo has them at its root.
PUB = ROOT / "public" if (ROOT / "public" / "site").is_dir() else ROOT
PUBLIC_OUT = PUB / "assets"
FONTS = ROOT / "work" / "release" / "fonts"
CSS = PUB / "site" / "style.css"
URL_TEXT = "undecuple.github.io/project-pyrrhus"   # the site (as KZ3 shows its github.io page); ASSUMPTION: the page goes live under this name
TAG_TEXT = "UNOFFICIAL PC PORT"
TAG_WIDE = "KILLZONE 2 // UNOFFICIAL PC PORT"   # banner and social preview (room for the game name)
BLURB = ("BUILT ON YOUR PC", "FROM YOUR OWN GAME")

# Google Fonts' official repository (OFL folders). Pinned by SHA-256 in art.json after the first fetch.
GF = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONT_FILES = {"head": ("rajdhani", "Rajdhani-Bold.ttf"),
              "small": ("rajdhani", "Rajdhani-Medium.ttf"),
              "small-bold": ("rajdhani", "Rajdhani-Bold.ttf")}

# The site's palette (public/site/style.css); --check fails when one of these leaves the stylesheet.
# orange = Helghast eyes and fire (main accent), arc = arc-tower lightning (second accent), white = the wordmark.
PAL = {"bg": "#0b0a08", "panel": "#17130f", "line": "#3d2a17", "orange": "#e0661a", "orange-hi": "#ff8a3d",
       "arc": "#8fb8d8", "arc-hi": "#c9e4f5", "text": "#e6e0d6", "dim": "#a39886", "glow": "#2a1606",
       "white": "#f2efe9"}
# The lightning's jag pattern (fractions of the amplitude, evenly spaced along the line); fixed = deterministic.
JAGS = (0, -0.5, 0.35, -1.0, 0.2, 0.9, -0.3, 0.6, -0.8, 0.1, 1.0, -0.45, 0.3, -0.9, 0.55, -0.2, 0)

# Inno Setup 6 sizes per DPI (ASSUMPTION, docstring): large wizard image, small header image.
WIZARD = {100: (164, 314), 125: (192, 386), 150: (246, 459), 200: (328, 604)}
HEADER = {100: (55, 55), 125: (64, 68), 150: (83, 80), 200: (110, 106)}
ICON_SIZES = (16, 24, 32, 48, 64, 256)
ICONS = ("setup", "launcher", "uninstall")
SS = 4   # supersampling: draw at 4x, scale down once (anti-aliased shapes and text)
SOCIAL = (1280, 640)
SOCIAL_SAFE = 40            # GitHub crops the preview on some surfaces: every mark stays this far from the edge
SOCIAL_MAX_BYTES = 1 << 20  # GitHub refuses a social preview of 1 MB or more
BANNER = {"banner.png": (1280, 320), "banner@2x.png": (2560, 640)}
BANNER_MAX_BYTES = 400 * 1024   # "light enough for the README" (our own limit, per file)


def rgb(name):
    h = PAL[name].lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def script_hash():
    return sha256(pathlib.Path(__file__).read_bytes())


# ------------------------------------------------------------------------------------------------------- fonts
class Fonts:
    """The three faces; `stand_in` = Pillow's built-in scalable font (tests only)."""

    def __init__(self, fonts_dir, stand_in=False):
        from PIL import ImageFont
        self.IF, self.stand_in, self.paths, self.hashes = ImageFont, stand_in, {}, {}
        if stand_in:
            return
        for role, (_, fn) in FONT_FILES.items():
            p = pathlib.Path(fonts_dir) / fn
            if not p.is_file():
                raise FileNotFoundError(f"font {p} missing (run --fetch-fonts, or pass --fonts DIR)")
            self.paths[role], self.hashes[fn] = p, sha256(p.read_bytes())

    def get(self, role, px):
        px = max(1, int(px))
        if self.stand_in:
            return self.IF.load_default(px)
        return self.IF.truetype(str(self.paths[role]), px, layout_engine=self.IF.Layout.BASIC)


def missing_fonts(fonts_dir):
    return [fn for _, fn in FONT_FILES.values() if not (pathlib.Path(fonts_dir) / fn).is_file()]


def fetch_fonts(fonts_dir, pinned, opener=urllib.request.urlopen):
    """Download the fonts and their OFL.txt; refuse a font whose hash differs from the pinned one."""
    d = pathlib.Path(fonts_dir)
    d.mkdir(parents=True, exist_ok=True)
    got = {}
    for folder, fn in sorted(set(FONT_FILES.values())) + [("rajdhani", "OFL.txt")]:
        with opener(GF + f"{folder}/{fn}", timeout=30) as r:
            data = r.read()
        name = fn if fn != "OFL.txt" else f"OFL-{folder}.txt"
        if fn != "OFL.txt":
            h = sha256(data)
            if pinned.get(fn) and pinned[fn] != h:
                raise ValueError(f"{fn}: SHA-256 {h} differs from art.json's {pinned[fn]} (upstream changed it; "
                                 "check the change, then delete the pin from art.json to accept it)")
            got[fn] = h
        (d / name).write_bytes(data)
    return got


# ----------------------------------------------------------------------------------------------------- drawing
def text_w(font, text, track):
    """Width of `text` with `track` extra em per letter gap (the site's letter-spacing)."""
    if not text:
        return 0
    return sum(font.getlength(c) for c in text) + track * font.size * (len(text) - 1)


def draw_text(draw, xy, text, font, fill, track=0.0):
    """Letter by letter (tracking); y is the top of the caps (font ascender offset removed)."""
    x, y = xy
    top = font.getbbox("H")[1]
    for c in text:
        draw.text((x, y - top), c, font=font, fill=fill)
        x += font.getlength(c) + track * font.size


def fit(fonts, role, text, max_w, max_h, track=0.0):
    """The largest size whose caps fit max_w x max_h; -> (font, width, cap height)."""
    lo, hi = 1, max(2, int(max_h * 2))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        f = fonts.get(role, mid)
        b = f.getbbox("H")
        if text_w(f, text, track) <= max_w and (b[3] - b[1]) <= max_h:
            lo = mid
        else:
            hi = mid - 1
    f = fonts.get(role, lo)
    b = f.getbbox("H")
    return f, text_w(f, text, track), b[3] - b[1]


def ground(w, h, glow_ry=0.6):
    """Dark ground with the site's warm glow from the top (radial-gradient(ellipse at top, glow, bg 60%))."""
    from PIL import Image
    rx, ry = max(1, int(w * 0.9)), max(1, int(h * glow_ry))
    g = Image.radial_gradient("L").resize((2 * rx, 2 * ry), Image.Resampling.BILINEAR)
    mask = Image.new("L", (w, h), 255)
    mask.paste(g.crop((rx - w // 2, ry, rx - w // 2 + w, ry + min(h, ry))), (0, 0))   # below the ellipse: ground
    mask = mask.point(lambda v: min(255, v * 2))     # 128 = the ellipse's edge in radial_gradient
    return Image.composite(Image.new("RGB", (w, h), rgb("bg")), Image.new("RGB", (w, h), rgb("glow")), mask)


def scanlines(img, step=3, add=4):
    """The site's faint horizontal lines, at the final size (1 px every `step`)."""
    from PIL import Image, ImageChops
    from PIL import ImageDraw
    ov = Image.new("RGB", img.size, (0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(0, img.size[1], step):
        d.line((0, y, img.size[0] - 1, y), fill=(add, add, add))
    return ImageChops.add(img, ov)


def brackets(draw, x0, y0, x1, y1, length, thick, color):
    """HUD frame corners (.frame::before/::after): top-left and bottom-right."""
    draw.rectangle((x0, y0, x0 + length, y0 + thick - 1), fill=color)
    draw.rectangle((x0, y0, x0 + thick - 1, y0 + length), fill=color)
    draw.rectangle((x1 - length, y1 - thick + 1, x1, y1), fill=color)
    draw.rectangle((x1 - thick + 1, y1 - length, x1, y1), fill=color)


def hazard(draw, x0, y0, x1, y1, period, color):
    """Diagonal stripes in a band (drawn clipped: polygons, then the band's edges are repainted by the caller)."""
    hgt = y1 - y0
    x = x0 - hgt
    while x < x1:
        draw.polygon([(x, y1), (x + hgt, y0), (x + hgt + period / 2, y0), (x + period / 2, y1)], fill=color)
        x += period


def bolt(draw, x0, x1, yc, amp, width, period=None):
    """An arc-tower lightning streak (abstract: a jagged line in the arc blue with a soft halo and a bright core)
    from x0 to x1 around yc; deterministic (a fixed jag pattern, no randomness)."""
    n = len(JAGS) - 1
    xs = [x0 + (x1 - x0) * i / n for i in range(n + 1)]
    pts = [(x, yc + amp * j) for x, j in zip(xs, JAGS)]
    halo = tuple((a + b) // 2 for a, b in zip(rgb("arc"), rgb("bg")))
    draw.line(pts, fill=halo, width=max(1, round(width * 3)), joint="curve")
    draw.line(pts, fill=rgb("arc"), width=max(1, round(width * 1.6)), joint="curve")
    draw.line(pts, fill=rgb("arc-hi"), width=max(1, round(width * 0.7)), joint="curve")


def game_line(d, fonts, x, y, cap, max_w):
    """KILLZONE (text colour) 2 (orange) PC (arc, on the baseline, smaller); -> (width, cap height)."""
    gap = round(0.28 * cap)
    fk = fit(fonts, "head", "KILLZONE", max_w, cap, 0.06)
    f2 = fit(fonts, "head", "2", max_w, cap)
    fp = fit(fonts, "head", "PC", max_w, round(0.6 * cap), 0.1)
    if fk[1] + f2[1] + fp[1] + 2 * gap > max_w:
        return game_line(d, fonts, x, y, int(cap * max_w / (fk[1] + f2[1] + fp[1] + 2 * gap)), max_w)
    ch = max(fk[2], f2[2])
    draw_text(d, (x, y + ch - fk[2]), "KILLZONE", fk[0], rgb("text"), 0.06)
    x2 = x + fk[1] + gap
    draw_text(d, (x2, y + ch - f2[2]), "2", f2[0], rgb("orange-hi"))
    xp = x2 + f2[1] + gap
    draw_text(d, (xp, y + ch - fp[2]), "PC", fp[0], rgb("arc-hi"), 0.1)
    return xp + fp[1] - x, ch


def wordmark(d, fonts, x, y, cap, max_w, one_line=False):
    """PROJECT (text off-white) and PYRRHUS (orange), both the SAME size and weight (KZ3's banner layout).
    one_line: side by side on one baseline; otherwise stacked, one under the other. Largest size <= cap that fits
    max_w. -> (width, height)."""
    gap = round(0.28 * cap)
    fy = fit(fonts, "head", "PYRRHUS", max_w, cap, 0.06)
    fp = fit(fonts, "head", "PROJECT", max_w, cap, 0.06)
    size = min(fy[0].size, fp[0].size)
    if one_line:
        while True:
            f = fonts.get("head", size)
            wp, wy = text_w(f, "PROJECT", 0.06), text_w(f, "PYRRHUS", 0.06)
            gap = round(0.28 * (f.getbbox("H")[3] - f.getbbox("H")[1]))
            if wp + gap + wy <= max_w or size <= 4:
                break
            size -= 1
    f = fonts.get("head", size)
    b = f.getbbox("H")
    ch = b[3] - b[1]
    wp, wy = text_w(f, "PROJECT", 0.06), text_w(f, "PYRRHUS", 0.06)
    if one_line:
        draw_text(d, (x, y), "PROJECT", f, rgb("text"), 0.06)
        draw_text(d, (x + wp + gap, y), "PYRRHUS", f, rgb("orange"), 0.06)
        return wp + gap + wy, ch
    y2 = y + ch + round(0.22 * ch)
    draw_text(d, (x, y), "PROJECT", f, rgb("text"), 0.06)
    draw_text(d, (x, y2), "PYRRHUS", f, rgb("orange"), 0.06)
    return max(wp, wy), y2 + ch - y


def wizard_image(fonts, w, h):
    """The Welcome/Finish panel: tag, wordmark, game line, blurb, lightning, stripes, URL, inside a HUD frame."""
    from PIL import Image, ImageDraw
    W, H = w * SS, h * SS
    u = W / 164.0                                   # 1 px at 100 %, in drawing units
    img = ground(W, H)
    d = ImageDraw.Draw(img)
    m = round(14 * u)
    d.rectangle((round(5 * u), round(5 * u), W - round(5 * u) - 1, H - round(5 * u) - 1),
                outline=rgb("line"), width=max(1, round(u)))
    brackets(d, round(4 * u), round(4 * u), W - round(4 * u) - 1, H - round(4 * u) - 1, round(22 * u),
             max(1, round(2 * u)), rgb("orange-hi"))
    # tag (.tag: dark on orange, heading face)
    y = round(0.07 * H)
    f, tw, ch = fit(fonts, "head", TAG_TEXT, W - 2 * m - round(16 * u), round(9 * u), 0.06)
    d.rectangle((m, y, m + tw + round(16 * u), y + ch + round(10 * u)), fill=rgb("orange"))
    draw_text(d, (m + round(8 * u), y + round(5 * u)), TAG_TEXT, f, rgb("bg"), 0.06)
    # wordmark: PROJECT / PYRRHUS, then KILLZONE 2 PC
    y += ch + round(24 * u)
    _, wh = wordmark(d, fonts, m, y, round(34 * u), W - 2 * m)
    y += wh + round(14 * u)
    d.rectangle((m, y, W - m, y + max(1, round(2 * u)) - 1), fill=rgb("orange"))
    y += round(12 * u)
    _, gh = game_line(d, fonts, m, y, round(15 * u), W - 2 * m)
    y += gh + round(16 * u)
    # blurb (.note voice: short, direct)
    for line in BLURB:
        f, tw, ch = fit(fonts, "small-bold", max(BLURB, key=len), W - 2 * m, round(11 * u), 0.08)
        draw_text(d, (m, y), line, f, rgb("dim"), 0.08)
        y += ch + round(7 * u)
    # lightning over the stripes band, then the URL in two lines
    by0, by1 = round(0.80 * H), round(0.80 * H + 12 * u)
    bolt(d, m, W - m, by0 - round(14 * u), round(5 * u), u)
    band = Image.new("RGB", (W - 2 * m, by1 - by0), rgb("bg"))
    hazard(ImageDraw.Draw(band), 0, 0, band.size[0], band.size[1], round(14 * u), rgb("orange"))
    img.paste(band, (m, by0))
    y = by1 + round(12 * u)
    host, path = URL_TEXT.rsplit("/", 1)
    lines = [host, "/" + path]
    f, tw, ch = fit(fonts, "small-bold", max(lines, key=len), W - 2 * m, round(11 * u))
    for line in lines:
        draw_text(d, (m, y), line, f, rgb("text"))
        y += ch + round(6 * u)
    return scanlines(img.resize((w, h), Image.Resampling.LANCZOS))


def tile(fonts, w, h, badge=None, alpha=False, pc=True, chevrons=False):
    """Square-ish emblem used by the header image and the icons: KZ2 over an orange PC bar, HUD corners; small sizes
    keep a white 2 over the bar. badge: None, "setup" (arc blue, down arrow) or "uninstall" (grey, minus).
    chevrons=True (social preview only): two stacked chevrons (orange over light) as
    in Project Helghast's preview, no letters and no bar."""
    from PIL import Image, ImageDraw
    W, H = w * SS, h * SS
    s = min(W, H)
    img = ground(W, H, glow_ry=0.9).convert("RGBA")
    d = ImageDraw.Draw(img)
    t = max(SS, round(0.05 * s))
    if alpha:   # chamfered corners (.btn clip-path), transparent
        c = round(0.16 * s)
        d.polygon([(W - c, 0), (W, 0), (W, c)], fill=(0, 0, 0, 0))
        d.polygon([(0, H - c), (0, H), (c, H)], fill=(0, 0, 0, 0))
    else:
        d.rectangle((0, 0, W - 1, H - 1), outline=rgb("line"), width=max(1, SS))
    small = min(w, h) <= 24
    brackets(d, 0, 0, W - 1, H - 1, round(0.3 * s), t, rgb("orange-hi"))
    mx = round(0.12 * W)
    # Left-aligned "PC" on a short bar that ends before the badge's column; the launcher (no badge) uses the
    # same short bar so the three icons match.
    bsz = round((0.5 if small else 0.42) * s)            # badge square, bottom-right
    gap = max(SS, round(0.05 * s))
    bar_x1 = W - bsz - gap - 1
    pad = round(0.04 * s)
    if chevrons:
        # an upward V of stroke th, the second below the first (orange, then light); Project Helghast's emblem shape
        mxc = round(0.14 * W)
        th = round(0.11 * s)
        cw = W - 2 * mxc
        chh = round(0.42 * cw)
        y = round(0.12 * H)
        for col in (rgb("orange"), rgb("text")):
            cx = mxc + cw / 2
            d.polygon([(mxc, y + chh), (cx, y), (mxc + cw, y + chh), (mxc + cw - th * 1.25, y + chh),
                       (cx, y + th * 1.55), (mxc + th * 1.25, y + chh)], fill=col)
            y += round(th * 1.6)
        pc = False
    elif small:
        bar0, bar1 = round(0.62 * H), round(0.86 * H)
        f, tw, ch = fit(fonts, "head", "2", W - 2 * mx, round(0.42 * H))
        draw_text(d, (mx, round(0.10 * H)), "2", f, (255, 255, 255))
        d.rectangle((mx, bar0, bar_x1, bar1), fill=rgb("orange"))
    else:
        bar0, bar1 = round(0.64 * H), round(0.86 * H)
        f, tw, ch = fit(fonts, "head", "KZ2", W - 2 * mx, round(0.32 * H), 0.04)
        x, y = mx, round(0.18 * H)
        draw_text(d, (x, y), "KZ", f, (255, 255, 255), 0.04)
        draw_text(d, (x + text_w(f, "KZ", 0.04) + 0.04 * f.size, y), "2", f, rgb("orange-hi"))
        if pc:   # pc=False (social preview): KZ2 alone, no empty bar
            d.rectangle((mx, bar0, bar_x1, bar1), fill=rgb("orange"))
    if pc and not small and min(w, h) >= 48:   # at 32 px "PC" is a 4 px smear: the bar alone
        f, tw, ch = fit(fonts, "head", "PC", bar_x1 - mx - 2 * pad, round(0.6 * (bar1 - bar0)), 0.1)
        draw_text(d, (mx + pad, bar0 + (bar1 - bar0 - ch) / 2), "PC", f, rgb("bg"), 0.1)
    if badge:
        x0, y0 = W - bsz, H - bsz
        col = rgb("arc-hi") if badge == "setup" else rgb("dim")
        d.rectangle((x0, y0, W - 1, H - 1), fill=col)
        cx, cy, r = x0 + bsz / 2, y0 + bsz / 2, bsz * 0.32
        if badge == "setup":
            d.polygon([(cx - r, cy - r * 0.1), (cx + r, cy - r * 0.1), (cx, cy + r)], fill=rgb("bg"))
            d.rectangle((cx - r * 0.38, cy - r, cx + r * 0.38, cy - r * 0.1), fill=rgb("bg"))
        else:
            d.rectangle((cx - r, cy - r * 0.28, cx + r, cy + r * 0.28), fill=rgb("bg"))
    out = img.resize((w, h), Image.Resampling.LANCZOS)
    return out if alpha else out.convert("RGB")


def stripes(w, h, period, color, ground_col):
    """A band of diagonal stripes (the wizard's hazard band) as its own image, clipped to w x h."""
    from PIL import Image, ImageDraw
    band = Image.new("RGB", (w, h), ground_col)
    hazard(ImageDraw.Draw(band), 0, 0, w, h, period, color)
    return band


def finish_rgba(img, w, h, chamfer):
    """Scale an RGB drawing down to w x h, add the scanlines, cut the top-right and bottom-left chamfers
    (.btn clip-path) as transparent, anti-aliased."""
    from PIL import Image, ImageDraw
    W, H = img.size
    mask = Image.new("L", (W, H), 255)
    md = ImageDraw.Draw(mask)
    md.polygon([(W - chamfer, 0), (W, 0), (W, chamfer)], fill=0)
    md.polygon([(0, H - chamfer), (0, H), (chamfer, H)], fill=0)
    out = scanlines(img.resize((w, h), Image.Resampling.LANCZOS)).convert("RGBA")
    out.putalpha(mask.resize((w, h), Image.Resampling.LANCZOS))
    return out


def tag(d, fonts, x, y, cap, max_w, text=TAG_TEXT):
    """The orange .tag with dark text (the site's .tag); -> (width, height)."""
    f, tw, ch = fit(fonts, "head", text, max_w, cap, 0.06)
    padx, pady = round(0.9 * ch), round(0.55 * ch)
    d.rectangle((x, y, x + tw + 2 * padx, y + ch + 2 * pady), fill=rgb("orange"))
    draw_text(d, (x + padx, y + pady), text, f, rgb("bg"), 0.06)
    return tw + 2 * padx, ch + 2 * pady


def social_preview(fonts, w=SOCIAL[0], h=SOCIAL[1]):
    """GitHub's repository social preview: text column left, the chevron emblem (like Project Helghast's) right, all inside the safe
    margin (frame and brackets included). Opaque: GitHub shows it on cards of either theme."""
    from PIL import Image, ImageDraw
    ss = max(1, 5120 // w)
    W, H = w * ss, h * ss
    u = W / 1280.0
    img = ground(W, H, glow_ry=0.7)
    d = ImageDraw.Draw(img)
    s0 = round(SOCIAL_SAFE * u)                         # frame: the safe area's edge
    d.rectangle((s0 + round(6 * u), s0 + round(6 * u), W - s0 - round(6 * u) - 1, H - s0 - round(6 * u) - 1),
                outline=rgb("line"), width=max(1, round(2 * u)))
    brackets(d, s0, s0, W - s0 - 1, H - s0 - 1, round(90 * u), round(6 * u), rgb("orange-hi"))
    m = round(88 * u)                                   # text column's left edge
    emb = round(300 * u)                                # emblem square, right
    ex, ey = W - m - emb, round(150 * u)
    col_w = ex - m - round(56 * u)
    y = round(92 * u)
    _, th = tag(d, fonts, m, y, round(22 * u), col_w, TAG_WIDE)
    y += th + round(36 * u)
    _, wh = wordmark(d, fonts, m, y, round(84 * u), col_w)
    y += wh + round(28 * u)
    d.rectangle((m, y, m + col_w, y + round(4 * u) - 1), fill=rgb("orange"))   # the rule spans the text column
    y += round(24 * u)
    fb, _, cb = fit(fonts, "small-bold", "  \u00b7  ".join(BLURB), col_w + round(40 * u), round(26 * u), 0.08)
    draw_text(d, (m, y), "  \u00b7  ".join(BLURB), fb, rgb("text"), 0.08)
    # lightning, stripes band, URL (bottom of the safe area)
    y0 = H - s0 - round(112 * u)
    bolt(d, m, W - m, y0 - round(20 * u), round(9 * u), round(2 * u))
    img.paste(stripes(W - 2 * m, round(22 * u), round(28 * u), rgb("orange"), rgb("bg")), (m, y0))
    fu, _, cu = fit(fonts, "small", URL_TEXT, col_w, round(24 * u))
    draw_text(d, (m, y0 + round(22 * u) + round(26 * u)), URL_TEXT, fu, rgb("dim"))
    out = scanlines(img.resize((w, h), Image.Resampling.LANCZOS))
    em = tile(fonts, emb // ss, emb // ss, alpha=True, chevrons=True)
    out.paste(em, (ex // ss, ey // ss), em)
    return out


def banner(fonts, w, h):
    """The README banner: tag + one-line wordmark left, blurb + URL right, lightning and stripes along the bottom,
    HUD frame; an opaque dark panel (legible on GitHub's light and dark pages) with transparent chamfers."""
    from PIL import ImageDraw
    ss = max(1, 5120 // w)
    W, H = w * ss, h * ss
    u = H / 320.0
    img = ground(W, H, glow_ry=1.2)
    d = ImageDraw.Draw(img)
    ins = round(8 * u)
    d.rectangle((ins, ins, W - ins - 1, H - ins - 1), outline=rgb("line"), width=max(1, round(2 * u)))
    brackets(d, round(4 * u), round(4 * u), W - round(4 * u) - 1, H - round(4 * u) - 1, round(64 * u),
             round(5 * u), rgb("orange-hi"))
    m = round(56 * u)
    right_w = round(330 * u)
    y = round(46 * u)
    tag(d, fonts, m, y, round(18 * u), W - 2 * m, TAG_WIDE)
    y = round(104 * u)
    ww, ch = wordmark(d, fonts, m, y, round(92 * u), W - 2 * m - right_w - round(40 * u), one_line=True)
    y += ch + round(24 * u)
    d.rectangle((m, y, m + ww, y + round(4 * u) - 1), fill=rgb("orange"))
    # right column: blurb (bright) over the URL (dim), right-aligned to the frame
    rx1 = W - m
    fb, _, cb = fit(fonts, "small-bold", max(BLURB, key=len), right_w, round(22 * u), 0.08)
    by = round(112 * u)
    for line in BLURB:
        draw_text(d, (rx1 - text_w(fb, line, 0.08), by), line, fb, rgb("text"), 0.08)
        by += cb + round(12 * u)
    fu, uw, cu = fit(fonts, "small", URL_TEXT, right_w, round(20 * u))
    draw_text(d, (rx1 - uw, by + round(10 * u)), URL_TEXT, fu, rgb("dim"))
    # lightning over the stripes along the bottom
    sy = H - round(56 * u)
    bolt(d, m, W - m, sy - round(16 * u), round(6 * u), round(1.6 * u))
    img.paste(stripes(W - 2 * m, round(16 * u), round(24 * u), rgb("orange"), rgb("bg")), (m, sy))
    return finish_rgba(img, w, h, round(26 * u))


# --------------------------------------------------------------------------------------------------- encoding
def bmp_bytes(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="BMP")
    return buf.getvalue()


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=9)
    return buf.getvalue()


def dib(img):
    """One ICO entry as a 32-bit BI_RGB DIB: header with double height, BGRA rows bottom-up, then the AND mask."""
    w, h = img.size
    px = img.convert("RGBA").tobytes()
    rows = []
    for y in range(h - 1, -1, -1):
        r = px[y * w * 4:(y + 1) * w * 4]
        rows.append(b"".join(bytes((r[i + 2], r[i + 1], r[i], r[i + 3])) for i in range(0, len(r), 4)))
    stride = ((w + 31) // 32) * 4
    mask = []
    for y in range(h - 1, -1, -1):
        bits = bytearray(stride)
        for x in range(w):
            if px[(y * w + x) * 4 + 3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask.append(bytes(bits))
    body = b"".join(rows) + b"".join(mask)
    return struct.pack("<IiiHHIIiiII", 40, w, 2 * h, 1, 32, 0, len(body), 0, 0, 0, 0) + body


def ico_bytes(images):
    """ICONDIR + entries; 256 px as PNG (Vista+), the rest as DIBs (every Windows reader takes those)."""
    blobs = [png_bytes(im) if im.size[0] >= 256 else dib(im) for im in images]
    out = struct.pack("<HHH", 0, 1, len(images))
    off = 6 + 16 * len(images)
    for im, b in zip(images, blobs):
        w, h = im.size
        out += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(b), off)
        off += len(b)
    return out + b"".join(blobs)


def parse_ico(data):
    """-> [(w, h, kind)] for the host test and --check."""
    _, typ, n = struct.unpack_from("<HHH", data, 0)
    if typ != 1:
        raise ValueError("not an icon")
    out = []
    for i in range(n):
        w, h, _, _, _, bpp, size, off = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        kind = "png" if data[off:off + 8] == b"\x89PNG\r\n\x1a\n" else "dib"
        out.append((w or 256, h or 256, kind))
    return out


# ------------------------------------------------------------------------------------------------------- render
def render(fonts):
    """-> {file name: (bytes, (w, h))}, every output but art.json."""
    out = {}
    for pct, (w, h) in WIZARD.items():
        out[f"wizard-{pct}.bmp"] = (bmp_bytes(wizard_image(fonts, w, h)), (w, h))
    for pct, (w, h) in HEADER.items():
        out[f"header-{pct}.bmp"] = (bmp_bytes(tile(fonts, w, h)), (w, h))
    for kind in ICONS:
        badge = None if kind == "launcher" else kind
        imgs = [tile(fonts, s, s, badge=badge, alpha=True) for s in ICON_SIZES]
        out[f"kz2-{kind}.ico"] = (ico_bytes(imgs), (256, 256))
    return out


def render_public(fonts):
    """-> {file name: (bytes, (w, h))} for public/assets/."""
    out = {"social-preview.png": (png_bytes(social_preview(fonts)), SOCIAL)}
    for name, (w, h) in BANNER.items():
        out[name] = (png_bytes(banner(fonts, w, h)), (w, h))
    return out


def versions():
    import PIL
    from PIL import features
    return {"pillow": PIL.__version__, "freetype": features.version("freetype2") or "-"}


def manifest(files, fonts, public=None):
    def ent(fs):
        return {n: {"size": list(sz), "bytes": len(b), "sha256": sha256(b)} for n, (b, sz) in sorted(fs.items())}
    return {"format": 1, "generator_sha256": script_hash(), "fonts_sha256": dict(sorted(fonts.hashes.items())),
            "fonts_source": GF, **versions(), "files": ent(files), "public_files": ent(public or {})}


def size_problems(public):
    """The limits GitHub and the README set: the social preview under 1 MB, banners under BANNER_MAX_BYTES."""
    probs = []
    for name, (data, _) in public.items():
        lim = SOCIAL_MAX_BYTES if name == "social-preview.png" else BANNER_MAX_BYTES
        if len(data) >= lim:
            probs.append(f"{name} is {len(data)} bytes, the limit is under {lim}")
    return probs


def palette_problems(css_path):
    try:
        css = pathlib.Path(css_path).read_text(encoding="utf-8").lower()
    except OSError:
        return [f"{css_path} not readable (the palette's source)"]
    return [f"palette {k} {v} is not in {pathlib.Path(css_path).name} any more" for k, v in PAL.items()
            if not re.search(re.escape(v.lower()) + r"\b", css)]


def contact_sheet(files, path, stand_in=False):
    """Every image at 1:1 on the wizard's white, then the 16/24/32 icons enlarged 6x (nearest) to judge them."""
    from PIL import Image, ImageDraw
    ims, zoom = [], []
    for name, (data, _) in sorted(files.items()):
        im = Image.open(io.BytesIO(data))
        if name.endswith(".ico"):
            sizes = sorted(im.info.get("sizes", {(256, 256)}))
            for s in sizes:
                im.size = s
                ims.append(im.copy().convert("RGBA"))
                if s[0] <= 32:
                    zoom.append(ims[-1].resize((s[0] * 6, s[1] * 6), Image.Resampling.NEAREST))
        else:
            ims.append(im.convert("RGBA"))
    row1 = max(i.size[1] for i in ims) + 20
    W = max(sum(i.size[0] + 10 for i in r) for r in (ims, zoom)) + 10
    H = row1 + max(i.size[1] for i in zoom) + 40
    sheet = Image.new("RGBA", (W, H), (255, 255, 255, 255))   # the wizard's white page around the images
    x = 10
    for i in ims:
        sheet.alpha_composite(i, (x, 10))
        x += i.size[0] + 10
    x = 10
    for i in zoom:
        sheet.alpha_composite(i, (x, row1))
        x += i.size[0] + 10
    note = ("STAND-IN FONT (Pillow built-in): NOT Rajdhani; layout preview only" if stand_in
            else "font: Rajdhani (OFL)")
    ImageDraw.Draw(sheet).text((10, H - 22), note, fill=(200, 22, 29, 255) if stand_in else (0, 0, 0, 255))
    sheet.save(path)


def check(out_dir, fonts_dir, css_path, public_dir=PUBLIC_OUT):
    """-> list of problems."""
    probs = palette_problems(css_path)
    mpath = pathlib.Path(out_dir) / "art.json"
    if not mpath.is_file():
        return probs + [f"{mpath} missing (run tools/release/installer_art.py)"]
    man = json.loads(mpath.read_text(encoding="utf-8"))
    if man.get("generator_sha256") != script_hash():
        probs.append("art.json was made by another version of installer_art.py: render again")
    for key, d in (("files", out_dir), ("public_files", public_dir)):
        for name, meta in man.get(key, {}).items():
            p = pathlib.Path(d) / name
            if not p.is_file():
                probs.append(f"{name} missing")
            elif sha256(p.read_bytes()) != meta["sha256"]:
                probs.append(f"{name} differs from art.json (edited by hand? render again)")
            else:
                lim = SOCIAL_MAX_BYTES if name == "social-preview.png" else BANNER_MAX_BYTES
                if key == "public_files" and meta["bytes"] >= lim:
                    probs.append(f"{name} is {meta['bytes']} bytes, the limit is under {lim}")
    want = {f"wizard-{p}.bmp" for p in WIZARD} | {f"header-{p}.bmp" for p in HEADER} | {f"kz2-{k}.ico" for k in ICONS}
    if set(man.get("files", {})) != want:
        probs.append(f"art.json lists {sorted(man.get('files', {}))}, the generator makes {sorted(want)}")
    want_pub = {"social-preview.png"} | set(BANNER)
    if set(man.get("public_files", {})) != want_pub:
        probs.append(f"art.json lists public {sorted(man.get('public_files', {}))}, the generator makes "
                     f"{sorted(want_pub)}")
    if not missing_fonts(fonts_dir) and not probs:
        fonts = Fonts(fonts_dir)
        if fonts.hashes != man.get("fonts_sha256"):
            probs.append("the fonts in --fonts differ from the ones art.json was made with")
        elif versions() != {k: man.get(k) for k in ("pillow", "freetype")}:
            print(f"installer_art: note: Pillow/FreeType {versions()} differ from art.json's; byte compare skipped")
        else:
            fresh = {**{("files", n): v for n, v in render(fonts).items()},
                     **{("public_files", n): v for n, v in render_public(fonts).items()}}
            for (key, name), (data, _) in fresh.items():
                if sha256(data) != man[key][name]["sha256"]:
                    probs.append(f"{name}: a fresh render differs (non-deterministic or stale)")
    return probs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--public-out", default=str(PUBLIC_OUT))
    ap.add_argument("--fonts", default=str(FONTS))
    ap.add_argument("--css", default=str(CSS))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--fetch-fonts", action="store_true")
    ap.add_argument("--stand-in-fonts", action="store_true")
    ap.add_argument("--preview", default="")
    a = ap.parse_args(argv)
    out, pub = pathlib.Path(a.out), pathlib.Path(a.public_out)
    mpath = out / "art.json"
    pinned = json.loads(mpath.read_text(encoding="utf-8")).get("fonts_sha256", {}) if mpath.is_file() else {}
    if a.fetch_fonts:
        try:
            got = fetch_fonts(a.fonts, pinned)
        except (OSError, ValueError) as e:
            print(f"installer_art: fetch failed: {e}", file=sys.stderr)
            return 1
        for fn, h in sorted(got.items()):
            print(f"installer_art: {fn} {h}")
        return 0
    if a.check:
        try:
            import PIL  # noqa: F401
        except ImportError:
            print("installer_art: SKIP --check (no Pillow; run it in the .#re shell)")
            return 0
        probs = check(out, a.fonts, a.css, pub)
        for p in probs:
            print("installer_art: " + p, file=sys.stderr)
        if not probs:
            how = "files match art.json" + ("" if missing_fonts(a.fonts) else ", fresh render identical")
            print(f"installer_art: OK ({how})")
        return 1 if probs else 0
    if a.stand_in_fonts and (out.resolve() == OUT.resolve() or pub.resolve() == PUBLIC_OUT.resolve()):
        print("installer_art: --stand-in-fonts never writes into installer/art or public/assets (pass --out and "
              "--public-out)", file=sys.stderr)
        return 2
    probs = palette_problems(a.css)
    if probs:
        print("installer_art: " + "; ".join(probs), file=sys.stderr)
        return 1
    try:
        fonts = Fonts(a.fonts, a.stand_in_fonts)
    except FileNotFoundError as e:
        print(f"installer_art: {e}", file=sys.stderr)
        return 1
    if pinned and not a.stand_in_fonts and fonts.hashes != pinned:
        print("installer_art: the fonts differ from art.json's pins (fetch again or remove the pins)", file=sys.stderr)
        return 1
    files, public = render(fonts), render_public(fonts)
    probs = size_problems(public)
    if probs:
        print("installer_art: " + "; ".join(probs), file=sys.stderr)
        return 1
    for d, fs in ((out, files), (pub, public)):
        d.mkdir(parents=True, exist_ok=True)
        for name, (data, _) in fs.items():
            (d / name).write_bytes(data)
    mpath.write_text(json.dumps(manifest(files, fonts, public), indent=1) + "\n", encoding="utf-8", newline="\n")
    if a.preview:
        contact_sheet(files, a.preview, a.stand_in_fonts)
    print(f"installer_art: wrote {len(files)} files + art.json to {out}, {len(public)} to {pub} "
          f"({', '.join(f'{n} {len(b)} B' for n, (b, _) in sorted(public.items()))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
