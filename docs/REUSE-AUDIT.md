# Reuse review for the native macOS work

What the native macOS series took from other MIT projects, what it checked and left out, and why. Credits and licence
texts are in [NOTICE.md](../NOTICE.md). The macOS build itself is experimental: see
[BUILDING.md](BUILDING.md#building-on-macos) for what has been run and [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for what does
not work yet.

## Synchronization backport (patch 3010)

[ps3recomp PR #621](https://github.com/sp00nznet/ps3recomp/pull/621) by Max Leiter (commit
`5d3494a95a038e295cfa2aaf245d3f55cb2549bc`, MIT) is adapted in two parts:

| Component | Before | After |
|---|---|---|
| sysPrxForUser lightweight mutex | Creation drops the recursive attribute; a failed trylock returns `CELL_ETIMEDOUT`. | Store `protocol \| recursive`; return sign-extended `CELL_EBUSY` when another guest thread holds the lock. |
| cellSyncMutex | Misaligned guest addresses reach atomic operations and can change memory. | All four mutex APIs return `CELL_SYNC_ERROR_ALIGN` before logging, atomic access or coherence hooks. |

The patch keeps this port's coherence stripes (1056), diagnostic paths and lv2 mutex/condition-variable hand-off
(6027), and leaves the toolkit pin unchanged. The broader lv2 synchronization changes in the PR overlap that hand-off
and were not taken. The return-value change applies on every platform.

Validation: the host test compiles the production lwmutex handlers and the production cellSync mutex section with their
real atomics and headers (guest memory and unrelated services are small fixtures). It checks the attribute word,
successful and recursive trylock, the busy error with its sign extension, unchanged ownership on failure, null
arguments, all three misalignments and an aligned lock/unlock sequence. The negative control (the pinned toolkit plus
every patch but 3010) reproduces both missing lwmutex behaviours and the memory changes from misaligned cellSync calls.

## Ports reviewed

Erik Martins's MIT ports were reviewed for runtime, SPU/SPURS and GPU-sync work worth adapting: Afro Samurai
(ps3recomp v0.19.0, `ae92407b`), Resistance: Fall of Man, 2 and 3 (v0.17.0, `a6d76c8`, Resistance 3 with v0.19
backports) and inFAMOUS 1 and 2 (the NoahBPeterson fork, `v0.13.0-112-g770660a`). Their toolkit changes are
adaptable; their lifted game code is not, and none was imported. This port's pinned toolkit is newer than any of
theirs, so every candidate was checked against the patched tree rather than assumed missing.

Taken:

- The Afro Samurai port's main run loop and guest worker design and its build resource guards, newly implemented in
  `port/kz2/kz2_macos_host.cpp` and `tools/build-kz2-macos.py`.
- The Metal depth-bounds emulation and depth clamp (patches 2174 and 2175, his ps3recomp fork commits `59d1533b` and
  `53650c7d`), and the stale depth snapshot, sampler table and ZPASS counts after the Resistance 3 macOS port (2176,
  2177). 2174 and 2175 are off by default: with them on, menu text, in-game text and floor textures broke.

Checked and left out:

| Candidate | From | Why not |
|---|---|---|
| LF-queue push on the canonical 128-byte `CellSyncLFQueue` line and its lost-wakeup fixes | Afro Samurai, Resistance 2 | already covered differently: patch 6003 and the wake latch and wake-on-line-commit in `spu_workload.c` |
| Job-chain fixes (`SPURS_JG_WAIT_FOREVER`, `SPURS_JC_EVENT_FROM_JOB`, JOBLIST op 6, `SPURS_JOB_CTX_V1`) | Afro Samurai | not this game's path: Killzone 2 runs WWS jobs through SPURS policy modules, not job chains |
| Write-back at NV3089 blits | inFAMOUS 2 | a depth-consumer correctness candidate, not the cause of the stalls it was first blamed for |
| Shadow fetch of JUMP-entered command lists in the FIFO walker | Resistance 3 | only if stalls remain that the pipeline work does not explain |
| Relocatable SPU overlay lifts and overlay residency/retirement | ps3recomp v0.19 (`b3bfd018`), Afro Samurai, Resistance 3 | a larger change; still a candidate for re-streamed overlays |
| `cellAudio` mixer paced to the device (`AUDIO_ELASTIC`) | ps3recomp r8 (`b375e81f`), Resistance 2 | still a candidate for audio dropouts |
| The Resistance 2 spinlock word-width fix and its CR6 vector-compare change | Resistance 2 | already in the pinned toolkit |

## Stalls: what the measurement showed

A frame-trace timeline (`PS3_FTRACE`) and the walker's wall-clock sampler (`RSX_WALKER_PROF`) put the multi-second
mission-load stalls on first-seen Metal pipelines compiled synchronously on the FIFO walker thread, the GPU idle
meanwhile; the largest depth readback was 12.8 ms. Patches 2173, 2178 and 2179 (pipeline archive, drawable
presenter, background pipeline builds) and later 2181-2184 address that. The figures are from the contributor's own
scripted runs on one Apple M4 Pro; see [BUILDING.md](BUILDING.md#building-on-macos).
