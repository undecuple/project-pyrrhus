<p align="center">
  <img src="assets/banner.png" srcset="assets/banner@2x.png 2x" width="1280"
       alt="Project Pyrrhus. Killzone 2: Unofficial PC Port (static recompilation), built on your PC from your own game">
</p>

<h1 align="center">Project Pyrrhus</h1>

<p align="center"><b>Killzone 2 (PS3) as a native Windows program, built on your PC from your own copy.</b><br>
An unofficial fan port by static recompilation.</p>

<p align="center">
  <a href="https://github.com/undecuple/project-pyrrhus/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/undecuple/project-pyrrhus/actions/workflows/ci.yml/badge.svg"></a> <!-- version --><a href="https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.13"><img alt="pre-release 0.1.13" src="https://img.shields.io/badge/pre--release-0.1.13-b4500f?style=flat-square&labelColor=17130f"></a><!-- /version -->
  <a href="https://github.com/undecuple/project-pyrrhus/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/undecuple/project-pyrrhus/total?style=flat-square&color=b4500f&labelColor=17130f"></a>
  <a href="https://github.com/undecuple/project-pyrrhus/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/undecuple/project-pyrrhus?style=flat-square&color=b4500f&labelColor=17130f"></a>
</p>
<p align="center">
  <a href="LICENSE"><img alt="Licence: MIT" src="https://img.shields.io/badge/licence-MIT-b4500f?style=flat-square&labelColor=17130f"></a>
  <a href="https://github.com/undecuple/project-pyrrhus/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/undecuple/project-pyrrhus?style=flat-square&color=b4500f&labelColor=17130f"></a>
  <a href="https://github.com/undecuple/project-pyrrhus/issues"><img alt="Issues" src="https://img.shields.io/github/issues/undecuple/project-pyrrhus?style=flat-square&color=b4500f&labelColor=17130f"></a>
</p>
<p align="center">
  <img alt="Platform: Windows" src="https://img.shields.io/badge/platform-Windows-b4500f?style=flat-square&labelColor=17130f">
  <img alt="Renderer: Direct3D 12" src="https://img.shields.io/badge/renderer-Direct3D%2012-b4500f?style=flat-square&labelColor=17130f">
  <a href="https://deepwiki.com/undecuple/project-pyrrhus"><img alt="Ask DeepWiki" src="https://img.shields.io/badge/DeepWiki-Ask-b4500f?style=flat-square&labelColor=17130f"></a>
</p>

<p align="center">
  <b><a href="https://github.com/undecuple/project-pyrrhus/releases">Download</a></b> ·
  <b><a href="docs/INSTALL.md">Installing</a></b> ·
  <b><a href="docs/FAQ.md">Install walkthrough and FAQ</a></b> ·
  <b><a href="https://github.com/undecuple/project-pyrrhus/issues/new/choose">Report an issue</a></b> ·
  <b><a href="docs/BUILDING.md">Build from source</a></b>
</p>

---

**Project Pyrrhus** is an unofficial fan port of Killzone 2 (PS3) to Windows x64. The game's own code is recompiled ahead of time to a native program, and the setup builds it on your PC from your own copy.

> **Bring your own game.** This repository holds no game code, assets, keys or firmware, and downloads none. You
> need your own Killzone 2 disc dump, its 1.29 update and the decrypted EBOOT made from your copy
> ([what each must contain](docs/GETTING-FILES.md)).

---

## Status

**Status:** <!-- version -->[v0.1.13](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.13)<!-- /version --> is a pre-release, partly playable. The intro movie plays, the menus run with sound, and the first level loads and can be played. Speed is below the PS3's 30 frames per second in our scripted runs. Direct3D 12 only.

| | | | |
|---|---|---|---|
| **23-33 fps** in the first level, scripted runs under Proton (PS3: 30) · [proof](docs/KNOWN_ISSUES.md#frame-rate) | **4 disc regions** accepted, US tested · [proof](docs/GETTING-FILES.md#regions) | **0 game files** in the repo or the downloads · [proof](docs/HOW-IT-WORKS.md#in-short) | **About 18 minutes** to build with four jobs · [proof](docs/BUILDING.md#steps) |

One row per setup. *Verified* means we ran it on that setup. *Implemented* means the code is in but we have not run it there. *Planned* means neither. The full dated table is [docs/STATUS.md](docs/STATUS.md).

| Platform | How it runs | Renderer | State | Tested on |
|---|---|---|---|---|
| Windows 11 | native exe | Direct3D 12 | players report playing (issue #13); not run by us | a player's laptop: RTX 4070 Laptop GPU (21-28 fps in the first part of the first level, their report) |
| Windows 10 | native exe, in a virtual machine | Direct3D 12 | installer, first-run build and uninstall verified; the game starts and stops at its graphics device (no GPU there) | 6 cores, 8 GB, no GPU, 2026-10-27 and 2026-10-28 |
| Linux | the Windows exe under Proton | Direct3D 12 | verified: the first level loads and plays in our scripted runs, about 23 fps over one 330 s run (2026-10-22) and a median of 32.6 fps in short turn-and-walk windows (2026-10-29), against the PS3's 30; hand play is not measured | GE-Proton11-7, i7-12700KF, RTX 4060 |

Optional features, in the same three states (both new in 0.1.7):

| Feature | State | Tested on |
|---|---|---|
| Options > Display: field of view (45-75, 45 is the original), first-person only | verified in play under Proton (45, 60, 75) | GE-Proton11-7, RTX 4060 |
| Options > Display: upscaling (Off / FSR 1) and sharpness | implemented; drawn in the menu under Proton, not yet checked in play; adds about 0.4-1.3 ms of graphics time per frame at 2560x1440 in our tests | GE-Proton11-7, RTX 4060 |

---

## Download and play

**What you need:**

- **Windows 10 or 11 (64-bit)** with a Direct3D 12 graphics card ([requirements](docs/requirements.md)).
- **A CPU with AVX and FMA3** (about 2013 or later), and 16 GB of RAM advised for the build.
- **Your Killzone 2 disc**, dumped as a folder or as a decrypted `.iso`. US (BCUS98116) is tested. Europe (BCES00081), Asia (BCAS20066) and Japan (BCJS30032) are accepted but untested ([regions](docs/GETTING-FILES.md#regions)).
- **The 1.29 update of the same region**, from your copy.
- **The decrypted 1.29 EBOOT** (`EBOOT.elf`), made from that update's `EBOOT.BIN`.
- **Not included:** all three files. This project ships none of them and gives no decryption steps.

**Install:**

1. Download `Project-Pyrrhus-setup.exe` (or the portable zip) from <!-- version -->[v0.1.13](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.13)<!-- /version --> on the [releases page](https://github.com/undecuple/project-pyrrhus/releases). Every release is a pre-release for now. You should see the file in your Downloads folder.
2. Run it and point it at your disc dump, the 1.29 update and the decrypted EBOOT. If you play in RPCS3, "Use my RPCS3 install" finds all three. You should see the setup check your files and name anything wrong.
3. Let it build. The first start translates and builds the game's code on your PC, which takes a while (about 18 minutes with four jobs). No game code, assets or keys are shipped or downloaded.
4. Start the game from the launcher. You should see the intro movie, then the menus.

Do not install into a OneDrive folder. Native Windows is not yet confirmed by us, although players report playing there.

If setup fails or the game does not start, see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). Full steps: [docs/INSTALL.md](docs/INSTALL.md) and [docs/GETTING-FILES.md](docs/GETTING-FILES.md).

**Linux:** run the same Windows download under Proton, for example as a non-Steam game in Steam. The installer and the zip are made for Windows and not checked under Proton. We test the built game under GE-Proton ([known issues](docs/KNOWN_ISSUES.md)).

---

## What goes online and where your data goes

Nothing, unless you ask: the port starts no connection of its own. The optional check for new versions and the update download are described in [docs/PRIVACY.md](docs/PRIVACY.md).

---

## What makes it different

| Claim | Proof |
|---|---|
| A native Windows x64 program: the game's own code, recompiled ahead of time. No CPU emulator runs while you play (the graphics commands are translated at run time) | [How it works](docs/HOW-IT-WORKS.md#in-short) |
| Most of the game's SPU post-processing runs as native C by default (each job has a switch back). It gives the same output bits as the recompiled jobs on the tested inputs | [How it works](docs/HOW-IT-WORKS.md#what-kind-of-port-is-this) |
| Field of view (45-75) and FSR 1 upscaling as rows on the game's own Display page (FSR 1 checked in the menu only, not yet in play) | [Features](docs/FEATURES.md), [roadmap](docs/ROADMAP.md) |
| Shaders built during the load from a shipped list: pauses over 0.1 s in the first minute fell from 18-20 to 2 in paired scripted runs (not yet measured in an installed copy) | [Known issues](docs/KNOWN_ISSUES.md#frame-rate) |
| The setup checks your files before building and names what is wrong | [Getting your files](docs/GETTING-FILES.md#what-the-first-run-check-can-print) |

---

## Settings and controllers

- **Controls:** a keyboard and mouse, or a pad through SDL3 (PlayStation, Xbox and other pads SDL3 recognises; Windows' XInput is the fallback). Only the DualShock 4 has been hand-tested (2026-10-22). Xbox, DualSense and other pads are untested.
- **Settings files:** `keybinds.ini` and `gameplay.ini` are in `%APPDATA%\Project Pyrrhus`, or next to `kz2.exe` in the portable zip. `gameplay.ini` is created with its defaults on the first start, and an existing one is never changed.
- More: [features](docs/FEATURES.md) and [accessibility](docs/ACCESSIBILITY.md).

---

## Known issues

The main ones: speed is not yet a steady 30 frames per second, and only the first level has been played. Sound is stereo only. Shaders compile on first use, which stutters the first minute of each area. The full list is [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

---

## Troubleshooting and reporting bugs

Problems are listed by what you see, with the cause, the fix and the log paths, in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). To report a bug, [open an issue](https://github.com/undecuple/project-pyrrhus/issues/new/choose). The form asks for your system and the newest log file.

---

## Building

You can build the port yourself. It needs a lot of memory and about 18 minutes with four jobs. Steps: [docs/BUILDING.md](docs/BUILDING.md).

---

## How it works

The game's PPU and SPU code is recompiled ahead of time to native x64. The graphics commands are translated to Direct3D 12 at run time. The system libraries are reimplemented on PC APIs. Details: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).

---

## Roadmap

Not done yet, and said openly: a steady 30 frames per second, the campaign past the first level, and loading checkpoint saves back. Also 5.1 surround sound, and multiplayer (offline bots and self-hosted online). Where each stands: [roadmap](docs/ROADMAP.md) and [feature table](docs/FEATURES.md).

---

## Contributing

Pull requests are welcome: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md). People whose pull requests were merged are named in [CONTRIBUTORS.md](CONTRIBUTORS.md).

---

## How AI was used

This project is developed by one person with AI coding agents, with the maintainer reviewing and merging their work: [docs/AI.md](docs/AI.md).

---

## Licence and disclaimer

The port's own code, tools and documentation: [MIT](LICENSE). Third-party components and credits: [NOTICE.md](NOTICE.md). The licence covers nothing of the game itself. Security problems: [SECURITY.md](.github/SECURITY.md). Reuse, including by AI systems and automated tools: [NOTICE.md](NOTICE.md#reuse-and-attribution-including-ai-and-automated-use).

*Pyrrhus* is the Helghast capital where most of Killzone 2 is fought. Project Pyrrhus is a fan project, not official and not affiliated with or endorsed by Sony Interactive Entertainment or Guerrilla Games.

**You need your own copy of the game.** This repository contains only the port: source code, patches to the recompiler, tools and documentation. It contains no game code, data, assets, keys or firmware, and it never will. Killzone 2 is © Sony Interactive Entertainment.

---

## Related projects, credits and official channels

**[Project Helghast](https://github.com/undecuple/project-helghast)**: Killzone 3 (PS3) ported to PC the same way. Project Pyrrhus uses its method and reuses its general runtime work (ps3recomp fixes, renderer, SPU job system), adapted to Killzone 2. Most patches in `port/patches/` come from there; the rest are Killzone 2's own. Its builds are pre-releases on its [releases page](https://github.com/undecuple/project-helghast/releases), as this project's are.

**[Project Vekta](https://github.com/gustavomorinaga/project-vekta)**: Killzone HD, the PS3 remaster of the first Killzone, ported to PC the same way by Gustavo Morinaga, with Windows and Linux [pre-releases](https://github.com/gustavomorinaga/project-vekta/releases). Its README has the current state.

This port currently supports Direct3D 12 only. For a Vulkan version of a Killzone 2 port, please use [Tokisaki Port](https://github.com/YYOzcan/tokisaki-port), which is developed separately by its own author.

Project Pyrrhus is made by **undecuple**: GitHub [@undecuple](https://github.com/undecuple), Reddit [u/RelationshipNo4440](https://www.reddit.com/user/RelationshipNo4440) and the [undecuple Discord server](https://discord.gg/W8fMT78Q7k) [![Discord](https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white)](https://discord.gg/W8fMT78Q7k) (unofficial fan work), which has a Project Pyrrhus forum. Builds and fixes come only from this repository's [GitHub Releases](https://github.com/undecuple/project-pyrrhus/releases). We never ask anyone to paste a command into PowerShell or a terminal. Anyone else offering builds, "fixes" or donations in this project's name is not us.

More pages: [Features](docs/FEATURES.md) · [Screenshots](docs/SCREENSHOTS.md) · [Requirements](docs/requirements.md) · [Release criteria](docs/RELEASE-CRITERIA.md) · [Changelog](CHANGELOG.md)
