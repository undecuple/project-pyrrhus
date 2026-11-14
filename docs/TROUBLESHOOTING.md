# Troubleshooting

Find what you see, read the likely cause, try what is listed, and open an issue when the entry says so. Each entry
only lists causes that the setup or launcher detects and names, or that a player's issue has shown. The port is a
pre-release, so something not listed here may still be a bug: say so in an issue. Speed, graphics and other known
problems are in [KNOWN_ISSUES.md](KNOWN_ISSUES.md); questions about the files you need are in [FAQ.md](FAQ.md) and
[GETTING-FILES.md](GETTING-FILES.md).

- [Setup or the first-run build fails](#setup-or-the-first-run-build-fails)
- [Black screen, or nothing happens on Play](#black-screen-or-nothing-happens-on-play)
- [The game stops at the menu or soon after](#the-game-stops-at-the-menu-or-soon-after)
- [My pad is not detected](#my-pad-is-not-detected)
- [Slow or stuttering](#slow-or-stuttering)
- [Where the logs are, and what to attach to an issue](#where-the-logs-are-and-what-to-attach-to-an-issue)

## Setup or the first-run build fails

**What you see:** the setup, the launcher's dialog or the console names an input (`Disc dump`, `1.29 update` or
`EBOOT`), a path and what it expected; or the build stops with a plain message.

**Likely cause:** the setup checks your files before building, and one of them is not what the port needs. The codes
and the plain messages (wrong region, an encrypted ISO, a 1.01 EBOOT, not enough disk space, a OneDrive folder, a
missing part of the update) each have their fix in
[GETTING-FILES.md](GETTING-FILES.md#what-the-first-run-check-can-print). Three that players have met:

- **"The EBOOT changed since the port was built"**, again after every rebuild: the EBOOT file you picked at setup was
  replaced (for example by an EBOOT of another game decrypted into the same place). Make the Killzone 2 1.29 EBOOT again,
  keep it in its own folder, and run the setup again over the same install folder (issue #57).
- **A message about a link to your game files** (error 1392 or 183 in an older version's log, seen when the install
  folder was on a particular hard drive, issues #20 and #22): Windows refused the folder link the launcher used to make.
  Since 0.1.5 the launcher tries the link before the long build, keeps the link and the game's caches under
  `%LOCALAPPDATA%\Project Pyrrhus` when the install drive refuses it, and names the file system of each drive in its
  message. Update to the newest version; installing on an NTFS drive outside OneDrive is the first thing to try.
- **The game starts, then reads the main menu from the disc and crashes:** the update folder lacked
  `USRDIR\added_data_ps3.psarc` or the `USRDIR\patch_data_ps3` folder (issue #16). The setup and the launcher now refuse
  an update folder without them and say which is missing.

**What to do:** read the message first; it says which input and what to pick. Choose the dump folder (the one holding
`PS3_GAME`) or the decrypted ISO file itself, the update folder named after the title id, and the decrypted `EBOOT.elf`
of the same region. A first build takes a while (about 12 to 19 minutes in the runs we have: 12.5 minutes with 16 cores
on a player's PC in issue #31, 18.6 minutes with 2 jobs in our virtual machine); closing its window leaves the finished
steps kept, and the next start offers to go on. The Start menu entry "Verify and rebuild" checks the installed files and
runs the checks again.

**Open an issue when:** the message names a problem you have fixed and it comes back, the message is not one of those
in GETTING-FILES.md, or the build stops with a compiler error (code B1). Attach the first-run log
(see [the logs](#where-the-logs-are-and-what-to-attach-to-an-issue)).

## Black screen, or nothing happens on Play

**What you see:** you press Play and a window never appears, the window stays black, or the game's window closes at
once.

**Likely causes and what to do:**

- **The launcher shows a dialog.** It decides before every start: it offers the first build if there is none, to go on
  with one that did not finish, to pick again a folder or file that is gone (an unplugged drive, a moved folder), and to
  rebuild when the EBOOT, the game folders or the port changed. Answer it, or choose "Verify and rebuild" in the Start
  menu. A rebuild after a new version usually takes minutes (the launcher's own words); see the FAQ on
  [what an update keeps](FAQ.md).
- **"The game stopped unexpectedly (code 0x...)".** The launcher shows this when the game ends with an error code and
  says its log is the newest file in the `build\logs` folder. This is also what a computer with no usable Direct3D 12
  graphics device gave in our Windows 10 virtual machine without a GPU: the game started and stopped when it tried to
  open the device. Update your graphics driver, and check the game's log for the adapter it found.
- **A laptop with two graphics chips.** The game asks Windows for the high-performance GPU first and logs every adapter
  it found and the one it chose (issue #13). If it ran on the integrated chip, set `kz2.exe` (in the install folder's
  `build` folder) to High performance in Windows' graphics settings.
- **A black screen right after the gamma screen** was the intro movie in 0.1.2 installs, built without the movie decoder
  (issue #16). It is fixed from 0.1.4. If a movie is the trouble, Options > Display has a "Skip intro (next start)"
  choice, or set `KZ2_SKIP_INTRO=1`.
- **The CPU lacks AVX or FMA3.** The game checks at start-up and says so; it needs a CPU from about 2013 or later
  ([requirements](requirements.md)).

**Open an issue when:** none of these fits, or you reach a black screen again after updating to the newest version.
Attach the newest game log and `logs\launcher.log`, and say your graphics card and whether the laptop has two.

## The game stops at the menu or soon after

**What you see:** the game closes, or shows an error message box, at the main menu, after choosing New Campaign, or
later in the first level.

**Likely causes and what to do:**

- **The 1.29 update's data did not reach the game** (the crash in issue #16): the launcher checks it before every start
  and names what is missing. Pick a complete update folder again.
- **A stop in the game's job system.** If the log shows "ShadowMap" and "ASSERT", it is the stop described in
  [KNOWN_ISSUES.md](KNOWN_ISSUES.md#stability); please report it with the log.
- **A close after a checkpoint restart (issue #49).** From 0.1.11 the game ends as the PS3 would, writes a line saying so
  to its log and shows a message box; what makes the game decide to stop is not found yet. Say what you were doing just
  before.

**Open an issue when:** it happens twice in the same place, or the log has an error line. Attach the newest game log and
say where in the game it happened and what you did just before.

## My pad is not detected

**What you see:** the pad does nothing in the menus or the level, or only some buttons work.

**Likely cause:** which pads work is partly unknown. Pads go through SDL3 (`SDL3.dll` ships with the port; PlayStation
and Xbox pads, and others SDL recognises, are in the code), and Windows' XInput is the fallback when SDL3 does not load.
Only the DualShock 4 (wired, with its motion sensor) has been played by hand (2026-10-22). Xbox, DualSense and other
pads are untested by us.

**What to do:**

- Connect the pad before you start the game, and try it wired.
- Stop other programs that take over the pad (a vendor's remapping tool, or Steam Input); in issue #36 a Steam
  Controller under Proton reached the game over XInput only, with no motion sensor.
- A pad without a motion sensor (an Xbox pad or a handheld's built-in controller) drives valves and demolition charges
  with the right stick: hold both shoulder buttons the whole time, as the game asks. `motion = off` in `gameplay.ini`
  uses the stick on every pad (see [KNOWN_ISSUES.md](KNOWN_ISSUES.md#controls-and-motion)).
- The keyboard and mouse work without a pad (Keyboard page in the main menu, `keybinds.ini`).

**Open an issue when:** the pad does nothing at all or a button does the wrong thing. Say the pad's model, wired or
wireless, whether Steam is running, and attach the newest game log. A report that a pad works is worth sending too.

## Slow or stuttering

**What you see:** a low or uneven frame rate, sound dropouts that come with slow stretches, or a stutter at first.

**Likely causes and what to do:**

- **It is not at the PS3's 30 frames per second yet.** Our scripted runs of the first level gave about 23 to 33 frames per
  second, heavy scenes are slowest, and the port is limited mostly by the processor today. Players with low-power laptop
  chips have reported about 12 frames per second (issue #49). See
  [KNOWN_ISSUES.md](KNOWN_ISSUES.md#frame-rate).
- **The first start after an update.** The game's saved graphics pipelines belong to the build that made them and are
  rebuilt on the first start after some updates; that start loads more slowly and can stutter briefly.
- **The wrong graphics chip.** On a laptop with two, see the high-performance setting above.
- **Other programs.** Speed varies with what else the computer is doing.

**Open an issue when:** you want to add a data point. Use the performance issue template: CPU, graphics card, the newest
game log from a slow session, and the scene.

## Where the logs are, and what to attach to an issue

All of them are in the install folder (or the unpacked portable folder):

| Log | Where | What it is |
|---|---|---|
| The first-run log | `Project-Pyrrhus-firstrun.log` (earlier runs: time-stamped copies beside it) | the checks and the build's steps; what failed and why |
| The setup log | `Project-Pyrrhus-setup*.log`; the setup's finish page also offers "Open the install log" | what the installer did |
| The launcher log | `logs\launcher.log` | one line per start: what it decided, the version, the build stamp, the Online choice |
| The game log | `build\logs\kz2-<date>-<time>.log` (take the newest) | the game's own log of each session |

**Before you attach one:** the setup, first-run, launcher and game logs hide your Windows user name (paths in your user folder
appear as `%USERPROFILE%`, `%APPDATA%`, `%LOCALAPPDATA%` or `<user>`); open the file and search it for your name
before you post it, and replace anything left with `<user>`. Do not attach game files, decrypted binaries, saves or keys.

**What to put in the issue:** the port version (`logs\launcher.log` has it), what you did and what you expected, your
CPU and graphics card, whether it is a laptop with two graphics chips, and the newest log of the failing try. The
[bug report template](https://github.com/undecuple/project-pyrrhus/issues/new/choose) asks for these.
