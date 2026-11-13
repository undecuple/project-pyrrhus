/* kz2_online.cpp: ENHANCEMENT (D56): the online settings files, read once before main().
 *
 * The player picks Off, re-psn or a community server in the launcher's Online settings window
 * (tools/release/online_dialog.py, which writes the files through tools/release/online_ini.py); this file reads the
 * same files in the game and sets the runtime's online state before anything asks for it. Design after jsp-vs-ex
 * PR #83 (Tsamiuy, "Online settings: launcher tab, game-side reader", MIT): two small ini files in a shared folder,
 * a reader that runs before main(), command line and environment over the files, untrusted input. Code written here.
 *
 * Files (untrusted input: 64 KB per file, 512 bytes per line, known sections and keys only, nothing executed):
 *   shared folder: PS3RECOMP_SHARED_DIR, else <install root>\shared when kz2-install.ini [install] portable=1
 *                  (beside the exe or one level up: the exe sits in <root>\build), else %APPDATA%\PS3Recomp.
 *                  Never created here.
 *     repsn.ini      [repsn] enabled = 0|1, server = host[:port] (port 36100 when left out), name = online ID
 *     community.ini  [community] enabled = 0|1, active = PRESET; [preset LABEL] address = host[:port], name = ...
 *   game folder: the install root when portable, else %APPDATA%\Project Pyrrhus (launch.py data_dir)
 *     repsn.ini      [repsn] p2p_port, comm_id, report_rtt (the game's own values; may also set enabled/server/name)
 * Shared first, then the game's own; a later key wins, presets merge by label. The files never mix: a [preset] or
 * [community] in repsn.ini, or a server/name key or [repsn] in community.ini, is rejected and logged.
 *
 * Order of strength: the command line (--psnr host[:port], --username NAME, after the EBOOT path), then the
 * environment (KZ3_ONLINE on, read as the runtime reads it, or PSNR_SERVER set; PS3_NP_ONLINE_ID, PS3_NET_P2P_PORT:
 * a developer run keeps exactly today's behaviour; PS3_NET_ONLINE is not this runtime's switch and is ignored), then
 * the files. An invalid --psnr is ignored and the environment and files decide.
 *
 * What each method does in this build (an earlier change analysis, report "An earlier change"):
 *   off        nothing changes: the runtime's online switch stays off, no real socket exists.
 *   re-psn     the switch on (ps3_net_set_online, patch 4001; KZ2's runtime reads KZ3_ONLINE, not PS3_NET_ONLINE),
 *              PSNR_SERVER and PS3_NP_ONLINE_ID set, and the network policy in strict mode with no name and no
 *              address allowed: Killzone 2's own lobby client (Medius rt_msg_client 3.03.01 and SVO over cellHttp)
 *              resolves its own host itself, and with re-psn chosen nothing of the title may reach any other server
 *              (D56: with re-psn chosen, all of the title's online traffic goes to it). re-psn's own client connects
 *              outside sys_net (np_psnr). KZ2 imports neither sceNpMatching2 nor sceNpScore, which start that
 *              connection, so today re-psn mode brings no play: it is the switch and the fence, ready for the bridge.
 *   community  stays offline (logged): this build has no route to a community server yet.
 *   both on    refused, offline, an ERROR line; the launcher shows the same refusal before the start.
 * Every decision is one "[online]" line, kept until main() calls kz2_online_log_replay() after the session log
 * started, so the lines reach logs/kz2-*.log (with the user's folders redacted by its copy thread).
 */
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <map>
#include <string>
#include <vector>

#include "kz2_online.h"

namespace kz2_online {

struct Env {
    std::function<const char*(const char*)> get;
    std::function<void(const char*, const char*)> set;
    std::function<void(const char*)> unset;
    std::function<void(const std::string&)> log;
    std::function<void(int)> set_online;     /* ps3_net_set_online */
    std::function<void(int)> set_strict;     /* ps3_net_policy_set_strict */
    /* KZ2_NET_LISTEN only: ps3_net_policy_map_host, ps3_net_policy_allow, ps3_net_set_np_signed_in */
    std::function<int(const char*, const unsigned char*)> map_host;
    std::function<int(const unsigned char*, unsigned short, unsigned short, int)> allow;
    std::function<void(int)> np_signed_in;
};

struct Settings {
    int rep_enabled = 0;
    std::string server, name, comm_id, p2p_port, report_rtt;
    int com_enabled = 0;
    std::string active;
    std::map<std::string, std::map<std::string, std::string>> presets;   /* label -> {address, name} */
    int rejected = 0;
    int files = 0;
};

static const size_t kMaxFile = 64 * 1024, kMaxLine = 512;

static std::string trim(const std::string& s)
{
    size_t a = 0, b = s.size();
    while (a < b && (s[a] == ' ' || s[a] == '\t' || s[a] == '\r')) a++;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t' || s[b - 1] == '\r')) b--;
    return s.substr(a, b - a);
}

static std::string lower(std::string s)
{
    for (auto& c : s) if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
    return s;
}

static bool is_alpha(char c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); }
static bool is_digit(char c) { return c >= '0' && c <= '9'; }

/* A value as a log shows it: printable ASCII only, at most 64 bytes (the input is untrusted). */
static std::string shown(const std::string& v)
{
    std::string o;
    for (char c : v) {
        if (o.size() >= 64) { o += "..."; break; }
        o += (c >= 0x20 && c <= 0x7e) ? c : '?';
    }
    return o;
}

static std::string with_port(const std::string& s) { return s.find(':') == std::string::npos ? s + ":36100" : s; }

static bool valid_port(const std::string& p)
{
    if (p.empty() || p.size() > 5) return false;
    for (char c : p) if (!is_digit(c)) return false;
    int v = atoi(p.c_str());
    return v >= 1 && v <= 65535;
}

/* host[:port]: a host of letters, digits, '.', '-', '_' (at most 253; no IPv6 literal: re-psn's client is IPv4),
 * a port 1-65535. */
bool valid_hostport(const std::string& s)
{
    std::string host = s;
    size_t c = s.find(':');
    if (c != std::string::npos) {
        host = s.substr(0, c);
        if (!valid_port(s.substr(c + 1))) return false;
    }
    if (host.empty() || host.size() > 253 || host[0] == '.' || host[0] == '-') return false;
    for (char ch : host)
        if (!(is_alpha(ch) || is_digit(ch) || ch == '.' || ch == '-' || ch == '_')) return false;
    return true;
}

/* The online ID: 3-16 of A-Za-z0-9_-, starting with a letter (re-psn's desktop app; the toolkit's clean_online_id). */
bool valid_name(const std::string& n)
{
    if (n.size() < 3 || n.size() > 16 || !is_alpha(n[0])) return false;
    for (char c : n) if (!(is_alpha(c) || is_digit(c) || c == '_' || c == '-')) return false;
    return true;
}

/* A preset label: 1-32 of A-Za-z0-9_- (it is a section name and shows in the launcher's list). */
bool valid_label(const std::string& n)
{
    if (n.empty() || n.size() > 32) return false;
    for (char c : n) if (!(is_alpha(c) || is_digit(c) || c == '_' || c == '-')) return false;
    return true;
}

static bool valid_bool(const std::string& v) { return v == "0" || v == "1"; }

/* NPWR00153_00 shape: 9-12 of A-Z0-9_ (12 bytes on the wire). */
static bool valid_comm_id(const std::string& v)
{
    if (v.size() < 9 || v.size() > 12) return false;
    for (char c : v) if (!((c >= 'A' && c <= 'Z') || is_digit(c) || c == '_')) return false;
    return true;
}

/* 0: missing, 1: read, -1: there but refused (over 64 KB, unreadable). */
static int read_file(const std::string& path, std::string& out, const Env& env)
{
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return 0;
    std::vector<char> buf(kMaxFile + 1);
    size_t n = fread(buf.data(), 1, buf.size(), f);
    int err = ferror(f);
    fclose(f);
    if (err) { if (env.log) env.log("[online] " + path + ": could not be read, file ignored"); return -1; }
    if (n > kMaxFile) { if (env.log) env.log("[online] " + path + ": larger than 64 KB, file ignored"); return -1; }
    out.assign(buf.data(), n);
    return 1;
}

enum Kind { REPSN, COMMUNITY };

static void parse(const std::string& path, Kind kind, bool game, Settings& st, const Env& env)
{
    std::string text;
    int r = read_file(path, text, env);
    if (r == 0) return;
    if (r < 0) { st.rejected++; return; }
    st.files++;
    if (text.compare(0, 3, "\xEF\xBB\xBF") == 0) text.erase(0, 3);   /* a UTF-8 BOM (Notepad) */
    std::string preset;
    int sec = 0;    /* 0 none or unknown, 1 [repsn], 2 [community], 3 [preset LABEL] */
    int rej = 0;
    size_t pos = 0, lineno = 0;
    auto reject = [&](const std::string& why) {
        rej++; st.rejected++;
        env.log("[online] " + path + ":" + std::to_string(lineno) + ": rejected (" + why + ")");
    };
    while (pos < text.size()) {
        size_t e = text.find('\n', pos);
        if (e == std::string::npos) e = text.size();
        std::string raw = text.substr(pos, e - pos);
        pos = e + 1; lineno++;
        if (raw.size() > kMaxLine) { reject("line over 512 bytes"); continue; }
        if (raw.find('\0') != std::string::npos) { reject("NUL byte"); continue; }
        std::string l = trim(raw);
        if (l.empty() || l[0] == ';' || l[0] == '#') continue;
        if (l[0] == '[') {
            sec = 0;
            if (l.back() != ']') { reject("bad section line"); continue; }
            std::string s = trim(l.substr(1, l.size() - 2)), ls = lower(s);
            if (kind == REPSN && ls == "repsn") sec = 1;
            else if (kind == COMMUNITY && ls == "community") sec = 2;
            else if (ls.compare(0, 7, "preset ") == 0) {
                if (kind == REPSN) reject("[preset] in repsn.ini: presets belong in community.ini");
                else {
                    preset = trim(s.substr(7));
                    if (valid_label(preset)) sec = 3;
                    else reject("bad preset label, want 1-32 of A-Za-z0-9_-");
                }
            } else if (kind == REPSN && ls == "community") reject("[community] in repsn.ini");
            else if (kind == COMMUNITY && ls == "repsn") reject("[repsn] in community.ini");
            else reject("unknown section [" + shown(s) + "]");
            continue;
        }
        size_t eq = l.find('=');
        if (eq == std::string::npos) { reject("no '='"); continue; }
        std::string k = lower(trim(l.substr(0, eq))), v = trim(l.substr(eq + 1));
        if (sec == 0) { reject("key outside a known section"); continue; }
        if (sec == 1) {
            if (k == "enabled") { if (valid_bool(v)) st.rep_enabled = v == "1"; else reject("enabled must be 0 or 1"); }
            else if (k == "server") { if (valid_hostport(v)) st.server = with_port(v); else reject("bad server, want host[:port]"); }
            else if (k == "name") { if (valid_name(v)) st.name = v; else reject("bad name, want 3-16 of A-Za-z0-9_- starting with a letter"); }
            else if (game && k == "comm_id") { if (valid_comm_id(v)) st.comm_id = v; else reject("bad comm_id"); }
            else if (game && k == "p2p_port") { if (valid_port(v)) st.p2p_port = v; else reject("bad p2p_port"); }
            else if (game && k == "report_rtt") { if (valid_bool(v)) st.report_rtt = v; else reject("report_rtt must be 0 or 1"); }
            else reject("unknown key '" + shown(k) + "'");
        } else if (sec == 2) {
            if (k == "enabled") { if (valid_bool(v)) st.com_enabled = v == "1"; else reject("enabled must be 0 or 1"); }
            else if (k == "active") { if (v.empty() || valid_label(v)) st.active = v; else reject("bad active preset label"); }
            else if (k == "server") reject("re-psn key 'server' in community.ini");
            else reject("unknown key '" + shown(k) + "'");
        } else {
            if (k == "address") { if (valid_hostport(v)) st.presets[preset]["address"] = with_port(v); else reject("bad address, want host[:port]"); }
            else if (k == "name") { if (valid_name(v)) st.presets[preset]["name"] = v; else reject("bad name, want 3-16 of A-Za-z0-9_- starting with a letter"); }
            else reject("unknown key '" + shown(k) + "'");
        }
    }
    env.log("[online] " + path + ": read, " + std::to_string(rej) + " line(s) rejected");
}

static bool has(const Env& e, const char* n) { const char* v = e.get(n); return v && *v; }
/* A switch variable as the runtime's ps3_net_online() reads KZ3_ONLINE: set, non-empty and not "0". */
static bool on(const Env& e, const char* n) { const char* v = e.get(n); return v && *v && strcmp(v, "0") != 0; }

std::string join(const std::string& d, const char* f)
{
    if (d.empty()) return "";
    char last = d.back();
    const char* sep = d.find('\\') != std::string::npos ? "\\" : "/";   /* the folder's own separator */
    return d + ((last == '/' || last == '\\') ? "" : sep) + f;
}

/* The decision. The flags are the command line's --psnr / --username ("" when not given). */
/* KZ2_NET_LISTEN=1|np (Medius step 1; a developer diagnostic, off by default): the game's own lobby
 * client talks to a passive listener on this machine (tools/net/medius_listen.py) and nowhere else. The online
 * switch on, the policy strict, the lobby host (KZ2_NET_LISTEN_HOST, read from the EBOOT inside the sandbox by the
 * run recipe; never logged here) mapped to 127.0.0.1, only 127.0.0.1 allowed (every port, TCP and UDP), so the
 * policy's refusal log names any other destination the game tries. "np" also reports the NP manager signed in
 * (patch 4003), for a client that waits for it. Wins over the command line, the environment and the files. */
static const unsigned char kLoopback[4] = {127, 0, 0, 1};

static bool listen_mode(const Env& env, State& state)
{
    const char* m = env.get("KZ2_NET_LISTEN");
    if (!m || !*m || !strcmp(m, "0")) return false;
    state = KZ2_ONLINE_OFF;
    /* Every path below decides the runtime's state itself: the switch is set either way (ps3_net_set_online wins over
     * KZ3_ONLINE), the policy is strict either way, and PSNR_SERVER is removed so no re-psn connection can start. */
    if (has(env, "KZ3_ONLINE") || has(env, "PSNR_SERVER"))
        env.log("[online] KZ2_NET_LISTEN: KZ3_ONLINE / PSNR_SERVER in the environment are ignored");
    env.unset("PSNR_SERVER");
    auto fail = [&](const char* why) {
        env.set_online(0);
        env.set_strict(1);
        env.log(std::string("[online] KZ2_NET_LISTEN: ") + why + ": diagnostic not started, offline (switch off, policy strict)");
        return true;
    };
    const char* h = env.get("KZ2_NET_LISTEN_HOST");
    std::string host = h ? h : "";
    if (strcmp(m, "1") && strcmp(m, "np")) return fail("the mode must be 1 or np");
    if (host.empty() || host.find(':') != std::string::npos || !valid_hostport(host))
        return fail("KZ2_NET_LISTEN_HOST missing or not a host name");
    env.set_strict(1);
    if (env.map_host(host.c_str(), kLoopback) != 0) return fail("the network policy refused the host map");
    if (env.allow(kLoopback, 1, 65535, 3) != 0) return fail("the network policy refused the loopback allowlist");
    env.set_online(1);
    if (!strcmp(m, "np")) env.np_signed_in(1);
    state = KZ2_ONLINE_LISTEN;
    env.log("[online] KZ2_NET_LISTEN diagnostic: online switch on, policy strict, the lobby host (" +
            std::to_string(host.size()) + " characters) mapped to 127.0.0.1, only 127.0.0.1 allowed" +
            (strcmp(m, "np") ? "" : ", NP manager signed in") + "; the settings files, flags and variables are not applied");
    return true;
}

State apply(const Env& env, const std::string& shared_dir, const std::string& game_dir,
            const std::string& psnr_flag, const std::string& user_flag)
{
    {
        State ls = KZ2_ONLINE_OFF;
        const bool listened = listen_mode(env, ls);
#ifdef KZ2_ONLINE_DIAG   /* private diagnostics (kz2_online_diag.cpp; CMake defines this only when the file is there) */
        kz2_online_diag_np(env.get, env.log, ls == KZ2_ONLINE_LISTEN && !strcmp(env.get("KZ2_NET_LISTEN"), "np"));
#endif
        if (listened) return ls;
    }
    Settings st;
    if (!shared_dir.empty()) {
        parse(join(shared_dir, "repsn.ini"), REPSN, false, st, env);
        parse(join(shared_dir, "community.ini"), COMMUNITY, false, st, env);
    }
    if (!game_dir.empty()) parse(join(game_dir, "repsn.ini"), REPSN, true, st, env);
    if (!st.files) env.log("[online] no settings files (shared folder \"" + shared_dir + "\", game folder \"" + game_dir + "\")");

    State state = KZ2_ONLINE_OFF;
    /* The environment as the runtime reads it (patch 4001 ps3_net_online(): KZ3_ONLINE set, non-empty and not "0").
     * PSNR_SERVER alone is a developer's choice too (the files stay out); the runtime then stays offline. */
    bool env_switch = on(env, "KZ3_ONLINE");
    bool env_online = env_switch || has(env, "PSNR_SERVER");
    if (has(env, "PS3_NET_ONLINE") && !env_switch)
        env.log("[online] PS3_NET_ONLINE is not read by this runtime (its switch is KZ3_ONLINE): ignored");
    bool flag_ok = !psnr_flag.empty() && valid_hostport(psnr_flag);
    if (!psnr_flag.empty() && !flag_ok)
        env.log("[online] --psnr value is not host[:port], ignored");
    bool repsn_on = false;

    if (flag_ok) {
        env.set("PSNR_SERVER", with_port(psnr_flag).c_str());
        repsn_on = true;
        state = KZ2_ONLINE_REPSN;
        env.log("[online] --psnr " + shown(psnr_flag) + " given: re-psn, wins over the environment and the settings files");
    } else if (env_online) {
        state = KZ2_ONLINE_ENV;
        env.log(std::string("[online] online variables set in the environment: they win, the settings files are not "
                            "applied; the runtime is ") + (env_switch ? "online (KZ3_ONLINE)" : "offline (KZ3_ONLINE not on)"));
    } else if (st.rep_enabled && st.com_enabled) {
        state = KZ2_ONLINE_REFUSED;
        env.log("[online] ERROR: re-psn and a community server are both enabled; online play refused, staying "
                "offline. Pick one method in Online settings (repsn.ini [repsn] enabled, community.ini [community] enabled)");
    } else if (st.com_enabled) {
        state = KZ2_ONLINE_COMMUNITY;
        std::string a = st.active.empty() ? "(none)" : st.active;
        if (!st.active.empty() && !st.presets.count(st.active)) a += ", not defined";
        env.log("[online] community server chosen (preset " + shown(a) + "): this build has no route to a compatible "
                "server yet; staying offline");
    } else if (st.rep_enabled) {
        if (st.server.empty()) {
            env.log("[online] re-psn enabled but no valid server: staying offline");
        } else {
            env.set("PSNR_SERVER", st.server.c_str());
            repsn_on = true;
            state = KZ2_ONLINE_REPSN;
            env.log("[online] re-psn: server " + shown(st.server));
        }
    } else {
        env.log("[online] off");
    }

    if (repsn_on) {
        env.set("PS3_NET_ONLINE", "1");   /* the upstream form; KZ2's runtime takes the switch below */
        env.set_online(1);
        env.set_strict(1);
        env.log("[online] network policy strict, nothing allowed: the game's own lobby client reaches no server "
                "(re-psn carries the online traffic; it has no Killzone 2 lobby yet)");
        if (!user_flag.empty()) {
            if (valid_name(user_flag)) { env.set("PS3_NP_ONLINE_ID", user_flag.c_str()); env.log("[online] --username given: online ID " + user_flag); }
            else env.log("[online] --username value is not a valid online ID, ignored");
        } else if (has(env, "PS3_NP_ONLINE_ID")) {
            env.log("[online] PS3_NP_ONLINE_ID set in the environment: wins over name");
        } else if (!st.name.empty()) {
            env.set("PS3_NP_ONLINE_ID", st.name.c_str());
            env.log("[online] online ID " + st.name);
        } else {
            env.log("[online] no online ID set: the runtime uses PS3Player");
        }
        if (has(env, "PS3_NET_P2P_PORT")) {
            if (!st.p2p_port.empty()) env.log("[online] PS3_NET_P2P_PORT set in the environment: wins over p2p_port");
        } else if (!st.p2p_port.empty()) {
            env.set("PS3_NET_P2P_PORT", st.p2p_port.c_str());
            env.log("[online] peer port " + st.p2p_port);
        }
    }
    /* ASSUMPTION: no runtime reader exists for comm_id (the title passes its own, NPWR00153_00) or report_rtt. */
    if (!st.comm_id.empty() || !st.report_rtt.empty()) env.log("[online] comm_id / report_rtt read, not used by this build");
    if (st.rejected) env.log("[online] " + std::to_string(st.rejected) + " setting(s) rejected in total");
    return state;
}

/* [install] portable = 1 in an install ini (the first occurrence counts, as install_ini.py). */
bool portable_ini(const std::string& path)
{
    std::string t;
    Env quiet;
    quiet.log = [](const std::string&) {};
    if (read_file(path, t, quiet) != 1) return false;
    bool in = false;
    size_t pos = 0;
    while (pos < t.size()) {
        size_t e = t.find('\n', pos);
        if (e == std::string::npos) e = t.size();
        std::string l = trim(t.substr(pos, e - pos));
        pos = e + 1;
        if (l.compare(0, 3, "\xEF\xBB\xBF") == 0) l = trim(l.substr(3));
        if (!l.empty() && l[0] == '[') { in = lower(l) == "[install]"; continue; }
        size_t eq = l.find('=');
        if (in && eq != std::string::npos && lower(trim(l.substr(0, eq))) == "portable") return trim(l.substr(eq + 1)) == "1";
    }
    return false;
}

/* exe_dir: the exe's folder; appdata: %APPDATA% (may be empty). */
void resolve_dirs(const Env& env, const std::string& exe_dir, const std::string& appdata,
                  std::string& shared, std::string& game)
{
    std::string root = exe_dir;
    bool portable = !exe_dir.empty() && portable_ini(join(exe_dir, "kz2-install.ini"));
    if (!portable && !exe_dir.empty()) {
        size_t sl = exe_dir.find_last_of("\\/");
        if (sl != std::string::npos && sl > 0) {
            std::string up = exe_dir.substr(0, sl);
            if (portable_ini(join(up, "kz2-install.ini"))) { portable = true; root = up; }
        }
    }
    const char* ov = env.get("PS3RECOMP_SHARED_DIR");
    if (ov && *ov) shared = ov;
    else if (portable) shared = join(root, "shared");
    else shared = appdata.empty() ? "" : join(appdata, "PS3Recomp");
    game = portable ? root : (appdata.empty() ? "" : join(appdata, "Project Pyrrhus"));
}

/* --psnr / --username anywhere after argv[0], as "--psnr X" or "--psnr=X". */
void flags(int argc, char** argv, std::string& psnr, std::string& user)
{
    for (int i = 1; i < argc; i++) {
        if (!argv[i]) continue;
        std::string a = argv[i];
        std::string* dst = nullptr;
        size_t n = 0;
        if (a == "--psnr" || a.compare(0, 7, "--psnr=") == 0) { dst = &psnr; n = 6; }
        else if (a == "--username" || a.compare(0, 11, "--username=") == 0) { dst = &user; n = 10; }
        if (!dst) continue;
        if (a.size() > n) *dst = a.substr(n + 1);
        else if (i + 1 < argc && argv[i + 1]) *dst = argv[++i];
        if (dst->size() > 300) dst->clear();
    }
}

}  // namespace kz2_online

#ifndef KZ2_ONLINE_TEST
#ifdef _WIN32
#include <windows.h>
#include <stdlib.h>
#endif
#include "../../libs/network/net_policy.h"   /* ps3_net_set_online, ps3_net_policy_set_strict (patch 4001) */

static std::vector<std::string>* s_lines;   /* until kz2_online_log_replay */
static kz2_online_state s_state = KZ2_ONLINE_OFF;

static void kz2_online_boot(void)
{
    using namespace kz2_online;
    static std::vector<std::string> lines;
    s_lines = &lines;
    Env env;
    env.get = [](const char* n) { return getenv(n); };
    env.set = [](const char* k, const char* v) {
#ifdef _WIN32
        _putenv_s(k, v);
#else
        setenv(k, v, 1);
#endif
    };
    env.log = [](const std::string& s) { if (s_lines) s_lines->push_back(s); };
    env.unset = [](const char* k) {
#ifdef _WIN32
        _putenv_s(k, "");   /* an empty value removes the variable (MSVCRT/UCRT) */
#else
        unsetenv(k);
#endif
    };
    env.set_online = [](int on) { ps3_net_set_online(on); };
    env.set_strict = [](int on) { ps3_net_policy_set_strict(on); };
    env.map_host = [](const char* n, const unsigned char* ip) { return ps3_net_policy_map_host(n, ip); };
    env.allow = [](const unsigned char* ip, unsigned short lo, unsigned short hi, int protos) {
        return ps3_net_policy_allow(ip, lo, hi, protos);
    };
    env.np_signed_in = [](int on) { ps3_net_set_np_signed_in(on); };
    std::string exe_dir, appdata, psnr, user;
#ifdef _WIN32
    char p[MAX_PATH * 2];
    DWORD n = GetModuleFileNameA(NULL, p, sizeof p);
    if (n && n < sizeof p) {
        exe_dir.assign(p, n);
        size_t s = exe_dir.find_last_of("\\/");
        exe_dir = s == std::string::npos ? "" : exe_dir.substr(0, s);
    }
    if (const char* a = getenv("APPDATA")) appdata = a;
    flags(__argc, __argv, psnr, user);
#endif
    std::string shared, game;
    resolve_dirs(env, exe_dir, appdata, shared, game);
    s_state = apply(env, shared, game, psnr, user);
}

namespace { struct Kz2OnlineInit { Kz2OnlineInit() { kz2_online_boot(); } } s_kz2_online_init; }

extern "C" kz2_online_state kz2_online_current(void) { return s_state; }

extern "C" void kz2_online_log_replay(void)
{
    if (!s_lines) return;
    for (const auto& l : *s_lines) printf("%s\n", l.c_str());
    fflush(stdout);
    s_lines->clear();
}
#endif
