/* Host test (an earlier changeb): the two float steps native_skinning.c does itself instead of calling the runtime's helpers,
 * against the helpers, on every 32-bit input:
 *   sk_rsq(l)        == spu_fi(l, spu_frsqest(l))   (the unit steps' reciprocal square root estimate)
 *   sk_cflts142(x)   == spu_cflts(x, 142)            (x 2^31 truncated, saturating)
 * both with the patch-1071 exponent-255 recompute off and on (g_kz3_spu_xr). Each lane depends only on its own word,
 * so four consecutive inputs go in one vector. No game data. Built by tools/spu/test_native_skin.sh. */
#include "native_skinning.c"
#include <stdio.h>

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

int main(int argc, char** argv)
{
    /* argv[1] = "neg": the negative control (sk_rsq's exponent test off by one: exponent 254 to the fast path is fine,
     * but the fast path for exponent 0 must be caught) */
    const int neg = argc > 1 && !strcmp(argv[1], "neg");
    int fail = 0;
    for (int xr = 0; xr < 2; xr++) {
        g_kz3_spu_xr = xr;
        long bad_r = 0, bad_c = 0;
        for (uint64_t x = 0; x < (1ull << 32); x += 4) {
            const uint32_t w = (uint32_t)x;
            const __m128i v = _mm_setr_epi32((int)w, (int)(w + 1), (int)(w + 2), (int)(w + 3));
            u128 in;
            memcpy(&in, &v, 16);
            const u128 r0 = spu_fi(in, spu_frsqest(in)), c0 = spu_cflts(in, 142);
            u128 r1 = U(sk_rsq(F(in))), c1 = sk_cflts142(F(in));
            if (neg && (w >> 23 & 0xFF) == 0) {   /* the fast formula on exponent 0 (what the test must refuse) */
                r1 = U(_mm_sub_ps(F(in), F(in)));
            }
            bad_r += memcmp(&r0, &r1, 16) != 0;
            bad_c += memcmp(&c0, &c1, 16) != 0;
        }
        printf("xr=%d sk_rsq vs fi(frsqest) all 2^32: %ld vectors differ; sk_cflts142 vs cflts(142): %ld\n", xr, bad_r,
               bad_c);
        fail |= bad_r != 0 || bad_c != 0;
    }
    return fail;
}
