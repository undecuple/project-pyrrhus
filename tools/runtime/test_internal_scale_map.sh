#!/usr/bin/env bash
# Host test for patches 2300, 2301 and 6082 (internal resolution scale: groundwork, switch, the 2x path): the checked
# mapping header libs/video/rsx_internal_scale.h, and wiring checks on rsx_live_draw.c: physical extents take no part
# in surface lookup, aliases or guest texture sizes; the scale is set once before the first host resource; every
# guest-visible boundary goes through the native-size guards; the scale enters pipeline keys only when it is not 1x;
# FSR 1 is refused at 2x; the header stays free of platform and port code; RSX_INTERNAL_SCALE is read once and parsed
# by the header. Needs $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh).
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

# Guest identity stays in guest sample space: surface lookup and alias matching compare w/h, never a physical extent.
grep -qE 's->w = want_w; s->h = want_h;' "$LD" || bad "colour surfaces no longer record their guest sample size in w/h"
grep -qE 'g\.surfaces\[i\]\.w == want_w && g\.surfaces\[i\]\.h == want_h' "$LD" || bad "surface lookup no longer keys on w/h"
grep -qE 's->phys_w = phys\.w; s->phys_h = phys\.h;' "$LD" || bad "colour surfaces do not record their physical size"
grep -qE 'z->phys_w = zphys\.w; z->phys_h = zphys\.h;' "$LD" || bad "zeta surfaces do not record their physical size"
grep -qE 'g\.depth_phys_w = \(u32\)drd\.Width; g\.depth_phys_h = drd\.Height;' "$LD" || bad "the shared depth does not record its physical size"
# The last definition of a function (the stubs for other platforms come first): from its first line to the closing
# brace; a prototype (a line ending in ";" before any brace) is skipped.
body() { awk -v f="$1" '
  !on && $0 ~ "^[a-zA-Z_].*[ *]"f"[(]" { on=1; open=0; cur="" }
  on { cur = cur $0 "\n"
       if (!open && $0 ~ /;[[:space:]]*$/ && $0 !~ /[{]/) { on=0; next }
       if ($0 ~ /^[{].*[}][[:space:]]*$/) { last=cur; on=0; next }
       if ($0 ~ /^[{]/ || $0 ~ /[)][[:space:]]*[{][[:space:]]*$/) open=1
       if (open && $0 ~ /^[}]/) { last=cur; on=0 }
       next }
  END { printf "%s", last }' "$LD"; }
for f in surface_containing ld_ph_display_index; do
  b=$(body $f); [[ -n $b ]] || { bad "no $f in rsx_live_draw.c"; continue; }
  grep -qE 'phys_|snap_p' <<<"$b" && bad "$f (guest identity) reads a physical extent"
done
grep -qF 'unnorm_dim[uu][0] = ut.width;' "$LD" || bad "unnormalised texture sizes are no longer the guest's"

# Patch 6082: the scale is live state, set once at start before the shared depth and the first surface are made.
grep -qF 'static rsx_iscale_grid ld_iscale(void) { return g_ld_iscale; }' "$LD" || bad "ld_iscale does not return the live scale"
n=$(grep -cF 'ld_iscale_activate();' "$LD"); [[ $n == 1 ]] || bad "ld_iscale_activate is called $n times (want 1)"
la=$(grep -nF 'ld_iscale_activate();' "$LD" | head -1 | cut -d: -f1)
ld=$(grep -nF 'drd.Width = ld_isx(width)' "$LD" | head -1 | cut -d: -f1)
[[ -n $la && -n $ld && $la -lt $ld ]] || bad "the scale is not set before the shared depth is made"
grep -qF 'rd.Width = phys.w; rd.Height = phys.h;' "$LD" || bad "colour surfaces are not allocated at their physical extent"
grep -qF 'rd.Width = zphys.w;' "$LD" || bad "zeta surfaces are not allocated at their physical extent"

# The game only ever sees its own resolution (issue #55): every path out of a surface to the guest or the CPU reads
# the native-size view (ld_is_down), guest uploads are expanded (ld_is_up_rows), report counts are divided.
for f in ld_rb_record rsx_live_draw_debug_read_surface ld_movie_capture_overlay; do
  grep -qF 'ld_is_down(' <<<"$(body $f)" || bad "$f copies a surface out without ld_is_down"
done
grep -qF 'ld_is_up_rows(' <<<"$(body ld_gv_upload_rows)" || bad "ld_gv_upload_rows does not expand into a scaled surface"
grep -qF 'ld_is_count(c)' <<<"$(body ld_rb_drain)" || bad "report counts reach the guest undivided"
grep -qF 'rsx_iscale_count_to_guest(v, g_ld_iscale)' "$LD" || bad "ld_is_count does not use the header's rounding"

# Pipeline keys and templates: the scale enters the key only when it is not native, so 1x keys (and warm caches) are
# unchanged; the template records (no scale field) are written at 1x only and prewarmed for the live scale.
b=$(body ld_pso_key_tail)
grep -qF 'key = fnv1a(&xi->wpos_aa, sizeof xi->wpos_aa, key)' <<<"$b" || bad "the AA grid left the pipeline key"
grep -qE '^ *if \(xi->iscale\) \{ const u32 tag' <<<"$b" || bad "the scale is not keyed under if (xi->iscale)"
[[ $(grep -c 'iscale' <<<"$b") == 2 ]] || bad "ld_pso_key_tail uses the scale outside its keyed block"
b=$(body ld_pt_note)
grep -qF '((xi->wpos_aa & 0xFFFFu) << RSX_PT_WPOS_AA_SHIFT)' <<<"$b" || bad "the AA grid left the template record"
grep -qF 'if (xi->iscale) return;' <<<"$b" || bad "templates are written from a scaled session"
grep -qF 'static u32 ld_xl_iscale(void) { return ld_iscale_on() ?' "$LD" || bad "the key's scale field is not 0 at the native scale"
# Shader side: WPOS and DDX/DDY compose the AA grid with the live scale; the 1x WPOS text is the old one.
n=$(grep -cF 'ld_wpos_divisor(wpos_aa, scale, &d)' "$LD")
[[ $n == 2 ]] || bad "WPOS and DDX/DDY do not both take their divisor from ld_wpos_divisor with the scale ($n)"
n=$(grep -cF 'ld_xl_grid(in->iscale)' "$LD"); [[ $n == 2 ]] || bad "ld_xlate does not pass the scale to WPOS and DDX/DDY ($n)"
grep -qF '"float4(floor(input.position.xy / float2(%u.0, %u.0)) + 0.5, input.position.zw)"' "$LD" || bad "the 1x WPOS text changed"

# FSR 1 and the internal scale are exclusive, checked in ld_up_get (every frame: menu toggles included).
grep -qF 'if (be != RSX_UPSCALE_NONE && ld_iscale_on())' <<<"$(body ld_up_get)" || bad "FSR 1 is not refused at 2x"

# Patch 2301: RSX_INTERNAL_SCALE is read in one place, parsed by the header, and marked ENHANCEMENT:.
n=$(grep -cF 'getenv("RSX_INTERNAL_SCALE")' "$LD")
[[ $n == 1 ]] || bad "RSX_INTERNAL_SCALE is read $n times (want 1, in ld_iscale_requested)"
grep -qF 'rsx_iscale_parse_switch(e, &req)' <<<"$(body ld_iscale_requested)" || bad "RSX_INTERNAL_SCALE is not parsed by rsx_iscale_parse_switch"
grep -qF 'g_ld_iscale = ld_iscale_requested();' "$LD" || bad "the live scale is not the switch's"
grep -qE 'ENHANCEMENT:.*RSX_INTERNAL_SCALE' "$LD" || bad "RSX_INTERNAL_SCALE is not marked ENHANCEMENT:"

(( fail == 0 )) || exit 1
echo "test_internal_scale_map.sh: ok"
