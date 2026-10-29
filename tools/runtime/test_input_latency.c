/* Host test for include/ps3emu/input_latency.h (KZ2 patch 6037): the knob parser, the quantile,
 * and one press followed through read -> flip request -> FIFO flip -> present -> Present return, with the hooks
 * called the way cellPad.c, cellGcmSys.c and rsx_live_draw.c call them. POSIX build: no injector thread, so the
 * test opens the press itself as the thread does. */
#include "ps3emu/input_latency.h"
#include <assert.h>

static int fails;
#define CHECK(c, msg) do { if (!(c)) { printf("[FAIL] %s\n", msg); fails++; } else printf("PASS: %s\n", msg); } while (0)

static uint32_t open_press(void)
{
    ps3_lat_state* s = &g_ps3_lat;
    const uint32_t i = s->n_probe++;
    memset(&s->probe[i], 0, sizeof s->probe[i]);
    s->probe[i].t[PS3_LAT_IN] = ps3_lat_now();
    s->probe[i].stage = PS3_LAT_READ;
    s->open[s->n_open++] = i;
    s->inj_wait_read = 1; s->inj_mask = s->mask;
    return i;
}

int main(void)
{
    double a = 50, b = 700, c = 120, d = 0; uint32_t m = 2;
    CHECK(ps3_lat_parse("30:500:80:0x4000", &a, &b, &c, &m, &d) == 4 && a == 30 && b == 500 && c == 80 && m == 0x4000
          && d == 0, "parse: four fields, no stop");
    a = 50; b = 700; c = 120; m = 2;
    ps3_lat_parse("10", &a, &b, &c, &m, &d);
    CHECK(a == 10 && b == 700 && c == 120 && m == 2 && d == 0, "parse: missing fields keep their defaults");
    ps3_lat_parse("10:20:900:0", &a, &b, &c, &m, &d);
    CHECK(b == 700 && c == 120 && m == 2, "parse: period under 50 ms, hold over the period, mask 0 refused");
    a = 50; b = 700; c = 120; m = 2;
    CHECK(ps3_lat_parse("75:300:80:0x0010:105", &a, &b, &c, &m, &d) == 5 && a == 75 && m == 0x0010 && d == 105,
          "parse: fifth field is the window's stop");
    d = 0; ps3_lat_parse("75:300:80:0x0010:60", &a, &b, &c, &m, &d);
    CHECK(d == 0, "parse: a stop before the start is refused");
    double v[] = { 5, 1, 4, 2, 3, 10, 9, 8, 7, 6 };
    CHECK(ps3_lat_q(v, 10, 0.5) == 5 && ps3_lat_q(v, 10, 0.95) == 10 && ps3_lat_q(v, 10, 0.01) == 1,
          "quantile: nearest rank");

    /* off by default (no KZ2_LATENCY, and POSIX never turns it on): hooks are inert */
    CHECK(ps3_lat_pad_mask() == 0 && !ps3_lat_on(), "off: no injected bits, hooks inert");
    ps3_lat_flip_req(0);
    CHECK(g_ps3_lat.n_req == 0, "off: flip requests not counted");

    /* force on as the Windows init would */
    ps3_lat_state* s = &g_ps3_lat;
    s->on = 2; s->mask = 0x0002;
    s->probe = (ps3_lat_probe*)calloc(PS3_LAT_MAX, sizeof(ps3_lat_probe));
    s->ft = (double*)calloc(PS3_LAT_FT, sizeof(double));
    if (!s->probe || !s->ft) return 2;
    ps3_lat_flip_req(0); ps3_lat_flip_fifo();          /* frame 1 requested and drained before the press */
    const uint32_t p = open_press();
    CHECK(ps3_lat_pad_mask() == 0x0002, "on: the press is ORed into port 0");
    ps3_lat_pad_read(0, 0x0002);                         /* a stale read (len 0) does not hand it out */
    CHECK(s->probe[p].stage == PS3_LAT_READ, "read: len 0 is not the read");
    ps3_lat_pad_read(8, 0x0040);                         /* a fresh read without the bit */
    CHECK(s->probe[p].stage == PS3_LAT_READ, "read: a read without the bit is not the read");
    ps3_lat_pad_read(8, 0x0042);
    CHECK(s->probe[p].stage == PS3_LAT_REQ && s->probe[p].flip == 2 && s->probe[p].t[PS3_LAT_READ],
          "read: stamped, waits for flip request 2");
    ps3_lat_present(PS3_LAT_PRES);                       /* a present of the old frame does not count */
    CHECK(s->probe[p].stage == PS3_LAT_REQ, "present of an earlier frame ignored");
    ps3_lat_flip_req(0);
    CHECK(s->probe[p].stage == PS3_LAT_FIFO && s->probe[p].t[PS3_LAT_REQ], "req: the next flip request");
    ps3_lat_present(PS3_LAT_PRES);                       /* frame 2 not drained yet */
    CHECK(s->probe[p].stage == PS3_LAT_FIFO, "present before the drain reached the flip ignored");
    ps3_lat_walker(PS3_LAT_WALK_DRAIN, 5000); ps3_lat_walker(ps3_lat_walk_kind("park-wait"), 3000);
    ps3_lat_walker(PS3_LAT_WALK_DRAIN, 1500); ps3_lat_walker(ps3_lat_walk_kind("flip"), 4000);
    ps3_lat_walker(ps3_lat_walk_kind("caught-up"), 1000); ps3_lat_walker(ps3_lat_walk_kind("acquire"), 500);
    ps3_lat_flip_fifo();
    CHECK(s->probe[p].stage == PS3_LAT_PRES, "fifo: the drain reached flip 2");
    CHECK(s->probe[p].walk_ms[PS3_LAT_WALK_DRAIN] == 6.5 && s->probe[p].walk_ms[PS3_LAT_WALK_PARK] == 3.5 &&
          s->probe[p].walk_ms[PS3_LAT_WALK_FLIP] == 4.0 && s->probe[p].walk_ms[PS3_LAT_WALK_IDLE] == 1.0,
          "fifo: the frame thread's drain and sleeps (by stop reason) inside req->fifo");
    ps3_lat_present(PS3_LAT_PRES); ps3_lat_present(PS3_LAT_CALL); ps3_lat_present(PS3_LAT_RET);
    CHECK(s->probe[p].stage == PS3_LAT_GPU && s->probe[p].t[PS3_LAT_RET] >= s->probe[p].t[PS3_LAT_CALL],
          "present: pres, call, ret in order");
    /* direct (non-FIFO) flips count as request and drain at once */
    const uint32_t q = open_press();
    ps3_lat_pad_read(8, 0x0002);
    ps3_lat_flip_req(1);
    CHECK(s->probe[q].stage == PS3_LAT_PRES && s->probe[q].flip == 3, "direct flip: req and fifo together");
    /* finish the first press as the injector thread does after the fence; the summary covers it */
    s->probe[p].t[PS3_LAT_GPU] = ps3_lat_now(); s->probe[p].stage = PS3_LAT_NSTAMP;
    ps3_lat_finish(p);
    CHECK(s->n_done == 1 && s->n_open == 1 && s->open[0] == q, "finish: closed and removed from the open list");
    ps3_lat_summary("summary");
    /* frame times are kept from the first press until the stop, not after */
    s->ft_prev = 1;
    ps3_lat_present(PS3_LAT_RET); ps3_lat_present(PS3_LAT_RET); ps3_lat_present(PS3_LAT_RET);
    const uint32_t nft = s->n_ft;
    CHECK(nft == 2, "frame times: two intervals from three Present returns");
    s->ft_stop = 1;
    ps3_lat_present(PS3_LAT_RET);
    CHECK(s->n_ft == nft, "frame times: none kept past the window's stop");
    ps3_lat_summary("window summary");
    CHECK(g_ps3_lat.magic == PS3_LAT_MAGIC, "state: one initialised object (selectany on Windows)");
    free(s->probe); free(s->ft);
    printf(fails ? "FAILED %d\n" : "ALL PASS\n", fails);
    return fails ? 1 : 0;
}
