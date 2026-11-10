/* Exercise the real unwind helper and generated host continuation, with
 * synthetic guest registers. Real lifted-fixture checks are separate. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unordered_map>
#include <thread>
#include "kz2_lua_unwind.h"

struct ppu_context { uint64_t gpr[32] = {}; uint64_t lr = 0; };
#define PPU_MM_SNAP
static thread_local void (*g_trampoline_fn)(void*) = nullptr;
#define DRAIN_TRAMPOLINE(c) do { while (g_trampoline_fn) { auto f = g_trampoline_fn; g_trampoline_fn = nullptr; f(c); } } while (0)
static thread_local int depth, vsp, callbacks, destructors, returned, nesting, mode;
static thread_local uint32_t outer_buffer;
static thread_local std::unordered_map<uint32_t, ppu_context> saved;
extern "C" int* ps3_ppu_dispatch_depth_slot(void) { return &depth; }
extern "C" int* ps3_ppu_vcall_sp_slot(void) { return &vsp; }
static void callback(ppu_context*);
static void func_007C38E8(ppu_context* c) { saved[kz2lua::aligned((uint32_t)c->gpr[3])] = *c; c->gpr[3] = 0; }
static void restore(ppu_context* c)
{
    uint32_t p = kz2lua::aligned((uint32_t)c->gpr[3]);
    uint32_t value = (uint32_t)c->gpr[4];
    *c = saved.at(p); c->gpr[3] = value ? value : 1;
}
#include LUA_FIXTURE
struct Guard { ~Guard() { destructors++; } };
static void callback(ppu_context* c)
{
    callbacks++;
    if (!mode) return;
    Guard cleanup;
    const uint32_t own = (uint32_t)c->gpr[1] + 0x74;
    if ((mode == 2 || mode == 3) && !nesting) {
        outer_buffer = own;
        nesting++;
        func_00100000(c);
        nesting--;
        return;
    }
    c->gpr[3] = mode == 3 ? outer_buffer : own;
    c->gpr[4] = 0;  // libc longjmp(0) must become 1.
    c->gpr[14] = 0xDEADBEEF;
    depth += 7; vsp += 8;
    kz2lua::jump(c, restore);
    returned++;
}
static void check(bool good, const char* what) { if (!good) { fprintf(stderr, "FAIL lua-unwind: %s\n", what); exit(1); } }
static void series()
{
    for (int kind = 0; kind < 4; kind++) {
        for (int i = 0; i < 300; i++) {
            ppu_context c; c.gpr[1] = 0x100000; c.gpr[14] = 0x12345678;
            depth = 3; vsp = 4; callbacks = destructors = returned = nesting = 0; mode = kind;
            func_00100000(&c);
            check(returned == 0, "guest longjmp returned into abandoned caller");
            check(c.gpr[1] == 0x100000 && c.gpr[14] == 0x12345678, "entry register snapshots changed");
            check(depth == 3 && vsp == 4, "dispatch counters leaked");
            check(destructors == (kind == 0 ? 0 : kind == 1 ? 1 : 2), "host cleanup skipped");
            check(c.gpr[3] == (kind == 1 || kind == 3 ? 1u : 0u), "wrong continuation result");
        }
    }
    check(!kz2lua::Frame(nullptr).matches(kz2lua::Jump{nullptr, 1}), "unarmed frame matched");
}
int main()
{
    series();
    std::thread a(series), b(series); a.join(); b.join();
    puts("PASS lua-unwind: normal, nested, outer-target, repeated, thread-isolated and host cleanup");
}
