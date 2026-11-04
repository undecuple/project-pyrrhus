/* kz2_native_jobs.c -- fills the native gates: KZ2_NATIVE_JOB_<NAME>=1 per job or family,
 * KZ2_NATIVE_JOB_POST=1 for every Gfx.Post gate (=0: none), the Gfx.Post flags on by default for the slots recorded in
 * play (native_flags.h), KZ2_NATIVE_REC=DIR to record real gate inputs, KZ2_NATIVE_TOGGLE=<slots> to flip
 * those gates between lifted and native every KZ2_NATIVE_TOGGLE_PERIOD s of one run (native_toggle.h; an earlier change:
 * KZ2_NATIVE_TOGGLE_PERIOD=ab follows KZ2_AB_TOGGLE's phase, so KZ2_AB_TOGGLE_INVERT applies). Each slot's gate is
 * a trampoline into kz2_native_run (native_common.c) with that slot's entry. See kz2_native_jobs.h. */
#include "kz2_native_jobs.h"
#include "native_flags.h"
#include "native_toggle.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#endif

extern int (*g_kz2_native_gate[KZ2_NATIVE_SLOTS])(spu_context*);   /* generated spu_workloads.c (tools/spu/gen_spu_register.py) */

volatile long g_kz2_native_calls[KZ2_NATIVE_SLOTS], g_kz2_native_fallback[KZ2_NATIVE_SLOTS];

static const char* s_rec_dir;
static long s_rec_n = 24, s_rec_every = 61;
static double s_rec_after = 120.0;
static volatile long s_rec_calls[KZ2_NATIVE_SLOTS], s_rec_done[KZ2_NATIVE_SLOTS];
static time_t s_t0;
static const kz2_native_entry* s_ent[KZ2_NATIVE_SLOTS];

void kz2_native_count_print(int slot, long calls)
{
    fprintf(stderr, "[native] slot %d %s 0x%05X calls=%ld fallback=%ld\n", slot, s_ent[slot] ? s_ent[slot]->job : "?",
            s_ent[slot] ? s_ent[slot]->addr : 0u, calls, g_kz2_native_fallback[slot]);
}

static long env_long(const char* k, long d)
{
    const char* e = getenv(k);
    return (e && *e) ? strtol(e, NULL, 0) : d;
}

static int s_rec_blur;

/* KZ2_NATIVE_REC_DOF_BLUR=1: DepthOfField's gather calls count for the recorder only when a pixel has a blur radius
 * above 0 (Corinth River's walkway has none). r5 = control words (top byte = radius), r8 = pixels / 4. */
static int rec_skip(spu_context* ctx, const kz2_native_entry* e)
{
    if (!s_rec_blur || !e || strcmp(e->kind, "dof_gather")) return 0;
    const uint32_t ctl = ctx->gpr[5]._u32[0], n = ctx->gpr[8]._u32[0];
    for (uint32_t i = 0; i < 4 * n && i < 4096; i++)
        if (ctx->ls[(ctl + 4 * i) & SPU_LS_MASK]) return 0;
    return 1;
}

/* Spu an earlier change: KZ2_NATIVE_REC_SLOT=<slot>:<every>:<n>[,...] gives a slot its own spacing and count (VertexJob's
 * vertex emitter, slot 79, runs ~4 times per particle: every 7th call records one frame's vertices);
 * KZ2_NATIVE_REC_VJFLUSH=<n> also records up to n of its calls whose vertex fills the ring buffer (the fill offset
 * at LS 0x27B84 within 32 bytes of 16 KB: the DMA put and the tag wait), as s79_fNNN.kz2nj. */
static long s_rec_slot_every[KZ2_NATIVE_SLOTS], s_rec_slot_n[KZ2_NATIVE_SLOTS];
static long s_rec_vjflush;
static volatile long s_rec_fl_done;

static void rec_write(spu_context* ctx, int slot, const char* path, long n, long c)
{
    FILE* f = fopen(path, "wb");
    if (!f) {
        if (n == 0) fprintf(stderr, "[native] record: cannot write %s\n", path);
        return;
    }
    uint32_t hdr[4] = { (uint32_t)slot, s_ent[slot] ? s_ent[slot]->addr : 0u, (uint32_t)ctx->image_id,
                        (uint32_t)ctx->resident_ovl };
    fwrite(KZ2_NJ_MAGIC, 1, 8, f);
    fwrite(hdr, 4, 4, f);
    fwrite(ctx->gpr, 16, 128, f);
    fwrite(ctx->ls, 1, SPU_LS_SIZE, f);
    fclose(f);
    fprintf(stderr, "[native] recorded slot %d #%ld (call %ld) -> %s\n", slot, n, c, path);
}

static int rec(spu_context* ctx, int slot)
{
    kz2_native_count(slot);
    if (rec_skip(ctx, s_ent[slot])) return 0;
    if (difftime(time(NULL), s_t0) < s_rec_after) return 0;
    char path[1024];
    if (s_rec_vjflush && s_ent[slot] && !strcmp(s_ent[slot]->kind, "vj_vertex")) {
        const uint8_t* q = ctx->ls + 0x27B84;
        const uint32_t fill = (uint32_t)q[0] << 24 | (uint32_t)q[1] << 16 | (uint32_t)q[2] << 8 | q[3];
        if (fill >= 0x4000u - 32u && fill <= 0x4000u) {
            const long m = __atomic_fetch_add(&s_rec_fl_done, 1, __ATOMIC_RELAXED);
            if (m < s_rec_vjflush) {
                snprintf(path, sizeof path, "%s/s%02d_f%03ld.kz2nj", s_rec_dir, slot, m);
                rec_write(ctx, slot, path, m, -1);
            }
        }
    }
    const long every = s_rec_slot_every[slot] ? s_rec_slot_every[slot] : s_rec_every;
    const long nmax = s_rec_slot_n[slot] ? s_rec_slot_n[slot] : s_rec_n;
    /* calls counted from the first one after KZ2_NATIVE_REC_AFTER: that one is recorded (a rare gate gets one) */
    const long c = __atomic_fetch_add(&s_rec_calls[slot], 1, __ATOMIC_RELAXED);
    if (c % every) return 0;
    const long n = __atomic_fetch_add(&s_rec_done[slot], 1, __ATOMIC_RELAXED);
    if (n >= nmax) return 0;
    snprintf(path, sizeof path, "%s/s%02d_%03ld.kz2nj", s_rec_dir, slot, n);
    rec_write(ctx, slot, path, n, c);
    return 0;   /* the lifted body runs */
}

/* The same-run A/B (native_toggle.h): KZ2_NATIVE_TOGGLE=<slots>, KZ2_NATIVE_TOGGLE_PERIOD=<s>. */
static unsigned char s_tog[KZ2_NATIVE_SLOTS];
static unsigned long long s_tog_t0, s_tog_period = 4000;
static volatile long s_tog_phase;
static volatile long s_tog_calls[2][KZ2_NATIVE_SLOTS];
static char s_tog_list[128];

static unsigned long long now_ms(void)
{
#ifdef _WIN32
    return GetTickCount64();
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (unsigned long long)ts.tv_sec * 1000ull + (unsigned long long)ts.tv_nsec / 1000000ull;
#endif
}

/* 1 = this call runs native. The first call of a new phase prints the switch (one thread wins the exchange) and the
 * calls each toggled slot had in the phase that ended. */
extern volatile int g_kz2_ab_phase;   /* patch 7016, spu_coherency.c (KZ2_AB_TOGGLE, port/kz2/spu/kz2_ab_toggle.c) */
static int s_tog_ab;                  /* an earlier change: KZ2_NATIVE_TOGGLE_PERIOD=ab follows that phase (odd = native) */
static int tog_native(int slot)
{
    if (s_tog_ab) {   /* the [ab-toggle] lines record the switches (KZ2_AB_TOGGLE_INVERT starts the run native) */
        const int nat = __atomic_load_n(&g_kz2_ab_phase, __ATOMIC_RELAXED) & 1;
        __atomic_fetch_add(&s_tog_calls[nat][slot], 1, __ATOMIC_RELAXED);
        return nat;
    }
    const unsigned long long t = now_ms() - s_tog_t0;
    const long ph = kz2_native_toggle_phase(t, s_tog_period);
    const long old = __atomic_load_n(&s_tog_phase, __ATOMIC_RELAXED);
    if (ph != old && __atomic_compare_exchange_n(&s_tog_phase, (long*)&old, ph, 0, __ATOMIC_RELAXED,
                                                 __ATOMIC_RELAXED)) {
        char cs[512];
        int k = 0;
        cs[0] = 0;
        for (int s = 0; s < KZ2_NATIVE_SLOTS && k < (int)sizeof cs - 32; s++)
            if (s_tog[s])
                k += snprintf(cs + k, sizeof cs - k, " s%d=%ld/%ld", s,
                              __atomic_exchange_n(&s_tog_calls[0][s], 0, __ATOMIC_RELAXED),
                              __atomic_exchange_n(&s_tog_calls[1][s], 0, __ATOMIC_RELAXED));
        fprintf(stderr, "[native-toggle] t=%.3fs phase=%ld %s (ended phase %ld calls lifted/native:%s)\n",
                (double)t / 1000.0, ph, (ph & 1) ? "native" : "lifted", old, cs);
    }
    const int nat = (int)(ph & 1);
    __atomic_fetch_add(&s_tog_calls[nat][slot], 1, __ATOMIC_RELAXED);
    return nat;
}

/* KZ2_POST_SKIP (diagnostic, port/kz2/spu/kz2_ab_toggle.c): while patch 7016's g_kz2_post_skip is set,
 * a Gfx.Post subroutine gate returns at once (the pass or kernel does nothing; with the arena's DMA skipped too the
 * picture is wrong); otherwise the gate the slot would have had (s_skip_base, NULL = the lifted body). */
extern volatile int g_kz2_post_skip;   /* patch 7016, spu_coherency.c */
static int (*s_skip_base[KZ2_NATIVE_SLOTS])(spu_context*);
static volatile long s_skip_n;
static int post_skip(spu_context* c, int slot)
{
    if (__atomic_load_n(&g_kz2_post_skip, __ATOMIC_RELAXED)) { __atomic_fetch_add(&s_skip_n, 1, __ATOMIC_RELAXED); return 1; }
    return s_skip_base[slot] ? s_skip_base[slot](c) : 0;
}
long kz2_post_skip_gate_calls(void) { return __atomic_load_n(&s_skip_n, __ATOMIC_RELAXED); }

/* One trampoline per slot (the gate pointer takes only the context): the slot's entry through kz2_native_run, the
 * recorder, the toggle or the post skip. */
#define T1(a, b) static int gate_##a##b(spu_context* c) { return kz2_native_run(c, s_ent[8 * a + b]); } \
                 static int rec_##a##b(spu_context* c) { return rec(c, 8 * a + b); } \
                 static int tog_##a##b(spu_context* c) { \
                     return tog_native(8 * a + b) ? kz2_native_run(c, s_ent[8 * a + b]) : 0; } \
                 static int skp_##a##b(spu_context* c) { return post_skip(c, 8 * a + b); }
#define T8(a) T1(a, 0) T1(a, 1) T1(a, 2) T1(a, 3) T1(a, 4) T1(a, 5) T1(a, 6) T1(a, 7)
T8(0) T8(1) T8(2) T8(3) T8(4) T8(5) T8(6) T8(7) T8(8) T8(9) T8(10) T8(11) T8(12) T8(13) T8(14) T8(15)
#define P8(f, a) f##a##0, f##a##1, f##a##2, f##a##3, f##a##4, f##a##5, f##a##6, f##a##7
#define P128(f) P8(f, 0), P8(f, 1), P8(f, 2), P8(f, 3), P8(f, 4), P8(f, 5), P8(f, 6), P8(f, 7), P8(f, 8), P8(f, 9), \
                P8(f, 10), P8(f, 11), P8(f, 12), P8(f, 13), P8(f, 14), P8(f, 15)
static int (*const s_gate_fn[KZ2_NATIVE_SLOTS])(spu_context*) = { P128(gate_) };
static int (*const s_rec_fn[KZ2_NATIVE_SLOTS])(spu_context*) = { P128(rec_) };
static int (*const s_tog_fn[KZ2_NATIVE_SLOTS])(spu_context*) = { P128(tog_) };
static int (*const s_skp_fn[KZ2_NATIVE_SLOTS])(spu_context*) = { P128(skp_) };

static const char* get_env(const char* k) { return getenv(k); }

/* The flag that turns the entry on, or NULL (native_flags.h: the Gfx.Post flags on by default since an earlier change). */
static const char* enabled_by(const kz2_native_entry* e)
{
    static char buf[96];
    return kz2_native_enabled_by(e->env, e->job, e->slot, get_env, buf, sizeof buf);
}

static void add_one(const kz2_native_entry* e)
{
    if (s_rec_dir) {
        g_kz2_native_gate[e->slot] = s_rec_fn[e->slot];
        return;
    }
    if (s_tog[e->slot]) {
        g_kz2_native_gate[e->slot] = s_tog_fn[e->slot];
        fprintf(stderr, "[native] %s %s 0x%05X %s toggled every %llu ms (slot %d, KZ2_NATIVE_TOGGLE=%s)\n", e->job,
                e->image, e->addr, e->kind, s_tog_period, e->slot, s_tog_list);
        return;
    }
    const char* by = enabled_by(e);
    if (by) {
        g_kz2_native_gate[e->slot] = s_gate_fn[e->slot];
        fprintf(stderr, "[native] %s %s 0x%05X %s native (slot %d, %s)\n", e->job, e->image, e->addr, e->kind,
                e->slot, by);
    }
}

static int s_post_skip_on;   /* KZ2_POST_SKIP set (read once at init) */

/* KZ2_POST_SKIP: the Gfx.Post subroutine gates take the skip trampoline over whatever add() installed. Not ILR's
 * slot 68 (its native code also runs the pass's epilogue reloads) nor a "continue at" gate. */
static void add_skip(const kz2_native_entry* e)
{
    if (!s_post_skip_on || !e->job || strncmp(e->job, "Gfx.Post.", 9) || e->cont || e->slot == 68) return;
    s_skip_base[e->slot] = g_kz2_native_gate[e->slot];
    g_kz2_native_gate[e->slot] = s_skp_fn[e->slot];
}

static void add(const kz2_native_entry* t, unsigned n)
{
    for (unsigned i = 0; i < n; i++) {
        const kz2_native_entry* e = &t[i];
        if (e->slot < 0 || e->slot >= KZ2_NATIVE_SLOTS) continue;
        s_ent[e->slot] = e;
        add_one(e);
        add_skip(e);
    }
}

__attribute__((constructor)) static void kz2_native_jobs_init(void)
{
    s_t0 = time(NULL);
    const char* d = getenv("KZ2_NATIVE_REC");
    if (d && *d) {
        s_rec_dir = d;
        s_rec_n = env_long("KZ2_NATIVE_REC_N", 24);
        s_rec_every = env_long("KZ2_NATIVE_REC_EVERY", 61);
        if (s_rec_every < 1) s_rec_every = 1;
        s_rec_after = (double)env_long("KZ2_NATIVE_REC_AFTER", 120);
        s_rec_blur = (int)env_long("KZ2_NATIVE_REC_DOF_BLUR", 0);
        s_rec_vjflush = env_long("KZ2_NATIVE_REC_VJFLUSH", 0);
        for (const char* p = getenv("KZ2_NATIVE_REC_SLOT"); p && *p;) {   /* slot:every:n[,...] */
            char* q;
            const long sl = strtol(p, &q, 0);
            long ev = 0, nn = 0;
            if (*q == ':') ev = strtol(q + 1, &q, 0);
            if (*q == ':') nn = strtol(q + 1, &q, 0);
            if (sl >= 0 && sl < KZ2_NATIVE_SLOTS && ev > 0) {
                s_rec_slot_every[sl] = ev;
                s_rec_slot_n[sl] = nn > 0 ? nn : s_rec_n;
            }
            p = strchr(q, ',');
            if (p) p++;
        }
        fprintf(stderr, "[native] recording gate inputs to %s (%ld per slot, every %ld calls, after %.0f s)\n", d,
                s_rec_n, s_rec_every, s_rec_after);
    }
    { const char* ps = getenv("KZ2_POST_SKIP"); s_post_skip_on = ps && *ps && *ps != '0'; }   /* an earlier change */
    const char* tg = getenv("KZ2_NATIVE_TOGGLE");
    if (!s_rec_dir && tg && *tg) {
        const int n = kz2_native_toggle_parse(tg, s_tog, KZ2_NATIVE_SLOTS);
        const char* ps = getenv("KZ2_NATIVE_TOGGLE_PERIOD");
        s_tog_ab = ps && !strcmp(ps, "ab");   /* an earlier change */
        const double per = (ps && *ps && !s_tog_ab) ? strtod(ps, NULL) : 4.0;
        if (per >= 0.1) s_tog_period = (unsigned long long)(per * 1000.0 + 0.5);
        snprintf(s_tog_list, sizeof s_tog_list, "%s", tg);
        s_tog_t0 = now_ms();
        if (n < 0) fprintf(stderr, "[native] KZ2_NATIVE_TOGGLE=%s: not a slot list (75,76 or 75-77); toggle off\n", tg);
        else if (s_tog_ab) fprintf(stderr, "[native-toggle] %d slots follow KZ2_AB_TOGGLE's phase (odd = native)\n", n);
        else fprintf(stderr, "[native-toggle] t=0.000s phase=0 lifted (start: %d slots, period %llu ms)\n", n,
                     s_tog_period);
    }
    add(kz2_native_dof, kz2_native_dof_n);
    add(kz2_native_post, kz2_native_post_n);
    add(kz2_native_blur, kz2_native_blur_n);
    add(kz2_native_bloom, kz2_native_bloom_n);
    add(kz2_native_postjobs, kz2_native_postjobs_n);
    add(kz2_native_edgeanim, kz2_native_edgeanim_n);
    add(kz2_native_particles, kz2_native_particles_n);
    add(kz2_native_skinning, kz2_native_skinning_n);
    add(kz2_native_raycast, kz2_native_raycast_n);
    if (s_post_skip_on) {
        int n = 0;
        for (int k = 0; k < KZ2_NATIVE_SLOTS; k++) n += g_kz2_native_gate[k] == s_skp_fn[k];
        fprintf(stderr, "[post-skip] %d Gfx.Post gates return at once while the skip is on\n", n);
    }
}
