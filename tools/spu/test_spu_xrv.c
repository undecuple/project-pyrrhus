/* KZ2 patch 7021 host test: the exact vector exponent-255 paths (bit 1 of g_kz3_spu_xrq, KZ2_SPU_XRV=1)
 * against the paths they replace (the 1089 inline lanes plus the 1071 per-lane recompute, g_kz3_spu_xrq = 1, and the
 * per-lane recompute alone, g_kz3_spu_xrq = 0), bit for bit, for fa, fs, fm, fma, fms, fnms, fceq, fcgt, fcmeq, fcmgt,
 * in the FTZ (default) and no-FTZ fma modes. Parts:
 *   sweep   every exponent-255 word (both signs, 2^24; XRV_STEP=k takes every k-th mantissa) as each operand, against
 *           a partner set (zeros, the smallest and largest binades, 1, 0.5, Smax, -Smax, 2^128, the word itself, its
 *           negation, one unit either side, the VertexJob words 0x7FB50000/0x7F350000, products near 2^129 and 2^-126);
 *           fma with the word as a, b or c and the others from the set, the other lanes normal (so the vector takes
 *           the new path, not the whole-vector fallback);
 *   random  XRV_N vectors of words from every class (rword89 of test_spu_xr.c and a near-cancelling partner), all ops;
 *   cases   the game's words (an earlier change's xr stats: fm(+e255, 0.5), fnms(0, Smax, 1), fma(1, x, +e255), fcgt(-Smax, x)).
 * Then a timing of the game's cases, old vs new. Built by tools/spu/test_spu_xrv.sh (no game data). */
#include <math.h>
#include <stdint.h>
#include "spu_context.h"
#include "spu_helpers.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

int g_kz3_spu_slowcg = 0;
int g_kz3_fma_stats;
int g_kz3_xr_stats;
int g_kz3_spu_xrq = 1;
int g_kz3_spu_xr = 1;
static long s_chk_vec, s_chk_diff;   /* KZ2_SPU_XRV=c (xrq 7): the checked vectors and the lanes that differed */
void kz3_spu_xr_note(int op, unsigned m, const uint32_t* a, const uint32_t* b, const uint32_t* c, const uint32_t* r,
                     const void* ra)
{
    (void)a, (void)b, (void)c, (void)r, (void)ra;
    if ((op & 0xC0) == 0xC0) s_chk_diff += __builtin_popcount(m);
    else if (op & 0x80) s_chk_vec++;
}
void kz3_spu_fma_note(const double s[4], int ftz) { (void)s, (void)ftz; }

static uint64_t s_rng = 0x4B5A3321u;
static uint32_t rnd(void)
{
    s_rng ^= s_rng << 13, s_rng ^= s_rng >> 7, s_rng ^= s_rng << 17;
    return (uint32_t)(s_rng >> 16);
}
static uint32_t rnorm(void) { return (rnd() & 0x807FFFFFu) | ((uint32_t)(100 + rnd() % 56) << 23); }
static uint32_t rword(void)
{
    const uint32_t s = rnd() & 0x80000000u;
    switch (rnd() % 10) {
    case 0: return s | 0x7F800000u | (rnd() & 0x7FFFFFu);
    case 1: return s | (rnd() & 0x7FFFFFu);
    case 2: return s | (254u << 23) | (rnd() & 0x7FFFFFu);
    case 3: return s | (1u << 23) | (rnd() & 0x7FFFFFu);
    case 4: return s;
    case 5: return rnd();
    default: return rnorm();
    }
}
static const uint32_t K[] = {0x7FFFFFFFu, 0xFFFFFFFFu, 0x7FFFFC00u, 0x7FB50000u, 0x7F350000u, 0x7FB17215u, 0x7F800000u,
                             0xFF800000u, 0x00800000u, 0x80800000u, 0x00FFFFFFu, 0x3F800000u, 0x3F000000u, 0x5F800000u,
                             0x1F800000u, 0x20000000u, 0x00000000u, 0x80000000u, 0x00000001u, 0x7F7FFFFFu, 0x3F800001u,
                             0x3F7FFFFFu, 0xBF800000u, 0x40000000u, 0x00400000u};
static uint32_t rword89(uint32_t other)
{
    const uint32_t s = rnd() & 0x80000000u;
    const int oe = (int)((other >> 23) & 0xFF);
    int e;
    switch (rnd() % 13) {
    case 0: return K[rnd() % (sizeof K / sizeof K[0])];
    case 1: return s | 0x7F800000u | (rnd() & 0x7FFFFFu);
    case 2: return (other ^ 0x80000000u) + (rnd() % 7) - 3;
    case 3: e = oe - 20 - (int)(rnd() % 40); if (e < 1) e = 1; return s | ((uint32_t)e << 23) | (rnd() & 0x7FFFFFu);
    case 4: e = 255 - oe + 126 + (int)(rnd() % 5) - 2; if (e < 1) e = 1; if (e > 255) e = 255;
            return s | ((uint32_t)e << 23) | (rnd() & 0x7FFFFFu);
    case 5: e = 127 - 126 - (oe - 127) + (int)(rnd() % 5) - 2; if (e < 1) e = 1; if (e > 255) e = 255;
            return s | ((uint32_t)e << 23) | (rnd() & 0x7FFFFFu);
    case 6: return s | (1u << 23) | (rnd() & 0x7FFFFFu);
    case 7: return s | (rnd() & 0x7FFFFFu);
    case 8: return s | (254u << 23) | (rnd() & 0x7FFFFFu);
    case 9: return other;
    case 10: return other ^ 0x80000000u;
    case 11: return (other & 0xFF800000u) | (rnd() & 0x7u) << (rnd() % 21);   /* short mantissas: exact sums */
    default: return rword();
    }
}

enum { OP_FA, OP_FS, OP_FM, OP_FMA, OP_FMS, OP_FNMS, OP_FCEQ, OP_FCGT, OP_FCMEQ, OP_FCMGT, NOPS };
static const char* const opn[NOPS] = {"fa", "fs", "fm", "fma", "fms", "fnms", "fceq", "fcgt", "fcmeq", "fcmgt"};
static u128 run(int op, u128 a, u128 b, u128 c)
{
    switch (op) {
    case OP_FA: return spu_fa(a, b);
    case OP_FS: return spu_fs(a, b);
    case OP_FM: return spu_fm(a, b);
    case OP_FMA: return spu_fma(a, b, c);
    case OP_FMS: return spu_fms(a, b, c);
    case OP_FNMS: return spu_fnms(a, b, c);
    case OP_FCEQ: return spu_fceq(a, b);
    case OP_FCGT: return spu_fcgt(a, b);
    case OP_FCMEQ: return spu_fcmeq(a, b);
    default: return spu_fcmgt(a, b);
    }
}
static long s_bad, s_lanes, s_lanes255, s_newpath;
static long s_bad_op[NOPS];
/* one vector through the old paths (xrq 1 and 0) and the new ones (3 and 2), all four must agree; every 16th vector
 * also in the check mode (7: both paths, the old result kept, the note counts a lane that differs) */
static long s_cmp_n;
static void cmp(int op, u128 a, u128 b, u128 c)
{
    static const int modes[4] = {1, 0, 3, 2};
    u128 r[4];
    for (int k = 0; k < 4; k++) { g_kz3_spu_xrq = modes[k]; r[k] = run(op, a, b, c); }
    if ((s_cmp_n++ & 15) == 0) {
        g_kz3_spu_xrq = 7;
        const u128 r7 = run(op, a, b, c);
        if (memcmp(&r7, &r[0], 16)) { s_bad++; printf("FAIL %s check mode: not the old result\n", opn[op]); }
    }
    g_kz3_spu_xrq = 1;
    for (int i = 0; i < 4; i++) {
        s_lanes++;
        const int e255 = ((a._u32[i] & 0x7F800000u) == 0x7F800000u) || ((b._u32[i] & 0x7F800000u) == 0x7F800000u) ||
                         (op >= OP_FMA && op <= OP_FNMS && (c._u32[i] & 0x7F800000u) == 0x7F800000u);
        s_lanes255 += e255;
        const uint32_t w = r[0]._u32[i];
        if (r[1]._u32[i] != w || r[2]._u32[i] != w || r[3]._u32[i] != w) {
            s_bad_op[op]++;
            if (s_bad++ < 12)
                printf("FAIL %s cgm=%d lane %d: a=0x%08X b=0x%08X c=0x%08X: xrq1 0x%08X xrq0 0x%08X xrv3 0x%08X xrv2 0x%08X\n",
                       opn[op], g_kz3_spu_slowcg, i, a._u32[i], b._u32[i], c._u32[i], w, r[1]._u32[i], r[2]._u32[i],
                       r[3]._u32[i]);
        }
    }
}
static u128 v4(uint32_t w0, uint32_t w1, uint32_t w2, uint32_t w3)
{
    u128 r;
    r._u32[0] = w0, r._u32[1] = w1, r._u32[2] = w2, r._u32[3] = w3;
    return r;
}
static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

/* partners of an exponent-255 word w */
static int partners(uint32_t w, uint32_t* p)
{
    int n = 0;
    for (unsigned k = 0; k < sizeof K / sizeof K[0]; k++) p[n++] = K[k];
    p[n++] = w, p[n++] = w ^ 0x80000000u, p[n++] = w + 1, p[n++] = w - 1, p[n++] = (w ^ 0x80000000u) + 1;
    p[n++] = (w & 0x80000000u) | (254u << 23) | (w & 0x7FFFFFu);   /* one binade down: carries into 2^129 */
    p[n++] = 0x3F800000u | (w & 0x7FFFFFu);                        /* products near 2^128..2^129 */
    p[n++] = 0x00800000u | (w & 0x7FFFFFu) | (w & 0x80000000u);    /* products near 2^-126 */
    p[n++] = (101u << 23) | (w & 0x7FFFFFu);                       /* exponent gap 154: the far rule */
    return n;
}

int main(void)
{
    setvbuf(stdout, NULL, _IOLBF, 0);
    const char* st = getenv("XRV_STEP");
    const long step = st ? atol(st) : 61;   /* host test: every 61st mantissa (a prime: all low-bit patterns) */
    const char* nn = getenv("XRV_N");
    const long N = nn ? atol(nn) : 1500000;
    for (int cgm = 0; cgm <= 2; cgm += 2) {
        g_kz3_spu_slowcg = cgm;
        /* sweep: every exponent-255 word (mantissa step `step`), 4 per vector */
        uint32_t p[64];
        const double t0 = now();
        for (uint32_t m = 0; m < (1u << 23); m += (uint32_t)(4 * step)) {
            uint32_t w[4];
            for (int i = 0; i < 4; i++) {
                const uint32_t mi = (m + (uint32_t)(i * step)) & 0x7FFFFFu;
                w[i] = 0x7F800000u | mi | (i & 1 ? 0x80000000u : 0);
            }
            const u128 W = v4(w[0], w[1], w[2], w[3]);
            const int np = partners(w[0], p);
            for (int k = 0; k < np; k++) {
                u128 P;
                for (int i = 0; i < 4; i++) { uint32_t q[64]; partners(w[i], q); P._u32[i] = q[k]; }
                for (int op = 0; op < NOPS; op++) {
                    if (op >= OP_FMA && op <= OP_FNMS) continue;
                    cmp(op, W, P, W);
                    cmp(op, P, W, W);
                }
                /* fma family: the word as a, b, c; the partner and a second partner (the next one) elsewhere */
                u128 Q;
                for (int i = 0; i < 4; i++) { uint32_t q[64]; partners(w[i], q); Q._u32[i] = q[(k + 7) % np]; }
                for (int op = OP_FMA; op <= OP_FNMS; op++) {
                    cmp(op, W, P, Q);
                    cmp(op, P, W, Q);
                    cmp(op, P, Q, W);
                    /* one exponent-255 lane, the others normal (the new path, not the whole-vector fallback) */
                    u128 a1 = v4(rnorm(), rnorm(), rnorm(), P._u32[3]), b1 = v4(rnorm(), rnorm(), rnorm(), Q._u32[3]),
                         c1 = v4(rnorm(), rnorm(), rnorm(), W._u32[3]);
                    cmp(op, a1, b1, c1);
                }
            }
        }
        const double t1 = now();
        printf("sweep cgm=%d: exponent-255 words every %ld mantissa, %ld lanes (%ld with an exponent-255 word), %ld differ "
               "(%.1f s)\n",
               cgm, step, s_lanes, s_lanes255, s_bad, t1 - t0);
        /* random: every class, near-cancelling and far pairs, products at the range edges */
        long l0 = s_lanes, b0 = s_bad, e0 = s_lanes255;
        for (long it = 0; it < N; it++) {
            u128 a, b, c;
            for (int i = 0; i < 4; i++) {
                a._u32[i] = (rnd() & 3) ? rword89(0x3F800000u) : rword();
                if (rnd() & 1) a._u32[i] = rword89(rword());
                b._u32[i] = rword89(a._u32[i]);
                c._u32[i] = rnd() & 1 ? rword89(a._u32[i]) : rword89(b._u32[i]);
                if (rnd() % 8 == 0) { const uint32_t t = a._u32[i]; a._u32[i] = b._u32[i]; b._u32[i] = t; }
            }
            if (rnd() % 3 == 0)   /* mostly-normal vectors: one odd lane */
                for (int i = 0; i < 3; i++) a._u32[i] = rnorm(), b._u32[i] = rnorm(), c._u32[i] = rnorm();
            for (int op = 0; op < NOPS; op++) cmp(op, a, b, c);
        }
        printf("random cgm=%d: %ld vectors, %ld lanes (%ld with an exponent-255 word), %ld differ\n", cgm, N,
               s_lanes - l0, s_lanes255 - e0, s_bad - b0);
    }
    g_kz3_spu_slowcg = 0;
    /* the game's cases (an earlier change xr stats), checked and timed, old (xrq 1) vs new (xrq 3) */
    {
        const u128 E = v4(0x3F800000u, 0x3F000000u, 0x40000000u, 0x7FB50000u);   /* lane 3: fi(0, frsqest(0)) */
        const u128 H = v4(0x3F000000u, 0x3F000000u, 0x3F000000u, 0x3F000000u), ONE = v4(0x3F800000u, 0x3F800000u,
                                                                                      0x3F800000u, 0x3F800000u);
        const u128 X0 = v4(0x3F800000u, 0x40400000u, 0x3E800000u, 0), SM = v4(0x3F800000u, 0x3F000000u, 0x3E800000u,
                                                                                0x7FFFFFFFu);
        const u128 M1 = v4(0x3F800000u, 0x40000000u, 0x3F000000u, 0xFFFFFFFFu);
        for (int op = 0; op < NOPS; op++) cmp(op, E, H, E), cmp(op, X0, SM, ONE), cmp(op, ONE, H, E), cmp(op, M1, H, ONE);
        const int R = 3000000;
        double t[2];
        uint32_t sink = 0;
        for (int k = 0; k < 2; k++) {
            g_kz3_spu_xrq = k ? 3 : 1;
            u128 acc = H;
            const double a0 = now();
            for (int i = 0; i < R; i++) {
                const u128 y = spu_fm(E, H);           /* fm(+e255, 0.5) */
                const u128 n = spu_fnms(X0, SM, ONE);  /* 1 - 0 * Smax */
                const u128 f = spu_fma(n, y, E);       /* 1 * 0x7F35.. + 0x7FB5.. */
                const u128 g = spu_fcgt(M1, acc);      /* -Smax > x */
                acc._u32[0] ^= y._u32[3] ^ n._u32[3] ^ f._u32[3] ^ g._u32[3];
                __asm__ volatile("" : "+m"(acc));
            }
            t[k] = (now() - a0) / R * 1e9;
            sink ^= acc._u32[0];
        }
        g_kz3_spu_xrq = 1;
        printf("game cases (fm e255*0.5, fnms 1-0*Smax, fma 1*x+e255, fcgt -Smax>x), lane 3 odd: %.1f ns old, %.1f ns new "
               "per 4 ops (x%.2f)%s\n",
               t[0], t[1], t[0] / t[1], sink == 0xFFFFFFFFu ? " " : "");
    }
    /* per op, the game's vectors (lane 3 odd), old vs new */
    {
        const u128 E = v4(0x3F800000u, 0x3F000000u, 0x40000000u, 0x7FB50000u), H = v4(0x3F000000u, 0x3F000000u,
                                                                                        0x3F000000u, 0x3F000000u);
        const u128 ONE = v4(0x3F800000u, 0x3F800000u, 0x3F800000u, 0x3F800000u);
        const u128 X0 = v4(0x3F800000u, 0x40400000u, 0x3E800000u, 0), SM = v4(0x3F800000u, 0x3F000000u, 0x3E800000u,
                                                                                0x7FFFFFFFu);
        const u128 M1 = v4(0x3F800000u, 0x40000000u, 0x3F000000u, 0xFFFFFFFFu);
        const char* nm[4] = {"fm(e255, 0.5)", "fnms(0, Smax, 1)", "fma(1, x, e255)", "fcgt(-Smax, x)"};
        for (int o = 0; o < 4; o++) {
            double t[2];
            for (int k = 0; k < 2; k++) {
                g_kz3_spu_xrq = k ? 3 : 1;
                u128 acc = ONE;
                const int R = 2000000;
                const double a0 = now();
                for (int i = 0; i < R; i++) {
                    u128 y;
                    __asm__ volatile("" : "+m"(acc));
                    switch (o) {
                    case 0: y = spu_fm(E, H); break;
                    case 1: y = spu_fnms(X0, SM, ONE); break;
                    case 2: y = spu_fma(ONE, H, E); break;
                    default: y = spu_fcgt(M1, acc); break;
                    }
                    acc._u32[1] ^= y._u32[3];
                }
                t[k] = (now() - a0) / R * 1e9;
            }
            printf("  %-17s %.1f ns old, %.1f ns new (x%.2f)\n", nm[o], t[0], t[1], t[0] / t[1]);
        }
        g_kz3_spu_xrq = 1;
    }
    for (int op = 0; op < NOPS; op++)
        if (s_bad_op[op]) printf("  %s: %ld lanes differ\n", opn[op], s_bad_op[op]);
    printf("check mode (KZ2_SPU_XRV=c): %ld vectors checked, %ld lanes differ\n", s_chk_vec, s_chk_diff);
    if (s_chk_diff || !s_chk_vec) s_bad++;
    printf(s_bad ? "test_spu_xrv: %ld lanes FAILED of %ld\n" : "test_spu_xrv: all passed (%ld differ of %ld lanes)\n", s_bad,
           s_lanes);
    return s_bad != 0;
}
