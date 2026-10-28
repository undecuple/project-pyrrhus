/* From Project Helghast tools/spu/test_spu_ls_gate.c. ps3recomp v0.18.0: upstream #445 runs the WWS probes
 * only with SPU_WWS_PROBE (g_spu_wws_probe), so the probe checks turn it on, and a check that the caps do not arm the
 * gates while it is off. */
/* Patch 1100 host test: the per-function LS gates (spu_ls_dbg_armed, SPU_LS_LOCALS) with the WWS
 * range probes behind them. Self-contained (stubs below). Checks:
 *  1. the gate bits: bit 0 (loads) for SPU_LS_LOWREAD undecided/on, a watchpoint, the read probe below its cap; bit 1
 *     (stores) for a watchpoint, SPU_SMC_WATCH undecided/on, the code probe below its cap; 0 with all of them off;
 *  2. below the caps, an image-2 policy-mode load of 0xDF0..0xEAF and a store to 0x1320 through the fast accessors
 *     still reach the probes (the counters count up); past the caps they take the fast path;
 *  3. the fast and the full accessors read and write the same bytes for every 16-byte line and every misaligned
 *     address of a random LS, with the gates open and closed. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "spu_context.h"

int g_spu_ls_watch_n = 0;
static int s_watch_hits;
void spu_ls_watch_slow(uint32_t lsa, int is_write, const uint8_t* p, uint32_t pc, uint32_t lr)
{
    (void)lsa, (void)is_write, (void)p, (void)pc, (void)lr;
    s_watch_hits++;
}

static u128 splat(uint32_t x)
{
    u128 v;
    for (int k = 0; k < 4; k++) v._u32[k] = x;
    return v;
}
static int fails;
#define CHECK(c, ...)                                                                                                  \
    do {                                                                                                               \
        if (!(c)) {                                                                                                    \
            fails++;                                                                                                   \
            printf("FAIL: " __VA_ARGS__);                                                                              \
            printf("\n");                                                                                              \
        }                                                                                                              \
    } while (0)

int main(void)
{
#ifndef SPU_WWS_READ_CAP
    printf("SKIP: no SPU_WWS_READ_CAP (patch 1100 not applied)\n");
    return 0;
#else
    /* 1. gate bits */
    g_spu_ls_probe = 0, g_spu_smc_watch = 0, g_spu_ls_watch_n = 0;
    g_wws_read_probe = SPU_WWS_READ_CAP, g_wws_code_probe = SPU_WWS_CODE_CAP;
    CHECK(spu_ls_dbg_armed() == 0, "all off: %d", spu_ls_dbg_armed());
    g_spu_ls_probe = -1;
    CHECK(spu_ls_dbg_armed() == 1, "LOWREAD undecided: %d", spu_ls_dbg_armed());
    g_spu_ls_probe = 0, g_spu_smc_watch = 1;
    CHECK(spu_ls_dbg_armed() == 2, "SMC watch: %d", spu_ls_dbg_armed());
    g_spu_smc_watch = 0, g_spu_ls_watch_n = 2;
    CHECK(spu_ls_dbg_armed() == 3, "watchpoint: %d", spu_ls_dbg_armed());
    g_spu_ls_watch_n = 0, g_wws_read_probe = SPU_WWS_READ_CAP - 1;
    CHECK(spu_ls_dbg_armed() == 1, "read probe below cap: %d", spu_ls_dbg_armed());
    g_wws_read_probe = SPU_WWS_READ_CAP, g_wws_code_probe = 0;
    CHECK(spu_ls_dbg_armed() == 2, "code probe below cap: %d", spu_ls_dbg_armed());
    g_spu_wws_probe = 0, g_wws_read_probe = 0;
    CHECK(spu_ls_dbg_armed() == 0, "probes below cap but SPU_WWS_PROBE off: %d", spu_ls_dbg_armed());
    g_spu_wws_probe = 1;

    /* 2. the probes below their caps, through the fast accessors */
    spu_context* ctx = calloc(1, sizeof *ctx);
    ctx->ls = calloc(1, SPU_LS_SIZE);
    ctx->image_id = 2;
    ctx->policy_mode = 1;
    FILE* keep = stderr;
    stderr = fopen("/dev/null", "w"); /* the probes print */
    g_wws_read_probe = 0, g_wws_code_probe = 0;
    {
        SPU_LS_LOCALS
        for (int i = 0; i < 100; i++) (void)spu_ls_read128_l(ctx, spu__ls, spu__lsdbg, 0xDF0 + 4 * (i % 48));
        for (int i = 0; i < 10; i++) spu_ls_write128_l(ctx, spu__ls, spu__lsdbg, 0x1320, splat(0x4000u + i));
    }
    CHECK(g_wws_read_probe == SPU_WWS_READ_CAP && g_wws_code_probe == SPU_WWS_CODE_CAP,
          "probes below the caps did not count: %d %d", g_wws_read_probe, g_wws_code_probe);
    {
        SPU_LS_LOCALS
        CHECK(spu__lsdbg == 0, "gates still set past the caps: %d", spu__lsdbg);
        (void)spu_ls_read128_l(ctx, spu__ls, spu__lsdbg, 0xDF0);
        spu_ls_write128_l(ctx, spu__ls, spu__lsdbg, 0x1320, splat(1));
    }
    CHECK(g_wws_read_probe == SPU_WWS_READ_CAP && g_wws_code_probe == SPU_WWS_CODE_CAP, "counters moved past the caps");
    fclose(stderr);
    stderr = keep;

    /* 3. fast vs full accessors */
    ctx->image_id = 5;
    ctx->policy_mode = 0;
    uint8_t* ref = malloc(SPU_LS_SIZE);
    srand(73);
    for (int i = 0; i < SPU_LS_SIZE; i++) ctx->ls[i] = (uint8_t)rand();
    memcpy(ref, ctx->ls, SPU_LS_SIZE);
    unsigned bad = 0;
    for (int open = 0; open < 2; open++) {
        g_wws_read_probe = open ? 0 : SPU_WWS_READ_CAP;
        g_wws_code_probe = open ? 0 : SPU_WWS_CODE_CAP;
        SPU_LS_LOCALS
        for (uint32_t a = 0; a < SPU_LS_SIZE + 64; a += 7) {
            u128 x = spu_ls_read128_l(ctx, spu__ls, spu__lsdbg, a), y = spu_ls_read128(ctx, a);
            if (memcmp(&x, &y, 16)) bad++;
            u128 v = splat(a * 2654435761u);
            v._u32[1] ^= 0x5A5A5A5Au;
            spu_ls_write128_l(ctx, spu__ls, spu__lsdbg, a, v);
            uint8_t* p = ref + (a & (SPU_LS_MASK & ~0xFu));
            for (int k = 0; k < 4; k++)
                for (int b = 0; b < 4; b++) p[4 * k + b] = (uint8_t)(v._u32[k] >> (24 - 8 * b));
        }
    }
    CHECK(!bad && !memcmp(ref, ctx->ls, SPU_LS_SIZE), "fast and full accessors differ (%u reads)", bad);
    if (fails) {
        printf("FAIL (%d)\n", fails);
        return 1;
    }
    printf("PASS\n");
    return 0;
#endif
}
