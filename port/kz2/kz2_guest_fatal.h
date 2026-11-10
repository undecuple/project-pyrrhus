/* Killzone 2 port: the game's own fatal paths (public #49). Pure helpers, no ps3recomp types, so
 * tools/runtime/test_guest_fatal.sh can build them on the host with a fake guest memory.
 *
 * What #49 was (static, 1.29 EBOOT, tools/re/ppcdis.py; the RE notes "An earlier change"):
 *  - abort() @0x00028030 (v1.01 @0x00027F60) is `*(int*)0 = 0x0DEADCA7; blr`: on the PS3 the store faults and the
 *    process dies there. ps3recomp drops stores into the first page ([null-write] ... DROPPED), so the lifted abort
 *    RETURNS, and its callers are noreturn calls the compiler placed right before the next function:
 *    std::terminate @0x007D9AA0 (handler *0xF4E030, then abort) falls into std::unexpected @0x007D9AE0 (handler
 *    *0xF4E034, then terminate), the default handler @0x007D9B20 is abort again. abort returning turns one fatal
 *    error into terminate -> unexpected -> terminate ... until the host stack overflows (0xC00000FD).
 *  - Lua's luaD_throw @0x003F3160 (v1.01 @0x003E6D10): L->errorJmp (+0x5C) set -> longjmp; else L->status (+6) =
 *    errcode, G(L)->panic (+0x10 -> +0x58) if any, then exit(1) @0x007B7D60 (v1.01 @0x007AA3D8). KZ2 never calls
 *    exit in normal play (the EXIT TO DESKTOP row closes the window instead), so an unprotected Lua error is the
 *    game giving up.
 * Lua 5.1 layout as this build has it (read from 0x3F2AA0 luaS_newlstr, 0x3F9870 luaV_gettable): TValue 8 bytes
 * {value u32, tt u32}, LUA_TSTRING 4, TString {.., +0xC len, +0x10 chars}; lua_State +8 top, +0x10 l_G. */
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace kz2fatal {

enum : uint32_t {
    ABORT_129 = 0x00028030u, ABORT_101 = 0x00027F60u, ABORT_POISON = 0x0DEADCA7u,
    L_TOP = 0x08, L_GLOBAL = 0x10, L_ERRORJMP = 0x5C, G_PANIC = 0x58,
    TS_LEN = 0x0C, TS_CHARS = 0x10, LUA_TSTRING = 4,
};

/* PS3 user space starts at 0x10000; the guest's 32-bit space ends at 4 GB; the port's own windows sit above
 * 0xF0000000 only for RSX mappings, never for heap objects. */
inline bool plausible_ptr(uint32_t p) { return p >= 0x10000u && p < 0xF0000000u && (p & 3u) == 0; }

/* The error value on top of L's stack as text (luaG_runerror has pushed "chunk:line: message" before luaD_throw).
 * Fail soft: every pointer is checked with plausible_ptr before it is read, a length past MAX_TEXT counts as garbage,
 * the copy is bounded by cap and non-printable bytes become '?'. Returns 1 with msg filled, 0 (msg "") when the top is
 * not a readable string. */
enum : uint32_t { MAX_TEXT = 0x10000u };
template <class R32, class R8>
inline int read_top_text(uint32_t L, R32 rd32, R8 rd8, char* msg, size_t cap)
{
    if (cap) msg[0] = 0;
    if (!plausible_ptr(L) || cap == 0) return 0;
    const uint32_t top = rd32(L + L_TOP);
    if (!plausible_ptr(top) || top < 8u) return 0;
    const uint32_t v = rd32(top - 8u), tt = rd32(top - 4u);
    if (tt != LUA_TSTRING || !plausible_ptr(v)) return 0;
    uint32_t n = rd32(v + TS_LEN);
    if (n > MAX_TEXT) return 0;
    if (n > cap - 1) n = (uint32_t)(cap - 1);
    for (uint32_t i = 0; i < n; i++) {
        const uint8_t c = rd8(v + TS_CHARS + i);
        msg[i] = (c >= 0x20 && c < 0x7F) ? (char)c : '?';
    }
    msg[n] = 0;
    return 1;
}

/* What luaD_throw(L, errcode) is about to do, and the error text when it can be read.
 * rd32(ea) / rd8(ea) read guest memory (big-endian words already swapped). Returns:
 *   0 = protected (errorJmp set): a Lua error that a pcall catches; msg = the error text only when protected_text
 *       is set (the #49 trigger is such an error), else "";
 *   1 = unprotected with a plausible lua_State: the game will call exit(1); msg = the error string or "";
 *   2 = the lua_State pointer itself is not a pointer (L < 0x10000 and the like): msg empty. */
template <class R32, class R8>
inline int classify_throw(uint32_t L, R32 rd32, R8 rd8, char* msg, size_t cap, bool protected_text = false)
{
    if (cap) msg[0] = 0;
    if (!plausible_ptr(L)) return 2;
    if (rd32(L + L_ERRORJMP) != 0) {
        if (protected_text) read_top_text(L, rd32, rd8, msg, cap);
        return 0;
    }
    read_top_text(L, rd32, rd8, msg, cap);
    return 1;
}

/* Cap for the protected-error line: the first PROTECTED_LOG_CAP per session, all of them with
 * KZ2_LUA_LOG=1. n = how many were already printed. */
enum : unsigned { PROTECTED_LOG_CAP = 8u };
inline bool protected_log_allowed(unsigned n, const char* env) { return (env && env[0] == '1') || n < PROTECTED_LOG_CAP; }

}  // namespace kz2fatal
