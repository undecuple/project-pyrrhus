# Changelog

All notable changes for players, newest first, in the style of [Keep a Changelog](https://keepachangelog.com/). The
port is a pre-release (partly playable): see [RELEASE-CRITERIA.md](docs/RELEASE-CRITERIA.md). Versions follow
`vMAJOR.MINOR.PATCH`; every release stays a pre-release until `v1.0.0`.

## [Unreleased]

### Added
- A decrypted disc image (.iso) can be picked instead of a dump folder ("Browse for ISO file" in the setup, or the path in the console). The first run checks the disc inside it, then copies its game files (about 7 GB) into the install folder once; the ISO itself is only read. An encrypted ISO is refused with "this ISO is encrypted; use a decrypted dump".
- The setup reads the disc's title id and shows what it found under the folder ("Found: BCUS98116 (Killzone 2, US disc)"). Another game is refused by its title id and name. The Killzone Trilogy disc, whose Killzone 2 is the same title id, is named and allowed as untested.
- The game window shows the project's icon in its title bar and taskbar.

### Changed
- Picking the PS3_GAME or PS3_GAME/USRDIR folder of the dump, or the USRDIR folder of the update, works: the setup and the first run use the folder above.
- When the first start asks for the decrypted EBOOT, a folder is accepted too: it looks for EBOOT.elf in it and in its USRDIR folder, and says where it looked when it is not there. The setup's EBOOT page does the same.
- The update must carry the same title id as the disc; the setup and the first-run check say so when it does not.

### Fixed
- Installing into a OneDrive folder is refused, as a precaution taken from a problem reported on Project Helghast: OneDrive synced the build's thousands of files while they were written and locked them. The first-run check also stops when the install or build folder is inside OneDrive (O1), or when a game file is only online in OneDrive (O2, before anything is read, so nothing is downloaded); right-click the game folders and choose "Always keep on this device".
- When the first-run console window is closed with its X, the launcher says so ("its window was closed before it finished; finished steps are kept") instead of showing an error code. It names the first-run log only when the log exists.
- Uninstalling removes the whole install folder: the first-run logs and their earlier copies no longer keep it behind.
- "Verify and rebuild" counts only the files it checked.
- The game window's messages (input and window events) are now handled on every frame tick, the same fix as Project Helghast 0.1.4. In our tests a 3.7-second stretch with no messages handled, during a busy catch-up, is gone.
- The game's disk cache is rebuilt once when the installed build changes, so the first start after an update loads a little slower. This is a precaution taken from Project Helghast 0.1.4, where a cache left by an older build ended a level with error 20000; it has not been seen on Killzone 2.
- Files the game opens to create or append to are now opened the way the console does (the toolkit read three of the open flags with the wrong values). In our tests no visible change yet: the opens seen at start are read-only.

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
