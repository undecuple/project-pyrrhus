/* Host test for port/kz2/kz2_log_redact.h (issue #16): the user's folders out of the game log.
 * Build + run: tools/release/test_log_redact.sh. No game data. */
#include <stdio.h>
#include <string.h>
#include "kz2_log_redact.h"

static int fails;
static void expect(const char* name, const char* got, const char* want)
{
    if (strcmp(got, want)) { printf("[FAIL] %s\n  got  '%s'\n  want '%s'\n", name, got, want); fails++; }
    else printf("[PASS] %s\n", name);
}

static const char* red(const kz2_redactor* rd, const char* in)
{
    static char out[4096];
    kz2_redact(rd, in, strlen(in), out, sizeof out);
    return out;
}

int main(void)
{
    kz2_redactor rd;
    char small[16];
    memset(&rd, 0, sizeof rd);
    /* the order the port adds them; the table sorts longest first */
    kz2_redact_add(&rd, "C:\\Users\\Bob\\AppData\\Roaming", "%APPDATA%");
    kz2_redact_add(&rd, "C:\\Users\\Bob\\AppData\\Local\\", "%LOCALAPPDATA%");
    kz2_redact_add(&rd, "C:\\Users\\Bob", "%USERPROFILE%");
    expect("APPDATA path (issue #16's [display] line)",
           red(&rd, "[display] C:\\Users\\Bob\\AppData\\Roaming\\Project Pyrrhus\\display.ini: mode borderless\n"),
           "[display] %APPDATA%\\Project Pyrrhus\\display.ini: mode borderless\n");
    expect("keybinds line, other case",
           red(&rd, "[keybinds] c:\\users\\bob\\appdata\\roaming\\Project Pyrrhus\\keybinds.ini: read\n"),
           "[keybinds] %APPDATA%\\Project Pyrrhus\\keybinds.ini: read\n");
    expect("forward slashes (kz2_exe_dir's form)",
           red(&rd, "[log] session log: C:/Users/Bob/Games/Project Pyrrhus/build/logs/kz2-1.log\n"),
           "[log] session log: %USERPROFILE%/Games/Project Pyrrhus/build/logs/kz2-1.log\n");
    expect("LOCALAPPDATA (trailing separator dropped when added)",
           red(&rd, "x C:\\Users\\Bob\\AppData\\Local\\Temp\\a.txt"), "x %LOCALAPPDATA%\\Temp\\a.txt");
    expect("a longer user name is not cut", red(&rd, "C:\\Users\\Bobby\\x C:\\Users\\Bob.old\\y"),
           "C:\\Users\\Bobby\\x C:\\Users\\Bob.old\\y");
    expect("the folder itself at the end, in quotes", red(&rd, "home='C:\\Users\\Bob'"), "home='%USERPROFILE%'");
    expect("several on one line", red(&rd, "C:\\Users\\Bob\\a;C:\\Users\\Bob\\AppData\\Roaming\\b"),
           "%USERPROFILE%\\a;%APPDATA%\\b");
    expect("other paths untouched", red(&rd, "[boot] VFS root: C:\\KZ2\\Project Pyrrhus\\vfs\n"),
           "[boot] VFS root: C:\\KZ2\\Project Pyrrhus\\vfs\n");
    /* table rules */
    {
        kz2_redactor t;
        memset(&t, 0, sizeof t);
        int a = kz2_redact_add(&t, "C:\\", "%X%");
        int b = kz2_redact_add(&t, "", "%X%");
        int c = kz2_redact_add(&t, "C:\\Users\\Bob", "%USERPROFILE%");
        int d = kz2_redact_add(&t, "c:/users/bob/", "%USERPROFILE%");
        char got[64];
        snprintf(got, sizeof got, "%d%d%d%d count=%d", a, b, c, d, t.count);
        expect("too short, empty and duplicate folders are not added", got, "0010 count=1");
    }
    /* no rules: a copy */
    {
        kz2_redactor none;
        memset(&none, 0, sizeof none);
        expect("no rules: unchanged", red(&none, "C:\\Users\\Bob\\x"), "C:\\Users\\Bob\\x");
    }
    /* truncation stays NUL-terminated */
    kz2_redact(&rd, "C:\\Users\\Bob\\AppData\\Roaming\\Project Pyrrhus", 40, small, sizeof small);
    expect("output cap: truncated and terminated", small, "%APPDATA%\\Proje");
    /* line splitting for the copy thread */
    {
        char got[32];
        snprintf(got, sizeof got, "%zu %zu %zu", kz2_redact_line_end("ab\ncd\nef", 8), kz2_redact_line_end("abc", 3),
                 kz2_redact_line_end("a\n", 2));
        expect("line end: after the last newline, 0 without one", got, "6 0 2");
    }
    printf(fails ? "test_log_redact: FAIL\n" : "test_log_redact: PASS\n");
    return fails ? 1 : 0;
}
