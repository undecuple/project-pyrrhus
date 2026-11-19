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

## Complete local audit (2026-11-18)

The first review above was targeted; this pass audits the owner's local ports for SPU/SPURS and
GPU-sync work worth adapting, checking each candidate against the pinned toolkit plus the current
patch series (so nothing already present is duplicated). All audited ports are MIT by the owner
(Erik Martins) with ps3recomp attribution; their toolkit changes are adaptable, their lifted game
code is not.

### What each reference uses

| Port | ps3recomp base | Licence |
|---|---|---|
| Afro Samurai | upstream v0.19.0 (`ae92407b`), one big toolkit patch | MIT |
| Resistance: Fall of Man / R2 / R3 | v0.17.0 (`a6d76c8`), R3 with documented v0.19 backports | MIT |
| inFAMOUS 1 / 2 | NoahBPeterson fork `v0.13.0-112-g770660a` + upstream PR pack | MIT |

Pyrrhus's pinned toolkit is a newer fork than any of these ports', so candidates were verified
against the generated patched tree (`work/ps3recomp-patched`) rather than assumed missing.

### Candidates, checked against this tree

| Candidate | From | Present here? | Open symptom it targets |
|---|---|---|---|
| LF-queue push on the canonical 128-byte `CellSyncLFQueue` line + lost-wakeup fixes | Afro (adapted from the owner's R2) | **already covered, differently**: patch 6003 is the push with waiter signalling, read off this game's own SPU consumer, and the WAIT_SIGNAL lost-wakeup races are handled by the wake latch plus consume-before-park and wake-on-line-commit in `spu_workload.c` | mission-load stalls; SPURS readiness quirks |
| Guard waits while the chain runs (`SPURS_JG_WAIT_FOREVER`), END-overwrite re-walk; job-sent events only (`SPURS_JC_EVENT_FROM_JOB`); JOBLIST chain command (op 6) executed instead of no-op; older job-context layout (`SPURS_JOB_CTX_V1`) | Afro | **not this game's path**: Killzone 2 runs WWS jobs through SPURS policy modules (`AddWorkloadWA` with the lifted `jm_*` images), not `cellSpursRunJobChain`, so the chain walker's guard/END/JOBLIST rules do not run for it (they serve other titles on the same fork). The job-context staging this game needs is already in `spurs_job.c` (CRT Ver13, kernel-context LS view) | mission-load stalls; SPURS readiness quirks |
| Write-back at NV3089 blits: submit once, read the target/depth back into guest memory at the blit, invalidate the queued depth decode | inFAMOUS 2 | **no** (`rsx_draw_engine_write_back` absent) | the drain stalls attributed to depth readbacks |
| R3 FIFO walker: shadow fetch of JUMP-entered command lists, resync replays label releases, store bounds | Resistance 3 | **no** (R3's 6-24 s checkpoint stalls had this shape) | mission-load drain stalls |
| Relocatable SPU overlay lifts (translate streamed blobs once, resident wherever the GET lands) and overlay residency/retirement (LRU slots, byte verify) | upstream v0.19 (`b3bfd018`), Afro FMOD recipe, R3 slots | **no** (`spu_overlay_register_region_reloc` absent; map/skip/entry hooks 1004/1043/1044 exist) | "overlay image streamed 4096/16384 times"; interpreted re-streamed code |
| `cellAudio` POSIX mixer paced to the device (`AUDIO_ELASTIC`), stereo peak limiter, PCM-stall protection | upstream r8 (`b375e81f`), R2 | **no** (6024's steady block clock is a different half) | audio dropouts |
| Shader translation: disk cache, async/parallel builds | inFAMOUS (upstream r8) | **no** (pipeline list ships instead) | first-play shader pauses (ROADMAP 🔧) |
| DMA PUT into read-only guest text rejected (diagnosable, not fatal) | Afro | **no** | guard-rail for overlay re-streaming |
| Bounded label waits, park grace, faster frame clock, present-before-drain | inFAMOUS | **partly** (`GCM_SEMA_ACQUIRE` 6081, park-wake 6038, present-before-drain in `main.cpp`) | FIFO wedges |

Not importable: every port's lifted SPU/PPU game code, per-game patch words (`RES_*` addresses),
inFAMOUS's `gpu_light`/`gpu_ssao` payloads (the *mechanism* — replace a job's dispatch with
bookkeeping plus a Metal pass that keeps the labels — is documented and transferable; KZ2's own
jobs would need their own RE), and Afro's FMOD-specific `SPU_EXTRA` tuning.

### Import order

Generic, env-gated, A/B-able, each with a host test. Revised 2026-11-18 by measurement: a
`PS3_FTRACE` timeline plus the walker sampler (`RSX_WALKER_PROF`) proved the mission-load drain
stalls (up to 32 s) are **first-seen Metal pipeline builds compiling synchronously on the FIFO
walker thread** — 43 s of one 120 s window inside `newRenderPipelineStateWithDescriptor`, the GPU
idle meanwhile, the largest depth readback 12.8 ms. The inFAMOUS 2 lesson repeated: its "ref
stuck" stalls were first blamed on SPU caches before a profiler proved shader translation. So:

1. **Done (patches 2161, 2166, 2167):** the pipeline archive (`PS3RECOMP_METAL_PSO_ARCHIVE`), the
   drawable presenter with a bounded in-flight wait (`PS3RECOMP_METAL_PRESENT_WAIT_MS`), and async
   pipeline builds on a worker (`PS3RECOMP_METAL_ASYNC_PSO`) -- together they removed the freezes
   (a 400 s scripted session's worst frame-call is now one 805 ms present; it was 26-56 s drains,
   GPU idle). The host test `tools/runtime/test_metal_pso_archive.py` pins the archive's API flow,
   and the Metal smoke boot still passes offscreen and windowed. The R3 archive lessons (chunking,
   size caps) are noted for if the file grows past its current 10 MB.
2. The NV3089 write-back stays a candidate for depth-consumer correctness, but it is **not**
   the stall remedy; the attribution to depth readbacks did not survive the timeline.
3. Relocatable overlay lifts plus residency/retirement (targets re-streaming and, per
   inFAMOUS 2, much of the audio dropout cause).
4. `AUDIO_ELASTIC` mixer pacing.
5. The R3 shadow-fetch walker, only if stalls remain that the archive does not explain.
`SPURS_JOB_CTX_V1` and JOBLIST op-6 do not apply: this game runs WWS jobs through SPURS
policy modules, not job chains. Anything upstreamed (v0.19 overlay reloc, r8 audio) is
credited per `NOTICE.md` rules.

## Validation

The host regression compiles the production lwmutex handlers and the production cellSync mutex section with their
real atomics and headers. Guest memory and unrelated runtime services are supplied by small test fixtures.
It checks the attribute word, successful and recursive trylock, the busy error including sign extension, unchanged
ownership on failure, null arguments, all three misalignments and an aligned lock/unlock sequence.

The negative control is the pinned toolkit plus the existing patches without 3009; it reproduces both missing
lwmutex behaviors and memory changes from misaligned cellSync calls. The positive control uses the same pin and
all patches including 3009. No game files are read by these checks. Full Nix CI, a Windows build and game runs
are separate validation steps.
