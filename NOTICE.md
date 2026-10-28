# Third-party components and credits

Every piece of code, patch, library or font that came from outside this repository is listed here with its author,
source, licence and what was used. Licence texts are in [licenses/](licenses/) and ship with every release (installer
and portable zip: `licenses\`). Per-patch credit is also in each header in `port/patches/` (a header names its source
where there is one). The port's own code is MIT ([LICENSE](LICENSE)).

## Toolkit

| Project | Author | Source | Licence | What was used |
|---|---|---|---|---|
| ps3recomp | Ned Heller (sp00nznet) and its contributors ([CONTRIBUTORS.md](https://github.com/sp00nznet/ps3recomp/blob/main/CONTRIBUTORS.md)) | <https://github.com/sp00nznet/ps3recomp> (submodule `third_party/ps3recomp`, pinned at release v0.18.0) | MIT ([licenses/ps3recomp-LICENSE.txt](licenses/ps3recomp-LICENSE.txt)) | the PPU/SPU recompiler, lifters, PS3 runtime and HLE libraries the port is built on; our changes are the patches in `port/patches/`, applied on top of that exact release; the build uses ps3recomp v0.18.0 plus this patch set, not a newer or older ps3recomp |

## Absorbed upstream PRs (ps3recomp pull requests by other authors)

Code or logic from these pull requests is used in our patches or, where they were merged, comes in with ps3recomp
itself. One row per author: the pull requests first, our patch numbers (`port/patches/`) in brackets. All are MIT, as
ps3recomp.

| Author | Pull requests [our patches] | What was used | Project and source | Licence |
|---|---|---|---|---|
| NoahBPeterson | [#287](https://github.com/sp00nznet/ps3recomp/pull/287), [#213](https://github.com/sp00nznet/ps3recomp/pull/213) and fork commits e68e567, b709a08, e3ab49d [1071, 1000-spu, 1074, 1055, 1056] | the exact per-element code for SPU extended-range single precision (#287; patch 1000-spu keeps our helpers over the rest of the PR); the per-SPU SPURS kernel with ready-count admission (#213, opt-in); the ideas behind the hashed HLE NID lookup and the striped lock-line lock with seqlock GETLLAR (fork commits; that code is our own) | ps3recomp and the fork [NoahBPeterson/ps3recomp](https://github.com/NoahBPeterson/ps3recomp) | MIT |
| tekulvw | [#303](https://github.com/sp00nznet/ps3recomp/pull/303), [#302](https://github.com/sp00nznet/ps3recomp/pull/302), [#304](https://github.com/sp00nznet/ps3recomp/pull/304), [#266](https://github.com/sp00nznet/ps3recomp/pull/266), [#283](https://github.com/sp00nznet/ps3recomp/pull/283), [#296](https://github.com/sp00nznet/ps3recomp/pull/296) [2055, 6014, 6015] | fragment colour inputs clamped before source modifiers, 2D depth-texture comparisons, framebuffer sRGB output for half exports (patch 2055 keeps the D3D12 call site), the SPU interpreter fallback (#302-#304 are in ps3recomp's CONTRIBUTORS.md, so in v0.17.0); the `cellSpursTaskExitCodeInitialize` contract (#283; written independently, then dropped for upstream's); the `sys_memory_allocate` and `sys_mmapper_allocate_address` address ranges (#296, in v0.17.0; patch 6015 rebased around it) | ps3recomp | MIT |
| erikomis | [#313](https://github.com/sp00nznet/ps3recomp/pull/313), [#334](https://github.com/sp00nznet/ps3recomp/pull/334), [#489](https://github.com/sp00nznet/ps3recomp/pull/489) [2080, 9489] | SPU decrementer ticks that no longer overflow after about 231 s (#313, in v0.17.0); the row-at-a-time unscaled NV3089 blit (#334, adapted in patch 2080); a guest callback stack per host thread (#489, backported as patch 9489 with slot reuse added, and in the test tools/runtime/test_guest_call_stack.cpp) | ps3recomp | MIT |
| n0madic | [#501](https://github.com/sp00nznet/ps3recomp/pull/501) [9501] | depth texture formats present their one channel on every crossbar source (written from the PR description, backported as patch 9501) | ps3recomp | MIT |
| JonathanDC64 | [#47](https://github.com/JonathanDC64/ps3recomp/pull/47) [2085] | the reserved-bits rule for `SET_COLOR_MASK`, narrowed to a counter plus an opt-in switch | fork [JonathanDC64/ps3recomp](https://github.com/JonathanDC64/ps3recomp) | MIT |
| robbe1912 | commit 0d03c8b5 [2057] | the fragment decoder's third-source absolute modifier | [robbe1912/ps3recomp](https://github.com/robbe1912/ps3recomp) (from the MotorStorm: Monument Valley port) | MIT |
| MaChInEgUn3 | [#379](https://github.com/sp00nznet/ps3recomp/pull/379) [6013] | the cellVdec forwarders (in v0.17.0; patch 6013 dropped its own Vdec half for them) | ps3recomp | MIT |
| feanor-noldorin | [#456](https://github.com/sp00nznet/ps3recomp/pull/456) [4017] | cellFs repositions the stream when a file switches between reading and writing (via the Killzone 3 port's patch), and the link stubs in our cellFs host test | ps3recomp | MIT |
| undecuple (this project's author) | [#253](https://github.com/sp00nznet/ps3recomp/pull/253), [#254](https://github.com/sp00nznet/ps3recomp/pull/254), [#277](https://github.com/sp00nznet/ps3recomp/pull/277), [#309](https://github.com/sp00nznet/ps3recomp/pull/309), [#310](https://github.com/sp00nznet/ps3recomp/pull/310), [#323](https://github.com/sp00nznet/ps3recomp/pull/323) [3003, 3005, 0003, 7001, 5003] | our own fixes, merged upstream and part of v0.17.0; the listed patches are rebased around them (headers name the PR) | ps3recomp | MIT |

## Other ports' patches

| Project | Author | Source | Licence | What was used |
|---|---|---|---|---|
| Project Helghast (the Killzone 3 PC port) | undecuple (the same author as this project) | [undecuple/project-helghast](https://github.com/undecuple/project-helghast) | MIT (Copyright (c) 2026 undecuple) | the runtime, SPU, RSX/D3D12 and pad patches 0001-5004 in `port/patches/` (headers carry "From KZ3 <commit>"), the split disc archive reader in patch 6034 and its test, the disk cache stamp in patch 6035 (`port/kz2/kz2_fios_stamp.h`) and the window icon in patch 2123, the per-tick message pump in `port/kz2/main.cpp`, the lift/build/installer tooling (including the ISO 9660 reader `tools/release/iso9660.py`), the art and website generators and the AGENTS.md guide, adapted for Killzone 2 |
| A Ratchet & Clank PC port (not public yet) | undecuple (the same author as this project) | not public yet | MIT (Copyright (c) 2026 undecuple) | lv2 mutex and condition-variable rules (R&C patch 7007), adapted in [6027] |

## Libraries

| Library | Author | Source | Licence | What was used |
|---|---|---|---|---|
| SDL3 | Sam Lantinga and the SDL contributors | <https://libsdl.org/> | zlib ([licenses/SDL3-LICENSE.txt](licenses/SDL3-LICENSE.txt)) | gamepads (DualShock 4, DualSense, Switch Pro, Xbox) and rumble: `SDL3.dll` is shipped unmodified next to the game's exe (an unmodified mingw-w64 build of SDL 3.4.x) |
| llvm-mingw (clang, lld, LLVM, MinGW-w64, winpthreads), CMake, Ninja, Python (embeddable) | the respective projects | pinned with SHA-256 in `tools/release/toolchain.json` | Apache-2.0 with LLVM exception, ZPL-2.1, MIT/BSD-3-Clause, ISC, BSD-3-Clause, Apache-2.0, PSF-2.0 | the build tools the installer downloads on the player's machine for the first-run build; their licence texts are fetched with them and shipped under `licenses\<component>\` |
| ATRAC3 / ATRAC3+ decoder (`third_party/at3_standalone` in ps3recomp) | FFmpeg: Maxim Poliakovski, Benjamin Larsson, Fabrice Bellard, Michael Niedermayer, Loren Merritt and the FFmpeg developers; extracted as a standalone decoder by the PPSSPP project | <https://ffmpeg.org/> by way of [PPSSPP](https://github.com/hrydgard/ppsspp) `ext/at3_standalone`, commit ebc151f | LGPL-2.1-or-later ([licenses/LGPL-2.1.txt](licenses/LGPL-2.1.txt)) | decoding of the game's ATRAC3/ATRAC3+ audio. Built unmodified as `at3_standalone.dll` beside `kz2.exe`, which links it dynamically; replaceable by a rebuilt copy; its source is the unmodified directory in ps3recomp (`third_party/ps3recomp/third_party/at3_standalone`); the rest of the port stays MIT |
| FFmpeg libavcodec and libavutil (`avcodec-63.dll`, `avutil-61.dll`) | the FFmpeg developers | <https://ffmpeg.org/>, version 9.0.1 (git tag n9.0.1); the exact source and build options ship as `licenses/FFmpeg-SOURCE.txt` and `licenses/FFmpeg-LICENSE-build.txt`, with the licence text as `licenses/FFmpeg-COPYING.LGPLv2.1.txt` | LGPL-2.1-or-later ([text](licenses/LGPL-2.1.txt)) | decoding of the game's H.264 movies and AC3 surround audio. Built unmodified, LGPL-only (no GPL or non-free parts, H.264, MPEG-2 and AC3 decoders only), and loaded at run time from separate DLLs beside `kz2.exe`, so they can be replaced by a rebuilt copy; the rest of the port stays MIT |
| Mesa/nouveau `nv40_3d.xml.h` (RSXGL's copy) | Mesa and nouveau contributors; RSXGL: Alexander Betts | <https://gitlab.freedesktop.org/mesa/mesa> | MIT/X11 | the COLOR_MASK byte layout, read as a fact for a comment in patch 2031; no code is copied |

## Fonts

| Font | Author | Source | Licence | What was used |
|---|---|---|---|---|
| Rajdhani | Indian Type Foundry | <https://fonts.google.com/specimen/Rajdhani> (github.com/google/fonts, `ofl/`) | SIL Open Font License 1.1 ([licenses/Rajdhani-OFL.txt](licenses/Rajdhani-OFL.txt)) | rendered into the installer's wizard images and icons (`installer/art/`) and the README banner and social preview (`assets/`, made by `tools/release/installer_art.py`); Rajdhani Bold is embedded in the installer for its headings (the installer's own process only); Rajdhani Medium and Bold ship in `fonts\` of the installed folder and the portable zip, with the OFL text in `fonts\OFL.txt` and `licenses\Rajdhani-OFL.txt`; the game loads them for its on-screen button-prompt labels (its own process only). No other font file is bundled |

## Read only, not used as code

| Source | Use | Licence |
|---|---|---|
| [RPCS3](https://github.com/RPCS3/rpcs3) | reference for PS3 behaviour, read only; no RPCS3 code is included | GPL-2.0, not used as code |
| [RPCS3 wiki](https://wiki.rpcs3.net/index.php?title=Killzone_2) | facts about the game's behaviour under emulation (settings, known issues) | CC BY-SA 4.0, facts only |

Killzone and Killzone 2 are trademarks of Sony Interactive Entertainment. This project is not affiliated with or
endorsed by Sony Interactive Entertainment or Guerrilla Games. The names are used only to say which game the port runs;
no logos or other marks are used.

**No game content is distributed.** This repository contains no part of the game: no disc files, no decrypted or
translated game code, no assets and no keys. Players supply their own copy of the game; the game's code is translated
and compiled on the player's own machine from their own files. Screenshots of the port running (docs/screenshots/, listed in [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md)) show
the game's imagery, © Sony Interactive Entertainment, only to document the port; they come from the developer's own
copy of the game.

The MIT licence in LICENSE covers the port's own source code, tools and documentation only. It grants no rights to
Killzone 2 or any other software, data or trademark of Sony Interactive Entertainment or Guerrilla Games.

## Rights holders

- **No circumvention tools.** This repository and its releases ship no decryption or copy-protection circumvention
  tools, no keys and no instructions for decrypting game files. The port only reads a decrypted EBOOT that players
  make themselves from their own copy of the game.
- **Contact.** If you hold rights in material you believe is in this repository, report it privately through this
  repository's *Security* tab (*Report a vulnerability*). We review every report promptly and remove anything
  identified as infringing while it is checked.
- **Formal notices** under the DMCA go to GitHub as described in
  [GitHub's DMCA Takedown Policy](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy).

## References and thanks

Facts recovered for this port are checked against the game binary; these public sources helped find and explain them.
Nothing from them is copied into this repository.

- **recomp.board** (<https://recomp.fyi>): a community index of recompilation projects; this one is listed through the
  `.recomp.json` in the repository root.
- **PS3 Developer Wiki** (<https://www.psdevwiki.com/ps3/>), its contributors: formats, system calls and ticket layouts.
- **sagemono**: the archive of Sony's GPL PS3 toolchain source packages (<https://github.com/sagemono/ps3gcc>).
- **Guerrilla Games' conference talks**: Michal Valient, "Rendering Technology of Killzone 2" (GDC 2009) and "Deferred
  Rendering in Killzone 2" (Develop 2007); Michiel van der Leeuw, "The PlayStation 3's SPUs in the Real World: a
  Killzone 2 Case Study" (GDC 2009).
- **IBM, Sony Computer Entertainment and Toshiba**: the public Cell Broadband Engine documentation (architecture, PPU
  and SPU ABIs, SPU instruction set, language extensions).
- **RSXGL** (Alexander Betts) and the **nouveau** project's NV30/NV40 register database it carries: RSX method names
  and fields.

## Reuse and attribution (including AI and automated use)

This notice is for people, and for AI systems, crawlers, dataset builders and code-generation tools that read, index,
summarise, train on or reproduce this repository.

- **Licence:** the port's own code, tools and documentation are MIT ([LICENSE](LICENSE)). The MIT terms apply to
  automated use exactly as to any other: copies or substantial portions, including code an AI model reproduces from
  this repository, must include the copyright notice "Copyright (c) 2026 undecuple" and the MIT permission notice.
- **The name:** "Pyrrhus" is the name of the game's own city; "Project Pyrrhus" names this fan project only and is not
  affiliated with or endorsed by Sony Interactive Entertainment or Guerrilla Games.
- **Attribution we ask for:** name the source as "Project Pyrrhus by undecuple" with a link to
  <https://github.com/undecuple/project-pyrrhus>, in documentation, answers, summaries or derived projects that use its
  code, patches, findings or write-ups.
- **Keep the licence with the code:** do not present code from here as unlicensed, public domain or your own, and do
  not relicense it without keeping the MIT notice.
- **Third-party parts keep their own terms:** ps3recomp (MIT, its authors) and the components listed above.
- **Not covered by any licence here:** Killzone 2 itself. This repository contains no game code, data or assets;
  nothing here grants rights to them, and recovered names, numbers or formats are documented for interoperability.
- **Accuracy:** findings are dated and marked as verified, assumed or open in the docs; do not restate an
  `ASSUMPTION:` as fact.
