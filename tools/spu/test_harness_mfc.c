/* test_harness_mfc.c -- host test of the diff harness's MFC model (tools/spu/harness_mfc.h): the log
 * of one routine's MFC writes and reads, a put's bytes taken from the local store at the command, the synchronous
 * tag wait, and that hmfc_compare catches every kind of difference (an event's value, the order, a missing event,
 * a put's EA, size, tag or one byte) and nothing on equal logs. No game data.
 *   tools/spu/test_harness_mfc.sh */
#include "harness_mfc.h"

static int fails;
#define CHECK(c, msg) do { if (!(c)) { printf("FAIL %s (line %d)\n", msg, __LINE__); fails++; } } while (0)

static uint8_t ls[HMFC_LS_SIZE];

/* VertexJob 0x58D4-0x5958's sequence: a put of 16 KB from buffer b, then the tag wait on the other buffer */
static void vj_flush(hmfc_log* l, uint32_t b, uint32_t ea, uint32_t tag, uint32_t tag2)
{
    hmfc_wrch(l, ls, HMFC_LSA, 0x1FB80 + (b << 14));
    hmfc_wrch(l, ls, HMFC_EAL, ea);
    hmfc_wrch(l, ls, HMFC_Size, 0x4000);
    hmfc_wrch(l, ls, HMFC_TagID, tag);
    CHECK(hmfc_wrch(l, ls, HMFC_Cmd, 0x20) == 1, "put handled");
    hmfc_wrch(l, ls, HMFC_WrTagMask, 1u << tag2);
    hmfc_wrch(l, ls, HMFC_WrTagUpdate, 2);
    uint32_t v = 0;
    CHECK(hmfc_rdch(l, HMFC_RdTagStat, &v) == 1 && v == 1u << tag2, "tag status = the mask (synchronous)");
}

int main(void)
{
    for (uint32_t a = 0; a < HMFC_LS_SIZE; a++) ls[a] = (uint8_t)(a * 7 + (a >> 8));
    char d[200];
    hmfc_log a, b;
    memset(&a, 0, sizeof a);
    memset(&b, 0, sizeof b);

    vj_flush(&a, 0, 0x30001000, 3, 4);
    vj_flush(&b, 0, 0x30001000, 3, 4);
    CHECK(a.n == 8 && hmfc_puts(&a) == 1, "eight events, one put");
    CHECK(a.ev[4].lsa == 0x1FB80 && a.ev[4].eal == 0x30001000 && a.ev[4].size == 0x4000 && a.ev[4].tag == 3,
          "the put's parameters");
    CHECK(a.ev[4].data && a.ev[4].data[0] == ls[0x1FB80] && a.ev[4].data[0x3FFF] == ls[0x1FB80 + 0x3FFF],
          "the put's bytes from the LS");
    CHECK(hmfc_compare(&a, &b, d, sizeof d) == 0, "equal logs compare equal");

    /* the bytes are the LS at the command, not later */
    const uint8_t was = ls[0x1FB80 + 5];
    ls[0x1FB80 + 5] ^= 0xFF;
    CHECK(a.ev[4].data[5] == was, "put bytes copied at the command");
    hmfc_reset(&b);
    vj_flush(&b, 0, 0x30001000, 3, 4);
    CHECK(hmfc_compare(&a, &b, d, sizeof d) == 1 && strstr(d, "byte 0x5"), "one byte differs");
    ls[0x1FB80 + 5] = was;

    struct { uint32_t b, ea, tag, tag2; const char* what; const char* want; } m[] = {
        {1, 0x30001000, 3, 4, "another LSA", "lsa"},   /* LSA is also an event: caught there first */
        {0, 0x30005000, 3, 4, "another EA", "0x30005000"},
        {0, 0x30001000, 2, 4, "another tag", "ch 20"},
        {0, 0x30001000, 3, 5, "another wait mask", "ch 22"},
    };
    for (unsigned i = 0; i < sizeof m / sizeof m[0]; i++) {
        hmfc_reset(&b);
        vj_flush(&b, m[i].b, m[i].ea, m[i].tag, m[i].tag2);
        CHECK(hmfc_compare(&a, &b, d, sizeof d) == 1, m[i].what);
    }

    /* a missing event, an extra one, two swapped */
    hmfc_reset(&b);
    vj_flush(&b, 0, 0x30001000, 3, 4);
    b.n--;
    CHECK(hmfc_compare(&a, &b, d, sizeof d) == 1 && strstr(d, "events: 8 vs 7"), "a missing read");
    b.n++;
    { hmfc_ev t = b.ev[1]; b.ev[1] = b.ev[2]; b.ev[2] = t; }
    CHECK(hmfc_compare(&a, &b, d, sizeof d) == 1, "two writes swapped");
    hmfc_reset(&b);
    vj_flush(&b, 0, 0x30001000, 3, 4);
    hmfc_wrch(&b, ls, HMFC_WrTagUpdate, 2);
    CHECK(hmfc_compare(&a, &b, d, sizeof d) == 1, "an extra write");

    /* the same parameters through another route: the put compares its own copy of the parameters too */
    hmfc_reset(&b);
    vj_flush(&b, 0, 0x30001000, 3, 4);
    b.ev[4].size = 0x2000;
    CHECK(hmfc_compare(&a, &b, d, sizeof d) == 1 && strstr(d, "size 0x2000"), "a put's size");

    /* not modelled: a get (-1), a non-MFC channel (0), a non-MFC read */
    hmfc_reset(&b);
    CHECK(hmfc_wrch(&b, ls, HMFC_Cmd, 0x40) == -1, "a get is not modelled");
    CHECK(hmfc_wrch(&b, ls, 28, 1) == 0, "SPU_WrOutMbox is no MFC channel");
    uint32_t v;
    CHECK(hmfc_rdch(&b, 29, &v) == 0, "SPU_RdInMbox is not modelled");

    /* overflow is a difference, never a silent pass */
    hmfc_reset(&b);
    for (int i = 0; i < HMFC_MAX + 2; i++) hmfc_wrch(&b, ls, HMFC_LSA, i);
    hmfc_log c = b;   /* shallow: no puts, nothing to free twice */
    CHECK(hmfc_compare(&b, &c, d, sizeof d) == 1 && strstr(d, "overflow"), "overflow");

    /* the LSA wraps at the end of the local store as the runtime masks it */
    hmfc_reset(&b);
    hmfc_wrch(&b, ls, HMFC_LSA, HMFC_LS_SIZE - 4);
    hmfc_wrch(&b, ls, HMFC_Size, 16);
    hmfc_wrch(&b, ls, HMFC_Cmd, 0x20);
    CHECK(b.ev[2].data[4] == ls[0] && b.ev[2].data[3] == ls[HMFC_LS_SIZE - 1], "LSA wrap");

    hmfc_reset(&a);
    hmfc_reset(&b);
    if (fails) { printf("FAIL test_harness_mfc: %d\n", fails); return 1; }
    printf("PASS test_harness_mfc\n");
    return 0;
}
