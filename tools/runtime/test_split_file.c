/* Host test for ps3emu/split_file.h (KZ2 patch 6034): a file a FAT32 copy keeps as <name>.66600, .66601, ... read
 * as one file. No game data: small fake parts of uneven size, plus one sparse 4 GiB part for 64-bit offsets.
 * Adapted from the Killzone 3 PC port's port/vfs/test_splitfile.c (Project Helghast v0.1.3, same author, MIT).
 * Build and run: tools/runtime/test_split_file.sh */
#include "split_file.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fails;
#define CHECK(c, ...) do { if (c) printf("[ok]   " __VA_ARGS__); else { fails++; printf("[FAIL] " __VA_ARGS__); } printf("\n"); } while (0)

static void put(const char* path, const unsigned char* d, size_t n)
{
    FILE* f = fopen(path, "wb"); if (!f) { perror(path); exit(2); }
    if (n && fwrite(d, 1, n, f) != n) { perror(path); exit(2); }
    fclose(f);
}
static void part(char* out, size_t cap, const char* base, int i) { snprintf(out, cap, "%s.%d", base, 66600 + i); }

enum { N = 5000 };
static unsigned char all[N];

struct thr { ps3_sf* s; int seed, bad; };
static void* reader(void* a)
{
    struct thr* t = (struct thr*)a;
    unsigned char got[300];
    for (int i = 0; i < 2000; i++) {
        size_t o = (size_t)(((unsigned)(i + t->seed) * 7919u) % (N - 300)), len = 1 + ((unsigned)(i * 131 + t->seed)) % 299;
        if (ps3_sf_pread(t->s, o, got, len) != len || memcmp(got, all + o, len)) t->bad++;
    }
    return NULL;
}

int main(int argc, char** argv)
{
    if (argc < 2) return 2;
    static unsigned char got[N];
    for (int i = 0; i < N; i++) all[i] = (unsigned char)((i * 31u + (i >> 8) * 7u) ^ 0x5a);
    char base[1200], p[1300], why[1400];
    snprintf(base, sizeof base, "%s/data_ps3.psarc", argv[1]);

    /* 1. A single file: one part, the same bytes. */
    put(base, all, N);
    ps3_sf* s = ps3_sf_open(base, why, sizeof why);
    CHECK(s && s->nparts == 1 && ps3_sf_size(s) == N, "a single file opens as one part of %d bytes", N);
    if (!s) return 1;
    CHECK(ps3_sf_read(s, got, N) == N && !memcmp(got, all, N), "a single file reads back whole");
    ps3_sf_close(s);
    remove(base);

    /* 2. Parts of different sizes (1000, 1500, 64, 2436): sizes come from the files, not from a part size. */
    const size_t sz[] = { 1000, 1500, 64, 2436 };
    size_t off = 0;
    for (int i = 0; i < 4; i++) { part(p, sizeof p, base, i); put(p, all + off, sz[i]); off += sz[i]; }
    CHECK(ps3_sf_has_parts(base) == 1, "the existence probe sees the part set");
    int np = 0; uint64_t total = 0;
    CHECK(ps3_sf_scan(base, &np, &total, NULL, why, sizeof why) == 1 && np == 4 && total == N, "scan: 4 parts, %d bytes", N);
    s = ps3_sf_open(base, why, sizeof why);
    CHECK(s && s->nparts == 4 && ps3_sf_size(s) == N && s->new_part == -1 && !s->seen[0], "four parts open as one file of %d bytes", N);
    if (!s) return 1;
    CHECK(ps3_sf_read(s, got, N) == N && !memcmp(got, all, N), "the whole set read in one call equals the joined bytes");
    CHECK(s->edge_reads == 1 && s->seen[0] && s->seen[3] && s->new_part == 3, "that read is counted as one read across part edges, reaching all 4 parts");
    CHECK(ps3_sf_read(s, got, 10) == 0, "a read at the end returns 0");
    int bad = 0;
    const size_t bounds[] = { 1000, 2500, 2564 };
    for (int b = 0; b < 3; b++)
        for (int back = 1; back <= 40; back += 13)
            for (int len = 2; len <= 3000; len += 997) {
                size_t o = bounds[b] - back;
                if (o + len > N) continue;
                uint64_t at = 0;
                ps3_sf_seek(s, (int64_t)o, SEEK_SET, &at);
                memset(got, 0, sizeof got);
                if (at != o || ps3_sf_read(s, got, len) != (size_t)len || memcmp(got, all + o, len) || s->pos != o + len) bad++;
            }
    CHECK(!bad, "reads across each part edge (one spans the whole 64-byte part) match the joined bytes");
    memset(got, 0, 20);
    CHECK(ps3_sf_pread(s, 2490, got, 20) == 20 && !memcmp(got, all + 2490, 20) && s->pos != 2490,
          "a positional read across an edge matches and leaves the handle position");
    uint64_t at = 0;
    CHECK(ps3_sf_seek(s, -10, SEEK_END, &at) == 0 && at == N - 10, "SEEK_END -10 lands at %d", N - 10);
    memset(got, 0, 20);
    CHECK(ps3_sf_read(s, got, 20) == 10 && !memcmp(got, all + N - 10, 10), "a read past the end is short");
    CHECK(ps3_sf_seek(s, -20, SEEK_CUR, &at) == 0 && at == N - 20, "SEEK_CUR -20 lands at %d", N - 20);
    CHECK(ps3_sf_seek(s, -(int64_t)N - 1, SEEK_END, &at) == -1 && at == N - 20, "a negative position is refused and the position kept");
    CHECK(ps3_sf_seek(s, N + 100, SEEK_SET, &at) == 0 && ps3_sf_read(s, got, 4) == 0, "a seek past the end is allowed and reads 0");
    bad = 0;
    for (int i = 0; i < 200; i++) {                        /* random access, like an archive reader */
        size_t o = (size_t)((i * 7919u) % (N - 100)), len = 1 + (i * 131u) % 100;
        ps3_sf_seek(s, (int64_t)o, SEEK_SET, NULL);
        if (ps3_sf_read(s, got, len) != len || memcmp(got, all + o, len)) bad++;
    }
    CHECK(!bad, "200 random small reads match");
    struct thr t[4];
    pthread_t th[4];
    for (int i = 0; i < 4; i++) { t[i].s = s; t[i].seed = i * 1000 + 7; t[i].bad = 0; pthread_create(&th[i], NULL, reader, &t[i]); }
    bad = 0;
    for (int i = 0; i < 4; i++) { pthread_join(th[i], NULL); bad += t[i].bad; }
    CHECK(!bad, "4 threads x 2000 positional reads on one handle match");
    ps3_sf_close(s);

    /* 3. The single file wins over parts beside it. */
    put(base, all, 123);
    s = ps3_sf_open(base, why, sizeof why);
    CHECK(s && s->nparts == 1 && ps3_sf_size(s) == 123, "the single file is used when it exists");
    ps3_sf_close(s);
    remove(base);

    /* 4. A gap: .66602 missing while .66603 is there. Refused, and the missing part named. */
    part(p, sizeof p, base, 2); remove(p);
    s = ps3_sf_open(base, why, sizeof why);
    CHECK(s == NULL && strstr(why, "data_ps3.psarc.66602 is missing") && strstr(why, ".66603"), "a gap is refused and named: %s", why);
    CHECK(ps3_sf_scan(base, NULL, NULL, NULL, NULL, 0) == -1, "scan reports the broken set");
    part(p, sizeof p, base, 3); remove(p);
    part(p, sizeof p, base, 10); put(p, all, 10);
    s = ps3_sf_open(base, why, sizeof why);
    CHECK(s == NULL && strstr(why, "data_ps3.psarc.66602 is missing") && strstr(why, ".66610"), "a stray later part (.66610) is a gap too: %s", why);
    remove(p);

    /* 5. The first part missing (.66600 gone, .66601 and .66603 there). */
    part(p, sizeof p, base, 0); remove(p);
    s = ps3_sf_open(base, why, sizeof why);
    CHECK(s == NULL && strstr(why, "data_ps3.psarc.66600 is missing"), "a missing first part is named: %s", why);
    CHECK(ps3_sf_has_parts(base) == 0, "the existence probe needs the first part");

    /* 6. Nothing at all: NULL and no reason. */
    part(p, sizeof p, base, 1); remove(p);
    part(p, sizeof p, base, 3); remove(p);
    s = ps3_sf_open(base, why, sizeof why);
    CHECK(s == NULL && why[0] == 0 && ps3_sf_scan(base, NULL, NULL, NULL, NULL, 0) == 0, "no file and no parts: NULL, no reason");

    /* 7. 64-bit offsets: a sparse first part of 4 GiB - 1 bytes (the FAT32 limit) with a marker at its end, then a
     *    small second part. A read across that edge returns the marker and the second part's bytes. */
    {
        const uint64_t P0 = 4294967295ull;
        part(p, sizeof p, base, 0);
        FILE* f = fopen(p, "wb");
        int ok = f && PS3_SF_SEEK(f, P0 - 8) == 0 && fwrite("ABCDEFGH", 1, 8, f) == 8;
        if (f) fclose(f);
        part(p, sizeof p, base, 1); put(p, (const unsigned char*)"ijklmnop", 8);
        s = ok ? ps3_sf_open(base, why, sizeof why) : NULL;
        char b16[17] = { 0 };
        CHECK(s && ps3_sf_size(s) == P0 + 8 && ps3_sf_pread(s, P0 - 8, b16, 16) == 16 && !memcmp(b16, "ABCDEFGHijklmnop", 16),
              "a read across a 4 GiB - 1 part edge (64-bit offsets) returns %s", b16);
        CHECK(s && ps3_sf_seek(s, -4, SEEK_END, &at) == 0 && at == P0 + 4 && ps3_sf_read(s, b16, 8) == 4 && !memcmp(b16, "mnop", 4),
              "SEEK_END on a set over 4 GiB");
        ps3_sf_close(s);
        part(p, sizeof p, base, 0); remove(p);
        part(p, sizeof p, base, 1); remove(p);
    }
    printf("%s\n", fails ? "FAILED" : "all ok");
    return fails ? 1 : 0;
}
