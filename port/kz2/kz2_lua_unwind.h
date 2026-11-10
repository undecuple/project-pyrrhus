/* Host unwinding for the game's guest setjmp/longjmp boundaries (issue #49).
 * The guest routines still save/restore every register. A host exception carries
 * control back to the generated continuation, preserving C++ host cleanup.
 * The same failure class was found in the Ratchet & Clank port; implemented
 * independently here. No game code or other port's implementation is copied.
 * KZ2_LUA_UNWIND=0 restores the old behavior for diagnostic comparisons. */
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

extern "C" int* ps3_ppu_dispatch_depth_slot(void);
extern "C" int* ps3_ppu_vcall_sp_slot(void);

namespace kz2lua {

inline bool enabled()
{
    static const bool on = [] { const char* e = getenv("KZ2_LUA_UNWIND"); return !(e && e[0] == '0'); }();
    return on;
}

inline uint32_t aligned(uint32_t p) { return (p + 15u) & ~15u; }

struct Jump {
    void* ctx;
    uint32_t buffer;
};

template <class Context, class Restore>
inline void jump(Context* ctx, Restore restore)
{
    const uint32_t buffer = aligned((uint32_t)ctx->gpr[3]);
    restore(ctx);
    if (enabled()) throw Jump{ctx, buffer};
}

struct Frame {
    void* ctx;
    uint32_t buffer = 0;
    int depth = 0, vsp = 0;

    explicit Frame(void* p) : ctx(p) {}
    void arm(uint32_t p)
    {
        buffer = aligned(p);
        depth = *ps3_ppu_dispatch_depth_slot();
        vsp = *ps3_ppu_vcall_sp_slot();
    }
    bool matches(const Jump& j) const { return buffer && j.ctx == ctx && j.buffer == buffer; }
    void land() const
    {
        *ps3_ppu_dispatch_depth_slot() = depth;
        *ps3_ppu_vcall_sp_slot() = vsp;
        static thread_local unsigned logged = 0;
        if (logged++ < 16)
            fprintf(stderr, "[lua-unwind] caught guest longjmp buffer=0x%08X; resuming protected continuation\n", buffer);
    }
};

} // namespace kz2lua
