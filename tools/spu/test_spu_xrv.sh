#!/usr/bin/env bash
# KZ2 patch 7021 host test (tools/spu/test_spu_xrv.c): the exact vector exponent-255 paths (KZ2_SPU_XRV)
# bit for bit against the 1089/1071 paths, built twice with the port's SPU flags: -O2 -msse4.1, and with -mfma (the
# default build, KZ2_SPU_FMA). No game data. XRV_STEP=1 sweeps every exponent-255 word (about 4 min per build).
#   nix develop --command tools/sandbox.sh -- tools/spu/test_spu_xrv.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; O="$ROOT/work/spu"; mkdir -p "$O"
P="${KZ2_PATCHED_DIR:-$ROOT/${KZ2_OUT:-work}/ps3recomp-patched}"
[[ -f "$P/runtime/spu/spu_context.h" ]] || { echo "SKIP: no patched toolkit at $P (run tools/ps3recomp-patched.sh)"; exit 0; }
grep -q "spu__xrv_fma" "$P/runtime/spu/spu_helpers.h" || { echo "FAIL: $P has no patch 7021 (spu__xrv_fma)"; exit 1; }
rc=0
for isa in "-msse4.1" "-msse4.1 -mfma"; do
  B="$O/t_spu_xrv"; [[ -e "$B" ]] && "$ROOT/tools/safe_rm.sh" "$B" >/dev/null
  gcc -std=gnu17 -O2 $isa -w -ffp-contract=off -fno-strict-aliasing -I "$P/runtime/spu" -I "$P/include" -I "$P/runtime" \
      -o "$B" "$ROOT/tools/spu/test_spu_xrv.c" -lm 2>&1 | grep -m5 error
  echo "== $isa"
  "$B" || rc=1
done
exit $rc
