# Changelog

All notable changes for players, newest first, in the style of [Keep a Changelog](https://keepachangelog.com/). The
port is a pre-release (partly playable): see [RELEASE-CRITERIA.md](docs/RELEASE-CRITERIA.md). Versions follow
`vMAJOR.MINOR.PATCH`; every release stays a pre-release until `v1.0.0`.

## [Unreleased]

### Fixed
- The game should now start when the install folder is on a drive where Windows refuses the folder link the launcher makes to your game files (the game reads them through that link and never writes into them). The launcher then makes the link, and keeps the game's caches, in `%LOCALAPPDATA%\Project Pyrrhus\vfs` on the Windows drive instead, and stays with that folder. A failed link no longer leaves an empty `vfs\PS3_GAME` folder behind that made every later start refuse with "is a real folder"; such a folder left by an earlier version is removed (a folder with anything in it is never touched). The launcher tries the link before the first-run build, so a problem shows within seconds instead of after the build; when no link is possible anywhere, the message says folder links need a file system that supports them, such as NTFS, and for Windows' "corrupted and unreadable" answer it names both possible causes (a drive that does not support folder links, or a damaged file system). The first-run log and that message name the file system of each drive involved. Reading the game folder directly without a link is not offered, because the game would then write its caches into your game files. Tested with host tests only; not yet confirmed on Windows. Fixes #20 (also reported on Reddit).
- A rare crash in the main menu (about one start in twenty in our scripted runs under Proton): the SPU scheduler threads no longer use a Wine/Proton wait primitive that can corrupt its own wait list under load. No crash in 9 scripted runs since; not yet confirmed on native Windows.
- SPU interrupts that arrive back to back now resume the interrupted job with its own registers.

### Added
- Estimated hardware requirements to play and to build (README and `docs/requirements.md`): estimates, provisional until the game runs at full speed; hand play is not measured.

## [0.1.4] - 2026-10-29 (pre-release)

### Fixed
- The release build now carries FFmpeg's headers into the installer and the portable zip, which the first run needs since 0.1.3; 0.1.3's own release build stopped there, so 0.1.3 was tagged but not released, and this version holds everything listed under it.

## [0.1.3] - 2026-10-29 (tagged, not released)

### Added
- Three optional gameplay settings, all off or original by default, kept in a new `gameplay.ini` next to `keybinds.ini` (or `KZ2_AIM_ASSIST`, `KZ2_CROUCH_TOGGLE`, `KZ2_COVER_TOGGLE` for one run): `crouch_toggle = 1` makes crouch a toggle (tap to crouch, tap to stand; the game has this option itself but only turns it on online), `cover_toggle = 1` makes take-cover a toggle (tap to take cover, tap again, sprint or jump to leave), and `aim_assist = off` switches the game's aim assist off (`auto`, the default, leaves it on for a pad and the keyboard). Hold to crouch and hold to take cover stay the default. Checked in scripted runs on the first level only.

### Changed
- A new install starts in a borderless window: the installer, the first-run prompt, the launcher and the game itself all default to it when no display setting exists yet; Alt+Enter switches to a window and back. An existing `display.ini` keeps its mode, and exclusive fullscreen stays opt-in.
- The game's whole post-processing chain (depth of field, upsampling, blur, bloom, film grain, Modulate, BloomIntegrate, ILR, Vignette, DepthToFuzzy, Downsample, Zero and the shared blend steps) now runs as native PC code by default, with bit-for-bit the same result as the SPU code on every input recorded in play. In our scripted runs on the first level its SPU time halved (31-42 to 16-19 milliseconds per frame), the median time from a button press to the frame being handed to Windows fell by about 12 ms, and the frame rate was ahead in 4 of 6 pairs (median 30.8 to 32.6 fps; the PC was shared with other work, so single pairs vary). Hand play is not measured. `KZ2_NATIVE_JOB_POST=0` goes back to the SPU code; `KZ2_NATIVE_JOB_<NAME>=0` does it for one job. A few copies of shared steps that never ran in our recordings stay on the SPU code.
- Depth of field now runs as native PC code by default, with bit-for-bit the same result (`KZ2_NATIVE_JOB_DOF=0` goes back to the SPU code). In four of four scripted pairs on the first level the native version was faster (median 18 to 32 fps on that route). Hand play is not measured.
- The game's data decompression (a zlib job that ran on the emulated SPU) now runs directly on the PC by default, with zlib 1.3.2 linked into the game (`KZ2_NATIVE_ZLIB=0` goes back to the SPU job). The decompressed data is byte for byte the same, checked on two levels. In our scripted runs Corinth Sands started about 10 seconds sooner (70 to 60 seconds in three pairs), and frame times in play were unchanged. Hand play is not measured.
- A frame waiting on a graphics job from the game's SPU code is resumed as soon as the job writes its result, instead of after a fixed 4 ms sleep. In two scripted pairs under Proton the wait between the game's frame request and the renderer's drain fell by 4 to 5 ms (median), and the whole time from a button press to the frame being handed to Windows fell by 2 ms in one pair and 12 ms in the other, to about 60 ms; the screen's own delay comes on top and was not measured. Hand play is not measured.
- The release notes on GitHub list each change as its own bullet, with the fixes in a list of their own, instead of one long paragraph.
- "Use my RPCS3 install" also finds a portable RPCS3 (the official Windows download is a zip) in a folder named `RPCS3` in Documents, on the Desktop, in Downloads or at the root of a local drive, such as `C:\RPCS3`. Only those folders are looked at, and only one with `rpcs3.exe`, `vfs.yml` or `games.yml` is offered. Picking the folder by hand works as before (#9).

### Fixed
- Moving or renaming the unpacked portable folder after (or during) the first run no longer breaks it: CMake's build files kept the old folder's paths, so the build stopped with "CMakeCache.txt directory ... is different" or wrote into a folder with the old name. The first run and the launcher now notice the move, follow saved paths that were inside the folder (an extracted ISO), start the compiler's configure in an empty build folder and keep the lifted code, so only the compile runs again, and only when the game is updated or the build was not finished. A finished game keeps starting as it is. Checked with tests that move a temporary install between runs, not yet with a real portable install on Windows.
- The intro movie and the cutscenes were black and silent in every v0.1.2 install: the first run built the game without its movie decoder, because the release did not ship FFmpeg's headers and the build did not ask for them, so the game never loaded the FFmpeg DLLs installed beside it. The release now ships the headers (`ffmpeg/include`, from the same LGPL FFmpeg build as the DLLs), the first run passes them to the build, the build stops if they are missing, and the first run's last check fails if the game was built without movie decoding. Installing this version over v0.1.2 rebuilds the game once. Reported by @kolomeets80 (#16).
- The game stopped at the main menu, right after the intro, when the 1.29 update's data did not reach it: the 1.29 game then reads the disc's menus, which do not match it. The first-run check now fails (it only warned) when the update folder lacks `USRDIR\added_data_ps3.psarc` or the `USRDIR\patch_data_ps3` folder, the setup's update page asks for both, and the launcher checks the update folder before every start and says what is missing instead of starting a game that stops. Reported by @kolomeets80 (#16).
- The game's log no longer shows the Windows user name: paths under `%APPDATA%`, `%LOCALAPPDATA%` and the user's own folder are written as `%APPDATA%\...`, `%LOCALAPPDATA%\...` and `%USERPROFILE%\...` in every line of the log (for example `display.ini` and `keybinds.ini`), and in the launcher's `launcher.log`. Reported by @kolomeets80 (#16).
- The setup and the first run refuse an install or build folder whose path contains `[`, `]` or `;`, with a message, instead of failing later in the build: the bundled CMake cannot work from such a folder. The same failure was reported on Project Helghast (#20).
- On a laptop with two graphics chips (for example an Intel iGPU and an NVIDIA or AMD GPU) the game could draw on the weaker chip. It now picks the high-performance adapter first, falls back to the default adapter and then to the software renderer, and writes every adapter it found and which one it chose to the log. Not yet confirmed on a hybrid laptop. Reported by @feanor-noldorin (#13).
- Switching to exclusive fullscreen no longer leaves the picture frozen if the next present fails: the swap chain is resized after every switch, a failed present is recovered from (the game leaves fullscreen and keeps drawing in a borderless window; only a lost graphics device, or eight failures in a row, stops the picture). Only tried under Proton, not yet on real Windows.
- The first-run log no longer keeps the Windows user name when a path is written in its escaped form, with doubled backslashes (an error message, or a list or JSON of paths). Reported by @feanor-noldorin (#9).
- `bump_version.py` keeps each file's line endings instead of writing Windows line endings when run on Windows. Reported by @feanor-noldorin (#9).
- `tools/ps3recomp-patched.sh` stops before copying anything when git has checked the ps3recomp submodule out with Windows line endings (`core.autocrlf`, on by default in Git for Windows), and names the commands that fix it. Before, the patch series failed part-way through with a "patch does not apply" error. BUILDING.md has a note on cloning on Windows (#9).
- `tools/ps3recomp-patched.sh` finds a working Python 3 itself: `python3`, else `python`, else the Windows launcher `py -3`. On Windows, `python3` is often the Microsoft Store alias, and the script used to stop with exit code 49 after applying every patch. With no working Python, it now stops before copying anything and says what it tried (#9).

## [0.1.2] - 2026-10-28 (pre-release)

### Added
- A decrypted disc image (.iso) can be picked instead of a dump folder ("Browse for ISO file" in the setup, or the path in the console). The first run checks the disc inside it, then copies its game files (about 7 GB) into the install folder once; the ISO itself is only read. An encrypted ISO is refused with "this ISO is encrypted; use a decrypted dump".
- The setup reads the disc's title id and shows what it found under the folder ("Found: BCUS98116 (Killzone 2, US disc)"). Another game is refused by its title id and name. The Killzone Trilogy disc, whose Killzone 2 is the same title id, is named and allowed as untested.
- The game window shows the project's icon in its title bar and taskbar.

### Changed
- Picking the PS3_GAME or PS3_GAME/USRDIR folder of the dump, or the USRDIR folder of the update, works: the setup and the first run use the folder above.
- When the first start asks for the decrypted EBOOT, a folder is accepted too: it looks for EBOOT.elf in it and in its USRDIR folder, and says where it looked when it is not there. The setup's EBOOT page does the same.
- The update must carry the same title id as the disc; the setup and the first-run check say so when it does not.

### Fixed
- The folder hints of the setup and the first-run check offer only Killzone 2 dumps (other games' dumps on a drive are not named) and name up to three `.iso` files in the folder (or one level down on a drive) beside the folder hints. When no more input comes (a closed console), the first-run check stops with its FAIL lines instead of asking again. The same fixes as Project Helghast PR #17.
- Installing into a OneDrive folder is refused, as a precaution taken from a problem reported on Project Helghast: OneDrive synced the build's thousands of files while they were written and locked them. The first-run check also stops when the install or build folder is inside OneDrive (O1), or when a game file is only online in OneDrive (O2, before anything is read, so nothing is downloaded); right-click the game folders and choose "Always keep on this device".
- When the first-run console window is closed with its X, the launcher says so ("its window was closed before it finished; finished steps are kept") instead of showing an error code. It names the first-run log only when the log exists.
- When the setup or the first run stops, the setup's message box, the launcher's dialog and the portable zip's console say why (the same reason the log has). The next start checks your files first and asks again only for the one that was wrong. The setup's EBOOT page refuses the disc's 1.01 EBOOT and names the update's USRDIR folder, where the 1.29 one is; a silent install with /EBOOT= stops with the same text. Adapted from Project Helghast's fix for the same mix-up (its PR #11).
- When a check of your game files fails, the setup's message box, the launcher's dialog and the console say which input failed ("Disc dump", "1.29 update" or "EBOOT"), the path, what is there and what it must hold, and which inputs passed. A disc dump and an update given the wrong way round are named as such, a drive picked instead of a folder gets a pointer to the folders on it that look like the disc or the update, and the disc's PS3_GAME folder given as the update fails its check. Adapted from Project Helghast's fix for the same mix-ups (its PR #14).
- The setup's disc page says what a folder without PS3_GAME holds and where PS3_GAME is when it is one folder down; the update page names the path and the missing files, or says the folder is a disc dump.
- With a decrypted ISO as the disc, the first-run check could not load its ISO reader under the bundled Python, which does not look in the check's own folder; it now does.
- [Getting your files ready](docs/GETTING-FILES.md) lists what each input must contain, says that the update does not hold the disc archive, and warns against picking a drive instead of the dump folder or the .iso file.
- Uninstalling removes the whole install folder: the first-run logs and their earlier copies no longer keep it behind.
- "Verify and rebuild" counts only the files it checked.
- The game window's messages (input and window events) are now handled on every frame tick, the same fix as Project Helghast 0.1.4. In our tests a 3.7-second stretch with no messages handled, during a busy catch-up, is gone.
- The game's disk cache is rebuilt once when the installed build changes, so the first start after an update loads a little slower. This is a precaution taken from Project Helghast 0.1.4, where a cache left by an older build ended a level with error 20000; it has not been seen on Killzone 2.
- Files the game opens to create or append to are now opened the way the console does (the toolkit read three of the open flags with the wrong values). In our tests no visible change yet: the opens seen at start are read-only.
- The game window keeps responding while the game builds its graphics pipelines on the first start of a level, which can take several seconds with an empty shader cache: the window now has its own thread, so Windows no longer marks it as not responding. In our tests the longest stretch without an answer went from 7.9 s to 0.05 s; the first start of a level is still slower than later ones.

## [0.1.1] - 2026-10-28 (pre-release)

### Added
- A disc dump copied to a FAT32 drive, where the game archive is split into parts (data_ps3.psarc.66600, .66601, and so on), is accepted as it is by the setup, the first-run check and the game. A missing part is named.
- The first run checks the disc's game archive against the known copy (check A1) and says when it differs.
- The launcher log starts each run with a version line, so a shared log says which version made it.
- A new page, docs/GETTING-FILES.md, shows what the disc dump, the 1.29 update and the EBOOT must contain and what every first-run check means.

### Changed
- The game folders are given once: when the build is started later or a check fails, the first start checks the folders from the setup instead of asking for them again.
- When an upgrade changes the tables the game's code is translated with, the first start translates and builds the game again instead of reusing the old build.
- The help for using an RPCS3 install points to RPCS3's own documentation.

### Fixed
- Installed files carry the right time on PCs in time zones west of UTC (the Americas), so the first build does not loop on files dated in the future ("build.ninja still dirty after 100 tries"). The first run stops with a plain message if it finds such files.

## [0.1.0] - 2026-10-28 (tagged, not released)

The tag v0.1.0 marks the first build of the Windows installer and portable zip. It was never published as a release:
the fixes listed above came first, and the first published release is the next version.
