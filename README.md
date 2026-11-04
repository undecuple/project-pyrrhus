<p align="center">
  <img src="assets/banner.png" srcset="assets/banner@2x.png 2x" width="1280"
       alt="Project Pyrrhus. Killzone 2: Unofficial PC Port (static recompilation), built on your PC from your own game">
</p>

# Project Pyrrhus

**Killzone 2: Unofficial PC Port (static recompilation)**

[![CI](https://github.com/undecuple/project-pyrrhus/actions/workflows/ci.yml/badge.svg)](https://github.com/undecuple/project-pyrrhus/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/undecuple/project-pyrrhus?include_prereleases&label=release)](https://github.com/undecuple/project-pyrrhus/releases)
[![Downloads](https://img.shields.io/github/downloads/undecuple/project-pyrrhus/total)](https://github.com/undecuple/project-pyrrhus/releases)

Project Pyrrhus is a native Windows x64 port of **Killzone 2** (PS3, 2009), made by static recompilation of the game's own
code. You build it on your PC from your own US disc (BCUS98116) with the 1.29 update; it is **not an emulator** and
**not a rewrite**, and it ships none of the game.

**Status:** <!-- version -->[v0.1.10](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.10)<!-- /version --> is a pre-release, partly playable: the intro movie plays, the menus run with sound, and the first level loads and can be played. Speed is below the PS3's 30 frames per second in our scripted runs (below). MIT licence. Direct3D 12 only.

**[Download](#download-and-install)** · **[Compatibility](#compatibility)** · **[Building](docs/BUILDING.md)** · **[Known issues](docs/KNOWN_ISSUES.md)** · **[Reporting bugs](https://github.com/undecuple/project-pyrrhus/issues/new/choose)** · **[More](#more)**

<p align="center">
  <a href="docs/SCREENSHOTS.md"><img src="docs/screenshots/20261028_kz2-corinth-river-in-play.png" width="720"
       alt="Killzone 2 running in the port: the first level in first person, with the weapon, crosshair and ammo counter"></a><br>
  <sub>The first level in play on 2026-10-28 (an older build, under Proton). More: <a href="docs/SCREENSHOTS.md">screenshots</a>.</sub>
</p>

## Compatibility

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

## Download and install

**You need:**

- **Your Killzone 2 disc** (US, BCUS98116), dumped as a folder or as a decrypted `.iso`.
- **The 1.29 update** from your copy (on a PS3 or in RPCS3: the `dev_hdd0/game/BCUS98116` folder).
- **The decrypted 1.29 EBOOT** (`EBOOT.elf`), made from that update's `EBOOT.BIN`.
- Windows 10 or 11 (64-bit) with a CPU that has AVX and FMA3 (about 2013 or later), 16 GB of RAM advised for the build, and a Direct3D 12 graphics card: [docs/requirements.md](docs/requirements.md).

No emulator runs while you play. If you play the game in the PS3 emulator RPCS3, the setup can find all three in
your RPCS3 install ("Use my RPCS3 install"). What each must contain:
[docs/GETTING-FILES.md](docs/GETTING-FILES.md). This project ships none of them and gives no decryption steps.

1. Download the Windows installer (recommended) or the portable zip from <!-- version -->[v0.1.10](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.10)<!-- /version --> on the [releases page](https://github.com/undecuple/project-pyrrhus/releases) (every release is a pre-release for now).
2. Run it and point it at your disc dump, the 1.29 update and the decrypted EBOOT.
3. It translates and builds the game's code on your machine; no game code, assets or keys are shipped or downloaded.
4. Start the game from the launcher.

Do not install into a OneDrive folder. The settings files (`keybinds.ini`, `gameplay.ini`; the latter is created with its defaults on the first start, and an existing one is never changed) are in `%APPDATA%\Project Pyrrhus`, or next to `kz2.exe` in the portable zip. More: [docs/INSTALL.md](docs/INSTALL.md), [CHANGELOG.md](CHANGELOG.md).

## Settings and known issues

Pads (PlayStation and Xbox, through SDL3), keyboard and mouse, button prompts, window modes and the Display rows are in
[docs/FEATURES.md](docs/FEATURES.md) and [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md). The main problems today:

- Speed is below the PS3's in scripted runs; hand play is not measured.
- Only the first level has been played; the campaign has not been played through.
- Keyboard and mouse: checked in scripted runs, not by hand; pads work.
- Not yet confirmed on native Windows by us (players report playing there).

All of them: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

## Building

The installer builds the port on your machine; to build it yourself, see [docs/BUILDING.md](docs/BUILDING.md). The build
is heavy: about 18 minutes with four jobs, and over 1 GB of memory per compile job.

## More

[Features](docs/FEATURES.md) · [Screenshots](docs/SCREENSHOTS.md) · [Requirements](docs/requirements.md) · [How it works](docs/HOW-IT-WORKS.md) · [Accessibility](docs/ACCESSIBILITY.md) · [Roadmap](docs/ROADMAP.md) · [Release criteria](docs/RELEASE-CRITERIA.md) · [What goes online](docs/PRIVACY.md) · [AI use](docs/AI.md) · [Contributing](.github/CONTRIBUTING.md)

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

## AI, licence, disclaimer

This project is developed by one person with AI coding agents, with the maintainer reviewing and merging their work: [docs/AI.md](docs/AI.md).

The port's own code, tools and documentation: [MIT](LICENSE). Third-party components and credits: [NOTICE.md](NOTICE.md). The licence covers nothing of the game itself. Security problems: [SECURITY.md](.github/SECURITY.md). Reuse, including by AI systems and automated tools: [NOTICE.md](NOTICE.md#reuse-and-attribution-including-ai-and-automated-use).

*Pyrrhus* is the Helghast capital where most of Killzone 2 is fought; Project Pyrrhus is a fan project, not official
and not affiliated with or endorsed by Sony Interactive Entertainment or Guerrilla Games.

**You need your own copy of the game.** This repository contains only the port: source code, patches to the
recompiler, tools and documentation. It contains no game code, data, assets, keys or firmware, and it never will.
Killzone 2 is © Sony Interactive Entertainment.
