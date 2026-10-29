/* Host test (KZ2_NATIVE_ZLIB): port/kz2/kz2_edge_zlib.c on synthetic raw-deflate streams
 * (no game data). Vectors come from tools/runtime/test_edge_zlib.sh (Python's zlib, wbits -15): stored, fixed-Huffman
 * and dynamic-Huffman blocks, multi-block, empty. Checks, with a fake guest memory and recorded ops:
 *   - every stream decodes to the plain bytes (the decoder this build uses: stb_image, or zlib with -DKZ2_HAVE_ZLIB);
 *   - element parse (big-endian offsets 0x00..0x1C);
 *   - windows: skipBegin/skipEnd cut exactly [skipBegin, skipBegin + partial), bytes around `out` untouched;
 *   - completion order put -> decrement -> flag; flag only when the old counter was 1; no counter -> flag; no flag EA ->
 *     no set; old counter 0 -> decremented anyway, no flag (the task's 0xA850 / 0x3630);
 *   - mode 0: copy, in == expected required; overlapping in/out copied as through LS;
 *   - fallbacks with nothing written and nothing completed: expected != inflated size (both ways), corrupt stream,
 *     inSize/expected over 0x10000, misaligned counter, counter already 0 at push, unreadable input.
 *   test_edge_zlib VECTOR_DIR */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "kz2_edge_zlib.h"

static int fails, passes;
#define CHECK(c, ...) do { if (c) passes++; else { fails++; printf("[FAIL] " __VA_ARGS__); printf("\n"); } } while (0)

/* Fake guest: 1 MiB at EA 0x100000. */
#define GBASE 0x100000u
#define GSIZE 0x100000u
static uint8_t g_mem[GSIZE];
static char g_log[256];   /* "P" put, "D" dec, "F" flag, in order */
static uint32_t g_flag_ea, g_flag_bits;

static uint8_t* gp(uint32_t ea) { return g_mem + (ea - GBASE); }
static void wbe32(uint32_t ea, uint32_t v) { uint8_t* p = gp(ea); p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v; }
static uint32_t rbe32(uint32_t ea) { const uint8_t* p = gp(ea); return (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]; }

static const uint8_t* op_src(void* u, uint32_t ea, uint32_t n)
{
    (void)u;
    if (ea < GBASE || (uint64_t)ea + n > GBASE + GSIZE) return NULL;
    return gp(ea);
}
static int op_put(void* u, uint32_t ea, const uint8_t* p, uint32_t n)
{
    (void)u;
    if (ea < GBASE || (uint64_t)ea + n > GBASE + GSIZE) return -1;
    memcpy(gp(ea), p, n);   /* p is the scratch, never guest memory: memcpy must be safe */
    strcat(g_log, "P");
    return 0;
}
static uint32_t op_dec(void* u, uint32_t ea)
{
    (void)u;
    const uint32_t old = rbe32(ea);
    wbe32(ea, old - 1u);
    strcat(g_log, "D");
    return old;
}
static int op_flag(void* u, uint32_t ea, uint16_t bits)
{
    (void)u;
    g_flag_ea = ea; g_flag_bits = bits;
    strcat(g_log, "F");
    return 0;
}
static const kz2_edge_ops OPS = { NULL, op_src, op_put, op_dec, op_flag };

static uint8_t* load(const char* dir, const char* name, uint32_t* n)
{
    char path[512];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE* f = fopen(path, "rb");
    if (!f) { printf("[FAIL] missing vector %s\n", path); exit(1); }
    fseek(f, 0, SEEK_END); long len = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t* b = malloc(len ? (size_t)len : 1);
    if (fread(b, 1, (size_t)len, f) != (size_t)len) { printf("[FAIL] short read %s\n", path); exit(1); }
    fclose(f);
    *n = (uint32_t)len;
    return b;
}

#define IN_EA  0x110000u
#define OUT_EA 0x140000u
#define CNT_EA 0x1F0000u
#define EF_EA  0x1F0080u
static uint8_t scratch[KZ2_EDGE_MAX];

static void reset_guest(void)
{
    memset(g_mem, 0xA5, sizeof g_mem);
    g_log[0] = 0; g_flag_ea = 0; g_flag_bits = 0;
}

/* One element run; returns status. Puts z (compressed) at IN_EA, counter value cnt at CNT_EA. */
static int run(const uint8_t* z, uint32_t zn, uint32_t mode, uint32_t sb, uint32_t partial, uint32_t se, uint32_t cnt_ea,
               uint32_t cnt, uint32_t ef, kz2_edge_result* r)
{
    reset_guest();
    if (zn) memcpy(gp(IN_EA), z, zn);
    if (cnt_ea) wbe32(cnt_ea, cnt);
    /* Build the 32-byte BE element as edgeZlibAddInflateQueueElement does, and parse it. */
    uint8_t el[32] = {0};
    const uint32_t w[6] = { IN_EA, OUT_EA, zn, partial, cnt_ea | mode, ef };
    for (int i = 0; i < 6; i++) { el[4*i] = w[i] >> 24; el[4*i+1] = w[i] >> 16; el[4*i+2] = w[i] >> 8; el[4*i+3] = w[i]; }
    el[0x18] = 0x12; el[0x19] = 0x34;
    el[0x1A] = sb >> 8; el[0x1B] = sb; el[0x1C] = se >> 8; el[0x1D] = se;
    kz2_edge_elem e;
    kz2_edge_parse(el, &e);
    return kz2_edge_run(&e, &OPS, scratch, r);
}

static int untouched(uint32_t ea, uint32_t n)
{
    for (uint32_t i = 0; i < n; i++) if (gp(ea)[i] != 0xA5) return 0;
    return 1;
}

int main(int argc, char** argv)
{
    if (argc < 2) { printf("usage: test_edge_zlib VECTOR_DIR\n"); return 2; }
    const char* dir = argv[1];
    printf("decoder: %s\n", kz2_edge_backend());

    /* Parse: offsets. */
    {
        uint8_t el[32];
        for (int i = 0; i < 32; i++) el[i] = (uint8_t)(0x10 + i);
        kz2_edge_elem e;
        kz2_edge_parse(el, &e);
        CHECK(e.in == 0x10111213u && e.out == 0x14151617u && e.in_size == 0x18191A1Bu && e.partial == 0x1C1D1E1Fu &&
              e.counter_mode == 0x20212223u && e.event_flag == 0x24252627u && e.bits == 0x2829 && e.skip_begin == 0x2A2B &&
              e.skip_end == 0x2C2D, "element parse offsets");
    }

    static const char* const kinds[] = { "stored", "fixed", "dynamic", "multi", "empty", "full64k" };
    for (unsigned k = 0; k < sizeof kinds / sizeof kinds[0]; k++) {
        char zn_[64], pn_[64];
        snprintf(zn_, sizeof zn_, "%s.deflate", kinds[k]);
        snprintf(pn_, sizeof pn_, "%s.plain", kinds[k]);
        uint32_t zn, pn;
        uint8_t* z = load(dir, zn_, &zn);
        uint8_t* p = load(dir, pn_, &pn);
        static uint8_t out[KZ2_EDGE_MAX];
        const int n = kz2_edge_inflate_raw(out, pn, z, zn);
        CHECK(n == (int)pn && !memcmp(out, p, pn), "%s: raw inflate (%d of %u bytes)", kinds[k], n, pn);

        /* Whole block, counter 1 -> 0, flag set, order P D F. */
        kz2_edge_result r;
        int st = run(z, zn, 1, 0, pn, 0, CNT_EA, 1, EF_EA, &r);
        CHECK(st == KZ2_EDGE_DONE && r.produced == pn && !memcmp(gp(OUT_EA), p, pn) && untouched(OUT_EA + pn, 64) &&
              rbe32(CNT_EA) == 0 && r.flag_set && g_flag_ea == EF_EA && g_flag_bits == 0x1234 &&
              !strcmp(g_log, pn ? "PDF" : "DF"), "%s: whole block, completion order (log %s)", kinds[k], g_log);

        if (pn >= 64) {
            /* Window: skip 7 / 13. */
            const uint32_t sb = 7, se = 13, part = pn - sb - se;
            st = run(z, zn, 1, sb, part, se, CNT_EA, 1, EF_EA, &r);
            CHECK(st == KZ2_EDGE_DONE && !memcmp(gp(OUT_EA), p + sb, part) && untouched(OUT_EA + part, 64) &&
                  untouched(OUT_EA - 64, 64), "%s: window skip %u/%u", kinds[k], sb, se);
            /* Window with skipEnd only and skipBegin only. */
            st = run(z, zn, 1, 0, pn - 1, 1, CNT_EA, 1, EF_EA, &r);
            CHECK(st == KZ2_EDGE_DONE && !memcmp(gp(OUT_EA), p, pn - 1) && untouched(OUT_EA + pn - 1, 16), "%s: skipEnd 1", kinds[k]);
            st = run(z, zn, 1, pn - 5, 5, 0, CNT_EA, 1, EF_EA, &r);
            CHECK(st == KZ2_EDGE_DONE && !memcmp(gp(OUT_EA), p + pn - 5, 5) && untouched(OUT_EA + 5, 16), "%s: skipBegin %u", kinds[k], pn - 5);
            /* partial 0: nothing written, completion still done. */
            st = run(z, zn, 1, pn - 3, 0, 3, CNT_EA, 1, EF_EA, &r);
            CHECK(st == KZ2_EDGE_DONE && untouched(OUT_EA, 16) && !strcmp(g_log, "DF"), "%s: partial 0 (log %s)", kinds[k], g_log);
            /* Size mismatch both ways: fallback, nothing written or completed. */
            st = run(z, zn, 1, 0, pn - 1, 0, CNT_EA, 1, EF_EA, &r);
            CHECK(st == KZ2_EDGE_FB_INFLATE && untouched(OUT_EA, 64) && rbe32(CNT_EA) == 1 && !g_log[0],
                  "%s: expected < inflated -> fallback", kinds[k]);
            if (pn < KZ2_EDGE_MAX) {
                st = run(z, zn, 1, 0, pn + 1, 0, CNT_EA, 1, EF_EA, &r);
                CHECK(st == KZ2_EDGE_FB_INFLATE && untouched(OUT_EA, 64) && rbe32(CNT_EA) == 1 && !g_log[0],
                      "%s: expected > inflated -> fallback", kinds[k]);
            }
            /* Corrupt: truncated stream. */
            st = run(z, zn / 2, 1, 0, pn, 0, CNT_EA, 1, EF_EA, &r);
            CHECK(st == KZ2_EDGE_FB_INFLATE && untouched(OUT_EA, 64) && !g_log[0], "%s: truncated -> fallback", kinds[k]);
        }
        free(z); free(p);
    }

    /* Completion rules (dynamic vector). */
    {
        uint32_t zn, pn;
        uint8_t* z = load(dir, "dynamic.deflate", &zn);
        uint8_t* p = load(dir, "dynamic.plain", &pn);
        kz2_edge_result r;
        int st = run(z, zn, 1, 0, pn, 0, CNT_EA, 3, EF_EA, &r);
        CHECK(st == KZ2_EDGE_DONE && rbe32(CNT_EA) == 2 && !r.flag_set && !strcmp(g_log, "PD") && r.counter_old == 3,
              "counter 3 -> 2, no flag (log %s)", g_log);
        st = run(z, zn, 1, 0, pn, 0, 0, 0, EF_EA, &r);
        CHECK(st == KZ2_EDGE_DONE && r.flag_set && !strcmp(g_log, "PF"), "no counter -> flag (log %s)", g_log);
        st = run(z, zn, 1, 0, pn, 0, CNT_EA, 1, 0, &r);
        CHECK(st == KZ2_EDGE_DONE && !r.flag_set && rbe32(CNT_EA) == 0 && !strcmp(g_log, "PD"), "no flag EA -> no set (log %s)", g_log);
        st = run(z, zn, 1, 0, pn, 0, CNT_EA, 0, EF_EA, &r);
        CHECK(st == KZ2_EDGE_FB_ARGS && !g_log[0], "counter already 0 at push -> fallback (the PPU asserts)");
        st = run(z, zn, 1, 0, pn, 0, CNT_EA + 2, 1, EF_EA, &r);
        CHECK(st == KZ2_EDGE_FB_ARGS && !g_log[0], "misaligned counter -> fallback");
        st = run(z, zn, 1, 0, KZ2_EDGE_MAX + 1, 0, CNT_EA, 1, EF_EA, &r);
        CHECK(st == KZ2_EDGE_FB_ARGS && !g_log[0], "expected > 0x10000 -> fallback");
        /* Unreadable input. */
        {
            reset_guest(); wbe32(CNT_EA, 1);
            kz2_edge_elem e = { 0x10, OUT_EA, zn, pn, CNT_EA | 1u, EF_EA, 1, 0, 0 };
            st = kz2_edge_run(&e, &OPS, scratch, &r);
            CHECK(st == KZ2_EDGE_FB_SRC && !g_log[0], "unreadable input -> fallback");
            kz2_edge_elem e2 = { IN_EA, OUT_EA, KZ2_EDGE_MAX + 1, pn, CNT_EA | 1u, EF_EA, 1, 0, 0 };
            st = kz2_edge_run(&e2, &OPS, scratch, &r);
            CHECK(st == KZ2_EDGE_FB_ARGS && !g_log[0], "inSize > 0x10000 -> fallback");
        }
        free(z); free(p);
    }

    /* The task's own decrement goes on from 0 (old 0: no flag). The PPU asserts a zero counter before the push, so this
     * state is only reached by a second completion: model it by decrementing in the op directly. */
    {
        reset_guest(); wbe32(CNT_EA, 0);
        const uint32_t old = op_dec(NULL, CNT_EA);
        CHECK(old == 0 && rbe32(CNT_EA) == 0xFFFFFFFFu, "decrement from 0 wraps as the task's 0xA850");
    }

    /* Mode 0: copy, in == expected; window; size mismatch -> fallback; overlap copies as through LS. */
    {
        uint8_t src[300];
        for (int i = 0; i < 300; i++) src[i] = (uint8_t)(i * 7 + 3);
        kz2_edge_result r;
        int st = run(src, 300, 0, 10, 280, 10, CNT_EA, 1, EF_EA, &r);
        CHECK(st == KZ2_EDGE_DONE && !memcmp(gp(OUT_EA), src + 10, 280) && untouched(OUT_EA + 280, 16) &&
              !strcmp(g_log, "PDF"), "mode 0 copy with window (log %s)", g_log);
        st = run(src, 300, 0, 0, 299, 0, CNT_EA, 1, EF_EA, &r);
        CHECK(st == KZ2_EDGE_FB_COPY && untouched(OUT_EA, 16) && !g_log[0], "mode 0 in != expected -> fallback");
        /* Overlap: out = in + 16. */
        reset_guest(); wbe32(CNT_EA, 1);
        memcpy(gp(IN_EA), src, 300);
        kz2_edge_elem e = { IN_EA, IN_EA + 16, 300, 300, CNT_EA, EF_EA, 1, 0, 0 };
        st = kz2_edge_run(&e, &OPS, scratch, &r);
        CHECK(st == KZ2_EDGE_DONE && !memcmp(gp(IN_EA + 16), src, 300), "mode 0 overlapping in/out");
    }

    /* Bad output EA: fallback, counter untouched. */
    {
        uint32_t zn, pn;
        uint8_t* z = load(dir, "fixed.deflate", &zn);
        uint8_t* p = load(dir, "fixed.plain", &pn);
        reset_guest(); wbe32(CNT_EA, 1); memcpy(gp(IN_EA), z, zn);
        kz2_edge_elem e = { IN_EA, 0x20, zn, pn, CNT_EA | 1u, EF_EA, 1, 0, 0 };
        kz2_edge_result r;
        const int st = kz2_edge_run(&e, &OPS, scratch, &r);
        CHECK(st == KZ2_EDGE_FB_PUT && rbe32(CNT_EA) == 1 && !g_log[0], "unwritable output -> fallback");
        free(z); free(p);
    }

    printf("%s: %d passed, %d failed\n", fails ? "FAIL" : "PASS", passes, fails);
    return fails ? 1 : 0;
}
