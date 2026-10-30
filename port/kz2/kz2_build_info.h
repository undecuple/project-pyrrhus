/* Killzone 2 port: the build header at the top of the game log. ENHANCEMENT (port-only).
 *
 * A player's log has to say which build wrote it. The first lines of every run's stdout and session log
 * (kz2_session_log.c kz2_build_header) are:
 *   [build] Project Pyrrhus <version> (kz2.exe version resource | build-stamp.json | VERSION.txt)
 *   [build] built <time> (build-stamp.json | exe file time), patch set <id>
 *   [build] install: installed | portable | none (...)
 * Sources, first found wins:
 *  - version: the exe's own version resource (VS_FIXEDFILEINFO product version, from installer/app.rc.in), else
 *    build-stamp.json "version", else <root>/VERSION.txt, else "unknown";
 *  - built: build-stamp.json "built" (written by the installer's build step, tools/release/firstrun.py after_stamp)
 *    beside the exe, else the exe file's last-write time;
 *  - patch set: the id compiled in (KZ2_BUILD_PATCHSET, the toolkit copy's .kz2-patchset: sha256 of the patch series
 *    and the ps3recomp commit), and build-stamp.json "patchset" when that differs;
 *  - install: kz2-install.ini beside the exe or one level up (<root>/build/kz2.exe) says [install] portable = 1 ->
 *    portable (the keybinds rule, patch 2037, and tools/release/launch.py); a kz2-install.ini without it ->
 *    installed; none -> a build run where it was made.
 * Paths are never printed here; the session log's redactor runs over these lines like any other.
 *
 * The functions below are platform-free (host test tools/runtime/test_build_info.sh). */
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

static inline int kz2_bi_space(char c) { return c == ' ' || c == '\t' || c == '\r'; }

static inline int kz2_bi_ieq(const char* a, size_t n, const char* lit)
{
    size_t i;
    if (strlen(lit) != n) return 0;
    for (i = 0; i < n; i++) {
        char x = a[i], y = lit[i];
        if (x >= 'A' && x <= 'Z') x = (char)(x - 'A' + 'a');
        if (y >= 'A' && y <= 'Z') y = (char)(y - 'A' + 'a');
        if (x != y) return 0;
    }
    return 1;
}

/* kz2-install.ini text: [install] portable = 1? Same rule as patch 2037's pad_kb_ini_portable and launch.py: the
 * section name case-sensitive (configparser), the key case-insensitive, '=' or ':', portable only when the value is
 * exactly "1". */
static inline int kz2_bi_ini_portable(const char* text)
{
    const char* p = text;
    int in_install = 0;
    if (!text) return 0;
    while (*p) {
        const char* e = p;
        const char *a, *b;
        while (*e && *e != '\n') e++;
        a = p; b = e;
        while (a < b && kz2_bi_space(*a)) a++;
        while (b > a && kz2_bi_space(b[-1])) b--;
        if (a < b && *a == '[') {
            const char* r = (const char*)memchr(a, ']', (size_t)(b - a));
            in_install = r && r - a - 1 == 7 && memcmp(a + 1, "install", 7) == 0;
        } else if (in_install && a < b && *a != '#' && *a != ';') {
            const char* eq = a;
            while (eq < b && *eq != '=' && *eq != ':') eq++;
            if (eq < b) {
                const char* ke = eq;
                const char* v = eq + 1;
                while (ke > a && kz2_bi_space(ke[-1])) ke--;
                while (v < b && kz2_bi_space(*v)) v++;
                if (kz2_bi_ieq(a, (size_t)(ke - a), "portable")) return (b - v == 1 && *v == '1');
            }
        }
        p = *e ? e + 1 : e;
    }
    return 0;
}

/* The string value of a top-level key in a JSON object ("key": "value"; nested objects such as build-stamp.json's
 * "facts" are skipped, so their own "version" is never taken). Escapes \" \\ \/ are decoded, others kept as the
 * escaped character; control bytes become '?'. -> 1 and out filled, or 0 (no such key, not a string, or no room). */
static inline int kz2_bi_json_str(const char* js, const char* key, char* out, size_t n)
{
    const char* p = js;
    int depth = 0;
    size_t klen = strlen(key);
    if (!js || !n) return 0;
    while (*p) {
        char c = *p;
        if (c == '{' || c == '[') { depth++; p++; continue; }
        if (c == '}' || c == ']') { depth--; p++; continue; }
        if (c != '"') { p++; continue; }
        /* a string: find its end */
        {
            const char* s = ++p;
            const char* q;
            while (*p && *p != '"') p += (*p == '\\' && p[1]) ? 2 : 1;
            if (!*p) return 0;
            q = p++;                                  /* q = closing quote */
            if (depth != 1 || (size_t)(q - s) != klen || memcmp(s, key, klen) != 0) continue;
            while (kz2_bi_space(*p) || *p == '\n') p++;
            if (*p != ':') continue;                  /* a value that equals the key text */
            p++;
            while (kz2_bi_space(*p) || *p == '\n') p++;
            if (*p != '"') return 0;
            p++;
            {
                size_t o = 0;
                while (*p && *p != '"') {
                    char ch = *p++;
                    if (ch == '\\' && *p) ch = *p++;
                    if ((unsigned char)ch < 0x20) ch = '?';
                    if (o + 1 >= n) return 0;
                    out[o++] = ch;
                }
                if (!*p) return 0;
                out[o] = 0;
                return 1;
            }
        }
    }
    return 0;
}

/* The product version from a version resource's bytes (VS_VERSIONINFO): VS_FIXEDFILEINFO starts with the signature
 * 0xFEEF04BD, 32-bit aligned; dwProductVersionMS/LS are its 5th and 6th DWORDs. "a.b.c" (a 4th part only when it is
 * not 0). -> 1, or 0 without the signature. */
static inline int kz2_bi_fixed_version(const unsigned char* res, size_t n, char* out, size_t cap)
{
    size_t i;
    for (i = 0; i + 4 * 6 <= n; i += 4) {
        uint32_t sig = (uint32_t)res[i] | (uint32_t)res[i + 1] << 8 | (uint32_t)res[i + 2] << 16 | (uint32_t)res[i + 3] << 24;
        if (sig == 0xFEEF04BDu) {
            const unsigned char* d = res + i + 16;    /* dwProductVersionMS */
            uint32_t ms = (uint32_t)d[0] | (uint32_t)d[1] << 8 | (uint32_t)d[2] << 16 | (uint32_t)d[3] << 24;
            uint32_t ls = (uint32_t)d[4] | (uint32_t)d[5] << 8 | (uint32_t)d[6] << 16 | (uint32_t)d[7] << 24;
            int r = (ls & 0xFFFF) ? snprintf(out, cap, "%u.%u.%u.%u", ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
                                  : snprintf(out, cap, "%u.%u.%u", ms >> 16, ms & 0xFFFF, ls >> 16);
            return r > 0 && (size_t)r < cap;
        }
    }
    return 0;
}

/* VERSION.txt: one MAJOR.MINOR.PATCH line (tools/release/firstrun.py port_version). -> 1 and out, or 0. */
static inline int kz2_bi_version_txt(const char* text, char* out, size_t cap)
{
    size_t a = 0, b, i;
    int dots = 0;
    if (!text) return 0;
    while (text[a] && (kz2_bi_space(text[a]) || text[a] == '\n')) a++;
    b = a;
    while (text[b] && !kz2_bi_space(text[b]) && text[b] != '\n') b++;
    if (b == a || b - a >= cap) return 0;
    for (i = a; i < b; i++) {
        if (text[i] == '.') { if (i == a || text[i - 1] == '.') return 0; dots++; }
        else if (text[i] < '0' || text[i] > '9') return 0;
    }
    if (dots != 2 || text[b - 1] == '.') return 0;
    memcpy(out, text + a, b - a);
    out[b - a] = 0;
    return 1;
}

typedef struct {
    const char* version;      /* "" = unknown */
    const char* version_from; /* "kz2.exe version resource", "build-stamp.json", "VERSION.txt" */
    const char* built;        /* "" = unknown */
    const char* built_from;   /* "build-stamp.json", "exe file time" */
    const char* patchset;     /* compiled in; "" = unknown */
    const char* stamp_patchset; /* build-stamp.json's, "" = none */
    int install;              /* 0 none, 1 installed, 2 portable */
    const char* install_where; /* "beside the exe", "one level up" */
} kz2_build_info;

/* The three header lines (each ending in '\n') into out. -> length, or -1 when cap is too small. */
static inline int kz2_bi_format(const kz2_build_info* b, char* out, size_t cap)
{
    char ps[160];
    int r;
    const char* inst = b->install == 2 ? "portable" : b->install == 1 ? "installed" : "none";
    if (b->patchset && b->patchset[0] && b->stamp_patchset && b->stamp_patchset[0] &&
        strcmp(b->patchset, b->stamp_patchset) != 0)
        snprintf(ps, sizeof ps, "%s (build-stamp.json says %s)", b->patchset, b->stamp_patchset);
    else
        snprintf(ps, sizeof ps, "%s", (b->patchset && b->patchset[0]) ? b->patchset
                                     : (b->stamp_patchset && b->stamp_patchset[0]) ? b->stamp_patchset : "unknown");
    r = snprintf(out, cap,
                 "[build] Project Pyrrhus %s%s%s%s\n"
                 "[build] built %s%s%s%s, patch set %s\n"
                 "[build] install: %s%s%s%s\n",
                 (b->version && b->version[0]) ? b->version : "unknown",
                 (b->version && b->version[0]) ? " (" : "", (b->version && b->version[0]) ? b->version_from : "",
                 (b->version && b->version[0]) ? ")" : "",
                 (b->built && b->built[0]) ? b->built : "unknown",
                 (b->built && b->built[0]) ? " (" : "", (b->built && b->built[0]) ? b->built_from : "",
                 (b->built && b->built[0]) ? ")" : "",
                 ps, inst,
                 b->install ? " (kz2-install.ini " : " (no kz2-install.ini: a build run where it was made",
                 b->install ? b->install_where : "", ")");
    return (r < 0 || (size_t)r >= cap) ? -1 : r;
}

#ifdef __cplusplus
}
#endif
