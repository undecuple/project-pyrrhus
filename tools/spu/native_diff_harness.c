/* native_diff_harness.c -- lifted vs native (vs interpreted) for KZ2's native SPU gates.
 * From Project Helghast tools/spu/job_diff_harness.c (the runtime contract stubs, run_lifted, run_interp and the
 * compare), adapted: the second side is the native gate function (port/kz2/spu/native_*.c), the interpreter is a
 * third side, the inputs are synthetic per-kernel states or states recorded in the game (KZ2_NATIVE_REC).
 * Built and driven by tools/spu/native_diff.py, compiled together with the image's lifted spu_recomp.c, the
 * runtime's spu_drain.c and spu_interp.c, and the native sources.
 *
 * Usage: harness IMAGE.bin BASE synth SLOT SEED TRIALS
 *        harness IMAGE.bin BASE rec FILE...
 * One line per case: `C <name> ok|MISMATCH|fallback ...`, then `T slot=.. cases=.. match=.. mismatch=.. fallback=..
 * interp_mismatch=..`. A case matches when the whole 256 KB local store and the registers the SPU ABI preserves
 * across a call (r0, r1, r80-r127) are equal after the lifted and the native run; the scratch registers r2-r79 are
 * reported (`scratch_regs_differ=N`), not compared: the gated kernels are leaves whose caller writes every scratch
 * register before reading it (the RE notes an earlier change). With HARNESS_INTERP=1 the interpreter also runs and must
 * equal the lifted run in everything (registers included).
 * An earlier change, "continue at" gates (the entry's cont != 0: code that is no subroutine): the lifted run ends when it hops
 * to the lifted function at cont, the interpreter at a stop planted there, and all 128 registers are compared.
 */
#include "spu_context.h"
#include "spu_helpers.h"
#include "spu_interp.h"
#include "kz2_native_jobs.h"
#include "harness_mfc.h"
#include <setjmp.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

extern uint64_t g_spu_interp_steps;
static uint64_t now_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000u + t.tv_nsec;
}

static int g_no_arm;
static void arm(int on)
{
    if (g_no_arm) return;
    struct itimerval it;
    memset(&it, 0, sizeof it);
    it.it_value.tv_sec = on ? 2 : 0;   /* 2 s per run */
    setitimer(ITIMER_REAL, &it, NULL);
}

#define SENTINEL 0x3FF00u

/* ---- the native side's globals (kz2_native_jobs.c / the generated spu_workloads.c in the game) ---- */
int (*g_kz2_native_gate[KZ2_NATIVE_SLOTS])(spu_context*);
volatile long g_kz2_native_calls[KZ2_NATIVE_SLOTS], g_kz2_native_fallback[KZ2_NATIVE_SLOTS];
void kz2_native_count_print(int slot, long calls) { (void)slot; (void)calls; }

/* ---- the contract the lifted code and spu_drain.c expect from the runtime (Project Helghast job_diff_harness.c) ---- */
int g_spu_ls_watch_n = 0;
void spu_ls_watch_slow(uint32_t a, int w, const uint8_t* p, uint32_t pc, uint32_t lr)
{
    (void)a; (void)w; (void)p; (void)pc; (void)lr;
}
__attribute__((weak)) volatile unsigned g_spu_stack_reset_n;
__attribute__((weak)) volatile int g_yz_lockstep_on;
void yz_lockstep_tick(spu_context* c) { (void)c; }
void spu_check_stack_reset(spu_context* c, void (*f)(spu_context*)) { (void)c; (void)f; }

/* Runtime globals and hooks the lifted code and spu_drain.c reference since Project Helghast (ps3recomp v0.18.0 + the
 * KZ3 SPU batch): all off / empty here. */
unsigned g_spu_stack_reset_count;
void (*g_kz3_wtrace)(const char*, int, uint32_t, uint64_t, uint64_t);
volatile unsigned long long g_spu_ib_guess_n;
int g_kz3_pmend_ib;
void* volatile g_kz3_trace_ctx;
int g_spu_ovl_skip_any;
uint8_t g_spu_ovl_skip[512];
uint64_t g_spu_task_entry_bits[16];
uint64_t g_spu_task_pol_bits[16];
int g_spu_task_pol_big;
void kz3_jobcall_close(spu_context* c, uint32_t a) { (void)c; (void)a; }
int kz3_wws_interp_on(void) { return 0; }
void spu_jmp_no_unwind(void* env) { (void)env; }
int spu_ib_guess_register(const uint32_t* addrs, void (SPU_ABI* const* fns)(spu_context*), int n)
{
    (void)addrs; (void)fns; (void)n;
    return 0;
}

typedef void (*fn_t)(spu_context*);
static struct {
    uint32_t addr;
    fn_t fn;
} reg[65536];
static unsigned nreg;
void spu_begin_image(int id) { (void)id; }
void spu_register_function(uint32_t addr, fn_t fn)
{
    if (nreg < 65536) {
        reg[nreg].addr = addr;
        reg[nreg].fn = fn;
        nreg++;
    }
}
fn_t spu_lookup(uint32_t addr, int img)
{
    (void)img;
    for (unsigned i = 0; i < nreg; i++)
        if (reg[i].addr == addr) return reg[i].fn;
    return NULL;
}
spu_lifted_fn spu_lifted_lookup(const spu_context* c, uint32_t a) { (void)c; (void)a; return NULL; }
int spu_overlay_match_sig(const uint8_t hdr[16]) { (void)hdr; return 0; }
spu_lifted_fn spu_lookup_ovl_exact(uint32_t addr, int image_id) { (void)addr; (void)image_id; return NULL; }

enum { R_NONE, R_RET, R_CHAN, R_STOP, R_MISS, R_TIMEOUT, R_RESTART };
static sigjmp_buf jb;
static volatile int why;

void spu_halt(spu_context* c) { (void)c; if (!why) why = R_STOP; siglongjmp(jb, 1); }
void spu_stop(spu_context* c) { c->status = SPU_STATUS_STOPPED_BY_STOP; why = R_STOP; siglongjmp(jb, 1); }
static void chan(void) { why = R_CHAN; siglongjmp(jb, 1); }
/* the MFC model (harness_mfc.h): one log per side (A lifted, B native, C interpreter); MFC writes and
 * reads go to the context's log, puts with their bytes; anything else (or another context) ends the run as before. */
static spu_context S, A, B, C;
static hmfc_log LA, LB, LC;
static hmfc_log* mfc_log_of(spu_context* c) { return c == &A ? &LA : c == &B ? &LB : c == &C ? &LC : NULL; }
u128 spu_rdch(spu_context* c, uint32_t ch)
{
    hmfc_log* l = mfc_log_of(c);
    uint32_t v;
    if (l && hmfc_rdch(l, ch, &v)) return spu_splat_u32(v);
    chan();
    return spu_splat_u32(0);
}
uint32_t spu_rchcnt(spu_context* c, uint32_t ch) { (void)c; (void)ch; chan(); return 0; }
void spu_wrch(spu_context* c, uint32_t ch, u128 v)
{
    hmfc_log* l = mfc_log_of(c);
    if (l && hmfc_wrch(l, c->ls, ch, v._u32[0]) == 1) return;
    chan();
}
void spu_restart_dispatch(spu_context* c) { (void)c; why = R_RESTART; siglongjmp(jb, 1); }
void spu_spurs_taskset_syscall(spu_context* c) { (void)c; chan(); }
void spu_indirect_branch(spu_context* c)
{
    c->pc &= SPU_LS_MASK;
    if (c->pc == SENTINEL) { why = R_RET; siglongjmp(jb, 1); }
    fn_t f = spu_lookup(c->pc, 0);
    if (!f) { why = R_MISS; siglongjmp(jb, 1); }
    f(c);
}
void spu_indirect_branch_mt(spu_context* c) { spu_indirect_branch(c); }
spu_hop_fn spu_ib_direct(spu_context* ctx, uint32_t t)
{
    (void)ctx;
    return (spu_hop_fn)spu_lookup(t & SPU_LS_MASK, 0);
}
static void on_alarm(int s) { (void)s; why = R_TIMEOUT; siglongjmp(jb, 1); }

static fn_t g_stop_fn;             /* a "continue at" gate's lifted run ends at this function */
static uint32_t g_end = SENTINEL;   /* where the interpreter's planted stop sits */
/* An earlier change, a computed continuation (cont KZ2_NATIVE_CONT_PC): the native side runs first; the lifted run then ends
 * at the first transfer to the native exit's pc (g_end) after as many passes through the gate's own address (the loop
 * head) as the native code made (g_kz2_native_heads, set by the native code in harness builds), the first one being
 * the call itself. */
static int g_pc_mode;
static uint32_t g_pc_head, g_heads, g_heads_want;
unsigned g_kz2_native_heads;

static int run_lifted(spu_context* c, fn_t f)
{
    spu_context* ctx = c; /* g_spu_trampoline_fn is per context (patch 1017) */
    why = R_NONE;
    g_heads = 1;
    if (sigsetjmp(jb, 1) == 0) {
        arm(1);
        f(c);
        while (g_spu_trampoline_fn) {
            if (g_spu_trampoline_fn == spu_indirect_branch && (c->pc & SPU_LS_MASK) == SENTINEL) { why = R_RET; break; }
            if (g_stop_fn && g_spu_trampoline_fn == g_stop_fn) { why = R_RET; break; }
            if (g_pc_mode) {
                const uint32_t pc = c->pc & SPU_LS_MASK;
                if (pc == g_pc_head) g_heads++;
                if (pc == g_end && g_heads == g_heads_want) { why = R_RET; break; }
            }
            fn_t t = g_spu_trampoline_fn;
            g_spu_trampoline_fn = 0;
            t(c);
        }
        if (!why) why = (c->pc & SPU_LS_MASK) == SENTINEL ? R_RET : R_RESTART;
        if (why == R_RET && g_stop_fn && (c->pc & SPU_LS_MASK) != g_end) why = R_RESTART;
    }
    arm(0);
    g_spu_trampoline_fn = 0;
    return why;
}

static int run_interp(spu_context* c, uint32_t entry)
{
    why = R_NONE;
    c->image_id = -1;
    if (sigsetjmp(jb, 1) == 0) {
        arm(1);
        spu_interp_run(c, entry);
        why = (((c->pc & SPU_LS_MASK) == g_end || (c->pc & SPU_LS_MASK) == g_end + 4) && c->stop_code == 0x3FFF)
                  ? R_RET : R_STOP;
    }
    arm(0);
    return why;
}

/* ---- inputs ---- */
static uint64_t rng;
static uint32_t rnd(void)
{
    rng ^= rng << 13;
    rng ^= rng >> 7;
    rng ^= rng << 17;
    return (uint32_t)rng;
}
static uint8_t* image;
static long image_len;
static uint32_t base;

/* A context's local store is its own ls_store array; ctx->ls points at it (spu_context_init). A struct copy keeps
 * the source's pointer, so every copy is repointed at its own array (the copy of the bytes comes with the struct). */
static void ctx_copy(spu_context* d, const spu_context* s)
{
    memcpy(d, s, sizeof *s);
    d->ls = d->ls_store;
}

static void be32w(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v;
}

/* A float for the kernels' data: mostly ordinary positive values, some arbitrary bit patterns (zero, denormal,
 * exponent 255, negative) so the SPU float rules are exercised too. */
static int g_dirty;   /* this trial's data includes the odd patterns */
static uint32_t rfloat(void)
{
    uint32_t m = g_dirty ? rnd() % 16 : 3;
    if (m == 0) return rnd();
    if (m == 1) return rnd() & 0x807FFFFFu;         /* zero / denormal */
    if (m == 2) return 0x7F800000u | (rnd() & 0x807FFFFFu);   /* exponent 255 */
    float f = (float)(rnd() % 100000) / 1000.0f;
    uint32_t u;
    memcpy(&u, &f, 4);
    return u;
}

static void base_state(spu_context* c, uint64_t seed)
{
    spu_context_init(c, 0);
    rng = seed * 0x9E3779B97F4A7C15ull + 1;
    for (uint32_t a = 0; a < SPU_LS_SIZE; a += 4) be32w(c->ls + a, rnd());
    memcpy(c->ls + base, image, (size_t)image_len);
    for (int r = 2; r < 128; r++)
        for (int k = 0; k < 4; k++) c->gpr[r]._u32[k] = rnd();
    c->gpr[1] = spu_splat_u32(0x3F000);
    c->image_id = 1;
}

static void setreg(spu_context* c, int r, uint32_t v)
{
    c->gpr[r] = spu_splat_u32(v);
}

/* Gfx.Post.DepthOfField 0x5750 (slot 0): the gather; the layout of the game's pass @0x4A20 (a band of rows of float4
 * pixels, the scratch, the RGBA8 row, the control row), sizes and radii at random. */
static void synth_dof_gather(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    const uint32_t widths[4] = {64, 80, 96, 128};
    const uint32_t w = widths[rnd() % 4], st = 16 * w;
    const uint32_t work0 = 0x8000, x0 = rnd() % 8;
    g_dirty = rnd() % 4 == 0 && !(getenv("HARNESS_DIRTY") && *getenv("HARNESS_DIRTY") == '0');   /* a quarter of the trials: zero, denormal, exponent-255 and negative words too */
    for (uint32_t a = work0; a < work0 + 29 * st; a += 4) be32w(c->ls + a, rfloat());
    const uint32_t n = 4 * (1 + rnd() % ((w / 4 - x0) / 4 > 0 ? (w / 4 - x0) / 4 : 1));
    const uint32_t ctl = 0x30000, tmp = 0x32000, out = 0x34000;
    const int mode = (int)(rnd() % 4);
    for (uint32_t a = ctl; a < ctl + 16 * n + 64; a += 4) {
        uint32_t v = rnd(), r;
        if (mode == 0) r = 0;                                  /* all zero: the fma path */
        else if (mode == 1) r = (rnd() % 3) ? 0 : rnd() % 256; /* mixed */
        else if (mode == 2) r = rnd() % 32;                    /* small radii */
        else r = rnd() % 256;
        be32w(c->ls + a, (v & 0x00FFFFFFu) | r << 24);
    }
    setreg(c, 3, out);
    setreg(c, 4, work0 + 7 * st + 64 * x0);
    setreg(c, 5, ctl);
    setreg(c, 6, tmp);
    setreg(c, 7, st);
    setreg(c, 8, n);
}

/* Gfx.Post.DepthOfField 0x5F80 (slot 1): the unpack; 1-8 groups of 16 pixels, random bytes, into the band buffer. */
static void synth_dof_unpack(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    setreg(c, 3, 0x6CC0 + 1536 * (rnd() % 4));
    setreg(c, 4, 0x20000 + 64 * (rnd() % 16));
    setreg(c, 5, 0x24000 + 64 * (rnd() % 16));
    setreg(c, 6, 1 + rnd() % 8);
}

/* Spu an earlier change: the shared Gfx.Post output kernels (r3 = target in place, r4 = source, r5 = pixels, a multiple of 20)
 * and Gfx.Post.Upsample's two kernels. Buffers above the image (LS 0x10000 on), apart from each other. */
static void synth_mix(spu_context* c, uint64_t seed, uint32_t P)
{
    base_state(c, seed);
    const uint32_t n = 20 * (1 + rnd() % 20);
    setreg(c, 3, 0x20000 + 16 * (rnd() % 64));
    setreg(c, 4, 0x28000 + 16 * (rnd() % 64));
    setreg(c, 5, n);
    const int mode = (int)(rnd() % 3);   /* random bytes; many 0 and 255 bytes; halfwords near 0x7FFF/0x8000/0xFFFF */
    for (uint32_t a = 0x20000; a < 0x30000; a++) {
        if (mode == 1) c->ls[a] = (rnd() % 3 == 0) ? 0 : (rnd() % 2 ? 255 : c->ls[a]);
        else if (mode == 2 && !(a & 1)) c->ls[a] = (uint8_t[]){0x7F, 0x80, 0xFF, 0x00, 0x40}[rnd() % 5];
    }
    (void)P;
}
static void synth_blend(spu_context* c, uint64_t seed) { synth_mix(c, seed, 4); }
static void synth_addb(spu_context* c, uint64_t seed) { synth_mix(c, seed, 4); }
static void synth_addh(spu_context* c, uint64_t seed) { synth_mix(c, seed, 8); }

/* Upsample: r3 = output row A, r4 = source row 0, r5 = source stride, r6 = output stride, r7 = output pixels per row
 * (a multiple of 8). Source rows at 0x20000, outputs at 0x30000; strides at least the row (plus the quadword the
 * kernel reads past each end), sometimes much larger. Data: random bytes, or (16-bit pixels) many channels at or
 * above 0x8000 (the SPU's mpya takes them as negative). */
static void synth_up(spu_context* c, uint64_t seed, uint32_t P)
{
    base_state(c, seed);
    const uint32_t n = 8 * (1 + rnd() % (P == 4 ? 40 : 20));
    const uint32_t ib = n / 2 * P, ob = n * P;
    const uint32_t ss = 16 * ((ib + 32) / 16 + rnd() % 8), ds = 16 * (ob / 16 + rnd() % 8);
    setreg(c, 3, 0x30000 + 16 * (rnd() % 16));
    setreg(c, 4, 0x20010 + 16 * (rnd() % 16));
    setreg(c, 5, ss);
    setreg(c, 6, ds);
    setreg(c, 7, n);
    if (P == 8 && rnd() % 2)
        for (uint32_t a = 0x20000; a < 0x30000; a += 2) c->ls[a] = (uint8_t)(0x80 | rnd());
}
static void synth_up4(spu_context* c, uint64_t seed) { synth_up(c, seed, 4); }
static void synth_up8(spu_context* c, uint64_t seed) { synth_up(c, seed, 8); }

/* Spu an earlier change: Gfx.Post.VBlur / HBlur row kernels. VBlur: r3 = output, r4 = centre row (3 rows above and below it),
 * r5 = stride, r6 = pixels (a multiple of 4); HBlur: r3 = output, r4 = row, r5 = groups of 20 (4-byte) or 10 (8-byte)
 * pixels. Inputs from LS 0x20000, outputs at 0x38000. Data: random bytes; many 0 and 255 bytes; or (16-bit channels)
 * many halfwords at or above 0x8000 (the SPU's mpya takes them as negative). */
static void blur_data(spu_context* c, uint32_t P)
{
    const int mode = (int)(rnd() % 3);
    for (uint32_t a = 0x20000; a < 0x38000; a++) {
        if (mode == 1) c->ls[a] = (rnd() % 3 == 0) ? 0 : (rnd() % 2 ? 255 : c->ls[a]);
        else if (mode == 2 && P == 8 && !(a & 1)) c->ls[a] = (uint8_t)(0x80 | rnd());
    }
}
static void synth_vblur(spu_context* c, uint64_t seed, uint32_t P)
{
    base_state(c, seed);
    const uint32_t n = 4 * (1 + rnd() % (P == 4 ? 64 : 32)), bytes = n * P;
    const uint32_t ss = 16 * ((bytes + 15) / 16 + rnd() % 16);
    setreg(c, 3, 0x38000 + 16 * (rnd() % 64));
    setreg(c, 4, 0x20000 + 3 * ss + 16 * (rnd() % 16));
    setreg(c, 5, ss);
    setreg(c, 6, n);
    blur_data(c, P);
}
static void synth_hblur(spu_context* c, uint64_t seed, uint32_t P)
{
    base_state(c, seed);
    setreg(c, 3, 0x38000 + 16 * (rnd() % 64));
    setreg(c, 4, 0x20020 + 16 * (rnd() % 64));
    setreg(c, 5, 1 + rnd() % 24);
    blur_data(c, P);
}
static void synth_vblur4(spu_context* c, uint64_t seed) { synth_vblur(c, seed, 4); }
static void synth_vblur8(spu_context* c, uint64_t seed) { synth_vblur(c, seed, 8); }
static void synth_hblur4(spu_context* c, uint64_t seed) { synth_hblur(c, seed, 4); }
static void synth_hblur8(spu_context* c, uint64_t seed) { synth_hblur(c, seed, 8); }

/* Spu an earlier change: Gfx.Post.BloomCapture's pass @0x4AD8. r3 = parameters (quadword +0x10: width, rows, format at bytes
 * 4, 5, 6-7), r4 = curve table (129 bytes at a 4-byte stride, floats a, b at +0x210/+0x214), r5 = RGBA8 pixels,
 * r6 = one float per pixel, r9 = output. Formats 4 (RGBA8 out) and 8 or another value (16-bit channels out); widths
 * 0-255 (not always a multiple of 20), 0-3 rows; floats mostly in [-1, 2], a quarter of the trials with zero,
 * denormal, exponent-255 and negative words. */
static void synth_bloom(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    g_dirty = rnd() % 4 == 0;
    const uint32_t prm = 0x30000, tab = 0x1000 + 4 * (rnd() % 64);
    const uint32_t width = rnd() % 8 ? 20 * (1 + rnd() % 12) : rnd() % 256, rows = rnd() % 8 ? 1 + rnd() % 3 : 0;
    const uint32_t fmt = (uint32_t[]){4, 8, 4, 8, 0x100, 0}[rnd() % 6];
    c->ls[prm + 0x14] = (uint8_t)width;
    c->ls[prm + 0x15] = (uint8_t)rows;
    c->ls[prm + 0x16] = (uint8_t)(fmt >> 8);
    c->ls[prm + 0x17] = (uint8_t)fmt;
    /* half the trials keep the luminance term live: a in [0.5, 1.5], b in [-0.3, 0.3] and a first byte (the
     * coverage, times 4 in k2) below 64, so neither clamp saturates and its rounding reaches the output */
    const int live = rnd() % 2;
    for (int i = 0; i < 2; i++) {
        float f = live ? (i ? (float)((int)(rnd() % 600) - 300) / 1000.0f : 0.5f + (float)(rnd() % 1000) / 1000.0f)
                       : (float)((int)(rnd() % 8000) - 4000) / 1000.0f;
        uint32_t u;
        memcpy(&u, &f, 4);
        be32w(c->ls + tab + 0x210 + 4 * i, g_dirty && rnd() % 4 == 0 ? rfloat() : u);
    }
    if (live)
        for (uint32_t a = 0x10000; a < 0x14000; a += 4) c->ls[a] &= 0x3F;
    for (uint32_t a = 0x14000; a < 0x18000; a += 4) {
        float f = (float)((int)(rnd() % 3000) - 1000) / 1000.0f;
        uint32_t u;
        memcpy(&u, &f, 4);
        be32w(c->ls + a, g_dirty && rnd() % 3 == 0 ? rfloat() : u);
    }
    setreg(c, 3, prm);
    setreg(c, 4, tab);
    setreg(c, 5, 0x10000 + 16 * (rnd() % 16));
    setreg(c, 6, 0x14000 + 16 * (rnd() % 16));
    setreg(c, 9, 0x20000 + 16 * (rnd() % 16));
}

/* Gfx.Post.GrainWeight's pass @0x4AD8: r3 = parameters (width, rows at bytes 4, 5 of +0x10), r4 = table (bytes at
 * +4 i + 3), r5 = RGBA8 pixels, r6 = RGBA8 pixels whose bytes 1-3 pass through, r9 = output. */
static void synth_grain(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    const uint32_t prm = 0x30000, tab = 0x1000 + 4 * (rnd() % 64);
    const uint32_t width = rnd() % 8 ? 20 * (1 + rnd() % 12) : rnd() % 256, rows = rnd() % 8 ? 1 + rnd() % 3 : 0;
    c->ls[prm + 0x14] = (uint8_t)width;
    c->ls[prm + 0x15] = (uint8_t)rows;
    if (rnd() % 2)   /* a smooth curve sometimes (the lerp between neighbours matters) */
        for (uint32_t i = 0; i <= 128; i++) c->ls[tab + 4 * i + 3] = (uint8_t)(i * 2 > 255 ? 255 : i * 2);
    setreg(c, 3, prm);
    setreg(c, 4, tab);
    setreg(c, 5, 0x10000 + 16 * (rnd() % 16));
    setreg(c, 6, 0x14000 + 16 * (rnd() % 16));
    setreg(c, 9, 0x20000 + 16 * (rnd() % 16));
}

/* Spu an earlier change: the small Gfx.Post passes @0x4A20 (Modulate, BloomIntegrate, Vignette, DepthToFuzzy) and Downsample's
 * row kernels. Parameter block at 0x30000 (quadword +0x10: width, rows at bytes 4, 5; Modulate's format halfword at
 * bytes 6-7; BloomIntegrate's format byte 7 of the quadword at +0); sources from 0x10000, outputs from 0x20000 (or the
 * source itself: in place); widths mostly multiples of 20, sometimes any byte; data random, with odd patterns. */
static void pass_prm(spu_context* c, uint32_t* width, uint32_t* rows)
{
    *width = rnd() % 8 ? 20 * (1 + rnd() % 12) : rnd() % 256;
    *rows = rnd() % 8 ? 1 + rnd() % 3 : rnd() % 2;
    c->ls[0x30014] = (uint8_t)*width;
    c->ls[0x30015] = (uint8_t)*rows;
    setreg(c, 3, 0x30000);
}
static void put_float(spu_context* c, uint32_t a, float f)
{
    uint32_t u;
    memcpy(&u, &f, 4);
    be32w(c->ls + a, u);
}
/* Modulate: r4 = factor quadword (float lanes; cfltu 2^8: factors at or above 128 give a negative 16-bit m) */
static void synth_modulate(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    g_dirty = rnd() % 4 == 0;
    uint32_t w, r;
    pass_prm(c, &w, &r);
    const uint32_t fmt = (uint32_t[]){4, 8, 4, 8, 0x104, 0}[rnd() % 6];
    c->ls[0x30016] = (uint8_t)(fmt >> 8);
    c->ls[0x30017] = (uint8_t)fmt;
    const uint32_t fq = 0x31000 + 16 * (rnd() % 16);
    for (int k = 0; k < 4; k++) {
        const int m = (int)(rnd() % 4);
        const float f = m == 0 ? (float)(rnd() % 4000) / 1000.0f : m == 1 ? (float)(rnd() % 300) : (float)(rnd() % 1000) / 999.0f;
        if (g_dirty && rnd() % 3 == 0) be32w(c->ls + fq + 4 * k, rfloat());
        else put_float(c, fq + 4 * k, rnd() % 8 ? f : -f);
    }
    setreg(c, 4, fq);
    const uint32_t src = 0x10000 + 16 * (rnd() % 16);
    setreg(c, 5, src);
    setreg(c, 9, rnd() % 4 ? 0x20000 + 16 * (rnd() % 16) : src);
    if (rnd() % 2)
        for (uint32_t a = 0x10000; a < 0x20000; a += 2) c->ls[a] = (uint8_t)(rnd() % 2 ? 0x80 | rnd() : 0);
}
/* BloomIntegrate: r4 = address of the scale word (any byte offset; read by lqd + rotqby) */
static void synth_bloomint(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    g_dirty = rnd() % 4 == 0;
    uint32_t w, r;
    pass_prm(c, &w, &r);
    c->ls[0x30007] = (uint8_t)(uint32_t[]){4, 8, 4, 0, 5}[rnd() % 5];
    const uint32_t sa = 0x31000 + (rnd() % 2 ? 4 * (rnd() % 64) : rnd() % 256);
    const float S = rnd() % 2 ? (float)(rnd() % 255000) / 1000.0f : (float)(rnd() % 600000) / 1000.0f;
    uint32_t u;
    memcpy(&u, &S, 4);
    if (g_dirty && rnd() % 3 == 0) u = rfloat();
    /* the word as lqd + rotqby read it: bytes sa.. wrapping inside the quadword at sa & ~15 */
    for (int k = 0; k < 4; k++) c->ls[(sa & ~15u) + ((sa + (uint32_t)k) & 15)] = (uint8_t)(u >> (24 - 8 * k));
    setreg(c, 4, sa);
    const uint32_t src = 0x10000 + 16 * (rnd() % 16);
    setreg(c, 5, src);
    setreg(c, 9, rnd() % 4 ? 0x20000 + 16 * (rnd() % 16) : src);
}
/* Vignette: width and rows any byte (small rows); source and output at any byte / word offset, sometimes in place */
static void synth_vignette(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    const uint32_t w = rnd() % 4 ? 1 + rnd() % 160 : rnd() % 256, r = rnd() % 8 ? 1 + rnd() % 6 : rnd() % 2;
    c->ls[0x30014] = (uint8_t)w;
    c->ls[0x30015] = (uint8_t)r;
    setreg(c, 3, 0x30000);
    const uint32_t src = 0x10000 + (rnd() % 2 ? 16 * (rnd() % 16) : rnd() % 256);
    setreg(c, 5, src);
    setreg(c, 9, rnd() % 4 ? 0x20000 + (rnd() % 2 ? 16 * (rnd() % 16) : rnd() % 256) : src);
}
/* DepthToFuzzy: r4 = three floats a, b, c (any byte offset), r5 = floats */
static void synth_depthfuzzy(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    g_dirty = rnd() % 4 == 0;
    uint32_t w, r;
    pass_prm(c, &w, &r);
    const uint32_t t = 0x31000 + 16 * (rnd() % 16) + (rnd() % 2 ? 0 : 4 * (rnd() % 4));
    const float abc[3] = { (float)((int)(rnd() % 4000) - 2000) / 1000.0f, (float)((int)(rnd() % 2000) - 1000) / 1000.0f,
                           (float)(rnd() % 2000) / 1000.0f };
    for (int k = 0; k < 3; k++) {
        if (g_dirty && rnd() % 3 == 0) be32w(c->ls + t + 4 * k, rfloat());
        else put_float(c, t + 4 * (uint32_t)k, abc[k]);
    }
    setreg(c, 4, t);
    for (uint32_t a = 0x10000; a < 0x20000; a += 4) {
        const float f = (float)((int)(rnd() % 3000) - 1000) / 1000.0f;
        if (g_dirty && rnd() % 3 == 0) be32w(c->ls + a, rfloat());
        else put_float(c, a, f);
    }
    const uint32_t src = 0x10000 + 16 * (rnd() % 16);
    setreg(c, 5, src);
    setreg(c, 9, rnd() % 4 ? 0x20000 + 16 * (rnd() % 16) : src);
}
/* Downsample: r3 = output, r4 = row 0, r5 = stride (row 1 = r4 + r5), r6 = output pixels */
static void synth_down(spu_context* c, uint64_t seed, uint32_t step)
{
    base_state(c, seed);
    const uint32_t nq = 1 + rnd() % 40, in = 32 * nq;
    setreg(c, 3, 0x30000 + 16 * (rnd() % 64));
    setreg(c, 4, 0x10000 + 16 * (rnd() % 64));
    setreg(c, 5, 16 * ((in + 15) / 16 + rnd() % 64));
    setreg(c, 6, step * nq);
    if (rnd() % 2)
        for (uint32_t a = 0x10000; a < 0x30000; a++) c->ls[a] = (rnd() % 3 == 0) ? 0 : (rnd() % 2 ? 255 : c->ls[a]);
}
static void synth_down4(spu_context* c, uint64_t seed) { synth_down(c, seed, 4); }
static void synth_down8(spu_context* c, uint64_t seed) { synth_down(c, seed, 2); }

/* Spu an earlier change: DepthOfField's whole pass @0x4A20. Parameters at 0x30000 (q0 byte 4 = 96, byte 7 = 4; q1 byte 4 = W,
 * byte 5 = R), r5 = source pixels (the pass reads 7 rows and 8 pixels before them), r6 = control words (radius in the
 * top byte; also the unpack's weights), r9 = output; the float buffer 0x6CC0 and the scratch 0x11AC0 are the job's.
 * Radii: all 0 (the level's usual case), a few blurred patches, or any; a few cases with the SPU extended range off. */
extern int g_kz3_spu_xr;
static int s_xr_saved = -1;
static void synth_dofpass(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    if (s_xr_saved < 0) s_xr_saved = g_kz3_spu_xr;
    g_kz3_spu_xr = rnd() % 8 ? s_xr_saved : 0;
    const uint32_t W = rnd() % 8 ? 80 : 16 * (1 + rnd() % 5) + rnd() % 4, R = rnd() % 8 ? 1 + rnd() % 40 : rnd() % 3;
    c->ls[0x30004] = 96;
    c->ls[0x30007] = 4;
    c->ls[0x30014] = (uint8_t)W;
    c->ls[0x30015] = (uint8_t)R;
    setreg(c, 3, 0x30000);
    const uint32_t px = 0x20000 + 2720 + 16 * (rnd() % 16), ctl = 0x28000 + 2720 + 16 * (rnd() % 16);
    setreg(c, 5, px);
    setreg(c, 6, ctl);
    setreg(c, 9, 0x31000 + 16 * (rnd() % 16));
    const int mode = (int)(rnd() % 3);
    for (uint32_t a = 0x28000; a < 0x30000; a += 4) {
        uint32_t r = 0;
        if (mode == 1 && rnd() % 16 == 0) r = rnd() % 32;
        else if (mode == 2) r = rnd() % 4 ? rnd() % 256 : 0;
        c->ls[a] = (uint8_t)r;
    }
    if (mode == 1)   /* a blurred patch: rows of nonzero radius */
        for (uint32_t g = rnd() % 8; g < R && g < 20; g++)
            for (uint32_t j = 0; j < W; j++) c->ls[ctl + 384 * g + 4 * j] = (uint8_t)(1 + rnd() % 24);
}

/* Spu an earlier change: Gfx.Post.Zero's memset @0x5698: r3 = destination (sometimes unaligned: the native code declines),
 * r4 = fill (byte 3), r5 = bytes. */
static void synth_zero(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    setreg(c, 3, 0x20000 + 16 * (rnd() % 64) + (rnd() % 8 ? 0 : rnd() % 16));
    setreg(c, 4, rnd() % 2 ? 0 : rnd());
    setreg(c, 5, rnd() % 8 ? rnd() % 4096 : rnd() % 40);
}

/* Particles.VertexJob's crt0 .bss clear @0x411C (slot 77, an earlier change): r3 = start, r4 = end, r126 = the load offset.
 * Half the cases the game's own (0x1B980-0x288B0, offset 0); the rest random lengths (1 byte to 128 KB), starts off
 * the quadword now and then, offsets that wrap the local store, other lanes of r3/r4 not splatted, and 1 in 32 with
 * start >= end (the native code declines). The cleared range never covers the job's code (0x4000-0x8800): the
 * interpreter's stop is planted at 0x407C. */
static void synth_bss(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    for (int tries = 0; tries < 64; tries++) {
        uint32_t s0 = 0x1B980, e0 = 0x288B0, off = 0;
        if (rnd() % 2) {
            s0 = 0x8800 + 16 * (rnd() % 0x3000) + (rnd() % 8 ? 0 : rnd() % 16);
            e0 = s0 + (rnd() % 4 ? 1 + rnd() % 0x20000 : 1 + rnd() % 64);
            off = rnd() % 4 ? 0 : (rnd() % 2 ? 16 * (rnd() % 0x4000) : rnd());
            if (rnd() % 32 == 0) e0 = s0 - rnd() % 64;
        }
        const uint32_t a0 = (s0 + off) & (SPU_LS_MASK & ~0xFu);
        const uint32_t len = e0 > s0 ? ((e0 - s0 + 15) & ~15u) : 16;
        int hits = 0;
        for (uint32_t k = 0; k < len && !hits; k += 16) {
            const uint32_t a = (a0 + k) & SPU_LS_MASK;
            hits = a >= 0x4000 && a < 0x8800;
        }
        if (hits) continue;
        setreg(c, 3, s0);
        setreg(c, 4, e0);
        setreg(c, 126, off);
        if (rnd() % 4 == 0)
            for (int k = 1; k < 4; k++) {
                c->gpr[3]._u32[k] = rnd();
                c->gpr[4]._u32[k] = rnd();
                c->gpr[126]._u32[k] = rnd();
            }
        return;
    }
    setreg(c, 3, 0x1B980);
    setreg(c, 4, 0x288B0);
    setreg(c, 126, 0);
}

/* Particles.VertexJob's memcpy @0x7F00 (slot 78, an earlier change): r3 = destination, r4 = source, r5 = bytes. Destinations
 * above the job's code and shift table (>= 0x8800); every alignment pair of source and destination, lengths 0-4 KB
 * (a quarter under 48 bytes: the single-quadword merges), sources anywhere in the image or data; 1 in 16 overlapping
 * ranges and 1 in 32 near the end of the local store (both declined: a fallback), 1 in 4 with unsplatted lanes. */
static void synth_vjcopy(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    const uint32_t n = rnd() % 32 == 0 ? 0 : rnd() % 4 == 0 ? rnd() % 48 : rnd() % 4 ? rnd() % 4097 : 16 * (rnd() % 257);
    uint32_t d = 0x8800 + rnd() % 0x30000, s = rnd() % 2 ? 0x4000 + rnd() % 0x4000 : 0x8800 + rnd() % 0x30000;
    if (rnd() % 4 == 0) d &= ~15u;
    if (rnd() % 4 == 0) s &= ~15u;
    if (rnd() % 16 == 0) s = d + (rnd() % 2 ? 1 : -1) * (int32_t)(rnd() % 64);
    if (rnd() % 32 == 0) d = SPU_LS_SIZE - 16 - rnd() % 64;
    setreg(c, 3, d);
    setreg(c, 4, s);
    setreg(c, 5, n);
    if (rnd() % 4 == 0)
        for (int k = 1; k < 4; k++) {
            c->gpr[3]._u32[k] = rnd();
            c->gpr[4]._u32[k] = rnd();
            c->gpr[5]._u32[k] = rnd();
        }
}

/* Spu an earlier change: a gate that sits after a lifted prologue (Gfx.Post.ILR's row loop @0x4E20): the state there is made by
 * running the lifted pass from its entry with a gate that copies the state the first time it is reached (and lets the
 * lifted code go on). Synthetic cases build the pass's entry state; recorded states taken at the pass's entry (round
 * 18's recording build had the gate there) are brought forward the same way. */
static spu_context s_cap, s_pre;
static int s_cap_n;
static int capture_gate(spu_context* c)
{
    if (!s_cap_n++) ctx_copy(&s_cap, c);
    return 0;
}
static int prestate(int slot, uint32_t from)
{
    fn_t f = spu_lookup(from, 0);
    if (!f) return 0;
    ctx_copy(&s_pre, &S);
    s_pre.gpr[0] = spu_splat_u32(SENTINEL);
    s_pre.pc = from;
    s_cap_n = 0;
    g_kz2_native_gate[slot] = capture_gate;
    const int r = run_lifted(&s_pre, f);
    g_kz2_native_gate[slot] = NULL;
    if (r != R_RET || !s_cap_n) return 0;
    ctx_copy(&S, &s_cap);
    return 1;
}
/* Gfx.Post.ILR: the pass's entry state (q0 bytes 4, 7 = source row pixels, bytes per pixel; q1 bytes 4, 5 = width,
 * rows), then forward to @0x4E20. */
static void synth_ilr(spu_context* c, uint64_t seed)
{
    for (int tries = 0; tries < 8; tries++) {
        base_state(c, seed + 0x1000 * (uint64_t)tries);
        const uint32_t W = rnd() % 4 ? 20 * (1 + rnd() % 12) : 1 + rnd() % 240, R = 1 + rnd() % (rnd() % 4 ? 60 : 4);
        c->ls[0x30004] = (uint8_t)(rnd() % 4 ? W : 1 + rnd() % 255);
        c->ls[0x30007] = 4;
        c->ls[0x30014] = (uint8_t)W;
        c->ls[0x30015] = (uint8_t)R;
        setreg(c, 3, 0x30000);
        setreg(c, 5, 0x10000 + 16 * (rnd() % 16));
        setreg(c, 9, 0x20000 + 16 * (rnd() % 16));
        if (rnd() % 2)
            for (uint32_t a = 0x10000; a < 0x20000; a++) c->ls[a] = (rnd() % 3 == 0) ? 0 : (rnd() % 2 ? 255 : c->ls[a]);
        if (prestate(68, 0x4A20)) return;
    }
}

/* Anim.EdgeAnim 0x13100 (slot 75): a random bit stream at 0x20000 + any byte, a packing spec at any
 * byte after 0x31000 (three (s, e, m) fields: fixed point, small floats, wide mantissas, zero widths), the index table
 * at 0x31100 + a multiple of 8 or any even offset (repeats allowed: the store order counts), 48-byte records at 0x24000 + 0/16/32. */
static void synth_ea13100(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    uint32_t spec = rnd() & 3;
    for (int k = 0; k < 3; k++) {
        uint32_t s = rnd() & 1, e, m;
        switch (rnd() % 4) {
        case 0: e = 0; m = rnd() % 32; break;
        case 1: e = 1 + rnd() % 15; m = rnd() % 24; break;
        case 2: e = rnd() % 16; m = rnd() % 32; break;
        default: e = 0; m = 8 + rnd() % 8; break;
        }
        spec |= (s << 9 | e << 5 | m) << (22 - 10 * k);
    }
    /* the table is read 8 bytes a group wrapping inside its quadword: an offset that is not a multiple of 8 (1 case
     * in 4 here) reads other entries or random bytes, so some of those outputs land anywhere and the native code
     * declines them */
    const uint32_t sa = 0x31000 + rnd() % 64, n = 1 + rnd() % 40;
    const uint32_t ta = 0x31100 + (rnd() % 4 ? 8 * (rnd() % 8) : 2 * (rnd() % 32));
    be32w(c->ls + sa, spec);
    for (uint32_t i = 0; i < 4 * ((n + 3) / 4); i++) {
        const uint32_t idx = (rnd() % 8 == 0) ? 0 : rnd() % 64;
        c->ls[ta + 2 * i] = (uint8_t)(idx >> 8);
        c->ls[ta + 2 * i + 1] = (uint8_t)idx;
    }
    setreg(c, 3, 0x20000 + rnd() % 256);
    setreg(c, 4, n);
    setreg(c, 5, 0x24000 + 16 * (rnd() % 3));   /* outside the image (0x4000-0x16230): the interpreter runs its LS */
    setreg(c, 6, ta);
    setreg(c, 7, sa);
    setreg(c, 8, rnd() & 1);
}

/* Anim.EdgeAnim 0x12438 (slot 76): the keyframe sampler. Per element a spec (as 0x13100's: fixed point,
 * small floats, wide mantissas, zero widths; or the game's e = 0, m = 14-15 rotations) in a stream at 0x30000 + any
 * byte; four bitmask bit addresses 4 r20 apart a group (stride 1-128 bits, the game's 99) into random bytes or sparse
 * key masks; frame masks r4-r7 (the first F frames, or random words) and r8-r11 (the frames before r12, or random),
 * per lane or splatted; three streams of random keys (0x8000, 0x28000, 0x2C000 + any byte); r13 a fraction in
 * [0.5, 1), 0, 1 or any bits; rotations or not; the index table as 0x13100's; outputs at 0x24000 + 0/16/32 (+ 48 idx). */
static uint32_t pfx_word(uint32_t nbits, int j)   /* word j of a 128-bit mask of the first nbits bits (bit 31 of word 0 first) */
{
    const int lo = 32 * j;
    if ((int)nbits <= lo) return 0;
    if ((int)nbits >= lo + 32) return 0xFFFFFFFFu;
    return ~(0xFFFFFFFFu >> (nbits - lo));
}
static void synth_ea12438(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    const uint32_t n = 1 + rnd() % 40, iters = (n + 3) / 4;
    const int game = rnd() % 3 == 0;
    const uint32_t sa = 0x30000 + rnd() % 64;
    for (uint32_t i = 0; i < 4 * iters; i++) {
        uint32_t spec = rnd() & 3;
        for (int k = 0; k < 3; k++) {
            uint32_t s = rnd() & 1, e, m;
            if (game) { s = 1; e = 0; m = 14 + rnd() % 2; }
            else switch (rnd() % 4) {
                case 0: e = 0; m = rnd() % 32; break;
                case 1: e = 1 + rnd() % 15; m = rnd() % 24; break;
                case 2: e = rnd() % 16; m = rnd() % 32; break;
                default: e = 0; m = 8 + rnd() % 8; break;
            }
            spec |= (s << 9 | e << 5 | m) << (22 - 10 * k);
        }
        be32w(c->ls + sa + 4 * i, spec);
    }
    const uint32_t ta = 0x31100 + (rnd() % 4 ? 8 * (rnd() % 8) : 2 * (rnd() % 32));
    /* small indices around the table too: a table at an offset that is not a multiple of 8 reads its neighbours
     * (quadword-wrapped), and a wild index would store into the job image, which the interpreter then executes */
    for (uint32_t a = 0x31100; a < 0x31100 + 2 * 4 * iters + 128; a += 2) { c->ls[a] = 0; c->ls[a + 1] = rnd() % 64; }
    for (uint32_t i = 0; i < 4 * iters; i++) {
        const uint32_t idx = (rnd() % 8 == 0) ? 0 : rnd() % 64;
        c->ls[ta + 2 * i] = (uint8_t)(idx >> 8);
        c->ls[ta + 2 * i + 1] = (uint8_t)idx;
    }
    const uint32_t stride = rnd() % 4 ? 99 : 1 + rnd() % 128;
    const uint32_t mb = 0x20000 + rnd() % 64;
    if (rnd() % 2)   /* sparse key masks (a few keys per element) instead of random bytes */
        for (uint32_t a = mb; a < mb + (4 * iters * stride + 7) / 8 + 64 && a < 0x24000; a++)
            c->ls[a] = rnd() % 6 == 0 ? (uint8_t)(1u << (rnd() % 8)) : 0;
    const int lanes = rnd() % 4 == 0;   /* per-lane masks and frame indices (the game splats them) */
    const uint32_t F = 1 + rnd() % 128;
    for (int k = 0; k < 4; k++) {
        const uint32_t Fk = lanes ? 1 + rnd() % 128 : F, fr = rnd() % (Fk + 1);
        const int rnd4 = rnd() % 8 == 0, rnd8 = rnd() % 8 == 0;
        for (int j = 0; j < 4; j++) {
            c->gpr[4 + j]._u32[k] = rnd4 ? rnd() : pfx_word(Fk, j);
            c->gpr[8 + j]._u32[k] = rnd8 ? rnd() : pfx_word(fr, j);
        }
        c->gpr[12]._u32[k] = rnd() % 16 == 0 ? rnd() : fr;
        c->gpr[3]._u32[k] = 8 * mb + (rnd() % 8) + (uint32_t)k * stride;
        c->gpr[13]._u32[k] = rnd() % 8 == 0 ? rnd() : 0x3F000000u | (rnd() & 0x7FFFFFu);
    }
    if (!lanes)
        for (int r = 4; r <= 13; r++)
            if (r != 3 && (r != 12 || rnd() % 2)) c->gpr[r] = spu_splat_u32(c->gpr[r]._u32[0]);
    if (rnd() % 4 == 0) c->gpr[13] = spu_splat_u32(rnd() % 2 ? 0x3F800000u : 0);
    setreg(c, 14, 0x8000 + rnd() % 4096);
    setreg(c, 15, 0x28000 + rnd() % 256);
    setreg(c, 16, 0x2C000 + rnd() % 256);
    setreg(c, 17, n);
    setreg(c, 18, 0x24000 + 16 * (rnd() % 3));
    setreg(c, 19, ta);
    c->gpr[20]._u32[0] = stride;
    setreg(c, 21, sa);
    c->gpr[22]._u32[0] = rnd() % 3 ? 1 : (rnd() & 0xE);
}

/* Particles.VertexJob 0x50F8 (slot 79): the vertex emitter. The pointer at LS 0x84C0 (to a block at
 * 0x2A000 + 16 k: the relight byte at +0x9EC, the mode word at +0x9F0, the falloff word +0x9F4, the hemisphere word
 * +0xA08), the light pointer at 0x84B0 (two quadwords at +0x30, +0x40), the matrix and scales at 0x8800-0x8890, the
 * coefficients at 0x1BA00-0x1BB60, the 8x8x8 grid at 0x19B00, the descriptor (format bits: every combination of
 * 0x200, 0x20, 0x10, 0x400 and format & 7), the 4-byte attribute, the ring state at 0x27B80 (index 0/1, a fill
 * offset near the end of the buffer a third of the time: a put and a tag wait, the vertex split over both buffers),
 * floats in their ranges or (a quarter of the trials) with zero, denormal, exponent-255 and negative words; half the
 * trials with the game's stack pointer (0x1F630, just below the ring) and r10 in the caller's frame. 1 in 32 a stack
 * pointer or a ring state the native code declines. */
static uint32_t fbits_in(float lo, float hi)
{
    float f = lo + (hi - lo) * (float)(rnd() % 100001) / 100000.0f;
    uint32_t u;
    memcpy(&u, &f, 4);
    return g_dirty && rnd() % 6 == 0 ? rfloat() : u;
}
static void fq(spu_context* c, int r, float lo, float hi)
{
    for (int k = 0; k < 4; k++) c->gpr[r]._u32[k] = fbits_in(lo, hi);
}
static void fls(spu_context* c, uint32_t a, uint32_t n, float lo, float hi)
{
    for (uint32_t i = 0; i < n; i += 4) be32w(c->ls + a + i, fbits_in(lo, hi));
}
static void synth_vjvert(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    g_dirty = rnd() % 4 == 0;
    const uint32_t P = 0x2A000 + 16 * (rnd() % 64), Q = 0x2B000 + 16 * (rnd() % 16);
    be32w(c->ls + 0x84C0, P);
    be32w(c->ls + 0x84B0, Q);
    c->ls[P + 0x9EC] = rnd() % 4 == 0 ? 0 : (uint8_t)(1 + rnd() % 255);   /* relight or not */
    const uint32_t mode = (uint32_t[]){0, 1, 2, 0, 1, 2, 3, 0xFFFFFFFFu, 2, 2}[rnd() % 10];
    be32w(c->ls + P + 0x9F0, mode);
    be32w(c->ls + P + 0x9F4, fbits_in(0.0f, 2.0f));
    be32w(c->ls + P + 0xA08, fbits_in(-1.0f, 1.0f));
    fls(c, Q + 0x30, 32, -20.0f, 20.0f);
    fls(c, 0x8800, 0x30, -1.0f, 1.0f);
    fls(c, 0x8880, 0x20, -2.0f, 2.0f);
    fls(c, 0x1BA00, 0x90, -1.0f, 1.0f);
    fls(c, 0x1BB40, 0x10, -1.0f, 0.0f);   /* the grid origin and scale: indices below 0, 0-7 and above 7 */
    fls(c, 0x1BB50, 0x10, 1.0f, 3.0f);
    fls(c, 0x1BB60, 0x10, -2.0f, 2.0f);
    fls(c, 0x19B00, 0x1000, 0.0f, 1.5f);   /* above 1 too: 1 - lerp below 0 (@0x5A84) */
    const uint32_t desc = 0x2C000 + 16 * (rnd() % 64);
    be32w(c->ls + desc + 8, (rnd() & 0x630u) | (rnd() % 8) | (rnd() % 8 == 0 ? rnd() & ~0x637u : 0));
    const uint32_t b = rnd() & 1, f = rnd() % 3 == 0 ? 0x4000 - rnd() % 24 : 16 * (rnd() % 1024) + 2 * (rnd() % 8);
    be32w(c->ls + 0x27B80, b);
    be32w(c->ls + 0x27B84, f);
    be32w(c->ls + 0x27B88, 0x30000000u + 0x4000u * (rnd() % 256));
    be32w(c->ls + 0x27B8C, rnd() % 32);
    be32w(c->ls + 0x27B90, rnd() % 32);
    setreg(c, 3, desc);
    fq(c, 6, -0.5f, 3.0f);
    fq(c, 7, -1.0f, 1.0f);
    fq(c, 8, -0.5f, 1.5f);
    fq(c, 9, -0.1f, 1.2f);
    setreg(c, 10, 0x2D000 + rnd() % 256);
    fq(c, 11, -1.0f, 1.0f);
    if (rnd() % 2) {   /* the game's stack: just below the ring, r10 in the caller's frame */
        c->gpr[1] = spu_splat_u32(0x1F630);
        c->gpr[1]._u32[1] = rnd();
        if (rnd() % 2) setreg(c, 10, 0x1F660 + 4 * (rnd() % 8));
    }
    if (rnd() % 32 == 0) {   /* the declined cases */
        switch (rnd() % 4) {
        case 0: c->gpr[1]._u32[0] += 4; break;
        case 3: c->gpr[1]._u32[0] = 0x1FB80 + 16 * (rnd() % 64); break;   /* the frame in the ring */
        case 1: be32w(c->ls + 0x27B80, 2 + rnd() % 4); break;
        default: be32w(c->ls + 0x27B84, 0x4001 + rnd() % 64); break;
        }
    }
}

/* Anim.Skinning 0x54C0 (slot 80): the skinning loop. The game's layout (positions at 0x6100, normals
 * at 0x7100, just past the image) or streams anywhere; records (20 bytes, the window at r6 + 6) with random weight,
 * bone and byte-vector bytes (bones 0-255, or few bones), two palettes of 256 matrices (rows of floats, translation
 * row larger; lane 3 0/1 or random), counts 1-200; odd floats a quarter of the trials (NaN, infinity, denormals
 * through every multiply); the zero vector for the unit steps now and then (frsqest of 0). 1 in 16 declined on
 * purpose (an overlap with the output, an unaligned output). */
static void synth_skin(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    g_dirty = rnd() % 4 == 0;
    const uint32_t n = 1 + rnd() % 200;
    const int game = rnd() % 2;
    const uint32_t r4 = game ? 0x6100 : 0x8000 + 16 * (rnd() % 64), r5 = game ? 0x7100 : 0x9000 + 16 * (rnd() % 64);
    const uint32_t r6 = 0xA000 + rnd() % 256, out = 0xC000 + 16 * (rnd() % 64);
    const uint32_t m7 = 0x30000 + 16 * (rnd() % 16), m8 = 0x35000 + 16 * (rnd() % 16);
    const int few = rnd() % 3 == 0;
    for (uint32_t k = 0; k <= n; k++) {
        uint8_t* w = c->ls + r6 + 6 + 20 * k;
        for (int i = 0; i < 20; i++) w[i] = (uint8_t)rnd();
        if (rnd() % 4 == 0) { w[0] = 255; w[1] = 0; }
        if (rnd() % 8 == 0) { w[0] = (uint8_t)(128 + rnd() % 128); w[1] = (uint8_t)(rnd() % 128); }
        if (few) for (int j = 5; j < 8; j++) w[j] = (uint8_t)(rnd() % 4);
        if (rnd() % 16 == 0) w[8] = w[9] = w[10] = 0;
        if (rnd() % 16 == 0) w[11] = w[12] = w[13] = 0x80;
        fls(c, r4 + 16 * k, 16, -50.0f, 50.0f);
        fls(c, r5 + 16 * k, 16, -1.0f, 1.0f);
        if (rnd() % 16 == 0) memset(c->ls + r5 + 16 * k, 0, 12);
    }
    for (int pal = 0; pal < 2; pal++) {
        const uint32_t b = pal ? m8 : m7;
        for (uint32_t j = 0; j < 256; j++) {
            fls(c, b + 64 * j, 48, -1.0f, 1.0f);
            fls(c, b + 64 * j + 48, 16, -100.0f, 100.0f);
            if (rnd() % 2)
                for (int r = 0; r < 4; r++) be32w(c->ls + b + 64 * j + 16 * r + 12, r == 3 ? 0x3F800000u : 0);
        }
    }
    if (rnd() % 4 == 0) {   /* random lane-3 words (NaN, infinity, huge; the fast form ignores lane 3) */
        for (uint32_t k = 0; k <= n; k++) {
            be32w(c->ls + r4 + 16 * k + 12, rnd());
            be32w(c->ls + r5 + 16 * k + 12, rnd() % 2 ? rnd() : 0x7F800000u | rnd());
        }
        for (int pal = 0; pal < 2; pal++)
            for (uint32_t j = 0; j < 256 * 4; j++)
                if (rnd() % 2) be32w(c->ls + (pal ? m8 : m7) + 16 * j + 12, rnd() % 2 ? rnd() : 0x7F800000u | rnd());
    }
    setreg(c, 3, out);
    setreg(c, 4, r4);
    setreg(c, 5, r5);
    setreg(c, 6, r6);
    setreg(c, 7, m7 + (rnd() % 4 ? 0 : rnd() % 16));
    setreg(c, 8, m8);
    setreg(c, 9, n);
    if (rnd() % 16 == 0) {   /* the declined cases */
        switch (rnd() % 4) {
        case 0: setreg(c, 3, m7 + 64 * (rnd() % 200)); break;   /* the output over a palette */
        case 1: setreg(c, 4, out + 16 * (rnd() % 4)); break;   /* the positions under the output */
        case 2: setreg(c, 3, out + 4); break;
        default: setreg(c, 3, r6 - 16); break;   /* over the records */
        }
    }
}


/* Physics.Raycast's MOPP ray machine at its loop head 0xCA40 (slot 82, a computed continuation). A random
 * program of MOPP opcodes (mostly the ones the native code takes: rescales, jumps, splits, single splits, splits
 * with jumps, double cuts of both widths, chunk jumps; now and then a diagonal split, a terminal or a return, where
 * it hands over) at a random 16-byte-aligned code pointer; children and jumps a few bytes ahead; the ray from/to in
 * MOPP space mostly in [0, 256) (equal ends, ends on a plane, negative ones now and then; odd floats -- huge,
 * denormal, exponent 255 -- a quarter of the trials); the scale state and the query's 24-bit scale; a 4-way code
 * cache at [0x11AD0] whose tags hold half the chunks the program jumps to (hits continue at a line of random code).
 * 1 in 32 trials misaligns r1 (declined on purpose). */
static uint32_t mopp_float(int odd)
{
    union { float f; uint32_t u; } x;
    const uint32_t k = rnd() % 16;
    if (odd && k < 4) {
        static const uint32_t w[4] = { 0x7F800000u, 0x00012345u, 0x7FFFFFFFu, 0x80000000u };
        return w[k] ^ (k < 3 && (rnd() & 1) ? 0x80000000u : 0);
    }
    if (k < 3) x.f = (float)(rnd() % 256);   /* on a plane */
    else if (k < 4) x.f = -(float)(rnd() % 64) - (float)(rnd() % 1000) / 1000.0f;
    else x.f = (float)(rnd() % 256000) / 1000.0f;
    return x.u;
}
/* rf/rt: the ray's ends as the program goes (rescales applied), so that most splits are not crossed and most cuts
 * keep the ray: children follow each other (offset 0) and the run goes on */
static uint8_t mopp_clamp(float v) { return v < 0 ? 0 : v > 255 ? 255 : (uint8_t)v; }
static uint32_t mopp_prog(uint8_t* ls, uint32_t a, int nops, const uint16_t* chunks, int nch, float* rf, float* rt)
{
    for (int i = 0; i < nops; i++) {
        const uint32_t k = rnd() % 100, ax = rnd() % 3, near = rnd() % 4 != 0;
        const float lo = rf[ax] < rt[ax] ? rf[ax] : rt[ax], hi = rf[ax] < rt[ax] ? rt[ax] : rf[ax];
        uint8_t b[8];
        int n;
        for (int j = 0; j < 8; j++) b[j] = (uint8_t)rnd();
        if (k < 10) {                                                                  /* rescale */
            b[0] = 1 + rnd() % 4;
            for (int j = 0; j < 3; j++) {
                const float m = rf[j] < rt[j] ? rf[j] : rt[j];
                if (near) b[1 + j] = mopp_clamp(m);
                const float s = (float)(1 << b[0]);
                rf[j] = (rf[j] - b[1 + j]) * s;
                rt[j] = (rt[j] - b[1 + j]) * s;
            }
            n = 4;
        } else if (k < 14) { b[0] = 5; b[1] %= 4; n = 2; }                             /* jumps, a little ahead */
        else if (k < 16) { b[0] = 6; b[1] = 0; b[2] %= 4; n = 3; }
        else if (k < 18) { b[0] = 7; b[1] = 0; b[2] = 0; b[3] %= 4; n = 4; }
        else if (k < 21) { b[0] = 12; const uint16_t c = chunks[rnd() % nch]; b[1] = (uint8_t)(c >> 8); b[2] = (uint8_t)c; n = 3; }
        else if (k < 23) { b[0] = 13; n = 5; }
        else if (k < 38) {                                                             /* split: b1 high, b2 low */
            b[0] = 16 + ax;
            if (near) {
                if (rnd() & 1) { b[2] = mopp_clamp(hi + 1 + rnd() % 3); b[1] = mopp_clamp(b[2] + rnd() % 4); }
                else { b[1] = mopp_clamp(lo - 1 - rnd() % 3); b[2] = b[1]; }
            }
            b[3] = rnd() % 4 ? 0 : b[3] % 4;
            n = 4;
        } else if (k < 53) {                                                           /* single split */
            b[0] = 32 + ax;
            if (near) b[1] = rnd() & 1 ? mopp_clamp(hi + 1 + rnd() % 3) : mopp_clamp(lo - 2 - rnd() % 3);
            b[2] = rnd() % 4 ? 0 : b[2] % 4;
            n = 3;
        } else if (k < 60) {                                                           /* split with jumps */
            b[0] = 35 + ax;
            if (near) {
                if (rnd() & 1) { b[2] = mopp_clamp(hi + 1 + rnd() % 3); b[1] = b[2]; }
                else { b[1] = mopp_clamp(lo - 1 - rnd() % 3); b[2] = b[1]; }
            }
            b[3] = 0; b[4] %= 4; b[5] = 0; b[6] %= 4;
            n = 7;
        } else if (k < 75) {                                                           /* double cut */
            b[0] = 38 + ax;
            if (near) { b[1] = mopp_clamp(lo - rnd() % 3); b[2] = mopp_clamp(hi + 1 + rnd() % 3); }
            else if (b[1] > b[2]) { const uint8_t s = b[1]; b[1] = b[2]; b[2] = s; }
            n = 3;
        } else if (k < 83) {                                                           /* double cut 24 (x 1/256) */
            b[0] = 41 + ax;
            uint32_t p0 = (uint32_t)(lo < 0 ? 0 : lo * 256.0f), p1 = (uint32_t)(hi < 0 ? 0 : hi * 256.0f) + 256;
            if (near) p0 = p0 > 300 ? p0 - rnd() % 300 : 0;
            else p0 = rnd() % 0x10000, p1 = p0 + rnd() % 0x10000;
            b[1] = (uint8_t)(p0 >> 16); b[2] = (uint8_t)(p0 >> 8); b[3] = (uint8_t)p0;
            b[4] = (uint8_t)(p1 >> 16); b[5] = (uint8_t)(p1 >> 8); b[6] = (uint8_t)p1;
            n = 7;
        } else if (k < 86) { b[0] = 19 + rnd() % 10; n = 4; }                          /* hands over */
        else if (k < 88) { b[0] = 48 + rnd() % 32; n = 1; }
        else if (k < 89) { b[0] = 0; n = 1; }
        else if (k < 90) { b[0] = 96 + rnd() % 12; n = 3; }
        else { b[0] = 13; n = 5; }
        for (int j = 0; j < n; j++) ls[(a++) & SPU_LS_MASK] = b[j];
    }
    return a;
}
static void synth_mopp(spu_context* c, uint64_t seed)
{
    base_state(c, seed);
    const int odd = (rnd() % 4) == 0;
    uint8_t* ls = c->ls;
    uint16_t chunks[8];
    for (int i = 0; i < 8; i++) chunks[i] = (uint16_t)(rnd() % 4096);
    const uint32_t code = 0x30000u + 16u * (rnd() % 64), ray = 0x31000u, st = 0x31100u, q = 0x31200u;
    const uint32_t cache = 0x31400u, tags = 0x31500u, lines = 0x32000u, ea0 = 0x00400000u + 512u * (rnd() % 64);
    float rf[3], rt[3];
    const int longray = rnd() % 4 == 0;
    for (int i = 0; i < 3; i++) {
        rf[i] = (float)(rnd() % 250000) / 1000.0f;
        rt[i] = longray ? (float)(rnd() % 256000) / 1000.0f : rf[i] + (float)((int)(rnd() % 6000) - 3000) / 1000.0f;
        if (rnd() % 8 == 0) rt[i] = rf[i];   /* equal ends */
        union { float f; uint32_t u; } x;
        x.f = rf[i]; be32w(ls + ray + 4 * i, odd && rnd() % 6 == 0 ? mopp_float(1) : x.u);
        x.f = rt[i]; be32w(ls + ray + 16 + 4 * i, odd && rnd() % 6 == 0 ? mopp_float(1) : x.u);
    }
    be32w(ls + ray + 12, rnd() % 4 ? 0 : mopp_float(odd));
    be32w(ls + ray + 28, rnd() % 4 ? 0 : mopp_float(odd));
    float tf[3] = { rf[0], rf[1], rf[2] }, tt[3] = { rt[0], rt[1], rt[2] };
    mopp_prog(ls, code, 40, chunks, 8, tf, tt);
    for (int i = 0; i < 4; i++) be32w(ls + st + 4 * i, rnd() % 4 ? 0 : mopp_float(odd));   /* the offset */
    be32w(ls + st + 16, rnd() % 8);   /* the accumulated shift */
    be32w(ls + st + 20, rnd() % 4 ? 0x3F800000u : mopp_float(odd));   /* the scale */
    be32w(ls + st + 24, rnd());
    be32w(ls + st + 28, rnd());
    be32w(ls + q + 0x40, rnd() % 4 ? 0x3B800000u : 0x3B800000u + (rnd() % 0x100000));   /* 1/256 */
    be32w(ls + q + 0xF0, ea0);
    be32w(ls + 0x11AD0, cache);
    for (int i = 0; i < 4; i++) {
        be32w(ls + cache + 0x20 + 4 * i, 0xC0);
        be32w(ls + cache + 0x50 + 4 * i, tags);
    }
    for (int s = 0; s < 4; s++)
        for (int w = 0; w < 4; w++) {
            const uint32_t line = lines + 512u * (4u * s + w);
            be32w(ls + tags + 0x40 * s + 4 * w, line);
            be32w(ls + tags + 0x40 * s + 0x10 + 4 * w, rnd() % 4);   /* a tag that matches nothing */
            be32w(ls + tags + 0x40 * s + 0x20 + 4 * w, rnd() % 16);
            float lf[3] = { rf[0], rf[1], rf[2] }, lt[3] = { rt[0], rt[1], rt[2] };
            mopp_prog(ls, line, 24, chunks, 8, lf, lt);
        }
    for (int i = 0; i < 4; i++) {   /* half the program's chunks are in the cache, in their set */
        const uint32_t ea = ea0 + 512u * chunks[2 * i];
        const uint32_t set = (ea >> 3) & 0xC0, way = rnd() % 4;
        be32w(ls + tags + set + 0x10 + 4 * way, ea);
    }
    setreg(c, 80, code);
    for (int k = 1; k < 4; k++) c->gpr[80]._u32[k] = rnd();   /* the code pointer's other lanes, as the VM's adds leave them */
    setreg(c, 86, ray);
    setreg(c, 89, st);
    setreg(c, 91, q);
    setreg(c, 93, rnd() % 4096);
    setreg(c, 94, 0xCA6C);
    for (int k = 0; k < 4; k++) {   /* lqr r96, 0x10EF0 (the prologue's): the cache's LRU step */
        const uint8_t* w = ls + 0x10EF0 + 4 * k;
        c->gpr[96]._u32[k] = (uint32_t)w[0] << 24 | (uint32_t)w[1] << 16 | (uint32_t)w[2] << 8 | w[3];
    }
    if (rnd() % 32 == 0) setreg(c, 1, 0x3F008);
}

static const struct {
    const char* kind;
    void (*synth)(spu_context*, uint64_t);
} kernels[] = {
    {"dof_gather", synth_dof_gather}, {"dof_unpack", synth_dof_unpack}, {"blend", synth_blend},
    {"addb", synth_addb},             {"addh", synth_addh},             {"upsample4", synth_up4},
    {"upsample8", synth_up8},          {"vblur4", synth_vblur4},         {"vblur8", synth_vblur8},
    {"hblur4", synth_hblur4},         {"hblur8", synth_hblur8},         {"bloom", synth_bloom},
    {"grain", synth_grain},           {"modulate", synth_modulate},     {"bloomint", synth_bloomint},
    {"vignette", synth_vignette},     {"depthfuzzy", synth_depthfuzzy}, {"down4", synth_down4},
    {"down8", synth_down8},           {"dofpass", synth_dofpass},
    {"zero", synth_zero},             {"ilr", synth_ilr},
    {"ea_13100", synth_ea13100},      {"ea_12438", synth_ea12438},
    {"bss_clear", synth_bss},         {"vj_memcpy", synth_vjcopy},
    {"vj_vertex", synth_vjvert},     {"sk_skin", synth_skin},
    {"vj_light", synth_vjvert},   /* slot 81, the emitter with the SSE relight */
    {"mopp_vm", synth_mopp},      /* slot 82, the MOPP ray machine's loop head (a computed continuation) */
};

static const char* g_image;   /* the image under test (the .bin's base name) */

/* ---- one case ---- */
static long n_case, n_match, n_mis, n_fb, n_imis, n_bad, n_puts;

/* gates whose r3 is a result (VertexJob's vertex emitter leaves its last memcpy's destination there, as
 * the SPU code does) */
static int kind_r3(const kz2_native_entry* e)
{
    return e->kind && (!strcmp(e->kind, "vj_vertex") || !strcmp(e->kind, "vj_light"));   /* slots 79, 81 */
}

/* registers a computed-continuation gate does not keep: dead at its loop head on every path
 * (tools/spu/vm_live.py; native_raycast.c's header). Counted with the scratch registers, not compared. */
static int kind_dead(const kz2_native_entry* e, int r)
{
    if (!e->kind || strcmp(e->kind, "mopp_vm")) return 0;
    if (r <= 9 || r == 14 || r == 80 || r == 86 || r == 89 || r == 91 || r == 93 || r == 94 || r == 95 || r == 96)
        return 0;
    return r < 98;
}

/* HARNESS_MFC_MUTATE=ea|data|tag|drop|order (the harness's own test, test_native_vjvert.sh): change the native side's
 * log after its run, so the compare must catch it. */
static void mfc_mutate(hmfc_log* l)
{
    static const char* m = (const char*)1;
    if (m == (const char*)1) m = getenv("HARNESS_MFC_MUTATE");
    if (!m || !*m || !l->n || l->overflow) return;
    for (int i = 0; i < l->n; i++) {
        hmfc_ev* e = &l->ev[i];
        if (e->ch != HMFC_Cmd || e->rd) continue;
        if (!strcmp(m, "ea")) e->eal += 16;
        else if (!strcmp(m, "tag")) e->tag ^= 1;
        else if (!strcmp(m, "data") && e->data && (e->size & 0x7FFF)) e->data[(e->size & 0x7FFF) - 1] ^= 0x01;
        else if (!strcmp(m, "drop")) { free(e->data); memmove(e, e + 1, (size_t)(l->n - i - 1) * sizeof *e); l->n--; }
        else if (!strcmp(m, "order") && i > 0) { hmfc_ev t = l->ev[i - 1]; l->ev[i - 1] = *e; *e = t; }
        return;
    }
}
static uint64_t t_lift, t_nat, b_lift, b_nat;
static int do_interp;

static void one(const char* name, int slot, uint32_t entry)
{
    fn_t lf = spu_lookup(entry, 0);
    const kz2_native_entry* e = kz2_native_find(slot);
    n_case++;
    if (!lf || !e) {
        printf("C %s no lifted or native function for slot %d 0x%05X\n", name, slot, entry);
        n_bad++;
        return;
    }
    if (e->addr != entry || (g_image && strcmp(e->image, g_image))) {
        printf("C %s slot %d is %s 0x%05X in the native table, not %s 0x%05X\n", name, slot, e->image, e->addr,
               g_image ? g_image : "?", entry);
        n_bad++;
        return;
    }
    S.gpr[0] = spu_splat_u32(SENTINEL);
    S.pc = entry;
    g_pc_mode = e->cont == KZ2_NATIVE_CONT_PC;
    g_stop_fn = e->cont && !g_pc_mode ? spu_lookup(e->cont, 0) : NULL;
    g_end = e->cont && !g_pc_mode ? e->cont : SENTINEL;
    if (e->cont && !g_pc_mode && !g_stop_fn) { printf("C %s no lifted function at the continue address 0x%05X\n", name, e->cont); n_bad++; return; }
    if (S.ls != S.ls_store) { printf("C %s state LS not in its context\n", name); n_bad++; return; }
    ctx_copy(&A, &S);
    ctx_copy(&B, &S);
    hmfc_reset(&LA);
    hmfc_reset(&LB);
    uint64_t t0, t1, t2;
    int ra, nb;
    if (g_pc_mode) {   /* the native side first, for its exit */
        g_kz2_native_heads = 0;
        const uint64_t n0 = now_ns();
        nb = kz2_native_run(&B, e);
        const uint64_t tn = now_ns() - n0;
        if (!nb) {
            printf("C %s fallback (the native code declined: lifted runs)\n", name);
            n_fb++;
            return;
        }
        g_end = B.pc & SPU_LS_MASK;
        g_pc_head = entry;
        g_heads_want = g_kz2_native_heads;
        static int pcm = -1;   /* HARNESS_PC_MUTATE=1 (the harness's own test): stop the lifted run one head late */
        if (pcm < 0) pcm = getenv("HARNESS_PC_MUTATE") && atoi(getenv("HARNESS_PC_MUTATE"));
        g_heads_want += (unsigned)pcm;
        if (!spu_lookup(g_end, 0)) { printf("C %s MISMATCH no lifted function at the native exit 0x%05X\n", name, g_end); n_mis++; return; }
        t0 = now_ns();
        ra = run_lifted(&A, lf);
        t1 = now_ns();
        t2 = t1 + tn;   /* t1 - t0 the lifted run, t2 - t1 the native one */
    } else {
        t0 = now_ns();
        ra = run_lifted(&A, lf);
        t1 = now_ns();
        nb = kz2_native_run(&B, e);
        t2 = now_ns();
    }
    if (ra != R_RET) {
        printf("C %s lifted did not return (%d)\n", name, ra);
        n_bad++;
        return;
    }
    if (!nb) {
        printf("C %s fallback (the native code declined: lifted runs)\n", name);
        n_fb++;
        return;
    }
    if (e->cont && !g_pc_mode) B.pc = e->cont;   /* the gate line's SPU_HOP (a computed continuation set B.pc itself) */
    t_lift += t1 - t0;
    t_nat += t2 - t1;
    char diff[200] = "";
    int bad = 0;
    for (uint32_t a = 0; a < SPU_LS_SIZE && !bad; a++)
        if (A.ls[a] != B.ls[a]) {
            bad = 1;
            uint32_t q = a & ~15u;
            snprintf(diff, sizeof diff, "LS 0x%05X lifted %08X %08X %08X %08X native %08X %08X %08X %08X", a,
                     A.ls[q] << 24 | A.ls[q + 1] << 16 | A.ls[q + 2] << 8 | A.ls[q + 3],
                     A.ls[q + 4] << 24 | A.ls[q + 5] << 16 | A.ls[q + 6] << 8 | A.ls[q + 7],
                     A.ls[q + 8] << 24 | A.ls[q + 9] << 16 | A.ls[q + 10] << 8 | A.ls[q + 11],
                     A.ls[q + 12] << 24 | A.ls[q + 13] << 16 | A.ls[q + 14] << 8 | A.ls[q + 15],
                     B.ls[q] << 24 | B.ls[q + 1] << 16 | B.ls[q + 2] << 8 | B.ls[q + 3],
                     B.ls[q + 4] << 24 | B.ls[q + 5] << 16 | B.ls[q + 6] << 8 | B.ls[q + 7],
                     B.ls[q + 8] << 24 | B.ls[q + 9] << 16 | B.ls[q + 10] << 8 | B.ls[q + 11],
                     B.ls[q + 12] << 24 | B.ls[q + 13] << 16 | B.ls[q + 14] << 8 | B.ls[q + 15]);
        }
    const int keep[] = {0, 1};
    for (unsigned i = 0; i < 2 && !bad; i++)
        if (memcmp(&A.gpr[keep[i]], &B.gpr[keep[i]], 16)) {
            bad = 1;
            snprintf(diff, sizeof diff, "r%d", keep[i]);
        }
    for (int r = e->cont ? 2 : 80; r < 128 && !bad; r++)   /* a "continue at" gate: every register */
        if (!kind_dead(e, r) && memcmp(&A.gpr[r], &B.gpr[r], 16)) {
            bad = 1;
            snprintf(diff, sizeof diff, "r%d", r);
        }
    if (!bad && kind_r3(e) && memcmp(&A.gpr[3], &B.gpr[3], 16)) {   /* a gate that returns r3 */
        bad = 1;
        snprintf(diff, sizeof diff, "r3 lifted %08X %08X %08X %08X native %08X %08X %08X %08X", A.gpr[3]._u32[0],
                 A.gpr[3]._u32[1], A.gpr[3]._u32[2], A.gpr[3]._u32[3], B.gpr[3]._u32[0], B.gpr[3]._u32[1],
                 B.gpr[3]._u32[2], B.gpr[3]._u32[3]);
    }
    /* the MFC commands (harness_mfc.h) and the interrupt enable they toggle (bid/bie) */
    mfc_mutate(&LB);
    if (!bad && hmfc_compare(&LA, &LB, diff, sizeof diff)) bad = 1;
    if (!bad && A.int_enable != B.int_enable) {
        bad = 1;
        snprintf(diff, sizeof diff, "int_enable lifted %u native %u", A.int_enable, B.int_enable);
    }
    int scratch = 0;
    for (int r = 2; r < 128; r++) scratch += (r < 80 || kind_dead(e, r)) && memcmp(&A.gpr[r], &B.gpr[r], 16) != 0;
    if ((A.pc & SPU_LS_MASK) != g_end || (e->cont && (B.pc & SPU_LS_MASK) != g_end)) {
        bad = 1;
        snprintf(diff, sizeof diff, "pc lifted 0x%05X native 0x%05X", A.pc, B.pc);
    }
    int ib = 0;
    if (do_interp && !g_pc_mode) {   /* not for a computed continuation: a stop planted at its exit would end the
                                     * interpreter at an earlier pass through that handler */
        ctx_copy(&C, &S);
        hmfc_reset(&LC);
        C.ls[g_end] = 0; C.ls[g_end + 1] = 0; C.ls[g_end + 2] = 0x3F; C.ls[g_end + 3] = 0xFF;
        memcpy(A.ls + g_end, C.ls + g_end, 4);   /* the stop the interpreter needs (not in the lifted run) */
        int rc = run_interp(&C, entry);
        if (rc != R_RET) {
            ib = 1;
            if (!diff[0]) snprintf(diff, sizeof diff, "interp did not return (%d, pc 0x%05X)", rc, C.pc);
        }
        for (uint32_t a = 0; a < SPU_LS_SIZE && !ib; a++)
            if (A.ls[a] != C.ls[a]) {   /* say where (an interpreter-only difference is a finding) */
                ib = 1;
                if (!diff[0]) snprintf(diff, sizeof diff, "interp LS 0x%05X lifted %02X interp %02X", a, A.ls[a], C.ls[a]);
            }
        for (int r = 0; r < 128 && !ib; r++)
            if (r != 0 && memcmp(&A.gpr[r], &C.gpr[r], 16)) {
                ib = 1;
                if (!diff[0])
                    snprintf(diff, sizeof diff, "interp r%d lifted %08X %08X %08X %08X interp %08X %08X %08X %08X", r,
                             A.gpr[r]._u32[0], A.gpr[r]._u32[1], A.gpr[r]._u32[2], A.gpr[r]._u32[3],
                             C.gpr[r]._u32[0], C.gpr[r]._u32[1], C.gpr[r]._u32[2], C.gpr[r]._u32[3]);
            }
        /* the interpreter's MFC log too; not its int_enable: spu_interp.c ignores the E/D bits of the bi
         * family (bie/bid leave int_enable as it was; the lifted code sets it), an interpreter gap (spu report) */
        if (!ib && hmfc_compare(&LA, &LC, diff[0] ? (char[200]){0} : diff, 200)) ib = 1;
        n_imis += ib;
    }
    if (bad) n_mis++; else n_match++;
    /* HARNESS_BENCH=R: the best of R runs of each side from the case's registers and local store. An earlier change: the
     * local store is restored before every run (outside the timing): not every gate is idempotent on it. ILR (slot
     * 68) keeps its row counter in its stack frame ([r1 + 0x30], incremented per row until it equals [r1 + 0x50]):
     * a second run from the same registers started past the end, so the lifted loop ran ~2^32 rows (the "hang"
     * with --bench) and the native code declined (rows = 0). */
    static int bench = -1;
    if (bench < 0) bench = getenv("HARNESS_BENCH") ? atoi(getenv("HARNESS_BENCH")) : 0;
    static int bench_any = -1;   /* HARNESS_BENCH_ANY=1: time mismatching cases too (ablations, timing only) */
    if (bench_any < 0) bench_any = getenv("HARNESS_BENCH_ANY") && atoi(getenv("HARNESS_BENCH_ANY"));
    if (bench > 0 && (!bad || bench_any) && !hmfc_puts(&LA)) {   /* cases with a put time the harness's MFC model */
        uint64_t bl = ~0ull, bn = ~0ull;
        g_no_arm = 1;
        for (int r = 0; r < bench; r++) {
            memcpy(A.gpr, S.gpr, sizeof S.gpr);
            memcpy(A.ls, S.ls, SPU_LS_SIZE);
            memcpy(B.ls, S.ls, SPU_LS_SIZE);
            if (kind_r3(e)) {   /* the vertex emitter advances its ring state (LS 0x27B80): restore it */
                memcpy(A.ls + 0x27B80, S.ls + 0x27B80, 32);
                memcpy(B.ls + 0x27B80, S.ls + 0x27B80, 32);
                hmfc_reset(&LA);
                hmfc_reset(&LB);
            }
            uint64_t a0 = now_ns();
            run_lifted(&A, lf);
            uint64_t a1 = now_ns();
            memcpy(B.gpr, S.gpr, sizeof S.gpr);
            kz2_native_run(&B, e);
            uint64_t a2 = now_ns();
            if (a1 - a0 < bl) bl = a1 - a0;
            if (a2 - a1 < bn) bn = a2 - a1;
        }
        g_no_arm = 0;
        b_lift += bl;
        b_nat += bn;
    }
    n_puts += hmfc_puts(&LA);
    char pcx[48] = "";
    if (g_pc_mode) snprintf(pcx, sizeof pcx, " heads=%u exit=0x%05X", g_heads_want, g_end);   /* an earlier change */
    printf("C %s %s scratch_regs_differ=%d mfc_puts=%d lifted_us=%.1f native_us=%.1f%s%s%s%s\n", name,
           bad ? "MISMATCH" : "ok", scratch, hmfc_puts(&LA), (t1 - t0) / 1000.0, (t2 - t1) / 1000.0, pcx,
           do_interp && !g_pc_mode ? (ib ? " interp=MISMATCH" : " interp=ok") : "", diff[0] ? " " : "", diff);
}

static int load_record(const char* path, int* slot, uint32_t* addr)
{
    FILE* f = fopen(path, "rb");
    if (!f) return 0;
    char m[8];
    uint32_t h[4];
    int ok = fread(m, 1, 8, f) == 8 && !memcmp(m, KZ2_NJ_MAGIC, 8) && fread(h, 4, 4, f) == 4;
    spu_context_init(&S, 0);
    ok = ok && fread(S.gpr, 16, 128, f) == 128 && fread(S.ls, 1, SPU_LS_SIZE, f) == SPU_LS_SIZE;
    fclose(f);
    *slot = (int)h[0];
    *addr = h[1];
    S.image_id = 1;
    return ok;
}

int main(int argc, char** argv)
{
    if (argc < 4) { fprintf(stderr, "usage: see the header\n"); return 2; }
    FILE* f = fopen(argv[1], "rb");
    if (!f) return 2;
    fseek(f, 0, SEEK_END);
    image_len = ftell(f);
    fseek(f, 0, SEEK_SET);
    image = malloc(image_len);
    if (fread(image, 1, image_len, f) != (size_t)image_len) return 2;
    fclose(f);
    base = (uint32_t)strtoul(argv[2], 0, 0);
    {
        static char nm[256];
        const char* b = strrchr(argv[1], '/');
        snprintf(nm, sizeof nm, "%s", b ? b + 1 : argv[1]);
        char* dot = strrchr(nm, '.');
        if (dot) *dot = 0;
        g_image = nm;
    }
    extern void HARNESS_REGISTER(void);
    HARNESS_REGISTER();
    {   /* an earlier change: settle the LS debug gates as the game has by the time a job runs (-1 until the first full
         * read and write read their env; with them unsettled kz2_native_run declines: a job that only stores, as
         * Gfx.Post.Zero's memset, would never reach its native code here) */
        static spu_context z;
        spu_context_init(&z, 0);
        spu_ls_write128(&z, 0x100, spu_ls_read128(&z, 0x100));
    }
    signal(SIGALRM, on_alarm);
    do_interp = getenv("HARNESS_INTERP") && atoi(getenv("HARNESS_INTERP"));
    int slot_seen = -1;
    if (!strcmp(argv[3], "synth") && argc >= 7) {
        const int slot = atoi(argv[4]);
        const uint64_t seed = strtoull(argv[5], 0, 0);
        const int trials = atoi(argv[6]);
        const kz2_native_entry* e = kz2_native_find(slot);
        for (unsigned k = 0; e && k < sizeof kernels / sizeof kernels[0]; k++) {
            if (strcmp(kernels[k].kind, e->kind)) continue;
            for (int t = 0; t < trials; t++) {
                char nm[64];
                snprintf(nm, sizeof nm, "synth%d#%d", slot, t);
                kernels[k].synth(&S, seed ^ ((uint64_t)slot << 40) ^ (uint64_t)t);
                one(nm, slot, e->addr);
            }
        }
        slot_seen = slot;
    } else if (!strcmp(argv[3], "rec")) {
        for (int i = 4; i < argc; i++) {
            int slot;
            uint32_t addr;
            if (!load_record(argv[i], &slot, &addr)) {
                printf("C %s unreadable\n", argv[i]);
                n_bad++;
                continue;
            }
            const char* nm = strrchr(argv[i], '/');
            {   /* HARNESS_AS_SLOT=N replays a state recorded at another slot of the same function (slot
                 * 79's recordings through slot 81, the same emitter with the SSE relight) */
                const char* as = getenv("HARNESS_AS_SLOT");
                const kz2_native_entry* ea = (as && *as) ? kz2_native_find(atoi(as)) : NULL;
                if (ea && ea->addr == addr) slot = ea->slot;
            }
            if (slot == 68 && addr == 0x4A20) {   /* an earlier change's recording build: Gfx.Post.ILR's pass entry */
                if (!prestate(68, 0x4A20)) {
                    printf("C %s could not bring the state forward to 0x4E20\n", argv[i]);
                    n_bad++;
                    continue;
                }
                addr = 0x4E20;
            }
            one(nm ? nm + 1 : argv[i], slot, addr);
            slot_seen = slot;
        }
    } else {
        fprintf(stderr, "usage: see the header\n");
        return 2;
    }
    printf("T slot=%d cases=%ld match=%ld mismatch=%ld fallback=%ld broken=%ld interp_mismatch=%ld mfc_puts=%ld "
           "lifted_ms=%.2f native_ms=%.2f speedup=%.2f\n", slot_seen, n_case, n_match, n_mis, n_fb, n_bad, n_imis,
           n_puts, t_lift / 1e6,
           t_nat / 1e6, t_nat ? (double)t_lift / (double)t_nat : 0.0);
    if (b_nat)
        printf("B slot=%d best-of lifted_ms=%.3f native_ms=%.3f speedup=%.2f\n", slot_seen, b_lift / 1e6, b_nat / 1e6,
               (double)b_lift / (double)b_nat);
    return (n_mis || n_bad || n_imis) ? 1 : 0;
}
