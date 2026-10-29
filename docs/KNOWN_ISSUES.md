# Known issues

What is wrong or unfinished today, stated plainly. It is checked against [FEATURES.md](FEATURES.md) and the README's
[status table](../README.md#status); where those change, this page changes with them. Last checked 2026-10-27.
Everything below was observed on Windows x64 builds run under Proton on Linux. On real Windows only the installer and
the first-run build have been tried (in a virtual machine without a GPU); the game has not been played there.

If you hit something that is not listed, please open an issue with the bug report template (it asks for your system
and the newest log file).

## Partly playable

- **Only the first level has been played.** Corinth River loads, draws and can be played with a pad, but the campaign
  has not been played from start to finish, and the other missions have not been tried. Checkpoint saves are written
  in the first level; loading a checkpoint back is not checked yet, nor is loading a save copied over from RPCS3 (those
  are copied unchanged, with no promise that they load).
- **Pre-release, playing on Windows untested.** The installer and portable zip are published as pre-releases on the
  [releases page](https://github.com/undecuple/project-pyrrhus/releases). On 2026-10-28 the installer ran in a Windows
  virtual machine with no GPU: the silent install, the check of every installed file, the game-file checks (including
  a OneDrive folder, wrong and swapped inputs, a drive root, a disc ISO and the disc's own EBOOT), the first-run build
  (18.6 minutes with 2 jobs), start-up and uninstall all worked. The game started there and stopped when it tried to
  open its graphics device, because that machine has no GPU. Playing on Windows is still untested. See
  [RELEASE-CRITERIA.md](RELEASE-CRITERIA.md).
- **Not yet in the port:** the settings and controls menus, a keyboard-and-mouse scheme, skirmish with bots, online play,
  trophies, a 60 frames-per-second option, and the 5.1/7.1 output below. The main menu now has an "Exit to desktop"
  entry and a Keyboard page that saves key choices to `keybinds.ini`; both were checked in scripted runs only.

## Frame rate

- **Not yet at 30.** One 330 s scripted run of the first level measured 23.3 frames per second after a logging
  fix (earlier runs gave 13-17); the PS3 runs it at 30. It has not been measured by hand. Speed varies with what else
  the computer is doing. The
  translated SPU code is built for AVX and FMA3, so the port needs a CPU from about 2013 or later; it checks at start-up
  and says so if they are missing.
- **Heavy scenes are slowest:** large firefights and the post-processing stages (the game runs these on its SPUs) cost
  the most. Work on speed is ongoing; it is the main thing standing between the port and a playable first level.
- **Stutter in the first minute of each area.** Shaders are compiled the first time they are needed, and the game
  waits for them: hand-play recordings show pauses of 0.2 to 0.9 s, and some black frames, until most shaders are
  built. A later visit to the same area is smoother. A fix builds the known shaders during the load from a list kept
  by each session: in two pairs of scripted runs with an empty cache, pauses over 0.1 s in the first minute of the
  level fell from 18-20 to 2. The installer and the portable zip ship this list
  (`pso-template.bin`); its effect has not been measured in an installed copy yet. A build from source needs the file
  next to `kz2.exe` or one folder up.
- **Motion blur is off by default.** The game's blur is tuned for 30 frames per second and looks doubled at lower
  rates; there is a switch to turn it back on.

## Audio

- **Stereo only.** The PS3 outputs 5.1 or 7.1; the port decodes the movies' 5.1 tracks and the game's multichannel
  output, then mixes everything down to stereo. There is no surround output yet.
- **Movies:** the intro movie plays with picture and sound; it is the only one of the game's 28 movies tried so far. In
  an early test its sound crackled; a fix is in and a later test heard no crackle, but it has not been checked on other
  machines.
- **Dropouts** can be heard while a cutscene stalls on shader compiles (see Frame rate).
- **Sound quality** and every sound bank have not been checked; menu and in-game sound and music play.

## Picture

- **Pause screen:** the pause screen was entirely white in an early hand test. A fix (patch 2097) is in the build and
  was checked in screenshots under Proton; it has not yet been confirmed by hand on a desktop compositor. If your pause
  screen is white, please report it with your compositor and GPU.
- **Mouse cursor:** the cursor used to stay visible over the game. Patch 2098 hides it while the window has focus; this
  was checked on a virtual display only, not on a Wayland compositor. If it is still visible in game, please report it.
- **Compared with RPCS3:** the first level matches RPCS3's frames in the checks made so far, but only one level has
  been compared. Other levels may show missing or wrong effects.
- **Seen in hand-play recordings (2026-10-22):** with PlayStation 4 or 5 symbols, the START and SELECT labels (OPTIONS, TOUCHPAD,
  CREATE) were drawn as white boxes; fixed since (the wrong font face was picked), checked in scripted runs; "LOADING..." can be drawn twice, one line over the other
  (seen after Mission Select or Continue, not yet reproduced); the load into the first level shows a black, frozen
  picture with the last subtitle still up for several seconds. That freeze is the shader wait above: with the shader
  list it fell from about 10 s to 2-3 s in scripted runs.
- Other languages than the default are not tried; menu pages and subtitles were checked in one language.

## Display

- **Borderless is the default window mode** for a new install (no `display.ini`); Alt+Enter switches to a window and
  back. An existing `display.ini` keeps its mode.
- **Exclusive fullscreen is opt-in** (`mode = fullscreen` in `display.ini`, or the Display entry). On Windows it was
  reported to freeze the picture after the switch on a flip-model swap chain; the port now resizes the swap chain after
  every switch and keeps drawing (borderless) if a present fails, but this is only tried under Proton, not on real
  Windows.
- **Laptops with two graphics chips:** the game now asks Windows for the high-performance GPU first and logs every
  adapter it found and the one it chose (#13). This is not yet confirmed on a hybrid laptop; if the game still runs on
  the integrated chip, set `kz2.exe` to High performance in Windows' graphics settings and tell us in #13.

## Stability

- **A stop in the SPU job system.** A `Gfx.PB.ShadowMap` assert stops a level load. It was seen once in a run with
  verbose logging on a heavily loaded machine, and in every test run with the per-event log lines switched off. The
  cause was a timing race in how SPU task ids were handed over; after the fix (patch 7004) the quiet-log runs loaded
  in 4 of 4 tries and 10 of 10 level starts. That does not yet prove it gone. If your log shows "ShadowMap" and "ASSERT", please attach it to an
  issue.
- Verbose logging is now off by default; a 300 s run writes about 0.4 MB of log. With it off, four level loads in a
  row completed with no stop.

## Controls and motion

- **Pads:** a DualShock 4 (wired, through SDL3), including its motion sensor, was played by hand. Xbox and DualSense
  pads work in code but have not been tried by hand. Prompts can show PlayStation, Xbox or keyboard symbols; a pad
  layout setting (Original or Modern) is available.
- **Crouch and cover toggles, aim assist switch:** options in `gameplay.ini` (see ACCESSIBILITY.md), off or original by
  default. They were checked in scripted runs on the first level only (the crouch and cover toggles worked there; the
  aim assist's effect on the aim was not seen, because no enemy was in view); there is no in-game page for them, and
  the aim assist cannot yet follow a mouse (no mouse look).
- **Motion sections:** the real motion sensor reaches the game (the loading screen tilts). The campaign's valve and
  charge sections have not been done by hand yet. As a stand-in, holding L1 and R1 and moving the right stick turns the
  valve; that it completes the valve is not proven.
- **Keyboard and mouse:** there is no keyboard-and-mouse play yet.

## Game data and version

- **US disc only:** the port targets the US disc (BCUS98116) with update 1.29. Other regions are untested.
- **Update 1.29:** its added archives and patch files are read; the effect of the patches on the game's data is not
  fully checked yet.
- **You need a decrypted main program made from your own copy**, see [requirements.md](requirements.md). This project
  provides no tools or instructions for making it.

## Building

- The build is heavy: each lifted source chunk can need over 1 GB of memory to compile, the build takes roughly 18
  minutes with four jobs, and `kz2.exe` is about 1 GB. 16 GB of RAM or more is advised.
- macOS and native Windows builds are untested ([BUILDING.md](BUILDING.md)).
