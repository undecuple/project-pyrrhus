# Installing

This page takes you from the download to a running game. Each step says what you should see afterwards. If a step fails, go to [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

**Latest release <!-- version -->[v0.1.13](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.13)<!-- /version -->.** It is partly playable. The first level can be played with a pad. A scripted run gives about 23 frames per second, and the PS3 gives 30. Hand play is not measured. The rest of the campaign has not been tried. What changed in each version: [CHANGELOG.md](../CHANGELOG.md).

## What you need

| You need | Details |
|---|---|
| A Killzone 2 disc dump | A folder or a decrypted `.iso`, from your own disc. US (BCUS98116) is tested. The European, Asian and Japanese discs are accepted but untested. |
| The 1.29 update | The update of the same region, from your copy. |
| The decrypted EBOOT | `EBOOT.elf`, made from your copy's 1.29 update. |
| A PC | Windows 10 or 11 (64-bit), a Direct3D 12 graphics card, and a CPU with AVX and FMA3. The hardware figures are estimates, provisional until the game runs at full speed. |
| An install folder | On this device, not inside OneDrive; empty or new, or an earlier Project Pyrrhus install. |

What each file must contain and what the first-run check prints: [GETTING-FILES.md](GETTING-FILES.md). Hardware: [requirements.md](requirements.md). No game files, keys or decryption steps are given by this project.

## Steps

1. **Download the installer.** Get `Project-Pyrrhus-setup.exe` (recommended) or the portable zip (`Project-Pyrrhus-<version>-Windows-x64.zip`) from the [releases page](https://github.com/undecuple/project-pyrrhus/releases). Each file has a `.sha256` file, and `SHA256SUMS` lists them all. You should see the file in your Downloads folder.
2. **Run the setup.** For the portable zip, unzip it and run `run.cmd` instead. You should see the setup or its console.
3. **Choose an install folder.** Pick an empty or new folder outside OneDrive, or the folder of an earlier Project Pyrrhus install to update it. The setup refuses a folder that already holds other files, so that installing, updating or uninstalling never deletes files it did not put there. The setup refuses a OneDrive folder, because OneDrive would sync the build's thousands of files while they are written (a problem reported on Project Helghast). You should see the folder on the page.
4. **Point it at your files.** Pick the disc dump, the 1.29 update and the decrypted EBOOT. If you play in RPCS3, "Use my RPCS3 install" fills them in. Keep your game files on this device (in OneDrive: "Always keep on this device"), or the setup refuses them. You should see a check mark or a named problem for each input.
5. **Let it build.** The setup checks your files, then translates and builds the game's code on your machine with a bundled compiler. This takes a while. You should see its progress. No game code, assets or keys are shipped or downloaded.
6. **Start the game.** Use the launcher. You should see the intro movie, then the menus.

A worked example with RPCS3 on one drive and the ISO on another, and common questions: [FAQ.md](FAQ.md). You can also build the port yourself: [BUILDING.md](BUILDING.md).

## After installing

- **Settings.** The first start creates `gameplay.ini` (aim assist, crouch and cover toggle, motion, mouse) with its defaults next to `keybinds.ini`. The folder is `%APPDATA%\Project Pyrrhus`, or, in the portable zip, the folder with `kz2.exe`. An existing file is never changed.
- **Pads.** If a pad is not seen, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Only the DualShock 4 has been hand-tested. Other pads are untested.
- **Releases.** A first release that calls itself playable waits for the conditions in [RELEASE-CRITERIA.md](RELEASE-CRITERIA.md). Until then every release is an early, experimental preview (GitHub pre-releases up to 0.1.13, full GitHub releases from 0.1.14). There is no date for it.
