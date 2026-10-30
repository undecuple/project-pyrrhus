# Status

The full status of the port. The short version is in the [README](../README.md).

> **Status: early, partly playable.** The game's code is translated, and the Windows program builds and starts. The
> intro movie plays, the menus run with sound, and the first level loads and draws, but
> **at about 23 frames per second** in one 330 s scripted run after a logging fix (the PS3 runs it at 30; earlier
> runs gave 13-17, and a hand-played run is not measured yet). Sound is
> stereo only. A DualShock 4, including motion, was hand-tested on
> 2026-10-22. What works today and what does not: the dated table in the table below.

<p align="center">
  <a href="SCREENSHOTS.md"><img src="screenshots/20261028_kz2-corinth-river-in-play.png" width="720"
       alt="Killzone 2 running in the port: the first level in first person, with the weapon, crosshair and ammo counter"></a><br>
  <sub>The port on 2026-10-28: the first level in play. More, by milestone: <a href="SCREENSHOTS.md">screenshots</a>.</sub>
</p>

As of 2026-10-29, on Windows x64, tested by us under Proton on Linux; the installer and first-run build also ran on Windows 10 in a virtual machine on 2026-10-27 and 2026-10-28 (no play there). Players have reported playing on native Windows 11 (issue #13); those are their reports, not our measurements.

| | |
|---|---|
| Code translation | the game's PowerPC code is translated (about 54,000 functions for the 1.29 update) on ps3recomp v0.18.0 with this project's patches, and the Windows program builds |
| Boot and menus | starts, brings up the game's job system, file system and graphics, shows the front end and menus (played by hand with a pad on 2026-10-22, with the selection highlight, Mission Select pictures and pause menu drawn since that day), and starts the first level (Corinth River). The main menu has an Exit to desktop entry and a Keyboard page that saves key choices to `keybinds.ini`; both were checked in scripted runs only, not by hand |
| First level | loads and runs without a stall; the briefing cutscene plays with its subtitles |
| Picture | the first level is drawn lit and in proportion (since 2026-10-19). Since 2026-10-20 the lighting reads the scene the right way up: a faint mirrored copy of the scene, with a second upside-down head, is gone, and the compared frames matched RPCS3 apart from the sky, which draws green in the first level (cause not yet known; see Known issues). Moving images looked doubled, because the game's motion blur is tuned for 30 frames per second; motion blur is now off by default until the port runs near full speed, with a switch to turn it back on |
| Speed | Two kinds of scripted runs under Proton, both on an RTX 4060 class GPU, against the PS3's 30: one 330 s run of the first level on 2026-10-22 gave 23.3 frames per second with motion blur off, after the session-log buffering fix (13-17 before it); short turn-and-walk windows on 2026-10-29 gave a median of 30.8 frames per second with the older defaults and 32.6 with the native post-processing that is now the default (six pairs; single runs 22-44; the PC was shared with other work). Hand play is not measured. Since 2026-10-20 the translated SPU code is built for SSE4.1 and FMA (about 3x), so the port needs a CPU with AVX and FMA3 (from about 2013); the port checks at startup for AVX and FMA3 and says so if they are missing. Most of each frame was the game's SPU post-processing; its jobs now also spread over all SPU threads. Shaders are still compiled the first time they are needed, which pauses the first minute of a level; a pipeline list kept by each session cut frames over 100 ms in that minute from 18-20 to 2 in scripted runs, and the installer ships a starting list (pso-template.bin) |
| SPU programs | the game's SPU programs and job modules are translated and run, including the post-processing chain |
| Update 1.29 | the build targets the 1.29 update; its added archive and patch files are mapped and read; the effect of the patches on the game data is not checked yet |
| Saves | the game's save format is mapped; the port writes its own saves, including checkpoint saves in the first level; loading a checkpoint back is not checked yet. Saves copied over from RPCS3 are copied unchanged, with no promise that they load |
| Input | pads go through SDL3 (PlayStation and Xbox pads; SDL3.dll ships with the port, XInput is the fallback without it); a DualShock 4 was played by hand on 2026-10-22, including its motion sensor; Xbox and DualSense pads are not yet tried by hand; a pad layout setting (Original by default, Modern selectable) writes the chosen layout into the game's profile, and the game's buttons follow it in play (Modern: crouch on Circle, use on Square, zoom and flashlight on L1); on-screen button prompts can show PlayStation 4/5, Xbox or keyboard symbols (set in keybinds.ini), in menus and in the level; optional, off by default: toggles for crouch and take cover and an aim assist switch (`gameplay.ini`) |
| Audio, video, online | the intro movie plays with pictures and sound through FFmpeg's LGPL decoders, loaded from separate DLLs (the other 27 movies are not yet tried); the movies' 5.1 tracks decode, but all sound is mixed down to stereo for now (no surround output yet); menu and game sound play; online not started |
| Installer and portable zip | the first-run checks, generators and packaging (including SDL3.dll and the movie decoders) exist and are tested without the game; the installer compiles; setup can reuse an existing RPCS3 install (tested with stand-in folders only); on 2026-10-27 and again on 2026-10-28 install, first-run build and uninstall worked in a Windows 10 virtual machine without a GPU, and the game started but exited with a message there (no GPU, no play); pre-releases are published, and players have installed and played them on native Windows (their reports) |

Feature by feature, the PS3 game against the port: [FEATURES.md](FEATURES.md) (generated from the repository's own
records). What is broken or unfinished today: [docs/KNOWN_ISSUES.md](KNOWN_ISSUES.md). Controls, button prompts,
display modes (a new install starts borderless; Alt+Enter switches to a window) and subtitles: [docs/ACCESSIBILITY.md](ACCESSIBILITY.md).
