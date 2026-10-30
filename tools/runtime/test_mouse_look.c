/* Host test for the mouse look: pad_mouse.h (script parse, due events, clip decision, in-play window) from
 * patch 6046 and the [mouse] settings and look arithmetic in port/kz2/kz2_gameplay.[ch]. */
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "pad_mouse.h"
#include "kz2_gameplay.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
#define NEAR(a, b) (fabs((double)(a) - (double)(b)) < 1e-5 * (1.0 + fabs((double)(b))))

int main(int argc, char** argv)
{
    if (argc > 1 && !strcmp(argv[1], "get")) { kz2_gameplay_get(); return 0; }
    /* script parse */
    PadMouseEv ev[8];
    int bad = -1, n = pad_mouse_script_parse("5:600,0 8.5:0,-100*4;9:-3,2|x:1,1 7:1 3:1,2*0", ev, 8, &bad);
    CHECK(n == 3 && bad == 3);
    CHECK(ev[0].t == 5.0 && ev[0].dx == 600 && ev[0].dy == 0 && ev[0].left == 1);
    CHECK(ev[1].t == 8.5 && ev[1].dy == -100 && ev[1].left == 4 && ev[2].dx == -3 && ev[2].dy == 2);
    CHECK(pad_mouse_script_parse(NULL, ev, 8, &bad) == 0 && bad == 0);
    CHECK(pad_mouse_script_parse("1:1,1 2:2,2 3:3,3", ev, 2, &bad) == 2 && bad == 1);
    /* due: each event once per update until its count runs out; nothing before its time */
    n = pad_mouse_script_parse("1:10,0*2 2:0,5", ev, 8, &bad);
    int dx = 0, dy = 0;
    CHECK(!pad_mouse_script_due(ev, n, 0.5, &dx, &dy) && dx == 0);
    CHECK(pad_mouse_script_due(ev, n, 1.0, &dx, &dy) && dx == 10 && dy == 0);
    CHECK(pad_mouse_script_due(ev, n, 2.0, &dx, &dy) && dx == 20 && dy == 5);
    CHECK(!pad_mouse_script_due(ev, n, 3.0, &dx, &dy) && dx == 20 && dy == 5);
    /* clip: focused, live and in play; released in menus (not in play), on focus loss, minimise, drag, close, look off */
    PadMouseClip s = {1, 0, 0, 0, 1, 1};
    CHECK(pad_mouse_clip_want(&s));
    s.in_play = 0; CHECK(!pad_mouse_clip_want(&s)); s.in_play = 1;
    s.focused = 0; CHECK(!pad_mouse_clip_want(&s)); s.focused = 1;
    s.minimized = 1; CHECK(!pad_mouse_clip_want(&s)); s.minimized = 0;
    s.sizemove = 1; CHECK(!pad_mouse_clip_want(&s)); s.sizemove = 0;
    s.closing = 1; CHECK(!pad_mouse_clip_want(&s)); s.closing = 0;
    s.look_on = 0; CHECK(!pad_mouse_clip_want(&s));
    CHECK(!pad_mouse_in_play(1000, 0) && pad_mouse_in_play(1000, 1000) && pad_mouse_in_play(1300, 1000));
    CHECK(!pad_mouse_in_play(1301, 1000) && !pad_mouse_in_play(999, 1000));
    /* [mouse] settings: defaults, file, bad values, env wins */
    kz2_gameplay_cfg c;
    CHECK(kz2_gp_ini_parse("", &c) == 0 && c.mouse_look == 1 && c.mouse_sens == 2.5f && c.mouse_zoom == 1.0f &&
          c.mouse_yaw == 0.022f && c.mouse_invert == 0 && c.aim_assist == KZ2_AIM_AUTO);
    CHECK(kz2_gp_ini_parse("[mouse]\nmouse_look = 0\nmouse_sensitivity = 4\nmouse_zoom_sensitivity=0.5\nmouse_invert_y = yes\n"
                           "mouse_yaw = 0.0066\n[gameplay]\nmouse_look = 1\n", &c) == 0);
    CHECK(c.mouse_look == 0 && c.mouse_sens == 4.0f && c.mouse_zoom == 0.5f && c.mouse_invert == 1 && NEAR(c.mouse_yaw, 0.0066));
    CHECK(kz2_gp_ini_parse("[mouse]\nmouse_sensitivity = -1\nmouse_zoom_sensitivity = fast\nmouse_look = maybe\nmouse_yaw = 0\n", &c) == 4);
    CHECK(c.mouse_sens == 2.5f && c.mouse_zoom == 1.0f && c.mouse_look == 1 && c.mouse_yaw == 0.022f);
    CHECK(kz2_gp_ini_parse("[gameplay]\naim_assist = off\n[mouse]\naim_assist = on\n", &c) == 0 && c.aim_assist == KZ2_AIM_OFF);
    kz2_gp_ini_parse("[mouse]\nmouse_sensitivity = 4\n", &c);
    CHECK(kz2_gp_apply_mouse_env(&c, "0", "1.5", "2", NULL, "1") == 0 && c.mouse_look == 0 && c.mouse_sens == 1.5f &&
          c.mouse_zoom == 2.0f && c.mouse_invert == 1);
    CHECK(kz2_gp_apply_mouse_env(&c, "x", "nan", "", "1e9", NULL) == 3 && c.mouse_sens == 1.5f && c.mouse_yaw == 0.022f);
    /* arithmetic: 2.5 x 0.022 deg = 0.055 deg per count, the same for every speed (no acceleration) */
    kz2_gp_ini_parse("", &c);
    const float k = kz2_mouse_rad_per_count(&c);
    CHECK(NEAR(k, 0.055 * M_PI / 180.0));
    float yaw, pitch;
    kz2_mouse_angles(&c, 100, -50, 0, &yaw, &pitch);
    CHECK(NEAR(yaw, 100 * k) && NEAR(pitch, 50 * k));
    float y2, p2;
    kz2_mouse_angles(&c, 1000, -500, 0, &y2, &p2);
    CHECK(NEAR(y2, 10 * yaw) && NEAR(p2, 10 * pitch));
    c.mouse_invert = 1; kz2_mouse_angles(&c, 0, -50, 0, &yaw, &pitch); CHECK(NEAR(pitch, -50 * k)); c.mouse_invert = 0;
    c.mouse_zoom = 0.5f; kz2_mouse_angles(&c, 100, 0, 1, &yaw, &pitch); CHECK(NEAR(yaw, 50 * k));
    kz2_mouse_angles(&c, 100, 0, 0, &yaw, &pitch); CHECK(NEAR(yaw, 100 * k));
    /* rate: turn 180 deg/s, dt 1/30 s: 0.1 rad needs 0.1 / (pi x 1/30) */
    CHECK(NEAR(kz2_mouse_rate_for(0.1f, 180.0f, 1.0f / 30.0f), 0.1 / (M_PI / 30.0)));
    CHECK(kz2_mouse_rate_for(0.1f, 0.0f, 0.033f) == 0.0f && kz2_mouse_rate_for(0.1f, 180.0f, 0.0f) == 0.0f);
    CHECK(kz2_mouse_rate_for(0.1f, NAN, 0.033f) == 0.0f);
    /* pitch clamp to the game's limits; an unusable range does not clamp */
    CHECK(NEAR(kz2_mouse_pitch(0.2f, 0.1f, -1.0f, 1.0f), 0.3f));
    CHECK(kz2_mouse_pitch(0.9f, 0.5f, -1.0f, 1.0f) == 1.0f && kz2_mouse_pitch(-0.9f, -0.5f, -1.0f, 1.0f) == -1.0f);
    CHECK(NEAR(kz2_mouse_pitch(0.9f, 0.5f, 1.0f, -1.0f), 1.4f) && NEAR(kz2_mouse_pitch(0.9f, 0.5f, NAN, 1.0f), 1.4f));
    /* last look device and aim_assist=auto */
    kz2_look_src ls = {0};
    CHECK(kz2_gp_aim_on(&c, ls.mouse) == 1);
    kz2_look_note(&ls, 0.0f, 0.0f, 0.25f, 1); CHECK(ls.mouse == 1 && kz2_gp_aim_on(&c, ls.mouse) == 0);
    kz2_look_note(&ls, 0.1f, -0.2f, 0.25f, 0); CHECK(ls.mouse == 1);   /* stick at rest (inside the dead zone): no change */
    kz2_look_note(&ls, 0.0f, -0.8f, 0.25f, 0); CHECK(ls.mouse == 0 && kz2_gp_aim_on(&c, ls.mouse) == 1);
    kz2_look_note(&ls, 0.9f, 0.0f, 0.25f, 1); CHECK(ls.mouse == 1);   /* both in one update: the mouse moved */
    c.aim_assist = KZ2_AIM_ON; CHECK(kz2_gp_aim_on(&c, 1) == 1);
    c.aim_assist = KZ2_AIM_OFF; CHECK(kz2_gp_aim_on(&c, 0) == 0);
    if (fails) { printf("test_mouse_look: %d failure(s)\n", fails); return 1; }
    printf("test_mouse_look: ok\n");
    return 0;
}
