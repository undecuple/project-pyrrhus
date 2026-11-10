/* Tests the actual helper shipped by patch 6071, with synthetic programs only. */
#include <assert.h>
#include <stdio.h>
#include "rsx_program_memo.h"
static rsx_program_memo memo;
int main(void)
{
    uint64_t out = 0xfeed;
    rsx_pm_entry* a = rsx_pm_select(&memo, 0, 0x100);
    assert(a->size == 0 && a->loc == 0 && a->off == 0x100);
    a->size = a->n = 16; memset(a->bytes, 0x42, a->size);
    rsx_pm_hash_put(a, 1, 10, 100);
    rsx_pm_hash_put(a, 1, 20, 200);
    rsx_pm_hash_put(a, 2, 10, 300);
    assert(rsx_pm_hash_get(a, 1, 10, &out) && out == 100);
    assert(rsx_pm_hash_get(a, 1, 20, &out) && out == 200);
    assert(rsx_pm_hash_get(a, 2, 10, &out) && out == 300);
    out = 0xfeed;
    assert(!rsx_pm_hash_get(a, 2, 20, &out) && out == 0xfeed);
    rsx_pm_hash_put(a, 2, 20, 0); /* zero is a value, never an occupancy sentinel */
    assert(rsx_pm_hash_get(a, 2, 20, &out) && out == 0);
    rsx_pm_hash_put(a, 3, 30, 400); /* bounded hash eviction */
    assert(!rsx_pm_hash_get(a, 1, 10, &out));
    assert(rsx_pm_hash_get(a, 1, 20, &out) && out == 200);
    /* Selecting a different program must preserve A's snapshot and hash state. */
    rsx_pm_entry* b = rsx_pm_select(&memo, 1, 0x100);
    assert(b != a && b->loc == 1 && b->off == 0x100);
    b->size = 32; memset(b->bytes, 0x24, b->size);
    assert(rsx_pm_select(&memo, 0, 0x100) == a);
    unsigned char changed[16]; memset(changed, 0x42, sizeof changed);
    assert(!memcmp(a->bytes, changed, sizeof changed));
    changed[15] ^= 1; /* a byte beyond the quick prefix must invalidate reuse */
    assert(memcmp(a->bytes, changed, sizeof changed));
    a->hvalid = a->scans_valid = 1; a->units = 7; a->ddy = a->wpos = 1;
    rsx_pm_invalidate(a);
    assert(!a->hvalid && !a->scans_valid && !a->hash_next);
    assert(!rsx_pm_hash_get(a, 1, 20, &out));
    assert(!rsx_pm_hash_get(a, 2, 10, &out));
    /* Same address with new bytes starts with no inherited derived identities. */
    memcpy(a->bytes, changed, sizeof changed);
    rsx_pm_hash_put(a, 1, 20, 999);
    assert(rsx_pm_hash_get(a, 1, 20, &out) && out == 999);
    for (uint32_t i = 2; i < RSX_PM_SLOTS; i++) {
        rsx_pm_entry* e = rsx_pm_select(&memo, 0, 0x100 + i);
        e->size = 16;
    }
    rsx_pm_entry* evicted = rsx_pm_select(&memo, 0, 0x900);
    assert(evicted == a && !evicted->size && !evicted->n && !evicted->hvalid && !evicted->scans_valid);
    assert(!rsx_pm_hash_get(evicted, 1, 20, &out));
    assert(rsx_pm_select(&memo, 1, 0x100) == b && b->bytes[0] == 0x24);
    /* A miss with no published size must not become a valid lookup entry. */
    rsx_pm_entry* unpublished = rsx_pm_select(&memo, 0, 0x901);
    assert(!unpublished->size);
    assert(rsx_pm_select(&memo, 0, 0x901) != unpublished);
    puts("shader program memo: mode/seed/zero, address identity, mutation invalidation and bounded eviction passed");
    return 0;
}
