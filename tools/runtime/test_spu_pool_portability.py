#!/usr/bin/env python3
"""Exercise the real SPU pool's timed wait, worker reuse and idle retirement without game data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = r'''
#include "spu_async_pool.h"
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
static atomic_int completed;
static void job(void* arg) { assert(arg == &completed); atomic_fetch_add(&completed, 1); }
static void pause_ms(void) { struct timespec t = {0, 1000000}; nanosleep(&t, NULL); }
int main(void) {
    pool_lock_t lock = POOL_LOCK_INIT;
    pool_cv_t cv;
    struct timespec start, end;
    pool_cv_init(&cv);
    pool_lock(&lock);
    clock_gettime(CLOCK_MONOTONIC, &start);
    assert(pool_cv_wait(&cv, &lock, 20) == 1);
    clock_gettime(CLOCK_MONOTONIC, &end);
    double elapsed_ms = (end.tv_sec - start.tv_sec) * 1000.0 + (end.tv_nsec - start.tv_nsec) / 1000000.0;
    assert(elapsed_ms >= 10.0 && elapsed_ms < 2000.0);
    pool_unlock(&lock);
    pool_cv_destroy(&cv);
    assert(spu_async_pool_submit(job, &completed, 1024 * 1024));
    spu_async_pool_stats_t stats = {0};
    for (int n = 0; n < 2000; n++) {
        spu_async_pool_stats(&stats);
        if (stats.idle == 1) break;
        pause_ms();
    }
    assert(atomic_load(&completed) == 1 && stats.idle == 1);
    assert(spu_async_pool_submit(job, &completed, 1024 * 1024));
    for (int n = 0; n < 3000; n++) {
        spu_async_pool_stats(&stats);
        if (stats.retired == 1) break;
        pause_ms();
    }
    assert(atomic_load(&completed) == 2 && stats.reused == 1 && stats.created == 1);
    assert(stats.retired == 1 && stats.live == 0 && stats.idle == 0);
    puts("PASS: real SPU pool timeout, reuse and idle retirement");
}
'''


def main():
    if os.name == 'nt':
        print('SKIP: POSIX pool portability test')
        return
    toolkit = Path(os.environ.get('KZ2_PATCHED_DIR', ROOT / 'work/ps3recomp-patched'))
    if not (toolkit / 'runtime/spu/spu_async_pool.h').is_file():
        print('SKIP: no patched toolkit')
        return
    with tempfile.TemporaryDirectory(prefix='kz2-pool-') as tmp:
        source, binary = Path(tmp) / 'pool.c', Path(tmp) / 'pool'
        source.write_text(SOURCE)
        features = ['-D_DARWIN_C_SOURCE'] if sys.platform == 'darwin' else ['-D_POSIX_C_SOURCE=200809L']
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c17', *features,
                        '-pthread', '-I', str(toolkit / 'runtime/spu'), str(source),
                        '-o', str(binary)], check=True, timeout=60)
        env = dict(os.environ, SPU_ASYNC_POOL='1', SPU_ASYNC_POOL_IDLE_MS='500')
        subprocess.run([str(binary)], env=env, check=True, timeout=10)


if __name__ == '__main__':
    main()
