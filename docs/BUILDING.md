# Building the port

The port's executable is generated from **your own copy** of the game: the game's PowerPC code is lifted to C++ from
your decrypted EBOOT and compiled on your machine. Nothing of the game is in this repository, and nothing is
downloaded.

There are two ways to get a build:

- **The installer or portable zip (Windows), pre-release <!-- version -->[v0.1.2](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.2)<!-- /version -->.**
  It checks your disc dump and the 1.29 update, then lifts and compiles the game's code on your machine with a bundled
  compiler, behind one progress bar, with a full log. Download it from the
  [releases page](https://github.com/undecuple/project-pyrrhus/releases). The scripts and the installer definition are in this repository (`installer/`,
  `tools/release/`) and are tested without the game.
- **A developer build from source with Nix**, described below. It is how the port is developed and tested today, on
  Linux (see [Status](#status-of-the-linux-build)). macOS and Windows (inside WSL2) use the same commands but have not been tried (see
  [Building on macOS](#building-on-macos) and [Building on Windows](#building-on-windows)).

The port is early and partly playable: the first level can be played with a pad (see the [README](../README.md#status) and [KNOWN_ISSUES.md](KNOWN_ISSUES.md)).
A build starts, shows the menus and draws the first level at about 23 frames per second in one scripted run under Proton (the PS3 runs it at 30).

**Pinned versions:** the build uses ps3recomp **v0.18.0** (the `third_party/ps3recomp` submodule) with this project's
patch set from `port/patches/` applied on top (step 2). Do not substitute another ps3recomp version: the patches are
made against that release and step 2 stops on one that does not apply.

## What you need

From your own copy of the game (details in [requirements.md](requirements.md); what each folder must hold and what the
first-run check prints: [GETTING-FILES.md](GETTING-FILES.md)):

| Item | Notes |
|---|---|
| Killzone 2, US disc **BCUS98116**, dumped as a folder | The folder that holds `PS3_GAME/`. Other regions are untested. |
| Update **1.29** | The port's target version. The build reads its added archive and patch files. |
| The **decrypted EBOOT** | `EBOOT-129.elf`, the decrypted main program of the 1.29 update, from your own copy of the game. This project provides no tools or instructions for making it. |

To build: Linux with [Nix](https://nixos.org/) (flakes enabled), 16 GB of RAM or more, and free disk beyond the game
dump: the build tree itself took about 2.7 GB (build 2.3 GB, lifted code 0.4 GB), and `kz2.exe` alone is about 1 GB. To run: a GPU with Direct3D 12 and a CPU with AVX and FMA3. The
tested way is the Windows build under Proton (Experimental or GE-Proton) on Linux.

**Version note:** the lift can also start from the disc's own v1.01 EBOOT (`KZ2_EBOOT_VER=101`), which needs
`Game/PS3_GAME/USRDIR/EBOOT.elf`. The default and the target is 1.29.

## Toolchain

Everything comes from the Nix flake; nothing needs to be installed system-wide.

```sh
nix develop .#re     # analysis and lifting: Python tools, bubblewrap
nix develop .#win    # Windows x64 cross build: MinGW-w64, CMake, Ninja, SDL3 for Windows
nix develop          # everything, plus the tools for test runs under Proton
```

`tools/sandbox.sh -- CMD` runs a command with the game and the repository read-only, only `work/` and `build/`
writable, and no network. The steps below run inside it.

## Steps

```sh
git clone --recursive https://github.com/undecuple/project-pyrrhus
cd project-pyrrhus                                   # third_party/ps3recomp comes with --recursive, pinned
```

Steps 1 to 4 below were run in a fresh copy of the repository (with `third_party/ps3recomp` checked out at the pinned
commit) on NixOS; the `git clone --recursive` line itself was not run.

```sh
# 1. Point the repo at your game files (they stay outside git and are mounted read-only)
ln -s /path/to/your/disc-dump Game                   # the folder that holds PS3_GAME/
mkdir -p work/bin && cp /path/to/decrypted/EBOOT-129.elf work/bin/EBOOT-129.elf

# 2. Patched recompiler: a fresh copy of the pinned ps3recomp with port/patches/*.patch applied
nix develop .#re --command tools/sandbox.sh -- tools/ps3recomp-patched.sh

# 3. Lift the PPU code into work/recomp/ (65 source chunks, about 325 MB; 1 minute)
nix develop .#re --command tools/sandbox.sh -- tools/lift.sh

# 3b. Lift the SPU code into work/spu/ (60 images, about 40 MB; 30 seconds). Needs step 2.
nix develop .#re --command tools/sandbox.sh -- tools/spu/lift_spu.sh -j 4

# 4. Configure and build kz2.exe (build-kz2.sh configures on first use, picks up work/spu/lift by itself,
#    and caps the compiler jobs by free memory; KZ2_BUILD_JOBS_MAX=4 lowers the cap, the default is 6)
KZ2_BUILD_JOBS_MAX=4 nix develop .#win --command tools/sandbox.sh -- tools/build-kz2.sh build/kz2-win
# prints "build-kz2: build/kz2-win with -j4 ..." and "build-kz2: done in 1079 s (-j4, exit 0)"; the result is
# build/kz2-win/kz2.exe (about 1 GB) with at3_standalone.dll beside it; kz2.exe needs that DLL to start.
# Movie pictures and 5.1 sound need two more DLLs, see "Movie decoders (FFmpeg DLLs)" below.

# 5. Run under Proton (hidden display, audio off; output in work/proton/NAME/). Not run in the build test above (untested here).
nix develop --command tools/proton-test.sh --seconds 60 --name boot build/kz2-win/kz2.exe ./Game/PS3_GAME/USRDIR/EBOOT.elf
```

The build is the slow part: with four compiler jobs it took about 18 minutes (the lifts took 1 minute and
30 seconds). Each lifted source chunk can take well over 1 GB of memory to compile. The
SPU lift (3b) must be done before step 4: without `work/spu/lift/spu_workloads.c` the build does not include the
lifted SPU code (`KZ2_SPU=0` also leaves it out).
After a change to a patch, rerun step 2; the build refuses a patched recompiler that is older than the patch set.

Step 5 uses GE-Proton from Steam's `compatibilitytools.d` by default (`--proton DIR` picks another). The program's
output is in `work/proton/NAME/app/app_stdout.txt` and a screenshot in `work/shots/NAME.png`. Environment switches
for logging and diagnostics are documented in the source where they are read (`getenv`).

## Movie decoders (FFmpeg DLLs)

Without `avcodec-63.dll` and `avutil-61.dll` beside `kz2.exe` the game still starts, but movies stay black and
have no 5.1 sound. They are FFmpeg 9.0.1 built LGPL-only (H.264, MPEG-2 and AC-3 decoders; no GPL or non-free parts)
as separate DLLs that `kz2.exe` loads at run time. Build them before step 4, with Nix's MinGW-w64 cross compiler (this step
needs the network once, to fetch the FFmpeg source). Give the flake reference as `git+file://` and your checkout's
absolute path, with `%20` for each space:

```sh
nix build --impure -o work/ffmpeg-win --expr \
  'import ./tools/runtime/ffmpeg-lgpl-win.nix { pkgs = import (builtins.getFlake "git+file:///path/to/this/checkout").inputs.nixpkgs { system = "x86_64-linux"; }; }'
# work/ffmpeg-win/bin/avcodec-63.dll and avutil-61.dll; share/ffmpeg-lgpl/ holds the licence text, SOURCE.txt and LICENSE-build.txt
```

Step 4's `tools/build-kz2.sh` then finds the FFmpeg headers in `work/ffmpeg-win/include`; copy the two DLLs next to
`kz2.exe`. Keep the three text files with them if you pass the DLLs on (LGPL).

## Running

`kz2.exe` takes the path of the decrypted EBOOT as its one argument:

```
kz2.exe path\to\EBOOT.elf
```

There is no ini file for the program itself. It reads these environment variables (set them before starting):

| Variable | Meaning |
|---|---|
| `PS3_VFS_ROOT` | The folder holding `PS3_GAME`. Default: three folders above the EBOOT (`<root>/PS3_GAME/USRDIR/EBOOT.elf`). |
| `KZ2_UPDATE_DIR` | The 1.29 update's `USRDIR` folder. |
| `PS3_HDD0_ROOT` | A `dev_hdd0` folder, only if your update sits in one. Optional. |
| `PS3_EDAT_CACHE` | Where decrypted game files are cached. Optional. |
| `KZ2_PAD_LAYOUT` | `original` (default) or `modern` pad buttons. |
| `KZ2_PROMPTS` | Button prompt symbols: `ps3`, `ps4`, `xbox` or `keyboard`. Unset: chosen from the pad in use. |
| `KZ2_DISPLAY` | `windowed` (default), `borderless` or `fullscreen`. Unset: the game's `display.ini` decides (Alt+Enter also switches). |

The installer and the portable zip set these for you. They keep their choices in `kz2-install.ini` in the install
folder: `[install] portable` (1 keeps saves and settings in that folder), `[online] check_updates` (0 by default; the
only network use, and it asks first) and `[controls] layout` (`original` or `modern`), `[controls] prompts` (as `KZ2_PROMPTS`, `auto` by default) and
`[display] mode` (as `KZ2_DISPLAY`). The launcher in
`installer/launcher/` reads that file and starts the game with the variables above.

## Status of the Linux build

Built from a fresh copy of the repository on NixOS, CPU build only; run under Proton, not on real Windows. Steps 1 to 4 (including 3b)
ran to the end and produced `kz2.exe`, linked with the lifted SPU code. Step 5 was not part of that build test.

## Building on macOS

**Status: not tested. No build has been run on a Mac yet, and nothing has been run on macOS.** Reports are welcome
(open an issue).

- **Untested route:** a Mac with Apple silicon and Nix with flakes enabled, then the [Steps](#steps) 1 to 4 as
  written. `tools/sandbox.sh` needs bubblewrap, which is Linux-only, so on macOS it may need to be bypassed by running
  the commands directly. Nobody has tried this. The cross-compiler would be built by Nix the first time, which can
  take a long while.
- **Running:** `kz2.exe` is a Windows program and Proton does not run on macOS. The route is the one in
  [Building on Windows](#building-on-windows): copy the finished build and the game to a Windows PC. Not tried.
- **Windows-on-Mac layers (untested):** tools that run Windows programs on Apple silicon with Direct3D 12 translated
  to Metal might start `kz2.exe`, but expect it to be much slower than on a PC; the port is not at full speed even
  natively. If you try, open an issue with your Mac model, macOS version, the tool and its version, how far the game
  got, and the log.
- **Native macOS build:** not started.

## Building on Windows

**Status: partly tested.** The installer's first-run build (the bundled compiler translating and building the game on
Windows) ran in a Windows 10 virtual machine with no GPU (6 cores, 8 GB of memory) on 2026-10-27 and produced kz2.exe in 18.6 minutes with 2 jobs. Building
from the repository by hand on Windows is not tested, and the game has not been played on Windows; play is tested
under Proton on Linux.

1. **The route to try first (untested): build on Linux, run on Windows.** Do the [Steps](#steps) 1 to 4 on a Linux
   machine. Copy `kz2.exe` and `at3_standalone.dll` (and, for movies, `avcodec-63.dll` and `avutil-61.dll` from
   [Movie decoders](#movie-decoders-ffmpeg-dlls)) into one folder, and your game folder (`PS3_GAME`, which holds
   the game's data and takes many gigabytes) to a Windows PC with a Direct3D 12 GPU, keeping the layout
   `PS3_GAME\USRDIR\...`. Put the decrypted `EBOOT-129.elf` in `PS3_GAME\USRDIR\` (beside the disc's own files) and, in a terminal
   in the folder with `kz2.exe`, run `kz2.exe .\PS3_GAME\USRDIR\EBOOT-129.elf`. Set `KZ2_UPDATE_DIR` to the update's `USRDIR` first.
2. **Build inside WSL2 (untested):** install WSL2 with Ubuntu (`wsl --install -d Ubuntu`), install Nix there with
   flakes enabled, give WSL2 at least 16 GB of memory in `%UserProfile%\.wslconfig`, keep the repository in the
   Linux file system (not under `/mnt/c`), link your dump from `/mnt/...` as in step 1, and run the Steps 1 to 4. Then
   copy the result to a Windows folder as in route 1. No one has run this on WSL2.
3. **The installer or portable zip:** it does the lift and the build on Windows without WSL2 or Nix (see the top of
   this page).

If you try either route, open an issue with your Windows version, GPU and driver, how far it got, and the log.

**Cloning on Windows: turn off git's line-ending conversion.** Git for Windows installs with `core.autocrlf=true`, which
checks LF files out with CRLF line endings. The patches in `port/patches/` then stop applying part-way through the
series (patch 1041 was the first in one test on Windows 11 with Git for Windows 2.46, issue #9). Clone without it, and
turn it off in the submodule too:

```sh
git -c core.autocrlf=false clone --recurse-submodules https://github.com/undecuple/project-pyrrhus.git
cd project-pyrrhus
git config core.autocrlf false
git -C third_party/ps3recomp config core.autocrlf false
```

An existing clone can be fixed the same way. After the two `config` lines, write the submodule's files out again with
`git -C third_party/ps3recomp rm -r -q --cached .` and then `git -C third_party/ps3recomp reset -q --hard`. A plain
checkout skips files that git considers unchanged, and the reset discards any edits in the submodule.
`tools/ps3recomp-patched.sh` checks this before it copies anything and stops with these commands when it finds CRLF files
in the submodule.

## Tests without the game

```sh
nix develop .#re --command python3 tools/release/test_installer_art.py
```

`tools/host-tests.txt` lists the host tests (the installer's checks, packaging, the asset tools). They need no game
data and no GPU. Each line is a command to run inside the Nix shell shown on that line.

On Windows without Nix, the Python tests run with Python 3.12 (`python tools/release/test_....py`), and the shell
tests in `tools/` with Git Bash. The exception is the shell tests in `tools/spu/` and `tools/runtime/` that compile C
test programs against the runtime with the Nix shell's Linux compilers: they are Linux tests, run by CI, and are not
expected to pass on Windows.
