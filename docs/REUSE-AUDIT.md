# Local recompilation project review

This review brings generic runtime fixes into Pyrrhus without game data or a game run. It does not establish that
Killzone 2 boots or renders correctly. The subsequent native macOS integration is described below.

## Selected backport

The local `ps3recomp-up-r10` checkout contains upstream commit
`5d3494a95a038e295cfa2aaf245d3f55cb2549bc`, by Max Leiter,
[ps3recomp PR #621](https://github.com/sp00nznet/ps3recomp/pull/621), MIT. Patch 3009 adapts two related parts:

| Component | Before | After |
|---|---|---|
| sysPrxForUser lightweight mutex | Creation drops the recursive attribute; a failed trylock returns `CELL_ETIMEDOUT`. | Store `protocol \| recursive`; return sign-extended `CELL_EBUSY` when another guest thread holds the lock. |
| cellSyncMutex | Misaligned guest addresses reach atomic operations and can change memory. | All four mutex APIs return `CELL_SYNC_ERROR_ALIGN` before logging, atomic access or coherence hooks. |

The patch keeps Pyrrhus's coherence stripes (1056), diagnostic paths and lv2 mutex/condition-variable hand-off (6027).
It leaves the toolkit pin unchanged. The adapted focused tests and licence credit are listed in `NOTICE.md`.
Any future commit carrying this work should credit “adapted from sp00nznet/ps3recomp PR #621 by Max Leiter”.

## Other local candidates

Initial inspection covered the licences and tool inventories of the Afro Samurai, PES 2013, Resistance 2,
Resistance 3, Demon's Souls and Deadpool projects, plus available ps3recomp checkouts. This was a targeted review,
not a complete audit of those repositories.

- The Resistance 2 spinlock word-width correction is already present in Pyrrhus's pinned toolkit. It was not duplicated.
- The byte/halfword vector-compare CR6 regression from Resistance 2 does not supply a missing change in the pinned
  lifter; that compare implementation already matches the reviewed local implementation.
- The broader lv2 synchronization changes in PR #621 overlap Pyrrhus's hand-off implementation. Only the isolated
  sysPrxForUser and cellSyncMutex fixes were selected, avoiding replacement of that existing implementation.
- macOS graphics backends, title-specific hooks and lifted game code were not imported. Pyrrhus's native Mac build
  was outside the initial synchronization backport; see the subsequent work below.

## Subsequent native macOS integration

The Afro Samurai port's main-thread run-loop design and build resource guards informed the new
`kz2_macos_host.cpp` and `build-kz2-macos.py` implementations. Credits and licence text are in `NOTICE.md`.
The existing pinned toolkit already contains the Metal backend; it was integrated without importing a newer
runtime or changing the submodule pin. Patches 6083 and 7023 repair native compilation and library-loading issues.
ARM64 uses the lifted SPU path without x86 ISA flags or the optional x86 native-job replacements.

The native ARM64 executable compiled on an Apple M4 Pro. The synthetic boot passed with Metal both offscreen and
in a Cocoa window: all 11 boot markers, three presented frames, vblank and exit. Separate tests cover main-queue
dispatch from the guest worker, fiber register/local restoration, and SPU pool timeout/reuse/retirement.
No actual game, game lift, physical controller, native movie playback or full Nix CI was tested.
See [BUILDING.md](BUILDING.md#building-on-macos) for commands and current limitations.

## Validation

The host regression compiles the production lwmutex handlers and the production cellSync mutex section with their
real atomics and headers. Guest memory and unrelated runtime services are supplied by small test fixtures.
It checks the attribute word, successful and recursive trylock, the busy error including sign extension, unchanged
ownership on failure, null arguments, all three misalignments and an aligned lock/unlock sequence.

The negative control is the pinned toolkit plus the existing patches without 3009; it reproduces both missing
lwmutex behaviors and memory changes from misaligned cellSync calls. The positive control uses the same pin and
all patches including 3009. No game files are read by these checks. Full Nix CI, a Windows build and game runs
are separate validation steps.
