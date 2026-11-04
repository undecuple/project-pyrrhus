#!/usr/bin/env bash
# Host test: the GPU post-kernel harness (tools/spu/gpu_post_test.c with port/kz2/spu/gpu_post_hlsl.h)
# and the post-chain map module (port/kz2/spu/kz2_post_map.c) cross-compile for Windows without warnings, and the
# shader source carries both kernels and the mutation switch. The GPU run itself needs Proton and the gpu lock:
#   tools/agents/lock.sh gpu -- nix develop --command tools/proton-test.sh --name N build/gpu_post_test/gpu_post_test.exe CASES
# Run: nix develop .#win --command tools/sandbox.sh -- tools/spu/test_gpu_post.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
T="$(mktemp -d "${TMPDIR:-/tmp}/kz2-gpupost.XXXXXX")"; trap 'rm -rf "$T"' EXIT
fail=0
x86_64-w64-mingw32-gcc -O2 -Wall -Werror -I port/kz2/spu tools/spu/gpu_post_test.c -o "$T/g.exe" \
  -ld3d12 -ldxgi -ld3dcompiler -ldxguid -static 2> "$T/g.err" || { echo "harness build failed:"; head -5 "$T/g.err"; fail=1; }
PT="${KZ2_PATCHED_DIR:-work/ps3recomp-patched}"
if [[ -f "$PT/runtime/spu/spu_context.h" ]]; then
  x86_64-w64-mingw32-gcc -O2 -Wall -Werror -fsyntax-only -I "$PT/runtime/spu" -I "$PT/runtime" -I "$PT/include" \
    port/kz2/spu/kz2_post_map.c 2> "$T/m.err" || { echo "kz2_post_map.c:"; head -5 "$T/m.err"; fail=1; }
else echo "skip kz2_post_map.c syntax check: no $PT (tools/ps3recomp-patched.sh)"; fi
for k in 'kind == 71u' 'kind == 72u' 'KZ2_GPU_POST_MUTATE' 'avgb'; do
  grep -q "$k" port/kz2/spu/gpu_post_hlsl.h || { echo "gpu_post_hlsl.h lacks $k"; fail=1; }
done
grep -q 'g_kz2_pmap_dma' port/patches/7015-post-map-hooks.patch || { echo "patch 7015 lacks the DMA hook"; fail=1; }
echo "test_gpu_post: $([[ $fail == 0 ]] && echo PASS || echo FAIL)"
exit $fail
