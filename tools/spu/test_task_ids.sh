#!/usr/bin/env bash
# KZ2 host test for patch 7004 (tools/spu/test_task_ids.c): tasks started by the taskset exit scan
# run as their own task id while another thread writes the CreateTask bridge globals. Needs work/ps3recomp-patched
# (SPU_TREE=DIR); SKIP without it. The second run (SPU_TASK_IDS_GLOBAL=1, the pre-7004 hand-over) is printed as
# evidence of the race and does not decide PASS (it is a race: it may or may not hit in one run).
#   nix develop --command tools/sandbox.sh -- tools/spu/test_task_ids.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/work/spu"; mkdir -p "$O"
T="${SPU_TREE:-$ROOT/${KZ2_OUT:-work}/ps3recomp-patched}"
[[ -f "$T/runtime/spu/spu_workload.c" ]] || { echo "SKIP: no patched toolkit at $T"; exit 0; }
grep -q "spu_dispatch_async_ids" "$T/runtime/spu/spu_workload.c" || { echo "FAIL: $T has no patch 7004 (spu_dispatch_async_ids)"; exit 1; }
B="runtime/spu/spu_drain.c runtime/spu/spu_lockstep.c runtime/spu/spu_coherency.c runtime/spu/spu_workload.c runtime/spu/spurs_policy.c runtime/spu/spurs_job.c runtime/spu/spu_tsp_weak.c runtime/spu/spu_vm_pagemap.c runtime/spu/spurs_policy_blob_weak.c runtime/spu/spu_interp.c runtime/platform/win32_compat.c"
extra=""; [[ -f "$T/runtime/diag/kz3_wait_acct.c" ]] && extra="runtime/diag/kz3_wait_acct.c -I runtime/diag"
rm -f "$O/t_task_ids"
(cd "$T" && gcc -std=gnu17 -O2 -w -pthread -I include -I runtime/spu -I runtime/platform -o "$O/t_task_ids" \
    "$ROOT/tools/spu/test_task_ids.c" $B $extra -lm 2>&1 | grep -m8 error)
[[ -x "$O/t_task_ids" ]] || { echo "FAIL: build"; exit 1; }
old="$(SPU_TASK_IDS_GLOBAL=1 timeout 120 "$O/t_task_ids" 2>/dev/null | grep -m1 "^test_task_ids\|^round")"
echo "old hand-over (evidence only): ${old:-no result}"
out="$(timeout 120 "$O/t_task_ids" 2>"$O/t_task_ids.err")"; r=$?
echo "$out" | tail -4; grep -m3 "MISMATCH" "$O/t_task_ids.err"
[[ $r == 0 ]] && echo PASS || echo FAIL
exit $r
