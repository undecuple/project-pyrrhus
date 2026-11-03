/* Host test: port/kz2/kz2_cache_root.h (KZ2_CACHE_ROOT, an earlier change). No game data, no GPU. */
#include <stdio.h>
#include <string.h>
#include "../../port/kz2/kz2_cache_root.h"

static int fails;
#define EQ(a, b) do { if (strcmp((a), (b)) != 0) { printf("[FAIL] %s:%d '%s' != '%s'\n", __FILE__, __LINE__, (a), (b)); fails++; } } while (0)
#define OK(c) do { if (!(c)) { printf("[FAIL] %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

int main(void)
{
    kz2_cache_plan p = kz2_cache_root_plan(NULL, NULL, NULL, NULL);       /* unset: today's layout */
    OK(!p.split); EQ(p.hdd1, ""); EQ(p.hdd0, "");
    p = kz2_cache_root_plan("", "x", "y", "z");
    OK(!p.split); EQ(p.hdd1, ""); EQ(p.hdd0, "");
    /* the launcher's value: <install>\vfs */
    p = kz2_cache_root_plan("C:\\Games\\Project Pyrrhus\\vfs\\", NULL, NULL, NULL);
    OK(p.split); EQ(p.cache, "C:/Games/Project Pyrrhus/vfs"); EQ(p.hdd1, "C:/Games/Project Pyrrhus/vfs");
    EQ(p.hdd0, "gamedata/dev_hdd0");
    /* an RPCS3 update tree already set PS3_HDD0_ROOT; an explicit PS3_HDD1_ROOT wins too */
    p = kz2_cache_root_plan("Z:/c", "Z:/h1", "Z:/rpcs3/dev_hdd0", NULL);
    OK(p.split); EQ(p.hdd1, ""); EQ(p.hdd0, "");
    /* PS3_GAMEDATA_ROOT moves the saves and trophies' tree; /dev_hdd0 follows it */
    p = kz2_cache_root_plan("Z:/c", "", "", "D:\\saves\\");
    EQ(p.hdd1, "Z:/c"); EQ(p.hdd0, "D:/saves/dev_hdd0");
    /* a drive root keeps its slash */
    p = kz2_cache_root_plan("D:\\", NULL, NULL, NULL);
    EQ(p.cache, "D:/");
    /* the FIOS cache path relative to the root stays where the junction layout had it: <root>/cache/BCUS98116 */
    char a[1200], b[1200];
    snprintf(a, sizeof a, "%s/cache/BCUS98116/fios/cache.idx", kz2_cache_root_or(NULL, "C:/x/vfs"));
    p = kz2_cache_root_plan("C:/x/vfs", NULL, NULL, NULL);
    snprintf(b, sizeof b, "%s/cache/BCUS98116/fios/cache.idx", p.hdd1);
    EQ(a, b);
    EQ(kz2_cache_root_or("", "v"), "v"); EQ(kz2_cache_root_or("c", "v"), "c");
    if (fails) { printf("FAIL: %d\n", fails); return 1; }
    printf("PASS: cache root plan (12 cases)\n");
    return 0;
}
