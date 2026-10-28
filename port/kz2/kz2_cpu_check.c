/* Killzone 2: CPU check for the lifted SPU code (from Project Helghast+ port/spu/kz3_cpu_check.c,
 * adapted: own CPUID/XGETBV reads instead of __builtin_cpu_supports, a pure decision function for
 * the host test, and a forced-fail switch).
 *
 * The lifted SPU sources are built with -mfma by default (KZ2_SPU_FMA, port/kz2/CMakeLists.txt), which
 * also lets the compiler use AVX (VEX) encodings in them. A CPU without FMA3/AVX, or an OS that does not save the
 * AVX register state, would die with an illegal instruction on the first such opcode and no word why. This file is
 * built WITHOUT those flags (it is not one of the SPU sources) and runs as a priority-101 constructor, ahead of every
 * default-priority constructor and of main(). FMA3 + AVX: Intel Haswell (2013) / AMD Piledriver (2012) or newer.
 *
 * The check is compiled in only when CMake defines KZ2_SPU_NEEDS_FMA (KZ2_SPU_FMA=ON); a build with -DKZ2_SPU_FMA=OFF
 * demands nothing. KZ2_CPU_CHECK_FAIL=1 forces the failure path (host test tools/runtime/test_cpu_check.sh). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(_WIN32)
#include <windows.h>
#endif

#include "kz2_cpu_check.h"

/* CPUID.1:ECX bits and the XCR0 bits the OS sets when it saves the SSE (bit 1) and AVX (bit 2) state. */
#define KZ2_CPUID1_ECX_FMA     (1u << 12)
#define KZ2_CPUID1_ECX_OSXSAVE (1u << 27)
#define KZ2_CPUID1_ECX_AVX     (1u << 28)
#define KZ2_XCR0_SSE_AVX       0x6u

/* Pure decision, no CPU access: 0 = fine, otherwise a KZ2_CPU_MISSING_* bit set. xcr0 is only looked at when the
 * CPU reports OSXSAVE (XGETBV faults otherwise). */
unsigned kz2_cpu_check_eval(unsigned cpuid1_ecx, unsigned long long xcr0)
{
    unsigned miss = 0;
    if (!(cpuid1_ecx & KZ2_CPUID1_ECX_AVX)) miss |= KZ2_CPU_MISSING_AVX;
    if (!(cpuid1_ecx & KZ2_CPUID1_ECX_FMA)) miss |= KZ2_CPU_MISSING_FMA;
    if (!(cpuid1_ecx & KZ2_CPUID1_ECX_OSXSAVE) || (xcr0 & KZ2_XCR0_SSE_AVX) != KZ2_XCR0_SSE_AVX)
        miss |= KZ2_CPU_MISSING_OS_AVX;
    return miss;
}

#if (defined(__GNUC__) || defined(__clang__)) && (defined(__x86_64__) || defined(__i386__))
#include <cpuid.h>

unsigned kz2_cpu_check_host(void)
{
    unsigned a = 0, b = 0, c = 0, d = 0;
    if (!__get_cpuid(1, &a, &b, &c, &d)) return KZ2_CPU_MISSING_AVX | KZ2_CPU_MISSING_FMA | KZ2_CPU_MISSING_OS_AVX;
    unsigned long long xcr0 = 0;
    if (c & KZ2_CPUID1_ECX_OSXSAVE) {
        unsigned lo, hi;
        /* xgetbv with ecx = 0, as raw bytes so the file needs no -mxsave. */
        __asm__ volatile(".byte 0x0f, 0x01, 0xd0" : "=a"(lo), "=d"(hi) : "c"(0));
        xcr0 = ((unsigned long long)hi << 32) | lo;
    }
    return kz2_cpu_check_eval(c, xcr0);
}

/* Returns 0 if the process may go on; otherwise shows the message and returns the missing bits. */
unsigned kz2_cpu_check_run(void)
{
    const char *force = getenv("KZ2_CPU_CHECK_FAIL");
    unsigned miss = (force && force[0] && strcmp(force, "0") != 0) ? KZ2_CPU_MISSING_FORCED : kz2_cpu_check_host();
    if (!miss) return 0;
    char msg[512];
    snprintf(msg, sizeof msg,
             "This build of Killzone 2 needs a CPU with AVX and FMA3 (Intel Haswell / AMD Piledriver or newer) and an "
             "operating system that enables AVX.\n"
             "Missing here:%s%s%s%s\n"
             "A build made with -DKZ2_SPU_FMA=OFF runs without them.",
             (miss & KZ2_CPU_MISSING_AVX) ? " AVX" : "", (miss & KZ2_CPU_MISSING_FMA) ? " FMA3" : "",
             (miss & KZ2_CPU_MISSING_OS_AVX) ? " OS-AVX-state" : "",
             (miss & KZ2_CPU_MISSING_FORCED) ? " (forced by KZ2_CPU_CHECK_FAIL)" : "");
    fprintf(stderr, "[kz2-cpu] %s\n", msg);
    fflush(stderr);
#if defined(_WIN32)
    MessageBoxA(NULL, msg, "Killzone 2", MB_OK | MB_ICONERROR | MB_TOPMOST);
#endif
    return miss;
}

#if defined(KZ2_SPU_NEEDS_FMA)
__attribute__((constructor(101))) static void kz2_cpu_check(void)
{
    if (kz2_cpu_check_run()) exit(1);
}
#endif
#endif
