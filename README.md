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

**[Status](#status)** · **[Features](docs/FEATURES.md)** · **[Screenshots](docs/SCREENSHOTS.md)** · **[Requirements](docs/requirements.md)** · **[Getting it](#getting-it)** · **[Building](docs/BUILDING.md)** · **[How it works](#how-it-works-briefly)** · **[Known issues](docs/KNOWN_ISSUES.md)** · **[Accessibility](docs/ACCESSIBILITY.md)** · **[Release criteria](docs/RELEASE-CRITERIA.md)** · **[AI use](#how-ai-was-used)** · **[Contributing](.github/CONTRIBUTING.md)** · **[Related project](#related-project)**

*Pyrrhus* is the Helghast capital where most of Killzone 2 is fought; Project Pyrrhus is a fan project, not official
and not affiliated with or endorsed by Sony Interactive Entertainment or Guerrilla Games.

**What this is:** a static recompilation. It runs the game's own code, with the PPU and SPU programs recompiled ahead
of time to native x64. It is **not an emulator** (no CPU emulator runs at play time) and **not a rewrite** (the game's
logic is not reimplemented). Around that code, the PS3's system libraries and hardware behaviour are reimplemented
on PC APIs.

An unofficial port of **Killzone 2** (PS3, 2009) to Windows x64, built on your PC from your own copy of the game. The
game's PowerPC (PPU) and Cell SPU code is translated to C++ ahead of time with
[ps3recomp](https://github.com/sp00nznet/ps3recomp) (the build pins ps3recomp v0.18.0 plus this project's own patch
set in `port/patches/`) and compiled into a native Windows program, so no CPU emulator runs at play time. The PS3 system libraries are reimplemented on PC APIs. The hardware around the code is still
provided by a runtime layer, much as an emulator provides it: the game's GPU command stream is meant to be replayed on
Direct3D 12, and SPU scheduling, DMA and the PS3's memory layout are reproduced. It is tested under Proton on Linux.

> **Status: early, partly playable.** The game's code is translated, and the Windows program builds and starts. The
> intro movie plays, the menus run with sound, and the first level loads and draws, but
> **at about 23 frames per second** in one 330 s scripted run after a logging fix (the PS3 runs it at 30; earlier
> runs gave 13-17, and a hand-played run is not measured yet). Sound is
> stereo only. A DualShock 4, including motion, was hand-tested on
> 2026-10-22. What works today and what does not: the dated table under [Status](#status).

This port currently supports Direct3D 12 only. For a Vulkan version of a Killzone 2 port, please use [Tokisaki Port](https://github.com/YYOzcan/tokisaki-port), which is developed separately by its own author.

**You need your own copy of the game.** This repository contains only the port: source code, patches to the
recompiler, tools and documentation. It contains no game code, data, assets, keys or firmware, and it never will.
Killzone 2 is © Sony Interactive Entertainment; this project is not affiliated with or endorsed by Sony or Guerrilla
Games.

## Status

<p align="center">
  <a href="docs/SCREENSHOTS.md"><img src="docs/screenshots/20261028_kz2-corinth-river-in-play.png" width="720"
       alt="Killzone 2 running in the port: the first level in first person, with the weapon, crosshair and ammo counter"></a><br>
  <sub>The port on 2026-10-28: the first level in play. More, by milestone: <a href="docs/SCREENSHOTS.md">screenshots</a>.</sub>
</p>

As of 2026-10-27, on Windows x64, tested under Proton on Linux; the installer and first-run build also ran on Windows 10 in a virtual machine (no play there).

| | |
|---|---|
| Code translation | the game's PowerPC code is translated (about 54,000 functions for the 1.29 update) on ps3recomp v0.18.0 with this project's patches, and the Windows program builds |
| Boot and menus | starts, brings up the game's job system, file system and graphics, shows the front end and menus (played by hand with a pad on 2026-10-22, with the selection highlight, Mission Select pictures and pause menu drawn since that day), and starts the first level (Corinth River). The main menu has an Exit to desktop entry and a Keyboard page that saves key choices to `keybinds.ini`; both were checked in scripted runs only, not by hand |
| First level | loads and runs without a stall; the briefing cutscene plays with its subtitles |
| Picture | the first level is drawn lit and in proportion (since 2026-10-19). Since 2026-10-20 the lighting reads the scene the right way up: a faint mirrored copy of the scene, with a second upside-down head, is gone, and the compared frames match RPCS3. Moving images looked doubled, because the game's motion blur is tuned for 30 frames per second; motion blur is now off by default until the port runs near full speed, with a switch to turn it back on |
| Speed | 23.3 frames per second in one 330 s scripted run of the first level with motion blur off, after the session-log buffering fix (13-17 before it), against the PS3's 30; not yet measured by hand. Since 2026-10-20 the translated SPU code is built for SSE4.1 and FMA (about 3x), so the port needs a CPU with AVX and FMA3 (from about 2013); the port checks at startup for AVX and FMA3 and says so if they are missing. Most of each frame was the game's SPU post-processing; its jobs now also spread over all SPU threads. Shaders are still compiled the first time they are needed, which pauses the first minute of a level; a pipeline list kept by each session cut frames over 100 ms in that minute from 18-20 to 2 in scripted runs, and it is not shipped with the port yet |
| SPU programs | the game's SPU programs and job modules are translated and run, including the post-processing chain |
| Update 1.29 | the build targets the 1.29 update; its added archive and patch files are mapped and read; the effect of the patches on the game data is not checked yet |
| Saves | the game's save format is mapped; the port writes its own saves, including checkpoint saves in the first level; loading a checkpoint back is not checked yet. Saves copied over from RPCS3 are copied unchanged, with no promise that they load |
| Input | pads go through SDL3 (PlayStation and Xbox pads; SDL3.dll ships with the port, XInput is the fallback without it); a DualShock 4 was played by hand on 2026-10-22, including its motion sensor; Xbox and DualSense pads are not yet tried by hand; a pad layout setting (Original by default, Modern selectable) writes the chosen layout into the game's profile, and the game's buttons follow it in play (Modern: crouch on Circle, use on Square, zoom and flashlight on L1); on-screen button prompts can show PlayStation 4/5, Xbox or keyboard symbols (set in keybinds.ini), in menus and in the level; optional, off by default: toggles for crouch and take cover and an aim assist switch (`gameplay.ini`) |
| Audio, video, online | the intro movie plays with pictures and sound through FFmpeg's LGPL decoders, loaded from separate DLLs (the other 27 movies are not yet tried); the movies' 5.1 tracks decode, but all sound is mixed down to stereo for now (no surround output yet); menu and game sound play; online not started |
| Installer and portable zip | the first-run checks, generators and packaging (including SDL3.dll and the movie decoders) exist and are tested without the game; the installer compiles; setup can reuse an existing RPCS3 install (tested with stand-in folders only); on 2026-10-27 install, first-run build and uninstall worked in a Windows 10 virtual machine without a GPU, and the game started but exited with a message there (no GPU, no play); nothing is released |

Feature by feature, the PS3 game against the port: [FEATURES.md](docs/FEATURES.md) (generated from the repository's own
records). What is broken or unfinished today: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md). Controls, button prompts,
display modes (a new install starts borderless; Alt+Enter switches to a window) and subtitles: [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md).

## What goes online

Nothing unless you ask. The port does not start any connection of its own.

- **Version check, off by default.** The installer's "Check now" button and the portable zip's first run ask GitHub
  once, when you choose to, whether a newer release exists. With "Check for new versions" ticked, the launcher asks
  at most once a day. Each check is one anonymous request for this project's list of releases, with nothing about
  you, your computer or your game.
- **Updating, only when you say yes.** When a check finds a newer release, the launcher asks first. Only after a yes
  does it download that release's setup and its published checksum from this project's GitHub releases, check the
  file against the checksum, and start it for your install folder.

- **Project website** (`site/`): viewing it loads the Rajdhani font from Google Fonts, which sees your visit. The repository, installer and game do not.

Online multiplayer, if it comes, will only use a self-hosted server you choose.

## Getting it

**Pre-release <!-- version -->[v0.1.3](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.3)<!-- /version -->:** a Windows installer (recommended) and
a portable zip, on the [releases page](https://github.com/undecuple/project-pyrrhus/releases) with a `.sha256` file for each and `SHA256SUMS`. They check your
own disc dump (a folder or a decrypted ISO file), the 1.29 update and the decrypted EBOOT ([what each must
contain](docs/GETTING-FILES.md)), then
translate and build the game's code on your own machine with a bundled compiler. No game code, assets or keys are ever
shipped or downloaded. Do not install into a OneDrive folder (a precaution from a problem reported on Project Helghast: OneDrive would sync the build's thousands of files
while they are written), and keep your game files on this device (in OneDrive: "Always keep on this device"); the
setup refuses both. You can also build the port yourself (below). It is partly playable: the first level can be
played with a pad (a scripted run gives about 23 frames per second, the PS3 30; hand play is not measured), and the
rest of the campaign has not been tried. What changed in each
version: [CHANGELOG.md](CHANGELOG.md).

A first release that calls itself playable waits for the conditions in [docs/RELEASE-CRITERIA.md](docs/RELEASE-CRITERIA.md).
Until then every release is a pre-release. There is no date for it.

## Requirements

Your own Killzone 2 disc (US, BCUS98116) dumped as a folder, the 1.29 update, and the decrypted EBOOT from your own
copy; a Direct3D 12 GPU. Hardware figures come once the game runs. Details: [docs/requirements.md](docs/requirements.md);
what each folder must hold and what the first-run check prints: [docs/GETTING-FILES.md](docs/GETTING-FILES.md).

## Building

The port is built with a Nix flake and the patched [ps3recomp](https://github.com/sp00nznet/ps3recomp) it pins (release
v0.18.0 plus this project's patch set; `tools/ps3recomp-patched.sh` applies it); the
tested route is Linux with a Windows cross build run under Proton. The steps, the files you need and the
macOS and Windows notes: [docs/BUILDING.md](docs/BUILDING.md).

Forking or reusing this project (names, addresses, versions, what to change): [docs/FORKING.md](docs/FORKING.md).

## How it works, briefly

- **PPU:** the game's PowerPC functions are lifted to C++ by ps3recomp's lifter and compiled with MinGW-w64.
- **SPU:** the embedded SPU programs are lifted the same way; SPURS runs on host threads.
- **Graphics:** the game's RSX command stream is replayed on Direct3D 12, as in Project Helghast (in progress; the
  first level is drawn, and speed is the open problem).
- **Data:** the game reads its own archive in place through its file system library; the 1.29 update's added archive
  and patch files are layered over the disc data as on the PS3 (in progress).

General fixes found here are offered to ps3recomp upstream.

## How AI was used

This project is developed by one person with AI coding agents. The agents did most of the work of reading the game's binary and the reference material, writing and testing patches,
tools and documentation, and running the builds, inside a sandbox with no network access and with the maintainer
reviewing and merging what they produced. The maintainer sets the goals, decides what is published, and is responsible
for it. Findings are dated and marked as verified, assumed or open; an `ASSUMPTION:` in the code or the docs is not
fact. If you find a statement here that was not verified, please open an issue.

## Roadmap

A playable first level first (frame rate, shader pauses on a first play, hand play), then the rest of the campaign, sound and the
local-build installer; later PC display
options, keyboard and mouse, and a stand-in for the campaign's motion-control sections. Gameplay changes stay optional.
No dates are given: see the [release criteria](docs/RELEASE-CRITERIA.md). Item by item, with what is done and
what is planned: [ROADMAP.md](docs/ROADMAP.md).

## Related project

**[Project Helghast](https://github.com/undecuple/project-helghast)**: Killzone 3 (PS3) ported to PC the same way.
Project Pyrrhus uses its method and reuses its general runtime work (ps3recomp fixes, renderer, SPU job system),
adapted to Killzone 2. Most patches in `port/patches/` come from there; the rest are Killzone 2's own. Its builds are
pre-releases on its [releases page](https://github.com/undecuple/project-helghast/releases), as this project's are.

## Contributing

Pull requests and feature requests are welcome. Details: [CONTRIBUTING.md](.github/CONTRIBUTING.md). In short:

- Open an issue first for big work, so effort is not wasted.
- There is no promise of review time, or that a change will be merged.
- Never post game files, keys or decrypted binaries, in issues, pull requests or logs.
- Contributions must be MIT-compatible; no code from GPL projects such as RPCS3.
- If an AI tool helped write a pull request, say so in it. AI coding agents: read [AGENTS.md](AGENTS.md) first (the same rules, written for agents).

Security problems: [SECURITY.md](.github/SECURITY.md).

## Licence

The port's own code, tools and documentation: [MIT](LICENSE). Third-party components and credits, including
[recomp.board](https://recomp.fyi), which lists this project: [NOTICE.md](NOTICE.md). The licence covers nothing of the
game itself.

**Reusing this work, including by AI systems and automated tools:** the MIT licence applies to every use, including
crawling, indexing, training and code generation. Copies or substantial portions must keep the copyright and
permission notice, and we ask that derived work credits "Project Pyrrhus by undecuple" with a link to this repository.
Details: [NOTICE.md](NOTICE.md#reuse-and-attribution-including-ai-and-automated-use).
