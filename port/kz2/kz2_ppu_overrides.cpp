/* Killzone 2 port: host replacements for lifted PPU functions (ps3recomp patch 1018, `ppu_lifter --overrides`).
 * Each address in port/kz2/ppu_overrides.txt gets its lifted body renamed func_X__lifted and PPU_OVERRIDE_X defined
 * in ppu_overrides.h; the host's func_X lives here, inside #ifdef PPU_OVERRIDE_X, so a lift without the row still
 * builds. Pattern from Project Helghast port/net/kz3_net_hooks.h (wrap the lifted body, keep r1/r2/lr). */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ppu_overrides.h"   /* ppu_recomp.h + the PPU_OVERRIDE_* announcements */

/* @0x00A5A7B0 (1.29) / @0x00A463E0 (v1.01, same 32-byte prologue): the loop the RPCS3 wiki's "Disable Post
 * Processing on SPU" patch cuts (the RE notes); patched instruction 1.29 0xA5A7CC =
 * v1.01 0xA463FC `lhz r20,0xA(r4)` -> `lbz r20,0x89(r4)`. r3 = owner (bits ORed into +0xAC), r4 = a list whose u16 +0xA is the item
 * count, r5 = items (8 bytes each); every item goes through func_0038F020 / func_0038F0F0.
 *
 * KZ2_SPU_POST=0 (ENHANCEMENT, off by default): the patch's effect. The patched code compares 0 with u8 +0x89 before
 * the first iteration and re-reads u16 +0xA after each one, so: u8 +0x89 == 0 -> the loop never runs (return, as the
 * lifted body does for count 0: it only saves and restores registers); otherwise the lifted body runs unchanged
 * (the case u16 +0xA == 0 with u8 +0x89 != 0 is not modelled; it is logged).
 * KZ2_POST_LOG=N: log the first N calls (lr, r3, r4, count, byte +0x89, r5), diagnostic. */
[[maybe_unused]] static void kz2_spu_post_list(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static int mode = -1, log_left = -1;
    if (mode < 0) {
        const char* e = getenv("KZ2_SPU_POST");
        mode = (e && e[0] == '0') ? 0 : 1;
        const char* l = getenv("KZ2_POST_LOG");
        log_left = l ? atoi(l) : 0;
    }
    const uint32_t list = (uint32_t)ctx->gpr[4];
    const uint16_t count = vm_read16(list + 0xA);
    const uint8_t b89 = vm_read8(list + 0x89);
    if (log_left > 0) {
        log_left--;
        fprintf(stderr, "[kz2-post] lr=0x%08X r3=0x%08X list=0x%08X count=%u b89=%u items=0x%08X mode=%d\n",
                (uint32_t)ctx->lr, (uint32_t)ctx->gpr[3], list, count, b89, (uint32_t)ctx->gpr[5], mode);
    }
    if (mode == 0) {
        if (b89 == 0) return;
        if (count == 0) {
            static int warned = 0;
            if (!warned++) fprintf(stderr, "[kz2-post] count 0 with b89=%u: not modelled, lifted body runs\n", b89);
        }
    }
    lifted(ctx);
}

#ifdef PPU_OVERRIDE_00A5A7B0
void func_00A5A7B0(ppu_context* ctx) { kz2_spu_post_list(ctx, func_00A5A7B0__lifted); }   // @0x00A5A7B0 (1.29)
#endif
#ifdef PPU_OVERRIDE_00A463E0
void func_00A463E0(ppu_context* ctx) { kz2_spu_post_list(ctx, func_00A463E0__lifted); }   // @0x00A463E0 (v1.01)
#endif

/* @0x00045568 (v1.01) / @0x00045DB0 (1.29, same first 48 bytes): the GCM user-command handler the game registers
 * (cellGcmSetUserHandler(opd 0xE68BE8), called by the runtime for every user command in the FIFO, from whichever
 * thread drains it). Body: cmd != 0 -> `obj = cmd; obj->vtable[2](obj)` (lwz r4,0(r3); lwz r4,8(r4); lwz r4,0(r4);
 * bctrl). So the GPU stream carries object pointers whose virtual method the PPU runs at that point of the frame;
 * one of them is 0x48660 (two-party countdown at 0xEC1134 that writes label 0x49 = 1, which the FIFO acquires).
 * KZ2_USERCMD_LOG=N (diagnostic, off by default): print each distinct (object, method) pair the first time it runs,
 * up to N pairs, plus a per-pair call count every 4096 calls. The lifted body always runs. */
[[maybe_unused]] static void kz2_user_handler(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static int cap = -1;
    if (cap < 0) { const char* e = getenv("KZ2_USERCMD_LOG"); cap = e ? atoi(e) : 0; }
    if (cap > 0) {
        const uint32_t obj = (uint32_t)ctx->gpr[3];
        uint32_t fn = 0;
        if (obj) { uint32_t vt = vm_read32(obj); uint32_t opd = vt ? vm_read32(vt + 8) : 0; fn = opd ? vm_read32(opd) : 0; }
        static uint32_t keys[64][2]; static uint32_t counts[64]; static int nkeys = 0; static uint32_t total = 0;
        int k = 0;
        for (; k < nkeys; k++) if (keys[k][0] == obj && keys[k][1] == fn) break;
        if (k == nkeys && nkeys < 64 && nkeys < cap) {
            keys[nkeys][0] = obj; keys[nkeys][1] = fn; counts[nkeys] = 0; nkeys++;
            fprintf(stderr, "[kz2-usercmd] new obj=0x%08X method=0x%08X (pair %d)\n", obj, fn, k);
        }
        if (k < nkeys) counts[k]++;
        if ((++total & 4095u) == 0) {
            fprintf(stderr, "[kz2-usercmd] %u calls:", total);
            for (int i = 0; i < nkeys; i++) fprintf(stderr, " %08X/%08X=%u", keys[i][0], keys[i][1], counts[i]);
            fprintf(stderr, "\n");
        }
    }
    lifted(ctx);
}
#ifdef PPU_OVERRIDE_00045DB0
void func_00045DB0(ppu_context* ctx) { kz2_user_handler(ctx, func_00045DB0__lifted); }   // @0x00045DB0 (1.29)
#endif
#ifdef PPU_OVERRIDE_00045568
void func_00045568(ppu_context* ctx) { kz2_user_handler(ctx, func_00045568__lifted); }   // @0x00045568 (v1.01)
#endif

/* Post stage (vtable 0xFA1030 v1.01): Render [5] @0x0054B9D0 (1.29) / @0x0053E930 (v1.01),
 * Submit [13] @0x0054CE18 / @0x0053FD78, and the Unlock-job setup Render calls, @0x0054B4E8 / @0x0053E448 (1.29 = v1.01
 * + 0xD0A0 for this module). Diagnostic, off by default: KZ2_POSTSTAGE_LOG=N logs the first N calls of each (then every
 * 1024th) with lr and the fields that decide what runs: Render returns early (through 0x545130 / 0x538090) when byte
 * this+0x268 is 0, and does nothing when the effect mask this+0x14 & 0x1F is 0. The Unlock setup builds the SPU job
 * that writes JUMP io(P+4) at the command word P = state+0x220 (r4 = state); its log names P, the word there and the
 * job's parameter words, and registers P with the GCM walker (cellGcm_watch_cmd_ea, tag 1), whose [gcm-watch] lines
 * then say what the RSX finds at P and when. The lifted bodies always run. Render also arms the local-memory
 * write-back (patch 6008) the first time it runs with byte +0x268 set and a non-zero effect mask. */
extern "C" void cellGcm_watch_cmd_ea(uint32_t ea, uint32_t tag);
extern "C" void rsx_live_draw_local_writeback_arm(void);
static int kz2_poststage_log_n(void)
{
    static int n = -1;
    if (n < 0) { const char* e = getenv("KZ2_POSTSTAGE_LOG"); n = e ? atoi(e) : 0; }
    return n;
}
static int kz2_poststage_should_log(uint32_t* count)
{
    const int n = kz2_poststage_log_n();
    const uint32_t c = ++*count;
    return n > 0 && (c <= (uint32_t)n || (c & 1023u) == 0);
}
/* ENHANCEMENT: post effects the port switches off. Post+0x14 & 0x1F are the
 * effect flags Render @0x0054B9D0 reads each frame (lwz at 0x54BAC8; the GPU-pass builder 0x54B600 it calls reads them
 * again at 0x54B698/0x54B6C0); the RE notes: value 1 = motion blur (the GPU motion
 * vector pass @0x544D18 and the mask-1 SPU jobs HBlur, Upsample, MotionBlur), 2 = depth of field (DoF GPU passes,
 * DepthOfField/DepthToFuzzy jobs), 0x14 bloom, 8 grain, 0x10 ILR/vignette. The field's owner rewrites it, so the bits
 * are cleared at every Render entry. Motion blur is off by default (it doubles moving images at a few frames per
 * second): KZ2_MOTION_BLUR=1 keeps it. Depth of field stays on: KZ2_DOF=0 switches it off (speed option). */
static uint32_t kz2_post_clear_mask(void)
{
    static int m = -1;
    if (m < 0) {
        const char* mb = getenv("KZ2_MOTION_BLUR");
        const char* dof = getenv("KZ2_DOF");
        int v = 0;
        if (!(mb && atoi(mb) != 0)) v |= 0x1;
        if (dof && *dof && atoi(dof) == 0) v |= 0x2;
        m = v;
    }
    return (uint32_t)m;
}
static void kz2_post_effects(uint32_t self)
{
    const uint32_t clr = kz2_post_clear_mask();
    const uint32_t f = vm_read32(self + 0x14);
    static int logged;
    if (!logged && (f & 0x1Fu)) {
        logged = 1;
        fprintf(stderr, "[kz2-post] effects: motion blur %s (KZ2_MOTION_BLUR), depth of field %s (KZ2_DOF); "
                "Post+0x14 & 0x1F = 0x%X -> 0x%X\n", (clr & 1u) ? "off" : "on", (clr & 2u) ? "off" : "on",
                f & 0x1Fu, f & 0x1Fu & ~clr);
    }
    if (f & clr) vm_write32(self + 0x14, f & ~clr);
}
[[maybe_unused]] static void kz2_post_render(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    if ((uint32_t)ctx->gpr[3]) kz2_post_effects((uint32_t)ctx->gpr[3]);
    const uint32_t self = (uint32_t)ctx->gpr[3], r4 = (uint32_t)ctx->gpr[4], r5 = (uint32_t)ctx->gpr[5];
    const uint32_t lr = (uint32_t)ctx->lr;
    if (kz2_poststage_should_log(&calls))
        fprintf(stderr, "[kz2-poststage] Render #%u lr=0x%08X this=0x%08X r4=0x%08X r5=0x%08X b268=%u mask14=0x%X "
                "this+18=0x%08X r5+4=0x%08X\n", calls, lr, self, r4, r5, vm_read8(self + 0x268),
                vm_read32(self + 0x14) & 0x1Fu, vm_read32(self + 0x18), r5 ? vm_read32(r5 + 4) : 0u);
    /* The first Render that will run effects arms live-draw's local-memory write-back (patch 6008). It acts only
     * with LD_LOCAL_WRITEBACK=post, no longer the port's default (the post jobs read main-memory
     * surfaces only); the "[kz2-wb] local write-back armed" line it logs still marks the level start for the scripts. */
    if (vm_read8(self + 0x268) && (vm_read32(self + 0x14) & 0x1Fu)) rsx_live_draw_local_writeback_arm();
    lifted(ctx);
}
[[maybe_unused]] static void kz2_post_submit(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    const uint32_t self = (uint32_t)ctx->gpr[3];
    if (kz2_poststage_should_log(&calls))
        fprintf(stderr, "[kz2-poststage] Submit #%u lr=0x%08X this=0x%08X r4=0x%08X mask14=0x%X\n", calls,
                (uint32_t)ctx->lr, self, (uint32_t)ctx->gpr[4], self ? (vm_read32(self + 0x14) & 0x1Fu) : 0u);
    lifted(ctx);
}
[[maybe_unused]] static void kz2_post_unlock_setup(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    const uint32_t self = (uint32_t)ctx->gpr[3], state = (uint32_t)ctx->gpr[4];
    const uint32_t P = vm_read32(state + 0x220);
    const uint32_t before = P ? vm_read32(P) : 0u;
    lifted(ctx);
    if (P) cellGcm_watch_cmd_ea(P, 1);
    if (kz2_poststage_should_log(&calls))
        fprintf(stderr, "[kz2-poststage] Unlock-setup #%u lr=0x%08X this=0x%08X state=0x%08X P=0x%08X word@P before=0x%08X "
                "after=0x%08X next=0x%08X job=0x%016llX\n", calls, (uint32_t)ctx->lr, self, state, P, before,
                P ? vm_read32(P) : 0u, P ? vm_read32(P + 4) : 0u, (unsigned long long)vm_read64(state + 0x218));
}
#ifdef PPU_OVERRIDE_0054B9D0
void func_0054B9D0(ppu_context* ctx) { kz2_post_render(ctx, func_0054B9D0__lifted); }   // @0x0054B9D0 (1.29)
#endif
#ifdef PPU_OVERRIDE_0053E930
void func_0053E930(ppu_context* ctx) { kz2_post_render(ctx, func_0053E930__lifted); }   // @0x0053E930 (v1.01)
#endif
#ifdef PPU_OVERRIDE_0054CE18
void func_0054CE18(ppu_context* ctx) { kz2_post_submit(ctx, func_0054CE18__lifted); }   // @0x0054CE18 (1.29)
#endif
#ifdef PPU_OVERRIDE_0053FD78
void func_0053FD78(ppu_context* ctx) { kz2_post_submit(ctx, func_0053FD78__lifted); }   // @0x0053FD78 (v1.01)
#endif
#ifdef PPU_OVERRIDE_0054B4E8
void func_0054B4E8(ppu_context* ctx) { kz2_post_unlock_setup(ctx, func_0054B4E8__lifted); }   // @0x0054B4E8 (1.29)
#endif
#ifdef PPU_OVERRIDE_0053E448
void func_0053E448(ppu_context* ctx) { kz2_post_unlock_setup(ctx, func_0053E448__lifted); }   // @0x0053E448 (v1.01)
#endif

/* Front-end page layer (addresses 1.29 only, v1.01 not mapped). Diagnostic, off by default:
 * KZ2_PAGE_LOG=N logs the first N calls of each hook (then every 4096th) and every change of a ready/state result.
 * Addresses:
 *   @0x00078528 Game::ShowPage(game, url, camera): attaches the SVOModule and hands it the url (Init: start page).
 *   @0x002C7688 SVOModule::OpenURL(svo, url): copies url into the global string 0x11F24F8; browser ready
 *               (byte svo+0x2C) -> Browser::OpenPage(svo+0x24 browser, url, 0) now, else pending flag 0x11F2504 = 1.
 *   @0x002C4A78 SVOModule slot 17 (Update, per frame): pending && Browser::IsReady -> OpenPage(pending url), flag = 0.
 *   @0x002C6E38 SVOModule slot 18 (Render, per frame): camera svo+0xF0 decides scene / no-scene path.
 *   @0x00489970 Browser::OpenPage(browser, url, r5) (name ASSUMPTION).
 *   @0x0048D848 Browser::IsReady(browser) = (browser+0x8C)->+0x1C == 0 && 0x3ABC40(*0xFE17B0) == 1 (name ASSUMPTION).
 *   @0x003ABC40 the state query of the object at *0xFE17B0 (another compiler's code: std r2,0x28(r1) around bctrl).
 * The lifted bodies always run. */
static int kz2_page_log_n(void)
{
    static int n = -1;
    if (n < 0) { const char* e = getenv("KZ2_PAGE_LOG"); n = e ? atoi(e) : 0; }
    return n;
}
static uint32_t kz2_page_frame;   /* SVOModule Update calls so far: the frame counter of the page logs */
static int kz2_page_should_log(uint32_t* count)
{
    const int n = kz2_page_log_n();
    const uint32_t c = ++*count;
    return n > 0 && (c <= (uint32_t)n || (c & 4095u) == 0);
}
static const char* kz2_guest_str(uint32_t ea, char* buf, size_t cap)
{
    size_t i = 0;
    if (ea) for (; i + 1 < cap; i++) { const uint8_t c = vm_read8(ea + i); if (!c) break; buf[i] = (c >= 32 && c < 127) ? (char)c : '?'; }
    buf[i] = 0;
    return ea ? buf : "<null>";
}
[[maybe_unused]] static void kz2_show_page(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    char s[160];
    if (kz2_page_should_log(&calls))
        fprintf(stderr, "[kz2-page] ShowPage #%u lr=0x%08X game=0x%08X url=\"%s\" camera=%u\n", calls, (uint32_t)ctx->lr,
                (uint32_t)ctx->gpr[3], kz2_guest_str((uint32_t)ctx->gpr[4], s, sizeof s), (uint32_t)ctx->gpr[5] & 0xFFu);
    lifted(ctx);
}
[[maybe_unused]] static void kz2_svo_open_url(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    char s[160];
    const uint32_t svo = (uint32_t)ctx->gpr[3];
    const bool log = kz2_page_should_log(&calls);
    if (log)
        fprintf(stderr, "[kz2-page] SVO OpenURL #%u lr=0x%08X svo=0x%08X url=\"%s\" ready(+2C)=%u browser(+24)=0x%08X\n",
                calls, (uint32_t)ctx->lr, svo, kz2_guest_str((uint32_t)ctx->gpr[4], s, sizeof s), vm_read8(svo + 0x2C),
                vm_read32(svo + 0x24));
    lifted(ctx);
    if (log) fprintf(stderr, "[kz2-page]   -> pending(0x11F2504)=%u\n", vm_read8(0x11F2504));
}
[[maybe_unused]] static void kz2_svo_update(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    static int last_pending = -1, last_ready = -1;
    const uint32_t svo = (uint32_t)ctx->gpr[3];
    const int pending = vm_read8(0x11F2504), ready = vm_read8(svo + 0x2C);
    kz2_page_frame++;
    const bool periodic = kz2_page_should_log(&calls);
    if (kz2_page_log_n() > 0 && (periodic || pending != last_pending || ready != last_ready)) {
        char s[160];
        const uint32_t str = vm_read32(0x11F24F8);
        fprintf(stderr, "[kz2-page] SVO Update #%u svo=0x%08X pending=%d url=\"%s\" ready(+2C)=%d browser(+24)=0x%08X "
                "camera(+F0)=0x%08X flags(+19..1C)=%02X%02X%02X%02X\n", calls, svo, pending,
                str ? kz2_guest_str(str + 0x10, s, sizeof s) : "<none>", ready, vm_read32(svo + 0x24), vm_read32(svo + 0xF0),
                vm_read8(svo + 0x19), vm_read8(svo + 0x1A), vm_read8(svo + 0x1B), vm_read8(svo + 0x1C));
        last_pending = pending; last_ready = ready;
    }
    lifted(ctx);
}
[[maybe_unused]] static void kz2_svo_render(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    const uint32_t svo = (uint32_t)ctx->gpr[3];
    if (kz2_page_should_log(&calls))
        fprintf(stderr, "[kz2-page] SVO Render #%u svo=0x%08X camera(+F0)=0x%08X\n", calls, svo, vm_read32(svo + 0xF0));
    lifted(ctx);
}
[[maybe_unused]] static void kz2_browser_open_page(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    char s[160];
    const uint32_t lr = (uint32_t)ctx->lr, br = (uint32_t)ctx->gpr[3], r5 = (uint32_t)ctx->gpr[5];
    const bool log = kz2_page_should_log(&calls);
    if (log)
        fprintf(stderr, "[kz2-page] Browser OpenPage #%u lr=0x%08X browser=0x%08X url=\"%s\" r5=0x%X\n", calls, lr, br,
                kz2_guest_str((uint32_t)ctx->gpr[4], s, sizeof s), r5);
    lifted(ctx);
    if (log) fprintf(stderr, "[kz2-page]   -> r3=0x%08X\n", (uint32_t)ctx->gpr[3]);
}
[[maybe_unused]] static void kz2_browser_is_ready(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    static int64_t last = -1;
    const uint32_t br = (uint32_t)ctx->gpr[3];
    lifted(ctx);
    const uint32_t r = (uint32_t)ctx->gpr[3];
    const bool periodic = kz2_page_should_log(&calls);
    if (kz2_page_log_n() > 0 && (periodic || (int64_t)r != last)) {
        const uint32_t p8c = vm_read32(br + 0x8C);
        fprintf(stderr, "[kz2-page] Browser IsReady #%u browser=0x%08X -> %u ((+8C)=0x%08X ->+1C=0x%08X, *0xFE17B0=0x%08X)\n",
                calls, br, r, p8c, p8c ? vm_read32(p8c + 0x1C) : 0u, vm_read32(0xFE17B0));
        last = r;
    }
}
[[maybe_unused]] static void kz2_fe17b0_state(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    static int64_t last = -1;
    const uint32_t obj = (uint32_t)ctx->gpr[3];
    lifted(ctx);
    const uint32_t r = (uint32_t)ctx->gpr[3];
    const bool periodic = kz2_page_should_log(&calls);
    if (kz2_page_log_n() > 0 && (periodic || (int64_t)r != last)) {
        fprintf(stderr, "[kz2-page] State(0x3ABC40) #%u lr=0x%08X obj=0x%08X -> %u (+30=0x%08X +34=0x%08X +38=0x%08X)\n",
                calls, (uint32_t)ctx->lr, obj, r, vm_read32(obj + 0x30), vm_read32(obj + 0x34), vm_read32(obj + 0x38));
        last = r;
    }
}
#ifdef PPU_OVERRIDE_00078528
void func_00078528(ppu_context* ctx) { kz2_show_page(ctx, func_00078528__lifted); }           // @0x00078528 (1.29)
#endif
#ifdef PPU_OVERRIDE_002C7688
void func_002C7688(ppu_context* ctx) { kz2_svo_open_url(ctx, func_002C7688__lifted); }        // @0x002C7688 (1.29)
#endif
#ifdef PPU_OVERRIDE_002C4A78
void func_002C4A78(ppu_context* ctx) { kz2_svo_update(ctx, func_002C4A78__lifted); }          // @0x002C4A78 (1.29)
#endif
#ifdef PPU_OVERRIDE_002C6E38
void func_002C6E38(ppu_context* ctx) { kz2_svo_render(ctx, func_002C6E38__lifted); }          // @0x002C6E38 (1.29)
#endif
#ifdef PPU_OVERRIDE_00489970
void func_00489970(ppu_context* ctx) { kz2_browser_open_page(ctx, func_00489970__lifted); }   // @0x00489970 (1.29)
#endif
#ifdef PPU_OVERRIDE_0048D848
void func_0048D848(ppu_context* ctx) { kz2_browser_is_ready(ctx, func_0048D848__lifted); }    // @0x0048D848 (1.29)
#endif
#ifdef PPU_OVERRIDE_003ABC40
void func_003ABC40(ppu_context* ctx) { kz2_fe17b0_state(ctx, func_003ABC40__lifted); }        // @0x003ABC40 (1.29)
#endif

/* The browser's "file" protocol handler (vtable 0xFAE130 + 8; CanHandle(scheme) @0x0049EF10 = strcmp(scheme, "file")),
 * 1.29 only. Its fetch @0x0049EA38 (this = handler, path String at +0x20, chars at *(+0x20) + 0x10) first asks every
 * CachedJspResource in the object dictionary 0x11F14C0 (@0x0049E5C0(resource, path)); a hit -> state +0xC = 5; a miss
 * -> a file stream (ctor 0x2B2C0, open @0x0002AF50(stream, &String, 1, 0)); open failure -> the request's error
 * callback with code 2. KZ2_PAGE_LOG covers them; the stream open is logged only while a fetch is running. */
extern "C" int kz2_menu_fetch(ppu_context* ctx);   /* kz2_menu_pages.cpp: serves the edited menu pages */
static int kz2_in_fetch;
[[maybe_unused]] static void kz2_file_fetch(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    char s[200];
    const uint32_t h = (uint32_t)ctx->gpr[3];
    const bool log = kz2_page_should_log(&calls);
    const uint32_t str = vm_read32(h + 0x20);
    if (log)
        fprintf(stderr, "[kz2-page] file fetch #%u lr=0x%08X handler=0x%08X path=\"%s\" state(+C)=%u\n", calls,
                (uint32_t)ctx->lr, h, str ? kz2_guest_str(str + 0x10, s, sizeof s) : "<none>", vm_read32(h + 0xC));
    kz2_in_fetch++;
    if (!kz2_menu_fetch(ctx)) lifted(ctx);   /* EXIT TO DESKTOP / KEYBOARD rows, the Keyboard page */
    kz2_in_fetch--;
    if (log)
        fprintf(stderr, "[kz2-page]   -> r3=%u state(+C)=%u cached(+24)=0x%08X stream(+10)=0x%08X size(+14)=0x%X\n",
                (uint32_t)ctx->gpr[3], vm_read32(h + 0xC), vm_read32(h + 0x24), vm_read32(h + 0x10), vm_read32(h + 0x14));
}
[[maybe_unused]] static void kz2_cachedjsp_find(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    char s[200];
    const uint32_t res = (uint32_t)ctx->gpr[3], path = (uint32_t)ctx->gpr[4];
    const bool log = kz2_page_should_log(&calls);
    if (log) kz2_guest_str(path, s, sizeof s);
    lifted(ctx);
    if (log)
        fprintf(stderr, "[kz2-page] CachedJsp find #%u res=0x%08X path=\"%s\" -> 0x%08X\n", calls, res, s,
                (uint32_t)ctx->gpr[3]);
}
[[maybe_unused]] static void kz2_stream_open(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static uint32_t calls;
    char s[200];
    const uint32_t sp = (uint32_t)ctx->gpr[4];
    const bool log = kz2_in_fetch > 0 && kz2_page_should_log(&calls);
    if (log) { const uint32_t str = sp ? vm_read32(sp) : 0; if (str) kz2_guest_str(str + 0x10, s, sizeof s); else snprintf(s, sizeof s, "<none>"); }
    const uint32_t r5 = (uint32_t)ctx->gpr[5], r6 = (uint32_t)ctx->gpr[6];
    lifted(ctx);
    if (log)
        fprintf(stderr, "[kz2-page] stream open #%u lr=0x%08X path=\"%s\" r5=%u r6=%u -> %u\n", calls, (uint32_t)ctx->lr, s,
                r5, r6, (uint32_t)ctx->gpr[3]);
}
#ifdef PPU_OVERRIDE_0049EA38
void func_0049EA38(ppu_context* ctx) { kz2_file_fetch(ctx, func_0049EA38__lifted); }        // @0x0049EA38 (1.29)
#endif
#ifdef PPU_OVERRIDE_0049E5C0
void func_0049E5C0(ppu_context* ctx) { kz2_cachedjsp_find(ctx, func_0049E5C0__lifted); }    // @0x0049E5C0 (1.29)
#endif
#ifdef PPU_OVERRIDE_0002AF50
void func_0002AF50(ppu_context* ctx) { kz2_stream_open(ctx, func_0002AF50__lifted); }       // @0x0002AF50 (1.29)
#endif

/* Generic entry/exit trace for the page-layer functions below (KZ2_PAGE_LOG, first N calls then every 4096th): lr,
 * r3..r6 on entry, r3 on return, and r4 shown as text when it points at a C string or at a String object (the game's
 * strings keep their characters at *(obj) + 0x10, or the url struct's first word does). 1.29 only. */
static void kz2_guest_text(uint32_t p, char* out, size_t cap)
{
    out[0] = 0;
    if (p < 0x10000 || p >= 0xF0000000u) return;
    const uint8_t c0 = vm_read8(p);
    if (c0 >= 32 && c0 < 127) { kz2_guest_str(p, out, cap); return; }
    const uint32_t q = vm_read32(p);
    if (q >= 0x10000 && q < 0xF0000000u) {
        if (vm_read8(q) >= 32 && vm_read8(q) < 127) { kz2_guest_str(q, out, cap); return; }
        if (vm_read8(q + 0x10) >= 32 && vm_read8(q + 0x10) < 127) { kz2_guest_str(q + 0x10, out, cap); return; }
    }
}
static void kz2_page_trace(const char* name, uint32_t* calls, ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const bool log = kz2_page_should_log(calls);
    const uint32_t lr = (uint32_t)ctx->lr, r3 = (uint32_t)ctx->gpr[3], r4 = (uint32_t)ctx->gpr[4];
    const uint32_t r5 = (uint32_t)ctx->gpr[5], r6 = (uint32_t)ctx->gpr[6];
    char s[160];
    if (log) kz2_guest_text(r4, s, sizeof s);
    lifted(ctx);
    if (log)
        fprintf(stderr, "[kz2-page] %s #%u f=%u lr=0x%08X r3=0x%08X r4=0x%08X \"%s\" r5=0x%X r6=0x%X -> 0x%08X\n", name,
                *calls, kz2_page_frame, lr, r3, r4, s, r5, r6, (uint32_t)ctx->gpr[3]);
}
#define KZ2_PAGE_TRACE(ADDR, NAME) \
    void func_##ADDR(ppu_context* ctx) { static uint32_t c; kz2_page_trace(NAME, &c, ctx, func_##ADDR##__lifted); }
#ifdef PPU_OVERRIDE_004893A8
KZ2_PAGE_TRACE(004893A8, "Browser Navigate")                 // @0x004893A8 (1.29)
#endif
#ifdef PPU_OVERRIDE_00489078
KZ2_PAGE_TRACE(00489078, "Browser LoadNow")                  // @0x00489078 (1.29)
#endif
#ifdef PPU_OVERRIDE_00488FB8
KZ2_PAGE_TRACE(00488FB8, "Browser Queue")                    // @0x00488FB8 (1.29)
#endif
#ifdef PPU_OVERRIDE_003ABED0
KZ2_PAGE_TRACE(003ABED0, "SvoClient 0x3ABED0")               // @0x003ABED0 (1.29)
#endif
#ifdef PPU_OVERRIDE_0049E820
KZ2_PAGE_TRACE(0049E820, "file handler Open")                // @0x0049E820 (1.29)
#endif
#ifdef PPU_OVERRIDE_0049ED98
KZ2_PAGE_TRACE(0049ED98, "file handler Process")             // @0x0049ED98 (1.29)
#endif
/* The game's svo-client listener (vtable 0xFAC270 + 8, built at 0x48B908); its slot 7 @0x0048A660(listener, a, b) is the
 * connection-state callback that creates the "file" protocol handler (ctor 0x49E668) on the transitions 0 -> 1 and
 * 0 -> 7. The other slots are traced to see which callbacks the client makes at all. */
#ifdef PPU_OVERRIDE_0048A660
KZ2_PAGE_TRACE(0048A660, "listener[7] state change")         // @0x0048A660 (1.29)
#endif
#ifdef PPU_OVERRIDE_0048A520
KZ2_PAGE_TRACE(0048A520, "listener[5]")                      // @0x0048A520 (1.29)
#endif
#ifdef PPU_OVERRIDE_0048A5B0
KZ2_PAGE_TRACE(0048A5B0, "listener[6]")                      // @0x0048A5B0 (1.29)
#endif
#ifdef PPU_OVERRIDE_0048A650
KZ2_PAGE_TRACE(0048A650, "listener[8]")                      // @0x0048A650 (1.29)
#endif
#ifdef PPU_OVERRIDE_0048A920
KZ2_PAGE_TRACE(0048A920, "listener[10]")                     // @0x0048A920 (1.29)
#endif
#ifdef PPU_OVERRIDE_0048A948
KZ2_PAGE_TRACE(0048A948, "listener[11]")                     // @0x0048A948 (1.29)
#endif
#ifdef PPU_OVERRIDE_00484170
KZ2_PAGE_TRACE(00484170, "listener[2]")                      // @0x00484170 (1.29)
#endif

/* The SV engine (vtable 0xE617D8; client+0x34 / +0x38) and the
 * scheme -> handler step, 1.29 only. Diagnostic, KZ2_PAGE_LOG. */
#ifdef PPU_OVERRIDE_003B7908
void func_003B7908(ppu_context* ctx)   // @0x003B7908 (1.29) SV engine vt[5] Go(engine, url, type, ...)
{
    static uint32_t calls;
    const bool log = kz2_page_should_log(&calls);
    const uint32_t e = (uint32_t)ctx->gpr[3];
    char s[160];
    if (log)
        fprintf(stderr, "[kz2-page] Engine Go #%u f=%u lr=0x%08X engine=0x%08X url=\"%s\" type=%u state(+99B4)=%u req(+99C4)=0x%08X\n",
                calls, kz2_page_frame, (uint32_t)ctx->lr, e, kz2_guest_str((uint32_t)ctx->gpr[4], s, sizeof s),
                (uint32_t)ctx->gpr[5], vm_read32(e + 0x99B4), vm_read32(e + 0x99C4));
    func_003B7908__lifted(ctx);
    if (log)
        fprintf(stderr, "[kz2-page]   Engine Go -> %u state(+99B4)=%u req(+99C4)=0x%08X\n", (uint32_t)ctx->gpr[3],
                vm_read32(e + 0x99B4), vm_read32(e + 0x99C4));
}
#endif
#ifdef PPU_OVERRIDE_003B6220
void func_003B6220(ppu_context* ctx)   // @0x003B6220 (1.29) SV engine request start
{
    static uint32_t calls;
    const bool log = kz2_page_should_log(&calls);
    const uint32_t e = (uint32_t)ctx->gpr[3];
    if (log)
        fprintf(stderr, "[kz2-page] Engine StartRequest #%u f=%u lr=0x%08X engine=0x%08X r4=0x%08X r5=0x%X req(+99C4)=0x%08X\n",
                calls, kz2_page_frame, (uint32_t)ctx->lr, e, (uint32_t)ctx->gpr[4], (uint32_t)ctx->gpr[5], vm_read32(e + 0x99C4));
    func_003B6220__lifted(ctx);
    if (log)
        fprintf(stderr, "[kz2-page]   StartRequest -> %u state(+99B4)=%u req(+99C4)=0x%08X\n", (uint32_t)ctx->gpr[3],
                vm_read32(e + 0x99B4), vm_read32(e + 0x99C4));
}
#endif
#ifdef PPU_OVERRIDE_003A7198
void func_003A7198(ppu_context* ctx)   // @0x003A7198 (1.29) handler registry walk(registry, scheme): slots 15..0
{
    static uint32_t calls;
    const bool log = kz2_page_should_log(&calls);
    const uint32_t reg = (uint32_t)ctx->gpr[3];
    char s[64];
    if (log) {
        fprintf(stderr, "[kz2-page] Registry walk #%u f=%u lr=0x%08X registry=0x%08X scheme=\"%s\" slots:", calls,
                kz2_page_frame, (uint32_t)ctx->lr, reg, kz2_guest_str((uint32_t)ctx->gpr[4], s, sizeof s));
        for (uint32_t i = 0; i < 16; i++) {
            const uint32_t h = vm_read32(reg + 4 * i);
            if (h) fprintf(stderr, " [%u]=0x%08X(vt 0x%08X)", i, h, vm_read32(h));
        }
        fprintf(stderr, "\n");
    }
    func_003A7198__lifted(ctx);
    if (log) fprintf(stderr, "[kz2-page]   Registry walk -> 0x%08X\n", (uint32_t)ctx->gpr[3]);
}
#endif
#ifdef PPU_OVERRIDE_003A8330
KZ2_PAGE_TRACE(003A8330, "url parse")                        // @0x003A8330 (1.29) (out, base, url) -> ok
#endif
#ifdef PPU_OVERRIDE_003A8264
KZ2_PAGE_TRACE(003A8264, "handler lookup")                   // @0x003A8264 (1.29) (registry, url, listener) -> handler
#endif
#ifdef PPU_OVERRIDE_003B69C0
KZ2_PAGE_TRACE(003B69C0, "engine 0x3B69C0")                  // @0x003B69C0 (1.29) called by 0x3ABED0 before Go
#endif
#ifdef PPU_OVERRIDE_0049E668
KZ2_PAGE_TRACE(0049E668, "file provider ctor")               // @0x0049E668 (1.29) SVOLocalFileProvider(this, owner)
#endif
#ifdef PPU_OVERRIDE_0049EF10
KZ2_PAGE_TRACE(0049EF10, "file CanHandle")                   // @0x0049EF10 (1.29) (this, scheme) -> scheme == "file"
#endif
#ifdef PPU_OVERRIDE_003B8628
KZ2_PAGE_TRACE(003B8628, "engine IsIdle")                    // @0x003B8628 (1.29) SV engine vt[3]
#endif

/* Havok job queue hooks (1.29 only). KZ2_HAVOK_LOG=<n> logs the first n calls of each hook (and every 4096th), with the job record
 * words. Off by default. The record is 0x80 bytes: u16 type at +0, +8 pointer P (type 1), +0xC element array,
 * +0x10 u16 first index, +0x12 u16 count. */
static int kz2_havok_should_log(uint32_t* count)
{
    static int n = -1;
    if (n < 0) { const char* e = getenv("KZ2_HAVOK_LOG"); n = e ? atoi(e) : 0; }
    const uint32_t c = ++*count;
    return n > 0 && (c <= (uint32_t)n || (c & 4095u) == 0);
}
static bool kz2_guest_ok(uint32_t ea) { return ea >= 0x10000u && ea < 0xF0000000u; }
static uint32_t kz2_r32s(uint32_t ea) { return kz2_guest_ok(ea) ? vm_read32(ea) : 0xDEADDEADu; }
static void kz2_havok_rec(char* s, size_t cap, uint32_t rec)
{
    if (!kz2_guest_ok(rec)) { snprintf(s, cap, "rec=0x%08X <bad>", rec); return; }
    snprintf(s, cap, "rec=0x%08X [%08X %08X %08X %08X %08X]", rec, vm_read32(rec), vm_read32(rec + 4),
             vm_read32(rec + 8), vm_read32(rec + 0xC), vm_read32(rec + 0x10));
}
[[maybe_unused]] static void kz2_havok_trace(const char* name, uint32_t* calls, ppu_context* ctx,
                                             void (*lifted)(ppu_context*), int rec_reg, int after)
{
    const bool log = kz2_havok_should_log(calls);
    const uint32_t lr = (uint32_t)ctx->lr, r3 = (uint32_t)ctx->gpr[3], r4 = (uint32_t)ctx->gpr[4];
    const uint32_t r5 = (uint32_t)ctx->gpr[5], r6 = (uint32_t)ctx->gpr[6], r7 = (uint32_t)ctx->gpr[7];
    const uint32_t rec = rec_reg ? (uint32_t)ctx->gpr[rec_reg] : 0;
    char s[160] = "";
    if (log && rec_reg && !after) kz2_havok_rec(s, sizeof s, rec);
    lifted(ctx);
    if (log && rec_reg && after) kz2_havok_rec(s, sizeof s, rec);
    if (log)
        fprintf(stderr, "[kz2-havok] %s #%u tid=%u lr=0x%08X r3=0x%08X r4=0x%08X r5=0x%08X r6=0x%08X r7=0x%08X %s -> 0x%08X\n",
                name, *calls, (unsigned)ctx->thread_id, lr, r3, r4, r5, r6, r7, s, (uint32_t)ctx->gpr[3]);
}
#define KZ2_HAVOK_TRACE(ADDR, NAME, RECREG, AFTER) \
    void func_##ADDR(ppu_context* ctx) { static uint32_t c; kz2_havok_trace(NAME, &c, ctx, func_##ADDR##__lifted, RECREG, AFTER); }
#ifdef PPU_OVERRIDE_008D3398
/* @0x008D3398 step setup (thread 0): r3 = pool (pool+8 = world); seeds the type-0 job if *(world+0x2C) > 0 and
 * *(world+0xA0) == 0. Logs the pool, world and both conditions before the call. */
void func_008D3398(ppu_context* ctx)
{
    static uint32_t c;
    if (kz2_havok_should_log(&c)) {
        const uint32_t pool = (uint32_t)ctx->gpr[3], world = kz2_r32s(pool + 8);
        fprintf(stderr, "[kz2-havok] step setup #%u tid=%u lr=0x%08X pool=0x%08X world=0x%08X n=*(w+0x2C)=%d *(w+0xA0)=0x%08X "
                "r4=0x%08X r5=0x%08X queue[+0x28 m_data]=0x%08X\n", c, (unsigned)ctx->thread_id, (uint32_t)ctx->lr, pool,
                world, (int)kz2_r32s(world + 0x2C), kz2_r32s(world + 0xA0), (uint32_t)ctx->gpr[4], (uint32_t)ctx->gpr[5],
                kz2_r32s(pool + 0x140 + 0x28));
    }
    func_008D3398__lifted(ctx);
}
#endif
#ifdef PPU_OVERRIDE_00816828
KZ2_HAVOK_TRACE(00816828, "addJob(out,queue,entry,0,prio)", 5, 0)   // @0x00816828
#endif
#ifdef PPU_OVERRIDE_008149C8
KZ2_HAVOK_TRACE(008149C8, "addJob-child", 5, 0)                     // @0x008149C8 (record register ASSUMPTION r5)
#endif
#ifdef PPU_OVERRIDE_00816F68
KZ2_HAVOK_TRACE(00816F68, "getNextJob(queue,wait,out)", 5, 1)        // @0x00816F68 (record copied into r5's buffer)
#endif
#ifdef PPU_OVERRIDE_008DAD20
KZ2_HAVOK_TRACE(008DAD20, "type-1 handler(ctx,queue,buf)", 5, 0)     // @0x008DAD20
#endif

#if defined(PPU_OVERRIDE_00072FB0) && defined(PPU_OVERRIDE_00073178) && defined(PPU_OVERRIDE_000732D8)
/* The PPU job-fiber scheduler that runs the world's entity updates (1.29 addresses; names
 * ASSUMPTION, from behaviour). Same design as KZ3's (Project Helghast port/spu/kz3_ppu_overrides.cpp @0x000C3A54, KZ3
 * the RE notes), different code: KZ2's run_all and finish are compiled C around four asm helpers.
 *   @0x00072988 save(buf)     r14-r31 (+0), r1 (+0x90), r2 (+0x98), r0=LR (+0xA0 word), r3 (+0xA8), f14-f31 (+0xB0),
 *                             v20-v31 (+0x140), r4 (+0x200), r5 (+0x208), CR (+0x210)
 *   @0x00072A9C restore(buf)  the reverse, then blr to the saved LR on the saved r1 (longjmp)
 *   @0x00072BB4 switch(buf, S): save(buf); restore(pick(S))
 *   @0x000731F8 pick(S)       round robin from slot S+0xC + 1 over 5 slots: the first with a job (B+0xF2C+4i != 0)
 *                             whose watched word (B+0xF18+4i) is 0 or points at a non-zero word; spins while none is
 *                             ready; none with a job: S+0xC = -1 and B+0xC80 (the caller of run_all)
 *   @0x00072FB0 run_all(S, list{count, entries* {opd*, arg}}): [0xED5C88] = S, S+0 = list, S+4 = cursor 0; fills
 *                             slots 0..4: buf = B + i*0x280, r1 = [0x11F14AC] + [B+0xF00]*0xB0000 + i*0x20000 +
 *                             0x10000 - 0x80, r2 = opd+4, LR = opd+0, r3 = arg, r4 = S; B+0xF2C+4i = &entry, B+0xF18+4i
 *                             = 0; S+0xC = -1; switch(B+0xC80, S); returns when every job is done
 *   @0x00073178 wait(S, ptr): returns at once if ptr && *ptr != 0; else B+0xF18+4*cur = ptr, switch(B+cur*0x280, S)
 *   @0x000732D8 finish(S): the next list entry (if any) goes into the current slot as above, else B+0xF2C+4*cur = 0;
 *                             B+0xF18+4*cur = 0; restore(pick(S)). Called at the end of a job (0x67B81C).
 * S = world+0x48; B = [S+8]. Lifted as plain C, restore only sets ctx->r1/LR and returns into the lifted caller, so
 * run_all came back at once and no job ever ran: the entity update job 0x67B760 (OPD 0xEADAF8, built by
 * 0x691CF0 for every active entity) never called Entity::Update 0x67B218 (0 calls in 296 s; a call-count
 * profile: run_all 3/s, 0x67B760 0 calls). Here run_all runs pick on the calling host fiber and each slot's
 * job gets a host fiber (guest_fiber.c); wait and finish switch back to it. Guest-visible state (S fields, slot
 * buffers, [0xED5C88]) is written as the original does. KZ2_FIBER_LOG=N logs the first N events (default 16). */
#include "guest_fiber.h"
extern "C" void ps3_indirect_call(ppu_context* ctx);
extern "C" int* ps3_ppu_dispatch_depth_slot(void);
extern "C" int* ps3_ppu_vcall_sp_slot(void);
extern "C" PPU_THREAD_LOCAL void (*g_trampoline_fn)(void*);

namespace {
const uint32_t kRunningS = 0x00ED5C88u, kStackBase = 0x011F14ACu, kSlots = 5, kBufSize = 0x280;
struct Kz2FiberSched {
    uint32_t S; guest_fiber* home; guest_fiber* slot[kSlots]; guest_fiber* dead;
};
thread_local Kz2FiberSched t_kfs[4];
thread_local int t_kfs_n;
int g_kf_log = -1;
unsigned long long g_kf_runs, g_kf_jobs, g_kf_waits, g_kf_finishes;

bool kf_log()
{
    if (g_kf_log < 0) { const char* e = getenv("KZ2_FIBER_LOG"); g_kf_log = e ? atoi(e) : 16; }
    return g_kf_log > 0 && g_kf_log-- > 0;
}
Kz2FiberSched* kf_find(uint32_t S)
{
    for (int i = t_kfs_n - 1; i >= 0; i--) if (t_kfs[i].S == S) return &t_kfs[i];
    return nullptr;
}
/* The slot set-up shared by run_all (@0x00073020..0x730EC) and finish (@0x00073318..0x733EC): the next list entry
 * into slot i, or the slot marked free. Returns true if a job was placed. */
bool kf_place(ppu_context* ctx, uint32_t S, uint32_t i)
{
    const uint32_t list = vm_read32(S), cursor = vm_read32(S + 4), B = vm_read32(S + 8);
    if (cursor >= vm_read32(list)) { vm_write32(B + 0xF2C + 4 * i, 0); return false; }
    const uint32_t ent = vm_read32(list + 4) + cursor * 8, opd = vm_read32(ent), arg = vm_read32(ent + 4);
    const uint32_t buf = B + i * kBufSize;
    const uint32_t top = vm_read32(kStackBase) + vm_read32(B + 0xF00) * 0xB0000u + i * 0x20000u + 0x10000u;
    const uint64_t r3 = ctx->gpr[3];
    ctx->gpr[3] = buf;
    func_00072988(ctx);                       /* save(buf), as the original (most fields are overwritten next) */
    ctx->gpr[3] = r3;
    vm_write64(buf + 0x90, (uint64_t)(top - 0x80u));
    vm_write64(buf + 0x98, (uint64_t)vm_read32(opd + 4));
    vm_write32(buf + 0xA0, vm_read32(opd));
    vm_write64(buf + 0xA8, (uint64_t)arg);
    vm_write64(buf + 0x200, (uint64_t)S);
    vm_write32(B + 0xF2C + 4 * i, ent);
    vm_write32(S + 4, cursor + 1);
    return true;
}
/* @0x000731F8 pick, without the spin: slot index, -1 = no job left, -2 = none ready yet. */
int kf_pick(uint32_t S)
{
    const int cur = (int)vm_read32(S + 0xC);
    const uint32_t B = vm_read32(S + 8);
    bool none = true;
    for (int k = 0; k < (int)kSlots; k++) {
        const int i = (cur + k + 1) % (int)kSlots;
        if (!vm_read32(B + 0xF2C + 4 * i)) continue;
        none = false;
        const uint32_t w = vm_read32(B + 0xF18 + 4 * i);
        if (!w || vm_read32(w) != 0) return i;
    }
    return none ? -1 : -2;
}
/* Body of every job fiber: the register block was loaded by restore(buf), so call LR. */
void kf_job_body(void* vctx, void* arg)
{
    ppu_context* ctx = (ppu_context*)vctx;
    Kz2FiberSched* fs = (Kz2FiberSched*)arg;
    const uint32_t entry = (uint32_t)ctx->lr;
    ctx->ctr = entry;
    ps3_indirect_call(ctx);
    while (g_trampoline_fn) { void (*f)(void*) = g_trampoline_fn; g_trampoline_fn = 0; f(ctx); }
    /* The original would blr to LR (= entry); finish() is the only way out of a job. Treat it as finish. */
    fprintf(stderr, "[kz2-fiber] S=0x%08X entry 0x%08X returned without finish(); freeing its slot\n", fs->S, entry);
    const uint32_t S = fs->S, cur = vm_read32(S + 0xC), B = vm_read32(S + 8);
    if (cur < kSlots) { vm_write32(B + 0xF2C + 4 * cur, 0); vm_write32(B + 0xF18 + 4 * cur, 0); fs->slot[cur] = nullptr; }
    fs->dead = guest_fiber_current();
    guest_fiber_switch(fs->home);
}
} // namespace

/* @0x00072FB0 run_all(S, list) */
void func_00072FB0(ppu_context* ctx)
{
    const uint32_t S = (uint32_t)ctx->gpr[3], list = (uint32_t)ctx->gpr[4];
    if (!list || !vm_read32(list)) return;                       /* @0x00072FEC / 0x00072FF8 */
    if (!S || t_kfs_n >= 4 || kf_find(S)) {
        fprintf(stderr, "[kz2-fiber] run_all S=0x%08X depth %d: nested or NULL, lifted body\n", S, t_kfs_n);
        func_00072FB0__lifted(ctx);
        return;
    }
    g_kf_runs++;
    const uint32_t count = vm_read32(list);
    vm_write32(kRunningS, S);
    vm_write32(S, list);
    vm_write32(S + 4, 0);
    const uint32_t B = vm_read32(S + 8);
    for (uint32_t i = 0; i < kSlots; i++) { kf_place(ctx, S, i); vm_write32(B + 0xF18 + 4 * i, 0); }
    vm_write32(S + 0xC, 0xFFFFFFFFu);
    if (kf_log())
        fprintf(stderr, "[kz2-fiber] run_all #%llu S=0x%08X list=0x%08X count=%u first={0x%08X,0x%08X} lr=0x%08X (jobs so far %llu, waits %llu)\n",
                g_kf_runs, S, list, count, vm_read32(vm_read32(list + 4)), vm_read32(vm_read32(list + 4) + 4),
                (uint32_t)ctx->lr, g_kf_jobs, g_kf_waits);
    {   /* switch(B+0xC80, S)'s save of the caller, as the original */
        const uint64_t r3 = ctx->gpr[3], r0 = ctx->gpr[0];
        ctx->gpr[0] = ctx->lr; ctx->gpr[3] = B + 0xC80; func_00072988(ctx);
        ctx->gpr[3] = r3; ctx->gpr[0] = r0;
    }
    /* Patch 1031 (in v0.15.0): the indirect-call depth guard and its vcall stack count per fiber. */
    static const bool locals_added = [] {
        guest_fiber_add_local(ps3_ppu_dispatch_depth_slot);
        guest_fiber_add_local(ps3_ppu_vcall_sp_slot);
        return true;
    }();
    (void)locals_added;
    Kz2FiberSched* fs = &t_kfs[t_kfs_n++];
    memset(fs, 0, sizeof *fs);
    fs->S = S;
    guest_fiber_self(ctx, sizeof *ctx);
    fs->home = guest_fiber_current();
    double stall_since = -1, stall_next = 0;
    for (;;) {
        if (fs->dead) { guest_fiber_destroy(fs->dead); fs->dead = nullptr; }
        const int i = kf_pick(S);
        if (i == -1) break;
        if (i == -2) {                                            /* the original spins in pick */
            const double t = guest_fiber_seconds();
            if (stall_since < 0) { stall_since = t; stall_next = t + 2.0; }
            else if (t >= stall_next) {
                stall_next = t + 10.0;
                fprintf(stderr, "[kz2-fiber] S=0x%08X no slot ready for %.0f s:", S, t - stall_since);
                for (uint32_t k = 0; k < kSlots; k++) {
                    const uint32_t w = vm_read32(B + 0xF18 + 4 * k);
                    fprintf(stderr, " [%u job=0x%08X w=0x%08X *w=0x%08X]", k, vm_read32(B + 0xF2C + 4 * k), w, w ? vm_read32(w) : 0);
                }
                fprintf(stderr, "\n");
            }
            guest_fiber_yield_thread();
            continue;
        }
        stall_since = -1;
        vm_write32(S + 0xC, (uint32_t)i);
        guest_fiber* f = fs->slot[i];
        if (!f) {                                                 /* a fresh job: restore(buf) into its register block */
            f = guest_fiber_create(kf_job_body, fs, 0);
            ppu_context* st = (ppu_context*)guest_fiber_state(f);
            st->gpr[3] = B + i * kBufSize;
            func_00072A9C(st);
            fs->slot[i] = f;
            g_kf_jobs++;
            if (kf_log())
                fprintf(stderr, "[kz2-fiber] S=0x%08X start slot %d entry 0x%08X arg 0x%08X r1 0x%08X (job #%llu)\n", S, i,
                        (uint32_t)st->lr, (uint32_t)st->gpr[3], (uint32_t)st->gpr[1], g_kf_jobs);
        }
        guest_fiber_switch(f);
    }
    if (fs->dead) { guest_fiber_destroy(fs->dead); fs->dead = nullptr; }
    for (uint32_t k = 0; k < kSlots; k++)
        if (fs->slot[k]) { fprintf(stderr, "[kz2-fiber] S=0x%08X slot %u fiber left at the end\n", S, k); guest_fiber_destroy(fs->slot[k]); }
    t_kfs_n--;
    vm_write32(S + 0xC, 0xFFFFFFFFu);                             /* pick's "all done" */
    if (kf_log()) fprintf(stderr, "[kz2-fiber] run_all S=0x%08X done (jobs %llu, waits %llu, finishes %llu)\n", S, g_kf_jobs,
                          g_kf_waits, g_kf_finishes);
}

/* @0x00073178 wait(S, ptr): runs on a job fiber. */
void func_00073178(ppu_context* ctx)
{
    const uint32_t S = (uint32_t)ctx->gpr[3], ptr = (uint32_t)ctx->gpr[4];
    if (ptr && vm_read32(ptr) != 0) return;                      /* @0x00073194..0x000731A8 */
    Kz2FiberSched* fs = kf_find(S);
    if (!fs || guest_fiber_current() == fs->home) {
        static int n;
        if (n++ < 8) fprintf(stderr, "[kz2-fiber] wait S=0x%08X ptr=0x%08X outside a job fiber (lr 0x%08X); returning\n", S, ptr, (uint32_t)ctx->lr);
        return;
    }
    const uint32_t cur = vm_read32(S + 0xC), B = vm_read32(S + 8);
    vm_write32(B + 0xF18 + 4 * cur, ptr);
    g_kf_waits++;
    if (kf_log()) fprintf(stderr, "[kz2-fiber] S=0x%08X wait slot %u on 0x%08X (lr 0x%08X)\n", S, cur, ptr, (uint32_t)ctx->lr);
    const uint64_t r3 = ctx->gpr[3], r0 = ctx->gpr[0];
    ctx->gpr[0] = ctx->lr; ctx->gpr[3] = B + cur * kBufSize; func_00072988(ctx);   /* switch's save(buf) */
    ctx->gpr[0] = r0; ctx->gpr[3] = r3;
    guest_fiber_switch(fs->home);
    ctx->gpr[3] = B + cur * kBufSize;                            /* restore(buf) returns r3 = buf */
}

/* @0x000732D8 finish(S): runs on a job fiber and never returns. */
void func_000732D8(ppu_context* ctx)
{
    const uint32_t S = (uint32_t)ctx->gpr[3];
    Kz2FiberSched* fs = kf_find(S);
    if (!fs || guest_fiber_current() == fs->home) {
        fprintf(stderr, "[kz2-fiber] finish S=0x%08X outside a job fiber (lr 0x%08X); returning\n", S, (uint32_t)ctx->lr);
        return;
    }
    const uint32_t cur = vm_read32(S + 0xC), B = vm_read32(S + 8);
    g_kf_finishes++;
    if (cur < kSlots) {
        kf_place(ctx, S, cur);
        vm_write32(B + 0xF18 + 4 * cur, 0);
        fs->slot[cur] = nullptr;                                  /* the slot's next job (if any) gets a new fiber */
    }
    if (kf_log()) fprintf(stderr, "[kz2-fiber] S=0x%08X finish slot %u (#%llu)\n", S, cur, g_kf_finishes);
    fs->dead = guest_fiber_current();
    guest_fiber_switch(fs->home);
    fprintf(stderr, "[kz2-fiber] finished fiber resumed (S=0x%08X)\n", S);
    abort();
}
#endif

/* @0x00048AE8 (1.29) Renderer::WaitLabel(this, idx, value) (name ASSUMPTION; the RE notes): the main
 * thread's wait for GCM label `idx` (0x4B in the level, released by the scene render pass's own NV406E release) to
 * reach `value`. The game polls `while (label < value) sys_timer_usleep(30)` (loop 0x48B20..0x48B58, about 16,700
 * syscalls per second in the level) and then adds the elapsed microseconds to its wait statistic
 * this+0x3C0 + (this+0x3B8 & 3)*0x30 + 0xC. The override is the same function on the host, sleeping on patch 6019's
 * label-release wake instead of the poll (2 ms timeout as a safety net, then the label is read again). Label address
 * = *(0xFE1194) + idx * *(0xFE1198) (GcmDevice 0xFE1100 +0x94/+0x98, cellGcmGetLabelAddress(0) and the stride);
 * microseconds = (tb1 - tb0) * 1000000 / *(u64*)0x011B0878 (the timebase frequency, as 0x22130 computes it). No
 * timeout, like the original. Wait accounting (KZ3_WAIT_ACCT) books the wait as KZ3_WA_LABEL, site = idx.
 * KZ2_LABEL_WAIT=0 runs the game's poll (lifted body) instead. v1.01: not mapped (no v1.01 entry). */
#include "../diag/kz3_wait_acct.h"
extern "C" uint64_t ppu_timebase_now(void);   /* runtime/syscalls/sys_timer.h */
extern "C" uint32_t cellGcm_label_seq(void);
extern "C" void cellGcm_label_wait_seq(uint32_t seq, uint32_t timeout_ms);
[[maybe_unused]] static void kz2_wait_label(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    static int mode = -1;
    if (mode < 0) { const char* e = getenv("KZ2_LABEL_WAIT"); mode = (e && *e) ? atoi(e) : 1; }
    if (!mode) { lifted(ctx); return; }
    const uint32_t self = (uint32_t)ctx->gpr[3];
    const int32_t idx = (int32_t)ctx->gpr[4];
    const uint32_t value = (uint32_t)ctx->gpr[5];
    const uint64_t tb0 = ppu_timebase_now();
    uint64_t wa = 0;
    uint32_t sleeps = 0;
    for (int first = 1;; first = 0) {
        const uint32_t seq = cellGcm_label_seq();
        const uint32_t base = vm_read32(0x00FE1194u), stride = vm_read32(0x00FE1198u);
        if (vm_read32(base + (uint32_t)idx * stride) >= value) break;
        if (first) wa = kz3_wacct_begin();
        cellGcm_label_wait_seq(seq, 2);
        sleeps++;
    }
    /* "[kz2-label]": the first call, then with KZ2_LABEL_WAIT_LOG=1 every 256th call: calls, calls that slept, sleeps
     * (wakes + 2 ms timeouts) since the last line. */
    {
        static uint32_t calls, waited, slept;
        static int logn = -1;
        if (logn < 0) { const char* e = getenv("KZ2_LABEL_WAIT_LOG"); logn = (e && *e) ? atoi(e) : 0; }
        calls++; waited += sleeps != 0; slept += sleeps;
        if (calls == 1 || (logn && (calls & 255u) == 0)) {
            fprintf(stderr, "[kz2-label] WaitLabel host wait (patch 6019): call %u idx 0x%X value 0x%X; last %u calls: %u "
                    "waited, %u sleeps\n", calls, (unsigned)idx, value, calls == 1 ? 1u : 256u, waited, slept);
            waited = slept = 0;
        }
    }
    if (wa) kz3_wacct_end(KZ3_WA_LABEL, (uint32_t)idx, wa);
    const uint32_t rec = self + 0x3C0u + (vm_read32(self + 0x3B8u) & 3u) * 0x30u;
    const uint64_t freq = vm_read64(0x011B0878u);
    const uint64_t us = freq ? (ppu_timebase_now() - tb0) * 1000000ull / freq : 0;
    const uint64_t old = vm_read32(rec + 0xC);
    vm_write32(rec + 0xC, (uint32_t)(old + us));
    ctx->gpr[3] = us;               /* as the lifted body leaves them: r3 = elapsed (0x22130), r4/r5 the stat words */
    ctx->gpr[4] = old;
    ctx->gpr[5] = old + us;
}
#ifdef PPU_OVERRIDE_00048AE8
void func_00048AE8(ppu_context* ctx) { kz2_wait_label(ctx, func_00048AE8__lifted); }   // @0x00048AE8 (1.29)
#endif

/* Pad layout: KZ2_PAD_LAYOUT=original|modern, logic and tables in
 * kz2_pad_layout.{c,h} (table generated from tools/assets/pad_layouts.py). PlayerProfile (1.29): button map
 * obj+0x64 + 4*func (u32 EButton per EDeviceFunction, PROFILE.DAT 0x40), scheme index obj+0x168 (0..5), dirty byte
 * obj+0x1D (set = the game saves the profile), file image obj+0x24..+0x5B10. Input and prompts read the map from
 * the profile (ASSUMPTION for the prompts, as in KZ3; untested in game until a GPU run).
 *  - @0x000826B0 PlayerProfile::SetFunctionButton(this, func, button), Lua binding (OPD 0xE7AA68; no direct
 *    callers): every preset choice (options page, "SET TO DEFAULT", first-boot SetDefaultControllerScheme) calls it
 *    19 times; with modern the scripted ids get the Modern button. The lifted body keeps its own checks (func < 0,
 *    func == 18, func >= 0x37 ignored; unchanged value: no dirty).
 *  - @0x00079BC8 profile load-or-create at boot (calls the loader 0x79A78: memcpy 0x5AEC into obj+0x24, obj+0xAC =
 *    status, dirty cleared) and @0x0007BA60 the profile save/load state machine (state obj+0x8; load branch
 *    0x7BD30..0x7BD7C copies into obj+0x24 the same way): after either, kz2_pad_profile_fix applies the layout to
 *    the profile in memory (modern: Modern map; original: a map saved as exactly Modern gets the chosen preset
 *    back) and sets the dirty byte when it changed something, so the next save carries it.
 * original or unset + a profile that never held the Modern map: nothing is written (byte-identical behaviour). */
#include "kz2_pad_layout.h"
static void kz2_pad_profile_fix(uint32_t obj, const char* where)
{
    if (!obj) return;
    const int mode = kz2_pad_layout_mode();
    int32_t map[KZ2_PAD_NFUNC];
    for (int f = 0; f < KZ2_PAD_NFUNC; f++) map[f] = (int32_t)vm_read32(obj + 0x64u + 4u * (uint32_t)f);
    const uint32_t scheme = vm_read32(obj + 0x168u);
    const int n = kz2_pad_layout_fix_map(mode, map, scheme);
    if (!n) return;
    for (int f = 0; f < KZ2_PAD_NFUNC; f++)
        if (kz2_pad_layout_slot_ok(f)) vm_write32(obj + 0x64u + 4u * (uint32_t)f, (uint32_t)map[f]);
    vm_write8(obj + 0x1Du, 1);
    static int logged;
    if (logged++ < 8)
        fprintf(stderr, "[kz2-pad] %s: profile 0x%08X button map -> %s (%d slots; scheme index %u)\n", where, obj,
                mode == KZ2_PAD_MODERN ? "modern" : "original preset", n, scheme);
}
/* ENHANCEMENT (test runs only): KZ2_GOD=1 makes the local player invulnerable and gives infinite ammo through the
 * profile's own debug flags, as the debug options page would (1.29): god mode u32 obj+0x54 (only the value 2,
 * "Invulnerable", has a reader: @0x000CE7E0 in IsInvulnerable 0xCE7A0), infinite ammo u8 obj+0xA44 (read once per
 * section enter at @0x00253EAC). The flags live in memory only: around every step of the profile save/load state
 * machine the loaded values are put back, so a saved PROFILE.DAT never carries them. ASSUMPTION: 0x7BA60 is the only
 * path that copies the profile object into a save buffer. Unset: nothing is written. */
static int kz2_god_mode()
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("KZ2_GOD"); on = (e && *e && *e != '0') ? 1 : 0; }
    return on;
}
static uint32_t g_god_obj, g_god_orig; static uint8_t g_ammo_orig;
static void kz2_god_apply(uint32_t obj, const char* where)
{
    if (!obj || !kz2_god_mode()) return;
    g_god_obj = obj; g_god_orig = vm_read32(obj + 0x54u); g_ammo_orig = vm_read8(obj + 0xA44u);
    vm_write32(obj + 0x54u, 2u);
    vm_write8(obj + 0xA44u, 1u);
    static int logged;
    if (logged++ < 4)
        fprintf(stderr, "[kz2-god] %s: profile 0x%08X god 2 (was %u), infinite ammo 1 (was %u)\n", where, obj,
                g_god_orig, g_ammo_orig);
}
static void kz2_god_restore(uint32_t obj)
{
    if (!obj || obj != g_god_obj) return;
    vm_write32(obj + 0x54u, g_god_orig);
    vm_write8(obj + 0xA44u, g_ammo_orig);
    g_god_obj = 0;
}
[[maybe_unused]] static void kz2_set_function_button(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const int mode = kz2_pad_layout_mode();
    if (mode == KZ2_PAD_MODERN) {
        const int32_t func = (int32_t)ctx->gpr[4], btn = (int32_t)ctx->gpr[5];
        const int32_t nb = kz2_pad_layout_set_button(mode, func, btn);
        if (nb != btn) ctx->gpr[5] = (uint64_t)(int64_t)nb;
    }
    lifted(ctx);
}
[[maybe_unused]] static void kz2_profile_load_boot(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t obj = (uint32_t)ctx->gpr[3];
    lifted(ctx);
    const uint64_t r3 = ctx->gpr[3];
    kz2_pad_profile_fix(obj, "profile load (0x79BC8)");
    kz2_god_apply(obj, "profile load (0x79BC8)");
    ctx->gpr[3] = r3;
}
[[maybe_unused]] static void kz2_profile_state(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t obj = (uint32_t)ctx->gpr[3];
    const uint32_t before = obj ? vm_read32(obj + 0x8u) : 0u;
    const int god = obj && obj == g_god_obj;
    if (god) kz2_god_restore(obj);
    lifted(ctx);
    if (before && !vm_read32(obj + 0x8u)) {       /* a save or load step finished (state back to idle) */
        const uint64_t r3 = ctx->gpr[3];
        kz2_pad_profile_fix(obj, "profile load/save done (0x7BA60)");
        ctx->gpr[3] = r3;
    }
    if (god || (before && !vm_read32(obj + 0x8u))) kz2_god_apply(obj, "profile state (0x7BA60)");
}
#ifdef PPU_OVERRIDE_000826B0
void func_000826B0(ppu_context* ctx) { kz2_set_function_button(ctx, func_000826B0__lifted); }   // @0x000826B0 (1.29)
#endif
#ifdef PPU_OVERRIDE_00079BC8
void func_00079BC8(ppu_context* ctx) { kz2_profile_load_boot(ctx, func_00079BC8__lifted); }     // @0x00079BC8 (1.29)
#endif
#ifdef PPU_OVERRIDE_0007BA60
void func_0007BA60(ppu_context* ctx) { kz2_profile_state(ctx, func_0007BA60__lifted); }         // @0x0007BA60 (1.29)
#endif
/* KZ2_PAD_LOG=1: which button the game's input reads for each EDeviceFunction, as it plays.
 * The 1.29 helpers below are the game's function queries (93 call sites): each takes (button-state array r3,
 * EDeviceFunction r4), loads the profile from the global *(0x11B0540 + 0x240) (stored by 0x79CB0 before it calls the
 * boot loader 0x79BC8), looks up map[func] at profile+0x64+4*func and tests the state word of that button
 * (state array + 4*button; -1 = unbound -> 0):
 *  - @0x00082248 bit 0 of the state ("down"),
 *  - @0x00082290 state == 3 ("pressed"; ASSUMPTION: 3 = went down this frame),
 *  - @0x000822F0 state == 2 ("released"; ASSUMPTION).
 * So the input reads the live profile map on every query (no copy): KZ2_PAD_LAYOUT's write to the map is what input
 * sees. The log prints one line per (helper, func, button) the first 4 times it returns non-zero (at most 400 lines). */
static int kz2_pad_log_on(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("KZ2_PAD_LOG"); on = (e && *e && *e != '0') ? 1 : 0; }
    return on;
}
static const char* kz2_pad_func_name(int32_t f)
{
    static const char* const n[20] = { "PrimaryFire", "SecondaryFire", "ZoomSwitch", "ZoomModeSwitch", "SprintToggle",
        "Jump", "Use", "PickupWeapon", "QuickThrow", "Reload", "Crouch", "Cover", "DropWeapon", "NextWeapon", "DoItNow",
        "ToggleFlashlight", "CloseCombat", "TriggerC4", "Suicide", "PlanPath" };
    return (f >= 0 && f < 20) ? n[f] : "other";
}
static const char* kz2_pad_button_name(int32_t b)
{
    static const char* const n[16] = { "Triangle", "Circle", "Cross", "Square", "L2", "R2", "L1", "R1", "Start", "Select",
        "L3", "R3", "Up", "Right", "Down", "Left" };
    return (b >= 0 && b < 16) ? n[b] : "none";
}
[[maybe_unused]] static void kz2_pad_query(ppu_context* ctx, void (*lifted)(ppu_context*), int kind)
{
    if (!kz2_pad_log_on()) { lifted(ctx); return; }
    const int32_t func = (int32_t)ctx->gpr[4];
    lifted(ctx);
    if (!(uint32_t)ctx->gpr[3] || func < 0 || func >= 0x37) return;
    const uint32_t prof = vm_read32(0x011B0540u + 0x240u);
    const int32_t btn = prof ? (int32_t)vm_read32(prof + 0x64u + 4u * (uint32_t)func) : -1;
    static uint8_t seen[3][0x37][17];
    static unsigned lines;
    const int bi = (btn >= 0 && btn < 16) ? btn : 16;
    if (seen[kind][func][bi] >= 4 || lines >= 400) return;
    seen[kind][func][bi]++; lines++;
    static const char* const kn[3] = { "down", "pressed", "released" };
    fprintf(stderr, "[kz2-pad] input %s: func %d (%s) <- button %d (%s)\n", kn[kind], func, kz2_pad_func_name(func),
            btn, kz2_pad_button_name(btn));
}
/* @0x00082248 (1.29): also the cover_toggle hook, defined with the gameplay settings below (kz2_cover_held_q). */
#ifdef PPU_OVERRIDE_00082290
void func_00082290(ppu_context* ctx) { kz2_pad_query(ctx, func_00082290__lifted, 1); }   // @0x00082290 (1.29)
#endif
#ifdef PPU_OVERRIDE_000822F0
void func_000822F0(ppu_context* ctx) { kz2_pad_query(ctx, func_000822F0__lifted, 2); }   // @0x000822F0 (1.29)
#endif

/* ---- the Edge zlib inflate job on the host (KZ2_NATIVE_ZLIB) ----
 * @0x003C8BA0 (1.29) / @0x003BCAA0 (v1.01, same first 80 bytes) = edgeZlibAddInflateQueueElement(q r3, in r4, inSize r5,
 * out r6, skipBegin r7, partial r8, skipEnd r9, counter r10, eventFlag = caller stack +0x74, bits = u16 at +0x7E,
 * mode = +0x84). Its callers are FIOS's dearchiver only: func_0002CD20 (mode 1, in = block + 2, i.e. the zlib header
 * skipped) and func_0002CFD8 (mode 0 = a plain copy of >= 0x1000 bytes; smaller copies are a PPU memmove, 0x7B9170),
 * both through the wrapper func_003C8E40 (skips 0), counter = dearchiver +0x2C00, event flag = +0x2980 (direction
 * SPU2PPU), bits = slot +0x1E. The SPU task's behaviour is in kz2_edge_zlib.h; kz2_edge_run does it here.
 * KZ2_NATIVE_ZLIB=1: run the element on the calling PPU thread (inflate or copy, the window, the counter decrement, the
 *   event flag), return without pushing; anything the task would refuse, or that fails, goes to the lifted push
 *   unchanged. Default on (scripted in-play A/B, 3 pairs: level start 9.7-10.9 s sooner, frame times
 *   within noise; equality 400/400 on two captures); KZ2_NATIVE_ZLIB=0 is the fallback to the lifted push (task
 *   image 35).
 * KZ2_NATIVE_ZLIB_STATS=1: one line every 1000 elements or 5 s of elements, and at exit: native / fallback (by reason) /
 *   lifted counts, mode-0 count, bytes in and out, host time.
 * KZ2_NATIVE_ZLIB_RECORD=N[:STRIDE[:SKIP]] (diagnostic, the native zlib job's diff test; STRIDE and SKIP came later: every
 *   STRIDE-th element after the first SKIP, so a capture can span a whole level load): with the lifted path, N elements are also
 *   inflated on the host before the push; after the task completes (the counter drops) the window the SPU wrote is
 *   compared byte for byte ([kz2-zlib] rec lines), and each record (element, input, SPU window) is written to
 *   kz2-zrec/NNNNN.bin in the working directory for tools/runtime/edge_zlib_check.py. Game bytes: keep them in work/. */
#include "kz2_edge_zlib.h"
#include <atomic>
#include <chrono>
#include <cmath>
#include <thread>
#include <vector>
#include <sys/stat.h>
#ifdef _WIN32
#include <direct.h>
#endif
extern "C" int kz2_guest_put(uint32_t ea, const void* src, uint32_t n);   /* kz2_edge_guest.c */
extern "C" int32_t cellSpursEventFlagSet(void* eventFlag, uint16_t bits);  /* libs/spurs/cellSpurs.c: takes the EA */

namespace {
struct Kz2ZlibStats {
    std::atomic<uint64_t> native{0}, lifted{0}, mode0{0}, in{0}, out{0}, host_ns{0}, max_ns{0}, last_print{0};
    std::atomic<uint64_t> fb[KZ2_EDGE_NSTATUS] = {};
    std::atomic<uint64_t> rec_ok{0}, rec_bad{0}, rec_timeout{0};
};
Kz2ZlibStats g_kz2_zlib;
int g_kz2_zlib_mode = -1, g_kz2_zlib_stats = 0, g_kz2_zlib_rec = 0;
int g_kz2_zlib_rec_stride = 1, g_kz2_zlib_rec_skip = 0;   /* KZ2_NATIVE_ZLIB_RECORD=N:STRIDE:SKIP */
std::atomic<int> g_kz2_zlib_rec_seen{0};
std::atomic<int> g_kz2_zlib_rec_n{0};

uint64_t kz2_zlib_now_ns()
{
    return (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

void kz2_zlib_print(const char* why)
{
    Kz2ZlibStats& s = g_kz2_zlib;
    fprintf(stderr, "[kz2-zlib] KZ2_NATIVE_ZLIB_STATS (%s) native=%llu fallback=%llu (args %llu src %llu inflate %llu copy %llu "
            "put %llu) lifted=%llu mode0=%llu in=%llu out=%llu host_ms=%.1f max_us=%.0f rec ok=%llu bad=%llu timeout=%llu\n",
            why, (unsigned long long)s.native.load(),
            (unsigned long long)(s.fb[1] + s.fb[2] + s.fb[3] + s.fb[4] + s.fb[5]), (unsigned long long)s.fb[1].load(),
            (unsigned long long)s.fb[2].load(), (unsigned long long)s.fb[3].load(), (unsigned long long)s.fb[4].load(),
            (unsigned long long)s.fb[5].load(), (unsigned long long)s.lifted.load(), (unsigned long long)s.mode0.load(),
            (unsigned long long)s.in.load(), (unsigned long long)s.out.load(), s.host_ns.load() / 1e6, s.max_ns.load() / 1e3,
            (unsigned long long)s.rec_ok.load(), (unsigned long long)s.rec_bad.load(),
            (unsigned long long)s.rec_timeout.load());
}
void kz2_zlib_atexit() { kz2_zlib_print("exit"); }

void kz2_zlib_init()
{
    if (g_kz2_zlib_mode >= 0) return;
    const char* e = getenv("KZ2_NATIVE_ZLIB");
    const char* st = getenv("KZ2_NATIVE_ZLIB_STATS");
    const char* rc = getenv("KZ2_NATIVE_ZLIB_RECORD");
    g_kz2_zlib_stats = (st && *st && *st != '0') ? 1 : 0;
    g_kz2_zlib_rec = rc ? atoi(rc) : 0;
    if (rc && g_kz2_zlib_rec > 0) {   /* N:STRIDE:SKIP (every STRIDE-th element after the first SKIP) */
        int n = 0, stride = 1, skip = 0;
        if (sscanf(rc, "%d:%d:%d", &n, &stride, &skip) >= 2) {
            g_kz2_zlib_rec_stride = stride > 0 ? stride : 1;
            g_kz2_zlib_rec_skip = skip > 0 ? skip : 0;
        }
    }
    if (g_kz2_zlib_stats) atexit(kz2_zlib_atexit);
    g_kz2_zlib_mode = (e && *e == '0') ? 0 : 1;   /* on unless KZ2_NATIVE_ZLIB=0 */
    fprintf(stderr, "[kz2-zlib] Edge zlib job: %s (host decoder %s)%s\n",
            g_kz2_zlib_mode ? "native, on the PPU thread (default; KZ2_NATIVE_ZLIB=0 for the SPU task)" : "SPU task image 35 (lifted push)",
            kz2_edge_backend(), g_kz2_zlib_rec ? ", recording the SPU's output for the diff test" : "");
    if (g_kz2_zlib_rec)
        fprintf(stderr, "[kz2-zlib] recording %d elements: every %d after the first %d\n", g_kz2_zlib_rec,
                g_kz2_zlib_rec_stride, g_kz2_zlib_rec_skip);
}

void kz2_zlib_tick(uint64_t n)
{
    if (!g_kz2_zlib_stats) return;
    const uint64_t now = kz2_zlib_now_ns(), last = g_kz2_zlib.last_print.load();
    if (n % 1000 == 0 || now - last > 5000000000ull) {
        g_kz2_zlib.last_print = now;
        kz2_zlib_print(n % 1000 == 0 ? "1000" : "5s");
    }
}

const uint8_t* kz2_zlib_src(void*, uint32_t ea, uint32_t n)
{
    if (ea < 0x10000u || (uint64_t)ea + n > 0xF0000000ull) return nullptr;
    return (const uint8_t*)vm_base + ea;
}
int kz2_zlib_put(void*, uint32_t ea, const uint8_t* p, uint32_t n) { return kz2_guest_put(ea, p, n); }
/* lwarx/stwcx. through the runtime's reservation emulation (the same path the caller's increment at 0x2CEE8 takes, and
 * the one that breaks an SPU GETLLAR reservation on the line), so the decrement is atomic against both. */
uint32_t kz2_zlib_dec(void* user, uint32_t ea)
{
    ppu_context* ctx = (ppu_context*)user;
    const uint64_t ra = ctx->reserve_addr, rv = ctx->reserve_value;
    uint32_t old;
    for (;;) {
        old = vm_read32(ea);
        ctx->reserve_addr = ea;
        ctx->reserve_value = old;
        if (ppu_stwcx32(ea, old, old - 1u)) break;
    }
    ctx->reserve_addr = ra;
    ctx->reserve_value = rv;
    if (old == 0) {
        static int warned;
        if (warned++ < 4) fprintf(stderr, "[kz2-zlib] work-to-do counter 0x%08X already at zero (the task's error)\n", ea);
    }
    return old;
}
int kz2_zlib_flag(void*, uint32_t ea, uint16_t bits) { return (int)cellSpursEventFlagSet((void*)(uintptr_t)ea, bits); }

/* The diff test: the host result first (nothing written), then the lifted push, then wait for the task's decrement. */
void kz2_zlib_record(ppu_context* ctx, const kz2_edge_elem& e, void (*lifted)(ppu_context*))
{
    static thread_local uint8_t host[KZ2_EDGE_MAX];
    const int idx = g_kz2_zlib_rec_n++;
    const uint32_t counter = e.counter_mode & ~1u;
    const uint32_t expected = (uint32_t)e.skip_begin + e.partial + e.skip_end;
    int hn = -1;
    const uint8_t* in = kz2_zlib_src(nullptr, e.in, e.in_size);
    if (in && expected <= KZ2_EDGE_MAX && e.in_size <= KZ2_EDGE_MAX) {
        if (e.counter_mode & 1u) hn = kz2_edge_inflate_raw(host, expected, in, e.in_size);
        else if (e.in_size == expected) { memcpy(host, in, expected); hn = (int)expected; }
    }
    std::vector<uint8_t> inb(in ? in : host, (in ? in : host) + (in ? e.in_size : 0));
    const uint32_t c0 = counter ? vm_read32(counter) : 0;
    lifted(ctx);
    bool done = false;
    const uint64_t t0 = kz2_zlib_now_ns();
    while (counter && !(done = (vm_read32(counter) != c0)) && kz2_zlib_now_ns() - t0 < 5000000000ull)
        std::this_thread::yield();
    if (!done) { g_kz2_zlib.rec_timeout++; fprintf(stderr, "[kz2-zlib] rec %d: no completion seen\n", idx); return; }
    const uint8_t* spu = kz2_zlib_src(nullptr, e.out, e.partial);
    uint32_t diff = UINT32_MAX;
    if (hn != (int)expected || !spu) diff = 0;
    else for (uint32_t i = 0; i < e.partial; i++) if (host[e.skip_begin + i] != spu[i]) { diff = i; break; }
    if (diff == UINT32_MAX) g_kz2_zlib.rec_ok++; else g_kz2_zlib.rec_bad++;
    if (diff != UINT32_MAX || idx < 8 || idx % 500 == 0)
        fprintf(stderr, "[kz2-zlib] rec %d mode=%u in=%u expected=%u skip=%u/%u partial=%u host=%d -> %s (first diff %d)\n",
                idx, e.counter_mode & 1u, e.in_size, expected, e.skip_begin, e.skip_end, e.partial, hn,
                diff == UINT32_MAX ? "MATCH" : "DIFFER", diff == UINT32_MAX ? -1 : (int)diff);
    if (spu) {
        char name[64];
        static std::atomic<int> dir_made{0};
        if (!dir_made.exchange(1)) {
#ifdef _WIN32
            _mkdir("kz2-zrec");
#else
            mkdir("kz2-zrec", 0755);
#endif
        }
        snprintf(name, sizeof name, "kz2-zrec/%05d.bin", idx);
        if (FILE* f = fopen(name, "wb")) {
            uint8_t el[32] = {};
            auto w32 = [&](int o, uint32_t v) { el[o] = v >> 24; el[o + 1] = v >> 16; el[o + 2] = v >> 8; el[o + 3] = v; };
            auto w16 = [&](int o, uint16_t v) { el[o] = v >> 8; el[o + 1] = (uint8_t)v; };
            w32(0, e.in); w32(4, e.out); w32(8, e.in_size); w32(0xC, e.partial); w32(0x10, e.counter_mode);
            w32(0x14, e.event_flag); w16(0x18, e.bits); w16(0x1A, e.skip_begin); w16(0x1C, e.skip_end);
            fwrite(el, 1, 32, f);
            fwrite(inb.data(), 1, inb.size(), f);
            fwrite(spu, 1, e.partial, f);
            fclose(f);
        }
    }
}
}  // namespace

[[maybe_unused]] static void kz2_edge_add(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    kz2_zlib_init();
    const uint32_t sp = (uint32_t)ctx->gpr[1];
    const uint32_t mode = vm_read32(sp + 0x84);
    kz2_edge_elem e;
    e.in = (uint32_t)ctx->gpr[4];
    e.in_size = (uint32_t)ctx->gpr[5];
    e.out = (uint32_t)ctx->gpr[6];
    e.skip_begin = (uint16_t)ctx->gpr[7];
    e.partial = (uint32_t)ctx->gpr[8];
    e.skip_end = (uint16_t)ctx->gpr[9];
    e.counter_mode = (uint32_t)ctx->gpr[10] | mode;
    e.event_flag = vm_read32(sp + 0x74);
    e.bits = vm_read16(sp + 0x7E);
    Kz2ZlibStats& s = g_kz2_zlib;
    if (g_kz2_zlib_mode == 1 && mode <= 1u && !((uint32_t)ctx->gpr[10] & 3u)) {
        static thread_local uint8_t scratch[KZ2_EDGE_MAX];
        const kz2_edge_ops ops = { ctx, kz2_zlib_src, kz2_zlib_put, kz2_zlib_dec, kz2_zlib_flag };
        kz2_edge_result r;
        const uint64_t t0 = kz2_zlib_now_ns();
        const int st = kz2_edge_run(&e, &ops, scratch, &r);
        const uint64_t dt = kz2_zlib_now_ns() - t0;
        if (st == KZ2_EDGE_DONE) {
            s.host_ns += dt;
            for (uint64_t m = s.max_ns.load(); dt > m && !s.max_ns.compare_exchange_weak(m, dt);) {}
            s.in += e.in_size;
            s.out += e.partial;
            if (!mode) s.mode0++;
            ctx->gpr[3] = 0;   /* the lifted body ends with the unlock's result (0); its callers ignore r3 */
            kz2_zlib_tick(++s.native);
            return;
        }
        s.fb[st]++;
        static int fb_lines;
        if (fb_lines++ < 16)
            fprintf(stderr, "[kz2-zlib] fallback %d: in=0x%08X size=%u out=0x%08X skip=%u/%u partial=%u mode=%u counter=0x%08X\n",
                    st, e.in, e.in_size, e.out, e.skip_begin, e.skip_end, e.partial, mode, (uint32_t)ctx->gpr[10]);
    } else if (g_kz2_zlib_mode == 1) {
        s.fb[KZ2_EDGE_FB_ARGS]++;
    }
    s.in += e.in_size;
    s.out += e.partial;
    if (!mode) s.mode0++;
    int seen = -1;   /* the element's number among the lifted ones, for the record's stride and skip */
    if (g_kz2_zlib_mode == 0 && g_kz2_zlib_rec > 0 && g_kz2_zlib_rec_n.load() < g_kz2_zlib_rec)
        seen = g_kz2_zlib_rec_seen++;
    if (seen >= g_kz2_zlib_rec_skip && (seen - g_kz2_zlib_rec_skip) % g_kz2_zlib_rec_stride == 0)
        kz2_zlib_record(ctx, e, lifted);
    else lifted(ctx);
    kz2_zlib_tick(++s.lifted);
}
#ifdef PPU_OVERRIDE_003C8BA0
void func_003C8BA0(ppu_context* ctx) { kz2_edge_add(ctx, func_003C8BA0__lifted); }   // @0x003C8BA0 (1.29)
#endif
#ifdef PPU_OVERRIDE_003BCAA0
void func_003BCAA0(ppu_context* ctx) { kz2_edge_add(ctx, func_003BCAA0__lifted); }   // @0x003BCAA0 (v1.01)
#endif

/* ---- Player gameplay settings (ENHANCEMENT, original behaviour is the default) ------------------------
 * kz2_gameplay.h has the settings (gameplay.ini [gameplay], KZ2_AIM_ASSIST / KZ2_CROUCH_TOGGLE / KZ2_COVER_TOGGLE) and
 * the pure logic; this is the guest glue. Addresses are 1.29 with the v1.01 twin in the table (found with the
 * name_census call-graph map and checked by disassembling the call sites). C = SoldierJoystickController, E = C+0x10,
 * P = the PlayerProfile (*(0x11B0540 + 0x240) in 1.29, *(0x117E740 + 0x240) in v1.01). KZ2_GP_LOG=1 logs what the hooks see.
 *
 *  aim_assist   ApplyInputModifier @0x2F0120 (v1.01 0x2E4EF8) when lr is 0x174160 (v1.01 0x16E900) and the shoot/zoom
 *               assist helper @0x2F0880 (0x2E5658) when lr is 0x1741F8 or 0x1742CC (0x16E998 / 0x16EA2C): UpdateLook
 *               @0x173E80 (0x16E620) only. They return early when the assist is off (except a pad with
 *               aim_assist = off, where the modifier runs for its smoother and the softlock search / aim cone take
 *               their no-target exits; aim_assist_strength scales the cone factor and the pull); the modifier pointer C+0x30C is
 *               never touched (the sprint slowdown shares that gate), the follow camera (0xBF398) and mounted gun
 *               (0x102148) callers keep running. Results are not read by the callers (they reload from memory).
 *  crouch_toggle  Crouch decision @0x176208 (0x170990): P+0x61 (CrouchButtonIsToggle) is set to 1 around the body and
 *               put back after it, so the saved profile keeps the player's own value; the net-state test @0x7B388
 *               (0x7A098) is forced to 1 at its only use there (lr 0x1762AC, v1.01 0x170A34), since the retail toggle
 *               also needs it (UNKNOWN offline: KZ2_GP_LOG prints the raw result).
 *  cover_toggle   held(11) @0x82248 (0x80D38) at the cover query (lr 0x1764A8, v1.01 0x170C30) returns a latch flipped by
 *               pressed(11) @0x82290 (0x80D80); the cover finder @0xB1E78 (0xAD4F0) at lr 0x1764D0 (0x170C58) reports
 *               "found"; the cover function @0x1763B0 (0x170B38) resets and closes the frame (kz2_cover_end). */
#include "kz2_gameplay.h"

static int kz2_gp_log_on(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("KZ2_GP_LOG"); on = (e && *e && *e != '0') ? 1 : 0; }
    return on;
}
static float kz2_gp_f32(uint32_t ea) { const uint32_t u = vm_read32(ea); float f; memcpy(&f, &u, 4); return f; }

static int kz2_look_is_mouse(void);   /* mouse look, below */

/* KZ2_AIM_LOG=1 (diagnostic, off by default): one "[aim]" summary per 150 look updates (kz2_aim_stats in
 * kz2_gameplay.h) plus the first 40 updates where the stick was edited or the target search found something. The search
 * hooks below count only while ApplyInputModifier runs for UpdateLook (kz2_aim_in_mod). */
static int kz2_aim_log_on(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("KZ2_AIM_LOG"); on = (e && *e && *e != '0') ? 1 : 0; }
    return on;
}
static kz2_aim_stats kz2_aim = { 0, 0, 0.0f, 0.0f, 1.0f, 0.0f, 0, 0, 0, 0, 0, 0, 0, 0, 1.0f, 0, 0 };
static int kz2_aim_in_mod;
static void kz2_aim_flush(const char* state)
{
    if (kz2_aim.mod < 150) return;
    char line[512];
    kz2_aim_stats_line(&kz2_aim, state, line, (int)sizeof line);
    fprintf(stderr, "%s\n", line);
    kz2_aim_stats_reset(&kz2_aim);
}
/* Candidate gather (r3 = E, r4 = cone, f1 = range, r6 = mode, r7 = &list {count, base, capacity}; 20-byte entries). The
 * game's entity list it walks: *(0xF3B288) + 0x398 = count (1.29; the v1.01 global is not mapped: 0). */
extern "C" uint64_t ppu_guest_call(uint32_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
static uint32_t kz2_aim_vcall_args(uint32_t obj, uint32_t slot, uint32_t a1)   /* obj->vf(slot)(a1): OPD pointers */
{
    const uint32_t vt = vm_read32(obj);
    return vt ? (uint32_t)ppu_guest_call(vm_read32(vt + slot), obj, a1, 0, 0, 0, 0, 0, 0) : 0;
}
static uint32_t kz2_aim_vcall(uint32_t obj, uint32_t slot) { return kz2_aim_vcall_args(obj, slot, 0); }
/* The gather's first filters replayed over the game's list (1.29 only, KZ2_AIM_LOG, once per 30 empty gathers): range
 * (|pos - player| <= f1, pos = +0xB0), the +0xE4 bit 10 skip, not attached to the player (+0xCC), vf 0x94 != 0,
 * vf 0x5C (faction) hostile to the player's (byte faction_player + 0x28 + faction->+0xC); nearest hostile at any range. */
static struct { int have; float x, y, z, d; } kz2_aim_tgt;   /* nearest hostile of the last scan (KZ2_AIM_FACE) */
static void kz2_aim_gather_detail(uint32_t E, float range, uint32_t g, int print = 1)
{
    const uint32_t n = vm_read32(g + 0x398), base = vm_read32(g + 0x39C);
    const float px = kz2_gp_f32(E + 0xB0), py = kz2_gp_f32(E + 0xB4), pz = kz2_gp_f32(E + 0xB8);
    const uint32_t pf = kz2_aim_vcall(E, 0x5C);
    unsigned in_range = 0, flag_ok = 0, alive = 0, hostile = 0, hostile_any = 0;
    float near_h = 1e30f;
    for (uint32_t i = 0; i < n && i < 4096; i++) {
        const uint32_t e = vm_read32(base + 4 * i);
        if (!e || e == E) continue;
        const float dx = kz2_gp_f32(e + 0xB0) - px, dy = kz2_gp_f32(e + 0xB4) - py, dz = kz2_gp_f32(e + 0xB8) - pz;
        const float d = sqrtf(dx * dx + dy * dy + dz * dz);
        const int r = d <= range, f = !((vm_read32(e + 0xE4) >> 10) & 1) && vm_read32(e + 0xCC) != E;
        if (!f) { in_range += r; continue; }
        const int a = kz2_aim_vcall(e, 0x94) != 0;
        const uint32_t ef = a ? kz2_aim_vcall(e, 0x5C) : 0;
        const int h = pf && ef && vm_read8(pf + (uint32_t)(int32_t)vm_read32(ef + 0xC) + 0x28) != 0;
        in_range += r; flag_ok += r; alive += r && a; hostile += r && h;
        if (h && a) {
            hostile_any++;
            if (d < near_h) { near_h = d; kz2_aim_tgt.x = kz2_gp_f32(e + 0xB0); kz2_aim_tgt.y = kz2_gp_f32(e + 0xB4); kz2_aim_tgt.z = kz2_gp_f32(e + 0xB8); }
        }
    }
    kz2_aim_tgt.have = hostile_any > 0; kz2_aim_tgt.d = near_h;
    if (print) fprintf(stderr, "[aim] gather detail: range %.1f, player (%.1f, %.1f, %.1f), %u entities: %u in range, %u not skipped, %u alive,"
            " %u hostile; hostile at any range %u (nearest %.1f)\n", range, px, py, pz, n, in_range, flag_ok, alive, hostile,
            hostile_any, hostile_any ? near_h : -1.0f);
}
[[maybe_unused]] static void kz2_aim_gather(ppu_context* ctx, void (*lifted)(ppu_context*), uint32_t ents_global)
{
    const uint32_t list = (uint32_t)ctx->gpr[7], E = (uint32_t)ctx->gpr[3];
    const float range = (float)ctx->fpr[1];
    lifted(ctx);
    if (!kz2_aim_in_mod) return;
    const uint32_t g = ents_global ? vm_read32(ents_global) : 0;
    const uint32_t cand = vm_read32(list);
    kz2_aim_stats_gather(&kz2_aim, cand, g ? vm_read32(g + 0x398) : 0);
    static unsigned s_empty;
    if (g && !cand && s_empty++ % 300 == 0) kz2_aim_gather_detail(E, range, g);
}
/* Target finder: gather, then a line-of-sight ray per candidate; returns 1 with the target in *r8. */
extern "C" uint64_t ppu_guest_call_ct(uint32_t, uint32_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t,
                                      uint64_t, uint64_t);
[[maybe_unused]] static void kz2_aim_find(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    /* Once (KZ2_AIM_LOG, 1.29): which function the finder's line-of-sight query is. The finder gets a world handle
     * from E vf 0x234 into {flag, &p, 0} @0x2FAFF8, uses *p, and calls its vf 0x18 per candidate @0x2FB2E8; replayed
     * here into scratch below the caller's stack, then released with 0x1DEB8 as the finder does. */
    static int s_once;
    if (kz2_aim_in_mod && !s_once && vm_read32(0x00F3B288u)) {
        s_once = 1;
        const uint32_t E = (uint32_t)ctx->gpr[3], sc = ((uint32_t)ctx->gpr[1] - 0x800u) & ~0xFu;
        vm_write32(sc, 0); vm_write32(sc + 4, 0); vm_write32(sc + 8, 0);
        kz2_aim_vcall_args(E, 0x234, sc);
        const uint32_t ok = vm_read32(sc), pp = vm_read32(sc + 4), w = pp ? vm_read32(pp) : 0;
        const uint32_t vt = w ? vm_read32(w) : 0, opd = vt ? vm_read32(vt + 0x18) : 0;
        fprintf(stderr, "[aim] finder world: flag %u, holder 0x%08X, world 0x%08X, vtable 0x%08X, vf 0x18 OPD 0x%08X -> code 0x%08X\n",
                ok, pp, w, vt, opd, opd ? vm_read32(opd) : 0);
        ppu_guest_call_ct(0x0001DEB8u, 0x00EC3038u, sc, 0, 0, 0, 0, 0, 0, 0);
    }
    lifted(ctx);
    if (kz2_aim_in_mod) kz2_aim_stats_find(&kz2_aim, (uint32_t)ctx->gpr[3] != 0);
}
/* Aim-cone factor (r3 = M, r4 = E, r5 = &factor out): 1 without a target, the AimAssistSpeedCurve value with one. */
/* what UpdateLook's ApplyInputModifier is running for right now (set by kz2_aim_gate around the lifted body;
 * KZ2_AIM_MODE_SKIP = not inside it): FULL = the game's assist at aim_assist_strength (kz2_aim_strength_now), SMOOTH =
 * pad with aim_assist = off: the softlock search and the aim cone below take their own "no target" exits, so only the
 * smoother edits the stick. Counters for the KZ2_AIM_LOG / KZ2_GP_LOG lines. */
static int kz2_aim_site_mode = KZ2_AIM_MODE_SKIP;
static float kz2_aim_strength_now = 1.0f;
static unsigned kz2_aim_noassist_soft, kz2_aim_noassist_cone, kz2_aim_scaled_cone, kz2_aim_scaled_pull;
static int kz2_aim_cone_site(uint32_t lr) { return lr == 0x002F0264u || lr == 0x002E503Cu; }   /* 1.29 / v1.01 */
static int kz2_aim_soft_site(uint32_t lr) { return lr == 0x002F023Cu || lr == 0x002E5014u; }
static int kz2_aim_pull_site(uint32_t lr) { return lr == 0x002F041Cu || lr == 0x002E51F4u; }
[[maybe_unused]] static void kz2_aim_cone(ppu_context* ctx, void (*lifted)(ppu_context*), uint32_t self)
{
    const uint32_t out = (uint32_t)ctx->gpr[5];
    if (kz2_aim_site_mode == KZ2_AIM_MODE_SMOOTH && kz2_aim_cone_site((uint32_t)ctx->lr)) {
        /* The function's own no-target exit (@0x2EFDD0 in 1.29: no AimAssistDistanceCurve, or the finder found none):
         * *out = the float at fn - 0xC (lis/addi r29 = fn - 0x10, lfs +4), 1.0 = no slowdown. */
        const uint32_t one = vm_read32(self - 0xCu);
        vm_write32(out, one);
        if (++kz2_aim_noassist_cone == 1)
            fprintf(stderr, "[gameplay] aim assist off with a pad: aim cone @0x%08X returns its no-target value %.3f "
                            "(the stick smoother still runs)\n", self, kz2_gp_f32(self - 0xCu));
        if (kz2_aim_in_mod) kz2_aim_stats_cone(&kz2_aim, kz2_gp_f32(out));
        return;
    }
    lifted(ctx);
    if (kz2_aim_site_mode == KZ2_AIM_MODE_FULL && kz2_aim_strength_now != 1.0f && kz2_aim_cone_site((uint32_t)ctx->lr)) {
        const float f = kz2_gp_f32(out), g = kz2_aim_scale_cone(f, kz2_aim_strength_now);
        uint32_t u; memcpy(&u, &g, 4); vm_write32(out, u);
        if (g != f && (++kz2_aim_scaled_cone <= 5 || kz2_aim_scaled_cone % 300 == 0) && (kz2_aim_log_on() || kz2_gp_log_on()))
            fprintf(stderr, "[aim] strength %.3g: cone factor %.3f -> %.3f (%u scaled)\n", kz2_aim_strength_now, f, g,
                    kz2_aim_scaled_cone);
    }
    if (kz2_aim_in_mod) kz2_aim_stats_cone(&kz2_aim, kz2_gp_f32(out));
}
/* The pull (r3 = M, r4 = E, r5 = target, f1 = softlock factor M+0x0C, r6 / r7 = &dy / &dx out; ApplyInputModifier
 * adds them to the stick right after, 0x2F041C..0x2F0438): at aim_assist_strength s the two changes are times s. */
[[maybe_unused]] static void kz2_aim_pull(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t o6 = (uint32_t)ctx->gpr[6], o7 = (uint32_t)ctx->gpr[7];
    const int scale = kz2_aim_site_mode == KZ2_AIM_MODE_FULL && kz2_aim_strength_now != 1.0f && kz2_aim_pull_site((uint32_t)ctx->lr);
    lifted(ctx);
    if (!scale) return;
    const float a = kz2_gp_f32(o6), b = kz2_gp_f32(o7);
    const float a2 = kz2_aim_scale_pull(a, kz2_aim_strength_now), b2 = kz2_aim_scale_pull(b, kz2_aim_strength_now);
    uint32_t u; memcpy(&u, &a2, 4); vm_write32(o6, u); memcpy(&u, &b2, 4); vm_write32(o7, u);
    if ((a != 0.0f || b != 0.0f) && (++kz2_aim_scaled_pull <= 10 || kz2_aim_scaled_pull % 300 == 0) &&
        (kz2_aim_log_on() || kz2_gp_log_on()))
        fprintf(stderr, "[aim] strength %.3g: pull (%.4f, %.4f) -> (%.4f, %.4f) (%u scaled)\n", kz2_aim_strength_now, b, a, b2,
                a2, kz2_aim_scaled_pull);
}
/* Softlock search (r3 = M, r4 = E, r5 = &score out, r6 = &target out, cleared first). In SMOOTH mode it takes its own
 * no-softlock-curve exit (@0x2EFF28 in 1.29): r3 = 0, *target = 0, *score = the float at fn - 8 (lis/addi r26 = fn - 8),
 * so ApplyInputModifier runs no slowdown and no pull. */
[[maybe_unused]] static void kz2_aim_soft(ppu_context* ctx, void (*lifted)(ppu_context*), uint32_t self)
{
    const uint32_t out = (uint32_t)ctx->gpr[6], score = (uint32_t)ctx->gpr[5];
    if (kz2_aim_site_mode == KZ2_AIM_MODE_SMOOTH && kz2_aim_soft_site((uint32_t)ctx->lr)) {
        vm_write32(out, 0);
        vm_write32(score, vm_read32(self - 8u));
        ctx->gpr[3] = 0;
        if (++kz2_aim_noassist_soft == 1 || kz2_aim_noassist_soft % 3000 == 0)
            fprintf(stderr, "[gameplay] aim assist off with a pad: softlock search @0x%08X leaves no target (%u updates; "
                            "score %.3f)\n", self, kz2_aim_noassist_soft, kz2_gp_f32(self - 8u));
        if (kz2_aim_in_mod) kz2_aim_stats_soft(&kz2_aim, 0);
        return;
    }
    lifted(ctx);
    if (kz2_aim_in_mod) kz2_aim_stats_soft(&kz2_aim, vm_read32(out) != 0);
}
#ifdef PPU_OVERRIDE_002EF0C0
void func_002EF0C0(ppu_context* ctx) { kz2_aim_pull(ctx, func_002EF0C0__lifted); }   // @0x002EF0C0 aim pull (1.29)
#endif
#ifdef PPU_OVERRIDE_002E3E98
void func_002E3E98(ppu_context* ctx) { kz2_aim_pull(ctx, func_002E3E98__lifted); }   // @0x002E3E98 aim pull (v1.01)
#endif
/* Softlock search (r3 = M, r4 = E, r6 = &target out, cleared first): no target = ApplyInputModifier skips the slowdown
 * @0x2EF948 and the pull @0x2EF7E8. */
[[maybe_unused]] static void kz2_aim_soft(ppu_context* ctx, void (*lifted)(ppu_context*), uint32_t self);
#ifdef PPU_OVERRIDE_002EFEB8
void func_002EFEB8(ppu_context* ctx) { kz2_aim_soft(ctx, func_002EFEB8__lifted, 0x002EFEB8u); }   // @0x002EFEB8 (1.29)
#endif
#ifdef PPU_OVERRIDE_002E4C90
void func_002E4C90(ppu_context* ctx) { kz2_aim_soft(ctx, func_002E4C90__lifted, 0x002E4C90u); }   // @0x002E4C90 (v1.01)
#endif
/* The finder's per-candidate line-of-sight query (world vf 0x18 = the thunk 0x19BFD8 -> 0x19BEF8; r4 = 0, r5 = the
 * candidate's 16-byte point block (candidate + 4), r6 = the candidate entity, r7 = the finder's filter object, r8 = the
 * finder's state: after the call +0x1C = the hit index (-1 = none) and byte +0x20 = "it is the candidate"). */
[[maybe_unused]] static void kz2_aim_los(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    if (!kz2_aim_in_mod) { lifted(ctx); return; }
    const uint32_t pts = (uint32_t)ctx->gpr[5], ent = (uint32_t)ctx->gpr[6], st = (uint32_t)ctx->gpr[8];
    static int s_where;
    if (!s_where) {   /* 0x19BEF8 with r4 = 0: (*(*(this - 0x138 + 0x1A4) + 0xC4))->vf 0x50 does the query */
        s_where = 1;
        const uint32_t th = (uint32_t)ctx->gpr[3] - 0x138u, a = vm_read32(th + 0x1A4), o = a ? vm_read32(a + 0xC4) : 0;
        const uint32_t vt = o ? vm_read32(o) : 0, opd = vt ? vm_read32(vt + 0x50) : 0;
        fprintf(stderr, "[aim] los query: this 0x%08X, +0x1A4 0x%08X, +0xC4 0x%08X, vtable 0x%08X, vf 0x50 OPD 0x%08X -> code 0x%08X;"
                " filter 0x%08X vtable 0x%08X, masks 0x%08X 0x%08X 0x%08X 0x%08X\n", th, a, o, vt, opd, opd ? vm_read32(opd) : 0,
                (uint32_t)ctx->gpr[7], vm_read32((uint32_t)ctx->gpr[7]), vm_read32((uint32_t)ctx->gpr[7] + 4),
                vm_read32((uint32_t)ctx->gpr[7] + 8), vm_read32((uint32_t)ctx->gpr[7] + 12), vm_read32((uint32_t)ctx->gpr[7] + 16));
    }
    const uint32_t cnt0 = vm_read32(st + 0x10);
    float p[8];
    for (int i = 0; i < 8; i++) p[i] = kz2_gp_f32(pts + 4u * (uint32_t)i);
    lifted(ctx);
    static unsigned n, none, other, hit;
    const int32_t idx = (int32_t)vm_read32(st + 0x1C);
    const unsigned fl = vm_read8(st + 0x20);
    n++; if (idx == -1) none++; else if (!fl) other++; else hit++;
    if (n <= 8 || n % 500 == 0)
        fprintf(stderr, "[aim] los #%u: entity 0x%08X at (%.1f, %.1f, %.1f), block %.2f %.2f %.2f %.2f | %.2f %.2f %.2f %.2f -> r3 %u,"
                " hit %d, flag %u, state hits %u -> %u (so far: %u none, %u other, %u the candidate)\n", n, ent, kz2_gp_f32(ent + 0xB0),
                kz2_gp_f32(ent + 0xB4), kz2_gp_f32(ent + 0xB8), p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7],
                (uint32_t)ctx->gpr[3], idx, fl, cnt0, vm_read32(st + 0x10), none, other, hit);
}
/* The line-of-sight queue: the query (0x1FED30) appends {state, request} to *(0xF3B288) + 0x338; 0x68F6F0 (submit, r3 =
 * queue) and 0x68FAC0 (collect, r3 = queue, r4 = wait) run it; the collect gives up unless byte +0x10 is set, +4 (count)
 * is non-zero and the job at +0x14 reports done (0x508D40 at lr 0x68FB44). KZ2_AIM_LOG counts what they see, for this
 * queue only, one line per 200 collects. */
static unsigned kz2_los_sub, kz2_los_col, kz2_los_col_off, kz2_los_col_empty, kz2_los_col_wait, kz2_los_ready, kz2_los_notready;
[[maybe_unused]] static void kz2_los_submit(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t q = (uint32_t)ctx->gpr[3], g = kz2_aim_log_on() ? vm_read32(0x00F3B288u) : 0;
    if (g && q == g + 0x338) {
        static unsigned s_n;
        if (++s_n <= 3) fprintf(stderr, "[aim] los submit #%u: queue count %u, flag +0x10 %u, lr 0x%08X\n", s_n, vm_read32(q + 4),
                                vm_read8(q + 0x10), (uint32_t)ctx->lr);
        kz2_los_sub++;
    }
    lifted(ctx);
}
static uint32_t kz2_aim_M;   /* the soldier's JoystickInputModifier (its finder states are M+0x18 aim, M+0x3C softlock) */
[[maybe_unused]] static void kz2_los_collect(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t q = (uint32_t)ctx->gpr[3], g = kz2_aim_log_on() ? vm_read32(0x00F3B288u) : 0;
    if (g && q == g + 0x338 && kz2_aim_M && vm_read8(q + 0x10) && vm_read32(q + 4)) {
        /* Ours in this batch: queue entries {state, request, valid} (12 B at +8); after the collect the job's results
         * (44 B each at *(q + 0x1C): from, to, ..., +0x24 -> hit {+0 object, +4 t, +8 normal}) and each state's +0x1C. */
        const uint32_t n = vm_read32(q + 4), arr = vm_read32(q + 8);
        uint32_t idx[8], st[8]; int k = 0;
        for (uint32_t i = 0; i < n && i < 512 && k < 8; i++) {
            const uint32_t s0 = vm_read32(arr + 12 * i);
            if (s0 == kz2_aim_M + 0x18 || s0 == kz2_aim_M + 0x3C) { idx[k] = i; st[k] = s0; k++; }
        }
        lifted(ctx);
        static unsigned s_lines, s_ours, s_clear, s_all, s_all_clear, s_batches;
        const uint32_t res = vm_read32(q + 0x1C);
        static unsigned s_hist[8], s_noobj, s_near;   /* t: null hit, <0.1, <0.5, <0.9, <0.999, <1, ==1, >1 */
        static uint32_t s_obj[16]; static unsigned s_objn[16], s_objmiss, s_short; static float s_objlo[16], s_objhi[16];
        static uint32_t s_cv[16]; static unsigned s_cn[16], s_cclear, s_cshort[16], s_cok[16]; static float s_clen[16];
        /* Every caller of this queue (by the queue state's vtable: the aim finder 0xF9F02C, 11 m downward
         * ground probes 0xF97DE8, 1.3 m probes 0xFBB8D8, 3 m 0xF80B08; no AI line-of-sight caller seen on it). */
        for (uint32_t i = 0; i < n && i < 512; i++) {
            const uint32_t h = vm_read32(res + 44 * i + 0x24);
            s_all++;
            if (!h) { s_hist[0]++; continue; }
            const float t = kz2_gp_f32(h + 4);
            s_all_clear += t >= 1.0f;
            s_hist[t < 0.1f ? 1 : t < 0.5f ? 2 : t < 0.9f ? 3 : t < 0.999f ? 4 : t < 1.0f ? 5 : t == 1.0f ? 6 : 7]++;
            if (!vm_read32(h)) s_noobj++;
            if (t >= 0.999f && t != 1.0f && s_near++ < 6)
                fprintf(stderr, "[aim] los near-1 t %.9g (bits 0x%08X), object 0x%08X\n", t, vm_read32(h + 4), vm_read32(h));
            /* which objects the rays hit (every caller) and a sample of the short ones, with the queue state's
             * vtable as the caller (ASSUMPTION: entry i <-> result i, true while every entry is valid). */
            const uint32_t ob = vm_read32(h), sv = vm_read32(vm_read32(arr + 12 * i));
            int slot = -1;
            for (int j = 0; j < 16; j++) if (s_objn[j] && s_obj[j] == ob) { slot = j; break; }
            if (slot < 0) for (int j = 0; j < 16; j++) if (!s_objn[j]) { slot = j; s_obj[j] = ob; s_objlo[j] = 9.f; s_objhi[j] = -9.f; break; }
            if (slot >= 0) { s_objn[slot]++; if (t < s_objlo[slot]) s_objlo[slot] = t; if (t > s_objhi[slot]) s_objhi[slot] = t; }
            else s_objmiss++;
            {   /* per caller (the queue state's vtable): rays, clear, t < 0.1, mean length */
                int c = -1;
                for (int j = 0; j < 16; j++) if (s_cn[j] && s_cv[j] == sv) { c = j; break; }
                if (c < 0) for (int j = 0; j < 16; j++) if (!s_cn[j]) { c = j; s_cv[j] = sv; break; }
                if (c >= 0) {
                    const uint32_t r = res + 44 * i;
                    const float dx = kz2_gp_f32(r + 12) - kz2_gp_f32(r), dy = kz2_gp_f32(r + 16) - kz2_gp_f32(r + 4),
                                dz = kz2_gp_f32(r + 20) - kz2_gp_f32(r + 8);
                    s_cn[c]++; s_cok[c] += t >= 1.0f; s_cshort[c] += t < 0.1f; s_clen[c] += sqrtf(dx * dx + dy * dy + dz * dz);
                } else s_cclear++;
            }
            if (t < 0.1f && s_short++ % 1500 == 0) {
                const uint32_t r = res + 44 * i;
                fprintf(stderr, "[aim] los short: caller vtable 0x%08X, from (%.2f, %.2f, %.2f) to (%.2f, %.2f, %.2f), +0x18 0x%08X"
                        " +0x1C 0x%08X, t %.4f object 0x%08X (vtable 0x%08X, +4 0x%08X +8 0x%08X +0xC 0x%08X) normal (%.2f, %.2f, %.2f)"
                        " +0x14 0x%08X\n", sv, kz2_gp_f32(r), kz2_gp_f32(r + 4), kz2_gp_f32(r + 8), kz2_gp_f32(r + 12),
                        kz2_gp_f32(r + 16), kz2_gp_f32(r + 20), vm_read32(r + 0x18), vm_read32(r + 0x1C), t, ob,
                        ob ? vm_read32(ob) : 0, ob ? vm_read32(ob + 4) : 0, ob ? vm_read32(ob + 8) : 0, ob ? vm_read32(ob + 12) : 0,
                        kz2_gp_f32(h + 8), kz2_gp_f32(h + 12), kz2_gp_f32(h + 16), vm_read32(h + 0x14));
            }
        }
        if (s_batches % 250 == 249) {
            fprintf(stderr, "[aim] los objects (%u not tabled):", s_objmiss);
            for (int j = 0; j < 16; j++) if (s_objn[j])
                fprintf(stderr, " 0x%08X(vt 0x%08X) n %u t %.3f..%.3f;", s_obj[j], s_obj[j] ? vm_read32(s_obj[j]) : 0, s_objn[j],
                        s_objlo[j], s_objhi[j]);
            fprintf(stderr, "\n");
        }
        if (s_batches % 250 == 249) {
            fprintf(stderr, "[aim] los callers (%u not tabled):", s_cclear);
            for (int j = 0; j < 16; j++) if (s_cn[j])
                fprintf(stderr, " vt 0x%08X n %u clear %u short %u len %.1f;", s_cv[j], s_cn[j], s_cok[j], s_cshort[j], s_clen[j] / s_cn[j]);
            fprintf(stderr, "\n");
        }
        if (++s_batches % 100 == 0)
            fprintf(stderr, "[aim] los batches %u: all callers %u rays, %u clear (t >= 1); ours %u, %u clear; t: null %u, <0.1 %u,"
                    " <0.5 %u, <0.9 %u, <0.999 %u, <1 %u, =1 %u, >1 %u; no object %u\n", s_batches, s_all, s_all_clear, s_ours, s_clear,
                    s_hist[0], s_hist[1], s_hist[2], s_hist[3], s_hist[4], s_hist[5], s_hist[6], s_hist[7], s_noobj);
        for (int j = 0; j < k; j++) {
            const uint32_t r = res + 44 * idx[j], h = vm_read32(r + 0x24);
            const float tt = h ? kz2_gp_f32(h + 4) : -1.0f;
            s_ours++; s_clear += tt >= 1.0f;   /* 0x30A580: the state's flag = (t >= 1), i.e. the ray reached its end point */
            if (!(s_lines < 20 || s_ours % 40 == 0)) continue;
            s_lines++;
            const float hx = kz2_gp_f32(r) + tt * (kz2_gp_f32(r + 12) - kz2_gp_f32(r)), hy = kz2_gp_f32(r + 4) + tt * (kz2_gp_f32(r + 16) - kz2_gp_f32(r + 4));
            fprintf(stderr, "[aim] los t %.3f at (%.1f, %.1f); %u of ours so far, %u clear\n", tt, hx, hy, s_ours, s_clear);
            if (s_lines > 20) continue;
            fprintf(stderr, "[aim] los result: entry %u of %u (%s state): from (%.1f, %.1f, %.1f) to (%.1f, %.1f, %.1f), hit 0x%08X"
                    " {object 0x%08X, t %.3f}, state +0x1C %d +0x20 %u, state vtable 0x%08X vf 0xC code 0x%08X\n", idx[j], n,
                    st[j] == kz2_aim_M + 0x18 ? "aim" : "softlock", kz2_gp_f32(r), kz2_gp_f32(r + 4), kz2_gp_f32(r + 8),
                    kz2_gp_f32(r + 12), kz2_gp_f32(r + 16), kz2_gp_f32(r + 20), h, h ? vm_read32(h) : 0, h ? kz2_gp_f32(h + 4) : -1.0f,
                    (int32_t)vm_read32(st[j] + 0x1C), vm_read8(st[j] + 0x20), vm_read32(st[j]),
                    vm_read32(st[j]) ? vm_read32(vm_read32(vm_read32(st[j]) + 0xC)) : 0);
        }
        return;
    }
    if (g && q == g + 0x338) {
        kz2_los_col++;
        if (!vm_read8(q + 0x10)) kz2_los_col_off++;
        if (!vm_read32(q + 4)) kz2_los_col_empty++;
        if ((uint32_t)ctx->gpr[4] & 0xFF) kz2_los_col_wait++;
        static unsigned s_n;
        if (++s_n <= 3 || s_n % 200 == 0)
            fprintf(stderr, "[aim] los collect #%u (lr 0x%08X, wait %u, flag %u, count %u): %u submits, %u collects (%u flag off, %u empty,"
                    " %u waiting), job done %u / not done %u\n", s_n, (uint32_t)ctx->lr, (uint32_t)ctx->gpr[4] & 0xFF, vm_read8(q + 0x10),
                    vm_read32(q + 4), kz2_los_sub, kz2_los_col, kz2_los_col_off, kz2_los_col_empty, kz2_los_col_wait, kz2_los_ready,
                    kz2_los_notready);
    }
    lifted(ctx);
}
[[maybe_unused]] static void kz2_los_done(ppu_context* ctx, void (*lifted)(ppu_context*), uint32_t lr_collect)
{
    const uint32_t lr = (uint32_t)ctx->lr;
    lifted(ctx);
    if (lr == lr_collect && kz2_aim_log_on()) { if ((uint32_t)ctx->gpr[3]) kz2_los_ready++; else kz2_los_notready++; }
}
#ifdef PPU_OVERRIDE_0068F6F0
void func_0068F6F0(ppu_context* ctx) { kz2_los_submit(ctx, func_0068F6F0__lifted); }   // @0x0068F6F0 (1.29)
#endif
#ifdef PPU_OVERRIDE_0068FAC0
void func_0068FAC0(ppu_context* ctx) { kz2_los_collect(ctx, func_0068FAC0__lifted); }   // @0x0068FAC0 (1.29)
#endif
#ifdef PPU_OVERRIDE_00508D40
void func_00508D40(ppu_context* ctx) { kz2_los_done(ctx, func_00508D40__lifted, 0x0068FB44u); }   // @0x00508D40 (1.29)
#endif
#ifdef PPU_OVERRIDE_00682000
void func_00682000(ppu_context* ctx) { kz2_los_submit(ctx, func_00682000__lifted); }   // @0x00682000 (v1.01)
#endif
#ifdef PPU_OVERRIDE_006823D0
void func_006823D0(ppu_context* ctx) { kz2_los_collect(ctx, func_006823D0__lifted); }   // @0x006823D0 (v1.01)
#endif
#ifdef PPU_OVERRIDE_004FBC90
void func_004FBC90(ppu_context* ctx) { kz2_los_done(ctx, func_004FBC90__lifted, 0x006823D0u + 0x84u); }   // @0x004FBC90 (v1.01; lr ASSUMPTION: same offset)
#endif
#ifdef PPU_OVERRIDE_0019BFD8
void func_0019BFD8(ppu_context* ctx) { kz2_aim_los(ctx, func_0019BFD8__lifted); }   // @0x0019BFD8 (1.29)
#endif
#ifdef PPU_OVERRIDE_00196660
void func_00196660(ppu_context* ctx) { kz2_aim_los(ctx, func_00196660__lifted); }   // @0x00196660 (v1.01)
#endif
#ifdef PPU_OVERRIDE_002F9F50
void func_002F9F50(ppu_context* ctx) { kz2_aim_gather(ctx, func_002F9F50__lifted, 0x00F3B288u); }   // @0x002F9F50 (1.29)
#endif
#ifdef PPU_OVERRIDE_002FAF70
void func_002FAF70(ppu_context* ctx) { kz2_aim_find(ctx, func_002FAF70__lifted); }   // @0x002FAF70 (1.29)
#endif
#ifdef PPU_OVERRIDE_002EFC88
void func_002EFC88(ppu_context* ctx) { kz2_aim_cone(ctx, func_002EFC88__lifted, 0x002EFC88u); }   // @0x002EFC88 (1.29)
#endif
#ifdef PPU_OVERRIDE_002EECD8
void func_002EECD8(ppu_context* ctx) { kz2_aim_gather(ctx, func_002EECD8__lifted, 0); }   // @0x002EECD8 (v1.01)
#endif
#ifdef PPU_OVERRIDE_002EFCF8
void func_002EFCF8(ppu_context* ctx) { kz2_aim_find(ctx, func_002EFCF8__lifted); }   // @0x002EFCF8 (v1.01)
#endif
#ifdef PPU_OVERRIDE_002E4A60
void func_002E4A60(ppu_context* ctx) { kz2_aim_cone(ctx, func_002E4A60__lifted, 0x002E4A60u); }   // @0x002E4A60 (v1.01)
#endif

[[maybe_unused]] static void kz2_aim_gate(ppu_context* ctx, void (*lifted)(ppu_context*), const uint32_t* sites, int n,
                                          int stick_args, const char* name)
{
    const kz2_gameplay_cfg* cfg = kz2_gameplay_get();
    const int mode = kz2_gp_aim_mode(cfg, kz2_look_is_mouse());   /* auto: off while the mouse looks */
    const int on = mode == KZ2_AIM_MODE_FULL;
    const uint32_t lr = (uint32_t)ctx->lr;
    static unsigned skipped, ran_site, changed, ran_other;
    /* a pad with aim_assist = off keeps ApplyInputModifier for its stick smoother (KZ2_AIM_MODE_SMOOTH; the
     * softlock and cone hooks take their no-target exits); the shoot/zoom helper (target help only) stays skipped. */
    if (kz2_gp_aim_skip(on, lr, sites, n) && !(mode == KZ2_AIM_MODE_SMOOTH && stick_args)) {
        if (stick_args && kz2_aim_log_on()) { kz2_aim.mod++; kz2_aim_flush("off (modifier skipped)"); }
        if (kz2_gp_log_on() && (++skipped == 1 || skipped % 600 == 0))
            fprintf(stderr, "[gameplay] aim assist off: %s skipped at lr 0x%08X (%u skipped, %u ran at the look sites, %u other callers)\n",
                    name, lr, skipped, ran_site, ran_other);
        else skipped++;
        return;
    }
    int site = 0;
    for (int i = 0; i < n; i++) site |= sites[i] == lr;
    if (!site) { ran_other++; lifted(ctx); return; }
    ran_site++;
    /* the softlock / cone / pull hooks read the mode while the lifted body runs (the look update is one thread) */
    struct site_mode_scope {
        explicit site_mode_scope(int m, float s) { kz2_aim_site_mode = m; kz2_aim_strength_now = s; }
        ~site_mode_scope() { kz2_aim_site_mode = KZ2_AIM_MODE_SKIP; kz2_aim_strength_now = 1.0f; }
    } scope(stick_args ? mode : KZ2_AIM_MODE_SKIP, cfg->aim_strength);
    if (mode == KZ2_AIM_MODE_SMOOTH && stick_args && kz2_gp_log_on() && (ran_site == 1 || ran_site % 600 == 0))
        fprintf(stderr, "[gameplay] aim assist off with a pad: %s runs for its stick smoother only (%u calls)\n", name, ran_site);
    if (stick_args && kz2_aim_log_on()) {   /* KZ2_AIM_LOG: inputs, outputs and the target search under it */
        const uint32_t M = (uint32_t)ctx->gpr[3], px = (uint32_t)ctx->gpr[5], py = (uint32_t)ctx->gpr[6];
        kz2_aim_M = M;
        const float fx = kz2_gp_f32(px), fy = kz2_gp_f32(py);
        const unsigned found0 = kz2_aim.found + kz2_aim.soft_found, cand0 = kz2_aim.cand_max;
        /* The JoystickInputModifierResource in force (M+8: the mounted gun's, else the weapon's InventoryWeaponResource
         * +0x11C, else SoldierResource +0x484; picked by 0x1668A8 each Update): which curves it has decides what can run.
         * +0x14 AimAssistDistanceCurve (aim cone factor), +0x1C SoftlockDistanceCurve (no softlock target = no slowdown
         * and no pull), +0x34 shoot curve, +0x40 zoom AssistCurve; cones in degrees. Logged when it changes. */
        static uint32_t s_res = 0xFFFFFFFFu;
        const uint32_t res = vm_read32(M + 8);
        if (res != s_res) {
            s_res = res;
            if (res)
                fprintf(stderr, "[aim] resource 0x%08X: softlock curve 0x%08X cone %.3g/%.3g, aim curve 0x%08X cone %.3g/%.3g,"
                        " shoot curve 0x%08X cone %.3g/%.3g, zoom curve 0x%08X cone %.3g/%.3g, accel %.3g/%.3g\n", res,
                        vm_read32(res + 0x1C), kz2_gp_f32(res + 0x24), kz2_gp_f32(res + 0x28), vm_read32(res + 0x14),
                        kz2_gp_f32(res + 0x0C), kz2_gp_f32(res + 0x10), vm_read32(res + 0x34), kz2_gp_f32(res + 0x2C),
                        kz2_gp_f32(res + 0x30), vm_read32(res + 0x40), kz2_gp_f32(res + 0x38), kz2_gp_f32(res + 0x3C),
                        kz2_gp_f32(res + 0x48), kz2_gp_f32(res + 0x44));
            else fprintf(stderr, "[aim] resource none (M+8 = 0)\n");
        }
        kz2_aim_in_mod = 1;
        lifted(ctx);
        kz2_aim_in_mod = 0;
        const float ox = kz2_gp_f32(px), oy = kz2_gp_f32(py);
        kz2_aim_stats_mod(&kz2_aim, fx, fy, ox, oy, kz2_gp_f32(M + 0x10), kz2_gp_f32(M + 0x0C));
        static unsigned s_events;
        if ((ox != fx || oy != fy || kz2_aim.found + kz2_aim.soft_found != found0 || kz2_aim.cand_max != cand0) && ++s_events <= 40)
            fprintf(stderr, "[aim] event: stick (%.3f, %.3f) -> (%.3f, %.3f), M+0x10 %.3f M+0x0C %.3f, cand max %u, found %u\n",
                    fx, fy, ox, oy, kz2_gp_f32(M + 0x10), kz2_gp_f32(M + 0x0C), kz2_aim.cand_max, kz2_aim.found);
        kz2_aim_flush(mode == KZ2_AIM_MODE_SMOOTH ? "off with a pad (smoother only)" : "on");
        return;
    }
    if (!kz2_gp_log_on() || !stick_args) { lifted(ctx); return; }
    const uint32_t px = (uint32_t)ctx->gpr[5], py = (uint32_t)ctx->gpr[6];
    const float fx = kz2_gp_f32(px), fy = kz2_gp_f32(py);
    lifted(ctx);
    if (kz2_gp_f32(px) != fx || kz2_gp_f32(py) != fy) {   /* float compare: -0.0 -> 0.0 is no edit */
        if (++changed <= 5 || changed % 300 == 0)
            fprintf(stderr, "[gameplay] aim assist on: %s edited the stick at lr 0x%08X: (%.3f, %.3f) -> (%.3f, %.3f)"
                    " (%u edits in %u calls)\n", name, lr, fx, fy, kz2_gp_f32(px), kz2_gp_f32(py), changed, ran_site);
    } else if (ran_site % 600 == 1) {
        fprintf(stderr, "[gameplay] aim assist on: %s left the stick alone (%u edits in %u calls)\n", name, changed, ran_site);
    }
}
static const uint32_t kz2_aim_sites_modifier_129[] = { 0x00174160u };
static const uint32_t kz2_aim_sites_shoot_129[] = { 0x001741F8u, 0x001742CCu };
static const uint32_t kz2_aim_sites_modifier_101[] = { 0x0016E900u };
static const uint32_t kz2_aim_sites_shoot_101[] = { 0x0016E998u, 0x0016EA2Cu };
#ifdef PPU_OVERRIDE_002F0120
void func_002F0120(ppu_context* ctx) { kz2_aim_gate(ctx, func_002F0120__lifted, kz2_aim_sites_modifier_129, 1, 1, "ApplyInputModifier"); }   // @0x002F0120 (1.29)
#endif
#ifdef PPU_OVERRIDE_002F0880
void func_002F0880(ppu_context* ctx) { kz2_aim_gate(ctx, func_002F0880__lifted, kz2_aim_sites_shoot_129, 2, 0, "ShootZoomAssist"); }   // @0x002F0880 (1.29)
#endif
#ifdef PPU_OVERRIDE_002E4EF8
void func_002E4EF8(ppu_context* ctx) { kz2_aim_gate(ctx, func_002E4EF8__lifted, kz2_aim_sites_modifier_101, 1, 1, "ApplyInputModifier"); }   // @0x002E4EF8 (v1.01)
#endif
#ifdef PPU_OVERRIDE_002E5658
void func_002E5658(ppu_context* ctx) { kz2_aim_gate(ctx, func_002E5658__lifted, kz2_aim_sites_shoot_101, 2, 0, "ShootZoomAssist"); }   // @0x002E5658 (v1.01)
#endif

/* crouch_toggle. prof_global = the address holding the PlayerProfile pointer. */
[[maybe_unused]] static void kz2_crouch_body(ppu_context* ctx, void (*lifted)(ppu_context*), uint32_t prof_global)
{
    const kz2_gameplay_cfg* c = kz2_gameplay_get();
    const uint32_t C = (uint32_t)ctx->gpr[3];
    const uint32_t P = vm_read32(prof_global);
    const int active = c->crouch_toggle && P;
    uint8_t saved = 0;
    if (active) { saved = vm_read8(P + 0x61); vm_write8(P + 0x61, 1); }
    lifted(ctx);
    if (active) vm_write8(P + 0x61, saved);   /* the save keeps the player's own value */
    if (kz2_gp_log_on() && C) {
        static uint32_t last = 0xFFFFFFFFu; static unsigned lines;
        const uint32_t E = vm_read32(C + 0x10);
        const uint32_t st = (uint32_t)(vm_read8(C + 0x3BC) | (vm_read8(C + 0x3B8) << 8) | ((E ? vm_read32(E + 0x360) : 0xFF) << 16));
        if (st != last && lines < 200) {
            lines++; last = st;
            fprintf(stderr, "[gameplay] crouch: want C+0x3BC=%u latch C+0x3B8=%u stance E+0x360=%u (toggle %d, P+0x61 %u, ret %u)\n",
                    st & 0xFF, (st >> 8) & 0xFF, st >> 16, c->crouch_toggle, vm_read8(P + 0x61), (uint32_t)ctx->gpr[3]);
        }
    }
}
[[maybe_unused]] static void kz2_net_state(ppu_context* ctx, void (*lifted)(ppu_context*), uint32_t site_lr)
{
    const uint32_t lr = (uint32_t)ctx->lr;
    lifted(ctx);
    if (lr != site_lr) return;
    const kz2_gameplay_cfg* c = kz2_gameplay_get();
    static int32_t last = 0x7FFFFFFF; static unsigned lines;
    const int32_t r = (int32_t)ctx->gpr[3];
    if (kz2_gp_log_on() && r != last && lines++ < 20) {
        last = r;
        fprintf(stderr, "[gameplay] 0x7B388() at the crouch decision (lr 0x%08X) = %d%s\n", lr, r,
                c->crouch_toggle && !r ? " (forced to 1: crouch_toggle)" : "");
    }
    if (c->crouch_toggle) ctx->gpr[3] = 1;
}
#ifdef PPU_OVERRIDE_00176208
void func_00176208(ppu_context* ctx) { kz2_crouch_body(ctx, func_00176208__lifted, 0x011B0540u + 0x240u); }   // @0x00176208 (1.29)
#endif
#ifdef PPU_OVERRIDE_0007B388
void func_0007B388(ppu_context* ctx) { kz2_net_state(ctx, func_0007B388__lifted, 0x001762ACu); }   // @0x0007B388 (1.29)
#endif
#ifdef PPU_OVERRIDE_00170990
void func_00170990(ppu_context* ctx) { kz2_crouch_body(ctx, func_00170990__lifted, 0x0117E740u + 0x240u); }   // @0x00170990 (v1.01)
#endif
#ifdef PPU_OVERRIDE_0007A098
void func_0007A098(ppu_context* ctx) { kz2_net_state(ctx, func_0007A098__lifted, 0x00170A34u); }   // @0x0007A098 (v1.01)
#endif

/* cover_toggle. */
static kz2_cover_latch kz2_cover;
static unsigned kz2_cover_lines;
[[maybe_unused]] static void kz2_cover_frame(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    kz2_cover_begin(&kz2_cover);
    const int before = kz2_cover.latch;
    const uint32_t C = (uint32_t)ctx->gpr[3];
    lifted(ctx);
    kz2_cover_end(&kz2_cover);
    static unsigned latched_frames;
    const unsigned was_latched = latched_frames;   /* frames the latch had been on before this one */
    latched_frames = kz2_cover.latch ? latched_frames + 1 : 0;
    if (kz2_gp_log_on() && kz2_gameplay_get()->cover_toggle && kz2_cover_lines < 300 &&
        (kz2_cover.latch != before || kz2_cover.queried != 0) ) {
        static int last_l = -1, last_q = -1, last_f = -1;
        if (kz2_cover.latch != last_l || kz2_cover.queried != last_q || kz2_cover.found != last_f) {
            last_l = kz2_cover.latch; last_q = kz2_cover.queried; last_f = kz2_cover.found;
            kz2_cover_lines++;
            const uint32_t E = vm_read32(C + 0x10);
            fprintf(stderr, "[gameplay] cover frame: latch %d -> %d (query reached %d, cover found %d), C+0x13C=0x%08X"
                    " stance E+0x360=%u, latched for %u frames before\n", before, kz2_cover.latch, kz2_cover.queried, kz2_cover.found,
                    vm_read32(C + 0x13C), E ? vm_read32(E + 0x360) : 0xFFu, was_latched);
        }
    }
}
[[maybe_unused]] static void kz2_cover_held_q(ppu_context* ctx, void (*lifted)(ppu_context*), void (*pressed)(ppu_context*),
                                              uint32_t site_lr)
{
    if ((uint32_t)ctx->lr != site_lr || !kz2_gameplay_get()->cover_toggle) { kz2_pad_query(ctx, lifted, 0); return; }
    const uint64_t input = ctx->gpr[3], lr = ctx->lr;
    lifted(ctx);
    const int orig = (uint32_t)ctx->gpr[3] & 1u;
    int p[3];
    static const int ids[3] = { 11, 5, 4 };   /* Cover, Jump, SprintToggle */
    for (int i = 0; i < 3; i++) { ctx->gpr[3] = input; ctx->gpr[4] = (uint64_t)ids[i]; pressed(ctx); p[i] = ((uint32_t)ctx->gpr[3]) != 0; }
    ctx->lr = lr;
    const int before = kz2_cover.latch;
    const int held = kz2_cover_held(&kz2_cover, 1, orig, p[0], p[1], p[2]);
    ctx->gpr[3] = (uint64_t)held;
    if (kz2_gp_log_on() && (p[0] || p[1] || p[2]) && kz2_cover_lines < 300) {
        kz2_cover_lines++;
        fprintf(stderr, "[gameplay] cover query: pressed cover %d jump %d sprint %d, button held %d: latch %d -> %d, game told held=%d\n",
                p[0], p[1], p[2], orig, before, kz2_cover.latch, held);
    }
}
[[maybe_unused]] static void kz2_cover_find(ppu_context* ctx, void (*lifted)(ppu_context*), uint32_t site_lr)
{
    const uint32_t lr = (uint32_t)ctx->lr;
    lifted(ctx);
    if (lr == site_lr) {
        kz2_cover_found(&kz2_cover, (uint32_t)ctx->gpr[3] != 0);
        static unsigned calls, hits;
        calls++; hits += kz2_cover.found;
        if (kz2_gp_log_on() && kz2_gameplay_get()->cover_toggle && (kz2_cover.found || calls == 1 || calls % 50 == 0) && kz2_cover_lines < 300) {
            kz2_cover_lines++;
            fprintf(stderr, "[gameplay] cover finder: found %d (%u calls, %u found)\n", kz2_cover.found, calls, hits);
        }
    }
}
#ifdef PPU_OVERRIDE_001763B0
void func_001763B0(ppu_context* ctx) { kz2_cover_frame(ctx, func_001763B0__lifted); }   // @0x001763B0 (1.29)
#endif
#ifdef PPU_OVERRIDE_000B1E78
void func_000B1E78(ppu_context* ctx) { kz2_cover_find(ctx, func_000B1E78__lifted, 0x001764D0u); }   // @0x000B1E78 (1.29)
#endif
#ifdef PPU_OVERRIDE_00170B38
void func_00170B38(ppu_context* ctx) { kz2_cover_frame(ctx, func_00170B38__lifted); }   // @0x00170B38 (v1.01)
#endif
#ifdef PPU_OVERRIDE_000AD4F0
void func_000AD4F0(ppu_context* ctx) { kz2_cover_find(ctx, func_000AD4F0__lifted, 0x00170C58u); }   // @0x000AD4F0 (v1.01)
#endif
#if defined(PPU_OVERRIDE_00082248) && defined(PPU_OVERRIDE_00082290)
void func_00082248(ppu_context* ctx) { kz2_cover_held_q(ctx, func_00082248__lifted, func_00082290__lifted, 0x001764A8u); }   // @0x00082248 (1.29)
#elif defined(PPU_OVERRIDE_00082248)
void func_00082248(ppu_context* ctx) { kz2_pad_query(ctx, func_00082248__lifted, 0); }   // @0x00082248 (1.29)
#endif
#if defined(PPU_OVERRIDE_00080D38) && defined(PPU_OVERRIDE_00080D80)
void func_00080D38(ppu_context* ctx) { kz2_cover_held_q(ctx, func_00080D38__lifted, func_00080D80__lifted, 0x00170C30u); }   // @0x00080D38 (v1.01)
void func_00080D80(ppu_context* ctx) { func_00080D80__lifted(ctx); }   // @0x00080D80 (v1.01): listed so the cover hook can call the body
#endif

/* ---- Mouse look (ENHANCEMENT; adapted from Project Helghast's native mouse look, same author, MIT) -------
 * Runtime side: libs/input/pad_mouse.{h,c} (patch 6046: Raw Input counts summed on the window thread, the in-play
 * pointer clip). Settings: gameplay.ini [mouse] (kz2_gameplay.h). The counts are added where the game itself writes the
 * look, after the stick path, so the dead zone, response curve and aim assist never see them:
 *   UpdateLook(C, f1 = game clock in s) @0x173E80 (v1.01 0x16E620; the RE notes "An earlier change") is wrapped only to note C
 *   and the clock step dt (f1 is the clock, not a step: run r63-a).
 *   Its last act is C->vf44(C, f1 = 0, f2 = pitch) = @0x15A7F0 (vtable 0xF804BC + 0xB0), which stores f1 at C+0x74, the
 *   pitch at C+0x78 and the pitch rate at C+0xFC; the call returns to lr 0x174CE8. Just before it UpdateLook stored the
 *   yaw rate at C+0xF8 (0x174CCC `stfs f28,0xF8(r31)`), in stick units: the yaw-rate getter @0x167CF0 returns
 *   C+0xF8 x HumanoidResource+0x2A8 (turn speed, degrees per second) x pi/180 (the constant at 0x167CE4).
 *   The pre-hook (lr 0x174CE8 and the C that UpdateLook is running for) takes the counts and adds
 *     yaw:   C+0xF8 += dyaw / (turn x pi/180 x dt)     (kz2_mouse_rate_for; the body turns by dyaw this update)
 *     pitch: f2 = clamp(f2 + dpitch, E+0x1A4, E+0x1A8)  (UpdateLook's own clamp at 0x174C64..0x174C9C)
 *   E = C+0x10, res = E+0xC4. Skipped (counts dropped) while a scripted look-at runs (E+0x6B0 set, 0x174334).
 *   Zoomed = C+0x13C bit 6 (the RE notes "An earlier change": the zoom bit). ASSUMPTION: mouse_zoom_sensitivity is the only
 *   zoom scale (the stick's zoom slowdown lives in tables not traced).
 * 1.29 only: the v1.01 twin of @0x15A7F0 and its return address were not read.
 * Test input: KZ2_MOUSE_SCRIPT="T:dx,dy[*N] ..." (pad_mouse.h; T = seconds since the first look update), added to the
 * take, or sent through SendInput (the whole WM_INPUT path) with KZ2_MOUSE_SEND=1; KZ2_MOUSE_ANCHOR=<file> starts its
 * clock when that file appears. KZ2_MOUSE_LOG=1: one [mouse] line
 * per update that moved (and the stick's own rate and pitch while it is held); KZ2_MOUSE_DUMP=1 also writes E's first
 * 0x400 bytes as floats at the first update, at the script's start and one second after each script event ends. The
 * body heading is atan2(E+0x40, E+0x3C) and the view's forward vector E+0x31C (its z = sin(pitch)): run r63-b. */
#include "../../libs/input/pad_mouse.h"   /* patch 6046 (from runtime/ppu, as ../diag above) */
#include <chrono>
#include <cmath>

static kz2_look_src kz2_look;
static uint32_t kz2_ul_C;
static double kz2_ul_dt;
static int kz2_look_is_mouse(void) { return kz2_look.mouse; }

static int kz2_mouse_env_on(const char* n)
{
    const char* e = getenv(n);
    return e && *e && *e != '0';
}

static void kz2_mouse_dump(const char* why, uint32_t E, double t)
{
    char line[256 * 12 + 128];
    int n = snprintf(line, sizeof line, "[mouse] dump %s t=%.3f E=0x%08X:", why, t, E);
    for (uint32_t o = 0; o < 0x400 && n < (int)sizeof line - 16; o += 4) n += snprintf(line + n, sizeof line - n, " %.5g", kz2_gp_f32(E + o));
    fprintf(stderr, "%s\n", line);
}

static void kz2_mouse_pre(ppu_context* ctx)
{
    static int s_init, s_nev, s_send, s_log, s_dump;
    static PadMouseEv s_ev[PAD_MOUSE_SCRIPT_MAX];
    static double s_t0, s_dump_at = -1.0, s_last_line;
    static unsigned long long s_updates, s_moves;
    const kz2_gameplay_cfg* c = kz2_gameplay_get();
    const double now = std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
    if (!s_init) {
        s_init = 1;
        s_t0 = now;
        pad_mouse_set_enabled(c->mouse_look);
        int bad = 0;
        s_nev = pad_mouse_script_parse(getenv("KZ2_MOUSE_SCRIPT"), s_ev, PAD_MOUSE_SCRIPT_MAX, &bad);
        s_send = kz2_mouse_env_on("KZ2_MOUSE_SEND");
        s_log = kz2_mouse_env_on("KZ2_MOUSE_LOG");
        s_dump = kz2_mouse_env_on("KZ2_MOUSE_DUMP");
        fprintf(stderr, "[mouse] look hook reached (UpdateLook -> view setter, lr 0x%08X): mouse look %s, %.6f rad/count;"
                        " script %d event(s)%s, %d unreadable\n", (uint32_t)ctx->lr, c->mouse_look ? "on" : "off",
                kz2_mouse_rad_per_count(c), s_nev, s_send ? " through SendInput" : "", bad);
    }
    /* KZ2_MOUSE_ANCHOR=<file>: the script's clock starts at the first update that finds the file (checked twice a second;
     * tools/runtime/native_ab_drive.py writes it at the settle point after the player gets control) */
    static const char* s_anchor = getenv("KZ2_MOUSE_ANCHOR");
    static double s_anchor_next;
    if (s_anchor && *s_anchor && now >= s_anchor_next) {
        s_anchor_next = now + 0.5;
        if (GetFileAttributesA(s_anchor) != INVALID_FILE_ATTRIBUTES) {
            s_t0 = now; s_anchor = nullptr;
            fprintf(stderr, "[mouse] script clock starts (anchor found)\n");
            if (kz2_mouse_env_on("KZ2_MOUSE_DUMP")) kz2_mouse_dump("start", vm_read32((uint32_t)ctx->gpr[3] + 0x10), 0.0);
        }
    }
    const double t = (s_anchor && *s_anchor) ? -1.0 : now - s_t0;
    const uint32_t C = (uint32_t)ctx->gpr[3], E = vm_read32(C + 0x10), sp = (uint32_t)ctx->gpr[1];
    const float sx = kz2_gp_f32(sp + 0x78), sy = kz2_gp_f32(sp + 0x7C);   /* UpdateLook's stick floats */
    int dx = 0, dy = 0;
    int moved = pad_mouse_take(&dx, &dy);   /* also tells the window thread the game is in play */
    if (s_nev) {
        int sdx = 0, sdy = 0;
        if (pad_mouse_script_due(s_ev, s_nev, t, &sdx, &sdy)) {
            if (s_send) pad_mouse_send(sdx, sdy);   /* arrives as WM_INPUT, taken by a later update */
            else { dx += sdx; dy += sdy; moved = dx || dy; }
            int left = 0;
            for (int i = 0; i < s_nev; i++) left += s_ev[i].left;
            if (s_dump) s_dump_at = t + 1.0;
            if (!left) fprintf(stderr, "[mouse] script done at t=%.3f\n", t);
        }
    }
    s_updates++;
    if (s_updates == 1) {   /* the starting device and assist state, not only the changes */
        char b[200];
        kz2_look_start_line(c, kz2_look.mouse, b, (int)sizeof b);
        fprintf(stderr, "[mouse] %s\n", b);
    }
    if (s_dump && s_updates == 1) kz2_mouse_dump("first", E, t);
    if (s_dump && s_dump_at > 0.0 && t >= s_dump_at) { s_dump_at = -1.0; kz2_mouse_dump("after", E, t); }
    if (s_log && (fabsf(sx) > 0.25f || fabsf(sy) > 0.25f)) {   /* stick reference: the game's own rate and pitch */
        static double s_last_stick = -1.0;
        if (t - s_last_stick >= 0.2 || t < s_last_stick) {
            s_last_stick = t;
            fprintf(stderr, "[mouse] stick t=%.3f stick=%.3f,%.3f rate=%.4f pitch=%.5f dt=%.5f fwd=%.4f,%.4f,%.4f\n", t, sx, sy,
                    kz2_gp_f32(C + 0xF8), ctx->fpr[2], kz2_ul_dt, kz2_gp_f32(E + 0x31C), kz2_gp_f32(E + 0x320), kz2_gp_f32(E + 0x324));
        }
    }
    /* KZ2_AIM_FACE=T0-T1[,T0-T1...] (TEST HARNESS, off by default; needs KZ2_AIM_LOG=1 and the 1.29 EBOOT): in
     * those windows of the script clock the yaw rate is set to turn the body toward the nearest live hostile (scan of the
     * game's entity list every 5th update), so a scripted run can bring an enemy into the assist's cones; outside them
     * the stick alone looks. One line a second: distance, bearing error, the rate written. */
    static const char* s_face = getenv("KZ2_AIM_FACE");
    if (s_face && *s_face && kz2_aim_log_on() && t >= 0.0) {
        int in = 0;
        for (const char* q = s_face; *q;) {
            char* e1; const double a0 = strtod(q, &e1); if (*e1 != '-') break;
            char* e2; const double a1 = strtod(e1 + 1, &e2);
            in |= t >= a0 && t < a1;
            q = *e2 == ',' ? e2 + 1 : e2; if (e2 == e1 + 1) break;
        }
        static unsigned s_fn; static double s_fline = -1.0;
        if (in && s_fn++ % 5 == 0) { const uint32_t g = vm_read32(0x00F3B288u); if (g) kz2_aim_gather_detail(E, 0.0f, g, 0); }
        if (in && kz2_aim_tgt.have) {
            const float hx = kz2_gp_f32(E + 0x320), hy = kz2_gp_f32(E + 0x324);   /* view forward x, y (+0x31C reads 0; run kz2-r74-aim-on2) */
            const float want = atan2f(kz2_aim_tgt.y - kz2_gp_f32(E + 0xB4), kz2_aim_tgt.x - kz2_gp_f32(E + 0xB0));
            float err = want - atan2f(hy, hx);
            while (err > 3.14159265f) err -= 6.2831853f;
            while (err < -3.14159265f) err += 6.2831853f;
            const uint32_t res = vm_read32(E + 0xC4);
            float rate = kz2_mouse_rate_for(err * 0.3f, res ? kz2_gp_f32(res + 0x2A8) : 0.0f, (float)kz2_ul_dt);
            rate = rate > 1.0f ? 1.0f : rate < -1.0f ? -1.0f : rate;
            uint32_t u; memcpy(&u, &rate, 4); vm_write32(C + 0xF8, u);
            if (t - s_fline >= 1.0 || t < s_fline) {
                s_fline = t;
                fprintf(stderr, "[aim] face t=%.2f: hostile at %.1f, bearing error %+.1f deg, rate %+.3f (view %.3f,%.3f body %.3f,%.3f)\n",
                        t, kz2_aim_tgt.d, err * 57.29578f, rate, hx, hy, kz2_gp_f32(E + 0x40), kz2_gp_f32(E + 0x44));
            }
        }
    }
    if (!c->mouse_look) { kz2_look_note(&kz2_look, sx, sy, 0.25f, 0); return; }
    const int was_mouse = kz2_look.mouse;
    kz2_look_note(&kz2_look, sx, sy, 0.25f, moved);
    if (kz2_look.mouse != was_mouse)
        fprintf(stderr, "[mouse] look device: %s (aim assist %s)\n", kz2_look.mouse ? "mouse" : "stick",
                kz2_gp_aim_on(c, kz2_look.mouse) ? "on" : "off");
    if (!moved) return;
    if (vm_read32(E + 0x6B0)) return;   /* scripted look-at owns the view: the counts are dropped */
    const uint32_t res = vm_read32(E + 0xC4);
    const int zoomed = (vm_read32(C + 0x13C) >> 6) & 1;
    float dyaw, dpitch;
    kz2_mouse_angles(c, dx, dy, zoomed, &dyaw, &dpitch);
    const float turn = res ? kz2_gp_f32(res + 0x2A8) : 0.0f;
    const float rate0 = kz2_gp_f32(C + 0xF8);
    /* The game's rate is positive to the LEFT: a pad's right stick held right reads -1 at 0x78(r1) and UpdateLook stores
     * -0.5 (run r63-b), and the body heading (atan2(E+0x40, E+0x3C)) then decreases. So mouse right = a negative rate. */
    const float rate = rate0 + kz2_mouse_rate_for(-dyaw, turn, (float)kz2_ul_dt);
    uint32_t u; memcpy(&u, &rate, 4); vm_write32(C + 0xF8, u);
    const float pmin = kz2_gp_f32(E + 0x1A4), pmax = kz2_gp_f32(E + 0x1A8), p0 = (float)ctx->fpr[2];
    ctx->fpr[2] = kz2_mouse_pitch(p0, dpitch, pmin, pmax);
    s_moves++;
    if (s_log || t - s_last_line >= 1.0) {
        s_last_line = t;
        fprintf(stderr, "[mouse] t=%.3f d=%d,%d dyaw=%.5f dpitch=%.5f dt=%.5f turn=%.2f rate=%.4f->%.4f pitch=%.5f->%.5f"
                        " lim=[%.4f,%.4f] zoom=%d stick=%.3f,%.3f fwd=%.4f,%.4f,%.4f (%llu moves in %llu updates)\n", t, dx, dy, dyaw,
                dpitch, kz2_ul_dt, turn, rate0, rate, p0, ctx->fpr[2], pmin, pmax, zoomed, sx, sy, kz2_gp_f32(E + 0x31C),
                kz2_gp_f32(E + 0x320), kz2_gp_f32(E + 0x324), s_moves, s_updates);
    }
}

/* ---- Keys keep their action under any layout (patch 6050) ----------------------------------------------
 * Each on-foot look update hands cellPad the button each key's Standard 1 action is on in the live profile map
 * (*(0x011B0540 + 0x240) + 0x64 + 4 * function; kz2_kb_roles), valid 300 ms, so menus, vehicles and mounted guns
 * (no on-foot look update) get the plain buttons back by themselves. One "[keys]" line each time the table changes.
 * Test input KZ2_KEY_SCRIPT="T:KEY:SEC ..." (KEY = Mouse1, Mouse2, a letter or 0xVK): SendInput presses KEY for SEC
 * seconds, T seconds after the first look update or after KZ2_MOUSE_ANCHOR appears (the mouse script's clock). */
extern "C" void pad_kb_set_roles(const unsigned short out[16], unsigned valid_ms);   /* cellPad.c (patch 6050) */
static void kz2_key_send(unsigned vk, int down)
{
    INPUT in; memset(&in, 0, sizeof in);
    if (vk == 1 || vk == 2) {
        in.type = INPUT_MOUSE;
        in.mi.dwFlags = vk == 1 ? (down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP) : (down ? MOUSEEVENTF_RIGHTDOWN : MOUSEEVENTF_RIGHTUP);
    } else {
        in.type = INPUT_KEYBOARD; in.ki.wVk = (WORD)vk; in.ki.wScan = (WORD)MapVirtualKeyA(vk, 0);
        in.ki.dwFlags = down ? 0 : KEYEVENTF_KEYUP;
    }
    SendInput(1, &in, sizeof in);
}
static void kz2_keys_tick(void)
{
    const uint32_t prof = vm_read32(0x011B0540u + 0x240u);
    if (prof >= 0x10000u && prof < 0xF0000000u) {
        int32_t map[KZ2_PAD_NFUNC];
        for (int f = 0; f < KZ2_PAD_NFUNC; f++) map[f] = (int32_t)vm_read32(prof + 0x64u + 4u * (uint32_t)f);
        uint16_t out[16];
        const int changed = kz2_kb_roles(map, out);
        static uint16_t s_last[16]; static int s_have;
        if (!s_have || memcmp(s_last, out, sizeof out)) {
            s_have = 1; memcpy(s_last, out, sizeof out);
            fprintf(stderr, "[keys] on foot: %d key(s) follow their action to another button (zoom key -> 0x%04X, close combat key"
                            " -> 0x%04X, use key -> 0x%04X, crouch key -> 0x%04X, grenade key -> 0x%04X)\n", changed, out[2], out[10],
                    out[13], out[8], out[9]);
            fflush(stderr);
        }
        pad_kb_set_roles(out, 300);
    }
    static int s_init, s_n; static double s_t0;
    static struct { double t, sec; unsigned vk; int state; } s_ev[16];
    const double now = std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
    if (!s_init) {
        s_init = 1; s_t0 = now;
        const char* e = getenv("KZ2_KEY_SCRIPT");
        while (e && *e && s_n < 16) {
            while (*e == ' ' || *e == ';' || *e == '|') e++;
            if (!*e) break;
            char name[16] = ""; double t = 0, sec = 0.2;
            if (sscanf(e, "%lf:%15[^:]:%lf", &t, name, &sec) >= 2) {
                unsigned vk = 0;
                if (!strcmp(name, "Mouse1")) vk = 1; else if (!strcmp(name, "Mouse2")) vk = 2;
                else if (name[0] && !name[1] && name[0] >= 'A' && name[0] <= 'Z') vk = (unsigned)name[0];
                else if (!strncmp(name, "0x", 2)) vk = (unsigned)strtoul(name, nullptr, 16);
                if (vk) { s_ev[s_n].t = t; s_ev[s_n].sec = sec; s_ev[s_n].vk = vk; s_ev[s_n].state = 0; s_n++; }
            }
            while (*e && *e != ' ' && *e != ';' && *e != '|') e++;
        }
        if (s_n) fprintf(stderr, "[keys] test script: %d key press(es) through SendInput\n", s_n);
    }
    if (!s_n) return;
    static const char* s_anchor = getenv("KZ2_MOUSE_ANCHOR");
    if (s_anchor && *s_anchor) {
        if (GetFileAttributesA(s_anchor) == INVALID_FILE_ATTRIBUTES) return;
        s_anchor = nullptr; s_t0 = now;
    }
    const double t = now - s_t0;
    for (int i = 0; i < s_n; i++) {
        if (s_ev[i].state == 0 && t >= s_ev[i].t) {
            s_ev[i].state = 1; kz2_key_send(s_ev[i].vk, 1);
            fprintf(stderr, "[keys] test t=%.2f: 0x%02X down\n", t, s_ev[i].vk); fflush(stderr);
        } else if (s_ev[i].state == 1 && t >= s_ev[i].t + s_ev[i].sec) {
            s_ev[i].state = 2; kz2_key_send(s_ev[i].vk, 0);
            fprintf(stderr, "[keys] test t=%.2f: 0x%02X up\n", t, s_ev[i].vk); fflush(stderr);
        }
    }
}
[[maybe_unused]] static void kz2_update_look(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    kz2_keys_tick();
    /* f1 is the game clock in seconds (r63 run a: 47.33, 47.40, ... one 1/15 s step per update at 15 fps), not a step:
     * dt = the clock's step since this controller's last update (first update or a jump: 1/30 s). */
    static uint32_t s_C;
    static double s_clock;
    const uint32_t C = (uint32_t)ctx->gpr[3];
    const double clock = ctx->fpr[1];
    double dt = clock - s_clock;
    if (C != s_C || !(dt > 0.0 && dt < 0.5)) dt = 1.0 / 30.0;
    s_C = C; s_clock = clock;
    kz2_ul_C = C; kz2_ul_dt = dt;
    lifted(ctx);
    kz2_ul_C = 0;
}
[[maybe_unused]] static void kz2_view_setter(ppu_context* ctx, void (*lifted)(ppu_context*), uint32_t site_lr)
{
    if ((uint32_t)ctx->lr == site_lr && kz2_ul_C && (uint32_t)ctx->gpr[3] == kz2_ul_C) kz2_mouse_pre(ctx);
    lifted(ctx);
}
#ifdef PPU_OVERRIDE_00173E80
void func_00173E80(ppu_context* ctx) { kz2_update_look(ctx, func_00173E80__lifted); }   // @0x00173E80 UpdateLook (1.29)
#endif
#ifdef PPU_OVERRIDE_0015A7F0
void func_0015A7F0(ppu_context* ctx) { kz2_view_setter(ctx, func_0015A7F0__lifted, 0x00174CE8u); }   // @0x0015A7F0 view setter (1.29)
#endif

/* ---- Valves and demolition charges without a motion sensor (ENHANCEMENT; kz2_motion.h has the decode) ----
 * gameplay.ini motion = auto|on|off (KZ2_MOTION). The motion getter @0x000821D0(device r3, &a r4, &b r5, &c r6, &g r7)
 * has three callers: the charge controller (lr 0x00119CFC), the valve controller (lr 0x00127288) and the zoom aim
 * correction (lr 0x00173748). When the stick drives the tilt (kz2_motion_feed), the getter's a/b/c are replaced at the
 * first two only, by the tilt of port 0's right stick X (pad_motion_port, patch 6049); the zoom aim is never touched.
 * Both callers keep the controller in r31 across the call (`ori r31, r3, 0` @0x00119CA0 / @0x00127228), so the hook
 * reads the controller's hand (+0x100) and dead band (charge +0x114, valve +0x110) from it for the log.
 * ASSUMPTION: the player's pad is port 0 (single player; the game's device object was not mapped to a port).
 * Lines: one "[motion] ... right stick" per controller kind the first time the stick drives it; every arm step of a
 * charge (@0x001174A8: entity +0x244 steps, resource +0xC4 -> +0x1F0 range count, +0x1F4 the {min, max} pairs in
 * radians, hand +0x25C in radians; an earlier change: logged in degrees, x 57.29578, not x 45 as before); a valve's angle (@0x00125BF0: rep +0x240, radians) each time it has moved 30 deg.
 * KZ2_MOTION_LOG=1 adds the stick, the tilt and the hand of every getter call (at most 4000 lines).
 * each fed call also tells cellPad (pad_motion_tilt_note) that a tilt controller is reading, so the
 * keyboard's tilt_left / tilt_right keys (keybinds.ini, Z / X by default; patch 6060) give the grab and the tilt
 * only then. */
#include "kz2_motion.h"
extern "C" int  pad_motion_port(unsigned port, unsigned char* rx);   /* cellPad.c (patch 6049) */
extern "C" void pad_motion_set_mode(int mode);
extern "C" void pad_motion_tilt_note(void);   /* cellPad.c (patch 6060): the tilt keys act while this is fresh */
extern "C" void pad_dsu_set_port(unsigned port);   /* cellPad.c (patch 6062): DSU motion client, 0 = off */
static int kz2_motion_log_on(void)
{
    static int v = -1;
    if (v < 0) { const char* e = getenv("KZ2_MOTION_LOG"); v = e && e[0] == '1'; }
    return v;
}
static void kz2_put_f32(uint32_t ea, float f) { uint32_t u; memcpy(&u, &f, 4); vm_write32(ea, u); }
static std::chrono::steady_clock::time_point kz2_motion_t0 = std::chrono::steady_clock::now();
static double kz2_motion_t(void)   /* seconds since kz2_motion_init (the "t=" of every [motion] line) */
{
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - kz2_motion_t0).count();
}
extern "C" void kz2_motion_init(void)   /* main.cpp, before the game runs */
{
    kz2_motion_t0 = std::chrono::steady_clock::now();
    const int m = kz2_gameplay_get()->motion;
    pad_motion_set_mode(m);
    static const char* const mn[3] = { "auto", "on", "off" };
    fprintf(stderr, "[motion] motion = %s: %s\n", mn[m],
            m == KZ2_MOTION_OFF ? "the right stick turns valves and arms charges (the pad's own tilt is not used)"
            : m == KZ2_MOTION_ON ? "only the pad's own tilt (a pad without an accelerometer cannot turn valves or arm charges)"
                                 : "the pad's own tilt when it has a working accelerometer, else the right stick");
    /* An earlier change (ENHANCEMENT, from KZ3 patch 4028): gameplay.ini dsu_port (KZ2_DSU_PORT) starts cellPad's DSU (cemuhook)
     * client; its samples become port 0's accelerometer and gyro words, so motion = auto/on treat it as a pad with
     * sensors (the getter keeps the real tilt, the right stick no longer drives the valves and charges). */
    const int dsu = kz2_gameplay_get()->dsu_port;
    pad_dsu_set_port((unsigned)dsu);
    if (dsu)
        fprintf(stderr, "[motion] dsu_port = %d: DSU (cemuhook) motion from 127.0.0.1:%d%s\n", dsu, dsu,
                m == KZ2_MOTION_OFF ? " (motion = off: the game gets a still pad, the right stick turns valves and charges)"
                                    : " (while samples arrive, valves and charges take the tilt, not the right stick)");
}
[[maybe_unused]] static void kz2_motion_get(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t lr = (uint32_t)ctx->lr;
    const int kind = lr == KZ2_MOTION_LR_CHARGE ? 1 : lr == KZ2_MOTION_LR_VALVE ? 2 : 0;
    const uint32_t pa = (uint32_t)ctx->gpr[4], pb = (uint32_t)ctx->gpr[5], pc = (uint32_t)ctx->gpr[6];
    const uint32_t C = (uint32_t)ctx->gpr[31];
    lifted(ctx);
    if (!kind) return;
    unsigned char rx = 128;
    const int live = pad_motion_port(0, &rx);
    if (!kz2_motion_feed(kz2_gameplay_get()->motion, live)) return;
    pad_motion_tilt_note();   /* a valve or charge reads the tilt now (keyboard tilt keys, patch 6060) */
    const float s = kz2_motion_unit(rx), deg = kz2_motion_deg(s);
    float v[3];
    kz2_motion_vec(deg, v);
    const float a0 = kz2_gp_f32(pa), b0 = kz2_gp_f32(pb), c0 = kz2_gp_f32(pc);
    kz2_put_f32(pa, v[0]); kz2_put_f32(pb, v[1]); kz2_put_f32(pc, v[2]);
    static int s_first[3];
    static unsigned s_lines;
    const char* nm = kind == 1 ? "charge" : "valve";
    const float band = kz2_gp_f32(C + (kind == 1 ? 0x114u : 0x110u)) * 57.29578f;
    const float hand = kz2_gp_f32(C + 0x100) * 57.29578f;
    if (!s_first[kind]) {
        s_first[kind] = 1;
        fprintf(stderr, "[motion] t=%.2f %s controller 0x%08X: the right stick drives the tilt (pad accelerometer %s; dead band %.3f deg;"
                " full tilt %.2f deg from %.0f %% of the stick)\n", kz2_motion_t(), nm, C, live ? "working" : "none", band,
                (double)KZ2_MOTION_PEAK_DEG, (double)(KZ2_MOTION_FULL_AT * 100.0f));
        fflush(stderr);
    }
    if (kz2_motion_log_on() && s_lines < 4000) {
        static uint8_t s_rx[3] = { 0, 0, 0 };
        static unsigned s_n[3];
        if (rx != s_rx[kind] || ++s_n[kind] % 15 == 0) {
            s_rx[kind] = rx; s_lines++;
            fprintf(stderr, "[motion] t=%.2f %s: stick %3u (%+.3f) tilt %+.2f deg, getter had %.4f %.4f %.4f, hand %+.2f deg, band %.3f\n",
                    kz2_motion_t(), nm, rx, s, deg, a0, b0, c0, hand, band);
        }
    }
}
[[maybe_unused]] static void kz2_charge_arm(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t E = (uint32_t)ctx->gpr[3];
    const uint32_t before = vm_read32(E + 0x244);
    lifted(ctx);
    const uint32_t after = vm_read32(E + 0x244);
    static unsigned s_lines;
    if (after == before || s_lines >= 200) return;
    s_lines++;
    const uint32_t res = vm_read32(E + 0xC4);
    const uint32_t n = res ? vm_read32(res + 0x1F0) : 0, arr = res ? vm_read32(res + 0x1F4) : 0;
    char win[160] = "";
    for (uint32_t i = 0, o = 0; arr && i < n && i < 6 && o < sizeof win - 32; i++)
        o += (uint32_t)snprintf(win + o, sizeof win - o, " [%.2f..%.2f]", kz2_gp_f32(arr + 8 * i) * 57.29578f, kz2_gp_f32(arr + 8 * i + 4) * 57.29578f);
    fprintf(stderr, "[motion] t=%.2f charge 0x%08X arm step %u of %u (hand %+.2f deg; windows in deg:%s)%s\n", kz2_motion_t(), E, after, n,
            kz2_gp_f32(E + 0x25C) * 57.29578f, win, after >= n && n ? ": armed" : "");
    fflush(stderr);
}
[[maybe_unused]] static void kz2_valve_rep(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t R = (uint32_t)ctx->gpr[3];
    lifted(ctx);
    static uint32_t s_R;
    static float s_last;
    static unsigned s_lines;
    const float ang = kz2_gp_f32(R + 0x240) * 57.29578f;
    if (R != s_R) { s_R = R; s_last = ang; return; }
    if (fabsf(ang - s_last) >= 30.0f && s_lines < 200) {
        s_lines++;
        fprintf(stderr, "[motion] t=%.2f valve 0x%08X angle %.1f deg (was %.1f; hand %+.2f deg)\n", kz2_motion_t(), R, ang, s_last,
                kz2_gp_f32(R + 0x248) * 57.29578f);
        fflush(stderr);
        s_last = ang;
    }
}
#ifdef PPU_OVERRIDE_000821D0
void func_000821D0(ppu_context* ctx) { kz2_motion_get(ctx, func_000821D0__lifted); }   // @0x000821D0 motion getter (1.29)
#endif
#ifdef PPU_OVERRIDE_001174A8
void func_001174A8(ppu_context* ctx) { kz2_charge_arm(ctx, func_001174A8__lifted); }   // @0x001174A8 charge arm update (1.29)
#endif
#ifdef PPU_OVERRIDE_00125BF0
void func_00125BF0(ppu_context* ctx) { kz2_valve_rep(ctx, func_00125BF0__lifted); }   // @0x00125BF0 ValveRep update (1.29)
#endif

/* ---- Field of view search (diagnostic only: KZ2_FOV_LOG=1) ------------------------------------------------
 * tanf @0x007D0818 (libm; 33 call sites) and the Camera FieldOfView writer @0x0066F3C0(camera r3, resource r4: near
 * R+0x28 -> C+0x6C, far R+0x2C -> C+0x70, FieldOfView C+0x74 scaled at 0x0066F420, ViewConeAspect C+0x78,
 * FOVAspectAdjust C+0x84; the Camera attribute table @0x00F3AF00). Lists, per caller, the first arguments and every
 * change of more than 1 %, to find the projection's half angle. */
static int kz2_fov_log_on(void)
{
    static int v = -1;
    if (v < 0) { const char* e = getenv("KZ2_FOV_LOG"); v = e && e[0] == '1'; }
    return v;
}
[[maybe_unused]] static void kz2_fov_tanf(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    if (!kz2_fov_log_on()) { lifted(ctx); return; }
    const uint32_t lr = (uint32_t)ctx->lr;
    const double x = ctx->fpr[1];
    lifted(ctx);
    static uint32_t s_lr[64]; static float s_x[64]; static unsigned s_n[64], s_lines;
    int i = 0;
    while (i < 64 && s_lr[i] && s_lr[i] != lr) i++;
    if (i == 64 || s_lines > 3000) return;
    if (!s_lr[i]) { s_lr[i] = lr; s_x[i] = (float)x + 1e9f; }
    s_n[i]++;
    if (fabsf((float)x - s_x[i]) > 0.01f * fabsf(s_x[i]) + 1e-6f) {
        s_x[i] = (float)x; s_lines++;
        fprintf(stderr, "[fov] tanf lr 0x%08X x %.5f (%.3f deg) -> %.5f (call %u)\n", lr, x, x * 57.29578, ctx->fpr[1], s_n[i]);
    }
}
[[maybe_unused]] static void kz2_fov_cam(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t C = (uint32_t)ctx->gpr[3], R = (uint32_t)ctx->gpr[4], lr = (uint32_t)ctx->lr;
    lifted(ctx);
    static unsigned s_lines;
    if (kz2_fov_log_on() && s_lines++ < 300)
        fprintf(stderr, "[fov] camera writer lr 0x%08X C 0x%08X R 0x%08X: fov %.4f aspect %.4f zoom %.4f adjust %u\n", lr, C, R,
                kz2_gp_f32(C + 0x74), kz2_gp_f32(C + 0x78), kz2_gp_f32(C + 0x80), (unsigned)(vm_read32(C + 0x84) >> 24));
}
#ifdef PPU_OVERRIDE_007D0818
void func_007D0818(ppu_context* ctx) { kz2_fov_tanf(ctx, func_007D0818__lifted); }   // @0x007D0818 tanf (1.29)
#endif
#ifdef PPU_OVERRIDE_0066F3C0
void func_0066F3C0(ppu_context* ctx) { kz2_fov_cam(ctx, func_0066F3C0__lifted); }   // @0x0066F3C0 Camera FOV writer (1.29)
#endif
/* Frustum perspective setter @0x003D9640(frustum r3, r4..r6 vectors, f1 near, f2 far, f3 FOV in degrees, f4 aspect;
 * @0x003D96FC: top = near * tan(FOV/2), right = top * aspect, so the FOV is vertical). Five callers (lr 0x00143160,
 * 0x001ABA74, 0x0027661C, 0x0030D688, 0x0066F638). KZ2_FOV_LOG=1 prints each new (lr, frustum, FOV).
 *
 * Field of view setting (ENHANCEMENT; display.ini fov / KZ2_FOV / the Display page's FIELD OF VIEW row,
 * kz2_port_settings.cpp): the vertical FOV of the first-person view. The world view is built by the Camera's frustum
 * method 0x66F530 (lr 0x66F638; Camera r31: NearPlane +0x6C, FarPlane +0x70, FieldOfView +0x74; RTTI 0xF3AC1C, vtable
 * 0xFBA480). The same Camera object draws the level's in-engine scenes: runs kz2-r67-fovown/-fovown2 (Corinth Sands)
 * show one Camera for the dropship-crash scene and for play, and only its near plane tells them apart:
 *   first-person play   45 deg, near 0.25 (CameraEntityResource FirstPersonNearPlane), far 4096; the sight zoom
 *                       narrows the FOV with the near plane kept (an earlier change run kz2-r65-keys-*)
 *   in-engine scene     near 0.01, far 4096, FOV animated (40.7 -> 30.1 deg over the crash scene)
 *   front end / loading near 1.0 far 2000 (40 deg; menus, CamOrbit 0xFBA534) and near 0.1 far 512 (50.6 deg)
 * The weapon view model has its own frustum (lr 0x27661C, 33.75 deg, near 0.01) and is never touched. So the rule is
 * the game's own first-person marker: lr 0x66F638 and near == the first-person near plane (0.25). There tan(FOV/2) is
 * multiplied by tan(T/2) / tan(22.5 deg) (T = the setting), which keeps every zoom step relative to the view (the
 * approach of KZ3 patch 2109, port/kz3/main.cpp, read in the KZ3 snapshot, adapted; no code taken).
 * ASSUMPTION: every first-person view of the campaign uses the 0.25 near plane (one FirstPersonCameraEntityResource);
 * a view that does not keeps the game's own FOV. One "[fov]" line names each other near plane seen at the site while
 * the setting is on (0.005 apart, at most 16) and each new whole degree of the first-person FOV (zoom steps, at most 12), so a level where that assumption fails shows in the log. */
static volatile double s_fov_k = 1.0;    /* factor on tan(FOV/2); 1 = the game's own view */
static volatile double s_fov_deg = 45.0;
extern "C" void kz2_fov_set(double deg)
{
    if (!(deg >= 30.0 && deg <= 120.0)) deg = 45.0;
    s_fov_deg = deg;
    s_fov_k = tan(deg * 0.5 * 0.017453292519943295) / tan(22.5 * 0.017453292519943295);
    fprintf(stderr, "[fov] first-person view %.0f deg vertical (game 45; factor %.4f on tan(FOV/2)); in-engine scenes, menus and the "
                    "weapon model unchanged\n", deg, (double)s_fov_k);
}
[[maybe_unused]] static void kz2_fov_frustum(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t lr = (uint32_t)ctx->lr, F = (uint32_t)ctx->gpr[3];
    const double fov0 = ctx->fpr[3], near0 = ctx->fpr[1];
    const double k = s_fov_k;
    if (lr == 0x0066F638u && k != 1.0 && fov0 > 1.0 && fov0 < 170.0) {
        if (fabs(near0 - 0.25) < 1e-4) {
            ctx->fpr[3] = 2.0 * atan(tan(fov0 * 0.5 * 0.017453292519943295) * k) * 57.29577951308232;
            static int s_fv[12]; static unsigned s_nf;   /* each new whole degree of the game's FOV (zoom steps), at most 12 */
            const int d = (int)floor(fov0 + 0.5);
            unsigned i = 0;
            while (i < s_nf && s_fv[i] != d) i++;
            if (i == s_nf && s_nf < 12) {
                s_fv[s_nf++] = d;
                fprintf(stderr, "[fov] first-person %.3f -> %.3f deg (near %.4f)\n", fov0, ctx->fpr[3], near0);
            }
        } else {
            static float s_near[16]; static unsigned s_nn;
            unsigned i = 0;
            while (i < s_nn && fabsf(s_near[i] - (float)near0) > 0.005f) i++;
            if (i == s_nn && s_nn < 16) {
                s_near[s_nn++] = (float)near0;
                fprintf(stderr, "[fov] not first-person (near %.4f far %.1f fov %.3f): the game's own FOV\n", near0, ctx->fpr[2], fov0);
            }
        }
    }
    if (kz2_fov_log_on()) {
        static uint32_t s_lr[200], s_f[200]; static float s_v[200]; static unsigned s_n;
        int i = 0;
        while (i < (int)s_n && !(s_lr[i] == lr && s_f[i] == F && fabsf(s_v[i] - (float)fov0) < 0.01f)) i++;
        if (i == (int)s_n && s_n < 200) {
            s_lr[s_n] = lr; s_f[s_n] = F; s_v[s_n] = (float)fov0; s_n++;
            fprintf(stderr, "[fov] frustum lr 0x%08X F 0x%08X fov %.3f -> %.3f aspect %.4f near %.4f far %.1f\n", lr, F, fov0,
                    ctx->fpr[3], ctx->fpr[4], ctx->fpr[1], ctx->fpr[2]);
        }
    }
    lifted(ctx);
}
#ifdef PPU_OVERRIDE_003D9640
void func_003D9640(ppu_context* ctx) { kz2_fov_frustum(ctx, func_003D9640__lifted); }   // @0x003D9640 frustum setter (1.29)
#endif

/* Runtime an earlier change (public #49): the game's own fatal paths, kz2_guest_fatal.h has the static reading.
 * abort() @0x00028030 (1.29) / @0x00027F60 (v1.01) is `*(int*)0 = 0x0DEADCA7; blr`. On the PS3 that store faults and
 * the process ends; here ps3recomp drops null-page stores, the lifted abort returns, and std::terminate @0x007D9AA0
 * falls through into std::unexpected @0x007D9AE0 and back, recursing until the host stack overflows (0xC00000FD, the
 * #49 crash). The host body does what the PS3 does at that store: the process ends, here with a log line, the guest
 * chain, the log flushed, a message box (KZ2_NO_ERROR_DIALOG=1 skips it) and exit code 5 (kz2_guest_fatal_exit,
 * main.cpp). The store itself is not replayed: it only ever existed to fault. */
#include "kz2_guest_fatal.h"
extern "C" void ppu_dump_guest_stack(ppu_context*, const char*);
extern "C" void kz2_guest_fatal_exit(const char* what);   /* main.cpp: log flush, message box, TerminateProcess(5) */
[[maybe_unused]] static void kz2_guest_abort(ppu_context* ctx, uint32_t self)
{
    fprintf(stderr, "[guest-abort] the game called abort() @0x%08X from lr=0x%08X (guest tid %u): on the PS3 its "
                    "store of 0x%08X to address 0 ends the process; ending it here\n",
            self, (uint32_t)ctx->lr, (unsigned)ctx->thread_id, kz2fatal::ABORT_POISON);
    ppu_dump_guest_stack(ctx, "abort");
    kz2_guest_fatal_exit("abort");
}
#ifdef PPU_OVERRIDE_00028030
void func_00028030(ppu_context* ctx) { kz2_guest_abort(ctx, 0x00028030u); }   // @0x00028030 abort (1.29)
#endif
#ifdef PPU_OVERRIDE_00027F60
void func_00027F60(ppu_context* ctx) { kz2_guest_abort(ctx, 0x00027F60u); }   // @0x00027F60 abort (v1.01)
#endif

/* luaD_throw(L, errcode) @0x003F3160 (1.29) / @0x003E6D10 (v1.01): diagnostic only, the lifted body always runs.
 * When no pcall catches the error (L->errorJmp 0) the game is about to call exit(1); say so, with the error text when
 * L is readable, the errcode (2 run, 3 syntax, 4 memory, 5 error handler) and the guest chain. #49's log shows such a
 * throw on L = 0x00000001 (a bad lua_State pointer, not a script error), right after a checkpoint restart. */
[[maybe_unused]] static void kz2_lua_throw(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t L = (uint32_t)ctx->gpr[3];
    char msg[200];
    const int k = kz2fatal::classify_throw(L, [](uint32_t a) { return vm_read32(a); },
                                           [](uint32_t a) { return vm_read8(a); }, msg, sizeof msg);
    if (k) {
        static int n = 0;
        if (n++ < 4) {
            fprintf(stderr, "[lua] unprotected error %d on lua_State 0x%08X%s (lr=0x%08X, guest tid %u): \"%s\"; the game "
                            "calls exit(1) next\n", (int)(uint32_t)ctx->gpr[4], L,
                    k == 2 ? " (not a valid pointer)" : "", (uint32_t)ctx->lr, (unsigned)ctx->thread_id, msg);
            ppu_dump_guest_stack(ctx, "lua-throw");
        }
    }
    lifted(ctx);
}
#ifdef PPU_OVERRIDE_003F3160
void func_003F3160(ppu_context* ctx) { kz2_lua_throw(ctx, func_003F3160__lifted); }   // @0x003F3160 luaD_throw (1.29)
#endif
#ifdef PPU_OVERRIDE_003E6D10
void func_003E6D10(ppu_context* ctx) { kz2_lua_throw(ctx, func_003E6D10__lifted); }   // @0x003E6D10 luaD_throw (v1.01)
#endif

/* exit(code) @0x007B7D60 (1.29) / @0x007AA3D8 (v1.01): diagnostic only, the lifted body runs (atexit list, PRX
 * unload, _Exit). KZ2 does not exit on its own in play, so this line names who did. */
[[maybe_unused]] static void kz2_guest_exit(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    fprintf(stderr, "[guest-exit] the game called exit(%d) from lr=0x%08X (guest tid %u)\n", (int)(int32_t)ctx->gpr[3],
            (uint32_t)ctx->lr, (unsigned)ctx->thread_id);
    ppu_dump_guest_stack(ctx, "exit");
    lifted(ctx);
}
#ifdef PPU_OVERRIDE_007B7D60
void func_007B7D60(ppu_context* ctx) { kz2_guest_exit(ctx, func_007B7D60__lifted); }   // @0x007B7D60 exit (1.29)
#endif
#ifdef PPU_OVERRIDE_007AA3D8
void func_007AA3D8(ppu_context* ctx) { kz2_guest_exit(ctx, func_007AA3D8__lifted); }   // @0x007AA3D8 exit (v1.01)
#endif

/* luaV_gettable(L, t, key, val) @0x003F9870 (1.29) / @0x003ED420 (v1.01, same body; luaD_throw's delta 0xC450):
 * diagnostic only, the lifted body always runs. #49: the first bad read was this function's t->tt at address 4 with
 * L = 1, and the guest chain stopped here, so its direct caller (lr) is the one datum the log lacked. Logged when L or
 * t is not a pointer (at most 4 lines, each with the chain). One compare per call otherwise. */
[[maybe_unused]] static void kz2_lua_gettable(ppu_context* ctx, void (*lifted)(ppu_context*))
{
    const uint32_t L = (uint32_t)ctx->gpr[3], tv = (uint32_t)ctx->gpr[4];
    if (__builtin_expect(!kz2fatal::plausible_ptr(L) || tv < 0x10000u, 0)) {
        static int n = 0;
        if (n++ < 4) {
            fprintf(stderr, "[lua] luaV_gettable on a bad %s: L=0x%08X t=0x%08X key=0x%08X from lr=0x%08X (guest tid %u)\n",
                    !kz2fatal::plausible_ptr(L) ? "lua_State" : "table value", L, tv, (uint32_t)ctx->gpr[5],
                    (uint32_t)ctx->lr, (unsigned)ctx->thread_id);
            ppu_dump_guest_stack(ctx, "lua-gettable");
        }
    }
    lifted(ctx);
}
#ifdef PPU_OVERRIDE_003F9870
void func_003F9870(ppu_context* ctx) { kz2_lua_gettable(ctx, func_003F9870__lifted); }   // @0x003F9870 luaV_gettable (1.29)
#endif
#ifdef PPU_OVERRIDE_003ED420
void func_003ED420(ppu_context* ctx) { kz2_lua_gettable(ctx, func_003ED420__lifted); }   // @0x003ED420 luaV_gettable (v1.01)
#endif
