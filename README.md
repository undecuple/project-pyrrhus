<p align="center">
  <img src="assets/banner.png" srcset="assets/banner@2x.png 2x" width="1280"
       alt="Project Pyrrhus. Killzone 2: Unofficial PC Port (static recompilation), built on your PC from your own game">
</p>

# Project Pyrrhus (work in progress)

**Killzone 2: Unofficial PC Port (static recompilation)**

[![CI](https://github.com/undecuple/project-pyrrhus/actions/workflows/ci.yml/badge.svg)](https://github.com/undecuple/project-pyrrhus/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![Status: partly playable](https://img.shields.io/badge/status-partly%20playable-orange)
[![Release](https://img.shields.io/github/v/release/undecuple/project-pyrrhus?include_prereleases&label=release)](https://github.com/undecuple/project-pyrrhus/releases)
[![Downloads](https://img.shields.io/github/downloads/undecuple/project-pyrrhus/total)](https://github.com/undecuple/project-pyrrhus/releases)
![Windows x64](https://img.shields.io/badge/platform-Windows%20x64-0078D6)
![Direct3D 12](https://img.shields.io/badge/graphics-Direct3D%2012-555)

**[Status](docs/STATUS.md)** · **[Features](docs/FEATURES.md)** · **[Screenshots](docs/SCREENSHOTS.md)** · **[Requirements](docs/requirements.md)** · **[Getting it](docs/INSTALL.md)** · **[Building](docs/BUILDING.md)** · **[How it works](docs/HOW-IT-WORKS.md)** · **[Known issues](docs/KNOWN_ISSUES.md)** · **[Accessibility](docs/ACCESSIBILITY.md)** · **[Roadmap](docs/ROADMAP.md)** · **[Release criteria](docs/RELEASE-CRITERIA.md)** · **[What goes online](docs/PRIVACY.md)** · **[AI use](docs/AI.md)** · **[Contributing](.github/CONTRIBUTING.md)** · **[Related project](#related-project)**

An unofficial port of **Killzone 2** (PS3, 2009) to Windows x64, built on your PC from your own copy of the game. It is a
static recompilation: the game's own code, translated ahead of time to native x64. It is **not an emulator** and **not
a rewrite**. How it works: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).

> **Status: early, partly playable.** The intro movie plays, the menus run with sound, and the first level loads and
> draws, at about 23 frames per second in one scripted run (the PS3 runs it at 30; hand play is not measured). Full
> dated table: [docs/STATUS.md](docs/STATUS.md).

<p align="center">
  <a href="docs/SCREENSHOTS.md"><img src="docs/screenshots/20261028_kz2-corinth-river-in-play.png" width="720"
       alt="Killzone 2 running in the port: the first level in first person, with the weapon, crosshair and ammo counter"></a>
</p>

### What you need

- **Your Killzone 2 disc** (US, BCUS98116), dumped as a folder or as a decrypted `.iso`.
- **The 1.29 update** from your copy (on a PS3 or in RPCS3: the `dev_hdd0/game/BCUS98116` folder).
- **The decrypted 1.29 EBOOT** (`EBOOT.elf`), made from that update's `EBOOT.BIN`.

No emulator runs while you play. If you play the game in the PS3 emulator RPCS3, the setup can find all three in
your RPCS3 install ("Use my RPCS3 install"). What each must contain:
[docs/GETTING-FILES.md](docs/GETTING-FILES.md). This project ships none of them and gives no decryption steps.

## Getting it

1. Download the Windows installer (recommended) or the portable zip from <!-- version -->[v0.1.6](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.6)<!-- /version --> on the [releases page](https://github.com/undecuple/project-pyrrhus/releases) (every release is a pre-release for now).
2. Run it and point it at your disc dump, the 1.29 update and the decrypted EBOOT.
3. It translates and builds the game's code on your machine; no game code, assets or keys are shipped or downloaded.
4. Start the game from the launcher.

Do not install into a OneDrive folder. More: [docs/INSTALL.md](docs/INSTALL.md), [docs/GETTING-FILES.md](docs/GETTING-FILES.md), [docs/requirements.md](docs/requirements.md). Changes per version: [CHANGELOG.md](CHANGELOG.md).

## Known problems

- The sky draws green in the first level (cause not yet known).
- Speed is below the PS3's in scripted runs; hand play is not measured.
- Not yet confirmed on native Windows by us (players report playing there).
- Keyboard and mouse: only checked in scripted runs, not by hand; pads work.

All of them: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

## Related project

**[Project Helghast](https://github.com/undecuple/project-helghast)**: Killzone 3 (PS3) ported to PC the same way.
Project Pyrrhus uses its method and reuses its general runtime work (ps3recomp fixes, renderer, SPU job system),
adapted to Killzone 2. Most patches in `port/patches/` come from there; the rest are Killzone 2's own. Its builds are
pre-releases on its [releases page](https://github.com/undecuple/project-helghast/releases), as this project's are.

This port currently supports Direct3D 12 only. For a Vulkan version of a Killzone 2 port, please use [Tokisaki Port](https://github.com/YYOzcan/tokisaki-port), which is developed separately by its own author.

## Official channels

Project Pyrrhus is made by **undecuple**: GitHub [@undecuple](https://github.com/undecuple), Reddit [u/RelationshipNo4440](https://www.reddit.com/user/RelationshipNo4440), Discord **itekso.** (on the ps3recomp server). Builds and fixes come only from this repository's [GitHub Releases](https://github.com/undecuple/project-pyrrhus/releases); we never ask anyone to paste a command into PowerShell or a terminal. Anyone else offering builds, "fixes" or donations in this project's name is not us.

## Contributing

Pull requests are welcome: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).

## AI, licence, disclaimer

This project is developed by one person with AI coding agents, with the maintainer reviewing and merging their work: [docs/AI.md](docs/AI.md).

The port's own code, tools and documentation: [MIT](LICENSE). Third-party components and credits: [NOTICE.md](NOTICE.md). The licence covers nothing of the game itself. Security problems: [SECURITY.md](.github/SECURITY.md). Reuse, including by AI systems and automated tools: [NOTICE.md](NOTICE.md#reuse-and-attribution-including-ai-and-automated-use).

*Pyrrhus* is the Helghast capital where most of Killzone 2 is fought; Project Pyrrhus is a fan project, not official
and not affiliated with or endorsed by Sony Interactive Entertainment or Guerrilla Games.

**You need your own copy of the game.** This repository contains only the port: source code, patches to the
recompiler, tools and documentation. It contains no game code, data, assets, keys or firmware, and it never will.
Killzone 2 is © Sony Interactive Entertainment.
