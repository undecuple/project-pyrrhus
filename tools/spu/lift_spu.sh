#!/usr/bin/env bash
# Lift Killzone 2's SPU code (the WWS job-manager policy module, the WWS job modules, the SPU ELFs) and write the
# registration TU the port build picks up (port/kz2/CMakeLists.txt: SPU_DIR/<image>/spu_recomp.c + SPU_DIR/spu_workloads.c,
# constructor-registered). Recipe from Project Helghast tools/spu/lift_spu.sh + lift_spu.py + gen_spu_register.py.
#
#   nix develop .#re --command tools/sandbox.sh -- env KZ2_OUT=work/spu tools/spu/lift_spu.sh [-j N] [--only NAME,...] [--kinds pm,job,elf]
#
# Needs $KZ2_OUT/ps3recomp-patched (tools/ps3recomp-patched.sh). Inputs: the EBOOT of KZ2_EBOOT_VER (129 default, 101)
# and re/wws_jobs_v<VER>.tsv (image table). Outputs (derived from the binary, never committed):
#   $KZ2_OUT/spu/lift/<image>/spu_recomp.{c,h}, lift.log    one dir per image (pm_*, job_*, elf_*)
#   $KZ2_OUT/spu/lift/spu_workloads.c                        kz2_spu_register_all() (tools/spu/gen_spu_register.py)
#   $KZ2_OUT/spu/spu_lift.json, kz2_spu_manifest.json, elf_in/ (wrapped inputs), eboot_ver
# Image ids: PM 2 (the runtime's WWS hooks key on it), ELFs 30+, job modules 200+.
# Then build: tools/build-kz2.sh passes -DSPU_DIR=$KZ2_OUT/spu/lift when that directory has a spu_workloads.c.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
OUT="${KZ2_OUT:-work}"
PT="$OUT/ps3recomp-patched"
[[ -f "$PT/tools/spu_lifter.py" ]] || { echo "no $PT: run tools/ps3recomp-patched.sh first" >&2; exit 3; }
S="$OUT/spu"
for d in "$S/lift" "$S/elf_in"; do [[ -e "$d" ]] && "$ROOT/tools/safe_rm.sh" "$d"; done
mkdir -p "$S"
python3 tools/spu/lift_spu.py --ps3recomp "$PT" --out "$S" "$@"
python3 tools/spu/gen_spu_register.py --lift "$S"
