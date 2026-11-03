/* Host test: libs/video/rsx_pre_hud.h (KZ2 patch 6052, where the HUD starts). Walks Killzone 2's frame order from the
 * gated draw captures (the RE notes rounds 20 and 67b). No game data, no GPU. */
#include <stdio.h>
#include "rsx_pre_hud.h"

static int fails;
#define OK(c) do { if (!(c)) { printf("[FAIL] %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

enum { LIGHT = 1, GRADE = 1, HALF = 2, GBUF = 3, D0 = 10, D1 = 11, UI = 4 };
static int buf_of(unsigned t) { return t == D0 ? 0 : t == D1 ? 1 : -1; }

/* one frame: n draws per entry; returns the index of the draw before which the tap ran (-1 none), and how many draws
 * into the display buffer were redirected */
static int frame(rsx_pre_hud* p, const unsigned* seq, const int* n, int k, int* redirected)
{
    int at = -1, i = 0;
    *redirected = 0;
    for (int e = 0; e < k; e++)
        for (int j = 0; j < n[e]; j++, i++) {
            if (rsx_pre_hud_draw(p, seq[e], buf_of(seq[e]))) { OK(at < 0); at = i; rsx_pre_hud_tapped(p, seq[e]); }
            if (rsx_pre_hud_redirects(p, seq[e])) { OK(seq[e] == p->target); (*redirected)++; }
        }
    rsx_pre_hud_reset(p);
    return at;
}

int main(void)
{
    rsx_pre_hud p;
    rsx_pre_hud_reset(&p);
    int red;
    /* play: lights + grading into the sample buffer, the resolve (1 draw) into D0, the half-res chain, the next
     * frame's G-buffer, then the HUD into D0 (with an offscreen run in between: still the HUD's frame) */
    const unsigned play[] = { LIGHT, GRADE, D0, HALF, GBUF, D0, UI, D0 };
    const int pn[] = { 300, 1, 1, 145, 710, 4, 3, 2 };
    const int first_hud = 300 + 1 + 1 + 145 + 710;
    OK(frame(&p, play, pn, 8, &red) == first_hud && red == 6);
    /* the next frame flips the other buffer: same again on D1, nothing carried over */
    const unsigned play1[] = { LIGHT, D1, HALF, GBUF, D1 };
    const int pn1[] = { 300, 1, 145, 710, 6 };
    OK(frame(&p, play1, pn1, 5, &red) == 300 + 1 + 145 + 710 && red == 6);
    /* front end: the UI drawn offscreen, then copied into the display buffer in one visit: no tap (FSR at present) */
    const unsigned menu[] = { UI, D0 };
    const int mn[] = { 253, 3 };
    OK(frame(&p, menu, mn, 2, &red) == -1 && red == 0);
    /* a loading frame with no display-buffer draws */
    const unsigned load[] = { UI };
    const int ln[] = { 10 };
    OK(frame(&p, load, ln, 1, &red) == -1 && red == 0);
    /* back-to-back draws into the display buffer are one visit; draws into the other buffer do not count for this one */
    const unsigned mix[] = { D0, D1, D0 };
    const int xn[] = { 5, 1, 2 };
    OK(frame(&p, mix, xn, 3, &red) == 6 && red == 2);
    /* a display buffer id out of range is ignored */
    rsx_pre_hud_reset(&p);
    OK(!rsx_pre_hud_draw(&p, 99, 8) && !rsx_pre_hud_draw(&p, 98, 8) && !rsx_pre_hud_draw(&p, 99, 8));
    /* without the tap (FSR off: the caller passes -1) nothing is counted */
    rsx_pre_hud_reset(&p);
    OK(!rsx_pre_hud_draw(&p, D0, -1) && !rsx_pre_hud_draw(&p, HALF, -1) && !rsx_pre_hud_draw(&p, D0, -1));
    /* saturation: 300 visits do not wrap back to 2 */
    rsx_pre_hud_reset(&p);
    int taps = 0;
    for (int i = 0; i < 300; i++) { taps += rsx_pre_hud_draw(&p, D0, 0); rsx_pre_hud_draw(&p, HALF, -1); }
    OK(taps == 1);
    if (fails) { printf("FAIL: %d\n", fails); return 1; }
    printf("PASS: pre-HUD rule (play, next buffer, front end, loading, mixed buffers, range, off, saturation)\n");
    return 0;
}
