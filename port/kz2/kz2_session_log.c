/* Killzone 2 port: console switch and session log file (kz2_session_log.h has the rules). ENHANCEMENT (port-only). */
#include "kz2_session_log.h"

#include <stdlib.h>

#ifndef _WIN32
const char* kz2_exe_dir(void) { return "."; }
int  kz2_console_open(void) { return 0; }
int  kz2_session_log_start(void) { return 0; }
const char* kz2_session_log_path(void) { return ""; }
void kz2_session_log_flush(unsigned timeout_ms) { (void)timeout_ms; fflush(stdout); fflush(stderr); }
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

/* The copy thread: pipe -> log file (and the original stdout, if there was one). */
static DWORD WINAPI kz2_log_copy(LPVOID unused)
{
    char buf[16384];
    (void)unused;
    for (;;) {
        DWORD got = 0, put;
        BOOL ok;
        InterlockedExchange(&s_in_read, 1);
        ok = ReadFile(s_pipe_r, buf, sizeof buf, &got, NULL);
        InterlockedExchange(&s_in_read, 0);
        if (!ok || !got) break;
        WriteFile(s_file, buf, got, &put, NULL);
        if (s_orig_out != INVALID_HANDLE_VALUE) WriteFile(s_orig_out, buf, got, &put, NULL);
    }
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

/* An earlier change's buffered stdio is upstream since ps3recomp v0.18.0 (#524, the general form of KZ2's patch 6029):
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
    CreateThread(NULL, 64 * 1024, kz2_log_copy, NULL, 0, NULL);
    CreateThread(NULL, 64 * 1024, kz2_log_filter_chain, NULL, 0, NULL);
    atexit(kz2_log_atexit);
    printf("[log] session log: %s (KZ2_LOG_FILE=0 turns it off)\n", s_log_path);
    return 1;
}
#endif
