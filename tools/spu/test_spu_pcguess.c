/* test_spu_pcguess.c -- KZ2 patch 7022: computed hops whose lift-time guess comes from a link
 * register (SPU_IB_GUESS_PC, spu_context.h; tools/spu_lifter.py compute_ib_guesses). The "lifted" functions are
 * hand-written in the form the lifter emits for the job libraries' interrupt-window idiom
 * (`brsl $r2, .+4 ; ai $r2, $r2, 8 ; bid $r2`, Gfx.Particles.UpdateJob 0xF87C):
 *  1. KZ2_SPU_PCGUESS on (g_kz2_pcguess 1): every idiom hop is a direct tail call, no spu_ib_direct call, the same
 *     registers and step/recent-pc bookkeeping as with it off;
 *  2. off (0): every hop goes through spu_ib_direct, as before the patch;
 *  3. on, with an enabled pending interrupt: the hop goes to the drain (trampoline), never the guess;
 *  4. on, the register not the guessed address: spu_ib_direct answers, the guess is not taken;
 *  5. on, KZ3_SPU_IBGUESS=0 (g_spu_ib_guess 0): no guess.
 * Built by tools/spu/test_spu_pcguess.sh, which also builds it against a copy of the patched spu_context.h whose
 * SPU_IB_GUESS_PC ignores g_kz2_pcguess (negative control: case 2 must fail). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "spu_context.h"

#ifndef SPU_IB_GUESS_PC
#error "patched tree without KZ2 patch 7022"
#endif
/* runtime stubs */
int g_spu_hop_on = 1;
volatile int g_yz_lockstep_on = 0;
int g_spu_launch_diag = 0;
void* volatile g_pm_flow_ctx = 0;
volatile unsigned g_spu_stack_reset_n = 0;
uint32_t g_spu_depth_max = 1000;
void spu_hop_init(void) {}
void (*g_kz3_wtrace)(const char*, int, uint32_t, uint64_t, uint64_t) = 0;
int g_spu_ib_guess = 1;
volatile unsigned long long g_spu_ib_guess_n;
int g_kz3_pmend_ib = 0;
void* volatile g_kz3_trace_ctx = 0;
int g_spu_ovl_skip_any = 0;
uint8_t g_spu_ovl_skip[512];
uint64_t g_spu_task_entry_bits[16];
uint64_t g_spu_task_pol_bits[16];
int g_spu_task_pol_big;
static int s_spu_ib_gid = 7; /* the TU's image id (spu_ib_guess_register in the runtime) */
static int s_full_drains;
void spu_drain_call_full(spu_context* c, uint32_t ret)
{
    (void)c;
    (void)ret;
    s_full_drains++;
}
static void wt_stub(const char* t, int k, uint32_t s, uint64_t a, uint64_t b)
{
    (void)t, (void)k, (void)s, (void)a, (void)b;
}
void spu_task_launch_check_full(spu_context* c, void* fn)
{
    (void)c;
    (void)fn;
}
void spu_check_stack_reset(spu_context* c, void (*f)(spu_context*))
{
    (void)c;
    (void)f;
}
void spu_launch_ls0_end(spu_context* c)
{
    (void)c;
}
void yz_lockstep_tick(spu_context* c)
{
    (void)c;
}

int g_kz2_pcguess;

#define A_PC 0xF87Cu   /* brsl $r2, .+4 ; ... the loop body */
#define B_PC 0xF888u   /* the instruction after bid $r2 */
#define EXIT_PC 0xF900u
static unsigned long long s_ibd_calls, s_resolves;
static void fn_a(spu_context* ctx);
static void fn_b(spu_context* ctx);
static void fn_exit(spu_context* ctx) { ctx->gpr[9]._u32[0] = 0xE717u; }
static spu_hop_fn lookup(uint32_t t) { return t == A_PC ? fn_a : t == B_PC ? fn_b : t == EXIT_PC ? fn_exit : 0; }
void spu_indirect_branch(spu_context* ctx) { s_resolves++; ctx->pc &= SPU_LS_MASK; }
spu_hop_fn spu_ib_direct(spu_context* ctx, uint32_t t)
{
    s_ibd_calls++;
    if (!spu_hop_ok(ctx) || t == 0 || t == ctx->hop_ret_pc) return 0;
    return lookup(t);
}
/* A (0xF87C..0xF884): r2 = link 0xF880 + 8 (+ r7 when the test bends it); int_enable = 0; bi $r2 with the guess */
static void fn_a(spu_context* ctx)
{
    ctx->gpr[2]._u32[0] = 0xF880u;
    ctx->gpr[2]._u32[0] += 8 + ctx->gpr[7]._u32[0];
    ctx->int_enable = 0; SPU_IB_HOP_G(ctx, ctx->gpr[2]._u32[0], SPU_IB_GUESS_PC(ctx, 0xF888u, fn_b));
}
/* B (0xF888): count down r3, accumulate r4; static hop back to A or out */
static void fn_b(spu_context* ctx)
{
    ctx->gpr[4]._u32[0] += ctx->gpr[3]._u32[0] ^ 0x5Au;
    ctx->gpr[3]._u32[0] -= 1;
    if (ctx->gpr[3]._u32[0]) SPU_HOP(ctx, A_PC, fn_a);
    SPU_HOP(ctx, EXIT_PC, fn_exit);
}
/* the bie form: interrupts enabled by the branch itself */
static void hop_bie(spu_context* ctx)
{
    ctx->gpr[2]._u32[0] = 0xF888u;
    ctx->int_enable = 1; SPU_IB_HOP_G(ctx, ctx->gpr[2]._u32[0], SPU_IB_GUESS_PC(ctx, 0xF888u, fn_b));
}
static spu_context* mk(void)
{
    spu_context* c = calloc(1, sizeof *c);
    c->ls = calloc(1, SPU_LS_SIZE);
    c->image_id = 7;   /* = s_spu_ib_gid */
    return c;
}
static int fails;
#define CHECK(cond, ...) do { if (!(cond)) { fails++; printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* the drain: run trampolines until none is pending (the hop-off and fallback paths) */
static void run(spu_context* ctx)
{
    g_spu_trampoline_fn = 0;
    fn_a(ctx);
    for (int n = 0; g_spu_trampoline_fn && n < 100000000; n++) {
        spu_hop_fn f = (spu_hop_fn)g_spu_trampoline_fn;
        g_spu_trampoline_fn = 0;
        if (f == spu_indirect_branch) { spu_indirect_branch(ctx); f = lookup(ctx->pc); if (!f) break; }
        f(ctx);
    }
}

int main(void)
{
    const unsigned N = 200000;
    uint32_t r4[2]; unsigned long long st[2];
    for (int on = 0; on < 2; on++) {
        spu_context* ctx = mk();
        ctx->gpr[3]._u32[0] = N;
        g_kz2_pcguess = on; g_spu_ib_guess = 2; g_spu_ib_guess_n = 0; s_ibd_calls = 0;
        run(ctx);
        r4[on] = ctx->gpr[4]._u32[0]; st[on] = ctx->steps;
        CHECK(ctx->gpr[9]._u32[0] == 0xE717u && ctx->gpr[3]._u32[0] == 0, "case %d: loop did not finish", on ? 1 : 2);
        if (on) CHECK(s_ibd_calls == 0 && g_spu_ib_guess_n == N, "case 1: %llu spu_ib_direct calls, %llu guess hops (want 0, %u)",
                      s_ibd_calls, g_spu_ib_guess_n, N);
        else CHECK(s_ibd_calls == N && g_spu_ib_guess_n == 0, "case 2: %llu spu_ib_direct calls, %llu guess hops (want %u, 0)",
                   s_ibd_calls, g_spu_ib_guess_n, N);
    }
    CHECK(r4[0] == r4[1] && st[0] == st[1], "cases 1/2: r4 %08X/%08X steps %llu/%llu differ", r4[0], r4[1], st[0], st[1]);
    /* 3-5: one hop each (fn_a with r3 = 1: B runs once, then exits) */
    for (int k = 3; k <= 5; k++) {
        spu_context* ctx = mk();
        ctx->gpr[3]._u32[0] = 1;
        g_kz2_pcguess = 1; g_spu_ib_guess = k == 5 ? 0 : 2; g_spu_ib_guess_n = 0; s_ibd_calls = 0;
        if (k == 3) { ctx->event_mask = 0x2; ctx->event_status = 0x2; }
        if (k == 4) ctx->gpr[7]._u32[0] = 4;   /* r2 = 0xF88C, not the guess */
        g_spu_trampoline_fn = 0;
        if (k == 3) { ctx->int_enable = 1; hop_bie(ctx); } else fn_a(ctx);
        const int to_drain = g_spu_trampoline_fn == (void*)spu_indirect_branch;
        if (k == 3) CHECK(to_drain && s_ibd_calls == 1 && g_spu_ib_guess_n == 0 && ctx->gpr[4]._u32[0] == 0,
                          "case 3: drain %d, %llu spu_ib_direct calls, %llu guess hops", to_drain, s_ibd_calls, g_spu_ib_guess_n);
        if (k == 4) CHECK(to_drain && s_ibd_calls == 1 && g_spu_ib_guess_n == 0,
                          "case 4: drain %d, %llu spu_ib_direct calls, %llu guess hops", to_drain, s_ibd_calls, g_spu_ib_guess_n);
        if (k == 5) CHECK(!to_drain && s_ibd_calls == 1 && g_spu_ib_guess_n == 0 && ctx->gpr[9]._u32[0] == 0xE717u,
                          "case 5: drain %d, %llu spu_ib_direct calls, %llu guess hops", to_drain, s_ibd_calls, g_spu_ib_guess_n);
    }
    printf("%s test_spu_pcguess: %u idiom hops on/off, r4 %08X both ways, steps %llu\n", fails ? "FAIL" : "PASS", N, r4[1],
           st[1]);
    return fails ? 1 : 0;
}
