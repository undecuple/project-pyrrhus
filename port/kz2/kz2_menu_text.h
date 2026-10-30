/* Killzone 2 port: text edits of the front end's SVML pages (ENHANCEMENT).
 *
 * C++ port of two Python reference transforms in the project's private data tools (not in the public tree): jsp_overlay.py
 * (exit_page, check, renumber, popup_strings) and kbpage.py (patch_options, keyboard_page, extract_descriptions). They
 * are the specification: a host test outside the public tree runs both on the same pages and requires byte-identical
 * output. Pure std::string, no regex (libstdc++'s std::regex recurses per character and the <_s> script blocks are
 * tens of KB), no OS calls, so the host test builds it with the system compiler.
 *
 * The edits are applied at run time to the player's own page text (the lookup override in kz2_menu_pages.cpp); no game
 * text is in this file or anywhere in the repository. Every anchor must match exactly once, else the page is left
 * unchanged (kz2mt::Anchor), so a page of another shape is never half edited.
 */
#pragma once
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace kz2mt {

struct Anchor : std::runtime_error { explicit Anchor(const std::string& s) : std::runtime_error(s) {} };

static const char* const URL = "pc:exit";
static const char* const LABEL = "EXIT TO DESKTOP";
static const char* const DESC = "Close the game and return to the desktop";
static const char* const MSG = "Exit the game and return to the desktop?";

/* kbpage.py constants */
static const char* const KB_PAGE = "keyboardsettings";
static const char* const KB_PAGE_URL = "file:///kin/menu/options/keyboardsettings.jsp";
static const char* const KB_PAGE_URL_INGAME = "file:///kin/menu/options/keyboardsettings_ingame.jsp";
static const char* const KB_TITLE = "Keyboard and mouse";
static const char* const KB_ROW_TITLE = "KEYBOARD";
static const char* const KB_ROW_DESC = "Change the keyboard and mouse controls";
static const char* const KB_FLAG = "options.returningfromkeyboard";
static const int KB_NSLOT = 2;
static const int KB_ROW_INDEX = 3;
struct KbInput { const char* host; const char* shown; const char* cap; const char* label; };
static const KbInput KB_INPUTS[24] = {
    {"up", "D-PAD UP", "up", "d-pad up (zoom mode)"},
    {"down", "D-PAD DOWN", "dpad", "d-pad down"},
    {"left", "D-PAD LEFT", "dpad", "d-pad left"},
    {"right", "D-PAD RIGHT", "dpad", "d-pad right"},
    {"cross", "CROSS", "cross", "jump, vault; menu accept"},
    {"circle", "CIRCLE", "circle", "use; menu back"},
    {"square", "SQUARE", "square", "reload, pick up weapon"},
    {"triangle", "TRIANGLE", "triangle", "next weapon"},
    {"l1", "L1", "L1", "close combat"},
    {"r1", "R1", "R1", "fire"},
    {"l2", "L2", "L2", "crouch, cover"},
    {"r2", "R2", "R2", "throw grenade"},
    {"l3", "L3", "leftAnalog", "sprint"},
    {"r3", "R3", "rightAnalog", "zoom, flashlight"},
    {"start", "START", "", "pause menu"},
    {"select", "SELECT", "", "select"},
    {"ls_up", "LEFT STICK UP", "leftAnalog", "move forward (left stick up)"},
    {"ls_down", "LEFT STICK DOWN", "leftAnalog", "move back"},
    {"ls_left", "LEFT STICK LEFT", "leftAnalog", "strafe left"},
    {"ls_right", "LEFT STICK RIGHT", "leftAnalog", "strafe right"},
    {"rs_up", "RIGHT STICK UP", "rightAnalog", "look up (right stick up)"},
    {"rs_down", "RIGHT STICK DOWN", "rightAnalog", "look down"},
    {"rs_left", "RIGHT STICK LEFT", "rightAnalog", "turn left"},
    {"rs_right", "RIGHT STICK RIGHT", "rightAnalog", "turn right"},
};
static const int KB_LIST_Y = 40, KB_LIST_H = 316, KB_ROW_H = 29;
static const int KB_COL_NAME = 0, KB_COL_CAP = 200, KB_COL_K0 = 530, KB_COL_K1 = 735;

/* ---------------------------------------------------------------- small helpers */
inline bool is_word(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_'; }
inline bool is_digit(char c) { return c >= '0' && c <= '9'; }
inline bool is_space(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v'; }
inline bool at(const std::string& t, size_t i, const char* lit) { size_t n = strlen(lit); return i + n <= t.size() && t.compare(i, n, lit) == 0; }

/* all positions of a literal */
inline std::vector<size_t> find_all(const std::string& t, const std::string& lit, size_t from = 0)
{
    std::vector<size_t> v;
    for (size_t p = t.find(lit, from); p != std::string::npos; p = t.find(lit, p + lit.size())) v.push_back(p);
    return v;
}
inline size_t once(const std::string& t, const std::string& lit, const std::string& what)
{
    std::vector<size_t> v = find_all(t, lit);
    if (v.size() != 1) throw Anchor(what + ": " + std::to_string(v.size()) + " matches (need exactly 1)");
    return v[0];
}
/* digits at i: value and end, or false */
inline bool digits(const std::string& t, size_t i, long* v, size_t* end)
{
    size_t j = i;
    while (j < t.size() && is_digit(t[j])) j++;
    if (j == i) return false;
    *v = std::stol(t.substr(i, j - i)); *end = j;
    return true;
}
/* Python's `literal \r?\n literal2` (one or the other line ending): positions of matches as (start, end) */
inline std::vector<std::pair<size_t, size_t>> find_nl(const std::string& t, const std::string& a, const std::string& b)
{
    std::vector<std::pair<size_t, size_t>> v;
    for (size_t p : find_all(t, a)) {
        size_t q = p + a.size();
        if (at(t, q, "\r\n")) q += 2; else if (at(t, q, "\n")) q += 1; else continue;
        if (t.compare(q, b.size(), b) == 0 && q + b.size() <= t.size()) v.push_back({p, q + b.size()});
    }
    return v;
}
inline std::pair<size_t, size_t> once_nl(const std::string& t, const std::string& a, const std::string& b, const std::string& what)
{
    auto v = find_nl(t, a, b);
    if (v.size() != 1) throw Anchor(what + ": " + std::to_string(v.size()) + " matches (need exactly 1)");
    return v[0];
}

/* <_s .*?</_s> spans (DOTALL, first closer after each opener) */
inline std::vector<std::pair<size_t, size_t>> script_spans(const std::string& t)
{
    std::vector<std::pair<size_t, size_t>> v;
    size_t p = 0;
    for (;;) {
        size_t s = t.find("<_s ", p);
        if (s == std::string::npos) break;
        size_t e = t.find("</_s>", s + 4);
        if (e == std::string::npos) break;
        v.push_back({s, e + 5});
        p = e + 5;
    }
    return v;
}

/* TAG = (<_[a-z]:? [^>]*?\bg=")(\d+)(") on a segment; colon: -1 either, 0 opener only, 1 closer only.
 * Calls f(pos_of_digits, end_of_digits, value) for every match, left to right, non-overlapping. */
template <class F> inline void each_tag_g(const std::string& t, size_t from, size_t to, int colon, F f)
{
    size_t i = from;
    while (i < to) {
        size_t lt = t.find("<_", i);
        if (lt == std::string::npos || lt >= to) break;
        size_t j = lt + 2;
        if (j >= to || !(t[j] >= 'a' && t[j] <= 'z')) { i = lt + 1; continue; }
        j++;
        bool has_colon = false;
        if (j < to && t[j] == ':') { has_colon = true; j++; }
        if (j >= to || t[j] != ' ' || (colon == 0 && has_colon) || (colon == 1 && !has_colon)) { i = lt + 1; continue; }
        j++;
        /* [^>]*?\bg="(\d+)" : first g=" preceded by a non-word char with digits and a quote, before any '>' */
        bool found = false;
        for (size_t k = j; k < to && t[k] != '>'; k++) {
            if (t[k] == 'g' && k + 2 < to && t[k + 1] == '=' && t[k + 2] == '"' && (k == 0 || !is_word(t[k - 1]))) {
                long v; size_t e;
                if (digits(t, k + 3, &v, &e) && e < to && t[e] == '"') {
                    f(k + 3, e, v);
                    i = e + 1; found = true; break;
                }
            }
        }
        if (!found) i = lt + 1;
    }
}

/* g >= first -> g + delta in tags outside <_s> blocks */
inline std::string renumber(const std::string& t, long first, long delta = 1)
{
    std::string out;
    out.reserve(t.size() + 64);
    size_t pos = 0;
    auto seg = [&](size_t a, size_t b) {
        size_t last = a;
        each_tag_g(t, a, b, -1, [&](size_t ds, size_t de, long v) {
            out.append(t, last, ds - last);
            out += std::to_string(v + (v >= first ? delta : 0));
            last = de;
        });
        out.append(t, last, b - last);
    };
    for (auto& s : script_spans(t)) { seg(pos, s.first); out.append(t, s.first, s.second - s.first); pos = s.second; }
    seg(pos, t.size());
    return out;
}

/* jsp_overlay.check: problems of a page's tag ids (empty = fine) */
inline std::vector<std::string> check(const std::string& text)
{
    std::string body;
    size_t pos = 0;
    for (auto& s : script_spans(text)) { body.append(text, pos, s.first - pos); pos = s.second; }
    body.append(text, pos, std::string::npos);
    std::vector<long> opens, closes;
    each_tag_g(body, 0, body.size(), 0, [&](size_t, size_t, long v) { opens.push_back(v); });
    each_tag_g(body, 0, body.size(), 1, [&](size_t, size_t, long v) { closes.push_back(v); });
    std::vector<std::string> bad;
    bool seq = true;
    for (size_t i = 0; i < opens.size(); i++) if (opens[i] != (long)i) { seq = false; break; }
    if (!seq) bad.push_back("opener g ids are not 0..n-1 in document order");
    std::vector<char> isopen(opens.size() + 1, 0);
    bool sub = true;
    for (long c : closes) { bool f = false; for (long o : opens) if (o == c) { f = true; break; } if (!f) { sub = false; break; } }
    if (!sub) bad.push_back("a closer has no opener");
    for (size_t i = 0; i < closes.size(); i++) for (size_t j = i + 1; j < closes.size(); j++)
        if (closes[i] == closes[j]) { bad.push_back("duplicate closer"); i = closes.size(); break; }
    return bad;
}

inline std::string lua(const std::string& s)
{
    std::string o = "\"";
    for (char c : s) { if (c == '\\') o += "\\\\"; else if (c == '"') o += "\\\""; else o += c; }
    return o + "\"";
}

/* a Lua string literal "(?:[^"\\]|\\.)*" at i: end index (one past the closing quote) or npos */
inline size_t lua_lit(const std::string& t, size_t i)
{
    if (i >= t.size() || t[i] != '"') return std::string::npos;
    for (size_t j = i + 1; j < t.size(); j++) {
        if (t[j] == '\\') { if (j + 1 >= t.size()) return std::string::npos; j++; continue; }
        if (t[j] == '"') return j + 1;
    }
    return std::string::npos;
}

/* popup_strings: (message, ok, cancel) literals (with quotes) of ShowPopup("quitgame", ...); false if absent */
inline bool popup_strings(const std::string& t, std::string* msg, std::string* ok, std::string* cancel)
{
    for (size_t p : find_all(t, "ShowPopup(\"quitgame\",")) {
        size_t i = p + strlen("ShowPopup(\"quitgame\",");
        std::string lit[3];
        bool good = true;
        for (int k = 0; k < 3 && good; k++) {
            if (k) { if (i < t.size() && t[i] == ',') i++; else { good = false; break; } }
            while (i < t.size() && is_space(t[i])) i++;
            size_t e = lua_lit(t, i);
            if (e == std::string::npos) { good = false; break; }
            lit[k] = t.substr(i, e - i); i = e;
        }
        if (good && i < t.size() && t[i] == ')') { *msg = lit[0]; *ok = lit[1]; *cancel = lit[2]; return true; }
    }
    return false;
}

inline std::string item(const std::string& name, long y, long g, const std::string& action, const std::string& label)
{
    return "<_i name=\"" + name + "\" c=\"_Medium\" p=\"," + std::to_string(y) + ",,29\" g=\"" + std::to_string(g) +
           "\" h=\"static://script." + action + "\" t=\"" + label + "\" /><_i: name=\"!\" g=\"" + std::to_string(g) + "\" />";
}

/* `<_i name="item<(QuitAndReload|DebugOptions)>" c="_Medium" p=",` at i: length of the prefix, or 0 */
inline size_t debug_row_at(const std::string& t, size_t i)
{
    static const char* const names[2] = { "<_i name=\"itemQuitAndReload\" c=\"_Medium\" p=\",", "<_i name=\"itemDebugOptions\" c=\"_Medium\" p=\"," };
    for (const char* n : names) if (at(t, i, n)) return strlen(n);
    return 0;
}

/* ---------------------------------------------------------------- jsp_overlay.exit_page */
inline std::string exit_page(const std::string& text, const std::string& kind, const std::string& label = LABEL,
                             const std::string& message = MSG, const std::string& ok = "\"OK\"",
                             const std::string& cancel = "\"CANCEL\"", const std::string& desc = DESC)
{
    std::string t = text;
    const std::string entry = "{ title = " + lua(label) + ", description = " + lua(desc) + ", links = nil }";
    if (kind == "main") {
        /* <_l name="listMainMenu"[^>]*?\bg="(\d+)" */
        std::vector<long> gls;
        for (size_t p : find_all(t, "<_l name=\"listMainMenu\"")) {
            size_t s = p + strlen("<_l name=\"listMainMenu\"");
            for (size_t k = s; k < t.size() && t[k] != '>'; k++)
                if (t[k] == 'g' && at(t, k + 1, "=\"") && !is_word(t[k - 1])) {
                    long v; size_t e;
                    if (digits(t, k + 3, &v, &e) && e < t.size() && t[e] == '"') { gls.push_back(v); break; }
                }
        }
        if (gls.size() != 1) throw Anchor("listMainMenu: " + std::to_string(gls.size()) + " matches (need exactly 1)");
        const long gl = gls[0];
        /* last item: <_i name="item\w+" c="_Medium" p=",(\d+),,29" g="(\d+)"[^>]*?/><_i: name="!" g="\2" />(?= <_l: name="!" g="gl" />) */
        struct M { size_t end; long y, g; };
        std::vector<M> ms;
        const std::string lclose = " <_l: name=\"!\" g=\"" + std::to_string(gl) + "\" />";
        for (size_t p : find_all(t, "<_i name=\"item")) {
            size_t i = p + strlen("<_i name=\"item");
            size_t w = i;
            while (w < t.size() && is_word(t[w])) w++;
            if (w == i || !at(t, w, "\" c=\"_Medium\" p=\",")) continue;
            long y, g; size_t e;
            if (!digits(t, w + strlen("\" c=\"_Medium\" p=\","), &y, &e) || !at(t, e, ",,29\" g=\"")) continue;
            if (!digits(t, e + strlen(",,29\" g=\""), &g, &e) || !at(t, e, "\"")) continue;
            size_t k = e + 1;
            while (k < t.size() && t[k] != '>') k++;
            if (k >= t.size() || t[k - 1] != '/') continue;
            const std::string closer = "<_i: name=\"!\" g=\"" + std::to_string(g) + "\" />";
            if (!at(t, k + 1, closer.c_str())) continue;
            size_t end = k + 1 + closer.size();
            if (!at(t, end, lclose.c_str())) continue;
            ms.push_back({end, y, g});
        }
        if (ms.size() != 1) throw Anchor("last main-list item: " + std::to_string(ms.size()) + " matches");
        const long y = ms[0].y + 29, g = ms[0].g + 1;
        const size_t e = ms[0].end;
        t = t.substr(0, e) + " " + item("itemExitDesktop", y, g, "mainmenuscript.ExitToDesktop()", label) + renumber(t.substr(e), g, 1);
        auto m = once_nl(t, "function OnEnterPage()", "gModule:CheckCampaignTrophyUnlocks()", "mainmenu OnEnterPage");
        t = t.substr(0, m.second) + "\r\ngMenu[7] = " + entry + t.substr(m.second);
        m = once_nl(t, "function OnPopupClose(id, value)", "", "mainmenu OnPopupClose");
        t = t.substr(0, m.second) + "if (id == \"exitdesktop\" and value == \"ok\") then\r\ngModule:ExitAll(\"" + URL +
            "\")\r\nreturn\r\nend\r\n" + t.substr(m.second);
        size_t tm = once(t, "function TestMenu()", "TestMenu");
        t = t.substr(0, tm) + "function ExitToDesktop()\r\ngBrowserContext:SetPageValue(\"popup.scriptname\", \"mainmenuscript\")\r\n"
            "gBrowserContext:SetPageValue(\"popup.id\", \"exitdesktop\")\r\n"
            "gBrowserContext:SetPageValue(\"popup.message\", " + lua(message) + ")\r\n"
            "gBrowserContext:SetPageValue(\"popup.ok\", " + ok + ")\r\ngBrowserContext:SetPageValue(\"popup.cancel\", " + cancel + ")\r\n"
            "gBrowser:OpenPopup(\"file:///kin/menu/popups/popupgeneric.jsp\")\r\nend\r\n" + t.substr(tm);
        return t;
    }
    /* pause pages: first <_i name="item(QuitAndReload|DebugOptions)" c="_Medium" p=",(\d+),,29" g="(\d+)" */
    long y0 = -1, g0 = -1;
    for (size_t p = t.find("<_i name=\"item"); p != std::string::npos; p = t.find("<_i name=\"item", p + 1)) {
        size_t n = debug_row_at(t, p);
        if (!n) continue;
        long y, g; size_t e;
        if (!digits(t, p + n, &y, &e) || !at(t, e, ",,29\" g=\"")) continue;
        if (!digits(t, e + strlen(",,29\" g=\""), &g, &e) || !at(t, e, "\"")) continue;
        y0 = y; g0 = g; break;
    }
    if (y0 < 0) throw Anchor("no debug row to anchor the pause menu");
    t = renumber(t, g0, 1);
    /* y of every debug row + 29 */
    {
        std::string o;
        size_t last = 0;
        for (size_t p = t.find("<_i name=\"item"); p != std::string::npos; p = t.find("<_i name=\"item", p + 1)) {
            size_t n = debug_row_at(t, p);
            if (!n) continue;
            long y; size_t e;
            if (!digits(t, p + n, &y, &e) || !at(t, e, ",,29\"")) continue;
            o.append(t, last, p + n - last);
            o += std::to_string(y + 29);
            last = e;
        }
        o.append(t, last, std::string::npos);
        t = o;
    }
    size_t anchor = std::string::npos;
    for (size_t p = t.find("<_i name=\"item"); p != std::string::npos; p = t.find("<_i name=\"item", p + 1))
        if (at(t, p, "<_i name=\"itemQuitAndReload\"") || at(t, p, "<_i name=\"itemDebugOptions\"")) { anchor = p; break; }
    t = t.substr(0, anchor) + item("itemExitDesktop", y0, g0, "ingameoptionsscript.ExitToDesktop", label) + " " + t.substr(anchor);
    const int base = kind == "sp" ? 5 : 4;
    std::vector<int> dbg = kind == "sp" ? std::vector<int>{6, 5} : std::vector<int>{4};
    for (int i : dbg) {
        /* (?m)^gMenu\[i\] ?= ?\{ title  -> gMenu[i+1] = { title */
        const std::string head = "gMenu[" + std::to_string(i) + "]";
        std::vector<std::pair<size_t, size_t>> hits;
        for (size_t p : find_all(t, head)) {
            if (p != 0 && t[p - 1] != '\n') continue;
            size_t q = p + head.size();
            if (q < t.size() && t[q] == ' ') q++;
            if (q >= t.size() || t[q] != '=') continue;
            q++;
            if (q < t.size() && t[q] == ' ') q++;
            if (!at(t, q, "{ title")) continue;
            hits.push_back({p, q + strlen("{ title")});
        }
        if (hits.size() != 1) throw Anchor("debug gMenu[" + std::to_string(i) + "] entry: " + std::to_string(hits.size()) + " matches");
        t = t.substr(0, hits[0].first) + "gMenu[" + std::to_string(i + 1) + "] = { title" + t.substr(hits[0].second);
    }
    /* function OnEnterPage\(\)\r?\nif\( ?gBrowser:IsRtDbg\(\) ?\) then */
    {
        std::vector<std::pair<size_t, size_t>> hits;
        for (size_t p : find_all(t, "function OnEnterPage()")) {
            size_t q = p + strlen("function OnEnterPage()");
            if (at(t, q, "\r\n")) q += 2; else if (at(t, q, "\n")) q++; else continue;
            if (!at(t, q, "if(")) continue;
            q += 3;
            if (at(t, q, " ")) q++;
            if (!at(t, q, "gBrowser:IsRtDbg()")) continue;
            q += strlen("gBrowser:IsRtDbg()");
            if (at(t, q, " ")) q++;
            if (!at(t, q, ") then")) continue;
            hits.push_back({p, q + strlen(") then")});
        }
        if (hits.size() != 1) throw Anchor("pause OnEnterPage: " + std::to_string(hits.size()) + " matches (need exactly 1)");
        t = t.substr(0, hits[0].first) + "function OnEnterPage()\r\ngMenu[" + std::to_string(base) + "] = " + entry +
            "\r\nif( gBrowser:IsRtDbg() ) then" + t.substr(hits[0].second);
    }
    auto m = once_nl(t, "function OnPopupClose(id, value)", "", "pause OnPopupClose");
    t = t.substr(0, m.second) + "if (id == \"exitdesktop\" and value == \"ok\") then\r\ngModule:ExitAll(\"" + URL +
        "\")\r\nreturn\r\nend\r\n" + t.substr(m.second);
    size_t q = once(t, "function Quit()", "pause Quit");
    t = t.substr(0, q) + "function ExitToDesktop()\r\nShowPopup(\"exitdesktop\", " + lua(message) + ", " + ok + ", " + cancel +
        ")\r\nend\r\n" + t.substr(q);
    return t;
}

/* ---------------------------------------------------------------- kbpage */
inline std::string attr(const std::string& s)
{
    std::string o;
    for (char c : s) { if (c == '&') o += "&amp;"; else if (c == '"') o += "&quot;"; else if (c == '<') o += "&lt;"; else o += c; }
    return o;
}
inline std::string upper(const std::string& s) { std::string o = s; for (char& c : o) if (c >= 'a' && c <= 'z') c = (char)(c - 32); return o; }

/* index of the } closing the { at i (Lua strings respected) */
inline size_t balanced(const std::string& t, size_t i)
{
    int depth = 0; bool instr = false;
    for (size_t j = i; j < t.size(); j++) {
        char c = t[j];
        if (instr) { if (c == '\\') j++; else if (c == '"') instr = false; }
        else if (c == '"') instr = true;
        else if (c == '{') depth++;
        else if (c == '}') { if (--depth == 0) return j; }
    }
    throw Anchor("unbalanced braces in the controller schemes");
}

/* `word\s*=\s*\{` searched from pos (word boundary before when wb): position of the '{' or npos */
inline size_t assign_brace(const std::string& t, const std::string& word, size_t pos, bool wb)
{
    for (size_t p = t.find(word, pos); p != std::string::npos; p = t.find(word, p + 1)) {
        if (wb && p > 0 && is_word(t[p - 1])) continue;
        size_t q = p + word.size();
        while (q < t.size() && is_space(t[q])) q++;
        if (q >= t.size() || t[q] != '=') continue;
        q++;
        while (q < t.size() && is_space(t[q])) q++;
        if (q < t.size() && t[q] == '{') return q;
    }
    return std::string::npos;
}

/* re.sub(r'\s*\r?\n\s*', ' ', s): every whitespace run that holds a newline becomes one space */
inline std::string join_lines(const std::string& s)
{
    std::string o;
    for (size_t i = 0; i < s.size();) {
        if (is_space(s[i])) {
            size_t j = i; bool nl = false;
            while (j < s.size() && is_space(s[j])) { if (s[j] == '\n') nl = true; j++; }
            if (nl) o += ' '; else o.append(s, i, j - i);
            i = j;
        } else o += s[i++];
    }
    return o;
}

inline std::vector<std::string> extract_descriptions(const std::string& options_text)
{
    std::vector<std::string> out;
    size_t b = assign_brace(options_text, "gControllerSchemes", 0, false);
    if (b == std::string::npos) return out;
    size_t end = balanced(options_text, b);
    const std::string body = options_text.substr(b, end + 1 - b);
    size_t pos = 1;
    for (;;) {
        size_t d = assign_brace(body, "description", pos, true);
        if (d == std::string::npos) break;
        size_t j = balanced(body, d);
        out.push_back(join_lines(body.substr(d, j + 1 - d)));
        pos = j + 1;
    }
    return out;
}

inline std::string kb_script(const std::vector<std::string>& descs)
{
    std::vector<std::string> L;
    auto a = [&](const std::string& s) { L.push_back(s); };
    const std::string N = std::to_string(KB_NSLOT), R = std::to_string(24 - 1), S = std::to_string(KB_NSLOT - 1);
    a("global gKbList = nil"); a("global gKbHint = nil"); a("global gKbTags = {}"); a("global gKbCapTags = {}"); a("global gKbBusy = false");
    { std::string d = "global gKbDesc = { "; for (size_t i = 0; i < descs.size(); i++) { if (i) d += ", "; d += descs[i]; } a(d + " }"); }
    { std::string c = "global gKbCapKey = { "; for (int i = 0; i < 24; i++) { if (i) c += ", "; c += std::string("\"") + KB_INPUTS[i].cap + "\""; } a(c + " }"); }
    a("function Kb(cmd)"); a("gPlayerProfile:SetTimeZone(\"kb:\" .. cmd)"); a("return gPlayerProfile:GetTimeZone()"); a("end");
    a("function CleanCaption(s)"); a("local out = gsub(s, \"<br>\", \" \")"); a("return out"); a("end");
    a("function SetCaptions()"); a("local desc = nil"); a("local ix = gPlayerProfile:GetControllerScheme() + 1");
    a("if gKbDesc[ix] then desc = gKbDesc[ix] end"); a("if desc == nil then return end");
    a("for r = 1, getn(gKbCapKey) do"); a("local key = gKbCapKey[r]"); a("if key ~= \"\" then"); a("for k = 1, getn(desc) do");
    a("if desc[k][1] == key then"); a("gKbCapTags[r]:SetValue(CleanCaption(desc[k][2]))"); a("end"); a("end"); a("end"); a("end"); a("end");
    a("function Refresh()"); a("for r = 0, " + R + " do"); a("for s = 0, " + S + " do");
    a("local v = Kb(\"key \" .. r .. \" \" .. s)"); a("if Kb(\"dup \" .. r .. \" \" .. s) == \"1\" then v = v .. \" !\" end");
    a("gKbTags[r * " + N + " + s + 1]:SetValue(v)"); a("end"); a("end"); a("RefreshHint()"); a("end");
    a("function RefreshHint()"); a("local st = Kb(\"state\")"); a("if st == \"capture\" then");
    a("gKbHint:SetValue(\"Press a key or mouse button. \" .. Kb(\"caphint\"))"); a("elseif st == \"conflict\" then");
    a("gKbHint:SetValue(\"Key \" .. Kb(\"cf key\") .. \" is bound twice.\")"); a("elseif st == \"timeout\" then");
    a("gKbHint:SetValue(\"No key pressed.\")"); a("else"); a("gKbHint:SetValue(Kb(\"hint\"))"); a("end"); a("end");
    a("function OnEnterPage()");
    a("gBrowserContext:SetPageValue(\"buttonlegend.ok\", \"REBIND KEY\")");
    a("gBrowserContext:SetPageValue(\"buttonlegend.square\", \"2ND KEY\")");
    a("gBrowserContext:SetPageValue(\"buttonlegend.triangle\", \"DEFAULTS\")");
    a("gBrowserContext:SetPageValue(\"buttonlegend.cancel\", \"BACK\")");
    a("gBrowserContext:SetPageValue(\"buttonlegend.updown\", \"NAVIGATE\")");
    a("gKbList = gBrowser:GetTagByName(\"listKeyboard\")"); a("gKbHint = gBrowser:GetTagByName(\"kbHint\")");
    a("for r = 0, " + R + " do"); a("gKbCapTags[r + 1] = gBrowser:GetTagByName(\"kbc_\" .. r)"); a("for s = 0, " + S + " do");
    a("gKbTags[r * " + N + " + s + 1] = gBrowser:GetTagByName(\"kbk_\" .. r .. \"_\" .. s)"); a("end"); a("end");
    a("SetCaptions()"); a("gKbList:SetOnChange(\"keyboardscript.OnRowChange\")"); a("gKbList:SetSelected(true)"); a("Refresh()");
    a("Kb(\"sel 0 0\")"); a("end");
    a("function OnLeavePage()"); a("Kb(\"cancel\")"); a("end");
    a("function OnRowChange()"); a("local r = gKbList:GetSelectedIndex()"); a("if r >= 0 then Kb(\"sel \" .. r .. \" 0\") end"); a("end");
    a("function Capture(s)"); a("local r = gKbList:GetSelectedIndex()"); a("if r >= 0 then"); a("Kb(\"sel \" .. r .. \" \" .. s)");
    a("Kb(\"capture \" .. r .. \" \" .. s)"); a("Refresh()"); a("end"); a("end");
    a("function CaptureFirst()"); a("Capture(0)"); a("end");
    a("function CaptureSecond()"); a("Capture(1)"); a("end");
    a("function ResetDefaults()"); a("Kb(\"reset\")"); a("Refresh()"); a("end");
    a("function OnUpdatePage()"); a("local p = Kb(\"poll\")"); a("if p == \"changed\" then"); a("Refresh()");
    a("elseif p == \"busy\" then"); a("gKbBusy = true"); a("RefreshHint()"); a("end"); a("end");
    a("function ClosePage()"); a("Kb(\"cancel\")"); a("gBrowser:BackToPage(\"\")"); a("end");
    std::string o;
    for (size_t i = 0; i < L.size(); i++) { if (i) o += "\r\n"; o += L[i]; }
    return o + "\r\n";
}

inline std::string kb_body(const std::vector<std::string>& descs)
{
    std::vector<std::string> t;
    auto a = [&](const std::string& s) { t.push_back(s); };
    auto I = [](long v) { return std::to_string(v); };
    a("<_p name=\"panelKeyboard\" c=\"_Normal\" p=\"196,196,956,410\" a=\"default\" g=\"0\" m=\"true\" />");
    a("<_t name=\"kbHeadAction\" c=\"_Small\" p=\"14,10," + I(KB_COL_CAP - KB_COL_NAME) + ",29\" l=\"#FFFFFFC0\" >INPUT</_t>");
    a("<_t name=\"kbHeadFunction\" c=\"_Small\" p=\"" + I(14 + KB_COL_CAP) + ",10,320,29\" l=\"#FFFFFFC0\" >FUNCTION</_t>");
    a("<_t name=\"kbHeadKey0\" c=\"_Small\" p=\"" + I(14 + KB_COL_K0) + ",10,200,29\" l=\"#FFFFFFC0\" >KEY</_t>");
    a("<_t name=\"kbHeadKey1\" c=\"_Small\" p=\"" + I(14 + KB_COL_K1) + ",10,200,29\" l=\"#FFFFFFC0\" >2ND KEY</_t>");
    a("<_l name=\"listKeyboard\" c=\"TransparentListScroll\" p=\"14," + I(KB_LIST_Y) + ",928," + I(KB_LIST_H) +
      "\" a=\"true\" bn=\"DOWN_BUTTON\" bp=\"UP_BUTTON\" g=\"1\" m=\"true\" sa=\"300\" sh=\"false\" />");
    for (int r = 0; r < 24; r++) {
        const long g = 2 + r;
        a("<_i name=\"kbrow_" + I(r) + "\" c=\"_Medium\" p=\"," + I(r * KB_ROW_H) + ",," + I(KB_ROW_H) + "\" g=\"" + I(g) +
          "\" h=\"static://script.keyboardscript.CaptureFirst()\" />");
        a("<_t name=\"kbn_" + I(r) + "\" c=\"_Medium\" >" + attr(KB_INPUTS[r].shown) + "</_t>");
        a("<_t name=\"kbc_" + I(r) + "\" c=\"_Small\" p=\"" + I(KB_COL_CAP) + ",,320,\" a=\"true\" >" + attr(upper(KB_INPUTS[r].label)) + "</_t>");
        a("<_t name=\"kbk_" + I(r) + "_0\" c=\"_Medium\" p=\"" + I(KB_COL_K0) + ",,200,\" a=\"true\" />");
        a("<_t name=\"kbk_" + I(r) + "_1\" c=\"_Medium\" p=\"" + I(KB_COL_K1) + ",,200,\" a=\"true\" />");
        a("<_i: name=\"!\" g=\"" + I(g) + "\" />");
    }
    a("<_l: name=\"!\" g=\"1\" />");
    a("<_t name=\"kbHint\" c=\"_Small\" p=\"14," + I(KB_LIST_Y + KB_LIST_H + 4) + ",928,29\" ah=\"left\" av=\"middle\" l=\"#FFFFFFC0\" />");
    a("<_p: name=\"!\" g=\"0\" />");
    /* CDATA as in the game's own script blocks: the captions hold "<br>", which a plain <_s> body would end at
     * (kbpage.py wrote the body plain; a test run showed a black page because no script ran) */
    a("<_s name=\"keyboardscript\" ><![CDATA[\r\n" + kb_script(descs) + "]]></_s>");
    a("<_q a=\"static://script.keyboardscript.ClosePage\" b=\"CIRCLE_BUTTON\" name=\"quicklink.back\" />");
    a("<_q a=\"static://script.keyboardscript.CaptureSecond\" b=\"SQUARE_BUTTON\" name=\"quicklink.second\" />");
    a("<_q a=\"static://script.keyboardscript.ResetDefaults\" b=\"TRIANGLE_BUTTON\" name=\"quicklink.defaults\" />");
    std::string o;
    for (size_t i = 0; i < t.size(); i++) { if (i) o += " "; o += t[i]; }
    return o;
}

inline std::string keyboard_page(const std::string& gamma_text, const std::vector<std::string>& descs, bool ingame)
{
    const std::string& t = gamma_text;
    size_t head_end = once(t, "<_p name=\"panelGammaCorrect\"", "gamma content panel");
    size_t leg = once(t, "<_g name=\"ButtonLegend\"", "gamma button legend");
    std::string head = t.substr(0, head_end), tail = t.substr(leg);
    /* <PAGEID name="kin-preparsed_menu_options_gammacorrection(_ingame)?" /> */
    {
        const std::string a1 = "<PAGEID name=\"kin-preparsed_menu_options_gammacorrection\" />";
        const std::string a2 = "<PAGEID name=\"kin-preparsed_menu_options_gammacorrection_ingame\" />";
        std::vector<size_t> h1 = find_all(head, a1), h2 = find_all(head, a2);
        if (h1.size() + h2.size() != 1) throw Anchor("gamma PAGEID: " + std::to_string(h1.size() + h2.size()) + " matches (need exactly 1)");
        const bool ig = !h2.empty();
        const size_t p = ig ? h2[0] : h1[0], n = ig ? a2.size() : a1.size();
        head = head.substr(0, p) + "<PAGEID name=\"kin-preparsed_menu_options_" + KB_PAGE + (ig ? "_ingame" : "") + "\" />" + head.substr(p + n);
    }
    /* (<_t name="pageTitle"[^>]*>)[^<]*(</_t>) */
    {
        std::vector<std::pair<size_t, size_t>> hits;   /* (end of open tag, start of </_t>) */
        std::vector<size_t> starts;
        for (size_t p : find_all(head, "<_t name=\"pageTitle\"")) {
            size_t k = head.find('>', p);
            if (k == std::string::npos) continue;
            size_t c = k + 1;
            while (c < head.size() && head[c] != '<') c++;
            if (!at(head, c, "</_t>")) continue;
            hits.push_back({k + 1, c}); starts.push_back(p);
        }
        if (hits.size() != 1) throw Anchor("gamma page title: " + std::to_string(hits.size()) + " matches (need exactly 1)");
        head = head.substr(0, hits[0].first) + attr(KB_TITLE) + head.substr(hits[0].second);
    }
    std::string out = head + kb_body(descs) + " " + tail;
    std::vector<std::string> bad = check(out);
    if (!bad.empty()) { std::string s = "generated page: "; for (size_t i = 0; i < bad.size(); i++) { if (i) s += "; "; s += bad[i]; } throw Anchor(s); }
    size_t pid = out.find("PAGEID name=\"");
    size_t pe = pid == std::string::npos ? pid : out.find('"', pid + 13);
    const bool has_ingame = pid != std::string::npos && pe != std::string::npos && out.substr(pid + 13, pe - pid - 13).find("ingame") != std::string::npos;
    if (ingame != has_ingame) throw Anchor("gamma page and --ingame disagree");
    return out;
}

inline std::string options_row()
{
    return std::string("{ title = \"") + KB_ROW_TITLE + "\", link = \"static://script.optionsmenuscript.GoToKeyboardPage()\", "
           "description = \"" + KB_ROW_DESC + "\", links = {}}";
}

inline std::string goto_function(const std::string& nl)
{
    std::string s = std::string("function GoToKeyboardPage()") + nl +
        "gBrowserContext:SetApplicationValue(\"" + KB_FLAG + "\", \"true\")" + nl +
        "CopyOptionSettings()" + nl + "if gGame then" + nl +
        "gBrowser:OpenPage(\"" + KB_PAGE_URL_INGAME + "\")" + nl + "else" + nl +
        "gBrowser:OpenPage(\"" + KB_PAGE_URL + "\")" + nl + "end" + nl + "end" + nl;
    return s;
}

inline std::string patch_options(const std::string& text)
{
    std::string t = text;
    if (t.find("GoToKeyboardPage") != std::string::npos) throw Anchor("page already has the KEYBOARD row");
    const std::string nl = t.find("\r\n") != std::string::npos ? "\r\n" : "\n";
    /* \{ title = "CONTROLS", link = "static://script\.\w+\.ShowOptionsSubMenu\(3\)", sub_menu_list="listControlSettings",
     *   description = "[^"]*", links = \{\}\}, */
    std::vector<size_t> ends;
    const std::string a = "{ title = \"CONTROLS\", link = \"static://script.";
    for (size_t p : find_all(t, a)) {
        size_t q = p + a.size(), w = q;
        while (w < t.size() && is_word(t[w])) w++;
        if (w == q) continue;
        const char* mid = ".ShowOptionsSubMenu(3)\", sub_menu_list=\"listControlSettings\", description = \"";
        if (!at(t, w, mid)) continue;
        size_t d = w + strlen(mid);
        while (d < t.size() && t[d] != '"') d++;
        if (!at(t, d, "\", links = {}},")) continue;
        ends.push_back(d + strlen("\", links = {}},"));
    }
    if (ends.size() != 1) throw Anchor("CONTROLS row: " + std::to_string(ends.size()) + " matches (need exactly 1)");
    t = t.substr(0, ends[0]) + nl + options_row() + "," + t.substr(ends[0]);
    size_t g = once(t, "function GoToGammaCorrection()", "GoToGammaCorrection");
    t = t.substr(0, g) + goto_function(nl) + t.substr(g);
    /* gOptionsTable = gMenu\[(\d+)\] */
    long n = -1;
    {
        std::vector<long> v;
        for (size_t p : find_all(t, "gOptionsTable = gMenu[")) {
            long x; size_t e;
            if (digits(t, p + strlen("gOptionsTable = gMenu["), &x, &e) && at(t, e, "]")) v.push_back(x);
        }
        if (v.size() != 1) throw Anchor("gOptionsTable: " + std::to_string(v.size()) + " matches (need exactly 1)");
        n = v[0];
    }
    size_t m = once(t, "if gBrowserContext:GetApplicationValue(\"options.returningfromgammacorrection\") == \"true\" then",
                    "returningfromgammacorrection branch");
    /* The return from the Keyboard page re-enters the options list the way the game's own return from the gamma page
     * does (`ShowOptionsSubMenu(2)` + `SetFocusSubMenu(gList)`), on the CONTROLS row's list (the anchor above pins it
     * as ShowOptionsSubMenu(3)); BACK then closes it onto the options list (GoBack -> HideListCurrentOptions).
     * kbpage.py's hook (gList:SetSelectedIndex, RenderSubMenu, SetSelectedIndex(3)) left no focus: the list's
     * on-change handler cleared it, and the next BACK left the main menu for the start screen. */
    (void)n;
    const std::string hook = std::string("if gBrowserContext:GetApplicationValue(\"") + KB_FLAG + "\") == \"true\" then" + nl +
        "gBrowserContext:SetApplicationValue(\"" + KB_FLAG + "\", \"false\")" + nl +
        "ShowOptionsSubMenu(3)" + nl +
        "SetFocusSubMenu(gList)" + nl + "elseif ";
    t = t.substr(0, m) + hook + t.substr(m + 3);
    return t;
}

}  // namespace kz2mt
