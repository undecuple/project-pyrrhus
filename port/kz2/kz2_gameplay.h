/* Player gameplay settings (ENHANCEMENT, all off / original by default): aim_assist, crouch_toggle,
 * cover_toggle. Home: gameplay.ini beside keybinds.ini ([gameplay] section; display.ini is rewritten whole by the
 * window thread on every Alt+Enter and keybinds.ini by the capture page, so neither keeps a foreign key; this file is
 * only ever read). KZ2_AIM_ASSIST, KZ2_CROUCH_TOGGLE, KZ2_COVER_TOGGLE win for one run.
 * Pure logic (no guest memory) so tools/runtime/test_gameplay.sh tests it on the host; the guest glue (hooks on the
 * game's functions, addresses in comments) is in kz2_ppu_overrides.cpp. */
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

enum { KZ2_AIM_AUTO = 0, KZ2_AIM_ON = 1, KZ2_AIM_OFF = 2 };

typedef struct {
    int aim_assist;     /* KZ2_AIM_* (default auto) */
    int crouch_toggle;  /* 0/1 (default 0) */
    int cover_toggle;   /* 0/1 (default 0) */
} kz2_gameplay_cfg;

/* "auto"/"on"/"off" (case-insensitive; also 1/0/true/false/yes/no for on/off) -> KZ2_AIM_*; NULL, "" or anything else -> -1. */
int kz2_gp_parse_aim(const char* s);
/* "0"/"1"/"on"/"off"/"true"/"false"/"yes"/"no" -> 0/1; NULL, "" or anything else -> -1. */
int kz2_gp_parse_bool(const char* s);
/* Defaults, then the [gameplay] section of an ini text (other sections ignored; "key = value", '#'/';' comments, a bad
 * value keeps the default and is counted). Returns the number of bad values. */
int kz2_gp_ini_parse(const char* text, kz2_gameplay_cfg* c);
/* Environment values (NULL = unset) override the file; a bad value is ignored and counted. */
int kz2_gp_apply_env(kz2_gameplay_cfg* c, const char* aim, const char* crouch, const char* cover);

/* Aim assist is on? auto = on unless the look comes from a real mouse (no mouse look exists yet: look_is_mouse is 0). */
int kz2_gp_aim_on(const kz2_gameplay_cfg* c, int look_is_mouse);
/* The UpdateLook call sites (return addresses, per EBOOT) of ApplyInputModifier / the shoot-zoom assist helper. A call
 * is skipped only when the assist is off AND its return address is one of these; the other callers (follow camera,
 * mounted gun) and the sprint slowdown (the modifier pointer is never touched) are not. */
int kz2_gp_aim_skip(int aim_on, uint32_t lr, const uint32_t* sites, int nsites);

/* Cover toggle latch. The game asks "is cover held" (held(11)) once per frame at one call site; with the toggle the
 * latch replaces the held bit. begin() before the game's cover function, held() at the query, end() after it. */
typedef struct { int latch; int queried; int found; } kz2_cover_latch;
void kz2_cover_begin(kz2_cover_latch* l);
/* The value to return for the held query. A sprint or jump press clears the latch (as the crouch toggle does), a cover
 * press flips it. enabled == 0: returns orig_held and keeps no state. */
int  kz2_cover_held(kz2_cover_latch* l, int enabled, int orig_held, int pressed_cover, int pressed_sprint, int pressed_jump);
/* The cover finder's result at its call site (0 = no cover near). */
void kz2_cover_found(kz2_cover_latch* l, int found);
/* After the cover function: the latch is dropped when the finder found nothing or was not reached at all (cover not
 * allowed this frame: weapon, input disabled), so a new wall never grabs the player later. */
void kz2_cover_end(kz2_cover_latch* l);

/* The settings of this run: defaults, gameplay.ini (Windows only: beside keybinds.ini; absent is fine), then the
 * KZ2_* variables. Read once on first use; one "[gameplay]" line on stderr says what was chosen and from where. */
const kz2_gameplay_cfg* kz2_gameplay_get(void);

#ifdef __cplusplus
}
#endif
