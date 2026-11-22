#!/usr/bin/env python3
"""The frame thread's POSIX sleep (runtime/platform/posix_sleep_ms.h, KZ2 patch 6087).

Builds the patched header with a small host program and checks:
  - 0 ms returns at once;
  - 30 ms sleeps at least 30 ms;
  - 1500 ms sleeps at least 1500 ms (usleep past one second is unspecified by POSIX; nanosleep takes it);
  - a signal that interrupts the sleep (SIGALRM after 100 ms, its handler installed without SA_RESTART) does not cut
    it short: the sleep resumes for the time left.
POSIX only; no game data. Needs work/ps3recomp-patched (tools/ps3recomp-patched.sh or tools/build-kz2-macos.py),
or KZ2_PATCHED_DIR / KZ2_OUT pointing at a patched toolkit.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include "posix_sleep_ms.h"
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/time.h>
static double now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec / 1e6; }
static volatile int alarms;
static void on_alarm(int s) { (void)s; alarms++; }
static int fails;
#define CHECK(cond, ...) do { int ok_ = (cond); printf("[%s] ", ok_ ? "PASS" : "FAIL"); printf(__VA_ARGS__); printf("\n"); fails += !ok_; } while (0)
int main(void) {
    double t0 = now_ms(); posix_sleep_ms(0); double d = now_ms() - t0;
    CHECK(d < 20.0, "0 ms returns at once (%.2f ms)", d);
    t0 = now_ms(); posix_sleep_ms(30); d = now_ms() - t0;
    CHECK(d >= 30.0, "30 ms sleeps at least 30 ms (%.1f ms)", d);
    t0 = now_ms(); posix_sleep_ms(1500); d = now_ms() - t0;
    CHECK(d >= 1500.0, "1500 ms sleeps at least 1500 ms (%.1f ms)", d);
    struct sigaction sa; memset(&sa, 0, sizeof sa); sa.sa_handler = on_alarm; sigemptyset(&sa.sa_mask); sa.sa_flags = 0;
    sigaction(SIGALRM, &sa, 0);
    struct itimerval it; memset(&it, 0, sizeof it); it.it_value.tv_usec = 100000; setitimer(ITIMER_REAL, &it, 0);
    t0 = now_ms(); posix_sleep_ms(400); d = now_ms() - t0;
    CHECK(alarms == 1 && d >= 400.0, "a signal 100 ms in does not cut a 400 ms sleep short (%d signal, %.1f ms)", alarms, d);
    return fails ? 1 : 0;
}
'''


def toolkit():
    for p in (Path(os.environ['KZ2_PATCHED_DIR']) if os.environ.get('KZ2_PATCHED_DIR') else None,
              Path(os.environ['KZ2_OUT']) / 'ps3recomp-patched' if os.environ.get('KZ2_OUT') else None,
              ROOT / 'work/ps3recomp-patched'):
        if p and (p / 'runtime/platform/posix_sleep_ms.h').is_file():
            return p
    return None


def main():
    if os.name == 'nt':
        print('SKIP: POSIX only (Windows sleeps on an event)')
        return
    cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if not cc:
        print('SKIP: no host C compiler')
        return
    tk = toolkit()
    if tk is None:
        print('SKIP: no patched toolkit with patch 6087; run tools/ps3recomp-patched.sh')
        return
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / 'harness.c').write_text(HARNESS)
        exe = t / 'sleep_ms'
        subprocess.run([cc, '-O1', '-w', '-D_POSIX_C_SOURCE=200809L', '-D_DEFAULT_SOURCE', '-I', str(tk / 'runtime/platform'),
                        str(t / 'harness.c'), '-o', str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        sys.stdout.write(r.stdout)
        if r.returncode:
            raise SystemExit('FAIL: posix_sleep_ms')
    print('PASS: the POSIX frame-thread sleep takes whole seconds and survives a signal (no game data)')


if __name__ == '__main__':
    main()
