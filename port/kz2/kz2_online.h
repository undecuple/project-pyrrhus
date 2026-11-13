/* kz2_online.h: the online settings files read before main() (kz2_online.cpp; an earlier change, D56). */
#ifndef KZ2_ONLINE_H
#define KZ2_ONLINE_H

typedef enum {
    KZ2_ONLINE_OFF = 0,        /* no method enabled (or re-psn without a valid server): offline */
    KZ2_ONLINE_REPSN = 1,      /* re-psn: the runtime's switch on, network policy strict with nothing allowed */
    KZ2_ONLINE_COMMUNITY = 2,  /* a community server chosen: offline in this build (no route yet) */
    KZ2_ONLINE_REFUSED = 3,    /* both methods enabled: refused, offline */
    KZ2_ONLINE_ENV = 4,        /* online variables in the environment: the files were not applied */
    KZ2_ONLINE_LISTEN = 5      /* KZ2_NET_LISTEN diagnostic: lobby host -> 127.0.0.1, only loopback allowed */
} kz2_online_state;

#ifdef __cplusplus
extern "C" {
#endif
kz2_online_state kz2_online_current(void);   /* the decision made before main() */
void kz2_online_log_replay(void);           /* prints the kept [online] lines once; main() calls it after the session log starts */
#ifdef __cplusplus
}

#include <functional>
#include <string>
namespace kz2_online { typedef kz2_online_state State; }
/* Private developer diagnostics of the listener mode (kz2_online_diag.cpp: compiled, with KZ2_ONLINE_DIAG defined for
 * kz2_online.cpp, only when the file is present; the public tree has none). Called once by the reader after the
 * KZ2_NET_LISTEN decision; np_started: the listener mode np started. */
void kz2_online_diag_np(const std::function<const char*(const char*)>& get,
                        const std::function<void(const std::string&)>& log, bool np_started);
#endif
#endif
