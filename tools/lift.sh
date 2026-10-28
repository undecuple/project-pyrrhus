#!/usr/bin/env bash
# Reproducible PPU lift of the Killzone 2 EBOOT with ps3recomp + port/patches.
# From Project Helghast tools/lift.sh (KZ3_* -> KZ2_*; KZ2's own code end and TOC; KZ2's own, empty, override list).
#
#   nix develop .#re --command tools/sandbox.sh -- tools/lift.sh [EBOOT.elf]
#   (a second worktree: ... tools/sandbox.sh -- env KZ2_OUT=work/runtime tools/lift.sh)
#
# 1. $KZ2_OUT/ps3recomp-patched (KZ2_OUT defaults to work) = third_party/ps3recomp + every port/patches/*.patch
#    (tools/ps3recomp-patched.sh).
# 2. ppu_loader + find_functions into $KZ2_OUT/analysis (if functions.json is missing there).
# 3. ppu_lifter --code-end KZ2_CODE_END --toc KZ2_TOC --overrides port/kz2/ppu_overrides.txt --chunks 64 into
#    $KZ2_OUT/recomp: ppu_recomp.h, ppu_overrides.h, ppu_recomp_000..063.cpp, ppu_recomp_table.cpp, .lift-stamp.
# 4. lift_audit into $KZ2_OUT/analysis/lift_audit.log.
# EBOOT (KZ2_EBOOT_VER; the port targets the 1.29 update):
#   129 (default): work/bin/EBOOT-129.elf (16,455,144 B, sha256 e8b0ddefc0cb1dc1...), code end 0xbd0d0c, TOC 0xec3038
#       (entry 0xe77ed0), overrides port/kz2/ppu_overrides.txt, analysis $KZ2_OUT/analysis-129.
#   101: the decrypted v1.01 disc EBOOT Game/PS3_GAME/USRDIR/EBOOT.elf (sha256 39a28358efd91fd0...): section headers
#       1-4 are the only executable (AX) sections, 0x10200..0xbba45c, so code end = 0xbba45c; TOC = 0xeb2958, the r2
#       of the entry descriptor (.opd at 0xe67e60 = {0x105e0, 0xeb2958}); overrides port/kz2/ppu_overrides-101.txt,
#       analysis $KZ2_OUT/analysis.
# KZ2_EBOOT / KZ2_CODE_END / KZ2_TOC / an ELF argument still override the version's values. The stamp records ver=,
# and tools/build-kz2.sh checks the lift against that version's override list.
set -euo pipefail
echo 1000 > /proc/self/oom_score_adj 2>/dev/null || true   # first OOM victim, not the editor
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VER="${KZ2_EBOOT_VER:-129}"
OUT="${KZ2_OUT:-work}"
case "$VER" in
  129) D_ELF=work/bin/EBOOT-129.elf; D_END=0xbd0d0c; D_TOC=0xec3038; OVR=port/kz2/ppu_overrides.txt; AN="$OUT/analysis-129" ;;
  101) D_ELF=Game/PS3_GAME/USRDIR/EBOOT.elf; D_END=0xbba45c; D_TOC=0xeb2958; OVR=port/kz2/ppu_overrides-101.txt; AN="$OUT/analysis" ;;
  *) echo "KZ2_EBOOT_VER must be 129 or 101 (got $VER)" >&2; exit 2 ;;
esac
ELF="${1:-${KZ2_EBOOT:-$D_ELF}}"
CODE_END="${KZ2_CODE_END:-$D_END}"
TOC="${KZ2_TOC:-$D_TOC}"
PT="$OUT/ps3recomp-patched"; RC="$OUT/recomp"
[[ -f "$ELF" ]] || { echo "missing $ELF (the decrypted EBOOT)" >&2; exit 1; }
# Build slots: a build compiles $RC, which this script rewrites; and a lift + a build together is memory the shared
# machine may not have. Taken only when the slot helper (tools/agents/slotlock.sh) is there; bound writable in the sandbox.
MAINC="$ROOT"; [[ -f "$ROOT/.kz2-main" ]] && MAINC="$(cat "$ROOT/.kz2-main")"
LOCKS="${KZ2_LOCK_DIR:-$(cat "$MAINC/.kz2-lockdir" 2>/dev/null || echo "$MAINC/work/locks")}"
[[ "$LOCKS" == "$MAINC/work/locks" ]] && mkdir -p "$LOCKS"   # only the repo's own lock dir is created
if [[ -d "$LOCKS" && -f "$ROOT/tools/agents/slotlock.sh" && " ${KZ2_HELD_LOCKS:-} " != *" build "* ]]; then
  source "$ROOT/tools/agents/slotlock.sh"; slot_take_all "$LOCKS" build "${KZ2_BUILD_SLOTS:-1}"
fi

KZ2_OUT="$OUT" "$ROOT/tools/ps3recomp-patched.sh"

mkdir -p "$AN" "$RC"
# The analysis is cached per EBOOT: $AN/.elf-sha names the ELF it was made from (a stale or foreign one is redone).
elf_sha="$(sha256sum "$ELF" | cut -c1-16)"
STEM="$(basename "$ELF")"; STEM="${STEM%.*}"   # ppu_loader names its outputs after the ELF (EBOOT-129.imports.json)
if [[ ! -f "$AN/functions.json" || "$(cat "$AN/.elf-sha" 2>/dev/null || echo "$elf_sha")" != "$elf_sha" ]]; then
  python3 "$PT/tools/ppu_loader.py" "$ELF" -o "$AN/"
  python3 "$PT/tools/find_functions.py" "$ELF" --seed-json "$AN/$STEM.functions.json" --output "$AN/functions.json"
fi
echo "$elf_sha" > "$AN/.elf-sha"

# --chunks 64 (patch 3005): address-keyed chunks, only changed files rewritten; stale chunk files removed by the lifter.
CHUNKS="${KZ2_LIFT_CHUNKS:-64}"
# KZ2_PROBES=<file> (patch 6017, off by default): instruction addresses where the lifted C calls ppu_probe(ctx, addr)
# (port/kz2/kz2_probe.cpp); lists in tools/runtime/probes/. A lift without it has no probe calls.
PROBES=(); [[ -n "${KZ2_PROBES:-}" ]] && PROBES=(--probes "$KZ2_PROBES")
python3 "$PT/tools/ppu_lifter.py" "$ELF" --functions "$AN/functions.json" \
  --hle-stubs "$AN/$STEM.imports.json" --toc "$TOC" --code-end "$CODE_END" \
  --overrides "$OVR" "${PROBES[@]}" -j 4 --chunks "$CHUNKS" --output "$RC" > "$RC/lift.log" 2>&1
tail -5 "$RC/lift.log"
printf 'ver=%s elf=%s sha=%s code_end=%s toc=%s overrides=%s probes=%s patchset=%s chunks=%s date=%s\n' "$VER" "$ELF" \
  "$elf_sha" "$CODE_END" "$TOC" "$(sha256sum "$OVR" | cut -c1-16)" "${KZ2_PROBES:-none}" \
  "$(cat "$PT/.kz2-patchset" 2>/dev/null)" "$CHUNKS" "$(date -Is)" > "$RC/.lift-stamp"

python3 "$PT/tools/lift_audit.py" --elf "$ELF" --functions "$AN/functions.json" \
  --recomp-dir "$RC" --baseline "$AN/none.json" > "$AN/lift_audit.log" 2>&1 || true
sed -n '/=== Pass 1/,/TOTAL \/\* unresolved/p' "$AN/lift_audit.log"
