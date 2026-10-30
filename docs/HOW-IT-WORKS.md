# How it works

## What kind of port is this?

"Recomp" covers a wide range: from an emulator's work done ahead of time up to a full rewrite. This port is a static
recompilation with a runtime layer, plus native replacements where they matter. By part, today:

| Part | How it runs today |
|---|---|
| PPU game code | recompiled ahead of time to C, compiled for x64 |
| SPU programs and jobs | recompiled ahead of time; SPURS scheduling and DMA are reproduced by the runtime. Native C by default: the Edge zlib decompression job (`KZ2_NATIVE_ZLIB=0` runs the recompiled job instead), the depth-of-field post job (`KZ2_NATIVE_JOB_DOF=0`), and the rest of the post-processing chain on the kernels checked against inputs recorded in play (upsample, blur, bloom, modulate, vignette and others; each has its own `KZ2_NATIVE_JOB_*` switch). Each native job gives the same output bits as the recompiled one on the tested inputs. Two animation kernels and the particle vertex job's start-up are native too, but off by default until they are shown to be faster |
| Graphics | **translated at run time**: the game's RSX command stream is replayed on Direct3D 12, shaders translated from RSX microcode (the same kind of work an emulator's GPU layer does) |
| Memory | the PS3's big-endian layout, kept as the recompiled code expects it |
| System libraries (lv2, cell*) | reimplemented on PC APIs (high-level emulation) |
| Audio output, files, saves | native PC APIs |
| Input | native: SDL3 gamepads (XInput without the SDL3 library) and the keyboard; no mouse look yet |
| Movies | decoded by FFmpeg (LGPL, built as separate libraries) |

It is not a decompilation: the game's logic is the recompiled original, not rewritten source, and the repository
holds none of it (everything is built on your PC from your own copy). Ahead-of-time recompilation is not faster by
itself; what it gives is a single PC program, hooks for fixes and PC features, and no emulator to set up. The plan
after the game is playable is to replace the run-time layers with native code step by step where it pays off: more
native SPU jobs first ([roadmap](ROADMAP.md)).

Building it yourself: [BUILDING.md](BUILDING.md). Known problems: [KNOWN_ISSUES.md](KNOWN_ISSUES.md).
