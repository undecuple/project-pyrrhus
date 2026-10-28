/*
 * Killzone 2 port: the FIOS disk cache belongs to what built it. From Project Helghast (the Killzone 3
 * PC port) v0.1.4, port/net/kz3_fios_stamp.h, MIT, adapted: KZ3_ -> KZ2_, title BCUS98116,
 * KZ2's switch list, log to stderr like the [fs] lines.
 *
 * FIOS (the game's file scheduler, linked into the EBOOT) keeps a disk cache of disc reads in
 * /dev_hdd1/cache/BCUS98116/fios/cache.idx + cache.dat (1.0 MB + 486 MB after a 10 min play run; opened
 * with cellFsOpen about the first second of a boot). On a PS3 neither the disc nor the code reading it changes under a
 * cache. In the port both can: an update of the port is a new exe whose runtime (cellFs, the SPU inflate task, the
 * split-part reader of patch 6034) built or reads that cache, and the update data it serves may come from another
 * folder. KZ3 met the failure on 0.1.3 (error 20000 on settings pages): FIOS kept the blocks of a disc file whose
 * served bytes had changed and failed the read instead of re-reading it (on Killzone 3: the fstat answered the new
 * size and mtime, FIOS still kept the old record). In KZ2 the port's rewritten menu pages never reach FIOS (they are
 * served in guest memory by the fetch hook, kz2_menu_pages.cpp), so the KZ2 exposure is the other half: a cache
 * written by another build of the runtime, or against another update folder.
 *
 * The fix keeps FIOS's contract: before the first open of cache.idx / cache.dat in a process (patch 6035's pre-open
 * hook), the stamp of what serves the disc files (a hash of this exe's bytes, the switches that choose the served
 * update data) is compared with the one stored next to the cache (kz2_cache_stamp.txt). When it differs, or the cache
 * has none (built before this fix), cache.idx and cache.dat are removed, as FIOS itself removes a cache it rejects
 * (patch 4018 makes that removal reach the host), so FIOS builds a new one; the new stamp is written. Same stamp = the
 * cache stays. A copy of the same exe (new mtime) gives the same stamp: the hash is of the bytes; the memo file
 * kz2_exe_hash.txt ("size mtime hash") saves re-reading an unchanged exe (about 0.4 s for the 1.1 GB debug-info build).
 * ASSUMPTION: the disc data itself (data_ps3.psarc) is not in the stamp; a player who swaps the game dump under the
 * same exe keeps the old cache (KZ3 measured that FIOS keeps a cache whose files only got a new mtime).
 * KZ2_FIOS_STAMP=0 turns the check off (tests and A/B of the old behaviour only).
 */
#ifndef KZ2_FIOS_STAMP_H
#define KZ2_FIOS_STAMP_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif

#ifndef KZ2_FIOS_PRINTF
#define KZ2_FIOS_PRINTF(...) fprintf(stderr, __VA_ARGS__)
#endif

/* Switches that change the bytes served under a game path FIOS reads (the 1.29 update folder, main.cpp). */
static const char* const kz2_fs_stamp_env[] = { "KZ2_UPDATE_DIR", "PS3_HDD0_ROOT" };
#define KZ2_FS_STAMP_FILE "kz2_cache_stamp.txt"
#define KZ2_FS_STAMP_MAX 4096

static const char* s_fs_stamp_exe;   /* test override of the exe path (NULL = this process's exe) */
static int s_fs_stamp_done;          /* the first cache open of the process has been handled */

/* 64-bit hash of a whole file (8-byte words, multiply-xor; change detection only, not security), 0 = not readable. */
static unsigned long long kz2_fs_stamp_hash_file(const char* path, long long* size_out)
{
    FILE* f = fopen(path, "rb");
    if (!f) return 0;
    static unsigned char buf[1 << 20];
    unsigned long long h = 0x6A09E667F3BCC908ull, total = 0;
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) {
        size_t i = 0;
        for (; i + 8 <= n; i += 8) {
            unsigned long long w;
            memcpy(&w, buf + i, 8);
            h = (h ^ w) * 0x9E3779B97F4A7C15ull;
            h ^= h >> 29;
        }
        for (; i < n; i++) { h = (h ^ buf[i]) * 0x100000001B3ull; }
        total += n;
    }
    fclose(f);
    h ^= total;
    *size_out = (long long)total;
    return h ? h : 1;
}

/* The stamp text of this process: a hash of the exe's bytes, then each switch above as NAME=value (unset ones left
 * out). memo = "<dir>/kz2_exe_hash.txt" (or NULL): "size mtime hash" of the last hashed exe. */
static int kz2_fs_stamp_text_memo(char* out, size_t cap, const char* memo)
{
    char exe[1024] = "";
    if (s_fs_stamp_exe) snprintf(exe, sizeof exe, "%s", s_fs_stamp_exe);
    else {
#ifdef _WIN32
        DWORD n = GetModuleFileNameA(NULL, exe, (DWORD)sizeof exe);
        if (n == 0 || n >= sizeof exe) exe[0] = 0;
#else
        ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
        exe[n > 0 ? (size_t)n : 0] = 0;
#endif
    }
    struct stat st;
    if (!exe[0] || stat(exe, &st) != 0) return 0;
    unsigned long long h = 0;
    long long sz = 0;
    if (memo) {
        FILE* m = fopen(memo, "rb");
        if (m) {
            long long ms = -1, mt = -1; unsigned long long mh = 0;
            if (fscanf(m, "%lld %lld %llx", &ms, &mt, &mh) == 3 && ms == (long long)st.st_size &&
                mt == (long long)st.st_mtime && mh)
                { h = mh; sz = ms; }
            fclose(m);
        }
    }
    if (!h) {
        h = kz2_fs_stamp_hash_file(exe, &sz);
        if (!h) return 0;
        FILE* m = memo ? fopen(memo, "wb") : NULL;
        if (m) { fprintf(m, "%lld %lld %llx\n", (long long)st.st_size, (long long)st.st_mtime, h); fclose(m); }
    }
    int k = snprintf(out, cap, "kz2 fios cache stamp 1\nexe %lld %016llx\n", sz, h);
    for (size_t i = 0; i < sizeof kz2_fs_stamp_env / sizeof kz2_fs_stamp_env[0] && k > 0 && (size_t)k < cap; i++) {
        const char* v = getenv(kz2_fs_stamp_env[i]);
        if (v) k += snprintf(out + k, cap - (size_t)k, "%s=%.1000s\n", kz2_fs_stamp_env[i], v);
    }
    return k > 0 && (size_t)k < cap;
}
static int kz2_fs_stamp_text(char* out, size_t cap) { return kz2_fs_stamp_text_memo(out, cap, NULL); }

/* 1 when guest path p is FIOS's cache index or data on /dev_hdd1 (".../fios/cache.idx" or ".../fios/cache.dat"). */
static int kz2_fs_stamp_is_cache(const char* p)
{
    size_t n = p ? strlen(p) : 0;
    if (n < 25 || strncmp(p, "/dev_hdd1/", 10)) return 0;
    return !strcmp(p + n - 15, "/fios/cache.idx") || !strcmp(p + n - 15, "/fios/cache.dat");
}

/* Patch 6035's pre-open hook. On the process's first open of the cache: compare stamps, remove a stale cache. */
static void kz2_fs_stamp_preopen(const char* gpath, const char* hpath)
{
    if (s_fs_stamp_done || !kz2_fs_stamp_is_cache(gpath) || !hpath) return;
    s_fs_stamp_done = 1;
    const char* e = getenv("KZ2_FIOS_STAMP");
    if (e && !strcmp(e, "0")) { KZ2_FIOS_PRINTF("[fios] KZ2_FIOS_STAMP=0: disk cache kept unchecked\n"); return; }
    size_t hn = strlen(hpath);
    if (hn < 9 || hn >= 1000) return;
    char dir[1000], idx[1100], dat[1100], stp[1100], memo[1100];
    memcpy(dir, hpath, hn - 9);                       /* strip "cache.idx" / "cache.dat" (same length) */
    dir[hn - 9] = 0;
    snprintf(idx, sizeof idx, "%scache.idx", dir);
    snprintf(dat, sizeof dat, "%scache.dat", dir);
    snprintf(stp, sizeof stp, "%s" KZ2_FS_STAMP_FILE, dir);
    snprintf(memo, sizeof memo, "%skz2_exe_hash.txt", dir);
    char want[KZ2_FS_STAMP_MAX], have[KZ2_FS_STAMP_MAX];
    if (!kz2_fs_stamp_text_memo(want, sizeof want, memo)) {
        KZ2_FIOS_PRINTF("[fios] no stamp for this exe (not readable): disk cache kept unchecked\n");
        return;
    }
    size_t hl = 0;
    FILE* f = fopen(stp, "rb");
    if (f) { hl = fread(have, 1, sizeof have - 1, f); fclose(f); }
    have[hl] = 0;
    struct stat st;
    const int cache = stat(idx, &st) == 0 || stat(dat, &st) == 0;
    if (!strcmp(have, want)) {                        /* the cache was built by what serves the disc now */
        KZ2_FIOS_PRINTF("[fios] disk cache stamp matches this build: %s\n", cache ? "cache kept" : "no cache yet");
        return;
    }
    if (cache) {
        const int ri = remove(idx), rd = remove(dat);
        KZ2_FIOS_PRINTF("[fios] disk cache built by %s: removed (cache.idx %s, cache.dat %s), FIOS builds a new one\n",
                        f ? "another port build or another update folder" : "a build without a cache stamp",
                        ri == 0 ? "removed" : "absent", rd == 0 ? "removed" : "absent");
    } else {
        KZ2_FIOS_PRINTF("[fios] new disk cache: stamp written\n");
    }
    FILE* o = fopen(stp, "wb");
    if (o) { fwrite(want, 1, strlen(want), o); fclose(o); }
    else KZ2_FIOS_PRINTF("[fios] stamp NOT written (%s)\n", stp);
}

/* Install at load time: FIOS opens its cache in the first second of a boot. */
#ifdef __cplusplus
extern "C" void (*g_ps3_fs_preopen_hook)(const char*, const char*);   /* patch 6035 */
#else
extern void (*g_ps3_fs_preopen_hook)(const char*, const char*);
#endif
__attribute__((constructor)) static void kz2_fs_stamp_install(void) { g_ps3_fs_preopen_hook = kz2_fs_stamp_preopen; }

#endif /* KZ2_FIOS_STAMP_H */
