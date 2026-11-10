# Project Pyrrhus: Windows VM installer test

Run in the guest as the normal user, one line at a time, from cmd.exe (an ssh session lands there). Python is
called by its full path (`python` and `py` may be the Microsoft Store stubs). Each step writes
`C:\kz2\out\NN-name.txt` and ends with `RESULT NN-name PASS|FAIL|SKIP <why>`. When done (or at the first FAIL), send
back the whole `C:\kz2\out` folder. Needs about 20 GB free on C:. A FAIL stops the run unless the line says otherwise.

Run the steps in the order below, not by their numbers: 11 and 12 come before the install, 13 to 22 on the fresh
install before the build, 23 just before the uninstall. Steps 11 to 23 test what changed for v0.1.2 with wrong
inputs the steps make themselves under `C:\kz2\t` (empty folders, a stand-in EBOOT, synthetic PARAM.SFO files and a
small synthetic ISO; no game data). Each shows the text a player would see, then one `ok` or `NOT` line per
expectation; a `NOT` line makes the step FAIL. A FAIL in 11 to 23 does not stop the run: go on and send everything.
Step 22 opens windows and must run from the desktop session (not over ssh); do not click anything while it runs.

### 01-copy
Copy the kit and the game files to a local folder (the share is slow and breaks junctions):
`powershell -NoProfile -Command "New-Item -ItemType Directory -Force C:\kz2\out | Out-Null; robocopy <SHARE> C:\kz2 /E /R:2 /W:5 /NP /NFL /NDL /LOG:C:\kz2\out\01-copy.txt; $rc = $LASTEXITCODE; Add-Content C:\kz2\out\01-copy.txt ('robocopy exit ' + $rc); 'robocopy exit ' + $rc"`
PASS: robocopy exit 0 to 7. FAIL: 8 or more.

### 02-verify
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 02-verify`
Checks the kit's SHA-256 list, the game files and the free space; notes Windows, cores, RAM.
PASS: `RESULT 02-verify PASS`. FAIL: a kit file differs, a game file is missing, or under 6 GB free.

### 11-setup-onedrive (before the install)
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 11-setup-onedrive`
The setup, silent, told to install inside OneDrive (`/DIR=<OneDrive>\Project Pyrrhus vm-test`). Without OneDrive on
the VM, the step gives the setup a stand-in `OneDrive` variable pointing at `C:\kz2\t\OneDrive`.
PASS (OneDrive on the VM) or SKIP (the stand-in): setup exit code 7; the step file shows "The folder ... is inside
OneDrive, which syncs the build's thousands of files while it runs and locks them. Choose a folder outside OneDrive
..."; no uninstall entry; nothing written there. FAIL: the setup installed or did not say why.

### 12-setup-eboot101 (before the install)
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 12-setup-eboot101`
The setup, silent, given `/EBOOT=C:\kz2\t\eboot101\EBOOT.elf`: a stand-in the size of the disc's 1.01 EBOOT (an ELF
header and zeros, made by the step).
PASS: setup exit code 7; the step file shows "Silent install stopped: ...: This is the disc's 1.01 EBOOT. This
release needs the EBOOT of the 1.29 update: EBOOT.elf, ... USRDIR ..." (read from
`C:\kz2\kit\Project-Pyrrhus-setup.log`); no uninstall entry; nothing installed.

### 03-install
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 03-install`
Silent per-user install to the default folder (`%LOCALAPPDATA%\Programs\Project Pyrrhus`), no build:
`Project-Pyrrhus-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=... /MERGETASKS=!buildnow`.
PASS: setup exit 0, the uninstall entry and the main files present. Expected: under a minute, no window.

### 04-layout
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 04-layout`
Every installed file against the payload's own list (manifest.json), the Start menu entries, the settings file.
PASS: 0 problems, Start menu entries present.

### 05-checks
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 05-checks`
The first-run file checks on the copied game files. PASS: every line OK or WARN, `first-run checks: pass`.

### 13-bundled-python
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 13-bundled-python`
The installed Python (`toolchain\python`, the embeddable one) as the first run uses it. Control: a script that
imports a module beside it fails with ModuleNotFoundError (the `._pth` file keeps the script's folder off
sys.path). Then `firstrun_check.py`, started by full path from `C:\`, with an `.iso` file as the disc.
PASS: no ModuleNotFoundError and no traceback, "INFO: dump: decrypted ISO not-an-image.iso", then "FAIL I2" (not a
disc image). SKIP: this Python finds a module beside the script by itself (the fix is then not exercised).

### 14-onedrive-check
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 14-onedrive-check`
The first-run check told that the install folder is inside OneDrive (the VM's OneDrive, else the stand-in).
PASS (OneDrive) or SKIP (the stand-in): "FAIL O1: the install folder ... is inside OneDrive ..." and the same text
among the stop reasons, then "Passed: the disc dump, the 1.29 update and the decrypted EBOOT."

### 15-empty-folder
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 15-empty-folder`
The check with the empty folder `C:\kz2\t\empty` as the disc, then as the update.
PASS: "Disc dump failed: C:\kz2\t\empty holds no PS3_GAME folder (the folder is empty). It must be ..." and
"1.29 update failed: C:\kz2\t\empty holds none of these files (the folder is empty). It must be ...", each followed
by "Passed: ..." naming the other two inputs.

### 16-drive-root
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 16-drive-root`
The check with `C:\` as the disc, then as the update.
PASS: "Disc dump failed: C:\ holds no PS3_GAME folder ..." and "1.29 update failed: C:\ holds none of these files
...", the other inputs passed. (A line may add where the disc or update seems to be on the drive.)

### 17-swapped
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 17-swapped`
The update folder given as the disc and the disc as the update; the disc's PS3_GAME as the update; then PS3_GAME as
the disc and the update's USRDIR as the update (one level too deep).
PASS: "Disc dump failed: ... looks like the 1.29 update ...", "1.29 update failed: ... looks like the disc dump, not
the update ...", "1.29 update failed: ... looks like the disc's PS3_GAME folder ...", and for the last pair the INFO
lines "using the folder that holds PS3_GAME" and "using the update folder" with `first-run checks: pass`.

### 18-disc-id
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 18-disc-id`
The disc's title id. The copied dump: "OK   disc dump: TITLE_ID BCUS98116 (...)". Synthetic PARAM.SFO files
(made by the step under `C:\kz2\t`): another game's id gives "FAIL disc dump: this is NPUB30001 (Synthetic
other game), not Killzone 2 ..."; the Trilogy disc (BCUS98116, VERSION 02.00) gives "WARN ... the Killzone
Trilogy disc ... Untested ..." and still passes. PASS: all three.

### 19-iso
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 19-iso`
A small synthetic decrypted ISO (built with the kit's `iso_fixture.py`) as the disc.
PASS: "INFO: dump: decrypted ISO synthetic.iso", "OK   ... inside the ISO)" and `first-run checks: pass`; then the
same image with a scrambled archive gives "FAIL I1: this ISO is encrypted; use a decrypted dump" and "Disc dump
failed: ...".

### 20-eboot-101
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 20-eboot-101`
The 1.01 stand-in EBOOT. The check: "FAIL E1: This EBOOT is Killzone 2 1.01, the disc's own version. ..." and
"EBOOT failed: ... This release needs Killzone 2 1.29 (BCUS98116, US).". Then the console (`firstrun.py --interactive`, the step types the answers; it never builds here): it asks for
the EBOOT alone ("The EBOOT must be the 1.29 update's one, not the disc's ..."), takes the folder
`C:\kz2\t\eboot101` as the answer ("using C:\kz2\t\eboot101\EBOOT.elf"), refuses it again, and q ends with "Nothing
was built. The next start checks your game files again."
PASS: all of that; the status file has "REASON EBOOT failed: ..."; `kz2-install.ini` [paths] has `wrong = eboot`.
The step puts `kz2-install.ini` back afterwards.

### 21-ask-again
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 21-ask-again`
Start 1: the console with the empty folder as the disc, q after the FAIL. Then what the launcher would run next
(`--check-first` with those answers). Start 2: the console with no folders given (as the zip's `run.cmd`): it
checks the recorded answers first; after c it asks again only for the disc dump.
PASS: the status file has "REASON Disc dump failed: ..." and "REASON Passed: ..."; `wrong = dump` recorded; the line
"questions asked after c: ['Disc dump: the folder holding PS3_GAME']". The step puts `kz2-install.ini` back.

### 22-launcher-dialog (desktop session, before the build)
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 22-launcher-dialog`
The step writes `build\paths.json` naming the empty folder as the disc and starts `Project Pyrrhus.exe`. It reads
each dialog's text from the window and presses the button itself: "The last build did not finish. Continue the
build now? ..." (Yes); a console window runs the check for a few seconds; then "The build did not finish (code 1):
- Disc dump failed: ... - Passed: ... Fix this, then open Project Pyrrhus again: it checks your game files first and
asks again only for the ones that are wrong. The log is ..." (OK). Do not click anything while it runs.
PASS: both dialogs with those texts in the step file. SKIP: no dialog seen (an ssh session). The step removes its
`paths.json` and puts `kz2-install.ini` back afterwards.

### 06-build
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 06-build`
The first-run build (translate and compile) with 2 jobs for 8 GB RAM. Expected: tens of minutes; the console
shows nothing until the end. PASS: `kz2.exe` and the build stamp present, and the launcher would now start the
game. Its log: `out\06-firstrun.log`.

### 07-launch
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 07-launch`
Starts `Project Pyrrhus.exe` once, watches its processes and windows for 60 s, then ends them by process id.
Expected without a GPU: the game stops at Direct3D 12 device creation (a WARP fallback is still to come), and the
launcher shows "The game stopped unexpectedly". PASS: `kz2.exe` started; a device-creation stop is not a FAIL.
Go on to the next step even on FAIL.

### 08-readonly
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 08-readonly`
The same start with the install folder denied to this user for writing (icacls, restored afterwards).
Facts only: which writes into the install folder fail. PASS or SKIP; go on either way.

### 23-uninstall-cover (just before the uninstall)
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 23-uninstall-cover`
Lists what the first run and the launcher wrote into the install folder, and adds what a first run may leave:
`game\disc\PS3_GAME\PARAM.SFO` (the copy out of a decrypted ISO), a rotated first-run log and
`logs\firstrun-status.txt`. PASS: written. 10-leftovers then fails if any of it stays after 09.

### 09-uninstall
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 09-uninstall`
Silent uninstall (`unins000.exe /VERYSILENT /SUPPRESSMSGBOXES`). PASS: the uninstall entry is gone.

### 10-leftovers
`"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 10-leftovers`
PASS: the install folder, shortcuts and uninstall entry are gone; `%APPDATA%\Project Pyrrhus` holds only saves
and settings (or nothing); the game files are unchanged.

### Optional: the setup's pages by hand (desktop session, after 10-leftovers)
The silent steps cannot show the setup's own boxes. With a desktop, double-click
`C:\kz2\kit\Project-Pyrrhus-setup.exe`, note each box's text (a screenshot is best), and Cancel at the end:
1. Folder page: a folder under your OneDrive (if the VM has one), Next: a box says it is inside OneDrive.
2. Disc page: `C:\kz2\t\empty`, Next: a box names the folder and says what it holds.
   `C:\kz2\game\update\BCUS98116`: it looks like the 1.29 update folder (give it as the update).
   `C:\kz2\game\dump\PS3_GAME`: taken, with "Found: BCUS98116 (...)" under the field.
3. Update page: `C:\kz2\game\dump`: a box says that is a disc dump.
4. EBOOT page: `C:\kz2\t\eboot101\EBOOT.elf`: "This is the disc's 1.01 EBOOT ...". The folder `C:\kz2\game\eboot`:
   taken (the EBOOT.elf in it).

To repeat a step, run its line again (it overwrites its file). Steps 07, 08 and 22 open windows; in an ssh session
without a desktop they may not show, and the step's file then lists no window titles (22 is then a SKIP).
