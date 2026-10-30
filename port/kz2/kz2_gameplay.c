/* See kz2_gameplay.h. Pure logic, no guest memory. */
#include "kz2_gameplay.h"
#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <wchar.h>
extern int pad_kb_sibling_path(const wchar_t* name, wchar_t* out, size_t n);   /* cellPad.c (patch 2095) */
#endif

static int ieq(const char* a, const char* b)
{
    for (; *a && *b; a++, b++) if (tolower((unsigned char)*a) != tolower((unsigned char)*b)) return 0;
    return *a == 0 && *b == 0;
}

int kz2_gp_parse_bool(const char* s)
{
    if (!s || !*s) return -1;
    if (ieq(s, "1") || ieq(s, "on") || ieq(s, "true") || ieq(s, "yes")) return 1;
    if (ieq(s, "0") || ieq(s, "off") || ieq(s, "false") || ieq(s, "no")) return 0;
    return -1;
}

int kz2_gp_parse_aim(const char* s)
{
    if (!s || !*s) return -1;
    if (ieq(s, "auto")) return KZ2_AIM_AUTO;
    const int b = kz2_gp_parse_bool(s);
    return b < 0 ? -1 : (b ? KZ2_AIM_ON : KZ2_AIM_OFF);
}

/* A positive finite number up to 1000, else -1. */
static float kz2_gp_parse_pos(const char* s)
{
    if (!s || !*s) return -1.0f;
    char* e;
    const double d = strtod(s, &e);
    while (*e == ' ' || *e == '\t') e++;
    if (*e || !(d > 0.0) || d > 1000.0 || !isfinite(d)) return -1.0f;
    return (float)d;
}

/* One [mouse] key; returns 1 for a bad value (the default stays), 0 otherwise (unknown keys are ignored). */
static int kz2_gp_mouse_key(kz2_gameplay_cfg* c, const char* k, const char* v)
{
    int x; float f;
    if (ieq(k, "mouse_look")) { x = kz2_gp_parse_bool(v); if (x < 0) return 1; c->mouse_look = x; }
    else if (ieq(k, "mouse_invert_y")) { x = kz2_gp_parse_bool(v); if (x < 0) return 1; c->mouse_invert = x; }
    else if (ieq(k, "mouse_sensitivity")) { f = kz2_gp_parse_pos(v); if (f < 0) return 1; c->mouse_sens = f; }
    else if (ieq(k, "mouse_zoom_sensitivity")) { f = kz2_gp_parse_pos(v); if (f < 0) return 1; c->mouse_zoom = f; }
    else if (ieq(k, "mouse_yaw")) { f = kz2_gp_parse_pos(v); if (f < 0) return 1; c->mouse_yaw = f; }
    return 0;
}

int kz2_gp_ini_parse(const char* text, kz2_gameplay_cfg* c)
{
    c->aim_assist = KZ2_AIM_AUTO; c->crouch_toggle = 0; c->cover_toggle = 0;
    c->mouse_look = 1; c->mouse_sens = KZ2_MOUSE_SENS_DEF; c->mouse_zoom = 1.0f; c->mouse_yaw = KZ2_MOUSE_YAW_DEF;
    c->mouse_invert = 0;
    int bad = 0, in = 0;   /* in: 1 = [gameplay], 2 = [mouse] */
    const char* p = text ? text : "";
    while (*p) {
        char line[160]; size_t n = 0;
        while (*p && *p != '\n') { if (n < sizeof line - 1) line[n++] = *p; p++; }
        if (*p == '\n') p++;
        line[n] = 0;
        char* s = line;
        while (*s == ' ' || *s == '\t' || *s == '\r') s++;
        char* e = s + strlen(s);
        while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r')) *--e = 0;
        if (!*s || *s == '#' || *s == ';') continue;
        if (*s == '[') {
            char* r = strchr(s, ']');
            in = 0;
            if (r) { *r = 0; char* nm = s + 1; while (*nm == ' ') nm++; e = nm + strlen(nm);
                     while (e > nm && e[-1] == ' ') *--e = 0;
                     in = ieq(nm, "gameplay") ? 1 : ieq(nm, "mouse") ? 2 : 0; }
            continue;
        }
        if (!in) continue;
        char* eq = strchr(s, '=');
        if (!eq) continue;
        *eq = 0;
        char* k = s; char* v = eq + 1;
        e = k + strlen(k); while (e > k && (e[-1] == ' ' || e[-1] == '\t')) *--e = 0;
        while (*v == ' ' || *v == '\t') v++;
        if (in == 2) { bad += kz2_gp_mouse_key(c, k, v); continue; }
        if (ieq(k, "aim_assist")) { const int x = kz2_gp_parse_aim(v); if (x < 0) bad++; else c->aim_assist = x; }
        else if (ieq(k, "crouch_toggle")) { const int x = kz2_gp_parse_bool(v); if (x < 0) bad++; else c->crouch_toggle = x; }
        else if (ieq(k, "cover_toggle")) { const int x = kz2_gp_parse_bool(v); if (x < 0) bad++; else c->cover_toggle = x; }
    }
    return bad;
}

int kz2_gp_apply_env(kz2_gameplay_cfg* c, const char* aim, const char* crouch, const char* cover)
{
    int bad = 0, x;
    if (aim && *aim) { x = kz2_gp_parse_aim(aim); if (x < 0) bad++; else c->aim_assist = x; }
    if (crouch && *crouch) { x = kz2_gp_parse_bool(crouch); if (x < 0) bad++; else c->crouch_toggle = x; }
    if (cover && *cover) { x = kz2_gp_parse_bool(cover); if (x < 0) bad++; else c->cover_toggle = x; }
    return bad;
}

int kz2_gp_apply_mouse_env(kz2_gameplay_cfg* c, const char* look, const char* sens, const char* zoom, const char* yaw,
                           const char* invert)
{
    int bad = 0;
    if (look && *look) bad += kz2_gp_mouse_key(c, "mouse_look", look);
    if (sens && *sens) bad += kz2_gp_mouse_key(c, "mouse_sensitivity", sens);
    if (zoom && *zoom) bad += kz2_gp_mouse_key(c, "mouse_zoom_sensitivity", zoom);
    if (yaw && *yaw) bad += kz2_gp_mouse_key(c, "mouse_yaw", yaw);
    if (invert && *invert) bad += kz2_gp_mouse_key(c, "mouse_invert_y", invert);
    return bad;
}

float kz2_mouse_rad_per_count(const kz2_gameplay_cfg* c)
{
    return c->mouse_sens * c->mouse_yaw * 0.017453292519943295f;
}

void kz2_mouse_angles(const kz2_gameplay_cfg* c, int dx, int dy, int zoomed, float* dyaw, float* dpitch)
{
    const float k = kz2_mouse_rad_per_count(c) * (zoomed ? c->mouse_zoom : 1.0f);
    *dyaw = (float)dx * k;
    *dpitch = -(float)dy * k * (c->mouse_invert ? -1.0f : 1.0f);
}

float kz2_mouse_rate_for(float dyaw, float turn_deg_s, float dt)
{
    const float kdt = turn_deg_s * 0.017453292519943295f * dt;
    if (!isfinite(kdt) || fabsf(kdt) < 1e-7f) return 0.0f;
    return dyaw / kdt;
}

float kz2_mouse_pitch(float pitch, float dpitch, float pmin, float pmax)
{
    float p = pitch + dpitch;
    if (isfinite(pmin) && isfinite(pmax) && pmin <= pmax) {
        if (p < pmin) p = pmin;
        if (p > pmax) p = pmax;
    }
    return p;
}

void kz2_look_note(kz2_look_src* s, float stick_x, float stick_y, float dead, int mouse_moved)
{
    if (mouse_moved) s->mouse = 1;
    else if (fabsf(stick_x) > dead || fabsf(stick_y) > dead) s->mouse = 0;
}

int kz2_gp_aim_on(const kz2_gameplay_cfg* c, int look_is_mouse)
{
    if (c->aim_assist == KZ2_AIM_ON) return 1;
    if (c->aim_assist == KZ2_AIM_OFF) return 0;
    return look_is_mouse ? 0 : 1;
}

int kz2_gp_aim_skip(int aim_on, uint32_t lr, const uint32_t* sites, int nsites)
{
    if (aim_on) return 0;
    for (int i = 0; i < nsites; i++) if (sites[i] == lr) return 1;
    return 0;
}

void kz2_cover_begin(kz2_cover_latch* l) { l->queried = 0; l->found = 0; }

int kz2_cover_held(kz2_cover_latch* l, int enabled, int orig_held, int pressed_cover, int pressed_sprint, int pressed_jump)
{
    if (!enabled) { l->latch = 0; return orig_held; }
    l->queried = 1;
    if (pressed_sprint || pressed_jump) l->latch = 0;
    else if (pressed_cover) l->latch = !l->latch;
    return l->latch;
}

void kz2_cover_found(kz2_cover_latch* l, int found) { l->found = found ? 1 : 0; }

void kz2_cover_end(kz2_cover_latch* l)
{
    if (l->latch && (!l->queried || !l->found)) l->latch = 0;
}

const kz2_gameplay_cfg* kz2_gameplay_get(void)
{
    static kz2_gameplay_cfg cfg;
    static int done;
    if (done) return &cfg;
    char t[2048]; t[0] = 0;
    int file = 0, bad;
#ifdef _WIN32
    wchar_t p[1100];
    if (pad_kb_sibling_path(L"gameplay.ini", p, 1100)) {
        FILE* f = _wfopen(p, L"rb");
        if (f) { const size_t n = fread(t, 1, sizeof t - 1, f); fclose(f); t[n] = 0; file = 1; }
    }
#endif
    bad = kz2_gp_ini_parse(t, &cfg);
    const int benv = kz2_gp_apply_env(&cfg, getenv("KZ2_AIM_ASSIST"), getenv("KZ2_CROUCH_TOGGLE"), getenv("KZ2_COVER_TOGGLE")) +
                     kz2_gp_apply_mouse_env(&cfg, getenv("KZ2_MOUSE_LOOK"), getenv("KZ2_MOUSE_SENS"), getenv("KZ2_MOUSE_ZOOM_SENS"),
                                            getenv("KZ2_MOUSE_YAW"), getenv("KZ2_MOUSE_INVERT"));
    static const char* const an[3] = { "auto", "on", "off" };
    fprintf(stderr, "[gameplay] aim_assist %s, crouch_toggle %d, cover_toggle %d, mouse_look %d (sensitivity %.3g x %.4g deg/count,"
            " zoom x%.3g, invert_y %d) (gameplay.ini %s; %d bad value(s) ignored)\n",
            an[cfg.aim_assist], cfg.crouch_toggle, cfg.cover_toggle, cfg.mouse_look, cfg.mouse_sens, cfg.mouse_yaw,
            cfg.mouse_zoom, cfg.mouse_invert, file ? "read" : "not there", bad + benv);
    done = 1;
    return &cfg;
}
