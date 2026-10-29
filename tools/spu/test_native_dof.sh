#!/usr/bin/env bash
# Spu an earlier change host test: the native Gfx.Post.DepthOfField kernels (port/kz2/spu/native_dof.c) against the lifted
# code and the SPU interpreter on synthetic inputs (tools/spu/native_diff.py synth --interp): every case must leave the
# whole local store and the preserved registers equal. Needs the SPU lift ($KZ2_OUT/spu/lift, the main checkout's
# work/spu/lift; KZ2_OUT=work/spu in the SPU) and the patched toolkit; no game data in git.
#   nix develop .#re --command tools/sandbox.sh -- tools/spu/test_native_dof.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${KZ2_OUT:-work}"; case "$OUT" in /*) ;; *) OUT="$ROOT/$OUT" ;; esac
L="$OUT/spu/lift/job_00d6d100/spu_recomp.c"
if [[ ! -f "$L" ]]; then echo "SKIP: no DepthOfField lift at $L (tools/spu/lift_spu.sh)"; exit 0; fi
out=$(python3 "$ROOT/tools/spu/native_diff.py" synth --slot 0 --slot 1 --slot 2 --trials "${TRIALS:-300}" --interp 2>&1); rc=$?
echo "$out" | tail -12
n=$(echo "$out" | grep -c "match=[1-9][0-9]* mismatch=0 fallback=0 broken=0 interp_mismatch=0")
if [[ $rc -eq 0 && $n -eq 3 ]]; then echo "PASS test_native_dof ($n gates)"; else echo "FAIL test_native_dof"; exit 1; fi
