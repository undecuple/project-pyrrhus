/* Prompt glyph source: what KZ2 patches 2091-2093 (rsx_keycaps.h, rsx_prompt_glyphs.h) ask the exe
 * for: the bound keys (cellPad.c, patches 2037/2038/2091), whether the prompts are keycaps (4011), the pad variant
 * (a DualSense, 4011) and the label text as an 8-bit coverage mask.
 *
 * From Project Helghast port/kz3/main.cpp (kz3_notice_face, kz3_notice_face_exists, kz3_notice_font, kz3_keycap_text,
 * kz3_keycaps_register), adapted: KZ2 has no error notice yet, so the fonts are loaded here. Rajdhani Bold and Medium
 * (SIL OFL 1.1) from <exe dir>\fonts\, privately (FR_PRIVATE: this process only, never installed); the payload ships
 * them there (tools/release/assemble_payload.py FONTS, firstrun/launcher copy them next to kz2.exe). Without them GDI
 * would substitute a serif face under Wine, so the fallback is the first installed of Segoe UI, Tahoma, Arial.
 * The thin face (2093: the PS3 icon labels' look) is Rajdhani Medium (GDI family "Rajdhani Medium") with one pixel of letter spacing per 12 px of em
 * (ASSUMPTION: Project Helghast's own value for the spacing was not in the import; this matches its description).
 * ENHANCEMENT. KZ2_KEYCAPS=0 turns the atlas replacement off (rsx_keycaps.h). */
#ifdef _WIN32
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "kz2_log.h"

extern "C" int pad_kb_last_device_keyboard(void);                 /* cellPad.c (2038, 4011) */
extern "C" int pad_kb_key_for_input(const char* name, int slot);  /* cellPad.c (2091) */
extern "C" const char* pad_kb_key_label(int vk);                  /* cellPad.c (2038) */
extern "C" int pad_prompt_device(void);                           /* cellPad.c (4011): PAD_DEV_PS5 = 4 */

/* The same layout as rsx_keycaps.h's rsx_keycap_source (2091 + 2093). */
struct rsx_keycap_source {
    int (*keyboard_active)(void);
    int (*key_for_input)(const char*, int);
    const char* (*key_name)(int);
    int (*text_mask)(const char*, int, unsigned char*, int, int);
    int (*text_mask_thin)(const char*, int, unsigned char*, int, int);
    int (*pad_variant)(void);
};
extern "C" void rsx_keycaps_set_source(const rsx_keycap_source* s);   /* rsx_live_draw.c (2091) */

static int kz2_face_exists_cb(const LOGFONTA*, const TEXTMETRICA*, DWORD, LPARAM found)
{
    *(int*)found = 1;
    return 0;
}

/* 1 when a family of exactly this name is installed (Wine maps a missing "Segoe UI" to a serif face and still reports
 * the asked name, so the name is enumerated rather than asked of a created font). */
static int kz2_face_exists(const char* face)
{
    LOGFONTA lf; memset(&lf, 0, sizeof lf);
    lf.lfCharSet = DEFAULT_CHARSET;
    snprintf(lf.lfFaceName, sizeof lf.lfFaceName, "%s", face);
    int found = 0;
    HDC dc = GetDC(NULL);
    EnumFontFamiliesExA(dc, &lf, (FONTENUMPROCA)kz2_face_exists_cb, (LPARAM)&found, 0);
    ReleaseDC(NULL, dc);
    return found;
}

/* The face for bold (1) or medium (0) labels: Rajdhani when its file loaded, else the fallback. */
static const char* kz2_prompt_face(int bold)
{
    static INIT_ONCE once = INIT_ONCE_STATIC_INIT;
    static char face_ok[2];
    static const char* fallback = "Arial";
    BOOL pending = FALSE;
    InitOnceBeginInitialize(&once, 0, &pending, NULL);
    if (pending) {
        char dir[MAX_PATH]; DWORD n = GetModuleFileNameA(NULL, dir, sizeof dir);
        while (n > 0 && dir[n - 1] != '\\' && dir[n - 1] != '/') n--;
        dir[n] = 0;
        const char* files[2] = { "fonts\\Rajdhani-Medium.ttf", "fonts\\Rajdhani-Bold.ttf" };
        for (int i = 0; i < 2; i++) {
            char path[MAX_PATH + 40];
            snprintf(path, sizeof path, "%s%s", dir, files[i]);
            face_ok[i] = AddFontResourceExA(path, FR_PRIVATE, 0) > 0;
        }
        if (!face_ok[0] || !face_ok[1]) {
            const char* order[3] = { "Segoe UI", "Tahoma", "Arial" };
            for (int i = 0; i < 3; i++) if (kz2_face_exists(order[i])) { fallback = order[i]; break; }
        }
        KZ2_LOGI("prompts", "label font: Rajdhani %s (fonts\\Rajdhani-Medium.ttf %s, -Bold.ttf %s)%s%s",
                 face_ok[0] && face_ok[1] ? "loaded privately" : "missing", face_ok[0] ? "ok" : "no", face_ok[1] ? "ok" : "no",
                 face_ok[0] && face_ok[1] ? "" : "; fallback ", face_ok[0] && face_ok[1] ? "" : fallback);
        InitOnceComplete(&once, 0, NULL);
    }
    /* GDI names a face by the font's family name (name ID 1): "Rajdhani" is only the Bold file, the Medium file's
     * family is "Rajdhani Medium" (subfamily Regular; "Rajdhani"/"Medium" are its typographic names, ID 16/17, which
     * GDI does not match). Asking "Rajdhani" at FW_MEDIUM gave the Bold file, so the thin labels were bold and
     * letter-spaced; at the HUD label size (cap about 7 px) the bold strokes filled the counters and 2093's dark
     * outline turned each letter into a light box (tools/runtime/test_prompt_font.sh). */
    return face_ok[bold ? 1 : 0] ? (bold ? "Rajdhani" : "Rajdhani Medium") : fallback;
}

static int kz2_prompt_weight(int bold) { return bold ? FW_BOLD : FW_MEDIUM; }

/* Rasterise `text` white on black, grey-scale anti-aliased, as large as fits w x h with the capitals at most max_px
 * (Rajdhani's capitals are about 0.7 em), into mask (w x h, 8-bit). spacing_div > 0 adds em/spacing_div pixels
 * between letters (at least 1). 0 = nothing drawn. */
static int kz2_text(const char* text, int max_px, unsigned char* mask, int w, int h, int bold, int spacing_div)
{
    if (!text || !*text || w < 2 || h < 2) return 0;
    const char* face = kz2_prompt_face(bold);
    HDC dc = CreateCompatibleDC(NULL);
    if (!dc) return 0;
    BITMAPINFO bi; memset(&bi, 0, sizeof bi);
    bi.bmiHeader.biSize = sizeof bi.bmiHeader; bi.bmiHeader.biWidth = w; bi.bmiHeader.biHeight = -h;
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    void* bits = nullptr;
    HBITMAP bm = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, NULL, 0);
    if (!bm || !bits) { if (bm) DeleteObject(bm); DeleteDC(dc); return 0; }
    HGDIOBJ obm = SelectObject(dc, bm);
    const int n = (int)strlen(text);
    int em = (int)(max_px / 0.70f + 0.5f), drawn = 0;
    for (; em >= 6 && !drawn; em--) {
        HFONT f = CreateFontA(-em, 0, 0, 0, kz2_prompt_weight(bold), FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_TT_PRECIS,
                              CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY, DEFAULT_PITCH | FF_SWISS, face);
        if (!f) continue;
        HGDIOBJ of = SelectObject(dc, f);
        const int extra = spacing_div > 0 ? (em / spacing_div > 1 ? em / spacing_div : 1) : 0;
        SetTextCharacterExtra(dc, extra);
        SIZE sz; GetTextExtentPoint32A(dc, text, n, &sz);
        if ((sz.cx <= w && sz.cy <= h + em / 4) || em == 6) {
            memset(bits, 0, (size_t)w * h * 4);
            SetBkMode(dc, TRANSPARENT); SetTextColor(dc, RGB(255, 255, 255));
            TextOutA(dc, (w - sz.cx) / 2, (h - sz.cy) / 2, text, n);
            GdiFlush();
            const uint8_t* px = (const uint8_t*)bits;
            for (int i = 0; i < w * h; i++) mask[i] = px[i * 4 + 1];
            drawn = 1;
        }
        SelectObject(dc, of); DeleteObject(f);
    }
    SelectObject(dc, obm); DeleteObject(bm); DeleteDC(dc);
    return drawn;
}

static int kz2_text_bold(const char* t, int max_px, unsigned char* m, int w, int h) { return kz2_text(t, max_px, m, w, h, 1, 0); }
static int kz2_text_thin(const char* t, int max_px, unsigned char* m, int w, int h) { return kz2_text(t, max_px, m, w, h, 0, 12); }
/* The pad variant (1 = DualSense: CREATE where the DualShock 4 shows the touchpad). KZ2_PROMPT_PAD=ps5|ps4 forces it for
 * tests (frames of the PS5 set without a DualSense on the machine); read once. */
static int kz2_pad_variant(void)
{
    static int forced = -2;
    if (forced == -2) {
        const char* e = getenv("KZ2_PROMPT_PAD");
        forced = !e || !*e ? -1 : !strcmp(e, "ps5") ? 1 : !strcmp(e, "ps4") ? 0 : -1;
        if (e && *e) KZ2_LOGI("prompts", "KZ2_PROMPT_PAD=%s: %s", e, forced < 0 ? "unknown value, ignored" : "pad variant forced");
    }
    return forced >= 0 ? forced : pad_prompt_device() == 4 ? 1 : 0;
}

extern "C" void kz2_prompts_register(void)
{
    static const rsx_keycap_source src = { pad_kb_last_device_keyboard, pad_kb_key_for_input, pad_kb_key_label,
                                           kz2_text_bold, kz2_text_thin, kz2_pad_variant };
    rsx_keycaps_set_source(&src);
}
#else
extern "C" void kz2_prompts_register(void) {}
#endif
