/* kz2_native_jobs.h -- native host versions of hot SPU job code.
 *
 * A native gate is a check at the top of a lifted SPU function (inserted by tools/spu/lift_spu.py from
 * re/spu/native_gates.tsv): when g_kz2_native_gate[slot] is set and returns 1, the native code has done the whole
 * subroutine (its local-store writes and the registers its caller reads) and the lifted function returns to its link
 * as the SPU's `bi $r0` would; a "continue at" gate (native_gates.tsv column 7, the entry's `cont`) covers
 * code that is not a subroutine and hops on to that address instead. Returning 0 runs the lifted body (unexpected arguments, a debug gate armed, the job's
 * constant tables not what the native code was written for). Which gates are filled: native_flags.h. A gate is
 * filled when one of its entry's flags is 1 (`env` lists KZ2_NATIVE_JOB_<NAME> alternatives separated by '|'), or
 * KZ2_NATIVE_JOB_POST=1 for a Gfx.Post gate, or by default: every Gfx.Post flag is on by default
 * for the 25 slots with equality on inputs recorded in play (KZ2_NATIVE_JOB_DOF only). A flag set to 0
 * turns its entries off; KZ2_NATIVE_JOB_POST=0 turns every Gfx.Post gate off. Non-post jobs (Anim.EdgeAnim, round
 * 19: KZ2_NATIVE_JOB_EDGEANIM) stay off unless their flag is 1.
 *
 * Every gate runs through kz2_native_run (native_common.c): it counts the call, declines while a debug LS gate is
 * armed, checks the entry's constant pool (the LS range its kernel's lqr loads read, against the hash of the 1.29
 * image's bytes: a different image or rewritten constants run the lifted code) and then calls the kernel, which
 * checks its own arguments. A kernel returns 1 when it did the whole subroutine, 0 to run the lifted body.
 *
 * KZ2_NATIVE_REC=DIR records real inputs instead (every gate, flags or not): the whole context (128 registers, the
 * 256 KB local store) at the gate, written to DIR/s<slot>_<n>.kz2nj, then the lifted body runs. KZ2_NATIVE_REC_N
 * (default 24) records per slot, KZ2_NATIVE_REC_EVERY (default 61) calls between records, KZ2_NATIVE_REC_AFTER
 * (default 120) seconds before the first; KZ2_NATIVE_REC_DOF_BLUR=1 counts only DepthOfField gather calls with a blur
 * radius above 0; KZ2_NATIVE_REC_SLOT=<slot>:<every>:<n>[,...] gives slots their own spacing and count,
 * KZ2_NATIVE_REC_VJFLUSH=<n> adds up to n VertexJob vertex calls that fill its ring buffer (the DMA put).
 * Recording also counts the calls per slot (`[native] slot N ... calls=`). The records
 * hold game data: keep them under work/, never commit them.
 * tools/spu/native_diff.py replays them through the lifted and the native code and compares (native_diff_harness.c).
 */
#ifndef KZ2_NATIVE_JOBS_H
#define KZ2_NATIVE_JOBS_H

#include <stdint.h>
#include "spu_context.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef int (*kz2_native_fn)(spu_context*);

typedef struct {
    int slot;              /* g_kz2_native_gate index (re/spu/native_gates.tsv) */
    const char* env;       /* KZ2_NATIVE_JOB_<NAME>, alternatives separated by '|' */
    const char* job;       /* census name */
    const char* image;     /* lifted image (job_<file offset>), as in native_gates.tsv */
    uint32_t addr;         /* LS address of the gated function */
    kz2_native_fn fn;
    const char* kind;      /* kernel family (the diff harness picks its synthetic inputs by it) */
    uint32_t pool_lo, pool_hi;   /* constant pool the kernel was written for: LS [lo, hi), 8-byte aligned */
    uint64_t pool_hash;          /* FNV-1a 64 over its little-endian 8-byte words (tools/spu/post_kernels.py) */
    uint32_t cont;         /* 0: a subroutine (the gate returns to r0); else a "continue at" gate: the
                            * native code did the code from addr up to this LS address, and the gate line hops there
                            * (native_gates.tsv column 7 names the same address; tools/spu/test_native_vjclear.sh
                            * checks the lifted gate line); KZ2_NATIVE_CONT_PC (column 7 "pc"): a computed
                            * continuation, the native code sets ctx->pc and the gate line hops there (SPU_IB_HOP) */
} kz2_native_entry;
#define KZ2_NATIVE_CONT_PC 1u   /* no SPU instruction address (they are 4-byte aligned) */

extern const kz2_native_entry kz2_native_dof[];
extern const unsigned kz2_native_dof_n;
extern const kz2_native_entry kz2_native_post[];
extern const unsigned kz2_native_post_n;
extern const kz2_native_entry kz2_native_blur[];
extern const unsigned kz2_native_blur_n;
extern const kz2_native_entry kz2_native_bloom[];
extern const unsigned kz2_native_bloom_n;
extern const kz2_native_entry kz2_native_postjobs[];   /* native_postjobs.c */
extern const unsigned kz2_native_postjobs_n;
extern const kz2_native_entry kz2_native_edgeanim[];   /* native_edgeanim.c */
extern const unsigned kz2_native_edgeanim_n;
extern const kz2_native_entry kz2_native_particles[];  /* native_particles.c */
extern const unsigned kz2_native_particles_n;
extern const kz2_native_entry kz2_native_skinning[];   /* native_skinning.c */
extern const unsigned kz2_native_skinning_n;
extern const kz2_native_entry kz2_native_raycast[];    /* native_raycast.c */
extern const unsigned kz2_native_raycast_n;

/* native_common.c: the entry of a slot (NULL: none), and one gated call (count, debug gate, pool, kernel; counts a
 * fallback when it returns 0). */
const kz2_native_entry* kz2_native_find(int slot);
int kz2_native_run(spu_context* ctx, const kz2_native_entry* e);

/* Record file layout (little-endian host): magic "KZ2NJ001", u32 slot, u32 addr, s32 image_id, u32 resident_ovl,
 * then 128 x 16 bytes of registers (the runtime's u128 layout, _u32[0] = SPU word 0), then the 256 KB local store. */
#define KZ2_NJ_MAGIC "KZ2NJ001"

/* Gate slots (128): g_kz2_native_gate[] in the generated spu_workloads.c has this size. */
#define KZ2_NATIVE_SLOTS 128

/* Calls and fallbacks per slot (the native function counts its own fallbacks). kz2_native_count prints
 * `[native] slot N calls=C fallback=F` when one context's count reaches 1024 and every power of two after (C: the sum
 * over every context then). Diagnostic only: nothing reads the counts but the print.
 * one row of call counters per SPU context, each written only by the thread that runs that context, with a
 * plain load and store (no lock prefix). An earlier change's eight shards picked by a hash of the context still took one
 * `lock xadd` per call, and two contexts could share a shard: kz2_native_run stayed 4.9 % of VertexJob's samples, 239 of
 * its 318 samples on the instruction after that `lock xadd` (spu 35 profile, 150-170 s; slot 81 runs ~350 000 times a
 * second). A context gets its row the first time it calls a native gate (kz2_native_row_claim: a 64-entry table of
 * context pointers, home index from the pointer's hash, linear probe, CAS to claim); a context that finds no free row
 * counts in the shared row KZ2_NATIVE_CTXS with an atomic add, as before. ASSUMPTION: one SPU context runs on one
 * thread at a time (persistent policy contexts belong to one (workload, SPU) pair; job contexts live on their thread's
 * stack); if two threads ever ran one context at once, only counts would be lost, never a crash. */
#define KZ2_NATIVE_CTXS 64
typedef struct { volatile long calls[KZ2_NATIVE_SLOTS]; } kz2_native_row;
extern kz2_native_row g_kz2_native_rows[KZ2_NATIVE_CTXS + 1];   /* native_common.c; the last row is shared */
extern const void* volatile g_kz2_native_keys[KZ2_NATIVE_CTXS];
extern volatile long g_kz2_native_fb[KZ2_NATIVE_SLOTS];
unsigned kz2_native_row_claim(const void* ctx);                   /* native_common.c: row index, or KZ2_NATIVE_CTXS */
static inline unsigned kz2_native_home(const void* ctx)
{
    return (unsigned)(((uint64_t)(uintptr_t)ctx * 0x9E3779B97F4A7C15ull) >> 58);
}
long kz2_native_calls_sum(int slot);
long kz2_native_fallback_sum(int slot);
void kz2_native_count_print(int slot, long calls);
static inline void kz2_native_count(int slot, const void* ctx)
{
    const unsigned s = (unsigned)slot & (KZ2_NATIVE_SLOTS - 1);
    unsigned r = kz2_native_home(ctx);
    if (__builtin_expect(__atomic_load_n(&g_kz2_native_keys[r], __ATOMIC_RELAXED) != ctx, 0)) r = kz2_native_row_claim(ctx);
    long c;
    if (__builtin_expect(r < KZ2_NATIVE_CTXS, 1)) {
        c = __atomic_load_n(&g_kz2_native_rows[r].calls[s], __ATOMIC_RELAXED) + 1;
        __atomic_store_n(&g_kz2_native_rows[r].calls[s], c, __ATOMIC_RELAXED);
    } else {
        c = __atomic_add_fetch(&g_kz2_native_rows[KZ2_NATIVE_CTXS].calls[s], 1, __ATOMIC_RELAXED);
    }
    if (__builtin_expect(c >= 1024 && !(c & (c - 1)), 0)) kz2_native_count_print(slot, kz2_native_calls_sum(slot));
}
static inline void kz2_native_fell_back(int slot, const void* ctx)
{
    (void)ctx;
    __atomic_fetch_add(&g_kz2_native_fb[(unsigned)slot & (KZ2_NATIVE_SLOTS - 1)], 1, __ATOMIC_RELAXED);
}

#ifdef __cplusplus
}
#endif
#endif
