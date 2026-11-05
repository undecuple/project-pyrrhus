# Copying or forking this project

This page is for people who fork or reuse this repository. It lists what carries this project's name, address or
settings, so your copy does not point at ours or claim to be ours. Check each item before you publish anything.

**Licence.** The port's own code, tools and documentation are MIT ([LICENSE](../LICENSE)): you may use, copy, modify,
merge, publish, distribute, sublicense and sell copies. Every copy or substantial portion must keep the copyright line
("Copyright (c) 2026 undecuple") and the MIT permission notice. [NOTICE.md](../NOTICE.md) also asks, but the licence
does not require, that derived work credit "Project Pyrrhus by undecuple" with a link to this repository. The licence
covers nothing of Killzone 2 itself.

## Names and branding

"Project Pyrrhus" is this fan project's name. Use your own name for a fork, and say it is unofficial and not affiliated
with Sony Interactive Entertainment or Guerrilla Games, as the README does. Where the name lives:

| Where | File |
|---|---|
| Title, banner text, badges, prose | `README.md`, `docs/*.md` (with `docs/FEATURES.md`), `.github/CONTRIBUTING.md`, `.github/SECURITY.md` |
| Banner and social preview images (generated) | `assets/banner.png`, `assets/banner@2x.png`, `assets/social-preview.png` |
| Installer name, publisher, output file name, app folder, launcher name | `installer/kz2.iss` (`AppName`, `AppDirName`, `AppPublisher`, `LauncherExe`, `SetupBase`) |
| Launcher version block (product name, company, file description) | `installer/launcher/launcher.rc` |
| `kz2.exe` version block (product name, company, file description) | `installer/app.rc.in` |
| Icons and wizard images (generated, with Rajdhani lettering) | `installer/art/`, made by `tools/release/installer_art.py` from `installer/art/art.json` |
| Portable zip first-run script text | `installer/run.cmd`, `tools/release/firstrun.py` |
| Project website page (generated) | `site/index.html`, `site/style.css`, made by `tools/release/website.py` |
| Directory entry for recomp.board | `.recomp.json` |
| Project citation | `CITATION.cff` |

Two things are easy to miss:

- **`AppId` in `installer/kz2.iss`** is the installer's identity on a user's machine. Give your fork its own GUID, or
  your installer will replace and uninstall ours.
- **The game window title.** `port/kz2/main.cpp` reads the `PS3_TITLE` environment variable and falls back to
  `ps3recomp` when it is empty; nothing in this tree sets it. Set it where you start the game, or change the default.
  Error boxes in `port/kz2/main.cpp` and `port/kz2/kz2_cpu_check.c` are titled "Killzone 2".

The generated art and the site have checks you can run after renaming:
`python3 tools/release/test_installer_art.py` and `python3 tools/release/test_website.py`. Re-run
`tools/release/installer_art.py` and `tools/release/website.py` rather than editing the images and `site/index.html` by hand.

## Identity and remotes

This project's repository address appears as plain text in many files. Search for `undecuple` and replace each
occurrence you do not mean to keep (the copyright line and credits in NOTICE.md stay):

- `README.md`, `docs/BUILDING.md` (clone command and releases page), `NOTICE.md`, `CITATION.cff` (`repository-code`,
  `url`, `authors`), `.recomp.json`, `.github/CODEOWNERS`, `.github/FUNDING.yml`, `.github/ISSUE_TEMPLATE/config.yml`
  (security and issue links).
- `installer/kz2.iss` (`ProjectURL`, `SiteURL`, `SiteText`) and `installer/launcher/launcher.rc` (`Comments`).
- `installer/launcher/launcher.c` and `tools/release/firstrun.py` (the "report it on the issues page" messages).
- `tools/release/launch.py` (`RELEASES`, `ISSUES_URL`) and `tools/release/website.py` (`REPO`, and the related-project link).

**The update check.** The launcher, the installer's "Check now" button and the portable zip can ask for a newer
release. They run `tools/release/version_check.py`, which makes one anonymous HTTPS request to `DEFAULT_URL` in that
file: `https://api.github.com/repos/undecuple/project-pyrrhus/releases?per_page=30`. It reads the releases list rather
than `releases/latest`, because GitHub's "latest" never returns a pre-release; it skips drafts and tags that are not
`vMAJOR.MINOR.PATCH`, and takes the newest by version. A fork must either change `DEFAULT_URL`
(and `USER_AGENT`) to its own repository, or leave the check off. It is off until the user asks: the setting is
`check_updates` under `[online]` in `kz2-install.ini`, written by the installer and by `tools/release/firstrun.py`.
The script also takes `--url`, so you can point it at a test server or a saved answer; `tools/release/test_version_check.py`
checks that the request carries nothing but a User-Agent and an Accept header. Keep that property, and keep the README
section "What goes online" true for your fork.

The git author is not set in the tree. Use your own `user.name` and `user.email`, and review your first commits for
personal paths and host names.

## Versions and releases

Tags are `vMAJOR.MINOR.PATCH`: a fix bumps the last number, a feature the middle one. Every release stays a GitHub
pre-release until `v1.0.0`. No suffixes (no `-alpha`, `-rc`). A tag is never moved or reused: if a release is wrong,
publish the next version (the first tag, `v0.1.0`, was never published as a release for that reason). Put the checksum
files next to the assets.

One file holds the version: `installer/VERSION` (`MAJOR.MINOR.PATCH`, nothing else). Change it only with
`python3 tools/release/bump_version.py X.Y.Z` (`--check` lists what would change): it writes `installer/VERSION`,
`CITATION.cff` (`version`, `date-released`), the `<!-- version -->...<!-- /version -->` spans in the README, the docs
and the site, any literal version in the resource scripts, `installer/kz2.iss` or `port/kz2/CMakeLists.txt`, and turns
`## [Unreleased]` in `CHANGELOG.md` into `## [X.Y.Z] - DATE (pre-release)`; then it regenerates the site and runs
`tools/release/test_version_agree.py`. Write the changes for players under `## [Unreleased]` as you make them.
`tools/release/release_version.py --check --tag vX.Y.Z` confirms that a release tag matches the version. The release
workflow writes the release notes from the tag's `CHANGELOG.md` entry (`tools/release/release_notes.py`) and stops
when there is none.

| Place | How it gets the version |
|---|---|
| Portable zip and installed files | `tools/release/assemble_payload.py` writes `VERSION.txt` from `installer/VERSION`; `tools/release/firstrun.py`, the launcher and the update check read it |
| Installer | `installer/kz2.iss` reads `AppVersion` from the payload's `VERSION.txt` when it is compiled |
| Launcher exe version block | `tools/release/build_launcher.sh` writes `launcher_version.h` for `installer/launcher/launcher.rc` (`FileVersion` X.Y.Z, `FILEVERSION` X,Y,Z,0) |
| `kz2.exe` version block and icon | `assemble_payload.py` writes the payload's `port/kz2/app.rc` from `installer/app.rc.in` and puts the launcher icon beside it as `kz2.ico`; `port/kz2/CMakeLists.txt` compiles it on the player's build |
| `CITATION.cff` | `bump_version.py` sets `version` and `date-released` (`release_version.py --stamp-citation --date YYYY-MM-DD` does the same alone) |

`assemble_payload.py`, `release_version.py` and `version_check.py` refuse a version with a suffix, and
`assemble_payload.py` refuses a `--version` that is not the one in `installer/VERSION`. `port/kz2/CMakeLists.txt`'s
`project()` line carries no version.

Checksums: `tools/release/pack_zip.py` writes `<zip>.sha256` ("hash, two spaces, name") beside the portable zip, and
`version_check.py` looks for a `.sha256` asset named after the installer. Publish one for each asset you upload.

## CI and GitHub settings

The workflows in `.github/workflows/` run on a fork too once Actions are enabled there. The host tests are listed in
`tools/host-tests.txt`, one command per line, with no game data and no network. For these workflows and your own:

- Pin every third-party action to a full commit SHA, not a tag.
- Give the workflow token the least permission it needs (`permissions: contents: read` at the top, widen per job).
- Require approval before Actions run for first-time contributors, and never run workflows from forks with secrets.
- Keep secrets in the repository's secret store. Never commit tokens, keys or credentials, and never print them in logs.
- Set up labels and a branch ruleset (no force-push to the default branch, no deleting tags). The issue forms in
  `.github/ISSUE_TEMPLATE/` and `.github/pull_request_template.md` assume labels you create yourself.
- Enable private vulnerability reporting, since `.github/SECURITY.md` points reporters to it.

## Paths, hosts and environment in the scripts

Check these before you run the scripts on another machine.

| Item | Where | Default or note |
|---|---|---|
| `KZ2_ROOT`, `KZ2_GAME`, `KZ2_WORK` | `flake.nix` dev shell | the repo directory, `Game/` and `work/` inside it |
| `VK_ICD_FILENAMES` | `flake.nix` dev shell | a fixed NVIDIA Vulkan driver path; change it for your system |
| `KZ2_OUT` | `tools/lift.sh`, `tools/build-kz2.sh`, `tools/ps3recomp-patched.sh` | `work` |
| `KZ2_EBOOT`, `KZ2_EBOOT_VER`, `KZ2_TOC`, `KZ2_CODE_END` | `tools/lift.sh` | version `129`; `101` selects the disc's own executable |
| `KZ2_LIFT_CHUNKS`, `KZ2_BUILD_SLOTS`, `KZ2_BUILD_JOBS_MAX`, `KZ2_BUILD_JOB_MB`, `KZ2_CCACHE`, `KZ2_SPU` | `tools/lift.sh`, `tools/build-kz2.sh` | tuning; the memory figure is per compile job |
| `KZ2_FFMPEG_WIN`, `KZ2_FFMPEG_INCLUDE` | `tools/build-kz2.sh` | where the LGPL movie decoder build is expected |
| `KZ2_PATCHED_DIR` | `tools/ps3recomp-patched.sh` | where the patched toolkit copy is made |
| `KZ2_LOCK_DIR`, `KZ2_HELD_LOCKS` | `tools/lift.sh`, `tools/build-kz2.sh` | lock files for shared build slots; you can ignore them on one machine |
| `PROTON_DIR` | `tools/proton-test.sh` (`--proton`), `tools/proton-inner.sh` | a Proton-GE folder in the Steam compatibility-tools directory of the script author's home; change it |
| `KZ2_REAL_DISPLAY`, `KZ2_EXIT_EARLY`, `KZ2_LOG_STDOUT`, `KZ2_NO_ERROR_BOX` | `tools/proton-inner.sh` | test-run switches; see the script header |
| `KZ2_WORK_DIR` | `tools/assets/profile_edit.py` and its test | where the tool may write |
| `PS3_VFS_ROOT`, `APPDATA`, `kz2-install.ini` | `tools/release/launch.py` | the launcher's game folder, settings location and settings file |

`tools/sandbox.sh` runs commands in a bubblewrap sandbox that makes the game folder and the repo read-only and allows
no network; adapt its mounts if your layout differs. `tools/safe_rm.sh` only deletes inside `work/` and `build/` of the
repo; keep that limit.

## What the user supplies

Nothing from the game is in this repository or in a release. Each user brings their own copy of the US disc
(BCUS98116; the European, Asian and Japanese discs are accepted but untested), the 1.29 update of the same region,
and a decrypted executable made from their own copy. This project gives no tools or
instructions for making that executable; [RPCS3](https://rpcs3.net/) and its documentation are the place to start
for the game files. Do not add a decryption procedure, keys, or links to either to your fork's docs or tests. The full
list is in [requirements.md](requirements.md). Do not add disc files, archives, executables or extracted assets to
your fork, including in test fixtures.

## Licences and credits to keep

- `NOTICE.md`: every outside component with author, source, licence and what was used. Keep it, add your own rows,
  and keep the pull-request credits for patches you carry.
- `licenses/`: the texts for ps3recomp (MIT), SDL3 (zlib), the LGPL decoder DLLs (LGPL-2.1), the Rajdhani font (SIL
  Open Font License 1.1) and this project's own licence. The installer and the portable zip ship this folder.
- `port/patches/`: each patch header names its source where there is one. Patches adapted from other projects keep
  those credit lines, and keep their licence terms.
- The build uses ps3recomp, which is MIT. If you move to another release, update the pinned version in `NOTICE.md`,
  `README.md` and `docs/BUILDING.md`, and check that every patch still applies.

## Security checks to keep or adapt

- Before you publish, scan your tree for personal or private paths, host names, tokens and keys, for game data (archive,
  executable and save-file headers, and any large binary), and for broken Markdown links. This repository was
  published only after such a scan; the script that runs it is not part of the export, so write your own.
- Keep the opt-in rule for network features and the test that guards it (`tools/release/test_version_check.py`).
- Keep the host tests in `tools/host-tests.txt` passing; they need no game and no network.
- `.github/SECURITY.md` names this repository as the place to report problems. Change it to yours.

## What is not here

Internal tooling and working notes are not part of this export, and some scripts mention optional pieces that are
absent (for example build-slot locks). That is why `KZ2_LOCK_DIR` and `KZ2_HELD_LOCKS` can be ignored. If a script
refers to a file you cannot find, treat it as optional first and check the script before assuming the tree is incomplete.
