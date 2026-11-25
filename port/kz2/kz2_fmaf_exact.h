/* Killzone 2 (patch 6094): a correctly rounded single-precision fused multiply-add in plain
 * double arithmetic, the exact reference of the [ppu-isa] boot self-test (ppu_isa_ref.cpp). MinGW's software fmaf is
 * not correctly rounded (it sums a split product with several roundings: kz2.exe 0x149081ee0), so the reference must
 * not be the library call. Host test: tools/runtime/test_ppu_vmx_fma.sh compares this with glibc's fmaf.
 *
 * Method: x*y is exact in double (24 + 24 bits < 53). s = xy + z rounds once; TwoSum gives the exact error e
 * (xy + z == s + e). If e == 0, (float)s is the one rounding. Otherwise the true value lies strictly within half a
 * double ulp of s on e's side, so the nearest float to it is the nearest float to s, except when s is exactly the
 * midpoint of two floats: then the float on e's side is the answer (ties-to-even of (float)s would be a second
 * rounding). Round-to-nearest-even host mode assumed (the default; nothing in the port changes it).
 * Build without -mfma and with -ffp-contract=off so xy + z is not fused itself. */
#ifndef KZ2_FMAF_EXACT_H
#define KZ2_FMAF_EXACT_H
#include <math.h>
#include <float.h>

static inline float kz2_fmaf_exact(float x, float y, float z)
{
    const double xy = (double)x * (double)y;
    const double s = xy + (double)z;
    const float f = (float)s;
    if (s - s != 0) return f;                            /* inf or NaN (any NaN: callers compare NaN as NaN) */
    const double bb = s - xy;                            /* TwoSum (Knuth): exact error of the sum */
    const double e = (xy - (s - bb)) + ((double)z - bb);
    if (e == 0) return f;
    const double fd = (double)f;
    if (fd == s) return f;                               /* s is a float: no midpoint within half a double ulp */
    if (isinf(f)) {                                      /* past FLT_MAX: the midpoint to 2^128 is 0x1.ffffffp+127 */
        const double mid = 0x1.ffffffp+127;
        if (fabs(s) == mid && ((e < 0) == (s > 0))) return s > 0 ? FLT_MAX : -FLT_MAX;
        return f;
    }
    const float g = nextafterf(f, s > fd ? INFINITY : -INFINITY);   /* the other float around s */
    if ((fd + (double)g) * 0.5 != s) return f;           /* not a midpoint: (float)s is the nearest */
    return ((e > 0) == (g > f)) ? g : f;                 /* a midpoint: the float on the true value's side */
}
#endif
