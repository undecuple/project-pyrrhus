#!/usr/bin/env bash
# Patch 1095 host test: tools/spu/test_spurs_teardown.c (SPURS workload Shutdown / WaitForWorkloadShutdown / Remove and
# SetPriorities on the instance bytes the default kernel reads, runtime/spu/spurs_wkl_teardown.h, checked through
# kz3_ksel / kz3_kleave of spurs_kern_sched.h), plus a source check that libs/spurs/cellSpurs.c uses them only under
# KZ2_SPURS_TEARDOWN. Needs a patched toolkit with patch 1095 ($KZ2_OUT/ps3recomp-patched, default work/, or
# KERN_HDR=DIR holding both headers); says SKIP without it.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_spurs_teardown.sh
#   KZ2_OUT=work/spu ... (the SPU's tree)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/${KZ2_OUT:-work}"; mkdir -p "$O"
H="${KERN_HDR:-$O/ps3recomp-patched/runtime/spu}"
[[ -f "$H/spurs_wkl_teardown.h" ]] || { echo "SKIP: no patched toolkit with patch 1095 at $H"; exit 0; }
gcc -std=gnu17 -O2 -Wall -Wextra -I "$H" -o "$O/t_spurs_teardown" "$ROOT/tools/spu/test_spurs_teardown.c" 2>&1 | grep -m5 -E "error|warning"
[[ -x "$O/t_spurs_teardown" ]] || { echo "FAIL: build"; exit 1; }
"$O/t_spurs_teardown"; rc=$?
C="$H/../../libs/spurs/cellSpurs.c"
if [[ -f "$C" ]]; then
  for s in "kz2_wkl_shutdown(vm_base" "kz2_wkl_wait_step(vm_base" "kz2_wkl_remove(vm_base" "kz2_wkl_set_priorities(vm_base" \
           "kz2_wkl_pm_forget(wid)" 'getenv("KZ2_SPURS_TEARDOWN")'; do
    grep -qF "$s" "$C" || { echo "FAIL: cellSpurs.c lacks $s"; rc=1; }
  done
  n=$(grep -c "kz2_spurs_teardown()" "$C"); [[ $n -ge 6 ]] || { echo "FAIL: only $n flag checks in cellSpurs.c"; rc=1; }
fi
[[ $rc -eq 0 ]] && echo "PASS test_spurs_teardown.sh" || echo "FAIL test_spurs_teardown.sh"
exit $rc
