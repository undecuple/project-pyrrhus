# Instructions for AI coding agents

Read this before changing anything in this repository. It applies to every automated contributor (Claude Code, Codex, Copilot,
Cursor and the like) and to the people who run them. Human contributors: the same rules
are in [CONTRIBUTING.md](.github/CONTRIBUTING.md).

Adapted from the same file in [Project Helghast](https://github.com/undecuple/project-helghast), the Killzone 3 port
by the same author (MIT).

## The project

Project Pyrrhus is an unofficial PC port of Killzone 2 (PS3, US disc BCUS98116, version 1.01, with the 1.29 update) made
by **static recompilation**: the game's PPU and SPU code is lifted to C++ ahead of time with
[ps3recomp](https://github.com/sp00nznet/ps3recomp), compiled into a Windows x64 program, and the PS3 system software
it calls is reimplemented; graphics go through Direct3D 12. The repository holds only the port. Each player lifts and
builds the game's code from their own copy of the game. Overview: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).
Status: [docs/FEATURES.md](docs/FEATURES.md), [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md),
[docs/RELEASE-CRITERIA.md](docs/RELEASE-CRITERIA.md).

## Repository map

| Path | What it holds |
|---|---|
| `port/kz2/` | the program: `main.cpp`, HLE overrides (`hle_kz2.cpp`, `stubs.cpp`), PPU function overrides (`kz2_ppu_overrides.cpp`, `ppu_overrides.txt`, `ppu_overrides-101.txt`), menu pages and prompts, pad layout, session log, CPU check |
| `port/patches/` | numbered patches to ps3recomp (see "Rules for everyone" for the number blocks) |
| `port/cmake/` | the MinGW-w64 and llvm-mingw toolchain files |
| `third_party/ps3recomp/` | the recompiler, a pinned submodule (never edited in place) |
| `tools/` | lift, build and run scripts (`lift.sh`, `build-kz2.sh`, `ps3recomp-patched.sh`, `sandbox.sh`, `proton-test.sh`, `safe_rm.sh`), data tools (`psarc.py`, `elf_info.py`, `disc_info.py`, `core.py`, `rtti_dump.py`) |
| `tools/spu/` | the SPU lifter (`lift_spu.sh`, `lift_spu.py`) and its host tests |
| `tools/release/` | first-run build, launcher, portable zip, installer payload and page generators, and their host tests (`ci_host_tests.sh` runs them) |
| `tools/assets/`, `tools/runtime/` | the save-profile editor and its test; the PSO template reader and the FFmpeg decoder build |
| `installer/` | the Inno Setup installer script and its art |
| `re/` | tables the tools read (`wws_jobs_v101.tsv`, `wws_jobs_v129.tsv`); numbers and names only |
| `site/`, `assets/` | the project web page source; banner and social-preview images |
| `docs/` | public documentation: `BUILDING.md`, `GETTING-FILES.md`, `requirements.md`, `FORKING.md`, `KNOWN_ISSUES.md`, `RELEASE-CRITERIA.md`, `ACCESSIBILITY.md`, `SCREENSHOTS.md`, `FEATURES.md` |
| `CHANGELOG.md` | what each release contains, newest first |
| `flake.nix` | the Nix shells (`default`, `re`, `win`) and their pinned inputs |

## Rules for everyone

- **No game material, ever.** Never commit, attach, paste, request or link to: files from the disc or the update,
  decrypted binaries (`EBOOT.elf`, SPU images), lifted or decompiled game code (`work/recomp/`, `work/spu/`),
  extracted assets, saves, keys or firmware. Numbers, names, structure layouts and formulas recovered from the game
  are fine. `Game/` and `work/` stay out of git (`.gitignore`); do not weaken it.
- **No circumvention.** The repository ships no decryption or copy-protection circumvention tools, no keys and no
  instructions for decrypting game files. Do not add any, and do not explain how to make the decrypted EBOOT; the
  docs only say what the player must have ([docs/GETTING-FILES.md](docs/GETTING-FILES.md)).
- **ps3recomp stays pristine.** Never edit `third_party/ps3recomp/` or move the pin as part of a fix. Every change
  to it is a new numbered patch in `port/patches/`, in its area's number block, applied by
  `tools/ps3recomp-patched.sh` (which fails on a patch that does not apply). The blocks: `0xxx` general (loader, VFS
  hook), `1xxx` SPU and SPURS, `2xxx` graphics (RSX, Direct3D 12), `3xxx` lifter and system libraries, `4xxx` network
  gate, HTTP, pad and file system, `5xxx` data, update and trophies, `6xxx` fixes found while bringing the port up,
  `7xxx` SPU and SPURS fixes. Take the next free number in the block; never renumber or reuse one.
- **No GPL code.** RPCS3 (GPL-2.0) may be read as a reference for behaviour and data layouts; never copy, translate
  or closely paraphrase its code. Write behaviour from your own understanding and say so in the change.
- **Gameplay stays original by default.** Mark features the PS3 game does not have `ENHANCEMENT:`; anything that
  changes gameplay is opt-in. Mark values not yet recovered from the binary `ASSUMPTION:` and never restate one as
  fact. Keep original function addresses in comments (`// @0x00123abc`).
- **Online is opt-in.** Nothing may contact the network unless the player chose it; a new connection must be named
  in the README's "What goes online" list.

## Licence, attribution and citation

- The port's code, tools and docs are MIT ([LICENSE](LICENSE)); ps3recomp is MIT; other components keep the terms
  listed in [NOTICE.md](NOTICE.md). Killzone 2 itself is covered by no licence here.
- A new dependency, bundled tool or font needs a licence compatible with MIT distribution and a row in NOTICE.md in
  the same change. No GPL code linked into the program.
- **Credit what you absorb.** Work taken from an upstream pull request, fork or other source is credited in the
  patch header, in [NOTICE.md](NOTICE.md) and in the commit message, for example
  `adapted from sp00nznet/ps3recomp PR #287 by NoahBPeterson`. Never remove or shorten existing credits.
- **Cite, do not paraphrase silently.** Facts taken from external references name their source next to the fact.
  Check a fact against the binary before relying on it.
- Citing the project: [CITATION.cff](CITATION.cff). Reuse terms for AI systems: NOTICE.md, "Reuse and attribution".

## Build and test

Wherever you work: **never write into the game dump**, and **keep the game's files out of the repository**. CI is the
gate for everyone: `.github/workflows/ci.yml` runs the full list. Build steps: [docs/BUILDING.md](docs/BUILDING.md).

- **Before every pull request** run what CI runs (needs no game data, no GPU): `nix flake check --no-build`,
  `nix develop .#re --command bash tools/ps3recomp-patched.sh`,
  `nix develop .#re --command python3 tools/release/fetch_toolchain.py --check --strict`,
  `nix develop .#re --command python3 tools/release/release_version.py --check`, and
  `bash tools/release/ci_host_tests.sh --gh --no-sandbox` (drop `--gh` outside Actions; it runs every line of
  `tools/host-tests.txt`, then every `tools/release/test_*.py` the list does not name). CI also scans the full history
  for secrets with gitleaks.
- **Host tests are self-contained.** A runtime fix comes with a focused host test that fails on the unpatched code and
  passes with the patch; list it in `tools/host-tests.txt`. A test builds from the patched ps3recomp alone, defines
  the runtime globals it needs, and prints SKIP (not FAIL) when it truly needs game data. When a patch changes what an
  old test checks, update that test in the same change.
- The target is the 1.29 update; the 1.01 disc is the base.
- Agents without the game can still work on the tools, patches with host tests, docs and the installer; say in the
  pull request that game runs were not done.

### The maintainers' setup (Linux with Nix; not a requirement)

How the maintainers run things; one way, not a requirement. Everything comes from the Nix flake; nothing is installed system-wide.

```sh
nix develop .#re     # analysis and lifting
nix develop .#win    # Windows x64 cross build (MinGW-w64, CMake, Ninja)
nix develop          # everything, plus Xvfb and steam-run for Proton runs
```

- **Anything that reads the game** runs inside `tools/sandbox.sh [--gpu] -- CMD` (game and repository read-only,
  only `work/` and `build/` writable, no network). The route is `tools/ps3recomp-patched.sh`, `tools/lift.sh`
  (PPU) and `tools/spu/lift_spu.sh` (SPU), then `tools/build-kz2.sh build/kz2-win`; it caps compiler jobs by free
  memory (a lifted chunk takes up to about 1.5 GB to compile); do not run `cmake --build -jN` on the lifted code.
- **Windows runs** on Linux go through `tools/proton-test.sh` (hidden Xvfb display, audio drivers off); output in
  `work/proton/NAME/app/app_stdout.txt`, a screenshot in `work/shots/NAME.png`. Look at the screenshot before you
  claim anything about the picture.

### Without Nix (for example native Windows)

- **Works with plain Python 3.11 or newer** (standard library only): the release tools and their tests, one file at
  a time, e.g. `python3 tools/release/test_firstrun.py`. Every `tools/release/test_*.py` passes with plain `python3`
  on Linux outside Nix; they have not been run on Windows.
- **The installer script** (`installer/kz2.iss`) needs Inno Setup to compile. That compile has only been run in the
  maintainers' setup.
- **Does not work without the flake toolchain:** the lift and the build (`ps3recomp-patched.sh`, `lift.sh`,
  `build-kz2.sh` are shell scripts that expect the Nix shells). Open the pull request and let CI build and test it, or
  say in the pull request what was not run. A native Windows build goes through the installer, which brings the
  patched toolkit and a bundled toolchain (`tools/release/fetch_toolchain.py`, `toolchain.json`; `firstrun.py` is the
  route it runs). Running `fetch_toolchain.py` and then `firstrun.py --root <checkout>` by hand is not tested from a
  checkout: `firstrun.py` looks for the patched toolkit in `work/ps3recomp-patched`, which only
  `tools/ps3recomp-patched.sh` makes.
- Keep the dump outside the repository and read-only; do not run anything that writes to it.

## Docs travel with code

- Update the docs a change affects in the same commit: build steps in `docs/BUILDING.md`, requirements in
  `docs/requirements.md`, the file checks in `docs/GETTING-FILES.md`, reuse notes in `docs/FORKING.md`, known
  problems in `docs/KNOWN_ISSUES.md`, credits and dependencies in `NOTICE.md`, and a line in `CHANGELOG.md` for
  anything a player would notice.
- `docs/FEATURES.md` is a generated page: do not edit it by hand. To change a feature's status, open an issue or say
  so in the pull request with the evidence (a run, a log line, a screenshot). A status changes only with evidence.
- Never write that something works unless you ran it, and say how. CI enforces the patch series, the manifests and
  the host tests; the rest is checked in review.
- Environment switches are documented where they are read (`getenv`), with their default.

## Commits and pull requests

- One topic per commit; short, plain, descriptive messages (what changed and why). Credits go in the message as
  above; no tool-generated footers or advertising lines.
- The pull request says what was run (host tests, a Proton run, a game build) and what was seen, and says if an AI
  tool helped write it. Use the templates in `.github/`.
- Never add personal paths, user names, tokens or other secrets; CI runs a secret scan on the full history.

## Fixes that belong upstream

A patch that is not specific to Killzone 2 (a lifter bug, a library that behaves differently from the PS3, a
runtime limit) is a candidate for [ps3recomp](https://github.com/sp00nznet/ps3recomp). Keep it free of anything
game-specific, with its focused test. Propose it there as an issue with symptom, cause, fix and test, and follow the
maintainer's lead on the pull request. The patch stays here until upstream takes it.

## Security and rights holders

- Report vulnerabilities privately ([SECURITY.md](.github/SECURITY.md)): GitHub's "Report a vulnerability" on the
  Security tab, never a public issue.
- Rights holders use the same private channel; formal notices follow [NOTICE.md](NOTICE.md). Do not open issues or
  pull requests about such reports.
