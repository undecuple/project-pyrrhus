/* test_native_ctr.c -- an earlier change: the native gates' per-context call counters (port/kz2/spu/native_ctr.c,
 * kz2_native_jobs.h kz2_native_count). Checks: T threads, each with its own context, count exactly; 70 contexts (more
 * than the 64 rows) still sum exactly (the shared row); the print fires at 1024 and the powers of two after. Prints the
 * per-call cost of the new path and of an earlier change's (one `lock xadd` on a shard picked by the context hash) for the
 * same threads, informational. Built and run by tools/spu/test_native_ctr.sh (also with a broken claim, which must
 * fail). */
#include "kz2_native_jobs.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static volatile long s_prints, s_last_print;
void kz2_native_count_print(int slot, long calls) { (void)slot; s_prints++; s_last_print = calls; }
long kz2_native_calls_sum(int slot)
{
    long n = 0;
    for (int k = 0; k <= KZ2_NATIVE_CTXS; k++) n += g_kz2_native_rows[k].calls[slot & (KZ2_NATIVE_SLOTS - 1)];
    return n;
}

#define N_PER 2000000L
#define SLOT 81
static spu_context* s_ctx[80];

static void* run_new(void* p)
{
    const void* c = p;
    for (long i = 0; i < N_PER; i++) kz2_native_count(SLOT, c);
    return 0;
}

/* an earlier change's counter, for the timing only */
typedef struct { volatile long calls; char pad[64 - sizeof(long)]; } old_ctr;
static __attribute__((aligned(64))) old_ctr s_old[KZ2_NATIVE_SLOTS][8];
static void* run_old(void* p)
{
    const unsigned k = (unsigned)(((uint64_t)(uintptr_t)p * 0x9E3779B97F4A7C15ull) >> 61);
    for (long i = 0; i < N_PER; i++) __atomic_add_fetch(&s_old[SLOT][k].calls, 1, __ATOMIC_RELAXED);
    return 0;
}

static double now_s(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

static double par(void* (*fn)(void*), int n, int first)
{
    pthread_t th[80];
    const double t0 = now_s();
    for (int i = 0; i < n; i++) pthread_create(&th[i], 0, fn, s_ctx[first + i]);
    for (int i = 0; i < n; i++) pthread_join(th[i], 0);
    return now_s() - t0;
}

int main(void)
{
    int fail = 0;
    /* contexts the size of the real ones, so the pointers look like the game's (heap, page-aligned-ish) */
    for (int i = 0; i < 80; i++) s_ctx[i] = aligned_alloc(4096, (sizeof(spu_context) + 4095) & ~(size_t)4095);
    const int T = 5;
    const double tn = par(run_new, T, 0);
    long sum = kz2_native_calls_sum(SLOT);
    if (sum != T * N_PER) { printf("FAIL: %d threads, sum %ld != %ld\n", T, sum, T * N_PER); fail = 1; }
    if (s_last_print != 0 && (s_last_print < 1024)) { printf("FAIL: print below 1024\n"); fail = 1; }
    if (s_prints == 0) { printf("FAIL: no print\n"); fail = 1; }
    const double to = par(run_old, T, 0);
    printf("per call, %d threads: new %.2f ns, an earlier change %.2f ns\n", T, tn * 1e9 / N_PER, to * 1e9 / N_PER);
    /* 70 contexts, 5 at a time: rows run out after 64; the shared row keeps the sum exact */
    for (int b = 5; b < 70; b += 5) par(run_new, 5, b);
    sum = kz2_native_calls_sum(SLOT);
    if (sum != 70 * N_PER) { printf("FAIL: 70 contexts, sum %ld != %ld\n", sum, 70 * N_PER); fail = 1; }
    if (g_kz2_native_rows[KZ2_NATIVE_CTXS].calls[SLOT] != 6 * N_PER) {
        printf("FAIL: shared row %ld, want %ld (6 contexts past 64)\n", (long)g_kz2_native_rows[KZ2_NATIVE_CTXS].calls[SLOT],
               6 * N_PER);
        fail = 1;
    }
    /* the fallback counter */
    for (int i = 0; i < 3; i++) kz2_native_fell_back(SLOT, s_ctx[0]);
    if (g_kz2_native_fb[SLOT] != 3) { printf("FAIL: fallback %ld\n", (long)g_kz2_native_fb[SLOT]); fail = 1; }
    printf("%s test_native_ctr: 5 threads x %ld exact, 70 contexts exact (shared row %ld), prints %ld\n",
           fail ? "FAIL" : "PASS", N_PER, (long)g_kz2_native_rows[KZ2_NATIVE_CTXS].calls[SLOT], (long)s_prints);
    return fail;
}
