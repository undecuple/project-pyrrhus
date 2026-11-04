/* kz2_post_map.c -- KZ2_POST_MAP=FROM,TO (seconds after process start; diagnostic, off by default):
 * maps the SPU post chain's data flow for the GPU-compute question (who reads each Gfx.Post output, where each input
 * comes from, how the chain is kicked and synchronised with the RSX). Records into a preallocated array, prints after
 * the window as `[pmap]` lines on stderr (tools/spu/post_map.py reads them):
 *   - every SPU DMA (patch 7015's g_kz2_pmap_dma) of a Gfx.Post job (images 206-222, also as the policy module's
 *     resident overlay), and any other SPU DMA that touches a page a post job or a surface write-back touched;
 *   - the walker's surface events (patch 7015's g_kz2_pmap_surf): first GPU write since the last write-back, write-back,
 *     texture binds over marked pages, flips, guest sync points;
 *   - patch 1085's trace events (chained after KZ2_FRAME_TRACE's hook, needs KZ3_WAIT_ACCT): flips, WWS job calls, user
 *     commands, label waits, patch 7013's park events;
 *   - KZ2_POST_MAP_WATCH=N (default 8, 0 = off; Windows): a read/write watch on every Nth 4 KB page of the marked ranges
 *     (every page of a range of at most 4 pages; DMAs under 128 bytes are not watched): an armed page is PAGE_NOACCESS;
 *     the first access faults, the vectored handler records the host thread, rip and [rsp] and opens the page. Pages an
 *     SPU thread opened are re-armed at the end of its WWS job call, pages the walker opened at its next texture bind,
 *     the rest (PPU threads, anything else) at the next flip. So every reader that is not an SPU DMA or the walker
 *     shows up at least once per frame per page it reads after the page's last re-arm (a read while a job that
 *     touched the page is still running can be missed).
 * The post jobs DMA row by row (~70 000 DMAs a heavy frame), so the DMA events are kept only in sampled frames: frames
 * f and f + 1 for every f % KZ2_POST_MAP_EVERY == 0 (default 16; frames counted by patch 1085's flips); pages are
 * marked in every frame. KZ2_POST_MAP_OUT=FILE writes the events there as binary records (struct pm_ev, 32 bytes,
 * after a 64-byte header "KZ2PMAP1", count, base) instead of printing them (printing 10^6 lines takes ~20 s).
 * Lines: [pmap-thr] IDX TID wacct=NAME ppu=NAME hook=H ; [pmap] KIND T_US TIDX A B C D E (hex, kinds below).
 * KZ2_POST_MAP_MAX (default 3 000 000) caps the events. The watch is off again before anything is written. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#endif
#include "spu_context.h"

enum {
    PM_GET = 1, PM_PUT = 2,                          /* a=ea b=size c=img|ovl<<9|spu<<18 d=pc e=lsa */
    PM_SGPU = 10, PM_SWB = 11, PM_STEX = 12,         /* a=ea b=bytes c=w|h<<16 d=pitch(span for tex) e=texel(fmt) */
    PM_SFLIP = 13, PM_SSYNC = 14,                    /* SSYNC a=caller (exe offset) */
    PM_WT = 20,                                      /* + patch 1085 kind; a=site b=dur_us */
    PM_FAULT = 90                                    /* a=ea b=rip(exe off) c=[rsp](exe off) d=write */
};

extern uint8_t* vm_base;
/* kz3_wacct_now's clock (QPC in ns; the wtrace times use it), with our own frequency: its own is set only once
 * accounting starts (as kz2_frame_trace.c). */
static uint64_t pm_now(void)
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
extern void (*g_kz3_wtrace)(const char* thr, int kind, uint32_t site, uint64_t t0, uint64_t t1);
extern void (*g_kz2_pmap_dma)(spu_context* spu, int put, uint32_t lsa, uint32_t ea, uint32_t size);
extern void (*g_kz2_pmap_surf)(int kind, uint32_t location, uint32_t offset, uint32_t w, uint32_t h, uint32_t pitch,
                               uint32_t texel);
extern uint32_t cellGcmResolveLocated(int local, uint32_t offset);
extern const char* ppu_thread_name_for_os_tid(unsigned long os_tid);

typedef struct { uint64_t t; uint32_t a, b, c, d, e; uint16_t kind, tidx; } pm_ev;

static pm_ev* s_ev;
static long s_max;
static volatile long s_n;
static uint64_t s_base, s_mark_from, s_from, s_to;
static volatile int s_done;
static uint32_t s_watch, s_every = 16;
static volatile long s_arm_fail; static volatile unsigned long s_arm_err;
static const char* s_out;
static uintptr_t s_exe;
static void (*s_prev_wt)(const char*, int, uint32_t, uint64_t, uint64_t);

/* ---- threads ---- */
enum { PM_THR = 128, PM_RING = 1024 };
typedef struct {
    volatile unsigned long tid;
    const char* volatile name;     /* patch 1085's wacct name, if seen */
    volatile uint8_t hooked;       /* 1 = SPU DMA hook ran here, 2 = walker surface hook */
    uint32_t ring[PM_RING];        /* pages this thread opened, re-armed at its next hook (own thread only) */
    uint32_t rn;
    uint32_t last_fault_page, last_fault_frame;
    uint32_t retry_ea, retries;
} pm_thr;
static pm_thr s_thr[PM_THR];
static volatile long s_nthr;
static volatile uint32_t s_frame;

static unsigned long pm_tid(void)
{
#ifdef _WIN32
    return GetCurrentThreadId();
#else
    return 0;
#endif
}
static int pm_thr_index(unsigned long tid)
{
    long n = __atomic_load_n(&s_nthr, __ATOMIC_ACQUIRE);
    for (long i = 0; i < n && i < PM_THR; i++) if (s_thr[i].tid == tid) return (int)i;
    for (;;) {
        n = __atomic_load_n(&s_nthr, __ATOMIC_ACQUIRE);
        for (long i = 0; i < n && i < PM_THR; i++) if (s_thr[i].tid == tid) return (int)i;
        if (n >= PM_THR) return PM_THR - 1;
        unsigned long z = 0;
        if (__atomic_compare_exchange_n(&s_thr[n].tid, &z, tid, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            __atomic_store_n(&s_nthr, n + 1, __ATOMIC_RELEASE);
            return (int)n;
        }
        /* another thread took slot n: publish it and retry */
        long e = n; __atomic_compare_exchange_n(&s_nthr, &e, n + 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    }
}

static void pm_rec(int kind, int ti, uint64_t t, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e)
{
    const long i = __atomic_fetch_add(&s_n, 1, __ATOMIC_RELAXED);
    if (i >= s_max) return;
    pm_ev* v = &s_ev[i];
    v->t = t; v->a = a; v->b = b; v->c = c; v->d = d; v->e = e; v->kind = (uint16_t)kind; v->tidx = (uint16_t)ti;
}

/* ---- marked pages (4 KB, EA space) and the watch ---- */
static uint8_t s_mark[1u << 17];               /* bit per page */
static volatile uint8_t s_st[1u << 20];        /* watch state: 0 no, 1 open, 2 armed, 3 arming, 4 opening */
static uint32_t* s_wl;                         /* watched pages */
static volatile long s_nwl;
enum { PM_WMAX = 16384 };

static inline int pm_marked(uint32_t ea, uint32_t size)
{
    if (!size) return 0;
    for (uint64_t p = ea >> 12, q = ((uint64_t)ea + size - 1u) >> 12; p <= q && p < (1u << 20); p++)
        if (s_mark[p >> 3] & (1u << (p & 7))) return 1;
    return 0;
}
static void pm_mark(uint32_t ea, uint32_t size, int watch)
{
    if (!size) return;
    const uint32_t p0 = ea >> 12, p1 = (uint32_t)(((uint64_t)ea + size - 1u) >> 12);
    for (uint32_t p = p0; p <= p1 && p < (1u << 20); p++) {
        if (!(s_mark[p >> 3] & (1u << (p & 7)))) __atomic_or_fetch(&s_mark[p >> 3], (uint8_t)(1u << (p & 7)), __ATOMIC_RELAXED);
        if (!watch || !s_watch || size < 128) continue;
        if (p1 - p0 >= 4 && (p % s_watch)) continue;
        uint8_t z = 0;
        if (__atomic_compare_exchange_n(&s_st[p], &z, 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
            const long k = __atomic_fetch_add(&s_nwl, 1, __ATOMIC_RELAXED);
            if (k < PM_WMAX) s_wl[k] = p; else __atomic_store_n(&s_st[p], 0, __ATOMIC_RELEASE);
        }
    }
}

#ifdef _WIN32
static void pm_arm(uint32_t p)
{
    uint8_t one = 1;
    if (!__atomic_compare_exchange_n(&s_st[p], &one, 3, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) return;
    DWORD old;
    const int ok = VirtualProtect(vm_base + ((uintptr_t)p << 12), 0x1000, PAGE_NOACCESS, &old) != 0;
    if (!ok) { __atomic_add_fetch(&s_arm_fail, 1, __ATOMIC_RELAXED); s_arm_err = GetLastError(); }
    __atomic_store_n(&s_st[p], ok ? 2 : 1, __ATOMIC_RELEASE);
}
static void pm_rearm_own(int ti)
{
    pm_thr* t = &s_thr[ti];
    for (uint32_t k = 0; k < t->rn && k < PM_RING; k++) pm_arm(t->ring[k]);
    t->rn = 0;
}
static LONG CALLBACK pm_veh(PEXCEPTION_POINTERS xp)
{
    const EXCEPTION_RECORD* er = xp->ExceptionRecord;
    if (er->ExceptionCode != EXCEPTION_ACCESS_VIOLATION || er->NumberParameters < 2) return EXCEPTION_CONTINUE_SEARCH;
    const uintptr_t a = (uintptr_t)er->ExceptionInformation[1];
    if (!vm_base || a < (uintptr_t)vm_base || a - (uintptr_t)vm_base >= 0x100000000ull) return EXCEPTION_CONTINUE_SEARCH;
    const uint32_t ea = (uint32_t)(a - (uintptr_t)vm_base), p = ea >> 12;
    uint8_t s = __atomic_load_n(&s_st[p], __ATOMIC_ACQUIRE);
    if (s == 0) return EXCEPTION_CONTINUE_SEARCH;
    if (s != 2 || !__atomic_compare_exchange_n(&s_st[p], &s, 4, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
        /* being opened or armed by another thread: retry; a fault that keeps coming on an open page is not ours */
        pm_thr* r = &s_thr[pm_thr_index(GetCurrentThreadId())];
        if (r->retry_ea != ea) { r->retry_ea = ea; r->retries = 0; }
        return ++r->retries > 100000u ? EXCEPTION_CONTINUE_SEARCH : EXCEPTION_CONTINUE_EXECUTION;
    }
    DWORD old;
    VirtualProtect(vm_base + ((uintptr_t)p << 12), 0x1000, PAGE_READWRITE, &old);
    __atomic_store_n(&s_st[p], 1, __ATOMIC_RELEASE);
    const int ti = pm_thr_index(GetCurrentThreadId());
    pm_thr* t = &s_thr[ti];
    if (t->hooked && t->rn < PM_RING) t->ring[t->rn++] = p;
    const uint32_t fr = s_frame;
    if (!s_done && (t->last_fault_page != p || t->last_fault_frame != fr || !t->hooked)) {
        t->last_fault_page = p; t->last_fault_frame = fr;
        const uint64_t rip = (uint64_t)xp->ContextRecord->Rip, rs = *(const uint64_t*)(uintptr_t)xp->ContextRecord->Rsp;
        pm_rec(PM_FAULT, ti, pm_now(), ea, (uint32_t)(rip - s_exe), (uint32_t)(rs - s_exe),
               (uint32_t)er->ExceptionInformation[0], fr);
    }
    return EXCEPTION_CONTINUE_EXECUTION;
}
static void pm_unwatch_all(void)
{
    const long n = s_nwl < PM_WMAX ? s_nwl : PM_WMAX;
    for (long k = 0; k < n; k++) {
        const uint32_t p = s_wl[k];
        for (;;) {
            uint8_t s = __atomic_load_n(&s_st[p], __ATOMIC_ACQUIRE);
            if (s == 3 || s == 4) continue;
            if (s == 2) { DWORD old; VirtualProtect(vm_base + ((uintptr_t)p << 12), 0x1000, PAGE_READWRITE, &old); }
            __atomic_store_n(&s_st[p], 0, __ATOMIC_RELEASE);
            break;
        }
    }
}
#endif

/* ---- hooks ---- */
static inline int pm_post_img(int i) { return i >= 206 && i <= 222; }

static void pm_dma(spu_context* spu, int put, uint32_t lsa, uint32_t ea, uint32_t size)
{
    const uint64_t t = pm_now();
    if (t < s_mark_from || t > s_to || s_done) return;
    const int ti = pm_thr_index(pm_tid());
    if (!s_thr[ti].hooked) s_thr[ti].hooked = 1;
    const int img = spu->image_id, ovl = spu->resident_ovl > 0 ? spu->resident_ovl : 0;
    const int post = pm_post_img(img) || (img == 2 && pm_post_img(ovl));
    if (post) pm_mark(ea, size, t >= s_from);
    else if (!pm_marked(ea, size)) return;
    if (t < s_from || (s_frame % s_every) > 1u) return;
    pm_rec(put ? PM_PUT : PM_GET, ti, t, ea, size, (uint32_t)(img & 511) | (uint32_t)(ovl & 511) << 9 |
           (spu->spu_id & 15u) << 18, spu->pc, lsa);
}

static void pm_surf(int kind, uint32_t loc, uint32_t off, uint32_t w, uint32_t h, uint32_t pitch, uint32_t texel)
{
    const uint64_t t = pm_now();
    if (t < s_mark_from || t > s_to || s_done) return;
    const int ti = pm_thr_index(pm_tid());
    if (!s_thr[ti].hooked) s_thr[ti].hooked = 2;
#ifdef _WIN32
    if (s_thr[ti].rn) pm_rearm_own(ti);
#endif
    if (kind == 3) { if (t >= s_from) pm_rec(PM_SFLIP, ti, t, s_frame, 0, 0, 0, 0); return; }
    if (kind == 4) { if (t >= s_from) pm_rec(PM_SSYNC, ti, t, off, 0, 0, 0, 0); return; }
    const uint32_t ea = cellGcmResolveLocated(loc == 0, off);
    const uint32_t bytes = kind == 2 ? pitch : (h ? pitch * (h - 1u) + w * texel : 0);
    if (kind == 1) pm_mark(ea, bytes, t >= s_from);
    if (kind == 2 && !pm_marked(ea, bytes)) return;
    if (t < s_from) return;
    pm_rec(kind == 0 ? PM_SGPU : kind == 1 ? PM_SWB : PM_STEX, ti, t, ea, bytes, w | h << 16, pitch, texel | loc << 16);
}

static void pm_wtrace(const char* thr, int kind, uint32_t site, uint64_t t0, uint64_t t1)
{
    if (s_prev_wt) s_prev_wt(thr, kind, site, t0, t1);
    if (s_done || t1 < s_from || t0 > s_to) return;
    if (!(kind == 32 || kind == 33 || kind == 34 || kind == 35 || kind == 3 || (kind >= 41 && kind <= 44))) return;
    const int ti = pm_thr_index(pm_tid());
    if (!s_thr[ti].name) s_thr[ti].name = thr;
#ifdef _WIN32
    if (kind == 33 && s_thr[ti].hooked == 1 && s_thr[ti].rn) pm_rearm_own(ti);   /* an SPU's pages: at its job's end */
#endif
    if (kind == 32) {   /* the frame clock (the live-draw flip hook is not reached with LD_NO_PRESENT) */
        __atomic_add_fetch(&s_frame, 1, __ATOMIC_RELAXED);
#ifdef _WIN32
        const long n = s_nwl < PM_WMAX ? s_nwl : PM_WMAX;
        for (long k = 0; k < n; k++) pm_arm(s_wl[k]);
#endif
    }
    pm_rec(PM_WT + kind, ti, t0, site, (uint32_t)((t1 - t0) / 1000u), s_frame, 0, 0);
}

#ifdef _WIN32
static DWORD WINAPI pm_thread(LPVOID p)
{
    (void)p;
    while (pm_now() < s_mark_from) Sleep(50);
    /* registered now, so that it runs before main.cpp's vm_commit_veh (added at the guest allocation, after our
     * constructor): that handler would commit, i.e. reopen, the whole 64 KB page and swallow the fault */
    if (s_watch) AddVectoredExceptionHandler(1, pm_veh);
    s_prev_wt = g_kz3_wtrace;   /* chained after KZ2_FRAME_TRACE's hook if that is on */
    if (s_prev_wt != pm_wtrace) g_kz3_wtrace = pm_wtrace;
    while (pm_now() < s_to + 300000000ull) Sleep(50);
    s_done = 1;
    pm_unwatch_all();
    Sleep(100);
    const long n = s_n < s_max ? s_n : s_max;
    fprintf(stderr, "[pmap] window done: %ld events (%ld dropped), %ld watched pages (%ld arm failures, error %lu), "
            "%u frames, every %u\n", n, s_n - n, s_nwl, s_arm_fail, s_arm_err, s_frame, s_every);
    const long nt = s_nthr < PM_THR ? s_nthr : PM_THR;
    for (long i = 0; i < nt; i++) {
        const char* g = ppu_thread_name_for_os_tid(s_thr[i].tid);
        fprintf(stderr, "[pmap-thr] %ld %lu wacct=%s ppu=%s hook=%u\n", i, s_thr[i].tid,
                s_thr[i].name && *s_thr[i].name ? s_thr[i].name : "-", g && *g ? g : "-", s_thr[i].hooked);
    }
    {   /* the watched pages, as runs */
        const long nw = s_nwl < PM_WMAX ? s_nwl : PM_WMAX;
        uint32_t* w = (uint32_t*)malloc(sizeof(uint32_t) * (size_t)(nw ? nw : 1));
        if (w) {
            memcpy(w, s_wl, sizeof(uint32_t) * (size_t)nw);
            for (long i = 1; i < nw; i++) { uint32_t x = w[i]; long j = i; while (j > 0 && w[j - 1] > x) { w[j] = w[j - 1]; j--; } w[j] = x; }
            for (long i = 0; i < nw;) {
                long j = i;
                while (j + 1 < nw && w[j + 1] - w[j] <= s_watch) j++;
                fprintf(stderr, "[pmap-w] 0x%08X..0x%08X %ld pages\n", w[i] << 12, (w[j] + 1) << 12, j - i + 1);
                i = j + 1;
            }
            free(w);
        }
    }
    FILE* f = s_out ? fopen(s_out, "wb") : NULL;
    if (f) {
        char hdr[64] = "KZ2PMAP1";
        memcpy(hdr + 8, &n, sizeof n); memcpy(hdr + 16, &s_from, 8);
        fwrite(hdr, 1, sizeof hdr, f);
        for (long i = 0; i < n; i++) { pm_ev v = s_ev[i]; v.t = v.t > s_from ? (v.t - s_from) / 1000u : 0; fwrite(&v, sizeof v, 1, f); }
        fclose(f);
        fprintf(stderr, "[pmap] %ld events written to %s\n", n, s_out);
    } else for (long i = 0; i < n; i++) {
        const pm_ev* v = &s_ev[i];
        fprintf(stderr, "[pmap] %u %llu %u %x %x %x %x %x\n", v->kind, (unsigned long long)(v->t > s_from ? (v->t - s_from) / 1000u : 0),
                v->tidx, v->a, v->b, v->c, v->d, v->e);
    }
    fprintf(stderr, "[pmap] end\n");
    return 0;
}
#endif

__attribute__((constructor)) static void kz2_post_map_init(void)
{
    const char* e = getenv("KZ2_POST_MAP");
    if (!e || !*e) return;
    double a = 0, b = 0;
    if (sscanf(e, "%lf,%lf", &a, &b) != 2 || b <= a) { fprintf(stderr, "[pmap] KZ2_POST_MAP=%s: want FROM,TO\n", e); return; }
    const char* m = getenv("KZ2_POST_MAP_MAX");
    s_max = (m && *m) ? strtol(m, NULL, 0) : 3000000;
    const char* w = getenv("KZ2_POST_MAP_WATCH");
    s_watch = (w && *w) ? (uint32_t)strtoul(w, NULL, 0) : 8u;
    const char* ev = getenv("KZ2_POST_MAP_EVERY");
    if (ev && *ev) s_every = (uint32_t)strtoul(ev, NULL, 0);
    if (!s_every) s_every = 1;
    s_out = getenv("KZ2_POST_MAP_OUT");
    if (s_max <= 0) return;
    s_ev = (pm_ev*)calloc((size_t)s_max, sizeof *s_ev);
    s_wl = (uint32_t*)calloc(PM_WMAX, sizeof *s_wl);
    if (!s_ev || !s_wl) return;
    s_base = pm_now();
    s_mark_from = s_base + (uint64_t)((a > 1.0 ? a - 1.0 : 0.0) * 1e9);   /* mark pages for a second first */
    s_from = s_base + (uint64_t)(a * 1e9);
    s_to = s_base + (uint64_t)(b * 1e9);
#ifdef _WIN32
    s_exe = (uintptr_t)GetModuleHandleA(NULL);
    g_kz2_pmap_dma = pm_dma;
    g_kz2_pmap_surf = pm_surf;
    CloseHandle(CreateThread(NULL, 0, pm_thread, NULL, 0, NULL));
#endif
    fprintf(stderr, "[pmap] KZ2_POST_MAP window %.3f-%.3f s, up to %ld events, watch every %u pages (needs KZ3_WAIT_ACCT)\n",
            a, b, s_max, s_watch);
}
