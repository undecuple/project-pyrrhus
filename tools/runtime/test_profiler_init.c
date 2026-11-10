/* Deterministic host test of the extracted accounting initializer/accessor.
 * Windows setup calls are stubs; prof_init pauses before publishing its own readiness.
 * The naming caller tries to attach exactly once, as the frame thread does. */
#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>

static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cv = PTHREAD_COND_INITIALIZER;
static int init_entered, allow_prof, naming_done, naming_reentered;
static int prof_ready, prof_calls, printer_calls, attached;
static _Thread_local int naming_thread;
int g_kz3_wacct = -1;
static uint64_t s_t0;
static unsigned long s_tls;
static int s_qf;
#define TLS_OUT_OF_INDEXES (~0UL)

static long test_cas(volatile long* p, long old, long value)
{
    if (naming_thread) {
        pthread_mutex_lock(&mu);
        naming_reentered = 1;
        pthread_cond_broadcast(&cv);
        pthread_mutex_unlock(&mu);
    }
    long expected = old;
    __atomic_compare_exchange_n(p, &expected, value, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST);
    return expected;
}
#define __sync_val_compare_and_swap test_cas
static int QueryPerformanceFrequency(int* f) { *f = 1000; return 1; }
static unsigned long TlsAlloc(void) { return 1; }
static uint64_t kz3_wacct_now(void) { return 42; }
static void* printer(void* p) { return p; }
static void* CreateThread(void* a, unsigned b, void* (*fn)(void*), void* c, unsigned d, void* e)
{
    (void)a; (void)b; (void)fn; (void)c; (void)d; (void)e;
    printer_calls++;
    return NULL;
}
static void prof_init(void)
{
    pthread_mutex_lock(&mu);
    prof_calls++;
    init_entered = 1;
    pthread_cond_broadcast(&cv);
    while (!allow_prof) pthread_cond_wait(&cv, &mu);
    __atomic_store_n(&prof_ready, 1, __ATOMIC_RELEASE);
    pthread_mutex_unlock(&mu);
}
#define _WIN32 1
#include PROFILER_INIT_BODY
#undef _WIN32
#include PROFILER_ON_BODY

static void* init_thread(void* p)
{
    (void)p;
    return (void*)(intptr_t)kz3_wacct_init();
}
static void* name_thread(void* p)
{
    (void)p;
    naming_thread = 1;
    /* Model prof_attach's readiness guard; real Windows handle creation is not tested. */
    if (kz3_wacct_on()) attached = __atomic_load_n(&prof_ready, __ATOMIC_ACQUIRE) > 0;
    pthread_mutex_lock(&mu);
    naming_done = 1;
    pthread_cond_broadcast(&cv);
    pthread_mutex_unlock(&mu);
    return NULL;
}
static int wait_for(int* flag, int* alternate)
{
    struct timespec until;
    clock_gettime(CLOCK_REALTIME, &until);
    until.tv_sec += 5;
    while (!*flag && !(alternate && *alternate)) {
        int r = pthread_cond_timedwait(&cv, &mu, &until);
        if (r != 0) {
            fprintf(stderr, "FAIL profiler_init: timed wait: %s\n", strerror(r));
            return 0;
        }
    }
    return 1;
}
int main(int argc, char** argv)
{
    if (argc > 1 && strcmp(argv[1], "off") == 0) {
        setenv("KZ3_WAIT_ACCT", "0", 1);
        if (kz3_wacct_init() || kz3_wacct_on() || prof_calls || printer_calls) {
            fprintf(stderr, "FAIL profiler_init: disabled path\n"); return 1;
        }
        puts("PASS profiler_init: disabled accounting starts no helpers");
        return 0;
    }
    setenv("KZ3_WAIT_ACCT", "1", 1);
    pthread_t initializer, naming;
    if (pthread_create(&initializer, NULL, init_thread, NULL)) return 2;
    pthread_mutex_lock(&mu);
    int ok = wait_for(&init_entered, NULL);
    pthread_mutex_unlock(&mu);
    if (!ok || pthread_create(&naming, NULL, name_thread, NULL)) return 2;
    pthread_mutex_lock(&mu);
    /* Old order completes naming with profiler unready. Fixed order enters init
     * and waits on readiness. Both decisions are observed before releasing setup. */
    ok = wait_for(&naming_done, &naming_reentered);
    int early = naming_done;
    allow_prof = 1;
    pthread_cond_broadcast(&cv);
    pthread_mutex_unlock(&mu);
    void* result;
    pthread_join(initializer, &result);
    pthread_join(naming, NULL);
    if (!ok || early || !attached || prof_calls != 1 || printer_calls != 1 ||
        (intptr_t)result != 1000 || kz3_wacct_on() != 1000 || s_t0 != 42 || s_tls != 1) {
        fprintf(stderr, "FAIL profiler_init: early=%d attached=%d setup=%d printer=%d ready=%d\n",
                early, attached, prof_calls, printer_calls, kz3_wacct_on());
        return 1;
    }
    puts("PASS profiler_init: naming waits for profiler setup and attaches once");
    return 0;
}
