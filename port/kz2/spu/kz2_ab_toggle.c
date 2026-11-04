/* kz2_ab_toggle.c -- an earlier change: the same-run A/B of runtime switches, and KZ2_POST_SKIP (diagnostic).
 *
 * KZ2_AB_TOGGLE=<s>: a thread flips patch 7016's g_kz2_ab_phase (runtime/spu/spu_coherency.c) every <s> seconds of
 * one run: phase k = floor((now - start) / s), odd = on, the run starts off (KZ2_AB_TOGGLE_INVERT=1: k + 1, the run
 * starts on; pooling a run of each cancels a scene change that falls at the same time in every run of the route). A runtime switch set to "t" follows it:
 * KZ3_COH_PREFETCH (7017), KZ3_PUTLLC_FAST (7018), KZ3_LL_TASKSET_STRIPE (7019), KZ3_SPU_TASK_POOL (7020),
 * KZ2_SPU_XRV (7021: this thread sets and clears bit 1 of g_kz3_spu_xrq, spu_drain.c) and
 * KZ2_POST_SKIP below. Each switch prints `[ab-toggle] t=<wacct s> phase=N on|off ...` on stderr, the stream patch
 * 1032's `[wacct]` windows go to: tools/spu/park_ab.py drops the windows that hold a switch and pairs the rest
 * (tools/spu/ab_phase_logs.py splits a log into its on and off phases for tools/runtime/perf/frame_split.py).
 *
 * KZ2_POST_SKIP=1|t (diagnostic, wrong picture; the upper bound of the post chain on the GPU): sets patch 7016's
 * g_kz2_post_skip, under which every SPU DMA GET or PUT whose EA lies in KZ2_POST_SKIP_RANGE (default an earlier change's
 * arena 0x129D5E00-0x12D84100: all post-chain DMA of 128 bytes or more, nothing else's) copies nothing, the walker's
 * sync point does not write back the surfaces there (S640, S320) and the Gfx.Post native gates return at once
 * (kz2_native_jobs.c; every pass or kernel with a gate). The jobs' own bookkeeping (crt0, the job API, their DMA of
 * parameters outside the arena) and the passes' loops around the gated kernels still run: a return at the jobs' entry
 * (KZ3 patch 1043's overlay skip) hung the WWS job list in kz2-spu31-post1. O640/O160 are then never written, so the
 * walker's texture cache finds them unchanged at the bind. "1" = all run long, "t" = in the toggle's on phases.
 * Off unless set. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#endif

extern volatile int g_kz2_ab_phase;                 /* patch 7016, spu_coherency.c */
extern volatile int g_kz2_post_skip;                /* patch 7016, spu_coherency.c */
extern uint32_t g_kz2_post_skip_lo, g_kz2_post_skip_hi;
extern volatile long g_kz2_post_skip_dma_n, g_kz2_post_skip_wb_n;
extern long kz2_post_skip_gate_calls(void);         /* kz2_native_jobs.c */
extern uint64_t kz3_wacct_base(void);

static double s_per;
static long s_inv;                  /* KZ2_AB_TOGGLE_INVERT=1: phase numbers start at 1 (the run starts on) */
static int s_post;                  /* 0 off, 1 always, 2 toggled */
static int s_xrv;                   /* KZ2_SPU_XRV=t: patch 7021's exact vector exponent-255 lanes follow the phase */
extern int g_kz3_spu_xrq;           /* patch 1089/7021, spu_drain.c: bit 0 = 1089's inline lanes, bit 1 = 7021 */

static uint64_t ab_now(void)        /* kz3_wacct_now's clock (QPC ns) with our own frequency, as kz2_post_map.c */
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

static void post_skip_set(int on) { __atomic_store_n(&g_kz2_post_skip, on, __ATOMIC_RELEASE); }

#ifdef _WIN32
static DWORD WINAPI ab_thread(LPVOID p)
{
    (void)p;
    const uint64_t t0 = ab_now();
    long last = -2, wb_last = 0, dma_last = 0, gate_last = 0;
    for (;;) {
        const uint64_t n = ab_now();
        const long ph = (long)((double)(n - t0) / (s_per * 1e9)) + s_inv;
        if (ph != last) {
            last = ph;
            if (s_post == 2) post_skip_set((int)(ph & 1));
            if (s_xrv) __atomic_store_n(&g_kz3_spu_xrq, (g_kz3_spu_xrq & ~2) | (int)(ph & 1) << 1, __ATOMIC_RELAXED);
            __atomic_store_n(&g_kz2_ab_phase, (int)ph, __ATOMIC_RELEASE);
            const uint64_t b = kz3_wacct_base();
            const long wb = g_kz2_post_skip_wb_n, dma = g_kz2_post_skip_dma_n, gate = kz2_post_skip_gate_calls();
            fprintf(stderr, "[ab-toggle] t=%.3fs phase=%ld %s (ended phase: post skips wb=%ld dma=%ld gates=%ld)\n",
                    b && n > b ? (double)(n - b) / 1e9 : (double)(n - t0) / 1e9, ph, (ph & 1) ? "on" : "off",
                    wb - wb_last, dma - dma_last, gate - gate_last);
            wb_last = wb; dma_last = dma; gate_last = gate;
        }
        Sleep(5);
    }
    return 0;
}
#endif

__attribute__((constructor)) static void kz2_ab_toggle_init(void)
{
    const char* e = getenv("KZ2_POST_SKIP");
    if (e && *e && *e != '0') s_post = (*e == 't') ? 2 : 1;
    if (s_post) {
        g_kz2_post_skip_lo = 0x129D5E00u; g_kz2_post_skip_hi = 0x12D84100u;
        const char* r = getenv("KZ2_POST_SKIP_RANGE");
        if (r && *r) {
            char* m;
            const unsigned long lo = strtoul(r, &m, 0);
            if (*m == '-') { g_kz2_post_skip_lo = (uint32_t)lo; g_kz2_post_skip_hi = (uint32_t)strtoul(m + 1, NULL, 0); }
        }
        fprintf(stderr, "[post-skip] KZ2_POST_SKIP=%s: SPU DMA and the sync write-back of EA 0x%08X-0x%08X and the "
                "Gfx.Post gates skipped%s (diagnostic: wrong picture)\n", e, g_kz2_post_skip_lo, g_kz2_post_skip_hi,
                s_post == 2 ? " in the toggle's on phases" : "");
        if (s_post == 1) post_skip_set(1);
    }
    { const char* x = getenv("KZ2_SPU_XRV"); s_xrv = x && *x == 't'; }
    const char* t = getenv("KZ2_AB_TOGGLE");
    s_per = (t && *t) ? atof(t) : 0.0;
    if (s_per <= 0.0) {
        if (s_post == 2) fprintf(stderr, "[post-skip] KZ2_POST_SKIP=t without KZ2_AB_TOGGLE=<s>: stays off\n");
        if (s_xrv) fprintf(stderr, "[spu-xrv] KZ2_SPU_XRV=t without KZ2_AB_TOGGLE=<s>: stays off\n");
        return;
    }
    { const char* iv = getenv("KZ2_AB_TOGGLE_INVERT"); s_inv = (iv && *iv && *iv != '0') ? 1 : 0; }
    fprintf(stderr, "[ab-toggle] KZ2_AB_TOGGLE=%s: switches set to \"t\" flip every %.3f s (odd phases on%s)\n", t, s_per,
            s_inv ? "; KZ2_AB_TOGGLE_INVERT: the run starts on" : "");
    if (s_xrv) fprintf(stderr, "[spu-xrv] KZ2_SPU_XRV=t: the exact vector exponent-255 lanes follow the toggle\n");
#ifdef _WIN32
    CloseHandle(CreateThread(NULL, 0, ab_thread, NULL, 0, NULL));
#endif
}
