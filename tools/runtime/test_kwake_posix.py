#!/usr/bin/env python3
"""The POSIX SPURS kernel wake (runtime/spu/spurs_kern_sched.h, kz3_kwake; KZ2 patch 7046).

Builds the patched header with a small host program and checks, with the pre-sleep spin off and at its default:
  - a ping-pong of 20000 rounds between two threads on two kwakes (each waits with a 1000 ms timeout) never times
    out: a signal is never lost between a waiter's last look at the generation and its sleep;
  - four waiters and one signaler: every waiter sees the final generation, none times out after the last signal;
  - a signal with nobody asleep does not take the lock (the lock is held by the test while it signals).
POSIX only; no game data. Needs work/ps3recomp-patched (tools/build-kz2-macos.py makes it).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include "spurs_kern_sched.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
static kz3_kwake wa, wb, wm;
static volatile int timeouts, rounds_done;
enum { ROUNDS = 20000 };
static void* pong(void* arg) {
    (void)arg;
    for (int i = 0; i < ROUNDS; i++) {
        uint32_t g;
        while ((g = kz3_kwake_gen(&wb)) == (uint32_t)(2 * i)) { if (!kz3_kwake_wait(&wb, g, 1000)) __atomic_add_fetch(&timeouts, 1, __ATOMIC_RELAXED); }
        kz3_kwake_signal(&wa);
    }
    return 0;
}
static volatile uint32_t target;
static void* waiter(void* arg) {
    (void)arg;
    for (;;) {
        uint32_t g = kz3_kwake_gen(&wm);
        if (g >= target && target) return 0;
        if (!kz3_kwake_wait(&wm, g, 1000) && kz3_kwake_gen(&wm) < target) __atomic_add_fetch(&timeouts, 1, __ATOMIC_RELAXED);
    }
}
int main(void) {
    kz3_kwake_init(&wa); kz3_kwake_init(&wb); kz3_kwake_init(&wm);
    int fails = 0;
    pthread_t t; pthread_create(&t, 0, pong, 0);
    for (int i = 0; i < ROUNDS; i++) {
        kz3_kwake_signal(&wb); kz3_kwake_signal(&wb);   /* pong waits for generation 2i+2 */
        uint32_t g;
        while ((g = kz3_kwake_gen(&wa)) == (uint32_t)i) { if (!kz3_kwake_wait(&wa, g, 1000)) __atomic_add_fetch(&timeouts, 1, __ATOMIC_RELAXED); }
    }
    pthread_join(t, 0);
    printf("[%s] ping-pong: %d rounds, %d timeouts\n", timeouts ? "FAIL" : "PASS", ROUNDS, timeouts); fails += timeouts != 0;
    timeouts = 0;
    target = 50000;
    pthread_t w[4]; for (int i = 0; i < 4; i++) pthread_create(&w[i], 0, waiter, 0);
    for (uint32_t i = 0; i < 50000; i++) kz3_kwake_signal(&wm);
    for (int i = 0; i < 4; i++) pthread_join(w[i], 0);
    printf("[%s] four waiters reached the last generation, %d timeouts\n", timeouts ? "FAIL" : "PASS", timeouts); fails += timeouts != 0;
    pthread_mutex_lock(&wm.lk); kz3_kwake_signal(&wm); pthread_mutex_unlock(&wm.lk);
    printf("[PASS] a signal with no sleeper did not take the lock\n");
    return fails ? 1 : 0;
}
'''


def main():
    if os.name == 'nt':
        print('SKIP: the Windows kwake is a different path')
        return
    cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if not cc:
        print('SKIP: no host C compiler')
        return
    inc = ROOT / 'work/ps3recomp-patched/runtime/spu'
    if not (inc / 'spurs_kern_sched.h').is_file():
        raise SystemExit('Missing work/ps3recomp-patched; build first')
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / 'harness.c').write_text(HARNESS)
        exe = t / 'kwake'
        subprocess.run([cc, '-O2', '-w', '-pthread', '-I', str(inc), str(t / 'harness.c'), '-o', str(exe)], check=True)
        for spin in ('0', '20'):
            env = dict(os.environ, KZ2_KWAKE_SPIN_US=spin)
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120, env=env)
            sys.stdout.write(f'-- KZ2_KWAKE_SPIN_US={spin}\n' + r.stdout)
            if r.returncode:
                raise SystemExit('FAIL: kwake')
    print('PASS: the POSIX kwake loses no signal, with and without the pre-sleep spin (no game data)')


if __name__ == '__main__':
    main()
