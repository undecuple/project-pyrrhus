/* Killzone 2 port, KZ2_NATIVE_ZLIB: the Edge zlib inflate job on the host.
 * See kz2_edge_zlib.h for what the SPU task does and where it was read. */
#include "kz2_edge_zlib.h"

#include <string.h>

#ifdef KZ2_HAVE_ZLIB
#include <zlib.h>

int kz2_edge_inflate_raw(uint8_t* dst, uint32_t dlen, const uint8_t* src, uint32_t slen)
{
    /* One stream per thread, reset per block: inflateInit2 allocates the 32 KiB window. */
    static _Thread_local z_stream zs;
    static _Thread_local int ready;
    if (!ready) {
        memset(&zs, 0, sizeof zs);
        if (inflateInit2(&zs, -15) != Z_OK) return -1;   /* raw deflate, 32 KiB window, as Edge's mode 1 */
        ready = 1;
    } else if (inflateReset(&zs) != Z_OK) {
        return -1;
    }
    zs.next_in = (Bytef*)src;
    zs.avail_in = slen;
    zs.next_out = dst;
    zs.avail_out = dlen;
    const int ret = inflate(&zs, Z_FINISH);
    if (ret != Z_STREAM_END) return -1;
    return (int)zs.total_out;
}

const char* kz2_edge_backend(void) { return "zlib " ZLIB_VERSION; }

#else
/* stb_image's zlib decoder (STB_IMAGE_IMPLEMENTATION is in the runtime's libs/codec/cellPngDec.c; public domain / MIT).
 * Fixed output buffer: decoding past dlen fails; returns the bytes produced once the final block is decoded. */
extern int stbi_zlib_decode_noheader_buffer(char* obuffer, int olen, const char* ibuffer, int ilen);

int kz2_edge_inflate_raw(uint8_t* dst, uint32_t dlen, const uint8_t* src, uint32_t slen)
{
    return stbi_zlib_decode_noheader_buffer((char*)dst, (int)dlen, (const char*)src, (int)slen);
}

const char* kz2_edge_backend(void) { return "stb_image"; }
#endif

static uint32_t be32(const uint8_t* p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }
static uint16_t be16(const uint8_t* p) { return (uint16_t)(p[0] << 8 | p[1]); }

void kz2_edge_parse(const uint8_t p[32], kz2_edge_elem* e)
{
    e->in = be32(p + 0x00);
    e->out = be32(p + 0x04);
    e->in_size = be32(p + 0x08);
    e->partial = be32(p + 0x0C);
    e->counter_mode = be32(p + 0x10);
    e->event_flag = be32(p + 0x14);
    e->bits = be16(p + 0x18);
    e->skip_begin = be16(p + 0x1A);
    e->skip_end = be16(p + 0x1C);
}

int kz2_edge_run(const kz2_edge_elem* e, const kz2_edge_ops* ops, uint8_t* scratch, kz2_edge_result* r)
{
    r->produced = 0;
    r->counter_old = 0;
    r->flag_set = 0;
    const uint64_t expected = (uint64_t)e->skip_begin + e->partial + e->skip_end;
    const uint32_t mode = e->counter_mode & 1u;
    const uint32_t counter = e->counter_mode & ~1u;   /* the task masks bit 0 only (andi -2) */
    /* The add-element function's asserts (1.29 0x3C8BA0) and the task's checks: outside them the lifted path runs. */
    if (e->in_size > KZ2_EDGE_MAX || expected > KZ2_EDGE_MAX || (counter & 3u)) return KZ2_EDGE_FB_ARGS;
    if (counter) {   /* edgeZlibAddInflateQueueElement asserts a non-zero counter before the push */
        const uint8_t* c = ops->src(ops->user, counter, 4);
        if (!c) return KZ2_EDGE_FB_SRC;
        if (be32(c) == 0) return KZ2_EDGE_FB_ARGS;
    }
    const uint8_t* in = e->in_size ? ops->src(ops->user, e->in, e->in_size) : scratch;
    if (!in) return KZ2_EDGE_FB_SRC;

    const uint8_t* data;
    if (mode) {
        const int n = kz2_edge_inflate_raw(scratch, (uint32_t)expected, in, e->in_size);
        if (n < 0 || (uint64_t)n != expected) return KZ2_EDGE_FB_INFLATE;
        r->produced = (uint32_t)n;
        data = scratch;
    } else {
        if ((uint64_t)e->in_size != expected) return KZ2_EDGE_FB_COPY;
        if (e->in_size) memcpy(scratch, in, e->in_size);   /* the task copies through its LS: in and out may overlap */
        r->produced = e->in_size;
        data = scratch;
    }
    /* The task's order: the window, then the counter, then the flag. */
    if (e->partial && ops->put(ops->user, e->out, data + e->skip_begin, e->partial)) return KZ2_EDGE_FB_PUT;
    int set = 1;
    if (counter) {
        r->counter_old = ops->dec(ops->user, counter);
        set = (r->counter_old == 1u);   /* old 0: the task prints "already at zero" and sets nothing */
    }
    if (set && e->event_flag) {
        ops->flag_set(ops->user, e->event_flag, e->bits);
        r->flag_set = 1;
    }
    return KZ2_EDGE_DONE;
}
