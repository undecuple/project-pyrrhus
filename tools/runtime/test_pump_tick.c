/* Host test (port/kz2/main.cpp frame_clock: the message pump on every vblank tick, KZ2_PUMP_TICK).
 * From Project Helghast (the Killzone 3 PC port) v0.1.4, tools/smoke/test_pump_tick.c (MIT), adapted: KZ2 has
 * no Raw Input mouse look accumulator (KZ3's pad_mouse.h), so the model measures what every window message sees, the
 * delay from its arrival to the next pump, instead of look counts per slot.
 * A model of frame_clock's two loops on a simulated millisecond clock: messages arrive every 1 ms and are handled when
 * the loop pumps. While a FIFO drain costs more than the 16 ms tick (a heavy level, 50 ms here):
 *   old loop (pump only in the outer loop): the catch-up pass grows to up to 240 ticks, messages wait seconds (4.9 s
 *     here, close to the 5 s after which Windows marks a window as not responding);
 *   new loop (pump after every tick): the longest pump gap is one drain + one tick.
 * The model is a copy of the loop's shape, not the loop itself: it checks the reasoning, the Proton runs ([pump] lines)
 * check the exe. tools/runtime/test_pump_tick.sh also checks that main.cpp pumps inside the catch-up loop.
 *   nix develop --command tools/sandbox.sh -- tools/runtime/test_pump_tick.sh */
#include <stdio.h>
#include <stdlib.h>

#define SIM_MS     20000.0
#define TICK_MS    16.0

static double cost(double t) { return (t >= 5000.0 && t < 15000.0) ? 50.0 : 2.0; }   /* one tick's FIFO drain */

static double s_pumps[200000];
static int s_np;

/* frame_clock's shape (Sleep, the catch-up loop with its 240 cap and resync, the outer drain + pump). */
static void run_loop(int pump_each_tick)
{
    double t = 0.0, next_tick = 0.0;
    s_np = 0;
    while (t < SIM_MS) {
        t += 4.0;                                   /* Sleep(4) */
        const double now = t;
        int fired = 0;
        while (now - next_tick >= 0.0 && fired < 240) {
            t += cost(t);                           /* TickVBlank/TickFlip, present, cellGcm_rsx_process_fifo */
            if (pump_each_tick) s_pumps[s_np++] = t;
            next_tick += TICK_MS;
            fired++;
        }
        if (fired >= 240) next_tick = now;
        t += 1.0;                                   /* outer drain (the catch-up pass left little queued) */
        s_pumps[s_np++] = t;                        /* kz2_rsx_pump */
    }
}

typedef struct { double max_gap, max_wait, mean_wait; int gaps_over_250; } Res;

/* Pump gaps and message waits in the heavy phase (5.5 s .. 15 s). */
static Res measure(void)
{
    Res r = {0, 0, 0, 0};
    double sum = 0.0; long n = 0;
    int p = 0;
    for (double m = 5500.0; m < 15000.0; m += 1.0) {        /* a message every 1 ms */
        while (p < s_np && s_pumps[p] < m) p++;
        if (p >= s_np) break;
        const double w = s_pumps[p] - m;
        if (w > r.max_wait) r.max_wait = w;
        sum += w; n++;
    }
    r.mean_wait = n ? sum / (double)n : 0.0;
    for (int k = 1; k < s_np; k++) {
        if (s_pumps[k] <= 5500.0 || s_pumps[k] >= 15000.0) continue;
        const double gap = s_pumps[k] - s_pumps[k - 1];
        if (gap > r.max_gap) r.max_gap = gap;
        if (gap > 250.0) r.gaps_over_250++;
    }
    return r;
}

int main(void)
{
    int fail = 0;
    run_loop(0);
    const Res o = measure();
    run_loop(1);
    const Res n = measure();
    printf("[test_pump_tick] heavy phase (drain 50 ms > 16 ms tick), a window message every 1 ms:\n");
    printf("  old loop: longest pump gap %.0f ms, %d gap(s) over 250 ms, message wait max %.0f ms mean %.1f ms\n",
           o.max_gap, o.gaps_over_250, o.max_wait, o.mean_wait);
    printf("  new loop: longest pump gap %.0f ms, %d gap(s) over 250 ms, message wait max %.0f ms mean %.1f ms\n",
           n.max_gap, n.gaps_over_250, n.max_wait, n.mean_wait);
    /* the model must show the hold-back on the old loop, or it is not testing the cause */
    if (!(o.max_gap > 1000.0 && o.max_wait > 1000.0)) {
        printf("FAIL: the old loop does not hold the messages back in the model\n"); fail = 1;
    }
    if (!(n.max_gap <= 50.0 + TICK_MS + 1.0)) { printf("FAIL: new loop pump gap %.0f ms\n", n.max_gap); fail = 1; }
    if (!(n.max_wait <= 50.0 + TICK_MS + 1.0)) { printf("FAIL: new loop message wait %.0f ms\n", n.max_wait); fail = 1; }
    if (n.gaps_over_250) { printf("FAIL: new loop has %d gap(s) over 250 ms\n", n.gaps_over_250); fail = 1; }
    printf("[test_pump_tick] %s\n", fail ? "FAIL" : "PASS");
    return fail;
}
