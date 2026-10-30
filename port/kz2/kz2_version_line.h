/* Killzone 2 port: the version line in the main menu. ENHANCEMENT (port-only).
 *
 * The main menu shows one line in its lower right corner, in the game's own font (the page's "_Tiny" text class):
 *   "Project Pyrrhus <current>"                              or, when the launcher's check found a newer release,
 *   "Project Pyrrhus <current>  -  <newer> available"
 * (the menu font is capitals only and has no middle dot: a test run drew "0.1.4    0.1.5" with a blank gap)
 * What it says comes from version.ini, which the launcher writes before each start into the folder that holds
 * keybinds.ini (pad_kb_sibling_path, patch 2095); the game reads it once and never writes it:
 *   ASCII, CRLF or LF, ';' comment lines, one [version] section, key=value (spaces trimmed, keys any case, unknown keys
 *   and other sections ignored); current = MAJOR.MINOR.PATCH, newer = MAJOR.MINOR.PATCH (only when newer), page = its
 *   release page (never opened or shown: the game makes no connection).
 * Missing or garbled (no file, over 4 KB, no [version], current not N.N.N): current comes from the exe's own version
 * resource, else there is no line. A newer that is not N.N.N or not greater than current is ignored.
 *
 * The line is put into the main menu's page text (kz2_menu_pages.cpp) as one top-level text tag just before the page's
 * button legend: such tags carry no g id, so nothing is renumbered. The anchor must match once, else the page is left
 * as it is. Platform-free (host test tools/runtime/test_version_line.sh). */
#pragma once
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

#define KZ2_VL_MAX_FILE 4096

/* Strict MAJOR.MINOR.PATCH (digits only, each part 1-6 digits). -> 1 and v[3], or 0. */
static inline int kz2_vl_semver(const char* s, size_t n, long v[3])
{
    size_t i = 0;
    int part;
    for (part = 0; part < 3; part++) {
        size_t d = 0;
        long x = 0;
        while (i < n && s[i] >= '0' && s[i] <= '9' && d < 7) { x = x * 10 + (s[i] - '0'); i++; d++; }
        if (d == 0 || d > 6) return 0;
        v[part] = x;
        if (part < 2) { if (i >= n || s[i] != '.') return 0; i++; }
    }
    return i == n;
}

static inline int kz2_vl_cmp(const long a[3], const long b[3])
{
    int i;
    for (i = 0; i < 3; i++) if (a[i] != b[i]) return a[i] < b[i] ? -1 : 1;
    return 0;
}

static inline int kz2_vl_space(char c) { return c == ' ' || c == '\t' || c == '\r'; }

/* version.ini text -> current and newer ("" when absent or not N.N.N; a newer not above current is dropped).
 * -> 1 when the file is usable (a [version] section with a valid current), else 0 (both left ""). */
static inline int kz2_vl_parse(const char* text, size_t n, char* current, size_t ccap, char* newer, size_t ncap)
{
    size_t p = 0;
    int in_ver = 0, seen = 0;
    char cur[32] = "", nw[32] = "";
    long cv[3], nv[3];
    if (current && ccap) current[0] = 0;
    if (newer && ncap) newer[0] = 0;
    if (!text || n > KZ2_VL_MAX_FILE) return 0;
    while (p < n) {
        size_t e = p, a, b;
        while (e < n && text[e] != '\n') e++;
        a = p; b = e;
        while (a < b && kz2_vl_space(text[a])) a++;
        while (b > a && kz2_vl_space(text[b - 1])) b--;
        if (a < b && text[a] == '[') {
            in_ver = (b - a == 9 && memcmp(text + a, "[version]", 9) == 0);
            seen |= in_ver;
        } else if (in_ver && a < b && text[a] != ';' && text[a] != '#') {
            size_t eq = a, ke, v;
            while (eq < b && text[eq] != '=') eq++;
            if (eq < b) {
                char key[16];
                size_t kl, i;
                ke = eq;
                while (ke > a && kz2_vl_space(text[ke - 1])) ke--;
                v = eq + 1;
                while (v < b && kz2_vl_space(text[v])) v++;
                kl = ke - a;
                if (kl < sizeof key) {
                    for (i = 0; i < kl; i++) { char c = text[a + i]; key[i] = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }
                    key[kl] = 0;
                    if (b - v < sizeof cur) {
                        if (!strcmp(key, "current")) { memcpy(cur, text + v, b - v); cur[b - v] = 0; }
                        else if (!strcmp(key, "newer")) { memcpy(nw, text + v, b - v); nw[b - v] = 0; }
                    } else if (!strcmp(key, "current")) cur[0] = 0;
                }
            }
        }
        p = e + 1;
    }
    if (!seen || !kz2_vl_semver(cur, strlen(cur), cv)) return 0;
    if (current) snprintf(current, ccap, "%s", cur);
    if (nw[0] && kz2_vl_semver(nw, strlen(nw), nv) && kz2_vl_cmp(nv, cv) > 0 && newer) snprintf(newer, ncap, "%s", nw);
    return 1;
}

/* The line's text (UTF-8): "" when there is no current version. */
static inline void kz2_vl_text(const char* current, const char* newer, char* out, size_t cap)
{
    if (!cap) return;
    out[0] = 0;
    if (!current || !current[0]) return;
    if (newer && newer[0])
        snprintf(out, cap, "Project Pyrrhus %s  -  %s available", current, newer);   /* the font has no middle dot */
    else
        snprintf(out, cap, "Project Pyrrhus %s", current);
}

#ifdef __cplusplus
}

#include <string>

/* The main menu page with the line added before its button legend (`<_g name="ButtonLegend"`, once), or "" when the
 * anchor is not there exactly once or the text is empty. The text is escaped for an SVML text node. */
inline std::string kz2_vl_page(const std::string& page, const std::string& line)
{
    static const char anchor[] = "<_g name=\"ButtonLegend\"";
    if (line.empty()) return std::string();
    const size_t a = page.find(anchor);
    if (a == std::string::npos || page.find(anchor, a + 1) != std::string::npos) return std::string();
    std::string esc;
    for (char c : line) {
        if (c == '&') esc += "&amp;";
        else if (c == '<') esc += "&lt;";
        else if (c == '>') esc += "&gt;";
        else if (c == '"') esc += "&quot;";
        else esc += c;
    }
    /* 1280x720 page frame: the panels' right edge is x 1152, the legend starts at y 620; the line sits under it,
     * right-aligned, in the page's own "_Tiny" class (as its techyVersionNumber text). */
    const std::string tag = "<_t name=\"pcVersionLine\" c=\"_Tiny\" p=\"652,694,500,20\" ah=\"right\" av=\"bottom\" "
                            "l=\"#FFFFFF90\" >" + esc + "</_t> ";
    return page.substr(0, a) + tag + page.substr(a);
}
#endif
