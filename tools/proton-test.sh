#!/usr/bin/env bash
# Run a Windows exe under the user's Proton, hidden and muted, inside the sandbox.
# From Project Helghast tools/proton-test.sh (KZ3_* -> KZ2_*; runprov calls run only once tools/runprov.py is copied).
# On a shared GPU, wrap it in a lock, e.g. flock: nix develop --command tools/proton-test.sh ...
#
#   tools/proton-test.sh [--seconds N] [--shot FILE.png] [--proton DIR] [--name NAME] EXE [ARGS...]
#
# Run from `nix develop` (needs steam-run, xvfb, imagemagick, bubblewrap on PATH).
#  - Sandbox: --gpu (NVIDIA device nodes), no network, repo/game read-only, Proton dir read-only.
#  - Copies EXE's directory to work/proton/<name>/app and uses its own prefix work/proton/<name>/compat.
#  - Hidden display: Xvfb inside the sandbox; never the user's screen. Exception: --real-display
#    runs on the user's X display :0 for real frame-rate numbers; the screenshot is then
#    of the game window only, never the whole screen. Audio stays disabled either way.
#  - Muted: Wine audio drivers disabled through WINEDLLOVERRIDES (never via the mixer).
#  - After N seconds (default 10) takes a screenshot (default work/shots/<name>.png), then kills the run.
# Exit status: 0 if the program was still running at screenshot time or exited 0; the log is printed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECONDS_RUN=10 SHOT="" NAME="" PROTON_DIR="$HOME/.local/share/Steam/compatibilitytools.d/Proton-GE Latest"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --seconds) SECONDS_RUN="$2"; shift 2 ;;
    --shot) SHOT="$2"; shift 2 ;;
    --proton) PROTON_DIR="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --real-display) REAL=1; shift ;;
    *) break ;;
  esac
done
[[ $# -ge 1 ]] || { echo "usage: $0 [--seconds N] [--shot F] [--proton DIR] [--name N] EXE [ARGS]" >&2; exit 2; }
EXE="$(readlink -f "$1")"; shift
NAME="${NAME:-$(basename "$EXE" .exe)}"
SHOT="${SHOT:-$ROOT/work/shots/$NAME.png}"
RUN="$ROOT/work/proton/$NAME"
[[ -x "$PROTON_DIR/proton" ]] || { echo "no proton at $PROTON_DIR" >&2; exit 2; }

mkdir -p "$RUN/app" "$RUN/compat" "$RUN/steam" "$(dirname "$SHOT")"
cp -a "$(dirname "$EXE")/." "$RUN/app/"

# Run provenance (tools/runprov.py, when present): work/proton/<name>/run.json records the staged exe, git state,
# patch set, env, Proton, fixtures and cache state before the run, and the outcome from the log after it. It never
# fails a run; tools/runcmp.py reads it before two runs are compared.
DISPLAY_KIND=xvfb; [[ ${REAL:-0} -eq 1 ]] && DISPLAY_KIND=real
if command -v python3 >/dev/null && [[ -f "$ROOT/tools/runprov.py" ]]; then
  python3 "$ROOT/tools/runprov.py" start "$RUN" --exe "$RUN/app/$(basename "$EXE")" --seconds "$SECONDS_RUN" \
    --display "$DISPLAY_KIND" --proton "$PROTON_DIR" --root "$ROOT" || true
fi

X11ARG=(); [[ ${REAL:-0} -eq 1 ]] && X11ARG=(--x11)
# On the real display under niri, float the game window when it appears: niri throttles a
# window it does not show (scrolled out of the strip, another workspace) to one frame per second, which voided
# rd-t1. Runtime IPC only (niri msg); the niri config file is not touched. KZ2_NIRI_FLOAT=0 turns it off.
if [[ ${REAL:-0} -eq 1 && "${KZ2_NIRI_FLOAT:-1}" == 1 ]] && command -v niri >/dev/null && niri msg version >/dev/null 2>&1; then
  ( before="$(niri msg -j windows 2>/dev/null | python3 -c 'import json,sys; print(" ".join(str(w["id"]) for w in json.load(sys.stdin)))')"
    for _ in $(seq 1 240); do
      sleep 1
      id="$(niri msg -j windows 2>/dev/null | python3 -c '
import json, re, sys
old = set(sys.argv[1].split())
for w in json.load(sys.stdin):
    tag = "%s %s" % (w.get("app_id") or "", w.get("title") or "")
    # The game window title starts with "Project Pyrrhus" (or "ps3recomp" in older builds and PS3_TITLE overrides); the Wine console (cmd.exe) opens first.
    if str(w["id"]) not in old and (w.get("title") or "").startswith(("Project Pyrrhus", "ps3recomp")):
        print(w["id"], int(bool(w.get("is_floating")))); break' "$before")"
      [[ -z "$id" ]] && continue
      read -r wid fl <<<"$id"
      (( fl )) || niri msg action toggle-window-floating --id "$wid" >/dev/null 2>&1
      echo "proton-test: floated niri window $wid" >&2; break
    done ) &
fi
set +e
"$ROOT/tools/sandbox.sh" --gpu "${X11ARG[@]}" --ro "$PROTON_DIR" -- \
  bash "$ROOT/tools/proton-inner.sh" "$PROTON_DIR" "$RUN" "$SECONDS_RUN" "$SHOT" "$(basename "$EXE")" "$@"
RC=$?
set -e
if command -v python3 >/dev/null && [[ -f "$ROOT/tools/runprov.py" ]]; then
  python3 "$ROOT/tools/runprov.py" finish "$RUN" --root "$ROOT" || true
fi
exit $RC
