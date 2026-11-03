/* Killzone 2 port: port rows on the game's own Display page (ENHANCEMENT).
 *
 * One small table (kz2_port_rows below) names every port setting that has a row in the front end's DISPLAY list:
 * its label, kind (a range shown as the game's own slider, or a choice cycled by CROSS), values, default, ini file +
 * section + key, and the number of decimals it is shown and saved with. Everything else is made from that table:
 *   - display_rows(page): the edit of a served options page (mainmenu.jsp, campaign/options.jsp,
 *     online/game/options.jsp: each carries the shared `optionsmenuscript` and the `listDisplaySettings` list).
 *     The rows go between DISPLAY HINTS and SET TO DEFAULT in the game's own markup (`_i` + `_r` slider like the
 *     AUDIO rows, or `_i` + `_t` value), the g ids from SET TO DEFAULT on move up by the row count, the list grows by
 *     the rows' height; the script gets one Pc(cmd) bridge function (PlayerProfile SetTimeZone/GetTimeZone, the
 *     Keyboard page's bridge, prefix "pc:"), PcInit() from InitOptionSettings, PcReset() from ResetDisplaySettings,
 *     and one setter per row from the slider's SetOnChange or the item's link, so a change applies at once.
 *   - command(): the host side of "pc:" commands ("get ID", "show ID", "set ID VALUE", "cycle ID", "reset");
 *     port/kz2/kz2_port_settings.cpp applies the change live and writes the ini key.
 *   - ini_get / ini_set: one "key = value" in one [section] of an ini text, every other line kept as it was
 *     (display.ini also holds mode/scaling/filter, written by Alt+Enter through the same ini_set).
 * Labels: the English text in the table. ASSUMPTION: the other 17 page languages show the English label too (the game's
 * own rows are translated in each page's text; ours have no translation yet: label_for() is where one would go).
 * Pure (no guest memory, no files), so tools/runtime/test_port_rows.sh tests it on the host. */
#pragma once
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <vector>

#include "kz2_menu_text.h"   /* Anchor, find_all, once, renumber, check */

namespace kz2rows {

enum Kind { RANGE = 0, CHOICE = 1 };

struct Row {
    const char* id;        /* command id, e.g. "fov" */
    const char* tag;       /* markup names: item<tag>, slider<tag>, text<tag>Value */
    const char* label;     /* English label, upper case like the game's rows */
    Kind kind;
    double min, max, step, def;   /* CHOICE: index 0..n-1 */
    int decimals;          /* RANGE: shown and saved with this many decimals */
    const char* const* ini_values;   /* CHOICE: what the ini holds */
    const char* const* shown;        /* CHOICE: what the row shows */
    int nchoices;
    const char* file;      /* "display.ini" */
    const char* section;   /* "display" */
    const char* key;
};

static const char* const UPSCALE_INI[2] = { "off", "fsr1" };
static const char* const UPSCALE_SHOWN[2] = { "OFF", "FSR 1" };

/* fov: vertical degrees of the first-person view without zoom; the game's own value is 45 (frustum setter 0x3D9640,
 * the Camera's FieldOfView; kz2_ppu_overrides.cpp). upscale + sharpness: rsx_upscale (patch 6051, KZ3 2145). */
static const Row kz2_port_rows[] = {
    { "fov", "PcFov", "FIELD OF VIEW", RANGE, 45.0, 75.0, 1.0, 45.0, 0, nullptr, nullptr, 0, "display.ini", "display", "fov" },
    { "upscale", "PcUpscale", "UPSCALING", CHOICE, 0.0, 1.0, 1.0, 0.0, 0, UPSCALE_INI, UPSCALE_SHOWN, 2, "display.ini", "display", "upscale" },
    { "sharpness", "PcSharpness", "SHARPNESS", RANGE, 0.0, 2.0, 0.1, 0.2, 1, nullptr, nullptr, 0, "display.ini", "display", "sharpness" },
};
static const int NROWS = (int)(sizeof kz2_port_rows / sizeof kz2_port_rows[0]);

inline int find(const std::string& id)
{
    for (int i = 0; i < NROWS; i++) if (id == kz2_port_rows[i].id) return i;
    return -1;
}

/* the label a page language shows (see the ASSUMPTION above) */
inline const char* label_for(const Row& r, const std::string& lang) { (void)lang; return r.label; }

/* clamp to [min, max] and round to the step grid from min; NaN -> default */
inline double snap(const Row& r, double v)
{
    if (v != v) return r.def;
    if (v < r.min) v = r.min;
    if (v > r.max) v = r.max;
    if (r.kind == CHOICE) return floor(v + 0.5);
    const double k = floor((v - r.min) / r.step + 0.5);
    double s = r.min + k * r.step;
    if (s > r.max) s = r.max;
    const double p = pow(10.0, r.decimals);
    return floor(s * p + 0.5) / p;
}

inline std::string num(double v, int decimals)
{
    char b[48];
    snprintf(b, sizeof b, "%.*f", decimals, v);
    return b;
}

inline std::string shown(const Row& r, double v)
{
    v = snap(r, v);
    if (r.kind == CHOICE) return r.shown[(int)v];
    return num(v, r.decimals);
}

inline std::string ini_value(const Row& r, double v)
{
    v = snap(r, v);
    if (r.kind == CHOICE) return r.ini_values[(int)v];
    return num(v, r.decimals);
}

inline bool ieq(const std::string& a, const char* b)
{
    if (a.size() != strlen(b)) return false;
    for (size_t i = 0; i < a.size(); i++) {
        char x = a[i], y = b[i];
        if (x >= 'A' && x <= 'Z') x = (char)(x + 32);
        if (y >= 'A' && y <= 'Z') y = (char)(y + 32);
        if (x != y) return false;
    }
    return true;
}

inline std::string trim(const std::string& s)
{
    size_t a = 0, b = s.size();
    while (a < b && kz2mt::is_space(s[a])) a++;
    while (b > a && kz2mt::is_space(s[b - 1])) b--;
    return s.substr(a, b - a);
}

/* an ini value (or a command argument) -> the row's value; false = not a value of this row (the caller keeps the old one) */
inline bool parse(const Row& r, const std::string& text, double* out)
{
    const std::string s = trim(text);
    if (s.empty()) return false;
    if (r.kind == CHOICE) {
        for (int i = 0; i < r.nchoices; i++)
            if (ieq(s, r.ini_values[i]) || ieq(s, r.shown[i])) { *out = i; return true; }
        return false;
    }
    char* end = nullptr;
    const double v = strtod(s.c_str(), &end);
    if (!end || *end || v != v) return false;
    *out = snap(r, v);
    return true;
}

/* ---------------------------------------------------------------- ini text: one key of one section */
/* Lines are split on \n (a \r before it stays with the line's text and is kept on rewrite). Section names and keys
 * compare case-insensitively; ';' and '#' start comment lines. */
inline std::vector<std::string> lines_of(const std::string& t)
{
    std::vector<std::string> L;
    size_t s = 0;
    for (size_t i = 0; i <= t.size(); i++)
        if (i == t.size() || t[i] == '\n') { if (i > s || i < t.size()) L.push_back(t.substr(s, i - s)); s = i + 1; }
    return L;
}

/* "[name]" -> name, else "" (not a header) */
inline bool header_of(const std::string& line, std::string* name)
{
    const std::string s = trim(line);
    if (s.size() < 2 || s[0] != '[' || s[s.size() - 1] != ']') return false;
    *name = trim(s.substr(1, s.size() - 2));
    return true;
}

inline bool key_of(const std::string& line, std::string* key, std::string* value)
{
    const std::string s = trim(line);
    if (s.empty() || s[0] == ';' || s[0] == '#' || s[0] == '[') return false;
    const size_t eq = s.find('=');
    if (eq == std::string::npos) return false;
    *key = trim(s.substr(0, eq));
    *value = trim(s.substr(eq + 1));
    return true;
}

/* The value of section/key (the last one if repeated), or false. Keys before any [section] belong to no section. */
inline bool ini_get(const std::string& text, const char* section, const char* key, std::string* value)
{
    bool in = false, found = false;
    std::string name, k, v;
    for (const std::string& line : lines_of(text)) {
        if (header_of(line, &name)) { in = ieq(name, section); continue; }
        if (in && key_of(line, &k, &v) && ieq(k, key)) { *value = v; found = true; }
    }
    return found;
}

/* text with section/key = value: the key's line(s) in that section replaced (the first one; later repeats dropped),
 * else a new line after the section's last key line, else a new section at the end. Every other line is kept. */
inline std::string ini_set(const std::string& text, const char* section, const char* key, const std::string& value)
{
    const bool crlf = text.find("\r\n") != std::string::npos;
    const std::string eol = crlf ? "\r" : "";
    std::vector<std::string> L = lines_of(text);
    if (!L.empty() && L.back().empty() && !text.empty() && text[text.size() - 1] == '\n') L.pop_back();
    const std::string line = std::string(key) + " = " + value + eol;
    bool in = false, done = false;
    long sec_last = -1;
    std::vector<std::string> out;
    std::string name, k, v;
    for (const std::string& l : L) {
        if (header_of(l, &name)) {
            if (in && !done && sec_last >= 0) { out.insert(out.begin() + sec_last + 1, line); done = true; }
            in = ieq(name, section);
            if (in) sec_last = (long)out.size();
            out.push_back(l);
            continue;
        }
        if (in && key_of(l, &k, &v)) {
            if (ieq(k, key)) { if (!done) { out.push_back(line); done = true; } continue; }
            out.push_back(l);
            sec_last = (long)out.size() - 1;
            continue;
        }
        out.push_back(l);
    }
    if (!done && in && sec_last >= 0) { out.insert(out.begin() + sec_last + 1, line); done = true; }
    if (!done) {
        if (!out.empty() && !trim(out.back()).empty()) out.push_back(eol);
        out.push_back("[" + std::string(section) + "]" + eol);
        out.push_back(line);
    }
    std::string o;
    for (const std::string& l : out) o += l + "\n";
    return o;
}

/* ---------------------------------------------------------------- the host side of the page's "pc:" commands */
struct State {
    double v[sizeof kz2_port_rows / sizeof kz2_port_rows[0]];
};

inline void defaults(State* s) { for (int i = 0; i < NROWS; i++) s->v[i] = kz2_port_rows[i].def; }

/* "get ID" -> the value as the slider takes it (choice: its index); "show ID" -> the row's text; "set ID V" -> the
 * new text; "cycle ID" (choice) -> the next choice's text; "reset" -> "ok". *changed gets the indices of the rows whose
 * value changed (the caller applies and saves those). Unknown -> "?". */
inline std::string command(State* s, const std::string& cmd, std::vector<int>* changed)
{
    changed->clear();
    std::vector<std::string> w;
    {
        size_t i = 0;
        while (i < cmd.size()) {
            while (i < cmd.size() && cmd[i] == ' ') i++;
            size_t j = i;
            while (j < cmd.size() && cmd[j] != ' ') j++;
            if (j > i) w.push_back(cmd.substr(i, j - i));
            i = j;
        }
    }
    if (w.size() == 1 && w[0] == "reset") {
        for (int i = 0; i < NROWS; i++) if (s->v[i] != kz2_port_rows[i].def) { s->v[i] = kz2_port_rows[i].def; changed->push_back(i); }
        return "ok";
    }
    if (w.size() < 2) return "?";
    const int i = find(w[1]);
    if (i < 0) return "?";
    const Row& r = kz2_port_rows[i];
    if (w[0] == "get" && w.size() == 2) return num(snap(r, s->v[i]), r.kind == CHOICE ? 0 : r.decimals);
    if (w[0] == "show" && w.size() == 2) return shown(r, s->v[i]);
    if (w[0] == "set" && w.size() == 3) {
        double v;
        if (parse(r, w[2], &v) && v != s->v[i]) { s->v[i] = v; changed->push_back(i); }
        return shown(r, s->v[i]);
    }
    if (w[0] == "cycle" && w.size() == 2 && r.kind == CHOICE) {
        s->v[i] = (double)(((int)s->v[i] + 1) % r.nchoices);
        changed->push_back(i);
        return shown(r, s->v[i]);
    }
    return "?";
}

/* ---------------------------------------------------------------- the page edit */
/* p="a,b,c,d" of the tag starting at `at` (exactly 4 fields, empty allowed): field values (-1 = empty) and the span
 * of the attribute's value */
inline bool p_fields(const std::string& t, size_t at, long f[4], size_t* vs, size_t* ve)
{
    const size_t end = t.find('>', at);
    const size_t p = t.find(" p=\"", at);
    if (p == std::string::npos || end == std::string::npos || p > end) return false;
    *vs = p + 4;
    *ve = t.find('"', *vs);
    if (*ve == std::string::npos || *ve > end) return false;
    const std::string v = t.substr(*vs, *ve - *vs);
    int n = 0;
    size_t s = 0;
    for (size_t i = 0; i <= v.size(); i++)
        if (i == v.size() || v[i] == ',') {
            if (n >= 4) return false;
            const std::string x = v.substr(s, i - s);
            f[n++] = x.empty() ? -1 : atol(x.c_str());
            s = i + 1;
        }
    return n == 4;
}

inline long g_of(const std::string& t, size_t at)
{
    const size_t end = t.find('>', at);
    const size_t g = t.find(" g=\"", at);
    if (g == std::string::npos || g > end) return -1;
    return atol(t.c_str() + g + 4);
}

inline std::string p_text(const long f[4])
{
    std::string o;
    for (int i = 0; i < 4; i++) { if (i) o += ","; if (f[i] >= 0) o += std::to_string(f[i]); }
    return o;
}

inline std::string row_markup(const Row& r, long y, long h, long g, const std::string& lang)
{
    const std::string Y = std::to_string(y), H = std::to_string(h), G = std::to_string(g);
    const std::string label = kz2mt::attr(label_for(r, lang));
    if (r.kind == RANGE) {
        return "<_i name=\"item" + std::string(r.tag) + "\" c=\"_Medium\" p=\"," + Y + ",620," + H + "\" g=\"" + G + "\" t=\"" + label +
               "\" /> <_r name=\"slider" + r.tag + "\" c=\"_SliderMedium\" p=\"250,,220,\" a=\"true\" d=\"LEFT_BUTTON\" i=\"RIGHT_BUTTON\" m=\"" +
               num(r.min, r.decimals) + "\" s=\"" + num(r.step, r.decimals) + "\" u=\"" + num(r.def, r.decimals) + "\" x=\"" +
               num(r.max, r.decimals) + "\" /> <_t name=\"text" + r.tag + "Value\" c=\"_Medium\" p=\"484,,120,\" a=\"true\" >" +
               kz2mt::attr(shown(r, r.def)) + "</_t> <_i: name=\"!\" g=\"" + G + "\" /> ";
    }
    return "<_i name=\"item" + std::string(r.tag) + "\" c=\"_Medium\" p=\"," + Y + ",620," + H + "\" g=\"" + G +
           "\" h=\"static://script.optionsmenuscript.PcCycle_" + r.id + "\" t=\"" + label + "\" /> <_t name=\"text" + r.tag +
           "Value\" c=\"_Medium\" p=\"250,,220,\" a=\"true\" >" + kz2mt::attr(shown(r, r.def)) + "</_t> <_i: name=\"!\" g=\"" + G + "\" /> ";
}

inline std::string script_functions(const std::string& nl)
{
    std::string s;
    auto a = [&](const std::string& l) { s += l + nl; };
    a("function Pc(cmd)"); a("gPlayerProfile:SetTimeZone(\"pc:\" .. cmd)"); a("return gPlayerProfile:GetTimeZone()"); a("end");
    a("function PcInit()");
    for (int i = 0; i < NROWS; i++) {
        const Row& r = kz2_port_rows[i];
        if (r.kind == RANGE) a(std::string("gBrowser:GetTagByName(\"slider") + r.tag + "\"):SetCurrentValue(Pc(\"get " + r.id + "\") + 0)");
        a(std::string("gBrowser:GetTagByName(\"text") + r.tag + "Value\"):SetValue(Pc(\"show " + r.id + "\"))");
    }
    a("end");
    a("function PcReset()"); a("Pc(\"reset\")"); a("PcInit()"); a("end");
    for (int i = 0; i < NROWS; i++) {
        const Row& r = kz2_port_rows[i];
        if (r.kind == RANGE) {
            a(std::string("function PcSet_") + r.id + "()");
            a(std::string("gBrowser:GetTagByName(\"text") + r.tag + "Value\"):SetValue(Pc(\"set " + r.id + " \" .. gBrowser:GetTagByName(\"slider" +
              r.tag + "\"):GetCurrentValue()))");
            a("end");
        } else {
            a(std::string("function PcCycle_") + r.id + "()");
            a(std::string("gBrowser:GetTagByName(\"text") + r.tag + "Value\"):SetValue(Pc(\"cycle " + r.id + "\"))");
            a("end");
        }
    }
    return s;
}

/* insert `what` right after the unique `anchor` + its line end */
inline std::string after_line(const std::string& t, const std::string& anchor, const std::string& what, const char* name)
{
    const size_t a = kz2mt::once(t, anchor, name);
    size_t e = t.find('\n', a);
    if (e == std::string::npos) throw kz2mt::Anchor(std::string(name) + ": no line end");
    return t.substr(0, e + 1) + what + t.substr(e + 1);
}

inline std::string display_rows(const std::string& text, const std::string& lang = "en")
{
    std::string t = text;
    if (t.find("name=\"itemPcFov\"") != std::string::npos) throw kz2mt::Anchor("page already has the port rows");
    const std::string nl = t.find("\r\n") != std::string::npos ? "\r\n" : "\n";
    const std::string list_a = "<_l name=\"listDisplaySettings\" ", reset_a = "<_i name=\"itemResetDisplaySettings\" ";
    const size_t L0 = kz2mt::once(t, list_a, "listDisplaySettings");
    const size_t R0 = kz2mt::once(t, reset_a, "itemResetDisplaySettings");
    if (R0 < L0) throw kz2mt::Anchor("SET TO DEFAULT before the Display list");
    long lf[4], rf[4];
    size_t lvs, lve, rvs, rve;
    if (!p_fields(t, L0, lf, &lvs, &lve) || lf[3] <= 0) throw kz2mt::Anchor("listDisplaySettings p=");
    if (!p_fields(t, R0, rf, &rvs, &rve) || rf[1] <= 0 || rf[3] <= 0) throw kz2mt::Anchor("itemResetDisplaySettings p=");
    const long G = g_of(t, R0);
    if (G <= 0) throw kz2mt::Anchor("itemResetDisplaySettings g=");
    const long H = rf[3], Y = rf[1];
    /* the free row above SET TO DEFAULT (the game leaves one at y = Y - H) takes the first port row */
    bool gap = true;
    for (size_t p : kz2mt::find_all(t.substr(L0, R0 - L0), "<_i name=\"")) {
        long f[4]; size_t a, b;
        if (p_fields(t, L0 + p, f, &a, &b) && f[1] == Y - H) gap = false;
    }
    const long y0 = gap ? Y - H : Y;
    const long newY = y0 + H * NROWS + H;   /* keep one free row above SET TO DEFAULT */
    const long grow = newY - Y;
    /* numbers first (renumber moves text), then the inserts from the back */
    t = kz2mt::renumber(t, G, NROWS);
    {
        const size_t R = kz2mt::once(t, reset_a, "itemResetDisplaySettings");
        if (!p_fields(t, R, rf, &rvs, &rve)) throw kz2mt::Anchor("itemResetDisplaySettings p=");
        rf[1] = newY;
        t = t.substr(0, rvs) + p_text(rf) + t.substr(rve);
        std::string rows;
        for (int i = 0; i < NROWS; i++) rows += row_markup(kz2_port_rows[i], y0 + H * i, H, G + i, lang);
        t = t.substr(0, R) + rows + t.substr(R);
        const size_t L = kz2mt::once(t, list_a, "listDisplaySettings");
        if (!p_fields(t, L, lf, &lvs, &lve)) throw kz2mt::Anchor("listDisplaySettings p=");
        lf[3] += grow;
        t = t.substr(0, lvs) + p_text(lf) + t.substr(lve);
    }
    {
        std::string on;
        for (int i = 0; i < NROWS; i++)
            if (kz2_port_rows[i].kind == RANGE)
                on += std::string("gBrowser:GetTagByName(\"slider") + kz2_port_rows[i].tag + "\"):SetOnChange(\"optionsmenuscript.PcSet_" +
                      kz2_port_rows[i].id + "\")" + nl;
        t = after_line(t, "gSliderMusicVolume:SetOnChange(\"optionsmenuscript.UpdateVolume(sliderMusicVolume)\")", on, "music slider SetOnChange");
        t = after_line(t, "function InitOptionSettings()", "PcInit()" + nl, "InitOptionSettings");
        t = after_line(t, "function ResetDisplaySettings()", "PcReset()" + nl, "ResetDisplaySettings");
        const size_t f = kz2mt::once(t, "function ToggleCheckBox(checkbox)", "ToggleCheckBox");
        t = t.substr(0, f) + script_functions(nl) + t.substr(f);
    }
    const std::vector<std::string> bad = kz2mt::check(t);
    if (!bad.empty()) throw kz2mt::Anchor("port rows: " + bad[0]);
    return t;
}

}  // namespace kz2rows
