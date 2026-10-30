/* Killzone 2 port: console switch and session log file (kz2_session_log.h has the rules). ENHANCEMENT (port-only). */
#include "kz2_session_log.h"
#include "kz2_log_redact.h"
#include "kz2_build_info.h"

#include <stdlib.h>

#ifndef _WIN32
const char* kz2_exe_dir(void) { return "."; }
int  kz2_console_open(void) { return 0; }
int  kz2_session_log_start(void) { return 0; }
const char* kz2_session_log_path(void) { return ""; }
void kz2_build_header(void) {}
int  kz2_exe_version(char* out, size_t n) { if (n) out[0] = 0; return 0; }
void kz2_session_log_flush(unsigned timeout_ms) { (void)timeout_ms; fflush(stdout); fflush(stderr); }
const char* kz2_log_path_w(const wchar_t* path, char* out, size_t n)
{
    if (n && snprintf(out, n, "%ls", path) < 0) out[0] = 0;
    return out;
}
int  kz2_stdio_buffer_start(void) { return 0; }
#else

#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include <signal.h>

static char s_exe_dir[1024];
static char s_log_path[1200];
static wchar_t s_log_dir_w[1100];
static HANDLE s_pipe_r = NULL, s_file = INVALID_HANDLE_VALUE, s_orig_out = INVALID_HANDLE_VALUE;
static volatile LONG s_in_read;      /* the copy thread waits in ReadFile: everything read so far is written */
static LPTOP_LEVEL_EXCEPTION_FILTER s_prev_filter;
static volatile LONG s_filter_set;

const char* kz2_exe_dir(void)
{
    if (!s_exe_dir[0]) {
        wchar_t w[1024];
        DWORD n = GetModuleFileNameW(NULL, w, 1024);
        snprintf(s_exe_dir, sizeof s_exe_dir, ".");
        if (n && n < 1024) {
            while (n && w[n - 1] != L'\\' && w[n - 1] != L'/') n--;   /* strip the exe name */
            if (n > 1) {
                w[n - 1] = 0;
                /* ppu_load_elf and the VFS open files with the ANSI API, so the ANSI code page (as KZ3's s_exe_dir). */
                if (!WideCharToMultiByte(CP_ACP, 0, w, -1, s_exe_dir, (int)sizeof s_exe_dir, NULL, NULL))
                    snprintf(s_exe_dir, sizeof s_exe_dir, ".");
                for (char* p = s_exe_dir; *p; p++) if (*p == '\\') *p = '/';
                wcsncpy(s_log_dir_w, w, 1080);
                s_log_dir_w[1080] = 0;
                wcscat(s_log_dir_w, L"\\logs");
            }
        }
    }
    return s_exe_dir;
}

/* From Project Helghast port/kz3/main.cpp kz3_logging_start (KZ3_CONSOLE): a console only on request. */
int kz2_console_open(void)
{
    const char* c = getenv("KZ2_CONSOLE");
    FILE* f;
    if (!(c && c[0] == '1') || GetConsoleWindow() || !AllocConsole()) return 0;
    f = freopen("CONOUT$", "w", stdout);
    f = freopen("CONOUT$", "w", stderr);
    (void)f;
    return 1;
}

const char* kz2_session_log_path(void) { return s_log_path; }

/* <dir>\<name> as text (at most max bytes), or NULL. */
static char* kz2_read_small(const wchar_t* dir, const wchar_t* name, DWORD max)
{
    wchar_t p[1200];
    HANDLE h;
    DWORD sz, got = 0;
    char* t;
    _snwprintf(p, 1200, L"%ls\\%ls", dir, name);
    p[1199] = 0;
    h = CreateFileW(p, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return NULL;
    sz = GetFileSize(h, NULL);
    if (sz == INVALID_FILE_SIZE || sz > max) { CloseHandle(h); return NULL; }
    t = (char*)malloc(sz + 1);
    if (t && !ReadFile(h, t, sz, &got, NULL)) got = 0;
    CloseHandle(h);
    if (t) t[got] = 0;
    return t;
}

/* The product version in kz2.exe's own version resource (installer/app.rc.in; a developer build has none). */
int kz2_exe_version(char* out, size_t n)
{
    HRSRC r = FindResourceW(NULL, MAKEINTRESOURCEW(1), MAKEINTRESOURCEW(16) /* RT_VERSION */);
    HGLOBAL g = r ? LoadResource(NULL, r) : NULL;
    const unsigned char* d = g ? (const unsigned char*)LockResource(g) : NULL;
    if (n) out[0] = 0;
    return d ? kz2_bi_fixed_version(d, SizeofResource(NULL, r), out, n) : 0;
}

/* The [build] lines (kz2_build_info.h), made once. */
static char s_bi_text[900];
static void kz2_build_text(void)
{
    static LONG done;
    wchar_t dir[1024], up[1024];
    DWORD n;
    char ver[64] = "", built[64] = "", sps[160] = "", text[900];
    char* stamp;
    kz2_build_info b;
    if (InterlockedExchange(&done, 1)) return;   /* ASSUMPTION: one caller at a time (start-up, single thread) */
    memset(&b, 0, sizeof b);
    n = GetModuleFileNameW(NULL, dir, 1024);
    if (!n || n >= 1024) dir[0] = 0;
    else { wchar_t* sl = wcsrchr(dir, L'\\'); if (sl) *sl = 0; }
    wcscpy(up, dir);
    { wchar_t* sl = wcsrchr(up, L'\\'); if (sl) *sl = 0; else up[0] = 0; }

    /* version: the exe's own version resource first */
    if (kz2_exe_version(ver, sizeof ver)) b.version_from = "kz2.exe version resource";
    stamp = dir[0] ? kz2_read_small(dir, L"build-stamp.json", 4u << 20) : NULL;
    if (!ver[0] && kz2_bi_json_str(stamp, "version", ver, sizeof ver)) b.version_from = "build-stamp.json";
    if (!ver[0]) {
        char* t = dir[0] ? kz2_read_small(dir, L"VERSION.txt", 256) : NULL;
        if (!t && up[0]) t = kz2_read_small(up, L"VERSION.txt", 256);
        if (kz2_bi_version_txt(t, ver, sizeof ver)) b.version_from = "VERSION.txt";
        free(t);
    }
#ifdef KZ2_BUILD_VERSION
    if (!ver[0]) { snprintf(ver, sizeof ver, "%s", KZ2_BUILD_VERSION); b.version_from = "source tree installer/VERSION"; }
#endif
    b.version = ver;

    /* built: the build step's stamp, else the exe's own file time (the link) */
    if (kz2_bi_json_str(stamp, "built", built, sizeof built)) b.built_from = "build-stamp.json";
    else {
        wchar_t exe[1024];
        WIN32_FILE_ATTRIBUTE_DATA fa;
        FILETIME lt;
        SYSTEMTIME st;
        n = GetModuleFileNameW(NULL, exe, 1024);
        if (n && n < 1024 && GetFileAttributesExW(exe, GetFileExInfoStandard, &fa) &&
            FileTimeToLocalFileTime(&fa.ftLastWriteTime, &lt) && FileTimeToSystemTime(&lt, &st)) {
            snprintf(built, sizeof built, "%04u-%02u-%02uT%02u:%02u:%02u", st.wYear, st.wMonth, st.wDay, st.wHour,
                     st.wMinute, st.wSecond);
            b.built_from = "exe file time";
        }
    }
    b.built = built;
#ifdef KZ2_BUILD_PATCHSET
    b.patchset = KZ2_BUILD_PATCHSET;
#endif
    if (kz2_bi_json_str(stamp, "patchset", sps, sizeof sps)) b.stamp_patchset = sps;
    free(stamp);

    /* install kind: kz2-install.ini beside the exe, then one level up (the keybinds rule, patch 2037) */
    {
        const wchar_t* where[2] = { dir, up };
        const char* name[2] = { "beside the exe", "one level up" };
        int i, found = -1;
        for (i = 0; i < 2; i++) {
            char* t = where[i][0] ? kz2_read_small(where[i], L"kz2-install.ini", 1u << 16) : NULL;
            if (t && kz2_bi_ini_portable(t)) { b.install = 2; b.install_where = name[i]; free(t); break; }
            if (t && found < 0) found = i;
            free(t);
        }
        if (!b.install && found >= 0) { b.install = 1; b.install_where = name[found]; }
    }
    if (kz2_bi_format(&b, text, sizeof text) > 0) memcpy(s_bi_text, text, strlen(text) + 1);
}

/* Printed on stdout once, before anything else: from a constructor that runs ahead of the other static initialisers
 * (the native SPU job table prints its lines from those), so the header is the first text of stdout too. The session
 * log file gets the same lines as its first lines (kz2_session_log_start writes them into the new file). */
void kz2_build_header(void)
{
    static LONG printed;
    if (InterlockedExchange(&printed, 1)) return;
    kz2_build_text();
    fputs(s_bi_text, stdout);
    fflush(stdout);
}
__attribute__((constructor(101))) static void kz2_build_header_early(void) { kz2_build_header(); }

static void kz2_log_prune(void)
{
    wchar_t pat[1200];
    WIN32_FIND_DATAW fd;
    char* names[256];
    int del[256], count = 0, i;
    HANDLE h;
    _snwprintf(pat, 1200, L"%ls\\" L"kz2-*.log", s_log_dir_w);
    pat[1199] = 0;
    h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        char a[300];
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        if (!WideCharToMultiByte(CP_UTF8, 0, fd.cFileName, -1, a, (int)sizeof a, NULL, NULL)) continue;
        if (!kz2_log_is_ours(a) || count >= 256) continue;
        names[count] = _strdup(a);
        if (names[count]) count++;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    kz2_log_prune_select((const char* const*)names, count, KZ2_LOG_KEEP, del);
    for (i = 0; i < count; i++) {
        if (del[i]) {
            wchar_t p[1200], wn[300];
            MultiByteToWideChar(CP_UTF8, 0, names[i], -1, wn, 300);
            _snwprintf(p, 1200, L"%ls\\%ls", s_log_dir_w, wn);
            p[1199] = 0;
            DeleteFileW(p);
        }
        free(names[i]);
    }
}

/* Issue #16 (logs attached to public issues): the user's folders, replaced in every log line (kz2_log_redact.h). Filled once from
 * the environment, in both spellings the prints can use (the ANSI code page: the runtime's %s paths; UTF-8). */
static kz2_redactor s_redact;
static volatile LONG s_redact_init;

static void kz2_redact_env(const wchar_t* var, const char* label)
{
    wchar_t w[KZ2_REDACT_FROM];
    char a[KZ2_REDACT_FROM];
    DWORD n = GetEnvironmentVariableW(var, w, KZ2_REDACT_FROM);
    if (!n || n >= KZ2_REDACT_FROM) return;
    if (WideCharToMultiByte(CP_ACP, 0, w, -1, a, (int)sizeof a, NULL, NULL)) kz2_redact_add(&s_redact, a, label);
    if (WideCharToMultiByte(CP_UTF8, 0, w, -1, a, (int)sizeof a, NULL, NULL)) kz2_redact_add(&s_redact, a, label);
}

static void kz2_redact_init(void)
{
    if (InterlockedCompareExchange(&s_redact_init, 1, 0) != 0) {   /* 1 = being filled by another thread, 2 = ready */
        while (s_redact_init != 2) Sleep(0);
        return;
    }
    kz2_redact_env(L"APPDATA", "%APPDATA%");
    kz2_redact_env(L"LOCALAPPDATA", "%LOCALAPPDATA%");
    kz2_redact_env(L"USERPROFILE", "%USERPROFILE%");
    InterlockedExchange(&s_redact_init, 2);
}

const char* kz2_log_path_w(const wchar_t* path, char* out, size_t n)
{
    char a[1200];
    if (!n) return out;
    kz2_redact_init();
    if (!WideCharToMultiByte(CP_ACP, 0, path, -1, a, (int)sizeof a, NULL, NULL)) a[0] = 0;
    kz2_redact(&s_redact, a, strlen(a), out, n);
    return out;
}

static void kz2_log_put(const char* p, size_t n)
{
    static char red[2 * (16384 + 4096) + 1];
    DWORD put;
    size_t m = kz2_redact(&s_redact, p, n, red, sizeof red);
    WriteFile(s_file, red, (DWORD)m, &put, NULL);
    if (s_orig_out != INVALID_HANDLE_VALUE) WriteFile(s_orig_out, red, (DWORD)m, &put, NULL);
}

/* The copy thread: pipe -> log file (and the original stdout, if there was one), whole lines through the redactor.
 * The text after the last newline waits for the next read while more arrives within 50 ms and it is under 4 KB; then
 * it is written too, so nothing stays held while the game waits (kz2_session_log_flush, a crash). */
static DWORD WINAPI kz2_log_copy(LPVOID unused)
{
    static char buf[4096 + 16384];
    size_t have = 0;
    (void)unused;
    for (;;) {
        DWORD got = 0, avail = 0;
        BOOL ok;
        size_t end;
        InterlockedExchange(&s_in_read, 1);
        ok = ReadFile(s_pipe_r, buf + have, 16384, &got, NULL);
        InterlockedExchange(&s_in_read, 0);
        if (!ok || !got) break;
        have += got;
        end = kz2_redact_line_end(buf, have);
        if (end) {
            kz2_log_put(buf, end);
            memmove(buf, buf + end, have - end);
            have -= end;
        }
        if (have && have < 4096) {
            /* An unbuffered writer (a DLL's own C runtime: Wine's openvr line in kz2-r33-new1) can send one line in
             * several writes; the rest of the line comes within milliseconds. Wait up to 50 ms for it. */
            for (int i = 0; i < 10; i++) {
                if (!PeekNamedPipe(s_pipe_r, NULL, 0, NULL, &avail, NULL) || avail) break;
                Sleep(5);
            }
            if (avail) continue;      /* more is there: read it into the same line */
        }
        if (have) {
            kz2_log_put(buf, have);
            have = 0;
        }
    }
    if (have) kz2_log_put(buf, have);
    return 0;
}

void kz2_session_log_flush(unsigned timeout_ms)
{
    ULONGLONG t0 = GetTickCount64();
    fflush(stdout);
    fflush(stderr);
    if (!s_pipe_r) return;
    for (;;) {
        DWORD avail = 0;
        if (!PeekNamedPipe(s_pipe_r, NULL, 0, NULL, &avail, NULL)) break;
        if (avail == 0 && s_in_read) break;   /* nothing left and the copier is back in ReadFile */
        if (GetTickCount64() - t0 >= timeout_ms) break;
        Sleep(1);
    }
    FlushFileBuffers(s_file);
}

static void kz2_log_atexit(void) { kz2_session_log_flush(1000); }

/* The runtime's crash filter (ppu_crash_report, set by ppu_run) prints its [CRASH] lines and returns
 * EXCEPTION_CONTINUE_SEARCH, which ends the process: chain behind it so those lines reach the file first. */
static LONG WINAPI kz2_log_crash_filter(EXCEPTION_POINTERS* ep)
{
    LONG r = s_prev_filter ? s_prev_filter(ep) : EXCEPTION_CONTINUE_SEARCH;
    kz2_session_log_flush(2000);
    return r;
}

/* ppu_run sets its filter on the main thread after this module starts; take the top spot once it has (polls 120 s). */
static DWORD WINAPI kz2_log_filter_chain(LPVOID unused)
{
    (void)unused;
    for (int i = 0; i < 240; i++) {
        /* None set yet: ours stays (flush only) until ppu_run replaces it; the next round then chains behind that.
         * Never put an older value back: that could undo a filter set in between. */
        LPTOP_LEVEL_EXCEPTION_FILTER cur = SetUnhandledExceptionFilter(kz2_log_crash_filter);
        if (cur && cur != kz2_log_crash_filter) { s_prev_filter = cur; InterlockedExchange(&s_filter_set, 1); return 0; }
        Sleep(500);
    }
    return 0;
}

/* The port's buffered stdio (the fix for a log written one character per write()) is upstream since ps3recomp v0.18.0 (#524, the general form of KZ2's patch 6029):
 * ppu_run calls ps3_stdio_init(), which gives stdout and stderr a 64 KB buffer each, flushes them every
 * PS3_STDIO_FLUSH_MS (50 ms) and on exit, abort and crash. Its flusher only calls fflush, which takes each stream's
 * lock, so a line being formatted by another thread is never split (MinGW's vfprintf holds the lock for the whole
 * call). This module only maps the port's switches onto it and adds the session-log flush on abort, so there is
 * one buffer and one flusher thread instead of two. ps3_stdio_init stays in ppu_run (not called from here): its
 * crash filter must go on top of ppu_run's ppu_crash_report so kz2_log_filter_chain chains behind both. */
static void kz2_log_on_abort(int sig)
{
    (void)sig;
    kz2_session_log_flush(1000);
}

int kz2_stdio_buffer_start(void)
{
    const char* u = getenv("KZ2_LOG_UNBUFFERED");
    if (u && u[0] == '1') {
        setvbuf(stdout, NULL, _IONBF, 0);
        setvbuf(stderr, NULL, _IONBF, 0);
        _putenv("PS3_STDIO_UNBUFFERED=1");   /* ps3_stdio_init then leaves both streams unbuffered */
        printf("[log] stdout/stderr unbuffered (KZ2_LOG_UNBUFFERED=1)\n");
        return 0;
    }
    if (getenv("KZ2_LOG_FLUSH_MS") && !getenv("PS3_STDIO_FLUSH_MS")) {
        char b[48];
        snprintf(b, sizeof b, "PS3_STDIO_FLUSH_MS=%u",
                 kz2_log_env_uint(getenv("KZ2_LOG_FLUSH_MS"), KZ2_LOG_FLUSH_MS_DEFAULT, 1, 10000));
        _putenv(b);
    }
    /* ps3_stdio_init saves this handler and calls it after its own flush (it chains SIGABRT). */
    signal(SIGABRT, kz2_log_on_abort);
    return 1;
}

int kz2_session_log_start(void)
{
    const char* e = getenv("KZ2_LOG_FILE");
    SYSTEMTIME st;
    HANDLE pr = NULL, pw = NULL, h;
    SECURITY_ATTRIBUTES sa = { sizeof sa, NULL, FALSE };
    wchar_t path[1200];
    char name[64];
    int fd_w, out_fd, err_fd;
    if (e && e[0] == '0') return 0;
    kz2_exe_dir();
    if (!s_log_dir_w[0]) return 0;
    if (!CreateDirectoryW(s_log_dir_w, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) {
        fprintf(stderr, "[log] cannot create %s/logs (error %lu): no session log file\n", s_exe_dir, GetLastError());
        return 0;
    }
    kz2_log_prune();
    GetLocalTime(&st);
    for (int seq = 1; seq < 100; seq++) {
        wchar_t wn[64];
        if (kz2_log_file_name(name, sizeof name, st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, seq) < 0)
            return 0;
        MultiByteToWideChar(CP_UTF8, 0, name, -1, wn, 64);
        _snwprintf(path, 1200, L"%ls\\%ls", s_log_dir_w, wn);
        path[1199] = 0;
        h = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, CREATE_NEW,
                        FILE_ATTRIBUTE_NORMAL, NULL);
        if (h != INVALID_HANDLE_VALUE) { s_file = h; break; }
        if (GetLastError() != ERROR_FILE_EXISTS) break;
    }
    if (s_file == INVALID_HANDLE_VALUE) {
        fprintf(stderr, "[log] cannot create a log file in %s/logs (error %lu)\n", s_exe_dir, GetLastError());
        return 0;
    }
    snprintf(s_log_path, sizeof s_log_path, "%s/logs/%s", s_exe_dir, name);
    /* The [build] lines first in the file (stdout had them from kz2_build_header already), redacted, CRLF as the
     * text-mode pipe writes every other line. */
    kz2_build_text();
    kz2_redact_init();
    {
        char red[2 * sizeof s_bi_text + 1], crlf[4 * sizeof s_bi_text + 1];
        size_t m = kz2_redact(&s_redact, s_bi_text, strlen(s_bi_text), red, sizeof red), i, o = 0;
        DWORD put;
        for (i = 0; i < m && o + 2 < sizeof crlf; i++) { if (red[i] == '\n') crlf[o++] = '\r'; crlf[o++] = red[i]; }
        WriteFile(s_file, crlf, (DWORD)o, &put, NULL);
    }

    /* The original stdout (a redirect or the console), if any: the copy goes there too. */
    fflush(stdout);
    fflush(stderr);
    out_fd = _fileno(stdout);
    if (out_fd >= 0) {
        intptr_t oh = _get_osfhandle(out_fd);
        if (oh != -1 && oh != -2 && (HANDLE)oh != NULL)
            DuplicateHandle(GetCurrentProcess(), (HANDLE)oh, GetCurrentProcess(), &s_orig_out, 0, FALSE,
                            DUPLICATE_SAME_ACCESS);
    }
    if (!CreatePipe(&pr, &pw, &sa, 1u << 20)) {
        fprintf(stderr, "[log] CreatePipe failed (%lu): log file without the copy of stdout\n", GetLastError());
        CloseHandle(s_file); s_file = INVALID_HANDLE_VALUE; s_log_path[0] = 0;
        return 0;
    }
    s_pipe_r = pr;
    fd_w = _open_osfhandle((intptr_t)pw, _O_WRONLY | _O_TEXT);   /* text mode, as the old stdout: CRLF lines */
    /* A GUI-subsystem process started with no std handles has stdout/stderr on no descriptor: give them one. */
    if (_fileno(stdout) < 0 && !freopen("NUL", "w", stdout)) { /* keeps the old stream */ }
    if (_fileno(stderr) < 0 && !freopen("NUL", "w", stderr)) { }
    out_fd = _fileno(stdout);
    err_fd = _fileno(stderr);
    if (fd_w >= 0) {
        if (out_fd >= 0) _dup2(fd_w, out_fd);
        if (err_fd >= 0) _dup2(fd_w, err_fd);
    }
    SetStdHandle(STD_OUTPUT_HANDLE, pw);
    SetStdHandle(STD_ERROR_HANDLE, pw);
    kz2_redact_init();   /* before the first line is copied */
    CreateThread(NULL, 64 * 1024, kz2_log_copy, NULL, 0, NULL);
    CreateThread(NULL, 64 * 1024, kz2_log_filter_chain, NULL, 0, NULL);
    atexit(kz2_log_atexit);
    printf("[log] session log: %s (KZ2_LOG_FILE=0 turns it off)\n", s_log_path);
    return 1;
}
#endif
