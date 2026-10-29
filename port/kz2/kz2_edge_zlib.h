/* Killzone 2 port, KZ2_NATIVE_ZLIB: the Edge zlib inflate job on the host.
 *
 * The game's only Edge zlib user is FIOS's dearchiver (1.29 func_0002CD20 / func_0002CFD8 -> func_003C8E40 ->
 * func_003C8BA0 = edgeZlibAddInflateQueueElement, v1.01 0x3BCAA0). The element (32 bytes, big-endian) goes through
 * _cellSpursLFQueuePushBody to SPURS task image 35 (spu_00ccb180.elf, zlib 1.2.3 "1.2.3.0-PS3-SPU-EDGE"), which pops it
 * and, read from the lifted task (elf_00ccb180, LS 0x3248..0x3630):
 *   - checks inSize <= 0x10000, expected = skipBegin + partial + skipEnd <= 0x10000, skipBegin + skipEnd <= expected;
 *   - mode (bit 0 of the counter word): 1 = raw-deflate inflate of the whole block (LS 0x3668 -> 0x3808),
 *     0 = plain copy, which requires inSize == expected (else "EDGE ZLIB ERROR" and no completion; LS 0x3344/0x3430);
 *   - DMAs out only bytes [skipBegin, skipBegin + partial) of the result to `out` and waits for that DMA (0x34A0..0x35E4);
 *   - counter = word & ~1: if non-zero, atomically decrements it (GETLLAR/PUTLLC at 0xA850, returns the old value,
 *     decrements even from 0 after printing the error) and sets the event flag only when the old value was 1;
 *     if the counter is 0, sets the event flag (when non-zero) unconditionally (0x35E4/0x3610/0x3630);
 *   - an inflate error or a size mismatch prints and skips the completion (the PPU then waits forever).
 * This file is that job in plain C, so the override (kz2_ppu_overrides.cpp) and the host test share it. Guest memory goes
 * through kz2_edge_ops. Written from the lifted code and our notes (the RE notes "An earlier change"). */
#ifndef KZ2_EDGE_ZLIB_H
#define KZ2_EDGE_ZLIB_H
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define KZ2_EDGE_MAX 0x10000u   /* the task's LS limits on compressed and expected sizes */

typedef struct kz2_edge_elem {
    uint32_t in, out, in_size, partial;   /* +0x00 +0x04 +0x08 +0x0C */
    uint32_t counter_mode;                /* +0x10: work-to-do counter EA | mode (bit 0) */
    uint32_t event_flag;                  /* +0x14 */
    uint16_t bits, skip_begin, skip_end;  /* +0x18 +0x1A +0x1C */
} kz2_edge_elem;

typedef struct kz2_edge_ops {
    void* user;
    const uint8_t* (*src)(void* user, uint32_t ea, uint32_t n);            /* n readable guest bytes, or NULL */
    int (*put)(void* user, uint32_t ea, const uint8_t* p, uint32_t n);      /* 0 = written (a DMA put) */
    uint32_t (*dec)(void* user, uint32_t ea);                               /* atomic BE u32 decrement, old value */
    int (*flag_set)(void* user, uint32_t ea, uint16_t bits);                /* cellSpursEventFlagSet */
} kz2_edge_ops;

enum kz2_edge_status {
    KZ2_EDGE_DONE = 0,          /* data written, completion done */
    KZ2_EDGE_FB_ARGS,           /* sizes, mode or alignment outside what the task accepts: the lifted path asserts */
    KZ2_EDGE_FB_SRC,            /* the input is not readable guest memory */
    KZ2_EDGE_FB_INFLATE,        /* inflate error, or output size != expected (the task errors too) */
    KZ2_EDGE_FB_COPY,           /* mode 0 with inSize != expected (the task errors too) */
    KZ2_EDGE_FB_PUT,            /* the output is not writable guest memory */
    KZ2_EDGE_NSTATUS
};

typedef struct kz2_edge_result {
    uint32_t produced;          /* inflated bytes (mode 1) or copied bytes (mode 0) */
    uint32_t counter_old;       /* the counter's value before the decrement (0 if no counter) */
    int flag_set;               /* 1 if the event flag was set */
} kz2_edge_result;

/* Raw deflate (no zlib header) of src into dst; returns the bytes produced, or -1 unless the stream ends (final block)
 * within dlen bytes of output. zlib when built with KZ2_HAVE_ZLIB, else stb_image's decoder (linked in the runtime). */
int kz2_edge_inflate_raw(uint8_t* dst, uint32_t dlen, const uint8_t* src, uint32_t slen);
const char* kz2_edge_backend(void);

/* Reads the 32-byte big-endian element at p. */
void kz2_edge_parse(const uint8_t p[32], kz2_edge_elem* e);

/* Runs one element: validate, inflate or copy into scratch (KZ2_EDGE_MAX bytes), put the window, then the completion
 * (decrement, then the flag), in the task's order. A status other than KZ2_EDGE_DONE means nothing was written and
 * nothing completed: the caller pushes the element to the task instead. */
int kz2_edge_run(const kz2_edge_elem* e, const kz2_edge_ops* ops, uint8_t* scratch, kz2_edge_result* r);

#ifdef __cplusplus
}
#endif
#endif
