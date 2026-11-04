/* SIXAXIS stand-in for the valves and demolition charges (ENHANCEMENT). Pure: no guest memory, no
 * OS call, so tools/runtime/test_motion_mode.sh tests it on the host. The guest glue is in kz2_ppu_overrides.cpp
 * (hooks @0x000821D0, @0x001174A8, @0x00125BF0), the pad side in port/patches/6049.
 *
 * The game reads the pad's tilt in three places, all through the motion getter @0x000821D0(device, &a, &b, &c, &g)
 * (a = X, b = -Z, c = Y of the low-passed accelerometer, 0.2209 per g; the RE notes "An earlier change"):
 *   the demolition charge  ExplosiveLocationJoystickController @0x00119C90 (return address 0x00119CFC),
 *   the valve              ValveJoystickController             @0x00127210 (return address 0x00127288),
 *   the zoom aim correction                                    @0x00171698 (return address 0x00173748).
 * Both controllers take roll = atan(-a / sqrt(b^2 + c^2)) and feed -roll to a follower with a dead band of exactly
 * 1 degree (the constructors store 0.0174533 rad: charge @0x00107700 into +0x114, value @0x00107688; valve @0x00108C90
 * into +0x110, value @0x00108C30), so the hand sits 1 degree behind the tilt.
 * A charge (the arm condition read from the lifted code, after the tester measurement credited below):
 *   the ExplosiveLocationRep hand E+0x25C (radians) follows the controller's +0x100 @0x00117898 at MaxRotationSpeed
 *   (360 deg/s) x 1/15 per update and is clamped to [MinAngle, MaxAngle] = [-45, +45] deg (resource +0x178/+0x17C, x pi/180);
 *   the arm update @0x001174A8 then takes a step for each ArmRanges window not yet done that CONTAINS the hand while the
 *   grab is held (controller +0x108 >= 0.05), once the hand has stayed in it for ArmStepTime (resource +0x1FC, 0 s: the
 *   first update), each window once, in any order. A containment test, not a crossing or speed test. The windows are
 *   RADIANS compared with the radian hand: 0.741765..0.829031 rad = 42.50..47.50 deg on each side, centred on pi/4 =
 *   45 deg, which is also the MaxAngle clamp, so the reachable part is 42.50..45.00 deg. (Rounds 65..73 read them as
 *   fractions of 45 deg, 33.38..37.31 deg, and set the peak tilt to 36.344 deg: the hand rested at 35.34 deg, 7 deg short
 *   of the window, and no charge ever armed from the stick.)
 *   Measured by Feralnet on public #47 (2026-11-04): 36.344 never armed (0 arm-step lines), 44.0 armed every time with
 *   the hand at 0.7504 rad (logged as 33.77 "deg" by the old x45 log = 43.0 deg), which is what this model predicts.
 * Here the hand angle follows the stick to full tilt at KZ2_MOTION_FULL_AT of the travel and stays there;
 * KZ2_MOTION_PEAK_DEG = window centre (45 deg) + the 1 deg band, so the hand rests on the MaxAngle clamp at the window
 * centre (2.5 deg inside each edge) from 57 % of the stick to 100 %; the valve's +-35 deg hand clamp (ValveResource
 * MinHandAngle/MaxHandAngle) is reached from 47 % (the valve turns by the hand's change while held, so the larger peak
 * only reaches the same clamp sooner).
 * The tilt goes only to those two controllers (the getter is rewritten at their return addresses), so the zoom aim
 * never sees it, and no button is added: the game's own grab (GrabLeftHand/GrabRightHand, L1+R1) still decides when
 * the valve turns and when the charge arms, as on the PS3. */
#pragma once
#include <math.h>
#include <stdint.h>

enum { KZ2_MOTION_AUTO = 0, KZ2_MOTION_ON = 1, KZ2_MOTION_OFF = 2 };

#define KZ2_MOTION_PEAK_DEG 46.0f     /* pi/4 rad (the ArmRanges centre and the charge's MaxAngle) + the follower's 1 deg band */
#define KZ2_MOTION_FULL_AT  0.6f      /* fraction of the stick travel at which the peak tilt is reached */
#define KZ2_MOTION_G        0.2209f   /* one g in the getter's units (113 words / 511.5) */

#define KZ2_MOTION_LR_CHARGE 0x00119CFCu
#define KZ2_MOTION_LR_VALVE  0x00127288u

/* Stick byte (0..255, 128 centre) to [-1, 1]: the same scale as the game's own stick reads (0 -> -1, 255 -> +1). */
static inline float kz2_motion_unit(uint8_t v)
{
    float s = v >= 128 ? (float)(v - 128) / 127.0f : (float)(v - 128) / 128.0f;
    return s < -1.0f ? -1.0f : s > 1.0f ? 1.0f : s;
}

/* Tilt in degrees for a stick position s in [-1, 1]: linear to the peak at KZ2_MOTION_FULL_AT, flat beyond. */
static inline float kz2_motion_deg(float s)
{
    const float m = fabsf(s) / KZ2_MOTION_FULL_AT;
    const float d = KZ2_MOTION_PEAK_DEG * (m > 1.0f ? 1.0f : m);
    return s < 0.0f ? -d : d;
}

/* Does the stick drive the valves and charges? off: always; on: never (the pad's own sensors or a still pad);
 * auto: when the pad has no working accelerometer (no sensor, a gyro only, or one that reads no gravity). */
static inline int kz2_motion_feed(int mode, int pad_accel_live)
{
    return mode == KZ2_MOTION_OFF || (mode == KZ2_MOTION_AUTO && !pad_accel_live);
}

/* The getter's (a, b, c) for a tilt of deg degrees (the pad rolled right for deg > 0): a still pad's 1 g on c, so the
 * controllers' roll = atan(-a / |c|) = -deg and their follower input -roll = deg (stick right = hand right, the sign
 * patch 4015 used). */
static inline void kz2_motion_vec(float deg, float out[3])
{
    out[0] = KZ2_MOTION_G * tanf(deg * 0.017453293f);
    out[1] = 0.0f;
    out[2] = -KZ2_MOTION_G;
}

/* The controllers' roll for (a, b, c), as @0x00127210 computes it (atanf @0x007CF460; +-90 deg when b = c = 0). */
static inline float kz2_motion_roll_deg(const float v[3])
{
    const float r = sqrtf(v[1] * v[1] + v[2] * v[2]);
    if (r == 0.0f) return v[0] > 0.0f ? -90.0f : 90.0f;
    return atanf(-v[0] / r) * 57.29578f;
}

/* One follower step (the controllers' dead band): the hand moves only when the input leaves [cur - band, cur + band]
 * and then sits band away from it. */
static inline float kz2_motion_follow(float cur, float in, float band)
{
    if (in <= cur - band) return in + band;
    if (in >= cur + band) return in - band;
    return cur;
}
