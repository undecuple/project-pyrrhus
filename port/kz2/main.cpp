/* Killzone 2 port host. From Project Helghast port/kz3/main.cpp (itself based on ps3recomp templates/project, MIT
 * licence: third_party/ps3recomp/LICENSE), cut to the game-independent boot: KZ3's keyboard page bridge, notice
 * window, keycap prompts (patch 2039, not carried over), PSARC VFS, KZ3 HLE glue and the file logger are left out;
 * KZ3_* switches are KZ2_* here. kz2_log.h is a stdio stand-in for the logger. */
/*
 * ps3recomp game project -- entry point template.
 *
 * This is the runner. It boots a lifted title through the toolkit's PPU
 * scaffold: allocate the flat guest VM, load the PPU ELF named on the command
 * line, register the lifted function table and the HLE NID handlers, start a
 * frame clock, and dispatch the entry OPD.
 *
 * The scaffold does the work; nothing below reimplements it. ppu_load_elf,
 * ppu_recomp_register, ppu_hle_init, ppu_sysprx_register, ppu_fs_register,
 * lv2_init_syscalls and ppu_run all come from the toolkit, compiled into this
 * project from PS3RECOMP_DIR (see CMakeLists.txt). What is left here is the
 * part a port owns: which backend to present through, how the frame clock is
 * paced, and whatever diagnostics the title turns out to need.
 *
 * runtime/ppu/tests/boot_main.cpp in the toolkit is the same boot in its
 * fully-instrumented form -- crash filter, hang watchdog, guest-PC sampling
 * profiler. Read it when a boot goes wrong; copy from it what the title
 * needs. It is deliberately not what a fresh project starts with.
 *
 * The one part that IS duplicated from it is the frame clock below, because a
 * port is expected to change its pacing and a shared one would be the wrong
 * shape for that. It was copied faithfully, comments and all. If a pacing bug
 * is fixed in one of the two, look at the other.
 *
 * This builds on Windows, macOS and Linux. CI builds and runs it against the
 * boot smoke title on the last two, and compile-checks it against clang-cl on
 * the first (tools/check_ppu_scaffold.py).
 */

/* The lifter's generated header, which declares ppu_context and the function
 * table. It comes first: everything below is written against that struct. */
#include "ppu_recomp.h"

/* The Win32 names -- Sleep, GetTickCount64, CreateThread, InterlockedIncrement,
 * VirtualAlloc, the scalar typedefs -- from one place. On Windows this is a
 * passthrough to <windows.h>; off Windows the toolkit's shim supplies the same
 * names over pthreads and mmap, so the call sites below are written once. */
#include "win32_compat.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <string>
#ifdef _WIN32
#include <direct.h>
#endif
#include <sys/stat.h>
#include "kz2_log.h"   /* stdio stand-in for KZ3's file logger */
#include "ps3emu/split_file.h"   /* patch 6034: ps3_sf_has_parts for the update miss hook */
#include "kz2_fios_stamp.h"       /* FIOS disk cache stamp (patch 6035 pre-open hook) */

#ifdef _WIN32
/* timeBeginPeriod: <windows.h> arrives with WIN32_LEAN_AND_MEAN set, which
 * excludes the multimedia timer API, so it is asked for by name -- and after
 * windows.h, since timeapi.h uses UINT. No shim exists off Windows because
 * there is nothing to shim: the 15.6 ms default timer granularity this works
 * around is a Windows problem. */
#include <timeapi.h>
#endif

/* ---------------------------------------------------------------------------
 * What the scaffold gives this file
 * -----------------------------------------------------------------------*/
extern "C" {
uint32_t ppu_load_elf(const char* path);      /* ELF -> guest RAM, returns entry OPD */
void     ppu_recomp_register(void);           /* generated: lifted table -> address map */
void     ppu_hle_init(void);                  /* firmware import NID -> HLE handler */
void     ppu_sysprx_register(void);           /* boot-critical CRT (sys_initialize_tls, ...) */
void     ppu_fs_register(void);               /* cellFs over the real game directory */
void     lv2_init_syscalls(void);             /* the lv2 syscall table */
void     cellSaveData_register_ctx_handlers(void); /* 9-argument User*Auto{Load,Save} (patch 3001) */
void     cellGame_init_from_paramsfo(const char* sfo_path); /* title id etc. from PARAM.SFO */
extern uint32_t ppu_hle_inject_base;           /* guest EA of the runtime's GCM window (labels, control) */
int      ppu_run(uint32_t entry_opd, uint32_t stack_top);
/* KZ3 patch 1032/1033 (runtime/diag/kz3_wait_acct.c): names this host thread's wait-accounting record. The 1033
 * sampler (KZ3_PROF=FROM,TO) only samples named threads whose name contains KZ3_PROF_FILTER (a plain substring in
 * KZ2's copy; default "spurs-kern" or "pm-worker"). KZ2 names the guest main thread "ppu:main" and the walker thread
 * "rsx:frame" when KZ3_WAIT_ACCT is set, so KZ3_PROF_FILTER=: samples them together with the SPURS threads
 * ("spurs-kern0:..", "pm-worker:..") (KZ3's 1079 names its main thread "ppu-main" in ppu_run). */
void     kz3_wacct_name(const char* name);

/* This project's own: load whatever real system PRX modules the title needs
 * into guest RAM and register their exports. stubs.cpp has the empty version
 * a game with no lifted PRX wants. */
void     ps3_load_prx_modules(void);

extern const char* ppu_vfs_root;              /* host dir the PS3 mount points map into */

/* The status the guest handed to sys_process_exit. A title that exits that way
 * never returns through ppu_run, so this is only read on the path where the
 * entry function unwound instead. */
extern int     g_sys_process_exit_called;
extern int32_t g_sys_process_exit_code;

/* Host-provided symbols the runtime and the HLE libraries link against. */
uint8_t* vm_base = nullptr;
extern uint32_t ppu_vm_size;                  /* ppu_loader.cpp: the OOB guard */

/* Guest-callback dispatch. g_ps3_guest_caller is the hook the HLE runtime
 * calls back into recompiled code through -- cellSysutil events and the GCM
 * vblank/flip handlers. ppu_guest_call does the OPD -> dispatch. */
typedef void (*ps3_guest_caller_fn)(uint32_t, uint64_t, uint64_t, uint64_t, uint64_t,
                                    uint64_t, uint64_t, uint64_t, uint64_t);
extern ps3_guest_caller_fn g_ps3_guest_caller;
uint64_t ppu_guest_call(uint32_t, uint64_t, uint64_t, uint64_t, uint64_t,
                        uint64_t, uint64_t, uint64_t, uint64_t);

/* The GCM half of the frame clock. */
void     cellGcmTickVBlank(void);
void     cellGcmTickFlip(void);
int      cellGcm_take_flip_pending(void);
void     cellGcm_rsx_process_fifo(void);      /* drain get -> put */
unsigned cellGcm_flip_request_count(void);
}

/* ---------------------------------------------------------------------------
 * RSX present backend
 * -----------------------------------------------------------------------*/
/* D3D12 on Windows, Metal on Apple, and the null backend's headless software
 * path anywhere else -- the same selection runtime/host/host_posix.c and the
 * toolkit's boot harness make. All three expose the same three entry points,
 * so the frame clock below is backend-agnostic. */
#if defined(_WIN32)
extern "C" int  rsx_d3d12_backend_init(uint32_t w, uint32_t h, const char* title);
extern "C" void rsx_d3d12_backend_present(void);
extern "C" int  rsx_d3d12_backend_pump_messages(void);
#  define rsx_backend_init    rsx_d3d12_backend_init
#  define rsx_backend_present rsx_d3d12_backend_present
#  define rsx_backend_pump    rsx_d3d12_backend_pump_messages
#  define RSX_BACKEND_NAME    "D3D12"
#elif defined(__APPLE__)
extern "C" int  rsx_metal_backend_init(uint32_t w, uint32_t h, const char* title);
extern "C" void rsx_metal_backend_present(void);
extern "C" int  rsx_metal_backend_pump_messages(void);
#  define rsx_backend_init    rsx_metal_backend_init
#  define rsx_backend_present rsx_metal_backend_present
#  define rsx_backend_pump    rsx_metal_backend_pump_messages
#  define RSX_BACKEND_NAME    "Metal"
#else
extern "C" int  rsx_null_backend_init(uint32_t w, uint32_t h, const char* title);
extern "C" void rsx_null_backend_present(void);
extern "C" int  rsx_null_backend_pump_messages(void);
#  define rsx_backend_init    rsx_null_backend_init
#  define rsx_backend_present rsx_null_backend_present
#  define rsx_backend_pump    rsx_null_backend_pump_messages
#  define RSX_BACKEND_NAME    "null (headless software)"
#endif

/* ---------------------------------------------------------------------------
 * Configuration
 * -----------------------------------------------------------------------*/
/* The flat VM must span every region the PS3 memory map uses, not just the
 * game image: sys_ppu_thread_create puts thread stacks at 0xD0000000, so a
 * smaller arena makes every spawned thread's stack access out of bounds. */
#define VM_SIZE       0x100010000ull   /* the full 32-bit guest space + a 64K guard */
#define STACK_TOP     0x0FF00000u      /* main-thread stack, below the 0x10000000 segment */
#define WINDOW_WIDTH  1280
#define WINDOW_HEIGHT 720

/* ---------------------------------------------------------------------------
 * Frame clock
 * -----------------------------------------------------------------------*/
/* On real hardware the RSX raises a vblank interrupt about 60 times a second
 * and that is what drives the game's frame loop. With no RSX it is synthesized
 * here: a host thread calls cellGcmTickVBlank/TickFlip, which invoke the
 * handlers the guest registered, and drains the GCM FIFO. Without this the
 * title initialises, registers its handlers and then waits forever.
 *
 * The ticks are driven off real elapsed time rather than off how long present()
 * took. A hidden or occluded window makes present block hard, and pacing the
 * ticks behind it paces the whole game behind it. */
static volatile LONG g_frames_presented = 0;

/* Frames handed to the backend at a guest FLIP boundary -- one per frame the
 * guest actually finished. The presents made before the guest's first flip, so
 * a fresh window is not left blank through a long boot, carry no guest frame
 * and are deliberately not counted. */
extern "C" unsigned ppu_boot_frames_presented(void)
{
    return (unsigned)g_frames_presented;
}

/* ps3recomp's second D3D12 path, the live-draw engine (libs/video/rsx_live_draw.c: per-surface depth, MRT,
 * mip chains), opt-in with RSX_LIVE_DRAW=1 for the renderer probe. The null backend opens the window and the
 * engine presents into it; unset, the rsx_d3d12_backend path below is unchanged. Bring-up follows the toolkit's
 * runtime/ppu/tests/boot_main.cpp. */
extern "C" int      rsx_live_draw_enabled(void);
extern "C" int      rsx_live_draw_init(void* hwnd, uint32_t w, uint32_t h,
                                       const uint8_t* (*guest_ptr)(void*, uint32_t, uint32_t, uint32_t), void* user);
extern "C" void     rsx_live_draw_present(uint32_t buffer_id);
extern "C" void     rsx_live_draw_shutdown(void);
extern "C" int      rsx_null_backend_init(uint32_t w, uint32_t h, const char* title);
extern "C" int      rsx_null_backend_pump_messages(void);
extern "C" void*    rsx_null_backend_get_hwnd(void);
extern "C" void     rsx_null_backend_suppress_present(int on);
extern "C" uint32_t cellGcmResolveLocated(int local, uint32_t offset);
extern "C" uint32_t cellGcmResolveIO(uint32_t offset);
extern "C" unsigned cellGcmGetCurrentDisplayBufferId(void);
static int s_rsx_live = 0;

/* (location, offset) -> host memory: location 0 = RSX local memory, 1 = main memory through the IO table. */
static const uint8_t* rsx_live_guest_ptr(void*, uint32_t location, uint32_t offset, uint32_t min_bytes)
{
    if (!vm_base) return nullptr;
    uint32_t ea;
    if (location == 0) ea = cellGcmResolveLocated(1, offset);
    else { ea = cellGcmResolveIO(offset); if (!ea) ea = cellGcmResolveLocated(0, offset); }
    if (!ea || ea == 0xFFFFFFFFu || (uint64_t)ea + min_bytes > 0x100000000ull) return nullptr;
    return (const uint8_t*)vm_base + ea;
}

/* Display modes (patch 2095, from Project Helghast port/kz3/main.cpp kz3_display_load/kz3_display_save; ENHANCEMENT): the
 * mode, scaling and filter are kept in display.ini beside keybinds.ini ([display] mode = windowed|borderless|fullscreen,
 * scaling = fit|stretch, filter = bilinear|nearest; rsx_display_mode.h), read here before the window opens and written
 * by the window's thread when Alt+Enter changes the mode. KZ2_DISPLAY, KZ2_DISPLAY_SCALING, KZ2_DISPLAY_FILTER win for
 * one run, and then nothing is saved (rsx_null_backend.c). KZ3's Options rows for these are not ported. */
#ifdef _WIN32
#include "rsx_display_mode.h"
extern "C" int  pad_kb_sibling_path(const wchar_t* name, wchar_t* out, size_t n);   /* cellPad.c (patch 2095) */
extern "C" void rsx_display_configure(int saved_mode, int saved_scaling, int saved_filter,
                                      void (*save)(int mode, int scaling, int filter));   /* rsx_null_backend.c */

static void kz2_display_save(int mode, int scaling, int filter)
{
    wchar_t p[1100];
    char t[512];
    const int n = rsx_dm_ini_write(t, sizeof t, mode, scaling, filter);
    if (n <= 0 || !pad_kb_sibling_path(L"display.ini", p, 1100)) return;
    FILE* f = _wfopen(p, L"wb");
    const bool ok = f && fwrite(t, 1, (size_t)n, f) == (size_t)n;
    if (f) fclose(f);
    printf("[display] %ls: mode %s, scaling %s, filter %s %s\n", p, rsx_dm_name(mode), rsx_dm_scaling_name(scaling),
           rsx_dm_filter_name(filter), ok ? "saved" : "NOT saved");
    fflush(stdout);
}

static void kz2_display_load(void)
{
    wchar_t p[1100];
    char t[2048];
    int mode = -1, scaling = -1, filter = -1;
    if (pad_kb_sibling_path(L"display.ini", p, 1100)) {
        FILE* f = _wfopen(p, L"rb");
        if (f) {
            const size_t n = fread(t, 1, sizeof t - 1, f);
            fclose(f);
            t[n] = 0;
            mode = rsx_dm_ini_parse(t);
            scaling = rsx_dm_ini_scaling(t);
            filter = rsx_dm_ini_filter(t);
            printf("[display] %ls: mode %s, scaling %s, filter %s\n", p, mode >= 0 ? rsx_dm_name(mode) : "(none)",
                   scaling >= 0 ? rsx_dm_scaling_name(scaling) : "(none)", filter >= 0 ? rsx_dm_filter_name(filter) : "(none)");
        } else {
            printf("[display] %ls: not there (optional; Alt+Enter writes it)\n", p);
        }
    }
    rsx_display_configure(mode, scaling, filter, kz2_display_save);
}
#endif

static int kz2_rsx_init(uint32_t w, uint32_t h, const char* title)
{
#ifdef _WIN32
    kz2_display_load();   /* patch 2095 */
    if (rsx_live_draw_enabled()) {
        if (rsx_null_backend_init(w, h, title) == 0 &&
            rsx_live_draw_init(rsx_null_backend_get_hwnd(), w, h, rsx_live_guest_ptr, nullptr) == 0) {
            s_rsx_live = 1;
            rsx_null_backend_suppress_present(1);
            fprintf(stderr, "[rsx] live-draw engine up (RSX_LIVE_DRAW=1)\n");
            return 0;
        }
        fprintf(stderr, "[rsx] live-draw init FAILED -- falling back to the D3D12 backend\n");
    }
#endif
    return rsx_backend_init(w, h, title);
}
static void kz2_rsx_present(void)
{
    if (s_rsx_live) rsx_live_draw_present(cellGcmGetCurrentDisplayBufferId());
    else            rsx_backend_present();
}
static int kz2_rsx_pump(void) { return s_rsx_live ? rsx_null_backend_pump_messages() : rsx_backend_pump(); }

/* Window closed (X button, Alt+F4, a scripted WM_CLOSE such as tools/release/shaders.py's): end the
 * process cleanly from the frame thread, which owns the window and the live-draw walker. Live-draw shutdown first
 * (GPU drain, PSO preload workers joined, pso_library.bin serialized), then the log is flushed and closed, then the
 * process ends with code 0. TerminateProcess rather than exit(): guest PPU/SPU threads are still running and may
 * hold CRT or loader locks, which exit()'s handlers and DLL detach would wait on. A watchdog ends the process with
 * code 3 if the shutdown itself hangs (KZ2_CLOSE_WATCHDOG=<s>, default 15). Before this the frame loop only
 * stopped presenting and kz2.exe kept running without a window. */
static DWORD WINAPI kz2_close_watchdog(LPVOID)
{
    const char* e = getenv("KZ2_CLOSE_WATCHDOG");
    const int s = (e && atoi(e) > 0) ? atoi(e) : 15;
    Sleep((DWORD)s * 1000u);
    KZ2_LOGE("exit", "window-close shutdown did not finish in %d s: terminating (exit code 3)", s);
    kz2_log_shutdown();
    fflush(NULL);
    TerminateProcess(GetCurrentProcess(), 3);
    return 0;
}
static void kz2_exit_on_window_close(void)
{
    LARGE_INTEGER f, t0, t1;
    QueryPerformanceFrequency(&f); QueryPerformanceCounter(&t0);
    KZ2_LOGI("exit", "window closed: shutting down (live draw %s)", s_rsx_live ? "on" : "off");
    HANDLE wd = CreateThread(NULL, 0, kz2_close_watchdog, NULL, 0, NULL);
    (void)wd;
    if (s_rsx_live) rsx_live_draw_shutdown();
    QueryPerformanceCounter(&t1);
    KZ2_LOGI("exit", "clean exit after %.0f ms (exit code 0)", (double)(t1.QuadPart - t0.QuadPart) * 1e3 / (double)f.QuadPart);
    kz2_log_shutdown();
    fflush(NULL);
    TerminateProcess(GetCurrentProcess(), 0);
}

/* KZ2_TEST_CLOSE=<s>: after s seconds, post WM_CLOSE to every top-level window of this process, as
 * tools/release/shaders.py's close_politely does from outside (Proton test of the clean exit). */
static BOOL CALLBACK kz2_test_close_enum(HWND h, LPARAM n)
{
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    if (pid == GetCurrentProcessId()) { PostMessageW(h, WM_CLOSE, 0, 0); ++*(int*)n; }
    return TRUE;
}
/* the menu's EXIT TO DESKTOP (gModule:ExitAll("pc:exit"), kz2_menu_pages.cpp) closes the game the way the
 * window's close button does: WM_CLOSE to this process's windows, then kz2_exit_on_window_close on the frame thread
 * (clean shutdown, exit code 0). */
extern "C" void kz2_request_close(const char* why)
{
    int n = 0;
    EnumWindows(kz2_test_close_enum, (LPARAM)&n);
    KZ2_LOGI("exit", "%s: WM_CLOSE posted to %d window(s)", why ? why : "close requested", n);
}
static DWORD WINAPI kz2_test_close(LPVOID)
{
    const char* e = getenv("KZ2_TEST_CLOSE");
    Sleep((DWORD)(atoi(e) * 1000));
    kz2_log_set_thread_label("test");
    int n = 0;
    EnumWindows(kz2_test_close_enum, (LPARAM)&n);
    KZ2_LOGI("test", "KZ2_TEST_CLOSE=%s: WM_CLOSE posted to %d window(s)", e, n);
    return 0;
}

extern "C" void kz2_watch_poll(unsigned flip);   /* kz2_watch.cpp: KZ2_WATCH region poll (off by default) */

static void present_guest_frame(void)
{
    kz2_rsx_present();
    kz2_watch_poll(cellGcm_flip_request_count());
    /* This thread increments and guest threads read, so interlocked rather
     * than a volatile ++, which on arm64 is neither atomic nor a fence. */
    InterlockedIncrement(&g_frames_presented);
}

/* No renderer: neither the live renderer nor the D3D12 backend got a device (no GPU and no WARP,
 * a broken driver). Before, the frame loop went on without a window and the process crashed (0xC0000005 under Wine
 * with no GPU, release 19's VM test). Now: one log line, a message box (KZ2_NO_ERROR_DIALOG=1 skips it, for scripted
 * runs), the log flushed, exit code 2. TerminateProcess as on window close: guest threads may hold CRT locks. */
static void kz2_no_renderer_exit(void)
{
    fprintf(stderr, "[rsx] ERROR: no Direct3D 12 device (see the [d3d12] lines above): exiting with code 2\n");
    kz2_log_shutdown();
    const char* q = getenv("KZ2_NO_ERROR_DIALOG");
    if (!(q && q[0] == '1'))
        MessageBoxW(NULL, L"Project Pyrrhus could not start: no Direct3D 12 graphics device was found.\n\n"
                          L"Please install or update the graphics driver. The log folder next to kz2.exe has the details.",
                    L"Project Pyrrhus", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
    TerminateProcess(GetCurrentProcess(), 2);
}

/* The message pump inside the vblank catch-up loop. From Project Helghast (the Killzone 3 PC port)
 * v0.1.4 (port/kz3/main.cpp; same author, MIT), KZ3_ -> KZ2_. The inner loop below fires every
 * vblank tick the clock is behind, and each tick drains the FIFO (the live renderer's walker: 29-30 ms a frame on
 * Corinth River), so while a drain takes longer than the 16 ms tick the backlog grows and the loop
 * runs on for up to 240 ticks without returning to the pump. The window's messages (WM_CLOSE, focus, size, the
 * keyboard page's capture) then wait seconds, and Windows marks a window that has not pumped for 5 s as not responding.
 * KZ3's player saw it as mouse look holding still then jumping. KZ2_PUMP_TICK=0 = the old pump (outer loop only).
 * kz2_pump_note: the longest gap between two pumps, a line per gap over 250 ms (first 20) and a summary every 10 s. */
static int kz2_pump_tick_on(void)
{
    static int on = -1;
    if (on < 0) {
        const char* e = getenv("KZ2_PUMP_TICK");
        on = !(e && e[0] == '0');
        fprintf(stderr, "[pump] message pump %s\n", on ? "on every vblank tick (default; KZ2_PUMP_TICK=0 = outer loop only)"
                                                       : "in the outer loop only (KZ2_PUMP_TICK=0)");
    }
    return on;
}
static void kz2_pump_note(int fired)
{
    static LARGE_INTEGER s_qf, s_last, s_win;
    static double s_max;
    static unsigned s_n, s_long, s_lines;
    LARGE_INTEGER q;
    QueryPerformanceCounter(&q);
    if (!s_qf.QuadPart) { QueryPerformanceFrequency(&s_qf); s_last = s_win = q; return; }
    const double gap = (double)(q.QuadPart - s_last.QuadPart) * 1e3 / (double)s_qf.QuadPart;
    s_last = q;
    s_n++;
    if (gap > s_max) s_max = gap;
    if (gap > 250.0) {
        s_long++;
        if (s_lines++ < 20)
            fprintf(stderr, "[pump] gap %.0f ms between message pumps (flip=%u, %d vblank tick(s) in that pass)\n", gap,
                    cellGcm_flip_request_count(), fired);
    }
    const double win = (double)(q.QuadPart - s_win.QuadPart) / (double)s_qf.QuadPart;
    if (win >= 10.0) {
        fprintf(stderr, "[pump] last %.1f s: %u pumps, longest gap %.0f ms, %u gap(s) over 250 ms\n", win, s_n, s_max, s_long);
        s_win = q; s_n = s_long = 0; s_max = 0.0;
    }
}

static DWORD WINAPI frame_clock(LPVOID)
{
    kz2_log_set_thread_label("frame");
    if (getenv("KZ3_WAIT_ACCT")) kz3_wacct_name("rsx:frame");   /* sampled with KZ3_PROF_FILTER=: */
    /* The window title (release 19's request): the port's name by default. PS3_TITLE (tests) still
     * overrides it; it is also the trophy folder's name, so the launcher does not set it. */
    const char* title = getenv("PS3_TITLE");
    if (!title || !*title) title = "Project Pyrrhus";

    int rsx_ok = (kz2_rsx_init(WINDOW_WIDTH, WINDOW_HEIGHT, title) == 0);
    fprintf(stderr, "[rsx] %s backend init %s\n", RSX_BACKEND_NAME,
            rsx_ok ? "OK -- window open" : "FAILED");
    if (!rsx_ok) kz2_no_renderer_exit();

    unsigned  last_flip = 0;
    ULONGLONG next_tick = GetTickCount64();

    for (;;) {
        Sleep(4);
        ULONGLONG now = GetTickCount64();

        int fired = 0;
        while ((long long)(now - next_tick) >= 0 && fired < 240) {
            cellGcmTickVBlank();
            cellGcmTickFlip();
            /* Present a pending flip BEFORE draining any further. The flip
             * fires at a get==put frame boundary on the guest thread, so the
             * batch held right now is exactly the completed frame; presenting
             * after the drain races the guest's next-frame writes and shows a
             * mixed one. */
            if (rsx_ok && cellGcm_take_flip_pending()) {
                present_guest_frame();
                last_flip = cellGcm_flip_request_count();
            }
            /* Drain the FIFO every tick. This is what writes the RSX sync-fence
             * labels the game's per-frame logic blocks on, so it has to keep
             * advancing at 60 Hz even while present() throttles. */
            if (rsx_ok) cellGcm_rsx_process_fifo();
            /* pump on every tick too, so a catch-up pass does not hold the window's messages back */
            if (rsx_ok && kz2_pump_tick_on()) {
                if (kz2_rsx_pump() != 0) {
                    kz2_exit_on_window_close();   /* does not return */
                    rsx_ok = 0;
                }
                kz2_pump_note(fired + 1);
            }
            next_tick += 16;             /* ~60 Hz */
            fired++;
        }
        if (fired >= 240) next_tick = now;   /* fell too far behind -- resync */

        /* Drain at the outer cadence too, not only on the 16 ms tick: titles
         * fence every render pass on a label the drain writes, and one wave of
         * those at 16 ms apiece paces the guest into single-figure frame rates.
         * The real RSX writes them in microseconds. */
        if (rsx_ok) {
            if (cellGcm_take_flip_pending()) {
                present_guest_frame();
                last_flip = cellGcm_flip_request_count();
            }
            cellGcm_rsx_process_fifo();

            if (kz2_rsx_pump() != 0) {
                kz2_exit_on_window_close();   /* does not return */
                rsx_ok = 0;
                continue;
            }
            kz2_pump_note(fired);
            /* Present on a guest flip. A present on a fixed clock can catch the
             * drain mid-frame and flash a partial one. Before the first flip
             * present freely, so the window is not blank during boot. */
            unsigned fc = cellGcm_flip_request_count();
            if (fc != last_flip) {
                /* Consume the pending flip too, or the next pass presents the same
                 * flip again (3,904 presents for 2,483 flips). */
                cellGcm_take_flip_pending();
                present_guest_frame();
                last_flip = fc;
            } else if (fc == 0) {
                kz2_rsx_present();
            }
        }
    }
    return 0;
}

/* ---------------------------------------------------------------------------
 * VFS root
 * -----------------------------------------------------------------------*/
/* Derive the directory holding PS3_GAME from the EBOOT path
 * <root>/PS3_GAME/USRDIR/EBOOT.elf -> <root>. $PS3_VFS_ROOT overrides. */
static char s_vfs_root[1024];

static void derive_vfs_root(const char* eboot)
{
    const char* env = getenv("PS3_VFS_ROOT");
    if (env && *env) { ppu_vfs_root = env; return; }

    strncpy(s_vfs_root, eboot, sizeof s_vfs_root - 1);
    for (char* p = s_vfs_root; *p; p++) if (*p == '\\') *p = '/';
    /* strip EBOOT.elf, USRDIR and PS3_GAME */
    for (int i = 0; i < 3; i++) { char* s = strrchr(s_vfs_root, '/'); if (s) *s = 0; }
    if (!s_vfs_root[0]) strcpy(s_vfs_root, ".");
    ppu_vfs_root = s_vfs_root;
}

/* ---------------------------------------------------------------------------
 * Game update (1.29) data: KZ2_UPDATE_DIR=<update>/USRDIR (the name tools/release/launch.py sets)
 * -----------------------------------------------------------------------*/
/* On a PS3 the 1.29 update lives in /dev_hdd0/game/BCUS98116/USRDIR (EBOOT.BIN, added_data_ps3.psarc,
 * patch_data_ps3/ with the .pspatch files; the game's FIOS reads them itself). Two ways to reach it:
 *  - KZ2_UPDATE_DIR ends in .../dev_hdd0/game/BCUS98116/USRDIR (an RPCS3 tree) and PS3_HDD0_ROOT is unset:
 *    PS3_HDD0_ROOT is set to that dev_hdd0, so every /dev_hdd0 path resolves there (sys_fs.c / ppu_fs.cpp).
 *  - any other folder: the runtime's VFS miss hook (g_ps3_vfs_miss_hook, sys_fs.c) retries a host path that still
 *    misses after the USRDIR flattening with its part from USRDIR/ on under KZ2_UPDATE_DIR. Only misses are
 *    retried, so a disc file is never shadowed (ASSUMPTION: the update adds files and does not re-use disc names;
 *    true for added_data_ps3.psarc and patch_data_ps3/).
 * Without KZ2_UPDATE_DIR, <vfs root>/dev_hdd0/game/BCUS98116/USRDIR is used when it exists (the stage layout of
 * tools/runtime/stage.sh, so the boot check needs no extra variable). Each miss-hook hit is logged ("[kz2-update] ...",
 * first 64); with PS3_HDD0_ROOT the opens show as ordinary "[fs] open '/dev_hdd0/...'" lines. */
extern "C" void (*g_ps3_vfs_miss_hook)(char* path, size_t cap);
static char s_update_dir[1024];
extern "C" const char* kz2_update_dir(void) { return s_update_dir; }   /* kz2_menu_pages.cpp: the 1.29 patch_data_ps3 */
static char s_hdd0_env[1100];

static void update_miss_hook(char* path, size_t cap)
{
    const char* u = strstr(path, "/USRDIR/"); if (!u) u = strstr(path, "\\USRDIR\\");
    if (!u || !s_update_dir[0]) return;
    char alt[1400];
    snprintf(alt, sizeof alt, "%s/%s", s_update_dir, u + 8);
    for (char* p = alt; *p; p++) if (*p == '\\') *p = '/';
    struct stat st;
    if (stat(alt, &st) != 0 && !ps3_sf_has_parts(alt)) return;   /* a FAT32 part set counts as the file (patch 6034) */
    static int logged = 0;
    if (logged < 64) { logged++; fprintf(stderr, "[kz2-update] %s -> %s\n", path, alt); }
    snprintf(path, cap, "%s", alt);
}

/* KZ2_SKIP_INTRO=1 (test aid, ENHANCEMENT): start the front end on the main menu page instead of the intro page.
 * The front end is a set of "JSP" pages; a data table holds the start page's URL pointer. The community 1.29 "Skip
 * Intro" patch swaps it (the RE notes): 1.29 @0x00F07460 "file:///kin/index.jsp" (0x00BFA880)
 * -> "file:///kin/menu/mainmenu.jsp" (0x00BFAB10). v1.01 has the same table at @0x00EF6618: 0x00BE3770 -> 0x00BE3A00
 * (strings and table neighbours checked). The word is changed only if it holds the expected
 * pointer, so the other EBOOT is left alone. Off unless KZ2_SKIP_INTRO=1: the intro movie (GameIntro_PS3.avi) plays
 * through to the title screen since patch 6021 (cellVdec handles are nonzero; the movie player read handle 0 as "not
 * open" and never submitted an AU, which stalled every movie thread). Until then hand-play launches skipped it. */
static void skip_intro_option(void)
{
    const char* e = getenv("KZ2_SKIP_INTRO");
    if (!(e && e[0] == '1')) return;
    static const struct { uint32_t at, from, to; const char* ver; } sites[] = {
        {0x00F07460u, 0x00BFA880u, 0x00BFAB10u, "1.29"},
        {0x00EF6618u, 0x00BE3770u, 0x00BE3A00u, "v1.01"},
    };
    for (const auto& s : sites) {
        if (vm_read32(s.at) != s.from) continue;
        vm_write32(s.at, s.to);
        printf("[boot] KZ2_SKIP_INTRO: start page -> mainmenu.jsp (%s, 0x%08X)\n", s.ver, s.at);
        return;
    }
    printf("[boot] KZ2_SKIP_INTRO: no known start-page word found; nothing changed\n");
}

static void setup_update_dir(void)
{
    const char* e = getenv("KZ2_UPDATE_DIR");
    if (!e || !*e) {   /* the stage layout (tools/runtime/stage.sh): <vfs root>/dev_hdd0/game/BCUS98116/USRDIR */
        static char staged[1100]; struct stat sst;
        snprintf(staged, sizeof staged, "%s/dev_hdd0/game/BCUS98116/USRDIR", ppu_vfs_root ? ppu_vfs_root : ".");
        if (stat(staged, &sst) != 0) return;
        e = staged;
    }
    snprintf(s_update_dir, sizeof s_update_dir, "%s", e);
    for (char* p = s_update_dir; *p; p++) if (*p == '\\') *p = '/';
    size_t n = strlen(s_update_dir);
    while (n > 1 && s_update_dir[n - 1] == '/') s_update_dir[--n] = 0;
    static const char tail[] = "/game/BCUS98116/USRDIR";
    const size_t tl = sizeof tail - 1;
    const char* hdd0 = getenv("PS3_HDD0_ROOT");
    if ((!hdd0 || !*hdd0) && n > tl && strcmp(s_update_dir + n - tl, tail) == 0) {
        snprintf(s_hdd0_env, sizeof s_hdd0_env, "PS3_HDD0_ROOT=%.*s", (int)(n - tl), s_update_dir);
        _putenv(s_hdd0_env);
        printf("[boot] update: %s (PS3_HDD0_ROOT=%s)\n", s_update_dir, s_hdd0_env + 14);
    } else {
        printf("[boot] update: %s (VFS miss hook%s)\n", s_update_dir, hdd0 && *hdd0 ? "; PS3_HDD0_ROOT already set" : "");
    }
    g_ps3_vfs_miss_hook = update_miss_hook;
    /* cellGameBootCheck reports the PATCH attribute, as for a PS3 title booted from its update (patch 6007). */
    if (!getenv("PS3_GAME_ATTR_PATCH")) _putenv("PS3_GAME_ATTR_PATCH=1");
    struct stat st;
    if (stat(s_update_dir, &st) != 0) printf("[boot] update: %s does not exist\n", s_update_dir);
}

/* ---------------------------------------------------------------------------
 * Guest VM
 * -----------------------------------------------------------------------*/
#ifdef _WIN32
/* Demand-paging for the flat VM: reserve the whole 4 GB guest space, which
 * costs no commit, and commit each 64 KB page on first access. Every 32-bit
 * guest offset is then valid, so a garbage guest pointer reads zero instead of
 * killing the process. Faults outside the arena fall through untouched. */
static LONG WINAPI vm_commit_veh(EXCEPTION_POINTERS* ep)
{
    if (ep->ExceptionRecord->ExceptionCode == EXCEPTION_ACCESS_VIOLATION) {
        ULONG_PTR fault = ep->ExceptionRecord->ExceptionInformation[1];
        uintptr_t base  = (uintptr_t)vm_base;
        if (vm_base && fault >= base && fault < base + VM_SIZE) {
            void* page = (void*)(fault & ~(uintptr_t)0xFFFF);
            if (VirtualAlloc(page, 0x10000, MEM_COMMIT, PAGE_READWRITE))
                return EXCEPTION_CONTINUE_EXECUTION;
        }
    }
    return EXCEPTION_CONTINUE_SEARCH;
}
#endif

static bool alloc_guest_vm(void)
{
#ifdef _WIN32
    AddVectoredExceptionHandler(1, vm_commit_veh);
    vm_base = (uint8_t*)VirtualAlloc(NULL, VM_SIZE, MEM_RESERVE, PAGE_READWRITE);
    ppu_vm_size = 0;              /* the whole space is backed; no OOB guard needed */
#else
    /* No vectored exception handlers off Windows, so the arena is committed up
     * front and lazily backed by the OS: only pages the title touches cost
     * anything. It stops below the 0xE0000000 mark, so ppu_vm_size arms the
     * loader's bounds check for what is left. */
    vm_base = (uint8_t*)calloc(1, 0xE0000000u);
    ppu_vm_size = 0xE0000000u;
#endif
    return vm_base != nullptr;
}

/* ---------------------------------------------------------------------------
 * Boot diagnostics (opt-in, environment)
 * -----------------------------------------------------------------------*/
/* KZ2_WATCHDOG="s1,s2,...": at each of those seconds after start, print which
 * HLE call every guest thread is inside and each thread's guest lr. A thread
 * parked in sys_lwmutex_lock / sys_lwcond_wait is invisible to the sampler
 * (it shows as ntdll); this names it. With PS3_LWCOND_RING=1 each report also prints the lwcond ring (patch 6004). Taken from the toolkit's boot_main.cpp
 * watchdog, minus the thread suspension. KZ2_PEEK="EA[+off],..." adds guest
 * words to each report: "0x0159493C+8" prints the u32 at EA and the u32 at
 * (that value + 8), i.e. one pointer hop. PS3_SAMPLE=<ms> starts the toolkit's
 * guest-PC sampler as well. */
extern "C" const char* g_hle_inflight[];      /* ppu_hle.cpp; 64 entries */
extern "C" ppu_context*  g_hle_inflight_ctx[];   /* ppu_hle.cpp, patch 6001 */
extern "C" uint32_t    g_last_hle_nid;
extern "C" const char* g_last_hle_name;
extern "C" void        ppu_report_guest_lrs(void);
extern "C" void        ps3_lwcond_ring_dump(void);   /* ppu_sysprx.cpp, patch 6004 */
extern void            ps3_sampler_start(void);

static DWORD WINAPI kz2_watchdog(LPVOID p)
{
    const char* spec = (const char*)p;
    ULONGLONG t0 = GetTickCount64();
    for (const char* s = spec; *s; ) {
        unsigned at = (unsigned)strtoul(s, (char**)&s, 10);
        while (*s == ',' || *s == ' ') s++;
        ULONGLONG due = t0 + (ULONGLONG)at * 1000;
        ULONGLONG now = GetTickCount64();
        if (due > now) Sleep((DWORD)(due - now));
        fprintf(stderr, "[WATCHDOG] t=%us; last HLE call = 0x%08X (%s)\n",
                at, g_last_hle_nid, g_last_hle_name ? g_last_hle_name : "");
        for (unsigned t = 0; t < 64u; t++)
            if (g_hle_inflight[t]) {
                fprintf(stderr, "[WATCHDOG]   guest-tid %-3u in %s", t, g_hle_inflight[t]);
                /* patch 6001: the calling context (also for callbacks an HLE handler runs): lr, r3 and the guest
                 * return addresses up the back chain (PPC64: [S] 64-bit back chain, saved lr at [caller S + 16]). */
                const ppu_context* c = g_hle_inflight_ctx[t];
                if (c) {
                    uint32_t sp = (uint32_t)c->gpr[1];
                    fprintf(stderr, "  lr=0x%08X r3=0x%08X sp=0x%08X chain:", (uint32_t)c->lr, (uint32_t)c->gpr[3], sp);
                    for (int i = 0; i < 16 && sp && sp < 0xF0000000u; i++) {
                        uint32_t nx = __builtin_bswap32(*(uint32_t*)(vm_base + sp + 4));
                        if (!nx || nx <= sp) break;
                        fprintf(stderr, " 0x%08X", __builtin_bswap32(*(uint32_t*)(vm_base + nx + 20)));
                        sp = nx;
                    }
                }
                fprintf(stderr, "\n");
            }
        ppu_report_guest_lrs();
        if (getenv("PS3_LWCOND_RING")) ps3_lwcond_ring_dump();   /* patch 6004: the in-memory lwcond trace */
        if (const char* pk = getenv("KZ2_PEEK")) {
            for (const char* q = pk; *q; ) {
                uint32_t ea = (uint32_t)strtoul(q, (char**)&q, 0), off = 0; int hop = 0;
                if (*q == '+') { off = (uint32_t)strtoul(q + 1, (char**)&q, 0); hop = 1; }
                while (*q == ',' || *q == ' ') q++;
                uint32_t v = __builtin_bswap32(*(uint32_t*)(vm_base + ea));
                if (hop) fprintf(stderr, "[WATCHDOG]   peek [0x%08X]=0x%08X  [0x%08X+0x%X]=0x%08X\n", ea, v, v, off,
                                 __builtin_bswap32(*(uint32_t*)(vm_base + (uint32_t)(v + off))));
                else     fprintf(stderr, "[WATCHDOG]   peek [0x%08X]=0x%08X\n", ea, v);
            }
        }
        /* KZ2_STACK="SP[,SP...]": walk the guest back chain from a parked thread's sp (taken from an earlier
         * watchdog line; a thread parked in an HLE wait keeps its sp). PPC64 ABI: [S] = 64-bit back chain,
         * the callee saves its return address at [caller frame + 16]; so each hop prints the u32 at S'+20. */
        if (const char* st = getenv("KZ2_STACK")) {
            for (const char* q = st; *q; ) {
                uint32_t sp = (uint32_t)strtoul(q, (char**)&q, 0);
                while (*q == ',' || *q == ' ') q++;
                fprintf(stderr, "[WATCHDOG]   stack sp=0x%08X:", sp);
                for (int i = 0; i < 24 && sp && sp < 0xF0000000u; i++) {
                    uint32_t nx = __builtin_bswap32(*(uint32_t*)(vm_base + sp + 4));
                    if (!nx || nx <= sp) break;
                    fprintf(stderr, " 0x%08X", __builtin_bswap32(*(uint32_t*)(vm_base + nx + 20)));
                    sp = nx;
                }
                fprintf(stderr, "\n");
            }
        }
        fflush(stderr);
    }
    return 0;
}


/* KZ2_DISPBUF_SCAN=<ms>: who writes the display buffers' guest bytes? Every <ms>, hash the guest
 * memory of both display buffers (local 0x10000 / 0x394000, 5120 x 720) and the scene target (local 0x7B0000,
 * 10240 x 720) at EA 0xC0000000 + offset, and log each change with the non-zero word count and the first non-zero
 * offset (at most 48 lines). Live-draw renders on the host GPU and does not write display buffers back, so any change
 * here is a CPU-side writer: a PPU store (scalar or VMX, which PPU_WWATCH does not see), an HLE copy or an SPU put.
 * Uncommitted pages are reported as such (nobody ever touched them). */
#ifdef _WIN32
static DWORD WINAPI kz2_dispbuf_scan(LPVOID arg)
{
    const DWORD ms = (DWORD)(uintptr_t)arg;
    static const struct { uint32_t off, bytes; const char* name; } r[3] = {
        {0x10000u, 5120u * 720u, "disp0"}, {0x394000u, 5120u * 720u, "disp1"}, {0x7B0000u, 10240u * 720u, "scene"}};
    uint64_t last[3] = {1, 1, 1};
    int lines = 0;
    for (unsigned tick = 0; lines < 48; tick++) {
        Sleep(ms);
        if (!vm_base) continue;
        for (int i = 0; i < 3 && lines < 48; i++) {
            const uint8_t* p = vm_base + 0xC0000000u + r[i].off;
            MEMORY_BASIC_INFORMATION mi;
            int committed = 1;
            for (uint32_t o = 0; o < r[i].bytes; o += 0x10000u)
                if (!VirtualQuery(p + o, &mi, sizeof mi) || mi.State != MEM_COMMIT) { committed = 0; break; }
            uint64_t h = 1469598103934665603ull; uint32_t nz = 0, first = 0xFFFFFFFFu;
            if (committed) {
                const uint32_t* w = (const uint32_t*)p;
                for (uint32_t k = 0; k < r[i].bytes / 4u; k++) {
                    const uint32_t v = w[k];
                    if (v) { nz++; if (first == 0xFFFFFFFFu) first = k * 4u; }
                    h = (h ^ v) * 1099511628211ull;
                }
            } else h = 0;
            if (h != last[i]) {
                last[i] = h; lines++;
                fprintf(stderr, "[kz2-dispscan] t=%u ms %s local 0x%07X %s nonzero words %u first +0x%X hash %016llX\n",
                        (unsigned)(tick * ms), r[i].name, r[i].off, committed ? "committed" : "UNCOMMITTED", nz,
                        first, (unsigned long long)h);
                fflush(stderr);
            }
        }
    }
    return 0;
}
#endif

extern "C" void kz2_hle_register(void);   /* hle_kz2.cpp */
extern "C" void kz2_menu_install(void);    /* kz2_menu_pages.cpp */

static void start_diagnostics(void)
{
    const char* wd = getenv("KZ2_WATCHDOG");
    if (wd && *wd) CreateThread(NULL, 0, kz2_watchdog, (LPVOID)wd, 0, NULL);
    const char* tc = getenv("KZ2_TEST_CLOSE");   /* scripted window close for test runs */
    if (tc && *tc) CreateThread(NULL, 0, kz2_test_close, NULL, 0, NULL);
#ifdef _WIN32
    const char* ds = getenv("KZ2_DISPBUF_SCAN");  /* display-buffer writer check */
    if (ds && atoi(ds) > 0) CreateThread(NULL, 0, kz2_dispbuf_scan, (LPVOID)(uintptr_t)atoi(ds), 0, NULL);
#endif
#ifdef _WIN32
    ps3_sampler_start();     /* no-op unless PS3_SAMPLE is set */
#endif
}

/* ---------------------------------------------------------------------------
 * Main
 * -----------------------------------------------------------------------*/
static void harness_guest_caller(uint32_t opd, uint64_t a0, uint64_t a1,
                                 uint64_t a2, uint64_t a3, uint64_t a4,
                                 uint64_t a5, uint64_t a6, uint64_t a7)
{
    ppu_guest_call(opd, a0, a1, a2, a3, a4, a5, a6, a7);
}


extern "C" void kz2_prompts_register(void);   /* kz2_prompts.cpp */

int main(int argc, char** argv)
{
#ifdef _WIN32
#pragma comment(lib, "winmm.lib")
    /* 1 ms timer resolution (the default ~15.6 ms granularity throttles every shorter guest wait). */
    timeBeginPeriod(1);
    /* ENHANCEMENT: kz2.exe is a GUI-subsystem program (CMakeLists.txt), so no console window opens beside the game;
     * KZ2_CONSOLE=1 opens one. A redirected stdout (the test runners) is inherited either way, and every run also
     * writes <exe dir>/logs/kz2-<date>-<time>.log (KZ2_LOG_FILE=0: off). kz2_session_log.h has the details. */
    kz2_console_open();
    kz2_session_log_start();
    kz2_stdio_buffer_start();   /* an earlier change switches for ppu_run's buffered stdio (upstream #524; kz2_session_log.h) */
    /* PS3_VERBOSE=0 quiets the per-event diagnostics (patch 6030 and upstream's ps3_log_verbose sites, ~2,000
     * lines/s in a level). The default since an earlier change (kz2_env below): the load stop it exposed (SPU assert in
     * Gfx.PB.ShadowMap, a SPURS task-id race) is fixed by 7004. PS3_VERBOSE=1 brings every line back. */
#endif

    printf("=== Killzone 2 (ps3recomp) ===\n");

    /* No launch option needed (ENHANCEMENT, as KZ3's kz3_boot_inputs): argv[1] if given, else
     * <exe dir>/PS3_GAME/USRDIR/EBOOT.elf, so kz2.exe dropped into the dump's folder (a Steam shortcut to it) starts
     * with no arguments. */
    static char eboot[1100];
    {
        const int from = kz2_eboot_path(kz2_exe_dir(), argc, argv, eboot, sizeof eboot);
        if (from < 0) { fprintf(stderr, "ERROR: the EBOOT path is too long\n"); kz2_log_shutdown(); return 2; }
        printf("[boot] EBOOT from %s: %s\n", from ? "the command line" : "beside the exe", eboot);
        struct stat est;
        if (from == 0 && stat(eboot, &est) != 0) {
            fprintf(stderr, "ERROR: no game files: %s not found. Put kz2.exe next to the PS3_GAME folder of your "
                    "decrypted dump, or pass the EBOOT.elf path as the first argument (usage: %s <PPU ELF>)\n",
                    eboot, argv[0]);
            kz2_log_shutdown();
#ifdef _WIN32
            if (!getenv("KZ2_NO_DIALOG")) {
                char msg[1400];
                snprintf(msg, sizeof msg, "No game files found: %s is missing.\n\nPut kz2.exe next to the "
                         "PS3_GAME folder of your decrypted dump, or pass the EBOOT.elf path as the first argument.%s%s",
                         eboot, kz2_session_log_path()[0] ? "\n\nLog: " : "", kz2_session_log_path());
                MessageBoxA(NULL, msg, "Killzone 2", MB_OK | MB_ICONERROR);
            }
#endif
            return 2;
        }
    }

    /* Runtime defaults (an explicit environment setting still wins), the general part of KZ3's list:
     *  PS3_CAMERA=0     no PlayStation Eye; the HLE reports one otherwise.
     *  RSX_LIVE_DRAW=1  the live-draw engine renders; RSX_LIVE_DRAW=0 selects the plain D3D12 backend.
     * KZ3's SPURS_TASKATTR_DESC=1 (patch 1005, KZ3's Bink task control block as the taskset argument) is left out:
     * ASSUMPTION until KZ2's SPURS task setup is mapped.
     *  LD_LOCAL_WRITEBACK  not set any more (= 0, off). It was `post`: local-memory colour targets
     *                   written back to guest memory at every sync point (patch 6008) once the post stage renders, on
     *                   the belief that the SPU post chain reads the scene target 0x7B0000. A later check showed the SPUs
     *                   read only main-memory surfaces (LD_POST_WB_DIAG), so the read-backs fed nobody; they cost the
     *                   walker ~60 ms of GPU waits per frame after the post park (frame 339 -> 294 ms).
     *                   LD_LOCAL_WRITEBACK=post restores the old behaviour (auto = always, a hex list = those surfaces).
     *  GCM_PARK_WAIT_MS=86400000  the FIFO walker waits at a JUMP-to-self park until the title patches it, as the RSX
     *                   does (KZ3 patch 1007's wait; its default is 30000 ms, then it resyncs get to put). In a level the
     *                   RSX parks every frame at the post stage's park (IO 0x01A8424C..0x01A8484C, EA 0x41D8424C..,
     *                   in the frame block) until the SPU job Gfx.Post.Unlock overwrites it (a 4-byte DMA put); one
     *                   post chain took more than 30 s on our slow SPU side, the resync skipped the frame tail with the
     *                   render fence release (NV406E label 0x4B, waited for at 0x48AE8) and the main thread waited
     *                   forever.
     *  LD_VTX_CACHE=1, LD_VTX_CACHE_MAIN=1  the live draw's draw payload cache (patch 2047, from KZ3) for local AND
     *                   main memory. Every frame the walker re-read each draw's indices, remapped
     *                   them and converted every referenced vertex to float4 (rsx_vertex_fetch_many and its helpers,
     *                   ~25 % of the walker's samples, ~9 ms a frame), although almost all of it is static geometry.
     *                   A draw whose full fetch state matches and whose source bytes are unchanged (tracked writes,
     *                   page stamps and a full byte compare of the sources) replays the payload it built before.
     *                   KZ2 keeps its vertex buffers in main memory (with local only, 0 hits). The New Sun: 85 % of
     *                   draws hit; LD_VTX_CACHE=verify checked 6.17 M hits byte for byte, 0 bad; A/B in
     *                   the RE notes "An earlier change". LD_VTX_CACHE=0 turns it off.
     *  PS3_VERBOSE=0    quiet log: per-event lines are counted, not printed (patch 6030; ~26 MB/min
     *                   verbose). Upstream's default is verbose whenever stderr is redirected, which a session log
     *                   always is. Set before the first ps3_log_verbose() call (each translation unit caches it).
     *                   With 7004: 0 of 4 load stops, 0 of 10 level starts quiet; an earlier change's quiet
     *                   level loads: the RE notes "An earlier change". */
    static const char* const kz2_env[][2] = { {"PS3_CAMERA", "0"}, {"RSX_LIVE_DRAW", "1"},
                                              {"GCM_PARK_WAIT_MS", "86400000"},
                                              {"LD_VTX_CACHE", "1"}, {"LD_VTX_CACHE_MAIN", "1"},
                                              {"PS3_VERBOSE", "0"} };
    for (const auto& e : kz2_env) {
        if (getenv(e[0])) continue;
#ifdef _WIN32
        char kv[64]; snprintf(kv, sizeof kv, "%s=%s", e[0], e[1]); _putenv(kv);
#else
        setenv(e[0], e[1], 0);
#endif
    }

    if (!alloc_guest_vm()) {
        fprintf(stderr, "ERROR: could not allocate the guest address space\n");
        return 1;
    }

    uint32_t entry = ppu_load_elf(eboot);
    if (!entry) {
        fprintf(stderr, "ERROR: could not load %s\n", eboot);
        return 1;
    }

    /* The runtime's GCM window defaults to 0x20000000, where KZ3 maps its own RSX main memory; KZ3 moved it to
     * 0x7F000000. Same default here until KZ2's cellGcmMapMainMemory ranges are known (ASSUMPTION: 0x7F000000 is free
     * in KZ2 too). KZ2_INJECT_BASE=<hex> overrides. */
    {
        const char* e = getenv("KZ2_INJECT_BASE");
        ppu_hle_inject_base = e ? (uint32_t)strtoul(e, nullptr, 16) : 0x7F000000u;
    }
    skip_intro_option();
    derive_vfs_root(eboot);
    printf("[boot] VFS root: %s\n", ppu_vfs_root);
    setup_update_dir();

    ppu_recomp_register();   /* lifted function table -> address map */
    ps3_load_prx_modules();  /* this game's lifted system PRX, if it has any */
    ppu_hle_init();          /* firmware import NID -> HLE handlers */
    ppu_sysprx_register();   /* boot-critical CRT */
    ppu_fs_register();       /* cellFs over the game directory */
    lv2_init_syscalls();     /* the lv2 syscall table */
    kz2_hle_register();      /* imports the runtime leaves unresolved (hle_kz2.cpp) */
    kz2_menu_install();      /* EXIT TO DESKTOP, Keyboard page: ExitAll and the Lua bridge (kz2_menu_pages.cpp, an earlier change) */
    kz2_prompts_register();  /* prompt glyph sets and keycaps: keys and label fonts for patches 2091-2093 */
    cellSaveData_register_ctx_handlers();   /* 9-argument User*Auto{Load,Save} (patch 3001) */
    {   /* title id from PARAM.SFO (BCUS98116) instead of the runtime default: save directory and SysCache id */
        char sfo[1100];
        snprintf(sfo, sizeof sfo, "%s/PS3_GAME/PARAM.SFO", ppu_vfs_root);
        cellGame_init_from_paramsfo(sfo);
    }

    g_ps3_guest_caller = harness_guest_caller;
    CreateThread(NULL, 4u * 1024 * 1024, frame_clock, NULL, 0, NULL);
    start_diagnostics();

    printf("\n[boot] dispatching entry OPD 0x%08X (stack top 0x%08X)\n\n", entry, STACK_TOP);
    if (getenv("KZ3_WAIT_ACCT")) kz3_wacct_name("ppu:main");   /* the thread that runs the guest entry */
    int rc = ppu_run(entry, STACK_TOP);
    printf("\n[boot] ppu_run returned %d (entry function unwound)\n", rc);
    kz2_log_shutdown();
    return g_sys_process_exit_called ? (int)g_sys_process_exit_code : 0;
}
