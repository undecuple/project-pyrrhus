/* native_particles.c -- Particles.VertexJob (job_00cd7180, image 201) native code. Off by default (KZ2_NATIVE_JOB_VJCLEAR).
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

const kz2_native_entry kz2_native_particles[] = {
    { 77, "KZ2_NATIVE_JOB_VJCLEAR", "Particles.VertexJob", "job_00cd7180", 0x411Cu, vj_bss_411C, "bss_clear", 0, 0, 0,
      0x407Cu },
};
const unsigned kz2_native_particles_n = sizeof kz2_native_particles / sizeof kz2_native_particles[0];
