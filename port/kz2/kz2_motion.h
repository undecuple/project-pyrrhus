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
 * A charge arms when the hand enters each ArmRanges window, 0.741765..0.829031 of 45 deg = 33.38..37.31 deg on each
 * side (0x001174A8). The stand-in that shipped before (patch 4015, L1+R1 + right stick) gave 36 deg at full stick, so
 * the hand reached 35 deg only with the stick at 95.6..100 % (36 s - 1 >= 33.38): a stick, pad mapper or driver
 * that stops short of the last 4.4 % (an outer dead zone, a round gate read on one axis, an XInput wrapper's scaling)
 * never arms the charge, the soft-lock players reported. Here the hand angle follows the stick to full tilt at
 * KZ2_MOTION_FULL_AT of the travel and stays there, KZ2_MOTION_PEAK_DEG = window centre + the dead band, so the hand
 * rests in the middle of both windows (1.95 deg margin each way) from 57 % of the stick to 100 %, and the valve's
 * +-35 deg hand clamp (ValveResource MinHandAngle/MaxHandAngle) is reached from 59 %.
 * The tilt goes only to those two controllers (the getter is rewritten at their return addresses), so the zoom aim
 * never sees it, and no button is added: the game's own grab (GrabLeftHand/GrabRightHand, L1+R1) still decides when
 * the valve turns and when the charge arms, as on the PS3. */
#pragma once
#include <math.h>
#include <stdint.h>

enum { KZ2_MOTION_AUTO = 0, KZ2_MOTION_ON = 1, KZ2_MOTION_OFF = 2 };

#define KZ2_MOTION_PEAK_DEG 36.344f   /* (33.379 + 37.309) / 2 + 1: window centre plus the follower's 1 deg band */
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
