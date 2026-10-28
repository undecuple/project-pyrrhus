/* Killzone 2 port: "Exit to desktop" and the Keyboard page in the game's own front end (
 * ENHANCEMENT). Plan A of an earlier change (the RE notes "An earlier change" and "An earlier change"):
 *
 * 1. Page text. The browser's "file" fetch (1.29 @0x0049EA38; override list, KZ2_PAGE_LOG) first asks every loaded
 *    CachedJspResource for the page through the lookup @0x0049E5C0 and on a miss reads the file; either way the page
 *    TEXT reaches the parser (its <_s> scripts are compiled from that text, keyed by its MD5, so a cached chunk never
 *    shadows edited text: an earlier change). Re-data's plan A edited the lookup's answer, but the first main menu
 *    after boot is read from the file before CachedJspMainMenu.core is loaded (kz2-r47-m2: no lookup call at all), so
 *    the edit sits one level up: for
 *      .../kin/menu/mainmenu.jsp, .../kin/menu/campaign/options.jsp, .../kin/menu/online/game/options.jsp
 *    kz2_menu_fetch serves an edited copy (kz2_menu_text.h: the EXIT TO DESKTOP row, the KEYBOARD row of the options
 *    list) of the text the game itself would read (data_ps3.psarc + the 1.29 update's .pspatch, as FIOS serves it and
 *    as the 1.29 CachedJsp cores hold it), and for .../kin/menu/options/keyboardsettings(.jsp|_ingame.jsp) (no such
 *    file exists) the generated Keyboard page, in exactly the way the fetch serves a cache hit. The copies live in
 *    guest memory for the whole process; a served buffer is never rewritten. No game text is stored anywhere but in
 *    that memory: everything is made at run time from the player's own files.
 * 2. gModule:ExitAll(url): the Lua method's code @0x002C8068 (OPD 0xE92C18; only reached through the method table, no
 *    `bl` callers) is re-registered in the indirect-call map. url "pc:exit" posts WM_CLOSE to the game window
 *    (kz2_request_close in main.cpp: the same clean shutdown as the window's close button, exit code 0); any other
 *    url runs the original body.
 * 3. Keyboard page <-> host: PlayerProfile SetTimeZone(s) @0x00082E40 and GetTimeZone() @0x00A619FC (OPDs 0xE7AB70 /
 *    0xE7AB78; no page and no `bl` calls them) are re-registered the same way, as Project Helghast port/kz3/main.cpp does
 *    (its "Keyboard page" bridge, copied and adapted): a "kb:<cmd>" string goes to pad_kb_ui_cmd (cellPad.c, patch
 *    2038), the reply is what the next GetTimeZone() returns; anything else runs the original bodies.
 * All three hooks check the first instruction words before they install (1.29 EBOOT only).
 * KZ2_MENU_PAGES=0 turns the whole feature off (pages served unchanged, no re-registration).
 *
 * Guest memory: the pages and the reply live in the 16 MB inject window (VM_HLE_INJECT_SIZE) at inject_base +
 * 0x400000 .. +0x800000 (4 MB). ASSUMPTION: nothing else uses that part of the window (the runtime's users end below
 * +0x100000, KZ2's own scratch is at +0x100000, hle_kz2.cpp); demand-committed like the rest of the window.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <map>
#include <mutex>
#include <string>
#include <vector>

#include "ppu_recomp.h"
#include "kz2_menu_text.h"
#include "ps3emu/split_file.h"   /* patch 6034: data_ps3.psarc or its FAT32 parts .66600, .66601, ... */

extern "C" {
extern uint8_t* vm_base;
extern uint32_t ppu_hle_inject_base;
extern const char* ppu_vfs_root;
void ppu_register_function(uint64_t addr, void (*fn)(ppu_context*));
int  pad_kb_ui_cmd(const char* cmd, char* out, size_t n);                       /* cellPad.c (patch 2038) */
int  stbi_zlib_decode_buffer(char* obuffer, int olen, const char* ibuffer, int ilen);   /* stb_image (cellPngDec.c) */
const char* kz2_update_dir(void);                                                /* main.cpp: <..>/dev_hdd0/game/BCUS98116/USRDIR */
void ps3_indirect_call(ppu_context* ctx);
extern PPU_THREAD_LOCAL void (*g_trampoline_fn)(void*);
void kz2_request_close(const char* why);                                         /* main.cpp */
}

namespace {

std::mutex g_mu;
int g_on = -1;
uint32_t g_heap = 0, g_heap_end = 0;
uint32_t g_reply = 0;

bool on(void)
{
    if (g_on < 0) { const char* e = getenv("KZ2_MENU_PAGES"); g_on = !(e && e[0] == '0'); }
    return g_on == 1;
}

uint32_t be32(uint32_t ea) { const uint8_t* p = vm_base + ea; return (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]; }

std::string guest_string(uint32_t ea, size_t cap)
{
    if (ea < 0x10000u || ea >= 0xF0000000u) return std::string();
    const char* p = (const char*)(vm_base + ea);
    size_t n = 0;
    while (n < cap && p[n]) n++;
    return std::string(p, n);
}

/* bump allocation of a NUL-terminated copy; 0 when the area is full */
uint32_t guest_copy(const std::string& s)
{
    if (!g_heap) { g_heap = ppu_hle_inject_base + 0x400000u; g_heap_end = ppu_hle_inject_base + 0x800000u; g_reply = g_heap; g_heap += 0x1000u; }
    const uint32_t need = (uint32_t)((s.size() + 1u + 15u) & ~15u);
    if (g_heap + need > g_heap_end) return 0;
    const uint32_t ea = g_heap;
    memcpy(vm_base + ea, s.data(), s.size());
    vm_base[ea + s.size()] = 0;
    g_heap += need;
    return ea;
}

/* ---------------------------------------------------------------- the player's data_ps3.psarc (read only) */
/* Read through ps3emu/split_file.h (patch 6034), as the game's own opens are: a dump copied to FAT32 keeps the
 * archive as data_ps3.psarc.66600, .66601, ... and this reader sees the same bytes as from the single file. */
struct Psarc {
    ps3_sf* f = nullptr;
    char why[1200] = "";
    uint32_t block_size = 0, count = 0;
    std::vector<uint32_t> block;
    std::vector<uint64_t> esize, eoff;
    std::vector<uint32_t> efirst;
    std::map<std::string, uint32_t> names;   /* lower-case path without a leading '/' -> entry */
    bool ok = false;

    static uint64_t be(const uint8_t* p, int n) { uint64_t v = 0; for (int i = 0; i < n; i++) v = v << 8 | p[i]; return v; }

    bool open(const std::string& path)
    {
        f = ps3_sf_open(path.c_str(), why, sizeof why);
        if (!f) return false;
        uint8_t h[32];
        if (ps3_sf_read(f, h, 32) != 32 || memcmp(h, "PSAR", 4) || memcmp(h + 8, "zlib", 4)) return false;
        const uint32_t toc_len = (uint32_t)be(h + 12, 4), esz = (uint32_t)be(h + 16, 4);
        count = (uint32_t)be(h + 20, 4); block_size = (uint32_t)be(h + 24, 4);
        const uint32_t flags = (uint32_t)be(h + 28, 4);
        if ((flags & 4) || esz < 30 || toc_len < 32 + count * esz || block_size == 0 || toc_len > (64u << 20)) return false;
        std::vector<uint8_t> toc(toc_len - 32);
        if (ps3_sf_read(f, toc.data(), toc.size()) != toc.size()) return false;
        for (uint32_t i = 0; i < count; i++) {
            const uint8_t* e = toc.data() + (size_t)i * esz;
            efirst.push_back((uint32_t)be(e + 16, 4)); esize.push_back(be(e + 20, 5)); eoff.push_back(be(e + 25, 5));
        }
        int w = 1;
        while ((1ull << (8 * w)) < block_size) w++;
        for (size_t j = (size_t)count * esz; j + w <= toc.size(); j += w) block.push_back((uint32_t)be(toc.data() + j, w));
        std::string man;
        if (!read(0, &man)) return false;
        size_t s = 0; uint32_t idx = 1;
        for (size_t i = 0; i <= man.size(); i++) {
            if (i == man.size() || man[i] == '\n') {
                std::string n = man.substr(s, i - s);
                while (!n.empty() && n[0] == '/') n.erase(0, 1);
                for (char& c : n) if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
                names.emplace(n, idx++);
                s = i + 1;
            }
        }
        ok = true;
        return true;
    }
    bool read(uint32_t idx, std::string* out)
    {
        if (idx >= count) return false;
        uint64_t size = esize[idx];
        uint32_t b = efirst[idx];
        if (size > (64u << 20)) return false;
        out->clear(); out->reserve((size_t)size);
        uint64_t at = eoff[idx];   /* the archive is larger than 4 GB: 64-bit offsets across the parts */
        std::vector<char> in(block_size), tmp(block_size);
        while (out->size() < size) {
            if (b >= block.size()) return false;
            const uint32_t csize = block[b] ? block[b] : block_size;
            const uint64_t want64 = size - out->size();
            const uint32_t want = (uint32_t)(want64 < block_size ? want64 : block_size);
            if (csize > in.size()) in.resize(csize);
            if (ps3_sf_pread(f, at, in.data(), csize) != csize) return false;
            at += csize;
            if (csize == want) out->append(in.data(), csize);
            else {
                const int n = stbi_zlib_decode_buffer(tmp.data(), (int)tmp.size(), in.data(), (int)csize);
                if (n < 0) out->append(in.data(), csize);   /* as tools/psarc.py: a raw block shorter than block_size */
                else out->append(tmp.data(), (size_t)n);
            }
            b++;
        }
        out->resize((size_t)size);
        return true;
    }
    bool read_name(const std::string& lower_path, std::string* out)
    {
        auto it = names.find(lower_path);
        return it != names.end() && read(it->second, out);
    }
};

Psarc* g_psarc = nullptr;
bool psarc_page(const std::string& code, const std::string& page, std::string* out)
{
    if (!g_psarc) {
        g_psarc = new Psarc();
        const std::string p = std::string(ppu_vfs_root ? ppu_vfs_root : ".") + "/PS3_GAME/USRDIR/data_ps3.psarc";
        if (!g_psarc->open(p)) fprintf(stderr, "[kz2-menu] cannot read '%s'%s%s: the Keyboard page is off\n", p.c_str(),
                                       g_psarc->why[0] ? ": " : "", g_psarc->why);
        else fprintf(stderr, "[kz2-menu] %s: %u entries%s\n", p.c_str(), g_psarc->count,
                     g_psarc->f->nparts > 1 ? " (FAT32 split parts)" : "");
    }
    return g_psarc->ok && g_psarc->read_name("interface/svo/svml/" + code + "/kin/menu/" + page, out);
}

/* ---------------------------------------------------------------- the 1.29 update's patch for a file (FIOS .pspatch) */
/* MD5 (RFC 1321), only for the patch file name: MD5("/DATA_PS3/" + upper-case archive path), tools/assets/pspatch.py. */
std::string md5_hex_upper(const std::string& msg)
{
    static const uint32_t K[64] = {
        0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501, 0x698098d8, 0x8b44f7af,
        0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa,
        0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8, 0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8,
        0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
        0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665, 0xf4292244, 0x432aff97,
        0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1, 0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1,
        0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391 };
    static const int R[16] = { 7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21 };
    uint32_t h[4] = { 0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476 };
    std::string m = msg;
    const uint64_t bits = (uint64_t)msg.size() * 8u;
    m += (char)0x80;
    while (m.size() % 64 != 56) m += (char)0;
    for (int i = 0; i < 8; i++) m += (char)(bits >> (8 * i));
    for (size_t off = 0; off < m.size(); off += 64) {
        uint32_t w[16];
        for (int i = 0; i < 16; i++)
            w[i] = (uint32_t)(uint8_t)m[off + 4 * i] | (uint32_t)(uint8_t)m[off + 4 * i + 1] << 8 |
                   (uint32_t)(uint8_t)m[off + 4 * i + 2] << 16 | (uint32_t)(uint8_t)m[off + 4 * i + 3] << 24;
        uint32_t A = h[0], B = h[1], C = h[2], D = h[3];
        for (int i = 0; i < 64; i++) {
            uint32_t F; int g;
            if (i < 16) { F = (B & C) | (~B & D); g = i; }
            else if (i < 32) { F = (D & B) | (~D & C); g = (5 * i + 1) % 16; }
            else if (i < 48) { F = B ^ C ^ D; g = (3 * i + 5) % 16; }
            else { F = C ^ (B | ~D); g = (7 * i) % 16; }
            const uint32_t t = D; D = C; C = B;
            const uint32_t x = A + F + K[i] + w[g];
            const int r = R[(i / 16) * 4 + (i % 4)];
            B = B + ((x << r) | (x >> (32 - r)));
            A = t;
        }
        h[0] += A; h[1] += B; h[2] += C; h[3] += D;
    }
    static const char* hx = "0123456789ABCDEF";
    std::string o;
    for (int i = 0; i < 4; i++) for (int k = 0; k < 4; k++) { const uint8_t v = (uint8_t)(h[i] >> (8 * k)); o += hx[v >> 4]; o += hx[v & 15]; }
    return o;
}

/* Apply a .pspatch (format in tools/assets/pspatch.py) to src. false on a malformed patch. */
bool pspatch_apply(const std::string& d, const std::string& src, std::string* out)
{
    auto be = [&](size_t o) { return (uint32_t)(uint8_t)d[o] << 24 | (uint32_t)(uint8_t)d[o + 1] << 16 | (uint32_t)(uint8_t)d[o + 2] << 8 | (uint8_t)d[o + 3]; };
    if (d.size() < 20) return false;
    const uint32_t last = be(0), dlen = be(4), tsize = be(8);
    if (last < 12 || (last - 12) % 8 || (uint64_t)last + dlen + 8 != d.size()) return false;
    const uint32_t n = (last - 12) / 8 + 1;
    const size_t lit = (size_t)last + 8;
    out->clear(); out->reserve(tsize);
    for (uint32_t k = 0; k < n; k++) {
        const uint32_t a = be(12 + 8 * k), b = be(16 + 8 * k);
        const uint32_t start = a & 0x7FFFFFFFu, end = k + 1 < n ? (be(12 + 8 * (k + 1)) & 0x7FFFFFFFu) : tsize;
        if (end < start || end > tsize || start != out->size()) return false;
        const uint32_t len = end - start;
        if (a >> 31) { if ((uint64_t)b + len > src.size()) return false; out->append(src, b, len); }
        else { if ((uint64_t)b + len > dlen) return false; out->append(d, lit + b, len); }
    }
    return out->size() == tsize;
}

std::string slurp(const std::string& path)
{
    std::string s;
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return s;
    char buf[65536];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) s.append(buf, n);
    fclose(f);
    return s;
}

/* The text the game reads for interface/svo/svml/<code>/kin/menu/<page>: the disc archive's file with the 1.29 patch
 * applied when the update has one (what FIOS serves, and what the 1.29 CachedJsp cores hold). why: how it was made. */
bool page_text(const std::string& code, const std::string& page, std::string* out, std::string* why)
{
    const std::string rel = "interface/svo/svml/" + code + "/kin/menu/" + page;
    std::string disc;
    if (!psarc_page(code, page, &disc)) { *why = "not in the archive"; return false; }
    std::string up = rel;
    for (char& c : up) if (c >= 'a' && c <= 'z') c = (char)(c - 32);
    const char* ud = kz2_update_dir();
    const std::string pf = std::string(ud && *ud ? ud : "") + "/patch_data_ps3/" + md5_hex_upper("/DATA_PS3/" + up) + ".pspatch";
    const std::string patch = (ud && *ud) ? slurp(pf) : std::string();
    if (patch.empty()) { *out = disc; *why = "disc"; return true; }
    if (!pspatch_apply(patch, disc, out)) { *out = disc; *why = "disc (the 1.29 patch did not apply)"; return true; }
    *why = "disc + 1.29 patch";
    return true;
}

/* ---------------------------------------------------------------- page edits */
std::map<std::string, uint32_t> g_served;                  /* fetch path -> guest copy (0 = not served) */
std::map<std::string, std::vector<std::string>> g_descs;   /* language -> controller scheme captions */

bool ends_with(const std::string& s, const char* t) { size_t n = strlen(t); return s.size() >= n && s.compare(s.size() - n, n, t) == 0; }

/* "source:interface/svo/svml/<code>/kin/menu/..." -> code */
std::string lang_of(const std::string& path)
{
    size_t p = path.find("svml/");
    if (p == std::string::npos) return std::string();
    size_t e = path.find('/', p + 5);
    return e == std::string::npos ? std::string() : path.substr(p + 5, e - p - 5);
}

std::vector<std::string>& descs_for(const std::string& code)
{
    if (!g_descs.count(code)) {
        std::string t, why;
        std::vector<std::string> d;
        if (page_text(code, "campaign/options.jsp", &t, &why)) try { d = kz2mt::extract_descriptions(t); } catch (const kz2mt::Anchor&) {}
        g_descs[code] = d;
    }
    return g_descs[code];
}

/* One of the three menu pages with the EXIT TO DESKTOP and KEYBOARD rows; 0 = serve the original (not edited). */
uint32_t edit_page(const std::string& path, const std::string& page, const char* kind)
{
    const std::string code = lang_of(path);
    std::string text, why;
    if (!page_text(code, page, &text, &why)) {
        fprintf(stderr, "[kz2-menu] %s: %s, served by the game as usual\n", path.c_str(), why.c_str());
        return 0;
    }
    std::string t = text, fail;
    int rows = 0;
    try {
        std::string m, ok = "\"OK\"", cancel = "\"CANCEL\"", sp, w2;
        if (!kz2mt::popup_strings(text, &m, &ok, &cancel) && page_text(code, "campaign/options.jsp", &sp, &w2))
            kz2mt::popup_strings(sp, &m, &ok, &cancel);
        t = kz2mt::exit_page(t, kind, kz2mt::LABEL, kz2mt::MSG, ok, cancel);
        rows++;
    } catch (const kz2mt::Anchor& e) { fail += std::string(" exit row: ") + e.what() + ";"; }
    try { t = kz2mt::patch_options(t); rows++; } catch (const kz2mt::Anchor& e) { fail += std::string(" keyboard row: ") + e.what() + ";"; }
    const std::vector<std::string> bad = kz2mt::check(t);
    const uint32_t ea = (rows && bad.empty()) ? guest_copy(t) : 0;
    fprintf(stderr, "[kz2-menu] %s (%s, %s, %zu -> %zu bytes): %s%s%s\n", path.c_str(), kind, why.c_str(), text.size(), t.size(),
            !rows ? "unchanged" : !bad.empty() ? "edit fails the tag check, unchanged" : !ea ? "no guest memory left, unchanged" :
            rows == 2 ? "EXIT TO DESKTOP and KEYBOARD rows added" : "one row added", fail.empty() ? "" : " |", fail.c_str());
    return ea;
}

uint32_t keyboard_page(const std::string& path, bool ingame)
{
    const std::string code = lang_of(path);
    std::string gamma, why;
    if (!page_text(code, ingame ? "options/gammacorrection_ingame.jsp" : "options/gammacorrection.jsp", &gamma, &why)) {
        fprintf(stderr, "[kz2-menu] %s: no gamma-correction page for '%s' (%s), Keyboard page not served\n", path.c_str(), code.c_str(), why.c_str());
        return 0;
    }
    try {
        const std::vector<std::string>& d = descs_for(code);
        std::string page = kz2mt::keyboard_page(gamma, d, ingame);
        {   /* KZ2_KB_PAGE_TEST (diagnostic, an earlier change): gamma = the gamma page itself; noscript = without keyboardscript */
            const char* tm = getenv("KZ2_KB_PAGE_TEST");
            if (tm && !strcmp(tm, "gamma")) page = gamma;
            if (tm && !strcmp(tm, "noscript")) {
                size_t a = page.find("<_s name=\"keyboardscript\" >"), b = page.find("</_s>", a);
                if (a != std::string::npos && b != std::string::npos) page.erase(a, b + 5 - a);
            }
            if (tm) fprintf(stderr, "[kz2-menu] KZ2_KB_PAGE_TEST=%s\n", tm);
        }
        const uint32_t ea = guest_copy(page);
        fprintf(stderr, "[kz2-menu] %s: Keyboard page generated from the %s gamma page (%zu bytes, %zu controller schemes)%s\n",
                path.c_str(), why.c_str(), page.size(), d.size(), ea ? "" : ", no guest memory left");
        return ea;
    } catch (const kz2mt::Anchor& e) {
        fprintf(stderr, "[kz2-menu] %s: Keyboard page not generated: %s\n", path.c_str(), e.what());
        return 0;
    }
}

/* ---------------------------------------------------------------- re-registered script methods */
void (*s_exit_orig)(ppu_context*) = nullptr;
void (*s_set_orig)(ppu_context*) = nullptr;
void (*s_get_orig)(ppu_context*) = nullptr;
char s_kb_reply[1024];
int  s_kb_pending = 0;

/* @0x002C8068 (1.29): gModule:ExitAll(url) -> Game 0x7B570(0x11B0540, url) */
void kz2_exit_all(ppu_context* ctx)
{
    const std::string url = guest_string((uint32_t)ctx->gpr[4], 256);
    static int n = 0;
    if (n++ < 8) fprintf(stderr, "[kz2-menu] ExitAll(\"%s\")\n", url.c_str());
    if (url == kz2mt::URL) { kz2_request_close("EXIT TO DESKTOP"); return; }
    if (s_exit_orig) s_exit_orig(ctx);
}

/* @0x00082E40 (1.29): PlayerProfile::SetTimeZone(this, s): strcpy into this+0xAFC unless s starts with "kb:" */
void kz2_kb_set(ppu_context* ctx)
{
    const uint32_t ea = (uint32_t)ctx->gpr[4];
    if (ea >= 0x10000u && ea < 0xF0000000u && !memcmp(vm_base + ea, "kb:", 3)) {
        const std::string cmd = guest_string(ea + 3, 127);
        std::lock_guard<std::mutex> lk(g_mu);
        pad_kb_ui_cmd(cmd.c_str(), s_kb_reply, sizeof s_kb_reply);
        s_kb_pending = 1;
        static int n = 0;
        if (n++ < 6 || (cmd.compare(0, 3, "key") && cmd.compare(0, 4, "poll") && cmd.compare(0, 5, "state") &&
                        cmd.compare(0, 3, "dup") && cmd.compare(0, 4, "hint") && cmd.compare(0, 3, "sel") &&
                        cmd.compare(0, 7, "caphint") && cmd.compare(0, 2, "cf")))
            fprintf(stderr, "[kb-page] '%s' -> '%s'\n", cmd.c_str(), s_kb_reply);
        return;
    }
    if (s_set_orig) s_set_orig(ctx);
}

/* @0x00A619FC (1.29): PlayerProfile::GetTimeZone(this) -> this+0xAFC, or the pending page reply */
void kz2_kb_get(ppu_context* ctx)
{
    {
        std::lock_guard<std::mutex> lk(g_mu);
        if (s_kb_pending && g_reply) {
            const size_t n = strlen(s_kb_reply);
            s_kb_pending = 0;
            memcpy(vm_base + g_reply, s_kb_reply, n + 1);
            ctx->gpr[3] = g_reply;
            return;
        }
    }
    if (s_get_orig) s_get_orig(ctx);
}

void (*lifted_fn(uint32_t addr))(ppu_context*)
{
    for (uint64_t i = 0; i < function_table_count; i++)
        if ((uint32_t)function_table[i].addr == addr) return function_table[i].func;
    return nullptr;
}

}  // namespace

/* The file fetch (1.29 @0x0049EA38, handler r3; called by its Process @0x0049ED98 in state 3). For our pages it serves
 * the text the way the fetch's own cache hit does (0x49EAFC..0x49EB64): size = strlen into +0x14 and +8, the listener
 * (+0x18) slot 0x10 is called with (+0x1C, &{1, 0, size, 0}), the text pointer goes to +0x24, state +0xC = 5, r3 = 0;
 * the next Process delivers +0x24 (0x49E938). Returns 1 when served (the caller skips the lifted fetch). */
extern "C" int kz2_menu_fetch(ppu_context* ctx)
{
    if (!on()) return 0;
    const uint32_t h = (uint32_t)ctx->gpr[3];
    const uint32_t str = vm_read32(h + 0x20), listener = vm_read32(h + 0x18);
    if (!str || !listener) return 0;
    const std::string path = guest_string(str + 0x10, 512);
    if (path.find("/kin/menu/") == std::string::npos) return 0;
    const char* kind = ends_with(path, "/kin/menu/mainmenu.jsp") ? "main" :
                       ends_with(path, "/kin/menu/campaign/options.jsp") ? "sp" :
                       ends_with(path, "/kin/menu/online/game/options.jsp") ? "mp" : nullptr;
    const bool kb = ends_with(path, "/kin/menu/options/keyboardsettings.jsp"), kbi = ends_with(path, "/kin/menu/options/keyboardsettings_ingame.jsp");
    if (!kind && !kb && !kbi) return 0;
    uint32_t ea = 0;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        auto it = g_served.find(path);
        if (it != g_served.end()) ea = it->second;
        else {
            const size_t slash = path.find("/kin/menu/");
            ea = kind ? edit_page(path, path.substr(slash + 10), kind) : keyboard_page(path, kbi);
            g_served[path] = ea;
        }
    }
    if (!ea) return 0;   /* the lifted fetch runs (unedited page; or, for the Keyboard page, a file that does not exist) */
    const uint32_t size = (uint32_t)strlen((const char*)vm_base + ea);
    vm_write32(h + 0x14, size);
    vm_write32(h + 0x08, size);
    /* listener->vtable[0x10/4](listener, arg, &info) with info on a scratch frame below the caller's stack pointer */
    const uint64_t r1 = ctx->gpr[1], lr = ctx->lr;
    const uint32_t sp = (uint32_t)((r1 - 0x100u) & ~0xFull);
    vm_write64(sp, r1);                       /* back chain, as stdu would leave it */
    const uint32_t info = sp + 0x80u;
    vm_write32(info, 1); vm_write32(info + 4, 0); vm_write32(info + 8, size); vm_write32(info + 12, 0);
    ctx->gpr[1] = sp;
    ctx->gpr[3] = listener; ctx->gpr[4] = vm_read32(h + 0x1C); ctx->gpr[5] = info;
    ctx->ctr = vm_read32(vm_read32(vm_read32(listener) + 0x10));
    ps3_indirect_call(ctx);
    while (g_trampoline_fn) { void (*f)(void*) = g_trampoline_fn; g_trampoline_fn = 0; f(ctx); }
    ctx->gpr[1] = r1; ctx->lr = lr;
    vm_write32(h + 0x24, ea);
    vm_write32(h + 0x0C, 5);
    ctx->gpr[3] = 0;
    return 1;
}

/* After ppu_recomp_register (the lifted table) and before the guest runs. */
extern "C" void kz2_menu_install(void)
{
    if (!on()) { fprintf(stderr, "[kz2-menu] off (KZ2_MENU_PAGES=0)\n"); return; }
    {
        std::lock_guard<std::mutex> lk(g_mu);
        if (!guest_copy(std::string())) { fprintf(stderr, "[kz2-menu] no guest memory: off\n"); g_on = 0; return; }
    }
    /* first words: stdu r1 (0xF821....) for ExitAll and SetTimeZone, addic r3,r3,0xAFC (0x30630AFC) for GetTimeZone */
    const uint32_t exit_ea = 0x002C8068u, set_ea = 0x00082E40u, get_ea = 0x00A619FCu;
    const bool exit_ok = (be32(exit_ea) >> 16) == 0xF821u && be32(exit_ea + 12) == 0x3C60011Bu;   /* lis r3,0x11B */
    const bool kb_ok = (be32(set_ea) >> 16) == 0xF821u && be32(get_ea) == 0x30630AFCu;
    s_exit_orig = exit_ok ? lifted_fn(exit_ea) : nullptr;
    s_set_orig = kb_ok ? lifted_fn(set_ea) : nullptr;
    s_get_orig = kb_ok ? lifted_fn(get_ea) : nullptr;
    if (s_exit_orig) ppu_register_function(exit_ea, kz2_exit_all);
    if (s_set_orig && s_get_orig) { ppu_register_function(set_ea, kz2_kb_set); ppu_register_function(get_ea, kz2_kb_get); }
    fprintf(stderr, "[kz2-menu] on: pages served by the file fetch 0x0049EA38; ExitAll 0x%08X %s; Keyboard page bridge "
                    "SetTimeZone 0x%08X / GetTimeZone 0x%08X %s; guest buffers 0x%08X..0x%08X\n",
            exit_ea, s_exit_orig ? "hooked" : "NOT hooked (unknown EBOOT)", set_ea, get_ea,
            (s_set_orig && s_get_orig) ? "hooked" : "NOT hooked (unknown EBOOT)", g_reply, g_heap_end);
}
