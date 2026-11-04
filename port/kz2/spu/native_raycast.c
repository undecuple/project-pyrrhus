/* native_raycast.c -- Physics.Raycast (job_00cef700, census image 204) native code: the dispatch loop of Havok's MOPP
 * ray virtual machine @0xC9C8 (slot 82, KZ2_NATIVE_JOB_RAYCAST, an earlier change; off by default).
 *
 * The routine (the RE notes "An earlier change"): 0xC9C8-0xE360 is a recursive bytecode interpreter. Its prologue saves
 * r80-r97 (frame 672 bytes) and keeps its state in callee-saved registers: r80 the code pointer (LS, inside a 512-byte
 * code chunk), r86 the ray segment in MOPP space (from at [r86], to at [r86 + 16], floats), r89 the scale state (two
 * quadwords: the offset vector, and w0 = the accumulated shift, w1 = the float scale), r91 the query, r93 the code
 * chunk number, r94 = 0xCA6C (the jump table), r95 the last rescale offset, r96 the code cache's LRU step. The
 * loop head @0xCA40 reads the opcode byte at r80 and jumps through the 108-word table at 0xCA6C (`bi $r2` @0xCA68;
 * above 107: 0xCC20, an assert). The opcodes are Havok's MOPP set: 0 return, 1-4 rescale, 5-7 jumps, 8 jump32
 * (not supported: the assert), 9-11 terminal re-offsets, 12 jump to another code chunk, 13 data offset, 16-18 split
 * X/Y/Z, 19-28 splits on diagonal axes, 32-34 single split, 35-37 split with jumps, 38-40 double cut, 41-43 double cut
 * with 24-bit planes, 48-79 short terminals, 80-83 terminals (8-32 bits), 96-107 properties. Terminals call the
 * shape's leaf callback (`bisl` through the table at 0x11640), a split the ray crosses recurses (`brsl 0xC9C8`), a
 * chunk jump that misses the code cache fetches the chunk by DMA (`brsl 0x107F8`).
 *
 * The gate is a "computed continuation" gate on the loop head (native_gates.tsv column 7 "pc"): the native code runs
 * opcodes as long as each one's whole handler would go back to 0xCA40 without a call, a DMA or a return, then does
 * the head's dispatch for the next opcode and leaves ctx->pc at the handler the lifted code's `bi $r2` would take;
 * the gate line hops there (SPU_IB_HOP). The lifted handler runs, and its `br 0xCA40` re-enters the gate. A handler
 * the native code does not take (any opcode not below, a split the ray crosses, a double cut the ray misses, a chunk
 * jump that misses the cache) is left whole to the lifted code: the native code decides before it changes anything.
 *
 * Native here: 1-4 rescale (0xCE70), 5-7 jumps (0xDFBC, 0xDF78, 0xDF18), 12 chunk jump on a cache hit (0xDC30), 13
 * (0xDC28), 16-18 split (0xDBD0 -> 0xD694 -> 0xD458), 32-34 single split (0xD3F8 -> 0xD458), 35-37 split with jumps
 * (0xD7E8 -> 0xD458), 38-40 double cut (0xD378 -> 0xD2E8/0xD3DC -> 0xD300 [-> 0xE318] -> 0xD320) and 41-43 double cut
 * 24 (0xD1F8, same tail), the ray clipped in place where it crosses a plane. Every value the SPU code computes on the
 * way to what the loop keeps is computed with the runtime's own helpers on full quadwords in the SPU code's order
 * (lane-wise, so every lane has the lifted code's bits; r80's lanes 1-3 too: they reach the stack through the
 * recursion's prologue), every load and store at the address and in the order the SPU code does them.
 *
 * Registers (tools/spu/vm_live.py, re-notes "An earlier change"): live at 0xCA40 are r0, r1, r80, r86, r89, r91, r93, r94,
 * r95, r96 (every path from the head, the jump table's 108 targets, calls reading r3-r9 and leaving r2-r79 undefined
 * as the ABI allows, the return reading r1 and r3); every handler's live-in is inside that set plus the head's own
 * r2-r9 and r14. The native code keeps the four of them the handlers write (r80, r89, r93, r95) exactly, and at the
 * exit writes r2-r9 and r14 as the head computes them; the other registers the lifted handlers write as scratch (r10-
 * r13, r15-r79 and the callee-saved r81-r85, r87, r88, r90, r92, r97, all restored by the epilogue at 0xCE10) are
 * not written. Declines (the lifted head runs) when r1 is not 16-byte aligned (the rescale's cwd inserts assume it).
 */
#include "native_simd.h"

#define RC_POOL_LO 0xCA68u   /* the jump table 0xCA6C-0xCC1B, 8-byte aligned */
#define RC_POOL_HI 0xCC20u
#define RC_MAX_OPS (1u << 20)   /* a guard: past this many opcodes in one gate call the lifted code goes on */

typedef struct {
    u128 r1, r80, r89, r93, r95, r96;
    uint32_t r86, r91;
} rc_vm;

#ifdef HARNESS_REGISTER
/* tools/spu/native_diff_harness.c stops the lifted run at the native code's exit: at the handler it names, after this
 * many passes through the loop head (the gate's own one included) */
extern unsigned g_kz2_native_heads;
#endif

/* andi(rotqby(lqx(r80 + off), r80 + 13 + off), 255): the byte at r80 + off in the preferred word, every lane */
static inline u128 rc_byte(const uint8_t* ls, u128 r80, int off)
{
    return spu_andi(spu_rotqby(ldq(ls, r80._u32[0] + (uint32_t)off), spu_ai(r80, 13 + off)), 255);
}
/* Planes and ray coordinates reach only lane 0 of what the loop keeps (the branch words, and the clip's t, splatted
 * before it meets the ray's quadwords), and every op on them is lane-wise: they are taken as splats of the SPU's
 * lane 0. cuflt(b, 155) of a byte is the exact float b. */
static inline u128 rc_plane(const uint8_t* ls, u128 r80, int off)
{
    union { float f; uint32_t u; } x;
    x.f = (float)ls[(r80._u32[0] + (uint32_t)off) & SPU_LS_MASK];
    return sp(x.u);
}
/* lane 0 of rotqby(lq(q), sh): bytes sh..sh+3 (mod 16) of the quadword at q & ~15 */
static inline u128 rc_word(const uint8_t* ls, uint32_t q, uint32_t sh)
{
    const uint8_t* b = ls + LSQ(q);
    return sp((uint32_t)b[sh & 15] << 24 | (uint32_t)b[(sh + 1) & 15] << 16 | (uint32_t)b[(sh + 2) & 15] << 8 |
              b[(sh + 3) & 15]);
}
/* the ray coordinates of the axis at byte offset o (4 x axis): rotqby(lqx(r86 + o), o) and, of the second
 * quadword, rotqby(lqd(r86 + o + 16), r86 + o) */
static inline u128 rc_from(const uint8_t* ls, uint32_t r86, u128 o) { return rc_word(ls, r86 + o._u32[0], o._u32[0]); }
static inline u128 rc_to(const uint8_t* ls, uint32_t r86, u128 o)
{
    return rc_word(ls, r86 + o._u32[0] + 0x10u, r86 + o._u32[0]);
}
static inline int w0(u128 x) { return x._u32[0] != 0; }

/* 0xD458, the splits' shared tail: r81/r83 the planes, r14 = from, r13 = to on the split axis. Both ends below the
 * low plane: the first child (r80 = r15 + r90); both above the high plane: the second (r80 = r15 + r88); else the
 * ray crosses: the lifted handler recurses (0). */
static inline int rc_d458(rc_vm* v, u128 r15, u128 r90, u128 r88, u128 r81, u128 r83, u128 r14, u128 r13)
{
    if (w0(spu_fcgt(r81, r14)) && w0(spu_fcgt(r81, r13))) { v->r80 = spu_a(r15, r90); return 1; }
    if (w0(spu_fcgt(r13, r83)) && w0(spu_fcgt(r14, r83))) { v->r80 = spu_a(r15, r88); return 1; }
    return 0;
}

/* 16-18 @0xDBD0 (split X/Y/Z), then 0xD694 */
static int rc_split(const uint8_t* ls, rc_vm* v, u128 r14)
{
    const u128 r80 = v->r80, r6 = spu_shli(spu_ai(r14, -16), 2);
    const u128 r83 = rc_plane(ls, r80, 1), r81 = rc_plane(ls, r80, 2);
    const u128 a = rc_from(ls, v->r86, r6), b = rc_to(ls, v->r86, r6);
    return rc_d458(v, spu_ai(r80, 4), spu_splat_u32(0), rc_byte(ls, r80, 3), r81, r83, a, b);
}
/* 32-34 @0xD3F8 (single split): one plane, r83 = r81 + 1.0 */
static int rc_single(const uint8_t* ls, rc_vm* v, u128 r14)
{
    const u128 r80 = v->r80, r44 = spu_shli(spu_ai(r14, -32), 2);
    const u128 r81 = rc_plane(ls, r80, 1), r83 = spu_fa(r81, spu_ilhu(0x3F80));
    const u128 a = rc_from(ls, v->r86, r44), b = rc_to(ls, v->r86, r44);
    return rc_d458(v, spu_ai(r80, 3), spu_splat_u32(0), rc_byte(ls, r80, 2), r81, r83, a, b);
}
/* 35-37 @0xD7E8 (split with 16-bit jumps): r90 = b3 << 8 + b4, r88 = b5 << 8 + b6, after r80 + 7 */
static int rc_splitjump(const uint8_t* ls, rc_vm* v, u128 r14)
{
    const u128 r80 = v->r80, r83o = spu_shli(spu_ai(r14, -35), 2);
    const u128 r83 = rc_plane(ls, r80, 1), r81 = rc_plane(ls, r80, 2);
    const u128 r90 = spu_a(spu_shli(rc_byte(ls, r80, 3), 8), rc_byte(ls, r80, 4));
    const u128 r88 = spu_a(spu_shli(rc_byte(ls, r80, 5), 8), rc_byte(ls, r80, 6));
    const u128 a = rc_from(ls, v->r86, r83o), b = rc_to(ls, v->r86, r83o);
    return rc_d458(v, spu_ai(r80, 7), r90, r88, r81, r83, a, b);
}

/* The double cuts' tail: 0xD2E8 (to > from) / 0xD3DC (else) reject a ray outside [r8, r5] (the lifted handler
 * returns, 0xCE10: 0 here), then 0xD300 clips the end beyond the high plane (0xE318, the end 1 - r12) and 0xD320 the
 * end below the low plane (the end r12): end = (1 - t) from + t to, t = r4 / (r4 - r3) by frest, fi and one
 * Newton step, from the quadwords as they were before either store. r6 = to, r7 = from on the axis. */
static int rc_cut_tail(uint8_t* ls, rc_vm* v, u128 r5, u128 r6, u128 r7, u128 r8, u128 r80n)
{
    int r12;
    if (w0(spu_fcgt(r6, r7))) {   /* 0xD2E8 */
        if (w0(spu_fcgt(r8, r6)) || w0(spu_fcgt(r7, r5))) return 0;
        r12 = 0;
    } else {                      /* 0xD3DC */
        if (w0(spu_fcgt(r8, r7)) || w0(spu_fcgt(r6, r5))) return 0;
        r12 = 1;
    }
    const uint32_t r86 = v->r86;
    const u128 zero = spu_splat_u32(0), one = spu_ilhu(0x3F80);
    u128 r3 = spu_fs(r6, r5), r4 = spu_fs(r7, r5);   /* 0xD300 */
    const u128 r11 = ldq(ls, r86), r10 = ldq(ls, r86 + 0x10u);
    if (w0(spu_fcgt(zero, spu_fm(r4, r3)))) {          /* 0xE318 */
        const u128 r84 = spu_fs(r4, r3), r82 = spu_fi(r84, spu_frest(r84)), r79 = spu_fm(r4, r82);
        const u128 r76 = spu_fma(spu_fnms(r79, r84, r4), r82, r79), r72 = sp(r76._u32[0]);
        const u128 r71 = spu_fma(r72, r10, spu_fm(spu_fs(one, r72), r11));
        stq(ls, (uint32_t)(1 - r12) * 16u + r86, r71);
    }
    r3 = spu_fs(r6, r8);                               /* 0xD320 */
    r4 = spu_fs(r7, r8);
    if (w0(spu_fcgt(zero, spu_fm(r4, r3)))) {
        const u128 r92 = spu_fs(r4, r3), r17 = spu_fi(r92, spu_frest(r92)), r16 = spu_fm(r4, r17);
        const u128 r3b = spu_fma(spu_fnms(r16, r92, r4), r17, r16), r88 = sp(r3b._u32[0]);
        const u128 r83 = spu_fma(r88, r10, spu_fm(spu_fs(one, r88), r11));
        stq(ls, (uint32_t)r12 * 16u + r86, r83);
    }
    v->r80 = r80n;
    return 1;
}
/* 38-40 @0xD378 (double cut): planes b1, b2 */
static int rc_cut(uint8_t* ls, rc_vm* v, u128 r14)
{
    const u128 r80 = v->r80, r7 = spu_shli(spu_ai(r14, -38), 2);
    const u128 r8 = rc_plane(ls, r80, 1), r5 = rc_plane(ls, r80, 2);
    const u128 from = rc_from(ls, v->r86, r7), to = rc_to(ls, v->r86, r7);
    return rc_cut_tail(ls, v, r5, to, from, r8, spu_ai(r80, 3));
}
/* 41-43 @0xD1F8 (double cut, 24-bit planes in the query's scale): plane = csflt(b1b2b3) [r91 + 0x40] * s.w1 -
 * s.offset[axis], with s = the scale state at r89 */
static int rc_cut24(uint8_t* ls, rc_vm* v, u128 r14)
{
    const u128 r80 = v->r80;
    const u128 r16 = ldq(ls, v->r91 + 0x40u), r12 = ldq(ls, v->r89._u32[0] + 0x10u);
    const u128 r18 = spu_a(spu_shli(rc_byte(ls, r80, 2), 8),
                           spu_a(spu_shli(rc_byte(ls, r80, 1), 16), rc_byte(ls, r80, 3)));
    const u128 r92 = spu_a(spu_shli(rc_byte(ls, r80, 5), 8),
                           spu_a(spu_shli(rc_byte(ls, r80, 4), 16), rc_byte(ls, r80, 6)));
    const u128 r7 = spu_shli(spu_ai(r14, -41), 2);
    const u128 r88 = spu_rotqby(ldq(ls, v->r89._u32[0] + r7._u32[0]), r7), r90 = spu_rotqbyi(r12, 4);
    const u128 from = rc_from(ls, v->r86, r7), to = rc_to(ls, v->r86, r7);
    const u128 r8 = spu_fms(spu_fm(spu_csflt(r18, 155), r16), r90, r88);
    const u128 r5 = spu_fms(spu_fm(spu_csflt(r92, 155), r16), r90, r88);
    return rc_cut_tail(ls, v, r5, to, from, r8, spu_ai(r80, 7));
}

/* 1-4 @0xCE70 (rescale by 2^op around the offset b1, b2, b3): the ray and the scale state are rewritten, the state
 * now in this frame (r89 = r1 + 32) */
static int rc_rescale(uint8_t* ls, rc_vm* v, u128 r14)
{
    const u128 r80 = v->r80, r1 = v->r1;
    const uint32_t r86 = v->r86, sp1 = r1._u32[0], r89 = v->r89._u32[0];
    const u128 r27 = spu_cuflt(rc_byte(ls, r80, 1), 155), r26 = spu_cuflt(rc_byte(ls, r80, 2), 155);
    const u128 r8 = spu_cuflt(rc_byte(ls, r80, 3), 155);
    const u128 r5 = spu_csflt(spu_shl(spu_il(1), r14), 155), r16 = sp(r5._u32[0]);
    u128 r95 = v->r95;   /* cwd at r1 + 0/4/8/12 with r1 16-byte aligned: the words in order */
    r95._u32[0] = r27._u32[0];
    r95._u32[1] = r26._u32[0];
    r95._u32[2] = r8._u32[0];
    r95._u32[3] = 0;
    const u128 r10 = ldq(ls, r86), r21 = ldq(ls, r86 + 0x10u), r90 = ldq(ls, sp1 + 0x30u);
    stq(ls, r86, spu_fm(spu_fs(r10, r95), r16));
    stq(ls, r86 + 0x10u, spu_fm(spu_fs(r21, r95), r16));
    const u128 r17 = ldq(ls, r89);
    stq(ls, sp1 + 0x20u, spu_fm(spu_fa(r17, r95), r16));
    u128 q = r90;
    q._u32[0] = spu_a(r14, ldq(ls, r89 + 0x10u))._u32[0];
    stq(ls, sp1 + 0x30u, q);
    q._u32[1] = spu_fm(r5, spu_rotqbyi(ldq(ls, r89 + 0x10u), 4))._u32[0];
    stq(ls, sp1 + 0x30u, q);
    q._u32[3] = ldq(ls, r89 + 0x10u)._u32[3];
    stq(ls, sp1 + 0x30u, q);
    q._u32[2] = ldq(ls, r89 + 0x10u)._u32[2];
    stq(ls, sp1 + 0x30u, q);
    v->r89 = spu_ai(r1, 32);
    v->r95 = r95;
    v->r80 = spu_ai(r80, 4);
    return 1;
}

/* 12 @0xDC30 (jump to code chunk b1 << 8 | b2): the 4-way code cache at [0x11AD0] (tags at +0x50 + set, the line
 * addresses before them, the LRU words after, the set from (EA >> 3) & [+0x20]); a hit continues at the line, a miss
 * fetches it (0xDFE8: lifted) */
static int rc_chunk(uint8_t* ls, rc_vm* v)
{
    const u128 r80 = v->r80;
    const u128 r93 = spu_or(spu_shli(rc_byte(ls, r80, 1), 8), rc_byte(ls, r80, 2));
    const u128 r8 = spu_a(ldq(ls, v->r91 + 0xF0u), spu_shli(r93, 9));
    const u128 r9 = ldq(ls, 0x11AD0u), r61 = ldq(ls, r9._u32[0] + 0x20u), r6 = ldq(ls, r9._u32[0] + 0x50u);
    const u128 r59 = spu_and(spu_rotmi(r8, -3), r61), r7 = spu_a(r6, r59);
    const u128 r54 = ldq(ls, r6._u32[0] + r59._u32[0]), r57 = ldq(ls, r7._u32[0] + 0x10u);
    const u128 r58 = ldq(ls, r7._u32[0] + 0x20u);
    const u128 r53 = spu_ceq(sp(r8._u32[0]), r57), r50 = spu_orx(spu_and(r53, r54));
    if (!r50._u32[0]) return 0;
    stq(ls, r7._u32[0] + 0x20u, spu_andc(spu_a(r58, v->r96), r53));
    v->r93 = r93;
    v->r80 = r50;
    return 1;
}

static int rc_vm_CA40(spu_context* ctx)   // @0x0000CA40 (job_00cef700)
{
    uint8_t* ls = ctx->ls;
    if (ctx->gpr[1]._u32[0] & 15u) return 0;
    rc_vm v;
    v.r1 = ctx->gpr[1];
    v.r80 = ctx->gpr[80];
    v.r89 = ctx->gpr[89];
    v.r93 = ctx->gpr[93];
    v.r95 = ctx->gpr[95];
    v.r96 = ctx->gpr[96];
    v.r86 = ctx->gpr[86]._u32[0];
    v.r91 = ctx->gpr[91]._u32[0];
    const u128 r94 = ctx->gpr[94];
    unsigned heads = 0;
    u128 r9, r8, r7, r14;
    for (;;) {
        heads++;
        r9 = spu_ai(v.r80, 13);   /* @0xCA40 */
        r8 = ldq(ls, v.r80._u32[0]);
        r7 = spu_rotqby(r8, r9);
        r14 = spu_andi(r7, 255);
        if (heads > RC_MAX_OPS) break;
        int done;
        switch (r14._u32[0]) {
        case 1: case 2: case 3: case 4: done = rc_rescale(ls, &v, r14); break;
        case 5: v.r80 = spu_a(spu_ai(v.r80, 2), rc_byte(ls, v.r80, 1)); done = 1; break;               /* 0xDFBC */
        case 6:                                                                                          /* 0xDF78 */
            v.r80 = spu_a(spu_ai(v.r80, 3), spu_a(rc_byte(ls, v.r80, 2), spu_shli(rc_byte(ls, v.r80, 1), 8)));
            done = 1;
            break;
        case 7: {                                                                                        /* 0xDF18 */
            const u128 r35 = spu_a(spu_shli(rc_byte(ls, v.r80, 2), 8), rc_byte(ls, v.r80, 3));
            v.r80 = spu_a(spu_ai(v.r80, 4), spu_a(spu_shli(rc_byte(ls, v.r80, 1), 16), r35));
            done = 1;
            break;
        }
        case 12: done = rc_chunk(ls, &v); break;
        case 13: v.r80 = spu_ai(v.r80, 5); done = 1; break;                                             /* 0xDC28 */
        case 16: case 17: case 18: done = rc_split(ls, &v, r14); break;
        case 32: case 33: case 34: done = rc_single(ls, &v, r14); break;
        case 35: case 36: case 37: done = rc_splitjump(ls, &v, r14); break;
        case 38: case 39: case 40: done = rc_cut(ls, &v, r14); break;
        case 41: case 42: case 43: done = rc_cut24(ls, &v, r14); break;
        default: done = 0; break;
        }
        if (!done) break;
    }
    /* the head's dispatch for the opcode the lifted code takes on (0xCA50-0xCA68) */
    const u128 r6 = spu_shli(r14, 2), r4 = spu_clgti(r14, 107), r3 = spu_a(r94, r6);
    const u128 r5 = ldq(ls, r94._u32[0] + r6._u32[0]), r2 = spu_rotqby(r5, r3);
    ctx->gpr[2] = r2;
    ctx->gpr[3] = r3;
    ctx->gpr[4] = r4;
    ctx->gpr[5] = r5;
    ctx->gpr[6] = r6;
    ctx->gpr[7] = r7;
    ctx->gpr[8] = r8;
    ctx->gpr[9] = r9;
    ctx->gpr[14] = r14;
    ctx->gpr[80] = v.r80;
    ctx->gpr[89] = v.r89;
    ctx->gpr[93] = v.r93;
    ctx->gpr[95] = v.r95;
    ctx->pc = r4._u32[0] ? 0xCC20u : r2._u32[0];
#ifdef HARNESS_REGISTER
    g_kz2_native_heads = heads;
#endif
    return 1;
}

const kz2_native_entry kz2_native_raycast[] = {
    { 82, "KZ2_NATIVE_JOB_RAYCAST", "Physics.Raycast", "job_00cef700", 0xCA40u, rc_vm_CA40, "mopp_vm", RC_POOL_LO,
      RC_POOL_HI, 0xda64e2a0ba39a2b0ull, KZ2_NATIVE_CONT_PC },
};
const unsigned kz2_native_raycast_n = sizeof kz2_native_raycast / sizeof kz2_native_raycast[0];
