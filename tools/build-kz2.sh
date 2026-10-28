#!/usr/bin/env bash
# Memory-safe Windows build of port/kz2, one build at a time on the machine shared with the Killzone 3 port.
# From Project Helghast tools/build-kz3.sh (KZ3_* -> KZ2_*; configures the build dir itself when it has no CMakeCache.txt;
# no SPU registration step yet). Run inside the sandbox:
#   nix develop .#win --command tools/sandbox.sh -- tools/build-kz2.sh build/kz2-win [extra cmake --build args]
#   (a second worktree: ... tools/sandbox.sh -- env KZ2_OUT=work/runtime tools/build-kz2.sh build/kz2-win)
# Inputs: $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh) and $KZ2_OUT/recomp (tools/lift.sh); KZ2_OUT
# defaults to work.
# Memory (KZ3's measurements, 2026-10-08..11): a cc1plus on a 64-chunk lifted file peaks at 0.7-1.3 GB (KZ3 saw up to
# 5.3 GB on some), an old 600k-line chunk 6.7 GB; -j8/-j20 next to Proton ran the 31 GB machine out of memory three
# times. So: jobs = (MemAvailable - 8 GB reserve) / KZ2_BUILD_JOB_MB (default 2048: the brief's 1.5-2.5 GB per lifted
# chunk) / build slots in use, 1..KZ2_BUILD_JOBS_MAX (default 6); oom_score_adj 1000 (this build dies first, not the
# editor); one build slot of KZ3's lock directory (shared: KZ3's builds and ours queue together; a lift takes them all).
set -euo pipefail
DIR="${1:?usage: build-kz2.sh BUILD_DIR [cmake --build args]}"; shift
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
PT="$OUT/ps3recomp-patched"
MAINC="$ROOT"; [[ -f "$ROOT/.kz2-main" ]] && MAINC="$(cat "$ROOT/.kz2-main")"
LOCKS="${KZ2_LOCK_DIR:-$(cat "$MAINC/.kz2-lockdir" 2>/dev/null || echo "$MAINC/work/locks")}"
[[ "$LOCKS" == "$MAINC/work/locks" ]] && mkdir -p "$LOCKS"   # only the repo's own lock dir is created
[[ -d "$LOCKS" ]] || { echo "build-kz2: $LOCKS missing (lock directory from .kz2-lockdir)" >&2; exit 2; }
# Refuse a patched toolkit older than the patch set (KZ2_ALLOW_STALE_PATCHES=1 overrides).
[[ -f "$PT/CMakeLists.txt" ]] || { echo "build-kz2: no $PT: run tools/ps3recomp-patched.sh first" >&2; exit 3; }
if [[ "${KZ2_ALLOW_STALE_PATCHES:-0}" != 1 ]]; then
  want="$(cat "$ROOT"/port/patches/*.patch | sha256sum | cut -c1-16)-$(git -C "$ROOT/third_party/ps3recomp" rev-parse --short HEAD 2>/dev/null)"
  have="$(cat "$PT/.kz2-patchset" 2>/dev/null || true)"
  [[ "$have" == "$want" ]] || { echo "build-kz2: $PT is stale ($have, want $want): run tools/ps3recomp-patched.sh first" >&2; exit 3; }
fi
# Configure once: MinGW toolchain (port/cmake), the patched toolkit, the lift.
GO="${KZ2_BUILD_GUARDS_ONLY:-0}"   # guards only: check, never configure (the remote client runs this outside the nix shell)
# The remote build (tools/remote) ships the checkout's work/ps3recomp-patched, whatever KZ2_OUT says: with KZ2_OUT
# naming another tree, refuse when the two trees hold different patch sets (else the remote compiles the old toolkit
# against new port code and fails late, at the link). KZ2_ALLOW_STALE_PATCHES=1 overrides.
if [[ "$GO" == 1 && "${KZ2_ALLOW_STALE_PATCHES:-0}" != 1 && "$(realpath -m "$PT")" != "$(realpath -m "$ROOT/work/ps3recomp-patched")" ]]; then
  wt="$(cat "$ROOT/work/ps3recomp-patched/.kz2-patchset" 2>/dev/null || true)"
  [[ "$wt" == "$(cat "$PT/.kz2-patchset" 2>/dev/null || true)" ]] || { echo "build-kz2: the remote build ships" \
    "$ROOT/work/ps3recomp-patched (${wt:-no stamp}), not $PT ($(cat "$PT/.kz2-patchset" 2>/dev/null)): run" \
    "tools/ps3recomp-patched.sh without KZ2_OUT too, or build locally" >&2; exit 3; }
fi
if [[ "$GO" != 1 && ! -f "$DIR/CMakeCache.txt" ]]; then
  cmake -S "$ROOT/port/kz2" -B "$DIR" -G Ninja -DCMAKE_TOOLCHAIN_FILE="$ROOT/port/cmake/mingw-w64.cmake" \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo -DPython3_EXECUTABLE="$(command -v python3)" \
    -DPS3RECOMP_DIR="$PT" -DRECOMP_DIR="$OUT/recomp" >"$DIR.configure.log" 2>&1 \
    || { tail -20 "$DIR.configure.log" >&2; exit 4; }
fi
# Re-configure when the patched toolkit changed: ps3recomp collects its sources with file(GLOB_RECURSE) without
# CONFIGURE_DEPENDS, so a patch that adds a source file (6003's cellSpursLFQueue.c) is not linked from an old cache
# (the link then fails with undefined _cellSpursLFQueuePushBody).
pt_stamp="$(cat "$PT/.kz2-patchset" 2>/dev/null || true)"
if [[ "$GO" != 1 && "$(cat "$DIR/.kz2-toolkit-stamp" 2>/dev/null || true)" != "$pt_stamp" ]]; then
  cmake -S "$ROOT/port/kz2" -B "$DIR" >>"$DIR.configure.log" 2>&1 || { tail -20 "$DIR.configure.log" >&2; exit 4; }
  echo "$pt_stamp" > "$DIR/.kz2-toolkit-stamp"
fi
# Lifted SPU images (tools/spu/lift_spu.sh): point the cache at $OUT/spu/lift when it has a registration TU
# (the CMake default port/kz2/spu does not exist). KZ2_SPU=0 builds without them.
SPU_LIFT="$OUT/spu/lift"
if [[ "${KZ2_SPU:-1}" != 0 && -f "$SPU_LIFT/spu_workloads.c" ]]; then want_spu="$SPU_LIFT"; else want_spu="$ROOT/port/kz2/spu"; fi
# an exe without the lifted SPU images boots to black ("[spu_workload] ERROR ... no lifted image ... DROPPED");
# a second worktree gets them by linking work/spu/lift to main's. Say so instead of building it silently.
[[ "$want_spu" == "$SPU_LIFT" || "${KZ2_SPU:-1}" == 0 ]] || echo "build-kz2: WARNING no lifted SPU images at $SPU_LIFT" \
  "(no spu_workloads.c): this exe will not run the game's SPU jobs; link it to main's work/spu/lift, or KZ2_SPU=0 to mean it" >&2
# a build dir configured against another toolkit tree (PS3RECOMP_DIR) builds that tree, whatever $PT's stamp
# says (a second worktree's dir made with KZ2_OUT=work/runtime kept building the pre-bump toolkit). Refuse the mismatch.
cfg_pt="$(sed -n 's/^PS3RECOMP_DIR:[A-Z]*=//p' "$DIR/CMakeCache.txt" 2>/dev/null || true)"
if [[ -n "$cfg_pt" && "$(realpath -m "$cfg_pt")" != "$(realpath -m "$PT")" && "${KZ2_ALLOW_STALE_PATCHES:-0}" != 1 ]]; then
  echo "build-kz2: $DIR is configured for the toolkit $cfg_pt, not $PT (KZ2_OUT=$OUT): use a new build dir or the" \
    "matching KZ2_OUT" >&2; exit 3
fi
if [[ "$GO" != 1 && "$(sed -n 's/^SPU_DIR:[A-Z]*=//p' "$DIR/CMakeCache.txt" 2>/dev/null)" != "$want_spu" ]]; then
  cmake -S "$ROOT/port/kz2" -B "$DIR" -DSPU_DIR="$want_spu" >>"$DIR.configure.log" 2>&1 || { tail -20 "$DIR.configure.log" >&2; exit 4; }
fi
# FFmpeg headers for the run-time loaded decoders (port/kz2/CMakeLists.txt KZ2_FFMPEG_INCLUDE_DIR): KZ2_FFMPEG_INCLUDE,
# else the include/ of KZ2_FFMPEG_WIN (default <main>/work/ffmpeg-win, the tools/runtime/ffmpeg-lgpl-win.nix output);
# none: the build goes on without (black movie pictures, silent AC3) and says so.
FFW="${KZ2_FFMPEG_WIN:-$MAINC/work/ffmpeg-win}"
want_ff="${KZ2_FFMPEG_INCLUDE:-$FFW/include}"
[[ -f "$want_ff/libavcodec/avcodec.h" ]] || { echo "build-kz2: no FFmpeg headers at $want_ff: movies stay black (see tools/runtime/ffmpeg-lgpl-win.nix)" >&2; want_ff=""; }
if [[ "$GO" != 1 && "$(sed -n 's/^KZ2_FFMPEG_INCLUDE_DIR:[A-Z]*=//p' "$DIR/CMakeCache.txt" 2>/dev/null)" != "$want_ff" ]]; then
  cmake -S "$ROOT/port/kz2" -B "$DIR" -DKZ2_FFMPEG_INCLUDE_DIR="$want_ff" >>"$DIR.configure.log" 2>&1 || { tail -20 "$DIR.configure.log" >&2; exit 4; }
fi
# The lift must announce exactly the overrides of its EBOOT's list (a host override is compiled only when the lift
# announced PPU_OVERRIDE_<addr>): port/kz2/ppu_overrides.txt for 1.29, ppu_overrides-101.txt for v1.01, by the ver=
# of the lift's .lift-stamp (tools/lift.sh; a stamp without ver= is a v1.01 lift); KZ2_ALLOW_STALE_LIFT=1 overrides.
recomp_l="$(sed -n 's/^RECOMP_DIR:[A-Z]*=//p' "$DIR/CMakeCache.txt" 2>/dev/null || true)"; recomp_l="${recomp_l:-$OUT/recomp}"
ann="$recomp_l/ppu_overrides.h"; [[ -f "$ann" ]] || ann="$recomp_l/ppu_recomp.h"
lift_ver="$(grep -o '^ver=[0-9]*' "$recomp_l/.lift-stamp" 2>/dev/null | cut -c5-)"; lift_ver="${lift_ver:-101}"
ovr_list="$ROOT/port/kz2/ppu_overrides.txt"; [[ "$lift_ver" == 101 ]] && ovr_list="$ROOT/port/kz2/ppu_overrides-101.txt"
if [[ -f "$ann" && "${KZ2_ALLOW_STALE_LIFT:-0}" != 1 ]]; then
  want="$( (grep -oE '^[[:space:]]*[0-9A-Fa-f]{8}' "$ovr_list" || true) | tr -d ' \t' | tr a-f A-F | sort -u)"
  have="$( (grep -oE 'PPU_OVERRIDE_[0-9A-Fa-f]{8}' "$ann" || true) | cut -c14- | tr a-f A-F | sort -u)"
  [[ "$want" == "$have" ]] || { echo "build-kz2: the lift in $recomp_l does not match ${ovr_list#$ROOT/} (lift ver $lift_ver): run tools/lift.sh" >&2; exit 3; }
fi
# Guards only (the remote build client, tools/remote/kz2remote.py): the checks above passed, build nothing here.
[[ "${KZ2_BUILD_GUARDS_ONLY:-0}" == 1 ]] && { echo "build-kz2: guards ok" >&2; exit 0; }
# Build slots across checkouts (tools/agents/slotlock.sh, private tooling): skipped when it is not there.
SLOTS="${KZ2_BUILD_SLOTS:-1}"; [[ "$SLOTS" =~ ^[1-9][0-9]*$ ]] || SLOTS=1; SLOT=none; in_use=1
if [[ -f "$ROOT/tools/agents/slotlock.sh" ]]; then
  # shellcheck source=agents/slotlock.sh
  source "$ROOT/tools/agents/slotlock.sh"
  if [[ " ${KZ2_HELD_LOCKS:-} " == *" build "* ]]; then SLOT=held   # run under the build lock
  else slot_take "$LOCKS" build "$SLOTS"; fi
  in_use=$(slot_held "$LOCKS" build "$SLOTS"); (( in_use < 1 )) && in_use=1
fi
echo 1000 > /proc/self/oom_score_adj 2>/dev/null || true
avail_mb=$(( $(awk '/MemAvailable/{print $2}' /proc/meminfo) / 1024 ))
job_mb="${KZ2_BUILD_JOB_MB:-2048}"; jobs_max="${KZ2_BUILD_JOBS_MAX:-6}"
jobs=$(( (avail_mb - 8192) / job_mb / in_use )); (( jobs < 1 )) && jobs=1; (( jobs > jobs_max )) && jobs=$jobs_max
# Optional temporary cap in the lock directory (build-cap = "EXPIRY_EPOCH MAXJOBS").
if read -r cap_until cap_jobs < "$LOCKS/build-cap" 2>/dev/null && (( $(date +%s) < cap_until )); then
  (( jobs > cap_jobs )) && jobs=$cap_jobs; renice -n 10 -p $$ >/dev/null 2>&1 || true
fi
echo "build-kz2: $DIR with -j$jobs ($(( avail_mb / 1024 )) GB available; build slot $SLOT)" >&2
if command -v ccache >/dev/null && [[ "${KZ2_CCACHE:-1}" != 0 ]]; then
  export CCACHE_DIR="$OUT/ccache" CCACHE_BASEDIR="$ROOT" CCACHE_MAXSIZE=20G CCACHE_COMPRESS=1
  grep -q '^CMAKE_CXX_COMPILER_LAUNCHER:.*=ccache' "$DIR/CMakeCache.txt" 2>/dev/null \
    || cmake -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache "$DIR" >/dev/null
fi
t0=$(date +%s); rc=0
cmake --build "$DIR" -j"$jobs" "$@" || rc=$?
echo "build-kz2: done in $(( $(date +%s) - t0 )) s (-j$jobs, exit $rc)" >&2
exit $rc
