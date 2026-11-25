/* Patch 7023 host test: a GET that matches a verified streamed region exactly (source EA and load address) takes
 * that region, although the image's 16-byte header signature was registered first.
 * This is how the port registers Killzone 2's Amadeus audio plugin modules: each is a WWS job-module image, so its
 * signature goes in with the other job modules (spu_overlay_register_sig, the lift at LS 0x4000), and with
 * KZ2_AMADEUS_PLUGINS=1 it goes in again as a verified region lifted for LS 0x8400, where Snd.Amadeus runs it.
 * The image here is made up (no game bytes).
 * 1. A GET of the image from its EA to LS 0x8400: the 0x8400 lift's code span becomes resident and verifies;
 *    the resident job module (Snd.Amadeus, at 0x4000) stays the resident overlay. Without 7023 the signature
 *    entry took the GET: no code span, and the resident overlay became the plugin's 0x4000 lift.
 * 2. The same image to the job code buffer (LS 0x4000): the signature entry, as before.
 * 3. The same bytes from another EA to LS 0x8400: the signature entry, as before.
 * 4. Other bytes at the registered EA, to LS 0x8400: the span is resident but fails the byte compare, so nothing
 *    of the lift is dispatched (the compare is what makes the exact match safe).
 * 5. A second verified region for the same EA at another address, registered later: each address gets its own.
 * Built by tools/spu/test_ovl_exact_region.sh against work/ps3recomp-patched. */
#include <pthread.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t g_guest_mem[1u << 20];
uint8_t* vm_base = g_guest_mem;
uint32_t ppu_vm_size = 0;
#include "spu_channels.c" /* the unit under test: spu_overlay_note_get */

unsigned long long ps3_ms_now(void)
{
    return 0;
}
void ppu_resv_break_store(uint64_t ea)
{
    (void)ea;
}
void ps3_ww_report_inline(uint32_t a, uint64_t v, int w)
{
    (void)a;
    (void)v;
    (void)w;
}
uint32_t g_ww_lo = 0xFFFFFFFFu, g_ww_hi = 0;
int g_resv_store_active = 0;
uint32_t g_barrier_sync_watch = 0;
void (*g_spurs_kernel_hook)(uint32_t) = 0;
uint32_t g_ydkj_spurs_ctx_ea = 0, g_ydkj_real_spurs_ea = 0, g_ydkj_real_taskset_ea = 0, g_ydkj_real_taskid = 0;
void spurs_ef_set_from_spu(uint32_t ea, uint16_t bits)
{
    (void)ea;
    (void)bits;
}
void ydkj_wake_all_event_flags(void) {}
void spurs_pm_build_context(spu_context* c, uint32_t a, uint32_t b, uint32_t d)
{
    (void)c;
    (void)a;
    (void)b;
    (void)d;
}
uint32_t g_spu_image_src_ea, g_spu_image_ls_start, g_spu_image_span;
void spu_thread_publish_ctx(uint32_t tid, void* ctx)
{
    (void)tid;
    (void)ctx;
}

static int g_pass, g_fail;
#define CHECK(cond, ...)                                                                                               \
    do {                                                                                                               \
        if (cond)                                                                                                      \
            g_pass++;                                                                                                  \
        else {                                                                                                         \
            g_fail++;                                                                                                  \
            fprintf(stderr, "FAIL %s:%d: ", __FILE__, __LINE__);                                                       \
            fprintf(stderr, __VA_ARGS__);                                                                              \
            fputc('\n', stderr);                                                                                       \
        }                                                                                                              \
    } while (0)

enum { EA = 0x20000, EA_OTHER = 0x40000, SIZE = 0x1000, PLUGIN_LSA = 0x8400, JOB_LSA = 0x4000, ALT_LSA = 0xC000 };
enum { ID_JOB_LIFT = 250, ID_PLUGIN_LIFT = 400, ID_ALT_LIFT = 401, ID_AMADEUS = 231 };

static spu_context* mk(void)
{
    spu_context* c = (spu_context*)calloc(1, sizeof *c); /* 256 KB LS: heap */
    if (!c) {
        fprintf(stderr, "out of memory\n");
        exit(2);
    }
    spu_context_init(c, 0);
    c->status = SPU_STATUS_RUNNING;
    c->image_id = 2;
    c->resident_ovl = ID_AMADEUS; /* the job module that streams the plugin is the resident overlay */
    return c;
}
/* What an MFC GET of `size` bytes from guest `ea` to local store `lsa` does: copy, then note. */
static void get(spu_context* c, uint32_t ea, uint32_t lsa, uint32_t size)
{
    memcpy(c->ls + lsa, g_guest_mem + ea, size);
    spu_overlay_note_get(c, ea, c->ls + lsa, size);
}
/* The resident code span of image `id`, or -1. */
static int span_of(spu_context* c, int id)
{
    for (int s = 0; s < 4; s++)
        if (c->resident_code[s].image_id == id) return s;
    return -1;
}
static int spans(spu_context* c)
{
    int n = 0;
    for (int s = 0; s < 4; s++) n += c->resident_code[s].image_id != 0;
    return n;
}

int main(void)
{
    /* A made-up job-module image: a 16-byte signature, then "code". */
    uint8_t* img = g_guest_mem + EA;
    for (uint32_t i = 0; i < SIZE; i++) img[i] = (uint8_t)(i * 7 + 3);
    memcpy(g_guest_mem + EA_OTHER, img, SIZE); /* the same bytes at another EA */

    /* Registration order of the generated spu_workloads.c: the signatures first, the regions after. */
    spu_overlay_register_sig(img, ID_JOB_LIFT);
    spu_overlay_code_segment seg = {PLUGIN_LSA + 0x30, 0x400, img + 0x30};
    CHECK(spu_overlay_register_verified_region(EA, PLUGIN_LSA, SIZE, ID_PLUGIN_LIFT, &seg, 1), "region not registered");

    /* 1 */
    spu_context* c = mk();
    get(c, EA, PLUGIN_LSA, SIZE);
    int s = span_of(c, ID_PLUGIN_LIFT);
    CHECK(s >= 0, "1: no resident code span for the 0x8400 lift (resident overlay %d)", c->resident_ovl);
    CHECK(c->resident_ovl == ID_AMADEUS, "1: resident overlay %d, want %d (the streaming job module)", c->resident_ovl,
          ID_AMADEUS);
    if (s >= 0) {
        CHECK(c->resident_code[s].lsa == PLUGIN_LSA && c->resident_code[s].size == SIZE &&
                  c->resident_code[s].source_ea == EA,
              "1: span 0x%X+0x%X from 0x%X", c->resident_code[s].lsa, c->resident_code[s].size,
              c->resident_code[s].source_ea);
        CHECK(spu_overlay_resident_verified(c, (unsigned)s), "1: the span's bytes did not verify");
    }

    /* 2 */
    spu_context* c2 = mk();
    get(c2, EA, JOB_LSA, SIZE);
    CHECK(c2->resident_ovl == ID_JOB_LIFT, "2: resident overlay %d, want %d (signature entry)", c2->resident_ovl,
          ID_JOB_LIFT);
    CHECK(spans(c2) == 0, "2: %d resident code spans, want 0", spans(c2));

    /* 3 */
    spu_context* c3 = mk();
    get(c3, EA_OTHER, PLUGIN_LSA, SIZE);
    CHECK(c3->resident_ovl == ID_JOB_LIFT, "3: resident overlay %d, want %d (signature entry)", c3->resident_ovl,
          ID_JOB_LIFT);
    CHECK(spans(c3) == 0, "3: %d resident code spans, want 0", spans(c3));

    /* 5 (before 4 changes the bytes): a later region for the same EA at another address */
    spu_overlay_code_segment seg2 = {ALT_LSA + 0x30, 0x400, img + 0x30};
    CHECK(spu_overlay_register_verified_region(EA, ALT_LSA, SIZE, ID_ALT_LIFT, &seg2, 1),
          "second region not registered");
    spu_context* c5 = mk();
    get(c5, EA, ALT_LSA, SIZE);
    CHECK(span_of(c5, ID_ALT_LIFT) >= 0 && span_of(c5, ID_PLUGIN_LIFT) < 0, "5: GET to 0x%X: spans %d/%d", ALT_LSA,
          span_of(c5, ID_ALT_LIFT), span_of(c5, ID_PLUGIN_LIFT));
    get(c5, EA, PLUGIN_LSA, SIZE);
    CHECK(span_of(c5, ID_ALT_LIFT) >= 0 && span_of(c5, ID_PLUGIN_LIFT) >= 0, "5: both loaded: spans %d/%d",
          span_of(c5, ID_ALT_LIFT), span_of(c5, ID_PLUGIN_LIFT));
    CHECK(c5->resident_ovl == ID_AMADEUS, "5: resident overlay %d", c5->resident_ovl);

    /* 4 */
    img[0x200] ^= 0xFF; /* the EA now holds other code than was lifted */
    spu_context* c4 = mk();
    get(c4, EA, PLUGIN_LSA, SIZE);
    s = span_of(c4, ID_PLUGIN_LIFT);
    CHECK(s >= 0, "4: no resident code span");
    if (s >= 0) CHECK(!spu_overlay_resident_verified(c4, (unsigned)s), "4: changed bytes verified");

    printf("test_ovl_exact_region: pass=%d fail=%d\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}

/* KZ2: patch 7002's WWS job-log hooks are defined in port/kz2 (not linked here); off (0) in this test. */
__attribute__((weak)) int g_kz2_joblog = 0;
__attribute__((weak)) void kz2_joblog_entry(spu_context* c) { (void)c; }
__attribute__((weak)) void kz2_joblog_get(spu_context* c, uint32_t a, uint32_t b, uint32_t d) { (void)c; (void)a; (void)b; (void)d; }
__attribute__((weak)) void kz2_joblog_put(spu_context* c, uint32_t a, uint32_t b) { (void)c; (void)a; (void)b; }
