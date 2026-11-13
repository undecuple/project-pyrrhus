#!/usr/bin/env bash
# Host test for patches 2300 and 2301 (internal resolution scale groundwork and its switch): the checked mapping header
# libs/video/rsx_internal_scale.h, and wiring checks on rsx_live_draw.c: physical extents are recorded but take no part
# in surface lookup, aliases or guest texture sizes, the pipeline key and the PSO template record do not see the scale,
# and the header stays free of platform and port code; RSX_INTERNAL_SCALE is read once, parsed by the header and not yet
# active. Needs $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh).
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_internal_scale_map.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched/libs/video"
H=$PT/rsx_internal_scale.h; LD=$PT/rsx_live_draw.c
[[ -f $H ]] || { echo "FAIL no $H (run tools/ps3recomp-patched.sh)"; exit 1; }
O=work/runtime/test; mkdir -p "$O"
${CC:-cc} -O2 -std=c99 -Wall -Wextra -Werror -I$PT -o $O/test_internal_scale_map tools/runtime/test_internal_scale_map.c \
  || { echo "FAIL build"; exit 1; }
$O/test_internal_scale_map || exit 1

fail=0
bad() { echo "FAIL $*"; fail=1; }

# The header can be copied to another port as is: standard headers only, no platform, graphics API or game names.
inc=$(grep -E '^[[:space:]]*#[[:space:]]*include' "$H" | grep -v '<stdint.h>')
[[ -z $inc ]] || bad "rsx_internal_scale.h includes more than <stdint.h>: $inc"
grep -qiE 'd3d|dxgi|windows\.h|vulkan|metal|kz2|kz3|killzone|pyrrhus|helghast' "$H" && bad "rsx_internal_scale.h names a platform or a port"

# Physical extents are only written in this patch: every line naming one is its declaration or an assignment to it.
# Surface lookup, alias matching, feedback copies and guest texture sizes keep using w/h (guest sample space).
reads=$(grep -nE 'phys_[wh]\b' "$LD" | grep -vE '(->|\.|g\.depth_)phys_[wh] = |u32 +(depth_)?phys_w, (depth_)?phys_h;')
[[ -z $reads ]] || bad "a physical extent is read outside its assignment:
$reads"
grep -qE 's->w = want_w; s->h = want_h;' "$LD" || bad "colour surfaces no longer record their guest sample size in w/h"
grep -qE 's->phys_w = phys\.w; s->phys_h = phys\.h;' "$LD" || bad "colour surfaces do not record their physical size"
grep -qE 'z->phys_w = zphys\.w; z->phys_h = zphys\.h;' "$LD" || bad "zeta surfaces do not record their physical size"
grep -qE 'g\.depth_phys_w = width; g\.depth_phys_h = height;' "$LD" || bad "the shared depth does not record its physical size"

# The internal scale is native in this patch, and the pipeline key (ld_pso_key_tail) and the PSO template record
# (ld_pt_note) do not see it: warm caches stay warm. Patch 2088's grid stays in both, as before.
grep -qF 'static rsx_iscale_grid ld_iscale(void) { return rsx_iscale_native(); }' "$LD" || bad "ld_iscale is not native"
body() { awk -v f="$1" '$0 ~ "^static .*"f"\\(" {on=1} on {print} on && /^}/ {exit}' "$LD"; }
for f in ld_pso_key_tail ld_pt_note; do
  b=$(body $f); [[ -n $b ]] || { bad "no $f in rsx_live_draw.c"; continue; }
  grep -qE 'iscale|phys_' <<<"$b" && bad "$f depends on the internal scale"
done
grep -qF 'key = fnv1a(&xi->wpos_aa, sizeof xi->wpos_aa, key)' <<<"$(body ld_pso_key_tail)" || bad "the AA grid left the pipeline key"
grep -qF '((xi->wpos_aa & 0xFFFFu) << RSX_PT_WPOS_AA_SHIFT)' <<<"$(body ld_pt_note)" || bad "the AA grid left the template record"
# The shader-side conversions compose the AA grid with the native scale only (a scaled grid needs its key first).
n=$(grep -cF 'ld_wpos_divisor(wpos_aa, rsx_iscale_native(), &d)' "$LD")
[[ $n == 2 ]] || bad "WPOS and DDX/DDY do not both take their divisor from ld_wpos_divisor at the native scale ($n)"

# Patch 2301: RSX_INTERNAL_SCALE is read in one place, parsed by the header, read at start, and not yet active.
n=$(grep -cF 'getenv("RSX_INTERNAL_SCALE")' "$LD")
[[ $n == 1 ]] || bad "RSX_INTERNAL_SCALE is read $n times (want 1, in ld_iscale_requested)"
grep -qF 'rsx_iscale_parse_switch(e, &req)' <<<"$(body ld_iscale_requested)" || bad "RSX_INTERNAL_SCALE is not parsed by rsx_iscale_parse_switch"
grep -qF '(void)ld_iscale_requested();' "$LD" || bad "RSX_INTERNAL_SCALE is not read and logged at start"
grep -qE 'ENHANCEMENT:.*RSX_INTERNAL_SCALE' "$LD" || bad "RSX_INTERNAL_SCALE is not marked ENHANCEMENT:"

(( fail == 0 )) || exit 1
echo "test_internal_scale_map.sh: ok"
