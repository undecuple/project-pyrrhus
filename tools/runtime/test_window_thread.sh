#!/usr/bin/env bash
# Host test for KZ2 patch 2124 (the live renderer's window on a thread of its own): the wiring in
# the patched libs/video/rsx_null_backend.c and port/kz2/main.cpp's frame-call timing. No game data, no GPU; the
# behaviour itself is checked under Proton (the RE notes "An earlier change").
#   nix develop --command tools/sandbox.sh -- tools/runtime/test_window_thread.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
P=""
for d in ${KZ2_PATCHED_DIR:+"$KZ2_PATCHED_DIR"} ${KZ2_OUT:+"$KZ2_OUT/ps3recomp-patched"} work/ps3recomp-patched work/runtime/ps3recomp-patched; do
  [[ -f "$d/libs/video/rsx_null_backend.c" ]] && grep -q "patch 2124" "$d/libs/video/rsx_null_backend.c" && { P="$d"; break; }
done
[[ -n "$P" ]] || { echo "SKIP test_window_thread: no patched toolkit with patch 2124 here (run tools/ps3recomp-patched.sh)"; exit 0; }
# python3, else python, else py -3: on Windows python3 is often the Microsoft Store alias (issue #9)
PY=()
for c in "python3" "python" "py -3"; do
  read -r -a cand <<<"$c"
  if "${cand[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)' >/dev/null 2>&1; then
    PY=("${cand[@]}"); break
  fi
done
(( ${#PY[@]} )) || { echo "FAIL: no Python 3.6 or newer (tried python3, python, py -3)"; exit 1; }
"${PY[@]}" - "$P/libs/video/rsx_null_backend.c" "$P/libs/video/rsx_live_draw.c" port/kz2/main.cpp <<'PY'
import re, sys
nb, ld, mc = (open(p).read() for p in sys.argv[1:4])
fails = []
def check(ok, what):
    print(("[PASS] " if ok else "[FAIL] ") + what)
    if not ok: fails.append(what)
def func(src, name):
    """Body of the C function `name` (first definition), by brace matching."""
    m = re.search(r"^[A-Za-z].*?\b" + re.escape(name) + r"\([^;{]*\)\s*\{", src, re.M)
    if not m: return ""
    i, depth = m.end() - 1, 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0: return src[i:j + 1]
    return ""
init = func(nb, "rsx_null_backend_init")
check('getenv("KZ2_WINDOW_THREAD")' in init and "CreateThread" in init and "rsx_window_thread" in init
      and "WaitForSingleObject(s_wt_args.ready" in init, "init starts the window thread (KZ2_WINDOW_THREAD) and waits for the window")
check("null_create_window(width, height, title)" in init, "init keeps the old path (KZ2_WINDOW_THREAD=0 or no thread)")
wt = func(nb, "rsx_window_thread")
m = re.search(r"MsgWaitForMultipleObjects\(0, NULL, FALSE, (\d+), QS_ALLINPUT\)", wt)
check(m is not None and int(m.group(1)) <= 50, "window thread waits for messages at most 50 ms at a time")
check("null_create_window(" in wt and "DispatchMessageA" in wt and "rsx_dm_script_step()" in wt and "rsx_null_title_tick()" in wt,
      "window thread creates the window, dispatches, runs the display test steps and the caption")
check("rsx_live_draw_set_fullscreen" not in wt and "WaitForSingleObject" not in wt and "rsx_live_draw_present" not in wt,
      "window thread itself never calls the swap chain or waits on an object")
# Every swap-chain call reachable from the window procedure is behind `if (s_wt_on)`: in these functions each
# rsx_live_draw_set_fullscreen( call must sit after an `if (s_wt_on)` that returns or is an `else` of one.
for name in ("rsx_dm_apply", "rsx_dm_apply_window", "rsx_dm_wndmsg"):
    body = func(nb, name)
    calls = [mm.start() for mm in re.finditer(r"rsx_live_draw_set_fullscreen\(", body)]
    ok = bool(body)
    for c in calls:
        before = body[:c]
        g = before.rfind("if (s_wt_on)")
        ok = ok and g >= 0 and ("return;" in before[g:] or "else" in before[g:])
    check(ok, f"{name}: swap-chain calls only on the window-on-the-frame-thread path")
pump = func(nb, "rsx_null_backend_pump_messages")
wtb = pump[pump.find("if (s_wt_on)"):pump.find("rsx_dm_script_step")]
check("InterlockedExchange(&s_wt_fs_req, -1)" in wtb and "rsx_live_draw_set_fullscreen(" in wtb
      and "PostMessageA(s_state.hwnd, RSX_DM_WM_FSDONE" in wtb and "PeekMessage" not in wtb,
      "frame thread's pump: takes the request, calls the swap chain, posts the answer, takes no message")
check("RSX_DM_WM_FSDONE) { rsx_dm_fs_done(" in nb, "window procedure takes the answer (RSX_DM_WM_FSDONE)")
done = func(nb, "rsx_dm_fs_done")
check("s_dm_next_m" in done and "rsx_dm_apply(m, s_dm_next_why)" in done, "a mode chosen while a request is out runs after the answer")
close = nb[nb.find("case WM_CLOSE:"):nb.find("case WM_DESTROY:")]
check("if (s_wt_on) { ShowWindow(hwnd, SW_HIDE); return 0; }" in close and "window_closed = 1" in close,
      "WM_CLOSE with the window thread: hide, flag, no DestroyWindow under a Present")
check("void rsx_live_draw_pso_await_totals(unsigned long long* n, unsigned long long* us)\n{" in ld
      and "*n = (unsigned long long)g_apso.awaits;" in ld and ld.count("rsx_live_draw_pso_await_totals(") == 2,
      "live renderer exports its pipeline-build waits (Windows and the stub)")
fc = mc[mc.index("static DWORD WINAPI frame_clock(LPVOID)"):]
fc = fc[:fc.index("\n}\n")]
check(fc.count("kz2_fc_end(KZ2_FC_DRAIN") == 2 and fc.count("kz2_fc_end(KZ2_FC_PUMP") == 2
      and fc.count("kz2_fc_end(KZ2_FC_PRESENT") == 3, "frame_clock times every drain, pump and flip present")
check(len(re.findall(r"cellGcm_rsx_process_fifo\(\)", fc)) == 2 and len(re.findall(r"present_guest_frame\(\)", fc)) == 3,
      "no untimed drain or flip present left in frame_clock")
print("PASS: test_window_thread" if not fails else f"FAIL: {len(fails)} check(s)")
sys.exit(1 if fails else 0)
PY
