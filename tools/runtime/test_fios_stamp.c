/* Host test: port/kz2/kz2_fios_stamp.h (the FIOS disk cache stamp, patch 6035's pre-open hook).
 * From Project Helghast (the Killzone 3 PC port) v0.1.4, tools/net/test_kz3_net.c test_fios_stamp (MIT),
 * adapted to KZ2's names, switches and title. Cases: a cache from before the fix (no stamp) is removed; the same exe
 * keeps the cache (and a copy of it with a new mtime too); a different exe removes it; no cache at all writes the
 * stamp and removes nothing; another update folder removes it; only the first cache open of a process is checked;
 * KZ2_FIOS_STAMP=0 keeps it; an unreadable exe leaves it alone; paths that are not the cache are ignored.
 *   nix develop --command tools/sandbox.sh -- tools/runtime/test_fios_stamp.sh */
#define _DEFAULT_SOURCE
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <utime.h>

void (*g_ps3_fs_preopen_hook)(const char*, const char*);   /* patch 6035 (kz2_fios_stamp.h sets it) */
#include "../../port/kz2/kz2_fios_stamp.h"

static int fs_exists(const char* p) { struct stat st; return stat(p, &st) == 0; }
static void fs_touch(const char* p, const char* text) { FILE* f = fopen(p, "wb"); assert(f); fputs(text, f); fclose(f); }
static int s_checks;
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "[FAIL] %s:%d %s\n", __FILE__, __LINE__, #c); exit(1); } s_checks++; } while (0)

int main(int argc, char** argv)
{
    const char* base = argc > 1 ? argv[1] : "/tmp";
    CHECK(g_ps3_fs_preopen_hook == kz2_fs_stamp_preopen);   /* the constructor installed it */
    char dir[512];
    snprintf(dir, sizeof dir, "%s/kz2fiosXXXXXX", base);
    CHECK(mkdtemp(dir) != NULL);
    char exe[600], idx[600], dat[600], stp[600], hidx[600], memo[600];
    snprintf(exe, sizeof exe, "%s/kz2.exe", dir);
    snprintf(idx, sizeof idx, "%s/cache.idx", dir); snprintf(dat, sizeof dat, "%s/cache.dat", dir);
    snprintf(stp, sizeof stp, "%s/" KZ2_FS_STAMP_FILE, dir); snprintf(hidx, sizeof hidx, "%s/cache.idx", dir);
    snprintf(memo, sizeof memo, "%s/kz2_exe_hash.txt", dir);
    const char* g = "/dev_hdd1/cache/BCUS98116/fios/cache.idx";
    fs_touch(exe, "exe v1");
    s_fs_stamp_exe = exe;
    unsetenv("KZ2_UPDATE_DIR"); unsetenv("PS3_HDD0_ROOT"); unsetenv("KZ2_FIOS_STAMP");

    /* not the cache: nothing, and the first-open flag stays */
    s_fs_stamp_done = 0;
    fs_touch(idx, "i"); fs_touch(dat, "d");
    kz2_fs_stamp_preopen("/dev_bdvd/PS3_GAME/USRDIR/data_ps3.psarc", hidx);
    kz2_fs_stamp_preopen("/dev_hdd0/fios/cache.idx", hidx);
    CHECK(!s_fs_stamp_done && fs_exists(idx) && fs_exists(dat) && !fs_exists(stp));

    /* a cache from before the fix (no stamp): removed, stamp written */
    kz2_fs_stamp_preopen(g, hidx);
    CHECK(s_fs_stamp_done && !fs_exists(idx) && !fs_exists(dat) && fs_exists(stp));

    /* only the first cache open of a process is checked */
    fs_touch(idx, "i"); fs_touch(dat, "d"); fs_touch(stp, "other");
    kz2_fs_stamp_preopen(g, hidx);
    CHECK(fs_exists(idx) && fs_exists(dat));

    /* CASE same exe (next start, same exe and switches): kept; cache.dat opened first works the same */
    s_fs_stamp_done = 0; remove(stp);
    { char w[KZ2_FS_STAMP_MAX]; CHECK(kz2_fs_stamp_text(w, sizeof w)); fs_touch(stp, w);
      CHECK(strstr(w, "kz2 fios cache stamp 1\nexe 6 ") == w && !strstr(w, "KZ2_UPDATE_DIR")); }
    kz2_fs_stamp_preopen("/dev_hdd1/cache/BCUS98116/fios/cache.dat", hidx);
    CHECK(s_fs_stamp_done && fs_exists(idx) && fs_exists(dat));

    /* a copy of the same exe (new mtime, as every staged run and an installer reinstall make): kept, memo follows */
    { struct utimbuf ut = { 1000000000, 1000000000 }; fs_touch(exe, "exe v1"); CHECK(utime(exe, &ut) == 0); }
    s_fs_stamp_done = 0;
    kz2_fs_stamp_preopen(g, hidx);
    CHECK(fs_exists(idx) && fs_exists(dat));
    { FILE* m = fopen(memo, "rb"); CHECK(m != NULL);
      long long ms, mt; unsigned long long mh; CHECK(fscanf(m, "%lld %lld %llx", &ms, &mt, &mh) == 3); fclose(m);
      CHECK(ms == 6 && mt == 1000000000 && mh); }

    /* another update folder: removed; the stamp names it */
    s_fs_stamp_done = 0; setenv("KZ2_UPDATE_DIR", "D:/kz2/update/USRDIR", 1);
    kz2_fs_stamp_preopen(g, hidx);
    CHECK(!fs_exists(idx) && !fs_exists(dat));
    { char w[KZ2_FS_STAMP_MAX]; CHECK(kz2_fs_stamp_text(w, sizeof w) && strstr(w, "KZ2_UPDATE_DIR=D:/kz2/update/USRDIR\n")); }
    unsetenv("KZ2_UPDATE_DIR");

    /* CASE no cache at all: the stamp is written, nothing removed, the cache FIOS then builds is kept next time */
    s_fs_stamp_done = 0; kz2_fs_stamp_preopen(g, hidx);
    CHECK(!fs_exists(idx) && !fs_exists(dat) && fs_exists(stp));
    { char w[KZ2_FS_STAMP_MAX], h[KZ2_FS_STAMP_MAX]; CHECK(kz2_fs_stamp_text(w, sizeof w));
      FILE* f = fopen(stp, "rb"); CHECK(f != NULL); size_t n = fread(h, 1, sizeof h - 1, f); fclose(f); h[n] = 0;
      CHECK(!strcmp(w, h)); }
    fs_touch(idx, "i"); fs_touch(dat, "d");
    s_fs_stamp_done = 0; kz2_fs_stamp_preopen(g, hidx);
    CHECK(fs_exists(idx) && fs_exists(dat));

    /* CASE different exe (an update of the port): removed */
    fs_touch(exe, "exe v2, longer");
    s_fs_stamp_done = 0; kz2_fs_stamp_preopen(g, hidx);
    CHECK(!fs_exists(idx) && !fs_exists(dat));
    /* same size, other bytes, same mtime as the memo: the memo is keyed on size + mtime, so give a new mtime as a
     * real write does; the hash then sees the new bytes */
    fs_touch(idx, "i"); fs_touch(dat, "d");
    { fs_touch(exe, "exe v3, longer"); struct utimbuf ut = { 1100000000, 1100000000 }; CHECK(utime(exe, &ut) == 0); }
    s_fs_stamp_done = 0; kz2_fs_stamp_preopen(g, hidx);
    CHECK(!fs_exists(idx) && !fs_exists(dat));

    /* KZ2_FIOS_STAMP=0: kept whatever the stamp */
    fs_touch(idx, "i"); fs_touch(stp, "stale");
    s_fs_stamp_done = 0; setenv("KZ2_FIOS_STAMP", "0", 1);
    kz2_fs_stamp_preopen(g, hidx);
    CHECK(fs_exists(idx));
    unsetenv("KZ2_FIOS_STAMP");

    /* no readable exe: no stamp, the cache is left alone */
    s_fs_stamp_exe = "/nonexistent/kz2.exe"; s_fs_stamp_done = 0;
    kz2_fs_stamp_preopen(g, hidx);
    CHECK(fs_exists(idx));
    s_fs_stamp_exe = NULL;

    remove(idx); remove(dat); remove(stp); remove(exe); remove(memo); rmdir(dir);
    printf("PASS test_fios_stamp (%d checks)\n", s_checks);
    return 0;
}
