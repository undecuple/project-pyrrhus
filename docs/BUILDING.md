# Building the port

The port's executable is generated from **your own copy** of the game: the game's PowerPC code is lifted to C++ from
your decrypted EBOOT and compiled on your machine. Nothing of the game is in this repository, and nothing is
downloaded.

There are two ways to get a build:

- **The installer or portable zip (Windows), pre-release <!-- version -->[v0.1.13](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.13)<!-- /version -->.**
  It checks your disc dump and the 1.29 update, then lifts and compiles the game's code on your machine with a bundled
  compiler, behind one progress bar, with a full log. Download it from the
  [releases page](https://github.com/undecuple/project-pyrrhus/releases). The scripts and the installer definition are in this repository (`installer/`,
  `tools/release/`) and are tested without the game.
- **A developer build from source with Nix**, described below. It is how the port is developed and tested today, on
  Linux (see [Status](#status-of-the-linux-build)). macOS and Windows (inside WSL2) use the same commands but have not been tried (see
  [Building on macOS](#building-on-macos) and [Building on Windows](#building-on-windows)).

The port is early and partly playable: the first level can be played with a pad (see the [README](STATUS.md) and [KNOWN_ISSUES.md](KNOWN_ISSUES.md)).
A build starts, shows the menus and draws the first level at 23-33 frames per second in our scripted runs under Proton (23.3 over one 330 s run on 2026-10-22, a median of 32.6 in short turn-and-walk windows on 2026-10-29; the PS3 runs it at 30).

**Pinned versions:** the build uses ps3recomp **v0.18.0** (the `third_party/ps3recomp` submodule) with this project's
patch set from `port/patches/` applied on top (step 2). Do not substitute another ps3recomp version: the patches are
made against that release and step 2 stops on one that does not apply.

## What you need

From your own copy of the game (details in [requirements.md](requirements.md); what each folder must hold and what the
first-run check prints: [GETTING-FILES.md](GETTING-FILES.md)):

| Item | Notes |
|---|---|
| Killzone 2, US disc **BCUS98116**, dumped as a folder | The folder that holds `PS3_GAME/`. The European (BCES00081), Asian (BCAS20066) and Japanese (BCJS30032) discs are accepted by the first run but untested; each needs its own region's 1.29 update. |
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

The Lua recovery change needs a fresh step 3 before rebuilding. `tools/lift.sh`
generates its host continuations automatically. If calling the PPU lifter directly,
follow it with `python3 tools/release/lua_unwind.py --recomp-dir work/recomp --version 129`
(use `101` for that executable). A missing continuation marker prevents compiling
the new jump override; `build-kz2.sh` also rejects stale generation receipts.

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
`kz2.exe`. Configuring `port/kz2` by hand needs `-DKZ2_FFMPEG_INCLUDE_DIR=<folder holding libavcodec/avcodec.h>`:
without it CMake stops, because the game would build without its movies. `-DKZ2_ALLOW_NO_FFMPEG=ON` builds without
them on purpose (black movie pictures, no 5.1 sound; `build-kz2.sh` does this, with a warning, when it finds no headers). Keep the three text files with them if you pass the DLLs on (LGPL).

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
| `KZ2_AIM_ASSIST` | `auto` (default), `on` or `off`: the game's aim assist (slows and pulls the aim towards a target on the right stick). `auto` is on for a pad and the keyboard. Unset: `gameplay.ini` decides. |
| `KZ2_CROUCH_TOGGLE` | `1`: a tap of the crouch button crouches and a second tap stands (the game's own toggle option, which the game only offers online). Default `0`: hold to crouch, as in the original. |
| `KZ2_COVER_TOGGLE` | `1`: a tap of the cover button takes cover and a second tap (or a sprint or jump) leaves it. Default `0`: hold to take cover, as in the original. |
| `KZ2_PROMPTS` | Button prompt symbols: `ps3`, `ps4`, `xbox` or `keyboard`. Unset: chosen from the pad in use. |
| `KZ2_DISPLAY` | `borderless`, `windowed` or `fullscreen`. Unset: the game's `display.ini` decides; with no `display.ini` a new install starts borderless (Alt+Enter switches to a window and back). |
| `KZ2_SKIP_INTRO` | `0` shows the opening movie page, `1` starts at the main menu. Unset: Options > Display's saved **Skip intro (next start)** choice decides; the default is off. |
| `KZ2_LUA_UNWIND` | `0` restores the previous guest jump behavior for diagnosis. Leave unset for corrected protected Lua error handling. |

The same three gameplay choices can be kept in `gameplay.ini` next to `keybinds.ini` (the installer and the launcher create it with the defaults when it is missing and never overwrite it; the game only reads it):
`[gameplay]` then `aim_assist = auto|on|off`, `crouch_toggle = 0|1`, `cover_toggle = 0|1`. The variables win for one run.

The installer and the portable zip set these for you. They keep their choices in `kz2-install.ini` in the install
folder: `[install] portable` (1 keeps saves and settings in that folder), `[online] check_updates` (0 by default; the
only network use, and it asks first) and `[controls] layout` (`original` or `modern`), `[controls] prompts` (as `KZ2_PROMPTS`, `auto` by default) and
`[display] mode` (as `KZ2_DISPLAY`). The launcher in
`installer/launcher/` reads that file and starts the game with the variables above.

## Status of the Linux build

Built from a fresh copy of the repository on NixOS, CPU build only; run under Proton, not on real Windows. Steps 1 to 4 (including 3b)
ran to the end and produced `kz2.exe`, linked with the lifted SPU code. Step 5 was not part of that build test.

## Building on macOS

**Experimental native ARM64 route.** It has been run on one Mac, an Apple M4 Pro, in the contributor's own runs,
driven by `PAD_FILE` button and stick input (no physical controller): the language and gamma screens, the intro movies
(H.264 and 5.1 AC-3 through the LGPL-only FFmpeg below), the title screen, the main menu, Continue and New Campaign,
the Corinth River loading screen, the first mission's cruiser sequence and, in one run, the beach landing with its HUD.
Known gaps on Mac are in [KNOWN_ISSUES.md](KNOWN_ISSUES.md): the SPU post effects start off, and the Metal
depth-bounds and depth-clamp emulation is off by default. Frame rates, from those scripted runs (per-second counts of
presented frames over 40-420 s windows, the player idle or walking): about 30 frames per second in the cruiser
sequence (55-59 of 60 seconds at 30 in a 7-minute run), about 50 walking on the cruiser, and a median of about 20 in
the beach fight (one 113 s window). They are one machine's numbers, not a requirement or a promise.

The first bring-up's multi-second freezes came from first-seen Metal pipelines compiled synchronously on the FIFO
thread and from a fully covered game window starving `nextDrawable`. Patch 2173 stores compiled pipelines in an
`MTLBinaryArchive` beside the game's other writes (`PS3RECOMP_METAL_PSO_ARCHIVE`); patch 2178 keeps the walker off
the compositor with a prefetching presenter thread and a bounded in-flight wait (`PS3RECOMP_METAL_PRESENT_WAIT_MS`,
default 100 ms); patch 2179 builds new pipelines in the background (`PS3RECOMP_METAL_ASYNC_PSO=0` restores the
synchronous build), and 2181-2184 record and prewarm them and keep the walker from waiting on them.

The native route uses Apple Clang and the toolkit's existing Metal backend with guest-shader translation, not
Direct3D 12 or Proton. The guest runs on a 256 MiB-stack worker while the main thread services Cocoa. ARM64 builds
omit x86 ISA flags and the optional x86 native SPU-job replacements; the lifted SPU jobs stay enabled.

Prerequisites are Xcode Command Line Tools (or Xcode), Python 3.11+, CMake, Ninja, SDL2 and SDL3. For guest shaders,
install glslang, SPIRV-Tools and SPIRV-Cross; a fixed-function-only fallback is insufficient for this smoke test.
The patch-preparation shell script also needs GNU coreutils (`realpath`, `sha256sum`). With Homebrew these are the
packages `python@3.12 cmake ninja sdl2 sdl3 glslang spirv-tools spirv-cross coreutils`. The tested build used already
installed tools; no package installation was performed as part of validation.

From an initialized checkout (`third_party/ps3recomp` at the repository's pinned commit), prepare the patched tree
as in the source-build steps. On macOS, put GNU coreutils on PATH for that shell script:

```sh
export PATH="$(brew --prefix coreutils)/libexec/gnubin:$PATH"
bash tools/ps3recomp-patched.sh
python3.12 tools/build-kz2-macos.py --smoke
python3.12 tools/runtime/test_macos_host.py
python3.12 tools/runtime/test_spu_pool_portability.py
python3.12 tools/test_macos_smoke.py
python3.12 tools/test_macos_smoke.py --windowed
```

The two Metal smoke commands require GPU access. They run only the toolkit's generated synthetic ELF, in temporary
folders; they do not read the game. The smoke build also compiles a synthetic SPU translation unit and the real
SPU dispatch source. Success requires all 11 boot markers, three presented frames, vblank and the guest's exit.
The generated executable is `build/kz2-macos-smoke/kz2`; logs are in `work/macos-smoke/run-*.log` and
`build/kz2-macos-smoke/build-macos.log`. This executable contains synthetic functions and cannot run Killzone 2.
The toolkit used on Mac was prepared from the exact pinned commit and the complete patch series without the
submodule (a `git archive` of the pinned commit); fresh submodule initialization and the shell preparation route
were not exercised on Mac.

For a game build, `tools/lift-kz2-macos.py` accepts an **existing decrypted 1.29 ELF** whose SHA-256 matches the
known US build. It performs no SELF conversion and uses no keys. It runs the same Python analysis/lifting tools,
TOC, code boundary, 64 chunks, overrides and Lua continuations as the Linux scripts, with one worker and the native
build's resource guard. The PPU/SPU lift has been generated from the verified USA 1.29 ELF on Apple silicon:
65 PPU translation units, 60 SPU images, no failed SPU lifts. It also turns on two SPU lift additions that are
opt-in elsewhere: the interpreter-found entry seeds (`re/spu_entry_seeds_v129.tsv`, `KZ2_SPU_ENTRY_SEEDS=1`) and the
Amadeus audio plugins lifted at LS 0x8400 (`KZ2_SPU_AMADEUS_PLUGINS=1`). Other games' lifted code cannot be substituted.

Run game-reading tools with read-only inputs and no network. For example, from the repository root on Mac:

```sh
KZ2_REPO="$(pwd -P)"
KZ2_SANDBOX="(version 1)(allow default)(deny network*)(deny file-write*)(allow file-write* (literal \"/dev/null\") (subpath \"$KZ2_REPO/work\") (subpath \"$KZ2_REPO/build\"))"
sandbox-exec -p "$KZ2_SANDBOX" python3.12 -B tools/lift-kz2-macos.py --eboot /path/to/EBOOT.elf
```

The generated sources stay under ignored `work/recomp` and `work/spu/lift`. Logs are in `work/native-lift`.
The build checks the lift's version, toolkit stamp, override announcements and Lua receipt before compiling.
Once those inputs exist:

```sh
bash tools/runtime/ffmpeg-lgpl-macos.sh
python3.12 tools/build-kz2-macos.py --ffmpeg-include work/ffmpeg-macos/include
python3.12 tools/run-kz2-macos.py --disc /Volumes/PS3VOLUME --update /path/to/BCUS98116 --eboot /path/to/EBOOT.elf --seconds 60
```

FFmpeg headers and matching libraries from an **LGPL-only build** are needed for movie/AC3 decoding, as in the
Windows route; do not substitute a GPL-enabled FFmpeg build (Homebrew's is one). `tools/runtime/ffmpeg-lgpl-macos.sh`
builds FFmpeg 9.0.1 with the Windows recipe's decoder set and checks `config.h` for LGPL 2.1 only; it needs the
network once, for the source. The runner then loads `work/ffmpeg-macos/lib`. On an Apple M4 Pro the intro movie
played with its picture and its 5.1 AC-3 sound decoded through it. `PS3RECOMP_FFMPEG_AVCODEC` and
`PS3RECOMP_FFMPEG_AVUTIL` select other matching dylibs at launch.
`--allow-no-ffmpeg` is an explicit developer-only build with black movies and silent AC3.

The system fontset (Cyrillic, Greek and CJK text) reads `build/kz2-macos/fonts/`. Without Nix, make the two files
with the release scripts from the pinned upstream sources (both scripts refuse a source whose SHA-256 differs) and
fontTools 4.63.0 in a throwaway virtual environment:

```sh
python3.12 -m venv /tmp/ft && /tmp/ft/bin/pip install fonttools==4.63.0
curl -fLo /tmp/NotoSans.ttf 'https://raw.githubusercontent.com/notofonts/notofonts.github.io/noto-monthly-release-2026.10.01/fonts/NotoSans/unhinted/variable-ttf/NotoSans%5Bwdth%2Cwght%5D.ttf'
curl -fLo /tmp/NotoSansCJK-VF.otf.ttc 'https://github.com/notofonts/noto-cjk/raw/Sans2.004/Sans/Variable/OTC/NotoSansCJK-VF.otf.ttc'
mkdir -p build/kz2-macos/fonts
/tmp/ft/bin/python -B tools/runtime/mkfont_noto.py --src /tmp/NotoSans.ttf build/kz2-macos/fonts/NotoSans-Regular.ttf
/tmp/ft/bin/python -B tools/runtime/mkfont_cjk.py --src /tmp/NotoSansCJK-VF.otf.ttc build/kz2-macos/fonts/NotoSansCJK-Regular.ttc
```

The CJK output matches the release's pinned SHA-256. A run's log should show `2 font file(s) in the chain`.

The bounded native runner uses the mounted disc in place, never copying the whole ISO. It verifies the inputs,
blocks network access and writes only under `work/` and `build/`. Saves/caches are isolated from RPCS3's data.
`--skip-intro` is an opt-in diagnostic for one run; `--headless` selects offscreen Metal. Each run has its own
`work/macos-runs/<timestamp>/stdout.log` and a result receipt. The default limit is 60 seconds; only its own process
group is terminated on timeout. The runner's write isolation is covered by a game-free host test.
`--toolkit <tree>` selects a patched toolkit; its stamp must match the current patches and pinned revision.
`--check` configures and prints the Ninja plan without compiling. Always build through this script: it holds a
build lock, uses one compiler job, refuses low disk space and stops its own build if free memory falls below 15%.

Native limitations: there is no `.app` bundle or Mac installer yet. SDL3 gamepad-library loading is wired, but the
scripted runs used no physical controller. The Windows keyboard/mouse remapping and SendInput scripts are unavailable; use a
controller for eventual game testing. Display/settings persistence, prompt-font replacement and D3D12-specific
options are not validated on Mac. The GUI session-log recorder remains Windows-only; native stdout/stderr can be
redirected to a file. No playability or performance claim is made by the synthetic smoke.

## Building on Windows

**Status: the installer and portable first-run build are tested; a source-tree build by hand is not.** The bundled
compiler translated and built the game in a Windows 10 virtual machine with no GPU (6 cores, 8 GB of memory) on
2026-10-27 and again on 2026-10-28, producing `kz2.exe` in 18.6 minutes with 2 jobs. A contributor also completed the
portable route and two native start-up smokes on Windows 11 on 2026-11-12, described below. Maintainer play testing
is under Proton on Linux; players report native Windows 11 play in issue #13.

1. **The installer or portable zip (recommended):** it does the lift and build on Windows without WSL2 or Nix (see
   the top of this page). From an unpacked portable zip, `run.cmd` accepts the three game paths as defaults for its
   normal interactive check and build, which makes a test run reproducible:

   ```powershell
   .\run.cmd `
     --dump "E:\PS3\Killzone 2.iso" `
     --update "D:\RPCS3\dev_hdd0\game\BCUS98116" `
     --eboot "D:\RPCS3\dev_hdd0\game\BCUS98116\USRDIR\EBOOT.elf" `
     --rpcs3 "D:\RPCS3"
   ```

   Pick paths on your machine; the EBOOT is the separate decrypted 1.29 `EBOOT.elf`, not the update's encrypted
   `EBOOT.BIN`. On Windows 11 on 2026-11-12, a v0.1.12 portable payload with the Unreleased Lua receipt fix completed
   all seven steps in 665.2 seconds of recorded step time (about 668 seconds wall-clock). It selected 15 compiler
   jobs, spent 187 seconds compiling and passed the final build check. The packaged `Project Pyrrhus.exe` launcher
   then kept a game window running for a 30-second smoke and both closed normally; a separate 90-second direct smoke
   selected an RTX 5070 and stayed running. No screenshot was taken, so these runs do not establish picture, audio or
   gameplay correctness. The resulting portable folder measured 13.9 GiB after the smokes; see
   [requirements](requirements.md#hardware-to-build-the-port-yourself).
2. **Build on Linux, run on Windows (untested).** Do the [Steps](#steps) 1 to 4 on a Linux
   machine. Copy `kz2.exe` and `at3_standalone.dll` (and, for movies, `avcodec-63.dll` and `avutil-61.dll` from
   [Movie decoders](#movie-decoders-ffmpeg-dlls)) into one folder, and your game folder (`PS3_GAME`, which holds
   the game's data and takes many gigabytes) to a Windows PC with a Direct3D 12 GPU, keeping the layout
   `PS3_GAME\USRDIR\...`. Put the decrypted `EBOOT-129.elf` in `PS3_GAME\USRDIR\` (beside the disc's own files) and, in a terminal
   in the folder with `kz2.exe`, run `kz2.exe .\PS3_GAME\USRDIR\EBOOT-129.elf`. Set `KZ2_UPDATE_DIR` to the update's `USRDIR` first.
3. **Build inside WSL2 (untested):** install WSL2 with Ubuntu (`wsl --install -d Ubuntu`), install Nix there with
   flakes enabled, give WSL2 at least 16 GB of memory in `%UserProfile%\.wslconfig`, keep the repository in the
   Linux file system (not under `/mnt/c`), link your dump from `/mnt/...` as in step 1, and run the Steps 1 to 4. Then
   copy the result to a Windows folder as in route 2. No one has run this on WSL2.

If a Windows route fails, open an issue with your Windows version, GPU and driver, how far it got, and the log.

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

The focused synchronization regression can also run with Python 3 and host C/C++ compilers:
`python3 tools/runtime/test_sync_mutex_semantics.py`. It finds the patched toolkit using `KZ2_PATCHED_DIR`,
`KZ2_OUT`, or the usual `work/` locations; `--toolkit <tree>` selects one explicitly. This test passed on macOS
with Apple Clang against the pinned toolkit plus the full patch series, and failed without patch 3010.
This validates the tested HLE contracts only; it does not validate a Mac build or a game run.

On Windows without Nix, the Python tests run with Python 3.12 (`python tools/release/test_....py`), and the shell
tests in `tools/` with Git Bash. All 38 `tools/release/test_*.py` files passed with Python 3.12.10 on native Windows
11 on 2026-11-12. The exception is the shell tests in `tools/spu/` and `tools/runtime/` that compile C test programs
against the runtime with the Nix shell's Linux compilers: they are Linux tests, run by CI, and are not expected to
pass on Windows.

## Which tools and which route

The port is built with a Nix flake and the patched [ps3recomp](https://github.com/sp00nznet/ps3recomp) it pins (release
v0.18.0 plus this project's patch set; `tools/ps3recomp-patched.sh` applies it); the
tested route is Linux with a Windows cross build run under Proton. The steps, the files you need and the
macOS and Windows notes: this page.

Forking or reusing this project (names, addresses, versions, what to change): [FORKING.md](FORKING.md).
