/* native_simd.h -- what the native Gfx.Post passes share:
 * local-store access as the SPU does it, and the runtime's SPU float helpers' own SSE fast paths inline.
 *
 * Exactness rule: each wrapper computes what the helper's fast path computes (the same SSE instruction)
 * and calls the helper itself (spu_helpers.h) for any vector the helper would treat specially, so a wrapper returns
 * the helper's bits for every input:
 *   fm_/fa_/fs_   mulps/addps/subps; a result lane with biased exponent 255 sends the vector to spu_fm/fa/fs (KZ3
 *                 patch 1105: an infinity or NaN operand always gives an exponent-255 result, so the result's mask is
 *                 the helper's own test)
 *   fma_/fnms_    spu__fma4's -mfma path (KZ3 1097/1106): one fused multiply-add when every result lane is normal or
 *                 zero and the slow-cg mode is off; otherwise spu_fma/spu_fnms
 *   fcgt_         cmpgtps unless an operand lane has exponent 255 (spu_fcgt)
 *   cfltu_        x 2^(173-i8) truncated, for i8 <= 173 (a power-of-two scale >= 1: the float product is exact); lanes
 *                 with exponent 255 or a product at or above 2^31 send the vector to spu_cfltu
 * The helpers are lane-wise (each result lane depends only on the same lane of the operands), so the native passes
 * may put any pixel's value in any lane.
 */
#ifndef KZ2_NATIVE_SIMD_H
#define KZ2_NATIVE_SIMD_H

#include "kz2_native_jobs.h"
#include "spu_helpers.h"

#include <smmintrin.h>
#include <string.h>

#define LSM(a) ((a) & SPU_LS_MASK)
#define LSQ(a) ((a) & (SPU_LS_MASK & ~0xFu))

/* the quadword at LS a (masked as lqd/lqx do) as the runtime's u128 (_u32[0] = SPU word 0), and back */
static inline u128 ldq(const uint8_t* ls, uint32_t a)
{
    const __m128i bs = _mm_set_epi8(12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3);
    __m128i v = _mm_shuffle_epi8(_mm_loadu_si128((const __m128i*)(ls + LSQ(a))), bs);
    u128 r;
    memcpy(&r, &v, 16);
    return r;
}

static inline void stq(uint8_t* ls, uint32_t a, u128 x)
{
    const __m128i bs = _mm_set_epi8(12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3);
    __m128i v;
    memcpy(&v, &x, 16);
    _mm_storeu_si128((__m128i*)(ls + LSQ(a)), _mm_shuffle_epi8(v, bs));
}

static inline uint32_t be32(const uint8_t* p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

/* The SPU word at byte address a as `lqd/lqx` + `rotqby` by a read it: bytes a, a+1, a+2, a+3 of the quadword at
 * a & ~15, wrapping inside that quadword. */
static inline uint32_t rdw(const uint8_t* ls, uint32_t a)
{
    const uint8_t* q = ls + LSQ(a);
    return (uint32_t)q[a & 15] << 24 | (uint32_t)q[(a + 1) & 15] << 16 | (uint32_t)q[(a + 2) & 15] << 8 |
           q[(a + 3) & 15];
}

static inline u128 sp(uint32_t v)
{
    return spu_splat_u32(v);
}

/* NSIMD_SLOW(k): a hook in each wrapper's helper branch (k: 0 fm, 1 fa, 2 fs, 3 fma, 4 fnms, 5 fms, 6 fcgt, 7 cfltu,
 * 8 rsq, 9 cflts142); empty unless a host test defines it (tools/spu/test_vjlight.c counts them) */
#ifndef NSIMD_SLOW
#define NSIMD_SLOW(k) ((void)0)
#endif

/* the wrappers' fast paths are forced inline (NSI) and each helper call sits in its own cold out-of-line
 * function (NSC). Before, GCC outlined every wrapper whole (the inlined helper made it too big), one copy per TU: under
 * the Windows x64 ABI each call passed its vectors through memory, saved xmm6/xmm7 and cleared the scratch registers,
 * around one mulps (spu 33 prof: fm_/fma_/fcgt_/fa_/rsq_ ~16 % of VertexJob's samples). Same instructions, same bits. */
#define NSI static inline __attribute__((always_inline))
#define NSC static __attribute__((noinline, cold, unused))

NSI __m128 F(u128 x) { __m128 r; memcpy(&r, &x, 16); return r; }
NSI u128 U(__m128 x) { u128 r; memcpy(&r, &x, 16); return r; }
NSI __m128 fbits(uint32_t v) { return _mm_castsi128_ps(_mm_set1_epi32((int)v)); }

NSI int e255(__m128 r)   /* a lane with biased exponent 255 */
{
    const __m128i e = _mm_set1_epi32(0x7F800000);
    return _mm_movemask_ps(_mm_castsi128_ps(_mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(r), e), e)));
}
NSC __m128 fm_slow(__m128 a, __m128 b) { NSIMD_SLOW(0); return F(spu_fm(U(a), U(b))); }
NSC __m128 fa_slow(__m128 a, __m128 b) { NSIMD_SLOW(1); return F(spu_fa(U(a), U(b))); }
NSC __m128 fs_slow(__m128 a, __m128 b) { NSIMD_SLOW(2); return F(spu_fs(U(a), U(b))); }
NSC __m128 fma_slow(__m128 a, __m128 b, __m128 c) { NSIMD_SLOW(3); return F(spu_fma(U(a), U(b), U(c))); }
NSC __m128 fnms_slow(__m128 a, __m128 b, __m128 c) { NSIMD_SLOW(4); return F(spu_fnms(U(a), U(b), U(c))); }
NSC __m128 fms_slow(__m128 a, __m128 b, __m128 c) { NSIMD_SLOW(5); return F(spu_fms(U(a), U(b), U(c))); }
NSC __m128 fcgt_slow(__m128 a, __m128 b) { NSIMD_SLOW(6); return F(spu_fcgt(U(a), U(b))); }
NSC __m128i cfltu_slow(__m128 x, int i8)
{
    NSIMD_SLOW(7);
    const u128 r = spu_cfltu(U(x), i8);
    __m128i v;
    memcpy(&v, &r, 16);
    return v;
}
NSC __m128 rsq_slow(__m128 l) { const u128 u = U(l); NSIMD_SLOW(8); return F(spu_fi(u, spu_frsqest(u))); }
NSC u128 cflts142_slow(__m128 x) { NSIMD_SLOW(9); return spu_cflts(U(x), 142); }

NSI __m128 fm_(__m128 a, __m128 b)   /* spu_fm: mulps, exponent-255 result lanes recomputed */
{
    const __m128 r = _mm_mul_ps(a, b);
    return __builtin_expect(e255(r), 0) ? fm_slow(a, b) : r;
}
NSI __m128 fa_(__m128 a, __m128 b)
{
    const __m128 r = _mm_add_ps(a, b);
    return __builtin_expect(e255(r), 0) ? fa_slow(a, b) : r;
}
NSI __m128 fs_(__m128 a, __m128 b)
{
    const __m128 r = _mm_sub_ps(a, b);
    return __builtin_expect(e255(r), 0) ? fs_slow(a, b) : r;
}
NSI int fma_ok(__m128 r)   /* spu__fma4's test (KZ3 1106): every lane normal or zero */
{
    const __m128i ab = _mm_and_si128(_mm_castps_si128(r), _mm_set1_epi32(0x7FFFFFFF));
    const __m128i nn = _mm_cmpgt_epi32(_mm_add_epi32(ab, _mm_set1_epi32(0x7F000000)), _mm_set1_epi32(-0x01800001));
    return _mm_testz_si128(nn, ab);
}
NSI __m128 fma_(__m128 a, __m128 b, __m128 c)   /* spu_fma = a b + c */
{
#if defined(__FMA__)
    if (__builtin_expect(g_kz3_spu_slowcg == 0, 1)) {
        const __m128 r = _mm_fmadd_ps(a, b, c);
        if (__builtin_expect(fma_ok(r), 1)) return r;
    }
#endif
    return fma_slow(a, b, c);
}
NSI __m128 fnms_(__m128 a, __m128 b, __m128 c)   /* spu_fnms = c - a b (b negated, as spu__fma4 does) */
{
#if defined(__FMA__)
    if (__builtin_expect(g_kz3_spu_slowcg == 0, 1)) {
        const __m128 r = _mm_fmadd_ps(a, _mm_xor_ps(b, _mm_castsi128_ps(_mm_set1_epi32((int)0x80000000u))), c);
        if (__builtin_expect(fma_ok(r), 1)) return r;
    }
#endif
    return fnms_slow(a, b, c);
}
NSI __m128 fms_(__m128 a, __m128 b, __m128 c)   /* spu_fms = a b - c (c negated, as spu__fma4 does) */
{
#if defined(__FMA__)
    if (__builtin_expect(g_kz3_spu_slowcg == 0, 1)) {
        const __m128 r = _mm_fmadd_ps(a, b, _mm_xor_ps(c, _mm_castsi128_ps(_mm_set1_epi32((int)0x80000000u))));
        if (__builtin_expect(fma_ok(r), 1)) return r;
    }
#endif
    return fms_slow(a, b, c);
}
NSI __m128 fcgt_(__m128 a, __m128 b)   /* spu_fcgt: cmpgtps unless an operand lane has exponent 255 */
{
    if (__builtin_expect(e255(a) | e255(b), 0)) return fcgt_slow(a, b);
    return _mm_cmpgt_ps(a, b);
}
/* x > hi ? hi : x, then x > 0 ? x : 0 (fcgt + selb twice, the SPU code's clamp) */
NSI __m128 clamp_(__m128 x, __m128 hi)
{
    x = _mm_blendv_ps(x, hi, fcgt_(x, hi));
    const __m128 z = _mm_setzero_ps();
    return _mm_blendv_ps(z, x, fcgt_(x, z));
}
/* spu_cfltu(x, i8), i8 <= 173: exact when every lane is below 2^31 after the scale and has no exponent 255 (the helper
 * floors max(0, x 2^s) in double; the float product is exact, negative lanes give 0). */
NSI __m128i cfltu_(__m128 x, int i8)
{
    const __m128 p = _mm_mul_ps(x, _mm_set1_ps((float)(1u << (173 - i8))));
    if (__builtin_expect(e255(x) | _mm_movemask_ps(_mm_cmpge_ps(p, _mm_set1_ps(2147483648.0f))), 0))
        return cfltu_slow(x, i8);
    return _mm_cvttps_epi32(_mm_max_ps(p, _mm_setzero_ps()));
}

/* fi(l, frsqest(l)) (native_skinning.c's sk_rsq until an earlier change): the helpers' steps for lanes with a normal exponent (1-254), in float. frsqest:
 * exponent 190 - ((e + 1) >> 1), fraction spu_frsqest_fraction_lut[(l >> 18) & 63]; fi: base = the estimate with its
 * low 10 bits cleared, step = those 10 bits times 2^(exponent - 140) (exact in float: the exponent is 63-189, so a
 * normal power of two times a 10-bit integer; the helper's double gives the same value), y = (l & 0x7FFFF) 2^-19
 * (exact), r = base - step y (mulps, subps: the helper's float steps; the base is positive, no sign flip). A vector
 * with any other exponent (zero, denormal, infinity, NaN) goes to the helpers. */
NSI __m128 rsq_(__m128 l)
{
    const __m128i L = _mm_castps_si128(l);
    const __m128i e = _mm_and_si128(_mm_srli_epi32(L, 23), _mm_set1_epi32(0xFF));
    if (__builtin_expect(_mm_movemask_epi8(_mm_cmpgt_epi32(_mm_sub_epi32(e, _mm_set1_epi32(128)),
                                                            _mm_set1_epi32(126))) |
                             _mm_movemask_epi8(_mm_cmpeq_epi32(e, _mm_setzero_si128())), 0))
        return rsq_slow(l);
    const __m128i fr = _mm_setr_epi32((int)spu_frsqest_fraction_lut[((uint32_t)_mm_cvtsi128_si32(L) >> 18) & 0x3F],
                                      (int)spu_frsqest_fraction_lut[((uint32_t)_mm_extract_epi32(L, 1) >> 18) & 0x3F],
                                      (int)spu_frsqest_fraction_lut[((uint32_t)_mm_extract_epi32(L, 2) >> 18) & 0x3F],
                                      (int)spu_frsqest_fraction_lut[((uint32_t)_mm_extract_epi32(L, 3) >> 18) & 0x3F]);
    const __m128i re = _mm_sub_epi32(_mm_set1_epi32(190), _mm_srli_epi32(_mm_add_epi32(e, _mm_set1_epi32(1)), 1));
    const __m128 base = _mm_castsi128_ps(_mm_or_si128(_mm_slli_epi32(re, 23), _mm_and_si128(fr, _mm_set1_epi32(0x7FFC00))));
    const __m128 p2 = _mm_castsi128_ps(_mm_slli_epi32(_mm_sub_epi32(re, _mm_set1_epi32(13)), 23));   /* 2^(re - 140) */
    const __m128 step = _mm_mul_ps(_mm_cvtepi32_ps(_mm_and_si128(fr, _mm_set1_epi32(0x3FF))), p2);
    const __m128 y = _mm_mul_ps(_mm_cvtepi32_ps(_mm_and_si128(L, _mm_set1_epi32(0x7FFFF))), _mm_set1_ps(0x1p-19f));
    return _mm_sub_ps(base, _mm_mul_ps(step, y));
}
/* spu_cflts(x, 142) (x 2^31, saturating): the float product is exact (a power of two; an overflow to infinity
 * saturates as the helper's double does), cvttps truncates as cvttpd does, a lane at or above 2^31 is 0x7FFFFFFF and
 * one at or below -2^31 cvttps's 0x80000000, the helper's clamp; lanes with exponent 255 go to the helper (round
 * 26b; was the helper's double path for every vector). */
NSI u128 cflts142_(__m128 x)
{
    if (__builtin_expect(e255(x), 0)) return cflts142_slow(x);
    const __m128 p = _mm_mul_ps(x, _mm_set1_ps(2147483648.0f));
    const __m128i r = _mm_blendv_epi8(_mm_cvttps_epi32(p), _mm_set1_epi32(0x7FFFFFFF),
                                      _mm_castps_si128(_mm_cmpge_ps(p, _mm_set1_ps(2147483648.0f))));
    u128 u;
    memcpy(&u, &r, 16);
    return u;
}

static inline int ovl(int64_t a, int64_t an, int64_t b, int64_t bn)
{
    return an > 0 && bn > 0 && a < b + bn && b < a + an;
}

/* SPU word lanes (big-endian in the local store) <-> host lanes */
static inline __m128i bswap32x4(__m128i v)
{
    return _mm_shuffle_epi8(v, _mm_set_epi8(12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3));
}

#endif
