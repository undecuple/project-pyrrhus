#!/usr/bin/env python3
"""The POSIX guest-fiber pool (port/kz2/guest_fiber.c, guest_fiber_exit).

Builds guest_fiber.c with a small host program and checks:
  - a fiber whose body returns, and a fiber that ends with guest_fiber_exit from deep in its stack, both go back to
    their creator with the creator's register block restored;
  - guest_fiber_destroy of such a finished fiber keeps it, and the next guest_fiber_create with the same stack size
    hands back that same fiber, which runs the NEW body on a fresh copy of the creator's block;
  - the per-fiber locals start at 0 in a reused fiber;
  - 2000 create/exit/destroy rounds all reuse that one fiber (no new stack, makecontext not called again).
Before the pool every job fiber of Killzone 2's scheduler got a fresh 32 MiB stack that macOS's makecontext zeroed
(3.7 % of all process samples in the first mission). POSIX only; no game data.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include "guest_fiber.h"
#include <stdio.h>
#include <string.h>
static struct { int reg; char pad[60]; } ctx;
static int g_local;
static int* local_slot(void) { return &g_local; }
static guest_fiber* home;
static int ran_a, ran_b, deep_seen, local_at_start;
static void deep(int n) { if (n) { deep(n - 1); return; } deep_seen++; guest_fiber_exit(); }
static void body_a(void* c, void* arg) { (void)arg; ran_a++; local_at_start = g_local; g_local = 77; ((int*)c)[0] = 111; }
static void body_b(void* c, void* arg) { (void)arg; ran_b++; local_at_start = g_local; g_local = 55; ((int*)c)[0] = 222; deep(20); }
static int fails;
#define CHECK(cond, what) do { int ok_ = (cond); printf("[%s] %s\n", ok_ ? "PASS" : "FAIL", what); fails += !ok_; } while (0)
int main(void) {
    guest_fiber_add_local(local_slot);
    home = guest_fiber_self(&ctx, sizeof ctx);
    ctx.reg = 5; g_local = 9;
    guest_fiber* f1 = guest_fiber_create(body_a, NULL, 0);
    guest_fiber_switch(f1);
    CHECK(ran_a == 1 && ctx.reg == 5 && g_local == 9, "a returning body goes back to its creator, block and local restored");
    guest_fiber_destroy(f1);
    guest_fiber* f2 = guest_fiber_create(body_b, NULL, 0);
    CHECK(f2 == f1, "the finished fiber is handed out again");
    guest_fiber_switch(f2);
    CHECK(ran_b == 1 && deep_seen == 1 && ctx.reg == 5 && g_local == 9, "guest_fiber_exit from deep in a reused fiber returns to the creator");
    CHECK(local_at_start == 0, "a reused fiber's locals start at 0");
    guest_fiber_destroy(f2);
    int same = 0;
    for (int i = 0; i < 2000; i++) { guest_fiber* f = guest_fiber_create(body_b, NULL, 0); same += f == f1; guest_fiber_switch(f); guest_fiber_destroy(f); }
    CHECK(ran_b == 2001 && deep_seen == 2001, "2000 more create/exit/destroy rounds ran");
    CHECK(same == 2000, "every round reused the one pooled fiber (no new stack, no makecontext)");
    return fails ? 1 : 0;
}
'''


def main():
    if os.name == 'nt':
        print('SKIP: the pool is the POSIX path')
        return
    cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if not cc:
        print('SKIP: no host C compiler')
        return
    src = ROOT / 'port/kz2/guest_fiber.c'
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / 'harness.c').write_text(HARNESS)
        exe = t / 'fiber_pool'
        # The build's own definition for this file (port/kz2/CMakeLists.txt): macOS's ucontext routines need it.
        subprocess.run([cc, '-O1', '-w', '-D_XOPEN_SOURCE=600', '-I', str(ROOT / 'port/kz2'), str(t / 'harness.c'),
                        str(src), '-o', str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        sys.stdout.write(r.stdout)
        if r.returncode:
            raise SystemExit('FAIL: guest fiber pool')
    print('PASS: POSIX guest fibers are reused after a return or guest_fiber_exit (no game data)')


if __name__ == '__main__':
    main()
