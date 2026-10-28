/* Killzone 2 port: hand-play boot helpers. ENHANCEMENT (port-only).
 *
 *  - kz2_console_open: KZ2_CONSOLE=1 opens a console window for kz2.exe, which is a GUI-subsystem program (no console
 *    by default; idea and code shape from Project Helghast port/kz3/main.cpp kz3_logging_start, KZ3_CONSOLE).
 *  - kz2_session_log_start: every run writes <exe dir>/logs/kz2-YYYYMMDD-HHMMSS.log (the newest KZ2_LOG_KEEP kept).
 *    stdout and stderr (the CRT descriptors and the Win32 std handles) are pointed at a pipe; a thread copies what
 *    arrives to the log file and to the original stdout, so a redirected stdout (tools/proton-test.sh, kz2-check.sh)
 *    and the console still get every line, in write order. KZ2_LOG_FILE=0 turns the file off (no pipe either).
 *    KZ3 has a full logger for this (kz3_log.c: levels, tags, crash files; patches 2030/2032 call into it under
 *    KZ3_LOG_REDIRECT_STDIO); KZ2 does not build that path, so this tee keeps the existing output byte for byte.
 *  - kz2_session_log_flush: waits until the pipe is drained into the file (exit paths, crash filter chain).
 *
 * The inline functions below are the platform-free parts (host test: tools/runtime/test_session_log.sh). */
#pragma once
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

#define KZ2_LOG_KEEP 10            /* newest kz2-*.log files kept in <exe dir>/logs, the new one included */
#define KZ2_LOG_PREFIX "kz2-"

/* "kz2-YYYYMMDD-HHMMSS.log" (seq > 1: "kz2-YYYYMMDD-HHMMSS-<seq>.log", two runs in one second). -> length, or -1. */
static inline int kz2_log_file_name(char* out, size_t n, int year, int mon, int day, int hour, int min, int sec, int seq)
{
    int r;
    if (seq > 1)
        r = snprintf(out, n, KZ2_LOG_PREFIX "%04d%02d%02d-%02d%02d%02d-%d.log", year, mon, day, hour, min, sec, seq);
    else
        r = snprintf(out, n, KZ2_LOG_PREFIX "%04d%02d%02d-%02d%02d%02d.log", year, mon, day, hour, min, sec);
    return (r < 0 || (size_t)r >= n) ? -1 : r;
}

/* Is name one of ours ("kz2-" + a digit ... ".log")? Other files in logs/ are never pruned. */
static inline int kz2_log_is_ours(const char* name)
{
    const size_t n = strlen(name), p = sizeof KZ2_LOG_PREFIX - 1;
    return n > p + 4 && !strncmp(name, KZ2_LOG_PREFIX, p) && name[p] >= '0' && name[p] <= '9' &&
           !strcmp(name + n - 4, ".log");
}

/* Pruning: names[0..count) are our log names (any order). Before a new file is made, everything but the newest
 * keep-1 has to go. The names sort by time as text ("-<seq>" after the same second sorts after it, '-' < '.').
 * Marks del[i] = 1 for the ones to delete; returns how many. */
static inline int kz2_log_prune_select(const char* const* names, int count, int keep, int* del)
{
    int i, j, ndel = 0;
    for (i = 0; i < count; i++) {
        int newer = 0;   /* how many names sort after names[i] */
        for (j = 0; j < count; j++)
            if (j != i && (strcmp(names[j], names[i]) > 0 || (strcmp(names[j], names[i]) == 0 && j > i))) newer++;
        del[i] = newer >= keep - 1;
        ndel += del[i];
    }
    return ndel;
}

/* The EBOOT to load (no launch option needed): argv[1] when given (an explicit argument wins), else
 * <exe dir>/PS3_GAME/USRDIR/EBOOT.elf, a dump folder with kz2.exe dropped into it (Steam: a non-Steam game pointing at
 * kz2.exe). KZ3 does the same last step (Project Helghast port/kz3/main.cpp kz3_boot_inputs); its kz3.ini and built-in
 * EBOOT steps are not here. -> 1 = from the command line, 0 = beside the exe, -1 = the path did not fit. */
static inline int kz2_eboot_path(const char* exe_dir, int argc, char** argv, char* out, size_t n)
{
    int r;
    if (argc >= 2 && argv[1] && argv[1][0]) {
        r = snprintf(out, n, "%s", argv[1]);
        return (r < 0 || (size_t)r >= n) ? -1 : 1;
    }
    r = snprintf(out, n, "%s/PS3_GAME/USRDIR/EBOOT.elf", exe_dir && *exe_dir ? exe_dir : ".");
    return (r < 0 || (size_t)r >= n) ? -1 : 0;
}

/* Windows-only parts (port/kz2/kz2_session_log.c); no-ops elsewhere. */
const char* kz2_exe_dir(void);                 /* the exe's folder (ANSI code page, '/' separators), "." if unknown */
int  kz2_console_open(void);                   /* KZ2_CONSOLE=1: 1 = a console was opened */
int  kz2_session_log_start(void);              /* 1 = logging to a file (path: kz2_session_log_path) */
const char* kz2_session_log_path(void);        /* "" when no file */
void kz2_session_log_flush(unsigned timeout_ms);
/* Buffered stdout/stderr (upstream since ps3recomp v0.18.0 #524): ppu_run's ps3_stdio_init()
 * buffers both streams (64 KB each) and flushes them every PS3_STDIO_FLUSH_MS (50 ms) and on exit, crash and abort.
 * This maps the port's switches onto it: KZ2_LOG_UNBUFFERED=1 -> PS3_STDIO_UNBUFFERED=1 (both streams unbuffered),
 * KZ2_LOG_FLUSH_MS -> PS3_STDIO_FLUSH_MS; and flushes the session log on abort. Returns 1 when buffering will be on.
 * Why buffering: MinGW's printf (__mingw_pformat) hands an unbuffered FILE one fputc per character, so every log
 * character was its own write() into the log pipe; with ~1,300 lines/s in a level that cost about 15 us per
 * character on the emitting guest thread. Output before ppu_run uses the CRT's default buffering. */
int  kz2_stdio_buffer_start(void);
#define KZ2_LOG_FLUSH_MS_DEFAULT 50
/* Parse KZ2_LOG_FLUSH_MS: NULL or not a positive number -> def; clamped to [lo, hi]. */
static inline unsigned kz2_log_env_uint(const char* v, unsigned def, unsigned lo, unsigned hi)
{
    unsigned long x = 0;
    if (!v || !*v) return def;
    for (const char* p = v; *p; p++) {
        if (*p < '0' || *p > '9') return def;
        x = x * 10 + (unsigned long)(*p - '0');
        if (x > hi) return hi;
    }
    if (x == 0) return def;
    return x < lo ? lo : (unsigned)x;
}

#ifdef __cplusplus
}
#endif
