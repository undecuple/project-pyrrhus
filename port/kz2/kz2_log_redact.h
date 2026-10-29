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
