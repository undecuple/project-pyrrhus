/* KZ2_PAD_LAYOUT: see kz2_pad_layout.h. ENHANCEMENT: the Modern preset is the port's
 * (tools/assets/pad_layouts.py MODERN); `original` (the launcher's default) and unset change
 * nothing for a profile that never held the Modern map. */
#include "kz2_pad_layout.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>

static int ieq(const char* a, const char* b)
{
    for (; *a && *b; a++, b++)
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b)) return 0;
    return *a == *b;
}

int kz2_pad_layout_parse(const char* s)
{
    if (!s || !*s || ieq(s, "original")) return KZ2_PAD_ORIGINAL;
    if (ieq(s, "modern")) return KZ2_PAD_MODERN;
    return -1;
}

int kz2_pad_layout_mode(void)
{
    static int mode = -2;
    if (mode == -2) {
        const char* e = getenv("KZ2_PAD_LAYOUT");
        int m = kz2_pad_layout_parse(e);
        if (m < 0) {
            fprintf(stderr, "[kz2-pad] KZ2_PAD_LAYOUT=%s not understood (original|modern): original\n", e);
            m = KZ2_PAD_ORIGINAL;
        }
        fprintf(stderr, "[kz2-pad] pad layout %s (KZ2_PAD_LAYOUT)\n", m == KZ2_PAD_MODERN ? "modern" : "original");
        mode = m;
    }
    return mode;
}

int kz2_pad_layout_slot_ok(int32_t func)
{
    return func >= 0 && func < KZ2_PAD_NFUNC && func != 18 && kz2_pad_modern[func] != KZ2_PAD_NOT_SET;
}

int32_t kz2_pad_layout_set_button(int mode, int32_t func, int32_t button)
{
    if (mode != KZ2_PAD_MODERN || !kz2_pad_layout_slot_ok(func)) return button;
    return kz2_pad_modern[func];
}

int kz2_pad_layout_is_modern(const int32_t map[KZ2_PAD_NFUNC])
{
    for (int f = 0; f < KZ2_PAD_NFUNC; f++)
        if (kz2_pad_layout_slot_ok(f) && map[f] != kz2_pad_modern[f]) return 0;
    return 1;
}

int kz2_pad_layout_fix_map(int mode, int32_t map[KZ2_PAD_NFUNC], uint32_t scheme)
{
    const int8_t* want;
    if (mode == KZ2_PAD_MODERN) want = kz2_pad_modern;
    else if (kz2_pad_layout_is_modern(map)) want = kz2_pad_original[scheme < KZ2_PAD_NPRESETS ? scheme : 0];
    else return 0;
    int n = 0;
    for (int f = 0; f < KZ2_PAD_NFUNC; f++)
        if (kz2_pad_layout_slot_ok(f) && map[f] != want[f]) { map[f] = want[f]; n++; }
    return n;
}

uint16_t kz2_ebutton_mask(int32_t b)
{
    /* EButton: Triangle 0, Circle 1, Cross 2, Square 3, L2 4, R2 5, L1 6, R1 7, Start 8, Select 9, L3 10, R3 11,
     * Up 12, Right 13, Down 14, Left 15 (the RE notes "An earlier change") */
    static const uint16_t m[16] = { 0x1000, 0x2000, 0x4000, 0x8000, 0x0100, 0x0200, 0x0400, 0x0800,
                                    0x0008, 0x0001, 0x0002, 0x0004, 0x0010, 0x0020, 0x0040, 0x0080 };
    return b >= 0 && b < 16 ? m[b] : 0;
}

int kz2_kb_roles(const int32_t map[KZ2_PAD_NFUNC], uint16_t out[16])
{
    /* key bit (CELL mask) -> its Standard 1 function (kz2_pad_original[0] puts each of these on that bit) */
    static const struct { uint16_t bit; int8_t func; } role[] = {
        { 0x0800, 0 }, { 0x0004, 2 }, { 0x0002, 4 }, { 0x4000, 5 }, { 0x2000, 6 }, { 0x0200, 8 },
        { 0x8000, 9 }, { 0x0100, 10 }, { 0x1000, 13 }, { 0x0400, 16 }, { 0x0010, 19 },
    };
    int changed = 0;
    for (int i = 0; i < 16; i++) out[i] = (uint16_t)(1u << i);
    for (unsigned k = 0; k < sizeof role / sizeof role[0]; k++) {
        const uint16_t m = kz2_ebutton_mask(map[role[k].func]);
        if (!m) continue;
        int i = 0;
        while ((1u << i) != role[k].bit) i++;
        if (out[i] != m) { out[i] = m; changed++; }
    }
    return changed;
}
