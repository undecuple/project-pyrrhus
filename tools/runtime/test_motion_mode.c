/* Host test for the valves' and charges' stick tilt (port/kz2/kz2_motion.h) and gameplay.ini's motion key
 * (kz2_gameplay.c). Simulates the game's own math on the hook's output: roll = atan(-a / sqrt(b^2 + c^2)) as
 * @0x00127210 / @0x00074A90 compute it, the 1 deg follower band of both controllers, the charge's ArmRanges windows
 * (0.741765..0.829031 of 45 deg on each side, ExplosiveLocationResource) and the valve's +-35 deg hand clamp; and
 * shows why patch 4015's map (36 deg at full stick) failed short of full travel. */
#include <stdio.h>
#include <math.h>
#include "kz2_motion.h"
#include "kz2_gameplay.h"

static int fails = 0;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

static const float WMIN = 0.741765f * 45.0f, WMAX = 0.829031f * 45.0f, BAND = 0.0174533f * 57.29578f;

/* Hand (degrees) after sweeping the stick from 0 to s and holding it (the follower comes from below). */
static float hand_after(float s, float (*map)(float))
{
    float cur = 0.0f;
    for (int i = 1; i <= 50; i++) {
        float v[3];
        kz2_motion_vec(map(s * (float)i / 50.0f), v);
        cur = kz2_motion_follow(cur, -kz2_motion_roll_deg(v), BAND);
    }
    return cur;
}
static float map_new(float s) { return kz2_motion_deg(s); }
static float map_4015(float s) { return 36.0f * s; }
static int in_window(float h) { const float a = fabsf(h); return a >= WMIN && a <= WMAX; }

int main(void)
{
    /* the vector gives the tilt back through the game's roll */
    for (float d = -40.0f; d <= 40.0f; d += 5.0f) {
        float v[3]; kz2_motion_vec(d, v);
        CHECK(fabsf(-kz2_motion_roll_deg(v) - d) < 0.01f, "roll of %.1f deg", d);
    }
    /* stick bytes */
    CHECK(kz2_motion_unit(0) == -1.0f && kz2_motion_unit(128) == 0.0f && kz2_motion_unit(255) == 1.0f, "stick unit");
    /* the charge arms from 57 % of the stick to 100 %, on both sides; the hand sits at the window centre at full stick */
    float first = -1.0f;
    for (int p = 0; p <= 100; p++) {
        const float s = p / 100.0f;
        const int inw = in_window(hand_after(s, map_new)) && in_window(hand_after(-s, map_new));
        if (inw && first < 0) first = s;
        if (p >= 58) CHECK(inw, "new map: stick %d %% arms both windows (hand %.2f)", p, hand_after(s, map_new));
    }
    printf("new map: arms from %.0f %% of the stick; hand at full stick %+.3f / %+.3f deg (window %.2f..%.2f)\n", first * 100.0f,
           hand_after(1.0f, map_new), hand_after(-1.0f, map_new), WMIN, WMAX);
    CHECK(first > 0.5f && first < 0.6f, "new map arms from 50..60 %% (got %.2f)", first);
    CHECK(fabsf(hand_after(1.0f, map_new) - (WMIN + WMAX) / 2.0f) < 0.01f, "full stick = window centre");
    /* 4015's map: only the last few per cent armed */
    float f4015 = -1.0f;
    for (int p = 0; p <= 100; p++) if (f4015 < 0 && in_window(hand_after(p / 100.0f, map_4015))) f4015 = p / 100.0f;
    printf("patch 4015's map: arms from %.0f %% of the stick (95 %% stick: hand %.2f deg, out of the window)\n", f4015 * 100.0f,
           hand_after(0.95f, map_4015));
    CHECK(f4015 >= 0.95f && !in_window(hand_after(0.95f, map_4015)), "4015 needed >= 96 %% (got %.2f)", f4015);
    /* valve: the +-35 deg hand clamp is reached from 60 % of the stick */
    CHECK(hand_after(0.6f, map_new) >= 35.0f && hand_after(-0.6f, map_new) <= -35.0f, "valve clamp reached at 60 %%");
    /* the return swing crosses back through 0 */
    CHECK(fabsf(kz2_motion_deg(0.0f)) == 0.0f && kz2_motion_deg(-0.3f) < 0.0f, "rest and sign");
    /* feed rules */
    CHECK(kz2_motion_feed(KZ2_MOTION_OFF, 1) && kz2_motion_feed(KZ2_MOTION_OFF, 0), "off always feeds");
    CHECK(!kz2_motion_feed(KZ2_MOTION_ON, 0) && !kz2_motion_feed(KZ2_MOTION_ON, 1), "on never feeds");
    CHECK(kz2_motion_feed(KZ2_MOTION_AUTO, 0) && !kz2_motion_feed(KZ2_MOTION_AUTO, 1), "auto feeds without a working accelerometer");
    /* gameplay.ini */
    kz2_gameplay_cfg c;
    CHECK(kz2_gp_ini_parse("", &c) == 0 && c.motion == KZ2_MOTION_AUTO, "default auto");
    CHECK(kz2_gp_ini_parse("[gameplay]\nmotion = off\n", &c) == 0 && c.motion == KZ2_MOTION_OFF, "motion off");
    CHECK(kz2_gp_ini_parse("[gameplay]\nmotion=ON\n", &c) == 0 && c.motion == KZ2_MOTION_ON, "motion on");
    CHECK(kz2_gp_ini_parse("[gameplay]\nmotion = sideways\n", &c) == 1 && c.motion == KZ2_MOTION_AUTO, "bad value counted");
    CHECK(kz2_gp_ini_parse("[mouse]\nmotion = off\n", &c) == 0 && c.motion == KZ2_MOTION_AUTO, "other section ignored");
    CHECK(kz2_gp_apply_motion_env(&c, "off") == 0 && c.motion == KZ2_MOTION_OFF, "env off");
    CHECK(kz2_gp_apply_motion_env(&c, "x") == 1 && c.motion == KZ2_MOTION_OFF, "bad env ignored");
    printf(fails ? "test_motion_mode: %d FAILED\n" : "test_motion_mode: all passed\n", fails);
    return fails ? 1 : 0;
}
