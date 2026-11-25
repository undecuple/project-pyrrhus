/* Killzone 2 patch 6094 (from KZ3 patch 2236, Project Helghast, same author, MIT): the half of the [ppu-isa] boot
 * self-test that is built with the lifted PPU sources' own compile options (port/kz2/CMakeLists.txt gives this file
 * KZ2_PPU_LIFTED_OPTS: -mfma when KZ2_PPU_ISA=ON). It runs runtime/ppu/ppu_vmx.h's vmaddfp / vnmsubfp and fmaf the way
 * the lifted code does; ppu_isa_ref.cpp runs the same inputs through the scalar path with an exact fmaf, built without
 * FMA, and compares. A toolchain that miscompiles the -mfma code on the player's machine then says so in the log at
 * boot instead of as wrong game maths; a build without -mfma shows how many of the 64 MinGW's fmaf gets wrong. */
#include <stdint.h>
#include <math.h>
#include "ppu_vmx.h"

extern "C" unsigned kz2_ppu_isa_probe(const uint8_t (*in)[48], const uint32_t* vscr, uint8_t (*madd)[16],
                                      uint8_t (*nmsub)[16], const float (*fin)[3], float* fout, int n)
{
    for (int i = 0; i < n; i++) {
        vmx_vmaddfp(madd[i], in[i], in[i] + 16, in[i] + 32, vscr[i]);
        vmx_vnmsubfp(nmsub[i], in[i], in[i] + 16, in[i] + 32, vscr[i]);
        fout[i] = fmaf(fin[i][0], fin[i][1], fin[i][2]);
    }
    unsigned flags = 0;
#if defined(__FMA__)
    flags |= 1u;
#endif
#if defined(VMX_SIMD_FMA)
    flags |= 2u;
#endif
#if defined(KZ2_PPU_PROBE_CMODEL_SMALL)
    flags |= 4u;
#endif
#if defined(KZ2_PPU_PROBE_TRAMP_TEB)
    flags |= 8u;
#endif
    return flags;
}
