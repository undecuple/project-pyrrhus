#!/usr/bin/env python3
# Adapted from ps3recomp PR #621 by Max Leiter (MIT), commit 5d3494a95a03.
# Copyright (c) 2026 Ned Heller / sp00nznet and contributors.
# Licence: licenses/ps3recomp-LICENSE.txt.
"""sys_lwmutex_create / sys_lwmutex_trylock in the context-style HLE (runtime/ppu/ppu_sysprx.cpp).

Builds the real handlers (pulled verbatim out of ppu_sysprx.cpp) into a small
host program over stubbed guest memory and checks:
  - sys_lwmutex_t.attribute (+0x08) is protocol | recursive, both words of
    sys_lwmutex_attribute_t, not the protocol alone;
  - a trylock of a lwmutex another thread holds answers CELL_EBUSY (0x8001000A),
    not 0x8001000B, which is CELL_ETIMEDOUT;
  - a free lwmutex is taken, and the owner's trylock nests;
  - cellSyncMutex rejects misalignment without changing guest memory, and
    aligned ticket locking and null-pointer errors remain supported.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def extract(src, name):
    m = re.search(r'static void %s\(ppu_context\* ctx\)\s*\{' % name, src)
    assert m, name + ' not found'
    i, depth = m.end(), 1
    while depth:
        depth += {'{': 1, '}': -1}.get(src[i], 0)
        i += 1
    return src[m.start():i]


HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
static uint8_t mem[0x10000];
static void vm_write32(uint32_t a, uint32_t v) { for (int i = 0; i < 4; i++) mem[a + i] = (uint8_t)(v >> (24 - 8 * i)); }
static uint32_t vm_read32(uint32_t a) { return (uint32_t)mem[a] << 24 | mem[a + 1] << 16 | mem[a + 2] << 8 | mem[a + 3]; }
struct ppu_context { uint64_t gpr[32]; uint64_t thread_id; };
#define PS3_GETENV_ONCE(name) getenv(name)
#define LWM_OWNER 0x00
#define LWM_ATTR  0x08
#define LWM_RECUR 0x0C
#define LWM_SELF(ctx) ((uint32_t)(ctx)->thread_id ? (uint32_t)(ctx)->thread_id : 0x7FFFFFFEu)
/* The kernel-object fixture: one binary lock for this test's lwmutex. */
struct LwmSlot { int held; long holder; long long acq_us, acq_fences; unsigned long long acq_cpu_us; };
static LwmSlot s_slot;
static struct LwmSlot* lwm_slot(uint32_t) { return &s_slot; }
static void lwm_release(struct LwmSlot* sl) { sl->held = 0; }
static int lwm_try(struct LwmSlot* sl) { if (sl->held) return 0; sl->held = 1; return 1; }
static int lwm_trace() { return 0; }
static struct LwmSlot* lwm_find(uint32_t) { return nullptr; }
static long long lwm_now_us() { return 0; }
static long long g_gcm_ref_pub_count = 0;
static unsigned long long ppu_thread_cpu_us(unsigned) { return 0; }
%s
%s
static int fails = 0;
static void check(bool ok, const char* what, unsigned long long got)
{
    printf("[%%s] %%s (0x%%llX)\n", ok ? "PASS" : "FAIL", what, got);
    fails += !ok;
}
int main() {
    const uint32_t LWM = 0x1000, ATTR = 0x2000;
    memset(mem, 0, sizeof mem);
    vm_write32(ATTR + 0, 0x2);      /* protocol: SYS_SYNC_PRIORITY */
    vm_write32(ATTR + 4, 0x10);     /* SYS_SYNC_RECURSIVE */
    ppu_context c = {};
    c.gpr[3] = LWM; c.gpr[4] = ATTR; c.thread_id = 1;
    sys_lwmutex_create(&c);
    check(c.gpr[3] == 0, "create returns CELL_OK", c.gpr[3]);
    check(vm_read32(LWM + LWM_ATTR) == 0x12, "attribute is protocol | recursive", vm_read32(LWM + LWM_ATTR));

    c = {}; c.gpr[3] = LWM; c.thread_id = 1;
    sys_lwmutex_trylock(&c);
    check(c.gpr[3] == 0 && vm_read32(LWM + LWM_OWNER) == 1, "trylock on a free lwmutex takes it", c.gpr[3]);
    c = {}; c.gpr[3] = LWM; c.thread_id = 1;
    sys_lwmutex_trylock(&c);
    check(c.gpr[3] == 0 && vm_read32(LWM + LWM_RECUR) == 2, "the owner's trylock nests", c.gpr[3]);
    c = {}; c.gpr[3] = LWM; c.thread_id = 2;
    sys_lwmutex_trylock(&c);
    check(c.gpr[3] == UINT64_C(0xFFFFFFFF8001000A), "trylock while another thread holds it is CELL_EBUSY", c.gpr[3]);
    check(vm_read32(LWM + LWM_OWNER) == 1 && vm_read32(LWM + LWM_RECUR) == 2,
          "busy trylock preserves owner and recursion", vm_read32(LWM + LWM_OWNER));
    c = {}; c.gpr[3] = LWM; /* no attributes */
    sys_lwmutex_create(&c);
    check(vm_read32(LWM + LWM_ATTR) == 0, "null attributes remain supported", vm_read32(LWM + LWM_ATTR));
    return fails ? 1 : 0;
}
'''


def check_lwmutex(toolkit):
    cxx = os.environ.get('CXX') or shutil.which('c++') or shutil.which('g++') or shutil.which('clang++')
    if not cxx:
        raise SystemExit('FAIL: no C++ compiler')
    src = (toolkit / 'runtime/ppu/ppu_sysprx.cpp').read_text()
    code = HARNESS % (extract(src, 'sys_lwmutex_create'), extract(src, 'sys_lwmutex_trylock'))
    with tempfile.TemporaryDirectory() as tmp:
        c = Path(tmp) / 't.cpp'
        exe = Path(tmp) / 't'
        c.write_text(code)
        r = subprocess.run([cxx, '-std=c++17', '-O1', '-w', str(c), '-o', str(exe)], capture_output=True, text=True, timeout=60)
        if r.returncode:
            print(r.stderr[-2000:])
            raise SystemExit('FAIL: harness did not compile')
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
        print(r.stdout, end='')
        if r.returncode:
            raise SystemExit('FAIL: lwmutex semantics')
    print('PASS: lwmutex attribute word and trylock result')


def check_cellsync(toolkit):
    cc = os.environ.get('CC') or shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if not cc:
        raise SystemExit('FAIL: no C compiler')
    source = (toolkit / 'libs/sync/cellSync.c').read_text()
    # Compile the entire production mutex section, including its real headers,
    # atomics and coherence calls. The unrelated barrier/queue APIs are omitted.
    end = source.index('/* =========================================================================\n * Barrier')
    with tempfile.TemporaryDirectory(prefix='kz2-cellsync-') as tmp:
        source_file = Path(tmp) / 'mutex.c'
        exe = Path(tmp) / 'mutex'
        source_file.write_text(source[:end])
        subprocess.run([cc, '-std=c11', '-O1',
                        '-I', str(toolkit), '-I', str(toolkit / 'include'),
                        '-I', str(toolkit / 'libs/sync'),
                        str(source_file), str(ROOT / 'tools/runtime/test_cellsync_mutex.c'),
                        '-o', str(exe)], check=True, timeout=60)
        subprocess.run([str(exe)], check=True, timeout=10)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolkit', type=Path, help='patched toolkit (also accepts a tree without patch 3010 for a negative control)')
    args = parser.parse_args()
    candidates = [args.toolkit] if args.toolkit else [
        Path(os.environ['KZ2_PATCHED_DIR']) if os.environ.get('KZ2_PATCHED_DIR') else None,
        Path(os.environ['KZ2_OUT']) / 'ps3recomp-patched' if os.environ.get('KZ2_OUT') else None,
        ROOT / 'work/runtime/ps3recomp-patched', ROOT / 'work/ps3recomp-patched',
    ]
    toolkit = next((p.resolve() for p in candidates if p and (p / 'runtime/ppu/ppu_sysprx.cpp').is_file()), None)
    if toolkit is None:
        if args.toolkit:
            raise SystemExit('FAIL: no toolkit at --toolkit path')
        print('SKIP: no patched toolkit; run tools/ps3recomp-patched.sh')
        return
    # Both run even when one fails, so a negative control diagnoses each fix.
    failures = []
    for check in (check_lwmutex, check_cellsync):
        try:
            check(toolkit)
        except (SystemExit, subprocess.SubprocessError) as exc:
            failures.append(str(exc))
    if failures:
        raise SystemExit('\n'.join(failures))
    print('PASS: patch 3010 sync mutex semantics (no game data)')


if __name__ == '__main__':
    main()
