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
#ifdef PPU_OVERRIDE_00082248
void func_00082248(ppu_context* ctx) { kz2_pad_query(ctx, func_00082248__lifted, 0); }   // @0x00082248 (1.29)
#endif
#ifdef PPU_OVERRIDE_00082290
void func_00082290(ppu_context* ctx) { kz2_pad_query(ctx, func_00082290__lifted, 1); }   // @0x00082290 (1.29)
#endif
#ifdef PPU_OVERRIDE_000822F0
void func_000822F0(ppu_context* ctx) { kz2_pad_query(ctx, func_000822F0__lifted, 2); }   // @0x000822F0 (1.29)
#endif
