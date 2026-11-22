#!/usr/bin/env python3
"""Every public SPU helper gives the same bits on its SSE4.1 path and on its scalar path (KZ2 patch 6086).

The Windows build compiles the lifted SPU code with -msse4.1 -mfma, so spu_helpers.h's SSE4.1 branches decide what
Killzone 2's SPU jobs compute. An ARM64 build (native macOS) has no SSE4.1 and runs the scalar #else branches instead.
This test generates one C program that calls each public u128 helper (spu_*, about 150) on the same deterministic
inputs, mixed towards the hard cases (float subnormals, numbers near the subnormal edge and near overflow, exponent-255
words, zeros, NaN/Inf patterns), builds it twice from the patched toolkit and compares the output line by line:
  - on an Apple silicon Mac: arm64 (scalar) against x86_64 -msse4.1 -mfma run under Rosetta 2;
  - on an x86-64 host: -mno-sse4.1 (scalar) against -msse4.1 -mfma (needs an FMA3 CPU).
Before 6086, spu_fma, spu_fms and spu_fnms differed: the scalar loops kept subnormal results that patch 1040 flushes.
The runtime gates take their defaults after spu_drain.c's start-up (no environment overrides). No game data is read.
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = 3000

PRELUDE = r'''#include "spu_helpers.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int g_kz3_spu_xr = 1, g_kz3_spu_xrq = 1 | 2, g_kz3_spu_slowcg = 0, g_kz3_xr_stats = 0, g_kz3_fma_stats = 0;
void kz3_spu_xr_note(int op, unsigned m, const uint32_t* a, const uint32_t* b, const uint32_t* c, const uint32_t* r,
                     const void* ra) { (void)op; (void)m; (void)a; (void)b; (void)c; (void)r; (void)ra; }
void kz3_spu_fma_note(const double s[4], int ftz) { (void)s; (void)ftz; }
static uint64_t s;
static uint32_t rnd(void) { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return (uint32_t)(s >> 11); }
static const uint32_t SP[] = {0u, 0x80000000u, 1u, 0x807FFFFFu, 0x007FFFFFu, 0x00800000u, 0x80800000u, 0x3F800000u,
  0xBF800000u, 0x7F800000u, 0xFF800000u, 0x7FC00000u, 0x7F800001u, 0xFFFFFFFFu, 0x7F7FFFFFu, 0xFF7FFFFFu, 0x4B000000u,
  0xCF000000u, 0x4F000000u, 0x4F800000u, 0x3EFFFFFFu, 0x33800000u, 0x0000FFFFu, 0x80u, 0x1Fu, 0x3F7FFFFFu, 0x00400000u,
  0x01000000u, 0x0C000000u, 0x7EFFFFFFu, 0x5F000000u, 0xDF000000u};
static uint32_t lane(void) {
  uint32_t m = rnd() % 6;
  if (m == 0) return rnd();
  if (m == 1) return SP[rnd() % (sizeof SP / sizeof SP[0])];
  if (m == 2) { float f = (float)((int)(rnd() % 20001) - 10000) / (float)(1 + rnd() % 97); uint32_t u; memcpy(&u, &f, 4); return u; }
  if (m == 3) return rnd() & 0x807FFFFFu;
  if (m == 4) return (rnd() & 0x80FFFFFFu) | ((1u + rnd() % 3u) << 24);
  return (rnd() & 0x807FFFFFu) | ((0x60u + rnd() % 0x3Fu) << 23);
}
static u128 vec(void) { u128 v; for (int i = 0; i < 4; i++) v._u32[i] = lane(); return v; }
static void pr(const char* n, int k, u128 a, u128 b, u128 c, int imm, u128 r) {
  printf("%s %d %08X%08X%08X%08X %08X%08X%08X%08X %08X%08X%08X%08X %d => %08X%08X%08X%08X\n", n, k,
    a._u32[0], a._u32[1], a._u32[2], a._u32[3], b._u32[0], b._u32[1], b._u32[2], b._u32[3],
    c._u32[0], c._u32[1], c._u32[2], c._u32[3], imm, r._u32[0], r._u32[1], r._u32[2], r._u32[3]);
}
static int imm_for(const char* t, const char* p) {
  uint32_t r = rnd();
  if (!strcmp(p, "i8")) return (int)(r % 256);
  if (!strcmp(p, "i7") || !strcmp(p, "sh")) return (int)(r % 128) - 64 + 64 * (int)(r >> 31);
  if (!strcmp(t, "uint16_t")) return (int)(r & 0xFFFF);
  return (int)(r % 1024) - 512;
}
int main(int argc, char** argv) {
  int n = argc > 1 ? atoi(argv[1]) : 1000;
'''
SKIP = {'spu_mfspr', 'spu_fscrrd', 'spu_shufb_ref', 'spu_shufb_1035'}   # state readers and internal references


def generate(header):
    helpers = {}
    for name, args in re.findall(r'u128 (spu_[a-z0-9_]+)\(([^)]*)\)', header):
        if name.startswith('spu__') or name in SKIP or name in helpers:
            continue
        parts = [p.strip() for p in args.split(',') if p.strip()]
        if not parts or not all(re.fullmatch(r'(u128|int|int32_t|uint16_t|uint32_t) [a-z0-9]+', p) for p in parts):
            continue
        kinds = ['v' if p.startswith('u128') else 'i' for p in parts]
        if kinds[0] != 'v' or kinds.count('i') > 1 or (kinds.count('i') == 1 and kinds[-1] != 'i'):
            continue
        imm = parts[-1].split() if kinds[-1] == 'i' else None
        helpers[name] = (kinds.count('v'), imm)
    body = []
    for name, (nv, imm) in sorted(helpers.items()):
        call = ', '.join(['a', 'b', 'c'][:nv] + (['(%s)imm' % imm[0]] if imm else []))
        imm_expr = 'imm_for("%s", "%s")' % (imm[0], imm[1]) if imm else '0'
        body.append('  s = 0x9E3779B97F4A7C15ull ^ %du; for (int k = 0; k < n; k++) { u128 a = vec(), b = vec(), c = vec(); '
                    'int imm = %s; u128 r = %s(%s); pr("%s", k, a, b, c, imm, r); }\n'
                    % (sum(map(ord, name)), imm_expr, name, call, name))
    return PRELUDE + ''.join(body) + '  return 0;\n}\n', len(helpers)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolkit', type=Path, help='patched toolkit (also accepts a tree without patch 6086 for a negative control)')
    parser.add_argument('--cases', type=int, default=CASES)
    parser.add_argument('--list', action='store_true', help='print every helper with its case count (the full run)')
    args = parser.parse_args()
    candidates = [args.toolkit] if args.toolkit else [
        Path(os.environ['KZ2_PATCHED_DIR']) if os.environ.get('KZ2_PATCHED_DIR') else None,
        Path(os.environ['KZ2_OUT']) / 'ps3recomp-patched' if os.environ.get('KZ2_OUT') else None,
        ROOT / 'work/runtime/ps3recomp-patched', ROOT / 'work/ps3recomp-patched',
    ]
    toolkit = next((p.resolve() for p in candidates if p and (p / 'runtime/spu/spu_helpers.h').is_file()), None)
    if toolkit is None:
        if args.toolkit:
            raise SystemExit('FAIL: no toolkit at --toolkit path')
        print('SKIP: no patched toolkit; run tools/ps3recomp-patched.sh')
        return
    cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if not cc or os.name == 'nt':
        print('SKIP: needs a POSIX host C compiler')
        return
    machine = platform.machine().lower()
    if sys.platform == 'darwin' and machine == 'arm64':
        if subprocess.run(['arch', '-x86_64', '/usr/bin/true'], capture_output=True).returncode:
            print('SKIP: Rosetta 2 is not installed (the SSE4.1 side runs as x86_64)')
            return
        sides = {'scalar': (['-arch', 'arm64'], []), 'sse41': (['-arch', 'x86_64', '-msse4.1', '-mfma'], ['arch', '-x86_64'])}
    elif machine in ('x86_64', 'amd64'):
        sides = {'scalar': (['-mno-sse4.1', '-mno-fma'], []), 'sse41': (['-msse4.1', '-mfma'], [])}
    else:
        print(f'SKIP: no SSE4.1 side on {machine}')
        return
    src, count = generate((toolkit / 'runtime/spu/spu_helpers.h').read_text())
    inc = []
    for d in ('runtime/spu', 'include', 'runtime/ppu', 'runtime/memory', 'runtime/syscalls', 'runtime/platform'):
        inc += ['-I', str(toolkit / d)]
    flags = ['-O2', '-std=gnu17', '-ffp-contract=off', '-fno-strict-aliasing', '-DPS3RECOMP_LL_STRIPED=1', '-w']
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / 'helpers.c').write_text(src)
        for side, (cflags, runner) in sides.items():
            exe = t / ('h_' + side)
            subprocess.run([cc, *cflags, *flags, *inc, str(t / 'helpers.c'), '-o', str(exe), '-lm'], check=True)
            out[side] = subprocess.run([*runner, str(exe), str(args.cases)], capture_output=True, text=True,
                                       check=True, timeout=600).stdout.splitlines()
    a, b = out['scalar'], out['sse41']
    assert len(a) == len(b) == count * args.cases, 'output length differs'
    bad = {}
    for x, y in zip(a, b):
        if x != y:
            assert x.split(' => ')[0] == y.split(' => ')[0], 'inputs differ between the two builds'
            bad.setdefault(x.split()[0], []).append((x, y))
    for name, rows in sorted(bad.items()):
        x, y = rows[0]
        print(f'[FAIL] {name}: {len(rows)}/{args.cases} cases differ; first: {x.split(" => ")[0]}\n'
              f'       scalar {x.split(" => ")[1]}  sse4.1 {y.split(" => ")[1]}')
    if args.list:
        names = sorted({x.split()[0] for x in a})
        for name in names:
            n = sum(1 for x in a if x.split()[0] == name)
            print(f"[{'FAIL' if name in bad else 'PASS'}] {name}: {n} cases")
    if bad:
        raise SystemExit(f'FAIL: {len(bad)} of {count} SPU helpers differ between the scalar and SSE4.1 paths')
    print(f'PASS: all {count} SPU helpers give the same bits on the scalar and SSE4.1 paths '
          f'({count * args.cases} cases, no game data)')


if __name__ == '__main__':
    main()
