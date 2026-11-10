# Getting your files ready

The setup needs three things from your own copy of Killzone 2: the disc dump, the 1.29 update folder and the decrypted
1.29 EBOOT. This page says what each one must look like and what the setup tells you when something is off. It does
not say how to make the files, and nothing here is shipped or downloaded by this project. If you play the game in the
PS3 emulator RPCS3, the setup can find all three in your RPCS3 install ("Use my RPCS3 install"); for installing the
update and adding the game there, see RPCS3's documentation. With the RPCS3 folder left empty, the setup looks in
`%LOCALAPPDATA%\Programs\rpcs3`, `%APPDATA%\rpcs3`, and for an unzipped RPCS3 in Documents, on the Desktop, in
Downloads (also where Windows has moved those folders), in Games or Emulators in your user folder, in Program Files,
and at the root of each local drive and its Games, Emulators, Emulator or PS3 folder: a folder named `RPCS3` or with
"rpcs3" in its name (such as `rpcs3-v0.0.34-...-win64`), one level deep, and only one that holds `rpcs3.exe` or
RPCS3's settings; anywhere else, pick the folder with `rpcs3.exe` yourself.

## Regions

Four Killzone 2 discs are accepted. Each needs the 1.29 update of its own region, which a PS3 or RPCS3 installs in
`dev_hdd0/game/<the disc's title id>`. The decrypted 1.29 EBOOT is the same file in all four regions.

| Disc | Title id | Disc version | Update folder | Status |
|---|---|---|---|---|
| US | BCUS98116 | 01.01 | `dev_hdd0/game/BCUS98116` | Tested: the port is built and played on it |
| Europe | BCES00081 | 01.01 | `dev_hdd0/game/BCES00081` | Untested |
| Asia | BCAS20066 | 01.02 | `dev_hdd0/game/BCAS20066` | Untested |
| Japan | BCJS30032 | 01.00 | `dev_hdd0/game/BCJS30032` | Untested |

"Untested" means that the port's code is the same, but the disc's data differs and no one has played it through on
the port yet. The European disc's game archive is the same as the US one; the Asian and Japanese archives and their
updates' data are their own. The first-run check says "untested" (a D1 WARN) and goes on.

Do not mix regions. A disc of one region with another region's update folder is refused (U1 names both), because
the update's data is made for its own disc. Use the update that matches your disc. The `PS3_UPDATE` folder on a
disc is a console system update: the setup never reads it.

## The three inputs

| Input | What to pick in the setup | The folder or file must contain | It does not hold | Quick self-check |
|---|---|---|---|---|
| Disc dump | The folder that holds `PS3_GAME`, or a decrypted `.iso` file | `PS3_GAME/PARAM.SFO`, `PS3_GAME/USRDIR/EBOOT.BIN` and the game archive `PS3_GAME/USRDIR/data_ps3.psarc` (D3; about 6.5 GiB), or its parts `data_ps3.psarc.66600`, `.66601`, ... with no gap | The update's files | Open the folder: you see `PS3_GAME`, and inside it `PARAM.SFO` and `USRDIR` |
| 1.29 update | The update folder of your disc's region (on a PS3 or in RPCS3 it is `dev_hdd0/game/<the disc's title id>`, such as `dev_hdd0/game/BCUS98116`; see [Regions](#regions)) | `PARAM.SFO` (U1) and `USRDIR/EBOOT.BIN` (U2). Also the update's own archive `USRDIR/added_data_ps3.psarc` and its folder `USRDIR/patch_data_ps3` (U3: without them the game stops at the main menu, so the check stops there) | The disc archive `data_ps3.psarc`: that one is only on the disc. Do not copy it into the update folder | `PARAM.SFO` sits next to `USRDIR`; its `APP_VER` is 01.29 |
| Decrypted 1.29 EBOOT | The file `EBOOT.elf`, or the folder that holds it. It is made from the 1.29 update's `USRDIR/EBOOT.BIN` (in the update folder, for example `dev_hdd0/game/BCUS98116/USRDIR`; the 1.29 EBOOT is the same file in every region), not from the disc's `PS3_GAME/USRDIR/EBOOT.BIN` | A 64-bit PowerPC ELF file, not the encrypted `EBOOT.BIN` (E1) | The disc's EBOOT, which is version 1.01: the setup's EBOOT page refuses it and names the update's `USRDIR` folder, and the first-run check stops on it (E1) | The file starts with the letters `ELF`; an encrypted file starts with `SCE`. The 1.29 one is 16,455,144 bytes, the disc's 1.01 one 16,381,928 |

**Pick the folder or the file itself, not the drive that holds it.** If drive `E:` holds `Killzone 2.iso`, pick
`E:\Killzone 2.iso`; `E:\` alone is a dump only when `PS3_GAME` sits right on that drive. The update is the
folder named after the disc's title id (such as `BCUS98116`), not the drive or the `dev_hdd0` folder above it. A drive picked by mistake fails D1 to D3 for the
disc, or U1 and U2 for the update, even when the files on it are fine.

When `USRDIR/EBOOT.elf` is already inside the update folder, the setup offers it as the EBOOT. When you give a folder
instead of the file, the setup looks for `EBOOT.elf` in it and in its `USRDIR` folder, and says where it looked when it
finds none. The port cannot decrypt
the EBOOT itself, and this project gives no decryption tools or instructions.

You give these once. The setup writes them into the install folder's `kz2-install.ini`. If you did not tick "Build
now", or a check failed, the first start of the game shows the check in a console window and starts from the folders
you gave in the setup. When the check fails, the setup's message box, the dialog of `Project Pyrrhus.exe` and the portable zip's
console show the reason (the same text as the log). On the next start the check runs first. When only the EBOOT is
wrong (E1), it asks for the EBOOT again and offers the update's `USRDIR/EBOOT.elf` when there is one. Otherwise, when
you choose to change the folders, it asks only for the inputs whose checks failed (the disc for D, I and A codes, the
update for U codes). The reason names the input and the path, so a disc and an update given the wrong way round are
easy to spot: an update folder (with `PARAM.SFO` and `USRDIR/EBOOT.BIN`, or the update's own
`USRDIR/added_data_ps3.psarc` or `USRDIR/patch_data_ps3` and no disc archive) given as the disc is named as the update,
and a folder holding `PS3_GAME` given as the update is named as the disc dump.

## Accepted layouts

- **Folder dump.** `PS3_GAME` with its files, as above. Pick the folder above `PS3_GAME`; a pick of `PS3_GAME` itself
  or of `PS3_GAME/USRDIR` is taken as the folder above it. In the same way, a pick of the update's `USRDIR` folder is
  taken as the update folder.
- **Decrypted ISO.** A disc image (`.iso`) that is already decrypted can be picked instead of a folder ("Browse for
  ISO file" in the setup). The first-run check reads the disc inside it; then its game files (about 7 GB) are copied
  once into the install folder (`game/disc`) and the build uses that copy; the ISO itself is only read. The archive
  check (A1) runs while the files are copied. An encrypted ISO is refused (I1), and so is a file that is not a
  readable ISO (I2). Uninstalling removes the copy, not the ISO.
- **Split archive.** A dump copied to a FAT32 drive holds `data_ps3.psarc.66600`, `.66601`, ... instead of one
  `data_ps3.psarc`, because FAT32 cannot store a file over 4 GiB. The setup accepts the parts as they are. The numbers
  must run on without a gap; a missing part is named. The archive check (A1) reads the parts in order as one file.
- **Region.** See [Regions](#regions): the US disc is tested, the European, Asian and Japanese discs are accepted but
  untested. The setup reads the title id from `PS3_GAME/PARAM.SFO` and shows it under the folder. Any other title id
  is refused, naming the id and the game found; the update must carry the same id as the disc.
- **Killzone Trilogy.** The Trilogy disc holds Killzone 2 itself in its `PS3_GAME` folder (title id BCUS98116, disc
  version 02.00). The setup names it and goes on, but it is untested: the port is built on the stand-alone disc
  (version 01.01). The archive check (A1) says whether its game archive is the same.
- **OneDrive.** Do not install into a OneDrive folder (a precaution from a problem reported on Project Helghast): OneDrive syncs the build's thousands of files while they are
  written and locks them. The setup refuses such a folder, and the first-run check refuses an install or build folder
  inside OneDrive (O1). Game files inside OneDrive are fine when they are on this device; files that are only online
  are refused before anything is read (O2): right-click the folder and choose "Always keep on this device" first.
- **EBOOT version.** The port is built on the 1.29 EBOOT. Your EBOOT is identified by its SHA-256, else by its
  program segments (so a copy that another tool laid out with extra padding is still recognised), else by its size.
  The disc's own 1.01 EBOOT is refused: on the setup's EBOOT page (a silent install with `/EBOOT=` stops with the same
  text) and by the first-run check (E1). The message names the EBOOT this release needs (title id, version, region).

## What the first-run check can print

The first step of the build prints one line per check: `OK`, `WARN` or `FAIL`, then a code. A `FAIL` stops the setup.
A `WARN` lets it go on. The full log is next to the installer (or in the install folder's `logs`).

| Code | Level | What it means | What to do |
|---|---|---|---|
| O1 | FAIL | The install folder or the build folder is inside OneDrive | Install into a folder outside OneDrive (the default is fine) |
| O2 | FAIL | A game file exists only online in OneDrive (nothing was read, so nothing was downloaded) | Right-click the game folders, choose "Always keep on this device", wait for the download, then run the setup again |
| O3 | OK | A note: the dump or update folder is inside OneDrive but its files are on this device | Nothing |
| D0 | OK / FAIL | FAIL: the dump folder was not found. OK: a note that the dump is a decrypted ISO file, or that `PS3_GAME` or `PS3_GAME/USRDIR` was picked and the folder above it is used | Pick the dump folder again |
| I1 | FAIL | "this ISO is encrypted; use a decrypted dump": the ISO's file table or its files cannot be read as plain data | Use a decrypted dump (a folder or a decrypted ISO) |
| I2 | FAIL | The ISO cannot be read: not an ISO image, damaged or cut short | Copy the ISO again |
| D1 | OK / WARN / FAIL | FAIL: `PS3_GAME/PARAM.SFO` is missing or unreadable, or its title id is not one of the four Killzone 2 discs (the id and game found are named). WARN: a European, Asian or Japanese disc (untested), the folder's category is not a disc game (maybe an installed copy), or the disc version is not the region's (02.00 on the US id is the Killzone Trilogy disc, untested) | Pick the folder that holds `PS3_GAME`. For a WARN you can go on |
| D2 | OK / WARN / FAIL | FAIL: `PS3_GAME/USRDIR/EBOOT.BIN` is missing, or is neither a SELF nor an ELF file. WARN: an unusual size (another version?) | Copy or dump the disc again if it is a FAIL |
| D3 | OK / FAIL | The game archive is missing, too small, does not start with `PSAR` (not an archive, or still encrypted), or its parts have a gap (the missing part is named) | Copy or dump the disc again; check that all parts `.66600`, `.66601`, ... are there |
| A1 | OK / WARN / FAIL | The archive is compared with the known archive of the disc's region (it reads the whole archive once; the result is kept, so later starts do not read it again). OK: it matches. WARN: it differs (a damaged or changed copy, or a printing of the disc not seen yet), or it could not be compared. FAIL: it is another region's archive, so the dump mixes two discs | If the game does not start or stops while loading, copy or dump the disc again; for a FAIL, dump one disc again, all of it |
| U0 | WARN / FAIL | No update folder was given (WARN), or it was not found (FAIL) | Pick the update folder |
| U1 | OK / WARN / FAIL | FAIL: the update's `PARAM.SFO` is missing or unreadable, its title id is not the disc's (another region's update: both are named), or it is the disc's own (category DG: the disc's `PS3_GAME` folder was given as the update). WARN: its version is not 01.29 | Pick the 1.29 update folder of the disc's region |
| U2 | OK / FAIL | `USRDIR/EBOOT.BIN` is missing in the update folder | Pick the folder that holds `PARAM.SFO` and `USRDIR` |
| U3 | OK / FAIL | `USRDIR/added_data_ps3.psarc` is missing or does not start with `PSAR`, or the `USRDIR/patch_data_ps3` folder is missing: the update's data would be missing | Use a complete update folder |
| E1 | OK / WARN / FAIL | FAIL: no decrypted `EBOOT.elf` was found; "This EBOOT is an encrypted SELF, not an ELF"; "This file is not a PS3 executable"; or "This EBOOT is Killzone 2 1.01 ..., the disc's own version" (or another known version). Each FAIL names the EBOOT this release needs, such as "Killzone 2 1.29 (BCUS98116, US)". WARN: an unknown size | Pick the decrypted EBOOT of the 1.29 update, from the update's `USRDIR` folder |
| H1 | OK / WARN / FAIL | The EBOOT is compared with the known Killzone 2 EBOOTs, by SHA-256, else by its program segments. OK: the US 1.29 EBOOT (tested). WARN: the 1.29 EBOOT of an untested region; "Wrong region" (a known EBOOT of another region than the disc's); "Your EBOOT is the 1.29 size but its contents differ from a clean copy. It may be patched or damaged." (unknown or modified); an EBOOT that matches no known build; or the comparison could not be made. FAIL: "a build this port does not run", or a known EBOOT whose status this check does not know | For "contents differ": make it again from your own 1.29 update's `EBOOT.BIN`, without patches, and pick the new file. For a FAIL: pick the 1.29 EBOOT |

When a check fails, the setup's message box, the dialog of `Project Pyrrhus.exe` and the console show one line per
input that failed, labelled `Disc dump`, `1.29 update` or `EBOOT`: the path it looked at, what is there, and what that
folder or file must hold, followed by the failed checks' own messages when the input is the right kind of thing. They
also say when the folder looks like the other input (the update given as the disc, or the disc dump or its
`PS3_GAME` folder given as the update), and which folders look like the disc dump or the update one level below the
folder you picked (two levels below a drive root such as `E:\`). A last line says which inputs passed, for example
"Passed: the 1.29 update and the decrypted EBOOT." The log keeps the coded lines above.

The build can also stop later with a plain message (no code):

| Message | What it means | What to do |
|---|---|---|
| "the decrypted EBOOT is the 1.01 one, this release is built for the 1.29 EBOOT" | The EBOOT is from the disc or another version | Pick the 1.29 update's decrypted `EBOOT.elf` |
| "... file(s) of the port are dated in the future ..." | The install's files carry a time later than this PC's clock, so the compiler would never settle. Seen with installers that kept the build machine's time zone | Check the PC's date, time and time zone; then install again with the current installer |
| "Not enough free disk space to copy the game files out of the ISO ..." | The ISO's files do not fit on the install folder's drive (the message says how much is needed) | Free some space, or install on a drive with more room |
| "the ISO is truncated ..." or "cannot read the ISO ..." | The ISO is cut short or damaged | Copy the ISO again |
| "the 1.29 PPU override table ... is missing from this install" | A file of the install is missing | Install again over the same folder |
| B1 (after compiling) | `kz2.exe` or `at3_standalone.dll` was not built | Run the setup again; the log shows the compiler error |

## More

- [Building the port](BUILDING.md) lists what the whole build needs.
- The [README](requirements.md) has the requirements in short.
