# Getting your files ready

The setup needs three things from your own copy of Killzone 2: the disc dump, the 1.29 update folder and the decrypted
1.29 EBOOT. This page says what each one must look like and what the setup tells you when something is off. It does
not say how to make the files, and nothing here is shipped or downloaded by this project. If you play the game in the
PS3 emulator RPCS3, the setup can find all three in your RPCS3 install ("Use my RPCS3 install"); for installing the
update and adding the game there, see RPCS3's documentation.

## The three inputs

| Input | What to pick in the setup | The folder or file must contain | Quick self-check |
|---|---|---|---|
| Disc dump | The folder that holds `PS3_GAME`, or a decrypted `.iso` file | `PS3_GAME/PARAM.SFO`, `PS3_GAME/USRDIR/EBOOT.BIN` and the game archive `PS3_GAME/USRDIR/data_ps3.psarc` (about 6.5 GiB), or its parts `data_ps3.psarc.66600`, `.66601`, ... with no gap | Open the folder: you see `PS3_GAME`, and inside it `PARAM.SFO` and `USRDIR` |
| 1.29 update | The update folder (on a PS3 or in RPCS3 it is `dev_hdd0/game/BCUS98116`) | `PARAM.SFO`, `USRDIR/EBOOT.BIN`, `USRDIR/added_data_ps3.psarc` and the folder `USRDIR/patch_data_ps3` | `PARAM.SFO` sits next to `USRDIR`; its `APP_VER` is 01.29 |
| Decrypted 1.29 EBOOT | The file `EBOOT.elf`, or the folder that holds it | A 64-bit PowerPC ELF file, not the encrypted `EBOOT.BIN` | The file starts with the letters `ELF`; an encrypted file starts with `SCE`. The 1.29 one is 16,455,144 bytes |

When `USRDIR/EBOOT.elf` is already inside the update folder, the setup offers it as the EBOOT. When you give a folder
instead of the file, the setup looks for `EBOOT.elf` in it and in its `USRDIR` folder, and says where it looked when it
finds none. The port cannot decrypt
the EBOOT itself, and this project gives no decryption tools or instructions.

You give these once. The setup writes them into the install folder's `kz2-install.ini`. If you did not tick "Build
now", or a check failed, the first start of the game shows the check in a console window and starts from the folders
you gave in the setup; it asks for folders again only when you choose to change them.

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
- **Region.** The US disc (BCUS98116) is the one the port is built and tested on. The setup reads the title id from
  `PS3_GAME/PARAM.SFO` and shows it under the folder. Any other title id is refused, naming the id and the game found;
  the update must carry the same id as the disc.
- **Killzone Trilogy.** The Trilogy disc holds Killzone 2 itself in its `PS3_GAME` folder (title id BCUS98116, disc
  version 02.00). The setup names it and goes on, but it is untested: the port is built on the stand-alone disc
  (version 01.01). The archive check (A1) says whether its game archive is the same.
- **OneDrive.** Do not install into a OneDrive folder (a precaution from a problem reported on Project Helghast): OneDrive syncs the build's thousands of files while they are
  written and locks them. The setup refuses such a folder, and the first-run check refuses an install or build folder
  inside OneDrive (O1). Game files inside OneDrive are fine when they are on this device; files that are only online
  are refused before anything is read (O2): right-click the folder and choose "Always keep on this device" first.
- **EBOOT version.** The port is built on the 1.29 EBOOT. The disc's own 1.01 EBOOT is recognised and refused with a
  note.

## What the first-run check can print

The first step of the build prints one line per check: `OK`, `WARN` or `FAIL`, then a code. A `FAIL` stops the setup.
A `WARN` lets it go on. The full log is next to the installer (or in the install folder's `logs`).

| Code | Level | What it means | What to do |
|---|---|---|---|
| O1 | FAIL | The install folder or the build folder is inside OneDrive | Install into a folder outside OneDrive (the default is fine) |
| O2 | FAIL | A game file exists only online in OneDrive (nothing was read, so nothing was downloaded) | Right-click the game folders, choose "Always keep on this device", wait for the download, then run the setup again |
| O3 | OK | A note: the dump or update folder is inside OneDrive but its files are on this device | Nothing |
| D0 | OK / FAIL | FAIL: the dump folder was not found. OK: a note that the dump is a decrypted ISO file | Pick the dump folder again |
| I1 | FAIL | "this ISO is encrypted; use a decrypted dump": the ISO's file table or its files cannot be read as plain data | Use a decrypted dump (a folder or a decrypted ISO) |
| I2 | FAIL | The ISO cannot be read: not an ISO image, damaged or cut short | Copy the ISO again |
| D1 | OK / WARN / FAIL | FAIL: `PS3_GAME/PARAM.SFO` is missing or unreadable, or its title id is not BCUS98116 (the id and game found are named). WARN: the folder's category is not a disc game (maybe an installed copy), or the disc version is not 01.01 (02.00 is the Killzone Trilogy disc, untested) | Pick the folder that holds `PS3_GAME`. For a WARN you can go on |
| D2 | OK / WARN / FAIL | FAIL: `PS3_GAME/USRDIR/EBOOT.BIN` is missing, or is neither a SELF nor an ELF file. WARN: an unusual size (another version?) | Copy or dump the disc again if it is a FAIL |
| D3 | OK / FAIL | The game archive is missing, too small, does not start with `PSAR` (not an archive, or still encrypted), or its parts have a gap (the missing part is named) | Copy or dump the disc again; check that all parts `.66600`, `.66601`, ... are there |
| A1 | OK / WARN | The archive is compared with the known disc archive, taken from our copy of the disc (it reads the whole archive once; the result is kept, so later starts do not read it again). OK: it matches. WARN: it differs (a damaged or changed copy, or a printing of the disc not seen yet), or it could not be compared | If the game does not start or stops while loading, copy or dump the disc again |
| U0 | WARN / FAIL | No update folder was given (WARN), or it was not found (FAIL) | Pick the update folder |
| U1 | OK / WARN / FAIL | FAIL: the update's `PARAM.SFO` is missing, unreadable, not BCUS98116 or not the disc's title id. WARN: its version is not 01.29 | Pick the 1.29 update folder |
| U2 | OK / FAIL | `USRDIR/EBOOT.BIN` is missing in the update folder | Pick the folder that holds `PARAM.SFO` and `USRDIR` |
| U3 | OK / WARN | `USRDIR/added_data_ps3.psarc` is missing or does not start with `PSAR`, or the `USRDIR/patch_data_ps3` folder is missing: the update's data would be missing | Use a complete update folder |
| E1 | OK / WARN / FAIL | FAIL: no decrypted `EBOOT.elf` was found, or it is not a 64-bit PowerPC ELF. WARN: it is the disc's 1.01 EBOOT, another version, or an unknown size | Pick the decrypted EBOOT of the 1.29 update |
| H1 | OK / WARN | The EBOOT is compared with the known 1.29 one. A WARN means it differs or could not be compared | The build may still work if it is a 1.29 EBOOT; if the build fails, check the file |

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
- The [README](../README.md#requirements) has the requirements in short.
