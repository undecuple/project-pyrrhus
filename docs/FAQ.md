# Install walkthrough and FAQ

A worked example for a common setup, then the questions players ask most. The full reference for each input and
every check is [GETTING-FILES.md](GETTING-FILES.md); where this page is shorter, that page is the reference. If
something does not start or works wrongly, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md), organised by what you see.
No game files, keys or decryption steps are given here or anywhere in this project: you need your own copy.

## Walkthrough: RPCS3 on one drive, the game ISO on another

The example: RPCS3 is unzipped in `D:\RPCS3`, where you have already installed Killzone 2's 1.29 update, and your own
disc dump is a decrypted ISO at `E:\PS3\Killzone 2.iso`. Project Pyrrhus goes on `C:`. Your drives and folders can
differ; only the kind of thing you pick matters.

1. **Check what you have.**
   - The update: `D:\RPCS3\dev_hdd0\game\BCUS98116` (or the folder of your disc's region: BCES00081, BCAS20066,
     BCJS30032), holding `USRDIR\EBOOT.BIN`, `USRDIR\added_data_ps3.psarc` and the `USRDIR\patch_data_ps3` folder.
   - The decrypted EBOOT from that update, made from your own copy (an `EBOOT.elf`). The setup cannot make it for you.
   - The ISO must be decrypted; an encrypted one is refused.
2. **Free space.** The setup copies the game files out of the ISO once (about 7 GB) into the install folder, then
   builds the game there. Pick an install folder on a drive with room for both, formatted NTFS (Windows' usual format),
   and not inside OneDrive.
3. **Run `Project-Pyrrhus-setup.exe`** from the [releases page](https://github.com/undecuple/project-pyrrhus/releases).
4. **"Use my RPCS3 install".** Pick `D:\RPCS3`, the folder with `rpcs3.exe`. If the setup finds it by itself, check it
   is the right one. It fills in the update and the EBOOT from there, and the disc too if RPCS3 has it as a folder.
   It asks before reading anything RPCS3's settings put outside that folder.
5. **The disc.** If the disc page is empty or points to the wrong place, choose "Browse for ISO file" and pick
   `E:\PS3\Killzone 2.iso`, the file itself. Do not pick `E:\` or `E:\PS3`.
6. **Finish.** The first run checks your files, copies them out of the ISO, then translates and builds the game. This
   takes a while, and the setup shows its progress. After that the launcher starts the game.

The ISO is only read; you can move it later. The copy inside the install folder is what the game uses, and
uninstalling removes it, not your ISO or your RPCS3 files.

## FAQ

**The setup says a check failed. Where do I start?**
The message names the input ("Disc dump", "1.29 update" or "EBOOT"), the path and what it expected. The codes and their
fixes are in [GETTING-FILES.md](GETTING-FILES.md#what-the-first-run-check-can-print).

**"The EBOOT changed since the port was built", again after every rebuild.**
The EBOOT file you picked at setup was changed or replaced, for example by decrypting an EBOOT for another game into
the same place. Make the Killzone 2 1.29 EBOOT again, keep it in its own folder, run the setup again over the same
install folder and pick it on the EBOOT page.

**It refuses my EBOOT.**
It must be the decrypted EBOOT of the 1.29 update, not the disc's 1.01 one, and of the same region as the disc.

**I picked a drive and it fails.**
Pick the dump folder (the one holding `PS3_GAME`), the ISO file itself, and the update folder named after the title id,
not the drive or `dev_hdd0`.

**Can I use a disc from one region and an update from another?**
No. The setup refuses the mix and names both regions.

**My dump is on a FAT32 drive and the archive is split into `.66600`, `.66601` files.**
That is accepted as it is.

**Does it run at full speed?**
Not yet. Our scripted runs of the first level under Proton are between about 23 and 33 frames per second; the PS3
holds 30. It has not been measured by hand, and speed varies with what else the computer is doing. See [KNOWN_ISSUES.md](KNOWN_ISSUES.md#frame-rate).

**Can I skip the intro movie?**
Yes: set `KZ2_SKIP_INTRO=1` (in a Command Prompt, `setx KZ2_SKIP_INTRO 1`, then start the game again).

**Where are the logs?**
The setup and first run write `Project-Pyrrhus-firstrun.log` in the install folder; the launcher writes
`logs\launcher.log`, and the game its own log, the newest `kz2-` file in `build\logs`. What to attach to an
[issue](https://github.com/undecuple/project-pyrrhus/issues/new/choose), and how user names are hidden:
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#where-the-logs-are-and-what-to-attach-to-an-issue).

**What does installing an update keep, and what does it rebuild?**
Run the new setup over the same install folder. It offers the folders you picked last time.
- **Kept:**
  - Your saves (the `gamedata` folder in your data folder, `%APPDATA%\Project Pyrrhus`, or in the install folder for the portable zip).
  - The settings files `display.ini`, `keybinds.ini` and `gameplay.ini` in that same folder (an existing `gameplay.ini` is never changed).
  - The Online settings (`repsn.ini`, `community.ini`), in `%APPDATA%\PS3Recomp`, or in `shared` in the install folder when portable.
  - The build folder, so the game's translated code is not thrown away.
  - The game's caches, and the logs.
- **Replaced:** only the port's own program folders (`port`, `ps3recomp`, `toolchain`, `kz2-setup`). They are replaced whole, so a file a newer version dropped cannot linger.
- **Written again:** the options on the setup's options page go back into `kz2-install.ini` each time you run the setup. These are portable or not, pad layout, button prompts, window mode and checking for new versions. Check them on that page. The folder pages are filled in from last time.
- **Rebuilt, if needed:** the launcher compares the build with the install.
  - If only the port changed, it compiles again, which its message calls "usually minutes".
  - If the new version changes the translation of the game's code, or the EBOOT or game folders changed, it translates and compiles again. That takes longer.
  - Steps whose inputs did not change are skipped. The launcher says which applies and asks before it starts.
- **Caches:**
  - The game's shader and pipeline cache (in the `scratch` folder) stays.
  - The saved list of pipelines belongs to the build that made it. When the shader translation changed, it is discarded with a line in the log and rebuilt on the first start (slower, with some stutter).
  - The game's disk cache of disc files (`cache.idx`, `cache.dat`) carries a stamp of the game's `kz2.exe`. A new exe removes it and the game makes a new one, so the first load after an update can be slower.
  - Neither is a save.
- **Uninstalling** is different: it removes the build, the logs and the caches, and asks whether to keep your saves.
  The settings files are not removed, and your game files and RPCS3 folder are never touched.

**Which pads work?**
Pads go through SDL3 (PlayStation and Xbox pads, and others SDL3 recognises; Windows' XInput is the fallback). Only the
DualShock 4 has been played by hand (2026-10-22); Xbox, DualSense and other pads are untested. If a pad is not
detected, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#my-pad-is-not-detected).

**Do I need RPCS3?**
No. It is only a convenient place to find your files. Nothing of RPCS3 runs while you play.
