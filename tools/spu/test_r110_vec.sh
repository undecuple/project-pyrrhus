#!/usr/bin/env bash
# From Project Helghast tools/spu/test_r110_vec.sh (patch(es) 1131 host test; the patched toolkit is $KZ2_PATCHED_DIR or $KZ2_OUT/ps3recomp-patched,
# default work/; one binary per ISA instead of a delete-and-rebuild). The vector helpers against the per-lane loops they
# replaced, built three ways: the port's SPU flags (-O2 -msse4.1 -mfma, no FP contraction), + -mavx2, and without SSE4.1.
# No game data.
#   nix develop --command tools/sandbox.sh -- tools/spu/test_r110_vec.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/work/spu/t_r110_vec"; mkdir -p "$O"
P="${KZ2_PATCHED_DIR:-$ROOT/${KZ2_OUT:-work}/ps3recomp-patched}"
if ! grep -q "spu__fi_ref" "$P/runtime/spu/spu_helpers.h" 2>/dev/null; then echo "SKIP: $P has no patch 1131"; exit 0; fi
grep -qw fma /proc/cpuinfo || { echo "SKIP: host CPU without FMA"; exit 0; }
rc=0; k=0
for isa in "-msse4.1 -mfma" "-msse4.1 -mfma -mavx2" "-mno-sse4.1"; do
  k=$((k + 1)); echo "== $isa"
  gcc -std=gnu17 -O2 $isa -w -ffp-contract=off -fno-strict-aliasing -I "$P/runtime/spu" -I "$P/include" -I "$P/runtime" \
      -o "$O/t$k" "$ROOT/tools/spu/test_r110_vec.c" -lm || { echo "build failed"; rc=1; continue; }
  "$O/t$k" || rc=1
done
[[ $rc == 0 ]] && echo "test_r110_vec: PASS" || echo "test_r110_vec: FAIL"
exit $rc
