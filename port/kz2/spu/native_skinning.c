/* native_skinning.c -- Anim.Skinning (job_00d90c00, census image 223) native code: the three-bone vertex skinning loop
 * @0x54C0-0x5A20 (slot 80, KZ2_NATIVE_JOB_SKIN, an earlier change; on by default since an earlier change, =0 turns it off).
 *
 * Profile (kz2-spu26-prof, Corinth Sands in play, KZ3_PROF 100-150 s, 77-79 on by default; the RE notes "An earlier change"):
 * Skinning is 6.7 SPU-ms per frame at 0.72 ms per load, and 77 % of its host samples are this one function (its loop
 * head 0x5678: the lifter's function there). Called once per batch from @0x4E7C (r3 = output, r4 = 0x6100, r5 =
 * 0x7100, r6 = the batch's vertex records, r7/r8 = two matrix palettes, r9 = the vertex count). A leaf: no calls,
 * no channel access, no DMA; a software-pipelined loop (each pass finishes vertex k while it loads vertex k + 1),
 * the dataflow below recovered with tools/spu/loop_dataflow.py.
 *
 * Per vertex k (record window W = the 16 bytes at r6 + 6 + 20 k, byte addresses wrapping in the local store):
 *   weights  w0 = cuflt(W[0]) * (1/255) (0x3B808081), w1 = cuflt(W[1]) * (1/255), w2 = 1 - (w0 + w1)
 *   bones    b = W[5], W[6], W[7]; palette matrix j: 4 quadwords (rows) at base + 64 b_j (mpya: the byte times 64
 *            plus the base's preferred word), base r7 (current) or r8 (the second palette, previous pose)
 *   p = quadword at r4 + 16 k, n = quadword at r5 + 16 k; T(M, v) = (M0 v.x + M1 v.y) + M2 v.z as
 *            fma(M2, v.z, fma(M1, v.y, fm(M0, v.x))), lanes = components; Tp = fa(T(M, p), M3)
 *   blend    S(X) = fma(X2, w2, fma(X1, w1, fm(X0, w0))) (X_j the bone-j term)
 *   P = S(Tp over the r7 matrices), Q = S(Tp over the r8 matrices), D = cflts(P - Q, 142) (x 2^31, saturating)
 *   N = S(T(M, n) over r7), unit: N * fi(l, frsqest(l)) with l = (N.x^2 + N.y^2) + N.z^2, then cflts(., 142)
 *   B, C = the signed bytes W[8..10], W[11..13], each csflt(sext) * (1/127) (0x3C010204), rotated and blended as n
 *            (S(T(M, .)) over r7), unit as N, scaled by (0x3F7FE000, 0x3F7FE000, 0x3F7FC000), cflts(., 142) = x, y,
 *            z, packed hi16(z) << 16 | lo16(x >> 21), with bits 11-21 from y >> 10 (selb mask 0x003FF800)
 *   output   [r3 + 32 k]      = P.x, P.y, P.z, hi16(D.x) << 16 | hi16(D.y)
 *            [r3 + 32 k + 16] = hi16(D.z) << 16 | hi16(Nu.x), hi16(Nu.y) << 16 | hi16(Nu.z), pack(B), pack(C)
 * Every float through the runtime's own helpers or native_simd.h's wrappers of them on full quadwords in the SPU
 * code's operand order (lane-wise, so every lane has the lifted code's bits); cuflt/csflt of a byte are exact in any
 * conversion; the constants are those of the pool [0x5ED0, 0x5FA0) (the gate checks its hash). An earlier change (speed, same
 * bits): the three unit steps share one fi(frsqest) (sk_rlen3, lanes transposed) done in float by sk_rsq, cflts(142)
 * by sk_cflts142 (both equal to the helpers on all 2^32 inputs: tools/spu/test_native_skin_ops.c), the record bytes in
 * one 16-byte copy, the bulk's loops unrolled, and lane 3 (dead) left out of the fast form's range and fma checks.
 *
 * Registers: the loop leaves r3 + 32 n, r4 and r5 + 16 (n + 1), r6 + 26 + 20 n, r9 - n (every lane, as the `ai`s do);
 * the native code sets those; the other registers it writes (r2, r7, r8, r10-r79: the ABI's volatile ones) are not
 * read before written again after the return (tools/spu/live_proof.py from 0x4E7C, an earlier change: RESULT clean with the
 * walker following the jobs' brsl/ai/bi interrupt idiom, the frames above seeded, the four callbacks through
 * [0x6080] + 0x40 walked into the job manager at 0x1820 and --stop at its job-call continuation; re-notes "An earlier change").
 * Declines (the lifted loop runs) unless 1 <= n <= 4096, r3 is 16-byte aligned, and the output [r3, r3 + 32 n) lies
 * inside the local store apart from everything the loop reads: the records, the two vertex streams and both palettes
 * (256 matrices from each base). The pipelined loop also reads vertex n's data (one prefetch past the end): reads
 * only, nothing to reproduce. */
#include "native_simd.h"

#define SK_POOL_LO 0x5ED0u
#define SK_POOL_HI 0x5FA0u

static inline __m128 lane(__m128 v, int i)
{
    switch (i) {
    case 0: return _mm_shuffle_ps(v, v, 0x00);
    case 1: return _mm_shuffle_ps(v, v, 0x55);
    case 2: return _mm_shuffle_ps(v, v, 0xAA);
    default: return _mm_shuffle_ps(v, v, 0xFF);
    }
}
static inline __m128 ldf(const uint8_t* ls, uint32_t a) { return F(ldq(ls, a)); }

/* The bulk arithmetic (rotations, translations, blends, P - Q) in two forms with the same bits:
 *  exact: native_simd.h's wrappers (each op checks its own result and calls the runtime's helper for the odd lanes);
 *  fast:  the bare SSE op the wrappers' fast paths execute (mulps/addps/subps, one vfmadd), valid when no op of the
 *         vertex reaches what a wrapper treats specially. fm/fa/fs only treat exponent-255 results specially: with
 *         every input lane (the six matrices' 16 lanes, p, n) below 2^20 in magnitude and the weights and byte
 *         vectors in [-1, 1] no value of the bulk exceeds 2^46, so none reaches exponent 255. fma also sends results
 *         with exponent 0 (non-zero) or 1 to the double path: every fma result's |r| - 1 goes into an unsigned
 *         minimum (sk_acc), and a vertex with one below 0x00FFFFFF (0 < |r| < 2^-125) is recomputed exactly.
 * The fast form needs the helpers' hardware fma path (-mfma, g_kz3_spu_slowcg == 0), as fma_ does. */
typedef struct { int exact; __m128i acc; } sk_ctx;
static inline __attribute__((always_inline)) __m128 sk_fm(sk_ctx* x, __m128 a, __m128 b) { return x->exact ? fm_(a, b) : _mm_mul_ps(a, b); }
static inline __attribute__((always_inline)) __m128 sk_fa(sk_ctx* x, __m128 a, __m128 b) { return x->exact ? fa_(a, b) : _mm_add_ps(a, b); }
static inline __attribute__((always_inline)) __m128 sk_fs(sk_ctx* x, __m128 a, __m128 b) { return x->exact ? fs_(a, b) : _mm_sub_ps(a, b); }
static inline __attribute__((always_inline)) __m128 sk_fma(sk_ctx* x, __m128 a, __m128 b, __m128 c)
{
#if defined(__FMA__)
    if (!x->exact) {
        const __m128 r = _mm_fmadd_ps(a, b, c);
        const __m128i ab = _mm_and_si128(_mm_castps_si128(r), _mm_set1_epi32(0x7FFFFFFF));
        x->acc = _mm_min_epu32(x->acc, _mm_sub_epi32(ab, _mm_set1_epi32(1)));
        return r;
    }
#endif
    return fma_(a, b, c);
}
/* fma(M2, v.z, fma(M1, v.y, fm(M0, v.x))) with the matrix rows M[0..2] */
static inline __attribute__((always_inline)) __m128 sk_rot(sk_ctx* x, const __m128* M, __m128 vx, __m128 vy, __m128 vz)
{
    return sk_fma(x, M[2], vz, sk_fma(x, M[1], vy, sk_fm(x, M[0], vx)));
}
static inline __attribute__((always_inline)) __m128 sk_blend(sk_ctx* x, __m128 x0, __m128 x1, __m128 x2, __m128 w0, __m128 w1, __m128 w2)
{
    return sk_fma(x, x2, w2, sk_fma(x, x1, w1, sk_fm(x, x0, w0)));
}
/* lanes 0-2 below 2^20 in magnitude (no NaN, no infinity). Lane 3 is not looked at: no output takes
 * anything from lane 3 of the bulk (the stores and the unit steps use lanes 0-2, the matrices' lane 3 only reaches
 * lane 3 of a result, p and n are read through splats of lanes 0-2, every op is lane-wise), so lane 3 may hold
 * anything in the fast form; the recorded positions and palettes carry large lane-3 words often enough to have
 * sent 2 % of the vertices to the exact form. */
static inline int sk_small(__m128 v)
{
    const __m128i ab = _mm_and_si128(_mm_castps_si128(v), _mm_set1_epi32(0x7FFFFFFF));
    return (_mm_movemask_epi8(_mm_cmpgt_epi32(ab, _mm_set1_epi32(0x497FFFFF))) & 0x0FFF) == 0;
}
/* The palettes, converted to host lanes on a bone's first use in a call (the output never overlaps them: checked),
 * with whether the matrix's 16 lanes are all below 2^20 */
typedef struct {
    uint64_t have[4], small[4];
    __m128 m[256][4];
} sk_pal;
static inline const __m128* sk_mat(sk_pal* pal, const uint8_t* ls, uint32_t base, uint32_t b, int* small)
{
    if (!(pal->have[b >> 6] >> (b & 63) & 1)) {
        const uint32_t a = base + 64u * b;   /* mpya: the bone byte times 64 plus the base */
        int ok = 1;
        for (int r = 0; r < 4; r++) {
            pal->m[b][r] = ldf(ls, a + 16u * r);
            ok &= sk_small(pal->m[b][r]);
        }
        pal->have[b >> 6] |= 1ull << (b & 63);
        pal->small[b >> 6] |= (uint64_t)ok << (b & 63);
    }
    *small &= (int)(pal->small[b >> 6] >> (b & 63) & 1);
    return pal->m[b];
}
/* sk_rsq = rsq_ (native_simd.h since an earlier change, shared with VertexJob's relight) */
static inline __m128 sk_rsq(__m128 l) { return rsq_(l); }
/* the unit steps of N and the two byte vectors in one go: their squares transposed so lane j holds
 * vector j's (x^2 + y^2) + z^2, then one frsqest and one fi for all three (lane-wise ops: every lane has the bits of
 * the separate sk_rlen calls of an earlier change, which splatted lane 0 of each). r[j] = fi(l_j, frsqest(l_j)), splatted. */
static inline __attribute__((always_inline)) void sk_rlen3(__m128 v0, __m128 v1, __m128 v2, __m128 r[3])
{
    __m128 s0 = fm_(v0, v0), s1 = fm_(v1, v1), s2 = fm_(v2, v2), s3 = _mm_set1_ps(1.0f);
    _MM_TRANSPOSE4_PS(s0, s1, s2, s3);   /* s0 = the x^2 of the three vectors, s1 the y^2, s2 the z^2 (lane 3: 3.0) */
    const __m128 q = sk_rsq(fa_(fa_(s0, s1), s2));
    r[0] = lane(q, 0);
    r[1] = lane(q, 1);
    r[2] = lane(q, 2);
}
/* sk_cflts142 = cflts142_ (native_simd.h since an earlier change) */
static inline u128 sk_cflts142(__m128 x) { return cflts142_(x); }
static inline uint32_t hi16(uint32_t x) { return x >> 16; }
/* the 11:11:10 word of a unit vector's cflts lanes */
static inline uint32_t sk_pack(u128 q)
{
    const uint32_t x = q._u32[0], y = q._u32[1], z = q._u32[2];
    const uint32_t a = (z & 0xFFFF0000u) | ((x >> 21) & 0xFFFFu);
    return (a & ~0x003FF800u) | ((y >> 10) & 0x003FF800u);
}
static inline int32_t sext8(uint8_t b) { return (int8_t)b; }

static inline int sk_apart(uint32_t o, uint32_t on, uint32_t a, uint32_t an)
{
    return !ovl(o, on, a, an);
}

/* P, P - Q, N and the two byte vectors' blends of one vertex; the fast form returns 0 when an fma result needs the
 * helper's double path (the caller then runs the exact form) */
static inline __attribute__((always_inline)) int sk_bulk(const int exact, const __m128* const A[3],
                                                         const __m128* const B[3], __m128 p, __m128 nv,
                                                         const __m128 bs[2], __m128 w0, __m128 w1, __m128 w2,
                                                         __m128 out[5])
{
    sk_ctx x = { exact, _mm_set1_epi32(-1) };
    const __m128 px = lane(p, 0), py = lane(p, 1), pz = lane(p, 2);
    const __m128 nx = lane(nv, 0), ny = lane(nv, 1), nz = lane(nv, 2);
    __m128 tp[3], tq[3], tn[3];
#pragma GCC unroll 3
    for (int j = 0; j < 3; j++) {
        tp[j] = sk_fa(&x, sk_rot(&x, A[j], px, py, pz), A[j][3]);
        tq[j] = sk_fa(&x, sk_rot(&x, B[j], px, py, pz), B[j][3]);
        tn[j] = sk_rot(&x, A[j], nx, ny, nz);
    }
    out[0] = sk_blend(&x, tp[0], tp[1], tp[2], w0, w1, w2);
    out[1] = sk_fs(&x, out[0], sk_blend(&x, tq[0], tq[1], tq[2], w0, w1, w2));
    out[2] = sk_blend(&x, tn[0], tn[1], tn[2], w0, w1, w2);
#pragma GCC unroll 2
    for (int v = 0; v < 2; v++) {
        const __m128 sx = lane(bs[v], 0), sy = lane(bs[v], 1), sz = lane(bs[v], 2);
        __m128 t[3];
#pragma GCC unroll 3
        for (int j = 0; j < 3; j++) t[j] = sk_rot(&x, A[j], sx, sy, sz);
        out[3 + v] = sk_blend(&x, t[0], t[1], t[2], w0, w1, w2);
    }
    if (exact) return 1;
    /* an fma result with 0 < |r| < 2^-125: the helper's double path decides it */
    const __m128i a3 = _mm_or_si128(x.acc, _mm_setr_epi32(0, 0, 0, -1));   /* lane 3: dead (see sk_small) */
    const __m128i m = _mm_min_epu32(a3, _mm_shuffle_epi32(a3, 0x4E));
    return (uint32_t)_mm_cvtsi128_si32(_mm_min_epu32(m, _mm_shuffle_epi32(m, 0xB1))) >= 0x00FFFFFFu;
}

static int sk_skin_54C0(spu_context* c)   // @0x000054C0 (job_00d90c00)
{
    uint8_t* const ls = c->ls;
    const uint32_t n = c->gpr[9]._u32[0];
    const uint32_t o = c->gpr[3]._u32[0], r4 = c->gpr[4]._u32[0], r5 = c->gpr[5]._u32[0];
    const uint32_t r6 = c->gpr[6]._u32[0], m7 = c->gpr[7]._u32[0], m8 = c->gpr[8]._u32[0];
    if (n < 1 || n > 4096 || (o & 15) || o >= SPU_LS_SIZE || SPU_LS_SIZE - o < 32 * n) return 0;
    const uint32_t on = 32 * n;
    /* everything the loop reads, as byte ranges (a range that wraps the local store: decline) */
    const uint32_t ra[5] = { r6 + 6, r4 & ~15u, r5 & ~15u, m7 & ~15u, m8 & ~15u };
    const uint32_t rn[5] = { 20 * n + 16, 16 * n + 16, 16 * n + 16, 64 * 255 + 64, 64 * 255 + 64 };
    for (int i = 0; i < 5; i++)
        if (ra[i] >= SPU_LS_SIZE || SPU_LS_SIZE - ra[i] < rn[i] || !sk_apart(o, on, ra[i], rn[i])) return 0;

    const __m128 k255 = fbits(0x3B808081u), k127 = fbits(0x3C010204u), one = fbits(0x3F800000u);
    const __m128 pscale = _mm_castsi128_ps(_mm_setr_epi32(0x3F7FE000, 0x3F7FE000, 0x3F7FC000, 0));
    static __thread sk_pal pa, pb;
    memset(pa.have, 0, sizeof pa.have);
    memset(pa.small, 0, sizeof pa.small);
    memset(pb.have, 0, sizeof pb.have);
    memset(pb.small, 0, sizeof pb.small);
#if defined(__FMA__)
    const int fast_ok = g_kz3_spu_slowcg == 0;
#else
    const int fast_ok = 0;
#endif
    for (uint32_t k = 0; k < n; k++) {
        const uint32_t wa = r6 + 6 + 20 * k;
        uint8_t W[16];
        memcpy(W, ls + wa, 16);   /* inside the local store: the records' range is checked above (no wrap) */
        /* weights: cuflt (exact for a byte) then fm, w2 = fs(1, fa(w0, w1)) */
        const __m128 wv = fm_(_mm_cvtepi32_ps(_mm_setr_epi32(W[0], W[1], 0, 0)), k255);
        const __m128 w0 = lane(wv, 0), w1 = lane(wv, 1), w2 = fs_(one, fa_(w0, w1));
        const __m128 *A[3], *B[3];
        int small = fast_ok;
        for (int j = 0; j < 3; j++) {
            A[j] = sk_mat(&pa, ls, m7, W[5 + j], &small);
            B[j] = sk_mat(&pb, ls, m8, W[5 + j], &small);
        }
        const __m128 p = ldf(ls, r4 + 16 * k), nv = ldf(ls, r5 + 16 * k);
        small &= sk_small(p) & sk_small(nv);
        __m128 bs[2];
        for (int v = 0; v < 2; v++) {
            const uint8_t* b = W + 8 + 3 * v;
            bs[v] = fm_(_mm_cvtepi32_ps(_mm_setr_epi32(sext8(b[0]), sext8(b[1]), sext8(b[2]), 0)), k127);
        }
        __m128 o4[5];
        const int fast = small && sk_bulk(0, A, B, p, nv, bs, w0, w1, w2, o4);
        if (!fast) sk_bulk(1, A, B, p, nv, bs, w0, w1, w2, o4);
        const __m128 P = o4[0], D = o4[1], N = o4[2], X[2] = { o4[3], o4[4] };
        __m128 rl[3];
        sk_rlen3(N, X[0], X[1], rl);
        const u128 Du = sk_cflts142(D);
        const u128 Nu = sk_cflts142(fm_(N, rl[0]));
        uint32_t pk[2];
        for (int v = 0; v < 2; v++) pk[v] = sk_pack(sk_cflts142(fm_(fm_(X[v], rl[1 + v]), pscale)));
        const u128 Pu = U(P);
        u128 q0, q1;
        q0._u32[0] = Pu._u32[0];
        q0._u32[1] = Pu._u32[1];
        q0._u32[2] = Pu._u32[2];
        q0._u32[3] = hi16(Du._u32[0]) << 16 | hi16(Du._u32[1]);
        q1._u32[0] = hi16(Du._u32[2]) << 16 | hi16(Nu._u32[0]);
        q1._u32[1] = hi16(Nu._u32[1]) << 16 | hi16(Nu._u32[2]);
        q1._u32[2] = pk[0];
        q1._u32[3] = pk[1];
        stq(ls, o + 32 * k, q0);
        stq(ls, o + 32 * k + 16, q1);
    }
    for (int i = 0; i < 4; i++) {
        c->gpr[3]._u32[i] += 32 * n;
        c->gpr[4]._u32[i] += 16 * (n + 1);
        c->gpr[5]._u32[i] += 16 * (n + 1);
        c->gpr[6]._u32[i] += 26 + 20 * n;
        c->gpr[9]._u32[i] -= n;
    }
    return 1;
}

const kz2_native_entry kz2_native_skinning[] = {
    { 80, "KZ2_NATIVE_JOB_SKIN", "Anim.Skinning", "job_00d90c00", 0x54C0u, sk_skin_54C0, "sk_skin", SK_POOL_LO,
      SK_POOL_HI, 0xb291e50c05d6cd08ull, 0 },
};
const unsigned kz2_native_skinning_n = sizeof kz2_native_skinning / sizeof kz2_native_skinning[0];
