/* Killzone 2 port: the Windows user's folders out of the game log. ENHANCEMENT (port-only), an earlier change.
 *
 * Issue #16 (v0.1.2): a player's session log, attached to a public issue, printed %APPDATA% paths with the Windows
 * user name ([display] display.ini, [keybinds] keybinds.ini), and an install under the user's own folders would put
 * the name on every [sys_fs] / [boot] / [log] path line too. Players attach these logs to public issues, so:
 *  - kz2_session_log.c fills one redactor at start from %APPDATA%, %LOCALAPPDATA% and %USERPROFILE% (the ANSI and the
 *    UTF-8 spelling) and its copy thread passes every line of stdout/stderr through kz2_redact before the log file
 *    and the original stdout get it: one place for every print, the toolkit's included (cellPad.c's [keybinds]
 *    lines, patches 2037/2038; the [CRASH] lines of patches 2030/2032, which KZ2 prints instead of writing crash
 *    files);
 *  - kz2_log_path_w (kz2_session_log.h) prints one path with the same rules where the port prints it itself
 *    (main.cpp [display]), so the line reads "%APPDATA%\Project Pyrrhus\display.ini" with or without the session log.
 * Same rule as the first-run log's redactor (tools/release/firstrun.py redactor, issue #9).
 *
 * Matching: ASCII case-insensitive ('\\' and '/' count as the same character), the longest folder first, and only
 * where the folder ends (the next byte is no name character), so a profile folder "bob" never eats "bobby\...".
 *
 * Linux and Proton (a player's log, 2026-10-29): Wine shows the Linux home folder as Z:/home/<name>, which is
 * none of the folders above (Proton's %USERPROFILE% is C:\users\steamuser), so the "[log] session log:" line and
 * every install path printed the Linux user name. kz2_redact_home finds any home folder by its shape, whatever the
 * name: [X:]/home/<name> (either slash, doubled backslashes as in an escaped string, Wine's \\?\unix\home\<name>)
 * and the %-encoded forms (%2Fhome%2F<name>, Z%3A%5Chome%5C<name>, the name itself %-encoded), and writes "<home>"
 * (the label tools/release/rpcs3_import.py uses for the same folder). It runs where no folder rule matched.
 * Platform-free inline functions: host test tools/release/test_log_redact.sh. */
#pragma once
#include <stddef.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

#define KZ2_REDACT_MAX 8
#define KZ2_REDACT_FROM 520

typedef struct {
    char from[KZ2_REDACT_FROM];   /* the folder, without a trailing separator */
    size_t n;
    const char* label;            /* "%APPDATA%", ... (static text) */
} kz2_redact_rule;

typedef struct {
    kz2_redact_rule r[KZ2_REDACT_MAX];
    int count;                    /* r[] is kept longest first */
} kz2_redactor;

static inline char kz2_redact_fold(char c)
{
    if (c == '/') return '\\';
    return (c >= 'A' && c <= 'Z') ? (char)(c - 'A' + 'a') : c;
}

/* A byte that continues a folder name: after a match, one of these means the match was only part of a longer name. */
static inline int kz2_redact_namechar(unsigned char c)
{
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-' ||
           c == '.' || c >= 0x80;
}

/* Add a folder (trailing separators dropped). Ignored: empty or too short to be a user folder ("C:\", 3 bytes), too
 * long, the same folder twice, or a full table. -> 1 when added. */
static inline int kz2_redact_add(kz2_redactor* rd, const char* folder, const char* label)
{
    size_t n = folder ? strlen(folder) : 0;
    int i, j;
    while (n && (folder[n - 1] == '\\' || folder[n - 1] == '/')) n--;
    if (n < 4 || n >= KZ2_REDACT_FROM || rd->count >= KZ2_REDACT_MAX) return 0;
    for (i = 0; i < rd->count; i++) {
        if (rd->r[i].n != n) continue;
        for (j = 0; j < (int)n && kz2_redact_fold(rd->r[i].from[j]) == kz2_redact_fold(folder[j]); j++) {}
        if (j == (int)n) return 0;
    }
    for (i = rd->count; i > 0 && rd->r[i - 1].n < n; i--) rd->r[i] = rd->r[i - 1];   /* longest first */
    memcpy(rd->r[i].from, folder, n);
    rd->r[i].from[n] = 0;
    rd->r[i].n = n;
    rd->r[i].label = label;
    rd->count++;
    return 1;
}

#define KZ2_REDACT_HOME_LABEL "<home>"

/* A path separator at in[i]: '/' or '\\' (1 byte, a doubled '\\' as 2), or with enc, "%2F" / "%5C" (3 bytes, either
 * case). -> its length, or 0. */
static inline size_t kz2_redact_sep(const char* in, size_t n, size_t i, int enc)
{
    if (i >= n) return 0;
    if (!enc) {
        if (in[i] == '/') return 1;
        if (in[i] == '\\') return (i + 1 < n && in[i + 1] == '\\') ? 2 : 1;
        return 0;
    }
    if (i + 3 <= n && in[i] == '%' &&
        ((in[i + 1] == '2' && (in[i + 2] == 'F' || in[i + 2] == 'f')) ||
         (in[i + 1] == '5' && (in[i + 2] == 'C' || in[i + 2] == 'c'))))
        return 3;
    return 0;
}

static inline int kz2_redact_hex(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

/* A Linux home folder starting at in[i] (shapes in the header comment). -> its length (drive and name included), or 0.
 * The match needs a boundary before it (start of text, a byte that is no name character, or Wine's "unix" prefix)
 * so "/x/myhome/..." or "abc/home/..." in the middle of a name is left alone. */
static inline size_t kz2_redact_home(const char* in, size_t n, size_t i)
{
    static const char home[] = "home";
    int enc;
    for (enc = 0; enc < 2; enc++) {
        size_t j = i, s, k, name0;
        if (i > 0 && kz2_redact_namechar((unsigned char)in[i - 1]) &&
            !(i >= 4 && kz2_redact_fold(in[i - 4]) == 'u' && kz2_redact_fold(in[i - 3]) == 'n' &&
              kz2_redact_fold(in[i - 2]) == 'i' && kz2_redact_fold(in[i - 1]) == 'x') &&
            !(enc && i >= 3 && in[i - 3] == '%'))
            continue;
        /* optional drive: "Z:" or "Z%3A" */
        if (j + 1 < n && ((in[j] >= 'A' && in[j] <= 'Z') || (in[j] >= 'a' && in[j] <= 'z'))) {
            if (!enc && in[j + 1] == ':') j += 2;
            else if (enc && j + 4 <= n && in[j + 1] == '%' && in[j + 2] == '3' && (in[j + 3] == 'A' || in[j + 3] == 'a'))
                j += 4;
        }
        if (!(s = kz2_redact_sep(in, n, j, enc))) continue;
        j += s;
        for (k = 0; k < 4 && j + k < n && kz2_redact_fold(in[j + k]) == home[k]; k++) {}
        if (k < 4) continue;
        j += 4;
        if (!(s = kz2_redact_sep(in, n, j, enc))) continue;
        j += s;
        name0 = j;
        while (j < n) {
            if (kz2_redact_namechar((unsigned char)in[j]) && in[j] != '%') { j++; continue; }
            if (enc && in[j] == '%' && j + 3 <= n && kz2_redact_hex(in[j + 1]) && kz2_redact_hex(in[j + 2]) &&
                !kz2_redact_sep(in, n, j, 1)) { j += 3; continue; }
            break;
        }
        if (j == name0) continue;
        return j - i;
    }
    return 0;
}

/* in[0..n) -> out (at most cap-1 bytes, NUL-terminated) with every folder replaced by its label. -> bytes written.
 * A label can be longer than its folder (%USERPROFILE% for C:\Users\ab): give cap >= 2*n + 1 for no truncation. */
static inline size_t kz2_redact(const kz2_redactor* rd, const char* in, size_t n, char* out, size_t cap)
{
    size_t i = 0, o = 0;
    if (!cap) return 0;
    while (i < n && o + 1 < cap) {
        int hit = -1, k;
        for (k = 0; k < rd->count && hit < 0; k++) {
            const kz2_redact_rule* r = &rd->r[k];
            size_t j;
            if (r->n > n - i) continue;
            for (j = 0; j < r->n && kz2_redact_fold(in[i + j]) == kz2_redact_fold(r->from[j]); j++) {}
            if (j == r->n && (i + j == n || !kz2_redact_namechar((unsigned char)in[i + j]))) hit = k;
        }
        if (hit >= 0) {
            const char* l = rd->r[hit].label;
            while (*l && o + 1 < cap) out[o++] = *l++;
            i += rd->r[hit].n;
        } else if ((k = (int)kz2_redact_home(in, n, i)) > 0) {
            const char* l = KZ2_REDACT_HOME_LABEL;
            while (*l && o + 1 < cap) out[o++] = *l++;
            i += (size_t)k;
        } else {
            out[o++] = in[i++];
        }
    }
    out[o] = 0;
    return o;
}

/* The end of the last complete line in buf[0..n) (one past its '\n'), or 0: the copy thread redacts whole lines and
 * keeps the rest until more arrives, so a folder split over two pipe reads is still found. */
static inline size_t kz2_redact_line_end(const char* buf, size_t n)
{
    while (n && buf[n - 1] != '\n') n--;
    return n;
}

#ifdef __cplusplus
}
#endif
