/* kz2_frame_trace.c -- KZ2_FRAME_TRACE=FROM,TO (seconds after process start; diagnostic, off by default;
 * an earlier change): records every event patch 1085's hook (g_kz3_wtrace, kz3_wait_acct.h) passes in that window -- accounted
 * brackets (HLE calls, syscalls, usleeps, label waits, SPURS kernel sleeps, policy-module runs, GCM parks), job-module
 * changes, flips, WWS job calls, GCM user commands -- into a preallocated array, and prints them once the window is
 * over as `[ftr]` lines on stderr (tools/spu/park_trace.py reads them):
 *   [ftr-thr] IDX NAME                         one per host thread seen
 *   [ftr] IDX KIND SITE T0_US DUR_US           T0 relative to the window start, KIND as kz3_wait_acct.h
 * Needs KZ3_WAIT_ACCT (the brackets exist only when accounting is on). KZ2_FRAME_TRACE_MAX (default 1 500 000)
 * caps the events kept. Job-module notes (kind 6) are dropped; HLE calls (0) and usleeps (2) are kept only with
 * KZ2_FRAME_TRACE_ALL=1. KZ2_FRAME_TRACE_INST=<EA> (the HiPrio SPURS instance, `[cellSpurs] Initialize "" ea=`) also
 * samples that instance every ~20 us in the window, as events on thread "ftr-inst" (kind 40, site = wid << 16 |
 * readyCount << 8 | contention, one per workload whose bytes changed), and prints each workload's priority bytes,
 * minimum and maximum contention once ([ftr-wkl]); the same thread watches the park word the GCM walker waits at
 * (patch 7013's kz2_park_ea_peek) and records kind 44 (site = its EA) when the word changes, whoever wrote it. Same idea as KZ3's port/spu/kz3_frame_trace.c (KZ3_FRAME_TRACE, not in the 78bf574
 * snapshot): written here from patch 1085's interface. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#endif

extern uint8_t* vm_base;
extern uint32_t kz2_park_ea_peek(void);   /* patch 7013 */
extern void (*g_kz3_wtrace)(const char* thr, int kind, uint32_t site, uint64_t t0, uint64_t t1);
/* kz3_wacct_now's clock (QPC in ns), read here directly: its own frequency is set only once accounting starts. */
static uint64_t ftr_now(void)
{
#ifdef _WIN32
    static LARGE_INTEGER f;
    if (!f.QuadPart) QueryPerformanceFrequency(&f);
    LARGE_INTEGER c; QueryPerformanceCounter(&c);
    return (uint64_t)((double)c.QuadPart * 1e9 / (double)f.QuadPart);
#else
    return 0;
#endif
}

typedef struct { uint64_t t0, t1; uint32_t site; uint8_t thr, kind; } ftr_ev;

static ftr_ev* s_ev;
static long s_max;
static volatile long s_n;
static uint64_t s_from, s_to, s_base;
static volatile int s_state;   /* 0 recording, 1 printing/done */
enum { FTR_THR = 96 };
static const char* volatile s_thr[FTR_THR];
static volatile long s_nthr;

static int thr_index(const char* name)
{
    long n = __atomic_load_n(&s_nthr, __ATOMIC_ACQUIRE);
    for (long i = 0; i < n && i < FTR_THR; i++) if (s_thr[i] == name) return (int)i;
    /* new thread: append under a tiny lock (rare) */
    static volatile long lk;
    while (__sync_lock_test_and_set(&lk, 1)) { }
    n = s_nthr;
    for (long i = 0; i < n && i < FTR_THR; i++) if (s_thr[i] == name) { __sync_lock_release(&lk); return (int)i; }
    int r = -1;
    if (n < FTR_THR) { s_thr[n] = name; __atomic_store_n(&s_nthr, n + 1, __ATOMIC_RELEASE); r = (int)n; }
    __sync_lock_release(&lk);
    return r;
}

static int s_all;

static void ftr_hook(const char* thr, int kind, uint32_t site, uint64_t t0, uint64_t t1)
{
    if (s_state || t1 < s_from) return;
    /* job-module notes come on every call; HLE calls and usleeps are ~170k a second: only with KZ2_FRAME_TRACE_ALL=1 */
    if (kind == 6 || (!s_all && (kind == 0 || kind == 2))) return;
    if (t0 > s_to) return;
    const int ti = thr_index(thr);
    if (ti < 0) return;
    const long i = __atomic_fetch_add(&s_n, 1, __ATOMIC_RELAXED);
    if (i >= s_max) return;
    ftr_ev* e = &s_ev[i];
    e->t0 = t0; e->t1 = t1; e->site = site; e->thr = (uint8_t)ti; e->kind = (uint8_t)kind;
}

static void ftr_print(void)
{
    long n = s_n; if (n > s_max) n = s_max;
    fprintf(stderr, "[ftr-begin] window %.3f-%.3f s events=%ld kept=%ld\n", (double)(s_from - s_base) / 1e9,
            (double)(s_to - s_base) / 1e9, (long)s_n, n);
    for (long i = 0; i < s_nthr && i < FTR_THR; i++) fprintf(stderr, "[ftr-thr] %ld %s\n", i, s_thr[i] ? s_thr[i] : "?");
    for (long i = 0; i < n; i++) {
        const ftr_ev* e = &s_ev[i];
        if (!e->t1) continue;   /* a slot taken but not filled yet */
        const long long a = (long long)(e->t0 - s_from) / 1000;
        fprintf(stderr, "[ftr] %u %u %X %lld %llu\n", e->thr, e->kind, e->site, a, (unsigned long long)((e->t1 - e->t0) / 1000));
    }
    fprintf(stderr, "[ftr-end]\n");
    fflush(stderr);
}

static uint32_t s_inst;

#ifdef _WIN32
static void ftr_inst_sample(void)
{
    static const char name[] = "ftr-inst";
    uint8_t last_r[16], last_c[16];
    uint32_t pk_ea = 0, pk_w = 0;
    memset(last_r, 0xFF, sizeof last_r); memset(last_c, 0xFF, sizeof last_c);
    timeBeginPeriod(1);
    while (ftr_now() < s_to) {
        const uint64_t t = ftr_now();
        if (t >= s_from) {
            const volatile uint8_t* S = vm_base + s_inst;
            for (uint32_t w = 0; w < 16; w++) {
                const uint8_t r = S[0x00 + w], c = S[0x20 + w];
                if (r == last_r[w] && c == last_c[w]) continue;
                last_r[w] = r; last_c[w] = c;
                ftr_hook(name, 40, w << 16 | (uint32_t)r << 8 | c, t, t + 1);
            }
        }
        {   /* patch 7013: the armed park word; 44 = it changed while armed (site = EA), whoever wrote it */
            const uint32_t pe = kz2_park_ea_peek();
            if (pe != pk_ea) { pk_ea = pe; pk_w = pe ? *(volatile uint32_t*)(vm_base + pe) : 0; }
            else if (pe) {
                const uint32_t w = *(volatile uint32_t*)(vm_base + pe);
                if (w != pk_w) { pk_w = w; ftr_hook(name, 44, pe, ftr_now(), ftr_now() + 1); }
            }
        }
        /* ~20 us: a spin with yields (the window is a few seconds; diagnostic only) */
        while (ftr_now() - t < 20000) SwitchToThread();
    }
    timeEndPeriod(1);
    const uint8_t* S = vm_base + s_inst;
    for (uint32_t w = 0; w < 16; w++) {
        const uint8_t* I = S + 0xB00 + w * 0x20;
        fprintf(stderr, "[ftr-wkl] wid %u prio %02X %02X %02X %02X %02X %02X %02X %02X minC %u maxC %u uid %u\n", w,
                I[0x18], I[0x19], I[0x1A], I[0x1B], I[0x1C], I[0x1D], I[0x1E], I[0x1F], S[0x40 + w], S[0x50 + w], I[0x14]);
    }
}

static DWORD WINAPI ftr_thread(LPVOID p)
{
    (void)p;
    if (s_inst) {
        while (ftr_now() < s_from) Sleep(100);
        ftr_inst_sample();
    }
    for (;;) {
        Sleep(200);
        if (ftr_now() > s_to + 300000000ull) break;   /* 0.3 s after the window: brackets have closed */
    }
    s_state = 1;
    Sleep(50);
    ftr_print();
    return 0;
}
#endif

__attribute__((constructor)) static void kz2_frame_trace_init(void)
{
    const char* e = getenv("KZ2_FRAME_TRACE");
    if (!e || !*e) return;
    double a = 0, b = 0;
    if (sscanf(e, "%lf,%lf", &a, &b) != 2 || b <= a) { fprintf(stderr, "[ftr] KZ2_FRAME_TRACE=%s: want FROM,TO\n", e); return; }
    const char* m = getenv("KZ2_FRAME_TRACE_MAX");
    s_max = (m && *m) ? strtol(m, NULL, 0) : 1500000;
    if (s_max <= 0) return;
    s_ev = (ftr_ev*)calloc((size_t)s_max, sizeof *s_ev);
    if (!s_ev) return;
    s_base = ftr_now();
    s_from = s_base + (uint64_t)(a * 1e9);
    s_to = s_base + (uint64_t)(b * 1e9);
    { const char* al = getenv("KZ2_FRAME_TRACE_ALL"); s_all = al && *al == '1'; }
    const char* ie = getenv("KZ2_FRAME_TRACE_INST");
    s_inst = (ie && *ie) ? (uint32_t)strtoul(ie, NULL, 16) : 0;
    g_kz3_wtrace = ftr_hook;
#ifdef _WIN32
    CloseHandle(CreateThread(NULL, 0, ftr_thread, NULL, 0, NULL));
#endif
    fprintf(stderr, "[ftr] KZ2_FRAME_TRACE window %.3f-%.3f s, up to %ld events (needs KZ3_WAIT_ACCT)\n", a, b, s_max);
}
