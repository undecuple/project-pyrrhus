#!/usr/bin/env python3
"""sys_lwcond wait/signal on a POSIX host (KZ2 patch 6089, runtime/ppu/ppu_sysprx.cpp).

Builds the real lwmutex slot code and the whole lwcond section (pulled verbatim out of ppu_sysprx.cpp) with the
toolkit's POSIX shim (win32_compat.c, ps3_evcv.h) into a small host program over stubbed guest memory, and checks:
  - sys_lwcond_create gives the lwcond a slot (its waiter count is readable);
  - a thread waiting on the lwcond releases the paired lwmutex while it sleeps, so another thread can take it;
  - sys_lwcond_signal wakes it, and it returns CELL_OK holding the lwmutex again with its owner and recursion count;
  - a timed wait nobody signals returns CELL_ETIMEDOUT (0x8001000B) after the timeout, not at once.
Before 6089 the slot table, the wait and the wake were Windows-only: off Windows the wait returned 0 at once without
releasing the lwmutex, which deadlocked the game's FIOS media threads on the first native macOS boot.
On Windows hosts the test prints SKIP: the code there was already real and the shim under test is POSIX-only.
No game data is read.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def region(src, start, end_func):
    """Text from the line holding `start` to the closing brace of function `end_func`."""
    i = src.find(start)
    assert i >= 0, start + ' not found'
    m = re.compile(r'static void %s\([^)]*\)\s*\{' % re.escape(end_func)).search(src, i)
    assert m, end_func + ' not found'
    j, depth = m.end(), 1
    while depth:
        depth += {'{': 1, '}': -1}.get(src[j], 0)
        j += 1
    return src[i:j]


HARNESS = r'''
#include "win32_compat.h"
#include "ps3_evcv.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <pthread.h>
#include <time.h>
static uint8_t mem[0x10000];
static void vm_write32(uint32_t a, uint32_t v) { for (int i = 0; i < 4; i++) mem[a + i] = (uint8_t)(v >> (24 - 8 * i)); }
static uint32_t vm_read32(uint32_t a) { return (uint32_t)mem[a] << 24 | mem[a + 1] << 16 | mem[a + 2] << 8 | mem[a + 3]; }
struct ppu_context { uint64_t gpr[32]; uint64_t thread_id; uint64_t lr; };
#define LWM_OWNER 0x00
#define LWM_RECUR 0x0C
extern "C" { volatile long long g_gcm_ref_pub_count = 0;
             unsigned long long ppu_thread_cpu_us(unsigned) { return 0; }
             unsigned ppu_thread_prof_pc(unsigned) { return 0; }
             void ppu_thread_note_block(uint64_t) {} }
%s
%s
static int fails = 0;
static void check(bool ok, const char* what, unsigned long long got)
{
    printf("[%%s] %%s (0x%%llX)\n", ok ? "PASS" : "FAIL", what, got);
    fails += !ok;
}
static long long now_ms() { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000ll + t.tv_nsec / 1000000; }
static const uint32_t LWM = 0x1000, LWC = 0x2000;
struct Waiter { uint64_t timeout_us; volatile int done; uint32_t rc, owner, recur; long long ms; };
static void hold(uint32_t tid)   /* the guest's lwmutex lock, as sys_lwmutex_lock leaves it */
{
    lwm_acquire(lwm_slot(LWM), 0);
    vm_write32(LWM + LWM_OWNER, tid); vm_write32(LWM + LWM_RECUR, 1);
}
static void drop()
{
    vm_write32(LWM + LWM_OWNER, 0); vm_write32(LWM + LWM_RECUR, 0);
    lwm_release(lwm_slot(LWM));
}
static void* wait_thread(void* p)
{
    Waiter* w = (Waiter*)p;
    hold(7);
    ppu_context c = {}; c.thread_id = 7; c.gpr[3] = LWC; c.gpr[4] = w->timeout_us;
    long long t0 = now_ms();
    sys_lwcond_wait(&c);
    w->ms = now_ms() - t0;
    w->rc = (uint32_t)c.gpr[3]; w->owner = vm_read32(LWM + LWM_OWNER); w->recur = vm_read32(LWM + LWM_RECUR);
    drop();
    __atomic_store_n(&w->done, 1, __ATOMIC_RELEASE);
    return nullptr;
}
static bool wait_for(volatile int* flag, int ms)
{
    for (long long end = now_ms() + ms; now_ms() < end; ) {
        if (__atomic_load_n(flag, __ATOMIC_ACQUIRE)) return true;
        Sleep(1);
    }
    return false;
}
int main() {
    memset(mem, 0, sizeof mem);
    ppu_context c = {}; c.thread_id = 1; c.gpr[3] = LWC; c.gpr[4] = LWM;
    sys_lwcond_create(&c);
    check(c.gpr[3] == 0, "create returns CELL_OK", c.gpr[3]);
    check(vm_read32(LWC + LWC_MUTEX) == LWM, "lwcond names its lwmutex", vm_read32(LWC + LWC_MUTEX));
    check(LWC_WAITERS(LWC) == 0, "lwcond has a slot with no waiters", (unsigned long long)LWC_WAITERS(LWC));

    Waiter w = {}; w.timeout_us = 0;
    pthread_t t; pthread_create(&t, nullptr, wait_thread, &w);
    long long end = now_ms() + 2000;
    while (LWC_WAITERS(LWC) != 1 && now_ms() < end && !w.done) Sleep(1);
    check(LWC_WAITERS(LWC) == 1 && !w.done, "waiter is queued and asleep", (unsigned long long)LWC_WAITERS(LWC));
    int taken = 0;
    for (end = now_ms() + 2000; !taken && now_ms() < end; Sleep(1)) taken = lwm_try(lwm_slot(LWM));
    check(taken, "the sleeping waiter released the lwmutex", (unsigned long long)taken);
    if (taken) {   /* signal under the lwmutex, as the guest does */
        vm_write32(LWM + LWM_OWNER, 1); vm_write32(LWM + LWM_RECUR, 1);
        ppu_context s = {}; s.thread_id = 1; s.gpr[3] = LWC;
        sys_lwcond_signal(&s);
        check(s.gpr[3] == 0, "signal returns CELL_OK", s.gpr[3]);
        drop();
    }
    bool woke = wait_for(&w.done, 2000);
    check(woke, "signal wakes the waiter", (unsigned long long)woke);
    if (!woke) { printf("FAIL: waiter still blocked\n"); return 1; }
    pthread_join(t, nullptr);
    check(w.rc == 0, "wait returns CELL_OK after a signal", w.rc);
    check(w.owner == 7 && w.recur == 1, "waiter holds the lwmutex again (owner, recursion)", (unsigned long long)w.owner << 32 | w.recur);

    Waiter tw = {}; tw.timeout_us = 30000;   /* 30 ms, never signalled */
    pthread_create(&t, nullptr, wait_thread, &tw);
    woke = wait_for(&tw.done, 2000);
    if (woke) pthread_join(t, nullptr);
    check(woke && tw.rc == 0x8001000Bu, "unsignalled timed wait returns CELL_ETIMEDOUT", tw.rc);
    check(woke && tw.ms >= 20, "timed wait sleeps for its timeout", (unsigned long long)tw.ms);
    check(LWC_WAITERS(LWC) == 0, "timed-out waiter left the queue", (unsigned long long)LWC_WAITERS(LWC));
    return fails ? 1 : 0;
}
'''


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolkit', type=Path, help='patched toolkit (also accepts a tree without patch 6089 for a negative control)')
    args = parser.parse_args()
    if os.name == 'nt':
        print('SKIP: the POSIX lwcond path is tested on POSIX hosts')
        return
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
    cxx = shutil.which('c++') or shutil.which('clang++') or shutil.which('g++')
    cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if not cxx or not cc:
        print('SKIP: no host C/C++ compiler')
        return
    src = (toolkit / 'runtime/ppu/ppu_sysprx.cpp').read_text()
    lwm = region(src, '#define LWM_HASH', 'lwm_release')
    lwc = region(src, '#define LWC_MUTEX', 'sys_lwcond_wait')
    platform = toolkit / 'runtime/platform'
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / 'harness.cpp').write_text(HARNESS % (lwm, lwc))
        exe = t / 'lwcond_test'
        flags = ['-I', str(platform), '-w', '-O1', '-pthread']
        subprocess.run([cc, *flags, '-c', str(platform / 'win32_compat.c'), '-o', str(t / 'compat.o')], check=True)
        subprocess.run([cxx, '-std=c++17', *flags, str(t / 'harness.cpp'), str(t / 'compat.o'), '-o', str(exe)],
                       check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        sys.stdout.write(result.stdout)
        if result.returncode:
            raise SystemExit('FAIL: lwcond wait/signal on this host (patch 6089)')
    print('PASS: patch 6089 lwcond wait/signal on a POSIX host (no game data)')


if __name__ == '__main__':
    main()
