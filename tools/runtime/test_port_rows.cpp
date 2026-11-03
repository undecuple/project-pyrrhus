/* Host test for port/kz2/kz2_port_rows.h: the Display-page row table (values, ini text, the
 * page's "pc:" commands) and the page edit on a synthetic miniature of the options page (no game data).
 * With KZ2_MENU_PAGES_DIR=<.../svml/<code>/kin/menu> (inside the sandbox) it also edits the player's own three
 * option pages after the EXIT/KEYBOARD edits and checks the result; nothing from them is printed.
 *   nix develop --command tools/sandbox.sh -- tools/runtime/test_port_rows.sh */
#include <fstream>
#include <iostream>
#include <sstream>

#include "kz2_port_rows.h"

static int fails = 0;
static void ok(bool c, const std::string& what)
{
    std::cout << (c ? "ok   " : "FAIL ") << what << "\n";
    if (!c) fails++;
}

static std::string slurp(const std::string& p)
{
    std::ifstream f(p, std::ios::binary);
    std::stringstream s; s << f.rdbuf();
    return s.str();
}

static size_t count(const std::string& t, const std::string& s) { return kz2mt::find_all(t, s).size(); }

int main()
{
    using namespace kz2rows;
    const Row& fov = kz2_port_rows[find("fov")];
    const Row& up = kz2_port_rows[find("upscale")];
    const Row& sh = kz2_port_rows[find("sharpness")];
    ok(find("nope") < 0, "unknown id");
    /* values */
    ok(snap(fov, 44.0) == 45.0 && snap(fov, 99.0) == 75.0 && snap(fov, 60.4) == 60.0 && snap(fov, 60.6) == 61.0, "fov snap");
    ok(snap(sh, 0.30000001192092896) == 0.3 && snap(sh, 2.5) == 2.0 && snap(sh, -1.0) == 0.0, "sharpness snap (Lua float)");
    ok(shown(sh, 0.2) == "0.2" && shown(fov, 70) == "70" && shown(up, 1) == "FSR 1" && shown(up, 0) == "OFF", "shown");
    ok(ini_value(up, 1) == "fsr1" && ini_value(sh, 1.0) == "1.0", "ini values");
    double v = -1;
    ok(parse(up, " FSR1 ", &v) && v == 1.0 && parse(up, "off", &v) && v == 0.0 && !parse(up, "dlss", &v), "parse choice");
    ok(parse(fov, "62.0", &v) && v == 62.0 && !parse(fov, "62x", &v) && !parse(fov, "", &v), "parse range");
    ok(fov.def == 45.0 && up.def == 0.0 && sh.def == 0.2, "defaults: original FOV, upscaling off, sharpness 0.2");
    /* ini text */
    const std::string ini = "; written by Alt+Enter\n[display]\nmode = borderless\nscaling = fit\n\n[other]\nfov = 99\n";
    std::string g;
    ok(!ini_get(ini, "display", "fov", &g), "ini_get: key in another section is not ours");
    std::string t2 = ini_set(ini, "display", "fov", "60");
    ok(t2 == "; written by Alt+Enter\n[display]\nmode = borderless\nscaling = fit\nfov = 60\n\n[other]\nfov = 99\n", "ini_set adds after the section's last key");
    ok(ini_get(t2, "display", "fov", &g) && g == "60" && ini_get(t2, "DISPLAY", "Mode", &g) && g == "borderless", "ini_get");
    std::string t3 = ini_set(t2, "display", "mode", "windowed");
    ok(t3.find("mode = windowed\nscaling = fit\nfov = 60\n") != std::string::npos && count(t3, "mode") == 1 && t3.find("; written") == 0,
       "ini_set replaces in place, keeps comments");
    ok(ini_set("", "display", "upscale", "fsr1") == "[display]\nupscale = fsr1\n", "ini_set on an empty file");
    ok(ini_set("[display]\r\nmode = fullscreen\r\n", "display", "fov", "50") == "[display]\r\nmode = fullscreen\r\nfov = 50\r\n", "ini_set keeps CRLF");
    ok(ini_set("[display]\nfov = 1\nfov = 2\n", "display", "fov", "3") == "[display]\nfov = 3\n", "ini_set drops repeats");
    ok(ini_set("[a]\nx = 1\n", "display", "fov", "50") == "[a]\nx = 1\n\n[display]\nfov = 50\n", "ini_set adds a section");
    /* commands */
    State s; defaults(&s);
    std::vector<int> ch;
    ok(command(&s, "get fov", &ch) == "45" && ch.empty(), "get fov");
    ok(command(&s, "set fov 61.7", &ch) == "62" && ch.size() == 1 && s.v[find("fov")] == 62.0, "set fov snaps and reports a change");
    ok(command(&s, "set fov 62", &ch) == "62" && ch.empty(), "set to the same value: no change");
    ok(command(&s, "show upscale", &ch) == "OFF" && command(&s, "cycle upscale", &ch) == "FSR 1" && ch.size() == 1, "cycle upscale");
    ok(command(&s, "cycle upscale", &ch) == "OFF", "cycle wraps");
    ok(command(&s, "get upscale", &ch) == "0" && command(&s, "get sharpness", &ch) == "0.2", "get index / decimals");
    /* the VSYNC row (patch 6054) */
    ok(command(&s, "show vsync", &ch) == "ON" && command(&s, "get vsync", &ch) == "1" && ch.empty(), "vsync on by default");
    ok(command(&s, "cycle vsync", &ch) == "OFF" && ch.size() == 1 && ini_value(kz2_port_rows[find("vsync")], s.v[find("vsync")]) == "off",
       "cycle vsync -> off, ini value off");
    { double d = -1; ok(parse(kz2_port_rows[find("vsync")], "on", &d) && d == 1.0 && !parse(kz2_port_rows[find("vsync")], "maybe", &d),
                        "vsync ini parse"); }
    ok(command(&s, "cycle vsync", &ch) == "ON", "vsync cycles back");
    ok(command(&s, "cycle fov", &ch) == "?" && command(&s, "set nope 1", &ch) == "?" && command(&s, "", &ch) == "?", "bad commands");
    command(&s, "cycle upscale", &ch);
    ok(command(&s, "reset", &ch) == "ok" && ch.size() == 2 && s.v[find("fov")] == 45.0 && s.v[find("upscale")] == 0.0, "reset");
    /* the page edit on a miniature of the options page */
    const std::string mini =
        "<SVML> <PAGEID name=\"kin-preparsed_x\" /> <_p name=\"optionsSubpanel\" c=\"_Normal\" p=\"514,196,638,400\" g=\"0\" /> "
        "<_l name=\"listDisplaySettings\" c=\"_Normal\" p=\"16,14,620,203\" a=\"true\" g=\"1\" /> "
        "<_i name=\"itemBrightness\" c=\"_Medium\" p=\",,620,29\" g=\"2\" t=\"GAMMA CORRECTION\" /><_i: name=\"!\" g=\"2\" /> "
        "<_i name=\"itemHints\" c=\"_Medium\" p=\",116,620,29\" g=\"3\" /> <_i: name=\"!\" g=\"3\" /> "
        "<_i name=\"itemResetDisplaySettings\" c=\"_Medium\" p=\",174,620,29\" g=\"4\" h=\"static://script.optionsmenuscript.ResetDisplaySettings\" "
        "t=\"SET TO DEFAULT\" /><_i: name=\"!\" g=\"4\" /> <_l: name=\"!\" g=\"1\" /> "
        "<_l name=\"listControlSettings\" c=\"_Normal\" p=\"16,14,620,203\" g=\"5\" /> <_l: name=\"!\" g=\"5\" /> <_p: name=\"!\" g=\"0\" /> "
        "<_s name=\"optionsmenuscript\" ><![CDATA[\r\nfunction OnEnterPage()\r\n"
        "gSliderMusicVolume:SetOnChange(\"optionsmenuscript.UpdateVolume(sliderMusicVolume)\")\r\nend\r\n"
        "function InitOptionSettings()\r\nend\r\nfunction ResetDisplaySettings()\r\nend\r\nfunction ToggleCheckBox(checkbox)\r\nend\r\n]]></_s> </SVML>";
    std::string e;
    try { e = display_rows(mini); } catch (const kz2mt::Anchor& a) { std::cout << "anchor: " << a.what() << "\n"; }
    ok(!e.empty() && kz2mt::check(e).empty(), "edited page passes the tag check");
    ok(e.find("<_i name=\"itemPcFov\" c=\"_Medium\" p=\",145,620,29\" g=\"4\" t=\"FIELD OF VIEW\" />") != std::string::npos,
       "FOV row in the free row above SET TO DEFAULT, g 4");
    ok(e.find("m=\"45\" s=\"1\" u=\"45\" x=\"75\"") != std::string::npos && e.find("m=\"0.0\" s=\"0.1\" u=\"0.2\" x=\"2.0\"") != std::string::npos,
       "slider ranges");
    ok(e.find("<_i name=\"itemPcUpscale\" c=\"_Medium\" p=\",174,620,29\" g=\"5\" h=\"static://script.optionsmenuscript.PcCycle_upscale\"") !=
           std::string::npos, "UPSCALING row cycles");
    ok(e.find("<_i name=\"itemResetDisplaySettings\" c=\"_Medium\" p=\",290,620,29\" g=\"8\"") != std::string::npos &&
           e.find("<_i: name=\"!\" g=\"8\" /> <_l: name=\"!\" g=\"1\" />") != std::string::npos, "SET TO DEFAULT moves down to y 290, g 8");
    ok(e.find("<_l name=\"listDisplaySettings\" c=\"_Normal\" p=\"16,14,620,319\"") != std::string::npos, "list grows to 319");
    ok(e.find("<_l name=\"listControlSettings\" c=\"_Normal\" p=\"16,14,620,203\" g=\"9\"") != std::string::npos, "later ids move by 4");
    ok(e.find("UpdateVolume(sliderMusicVolume)\")\r\ngBrowser:GetTagByName(\"sliderPcFov\"):SetOnChange(\"optionsmenuscript.PcSet_fov\")\r\n") !=
           std::string::npos, "slider change applies live");
    ok(e.find("function InitOptionSettings()\r\nPcInit()\r\n") != std::string::npos &&
           e.find("function ResetDisplaySettings()\r\nPcReset()\r\n") != std::string::npos, "init and reset hooks");
    ok(e.find("function Pc(cmd)\r\ngPlayerProfile:SetTimeZone(\"pc:\" .. cmd)\r\n") != std::string::npos &&
           e.find("function PcSet_sharpness()") != std::string::npos && e.find("function PcCycle_upscale()") != std::string::npos &&
           e.find("function PcCycle_upscale()") < e.find("function ToggleCheckBox") &&
           e.find("function PcCycle_vsync()") != std::string::npos, "script functions before ToggleCheckBox");
    ok(e.find("<_i name=\"itemPcVsync\" c=\"_Medium\" p=\",232,620,29\" g=\"7\" h=\"static://script.optionsmenuscript.PcCycle_vsync\"") !=
           std::string::npos, "VSYNC row cycles, below SHARPNESS");
    bool threw = false;
    try { display_rows(e); } catch (const kz2mt::Anchor&) { threw = true; }
    ok(threw, "a second edit is refused");
    threw = false;
    try { display_rows("<SVML> </SVML>"); } catch (const kz2mt::Anchor&) { threw = true; }
    ok(threw, "a page without the Display list is refused");
    /* the player's own pages (optional) */
    if (const char* dir = getenv("KZ2_MENU_PAGES_DIR")) {
        const char* pages[3][2] = { { "mainmenu.jsp", "main" }, { "campaign/options.jsp", "sp" }, { "online/game/options.jsp", "mp" } };
        for (auto& p : pages) {
            std::string t = slurp(std::string(dir) + "/" + p[0]);
            if (t.empty()) { ok(false, std::string("real page missing: ") + p[0]); continue; }
            std::string r;
            try {
                t = kz2mt::exit_page(t, p[1]);
                t = kz2mt::patch_options(t);
                r = display_rows(t);
            } catch (const kz2mt::Anchor& a) { std::cout << "anchor: " << a.what() << "\n"; }
            ok(!r.empty() && kz2mt::check(r).empty() && count(r, "name=\"itemPc") == (size_t)NROWS && count(r, "PcInit()") == 3,
               std::string("real page ") + p[0] + ": rows added, tag check passes");
        }
    }
    std::cout << (fails ? "test_port_rows: FAIL\n" : "test_port_rows: ok\n");
    return fails ? 1 : 0;
}
