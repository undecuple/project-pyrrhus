/* Host test for KZ2 patches 6063-6067. Built by tools/runtime/test_walker73.sh, which cuts the
 * shipped code out of the patched toolkit's cellGcmSys.c into walker73_cut.inc:
 *   - 6064 rsx_cb_reuse.h: when a draw may point at the previous constant-buffer slot,
 *   - 6063 gcm_perf_flush_line: the [perf-flush] line with the wrap counts, never past its buffer,
 *   - 6065 the GCM_FAST_METHODS block: the same calls in the same order as the per-word loop (a reference copy of the
 *     loop's routing, which the .sh checks against the shipped loop), for increment and non-increment headers,
 *     subchannels 0 and 1, the NV0039 methods on subchannel 1, GCM_SUBCH1_2D, a run crossing a 1 MB IO page edge,
 *   - 6067 gcm_walker_switch: unset / 0 / 1 / T and the phase it follows.
 * Negative controls: a fast path that drops a word or swaps the 2D/3D routing must be caught. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "rsx_cb_reuse.h"

typedef uint32_t u32;
static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; fprintf(stderr, "FAIL: " __VA_ARGS__); fprintf(stderr, "\n"); } } while (0)

/* ---- the perf counter indices gcm_perf_flush_line reads (any distinct values) ---- */
enum { RSX_PERF_W_TEX_UP_T, RSX_PERF_W_WRAP_SRV, RSX_PERF_W_WRAP_SMP, RSX_PERF_W_FLUSH_N0,
       RSX_PERF_W_FLUSH_T0 = RSX_PERF_W_FLUSH_N0 + 12, RSX_PERF_W_METH_T = RSX_PERF_W_FLUSH_T0 + 12,
       RSX_PERF_W_METH_CMD_N, NPERF };

/* ---- mocks the fast block calls ---- */
#define LOGN 256
typedef struct { char k; u32 a, b; } call;
static call g_log[LOGN]; static int g_n;
static void note(char k, u32 a, u32 b) { if (g_n < LOGN) { g_log[g_n].k = k; g_log[g_n].a = a; g_log[g_n].b = b; } g_n++; }
static uint8_t g_mem[4u << 20];                 /* guest memory: two IO pages mapped far apart */
static u32 gcm_io2ea(u32 io)
{
    const u32 page = io >> 20;   /* io page 0 -> ea 0x200000, page 1 -> ea 0x000000 (not contiguous) */
    if (page == 0) return 0x200000u + (io & 0xFFFFFu);
    if (page == 1) return 0x000000u + (io & 0xFFFFFu);
    return 0;
}
static u32 vm_read32(u32 ea) { return (u32)g_mem[ea] << 24 | (u32)g_mem[ea + 1] << 16 | (u32)g_mem[ea + 2] << 8 | g_mem[ea + 3]; }
static void vm_write32(u32 ea, u32 v) { g_mem[ea] = v >> 24; g_mem[ea + 1] = v >> 16; g_mem[ea + 2] = v >> 8; g_mem[ea + 3] = v; }
static int rsx_live_draw_enabled(void) { return 1; }
static int rsx_draw_engine_enabled(void) { return 1; }
static void rsx_live_draw_method(u32 m, u32 v) { note('L', m, v); }
static void rsx_draw_engine_method(u32 m, u32 v) { note('E', m, v); }
static void cellGcmQueueUserCommand(u32 v) { note('U', v, 0); }
static void cellGcmSetFlipCommand(u32 v) { note('F', v, 0); }
typedef struct { int dummy; } rsx_state;
static rsx_state s_state;
static int legacy_state_live = 1;
static void gcm_3d_method(rsx_state* st, u32 m, u32 v, int live) { (void)st; (void)live; note('3', m, v); }
static void gcm_2d_method(u32 subch, u32 m, u32 v) { note('2', subch << 16 | m, v); }
static int g_obj_same;   /* SET_OBJECT bound subchannel 1 to subchannel 0's handle */
static int gcm_subch1_nv0039(u32 m)
{
    if (g_obj_same) return 0;
    return m == 0x0180u || m == 0x0184u || m == 0x0188u || (m >= 0x030Cu && m <= 0x0328u);
}
static long long s_rsx_perf_methods;
static u32 s_fifo_getoff;
static long long g_perf[NPERF];
static void rsx_perf_add(int i, long long v) { g_perf[i] += v; }
static long long rsx_perf_now(void) { return 1; }

#include "walker73_cut.inc"

/* The per-word loop's routing (cellGcmSys.c, the lines test_walker73.sh checks), with live feed and draw engine on and
 * no diagnostic switch: the reference the fast block must match. */
static void ref_loop(u32 method, u32 count, u32 type, u32 subch, int s1_2d)
{
    for (u32 i = 0; i < count; i++) {
        u32 dea = gcm_io2ea(s_fifo_getoff + 4 + i * 4);
        if (!dea) break;
        u32 m = (type == 0) ? method + i * 4 : method;
        rsx_live_draw_method((subch << 13) | m, vm_read32(dea)); s_rsx_perf_methods++;
        rsx_draw_engine_method((subch << 13) | m, vm_read32(dea));
        const u32 mfull = (subch << 13) | m;
        if (mfull == 0xEB00u || mfull == 0xEB04u) {
            cellGcmQueueUserCommand(vm_read32(dea));
        } else if (mfull == 0xE920u || mfull == 0xE924u) {
            cellGcmSetFlipCommand(vm_read32(dea) & 7u);
        } else if (subch == 0 || (subch == 1 && !s1_2d && !gcm_subch1_nv0039(m))) {
            gcm_3d_method(&s_state, m, vm_read32(dea), legacy_state_live);
        } else
            gcm_2d_method(subch, m, vm_read32(dea));
    }
    s_fifo_getoff += 4 + count * 4;
}

static call r_log[LOGN];
static int compare(const char* what, u32 io, u32 method, u32 count, u32 type, u32 subch, int s1_2d, int expect_fast)
{
    for (u32 i = 0; i < count; i++) vm_write32(gcm_io2ea(io + 4 + i * 4), 0x1000u * (i + 1) + method);
    g_n = 0; s_fifo_getoff = io; ref_loop(method, count, type, subch, s1_2d);
    const int rn = g_n; memcpy(r_log, g_log, sizeof g_log); const u32 r_off = s_fifo_getoff;
    g_n = 0; s_fifo_getoff = io;
    const int took = fast_block(1, method, count, type, subch, s1_2d, 0);
    CHECK(took == expect_fast, "%s: fast path %s", what, took ? "taken" : "not taken");
    if (!took) return 0;
    CHECK(g_n == rn && memcmp(g_log, r_log, sizeof(call) * (size_t)(rn < LOGN ? rn : LOGN)) == 0,
          "%s: call stream differs (%d vs %d calls)", what, g_n, rn);
    CHECK(s_fifo_getoff == r_off, "%s: get 0x%X vs 0x%X", what, s_fifo_getoff, r_off);
    return 1;
}

int main(void)
{
    /* ---- 6064: the CB reuse decision ---- */
    ld_cbr r; memset(&r, 0, sizeof r);
    float xf[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    CHECK(!ld_cbr_can_reuse(&r, 0x2100, 0x2100, 5, xf, sizeof xf), "cbr: empty memo reused");
    ld_cbr_filled(&r, 0, 5, xf, sizeof xf);
    CHECK(ld_cbr_can_reuse(&r, 0x2100, 0x2100, 5, xf, sizeof xf), "cbr: same gen and tail not reused");
    CHECK(!ld_cbr_can_reuse(&r, 0x2100, 0x2100, 6, xf, sizeof xf), "cbr: new constant generation reused");
    xf[3] = 9;
    CHECK(!ld_cbr_can_reuse(&r, 0x2100, 0x2100, 5, xf, sizeof xf), "cbr: changed tail reused");
    xf[3] = 4;
    CHECK(!ld_cbr_can_reuse(&r, 0, 0x2100, 5, xf, sizeof xf), "cbr: slot above the ring cursor (wrap) reused");
    ld_cbr_invalidate(&r);
    CHECK(!ld_cbr_can_reuse(&r, 0x2100, 0x2100, 5, xf, sizeof xf), "cbr: invalidated memo reused");
    { char big[LD_CBR_TAIL_MAX + 4] = {0}; ld_cbr_filled(&r, 0, 5, big, sizeof big);
      CHECK(!r.valid, "cbr: oversized tail kept"); }

    /* ---- 6063: the [perf-flush] line ---- */
    long long d[NPERF] = {0};
    d[RSX_PERF_W_WRAP_SRV] = 3; d[RSX_PERF_W_WRAP_SMP] = 4; d[RSX_PERF_W_FLUSH_N0 + 11] = 5;
    d[RSX_PERF_W_FLUSH_N0 + 2] = 6; d[RSX_PERF_W_FLUSH_N0 + 3] = 7; d[RSX_PERF_W_FLUSH_N0 + 8] = 8;
    d[RSX_PERF_W_FLUSH_N0 + 9] = 20; d[RSX_PERF_W_FLUSH_T0 + 9] = 46;
    char fl[512];
    gcm_perf_flush_line(fl, sizeof fl, 130.0, d, 1.0);
    CHECK(strstr(fl, "[perf-flush] t=130s") && strstr(fl, " descring 20/46.0ms") &&
          strstr(fl, "| wraps srv 3 smp 4 up 5 vtx 6 cb 7 pscb 8"), "flush line: %s", fl);
    { char small[64 + 8]; memset(small, 'Z', sizeof small);
      gcm_perf_flush_line(small, 64, 130.0, d, 1.0);
      int ok = 1; for (int i = 64; i < 72; i++) ok &= small[i] == 'Z';
      CHECK(ok && small[63] == 0, "flush line: wrote past a 64-byte buffer"); }

    /* ---- 6065: the fast path against the per-word loop ---- */
    int fast = 0;
    fast += compare("inc subch0", 0x1000, 0x1A00, 8, 0, 0, 0, 1);
    fast += compare("non-inc subch0", 0x2000, 0x1D90, 5, 2, 0, 0, 1);         /* type != 0: same method */
    fast += compare("subch1 3D", 0x3000, 0x1A80, 4, 0, 1, 0, 1);
    fast += compare("subch1 NV0039 run", 0x4000, 0x0300, 12, 0, 1, 0, 1);     /* 0x300..0x32C: NV0039 for 0x30C..0x328 */
    fast += compare("subch1 2D forced", 0x5000, 0x1A80, 3, 0, 1, 1, 1);
    g_obj_same = 1;
    fast += compare("subch1 same object", 0x6000, 0x0180, 3, 0, 1, 0, 1);
    g_obj_same = 0;
    compare("page edge", 0x100000 - 8, 0x1A00, 6, 0, 0, 0, 0);                 /* words in io pages 0 and 1 */
    compare("method 0", 0x7000, 0x0000, 2, 0, 0, 0, 0);
    compare("subch2", 0x8000, 0x0300, 2, 0, 2, 0, 0);
    CHECK(fast == 6, "fast path taken %d of 6 times", fast);
    CHECK(!fast_block(0, 0x1A00, 4, 0, 0, 0, 0), "fast path taken with the switch off");
    /* negative control: a reference that routes subchannel 1 NV0039 words to 3D must differ from the fast path */
    { for (u32 i = 0; i < 2; i++) vm_write32(gcm_io2ea(0x9000 + 4 + i * 4), i);
      g_n = 0; s_fifo_getoff = 0x9000; fast_block(1, 0x0180, 2, 0, 1, 0, 0);
      int saw2d = 0; for (int i = 0; i < g_n && i < LOGN; i++) saw2d |= g_log[i].k == '2';
      CHECK(saw2d, "negative control: NV0039 method on subchannel 1 did not reach the 2D path"); }

    /* ---- 6067: the switch values ---- */
    int c1 = -1, c2 = -1, c3 = -1, c4 = -1;
    unsetenv("KZ2_T73_A"); setenv("KZ2_T73_B", "0", 1); setenv("KZ2_T73_C", "1", 1); setenv("KZ2_T73_D", "T", 1);
    g_gcm_walker_toggle_phase = 0;
    CHECK(gcm_walker_switch("KZ2_T73_A", 1, &c1) == 1 && gcm_walker_switch("KZ2_T73_A", 1, &c1) == 1, "switch: default");
    CHECK(gcm_walker_switch("KZ2_T73_B", 1, &c2) == 0, "switch: 0");
    CHECK(gcm_walker_switch("KZ2_T73_C", 0, &c3) == 1, "switch: 1");
    CHECK(gcm_walker_switch("KZ2_T73_D", 1, &c4) == 0, "switch: T in an even phase");
    g_gcm_walker_toggle_phase = 1;
    CHECK(gcm_walker_switch("KZ2_T73_D", 0, &c4) == 1 && gcm_walker_toggle_on() == 1, "switch: T in an odd phase");
    CHECK(gcm_walker_switch("KZ2_T73_C", 0, &c3) == 1 && gcm_walker_switch("KZ2_T73_B", 1, &c2) == 0,
          "switch: fixed values follow the phase");

    if (fails) { fprintf(stderr, "test_walker73: %d failure(s)\n", fails); return 1; }
    printf("PASS test_walker73 (cb reuse 7, flush line 2, fast path 6 taken + 3 refused + switch off + negative "
           "control, switches 6)\n");
    return 0;
}
