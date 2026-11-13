# Requirements

What you need to play and to build Project Pyrrhus. The game does not run at full speed yet (about 20-35 frames per
second in the first level on the machines tried, the PS3 runs it at 30) and hand play is not measured, so every
hardware figure below is provisional: a measurement is named as one, anything else is an estimate. Measured values
replace the estimates as they come in.

## What you need from your own copy of the game

| Item | Required | Details |
|---|---|---|
| **Operating system** | yes | Windows 10 or 11, 64-bit. Tested by us under Proton on Linux; players report playing on native Windows 11 (issue #13). A contributor completed the portable first-run build and native start-up smokes on Windows 11 on 2026-11-12; no screenshot was taken, so that run did not check the picture. |
| **Graphics card** | yes | A GPU with Direct3D 12 support. |
| **Killzone 2 disc dump** | yes | Your own copy of the US disc (BCUS98116), dumped to a folder or a decrypted ISO file (an encrypted ISO is refused); a FAT32 dump with the disc archive in parts is accepted as it is. Other title ids are refused, naming the id found; the Killzone Trilogy disc (its Killzone 2 is BCUS98116, disc version 02.00) is accepted as untested ([what each input must contain](GETTING-FILES.md)). |
| **Update 1.29** | yes | The game's last update, from your own console or copy. |
| **Decrypted EBOOT** | yes | The game's main program (EBOOT.elf), decrypted, made from your own copy. This project ships no decryption tools or instructions. |

## Hardware to play

A native Windows x64 program using Direct3D 12. Tested under Proton on Linux and, by players, on native Windows 11 (issue #13).
On the machines tried so far the game appears to be limited mostly by the processor, so the CPU row likely matters most; the graphics card matters too (issue #13's integrated GPU ran slower than its discrete one, though with a cold shader cache, so not like for like).

| | Minimum (estimate) | Recommended (estimate) | Basis |
|---|---|---|---|
| **CPU** | x86-64 with AVX and FMA3 (Intel Haswell or AMD Piledriver, about 2013, and newer; checked at start-up), 6 cores, about 3.5 GHz sustained | 8 or more cores, 4 GHz or more sustained, a recent desktop or laptop part | AVX and FMA3 are checked when the program starts. Speed follows the clock: a player's handheld (ROG Xbox Ally X) gave 19.6 fps at 1983 MHz and 34.9 fps at 3697 MHz with CPU boost, with the GPU only 15-22 % busy (a player's report, not our measurement). The core counts are an estimate: the PS3's main processor and its six SPUs run as host threads, and no run on fewer than 6 cores has been played |
| **Memory** | 8 GB (estimate) | 16 GB (estimate) | Measured 2026-10-29 under Proton: the game process reached 4.1 GiB resident (4.3 GB) within a 60 s start-up to the menus, 3.5 GiB of it from the first seconds, and was still growing at the end; a longer session and a level were not measured. 8 GB leaves little room for Windows and the game; 16 GB is the safe size (estimate) |
| **Graphics card** | Direct3D 12 (an integrated GPU runs, slowly) | a discrete Direct3D 12 GPU of the RTX 4060 / RTX 4070 Laptop class (8 GB), driver current | RTX 4060 (our scripted Proton runs, 2026-10-29) and RTX 4070 Laptop (a player's native Windows 11 session, issue #13) both reach the rates below. The same laptop's Intel Arc integrated GPU, with a cold shader cache, gave 10-22 fps in the level (issue #13; the cache differs, so not like for like). Video memory use was not measured. AMD GPUs are untested |
| **Disk space** | about 15 GB free beyond the disc dump | 20 GB, on an SSD | A native portable first-run build measured 13.9 GiB after two start-up smokes (2026-11-12): 12.1 GiB copied game data, 1.1 GiB build, 0.47 GiB toolchain and 0.25 GiB VFS/cache. The earlier 12 GB estimate counted the 6.5 GiB game archive but not all other disc files. A level's cache growth is not measured |
| **Operating system** | Windows 10 64-bit, or Linux with a current Proton | Windows 11 | Windows 11 native: players' sessions (issue #13). Proton on Linux: our runs. Windows 10: the first-run build ran in a virtual machine without a GPU (2026-10-27 and 2026-10-28); the game has not been played there |
| **Controller** | a keyboard and mouse (the default key layout and mouse look) | a gamepad | A DualShock 4, including motion, was hand-tested on 2026-10-22; keyboard-only play was used in issue #13 |

Current measured performance (the figures are scripted or logged runs, none is hand play, and hand play is not measured):

- **Our runs, RTX 4060 class GPU under Proton, 2026-10-29:** scripted turn-and-walk windows on Corinth Sands: the
  median over six pairs of runs was 30.75 fps with the older defaults and 32.62 fps with the newer native paths, single runs
  22-44 fps (one run that shared the machine with a heavy job gave 9.6), frame times at the 99th percentile 38-73 ms. An earlier, longer scripted run (330 s of the first level, 2026-10-22, before the native post-processing) gave 23.3 fps.
- **A player, native Windows 11, RTX 4070 Laptop (issue #13):** 21-28 fps in the first part of Corinth River, 26.6-28.5 fps in the
  steadiest stretch, 33.4 fps over the whole 150 s session including menus. The menus run at 60 fps.
- **A player, handheld (ROG Xbox Ally X):** 19.6 fps at 1983 MHz, 34.9 fps with boost, GPU 15-22 %. A report, not our measurement.
- **A video review on an RTX 4090** (a re-encoded recording, indicative only): roughly 27-29 new frames per second.
- **Memory (ours, same run kind):** peak resident size 4.1 GiB in a 60 s start-up, sampled every 2 s from the host (2026-10-29).
- **A contributor, native Windows 11 and RTX 5070, 2026-11-12:** a 90 s start-up at the main-menu page stayed
  running and reached 1.39 GiB peak working set. This was a process and renderer smoke only: no screenshot was taken,
  so it is not a picture or gameplay measurement.

## Hardware to build the port yourself

The installer (and the portable zip) lifts and compiles the game's own code on your machine at first run; this is the
same step when you build from the source by hand. Building needs more than playing:

| | Minimum (estimate) | Recommended (estimate) | Basis |
|---|---|---|---|
| **RAM** | 8 GB, with 2 compiler jobs | 16 GB or more | The first-run build ran in a Windows 10 virtual machine with 6 cores and 8 GB of memory and 2 jobs and finished in 18.6 minutes (2026-10-27 and 2026-10-28, no GPU). On a 32 GB laptop with 6.4 GiB free the installer chose 3 jobs and finished in 20.9 minutes (issue #13). A native Windows 11 run with 18.9 GiB available chose 15 jobs; its peak build memory was not measured. A source chunk can need well over 1 GB to compile, so the job count follows the free memory |
| **CPU / time** | 6 cores; about 20 minutes (18.6 and 20.9 minutes measured) | 8 or more cores; about 10-20 minutes, depending on available memory | The 20.9 minute run used 3 jobs on a 16-core laptop; its steps were check 6.8 s, load 31.5 s, PPU lift 56.7 s, SPU lift 66.7 s, configure 5.6 s, compile 1085 s and stamp 1.7 s (issue #13). A Ryzen 7 9800X3D native run used 15 jobs and took about 668 s total, including 187 s to compile (2026-11-12) |
| **Disk** | about 15 GB free beyond the source dump for the installer or portable zip | 20 GB, SSD | The native portable folder measured 13.9 GiB after a full build and start-up smokes: 12.1 GiB game copy, 1.1 GiB build, 0.47 GiB toolchain and 0.25 GiB VFS/cache (2026-11-12). Its `kz2.exe` was 226 MiB. A by-hand Linux cross build measured 2.4 GB for the build folder with a 1.1 GB exe (2026-10-29) |
| **OS** | Windows 10 or 11 for the installer; Linux with Nix for the by-hand build | same | The installer carries its own compiler. Its first-run build completed on native Windows 10 and 11. By-hand builds on Linux are in BUILDING.md |
