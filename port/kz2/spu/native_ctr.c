/* native_ctr.c -- the native gates' call counters: one row per SPU context, claimed on the context's
 * first native call (kz2_native_jobs.h kz2_native_count). Its own file so tools/spu/test_native_ctr.sh links it alone;
 * linked into the game (port/kz2/CMakeLists.txt globs spu/*.c) and into the diff harness (native_*.c). */
#include "kz2_native_jobs.h"

__attribute__((aligned(64))) kz2_native_row g_kz2_native_rows[KZ2_NATIVE_CTXS + 1];
const void* volatile g_kz2_native_keys[KZ2_NATIVE_CTXS];
volatile long g_kz2_native_fb[KZ2_NATIVE_SLOTS];

unsigned kz2_native_row_claim(const void* ctx)
{
    const unsigned h = kz2_native_home(ctx);
    for (unsigned k = 0; k < KZ2_NATIVE_CTXS; k++) {
        const unsigned i = (h + k) & (KZ2_NATIVE_CTXS - 1);
        const void* cur = __atomic_load_n(&g_kz2_native_keys[i], __ATOMIC_ACQUIRE);
        if (cur == ctx) return i;
        if (!cur) {
            const void* none = 0;
            if (__atomic_compare_exchange_n(&g_kz2_native_keys[i], &none, ctx, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE) ||
                none == ctx)
                return i;
        }
    }
    return KZ2_NATIVE_CTXS;
}

