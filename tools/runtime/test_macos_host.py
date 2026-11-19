#!/usr/bin/env python3
"""Run-loop regression: a guest worker can synchronously call the main queue.

No toolkit, game files, display or GPU required. Requires macOS and Clang.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = r'''
#include "kz2_macos_host.h"
#include <dispatch/dispatch.h>
#include <pthread.h>
#include <cstdio>
static int guest(uint32_t entry, uint32_t stack) {
    if (pthread_main_np() || entry != 17 || stack != 29) return 2;
    if (pthread_get_stacksize_np(pthread_self()) < 256u * 1024u * 1024u) return 3;
    __block int on_main = 0;
    dispatch_sync(dispatch_get_main_queue(), ^{ on_main = pthread_main_np(); });
    return on_main ? 73 : 4;
}
int main() {
    if (kz2_macos_run_guest(17, 29, nullptr) != 1) return 1;
    if (kz2_macos_run_guest(17, 29, guest) != 73) return 1;
    puts("PASS: guest runs on a large-stack worker, main queue stays live, return value preserved");
}
'''

FIBER_SOURCE = r'''
#include "guest_fiber.h"
#include <assert.h>
#include <stdio.h>
static guest_fiber* parent;
static int tls_value;
static int* local(void) { return &tls_value; }
static int steps;
static void body(void* ctx, void* arg) {
    int* reg = ctx;
    assert(*reg == 7 && tls_value == 0 && arg == &steps);
    *reg = 9; tls_value = 11; steps++;
    guest_fiber_switch(parent);
    assert(*reg == 9 && tls_value == 11);
    steps++;
}
int main(void) {
    int reg = 3;
    parent = guest_fiber_self(&reg, sizeof reg);
    assert(guest_fiber_add_local(local) == 0);
    tls_value = 5;
    guest_fiber* child = guest_fiber_create(body, &steps, 1024 * 1024);
    *(int*)guest_fiber_state(child) = 7;
    guest_fiber_switch(child);
    assert(reg == 3 && tls_value == 5 && steps == 1);
    guest_fiber_switch(child);
    assert(reg == 3 && tls_value == 5 && steps == 2);
    guest_fiber_destroy(child);
    puts("PASS: native fibers preserve registers, locals and resume/return behavior");
}
'''


def main():
    if sys.platform != 'darwin':
        print('SKIP: macOS run-loop test requires CoreFoundation')
        return
    with tempfile.TemporaryDirectory(prefix='kz2-macos-host-') as tmp:
        source = Path(tmp) / 'main.cpp'
        binary = Path(tmp) / 'test'
        source.write_text(SOURCE)
        subprocess.run([os.environ.get('CXX', 'clang++'), '-std=c++20', '-fblocks',
                        '-I', str(ROOT / 'port/kz2'), str(source),
                        str(ROOT / 'port/kz2/kz2_macos_host.cpp'),
                        '-framework', 'CoreFoundation', '-o', str(binary)], check=True, timeout=60)
        subprocess.run([str(binary)], check=True, timeout=10)
        fiber = Path(tmp) / 'fiber.c'
        fiber.write_text(FIBER_SOURCE)
        subprocess.run([os.environ.get('CC', 'clang'), '-std=c17', '-D_XOPEN_SOURCE=600',
                        '-Wno-deprecated-declarations', '-I', str(ROOT / 'port/kz2'),
                        str(fiber), str(ROOT / 'port/kz2/guest_fiber.c'),
                        '-o', str(binary)], check=True, timeout=60)
        subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == '__main__':
    main()
