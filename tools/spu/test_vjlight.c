/* Host test and bench: Particles.VertexJob's relight in SSE (port/kz2/spu/native_particles.c
 * vjf_light_52C0 and vjf_pack, slot 81) against the helper form (vj_light_52C0, vj_pack, slot 79, itself equal to the
 * lifted code: tools/spu/native_diff.py), all four result lanes compared, with the patch-1071 exponent-255 recompute
 * off and on (g_kz3_spu_xr).
 *   test_vjlight synth [TRIALS] [neg]   random local stores and arguments: the three relight modes (0, 1 = distance
 *                                       falloff, else the 8x8x8 grid), the coefficients, matrix, position and
 *                                       intensity normal floats, or (a quarter of the trials, per word) zero,
 *                                       denormal, huge, infinity/NaN bits or random words; neg = a negative control
 *                                       (a one-ulp change of the fast form's result must be caught)
 *   test_vjlight rec FILE.kz2nj ...      the recorded states of slot 79 (KZ2_NATIVE_REC) whose call relights: the
 *                                       arguments r6-r8 and the local store as the emitter sees them (game data:
 *                                       keep them under work/)
 * Each also times both forms on the same inputs (best of 5 passes of 2000 calls per input, one core).
 * No game data in the synthetic mode. Built by tools/spu/test_native_vjlight.sh. */
static long s_slow[10];
static int s_count;   /* count the wrappers' helper branches (only around the SSE form's calls) */
#define NSIMD_SLOW(k) (s_count ? (void)s_slow[k]++ : (void)0)
#include "native_particles.c"

#include <stdio.h>
#include <stdlib.h>
#include <time.h>

int g_kz3_spu_xr = 0;
int g_kz3_spu_slowcg;
int g_kz3_fma_stats;
int g_kz3_xr_stats;
int g_kz3_spu_xrq = 1;
void (*g_kz3_wtrace)(const char*, int, uint32_t, uint64_t, uint64_t);
void kz3_spu_xr_note(int op, unsigned m, const uint32_t* a, const uint32_t* b, const uint32_t* c, const uint32_t* r,
                     const void* ra)
{
    (void)op, (void)m, (void)a, (void)b, (void)c, (void)r, (void)ra;
}
void kz3_spu_fma_note(const double s[4], int ftz)
{
    (void)s, (void)ftz;
}
/* the emitter's channel calls are not reached here (only the relight and the packing are called) */
u128 spu_rdch(spu_context* ctx, uint32_t channel)
{
    (void)ctx, (void)channel;
    abort();
}
void spu_wrch(spu_context* ctx, uint32_t channel, u128 value)
{
    (void)ctx, (void)channel, (void)value;
    abort();
}

static uint64_t s_rng = 0x4B5A3227u;
static uint32_t rnd(void)
{
    s_rng = s_rng * 6364136223846793005ull + 1442695040888963407ull;
    return (uint32_t)(s_rng >> 33);
}
static uint32_t fbits32(float f)
{
    uint32_t u;
    memcpy(&u, &f, 4);
    return u;
}
/* a float word: normal in [-r, r], or (odd) one of the special classes */
static uint32_t word(float r, int odd)
{
    if (odd && rnd() % 4 == 0) {
        switch (rnd() % 7) {
        case 0: return 0;
        case 1: return 0x80000000u;
        case 2: return rnd() & 0x807FFFFFu;                  /* denormal */
        case 3: return (rnd() & 0x80000000u) | 0x7F800000u | (rnd() & 0x7FFFFFu);   /* exponent 255 */
        case 4: return (rnd() & 0x80000000u) | (0x7E000000u + (rnd() & 0xFFFFFFu));  /* huge */
        case 5: return (rnd() & 0x80000000u) | (0x00800000u + (rnd() & 0x7FFFFFu));  /* the smallest normals */
        default: return rnd();
        }
    }
    return fbits32(((float)rnd() / 4294967296.0f * 2.0f - 1.0f) * r);
}
static void wr(uint8_t* ls, uint32_t a, uint32_t v)
{
    uint8_t* p = ls + (a & SPU_LS_MASK & ~3u);
    p[0] = (uint8_t)(v >> 24), p[1] = (uint8_t)(v >> 16), p[2] = (uint8_t)(v >> 8), p[3] = (uint8_t)v;
}
static void wq(uint8_t* ls, uint32_t a, float r, int odd)
{
    for (int k = 0; k < 4; k++) wr(ls, (a & ~15u) + 4 * k, word(r, odd));
}

typedef struct {
    spu_context* c;
    u128 r4, a6, a7, a8;
} vjl_in;

static void synth(spu_context* c, vjl_in* in, int t)
{
    const int odd = t % 4 == 0;
    memset(c->ls, 0, SPU_LS_SIZE);
    for (uint32_t a = 0x8800; a < 0x8830; a += 16) wq(c->ls, a, 1.0f, odd);        /* the matrix */
    wq(c->ls, 0x8880, 4.0f, odd);
    wq(c->ls, 0x8890, 2.0f, odd);
    wq(c->ls, 0x8450, 1.0f, odd);
    wq(c->ls, 0x8460, 1.0f, odd);
    for (uint32_t a = 0x1BA00; a <= 0x1BA80; a += 16) wq(c->ls, a, 1.0f, odd);    /* the SH coefficients */
    wq(c->ls, 0x1BB40, 8.0f, odd);
    wq(c->ls, 0x1BB50, 2.0f, odd);
    wq(c->ls, 0x1BB60, 1.0f, odd);
    for (int k = 0; k < 4; k++) wr(c->ls, 0x83F0 + 4 * k, odd && rnd() % 8 == 0 ? word(1.0f, 1) : 0x3F800000u);
    for (uint32_t i = 0; i < 512; i++) wr(c->ls, 0x19B00 + 4 * i, word(1.5f, odd));   /* the grid */
    /* r4: a record base; [r4 + 0x9F0] the mode word (+ a falloff scale in word 1), [r4 + 0xA00] the intensity
     * quadword read at 0x55E0 (word 1 its blend), [0x84B0] the falloff's light pointer */
    const uint32_t r4 = 0x10000u + 16u * (rnd() % 256);
    const uint32_t mode = rnd() % 3 == 0 ? 0 : rnd() % 2 ? 1 : 2 + rnd() % 5;
    wq(c->ls, r4 + 0x9F0, 1.0f, odd);
    wr(c->ls, r4 + 0x9F0, mode);
    wq(c->ls, r4 + 0xA00, 1.0f, odd);
    const uint32_t lp = 0x12000u + 16u * (rnd() % 64);
    wr(c->ls, 0x84B0, lp);
    wq(c->ls, lp + 0x30, 8.0f, odd);
    wq(c->ls, lp + 0x40, 8.0f, odd);
    in->c = c;
    in->r4 = spu_splat_u32(r4);
    for (int k = 0; k < 4; k++) {
        in->a6._u32[k] = word(rnd() % 2 ? 6.0f : 40.0f, odd);   /* position (the grid spans 4 units at 2x) */
        in->a7._u32[k] = word(1.0f, odd);
        in->a8._u32[k] = word(1.5f, odd);
    }
}

static int load(const char* path, spu_context* c, vjl_in* in)
{
    FILE* f = fopen(path, "rb");
    if (!f) return 0;
    char m[8];
    uint32_t h[4];
    int ok = fread(m, 1, 8, f) == 8 && !memcmp(m, KZ2_NJ_MAGIC, 8) && fread(h, 4, 4, f) == 4 && h[1] == 0x50F8u;
    ok = ok && fread(c->gpr, 16, 128, f) == 128 && fread(c->ls, 1, SPU_LS_SIZE, f) == SPU_LS_SIZE;
    fclose(f);
    in->c = c;
    in->r4 = L(c, 0x84C0);
    in->a6 = c->gpr[6], in->a7 = c->gpr[7], in->a8 = c->gpr[8];
    return ok;
}

static uint64_t now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static volatile uint32_t s_sink;
static double t_ref, t_fast;
static void bench(const vjl_in* in)
{
    const u128 r1 = spu_splat_u32(0x1F520u);
    for (int form = 0; form < 2; form++) {
        uint64_t best = ~0ull;
        for (int p = 0; p < 5; p++) {
            const uint64_t t0 = now_ns();
            uint32_t acc = 0;
            for (int i = 0; i < 2000; i++) {
                const u128 r = form ? vjf_light_52C0(in->c, in->r4, in->a6, in->a7, in->a8)
                                    : vj_light_52C0(in->c, in->r4, in->a6, in->a7, in->a8, r1);
                acc += r._u32[0];
            }
            s_sink = acc;
            const uint64_t d = now_ns() - t0;
            if (d < best) best = d;
        }
        *(form ? &t_fast : &t_ref) += (double)best / 2000.0;
    }
}

static long n_case, n_bad, n_relit_modes[3], n_skip;
static int one(const vjl_in* in, int neg, const char* nm, int do_bench)
{
    const u128 r1 = spu_splat_u32(0x1F520u);
    int bad = 0;
    for (int xr = 0; xr < 2; xr++) {
        g_kz3_spu_xr = xr;
        const u128 a = vj_light_52C0(in->c, in->r4, in->a6, in->a7, in->a8, r1);
        s_count = xr == 0;
        u128 b = vjf_light_52C0(in->c, in->r4, in->a6, in->a7, in->a8);
        s_count = 0;
        if (neg) b._u32[0] ^= 1;
        if (memcmp(&a, &b, 16)) {
            if (!neg && n_bad < 8)
                printf("C %s xr=%d relight differs: %08x %08x %08x %08x / %08x %08x %08x %08x\n", nm, xr, a._u32[0],
                       a._u32[1], a._u32[2], a._u32[3], b._u32[0], b._u32[1], b._u32[2], b._u32[3]);
            bad = 1;
        }
        /* the packing of a7 and of a8 (the two vj_pack calls take r11 and r7) */
        const u128 p0 = vj_pack(in->c, in->a7), q0 = vjf_pack(in->c, in->a7);
        const u128 p1 = vj_pack(in->c, in->a8), q1 = vjf_pack(in->c, in->a8);
        if (p0._u32[0] != q0._u32[0] || p1._u32[0] != q1._u32[0]) {
            if (n_bad < 8) printf("C %s xr=%d pack differs\n", nm, xr);
            bad = 1;
        }
    }
    g_kz3_spu_xr = 0;
    const uint32_t mode = ldq(in->c->ls, in->r4._u32[0] + 0x9F0)._u32[0];
    n_relit_modes[mode == 0 ? 0 : mode == 1 ? 1 : 2]++;
    n_case++;
    n_bad += bad;
    if (do_bench) bench(in);
    return bad;
}

int main(int argc, char** argv)
{
    static spu_context ctx;
    spu_context_init(&ctx, 0);
    vjl_in in;
    if (argc >= 2 && !strcmp(argv[1], "synth")) {
        const int trials = argc >= 3 ? atoi(argv[2]) : 20000;
        const int neg = argc >= 4 && !strcmp(argv[3], "neg");
        long caught = 0;
        for (int t = 0; t < trials; t++) {
            char nm[32];
            snprintf(nm, sizeof nm, "synth#%d", t);
            synth(&ctx, &in, t);
            caught += one(&in, neg, nm, !neg && t < 200);
        }
        if (neg) {
            printf("neg: %ld of %ld one-ulp changes caught\n", caught, (long)trials);
            return caught == trials ? 0 : 1;
        }
    } else if (argc >= 3 && !strcmp(argv[1], "rec")) {
        for (int i = 2; i < argc; i++) {
            if (!load(argv[i], &ctx, &in)) {
                printf("C %s unreadable or not slot 79's function\n", argv[i]);
                n_bad++;
                continue;
            }
            const char* nm = strrchr(argv[i], '/');
            if (ctx.ls[LSQ(in.r4._u32[0] + 0x9E0) + 12] == 0) {   /* the emitter does not relight this call */
                n_skip++;
                continue;
            }
            one(&in, 0, nm ? nm + 1 : argv[i], 1);
        }
    } else {
        fprintf(stderr, "usage: test_vjlight synth [TRIALS] [neg] | rec FILE.kz2nj ...\n");
        return 2;
    }
    if (n_skip) printf("R %ld recorded calls without the relight (byte 12 of [0x84C0] + 0x9E0 = 0) left out\n", n_skip);
    printf("T cases=%ld differ=%ld modes(none/falloff/grid)=%ld/%ld/%ld helper_ns=%.1f sse_ns=%.1f speedup=%.2f\n",
           n_case, n_bad, n_relit_modes[0], n_relit_modes[1], n_relit_modes[2],
           t_ref / (n_case < 200 ? n_case : 200), t_fast / (n_case < 200 ? n_case : 200),
           t_fast > 0 ? t_ref / t_fast : 0.0);
    printf("S helper branches per case (fm fa fs fma fnms fms fcgt cfltu rsq cflts142):");
    for (int k = 0; k < 10; k++) printf(" %.2f", (double)s_slow[k] / (double)(n_case ? n_case : 1));
    printf("\n");
    return n_bad ? 1 : 0;
}
