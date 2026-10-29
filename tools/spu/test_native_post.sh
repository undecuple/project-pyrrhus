#!/usr/bin/env bash
# Spu rounds 16-18 host test: the native Gfx.Post kernels (port/kz2/spu/native_post.c: Gfx.Post.Upsample's two kernels
# and the three output kernels shared by 16 Gfx.Post images, 49 gates; native_blur.c: VBlur's and HBlur's 12 row
# kernels; native_bloom.c: BloomCapture's and GrainWeight's passes; native_postjobs.c: Modulate,
# BloomIntegrate, ILR, Vignette, DepthToFuzzy, Downsample (2), Zero, slots 66-73; native_dof.c's DepthOfField pass, slot
# 74; DepthOfField's kernel slots 0-2 are test_native_dof.sh; Anim.EdgeAnim's slots are test_native_edgeanim.sh)
# against the lifted code and the SPU interpreter on synthetic inputs (tools/spu/native_diff.py synth --interp): every
# case must leave the whole local store and the preserved registers equal, and each gate must be the image and
# address its native table entry names. Slots 66 and up plant cases the native code must decline (in-place or unaligned
# buffers, frames it was not written for): there a fallback is fine as long as at least 3/4 of the cases ran native. Needs the SPU lift ($KZ2_OUT/spu/lift, the main checkout's work/spu/lift;
# KZ2_OUT=work/spu in the SPU) and the patched toolkit; no game data in git.
#   nix develop .#re --command tools/sandbox.sh -- tools/spu/test_native_post.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00d51f00/spu_recomp.c"
if [[ ! -f "$L" ]]; then echo "SKIP: no Gfx.Post.Upsample lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
grep -q "native gate 3:" "$L" || { echo "FAIL test_native_post: the lift at $L has no round-16 gates (re-lift)"; exit 1; }
slots=$(awk -F'\t' '!/^#/ && NF > 2 && $3 > 2 && $4 ~ /^Gfx\.Post\./ { printf " --slot %s", $3 }' "$ROOT/re/spu/native_gates.tsv")
want=$(echo "$slots" | grep -o -- "--slot" | wc -l)
out=$(python3 "$ROOT/tools/spu/native_diff.py" synth $slots --trials "${TRIALS:-100}" --interp 2>&1); rc=$?
echo "$out" | grep -v "mismatch=0 fallback=0 broken=0 interp_mismatch=0" | tail -12
n=$(echo "$out" | awk '/ T slot=/ { s = c = m = f = 0; for (i = 1; i <= NF; i++) { split($i, kv, "=");
       if (kv[1] == "slot") s = kv[2]; if (kv[1] == "cases") c = kv[2]; if (kv[1] == "match") m = kv[2];
       if (kv[1] == "fallback") f = kv[2] }
     if ($0 ~ / mismatch=0 / && $0 ~ / broken=0 interp_mismatch=0/ && m > 0 && (f == 0 || (s >= 66 && 4 * m >= 3 * c))) n++ }
   END { print n + 0 }')
if [[ $rc -eq 0 && $n -eq $want ]]; then echo "PASS test_native_post ($n gates)"; else echo "FAIL test_native_post ($n of $want gates)"; exit 1; fi
