# Requirements

What you need to play and to build Project Pyrrhus. The game does not run at full speed yet (about 20-35 frames per
second in the first level on the machines tried, the PS3 runs it at 30) and hand play is not measured, so every
hardware figure below is provisional: a measurement is named as one, anything else is an estimate. Measured values
replace the estimates as they come in.

## What you need from your own copy of the game

| Item | Required | Details |
|---|---|---|
| **Operating system** | yes | Windows 10 or 11, 64-bit. Tested by us under Proton on Linux; players report playing on native Windows 11 (issue #13). |
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
| **Disk space** | about 12 GB free beyond the disc dump (estimate) | the same, on an SSD | The install copies the disc's game files, about 7 GB (the game archive is about 6.5 GiB); the installed program and the first-run build folder come to roughly 3 GB (estimate, see the build table). The game's own disk cache after 60 s of start-up was 7 MB (measured 2026-10-29); its growth during a level is not measured |
| **Operating system** | Windows 10 64-bit, or Linux with a current Proton | Windows 11 | Windows 11 native: players' sessions (issue #13). Proton on Linux: our runs. Windows 10: the first-run build ran in a virtual machine without a GPU (2026-10-27 and 2026-10-28); the game has not been played there |
| **Controller** | a keyboard (the default key layout; no mouse look yet) | a gamepad | A DualShock 4, including motion, was hand-tested on 2026-10-22; keyboard-only play was used in issue #13 |

Current measured performance (the figures are scripted or logged runs, none is hand play, and hand play is not measured):

- **Our runs, RTX 4060 class GPU under Proton, 2026-10-29:** scripted turn-and-walk windows on Corinth Sands: the
  median over six pairs of runs was 30.75 fps with the older defaults and 32.62 fps with the newer native paths, single runs
  22-44 fps (one run that shared the machine with a heavy job gave 9.6), frame times at the 99th percentile 38-73 ms. An earlier, longer scripted run (330 s of the first level, 2026-10-22, before the native post-processing) gave 23.3 fps.
- **A player, native Windows 11, RTX 4070 Laptop (issue #13):** 21-28 fps in the first part of Corinth River, 26.6-28.5 fps in the
  steadiest stretch, 33.4 fps over the whole 150 s session including menus. The menus run at 60 fps.
- **A player, handheld (ROG Xbox Ally X):** 19.6 fps at 1983 MHz, 34.9 fps with boost, GPU 15-22 %. A report, not our measurement.
- **A video review on an RTX 4090** (a re-encoded recording, indicative only): roughly 27-29 new frames per second.
- **Memory (ours, same run kind):** peak resident size 4.1 GiB in a 60 s start-up, sampled every 2 s from the host (2026-10-29).

## Hardware to build the port yourself

The installer (and the portable zip) lifts and compiles the game's own code on your machine at first run; this is the
same step when you build from the source by hand. Building needs more than playing:

| | Minimum (estimate) | Recommended (estimate) | Basis |
|---|---|---|---|
| **RAM** | 8 GB, with 2 compiler jobs | 16 GB or more | The first-run build ran in a Windows 10 virtual machine with 6 cores and 8 GB of memory and 2 jobs and finished in 18.6 minutes (2026-10-27 and 2026-10-28, no GPU). On a 32 GB laptop with 6.4 GiB free the installer chose 3 jobs and finished in 20.9 minutes (issue #13). A source chunk can need well over 1 GB to compile, so the job count follows the free memory |
| **CPU / time** | 6 cores; about 20 minutes (18.6 and 20.9 minutes measured) | 8 or more cores and enough free memory for more jobs |  Same two runs (the 20.9 minute one used 3 jobs on a 16-core laptop). Its steps: check 6.8 s, load 31.5 s, PPU lift 56.7 s, SPU lift 66.7 s, configure 5.6 s, compile 1085 s, stamp 1.7 s (issue #13) |
| **Disk** | about 5 GB free beyond the game (estimate) | 10 GB, SSD | The finished `kz2.exe` is 229 MB in the installed build (issue #13). A by-hand Linux cross build measured 2.4 GB for the whole build folder with a 1.1 GB exe (2026-10-29) and the build tree took about 2.7 GB earlier (BUILDING.md); the Windows installer's own folder was not measured |
| **OS** | Windows 10 or 11 for the installer; Linux with Nix for the by-hand build | same | The installer carries its own compiler. By-hand builds on Linux are in BUILDING.md |

