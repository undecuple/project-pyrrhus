/* Host test for port/kz2/kz2_guest_fatal.h (public #49): luaD_throw's classification on a fake
 * guest memory, plus the override rows the abort / luaD_throw / exit bodies need in both EBOOT lists.
 *   nix develop --command tools/sandbox.sh -- tools/runtime/test_guest_fatal.sh */
#include "kz2_guest_fatal.h"
#include <stdio.h>
#include <map>
#include <string>
#include <fstream>
#include <sstream>

static std::map<uint32_t, uint8_t> mem;
static void w32(uint32_t a, uint32_t v) { for (int i = 0; i < 4; i++) mem[a + i] = (uint8_t)(v >> (24 - 8 * i)); }
static uint32_t r32(uint32_t a) { uint32_t v = 0; for (int i = 0; i < 4; i++) v = (v << 8) | (mem.count(a + i) ? mem[a + i] : 0); return v; }
static uint8_t r8(uint32_t a) { return mem.count(a) ? mem[a] : 0; }
static int fails = 0;
#define CHECK(c, ...) do { if (!(c)) { fprintf(stderr, "FAIL: " __VA_ARGS__); fprintf(stderr, "\n"); fails++; } } while (0)

static std::string slurp(const char* p) { std::ifstream f(p); std::stringstream s; s << f.rdbuf(); return s.str(); }
static bool has_row(const std::string& t, const char* addr)
{
    size_t i = 0;
    while ((i = t.find(addr, i)) != std::string::npos) { if (i == 0 || t[i - 1] == '\n') return true; i++; }
    return false;
}

int main()
{
    using namespace kz2fatal;
    char msg[64];
    /* #49's case: L = 1 (and 0) are not lua_States */
    CHECK(classify_throw(1, r32, r8, msg, sizeof msg) == 2 && msg[0] == 0, "L=1 must be 'not a pointer'");
    CHECK(classify_throw(0, r32, r8, msg, sizeof msg) == 2, "L=0 must be 'not a pointer'");
    CHECK(classify_throw(0x20000002u, r32, r8, msg, sizeof msg) == 2, "unaligned L");
    /* a lua_State with a pcall around it: errorJmp set -> nothing to report */
    const uint32_t L = 0x20000000u, top = 0x20001010u, ts = 0x20002000u;
    w32(L + L_ERRORJMP, 0x20003000u); w32(L + L_TOP, top);
    CHECK(classify_throw(L, r32, r8, msg, sizeof msg) == 0, "protected throw must not report");
    /* unprotected with a string on top */
    w32(L + L_ERRORJMP, 0);
    const char* text = "attempt to index a nil value";
    w32(top - 8, ts); w32(top - 4, LUA_TSTRING); w32(ts + TS_LEN, (uint32_t)strlen(text));
    for (size_t i = 0; i < strlen(text); i++) mem[ts + TS_CHARS + (uint32_t)i] = (uint8_t)text[i];
    CHECK(classify_throw(L, r32, r8, msg, sizeof msg) == 1 && !strcmp(msg, text), "message text: got '%s'", msg);
    /* truncation and a non-printable byte */
    char small[8];
    CHECK(classify_throw(L, r32, r8, small, sizeof small) == 1 && !strcmp(small, "attempt"), "truncation: '%s'", small);
    mem[ts + TS_CHARS] = 0x01;
    CHECK(classify_throw(L, r32, r8, msg, sizeof msg) == 1 && msg[0] == '?', "non-printable byte");
    /* top of stack not a string (a number): unprotected, empty text */
    w32(top - 4, 3);
    CHECK(classify_throw(L, r32, r8, msg, sizeof msg) == 1 && msg[0] == 0, "non-string top");
    /* negative control: the same state with errorJmp set again is silent */
    w32(L + L_ERRORJMP, 0x20003000u);
    CHECK(classify_throw(L, r32, r8, msg, sizeof msg) == 0, "negative control");

    /* the override rows and bodies, both EBOOTs */
    const std::string o129 = slurp("port/kz2/ppu_overrides.txt"), o101 = slurp("port/kz2/ppu_overrides-101.txt");
    const std::string body = slurp("port/kz2/kz2_ppu_overrides.cpp");
    const char* rows129[] = {"00028030", "003F3160", "007B7D60", "003F9870"}, *rows101[] = {"00027F60", "003E6D10", "007AA3D8", "003ED420"};
    for (const char* a : rows129) {
        CHECK(has_row(o129, a), "ppu_overrides.txt lacks %s", a);
        CHECK(body.find(std::string("PPU_OVERRIDE_") + a) != std::string::npos, "no body for %s", a);
    }
    for (const char* a : rows101) {
        CHECK(has_row(o101, a), "ppu_overrides-101.txt lacks %s", a);
        CHECK(body.find(std::string("PPU_OVERRIDE_") + a) != std::string::npos, "no body for %s", a);
    }
    CHECK(ABORT_129 == 0x28030u && ABORT_101 == 0x27F60u && ABORT_POISON == 0x0DEADCA7u, "constants");
    if (fails) { fprintf(stderr, "test_guest_fatal: %d failure(s)\n", fails); return 1; }
    return 0;
}
