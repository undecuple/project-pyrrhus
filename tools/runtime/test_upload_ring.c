/* Host test for the upload ring placement (patch 6048, libs/video/rsx_upload_ring.h): a texture level that does not
 * fit in what is left of the ring must ask for a submit, never be skipped; the Corinth sky case is one of the rows. */
#include <stdio.h>
#include "rsx_upload_ring.h"

static int fails;
static void check(const char* what, uint64_t used, uint64_t bytes, uint64_t size, int want, uint64_t want_start)
{
    uint64_t start = 99;
    const int k = rsx_upload_place(used, bytes, size, &start);
    if (k != want || start != want_start) {
        printf("FAIL %s: used=%llu bytes=%llu size=%llu -> %d start=%llu (want %d start=%llu)\n", what,
               (unsigned long long)used, (unsigned long long)bytes, (unsigned long long)size, k,
               (unsigned long long)start, want, (unsigned long long)want_start);
        fails++;
    }
}

int main(void)
{
    const uint64_t RING = 64ull << 20;
    const uint64_t SKY = 8192ull * 128;   /* DXT5 2048x512: 512 blocks x 16 B per row (pitch 8192), 128 block rows */
    check("empty ring", 0, SKY, RING, RSX_UP_FIT, 0);
    check("aligned up to 512", 1, 4096, RING, RSX_UP_FIT, 512);
    check("already aligned", 1024, 4096, RING, RSX_UP_FIT, 1024);
    check("exactly fills", RING - SKY, SKY, RING, RSX_UP_FIT, RING - SKY);
    check("sky after a full ring (the bug)", RING - 4096, SKY, RING, RSX_UP_FLUSH, 0);
    check("one byte short", RING - SKY + 1, SKY, RING, RSX_UP_FLUSH, 0);
    check("alignment pushes it out", RING - SKY + 1, SKY - 400, RING, RSX_UP_FLUSH, 0);   /* fits unaligned */
    check("alignment still fits", RING - SKY - 100, SKY, RING, RSX_UP_FIT, RING - SKY);
    check("whole ring, empty", 0, RING, RING, RSX_UP_FIT, 0);
    check("whole ring, not empty", 512, RING, RING, RSX_UP_FLUSH, 0);
    check("larger than the ring", 0, RING + 1, RING, RSX_UP_TOO_BIG, 0);
    check("used past the end", RING + 4096, 16, RING, RSX_UP_FLUSH, 0);
    check("zero bytes", 700, 0, RING, RSX_UP_FIT, 1024);
    /* A frame of uploads: every level lands inside the ring, and a submit restarts at 0. */
    uint64_t used = 0; int submits = 0;
    for (int i = 0; i < 300; i++) {
        const uint64_t bytes = (i % 7 == 0) ? SKY : (uint64_t)(i * 4099 % 300000 + 1);
        uint64_t s;
        const int k = rsx_upload_place(used, bytes, RING, &s);
        if (k == RSX_UP_FLUSH) { submits++; used = 0; continue; }
        if (k != RSX_UP_FIT || s % RSX_UP_ALIGN || s < used || s + bytes > RING) {
            printf("FAIL frame walk at %d\n", i); fails++; break;
        }
        used = s + bytes;
    }
    if (!fails) printf("upload ring: 14 checks, frame walk ok (%d submits)\n", submits);
    return fails ? 1 : 0;
}
