/* Patch 1095 host test: the SPURS workload teardown and priority transitions (runtime/spu/spurs_wkl_teardown.h) on
 * a fake 4 KB CellSpurs instance, checked through the default kernel's own selection (kz3_ksel, kz3_kleave in
 * spurs_kern_sched.h): a shut-down workload is never picked or kept by a poll, Wait only reports removable once no
 * SPU holds it, Remove is BUSY until then and clears the instance bytes so the wid can be added again, and
 * SetPriorities' guest bytes steer the pick. Negative controls: the same scenarios run again with the old stubs
 * (Shutdown and Wait no-ops, Remove freeing nothing in the instance, SetPriorities only on the host copy) and with a
 * broken Remove that ignores CURCONT; each must fail some checks. */
#include <stdio.h>
#include <string.h>
#include "spurs_wkl_teardown.h"

static int g_fail, g_quiet;
#define CHECK(c, ...) do { if (!(c)) { g_fail++; if (!g_quiet) { printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } } while (0)

/* The operations under test: the patch's (spurs_wkl_teardown.h) or a stub standing in for the old behaviour. */
typedef struct {
    const char* name;
    int (*shutdown)(uint8_t*, uint32_t);
    int (*wait_step)(uint8_t*, uint32_t, int);
    int (*remove)(uint8_t*, uint32_t, int);
    void (*set_priorities)(uint8_t*, uint32_t, const uint8_t[8]);
} Ops;
static const Ops k_real = { "patch 1095", kz2_wkl_shutdown, kz2_wkl_wait_step, kz2_wkl_remove, kz2_wkl_set_priorities };
/* the stubs before patch 1095: Shutdown and Wait return OK and do nothing, Remove only freed the host row (nothing in
 * the instance), SetPriorities only wrote the host copy */
static int stub_shutdown(uint8_t* S, uint32_t w) { (void)S; (void)w; return KZ2_WKL_OK; }
static int stub_wait(uint8_t* S, uint32_t w, int hb) { (void)S; (void)w; (void)hb; return KZ2_WKL_OK; }
static int stub_remove(uint8_t* S, uint32_t w, int hb) { (void)S; (void)w; (void)hb; return KZ2_WKL_OK; }
static void stub_prio(uint8_t* S, uint32_t w, const uint8_t p[8]) { (void)S; (void)w; (void)p; }
static const Ops k_stub = { "old stubs", stub_shutdown, stub_wait, stub_remove, stub_prio };
/* a broken Remove: clears the instance bytes while an SPU still holds the workload */
static int broken_remove(uint8_t* S, uint32_t w, int hb) { (void)hb; const uint8_t c = S[KZ3_K_CURCONT + w]; S[KZ3_K_CURCONT + w] = 0;
                                                          const int r = kz2_wkl_remove(S, w, 0); S[KZ3_K_CURCONT + w] = c; return r; }
static const Ops k_broken = { "Remove ignoring CURCONT", kz2_wkl_shutdown, kz2_wkl_wait_step, broken_remove, kz2_wkl_set_priorities };

static uint8_t S[4096];

/* What cellSpursAddWorkload publishes (cellSpurs.c): state 2, contention limits, ENABLED bit, priorities. */
static void add(uint32_t wid, uint8_t prio, uint8_t maxc)
{
    uint8_t* info = S + KZ3_K_INFO1 + wid * KZ3_K_INFO_SZ;
    info[0x14] = (uint8_t)wid;
    for (int b = 0; b < 8; b++) info[0x18 + b] = prio;
    S[KZ3_K_STATE1 + wid] = 2;
    S[KZ3_K_MINCONT + wid] = 1;
    S[KZ3_K_MAXCONT + wid] = maxc;
    uint32_t e = kz3_k_be32(S + KZ3_K_ENABLED) | (0x80000000u >> wid);
    S[KZ3_K_ENABLED] = (uint8_t)(e >> 24); S[KZ3_K_ENABLED + 1] = (uint8_t)(e >> 16);
    S[KZ3_K_ENABLED + 2] = (uint8_t)(e >> 8); S[KZ3_K_ENABLED + 3] = (uint8_t)e;
}
static void reset(void) { memset(S, 0, sizeof S); S[KZ3_K_FLAG + 0x0C] = S[KZ3_K_FLAG + 0x0D] = S[KZ3_K_FLAG + 0x0E] = S[KZ3_K_FLAG + 0x0F] = 0xFF; S[KZ3_K_FLAG_RCV] = 0xFF; }
static uint32_t pick(uint32_t spu, uint32_t cur) { uint32_t st; return kz3_ksel(S, 0xFFFF, spu, cur, 0, 0, &st); }
static uint32_t poll(uint32_t spu, uint32_t cur) { uint32_t st; return kz3_ksel(S, 0xFFFF, spu, cur, 1, 0, &st); }

static void test_teardown(const Ops* o)
{
    reset();
    add(7, 1, 5);                       /* jm_post's wid in the game */
    S[KZ3_K_READY1 + 7] = 3;
    S[KZ3_K_IDLE2 + 7] = 2;
    S[KZ3_K_SIGNAL1] |= 0x01;           /* wid 7's signal bit (bit 15-7 of the be16) */
    CHECK(pick(0, KZ3_KSEL_NONE) == 7, "wid 7 picked before shutdown");
    CHECK(S[KZ3_K_CURCONT + 7] == 1, "contention 1 after the pick");
    CHECK(o->remove(S, 7, 0) == KZ2_WKL_BUSY, "Remove BUSY while an SPU holds it");
    CHECK(o->wait_step(S, 7, 0) == KZ2_WKL_STAT, "Wait before Shutdown is STAT");

    CHECK(o->shutdown(S, 7) == KZ2_WKL_OK, "Shutdown ok");
    CHECK(S[KZ3_K_STATE1 + 7] == 3, "state 3 after Shutdown");
    CHECK((kz3_k_be32(S + KZ3_K_ENABLED) & (0x80000000u >> 7)) == 0, "ENABLED bit cleared");
    CHECK(o->shutdown(S, 7) == KZ2_WKL_OK && S[KZ3_K_STATE1 + 7] == 3, "second Shutdown leaves it");
    CHECK(pick(1, KZ3_KSEL_NONE) == KZ3_KSEL_NONE, "a shut-down workload is not picked (ready 3)");
    CHECK(poll(0, 7) != 7, "a running module is told to switch at its poll");
    CHECK(S[KZ3_K_CURCONT + 7] == 1, "the polls changed no contention");

    CHECK(o->wait_step(S, 7, 0) == KZ2_WKL_BUSY, "Wait BUSY while CURCONT 1");
    CHECK(o->remove(S, 7, 0) == KZ2_WKL_BUSY, "Remove BUSY while CURCONT 1");
    kz3_kleave(S, 7);                   /* the module returned */
    CHECK(o->wait_step(S, 7, 1) == KZ2_WKL_BUSY, "Wait BUSY while a kernel thread is inside (s_run_wid)");
    CHECK(o->remove(S, 7, 1) == KZ2_WKL_BUSY, "Remove BUSY while a kernel thread is inside");
    CHECK(o->wait_step(S, 7, 0) == KZ2_WKL_OK, "Wait done once nothing holds it");
    CHECK(S[KZ3_K_STATE1 + 7] == 4, "state 4 (removable) after Wait");
    CHECK(o->wait_step(S, 7, 0) == KZ2_WKL_OK, "Wait again is ok");

    CHECK(o->remove(S, 7, 0) == KZ2_WKL_OK, "Remove ok");
    CHECK(S[KZ3_K_STATE1 + 7] == 0 && S[KZ3_K_READY1 + 7] == 0 && S[KZ3_K_IDLE2 + 7] == 0, "state, ready, idle cleared");
    CHECK((S[KZ3_K_SIGNAL1] & 0x01) == 0, "signal bit cleared");
    CHECK(pick(0, KZ3_KSEL_NONE) == KZ3_KSEL_NONE, "nothing to pick after Remove");

    add(7, 1, 5);                       /* the level's jm_post added again on the same wid */
    CHECK(pick(0, KZ3_KSEL_NONE) == KZ3_KSEL_NONE, "re-added workload with no stale ready count is not picked");
    S[KZ3_K_READY1 + 7] = 1;
    CHECK(pick(0, KZ3_KSEL_NONE) == 7, "re-added workload runs on its new kick");

    /* the other workloads are untouched by wid 7's teardown */
    reset();
    add(3, 1, 5); add(7, 1, 5);
    S[KZ3_K_READY1 + 3] = 1; S[KZ3_K_READY1 + 7] = 1;
    CHECK(o->shutdown(S, 7) == KZ2_WKL_OK, "Shutdown 7");
    CHECK(pick(0, KZ3_KSEL_NONE) == 3, "wid 3 still picked");
    CHECK(o->wait_step(S, 7, 0) == KZ2_WKL_OK && o->remove(S, 7, 0) == KZ2_WKL_OK, "7 removed");
    CHECK(S[KZ3_K_STATE1 + 3] == 2 && S[KZ3_K_READY1 + 3] == 1 && (kz3_k_be32(S + KZ3_K_ENABLED) & (0x80000000u >> 3)),
          "wid 3's bytes unchanged");
    CHECK(o->shutdown(S, 9) == KZ2_WKL_STAT, "Shutdown of an empty wid is STAT");
    CHECK(o->shutdown(S, 16) == KZ2_WKL_STAT && o->remove(S, 16, 0) == KZ2_WKL_STAT, "wid 16 is STAT");
}

static void test_priorities(const Ops* o)
{
    reset();
    add(2, 1, 5); add(5, 1, 5);
    S[KZ3_K_READY1 + 2] = 1; S[KZ3_K_READY1 + 5] = 1;
    CHECK(pick(0, KZ3_KSEL_NONE) == 2, "same priority: the lowest wid");
    S[KZ3_K_CURCONT + 2] = 0;
    const uint8_t p5[8] = { 0, 3, 3, 3, 3, 3, 3, 3 };   /* wid 5: not on SPU 0, low priority elsewhere */
    const uint8_t p2[8] = { 8, 8, 8, 8, 8, 8, 8, 8 };
    o->set_priorities(S, 5, (const uint8_t[8]){ 1, 1, 1, 1, 1, 1, 1, 1 });
    o->set_priorities(S, 2, p2);
    CHECK(pick(1, KZ3_KSEL_NONE) == 5, "wid 5 (priority 1) beats wid 2 (8) after SetPriorities");
    S[KZ3_K_CURCONT + 5] = 0;
    o->set_priorities(S, 5, p5);
    CHECK(S[KZ3_K_INFO1 + 5 * KZ3_K_INFO_SZ + 0x18] == 0 && S[KZ3_K_INFO1 + 5 * KZ3_K_INFO_SZ + 0x1F] == 3, "bytes at wklInfo+0x18");
    CHECK(pick(0, KZ3_KSEL_NONE) == 2, "priority 0 keeps wid 5 off SPU 0");
    S[KZ3_K_CURCONT + 2] = 0;
    S[KZ3_K_READY1 + 2] = 0;
    CHECK(pick(0, KZ3_KSEL_NONE) == KZ3_KSEL_NONE, "SPU 0 idles rather than run wid 5");
    CHECK(pick(1, KZ3_KSEL_NONE) == 5, "SPU 1 runs wid 5");
    CHECK(S[KZ3_K_INFO1 + 6 * KZ3_K_INFO_SZ + 0x18] == 0 && S[KZ3_K_INFO1 + 4 * KZ3_K_INFO_SZ + 0x1F] == 0, "neighbours untouched");
}

static int run(const Ops* o, int quiet)
{
    g_fail = 0; g_quiet = quiet;
    test_teardown(o);
    test_priorities(o);
    return g_fail;
}

int main(void)
{
    const int f = run(&k_real, 0);
    const int fs = run(&k_stub, 1), fb = run(&k_broken, 1);
    printf("negative controls: %s fails %d checks, %s fails %d\n", k_stub.name, fs, k_broken.name, fb);
    const int bad = f != 0 || fs == 0 || fb == 0;
    printf("%s test_spurs_teardown (%d failures with patch 1095)\n", bad ? "FAIL" : "PASS", f);
    return bad;
}
