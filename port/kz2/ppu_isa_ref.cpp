/* Killzone 2 patch 6094 (from KZ3 patch 2236, Project Helghast, same author, MIT; adapted): the reference half of the
 * [ppu-isa] boot self-test. Built with -mno-fma -mno-avx whatever the lifted flags are (port/kz2/CMakeLists.txt), so
 * ppu_vmx.h takes its scalar vmaddfp / vnmsubfp path, and with fmaf replaced by kz2_fmaf_exact (kz2_fmaf_exact.h):
 * KZ3's reference was the library fmaf, which on MinGW is not correctly rounded, so it would have checked the -mfma
 * code against the wrong bits. ppu_isa_probe.cpp, built with the lifted flags, runs the same 64 inputs;
 * kz2_ppu_isa_line() compares them bit for bit and returns the line main.cpp logs:
 *   [ppu-isa] fma=1 simd=1 cmodel=small tramp_teb=0 exact vmaddfp=64/64 vnmsubfp=64/64 fma=64/64
 * (a NaN result equals any NaN in the fma column: which payload x86 keeps depends on the vfmadd form). With
 * KZ2_PPU_ISA=ON anything below 64/64 is a MISMATCH; with it OFF the counts are MinGW's software fmaf against the
 * exact answer (informational). The probe runs only on a CPU with AVX + FMA3 when it was built with -mfma
 * (kz2_cpu_check.c has refused the others). */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "kz2_fmaf_exact.h"
#define fmaf kz2_fmaf_exact   /* the scalar vmaddfp / vnmsubfp below use the exact reference */
#include "ppu_vmx.h"
#undef fmaf

extern "C" unsigned kz2_ppu_isa_probe(const uint8_t (*in)[48], const uint32_t* vscr, uint8_t (*madd)[16],
                                      uint8_t (*nmsub)[16], const float (*fin)[3], float* fout, int n);

enum { KZ2_ISA_N = 64 };

static uint32_t isa_rng(uint32_t* s) { *s ^= *s << 13; *s ^= *s >> 17; *s ^= *s << 5; return *s; }

extern "C" const char* kz2_ppu_isa_line(void)
{
    static char line[260];
    static const uint32_t sp[] = {0x00000000u, 0x80000000u, 0x00000001u, 0x807FFFFFu, 0x00800000u, 0x7F7FFFFFu,
                                  0xFF800000u, 0x7FC00000u, 0x7F812345u, 0x3F800000u, 0xBF800000u, 0x40000000u};
    uint8_t in[KZ2_ISA_N][48], m0[KZ2_ISA_N][16], m1[KZ2_ISA_N][16], n0[KZ2_ISA_N][16], n1[KZ2_ISA_N][16];
    uint32_t vs[KZ2_ISA_N];
    float fin[KZ2_ISA_N][3], f0[KZ2_ISA_N], f1[KZ2_ISA_N];
    uint32_t s = 0x2236u;
    for (int i = 0; i < KZ2_ISA_N; i++) {
        for (int w = 0; w < 12; w++) {
            uint32_t x = isa_rng(&s);
            if (i < 16) x = sp[(i + 5 * w) % 12];                               /* specials */
            else if (i < 48 || w < 4) x = (x & 0x807FFFFFu) | ((110u + x % 35u) << 23);  /* mid exponents */
            else if (w >= 4 && w < 8) {                                         /* b: nearly cancels a*c */
                const uint32_t a = vmx_w(in[i], w - 4), c = (x & 0x007FFFFFu) | 0x3F800000u;
                vmx_sw(in[i], w + 4, c);
                const float p = vmx_f(a) * vmx_f(c);
                x = vmx_u((i & 1) ? -p : p) + (x >> 30) - 1u;
            } else if (w >= 8) continue;                                        /* c: written with b */
            vmx_sw(in[i], w, x);
        }
        if (i == 20) for (int w = 0; w < 12; w++) vmx_sw(in[i], w, 0x3F800000u);   /* 1*1 - 1 = exact zero */
        vs[i] = (i & 2) ? VMX_NJ : 0u;
        for (int k = 0; k < 3; k++) fin[i][k] = vmx_f(vmx_w(in[i], 4 * k + (i & 3)));
    }
    for (int i = 0; i < KZ2_ISA_N; i++) {
        vmx_vmaddfp(m0[i], in[i], in[i] + 16, in[i] + 32, vs[i]);
        vmx_vnmsubfp(n0[i], in[i], in[i] + 16, in[i] + 32, vs[i]);
        f0[i] = kz2_fmaf_exact(fin[i][0], fin[i][1], fin[i][2]);
    }
    const unsigned fl = kz2_ppu_isa_probe(in, vs, m1, n1, fin, f1, KZ2_ISA_N);
    int okm = 0, okn = 0, okf = 0;
    for (int i = 0; i < KZ2_ISA_N; i++) {
        okm += !memcmp(m0[i], m1[i], 16);
        okn += !memcmp(n0[i], n1[i], 16);
        okf += vmx_u(f0[i]) == vmx_u(f1[i]) || (isnan(f0[i]) && isnan(f1[i]));
    }
    const int bad = okm != KZ2_ISA_N || okn != KZ2_ISA_N || okf != KZ2_ISA_N;
    const char* note = !bad ? ""
                       : (fl & 1u) ? " MISMATCH: the -mfma build computes different bits than the exact reference (rebuild with -DKZ2_PPU_ISA=OFF)"
                                   : " (no -mfma: the library fmaf is not correctly rounded here; KZ2_PPU_ISA=ON gives the PS3's single rounding)";
    snprintf(line, sizeof line, "[ppu-isa] fma=%u simd=%u cmodel=%s tramp_teb=%u exact vmaddfp=%d/%d vnmsubfp=%d/%d fma=%d/%d%s",
             fl & 1u, (fl >> 1) & 1u, (fl & 4u) ? "small" : "default", (fl >> 3) & 1u, okm, KZ2_ISA_N, okn, KZ2_ISA_N,
             okf, KZ2_ISA_N, note);
    return line;
}
