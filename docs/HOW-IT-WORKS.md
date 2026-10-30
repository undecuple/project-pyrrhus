# How it works

## What kind of port is this?

"Recomp" covers a wide range: from an emulator's work done ahead of time up to a full rewrite. This port is a static
recompilation with a runtime layer, plus native replacements where they matter. By part, today:

| Part | How it runs today |
|---|---|
| PPU game code | recompiled ahead of time to C, compiled for x64 |
| SPU programs and jobs | recompiled ahead of time; SPURS scheduling and DMA are reproduced by the runtime. Native C by default: the Edge zlib decompression job (`KZ2_NATIVE_ZLIB=0` runs the recompiled job instead), the depth-of-field post job (`KZ2_NATIVE_JOB_DOF=0`), and the rest of the post-processing chain on the kernels checked against inputs recorded in play (upsample, blur, bloom, modulate, vignette and others; each has its own `KZ2_NATIVE_JOB_*` switch). Each native job gives the same output bits as the recompiled one on the tested inputs. Also native by default: the animation job's decoder and keyframe sampler (`KZ2_NATIVE_JOB_EDGEANIM=0` turns them off) and the particle vertex job's start-up clear (`KZ2_NATIVE_JOB_VJCLEAR=0`), measured 15-22 % and 3-11 % cheaper per job run in scripted runs. The particle vertex job's copy routine is native by default too (`KZ2_NATIVE_JOB_VJCOPY=0` turns it off), measured 6 % cheaper per job run alone and 10 % with the clear |
| Graphics | **translated at run time**: the game's RSX command stream is replayed on Direct3D 12, shaders translated from RSX microcode (the same kind of work an emulator's GPU layer does) |
| Memory | the PS3's big-endian layout, kept as the recompiled code expects it |
| System libraries (lv2, cell*) | reimplemented on PC APIs (high-level emulation) |
| Audio output, files, saves | native PC APIs |
| Input | native: SDL3 gamepads (XInput without the SDL3 library), the keyboard, and raw-input mouse look (checked in scripted runs only) |
| Movies | decoded by FFmpeg (LGPL, built as separate libraries) |

It is not a decompilation: the game's logic is the recompiled original, not rewritten source, and the repository
holds none of it (everything is built on your PC from your own copy). Ahead-of-time recompilation is not faster by
itself; what it gives is a single PC program, hooks for fixes and PC features, and no emulator to set up. The plan
after the game is playable is to replace the run-time layers with native code step by step where it pays off: more
native SPU jobs first ([roadmap](ROADMAP.md)).

Building it yourself: [BUILDING.md](BUILDING.md). Known problems: [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## In short

**What this is:** a static recompilation. It runs the game's own code, with the PPU and SPU programs recompiled ahead
of time to native x64. It is **not an emulator** (no CPU emulator runs at play time) and **not a rewrite** (the game's
logic is not reimplemented). Around that code, the PS3's system libraries and hardware behaviour are reimplemented
on PC APIs.

An unofficial port of **Killzone 2** (PS3, 2009) to Windows x64, built on your PC from your own copy of the game. The
game's PowerPC (PPU) and Cell SPU code is translated to C++ ahead of time with
[ps3recomp](https://github.com/sp00nznet/ps3recomp) (the build pins ps3recomp v0.18.0 plus this project's own patch
set in `port/patches/`) and compiled into a native Windows program, so no CPU emulator runs at play time. The PS3 system libraries are reimplemented on PC APIs. The hardware around the code is still
provided by a runtime layer, much as an emulator provides it: the game's GPU command stream is meant to be replayed on
Direct3D 12, and SPU scheduling, DMA and the PS3's memory layout are reproduced. It is tested under Proton on Linux.

- **PPU:** the game's PowerPC functions are lifted to C++ by ps3recomp's lifter and compiled with MinGW-w64.
- **SPU:** the embedded SPU programs are lifted the same way; SPURS runs on host threads.
- **Graphics:** the game's RSX command stream is replayed on Direct3D 12, as in Project Helghast (in progress; the
  first level is drawn, and speed is the open problem).
- **Data:** the game reads its own archive in place through its file system library; the 1.29 update's added archive
  and patch files are layered over the disc data as on the PS3 (in progress).

General fixes found here are offered to ps3recomp upstream.
