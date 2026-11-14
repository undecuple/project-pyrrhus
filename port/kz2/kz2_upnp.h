/* kz2_upnp.h: Killzone 2's UPnP gateway search answered "no gateway" at the source (2026-11-11:
 * "report it unavailable at the source").
 *
 * The game carries its own UPnP client (in the Medius/DME network code; strings at 1.29 0xC4B1E8..0xC4B908:
 * "M-SEARCH * HTTP/1.1 ... ssdp:discover", 239.255.255.250, WANIPConnection, AddPortMapping, GetExternalIPAddress).
 * KZ2 imports no cellNetCtlGetNatInfo (0x3A12865F; its eight cellNetCtl imports checked against analysis-129), so the
 * NAT question never goes to the system: the game asks the network itself. Static reading (1.29 addresses; v1.01 is
 * the same code 0xD880 lower, matched by tools/re/sigmatch.py with 600 fixed bytes):
 *
 *   search start @0x00767B78 (v1.01 @0x0075A2F8) (obj r3, service type r4, result callback r5):
 *     obj == 0 or callback == 0 -> 2; obj+0x1C != 0 (a search running) -> 0xD6DA; 0x765DA8 (allocates the
 *     0x2E78-byte work area at obj+0x38 when missing) fails -> 0x64;
 *     *CACHE != 0 (a finished search cached) -> no send, the cached result is delivered; else: the M-SEARCH text for
 *     the type (0x1000 WANIPConnection:1, 0x800 WANPPPConnection:1, 0x40
 *     WANCommonInterfaceConfig:1, 0x20 Layer3Forwarding:1), a UDP socket bound to port 1900,
 *     sendto 239.255.255.250:1900, then obj+0x1C = 1 (waiting), timer at obj->+0x38->+0x14, -> 0.
 *   waiting (update @0x0076841C, sub-state 1 @0x00768BD8): recvfrom; nothing after 0x1F4 = 500 ticks of the timer 0x702098 (ASSUMPTION: ms) (loc 0x00769700) ->
 *     error 0xD6D9, CACHE+0x1324 = 0xD6D9, *CACHE = 1, the socket closed, the callback (obj->+0x38->+0x2054) called
 *     with (obj, 0xD6D9, type).
 *   callback @0x00765988 (v1.01 @0x00758108): error with type 0x1000 -> *CACHE = 0, state 2, +0x2040 = 1 (try
 *     WANPPPConnection); error with type 0x800 -> *CACHE = 0, state 9 with the error; success -> state 3.
 *   the step @0x00767EB0: state 2 calls the search start; a nonzero return -> state 9 with that code; state 9 ->
 *     state 0, obj+0x1C = 0x12, the owner's callback (obj+0x40) with the code.
 *
 * So on a network without a UPnP gateway the game ends with state 9, code 0xD6D9 (two 500 ms timeouts, two sends to
 * 239.255.255.250:1900). Under the port's network policy that send is refused (an earlier change's listener run: one
 * "[net] refused UDP ...:1900" line). The answer here gives the game the same end state without any socket: the search
 * start returns 0xD6D9 (the step makes it state 9 with 0xD6D9, as after the second timeout) and CACHE+0x1324 holds
 * 0xD6D9 as the timeout path leaves it. *CACHE is not touched: it is 0 on this path, as both timeouts leave it.
 * The only differences: no WANPPPConnection retry and no 2 x 500 ms wait.
 * ASSUMPTION (not run: no Medius run in an earlier change): the game's own handling after state 9 is the one it already took
 * in an earlier change after the refused (dropped) send, the lobby TCP connect.
 *
 * KZ2_UPNP=search (diagnostic) runs the game's own search instead (the policy then refuses its send).
 * Pure functions only: the override is in kz2_ppu_overrides.cpp; host test tools/runtime/test_upnp_live_stop.sh. */
#ifndef KZ2_UPNP_H
#define KZ2_UPNP_H
#include <stdint.h>
#include <string.h>

#define KZ2_UPNP_ERR_TIMEOUT 0xD6D9u   /* the client's own "no answer in 500 ms" code (1.29 0x00769720) */
#define KZ2_UPNP_ERR_BUSY    0xD6DAu   /* a search is already running (1.29 0x00767BC4) */
#define KZ2_UPNP_CACHE_RESULT 0x1324u  /* CACHE + this: the last search's result (1.29 0x00768C98 stw r28,0x1324(r25)) */

typedef struct {
    uint32_t search;   /* the search start's address (the override's row) */
    uint32_t cache;    /* the result cache: *cache != 0 a finished search is cached; +0x1324 its result */
} kz2_upnp_site;

static const kz2_upnp_site kz2_upnp_site_129 = { 0x00767B78u, 0x01049348u };   /* TOC[-0x4C24] = 0x1049348 */
static const kz2_upnp_site kz2_upnp_site_101 = { 0x0075A2F8u, 0x01017548u };   /* TOC[-0x4CD4] = 0x1017548 */

enum { KZ2_UPNP_ANSWER = 0, KZ2_UPNP_SEARCH = 1 };

/* KZ2_UPNP: unset, "", "0", "off" -> answer (default); "search" -> the game's own search; anything else -> answer. */
static inline int kz2_upnp_mode_from(const char* v)
{
    return (v && !strcmp(v, "search")) ? KZ2_UPNP_SEARCH : KZ2_UPNP_ANSWER;
}

/* 1: answered, *r3 is the search start's return value and the cache result is written; 0: run the lifted body.
 * The lifted body runs where it sends nothing anyway (bad arguments, a search running, a cached result), so that
 * the game's own codes come back for those, and when the work area obj+0x38 is missing, so the game allocates it.
 * (The step that calls the search reads its state from that work area, so in play it always exists here.) */
static inline int kz2_upnp_search_answer(const kz2_upnp_site* site, uint32_t obj, uint32_t type, uint32_t callback,
                                         int mode, uint32_t (*rd32)(uint32_t), void (*wr32)(uint32_t, uint32_t),
                                         uint32_t* r3)
{
    (void)type;
    if (mode != KZ2_UPNP_ANSWER || !obj || !callback) return 0;
    if (rd32(obj + 0x1C) != 0) return 0;          /* KZ2_UPNP_ERR_BUSY from the lifted body */
    if (rd32(obj + 0x38) == 0) return 0;          /* no work area yet: 0x765DA8 allocates it (0x2E78 bytes) */
    if (rd32(site->cache) != 0) return 0;         /* the cached path: no send */
    wr32(site->cache + KZ2_UPNP_CACHE_RESULT, KZ2_UPNP_ERR_TIMEOUT);
    *r3 = KZ2_UPNP_ERR_TIMEOUT;
    return 1;
}

static inline const char* kz2_upnp_type_name(uint32_t type)
{
    switch (type) {
    case 0x1000: return "WANIPConnection";
    case 0x800: return "WANPPPConnection";
    case 0x40: return "WANCommonInterfaceConfig";
    case 0x20: return "Layer3Forwarding";
    default: return "other";
    }
}
#endif
