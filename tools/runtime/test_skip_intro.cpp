/* Test the real settings loader/bridge, with renderer entry points stubbed. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int applied;
extern "C" void kz2_fov_set(double) { applied++; }
extern "C" void rsx_upscale_live_set(int, float) { applied++; }
extern "C" void rsx_live_draw_set_vsync(int) { applied++; }
extern "C" int kz2_skip_intro_enabled(void);
extern "C" int kz2_port_settings_cmd(const char*, char*, size_t);
static void check(bool ok, const char* text) { if (!ok) { fprintf(stderr, "FAIL skip-intro: %s\n", text); exit(1); } }
int main(int argc, char** argv)
{
    check(argc == 2, "expected initial value");
    const int before = atoi(argv[1]);
    check(kz2_skip_intro_enabled() == before, "environment/default precedence");
    const int calls = applied;
    char reply[80];
    check(kz2_port_settings_cmd("cycle skip_intro", reply, sizeof reply) == 1, "command handled");
    check(kz2_skip_intro_enabled() == !before, "next-start choice changed");
    check(applied == calls, "boot-only change reapplied unrelated renderer state");
    kz2_port_settings_cmd("reset", reply, sizeof reply);
    check(kz2_skip_intro_enabled() == 0, "reset restores the original intro");
    puts("PASS skip-intro settings, boot-only apply and reset");
}
