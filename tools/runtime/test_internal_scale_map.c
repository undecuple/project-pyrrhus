/* Host test for the internal resolution scale mapping (patch 2300, libs/video/rsx_internal_scale.h): checked
 * conversion between guest pixel, guest sample and physical extents, and the equivalence of the live-draw call sites
 * routed through it (draw and clear scissor, viewport, WPOS divisor, DDX/DDY scale) with the code they replaced. */
#include <stdio.h>
#include <string.h>
#include "rsx_internal_scale.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

static rsx_iscale_grid G(uint32_t x, uint32_t y) { return rsx_iscale_grid_make(x, y); }
static int rect_eq(rsx_iscale_rect a, uint32_t l, uint32_t t, uint32_t r, uint32_t b)
{
    return a.left == l && a.top == t && a.right == r && a.bottom == b;
}
/* The AA grids the RSX has: 1x1, 2x1 (DIAGONAL_CENTERED_2) and 2x2 (SQUARE_*). */
static const uint32_t AA[3][2] = { { 1, 1 }, { 2, 1 }, { 2, 2 } };

static void identity(void)
{
    static const uint32_t v[] = { 0u, 1u, 2u, 639u, 640u, 1279u, 1280u, 0xFFFFu, 0x10000u, 0x3FFFFFFFu,
                                  RSX_ISCALE_COORD_MAX - 1u, RSX_ISCALE_COORD_MAX };
    const unsigned n = sizeof v / sizeof v[0];
    const rsx_iscale_grid one = rsx_iscale_native();
    CHECK(rsx_iscale_grid_is_native(one) && rsx_iscale_grid_ok(one));
    for (unsigned i = 0; i < n; i++)
        for (unsigned j = 0; j < n; j++) {
            rsx_iscale_point p = { v[i], v[j] }, q = { 7u, 7u };
            CHECK(rsx_iscale_map_point(p, one, &q) == RSX_ISCALE_OK && q.x == v[i] && q.y == v[j]);
            rsx_iscale_extent e = { v[i], v[j] }, f = { 7u, 7u };
            CHECK(rsx_iscale_map_extent(e, one, &f) == RSX_ISCALE_OK && f.w == v[i] && f.h == v[j]);
            CHECK(rsx_iscale_unmap_extent(e, one, &f) == RSX_ISCALE_OK && f.w == v[i] && f.h == v[j]);
            if (v[i] <= v[j]) {
                rsx_iscale_rect r = { v[i], v[i], v[j], v[j] }, s;
                CHECK(rsx_iscale_map_rect(r, one, &s) == RSX_ISCALE_OK && rect_eq(s, v[i], v[i], v[j], v[j]));
            }
        }
    /* composing with the native scale gives the AA grid back */
    for (int a = 0; a < 3; a++) {
        rsx_iscale_grid c;
        CHECK(rsx_iscale_compose(G(AA[a][0], AA[a][1]), one, &c) == RSX_ISCALE_OK && c.x == AA[a][0] && c.y == AA[a][1]);
    }
}

static void aa_grids(void)
{
    /* 1280x720 pixels on each grid, at the native scale and at 2x */
    static const uint32_t sample[3][2] = { { 1280, 720 }, { 2560, 720 }, { 2560, 1440 } };
    for (int a = 0; a < 3; a++) {
        const rsx_iscale_extent px = { 1280, 720 };
        rsx_iscale_target t;
        CHECK(rsx_iscale_target_from_pixel(px, G(AA[a][0], AA[a][1]), rsx_iscale_native(), &t) == RSX_ISCALE_OK);
        CHECK(t.pixel.w == 1280 && t.pixel.h == 720);
        CHECK(t.sample.w == sample[a][0] && t.sample.h == sample[a][1]);
        CHECK(t.physical.w == t.sample.w && t.physical.h == t.sample.h);   /* native: physical == sample */
        rsx_iscale_target u;
        CHECK(rsx_iscale_target_from_sample(t.sample, t.aa, rsx_iscale_native(), &u) == RSX_ISCALE_OK);
        CHECK(!memcmp(&t, &u, sizeof t));
        CHECK(rsx_iscale_target_from_pixel(px, G(AA[a][0], AA[a][1]), G(2, 2), &t) == RSX_ISCALE_OK);
        CHECK(t.sample.w == sample[a][0] && t.sample.h == sample[a][1]);   /* the guest's sizes do not move */
        CHECK(t.physical.w == 2 * sample[a][0] && t.physical.h == 2 * sample[a][1]);
    }
    /* the example in the header: 2x1 AA, 2x internal scale */
    rsx_iscale_target t;
    const rsx_iscale_extent s = { 2560, 720 };
    CHECK(rsx_iscale_target_from_sample(s, G(2, 1), G(2, 2), &t) == RSX_ISCALE_OK);
    CHECK(t.pixel.w == 1280 && t.pixel.h == 720 && t.physical.w == 5120 && t.physical.h == 1440);
    /* a sample extent that is not whole pixels is refused, not rounded */
    const rsx_iscale_extent odd = { 2561, 720 };
    t.pixel.w = 99;
    CHECK(rsx_iscale_target_from_sample(odd, G(2, 1), rsx_iscale_native(), &t) == RSX_ISCALE_E_EXTENT && t.pixel.w == 99);
}

/* The draw path's scissor before patch 2300 (patch 2006/2088): pixels times the grid, endpoint = origin + size. */
static void old_scissor(uint32_t sh, uint32_t sv, long ax, long ay, long* l, long* t, long* r, long* b)
{
    const long sx = (long)(sh & 0xFFFFu) * ax, sw = (long)(sh >> 16) * ax;
    const long sy = (long)(sv & 0xFFFFu) * ay, svh = (long)(sv >> 16) * ay;
    *l = sx; *t = sy; *r = sx + sw; *b = sy + svh;
}

static void scissor_and_clear(void)
{
    /* every 16-bit origin against a spread of sizes, on every grid: the routed mapping gives the old endpoints */
    static const uint32_t sizes[] = { 0u, 1u, 2u, 3u, 360u, 640u, 720u, 1280u, 4096u, 0xFFFEu, 0xFFFFu };
    unsigned bad = 0;
    for (int a = 0; a < 3; a++)
        for (uint32_t x = 0; x <= 0xFFFFu; x++)
            for (unsigned k = 0; k < sizeof sizes / sizeof sizes[0]; k++) {
                const uint32_t sh = x | (sizes[k] << 16), sv = ((x * 7u) & 0xFFFFu) | (sizes[(k + 3) % 11] << 16);
                long l, t, r, b;
                old_scissor(sh, sv, (long)AA[a][0], (long)AA[a][1], &l, &t, &r, &b);
                /* the draw path: one mapping by the AA grid composed with the scale; the clear: by the AA grid, then
                 * (after the clip) by the scale */
                rsx_iscale_rect px, sm, ph, dr;
                rsx_iscale_grid cg;
                if (rsx_iscale_rect_from_origin_size(sh & 0xFFFFu, sv & 0xFFFFu, sh >> 16, sv >> 16, &px) != RSX_ISCALE_OK ||
                    rsx_iscale_compose(G(AA[a][0], AA[a][1]), rsx_iscale_native(), &cg) != RSX_ISCALE_OK ||
                    rsx_iscale_map_rect(px, cg, &dr) != RSX_ISCALE_OK ||
                    !rect_eq(dr, (uint32_t)l, (uint32_t)t, (uint32_t)r, (uint32_t)b) ||
                    rsx_iscale_map_rect(px, G(AA[a][0], AA[a][1]), &sm) != RSX_ISCALE_OK ||
                    !rect_eq(sm, (uint32_t)l, (uint32_t)t, (uint32_t)r, (uint32_t)b) ||
                    rsx_iscale_map_rect(sm, rsx_iscale_native(), &ph) != RSX_ISCALE_OK || memcmp(&ph, &sm, sizeof ph))
                    bad++;
            }
    CHECK(bad == 0);

    /* a non-zero origin and a partial rectangle keep their exact size on every grid and scale */
    rsx_iscale_rect px, m;
    CHECK(rsx_iscale_rect_from_origin_size(100, 50, 640, 360, &px) == RSX_ISCALE_OK && rect_eq(px, 100, 50, 740, 410));
    CHECK(rsx_iscale_map_rect(px, G(2, 1), &m) == RSX_ISCALE_OK && rect_eq(m, 200, 50, 1480, 410));
    CHECK(m.right - m.left == 2 * 640 && m.bottom - m.top == 360);
    rsx_iscale_grid c;
    CHECK(rsx_iscale_compose(G(2, 1), G(2, 2), &c) == RSX_ISCALE_OK && c.x == 4 && c.y == 2);
    CHECK(rsx_iscale_map_rect(px, c, &m) == RSX_ISCALE_OK && rect_eq(m, 400, 100, 2960, 820));
    /* mapping in two steps (AA, then scale) is the same as the composed grid */
    rsx_iscale_rect m1, m2;
    CHECK(rsx_iscale_map_rect(px, G(2, 1), &m1) == RSX_ISCALE_OK && rsx_iscale_map_rect(m1, G(2, 2), &m2) == RSX_ISCALE_OK);
    CHECK(!memcmp(&m, &m2, sizeof m));

    /* a partial clear: the guest scissor in samples intersected with the 2560x720 clip of a 2x1 target, then physical */
    CHECK(rsx_iscale_rect_from_origin_size(640, 0, 1280, 720, &px) == RSX_ISCALE_OK);
    CHECK(rsx_iscale_map_rect(px, G(2, 1), &m) == RSX_ISCALE_OK && rect_eq(m, 1280, 0, 3840, 720));
    {
        rsx_iscale_rect clip = { 0, 0, 2560, 720 }, cl = m, ph;
        if (cl.right > clip.right) cl.right = clip.right;
        CHECK(rect_eq(cl, 1280, 0, 2560, 720));
        CHECK(rsx_iscale_map_rect(cl, rsx_iscale_native(), &ph) == RSX_ISCALE_OK && rect_eq(ph, 1280, 0, 2560, 720));
        CHECK(rsx_iscale_map_rect(cl, G(2, 2), &ph) == RSX_ISCALE_OK && rect_eq(ph, 2560, 0, 5120, 1440));
    }
    /* an alias subrectangle: the top-left 640x360 of a 1280x720 surface stays in guest space; only physical moves */
    CHECK(rsx_iscale_rect_from_origin_size(0, 0, 640, 360, &px) == RSX_ISCALE_OK);
    CHECK(rsx_iscale_map_rect(px, rsx_iscale_native(), &m) == RSX_ISCALE_OK && rect_eq(m, 0, 0, 640, 360));
    CHECK(rsx_iscale_map_rect(px, G(2, 2), &m) == RSX_ISCALE_OK && rect_eq(m, 0, 0, 1280, 720));

    /* the viewport: the sample extent through the native scale is itself (exact as a float as well) */
    for (int a = 0; a < 3; a++) {
        const rsx_iscale_extent vs = { 1280u * AA[a][0], 720u * AA[a][1] };
        rsx_iscale_extent vp;
        CHECK(rsx_iscale_map_extent(vs, rsx_iscale_native(), &vp) == RSX_ISCALE_OK);
        CHECK((float)vp.w == (float)vs.w && (float)vp.h == (float)vs.h);
    }
}

static void zero_and_max(void)
{
    rsx_iscale_rect r, m;
    /* a written zero width or height is a real, empty scissor: valid, maps to an empty rectangle */
    CHECK(rsx_iscale_rect_from_origin_size(1039, 0, 0, 720, &r) == RSX_ISCALE_OK && r.left == r.right);
    CHECK(rsx_iscale_map_rect(r, G(2, 2), &m) == RSX_ISCALE_OK && m.left == m.right && m.left == 2078);
    const rsx_iscale_extent z = { 0, 0 };
    rsx_iscale_extent e;
    CHECK(rsx_iscale_map_extent(z, G(2, 2), &e) == RSX_ISCALE_OK && e.w == 0 && e.h == 0);
    CHECK(rsx_iscale_unmap_extent(z, G(2, 1), &e) == RSX_ISCALE_OK && e.w == 0 && e.h == 0);
    /* the largest valid values */
    uint32_t o = 0;
    CHECK(rsx_iscale_mul(RSX_ISCALE_COORD_MAX, 1, &o) == RSX_ISCALE_OK && o == RSX_ISCALE_COORD_MAX);
    CHECK(rsx_iscale_mul(0x3FFFFFFFu, 2, &o) == RSX_ISCALE_OK && o == 0x7FFFFFFEu);
    CHECK(rsx_iscale_mul(0x7FFFFFFFu / 16u, 16, &o) == RSX_ISCALE_OK);
    CHECK(rsx_iscale_add(RSX_ISCALE_COORD_MAX - 5u, 5u, &o) == RSX_ISCALE_OK && o == RSX_ISCALE_COORD_MAX);
    /* the largest guest scissor (16-bit origin and size) on the largest grid an RSX target has, at 2x */
    rsx_iscale_grid c;
    CHECK(rsx_iscale_compose(G(2, 2), G(2, 2), &c) == RSX_ISCALE_OK);
    CHECK(rsx_iscale_rect_from_origin_size(0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, &r) == RSX_ISCALE_OK);
    CHECK(rsx_iscale_map_rect(r, c, &m) == RSX_ISCALE_OK && m.right == 0x1FFFEu * 4u);
}

static void overflow_and_invalid(void)
{
    uint32_t o = 1234;
    /* multiplication */
    CHECK(rsx_iscale_mul(0x40000000u, 2, &o) == RSX_ISCALE_E_OVERFLOW && o == 1234);
    CHECK(rsx_iscale_mul(RSX_ISCALE_COORD_MAX, 2, &o) == RSX_ISCALE_E_OVERFLOW && o == 1234);
    CHECK(rsx_iscale_mul(0xFFFFFFFFu, 16, &o) == RSX_ISCALE_E_OVERFLOW && o == 1234);   /* no 32-bit wrap */
    CHECK(rsx_iscale_mul(0x80000000u, 1, &o) == RSX_ISCALE_E_OVERFLOW && o == 1234);   /* above the signed range */
    /* endpoints */
    CHECK(rsx_iscale_add(RSX_ISCALE_COORD_MAX, 1, &o) == RSX_ISCALE_E_OVERFLOW && o == 1234);
    CHECK(rsx_iscale_add(0xFFFFFFFFu, 0xFFFFFFFFu, &o) == RSX_ISCALE_E_OVERFLOW && o == 1234);
    rsx_iscale_rect r = { 9, 9, 9, 9 }, keep = r;
    CHECK(rsx_iscale_rect_from_origin_size(RSX_ISCALE_COORD_MAX, 0, 1, 1, &r) == RSX_ISCALE_E_OVERFLOW && !memcmp(&r, &keep, sizeof r));
    CHECK(rsx_iscale_rect_from_origin_size(0, RSX_ISCALE_COORD_MAX, 1, 1, &r) == RSX_ISCALE_E_OVERFLOW && !memcmp(&r, &keep, sizeof r));
    const rsx_iscale_rect big = { 0x30000000u, 0, 0x40000000u, 1 };   /* left fits at 2x, right does not */
    CHECK(rsx_iscale_map_rect(big, G(2, 1), &r) == RSX_ISCALE_E_OVERFLOW && !memcmp(&r, &keep, sizeof r));
    rsx_iscale_extent e = { 5, 5 };
    const rsx_iscale_extent huge = { 1, 0x40000000u };
    CHECK(rsx_iscale_map_extent(huge, G(1, 2), &e) == RSX_ISCALE_E_OVERFLOW && e.w == 5 && e.h == 5);
    rsx_iscale_point p = { 5, 5 };
    const rsx_iscale_point hp = { 0x40000000u, 0 };
    CHECK(rsx_iscale_map_point(hp, G(2, 1), &p) == RSX_ISCALE_E_OVERFLOW && p.x == 5);

    /* invalid factors */
    CHECK(!rsx_iscale_factor_ok(0) && rsx_iscale_factor_ok(1) && rsx_iscale_factor_ok(16) && !rsx_iscale_factor_ok(17));
    CHECK(rsx_iscale_mul(10, 0, &o) == RSX_ISCALE_E_FACTOR && o == 1234);
    CHECK(rsx_iscale_mul(10, 17, &o) == RSX_ISCALE_E_FACTOR && o == 1234);
    const rsx_iscale_rect ok = { 0, 0, 10, 10 };
    CHECK(rsx_iscale_map_rect(ok, G(0, 1), &r) == RSX_ISCALE_E_FACTOR && !memcmp(&r, &keep, sizeof r));
    CHECK(rsx_iscale_map_rect(ok, G(1, 0xFFFFFFFFu), &r) == RSX_ISCALE_E_FACTOR && !memcmp(&r, &keep, sizeof r));
    CHECK(rsx_iscale_map_extent(e, G(1, 0), &e) == RSX_ISCALE_E_FACTOR);
    CHECK(rsx_iscale_unmap_extent(e, G(0, 1), &e) == RSX_ISCALE_E_FACTOR);
    rsx_iscale_grid c = { 3, 3 };
    CHECK(rsx_iscale_compose(G(4, 1), G(8, 1), &c) == RSX_ISCALE_E_FACTOR && c.x == 3);   /* 32: too big */
    CHECK(rsx_iscale_compose(G(0, 1), G(1, 1), &c) == RSX_ISCALE_E_FACTOR && c.x == 3);
    CHECK(rsx_iscale_compose(G(16, 16), G(16, 16), &c) == RSX_ISCALE_E_FACTOR && c.x == 3);
    rsx_iscale_target t;
    memset(&t, 0x5A, sizeof t);
    const rsx_iscale_target tk = t;
    const rsx_iscale_extent px = { 1280, 720 };
    CHECK(rsx_iscale_target_from_pixel(px, G(2, 1), G(0, 0), &t) == RSX_ISCALE_E_FACTOR && !memcmp(&t, &tk, sizeof t));
    CHECK(rsx_iscale_target_from_sample(px, G(17, 1), G(1, 1), &t) == RSX_ISCALE_E_FACTOR && !memcmp(&t, &tk, sizeof t));

    /* malformed rectangles */
    const rsx_iscale_rect inv_x = { 10, 0, 9, 10 }, inv_y = { 0, 10, 10, 9 }, wide = { 0, 0, 0x80000000u, 1 };
    CHECK(rsx_iscale_map_rect(inv_x, rsx_iscale_native(), &r) == RSX_ISCALE_E_RECT && !memcmp(&r, &keep, sizeof r));
    CHECK(rsx_iscale_map_rect(inv_y, rsx_iscale_native(), &r) == RSX_ISCALE_E_RECT && !memcmp(&r, &keep, sizeof r));
    CHECK(rsx_iscale_map_rect(wide, rsx_iscale_native(), &r) == RSX_ISCALE_E_RECT && !memcmp(&r, &keep, sizeof r));
}

/* WPOS (patch 2088) and DDX/DDY (patch 2096) before patch 2300, from the packed record value wpos_aa. */
static void old_wpos(uint32_t wpos_aa, char* text, size_t n, float* dsx, float* dsy)
{
    const uint32_t ax = wpos_aa & 0xFFu, ay = (wpos_aa >> 8) & 0xFFu;
    snprintf(text, n, "float4(floor(input.position.xy / float2(%u.0, %u.0)) + 0.5, input.position.zw)",
             ax ? ax : 1u, ay ? ay : 1u);
    *dsx = ax > 1u ? (float)ax : 1.0f; *dsy = ay > 1u ? (float)ay : 1.0f;
}

static void shader_side(void)
{
    /* every packed grid up to the factor limit: the divisor through the native scale gives the same HLSL text and
     * the same derivative scale, so translated shaders, their hashes and the pipeline keys stay as they were */
    unsigned bad = 0;
    for (uint32_t ay = 0; ay <= RSX_ISCALE_FACTOR_MAX; ay++)
        for (uint32_t ax = 0; ax <= RSX_ISCALE_FACTOR_MAX; ax++) {
            const uint32_t wpos_aa = ax | (ay << 8);
            char a[160], b[160];
            float osx, osy;
            old_wpos(wpos_aa, a, sizeof a, &osx, &osy);
            rsx_iscale_grid d;
            if (rsx_iscale_compose(G(ax ? ax : 1u, ay ? ay : 1u), rsx_iscale_native(), &d) != RSX_ISCALE_OK) { bad++; continue; }
            snprintf(b, sizeof b, "float4(floor(input.position.xy / float2(%u.0, %u.0)) + 0.5, input.position.zw)", d.x, d.y);
            if (strcmp(a, b) || (float)d.x != osx || (float)d.y != osy) bad++;
        }
    CHECK(bad == 0);
    /* a packed factor above the limit is refused (the translation fails) rather than emitted */
    rsx_iscale_grid d = { 0, 0 };
    CHECK(rsx_iscale_compose(G(17, 1), rsx_iscale_native(), &d) == RSX_ISCALE_E_FACTOR && d.x == 0);

    /* the order: floor(p / (aa * s)) == floor(floor(p / s) / aa), so dividing by the composed grid at once is the
     * same as going physical -> samples -> pixels */
    for (int a = 0; a < 3; a++)
        for (uint32_t s = 1; s <= 4; s++) {
            unsigned diff = 0;
            for (uint32_t p = 0; p < 20000; p++)
                if (p / (AA[a][0] * s) != (p / s) / AA[a][0] || p / (AA[a][1] * s) != (p / s) / AA[a][1]) diff++;
            CHECK(diff == 0);
        }
}

int main(void)
{
    identity();
    aa_grids();
    scissor_and_clear();
    zero_and_max();
    overflow_and_invalid();
    shader_side();
    if (fails) { printf("test_internal_scale_map: %d failure(s)\n", fails); return 1; }
    printf("test_internal_scale_map: ok\n");
    return 0;
}
