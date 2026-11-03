/* harness_mfc.h -- the MFC model of the native-gate diff harness (tools/spu/native_diff_harness.c).
 *
 * A gated routine that issues its own DMA (Particles.VertexJob's vertex emitter @0x50F8: a put of a full 16 KB
 * buffer, then a tag wait on the other buffer) must issue the same MFC commands natively as the lifted and the
 * interpreted code do, in the same order, with the same arguments, and the put must take the same bytes from the
 * local store. Each side of a case gets one log: every MFC channel write and read in order (channel, value: the
 * preferred word, as the runtime's mfc_channel_write takes it), and per command the parameters it was issued with
 * (LSA, EAH, EAL, size, tag, command) and, for a put, a copy of the LS bytes it sends to main memory at the moment
 * of the command (the runtime's mfc_do_transfer copies synchronously, so that is what main memory receives).
 * hmfc_compare reports the first difference.
 *
 * The model is the runtime's synchronous MFC (runtime/spu/spu_dma.h mfc_channel_write / mfc_channel_read): every
 * command completes when it is issued, so MFC_WrTagUpdate (0 immediate, 1 any, 2 all) makes the tag status the tag
 * mask and MFC_RdTagStat returns it. Gets, lists and atomic commands are not modelled (hmfc_wrch returns -1: the
 * harness ends the run as an unmodelled channel, as before this model), nor are channels outside the MFC set
 * (0: not an MFC channel).
 * Host test: tools/spu/test_harness_mfc.sh (tools/spu/test_harness_mfc.c). */
#ifndef KZ2_HARNESS_MFC_H
#define KZ2_HARNESS_MFC_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* channel numbers (runtime/spu/spu_context.h) */
enum {
    HMFC_WrTagMask = 22, HMFC_WrTagUpdate = 23, HMFC_RdTagStat = 24, HMFC_RdTagMask = 12,
    HMFC_LSA = 16, HMFC_EAH = 17, HMFC_EAL = 18, HMFC_Size = 19, HMFC_TagID = 20, HMFC_Cmd = 21,
};

#define HMFC_MAX 64
#define HMFC_LS_SIZE 0x40000u

typedef struct {
    uint32_t ch, v;   /* channel, preferred word written (or read) */
    int rd;           /* 1: a read */
    uint32_t lsa, eah, eal, size, tag;   /* a command's parameters */
    uint8_t* data;    /* a put's bytes (malloc'd), else NULL */
} hmfc_ev;

typedef struct {
    hmfc_ev ev[HMFC_MAX];
    int n, overflow;
    uint32_t lsa, eah, eal, size, tag, mask, stat;
} hmfc_log;

static inline void hmfc_reset(hmfc_log* l)
{
    for (int i = 0; i < l->n && i < HMFC_MAX; i++) free(l->ev[i].data);
    memset(l, 0, sizeof *l);
}

static inline hmfc_ev* hmfc_add(hmfc_log* l, uint32_t ch, uint32_t v, int rd)
{
    if (l->n >= HMFC_MAX) { l->overflow = 1; l->n++; return NULL; }
    hmfc_ev* e = &l->ev[l->n++];
    memset(e, 0, sizeof *e);
    e->ch = ch;
    e->v = v;
    e->rd = rd;
    return e;
}

static inline int hmfc_is_put(uint32_t cmd)   /* PUT, PUTB, PUTF (0x20-0x22) and the R/S variants (0x28-0x2E even) */
{
    cmd &= 0xFF;
    return cmd == 0x20 || cmd == 0x21 || cmd == 0x22 || cmd == 0x28 || cmd == 0x29 || cmd == 0x2A;
}

/* A channel write. Returns 1 (handled), 0 (not an MFC channel) or -1 (an MFC command the model does not cover). */
static inline int hmfc_wrch(hmfc_log* l, const uint8_t* ls, uint32_t ch, uint32_t v)
{
    switch (ch) {
    case HMFC_LSA: l->lsa = v; break;
    case HMFC_EAH: l->eah = v; break;
    case HMFC_EAL: l->eal = v; break;
    case HMFC_Size: l->size = v; break;
    case HMFC_TagID: l->tag = v & 0x1F; break;
    case HMFC_WrTagMask: l->mask = v; break;
    case HMFC_WrTagUpdate: l->stat = l->mask; break;   /* synchronous: every tag group is complete */
    case HMFC_Cmd: {
        if (!hmfc_is_put(v)) return -1;
        hmfc_ev* e = hmfc_add(l, ch, v, 0);
        if (!e) return 1;
        e->lsa = l->lsa; e->eah = l->eah; e->eal = l->eal; e->size = l->size; e->tag = l->tag;
        const uint32_t n = l->size & 0x7FFF;   /* the runtime: up to 16 KB per command */
        if (n) {
            e->data = (uint8_t*)malloc(n);
            const uint32_t a = l->lsa & (HMFC_LS_SIZE - 1);
            if (a + n <= HMFC_LS_SIZE) memcpy(e->data, ls + a, n);
            else for (uint32_t i = 0; i < n; i++) e->data[i] = ls[(a + i) & (HMFC_LS_SIZE - 1)];
        }
        return 1;
    }
    default: return 0;
    }
    hmfc_add(l, ch, v, 0);
    return 1;
}

/* A channel read: 1 and *v (handled) or 0 (not modelled). */
static inline int hmfc_rdch(hmfc_log* l, uint32_t ch, uint32_t* v)
{
    switch (ch) {
    case HMFC_RdTagStat: *v = l->stat; break;
    case HMFC_RdTagMask: *v = l->mask; break;
    default: return 0;
    }
    hmfc_add(l, ch, *v, 1);
    return 1;
}

/* 0 when the two logs are the same (every event, every put's parameters and bytes); else 1 and the first
 * difference in diff. */
static inline int hmfc_compare(const hmfc_log* a, const hmfc_log* b, char* diff, size_t dn)
{
    if (a->overflow || b->overflow) { snprintf(diff, dn, "mfc log overflow (%d / %d events)", a->n, b->n); return 1; }
    const int n = a->n < b->n ? a->n : b->n;
    for (int i = 0; i < n; i++) {
        const hmfc_ev *x = &a->ev[i], *y = &b->ev[i];
        if (x->ch != y->ch || x->v != y->v || x->rd != y->rd) {
            snprintf(diff, dn, "mfc event %d: %s ch %u = 0x%X vs %s ch %u = 0x%X", i, x->rd ? "rdch" : "wrch", x->ch,
                     x->v, y->rd ? "rdch" : "wrch", y->ch, y->v);
            return 1;
        }
        if (x->ch == HMFC_Cmd && !x->rd) {
            if (x->lsa != y->lsa || x->eah != y->eah || x->eal != y->eal || x->size != y->size || x->tag != y->tag) {
                snprintf(diff, dn, "mfc put %d: lsa 0x%X ea 0x%X:%08X size 0x%X tag %u vs lsa 0x%X ea 0x%X:%08X "
                         "size 0x%X tag %u", i, x->lsa, x->eah, x->eal, x->size, x->tag, y->lsa, y->eah, y->eal,
                         y->size, y->tag);
                return 1;
            }
            const uint32_t m = x->size & 0x7FFF;
            for (uint32_t k = 0; k < m; k++)
                if (x->data[k] != y->data[k]) {
                    snprintf(diff, dn, "mfc put %d: byte 0x%X (LS 0x%05X, EA 0x%08X) 0x%02X vs 0x%02X", i, k,
                             (x->lsa + k) & (HMFC_LS_SIZE - 1), x->eal + k, x->data[k], y->data[k]);
                    return 1;
                }
        }
    }
    if (a->n != b->n) { snprintf(diff, dn, "mfc events: %d vs %d", a->n, b->n); return 1; }
    return 0;
}

/* Puts in a log (the harness reports them per case). */
static inline int hmfc_puts(const hmfc_log* l)
{
    int p = 0;
    for (int i = 0; i < l->n && i < HMFC_MAX; i++) p += l->ev[i].ch == HMFC_Cmd && !l->ev[i].rd;
    return p;
}

#endif
