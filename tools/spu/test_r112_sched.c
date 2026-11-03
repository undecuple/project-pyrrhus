/* From Project Helghast tools/spu/test_r112_sched.c, plus the KZ2 patch 7012 cases (default list, switch picker).
 * Patch 1136 host test: kz3_pcore_mask (runtime/spu/kz3_spu_sched.h) on synthetic topologies. No game data. */
#include <stdio.h>
#include "kz3_spu_sched.h"
static int bad;
static void chk(const char* n, uint64_t got, uint64_t want) { if (got != want) { printf("FAIL %s: 0x%llX want 0x%llX\n", n, (unsigned long long)got, (unsigned long long)want); bad++; } else printf("ok   %s\n", n); }
int main(void)
{
    /* i7-12700KF as Proton reports it: 8 P-cores with SMT (class 1, cpus 0-15), 4 E-cores (class 0, cpus 16-19) */
    uint64_t c[12]; int k[12];
    for (int i = 0; i < 8; i++) { c[i] = 3ull << (2 * i); k[i] = 1; }
    for (int i = 0; i < 4; i++) { c[8 + i] = 1ull << (16 + i); k[8 + i] = 0; }
    chk("12700KF", kz3_pcore_mask(c, k, 12), 0xFFFFull);
    /* order of the entries does not matter */
    uint64_t c2[12]; int k2[12];
    for (int i = 0; i < 12; i++) { c2[i] = c[11 - i]; k2[i] = k[11 - i]; }
    chk("reversed", kz3_pcore_mask(c2, k2, 12), 0xFFFFull);
    /* uniform CPU: no restriction */
    int u[12] = {0}; chk("uniform class 0", kz3_pcore_mask(c, u, 12), 0);
    int u1[12]; for (int i = 0; i < 12; i++) u1[i] = 1; chk("uniform class 1", kz3_pcore_mask(c, u1, 12), 0);
    /* three classes (e.g. Core Ultra: P, E, LP-E): the highest only */
    uint64_t t[3] = {0x3, 0xC, 0x30}; int tk[3] = {2, 1, 0};
    chk("three classes", kz3_pcore_mask(t, tk, 3), 0x3ull);
    chk("empty", kz3_pcore_mask(c, k, 0), 0);
    chk("single core", kz3_pcore_mask(c, k, 1), 0);
    /* the top class covers everything that exists: nothing to exclude */
    uint64_t a[2] = {0x1, 0x2}; int ak[2] = {1, 1}; chk("same class two cores", kz3_pcore_mask(a, ak, 2), 0);
    /* scope: default = async threads only, CPU sets; all = every thread; 0 = off; mask = async, affinity mask */
    chk("scope default async", (uint64_t)kz3_sched_scope(NULL, 1), 2);
    chk("scope default kernel", (uint64_t)kz3_sched_scope(NULL, 0), 0);
    chk("scope all kernel", (uint64_t)kz3_sched_scope("all", 0), 2);
    chk("scope off async", (uint64_t)kz3_sched_scope("0", 1), 0);
    chk("scope off all", (uint64_t)kz3_sched_scope("0", 0), 0);
    chk("scope sets async", (uint64_t)kz3_sched_scope("sets", 1), 1);
    chk("scope sets kernel", (uint64_t)kz3_sched_scope("sets", 0), 0);
    /* patch 1140: SPURS instance name list (exact, comma-separated) */
    chk("spurs match default", (uint64_t)kz3_spurs_pcore_match("LoPrio", "LoPrio"), 1);
    chk("spurs no match", (uint64_t)kz3_spurs_pcore_match("LoPrio", "HiPrio"), 0);
    chk("spurs prefix only", (uint64_t)kz3_spurs_pcore_match("LoPrio", "LoPri"), 0);
    chk("spurs longer", (uint64_t)kz3_spurs_pcore_match("LoPri", "LoPrio"), 0);
    chk("spurs list second", (uint64_t)kz3_spurs_pcore_match("HiPrio,LoPrio", "LoPrio"), 1);
    chk("spurs list first", (uint64_t)kz3_spurs_pcore_match("HiPrio,LoPrio", "HiPrio"), 1);
    chk("spurs empty list", (uint64_t)kz3_spurs_pcore_match("", "LoPrio"), 0);
    chk("spurs empty name", (uint64_t)kz3_spurs_pcore_match("LoPrio", ""), 0);
    chk("spurs trailing comma", (uint64_t)kz3_spurs_pcore_match("LoPrio,", "LoPrio"), 1);
    /* KZ2 patch 7012: the default list names KZ2's audio SPURS ("LowPriority") and KZ3's ("LoPrio"), not KZ2's main one ("") */
    chk("default kz2 audio", (uint64_t)kz3_spurs_pcore_match(KZ3_SPU_PCORES_SPURS_DEFAULT, "LowPriority"), 1);
    chk("default kz3 audio", (uint64_t)kz3_spurs_pcore_match(KZ3_SPU_PCORES_SPURS_DEFAULT, "LoPrio"), 1);
    chk("default kz2 main", (uint64_t)kz3_spurs_pcore_match(KZ3_SPU_PCORES_SPURS_DEFAULT, ""), 0);
    chk("default kz3 frame", (uint64_t)kz3_spurs_pcore_match(KZ3_SPU_PCORES_SPURS_DEFAULT, "HiPrio"), 0);
    /* KZ2 patch 7012: the switch picker. KZ3_SPU_PCORES wins; KZ2_SPU_PCORES=1 = on (default scope); default off. */
#define PICK_SCOPE(k3, k2, async) (uint64_t)kz3_sched_scope(kz2_spu_pcores_pick(k3, k2, KZ2_SPU_PCORES_DEFAULT), async)
    chk("kz2 default off (async)", PICK_SCOPE(NULL, NULL, 1), 0);
    chk("kz2 default off (kernel)", PICK_SCOPE(NULL, NULL, 0), 0);
    chk("kz2 default is \"0\"", (uint64_t)strcmp(KZ2_SPU_PCORES_DEFAULT, "0"), 0);
    chk("KZ2_SPU_PCORES=1 async", PICK_SCOPE(NULL, "1", 1), 2);
    chk("KZ2_SPU_PCORES=1 kernel", PICK_SCOPE(NULL, "1", 0), 0);
    chk("KZ2_SPU_PCORES=all kernel", PICK_SCOPE(NULL, "all", 0), 2);
    chk("KZ2_SPU_PCORES=sets async", PICK_SCOPE(NULL, "sets", 1), 1);
    chk("KZ2_SPU_PCORES=0", PICK_SCOPE(NULL, "0", 1), 0);
    chk("KZ3_SPU_PCORES=1 wins over default", PICK_SCOPE("1", NULL, 1), 2);
    chk("KZ3_SPU_PCORES=0 wins over KZ2=1", PICK_SCOPE("0", "1", 1), 0);
    chk("KZ3 NULL default = KZ3 behaviour", (uint64_t)kz3_sched_scope(kz2_spu_pcores_pick(NULL, NULL, NULL), 1), 2);
    printf(bad ? "test_r112_sched: FAIL\n" : "test_r112_sched: PASS\n");
    return bad != 0;
}
