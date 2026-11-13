<p align="center">
  <img src="assets/banner.png" srcset="assets/banner@2x.png 2x" width="1280"
       alt="Project Pyrrhus. Killzone 2: Unofficial PC Port (static recompilation), built on your PC from your own game">
</p>

# Project Pyrrhus

**Killzone 2 (PS3) as a native Windows program, built on your PC from your own copy: an unofficial port by static recompilation.**

[![CI](https://github.com/undecuple/project-pyrrhus/actions/workflows/ci.yml/badge.svg)](https://github.com/undecuple/project-pyrrhus/actions/workflows/ci.yml) <!-- version -->[![pre-release 0.1.13](https://img.shields.io/badge/pre--release-0.1.13-b4500f?style=flat-square&labelColor=17130f)](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.13)<!-- /version --> [![Licence: MIT](https://img.shields.io/badge/licence-MIT-b4500f?style=flat-square&labelColor=17130f)](LICENSE) [![Ask DeepWiki](https://img.shields.io/badge/DeepWiki-Ask-b4500f?style=flat-square&labelColor=17130f)](https://deepwiki.com/undecuple/project-pyrrhus)

> **Bring your own game.** This repository holds no game code, assets, keys or firmware, and downloads none. You
> need your own Killzone 2 disc dump, its 1.29 update and the decrypted EBOOT made from your copy
> ([what each must contain](docs/GETTING-FILES.md)).

| | | | |
|---|---|---|---|
| **23-33 fps** in the first level, scripted runs under Proton (PS3: 30) · [proof](docs/KNOWN_ISSUES.md#frame-rate) | **4 disc regions** accepted, US tested · [proof](docs/GETTING-FILES.md#regions) | **0 game files** in the repo or the downloads · [proof](docs/HOW-IT-WORKS.md#in-short) | **About 18 minutes** to build with four jobs · [proof](docs/BUILDING.md#steps) |

**[Download](https://github.com/undecuple/project-pyrrhus/releases)** · **[Install walkthrough and FAQ](docs/FAQ.md)** · **[Known issues](docs/KNOWN_ISSUES.md)** · **[Reporting bugs](https://github.com/undecuple/project-pyrrhus/issues/new/choose)** · **[More](#more)**

## Play it

**Windows 10 or 11 (64-bit):**
1. Download `Project-Pyrrhus-setup.exe` (or the portable zip) from the [releases page](https://github.com/undecuple/project-pyrrhus/releases).
2. Point it at your disc dump, the 1.29 update and the decrypted EBOOT; if you play the game in RPCS3, "Use my RPCS3 install" finds them.
3. Start the game from the launcher.

*Caveat:* native Windows is not yet confirmed by us (players report playing there). The first start translates and builds the game on your PC, which takes a while. It needs a CPU with AVX and FMA3 and a Direct3D 12 graphics card ([requirements](docs/requirements.md)).

**Linux:**
1. Run the same Windows download under Proton, for example as a non-Steam game in Steam.

*Caveat:* the installer and the zip are made for Windows and not checked under Proton; we test the built game under GE-Proton ([known issues](docs/KNOWN_ISSUES.md)).

## What makes it different

| Claim | Proof |
|---|---|
| A native Windows x64 program: the game's own code, recompiled ahead of time; no CPU emulator runs while you play (the graphics commands are translated at run time) | [How it works](docs/HOW-IT-WORKS.md#in-short) |
| Most of the game's SPU post-processing runs as native C by default (each job has a switch back), giving the same output bits as the recompiled jobs on the tested inputs | [How it works](docs/HOW-IT-WORKS.md#what-kind-of-port-is-this) |
| Field of view (45-75) and FSR 1 upscaling as rows on the game's own Display page (FSR 1 checked in the menu only, not yet in play) | [Features](docs/FEATURES.md), [roadmap](docs/ROADMAP.md) |
| Shaders built during the load from a shipped list: pauses over 0.1 s in the first minute fell from 18-20 to 2 in paired scripted runs (not yet measured in an installed copy) | [Known issues](docs/KNOWN_ISSUES.md#frame-rate) |
| The setup checks your files before building and names what is wrong | [Getting your files](docs/GETTING-FILES.md#what-the-first-run-check-can-print) |

## Coming soon

Not done yet, and said openly: a steady 30 frames per second, the campaign past the first level, loading checkpoint
saves back, 5.1 surround sound, and multiplayer (offline bots and self-hosted online). Where each stands:
[roadmap](docs/ROADMAP.md) and [feature table](docs/FEATURES.md).

## Status

**Status:** <!-- version -->[v0.1.13](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.13)<!-- /version --> is a pre-release, partly playable: the intro movie plays, the menus run with sound, and the first level loads and can be played. Speed is below the PS3's 30 frames per second in our scripted runs. MIT licence. Direct3D 12 only.

### Compatibility

One row per setup. *Verified* means we ran it on that setup; *implemented* means the code is in but we have not run it
there; *planned* means neither. Full dated table: [docs/STATUS.md](docs/STATUS.md).

| Platform | How it runs | Renderer | State | Tested on |
|---|---|---|---|---|
| Windows 11 | native exe | Direct3D 12 | players report playing (issue #13); not run by us | a player's laptop: RTX 4070 Laptop GPU (21-28 fps in the first part of the first level, their report) |
| Windows 10 | native exe, in a virtual machine | Direct3D 12 | installer, first-run build and uninstall verified; the game starts and stops at its graphics device (no GPU there) | 6 cores, 8 GB, no GPU, 2026-10-27 and 2026-10-28 |
| Linux | the Windows exe under Proton | Direct3D 12 | verified: the first level loads and plays in our scripted runs, about 23 fps over one 330 s run (2026-10-22) and a median of 32.6 fps in short turn-and-walk windows (2026-10-29), against the PS3's 30; hand play is not measured | GE-Proton11-7, i7-12700KF, RTX 4060 |

Optional features, same three states (both new in 0.1.7):

| Feature | State | Tested on |
|---|---|---|
| Options > Display: field of view (45-75, 45 is the original), first-person only | verified in play under Proton (45, 60, 75) | GE-Proton11-7, RTX 4060 |
| Options > Display: upscaling (Off / FSR 1) and sharpness | implemented; drawn in the menu under Proton, not yet checked in play; adds about 0.4-1.3 ms of graphics time per frame at 2560x1440 in our tests | GE-Proton11-7, RTX 4060 |

## Install in detail

**You need:**

- **Your Killzone 2 disc**, dumped as a folder or as a decrypted `.iso`: US (BCUS98116, tested), or Europe
  (BCES00081), Asia (BCAS20066) or Japan (BCJS30032), which are accepted but untested: the code is the same, the data
  differs, and no one has played them through yet ([docs/GETTING-FILES.md](docs/GETTING-FILES.md#regions)).
- **The 1.29 update of the same region** from your copy (on a PS3 or in RPCS3: the `dev_hdd0/game/<title id>` folder,
  such as `dev_hdd0/game/BCUS98116`).
- **The decrypted 1.29 EBOOT** (`EBOOT.elf`), made from that update's `EBOOT.BIN`.
- Windows 10 or 11 (64-bit) with a CPU that has AVX and FMA3 (about 2013 or later), 16 GB of RAM advised for the build, and a Direct3D 12 graphics card: [docs/requirements.md](docs/requirements.md).

No CPU emulator runs while you play. If you play the game in the PS3 emulator RPCS3, the setup can find all three in
your RPCS3 install ("Use my RPCS3 install"). What each must contain:
[docs/GETTING-FILES.md](docs/GETTING-FILES.md). This project ships none of them and gives no decryption steps.

1. Download the Windows installer (recommended) or the portable zip from <!-- version -->[v0.1.13](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.13)<!-- /version --> on the [releases page](https://github.com/undecuple/project-pyrrhus/releases) (every release is a pre-release for now).
2. Run it and point it at your disc dump, the 1.29 update and the decrypted EBOOT.
3. It translates and builds the game's code on your machine; no game code, assets or keys are shipped or downloaded.
4. Start the game from the launcher.

Do not install into a OneDrive folder. The settings files (`keybinds.ini`, `gameplay.ini`; the latter is created with its defaults on the first start, and an existing one is never changed) are in `%APPDATA%\Project Pyrrhus`, or next to `kz2.exe` in the portable zip. More: [docs/INSTALL.md](docs/INSTALL.md), [CHANGELOG.md](CHANGELOG.md).

## How it works

The game's PPU and SPU code is recompiled ahead of time to native x64; the graphics commands are translated to
Direct3D 12 at run time; the system libraries are reimplemented on PC APIs. Details: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).
Settings and controls: [docs/FEATURES.md](docs/FEATURES.md), [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md). Building
it yourself: [docs/BUILDING.md](docs/BUILDING.md).

## More

[Features](docs/FEATURES.md) · [Screenshots](docs/SCREENSHOTS.md) · [Requirements](docs/requirements.md) · [How it works](docs/HOW-IT-WORKS.md) · [Accessibility](docs/ACCESSIBILITY.md) · [Roadmap](docs/ROADMAP.md) · [Release criteria](docs/RELEASE-CRITERIA.md) · [What goes online](docs/PRIVACY.md) · [How AI was used](docs/AI.md) · [Contributing](.github/CONTRIBUTING.md)

## Related projects

**[Project Helghast](https://github.com/undecuple/project-helghast)**: Killzone 3 (PS3) ported to PC the same way.
Project Pyrrhus uses its method and reuses its general runtime work (ps3recomp fixes, renderer, SPU job system),
adapted to Killzone 2. Most patches in `port/patches/` come from there; the rest are Killzone 2's own. Its builds are
pre-releases on its [releases page](https://github.com/undecuple/project-helghast/releases), as this project's are.

This port currently supports Direct3D 12 only. For a Vulkan version of a Killzone 2 port, please use [Tokisaki Port](https://github.com/YYOzcan/tokisaki-port), which is developed separately by its own author.

## Official channels

Project Pyrrhus is made by **undecuple**: GitHub [@undecuple](https://github.com/undecuple), Reddit [u/RelationshipNo4440](https://www.reddit.com/user/RelationshipNo4440), Discord **itekso.** (on the ps3recomp server). Builds and fixes come only from this repository's [GitHub Releases](https://github.com/undecuple/project-pyrrhus/releases); we never ask anyone to paste a command into PowerShell or a terminal. Anyone else offering builds, "fixes" or donations in this project's name is not us.

## Contributing

Pull requests are welcome: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).

## How AI was used

This project is developed by one person with AI coding agents, with the maintainer reviewing and merging their work: [docs/AI.md](docs/AI.md).

## Licence and disclaimer

The port's own code, tools and documentation: [MIT](LICENSE). Third-party components and credits: [NOTICE.md](NOTICE.md). The licence covers nothing of the game itself. Security problems: [SECURITY.md](.github/SECURITY.md). Reuse, including by AI systems and automated tools: [NOTICE.md](NOTICE.md#reuse-and-attribution-including-ai-and-automated-use).

*Pyrrhus* is the Helghast capital where most of Killzone 2 is fought; Project Pyrrhus is a fan project, not official
and not affiliated with or endorsed by Sony Interactive Entertainment or Guerrilla Games.

**You need your own copy of the game.** This repository contains only the port: source code, patches to the
recompiler, tools and documentation. It contains no game code, data, assets, keys or firmware, and it never will.
Killzone 2 is © Sony Interactive Entertainment.
