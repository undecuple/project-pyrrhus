/* KZ2_PAD_LAYOUT=original|modern: the port's optional "Modern" pad preset, applied through
 * the game's own player profile (PlayerProfile button map), so input and the game's button prompts follow it.
 * Pure logic (no guest memory) so tools/runtime/test_pad_layout.sh can test it on the host; the guest glue (hooks of
 * SetFunctionButton 0x826B0 and the two profile loaders 0x79BC8 / 0x7BA60) is in kz2_ppu_overrides.cpp. */
#pragma once
#include <stdint.h>
#include "kz2_pad_layout_table.h"
#ifdef __cplusplus
extern "C" {
#endif

enum { KZ2_PAD_ORIGINAL = 0, KZ2_PAD_MODERN = 1 };

/* "original" / "modern" (case-insensitive) -> mode; NULL or "" -> original; anything else -> -1 (caller: original). */
int kz2_pad_layout_parse(const char* s);
/* KZ2_PAD_LAYOUT read once (first call); logs the choice once on stderr ("[kz2-pad]"). */
int kz2_pad_layout_mode(void);
/* Map slot `func` is one the hook may write: ids 0..19 set by the presets, except 3 (not in them) and 18 (Suicide:
 * SetFunctionButton refuses it, profile word obj+0xAC = map slot 18 is the loader's status word). */
int kz2_pad_layout_slot_ok(int32_t func);
/* SetFunctionButton(profile, func, button): the button to store. Original: `button` unchanged. Modern: the Modern
 * button for the scripted ids, `button` for every other id. */
int32_t kz2_pad_layout_set_button(int mode, int32_t func, int32_t button);
/* 1 if the writable slots of map[0..19] hold exactly the Modern buttons (only the port writes that combination: no
 * shipped preset has Use on Square). */
int kz2_pad_layout_is_modern(const int32_t map[KZ2_PAD_NFUNC]);
/* After a profile load: Modern -> the writable slots get the Modern buttons; original -> a map that is exactly Modern
 * (saved while Modern was chosen) gets the preset of the profile's scheme index back (0..5; anything else: Standard 1),
 * any other map is left alone. Returns the number of slots changed (0 = nothing written). */
int kz2_pad_layout_fix_map(int mode, int32_t map[KZ2_PAD_NFUNC], uint32_t scheme);

/* Keys keep their action (patch 6050): keybinds.ini binds a key to a pad button and names the button's Standard 1 action
 * (l1 close combat, r3 zoom, ...). From the live profile map (EButton per function, map[0..19]) the CELL_PAD_CTRL mask
 * each key bit (1 << i, i = 0..15) must become so the key does that action: R1 fire (0), R3 zoom (2), L3 sprint (4),
 * Cross jump (5), Circle use (6), R2 grenade (8), Square reload (9), L2 crouch (10), Triangle next weapon (13),
 * L1 close combat (16), Up objective (19); Start, Select and the other d-pad bits stay. A function that is unbound or
 * not on a pad button keeps the key's own button. Returns the number of keys whose button changes. */
int kz2_kb_roles(const int32_t map[KZ2_PAD_NFUNC], uint16_t out[16]);
/* EButton id (0..15) -> CELL_PAD_CTRL mask (DIGITAL1 | DIGITAL2 << 8); 0 for anything else. */
uint16_t kz2_ebutton_mask(int32_t button);

#ifdef __cplusplus
}
#endif
