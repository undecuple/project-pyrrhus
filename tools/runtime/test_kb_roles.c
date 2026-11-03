/* Host test for patch 6050 (keys keep their action under any pad layout): kz2_kb_roles (port/kz2/kz2_pad_layout.c) on
 * the six shipped controller schemes and the port's Modern layout, and cellPad's pure pad_kb_roles.h (apply, and the
 * keycap source for a prompt's button). The 0.1.6 report: under a layout with zoom on L1 and close combat on R3, the
 * right mouse button (r3) meleed and F (l1) zoomed. */
#include <stdio.h>
#include <string.h>
#include "kz2_pad_layout.h"
#include "pad_kb_roles.h"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)
enum { L1 = 0x0400, R3 = 0x0004, R1 = 0x0800, L2 = 0x0100, R2 = 0x0200, CIRCLE = 0x2000, SQUARE = 0x8000, TRI = 0x1000,
       CROSS = 0x4000, START = 0x0008, L3 = 0x0002, UP = 0x0010 };

static void map_of(const int8_t* p, int32_t* m) { for (int f = 0; f < KZ2_PAD_NFUNC; f++) m[f] = p[f]; }

int main(void)
{
    int32_t map[KZ2_PAD_NFUNC]; uint16_t out[16]; unsigned short o2[16];
    /* Standard 1 (the default scheme): nothing moves */
    map_of(kz2_pad_original[0], map);
    CHECK(kz2_kb_roles(map, out) == 0, "Standard 1 changes nothing");
    for (int i = 0; i < 16; i++) CHECK(out[i] == (1u << i), "Standard 1 identity at bit %d", i);
    /* every scheme: the zoom key (r3 = Mouse2) gives ZoomSwitch's button, the melee key (l1 = F) CloseCombat's,
     * the fire key R1 PrimaryFire's */
    for (int s = 0; s <= KZ2_PAD_NPRESETS; s++) {
        map_of(s < KZ2_PAD_NPRESETS ? kz2_pad_original[s] : kz2_pad_modern, map);
        kz2_kb_roles(map, out);
        for (int i = 0; i < 16; i++) o2[i] = out[i];
        CHECK(pad_kb_roles_apply(o2, R3) == kz2_ebutton_mask(map[2]), "scheme %d: zoom key -> zoom", s);
        CHECK(pad_kb_roles_apply(o2, L1) == kz2_ebutton_mask(map[16]), "scheme %d: melee key -> close combat", s);
        CHECK(pad_kb_roles_apply(o2, R1) == kz2_ebutton_mask(map[0]), "scheme %d: fire key -> fire", s);
        CHECK(pad_kb_roles_apply(o2, START) == START, "scheme %d: start stays", s);
    }
    /* Modern and Alternate 2 (the reported swap): Mouse2 (r3) -> L1 (zoom), F (l1) -> R3 (close combat) */
    for (int k = 0; k < 2; k++) {
        map_of(k ? kz2_pad_original[5] : kz2_pad_modern, map);
        kz2_kb_roles(map, out);
        for (int i = 0; i < 16; i++) o2[i] = out[i];
        CHECK(pad_kb_roles_apply(o2, R3) == L1 && pad_kb_roles_apply(o2, L1) == R3, "%s: zoom/melee swap followed", k ? "Alternate 2" : "Modern");
        /* keycaps: the game prompts zoom on L1 -> show the r3 key (Mouse2); melee on R3 -> show the l1 key (F) */
        CHECK(pad_kb_roles_source(o2, L1) == R3 && pad_kb_roles_source(o2, R3) == L1, "%s: keycap sources", k ? "Alternate 2" : "Modern");
        CHECK(pad_kb_roles_source(o2, R1) == R1, "%s: fire keycap unchanged", k ? "Alternate 2" : "Modern");
    }
    /* Modern's other moves: use (circle key) -> Square, crouch (l2) -> Circle, grenade (r2) -> L2 */
    map_of(kz2_pad_modern, map); kz2_kb_roles(map, out);
    CHECK(out[13] == SQUARE && out[8] == CIRCLE && out[9] == L2 && out[15] == SQUARE && out[12] == TRI, "Modern use/crouch/grenade/reload/next");
    for (int i = 0; i < 16; i++) o2[i] = out[i];
    CHECK(pad_kb_roles_apply(o2, CIRCLE | L2) == (SQUARE | CIRCLE), "two keys at once");
    /* latch: Mouse2 (r3) pressed under Modern keeps L1 while held even when the table lapses; a new press after the
     * lapse is the plain button; released, the next press takes the table again */
    {
        PadKbRoleLatch l; memset(&l, 0, sizeof l);
        map_of(kz2_pad_modern, map); kz2_kb_roles(map, out);
        for (int i = 0; i < 16; i++) o2[i] = out[i];
        CHECK(pad_kb_roles_latch(&l, o2, R3) == L1, "press under the table");
        CHECK(pad_kb_roles_latch(&l, NULL, R3) == L1, "held through a lapse");
        CHECK(pad_kb_roles_latch(&l, NULL, R3 | CIRCLE) == (L1 | CIRCLE), "new press in a lapse is plain");
        CHECK(pad_kb_roles_latch(&l, NULL, 0) == 0, "released");
        CHECK(pad_kb_roles_latch(&l, o2, R3) == L1, "pressed again under the table");
    }
    /* unbound function: the key keeps its button */
    map_of(kz2_pad_original[0], map); map[16] = -1; kz2_kb_roles(map, out);
    CHECK(out[10] == L1, "unbound close combat keeps l1");
    printf(fails ? "test_kb_roles: %d FAILED\n" : "test_kb_roles: all passed\n", fails);
    return fails ? 1 : 0;
}
