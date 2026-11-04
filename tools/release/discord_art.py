#!/usr/bin/env python3
"""Discord application art for Project Pyrrhus's Rich Presence, drawn by installer_art.py's emblem code.

The same shapes, palette and fonts as the installer icons (no game logo, symbol or game art). The images are uploaded
by hand to the Discord developer portal and are not shipped or committed. Needs Pillow (the .#re shell) and the fonts
in work/release/fonts (installer_art.py --fetch-fonts).

    python3 tools/release/discord_art.py [--out work/release/discord]

Outputs, in Project Helghast's Discord style (its work/coord/discord files, 2026-10-22):
  kz2-discord-{512,1024}.png        the shortcut-icon emblem with chamfered corners (alpha): the App Icon and the Rich
                                    Presence art asset with key "kz2" (large_image).
  kz2-discord-cover-{1024x576,1920x1080}.png   the social-preview layout at 16:9 for the Rich Presence cover image
                                    (Discord crops a square to 16:9 there, which cut off the PC bar in Project
                                    Helghast's first try).
  preview.png                       the icon and the cover side by side (for checking, not uploaded).
ASSUMPTION: Discord asks for at least 512x512 for both and recommends 1024x1024.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import installer_art as ia  # noqa: E402

ICONS = (512, 1024)
COVERS = ((1024, 576), (1920, 1080))


def preview(icon, cover):
    from PIL import Image
    h = 288
    iw, cw = h, round(cover.width * h / cover.height)
    sheet = Image.new("RGB", (iw + cw + 24, h + 16), ia.rgb("bg"))
    sheet.paste(icon.resize((iw, h), Image.Resampling.LANCZOS), (8, 8), icon.resize((iw, h), Image.Resampling.LANCZOS))
    sheet.paste(cover.resize((cw, h), Image.Resampling.LANCZOS).convert("RGB"), (iw + 16, 8))
    return sheet


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ia.ROOT / "work" / "release" / "discord"))
    ap.add_argument("--fonts", default=str(ia.FONTS))
    a = ap.parse_args(argv)
    fonts = ia.Fonts(a.fonts)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for n in ICONS:
        icon = ia.tile(fonts, n, n, alpha=True)
        names.append(f"kz2-discord-{n}.png")
        icon.save(out / names[-1], optimize=True)
    for w, h in COVERS:
        cover = ia.social_preview(fonts, w, h)
        names.append(f"kz2-discord-cover-{w}x{h}.png")
        cover.save(out / names[-1], optimize=True)
    preview(icon, cover).save(out / "preview.png")
    for f in names + ["preview.png"]:
        print(out / f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
