/* test_online_reader.cpp: host test of port/kz2/kz2_online.cpp (D56), built on its own with
 * KZ2_ONLINE_TEST (no runtime, no network). Files go in a temporary tree; hosts are example.invalid, 192.0.2.x and
 * 127.0.0.1 only. Run through test_online_reader.sh. Prints "ok N" per check, "FAIL ..." and exit 1 on a failure. */
#define KZ2_ONLINE_TEST 1
#include "../../port/kz2/kz2_online.cpp"

#include <sys/stat.h>
#include <unistd.h>

using namespace kz2_online;

static int fails, checks;
#define CHECK(c, what) do { checks++; if (!(c)) { fails++; printf("FAIL %s (line %d)\n", what, __LINE__); } \
                            else printf("ok %d %s\n", checks, what); } while (0)

struct Fake {
    std::map<std::string, std::string> vars;
    std::vector<std::string> log;
    int online = 0, strict = 0, np = 0, map_fail = 0, allow_fail = 0;
    std::vector<int> online_calls;
    std::vector<std::string> maps, allows;
    Env env()
    {
        Env e;
        e.get = [this](const char* n) -> const char* { auto it = vars.find(n); return it == vars.end() ? nullptr : it->second.c_str(); };
        e.set = [this](const char* k, const char* v) { vars[k] = v; };
        e.unset = [this](const char* k) { vars.erase(k); };
        e.log = [this](const std::string& s) { log.push_back(s); };
        e.set_online = [this](int on) { online = on; online_calls.push_back(on); };
        e.set_strict = [this](int on) { strict = on; };
        e.map_host = [this](const char* n, const unsigned char* ip) {
            if (map_fail) return -1;
            maps.push_back(std::string(n) + "=" + std::to_string(ip[0]) + "." + std::to_string(ip[1]) + "." +
                           std::to_string(ip[2]) + "." + std::to_string(ip[3]));
            return 0;
        };
        e.allow = [this](const unsigned char* ip, unsigned short lo, unsigned short hi, int protos) {
            if (allow_fail) return -1;
            allows.push_back(std::to_string(ip[0]) + "." + std::to_string(ip[1]) + "." + std::to_string(ip[2]) + "." +
                             std::to_string(ip[3]) + ":" + std::to_string(lo) + "-" + std::to_string(hi) + "/" +
                             std::to_string(protos));
            return 0;
        };
        e.np_signed_in = [this](int on) { np = on; };
        return e;
    }
    bool logged(const char* part) const { for (auto& l : log) if (l.find(part) != std::string::npos) return true; return false; }
    std::string var(const char* k) const { auto it = vars.find(k); return it == vars.end() ? "" : it->second; }
};

static std::string g_root;
static void put(const std::string& rel, const std::string& text)
{
    std::string p = g_root + "/" + rel;
    FILE* f = fopen(p.c_str(), "wb");
    if (!f) { printf("FAIL cannot write %s\n", p.c_str()); exit(1); }
    fwrite(text.data(), 1, text.size(), f);
    fclose(f);
}
static void clear()
{
    for (const char* r : {"shared/repsn.ini", "shared/community.ini", "game/repsn.ini"}) unlink((g_root + "/" + r).c_str());
}
static State run(Fake& f, const std::string& psnr = "", const std::string& user = "")
{
    return apply(f.env(), g_root + "/shared", g_root + "/game", psnr, user);
}

int main(int argc, char** argv)
{
    if (argc == 4 && !strcmp(argv[1], "--decide")) {   /* test_online_ini.py: the decision for SHARED GAME, as a number */
        Fake f;
        printf("%d\n", (int)apply(f.env(), argv[2], argv[3], "", ""));
        return 0;
    }
    if (argc < 2) { printf("usage: %s TMPDIR | --decide SHARED GAME\n", argv[0]); return 2; }
    g_root = argv[1];
    mkdir((g_root + "/shared").c_str(), 0755);
    mkdir((g_root + "/game").c_str(), 0755);
    mkdir((g_root + "/inst").c_str(), 0755);
    mkdir((g_root + "/inst/build").c_str(), 0755);

    { Fake f; clear(); State s = run(f);
      CHECK(s == KZ2_ONLINE_OFF && f.vars.empty() && !f.online && !f.strict, "no files: off, nothing set");
      CHECK(f.logged("no settings files"), "no files: logged"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\nname = Rico_Velasquez\n");
      State s = run(f);
      CHECK(s == KZ2_ONLINE_REPSN, "re-psn: state");
      CHECK(f.var("PSNR_SERVER") == "127.0.0.1:36100", "re-psn: default port 36100");
      CHECK(f.online == 1 && f.strict == 1, "re-psn: switch on and policy strict");
      CHECK(f.var("PS3_NP_ONLINE_ID") == "Rico_Velasquez", "re-psn: online ID from the file");
      CHECK(f.var("PS3_NET_ONLINE") == "1", "re-psn: upstream variable too"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 192.0.2.7:36200\n");
      put("shared/community.ini", "[community]\nenabled = 1\nactive = mine\n[preset mine]\naddress = 192.0.2.8\nname = Sev\n");
      State s = run(f);
      CHECK(s == KZ2_ONLINE_REFUSED && f.vars.empty() && !f.online, "both enabled: refused, nothing set");
      CHECK(f.logged("ERROR: re-psn and a community server are both enabled"), "both enabled: clear message"); }

    { Fake f; clear(); put("shared/community.ini", "; comment\n[community]\nenabled = 1\nactive = mine\n[preset mine]\naddress = example.invalid:10075\nname = Natko\n");
      State s = run(f);
      CHECK(s == KZ2_ONLINE_COMMUNITY && f.vars.empty() && !f.online && !f.strict, "community: offline, nothing set");
      CHECK(f.logged("staying offline") && f.logged("preset mine"), "community: says it stays offline"); }

    { Fake f; clear(); put("shared/community.ini", "[community]\nenabled = 1\nactive = ghost\n");
      run(f); CHECK(f.logged("ghost, not defined"), "community: an undefined active preset is named"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n");
      f.vars["PSNR_SERVER"] = "127.0.0.2:1"; State s = run(f);
      CHECK(s == KZ2_ONLINE_ENV && f.var("PSNR_SERVER") == "127.0.0.2:1" && !f.online && !f.strict, "environment wins over the files"); }

    { Fake f; clear(); f.vars["KZ3_ONLINE"] = "1"; put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n");
      CHECK(run(f) == KZ2_ONLINE_ENV && !f.vars.count("PSNR_SERVER"), "KZ3_ONLINE in the environment: files not applied"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 192.0.2.7\nname = Filefile\n");
      put("shared/community.ini", "[community]\nenabled = 1\n");
      State s = run(f, "127.0.0.1:36101", "Flagname");
      CHECK(s == KZ2_ONLINE_REPSN && f.var("PSNR_SERVER") == "127.0.0.1:36101", "--psnr wins over the files (both on there)");
      CHECK(f.var("PS3_NP_ONLINE_ID") == "Flagname", "--username wins over name"); }

    { Fake f; clear(); State s = run(f, "127.0.0.1;calc.exe");
      CHECK(s == KZ2_ONLINE_OFF && f.vars.empty() && f.logged("not host[:port]"), "a bad --psnr is ignored"); }

    /* review an earlier change: an invalid --psnr falls through; the switch read as the runtime reads it */
    { Fake f; clear(); f.vars["KZ3_ONLINE"] = "1"; put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n");
      State s = run(f, "bad host!");
      CHECK(s == KZ2_ONLINE_ENV && !f.vars.count("PSNR_SERVER") && !f.strict && f.logged("ignored")
            && f.logged("the runtime is online (KZ3_ONLINE)"), "invalid --psnr + KZ3_ONLINE=1: the environment decides, log says online"); }
    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n");
      CHECK(run(f, "bad host!") == KZ2_ONLINE_REPSN && f.strict, "invalid --psnr without environment: the files decide"); }
    { Fake f; clear(); f.vars["KZ3_ONLINE"] = "0"; put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n");
      CHECK(run(f) == KZ2_ONLINE_REPSN, "KZ3_ONLINE=0 is off, as the runtime reads it: the files apply"); }
    { Fake f; clear(); f.vars["PS3_NET_ONLINE"] = "1"; put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n");
      CHECK(run(f) == KZ2_ONLINE_REPSN && f.logged("PS3_NET_ONLINE is not read"), "PS3_NET_ONLINE alone: ignored and said, the files apply"); }
    { Fake f; clear(); f.vars["PS3_NET_ONLINE"] = "0";
      CHECK(run(f) == KZ2_ONLINE_OFF && !f.online, "PS3_NET_ONLINE=0 alone, no files: off"); }
    { Fake f; clear(); f.vars["KZ3_ONLINE"] = "1"; f.vars["PSNR_SERVER"] = "192.0.2.3:1";
      State s = run(f, "127.0.0.1:36103");
      CHECK(s == KZ2_ONLINE_REPSN && f.var("PSNR_SERVER") == "127.0.0.1:36103" && f.strict, "--psnr wins over the environment"); }
    { Fake f; clear(); f.vars["PSNR_SERVER"] = "127.0.0.2:1"; run(f);
      CHECK(f.logged("the runtime is offline (KZ3_ONLINE not on)"), "PSNR_SERVER alone: the log says the runtime stays offline"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\nname = Filefile\n");
      f.vars["PS3_NP_ONLINE_ID"] = "Envname"; run(f);
      CHECK(f.var("PS3_NP_ONLINE_ID") == "Envname", "PS3_NP_ONLINE_ID wins over name"); }

    { Fake f; clear(); std::string big = "[repsn]\nenabled = 1\nserver = 127.0.0.1\n";
      big += std::string(64 * 1024 - big.size(), '\n'); put("shared/repsn.ini", big);
      CHECK(run(f) == KZ2_ONLINE_REPSN, "a file of exactly 64 KB is read");
      Fake g; big += "\n"; put("shared/repsn.ini", big);
      CHECK(run(g) == KZ2_ONLINE_OFF && g.logged("larger than 64 KB"), "a file over 64 KB is ignored whole"); }

    { Fake f; clear(); std::string l512 = "server = 127.0.0.1" + std::string(512 - 18, ' ');
      put("shared/repsn.ini", "[repsn]\nenabled = 1\n" + l512 + "\n");
      CHECK(run(f) == KZ2_ONLINE_REPSN, "a 512-byte line is read");
      Fake g; put("shared/repsn.ini", "[repsn]\nenabled = 1\n" + l512 + " \n");
      CHECK(run(g) == KZ2_ONLINE_OFF && g.logged("line over 512 bytes"), "a 513-byte line is rejected"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\nrelay = 1\nexec = calc.exe\n");
      run(f); CHECK(f.logged("unknown key 'relay'") && f.logged("unknown key 'exec'") && f.logged("2 setting(s) rejected"), "unknown keys rejected and counted"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n[preset x]\naddress = 192.0.2.1\n[community]\nenabled = 1\n");
      State s = run(f);
      CHECK(s == KZ2_ONLINE_REPSN && f.logged("[preset] in repsn.ini") && f.logged("[community] in repsn.ini"), "repsn.ini: community sections rejected (files never mix)"); }

    { Fake f; clear(); put("shared/community.ini", "[community]\nserver = 192.0.2.1\n[repsn]\nenabled = 1\n");
      State s = run(f);
      CHECK(s == KZ2_ONLINE_OFF && f.logged("'server' in community.ini") && f.logged("[repsn] in community.ini"), "community.ini: re-psn keys rejected"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1;rm -rf /\nserver = $(calc)\nserver = 127.0.0.1:0\n"
                                         "server = 127.0.0.1:99999\nserver = http://example.invalid/\nserver = [::1]:36100\nserver = -x\n"
                                         "name = 1abc\nname = %s%s%n\nname = a\nname = abcdefghijklmnopq\nenabled = yes\n");
      State s = run(f);
      CHECK(s == KZ2_ONLINE_OFF && !f.vars.count("PSNR_SERVER") && !f.online, "injection and malformed values: none applied");
      CHECK(f.logged("12 setting(s) rejected"), "injection and malformed values: each one rejected"); }

    { Fake f; clear(); put("shared/repsn.ini", std::string("[repsn]\nenabled = 1\nserver = 127.0.0.1\x00:1\n", 41));
      State s = run(f);
      CHECK(s == KZ2_ONLINE_OFF && f.logged("NUL byte"), "a NUL byte inside a line rejects the line"); }

    { Fake f; clear(); put("shared/community.ini", "[community]\nenabled = 1\n[preset ../evil]\naddress = 192.0.2.1\n[preset a b]\n");
      run(f); CHECK(f.logged("bad preset label") , "preset labels with path or space characters rejected"); }

    { Fake f; clear(); put("shared/repsn.ini", "\xEF\xBB\xBF[repsn]\r\nenabled = 1\r\nserver = example.invalid:36100\r\n");
      CHECK(run(f) == KZ2_ONLINE_REPSN && f.var("PSNR_SERVER") == "example.invalid:36100", "UTF-8 BOM and CRLF"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\np2p_port = 3700\n");
      put("game/repsn.ini", "[repsn]\np2p_port = 3659\ncomm_id = NPWR00153_00\nreport_rtt = 1\n");
      run(f);
      CHECK(f.var("PS3_NET_P2P_PORT") == "3659", "p2p_port from the game's own file");
      CHECK(f.logged("unknown key 'p2p_port'"), "p2p_port in the shared file rejected (a per-game value)"); }

    { Fake f; clear(); f.vars["PS3_NET_P2P_PORT"] = "4000"; put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n");
      put("game/repsn.ini", "[repsn]\np2p_port = 3659\n"); run(f);
      CHECK(f.var("PS3_NET_P2P_PORT") == "4000", "PS3_NET_P2P_PORT wins over p2p_port"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 0\nserver = 192.0.2.9\n");
      put("game/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1:36102\n");
      CHECK(run(f) == KZ2_ONLINE_REPSN && f.var("PSNR_SERVER") == "127.0.0.1:36102", "the game's own file is read last and wins"); }

    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\n");
      CHECK(run(f) == KZ2_ONLINE_OFF && f.logged("no valid server"), "re-psn without a server stays offline"); }

    { Fake f; clear(); put("game/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n");
      put("shared/community.ini", "[community]\nenabled = 1\n");
      CHECK(run(f) == KZ2_ONLINE_REFUSED, "both on across the shared and the game file: refused"); }

    /* an earlier change: KZ2_NET_LISTEN, the passive listener's diagnostic mode (lobby host name stands in) */
    { Fake f; clear(); put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 192.0.2.1\n");
      f.vars["KZ2_NET_LISTEN"] = "1"; f.vars["KZ2_NET_LISTEN_HOST"] = "lobby.example.invalid";
      State s = run(f, "192.0.2.2", "Flagname");
      CHECK(s == KZ2_ONLINE_LISTEN && f.online && f.strict && !f.np, "listen: switch on, strict, NP untouched");
      CHECK(f.maps.size() == 1 && f.maps[0] == "lobby.example.invalid=127.0.0.1", "listen: the lobby host mapped to 127.0.0.1 only");
      CHECK(f.allows.size() == 1 && f.allows[0] == "127.0.0.1:1-65535/3", "listen: only 127.0.0.1 allowed, TCP and UDP");
      CHECK(!f.vars.count("PSNR_SERVER") && !f.vars.count("PS3_NP_ONLINE_ID"), "listen: wins over --psnr, --username and the files");
      bool named = false; for (auto& l : f.log) if (l.find("lobby.example") != std::string::npos) named = true;
      CHECK(!named && f.logged("21 characters"), "listen: the host name is never logged"); }
    { Fake f; clear(); f.vars["KZ2_NET_LISTEN"] = "np"; f.vars["KZ2_NET_LISTEN_HOST"] = "lobby.example.invalid";
      CHECK(run(f) == KZ2_ONLINE_LISTEN && f.np == 1, "listen=np: NP manager signed in too"); }
    { Fake f; clear(); f.vars["KZ2_NET_LISTEN"] = "1";
      CHECK(run(f) == KZ2_ONLINE_OFF && !f.online && f.maps.empty() && f.logged("missing"), "listen without a host: offline"); }
    { Fake f; clear(); f.vars["KZ2_NET_LISTEN"] = "1"; f.vars["KZ2_NET_LISTEN_HOST"] = "lobby.example.invalid:10071";
      CHECK(run(f) == KZ2_ONLINE_OFF && !f.online, "listen with host:port: offline"); }
    { Fake f; clear(); f.vars["KZ2_NET_LISTEN"] = "1"; f.vars["KZ2_NET_LISTEN_HOST"] = "bad host;x";
      CHECK(run(f) == KZ2_ONLINE_OFF && !f.online, "listen with a malformed host: offline"); }
    { Fake f; clear(); f.vars["KZ2_NET_LISTEN"] = "yes"; f.vars["KZ2_NET_LISTEN_HOST"] = "lobby.example.invalid";
      CHECK(run(f) == KZ2_ONLINE_OFF && !f.online && f.logged("must be 1 or np"), "listen=yes: refused, offline"); }
    { Fake f; clear(); f.map_fail = 1; f.vars["KZ2_NET_LISTEN"] = "1"; f.vars["KZ2_NET_LISTEN_HOST"] = "lobby.example.invalid";
      CHECK(run(f) == KZ2_ONLINE_OFF && !f.online && f.allows.empty(), "listen: a refused map keeps the switch off"); }
    /* review an earlier change: every failure path forces the switch off and the policy strict, even with KZ3_ONLINE /
     * PSNR_SERVER in the environment; listen mode removes PSNR_SERVER */
    {
        struct Case { const char* mode; const char* host; int map_fail, allow_fail; const char* what; };
        const Case cases[] = {
            {"yes", "lobby.example.invalid", 0, 0, "bad mode"},
            {"1", nullptr, 0, 0, "missing host"},
            {"1", "bad host;x", 0, 0, "malformed host"},
            {"1", "lobby.example.invalid:10071", 0, 0, "host:port"},
            {"1", "lobby.example.invalid", 1, 0, "map refused"},
            {"np", "lobby.example.invalid", 0, 1, "allow refused after the map"},
        };
        for (const Case& c : cases) {
            Fake f; clear();
            f.vars["KZ3_ONLINE"] = "1"; f.vars["PSNR_SERVER"] = "127.0.0.1:36100";
            f.vars["KZ2_NET_LISTEN"] = c.mode;
            if (c.host) f.vars["KZ2_NET_LISTEN_HOST"] = c.host;
            f.map_fail = c.map_fail; f.allow_fail = c.allow_fail;
            State s = run(f);
            std::string what = std::string("listen failure (") + c.what + ", KZ3_ONLINE=1 + PSNR_SERVER): off, switch 0, strict 1";
            CHECK(s == KZ2_ONLINE_OFF && !f.online_calls.empty() && f.online_calls.back() == 0 && f.strict == 1
                  && !f.vars.count("PSNR_SERVER") && !f.np, what.c_str());
        }
        Fake f; clear(); f.allow_fail = 1; f.vars["KZ2_NET_LISTEN"] = "1"; f.vars["KZ2_NET_LISTEN_HOST"] = "lobby.example.invalid";
        run(f);
        CHECK(f.maps.size() == 1 && f.logged("refused the loopback allowlist"), "allow failing after map_host: said, offline");
        Fake g; clear(); g.vars["PSNR_SERVER"] = "127.0.0.1:36100"; g.vars["KZ2_NET_LISTEN"] = "1";
        g.vars["KZ2_NET_LISTEN_HOST"] = "lobby.example.invalid";
        CHECK(run(g) == KZ2_ONLINE_LISTEN && !g.vars.count("PSNR_SERVER") && g.logged("are ignored"),
              "listen success: PSNR_SERVER removed and said");
    }
    { Fake f; clear(); f.vars["KZ2_NET_LISTEN"] = "0"; put("shared/repsn.ini", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n");
      CHECK(run(f) == KZ2_ONLINE_REPSN && f.maps.empty(), "KZ2_NET_LISTEN=0: the normal decision"); }

    /* folders */
    { Fake f; std::string sh, gm;
      resolve_dirs(f.env(), g_root + "/inst/build", "C:\\Users\\x\\AppData\\Roaming", sh, gm);
      CHECK(sh == "C:\\Users\\x\\AppData\\Roaming\\PS3Recomp" && gm == "C:\\Users\\x\\AppData\\Roaming\\Project Pyrrhus", "installed: %APPDATA% folders");
      put("inst/kz2-install.ini", "[install]\r\nportable=1\r\n");
      resolve_dirs(f.env(), g_root + "/inst/build", "C:\\x", sh, gm);
      CHECK(sh == g_root + "/inst/shared" && gm == g_root + "/inst", "portable: kz2-install.ini one level up");
      put("inst/kz2-install.ini", "[install]\nportable = 0\n");
      resolve_dirs(f.env(), g_root + "/inst/build", "", sh, gm);
      CHECK(sh.empty() && gm.empty(), "installed without %APPDATA%: no folders");
      f.vars["PS3RECOMP_SHARED_DIR"] = g_root + "/shared";
      resolve_dirs(f.env(), g_root + "/inst/build", "C:\\x", sh, gm);
      CHECK(sh == g_root + "/shared", "PS3RECOMP_SHARED_DIR wins"); }

    { std::string p, u; const char* a[] = {"kz2.exe", "EBOOT.elf", "--psnr=127.0.0.1:36100", "--username", "Rico"};
      flags(5, (char**)a, p, u);
      CHECK(p == "127.0.0.1:36100" && u == "Rico", "flags: --psnr=X and --username X");
      std::string p2, u2; const char* b[] = {"kz2.exe", "--psnr"};
      flags(2, (char**)b, p2, u2); CHECK(p2.empty(), "flags: --psnr with no value"); }

    printf("%d of %d checks passed\n", checks - fails, checks);
    return fails ? 1 : 0;
}
