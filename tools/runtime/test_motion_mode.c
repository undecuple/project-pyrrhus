/* Host test for the valves' and charges' stick tilt (port/kz2/kz2_motion.h) and gameplay.ini's motion key
 * (kz2_gameplay.c). Simulates the game's own math on the hook's output: roll = atan(-a / sqrt(b^2 + c^2)) as
 * @0x00127210 / @0x00074A90 compute it, the 1 deg follower band of both controllers, the charge's ArmRanges windows
 * (0.741765..0.829031 RADIANS on each side = 42.50..47.50 deg, ExplosiveLocationResource; an earlier change), the charge rep's
 * hand step @0x00117898 (MaxRotationSpeed 360 deg/s x 1/15, clamp MinAngle/MaxAngle +-45 deg) and the valve's +-35 deg
 * hand clamp; shows that rounds 65..73's 36.344 deg peak never armed, that the 44 deg Feralnet measured on public #47
 * arms, and that patch 4015's map (36 deg at full stick) never armed either. */
#include <stdio.h>
#include <math.h>
#include "kz2_motion.h"
#include "kz2_gameplay.h"

static int fails = 0;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

static const float WMIN = 0.741765f * 57.29578f, WMAX = 0.829031f * 57.29578f, BAND = 0.0174533f * 57.29578f;
static const float REP_STEP = 360.0f / 15.0f, REP_MAX = 45.0f;   /* ExplosiveLocationRep @0x00117898 */

/* Hand (degrees) after sweeping the stick from 0 to s and holding it (the follower comes from below). */
static float ctrl_after(float s, float (*map)(float))
{
    float cur = 0.0f;
    for (int i = 1; i <= 50; i++) {
        float v[3];
        kz2_motion_vec(map(s * (float)i / 50.0f), v);
        cur = kz2_motion_follow(cur, -kz2_motion_roll_deg(v), BAND);
    }
    return cur;
}
/* The charge rep's hand (E+0x25C, here in degrees) after the same sweep: it follows the controller's hand by at most
 * REP_STEP per update, clamped to +-REP_MAX; 20 more updates of the held stick. */
static float hand_after(float s, float (*map)(float))
{
    float cur = 0.0f, h = 0.0f;
    for (int i = 1; i <= 70; i++) {
        float v[3];
        kz2_motion_vec(map(s * (float)(i < 50 ? i : 50) / 50.0f), v);
        cur = kz2_motion_follow(cur, -kz2_motion_roll_deg(v), BAND);
        float d = cur - h;
        d = d < -REP_STEP ? -REP_STEP : d > REP_STEP ? REP_STEP : d;
        h += d;
        h = h < -REP_MAX ? -REP_MAX : h > REP_MAX ? REP_MAX : h;
    }
    return h;
}
static float map_old(float s) { const float m = fabsf(s) / 0.6f, d = 36.344f * (m > 1.0f ? 1.0f : m); return s < 0 ? -d : d; }
static float map_44(float s) { const float m = fabsf(s) / 0.6f, d = 44.0f * (m > 1.0f ? 1.0f : m); return s < 0 ? -d : d; }
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
    CHECK(fabsf(WMIN - 42.50f) < 0.01f && fabsf(WMAX - 47.50f) < 0.01f, "windows 42.50..47.50 deg (%.3f..%.3f)", WMIN, WMAX);
    /* rounds 65..73 (36.344 deg) and patch 4015 (36 deg): no stick position arms; 44 deg (Feralnet, #47) arms */
    int old_any = 0, s4015_any = 0;
    for (int p = 0; p <= 100; p++) {
        old_any |= in_window(hand_after(p / 100.0f, map_old));
        s4015_any |= in_window(hand_after(p / 100.0f, map_4015));
    }
    printf("36.344 deg map: hand at full stick %.2f deg, arms: %s; patch 4015: %s; 44 deg: hand %.2f deg, arms %s\n",
           hand_after(1.0f, map_old), old_any ? "yes" : "never", s4015_any ? "yes" : "never", hand_after(1.0f, map_44),
           in_window(hand_after(1.0f, map_44)) && in_window(hand_after(-1.0f, map_44)) ? "both sides" : "no");
    CHECK(!old_any && !s4015_any, "the 36.344 / 36 deg maps never reach the windows");
    CHECK(fabsf(hand_after(1.0f, map_44) - 43.0f) < 0.01f && in_window(hand_after(1.0f, map_44)) && in_window(hand_after(-1.0f, map_44)),
          "44 deg: hand 43.00 deg, inside (the #47 measurement: 0.7504 rad)");
    CHECK(fabsf(ctrl_after(1.0f, map_new) - 45.0f) < 0.01f, "controller hand at full stick 45 deg");
    /* valve: the +-35 deg hand clamp is reached from 47 % of the stick (the controller's hand; ValveRep clamps it) */
    CHECK(ctrl_after(0.47f, map_new) >= 35.0f && ctrl_after(-0.47f, map_new) <= -35.0f, "valve clamp reached at 47 %%");
    CHECK(ctrl_after(0.40f, map_new) < 35.0f, "below 47 %% the valve hand is inside its clamp");
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
