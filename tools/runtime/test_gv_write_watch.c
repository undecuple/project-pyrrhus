/* Host test for KZ2 patch 6086 (guest-validate skipped by the write watch, LD_GV_WW): ld_ww_skip_or_arm of the patched
 * toolkit's libs/video/rsx_tex_ww.h against a fake OS write watch. A consumer keeps a hash of the bytes of a range
 * and asks, each "frame", whether to hash again. The test's reference is the plain rule "hash every time": whenever
 * the function says skip, the bytes must be exactly what they were at the last hash. No game data, no GPU. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define LD_WW_BATCH 8u   /* a small address array, so one range needs several queries */
#include "rsx_tex_ww.h"

enum { PAGES = 64 };
/* page-aligned, as guest memory is: the watch works on host pages, and the fake below counts pages from g_mem */
static _Alignas(4096) unsigned char g_mem[PAGES * 4096];
static unsigned char g_dirty[PAGES];   /* the fake OS write watch: one bit per page, reset by a query */
static int g_fail_queries;

static int fake_query(void* base, size_t size, void** addrs, uintptr_t* count)
{
    if (g_fail_queries) return -1;
    const uintptr_t b = (uintptr_t)base - (uintptr_t)g_mem;
    uintptr_t n = 0;
    for (uintptr_t p = b >> 12; p < (b + size + 4095) >> 12 && p < PAGES; p++) {
        if (!g_dirty[p]) continue;
        if (n == *count) break;                 /* array full: the reset stops here, as GetWriteWatch's does */
        addrs[n++] = g_mem + (p << 12);
        g_dirty[p] = 0;
    }
    *count = n;
    return 0;
}
static void guest_write(unsigned off, unsigned char v) { g_mem[off] = v; g_dirty[off >> 12] = 1; }

static unsigned hash_range(unsigned off, unsigned size)
{
    unsigned h = 2166136261u;
    for (unsigned i = 0; i < size; i++) h = (h ^ g_mem[off + i]) * 16777619u;
    return h;
}

static int g_bad;
#define CHECK(name, cond) do { int ok_ = (cond); printf("%s%s\n", ok_ ? "PASS: " : "[FAIL] ", name); g_bad += !ok_; } while (0)

/* One consumer: a surface at [off, off+size). step() is what ld_gv_hash_bands does with the switch on. */
typedef struct { unsigned off, size, hash; int have; ld_ww_arm_t arm; unsigned hashed, skipped; } surf;
static int step(ld_ww_state* st, surf* s, int same)
{
    if (ld_ww_skip_or_arm(st, &s->arm, (uintptr_t)g_mem + s->off, s->size, same && s->have)) {
        s->skipped++;
        return 1;
    }
    s->hash = hash_range(s->off, s->size); s->have = 1; s->hashed++;
    return 0;
}

int main(void)
{
    static uint64_t stamps[LD_WW_PAGES];
    ld_ww_state st;
    ld_ww_init(&st, stamps, (uintptr_t)g_mem, fake_query);
    surf a = { 3 * 4096 + 100, 20 * 4096, 0, 0, { 0, 0 }, 0, 0 };   /* 21 pages: three queries of 8 */
    surf b = { 20 * 4096, 6 * 4096, 0, 0, { 0, 0 }, 0, 0 };         /* shares pages 20..23 with a */

    CHECK("the first call hashes (nothing armed yet)", step(&st, &a, 1) == 0);
    CHECK("an untouched range is skipped", step(&st, &a, 1) == 1 && a.hash == hash_range(a.off, a.size));
    guest_write(a.off + 5 * 4096 + 7, 0x5A);
    CHECK("a write inside the range is hashed again", step(&st, &a, 1) == 0 && a.hash == hash_range(a.off, a.size));
    CHECK("and skipped again afterwards", step(&st, &a, 1) == 1);
    guest_write(a.off + a.size - 1, 0x11);
    CHECK("a write to the range's last byte is seen", step(&st, &a, 1) == 0);
    guest_write(a.off, 0x22);
    CHECK("a write to the range's first byte is seen", step(&st, &a, 1) == 0);
    guest_write(a.off - 200, 0x33);          /* the page before the range's first page */
    guest_write(40 * 4096, 0x44);
    CHECK("writes on pages outside the range do not force a hash", step(&st, &a, 1) == 1);
    guest_write(a.off - 1, 0x55);            /* outside the range, but on its first page: the watch is per page */
    CHECK("a write on a page the range shares is hashed (page granularity, never a wrong skip)", step(&st, &a, 1) == 0);

    /* a second consumer on shared pages: its collect resets the OS bits, the stamps keep the write for the first */
    step(&st, &b, 1);
    guest_write(21 * 4096 + 9, 0x77);
    CHECK("b sees a write on a shared page", step(&st, &b, 1) == 0);
    CHECK("a sees the same write although b's query reset the page", step(&st, &a, 1) == 0 && a.hash == hash_range(a.off, a.size));
    CHECK("then both skip", step(&st, &a, 1) == 1 && step(&st, &b, 1) == 1);

    CHECK("a changed geometry is hashed even when nothing was written", step(&st, &a, 0) == 0);
    surf moved = a; moved.off += 4096;
    CHECK("a moved range is hashed (the arm names another address)", step(&st, &moved, 1) == 0);

    g_fail_queries = 1;
    CHECK("a failed query hashes and disarms", step(&st, &a, 1) == 0 && a.arm.seq == 0);
    g_fail_queries = 0;
    CHECK("the call after a failed query hashes too (not armed)", step(&st, &a, 1) == 0);
    CHECK("and the one after that skips", step(&st, &a, 1) == 1);

    /* against the reference: random writes, a skip must never hide a change */
    unsigned rng = 12345, wrong = 0, skips = 0, hashes = 0;
    for (int frame = 0; frame < 20000; frame++) {
        rng = rng * 1103515245u + 12345u;
        if ((rng >> 16) % 5 == 0) guest_write((rng >> 8) % sizeof g_mem, (unsigned char)rng);
        surf* s = (frame & 1) ? &a : &b;
        if (step(&st, s, 1)) { skips++; wrong += s->hash != hash_range(s->off, s->size); } else hashes++;
    }
    printf("random run: %u skips, %u hashes, %u wrong skips\n", skips, hashes, wrong);
    CHECK("no skip hid a change in 20,000 random frames", wrong == 0);
    CHECK("the random run skipped and hashed (both paths taken)", skips > 1000 && hashes > 1000);

    /* negative control: a consumer that trusts only its own query (no stamps) loses the shared-page write */
    {
        memset(g_dirty, 0, sizeof g_dirty);
        void* addrs[LD_WW_BATCH]; uintptr_t n;
        const unsigned h0 = hash_range(a.off, a.size);
        guest_write(21 * 4096 + 10, 0x99);
        n = LD_WW_BATCH; fake_query(g_mem + b.off, b.size, addrs, &n);            /* b looks first and resets the page */
        uintptr_t seen = 0;
        for (unsigned o = 0; o < a.size + 4096; o += LD_WW_BATCH * 4096) {
            n = LD_WW_BATCH; fake_query(g_mem + (a.off & ~4095u) + o, LD_WW_BATCH * 4096, addrs, &n); seen += n;
        }
        CHECK("control: without the stamps the first consumer would have skipped a changed range",
              seen == 0 && h0 != hash_range(a.off, a.size));
    }
    return g_bad ? 1 : 0;
}
