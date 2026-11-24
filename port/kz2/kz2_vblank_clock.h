/* KZ2 vblank clock: when the frame thread's synthetic vblank ticks are due.
 *
 * The PS3 (NTSC, 480i/720p/1080i at 59.94 Hz) raises vblank every 1001/60000 s. The frame thread (port/kz2/main.cpp
 * frame_clock) used to step `next_tick += 16` on GetTickCount64: an integer 16 ms period, so the long-run rate was
 * 1000/16 = 62.5 Hz (an earlier change measured ~62.6 ticks a second), 4.3 % fast, and every vblank-driven pace in the guest
 * (Killzone 2's 30 Hz frame gate counts two handler calls, 1.29 0x48F40) ran 4.3 % fast with it.
 *
 * Here tick n is due at t0 + n * num / den seconds, computed exactly from the tick index in the caller's counter units
 * (QueryPerformanceCounter): no period is rounded and no error accumulates, whatever the counter frequency or the
 * wake-up jitter of the thread that polls it. A pass that wakes late fires the ticks it missed (bounded by the caller)
 * and the next tick stays on the original grid. kz2_vbclock_rebase starts a new grid at `now` (after a long stall,
 * where the caller gives up catching up).
 *
 * Pure C, no Windows calls: the host test (tools/runtime/test_vblank_clock.sh) drives it with a simulated counter.
 * KZ2_VBLANK_16MS=1 (main.cpp) selects the old 16 ms period (num/den = 16/1000) for an A/B only. */
#ifndef KZ2_VBLANK_CLOCK_H
#define KZ2_VBLANK_CLOCK_H

#include <stdint.h>

#define KZ2_VBLANK_NUM_NTSC 1001u    /* period = 1001 / 60000 s = 16.6833.. ms (59.94 Hz) */
#define KZ2_VBLANK_DEN_NTSC 60000u

typedef struct kz2_vbclock {
    uint64_t t0;     /* counter value of tick 0 of the current grid */
    uint64_t freq;   /* counter units per second */
    uint64_t next;   /* index of the next tick to fire */
    uint32_t num, den;
} kz2_vbclock;

/* counter units from t0 to tick n: n * num * freq / den, exact (split so nothing overflows: (n % den) * num * freq
 * stays below den * num * freq, about 6e14 for a 10 MHz counter at 59.94 Hz) */
static inline uint64_t kz2_vbclock_offset(const kz2_vbclock* c, uint64_t n)
{
    const uint64_t whole = n / c->den, part = n % c->den;
    return whole * (uint64_t)c->num * c->freq + (part * (uint64_t)c->num * c->freq) / c->den;
}

static inline void kz2_vbclock_init(kz2_vbclock* c, uint64_t now, uint64_t freq, uint32_t num, uint32_t den)
{
    c->t0 = now; c->freq = freq ? freq : 1; c->num = num ? num : 1; c->den = den ? den : 1;
    c->next = 1;   /* tick 0 is the start; the first tick fires one period later, as `next_tick` did */
}

/* the counter value at which the next tick is due */
static inline uint64_t kz2_vbclock_due(const kz2_vbclock* c)
{
    return c->t0 + kz2_vbclock_offset(c, c->next);
}

/* is the next tick due at `now`? (counter wrap is not a concern: a 64-bit QPC) */
static inline int kz2_vbclock_ready(const kz2_vbclock* c, uint64_t now)
{
    return now >= kz2_vbclock_due(c);
}

/* the next tick has fired */
static inline void kz2_vbclock_advance(kz2_vbclock* c)
{
    c->next++;
}

/* start a new grid at `now` (the caller fell too far behind and drops the backlog) */
static inline void kz2_vbclock_rebase(kz2_vbclock* c, uint64_t now)
{
    c->t0 = now; c->next = 1;
}

#endif /* KZ2_VBLANK_CLOCK_H */
