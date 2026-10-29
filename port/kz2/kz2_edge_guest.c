/* Killzone 2 port, KZ2_NATIVE_ZLIB: a host write into guest memory that stands in for
 * an SPU DMA put (kz2_ppu_overrides.cpp, the Edge zlib job on the host). As the task's put does (runtime/spu/spu_dma.h):
 * lines an SPU holds a reservation on are written under the lock-line lock and their reservations broken
 * (vm_memcpy_to), and the guest-write hook (live renderer page hashing, the walker's park wake) hears the range. */
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "ppu_memory.h"

extern void (*g_spu_guest_write_hook)(uint32_t ea, uint32_t size);   /* runtime/spu/spu_coherency.c */

int kz2_guest_put(uint32_t ea, const void* src, uint32_t n)
{
    if (!n) return 0;
    if (ea < 0x10000u || (uint64_t)ea + n > 0xF0000000ull) return -1;   /* not plain guest memory: the task path */
    vm_memcpy_to(ea, src, n);
    if (g_spu_guest_write_hook) g_spu_guest_write_hook(ea, n);
    return 0;
}
