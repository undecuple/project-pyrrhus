#!/usr/bin/env bash
# Patch 7023 host test (tools/spu/test_ovl_exact_region.c): a GET that matches a verified streamed region exactly
# (source EA and load address) takes that region although the image's header signature was registered first; the
# same image at another address or from another EA still takes the signature entry; changed bytes do not verify.
# Fails on a toolkit without patch 7023 (SPU_TREE=DIR to point at one). SKIP without a patched toolkit.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_ovl_exact_region.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/work/spu"; mkdir -p "$O"
T="${SPU_TREE:-$ROOT/${KZ2_OUT:-work}/ps3recomp-patched}"
[[ -f "$T/runtime/spu/spu_channels.c" ]] || { echo "SKIP: no patched toolkit at $T"; exit 0; }
B="runtime/spu/spu_drain.c runtime/spu/spu_lockstep.c runtime/spu/spu_coherency.c runtime/spu/spu_workload.c runtime/spu/spurs_policy.c runtime/spu/spurs_job.c runtime/spu/spu_tsp_weak.c runtime/spu/spu_vm_pagemap.c runtime/spu/spurs_policy_blob_weak.c runtime/spu/spu_interp.c runtime/platform/win32_compat.c"
extra=""; [[ -f "$T/runtime/diag/kz3_wait_acct.c" ]] && extra="runtime/diag/kz3_wait_acct.c -I runtime/diag"
rm -f "$O/t_ovl_exact"
(cd "$T" && gcc -std=gnu17 -O2 -w -pthread -I include -I runtime/spu -I runtime/platform -o "$O/t_ovl_exact" \
    "$ROOT/tools/spu/test_ovl_exact_region.c" $B $extra -lm 2>&1 | grep -m8 error)
[[ -x "$O/t_ovl_exact" ]] || { echo "FAIL: build"; exit 1; }
"$O/t_ovl_exact" 2>&1 | grep -v "^\[spu-ovl\]" | tail -12; r=${PIPESTATUS[0]}
[[ $r == 0 ]] && echo PASS || echo FAIL
exit $r
