#!/usr/bin/env bash
# Host test for patch 6052 (FSR 1 before the HUD): the visit rule (libs/video/rsx_pre_hud.h) on Killzone 2's frame
# order, and its wiring in the live draw. Needs $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh).
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_pre_hud.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched/libs/video"
[[ -f $PT/rsx_pre_hud.h ]] || { echo "FAIL no $PT/rsx_pre_hud.h (run tools/ps3recomp-patched.sh)"; exit 1; }
O=work/runtime/test; mkdir -p "$O"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -O1 -fsanitize=address,undefined -I"$PT" tools/runtime/test_pre_hud.c -o "$O/test_pre_hud"
"$O/test_pre_hud"
L=$PT/rsx_live_draw.c
for want in 'ld_ph_draw(target);   /\* patch 6052' 'ld_ph_redirect(target, n_mrt, &rtv, &dsv, &have_dsv, &ph_sx, &ph_sy)' \
            'rsx_upscale_pre_hud(up, &ev, &ur)' 'ld_ph_present_src(target, &ph_state)' 'ld_ph_frame_end();   /\* patch 6052 \*/' \
            'ld_ph_clear(target, &rtv, &crect, n_crect, mask)'; do
  grep -q "$want" "$L" || { echo "[FAIL] live draw lacks: $want"; exit 1; }
done
# the redirect scales the viewport and the scissor before they are set
awk '/if \(g_ph_cur\) \{   \/\* patch 6052: the HUD target/{a=NR} /RSSetViewports\(g.list, 1, &dvp\)/{if(a&&!v)v=NR} END{exit !(a && v && a < v)}' "$L" \
  || { echo "[FAIL] viewport scale not before RSSetViewports"; exit 1; }
echo "PASS: wiring"
