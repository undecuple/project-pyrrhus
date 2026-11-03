/*
 * Killzone 2 port: the game folder read in place, every write under KZ2_CACHE_ROOT (an earlier changeb, the link-free
 * install). The shape is Project Helghast's (the Killzone 3 PC port, port/kz3/main.cpp kz3_split_roots and
 * KZ3_CACHE_ROOT, same author, MIT); KZ3 adds KZ3_CACHE_ROOT with the same names.
 *
 * Without it, PS3_VFS_ROOT (the folder holding PS3_GAME) is also where the runtime writes, because every mount maps
 * under it (ppu_fs.cpp / sys_fs.c host_path: "/dev_hdd1/x" -> <vfs root>/x). So the release launcher made a writable
 * <install>/vfs whose PS3_GAME is a junction to the dump. With KZ2_CACHE_ROOT set:
 *   - PS3_VFS_ROOT = the dump, only read (/dev_bdvd, /app_home -> <dump>/PS3_GAME/...).
 *   - /dev_hdd1 (the cache partition; Killzone 2 mounts /dev_hdd1/cache/BCUS98116 and keeps FIOS's disk cache
 *     fios/cache.idx + cache.dat there, with kz2_fios_stamp.h's stamp beside it): PS3_HDD1_ROOT = <cache root>, so
 *     the files land at <cache root>/cache/BCUS98116/fios, the same place relative to the root as the junction
 *     layout's <install>/vfs/cache/BCUS98116/fios. The launcher passes KZ2_CACHE_ROOT = <install>/vfs, so an install
 *     updated from a junction build keeps its folder.
 *   - /dev_hdd0: PS3_HDD0_ROOT = <PS3_GAMEDATA_ROOT or "gamedata">/dev_hdd0, the tree under the working folder where
 *     cellSaveData already keeps the saves (home/00000001/savedata) and sceNpTrophy the trophies (trophy_hdd0_root's
 *     fallback): one /dev_hdd0, as on a PS3, and no write can reach the dump. Killzone 2 itself opens nothing on
 *     /dev_hdd0 but its 1.29 update (served through KZ2_UPDATE_DIR's miss hook either way; checked in rounds 67/67b
 *     logs: only /dev_bdvd and /dev_hdd1 opens).
 *   - A variable the caller already set wins (PS3_HDD0_ROOT for an update in an RPCS3 dev_hdd0 tree, set by the
 *     launcher or by main.cpp setup_update_dir, which runs first; PS3_HDD1_ROOT).
 * Saves, settings (%APPDATA%\Project Pyrrhus\*.ini), logs and the shader caches never lived under the VFS root and do
 * not move. Unset KZ2_CACHE_ROOT = today's layout, nothing changes.
 * tools/release/firstrun.py cache_root_supported looks for this file naming KZ2_CACHE_ROOT (build-stamp "cache_root").
 * Pure (no globals): host test tools/runtime/test_cache_root.sh.
 */
#ifndef KZ2_CACHE_ROOT_H
#define KZ2_CACHE_ROOT_H

#include <stdio.h>
#include <string.h>

#define KZ2_CACHE_ROOT_ENV "KZ2_CACHE_ROOT"

typedef struct {
    int split;            /* 1: KZ2_CACHE_ROOT is set, the roots are apart */
    char cache[1024];     /* the cache root, '/' separators, no trailing '/' */
    char hdd1[1100];      /* PS3_HDD1_ROOT to set, "" = leave it */
    char hdd0[1100];      /* PS3_HDD0_ROOT to set, "" = leave it */
} kz2_cache_plan;

static inline void kz2_cache_norm(char* s)
{
    for (char* p = s; *p; p++) if (*p == '\\') *p = '/';
    size_t n = strlen(s);
    while (n > 1 && s[n - 1] == '/' && !(n == 3 && s[1] == ':')) s[--n] = 0;   /* keep "C:/" */
}

/* What to set, from the four variables (NULL or "" = unset). */
static inline kz2_cache_plan kz2_cache_root_plan(const char* cache_root, const char* hdd1_root, const char* hdd0_root,
                                                 const char* gamedata_root)
{
    kz2_cache_plan p;
    memset(&p, 0, sizeof p);
    if (!cache_root || !*cache_root) return p;
    p.split = 1;
    snprintf(p.cache, sizeof p.cache, "%s", cache_root);
    kz2_cache_norm(p.cache);
    if (!hdd1_root || !*hdd1_root) snprintf(p.hdd1, sizeof p.hdd1, "%s", p.cache);
    if (!hdd0_root || !*hdd0_root) {
        char g[1024];
        snprintf(g, sizeof g, "%s", gamedata_root && *gamedata_root ? gamedata_root : "gamedata");
        kz2_cache_norm(g);
        snprintf(p.hdd0, sizeof p.hdd0, "%s/dev_hdd0", g);
    }
    return p;
}

/* The folder this port writes its own files under: KZ2_CACHE_ROOT, else the VFS root (today's layout). */
static inline const char* kz2_cache_root_or(const char* cache_root, const char* vfs_root)
{
    return cache_root && *cache_root ? cache_root : vfs_root;
}

#endif /* KZ2_CACHE_ROOT_H */
