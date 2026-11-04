/* Host test for KZ2 patch 6062 (the DSU motion client) and its path into patch 6049's motion words and the title port's
 * stick feed (kz2_motion.h). A fake DSU server on 127.0.0.1 in the same process: the client registers, the server checks
 * the request and answers with bad packets (each must be rejected) and good ones (each must come out as the expected
 * SIXAXIS words); the words then go through pad_motion_live_note / pad_motion_words by mode and kz2_motion_feed.
 * No game data; loopback only. Build and run: tools/runtime/test_dsu.sh. */
#include "pad_dsu_io.h"
#include "pad_motion_stick.h"
#include "kz2_motion.h"
#include <math.h>
#include <poll.h>
#include <stdio.h>

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

static void putf(uint8_t* p, float f) { uint32_t u; memcpy(&u, &f, 4); pdsu_put32(p, u); }

/* a server pad-data packet; flaw: 0 good, 1 bad CRC, 2 magic, 3 version, 4 slot not connected, 5 NaN, 6 out of range,
 * 7 event type, 8 short */
static int mkpkt(uint8_t* p, const float acc[3], const float gyr[3], uint32_t num, int flaw)
{
    memset(p, 0, PDSU_DATA_LEN);
    memcpy(p, flaw == 2 ? "DSUC" : "DSUS", 4);
    pdsu_put16(p + 4, flaw == 3 ? 1000 : PDSU_VERSION);
    pdsu_put16(p + 6, PDSU_DATA_LEN - 16);
    pdsu_put32(p + 12, 0x12345678u);
    pdsu_put32(p + 16, flaw == 7 ? 0x100001u : PDSU_EV_DATA);
    p[20] = 0; p[21] = flaw == 4 ? 0 : 2; p[22] = 2; p[23] = 2; p[30] = 5; p[31] = flaw == 4 ? 0 : 1;
    pdsu_put32(p + 32, num);
    pdsu_put32(p + 68, num * 4000u);
    for (int i = 0; i < 3; i++) { putf(p + 76 + 4 * i, acc[i]); putf(p + 88 + 4 * i, gyr[i]); }
    if (flaw == 5) putf(p + 80, NAN);
    if (flaw == 6) putf(p + 92, 5000.0f);
    pdsu_put32(p + 8, pdsu_crc32(p, PDSU_DATA_LEN));
    if (flaw == 1) p[8] ^= 1;
    return flaw == 8 ? 60 : PDSU_DATA_LEN;
}

/* roll the valve and charge controllers compute, from the words (centred, X against the Y/Z magnitude) */
static float roll_words(const u16 w[4])
{
    const float x = (float)w[0] - 512.0f, y = (float)w[1] - 512.0f, z = (float)w[2] - 512.0f;
    return atanf(-x / sqrtf(y * y + z * z)) * 57.29578f;
}

int main(void)
{
    /* the request packet: CRC over the packet with the field zero */
    uint8_t rq[PDSU_REQ_LEN];
    CHECK(pdsu_request(rq, 0xABCD) == PDSU_REQ_LEN);
    { uint8_t t[PDSU_REQ_LEN]; memcpy(t, rq, sizeof t); memset(t + 8, 0, 4);
      CHECK(pdsu_get32(rq + 8) == pdsu_crc32(t, sizeof t)); }
    CHECK(pdsu_crc32((const uint8_t*)"123456789", 9) == 0xCBF43926u);   /* the CRC-32 check value */

    /* the fake server: bound to 127.0.0.1, port chosen by the system */
    int srv = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in sa; socklen_t sl = sizeof sa;
    memset(&sa, 0, sizeof sa); sa.sin_family = AF_INET; sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (srv < 0 || bind(srv, (struct sockaddr*)&sa, sizeof sa) || getsockname(srv, (struct sockaddr*)&sa, &sl)) {
        printf("FAIL: no loopback socket\n"); return 1;
    }
    const unsigned port = ntohs(sa.sin_port);

    PadDsu d; memset(&d, 0, sizeof d); d.sock = PDSU_BAD;
    CHECK(!pdsu_open(&d, 0));
    CHECK(pdsu_open(&d, port) && d.port == port);
    unsigned long long t = 10000;
    CHECK(pdsu_poll(&d, t) == 0);   /* registers; nothing yet */

    /* the server takes the registration and knows the client's address from it */
    struct pollfd pf = { srv, POLLIN, 0 };
    CHECK(poll(&pf, 1, 2000) == 1);
    uint8_t buf[512]; struct sockaddr_in ca; socklen_t cl = sizeof ca;
    int n = (int)recvfrom(srv, buf, sizeof buf, 0, (struct sockaddr*)&ca, &cl);
    CHECK(n == PDSU_REQ_LEN && !memcmp(buf, "DSUC", 4) && pdsu_get16(buf + 4) == PDSU_VERSION && pdsu_get16(buf + 6) == 12
          && pdsu_get32(buf + 16) == PDSU_EV_DATA && ca.sin_addr.s_addr == htonl(INADDR_LOOPBACK));
    { uint32_t c = pdsu_get32(buf + 8); memset(buf + 8, 0, 4); CHECK(c == pdsu_crc32(buf, PDSU_REQ_LEN)); }

    /* 8 bad packets: all rejected, nothing accepted */
    const float flat[3] = { 0.0f, 1.0f, 0.0f }, still[3] = { 0, 0, 0 };
    for (int f = 1; f <= 8; f++) { n = mkpkt(buf, flat, still, (uint32_t)f, f); sendto(srv, buf, (size_t)n, 0, (struct sockaddr*)&ca, cl); }
    usleep(20000);
    t += 4;
    CHECK(pdsu_poll(&d, t) == 0 && d.accepted == 0 && d.rejected == 8);

    /* good packets: flat, then rolled 30 deg (x = sin 30, y = cos 30), with a yaw rate */
    struct { float acc[3], gyr[3]; unsigned w[4]; } cs[] = {
        { { 0.0f, 1.0f, 0.0f }, { 0, 0, 0 }, { 512, 399, 512, 512 } },
        { { 0.5f, 0.8660254f, 0.0f }, { 0, 45.0f, 0 }, { 456, 414, 512, 451 } },     /* 512-56.5, 512-97.86, 512-61.5 */
        { { -0.5f, 0.8660254f, 0.0f }, { 0, -90.0f, 0 }, { 569, 414, 512, 635 } },
    };
    for (unsigned k = 0; k < sizeof cs / sizeof cs[0]; k++) {
        n = mkpkt(buf, cs[k].acc, cs[k].gyr, 100 + k, 0);
        CHECK(sendto(srv, buf, (size_t)n, 0, (struct sockaddr*)&ca, cl) == n);
        usleep(20000);
        t += 4;
        CHECK(pdsu_poll(&d, t) == 1 && d.accepted == k + 1 && d.rejected == 8);
        PadDsuMap m; pdsu_map_default(&m);
        unsigned w[4]; pdsu_words(&d.last, &m, w);
        for (int i = 0; i < 4; i++) if (w[i] != cs[k].w[i]) { printf("case %u word %d: %u, want %u\n", k, i, w[i], cs[k].w[i]); fails++; }
        /* into 6049: has_sensor + has_accel, the latch reads gravity, auto/on pass the words, off a still pad */
        const u16 real[4] = { (u16)w[0], (u16)w[1], (u16)w[2], (u16)w[3] };
        int latch = 0;
        const int live = pad_motion_live_note(&latch, 1, real[0], real[1], real[2]);
        CHECK(live == 1);
        u16 o[4];
        pad_motion_words(PAD_MOTION_AUTO, 1, live, real, o); CHECK(!memcmp(o, real, sizeof o));
        pad_motion_words(PAD_MOTION_ON, 1, live, real, o);   CHECK(!memcmp(o, real, sizeof o));
        pad_motion_words(PAD_MOTION_OFF, 1, live, real, o);
        CHECK(o[0] == 512 && o[1] == 399 && o[2] == 512 && o[3] == 512);
        /* the title port's stick feed: never with DSU under auto/on, always under off */
        CHECK(!kz2_motion_feed(KZ2_MOTION_AUTO, live) && !kz2_motion_feed(KZ2_MOTION_ON, live) && kz2_motion_feed(KZ2_MOTION_OFF, live));
        /* the tilt the valve/charge controllers see from these words */
        const float r = roll_words(real), want = k == 0 ? 0.0f : k == 1 ? 30.0f : -30.0f;
        if (fabsf(r - want) > 1.0f) { printf("case %u roll %.2f, want %.0f\n", k, r, want); fails++; }
    }
    /* the newest of several waiting datagrams wins */
    for (unsigned k = 0; k < 3; k++) { n = mkpkt(buf, cs[k].acc, cs[k].gyr, 200 + k, 0); sendto(srv, buf, (size_t)n, 0, (struct sockaddr*)&ca, cl); }
    usleep(20000); t += 4;
    CHECK(pdsu_poll(&d, t) == 1 && d.accepted == 6 && d.last.accel[0] == -0.5f);
    /* a longer datagram (the first 100 bytes count) is accepted */
    n = mkpkt(buf, cs[1].acc, cs[1].gyr, 300, 0); memset(buf + 100, 0xEE, 40);
    sendto(srv, buf, 140, 0, (struct sockaddr*)&ca, cl); usleep(20000); t += 4;
    CHECK(pdsu_poll(&d, t) == 1 && d.accepted == 7 && d.last.accel[0] == 0.5f);
    /* the registration is renewed each second */
    t += 1000;
    pdsu_poll(&d, t);
    CHECK(poll(&pf, 1, 2000) == 1 && recv(srv, buf, sizeof buf, 0) == PDSU_REQ_LEN);
    /* silence: the last sample is older than 1 s -> no samples */
    t += 10;
    CHECK(pdsu_poll(&d, t) == 0);
    /* without a working accelerometer (DSU gone, pad without sensors) the latch drops and the stick feeds again */
    { int latch = 1; CHECK(pad_motion_live_note(&latch, 0, 512, 399, 512) == 0 && kz2_motion_feed(KZ2_MOTION_AUTO, 0)); }
    /* a server that answers from another address is not heard: the client is connect()ed to 127.0.0.1:port */
    {
        int other = socket(AF_INET, SOCK_DGRAM, 0);
        struct sockaddr_in oa; memset(&oa, 0, sizeof oa); oa.sin_family = AF_INET; oa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        bind(other, (struct sockaddr*)&oa, sizeof oa);
        n = mkpkt(buf, cs[1].acc, cs[1].gyr, 400, 0);
        sendto(other, buf, (size_t)n, 0, (struct sockaddr*)&ca, cl); usleep(20000); t += 4;
        const unsigned acc0 = d.accepted, rej0 = d.rejected;
        CHECK(pdsu_poll(&d, t) == 0 && d.accepted == acc0 && d.rejected == rej0);
        close(other);
    }
    pdsu_close(&d);
    CHECK(d.port == 0 && pdsu_poll(&d, t) == 0);
    close(srv);
    if (fails) { printf("test_dsu: %d FAILED\n", fails); return 1; }
    printf("test_dsu: ok (8 bad packets rejected, 3 tilt cases, newest-wins, long datagram, renewal, timeout, foreign sender)\n");
    return 0;
}
