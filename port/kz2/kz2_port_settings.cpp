/* Killzone 2 port: the settings behind the Display page's port rows (ENHANCEMENT).
 *
 * The rows are the table in kz2_port_rows.h (field of view, upscaling, sharpness). This file holds their values for
 * the process, reads them once at start (display.ini [display] beside keybinds.ini, then the environment), applies
 * each one live and writes a changed key back to display.ini (every other line of the file kept: kz2rows::ini_set).
 *   fov        -> kz2_fov_set (kz2_ppu_overrides.cpp: the first-person frustum's FOV at the Camera site 0x66F638)
 *   upscale,
 *   sharpness  -> rsx_upscale_live_set (patch 6051, from KZ3 patch 2145: FSR 1 at present, off = no pass)
 *   vsync      -> rsx_live_draw_set_vsync (patch 6054, from KZ3 patch 2103: the Present interval, tearing when off)
 * Environment, for one run (never saved by itself; a change on the page still saves): KZ2_FOV=<vertical degrees>,
 * RSX_UPSCALE=fsr1|none, RSX_UPSCALE_SHARPNESS=0..2, KZ2_VSYNC=on|off.
 * The page talks to it through kz2_menu_pages.cpp's bridge ("pc:<cmd>", kz2_port_settings_cmd); without the menu
 * feature (KZ2_MENU_PAGES=0) the values still load and apply. */
#include <mutex>
#include <string>
#include <vector>

#include "kz2_port_rows.h"

extern "C" {
void kz2_fov_set(double deg);                              /* kz2_ppu_overrides.cpp */
void rsx_upscale_live_set(int backend, float sharpness);   /* libs/video/rsx_upscale.c (patch 6051) */
void rsx_live_draw_set_vsync(int on);                      /* libs/video/rsx_live_draw.c (patch 6054) */
#ifdef _WIN32
int pad_kb_sibling_path(const wchar_t* name, wchar_t* out, size_t n);   /* cellPad.c (patch 2095) */
const char* kz2_log_path_w(const wchar_t* path, char* out, size_t n);   /* kz2_session_log.c */
#endif
}

namespace {

std::mutex g_mu;
kz2rows::State g_st;
bool g_loaded = false;

int row(const char* id) { return kz2rows::find(id); }

void apply(int i)
{
    const std::string id = kz2rows::kz2_port_rows[i].id;
    if (id == "fov") kz2_fov_set(g_st.v[i]);
    else if (id == "vsync") rsx_live_draw_set_vsync(g_st.v[i] >= 0.5 ? 1 : 0);
    else if (id == "upscale" || id == "sharpness")
        rsx_upscale_live_set(g_st.v[row("upscale")] >= 0.5 ? 1 : 0, (float)g_st.v[row("sharpness")]);   /* 1 = RSX_UPSCALE_FSR1 */
    /* skip_intro is saved now and consumed once at the next boot. */
}

std::string read_file(const char* name, std::string* shown)
{
    std::string t;
#ifdef _WIN32
    wchar_t p[1100];
    char s[1200];
    if (!pad_kb_sibling_path(std::wstring(name, name + strlen(name)).c_str(), p, 1100)) { *shown = "(no data folder)"; return t; }
    *shown = kz2_log_path_w(p, s, sizeof s);
    if (FILE* f = _wfopen(p, L"rb")) {
        char buf[4096];
        size_t n;
        while ((n = fread(buf, 1, sizeof buf, f)) > 0 && t.size() < (1u << 20)) t.append(buf, n);
        fclose(f);
    }
#else
    (void)name; *shown = "(host build: no file)";
#endif
    return t;
}

bool write_file(const char* name, const std::string& t)
{
#ifdef _WIN32
    wchar_t p[1100];
    if (!pad_kb_sibling_path(std::wstring(name, name + strlen(name)).c_str(), p, 1100)) return false;
    FILE* f = _wfopen(p, L"wb");
    const bool ok = f && fwrite(t.data(), 1, t.size(), f) == t.size();
    if (f) fclose(f);
    return ok;
#else
    (void)name; (void)t;
    return false;
#endif
}

void load_locked(void)
{
    if (g_loaded) return;
    g_loaded = true;
    kz2rows::defaults(&g_st);
    std::string shown;
    const std::string ini = read_file("display.ini", &shown);
    int bad = 0;
    for (int i = 0; i < kz2rows::NROWS; i++) {
        const kz2rows::Row& r = kz2rows::kz2_port_rows[i];
        std::string v;
        double d;
        if (kz2rows::ini_get(ini, r.section, r.key, &v)) { if (kz2rows::parse(r, v, &d)) g_st.v[i] = d; else bad++; }
    }
    std::string env;
    struct { const char* var; const char* id; } envs[] = { { "KZ2_FOV", "fov" }, { "RSX_UPSCALE", "upscale" }, { "RSX_UPSCALE_SHARPNESS", "sharpness" },
                                                    { "KZ2_VSYNC", "vsync" }, { "KZ2_SKIP_INTRO", "skip_intro" } };
    for (auto& e : envs) {
        const char* s = getenv(e.var);
        if (!s || !*s) continue;
        const int i = row(e.id);
        double d;
        std::string sv = s;
        if (!strcmp(e.id, "skip_intro") && (sv == "0" || sv == "1")) sv = sv == "1" ? "on" : "off";
        if (!strcmp(e.id, "upscale") && kz2rows::ieq(sv, "none")) sv = "off";
        if (kz2rows::parse(kz2rows::kz2_port_rows[i], sv, &d)) { g_st.v[i] = d; env += std::string(" ") + e.var; }
        else bad++;
    }
    for (int i = 0; i < kz2rows::NROWS; i++) apply(i);
    std::string line;
    for (int i = 0; i < kz2rows::NROWS; i++)
        line += std::string(i ? ", " : "") + kz2rows::kz2_port_rows[i].key + " " + kz2rows::ini_value(kz2rows::kz2_port_rows[i], g_st.v[i]);
    fprintf(stderr, "[port-rows] %s: %s%s%s%s\n", shown.c_str(), line.c_str(), env.empty() ? "" : " (environment:", env.c_str(),
            env.empty() ? "" : ")");
    if (bad) fprintf(stderr, "[port-rows] %d bad value(s) ignored (defaults kept)\n", bad);
}

}  // namespace

/* Once, before the guest runs (main.cpp, after the display settings). Also safe to call again. */
extern "C" void kz2_port_settings_load(void)
{
    std::lock_guard<std::mutex> lk(g_mu);
    load_locked();
}

extern "C" int kz2_skip_intro_enabled(void)
{
    std::lock_guard<std::mutex> lk(g_mu);
    load_locked();
    return g_st.v[row("skip_intro")] >= 0.5 ? 1 : 0;
}

/* The page's "pc:<cmd>" (kz2_menu_pages.cpp). The reply goes back through GetTimeZone. */
extern "C" int kz2_port_settings_cmd(const char* cmd, char* out, size_t n)
{
    std::lock_guard<std::mutex> lk(g_mu);
    load_locked();
    std::vector<int> changed;
    const std::string reply = kz2rows::command(&g_st, cmd ? cmd : "", &changed);
    snprintf(out, n, "%s", reply.c_str());
    if (changed.empty()) return 1;
    for (int i : changed) apply(i);
    std::string shown;
    std::string t = read_file("display.ini", &shown);
    std::string what;
    for (int i : changed) {
        const kz2rows::Row& r = kz2rows::kz2_port_rows[i];
        t = kz2rows::ini_set(t, r.section, r.key, kz2rows::ini_value(r, g_st.v[i]));
        what += std::string(what.empty() ? "" : ", ") + r.key + " = " + kz2rows::ini_value(r, g_st.v[i]);
    }
    const bool ok = write_file("display.ini", t);
    fprintf(stderr, "[port-rows] %s applied, %s %s\n", what.c_str(), shown.c_str(), ok ? "saved" : "NOT saved");
    return 1;
}

/* display.ini's mode/scaling/filter (main.cpp's Alt+Enter save, patch 2095) through the same key-wise rewrite, so the
 * port rows' keys survive a mode change. Returns 1 when written. */
extern "C" int kz2_display_ini_set3(const char* mode, const char* scaling, const char* filter)
{
    std::lock_guard<std::mutex> lk(g_mu);
    std::string shown;
    std::string t = read_file("display.ini", &shown);
    if (t.empty())
        t = "# Project Pyrrhus display settings (Alt+Enter toggles the mode; the Display page's port rows set fov, upscale, sharpness, vsync).\n"
            "# mode = windowed | borderless | fullscreen, scaling = fit | stretch, filter = bilinear | nearest, fov = 45..75 (vertical\n"
            "# degrees, 45 = the game's own), upscale = off | fsr1, sharpness = 0..2, vsync = on | off,\n"
            "# skip_intro = off | on (next start). KZ2_SKIP_INTRO=0|1 overrides this for one run. KZ2_DISPLAY,\n"
            "# KZ2_DISPLAY_SCALING, KZ2_DISPLAY_FILTER, KZ2_FOV, RSX_UPSCALE, RSX_UPSCALE_SHARPNESS, KZ2_VSYNC override them for\n"
            "# one run.\n";
    t = kz2rows::ini_set(t, "display", "mode", mode);
    t = kz2rows::ini_set(t, "display", "scaling", scaling);
    t = kz2rows::ini_set(t, "display", "filter", filter);
    return write_file("display.ini", t) ? 1 : 0;
}
