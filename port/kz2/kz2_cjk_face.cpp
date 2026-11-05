/* Killzone 2 port, an earlier change (D53): which face of the bundled CJK collection draws Han characters (patch 6061's weak
 * kz2_cjk_face_index(); ENHANCEMENT over the PS3, whose fontset 0x109 draws every Han character from its Japanese face).
 *
 * NotoSansCJK-Regular.ttc (tools/runtime/mkfont_cjk.py) holds five faces over one glyph set: 0 JP, 1 KR, 2 SC, 3 TC,
 * 4 HK; they differ in which shape a Han code point (and some full-width punctuation) maps to. The game opens one
 * system fontset at boot and asks for one code point at a time, so the language is not in the font requests. It is in
 * the game's own page fetches: the front end reads every page from interface/svo/svml/<code>/ (the game's language
 * code: ja, ko, zh-cn, zh-hk, en, ...), and kz2_menu_fetch (kz2_menu_pages.cpp, the fetch @0x0049EA38) passes each
 * path to kz2_cjk_note_page. Order:
 *   1. KZ2_CJK_FACE = ja | ko | zh-cn | zh-tw | zh-hk | 0..4 (test aid; logged once);
 *   2. the code of the last page the game fetched, when it is a CJK one;
 *   3. the disc's region (cellGame title id): BCJS/NPJA -> JP, BCKS/NPKA -> KR, BCAS -> HK (the Asian disc's Chinese
 *      pages are zh-hk), any other -> JP (the PS3's order).
 * ASSUMPTION: before the first CJK page (the Asian disc's first-start language page is read from en) the region
 * decides; the game's own language variable (gModule:GetLanguage, binding 0x002C81C0 -> module +0x40) is not read.
 * Characters already drawn keep their shapes: the game caches each converted glyph per character.
 */
#include <atomic>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern "C" {
const char* cellGame_get_title_id(void);   /* cellGame: the disc's PARAM.SFO TITLE_ID */
}

namespace {
std::atomic<int> g_page_face{-1};
std::atomic<int> g_env_face{-2};   /* -2 not read yet, -1 unset */

int face_of_code(const char* c, size_t n)
{
    static const struct { const char* code; int face; } k[] = {
        {"ja", 0}, {"ko", 1}, {"zh-cn", 2}, {"zh-tw", 3}, {"zh-hk", 4},
        {"0", 0}, {"1", 1}, {"2", 2}, {"3", 3}, {"4", 4},
    };
    for (const auto& e : k)
        if (strlen(e.code) == n && !strncmp(e.code, c, n)) return e.face;
    return -1;
}

int region_face(void)
{
    const char* t = cellGame_get_title_id();
    if (!t) return 0;
    if (!strncmp(t, "BCJS", 4) || !strncmp(t, "NPJA", 4) || !strncmp(t, "BCJT", 4)) return 0;
    if (!strncmp(t, "BCKS", 4) || !strncmp(t, "NPKA", 4) || !strncmp(t, "BCKT", 4)) return 1;
    if (!strncmp(t, "BCAS", 4)) return 4;
    return 0;
}
}  // namespace

/* A page path the game fetched ("source:interface/svo/svml/<code>/kin/..."). */
extern "C" void kz2_cjk_note_page(const char* path)
{
    const char* p = path ? strstr(path, "svml/") : nullptr;
    if (!p) return;
    p += 5;
    const char* e = strchr(p, '/');
    if (!e) return;
    const int f = face_of_code(p, (size_t)(e - p));
    if (f >= 0 && g_page_face.exchange(f) != f)
        fprintf(stderr, "[cellFont] CJK face %d from the game's page language '%.*s'\n", f, (int)(e - p), p);
}

extern "C" int kz2_cjk_face_index(void)
{
    int env = g_env_face.load();
    if (env == -2) {
        const char* v = getenv("KZ2_CJK_FACE");
        env = (v && *v) ? face_of_code(v, strlen(v)) : -1;
        if (v && *v) fprintf(stderr, "[cellFont] KZ2_CJK_FACE=%s -> face %d\n", v, env);
        g_env_face.store(env);
    }
    if (env >= 0) return env;
    const int pf = g_page_face.load();
    return pf >= 0 ? pf : region_face();
}
