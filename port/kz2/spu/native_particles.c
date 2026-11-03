/* native_particles.c -- Particles.VertexJob (job_00cd7180, image 201) native code: the .bss clear (on by default,
 * KZ2_NATIVE_JOB_VJCLEAR=0 turns it off) and the memcpy (on by default since an earlier change, KZ2_NATIVE_JOB_VJCOPY=0 turns it off)
 * and the vertex emitter (on by default since an earlier change, KZ2_NATIVE_JOB_VJVERT=0 turns it off).
 *
 * The job's crt0 .bss clear, the first "continue at" gate (re/spu/native_gates.tsv column 7): the WWS job crt0 that
 * 26 of the 36 job images share zeroes its .bss at every job start (@0x406C ila r3 = start, @0x4070 ila r4 = end,
 * @0x4074 clgt + brnz to the loop, which branches back to @0x407C). VertexJob's .bss is LS 0x1B980-0x288B0 (53 040
 * bytes, 3315 quadwords: 6.6 % of the job's host samples in an earlier change's profile); the next largest is 1664 bytes. The
 * clear is no subroutine (the loop's exit is `br 0x407C`, not a return), so its gate continues at 0x407C instead of
 * returning to r0.
 *
 *   @0x411C  hbrr            (hint, nothing)
 *   @0x4120  il    r5, 0
 *   @0x4124  stqx  r5, r3, r126        LS[(r3 + r126) & 0x3FFF0] = 0           (r126 = the image's load offset)
 *   @0x4128  ai    r3, r3, 16          every lane
 *   @0x412C  clgt  r6, r4, r3          every lane
 *   @0x4130  brnz  r6, 0x4124          on the preferred word
 *   @0x4134  br    0x407C
 *
 * The native code leaves everything as the loop does: the quadwords zeroed, r3 advanced by 16 per store in every lane,
 * r5 = 0, r6 = clgt(r4, r3) per lane, and the gate line hops to 0x407C. It declines (the lifted loop runs) when
 * the preferred words are not start < end (the do-while's single store for start >= end, never reached from 0x4078)
 * or the range is larger than the local store. */
#include "kz2_native_jobs.h"

#include <string.h>

static int vj_bss_411C(spu_context* ctx)   // @0x0000411C (job_00cd7180)
{
    const uint32_t s = ctx->gpr[3]._u32[0], e = ctx->gpr[4]._u32[0];
    if (s >= e || e - s > SPU_LS_SIZE || e > 0xFFFF0000u) return 0;
    const uint32_t n = (e - s + 15) >> 4;   /* stores: the loop runs until r3 >= r4 (unsigned) */
    uint32_t a = (s + ctx->gpr[126]._u32[0]) & (SPU_LS_MASK & ~0xFu);
    uint32_t left = n * 16;
    while (left) {   /* the store address wraps at the end of the local store, as spu_ls_write128 masks it */
        const uint32_t chunk = left < SPU_LS_SIZE - a ? left : SPU_LS_SIZE - a;
        memset(ctx->ls + a, 0, chunk);
        left -= chunk;
        a = 0;
    }
    for (int k = 0; k < 4; k++) {
        ctx->gpr[3]._u32[k] += 16 * n;
        ctx->gpr[5]._u32[k] = 0;
        ctx->gpr[6]._u32[k] = ctx->gpr[4]._u32[k] > ctx->gpr[3]._u32[k] ? 0xFFFFFFFFu : 0u;
    }
    return 1;
}

/* the job's memcpy @0x7F00 (slot 78, KZ2_NATIVE_JOB_VJCOPY). Called from the main loop @0x525C and
 * @0x598C: r3 = destination, r4 = source, r5 = bytes (preferred words), returns r3 unchanged. The SPU code:
 *   n == 0: return.
 *   both 16-byte aligned (@0x7F40): whole quadwords, then the first n & 15 bytes of the next destination quadword
 *     from the source's (@0x8070: selb with rotqmby(-1, -rest), the rest of that quadword kept).
 *   else (@0x7F70): the first destination quadword's bytes [d & 15, min(16, d & 15 + n)) from the source (shifted by
 *     rotqmby when s & 15 <= d & 15, else shufb of two source quadwords with the shift table at 0x8580 + 16 k: row k
 *     = bytes k..k+15), the other bytes kept (selb masks from shlqby/rotqmby of -1); then whole destination
 *     quadwords from source quadword pairs (shufb, table row (source & 15)); the last partial one merged as above.
 * So the local store ends as memcpy(d, s, n) leaves it when the source quadwords it reads ([s & ~15, s + n + 31))
 * are not written by the copy, every address stays below the end of the local store (lqd/stqd wrap: masked
 * 0x3FFF0) and n is the preferred word (clgti: unsigned). The native code declines otherwise. Scratch registers are
 * not reproduced (r3 is). An earlier change proved that nothing reads them: tools/spu/live_proof.py walks from both call
 * sites through the rest of the job, its calls into the job manager (API 0x1820/0x1818 through the table at LS
 * 0x1330, the command dispatcher, the SPURS kernel entries) and the job manager after the job returns, with the call
 * stack above 0x50F8 seeded; none of the 54 registers the SPU memcpy writes is read before it is written again
 * (the RE notes "An earlier change").
 * The pool (the shift table rows 0-15, LS 0x8580-0x8680) is checked: the lifted code reads it. */
static int vj_memcpy_7F00(spu_context* ctx)   // @0x00007F00 (job_00cd7180)
{
    const uint32_t d = ctx->gpr[3]._u32[0], s = ctx->gpr[4]._u32[0], n = ctx->gpr[5]._u32[0];
    if (!n) return 1;
    if ((uint64_t)d + n + 16 > SPU_LS_SIZE || (uint64_t)s + n + 32 > SPU_LS_SIZE) return 0;
    const uint32_t wlo = d & ~15u, whi = (d + n + 15) & ~15u, rlo = s & ~15u, rhi = s + n + 32;
    if (wlo < rhi && rlo < whi) return 0;   /* the copy would read what it wrote */
    memcpy(ctx->ls + d, ctx->ls + s, n);
    return 1;
}

/* VertexJob's vertex emitter @0x50F8-0x5A90 (slot 79, KZ2_NATIVE_JOB_VJVERT, on by default since
 * an earlier change, =0 off). Called from
 * the main loop @0x7014, 0x7534, 0x756C, 0x75A4 (four vertices per particle quad), argument registers:
 *   r3  the vertex format descriptor (LS address; word 2 of its quadword holds the format bits)
 *   r6  position (x, y, z)                     r7  normal / direction (x, y, z)
 *   r8  intensity (words 0-2) and alpha (3)    r9  two texture coordinates
 *   r10 LS address of a 4-byte attribute (the first word of its quadword is copied)
 *   r11 the vector of the packed attribute in the position quadword's last word
 * What it does (SPU order, which the native code keeps for every local-store access):
 *   1. prologue: r80-r90 and r0 saved at r1 - 0xB0 ... r1 + 0x10, the back chain at r1 - 0x110, r1 -= 272;
 *   2. when byte 12 of the quadword at [LS 0x84C0] + 0x9E0 is nonzero, the intensity is relit (@0x52C0): the
 *      direction through the 3x4 matrix at LS 0x8800, second-order spherical-harmonics terms with the coefficients
 *      at LS 0x1BA00-0x1BA80 (x^2 - y^2, 3 z^2 - 1), a hemisphere term clamped to [0, 1], and per the mode word at
 *      [0x84C0] + 0x9F0: 0 nothing more, 1 a distance falloff (@0x59A8: frsqest / frest refined by fi and a
 *      Newton step), else a trilinear lookup in an 8x8x8 float grid at LS 0x19B00 indexed by the position relative to
 *      LS 0x1BB40 scaled by 0x1BB50 (@0x5410, the lerp @0x48E0); then the result is scaled and clamped (@0x55E0,
 *      frsqest + fi + Newton again) into the intensity used below;
 *   3. the vertex is built on the stack at r1 + 0x20: position x, y, z, then per format bit 0x200 a packed 11:11:10
 *      word of r11 (cflts 2^31, rotm by the shifts at LS 0x8470, selb 0x003FF800), 0x20 the same packing of the
 *      direction, 0x10 the colour (intensity x3 and alpha clamped to [0, 1], times 255, cfltu: four bytes), 0x400
 *      the 4-byte attribute, format & 7 == 1 two texture-coordinate bytes (times 255, cfltu);
 *   4. it is appended to the 16 KB ring buffer (state at LS 0x27B80: buffer index, fill offset, EA, the two tags;
 *      buffers at LS 0x1FB80 + 16 KB index) with the job's memcpy; when a buffer fills (@0x58A0) it is put to main
 *      memory (MFC_Cmd 0x20 with its tag, interrupts disabled around the command as the SPU code does with bid/bie),
 *      the EA advances by 16 KB, the other buffer is waited for (MFC_WrTagMask = 1 << its tag, WrTagUpdate 2,
 *      RdTagStat) and the rest of the vertex is copied to its start;
 *   5. epilogue: r0 and r80-r90 reloaded from the stack, r1 restored.
 * The native code computes every float with the runtime's own SPU helpers (spu_fm, spu_fma, spu_fcgt, spu_cflts,
 * spu_frsqest, spu_fi, ... on full quadwords, as the lifted code calls them), so each value has the lifted code's
 * bits; it reads the constants from the local store as the SPU code does (LS 0x8800-0x8890 and the 0x1BA00
 * coefficients are written by the job at run time) except the three word-rotate shuffle patterns at LS 0x8400-0x8430,
 * which it applies as word moves (the pool: their hash), and it does the other shuffles (splats, cwd/cbd inserts with
 * the aligned stack pointer, the 11:11:10 merge) as the word and byte moves they select. It issues the same MFC channel writes and read with the
 * same values in the same order through spu_wrch / spu_rdch, and leaves int_enable as bie leaves it.
 * ASSUMPTION (bounded): an SPU interrupt that the lifted code could take at the hops after the two bie
 * (0x58F4, 0x5960) is taken at the gate's return instead: the SPU itself delivers interrupts asynchronously, so a
 * later point inside the same enabled window is a timing the hardware allows; the job's interrupt handler (WWS
 * list-stall notification) does not read this routine's state.
 * Registers: r0, r1, r80-r90 end as the epilogue leaves them (their values at the call); r3 is the last memcpy's
 * destination (full quadword); r2, r4-r79 are not written: tools/spu/live_proof.py shows that none of the registers
 * the SPU code writes (with 0x48E0 and 0x7F00) is read after the return at any of the four call sites
 * (the RE notes "An earlier change").
 * It declines (the lifted code runs) unless r1 is 16-byte aligned with the frame [r1 - 0x110, r1 + 0x20) inside
 * the local store and apart from the ring and its state [0x1FB80, 0x27BA0) (in play r1 = 0x1F630: the job's stack
 * ends just below the ring), and the ring state holds index 0 or 1 and a fill offset of at most 16 KB: then every
 * store of the routine lands in the frame or the ring, the ring copies meet neither the frame nor the state, and the
 * job's memcpy leaves the local store as memcpy does (slot 78's rule). The native code keeps the SPU order of every
 * load and store, so the frame may hold the routine's other inputs (in play r10 points into the caller's frame). */
#include "native_simd.h"

/* the runtime's channel entry points (the lifted code declares them the same way, spu_recomp.h) */
u128 spu_rdch(spu_context* ctx, uint32_t channel);
void spu_wrch(spu_context* ctx, uint32_t channel, u128 value);

#define VJ_RING 0x1FB80u
#define VJ_STATE 0x27B80u
#define SPL(x, k) sp((x)._u32[k])   /* rotqbyi 4k + shufb with the 0x00010203 pattern (ila 0x10203): splat word k */

static inline u128 L(const spu_context* c, uint32_t a) { return ldq(c->ls, a); }

/* shufb x, x with the job's word-rotate patterns at LS 0x8400 / 0x8410 / 0x8420 (n = 1, 2, 3; the pool checks them):
 * word k of the result is word k + n of x */
static inline u128 rotw(u128 x, int n)
{
    u128 r;
    for (int k = 0; k < 4; k++) r._u32[k] = x._u32[(k + n) & 3];
    return r;
}

/* shufb a, x, cwd(r1 + 4 k) with r1 16-byte aligned (the gate declines otherwise): x with word k = a's word 0 */
static inline u128 setw(u128 x, int k, uint32_t v)
{
    x._u32[k] = v;
    return x;
}

static inline void put_byte(spu_context* c, uint32_t a, u128 v)   /* cbd + lqx/shufb/stqx: byte a <- byte 3 of word 0 */
{
    c->ls[LSM(a)] = (uint8_t)v._u32[0];
}

static inline void put_word(spu_context* c, uint32_t a, u128 v)   /* cwd + lqd/shufb/stqd: the word slot of a */
{
    uint8_t* q = c->ls + LSQ(a) + (a & 0xC);
    const uint32_t w = v._u32[0];
    q[0] = (uint8_t)(w >> 24); q[1] = (uint8_t)(w >> 16); q[2] = (uint8_t)(w >> 8); q[3] = (uint8_t)w;
}

/* @0x48E0: trilinear lerp of the eight corners r3 (z = 0: c000 c100 c010 c110 by word), r4 (z = 1) at the
 * fractions r5 = (fx, fy, fz) with 1 - f from LS 0x83F0 */
static u128 vj_lerp_48E0(const spu_context* c, u128 r3, u128 r4, u128 r5)   // @0x000048E0
{
    const u128 r33 = L(c, 0x83F0);
    const u128 r10 = SPL(r5, 0), r28 = SPL(r5, 2), r16 = SPL(r5, 1);
    const u128 r27 = spu_fs(r33, r5);
    const u128 r23 = spu_fm(r4, r28);
    const u128 r9 = SPL(r27, 0), r24 = SPL(r27, 2), r7 = SPL(r27, 1);
    const u128 r21 = spu_fma(r3, r24, r23);
    const u128 r11 = SPL(r21, 0), r17 = SPL(r21, 3), r15 = SPL(r21, 2), r13 = SPL(r21, 1);
    const u128 r14 = spu_fm(r17, r16), r6 = spu_fm(r15, r16);
    const u128 r12 = spu_fma(r13, r7, r14), r5b = spu_fma(r11, r7, r6);
    const u128 r4b = SPL(r12, 0), r3b = SPL(r5b, 0);
    const u128 r2 = spu_fm(r4b, r10);
    return spu_fma(r3b, r9, r2);
}

/* @0x52C0-0x567C: the relit intensity (r12 at 0x5170) */
static u128 vj_light_52C0(const spu_context* c, u128 r4, u128 a6, u128 a7, u128 a8, u128 r1)   // @0x000052C0
{
    const u128 r19 = sp(0x3F800000u), r87 = sp(0), zero = sp(0);
    const u128 r73 = SPL(a7, 0), r55 = SPL(a7, 1), r67 = SPL(a7, 2);
    const u128 r88 = spu_ai(r4, 16);
    const u128 r72 = spu_fm(L(c, 0x8800), r73);
    const u128 r52 = L(c, 0x1BA00), r51 = L(c, 0x1BA10), r45 = L(c, 0x1BA20), r60 = L(c, 0x1BA40);
    const u128 r66 = spu_fma(L(c, 0x8810), r55, r72);
    const u128 r37 = L(c, 0x1BA30), r30 = L(c, 0x1BA60), r58 = L(c, 0x1BB60);
    const u128 r24a = spu_fa(r52, r51);
    const u128 r50 = L(c, 0x1BA50), r70 = L(c, r88._u32[0] + 0x9F0), r26 = L(c, 0x8410);
    const u128 r57 = spu_fma(L(c, 0x8820), r67, r66);   /* the direction through the matrix */
    const u128 r17 = L(c, 0x1BA80), r59 = L(c, 0x1BA70), r23 = L(c, r4._u32[0] + 0x9F0);
    const u128 r69 = spu_fma(r30, sp(0xBF800000u), r24a);
    const u128 half = sp(0x3F000000u);
    const u128 r24 = L(c, 0x8400);
    const u128 r25 = spu_rotqbyi(r70, 8);
    const u128 r47 = spu_fm(r57, r58);
    const u128 r39 = SPL(r57, 0), r35 = SPL(r57, 1), r29 = SPL(r57, 2);
    const u128 r61 = spu_fs(r69, r17);
    const u128 r62 = SPL(r25, 0);
    const u128 r68 = spu_fcgt(r25, r87);
    const u128 r33 = spu_fm(r60, r39);
    const u128 r48 = rotw(r47, 1);
    const u128 r28 = spu_fm(r59, r39);
    const u128 r42 = rotw(r47, 2);
    const u128 r46 = spu_fma(r51, r35, r52);
    const u128 r27 = L(c, 0x84B0);
    const u128 r31 = spu_fm(r50, r35);
    const u128 r44 = spu_fm(r29, sp(0x40400000u));
    const u128 r41 = spu_fa(r47, r48);
    const u128 r43 = spu_fm(r35, r35);
    const u128 r56 = spu_fm(r61, r62);
    const u128 r38 = spu_fma(r45, r29, r46);
    const u128 r63 = spu_ceqi(r68, 0);
    const u128 r8 = spu_fms(r44, r29, r19);     /* 3 z^2 - 1 */
    const u128 r40 = spu_fa(r41, r42);
    const u128 r20 = spu_fsm(r63);
    const u128 r10 = spu_fms(r39, r39, r43);    /* x^2 - y^2 */
    const u128 r12 = spu_fma(r55, r56, r56);
    const u128 r34 = spu_fma(r37, r39, r38);
    const u128 r36 = SPL(r40, 0);
    const u128 r11 = spu_fma(r33, r35, r34);
    const u128 r15 = spu_fma(r36, half, half);
    const u128 r9 = spu_fma(r31, r29, r11);
    const u128 r14 = spu_selb(r15, r19, spu_fcgt(r15, r19));
    const u128 r16 = spu_fma(r30, r8, r9);
    u128 r85 = spu_selb(zero, r14, spu_fcgt(r14, zero));
    const u128 r13 = spu_fma(r28, r29, r16);
    u128 r82 = spu_fma(r17, r10, r13);
    r82 = spu_selb(spu_fa(r82, r12), r82, r20);
    if (r23._u32[0] != 0) {
        u128 r7;
        if (spu_ceqi(r23, 1)._u32[0] != 0) {   /* @0x59A8: distance falloff */
            const uint32_t p = r27._u32[0];
            const u128 r52b = L(c, p + 0x40), r50b = L(c, p + 0x30);
            const u128 r51b = spu_fsmbi(0xF), r43b = spu_fsmbi(0xFFF0);
            const u128 r37b = L(c, 0x8880);
            const u128 r53 = spu_rotqbyi(r23, 4);
            const u128 r49 = spu_selb(r52b, r19, r51b);
            const u128 r47b = spu_fs(r52b, r50b);
            const u128 r48b = spu_selb(r50b, r19, r51b);
            const u128 r7a = spu_fm(r53, sp(0x40800000u));
            const u128 r46b = spu_fa(r48b, r49);
            const u128 r44b = spu_fm(r47b, r47b);
            const u128 r12b = SPL(r7a, 0);
            const u128 r42b = spu_fm(r46b, half);
            const u128 r45b = rotw(r44b, 1), r40b = rotw(r44b, 2);
            const u128 r41b = spu_and(r42b, r43b);
            const u128 r39b = spu_fa(r44b, r45b);
            const u128 r36b = spu_fs(a6, r41b);
            const u128 r38b = spu_fa(r39b, r40b);
            const u128 r33b = spu_fm(r36b, r37b);
            const u128 r29b = SPL(r38b, 0);
            const u128 r34b = rotw(r33b, 1), r9b = rotw(r33b, 2);
            const u128 r28b = spu_fcgt(r29b, sp(0x00800000u));
            const u128 r35b = spu_frsqest(r29b);
            const u128 r32b = spu_fa(r33b, r34b);
            const u128 r14b = spu_fi(r29b, r35b);
            const u128 r15b = spu_fa(r32b, r9b);
            const u128 r11b = spu_fm(r14b, r14b);
            const u128 r31b = spu_fm(r14b, half);
            const u128 r4b = SPL(r15b, 0);
            const u128 r30b = spu_fnms(r29b, r11b, r19);
            const u128 r16b = spu_fma(r30b, r31b, r14b);
            const u128 r17b = spu_fm(r16b, r29b);
            const u128 r13b = spu_selb(zero, r17b, r28b);
            const u128 r10b = spu_frest(r13b);
            const u128 r3b = spu_fi(r13b, r10b);
            const u128 r6b = spu_fnms(r3b, r13b, r19);
            const u128 r5b = spu_fma(r6b, r3b, r3b);
            const u128 r2b = spu_fma(r5b, r12b, zero);
            const u128 r79 = spu_fm(r4b, r2b);
            const u128 r77 = spu_fma(r79, half, half);
            const u128 r23b = spu_selb(r77, r19, spu_fcgt(r77, r19));
            const u128 r18b = spu_selb(r23b, r87, spu_fcgt(r87, r23b));
            r7 = spu_fnms(r18b, r18b, r19);
        } else {   /* @0x5410: the 8x8x8 grid at LS 0x19B00, trilinear */
            const u128 r69g = spu_fm(spu_fs(a6, L(c, 0x1BB40)), L(c, 0x1BB50));
            const u128 ci = spu_cflts(r69g, 173);   /* lane-wise: lanes 0-2 are the splatted x, y, z of the SPU code */
            int32_t ix = (int32_t)ci._u32[0], iy = (int32_t)ci._u32[1], iz = (int32_t)ci._u32[2];
            ix = ix > 7 ? 7 : ix; iy = iy > 7 ? 7 : iy; iz = iz > 7 ? 7 : iz;   /* cgti 7 + selb */
            ix = ix > -1 ? ix : 0; iy = iy > -1 ? iy : 0; iz = iz > -1 ? iz : 0;   /* cgti -1 + and */
            const uint32_t i0 = (uint32_t)(ix + 8 * (iy + 8 * iz));
            const uint32_t dx = ix != 7, dy = iy != 7 ? 8 : 0, dz = iz != 7 ? 64 : 0;   /* the far corner, clamped */
            const uint8_t* ls = c->ls;
#define G(i) rdw(ls, 0x19B00u + 4u * (i))   /* lqx + rotqby: the word at that byte address */
            u128 r3c, r4c;
            r3c._u32[0] = G(i0); r3c._u32[1] = G(i0 + dx); r3c._u32[2] = G(i0 + dy); r3c._u32[3] = G(i0 + dx + dy);
            r4c._u32[0] = G(i0 + dz); r4c._u32[1] = G(i0 + dx + dz); r4c._u32[2] = G(i0 + dy + dz);
            r4c._u32[3] = G(i0 + dx + dy + dz);
#undef G
            u128 fi;   /* csflt of the indices (lanes 0-2), lane 3 = 0 (the shufb with the zero register) */
            {
                u128 ii;
                ii._u32[0] = (uint32_t)ix; ii._u32[1] = (uint32_t)iy; ii._u32[2] = (uint32_t)iz; ii._u32[3] = 0;
                fi = spu_csflt(ii, 155);
                fi._u32[3] = 0;
            }
            const u128 r5f = spu_fs(r69g, fi);   /* the fractions */
            const u128 g = vj_lerp_48E0(c, r3c, r4c, r5f);
            const u128 one = sp(0x3F800000u);
            r7 = spu_fs(one, g);
            if (spu_fcgt(r87, r7)._u32[0] != 0) r7 = r87;   /* @0x5A84 */
            else r7 = spu_selb(r7, one, spu_fcgt(r7, one));
        }
        /* @0x55BC */
        const u128 r58 = spu_fma(r85, sp(0x3F4CCCCCu), sp(0x3E4CCCCCu));
        r85 = spu_fm(r58, SPL(r7, 0));
    }
    /* @0x55E0 */
    const u128 r12ae = spu_fm(a8, a8);
    const u128 r37e = L(c, r88._u32[0] + 0x9F0);
    const u128 r3e = spu_fma(L(c, 0x8890), r85, r82);
    const u128 r33e = spu_fm(r3e, L(c, 0x8450));
    const u128 r28e = SPL(r37e, 1);
    const u128 r34e = rotw(r33e, 1), r32e = rotw(r33e, 2), r4ce = rotw(r33e, 3);
    const u128 r6e = spu_fa(spu_fa(spu_fa(r33e, r34e), r32e), r4ce);
    const u128 r17ce = SPL(r6e, 0);
    const u128 r10ce = spu_fma(spu_fs(r3e, r17ce), r28e, r17ce);
    const u128 r13ce = spu_selb(zero, r10ce, spu_fcgt(r10ce, zero));
    const u128 r74e = spu_fm(spu_fm(r13ce, r13ce), r12ae);
    const u128 r88ce = spu_fcgt(r74e, sp(0x00800000u));
    const u128 r76e = spu_fi(r74e, spu_frsqest(r74e));
    const u128 r23ce = spu_fm(r76e, r76e), r22e = spu_fm(r76e, half);
    const u128 r75e = spu_fnms(r74e, r23ce, r19);
    const u128 r73e = spu_fma(r75e, r22e, r76e);
    return spu_selb(zero, spu_fm(r73e, r74e), r88ce);
}

/* @0x5850 / @0x57F8: the 11:11:10 packing (cflts 2^31, rotm by the shifts at LS 0x8470, two shuffles, selb) */
static inline u128 vj_pack(const spu_context* c, u128 v)
{
    const u128 r62 = spu_rotm(spu_cflts(spu_fm(v, L(c, 0x8460)), 142), L(c, 0x8470));
    /* shufb 0x08090203 / 0x04050607 + selb 0x003FF800: word 0 only is stored */
    const uint32_t lo = (r62._u32[2] & 0xFFFF0000u) | (r62._u32[0] & 0xFFFFu);
    return sp((lo & ~0x003FF800u) | (r62._u32[1] & 0x003FF800u));
}

static int vj_vertex_50F8(spu_context* ctx)   // @0x000050F8 (job_00cd7180)
{
    spu_context* const c = ctx;
    const uint32_t sp1 = c->gpr[1]._u32[0];
    /* the frame [r1 - 0x110, r1 + 0x20) inside the local store and apart from the ring and its state (the game's
     * stack sits just below the ring: r1 = 0x1F630) */
    if ((sp1 & 15) || sp1 < 0x110u || sp1 > SPU_LS_SIZE - 0x20u ||
        (sp1 - 0x110u < VJ_STATE + 0x20u && VJ_RING < sp1 + 0x20u)) return 0;
    {
        const u128 st = L(c, VJ_STATE);
        if (st._u32[0] > 1 || st._u32[1] > 0x4000u) return 0;
    }
    const u128 a3 = c->gpr[3], a6 = c->gpr[6], a7 = c->gpr[7], a8 = c->gpr[8], a9 = c->gpr[9], a10 = c->gpr[10],
               a11 = c->gpr[11];
    const u128 r4 = L(c, 0x84C0);
    /* @0x5104-0x5158: the prologue's stores, in order */
    static const struct { int r; int off; } save[] = {
        {80, -0x10}, {81, -0x20}, {83, -0x40}, {84, -0x50}, {86, -0x70}, {89, -0xA0}, {90, -0xB0}, {0, 0x10},
        {82, -0x30}, {85, -0x60}, {87, -0x80}, {88, -0x90}, {1, -0x110},
    };
    for (unsigned i = 0; i < sizeof save / sizeof save[0]; i++) stq(c->ls, sp1 + save[i].off, c->gpr[save[i].r]);
    const u128 r1 = spu_ai(c->gpr[1], -272);
    const uint32_t f = r1._u32[0];
    u128 r12 = a8;
    {
        /* rotqbyi 9 + ceqbi 0 + xsbh + brhz: relight when byte 12 of the quadword is nonzero */
        if (c->ls[LSQ(r4._u32[0] + 0x9E0) + 12] != 0) r12 = vj_light_52C0(c, r4, a6, a7, a8, r1);
    }
    /* @0x5170: the position and the format bits */
    const u128 one = sp(0x3F800000u), zero = sp(0);
    u128 q = L(c, f + 0x20);
    q._u32[0] = a6._u32[0];
    q._u32[1] = a6._u32[1];
    q._u32[2] = a6._u32[2];
    const u128 r19 = q;
    const u128 r16 = spu_rotqbyi(L(c, a3._u32[0]), 8);
    const u128 r47 = spu_selb(r12, one, spu_fcgt(r12, one));
    const u128 r81 = spu_selb(zero, r47, spu_fcgt(r47, zero));
    const u128 r9 = spu_selb(r81, SPL(a8, 3), spu_fsmbi(0xF));
    stq(c->ls, f + 0x20, r19);
    uint32_t r15 = f + 44;
    if (spu_and(r16, sp(512))._u32[0]) {   /* @0x5850: r11 packed into the position quadword's last word */
        stq(c->ls, f + 0x20, setw(r19, 3, vj_pack(c, a11)._u32[0]));
        r15 = f + 48;
    }
    if (spu_andi(r16, 32)._u32[0]) {   /* @0x57F8: the direction packed */
        put_word(c, r15, vj_pack(c, a7));
        r15 += 4;
    }
    if (spu_andi(r16, 16)._u32[0]) {   /* @0x5748: the colour bytes, stored in the order 2, 1, 0, 3 */
        const u128 m = spu_selb(r9, one, spu_fcgt(r9, one));
        const u128 r5 = spu_fm(spu_selb(zero, m, spu_fcgt(m, zero)), sp(0x437F0000u));
        const u128 b0 = spu_cfltu(SPL(r5, 0), 173), b1 = spu_cfltu(SPL(r5, 1), 173), b2 = spu_cfltu(SPL(r5, 2), 173),
                   b3 = spu_cfltu(SPL(r5, 3), 173);
        put_byte(c, r15 + 2, b2);
        put_byte(c, r15 + 1, b1);
        put_byte(c, r15, b0);
        put_byte(c, r15 + 3, b3);
        r15 += 4;
    }
    if (spu_and(r16, sp(1024))._u32[0]) {   /* @0x5680: the first word of r10's quadword, byte by byte */
        const uint8_t* s = c->ls + LSQ(a10._u32[0]);
        const uint8_t s0 = s[0], s1 = s[1], s2 = s[2], s3 = s[3];
        c->ls[LSM(r15)] = s0;
        c->ls[LSM(r15 + 1)] = s1;
        c->ls[LSM(r15 + 2)] = s2;
        c->ls[LSM(r15 + 3)] = s3;
        r15 += 4;
    }
    if (spu_ceqi(spu_andi(r16, 7), 1)._u32[0]) {   /* @0x56F8: two texture-coordinate bytes (no clamp) */
        const u128 t255 = sp(0x437F0000u);
        const u128 r65 = spu_cfltu(spu_fm(SPL(a9, 0), t255), 173), r61 = spu_cfltu(spu_fm(SPL(a9, 1), t255), 173);
        put_byte(c, r15, r65);
        put_byte(c, r15 + 1, r61);   /* lqx/stqx at r15 + r10, r10 = format & 7 = 1 */
        r15 += 2;
    }
    /* @0x5210: append to the ring */
    const u128 r87 = sp(0x4000u), r83 = sp(VJ_RING), r85 = sp(VJ_STATE);
    const u128 r4s = spu_ai(r1, 32);
    const u128 r82 = spu_sf(r4s, spu_ai(r1, (int)(r15 - f)));   /* r15 is r1 + offset in every lane */
    const u128 r73 = L(c, VJ_STATE);
    const u128 r88 = spu_rotqbyi(r73, 4);
    const u128 r25 = spu_sf(r88, r87);
    const u128 r3 = spu_a(spu_a(spu_shli(r73, 14), r83), r88);
    const u128 r81b = spu_selb(r82, r25, spu_clgt(r82, r25));
    u128 r3out = r3;
    memmove(c->ls + r3._u32[0], c->ls + r4s._u32[0], r81b._u32[0]);   /* @0x525C the job's memcpy (slot 78's rule) */
    {
        const u128 r67 = L(c, VJ_STATE);
        const u128 r8 = spu_a(r81b, spu_rotqbyi(r67, 4));
        const u128 r5 = setw(r67, 1, r8._u32[0]);
        stq(c->ls, VJ_STATE, r5);
        if (spu_ceq(r8, r87)._u32[0]) {   /* @0x58A0: the buffer is full: put it, wait for the other one */
            const u128 r46 = spu_a(spu_shli(r5, 2), r85);
            const u128 r39 = spu_rotqby(L(c, r46._u32[0] + 12), spu_ai(r46, 12));
            c->int_enable = 0;   /* bid */
            spu_wrch(c, MFC_LSA, spu_a(spu_shli(r5, 14), r83));
            spu_wrch(c, MFC_EAL, spu_rotqbyi(r5, 8));
            spu_wrch(c, MFC_Size, r8);
            spu_wrch(c, MFC_TagID, r39);
            spu_wrch(c, MFC_Cmd, sp(32));
            c->int_enable = 1;   /* bie */
            const u128 r11 = L(c, VJ_STATE);
            const u128 r34 = setw(r11, 2, r11._u32[2] + r8._u32[0]);
            const u128 r33 = spu_andi(spu_ai(r34, 1), 1);
            const u128 r30 = spu_a(spu_shli(r33, 2), r85);
            const u128 r31 = setw(setw(r34, 0, r33._u32[0]), 1, 0);
            stq(c->ls, VJ_STATE, r31);
            const u128 r28 = spu_rotqby(L(c, r30._u32[0] + 12), spu_ai(r30, 12));
            const u128 r20 = spu_shl(sp(1), r28);
            c->int_enable = 0;   /* bid */
            spu_wrch(c, MFC_WrTagMask, r20);
            spu_wrch(c, MFC_WrTagUpdate, sp(2));
            (void)spu_rdch(c, MFC_RdTagStat);
            c->int_enable = 1;   /* bie */
            const u128 r77 = L(c, VJ_STATE);
            const u128 r80 = spu_sf(r81b, r82);
            const u128 r4b = spu_a(r4s, r81b);
            r3out = spu_a(spu_a(spu_shli(r77, 14), r83), spu_rotqbyi(r77, 4));
            memmove(c->ls + r3out._u32[0], c->ls + r4b._u32[0], r80._u32[0]);   /* @0x598C */
            const u128 r23 = L(c, VJ_STATE);
            stq(c->ls, VJ_STATE, setw(r23, 1, r80._u32[0] + r23._u32[1]));
        }
    }
    /* @0x5280: the epilogue reloads r0 and r80-r90 from the save area [r1 - 0xB0, r1 + 0x20), which nothing wrote
     * after the prologue (the vertex lies at [r1 - 0xF0, r1 - 0xD2), the copies go to the ring): they end as they
     * came in, so the native code leaves them; r1 + 272 - 272 = r1 in every lane */
    c->gpr[3] = r3out;
    return 1;
}

const kz2_native_entry kz2_native_particles[] = {
    { 77, "KZ2_NATIVE_JOB_VJCLEAR", "Particles.VertexJob", "job_00cd7180", 0x411Cu, vj_bss_411C, "bss_clear", 0, 0, 0,
      0x407Cu },
    { 78, "KZ2_NATIVE_JOB_VJCOPY", "Particles.VertexJob", "job_00cd7180", 0x7F00u, vj_memcpy_7F00, "vj_memcpy", 0x8580u,
      0x8680u, 0x2a2ecd46ad5ff165ull, 0 },
    { 79, "KZ2_NATIVE_JOB_VJVERT", "Particles.VertexJob", "job_00cd7180", 0x50F8u, vj_vertex_50F8, "vj_vertex", 0x8400u,
      0x8430u, 0x061a2e8839fdd9d5ull, 0 },
};
const unsigned kz2_native_particles_n = sizeof kz2_native_particles / sizeof kz2_native_particles[0];
