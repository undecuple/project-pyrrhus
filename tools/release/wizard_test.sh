#!/usr/bin/env bash
# Inno Setup under Proton, headless (from Project Helghast tools/release/wizard_test.sh; not run for KZ2 yet): install
# ISCC into a private prefix, compile
# installer/kz2.iss, and walk the produced setup wizard page by page with screenshots. Never ships; ISCC is an
# approved build tool (KZ3) that is never committed and never in the payload. No network, Xvfb only, muted.
#
#   nix develop --command tools/release/wizard_test.sh install [VERSION]     (default 6.7.3; reads work/release/wizard/dl)
#   nix develop --command tools/release/wizard_test.sh compile PAYLOAD OUTDIR [ISCC /D args...]
#   nix develop --command tools/release/wizard_test.sh wizard SETUP.exe SHOTDIR [fail|stop|real|tasks]
#   nix develop --command tools/release/wizard_test.sh batch FILE   (several walks under one gpu lock; FILE
#       is sourced inside the sandbox, each `run MODE ARGS...` line runs one mode, env assignments before it apply)
#   nix develop --command tools/release/wizard_test.sh tasks SETUP.exe SHOTDIR        (the tasks page at
#       96 and 144 DPI, default and /TASKS=...portable, each walk cancelled after the page; KZ2_WT_DPIS="96 144")
#   KZ2_WT_PAYLOAD=DIR KZ2_WT_GAME=DIR nix develop --command tools/release/wizard_test.sh launcher SHOTDIR
#       (KZ2_WT_INI_EXTRA='[display]\nmode = fullscreen\n' adds sections to its kz2-install.ini)
#       (the real launcher exe in a staged install starting the game; GAME holds kz2.exe, its DLLs and PS3_GAME)
#   nix develop --command tools/release/wizard_test.sh uninstall SHOTDIR              (unins000.exe of the
#       install in KZ2_WT_STATE, walked with shots; before/after facts of the dump (KZ2_WT_DUMPDIR, a Linux path), the
#       install folder and the saves in SHOTDIR/facts-*.txt)
#   KZ2_WT_NOGPU=1 KZ2_WT_STATE=DIR nix develop --command tools/release/wizard_test.sh vmtest KIT PYDIR STEP...
#       (the Windows VM kit's vm_test.py steps under Proton in a fresh prefix; KZ2_WT_VMARGS adds arguments)
#   nix develop --command tools/release/wizard_test.sh zip ZIP SHOTDIR                (the portable zip
#       unpacked into KZ2_WT_STATE's C:\Games, run.cmd fed the answers, then the zip's launcher with KZ2_WT_PAD as
#       PAD_SCRIPT for KZ2_WT_PLAY s, a shot every 30 s)
#
# State: work/release/wizard/compat (the prefix; KZ2_WT_STATE=DIR uses DIR/compat instead, e.g. a fresh prefix for a
# real install; the ISCC installer download stays in work/release/wizard/dl). Takes the gpu lock and the sandbox itself
# (never wrap it). Xvfb runs with -dpi 96; KZ2_WT_DPI changes it. Fixture: tools/release/wizard_test/demo_firstrun.py.
# "real": the pages get KZ2_WT_DUMP / KZ2_WT_UPDATE / KZ2_WT_EBOOT (Z:\ paths of a real dump, update and EBOOT,
# read in place through the sandbox's read-only binds) instead of the empty markers, the build runs to its RESULT
# line (polled in the log next to SETUP.exe, a shot every minute, at most KZ2_WT_REAL_MAX s, default 3600), then
# Finish starts the installed launcher ("Start Project Pyrrhus" stays checked) and the display is shot after
# KZ2_WT_PLAY s (default 90). Wall times go to SHOTDIR/times.txt. KZ2_WT_KEEP=1 keeps an earlier install
# (install over it), KZ2_WT_TASKS passes /TASKS=..., KZ2_WT_WINEDPI sets Wine's LogPixels (96 = 100 %, 144 = 150 %).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROTON_DIR="${KZ2_WT_PROTON:-$HOME/.local/share/Steam/compatibilitytools.d/Proton-GE Latest}"
WT="$ROOT/work/release/wizard"
STATE="${KZ2_WT_STATE:-$WT}"

if [[ "${1:-}" != --inner ]]; then
  mkdir -p "$STATE/compat" "$STATE/steam"
  LOCK=(); [[ -x "$ROOT/tools/agents/lock.sh" ]] && LOCK=("$ROOT/tools/agents/lock.sh" gpu --)   # shared-GPU lock, when present
  GPU=(--gpu)
  # KZ2_WT_LAVAPIPE=1: Mesa's CPU Vulkan driver only (/run/opengl-driver read-only, no device nodes, no gpu lock;
  # VK_ICD_FILENAMES set inside): vkd3d-proton gets a device without the GPU (the vkd3d mode)
  # KZ2_WT_NOGPU=1: no GPU device and no gpu lock, for runs that draw nothing that needs one (the ISCC compile, the
  # vmtest mode's silent install and scripted steps); Wine renders to Xvfb in software either way.
  [[ "${KZ2_WT_NOGPU:-0}" == 1 ]] && { LOCK=(); GPU=(); }
  [[ "${KZ2_WT_LAVAPIPE:-0}" == 1 ]] && { LOCK=(); GPU=(--ro /run/opengl-driver); }
  # KZ2_WT_RO_INSTALL=1: the prefix's install folder bound read-only (chmod is not enforced in the sandbox's user
  # namespace: the vkd3d mode's chmod run still wrote there)
  [[ "${KZ2_WT_RO_INSTALL:-0}" == 1 ]] && GPU+=(--ro "$STATE/compat/pfx/drive_c/users/steamuser/AppData/Local/Programs/Project Pyrrhus")
  exec "${LOCK[@]}" "$ROOT/tools/sandbox.sh" "${GPU[@]}" --ro "$PROTON_DIR" -- \
    bash "$0" --inner "$@"
fi
shift
MODE="${1:?mode}"; shift

export DISPLAY=:98
XVFB=""   # a nested walk (the tasks mode) reuses the display of the walk that started it
if [[ ! -e /tmp/.X11-unix/X98 ]]; then
  Xvfb :98 -screen 0 1280x800x24 -dpi "${KZ2_WT_DPI:-96}" -nolisten tcp >/dev/null 2>&1 &
  XVFB=$!
fi
for _ in $(seq 50); do [[ -e /tmp/.X11-unix/X98 ]] && break; sleep 0.1; done
export STEAM_COMPAT_DATA_PATH="$STATE/compat" STEAM_COMPAT_CLIENT_INSTALL_PATH="$STATE/steam"
# The 32-bit side of steam-run has no libfreetype (no /usr/lib32/libfreetype.so.6): an old-WoW64 32-bit program
# such as Inno Setup gets no TrueType fonts, so dialog metrics are 0 ("AnchorOuterPage: BaseUnitX = 0"). New WoW64
# runs 32-bit programs on the 64-bit Unix libraries, which have it.
export PROTON_USE_WOW64="${PROTON_USE_WOW64:-1}"
export WINEDLLOVERRIDES="winepulse.drv,winealsa.drv,wineoss.drv=d" WINEDEBUG="${WINEDEBUG:--all}"
C="$STATE/compat/pfx/drive_c"
proton() { steam-run "$PROTON_DIR/proton" "$@"; }
# KZ3: wineserver -k needs the prefix (else it stops ~/.wine's server, not Proton's): the game a real walk's
# Finish started kept running into the next walk and took its key presses
# (and even so the game windows outlived it in a KZ3 batch, so the game and launcher processes are also ended
# by name: the sandbox has its own pid namespace, so this never reaches another worktree's run)
wskill() { WINEPREFIX="${1:-$STATE/compat/pfx}" steam-run "$PROTON_DIR/files/bin/wineserver" -k >/dev/null 2>&1
  pkill -f 'kz2\.exe|Project Pyrrhus\.exe' 2>/dev/null; true; }
winpath() { echo "Z:${1//\//\\}"; }
cleanup() {
  wskill
  [[ -n "$XVFB" ]] && kill "$XVFB" 2>/dev/null
}
trap cleanup EXIT

# Window helpers: the wizard is a top-level X window named "Setup - <AppName>"; no window manager on Xvfb.
win() { xdotool search --onlyvisible --name "$1" 2>/dev/null | head -1; }
shot() {  # shot NAME: the setup window's area (or the whole display if no window)
  local w; w="$(win "${2:-Setup - }")"
  if [[ -n "$w" ]]; then
    eval "$(xdotool getwindowgeometry --shell "$w")"
    import -window root -crop "${WIDTH}x${HEIGHT}+${X}+${Y}" +repage "$SHOTS/$1.png" 2>/dev/null
  else
    import -window root "$SHOTS/$1.png" 2>/dev/null
  fi
  echo "shot $1 ${w:-root}"
}
key() { local w; w="$(win "Setup - ")"; [[ -n "$w" ]] && xdotool windowfocus --sync "$w" 2>/dev/null; xdotool key --delay 80 "$@"; sleep 1.5; }
typ() { local w; w="$(win "Setup - ")"; [[ -n "$w" ]] && xdotool windowfocus --sync "$w" 2>/dev/null
  xdotool key End shift+Home; xdotool type --delay 30 "$1"; sleep 0.5; }

setdpi() {  # Wine's own DPI (Xvfb's -dpi does not change it): both keys Wine reads, then a fresh wineserver
  proton run reg add 'HKCU\Control Panel\Desktop' /v LogPixels /t REG_DWORD /d "$1" /f >/dev/null 2>&1
  proton run reg add 'HKLM\System\CurrentControlSet\Hardware Profiles\Current\Software\Fonts' /v LogPixels \
    /t REG_DWORD /d "$1" /f >/dev/null 2>&1
  wskill; sleep 1
}
keyw() {  # keyw TITLE-PATTERN KEYS...: focus the newest visible window matching, then press
  local w; w="$(xdotool search --onlyvisible --name "$1" 2>/dev/null | tail -1)"; shift
  [[ -n "$w" ]] && xdotool windowfocus --sync "$w" 2>/dev/null; xdotool key --delay 80 "$@"; sleep 1.5
}
names() { xdotool search --onlyvisible --name . getwindowname %@ 2>/dev/null | sort -u | head -8 | tr '\n' '|'; echo; }
INST_REL="users/steamuser/AppData/Local/Programs/Project Pyrrhus"
facts() {  # facts FILE: what the uninstall must remove or keep (Linux view of the prefix; the dump through the bind)
  { echo "# $(date +%T)"
    if [[ -n "${KZ2_WT_DUMPDIR:-}" ]]; then
      echo "dump files $(find "$KZ2_WT_DUMPDIR/" -type f | wc -l) bytes $(du -sb "$KZ2_WT_DUMPDIR/" | cut -f1)"
      echo "dump PS3_GAME/USRDIR mtime $(stat -c %Y "$KZ2_WT_DUMPDIR/PS3_GAME/USRDIR" 2>/dev/null)"
    fi
    local I="$C/$INST_REL"
    echo "install exists: $([[ -d "$I" ]] && echo yes || echo no)"
    [[ -d "$I" ]] && { echo "install top: $(ls -A "$I" | tr '\n' ' ')"; echo "install bytes $(du -sb "$I" | cut -f1)"
      echo "vfs: $(ls -lA "$I/vfs" 2>/dev/null | tail -n +2 | awk '{print $1, $NF}' | tr '\n' ';')"
      echo "build exists: $([[ -d "$I/build" ]] && echo yes || echo no)"; }
    local A="$C/users/steamuser/AppData/Roaming/Project Pyrrhus"
    echo "appdata: $(ls -A "$A" 2>/dev/null | tr '\n' ' ')"
    [[ -f "$A/keybinds.ini" ]] && echo "keybinds sha $(sha256sum "$A/keybinds.ini" | cut -c1-16)"
    [[ -d "$A/gamedata" ]] && echo "gamedata files $(find "$A/gamedata" -type f | wc -l) sha $(find "$A/gamedata" -type f -exec sha256sum {} + | sort | sha256sum | cut -c1-16)"
  } > "$1"; cat "$1" | cut -c1-200
}

case "$MODE" in
install)
  V="${1:-6.7.3}"
  # /CURRENTUSER: per-user, no admin; /DIR: fixed path for ISCC.exe; no wizard pages are shown at all
  proton run "$WT/dl/innosetup-$V.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER \
    '/DIR=C:\inno' '/LOG=C:\inno-install.log' >"$WT/install-$V.out" 2>&1
  echo "install rc=$?"; ls "$C/inno" 2>&1 | head -20
  tail -5 "$C/inno-install.log" 2>/dev/null | cut -c1-200
  ;;
compile)
  PAYLOAD="$1" OUT="$2"; shift 2; mkdir -p "$OUT"
  cd "$ROOT/installer" || exit 1
  T0=$SECONDS
  proton run 'C:\windows\system32\cmd.exe' /v:on /c "C:\\inno\\ISCC.exe /DPayload=$(winpath "$PAYLOAD") /O$(winpath "$OUT") $* kz2.iss > $(winpath "$OUT")\\iscc.txt 2>&1 & echo [exit code !errorlevel!] >> $(winpath "$OUT")\\iscc.txt" \
    >"$OUT/proton.out" 2>&1
  echo "compile: $((SECONDS - T0)) s"; tail -25 "$OUT/iscc.txt" | cut -c1-220; ls -la "$OUT"/*.exe 2>/dev/null
  ;;
wizard)
  SETUP="$1" SHOTS="$2" FAIL="${3:-}"; mkdir -p "$SHOTS"
  TIMES="$SHOTS/times.txt"; T0=$SECONDS; : > "$TIMES"
  mark() { echo "$1 $((SECONDS - T0)) s" | tee -a "$TIMES"; }
  DUMP="${KZ2_WT_DUMP:-C:\kz2test\dump}" UPDATE="${KZ2_WT_UPDATE:-C:\kz2test\update}" EBOOT="${KZ2_WT_EBOOT:-}"
  # Empty marker files only (the wizard's presence checks); no game data.
  for f in dump/PS3_GAME/PARAM.SFO dump/PS3_GAME/USRDIR/data_ps3.psarc update/PARAM.SFO update/USRDIR/EBOOT.BIN \
           update/USRDIR/added_data_ps3.psarc.edat update/USRDIR/EBOOT.elf; do
    mkdir -p "$(dirname "$C/kz2test/$f")"; : > "$C/kz2test/$f"; done
  [[ "${KZ2_WT_KEEP:-0}" == 1 ]] || rm -rf "$C/users/steamuser/AppData/Local/Programs/Project Pyrrhus"
  [[ "${KZ2_WT_KEEP:-0}" == 1 ]] && facts "$SHOTS/facts-before.txt"
  # firstrun.py rewrites the log next to SETUP.exe: an earlier walk's RESULT line must not end this one's wait
  if [[ "$FAIL" == real ]]; then for l in "$(dirname "$SETUP")"/*.log; do [[ -f "$l" ]] && mv "$l" "$l.$(date +%s).old"; done; fi
  [[ -n "${KZ2_WT_WINEDPI:-}" ]] && setdpi "$KZ2_WT_WINEDPI"
  # Windows 10 has Segoe UI (Inno's dialog font); this prefix does not, and Wine's fallback is a serif face. Map it
  # to Tahoma (in the prefix) so the shots are closer to what a player sees. KZ2_WT_NOSUBST=1 keeps the fallback.
  if [[ "${KZ2_WT_NOSUBST:-0}" != 1 ]]; then
    # Proton writes "Segoe UI"="Times New Roman" into the prefix (a reg add did not override it): edit the hive while
    # no wineserver runs
    sed -i 's/^"Segoe UI"="Times New Roman"/"Segoe UI"="Tahoma"/' "$STATE/compat/pfx/user.reg" 2>/dev/null
  fi
  [[ "$FAIL" == fail ]] && export KZ2_WIZARD_DEMO_FAIL=1
  [[ "$FAIL" == stop ]] && export KZ2_WIZARD_DEMO_SECS="${KZ2_WIZARD_DEMO_SECS:-8}"
  export KZ2_WIZARD_DEMO_SECS="${KZ2_WIZARD_DEMO_SECS:-3}"
  mkdir -p "$C/kz2test"
  TASKARG=(); [[ -n "${KZ2_WT_TASKS:-}" ]] && TASKARG=("/TASKS=$KZ2_WT_TASKS")
  proton run "$SETUP" '/LOG=C:\kz2test\setup-inno.log' "${TASKARG[@]}" >"$SHOTS/proton.out" 2>&1 &
  for _ in $(seq 600); do [[ -n "$(win 'Setup - ')" ]] && break; sleep 1; done
  sleep 3; mark "wizard-shown"
  xdotool search --onlyvisible --name . getwindowname %@ 2>/dev/null | head -10
  shot 01-welcome
  # Keyboard only (Alt+letter is unreliable here: it selected the licence text): the welcome page opens with the
  # focus on "Check for a new version" (Space = the click; offline in the sandbox), Return = the default button.
  key space; sleep 2; shot 02-welcome-checked; key Return; shot 03-licence
  key Tab Up; shot 03b-licence-accepted; key Return; shot 04-dir; key Return; shot 05-tasks
  if [[ "$FAIL" == tasks ]]; then  # cancel: Escape = Cancel, the "Exit Setup?" box takes y
    key Escape; sleep 1; keyw . y; sleep 3; names; mark "end"; exit 0
  fi
  key Return; shot 06-dump
  typ "$DUMP"; key Return; shot 07-update
  typ "$UPDATE"; key Return; shot 08-eboot
  [[ -n "$EBOOT" ]] && { typ "$EBOOT"; shot 08b-eboot-typed; }
  key Return; shot 09-ready
  mark "pages-done"; key Return; sleep 4; shot 10-installing
  if [[ "$FAIL" == stop ]]; then
    # The build page's only enabled control is "Stop the build": Tab focuses it, Space clicks; the confirmation
    # defaults to No, so "y" answers Yes
    sleep 3; shot 11-build-1; key Tab; key space; sleep 1; shot 11-stop-confirm "zzz-no-such-window"; key y; sleep 4
    shot 11-stopped; for _ in $(seq 10); do sleep 2; done; shot 13-finish
  else
    for i in 1 2 3 4 5 6; do sleep 4; shot "11-build-$i"; done
  fi
  if [[ "$FAIL" == real ]]; then
    # The build's RESULT line lands in the log next to SETUP.exe ({src}); the file copy before it is the first wait
    LOG=""; N=0
    while (( SECONDS - T0 < ${KZ2_WT_REAL_MAX:-3600} )); do
      sleep 10; N=$((N + 1))
      [[ -z "$LOG" ]] && LOG="$(ls -t "$(dirname "$SETUP")"/*.log 2>/dev/null | head -1)"
      (( N % 6 == 0 )) && { shot "11-build-$((N / 6))"; tail -1 "$LOG" 2>/dev/null | cut -c1-160; }
      [[ -n "$LOG" ]] && grep -q "^RESULT " "$LOG" && break
    done
    mark "build-result"; grep -m1 "^RESULT " "$LOG" 2>/dev/null; sleep 5; shot 13-finish
    # Finish with "Start Project Pyrrhus" checked: the installed launcher starts build\kz2.exe (launch.py "run")
    key Return; sleep "${KZ2_WT_PLAY:-90}"; mark "played"
    xdotool search --onlyvisible --name . getwindowname %@ 2>/dev/null | head -10
    shot 14-game "zzz-no-such-window"; shot 14-game-window "Killzone"
  elif [[ "$FAIL" == stop ]]; then :
  elif [[ "$FAIL" == fail ]]; then
    sleep 20; xdotool search --onlyvisible --name . getwindowname %@ 2>/dev/null | head; shot 12-error "Setup"
    shot 12-error-root "zzz-no-such-window"
  else
    for _ in $(seq 30); do sleep 2; xdotool search --onlyvisible --name . getwindowname %@ 2>/dev/null | grep -q . || break
      [[ -n "$(xdotool search --onlyvisible --name 'Setup - ' 2>/dev/null)" ]] || break; done
    sleep 3; shot 13-finish
  fi
  shot 99-display "zzz-no-such-window"; mark "end"
  [[ "${KZ2_WT_KEEP:-0}" == 1 ]] && facts "$SHOTS/facts-after.txt"
  grep -m20 -i "error\|exception\|page" "$C/kz2test/setup-inno.log" 2>/dev/null | cut -c1-200
  ;;
rpcs3)
  # rpcs3 SETUP SHOTDIR A|B: the "Use my RPCS3 install" pages with fake RPCS3 trees (wizard_test/fake_rpcs3.py, no game
  # data; the tree is made at KZ2_WT_FX, default work/release/wizard/fx). The payload's toolchain\python\python.exe is
  # wizard_test/pyshim.c (work/release/pyshim.exe) because the prefix has no Windows Python: it runs the Linux python3
  # on the same arguments (winpy.py maps the paths) and the payload's firstrun.py is the demo fixture, so the build
  # page and the save question run without game data. The scripts the pages run (rpcs3_import.py, rpcs3_locate.py)
  # are the payload's own.
  #   A  RPCS3 path: wrong folder (error), a tree missing the update (the problems box), fixed (Retry), the build
  #      fixture, the save question (dry run), No
  #   B  manual path with an encrypted EBOOT.BIN (HELP_ENCRYPTED)
  SETUP="$1" SHOTS="$2" WALK="${3:-A}"; mkdir -p "$SHOTS"
  FX="${KZ2_WT_FX:-$WT/fx}"; P=r14
  export KZ2_WT_LINUXPY="$(command -v python3)" KZ2_WT_CDRIVE="$C" KZ2_WIZARD_DEMO_SECS="${KZ2_WIZARD_DEMO_SECS:-2}"
  export KZ2_WT_WINPY="$ROOT/work/release/winpy.py"
  rm -f "$C/pyshim.log"; rm -rf "$C/users/steamuser/AppData/Local/Programs/Project Pyrrhus" "$C/users/steamuser/AppData/Roaming/Project Pyrrhus"
  rm -rf "$FX"; python3 -I "$ROOT/tools/release/wizard_test/fake_rpcs3.py" "$FX" >/dev/null || exit 1
  sed -i 's/^"Segoe UI"="Times New Roman"/"Segoe UI"="Tahoma"/' "$STATE/compat/pfx/user.reg" 2>/dev/null
  mkdir -p "$C/kz2test"
  proton run "$SETUP" '/LOG=C:\kz2test\setup-inno.log' >"$SHOTS/proton.out" 2>&1 &
  for _ in $(seq 600); do [[ -n "$(win 'Setup - ')" ]] && break; sleep 1; done
  sleep 3
  rshot() { import -window root "$SHOTS/$P-$1.png" 2>/dev/null; echo "shot $P-$1"; }
  # The display lags well behind the keys when the machine is busy (the first walks read a page behind): every step
  # waits for the picture to change (chg) and the long ones for it to hold still (calm).
  rhash() { import -window root png:- 2>/dev/null | md5sum | cut -c1-12; }
  chg() { local max="$1" h0 h i; shift; h0="$(rhash)"; "$@"; for i in $(seq "$max"); do sleep 1; h="$(rhash)"; [[ "$h" != "$h0" ]] && break; done; sleep 3; }
  calm() { local min="$1" max="$2" last="" same=0 t=0 h; while (( t < max )); do sleep 3; t=$((t + 3)); h="$(rhash)"
      if [[ "$h" == "$last" ]]; then same=$((same + 1)); else same=0; fi; last="$h"; (( same >= 4 && t >= min )) && break; done; }
  # The welcome page opens with the focus on "Check for a new version": Return there would click that (offline: it
  # reports "could not run"), so Space is the check and the next Return is Next (as in the wizard mode above)
  # waitbox: a message box's text (bright pixels in the middle of the window) has appeared; up to MAX s, then 5 s to paint
  waitbox() { local max="$1" t=0 n; while (( t < max )); do sleep 3; t=$((t + 3))
      n="$(import -window root -crop 260x110+$((X + 230))+$((Y + 100)) +repage txt:- 2>/dev/null | awk -F'[(,)]' 'NR>1 && $3+0 > 200 {n++} END {print n+0}')"
      (( n > 150 )) && break; done; sleep 5; }
  rshot "$WALK-00-welcome"; chg 60 key space; sleep 30; rshot "$WALK-00-welcome-checked"   # the check can block the wizard ~25 s (no network)
  chg 60 key Return; rshot "$WALK-00-licence"                                           # Next
  eval "$(xdotool getwindowgeometry --shell "$(win 'Setup - ')")"
  # The accept radio, by mouse. A click can be lost, and the display can show the old state for many seconds when the
  # machine is busy, so the radio is checked: a selected radio has a blue ring. The count of blue pixels in the
  # accept radio's box (window offset 40..54, 341..355) is compared with the other radio's box (20 px lower); the
  # click is repeated, waiting up to 30 s each time, at most 6 times; then the walk stops.
  blue() { import -window root -crop 15x15+$((X + 40))+$((Y + $1)) +repage txt:- 2>/dev/null |
      awk -F'[(,)]' 'NR>1 && $5+0 > $3+0+60 {n++} END {print n+0}'; }
  radio_on() { (( $(blue 341) >= 8 )); }
  for try in 1 2 3 4 5 6; do
    if (( try % 2 )); then   # odd tries: the mouse (moved first, so Wine sees the pointer arrive); even: Alt+A
      xdotool mousemove $((X + 40)) $((Y + 340)); sleep 1; xdotool mousemove $((X + 47)) $((Y + 348)); sleep 1; xdotool click 1
    else keyw "Setup - " alt+a; fi
    for _ in $(seq 10); do sleep 3; radio_on && break; done
    radio_on && break
    echo "accept: click $try not seen yet"
  done
  radio_on || { echo "FAIL: the accept radio never turned on"; rshot "$WALK-00-accept-failed"; exit 3; }
  rshot "$WALK-00-accepted"
  chg 60 key Return; rshot "$WALK-00-dir"; chg 60 key Return; rshot "$WALK-00-tasks"; chg 60 key Return    # folder, tasks
  rshot "$WALK-01-game-files"
  if [[ "$WALK" == A ]]; then
    chg 60 key Return; rshot A-02-rpcs3-folder
    typ "$(winpath "$FX/wrong")"; sleep 3; chg 60 key Return; rshot A-03-wrong-folder      # the error box
    chg 60 keyw . Return                                                                  # OK
    typ "$(winpath "$FX/noupdate/rpcs3")"; sleep 3; rshot A-04-folder-typed
    chg 60 key Return; rshot A-05-ready                                                   # -> Ready page
    chg 240 key Return; calm 20 120; rshot A-06-found-outside                             # install, then the approval box
    chg 120 keyw . y; waitbox 240; rshot A-07-problems                                    # missing update
    mkdir -p "$FX/noupdate/rpcs3/dev_hdd0/game/BCUS98116"
    cp -r "$FX/noupdate/update-129/." "$FX/noupdate/rpcs3/dev_hdd0/game/BCUS98116/"
    chg 120 keyw . Return; sleep 15; rshot A-08-build                                               # Retry: found, build fixture
    waitbox 300; rshot A-09-save-question                                                 # the dry run text
    chg 60 keyw . n; calm 10 120; rshot A-10-after-save-no
  else
    chg 60 key Down; rshot B-02-manual-choice; chg 60 key Return; rshot B-03-dump
    typ "$(winpath "$FX/manual/dump")"; sleep 3; chg 60 key Return; rshot B-04-update
    typ "$(winpath "$FX/manual/update")"; sleep 3; chg 60 key Return; rshot B-05-eboot
    typ "$(winpath "$FX/manual/update/USRDIR/EBOOT.BIN")"; sleep 3; rshot B-06-eboot-typed
    chg 120 key Return; waitbox 240; rshot B-07-encrypted-help
  fi
  cp "$C/kz2test/setup-inno.log" "$SHOTS/inno-$WALK.log" 2>/dev/null; cp "$C/pyshim.log" "$SHOTS/pyshim-$WALK.log" 2>/dev/null
  names; rshot "$WALK-99-end"
  grep -i -m10 "error\|exception" "$C/kz2test/setup-inno.log" 2>/dev/null | cut -c1-200
  ;;
run)
  # run ARGS...: one Proton command in the walk prefix, output to stdout (probing)
  export KZ2_WT_LINUXPY="$(command -v python3)" KZ2_WT_CDRIVE="$C" KZ2_WT_WINPY="$ROOT/work/release/winpy.py"
  echo "linuxpy=$KZ2_WT_LINUXPY"
  proton run "$@" 2>&1 | grep -v 'Fontconfig\|ProtonFixes\|machine-id\|fsync' | head -30 | tr -d '\r'
  ;;
batch)
  run() { echo "=== $(date +%T) $*"; bash "$0" --inner "$@"; wskill "${KZ2_WT_STATE:-$WT}/compat/pfx"; }
  # shellcheck disable=SC1090
  source "$1"
  ;;
tasks)
  SETUP="$1" SHOTS="$2"
  for d in ${KZ2_WT_DPIS:-96 144}; do
    for t in default portable; do
      [[ "$t" == default ]] && unset KZ2_WT_TASKS || export KZ2_WT_TASKS="desktopicon,portable,buildnow"
      KZ2_WT_WINEDPI="$d" bash "$0" --inner wizard "$SETUP" "$SHOTS/dpi$d-$t" tasks 2>&1 | grep -v '^shot ' | tail -3
      wskill
    done
  done
  ;;
uninstall)
  SHOTS="$1"; mkdir -p "$SHOTS"; T0=$SECONDS
  wskill; facts "$SHOTS/facts-before.txt"
  # Not silent: the player's path (Start menu > Uninstall). Pages: "Are you sure" (default Yes) -> progress ->
  # "Delete your saves too?" (default No = keep; KZ2_WT_DELSAVES=1 answers y) -> "was removed" (OK).
  proton run "$(winpath "$C/$INST_REL/unins000.exe")" >"$SHOTS/proton.out" 2>&1 &
  for _ in $(seq 120); do [[ -n "$(xdotool search --onlyvisible --name Uninstall 2>/dev/null)" ]] && break; sleep 1; done
  sleep 2; names; shot 21-confirm Uninstall; keyw Uninstall y   # the box's default is No
  sleep "${KZ2_WT_UNINST_WAIT:-40}"   # the removal itself (thousands of toolchain files) before the saves question
  sleep 2; names; shot 22-saves Uninstall; shot 22-saves-root "zzz-no-such-window"
  if [[ "${KZ2_WT_DELSAVES:-0}" == 1 ]]; then keyw Uninstall y; else keyw Uninstall n; fi
  sleep 4; names; shot 23-done Uninstall; keyw Uninstall Return; sleep 5; names
  echo "uninstall walk $((SECONDS - T0)) s"
  facts "$SHOTS/facts-after.txt"
  ;;
zip)
  ZIP="$1" SHOTS="$2"; mkdir -p "$SHOTS"; TIMES="$SHOTS/times.txt"; T0=$SECONDS; : > "$TIMES"
  mark() { echo "$1 $((SECONDS - T0)) s" | tee -a "$TIMES"; }
  G="$C/Games"; rm -rf "$G"; mkdir -p "$G"
  proton run 'C:\windows\system32\cmd.exe' /c ver >/dev/null 2>&1; mark "prefix-ready"
  python3 -I -m zipfile -e "$ZIP" "$G" && mark "unzipped"; du -sb "$G" | cut -f1
  D="$G/Project Pyrrhus"; WD='C:\Games\Project Pyrrhus'
  # run.cmd's questions: dump, update, EBOOT, check now (n), start the build (Enter = yes); the pause reads EOF. A
  # driver .cmd holds the quoted paths (cmd /c on a Wine-built command line mangles nested quotes).
  printf '%s\r\n' "${KZ2_WT_DUMP:?}" "${KZ2_WT_UPDATE:?}" "${KZ2_WT_EBOOT:?}" n '' '' > "$G/answers.txt"
  printf '@echo off\r\ncall "%s\\run.cmd" < C:\\Games\\answers.txt > C:\\Games\\run-out.txt 2>&1\r\n' "$WD" > "$G/drive.cmd"
  proton run 'C:\windows\system32\cmd.exe' /c 'C:\Games\drive.cmd' >"$SHOTS/proton-build.out" 2>&1
  mark "run.cmd-returned"; grep -m1 "^RESULT " "$D"/Project-Pyrrhus-firstrun*.log 2>/dev/null
  tail -4 "$G/run-out.txt" | tr -d '\r' | cut -c1-200
  [[ -f "$D/build/kz2.exe" ]] || { echo "no build/kz2.exe"; exit 1; }
  export PAD_SCRIPT="${KZ2_WT_PAD:-}" GCM_FLIPCOUNT=1
  proton run "$WD\\Project Pyrrhus.exe" >"$SHOTS/proton-game.out" 2>&1 &
  mark "launcher-started"; N=0
  while (( N * 30 < ${KZ2_WT_PLAY:-300} )); do sleep 30; N=$((N + 1)); shot "$(printf 'play-%03d' $((N * 30)))" "zzz-no-such-window"; done
  names; mark "played"
  ls -t "$D"/build/logs/*.log 2>/dev/null | head -1 | xargs -r -I{} cp {} "$SHOTS/game.log"
  cp "$D"/logs/launcher.log "$SHOTS/" 2>/dev/null; du -sb "$D" | cut -f1
  ;;
launcher)
  # The real Project Pyrrhus.exe in a staged install (stage_launcher.py): it starts the game through launch.py, which
  # runs on the Linux python behind pyshim.exe (no Windows Python offline) and starts kz2.exe through the winpy.py
  # bridge (KZ2_WT_WINE). Shots every 15 s, then Alt+F4 on the game window; the launcher's exit is waited for.
  SHOTS="$1"; mkdir -p "$SHOTS"; T0=$SECONDS
  G="$C/Games"; rm -rf "$G"; mkdir -p "$G"
  printf '[controls]\nlayout = modern\nprompts = ps4\n%b' "${KZ2_WT_INI_EXTRA:-}" > "$SHOTS/kz2-install.ini"
  python3 "$ROOT/tools/release/wizard_test/stage_launcher.py" --root "$G/PP" --payload "${KZ2_WT_PAYLOAD:?}" \
    --launcher "$ROOT/build/launcher/Project Pyrrhus.exe" --pyshim "$ROOT/work/release/pyshim.exe" \
    --game "${KZ2_WT_GAME:?}" --ini "$SHOTS/kz2-install.ini" | tee "$SHOTS/stage.txt"
  export KZ2_WT_LINUXPY="$(command -v python3)" KZ2_WT_CDRIVE="$C" KZ2_WT_WINPY="$ROOT/tools/release/wizard_test/winpy.py"
  export KZ2_WT_WINE="$PROTON_DIR/files/bin/wine" GCM_FLIPCOUNT=1 KZ2_SKIP_INTRO=1
  proton run 'C:\windows\system32\cmd.exe' /c ver >/dev/null 2>&1
  proton run 'C:\Games\PP\Project Pyrrhus.exe' --launcher-dry-run >/dev/null 2>&1; cp "$G/PP/launcher-dry-run.txt" "$SHOTS/" 2>/dev/null
  proton run 'C:\Games\PP\Project Pyrrhus.exe' >"$SHOTS/proton-launcher.out" 2>&1 &
  LP=$!; N=0
  while (( N * 15 < ${KZ2_WT_PLAY:-60} )); do sleep 15; N=$((N + 1)); shot "$(printf 'play-%03d' $((N * 15)))" "zzz-no-such-window"; done
  names
  GW="$(xdotool search --onlyvisible --name ps3recomp 2>/dev/null | head -1)"; echo "game window: ${GW:-none}"
  [[ -n "$GW" ]] && { xdotool windowfocus --sync "$GW" 2>/dev/null; xdotool key --delay 80 alt+F4; }
  for _ in $(seq 40); do kill -0 "$LP" 2>/dev/null || break; sleep 1; done
  kill -0 "$LP" 2>/dev/null && echo "launcher still running after Alt+F4" || { wait "$LP"; echo "launcher exited rc=$?"; }
  cp "$G"/PP/logs/*.log "$G"/PP/build/logs/*.log "$SHOTS/" 2>/dev/null; cp "$C/pyshim.log" "$SHOTS/" 2>/dev/null; ls "$G/PP" | tr '\n' ' '; echo
  echo "launcher walk $((SECONDS - T0)) s"
  ;;
vmtest)
  # The Windows VM kit's steps (tools/release/vm_test.py) under Proton, in the prefix of KZ2_WT_STATE (use a fresh
  # one, like a fresh VM): KIT = the staged shared/kz2 folder (kit/ and game/), PY = a folder holding a Windows
  # python.exe (the embeddable Python stands in for the guest's own), then the step names. C:\kz2 is the prefix's
  # own drive_c/kz2: kit/ copied in, game/ linked to KIT/game (read in place). out/ stays in the prefix.
  KIT="$1" PYDIR="$2"; shift 2
  B="$C/kz2"; mkdir -p "$B/out" "$B/py"
  rm -rf "$B/kit"; cp -r "$KIT/kit" "$B/kit"
  [[ -e "$B/game" ]] || ln -s "$KIT/game" "$B/game"
  [[ -f "$B/py/python.exe" ]] || cp -r "$PYDIR/." "$B/py/"
  proton run 'C:\windows\system32\cmd.exe' /c ver >/dev/null 2>&1     # first run creates the prefix
  for S in "$@"; do
    if [[ "$S" == fake-build ]]; then
      # Test only: a borrowed kz2.exe (KZ2_WT_FAKEBUILD: a folder with kz2.exe and at3_standalone.dll, linked in)
      # and a stamp, so 07-launch reaches the "run" path without a Windows compiler (fake_stamp.py)
      I="$C/$INST_REL"
      for f in kz2.exe at3_standalone.dll; do ln -sfn "$KZ2_WT_FAKEBUILD/$f" "$I/build/$f"; done
      cp "$ROOT/tools/release/wizard_test/fake_stamp.py" "$B/fake_stamp.py"
      proton run "C:\\users\\steamuser\\AppData\\Local\\Programs\\Project Pyrrhus\\toolchain\\python\\python.exe" \
        'C:\kz2\fake_stamp.py' 'C:\users\steamuser\AppData\Local\Programs\Project Pyrrhus' 2>/dev/null | tail -1
      continue
    fi
    T0=$SECONDS
    proton run 'C:\kz2\py\python.exe' 'C:\kz2\kit\vm_test.py' "$S" ${KZ2_WT_VMARGS:-} >"$B/out/$S.proton.txt" 2>&1
    echo "$S: rc=$? $((SECONDS - T0)) s; $(grep -a "RESULT " "$B/out/$S.txt" 2>/dev/null | tail -1 | cut -c1-200)"
  done
  ;;
vkd3d)
  # Where vkd3d-proton puts its pipeline cache, with the install folder read-only. Needs an install
  # with a finished (or fake-build) build in KZ2_WT_STATE's prefix and KZ2_WT_LAVAPIPE=1. Runs, SECS s each, then the
  # prefix's wineserver is stopped: B1 the launcher (install writable), then the install made read-only (chmod a-w),
  # A kz2.exe straight in the install folder without VKD3D_SHADER_CACHE_PATH, C the same with it, B2 the launcher again.
  # Every vkd3d-proton*cache* in the prefix is deleted first and listed after each run (OUT/vkd3d-runs.txt).
  OUT="$1" SECS="${2:-60}"; mkdir -p "$OUT"
  export VK_ICD_FILENAMES=/run/opengl-driver/share/vulkan/icd.d/lvp_icd.x86_64.json
  I="$C/$INST_REL"; A="$C/users/steamuser/AppData/Roaming/Project Pyrrhus"
  WI='C:\users\steamuser\AppData\Local\Programs\Project Pyrrhus'
  # vkd3d-proton names its cache vkd3d-proton.cache, or vkd3d-proton.<exe>.cache in newer builds (Proton GE: kz2.exe's)
  caches() { echo "  caches after $1:"; find "$C" -name 'vkd3d-proton*cache*' -printf '    %s bytes  %P\n' 2>/dev/null | head; }
  gameenv() {   # the launcher's game variables as KEY=VALUE lines, from the newest launch.py --print of vm_test.py
    local j; j="$(ls -t "$C"/kz2/out/*-launch-print.json 2>/dev/null | head -1)"
    [[ -n "$j" ]] && python3 -c 'import json,sys; [print(f"{k}={v}") for k,v in json.load(open(sys.argv[1])).get("env",{}).items()]' "$j"
  }
  launcher() {   # the launcher's dry run (its command line), then the real start; its last log lines after
    proton run "$WI\Project Pyrrhus.exe" --launcher-dry-run >/dev/null 2>&1; cp "$I/launcher-dry-run.txt" "$OUT/$1.dry-run.txt" 2>/dev/null
    proton run "$WI\Project Pyrrhus.exe" >"$OUT/$1.txt" 2>&1 & local P=$!; sleep "$SECS"; wskill; wait "$P" 2>/dev/null
    tail -4 "$I/logs/launcher.log" > "$OUT/$1.launcher-log.txt" 2>/dev/null
  }
  direct() {    # direct NAME [VAR=VALUE...]: kz2.exe with the launcher's variables, working folder = the install folder
    local n="$1" l; shift
    local -a E=()
    while IFS= read -r l; do [[ "$l" == VKD3D_SHADER_CACHE_PATH=* ]] || E+=("$l"); done < "$OUT/game-env.txt"
    ( cd "$I" && env "${E[@]}" KZ2_LOG_FILE=0 "$@" \
        steam-run "$PROTON_DIR/proton" run "$WI\build\kz2.exe" 'C:\kz2\game\eboot\EBOOT.elf' >"$OUT/$n.txt" 2>&1 ) &
    local P=$!; sleep "$SECS"; wskill; wait "$P" 2>/dev/null
  }
  {
    echo "# vkd3d cache runs, $SECS s each, lavapipe"
    gameenv > "$OUT/game-env.txt"; echo "the launcher's game variables: $(wc -l < "$OUT/game-env.txt")"
    find "$C" -name 'vkd3d-proton*cache*' -delete 2>/dev/null; caches "clearing the old ones"
    if [[ "${KZ2_WT_RO_INSTALL:-0}" == 1 ]]; then
      if touch "$I/write-probe" 2>/dev/null; then rm -f "$I/write-probe"; echo "install folder is STILL writable"
      else echo "install folder read-only (bind mount)"; fi
    else
      launcher B1-launcher-writable; caches B1
      chmod -R a-w "$I"; echo "install folder chmod a-w (not enforced in the sandbox: see KZ2_WT_RO_INSTALL)"
    fi
    direct A-direct-readonly-novar; caches A
    direct C-direct-readonly-var "VKD3D_SHADER_CACHE_PATH=C:\\users\\steamuser\\AppData\\Roaming\\Project Pyrrhus\\cache\\vkd3d"; caches C
    launcher B2-launcher-readonly; caches B2
    chmod -R u+w "$I"; echo "install folder writable again"
    for f in "$OUT"/*.txt; do echo "## $(basename "$f"): $(grep -aic 'vkd3d' "$f") vkd3d lines"
      grep -ai 'cache\|err:vkd3d\|device\|CRASH\|live-draw init' "$f" | grep -v '^Fontconfig' | head -8 | cut -c1-200; done
  } 2>&1 | tee "$OUT/vkd3d-runs.txt"
  ;;
*) echo "unknown mode $MODE" >&2; exit 2 ;;
esac
