/* native_edgeanim.c -- Anim.EdgeAnim (job_00d95d80, census image 224) kernels as native host code. Default off: KZ2_NATIVE_JOB_EDGEANIM=1 (not a Gfx.Post job: KZ2_NATIVE_JOB_POST does not reach it).
 *
 * Profile (kz2-spu19-scout2, Corinth Sands in play, KZ3_PROF 95-165 s, the RE notes "An earlier change"): the job is
 * 6.7 SPU-ms per frame there; 29 % of its host samples are two leaf subroutines that the joint-pose decoder @0x10D78
 * calls three times each (rotation, translation, scale; no calls, no channel access, no DMA):
 *   0x13100 (521 instructions, loop 0x13428-0x1384C, 15 % of the job's samples): the bit-packed decoder, native here;
 *   0x12438 (818 instructions, loop 0x125A8-0x13034, 14 %): the keyframe sampler, read but not written yet.
 * Gated at their entries (re/spu/native_gates.tsv slots 75, 76). Written from the disassembly and
 * tools/spu/spu_symtrace.py's dataflow (synthetic arguments and states recorded in play). */
#include "native_simd.h"

/* ---- 0x13100: the bit-packed three-component decoder ----
 *
 * Arguments (preferred word of each): r3 = byte address of the bit stream, r4 = element count n, r5 = output base,
 * r6 = index table (one big-endian halfword per element), r7 = the 32-bit packing spec (any byte address). The spec
 * describes three components c = 1, 2, 3, each as s (1 bit), e (4 bits), m (5 bits): from bit 31 down, (s1, e1, m1),
 * (s2, e2, m2), (s3, e3, m3), then two bits p. An element is T = sum(s + e + m) bits, element k at bit
 * 8 r3 + k T (big-endian bit order). Its components are the top 32 bits of the stream at the element's bit, at
 * + T1 and at + T1 + T2 (Tc = sc + ec + mc), each decoded by ea_comp below. Then
 *   w = sqrt(max(0, 1 - c1^2 - c2^2 - c3^2)) (frsqest + fi + one Newton step, times the argument)
 * and the quadword (c1, c2, c3 with w inserted at index p) is stored at r5 + 48 idx[k]: a joint's 48-byte
 * (rotation, translation, scale) record; the caller @0x10D78 runs it with r5 + 0, + 16, + 32. The w of a
 * translation or a scale is computed the same way (the caller's spec puts it where it is not read).
 * The loop runs ceil(n / 4) times, four elements each (elements n .. 4 ceil(n / 4) - 1 too, with their index table
 * entries), storing elements 0, 1, 3, 2 of each group in that order. It saves r80-r127 at r1 - 16 (k - 79) and
 * restores them; no other local store write. Bit operations follow the SPU's rules (rot by count & 31; rotm, shl
 * and rotma with counts of 32 and more give 0 or the sign). Float work is the runtime's own helpers, lane-wise: the
 * four elements of a group in the four lanes. Declines when an output quadword overlaps what the kernel reads (the
 * stream, the index table, the spec) or the stack save area. */
static inline uint32_t rotl32(uint32_t x, uint32_t c) { c &= 31; return c ? (x << c) | (x >> (32 - c)) : x; }
static inline uint32_t shl_(uint32_t x, uint32_t c) { c &= 63; return c > 31 ? 0 : x << c; }
static inline uint32_t rotm_(uint32_t x, uint32_t c) { c = (0u - c) & 63; return c > 31 ? 0 : x >> c; }
static inline uint32_t rotma_(uint32_t x, uint32_t c) { c = (0u - c) & 63; return (uint32_t)((int32_t)x >> (c > 31 ? 31 : c)); }

/* the 128 bits of the stream from bit B (big-endian), as two lqd at (B >> 3) and (B >> 3) + 16 and the rotates */
static inline unsigned __int128 ea_q(const uint8_t* q)   /* a quadword as a big-endian 128-bit number */
{
    uint64_t h, l;
    memcpy(&h, q, 8);
    memcpy(&l, q + 8, 8);
    return (unsigned __int128)__builtin_bswap64(h) << 64 | __builtin_bswap64(l);
}
static inline unsigned __int128 ea_window(const uint8_t* ls, uint32_t B)
{
    const uint32_t a = B >> 3, s = B & 127;
    const unsigned __int128 A = ea_q(ls + LSQ(a));
    return s ? (A << s) | (ea_q(ls + LSQ(a + 16)) >> (128 - s)) : A;
}
/* top 32 bits after shlqbybi + shlqbi by c (bytes (c >> 3) & 31, 16 or more: 0; bits c & 7) */
static inline unsigned __int128 shlq_(unsigned __int128 x, uint32_t c)
{
    const uint32_t by = (c >> 3) & 31, bi = c & 7;
    if (by >= 16) return 0;
    x <<= 8 * by;
    return x << bi;
}

/* index k of group g: lqd + rotqby at r6 + 8 g read 8 bytes wrapping inside that quadword */
static inline uint32_t ea_idx(const uint8_t* ls, uint32_t r6, uint32_t g, uint32_t k)
{
    const uint32_t a = r6 + 8 * g;
    const uint8_t* q = ls + LSQ(a);
    return (uint32_t)q[(a + 2 * k) & 15] << 8 | q[(a + 2 * k + 1) & 15];
}

/* spu_csflt(v, 155) (x 2^0): the helper converts through double and rounds once, so a lane below 2^24 in
 * magnitude (INT_MIN too: a power of two) is cvtdq2ps exactly; any other vector goes to the helper */
static inline __m128 csflt0_(u128 v)
{
    __m128i A;
    memcpy(&A, &v, 16);
    if (__builtin_expect(_mm_movemask_ps(_mm_castsi128_ps(_mm_cmpgt_epi32(_mm_abs_epi32(A), _mm_set1_epi32(1 << 24)))), 0))
        return F(spu_csflt(v, 155));
    return _mm_cvtepi32_ps(A);
}

typedef struct { uint32_t s, e, m; } ea_field;

/* One component from the top 32 bits w: e > 0 a small float (sign s bits, e exponent bits biased by
 * 2^(e - 1) - 1 against 127, m mantissa bits at the top of the mantissa: m > 23 drops them, as shl does); e = 0 a
 * signed fixed-point value (m bits plus the sign) times 1 / (2^m - 1) (frest, fi, one Newton step; 0 when m = 0).
 * The float case is the bits themselves (int_out, is_int = 1), the fixed case the integer for csflt and its divisor
 * for cuflt (computed by the caller in lanes). */
static inline void ea_comp(uint32_t w, ea_field f, uint32_t* bits, uint32_t* ival, uint32_t* dval)
{
    const uint32_t r100 = rotl32(w, f.s), r101 = rotl32(r100, f.e);
    const uint32_t E = r101 & rotm_(0xFFFFFFFFu, f.e - 32);
    const uint32_t ex = shl_(E + (128u - shl_(1u, f.e - 1)), 23);
    const uint32_t M = rotl32(r101, f.m) & rotm_(0xFFFFFFFFu, f.m - 32);
    const uint32_t S = shl_(r100 & rotm_(0xFFFFFFFFu, f.s - 32), 31);
    *bits = ex | shl_(M, 23 - f.m) | S;
    *ival = M | rotma_(S, f.m - 31);
    *dval = rotm_(0x7FFFFFFFu, f.m - 31);
}

static int ea_13100(spu_context* ctx)
{
    uint8_t* ls = ctx->ls;
    const uint32_t n = ctx->gpr[4]._u32[0];
    if (n == 0) return 1;   /* brz $r4: straight to the return, nothing written */
    const uint32_t r1 = ctx->gpr[1]._u32[0], r3 = ctx->gpr[3]._u32[0], r5 = ctx->gpr[5]._u32[0];
    const uint32_t r6 = ctx->gpr[6]._u32[0], r7 = ctx->gpr[7]._u32[0];
    const uint32_t spec = (uint32_t)ls[LSM(r7)] << 24 | (uint32_t)ls[LSM(r7 + 1)] << 16 |
                          (uint32_t)ls[LSM(r7 + 2)] << 8 | ls[LSM(r7 + 3)];
    const ea_field f1 = { (spec >> 31) & 1, (spec >> 27) & 15, (spec >> 22) & 31 };
    const ea_field f2 = { (spec >> 21) & 1, (spec >> 17) & 15, (spec >> 12) & 31 };
    const ea_field f3 = { (spec >> 11) & 1, (spec >> 7) & 15, (spec >> 2) & 31 };
    const uint32_t T1 = f1.s + f1.e + f1.m, T2 = f2.s + f2.e + f2.m, T = T1 + T2 + f3.s + f3.e + f3.m;
    const uint32_t iters = (n + 3) >> 2, bit0 = r3 << 3;
    /* what it reads: the stream bytes, the index table (8 bytes a group, quadword-wrapped), the spec, the stack area */
    const int64_t s_lo = (int64_t)LSQ(bit0 >> 3), s_n = (int64_t)(((uint64_t)T * 4 * iters + 7) >> 3) + 48;
    if ((uint64_t)T * 4 * iters >= ((uint64_t)SPU_LS_SIZE << 3) || s_lo + s_n > SPU_LS_SIZE) return 0;
    if (LSQ(r6) + 8u * iters + 16 > SPU_LS_SIZE || LSQ(r1 - 0x300u) + 0x300 > SPU_LS_SIZE) return 0;
    for (uint32_t g = 0; g < iters; g++)
        for (uint32_t k = 0; k < 4; k++) {
            const uint32_t idx = ea_idx(ls, r6, g, k);
            const int64_t o = (int64_t)LSQ(r5 + 48 * idx);
            if (ovl(o, 16, s_lo, s_n) || ovl(o, 16, LSQ(r6), 8 * iters + 16) || ovl(o, 16, LSQ(r7), 32) ||
                ovl(o, 16, LSQ(r1 - 0x300u), 0x300))
                return 0;
        }
    for (int k = 80; k <= 127; k++) stq(ls, r1 - 16 * (uint32_t)(k - 79), ctx->gpr[k]);
    const uint32_t kk = ~spec & 3;   /* w goes to lane p = spec & 3 */
    const __m128 one = fbits(0x3F800000u), half = fbits(0x3F000000u), zero = _mm_setzero_ps();
    /* the fixed-point components' 1 / (2^m - 1): the same in every lane and group (cuflt, frest, fi, one Newton step;
     * 0 when the divisor is 0), so computed once */
    const ea_field fs[3] = { f1, f2, f3 };
    __m128 rcp[3];
    for (int c = 0; c < 3; c++) {
        const u128 d = spu_cuflt(sp(rotm_(0x7FFFFFFFu, fs[c].m - 31)), 155);
        const u128 y = spu_fi(d, spu_frest(d));
        rcp[c] = d._u32[0] ? fma_(fnms_(F(d), F(y), one), F(y), F(y)) : zero;
    }
    for (uint32_t g = 0; g < iters; g++) {
        u128 cb[3], ci[3], cd[3];
        __m128 cv[3];
        uint32_t oaddr[4];
        for (uint32_t k = 0; k < 4; k++) {
            const uint32_t B = bit0 + (4 * g + k) * T;
            const unsigned __int128 win = ea_window(ls, B);
            const uint32_t w1 = (uint32_t)(win >> 96), w2 = (uint32_t)(shlq_(win, T1) >> 96),
                           w3 = (uint32_t)(shlq_(shlq_(win, T1), T2) >> 96);
            ea_comp(w1, f1, &cb[0]._u32[k], &ci[0]._u32[k], &cd[0]._u32[k]);
            ea_comp(w2, f2, &cb[1]._u32[k], &ci[1]._u32[k], &cd[1]._u32[k]);
            ea_comp(w3, f3, &cb[2]._u32[k], &ci[2]._u32[k], &cd[2]._u32[k]);
            oaddr[k] = r5 + 48 * ea_idx(ls, r6, g, k);
        }
        for (int c = 0; c < 3; c++)
            cv[c] = fs[c].e ? F(cb[c]) : fm_(csflt0_(ci[c]), rcp[c]);
        __m128 a = fnms_(cv[0], cv[0], one);
        a = fnms_(cv[1], cv[1], a);
        a = fnms_(cv[2], cv[2], a);
        a = _mm_blendv_ps(a, zero, fcgt_(zero, a));
        const __m128 y0 = F(spu_fi(U(a), spu_frsqest(U(a))));
        const __m128 h = fm_(y0, half), p = fm_(a, y0);
        const __m128 y1 = fma_(h, fnms_(p, y0, one), y0);
        const u128 w = U(fm_(y1, a));
        const u128 v0 = U(cv[0]), v1 = U(cv[1]), v2 = U(cv[2]);
        static const uint8_t order[4] = { 0, 1, 3, 2 };
        for (int t = 0; t < 4; t++) {
            const int l = order[t];
            const uint32_t c1 = v0._u32[l], c2 = v1._u32[l], c3 = v2._u32[l], wl = w._u32[l];
            u128 q;
            /* lane masks of the SPU code: 0xE0000000 << kk, << kk + 1, << kk + 2, bit 31 each */
            const int m1 = kk <= 2, m2 = kk <= 1, m3 = kk == 0;
            const uint32_t t236 = m1 ? c1 : wl, t237 = m1 ? wl : c1;
            const uint32_t t240 = m2 ? c2 : t237, t242 = m2 ? t237 : c2;
            const uint32_t t245 = m3 ? c3 : t242, t246 = m3 ? t242 : c3;
            q._u32[0] = t236;
            q._u32[1] = t240;
            q._u32[2] = t245;
            q._u32[3] = t246;
            stq(ls, oaddr[l], q);
        }
    }
    return 1;
}

/* ---- 0x12438: not written yet (an earlier change read it; the RE notes "An earlier change") ----
 * The keyframe sampler: per element a key-presence bitmask (four words masked with r4-r7 / r8-r11, popcounts by
 * cntb + sumb) locates the element's previous key in a packed stream (r3 = its bit address), two keys are decoded
 * with the same (s, e, m) packing as 0x13100 and blended by the factor r13 (slerp-style for rotations when r22 = 1,
 * threshold 0.999 = 0x3F7FBE77; lerp otherwise), written at r18 + 48 idx (index table r19). Its gate (slot 76) is in
 * the lift so its inputs can be recorded (KZ2_NATIVE_REC); the stub declines, and its flag
 * KZ2_NATIVE_JOB_EDGEANIM_KEYS is separate so KZ2_NATIVE_JOB_EDGEANIM=1 does not count fallbacks for it. */
static int ea_12438(spu_context* ctx)
{
    (void)ctx;
    return 0;
}

const kz2_native_entry kz2_native_edgeanim[] = {
    { 75, "KZ2_NATIVE_JOB_EDGEANIM", "Anim.EdgeAnim", "job_00d95d80", 0x13100u, ea_13100, "ea_13100", 0, 0, 0 },
    { 76, "KZ2_NATIVE_JOB_EDGEANIM_KEYS", "Anim.EdgeAnim", "job_00d95d80", 0x12438u, ea_12438, "ea_12438", 0, 0, 0 },
};
const unsigned kz2_native_edgeanim_n = sizeof kz2_native_edgeanim / sizeof kz2_native_edgeanim[0];
