#!/usr/bin/env python3
"""Coverage of the SPU byte-permute helpers' vector paths (KZ2 patches 7041 and 7042).

On ARM64 these run the NEON paths (TBL); on x86-64 with SSE4.1 the pshufb paths. Each is compared with the byte loop it
replaced (spu_shufb_ref, spu__byteperm_ref), exhaustively where the inputs are small:
  - shufb, shufb1 and the hoisted shufb1 decode (spu_shufb1_dec + spu_shufb1_h): every control byte value 0x00-0xFF
    in every one of the 16 lanes (the other lanes random), with 4 random (a, b) pairs, plus every value in all lanes
    at once -- which covers each decode class: 0x00-0x7F select a byte of a or b, 0x80-0xBF give 0x00, 0xC0-0xDF give
    0xFF, 0xE0-0xFF give 0x80;
  - spu__byteperm: every d in -31..31 with wrap 0 and 1, 64 random quadwords each;
  - statically, every spu__byteperm call in spu_helpers.h: its shift is masked to 0x1F or 0x0F before the call (so
    |d| <= 31, the range the vector index assumes) and a shift without wrap returns early for sh >= 16.
Prints the case counts. POSIX host with a C compiler; no game data. Needs work/ps3recomp-patched (or KZ2_PATCHED_DIR).
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

HARNESS = r'''#include "spu_helpers.h"
#include <stdio.h>
#include <string.h>
int g_kz3_spu_xr = 1, g_kz3_spu_xrq = 1 | 2, g_kz3_spu_slowcg = 0, g_kz3_xr_stats = 0, g_kz3_fma_stats = 0;
void kz3_spu_xr_note(int op, unsigned m, const uint32_t* a, const uint32_t* b, const uint32_t* c, const uint32_t* r,
                     const void* ra) { (void)op; (void)m; (void)a; (void)b; (void)c; (void)r; (void)ra; }
void kz3_spu_fma_note(const double s[4], int ftz) { (void)s; (void)ftz; }
static uint64_t s = 0x9E3779B97F4A7C15ull;
static uint32_t rnd(void) { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return (uint32_t)(s >> 11); }
static u128 rq(void) { u128 v; for (int i = 0; i < 4; i++) v._u32[i] = rnd(); return v; }
static int same(u128 x, u128 y) { return memcmp(&x, &y, 16) == 0; }
int main(void) {
    long n_shufb = 0, n_shufb1 = 0, n_dec = 0, bad = 0;
    for (int pass = 0; pass < 2; pass++)
    for (int lane = 0; lane < (pass ? 1 : 16); lane++)
    for (int v = 0; v < 256; v++)
    for (int k = 0; k < 4; k++) {
        u128 a = rq(), b = rq(), c = rq();
        if (pass) memset(c._u8, v, 16); else c._u8[lane] = (uint8_t)v;
        if (!same(spu_shufb(a, b, c), spu_shufb_ref(a, b, c))) { if (bad++ < 5) printf("shufb differs: lane %d value 0x%02X\n", lane, v); }
        n_shufb++;
        if (!same(spu_shufb1(a, c), spu_shufb_ref(a, a, c))) { if (bad++ < 5) printf("shufb1 differs: lane %d value 0x%02X\n", lane, v); }
        n_shufb1++;
#ifdef SPU_SHUFB1_DEC
        if (!same(spu_shufb1_h(a, spu_shufb1_dec(c), c), spu_shufb_ref(a, a, c))) { if (bad++ < 5) printf("shufb1 decode differs: lane %d value 0x%02X\n", lane, v); }
        n_dec++;
#endif
    }
    long n_perm = 0;
#if HAVE_BYTEPERM
    for (int d = -31; d <= 31; d++)
    for (int wrap = 0; wrap < 2; wrap++)
    for (int k = 0; k < 64; k++) {
        u128 a = rq();
        if (!same(spu__byteperm(a, d, wrap), spu__byteperm_ref(a, d, wrap))) { if (bad++ < 5) printf("byteperm differs: d %d wrap %d\n", d, wrap); }
        n_perm++;
    }
#endif
    printf("cases: shufb %ld, shufb1 %ld, shufb1 decode %ld, byteperm %ld; %ld differ\n", n_shufb, n_shufb1, n_dec, n_perm, bad);
    return bad ? 1 : 0;
}
'''

CALL = re.compile(r'spu__byteperm\(a,\s*(-?)sh,\s*([01])\)')


def static_check(text):
    """Each spu__byteperm call site (outside the definitions): the helper, its mask, the early return. Returns rows."""
    rows, bad = [], []
    for line in text.splitlines():
        m = CALL.search(line)
        if not m or 'SPU_HOT' in line or 'SPU_XR_COLD' in line:
            continue
        name = re.search(r'u128 (spu_\w+)\(', line)
        name = name.group(1) if name else '?'
        mask = re.search(r'&\s*=?\s*(0x1F|0x0F|31|15)\b', line) or re.search(r'sh\s*&=\s*(0x1F|0x0F)', line)
        wrap = m.group(2) == '1'
        guard = wrap or re.search(r'sh\s*>=\s*16', line) is not None
        ok = bool(mask) and guard
        rows.append((name, ('-' if m.group(1) else '+') + 'sh', 'wrap' if wrap else 'shift', mask.group(1) if mask else 'NONE',
                     'n/a' if wrap else ('sh>=16 returns' if guard else 'NO GUARD'), ok))
        if not ok:
            bad.append(name)
    return rows, bad


def main():
    if os.name == 'nt':
        print('SKIP: needs a POSIX host C compiler')
        return
    cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if not cc:
        print('SKIP: no host C compiler')
        return
    tk = None
    for p in (Path(os.environ['KZ2_PATCHED_DIR']) if os.environ.get('KZ2_PATCHED_DIR') else None,
              Path(os.environ['KZ2_OUT']) / 'ps3recomp-patched' if os.environ.get('KZ2_OUT') else None,
              ROOT / 'work/ps3recomp-patched'):
        if p and (p / 'runtime/spu/spu_helpers.h').is_file():
            tk = p
            break
    if tk is None:
        print('SKIP: no patched toolkit; run tools/ps3recomp-patched.sh')
        return
    header = (tk / 'runtime/spu/spu_helpers.h').read_text()
    rows, bad = static_check(header)
    for r in rows:
        print(f"[{'PASS' if r[5] else 'FAIL'}] byteperm caller {r[0]}: d = {r[1]} ({r[2]}), shift masked {r[3]}, {r[4]}")
    if not rows or bad:
        raise SystemExit('FAIL: a spu__byteperm caller can pass |d| > 31' if bad else 'FAIL: no spu__byteperm callers found')
    machine = platform.machine().lower()
    arch = []
    if machine in ('x86_64', 'amd64'):
        arch = (['-arch', 'x86_64'] if sys.platform == 'darwin' else []) + ['-msse4.1', '-mfma']
    elif machine not in ('arm64', 'aarch64'):
        print(f'SKIP: no vector path to cover on {machine}')
        return
    inc = []
    for d in ('runtime/spu', 'include', 'runtime/ppu', 'runtime/memory', 'runtime/syscalls', 'runtime/platform'):
        inc += ['-I', str(tk / d)]
    have_perm = 'spu__byteperm_ref' in header
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / 'cov.c').write_text(HARNESS)
        exe = t / 'cov'
        subprocess.run([cc, *arch, '-O2', '-std=gnu17', '-fno-strict-aliasing', '-DPS3RECOMP_LL_STRIPED=1', '-w',
                        f'-DHAVE_BYTEPERM={1 if have_perm else 0}', *inc, str(t / 'cov.c'), '-o', str(exe), '-lm'], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        sys.stdout.write(r.stdout)
        if r.returncode:
            raise SystemExit('FAIL: a vector byte permute differs from its byte loop')
    print(f'PASS: shufb/shufb1/decode over every control byte in every lane, byteperm over d -31..31, on {machine} '
          '(no game data)')


if __name__ == '__main__':
    main()
