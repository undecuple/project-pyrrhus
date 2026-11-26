#!/usr/bin/env bash
# Windows VM installer test kit: build the release artifacts, stage the folder the VM tester copies,
# and run the same steps under Proton first. No network, no GPU; game files are linked, never copied or committed.
#
#   tools/release/vm_kit.sh build             launcher (.#win), payload (assemble_payload.py with the toolchain cache),
#                                           installer (ISCC 6.7.3 under Proton, no GPU), portable zip (pack_zip.py)
#   tools/release/vm_kit.sh stage             work/release/vm-kit/shared/kz2/kit/ + SHA256SUMS.txt, ARTIFACTS.txt;
#                                           game/ as links to this machine's files (the pre-flight reads them)
#   tools/release/vm_kit.sh preflight [STEP...]  vm_test.py's steps (default: all, in vm_test.ORDER) under Proton in a
#                                           fresh prefix
#                                           (work/release/vm-kit/pre), the embeddable Python as the guest's Python
#
# Toolchain: work/release/toolchain-cache filled by tools/release/fetch_toolchain.py (needs the network once; with
# the downloads already there, --offline). With only the Python entry fetched, KZ2_VMKIT_PARTIAL=1 builds a
# pre-flight installer without compiler, CMake and Ninja: its build step stops at configure, and stage marks the kit
# NOT FOR THE VM. Outputs: work/release/vm-kit/{build,shared,pre}; never committed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
K="$ROOT/work/release/vm-kit"
B="$K/build"
CACHE="${KZ2_VMKIT_TOOLCHAIN:-$ROOT/work/release/toolchain-cache}"
MAIN="$(cat "$ROOT/.kz2-main" 2>/dev/null || echo "$ROOT")"
FFMPEG="${KZ2_VMKIT_FFMPEG:-$MAIN/work/ffmpeg-win}"
# the pipeline template (tools/runtime/pso_template.py merge): the committed installer/pso-template.bin, else the main
# checkout's merged work/pso-template.bin
PSO="${KZ2_VMKIT_PSO:-$ROOT/installer/pso-template.bin}"
[[ -f "$PSO" ]] || PSO="$MAIN/work/pso-template.bin"
# This machine's game files (pre-flight only; the VM gets the tester's own copy): the dump with PS3_GAME, the 1.29
# update as RPCS3 installed it (dev_hdd0/game/BCUS98116) and the decrypted 1.29 EBOOT.
G_DUMP="${KZ2_VMKIT_DUMP:-$(readlink -f "$ROOT/Game")}"
G_UPDATE="${KZ2_VMKIT_UPDATE:-$MAIN/work/rpcs3/rpcs3/dev_hdd0/game/BCUS98116}"
G_EBOOT="${KZ2_VMKIT_EBOOT:-$MAIN/work/bin/EBOOT-129.elf}"
SB=(tools/sandbox.sh --)
MODE="${1:?usage: vm_kit.sh build | stage | preflight [STEP...]}"; shift || true

# the zip's name for a version (release_version.zip_name: -portable.zip up to 0.1.13, -Windows-x64.zip from 0.1.14)
zip_name() { python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import release_version as r; print(r.zip_name(sys.argv[2]))' \
  "$PWD/tools/release" "$1"; }

case "$MODE" in
build)
  VER="$(python3 tools/release/release_version.py --check | sed -n 's/^ok //p')"   # installer/VERSION, the one version
  [[ -n "$VER" ]] || { python3 tools/release/release_version.py --check; exit 1; }
  mkdir -p "$B"
  nix develop .#win --command "${SB[@]}" tools/release/build_launcher.sh "$B/launcher" 2>&1 | tail -3
  TC=(--toolchain "$CACHE")
  if [[ "${KZ2_VMKIT_PARTIAL:-0}" == 1 ]]; then
    # Python only: a one-entry manifest (the pinned entry from toolchain.json), unpacked offline from the cache
    python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); m["components"]=[c for c in m["components"] if c["name"]=="python"]; json.dump(m,open(sys.argv[2],"w"),indent=1)' \
      tools/release/toolchain.json "$B/toolchain-python-only.json"
    nix develop .#re --command "${SB[@]}" python3 -I tools/release/fetch_toolchain.py --manifest "$B/toolchain-python-only.json" \
      --cache "$CACHE" --offline 2>&1 | tail -2
    TC+=(--toolchain-manifest "$B/toolchain-python-only.json")
    echo "PREFLIGHT ONLY: no compiler, CMake or Ninja in this payload" > "$B/PARTIAL"
  else
    rm -f "$B/PARTIAL"
  fi
  nix develop .#re --command "${SB[@]}" python3 -I tools/release/assemble_payload.py --out "$B/payload" --replace \
    --launcher "$B/launcher/Project Pyrrhus.exe" --ffmpeg "$FFMPEG" --pso-template "$PSO" "${TC[@]}" 2>&1 | tail -4 | cut -c1-200
  rm -f "$B/iscc/Project-Pyrrhus-setup.exe"
  KZ2_WT_NOGPU=1 nix develop --command tools/release/wizard_test.sh compile "$B/payload" "$B/iscc" 2>&1 \
    | grep -ai "error\|successful\|warning\|compile:" | head -8 | cut -c1-200
  [[ -f "$B/iscc/Project-Pyrrhus-setup.exe" ]] || { echo "vm_kit: no setup exe (see $B/iscc/iscc.txt)"; exit 1; }
  nix develop .#re --command "${SB[@]}" python3 -I tools/release/pack_zip.py --payload "$B/payload" \
    --out "$B/zip/$(zip_name "$VER")" --replace 2>&1 | tail -2 | cut -c1-200 || echo "vm_kit: zip refused"
  echo "$VER" > "$B/VERSION"
  ;;
stage)
  S="$K/shared/kz2"; VER="$(cat "$B/VERSION")"
  rm -rf "$S/kit"; mkdir -p "$S/kit" "$S/game/dump" "$S/game/update" "$S/game/eboot"
  # iso_fixture.py: 19-iso builds its synthetic ISO with it (a test helper, never in the payload)
  cp "$B/iscc/Project-Pyrrhus-setup.exe" tools/release/vm_test.py tools/release/iso_fixture.py "$S/kit/"
  # COMMANDS.md with the guest's path of the shared folder (KZ2_VMKIT_SHARE, e.g. a UNC path; else left as <SHARE>)
  python3 -c 'import sys; t=open(sys.argv[1]).read(); open(sys.argv[2],"w").write(t.replace("<SHARE>", sys.argv[3]))' \
    tools/release/vm_kit/COMMANDS.md "$S/kit/COMMANDS.md" "${KZ2_VMKIT_SHARE:-<SHARE>}"
  ZIP="$B/zip/$(zip_name "$VER")"; [[ -f "$ZIP" ]] && cp "$ZIP" "$S/kit/"
  [[ -f "$B/PARTIAL" ]] && cp "$B/PARTIAL" "$S/kit/NOT-FOR-THE-VM.txt"
  (cd "$S/kit" && sha256sum -- * | grep -v "SHA256SUMS" > SHA256SUMS.txt)
  ln -sfn "$G_DUMP/PS3_GAME" "$S/game/dump/PS3_GAME"
  ln -sfn "$G_UPDATE" "$S/game/update/BCUS98116"
  ln -sfn "$G_EBOOT" "$S/game/eboot/EBOOT.elf"
  {
    echo "# Project Pyrrhus $VER VM kit ($(git rev-parse --short HEAD), $(date -u +%F))"
    [[ -f "$B/PARTIAL" ]] && echo "# $(cat "$B/PARTIAL")"
    echo "## shared/kz2/kit (size, sha256, name)"
    (cd "$S/kit" && for f in *; do printf '%12d  %s  %s\n' "$(stat -c %s "$f")" "$(sha256sum "$f" | cut -c1-64)" "$f"; done)
    echo "## build artifacts"
    for f in "$B/launcher/Project Pyrrhus.exe" "$B/payload/manifest.json"; do
      printf '%12d  %s  %s\n' "$(stat -c %s "$f")" "$(sha256sum "$f" | cut -c1-64)" "${f#"$K/"}"; done
    python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print("payload: %d files, %s bytes; commit %s" % (m["count"], format(m["total_bytes"], ","), m.get("repo_commit", "?")))' "$B/payload/manifest.json"
  } > "$K/ARTIFACTS.txt"
  cat "$K/ARTIFACTS.txt"
  ;;
preflight)
  PY="$B/py"
  if [[ ! -f "$PY/python.exe" ]]; then
    mkdir -p "$PY"; python3 -m zipfile -e "$(ls "$CACHE"/downloads/python/python-*-embed-amd64.zip | head -1)" "$PY"
  fi
  # default: every step in vm_test.ORDER, the order COMMANDS.md gives the tester
  STEPS=("$@"); (( ${#STEPS[@]} )) || read -r -a STEPS <<< "$(python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import vm_test; print(" ".join(vm_test.ORDER))' "$ROOT/tools/release")"
  # KZ2_VMKIT_FAKEBUILD=DIR (kz2.exe + at3_standalone.dll of a developer build): the step name fake-build before
  # 07-launch links them into the partial build and stamps it (test only), so the launcher's run path is walked
  KZ2_WT_FAKEBUILD="${KZ2_VMKIT_FAKEBUILD:-}" KZ2_WT_NOGPU=1 KZ2_WT_STATE="$K/pre" nix develop --command tools/release/wizard_test.sh vmtest "$K/shared/kz2" "$PY" "${STEPS[@]}"
  ;;
*) echo "unknown mode $MODE" >&2; exit 2 ;;
esac
