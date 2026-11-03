/* Host test for patch 6051 (FSR 1 as an in-game option, from KZ3 patch 2145): the live choice (rsx_upscale_live_set /
 * _get, environment fallback), the off rule (NULL context = no pass), which size pairs want a pass, the FSR 1
 * constants and the HLSL assembly. A fake backend stands in for D3D12. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rsx_upscale.h"

static int fails;
#define OK(c, what) do { if (!(c)) { printf("FAIL %s\n", what); fails++; } } while (0)

static int g_evals;
static void* f_create(void* d, const rsx_upscale_config* c) { (void)d; (void)c; return (void*)1; }
static void f_destroy(void* be, void (*r)(void*, void*), void* u) { (void)be; (void)r; (void)u; }
static float g_last_sh = -1.0f;
static int f_eval(void* be, const rsx_upscale_eval* e, float sh, rsx_upscale_result* res, void (*r)(void*, void*), void* u)
{
    (void)be; (void)r; (void)u;
    g_evals++; g_last_sh = sh;
    res->resource = (void*)2; res->width = e->output_width; res->height = e->output_height;
    return 1;
}
static const rsx_upscale_ops fake = { f_create, f_destroy, f_eval };

int main(int argc, char** argv)
{
    int be = -1; float sh = -1.0f;
    if (argc > 1 && !strcmp(argv[1], "env")) {   /* the first get without a set reads the environment */
        rsx_upscale_live_get(&be, &sh);
        printf("%d %.2f\n", be, sh);
        return 0;
    }
    rsx_upscale_live_set(RSX_UPSCALE_FSR1, 1.0f);
    rsx_upscale_live_get(&be, &sh);
    OK(be == RSX_UPSCALE_FSR1 && sh == 1.0f, "live set fsr1 1.0");
    rsx_upscale_live_set(RSX_UPSCALE_DLSS, 9.0f);
    rsx_upscale_live_get(&be, &sh);
    OK(be == RSX_UPSCALE_NONE && sh == 2.0f, "unimplemented backend -> none, sharpness clamped to 2");
    rsx_upscale_live_set(RSX_UPSCALE_FSR1, NAN);
    rsx_upscale_live_get(&be, &sh);
    OK(sh == RSX_UPSCALE_SHARPNESS_DEFAULT, "NaN sharpness -> 0.2");
    rsx_upscale_live_set(-3, 0.5f);
    rsx_upscale_live_get(&be, NULL);
    OK(be == RSX_UPSCALE_NONE, "bad id -> none");
    /* off = no context, nothing wanted */
    rsx_upscale_config c = { RSX_UPSCALE_NONE, 0.2f };
    OK(rsx_upscale_create(&c, NULL) == NULL && !rsx_upscale_wants_pass(NULL, 1280, 720, 1920, 1080), "off: no context, no pass");
    rsx_upscale_set_test_ops(&fake);
    c.backend = RSX_UPSCALE_FSR1;
    rsx_upscale* u = rsx_upscale_create(&c, NULL);
    OK(u != NULL, "fsr1 context (fake backend)");
    OK(rsx_upscale_wants_pass(u, 1280, 720, 1920, 1080) && rsx_upscale_wants_pass(u, 1280, 720, 1280, 1080), "enlarging pairs want a pass");
    OK(!rsx_upscale_wants_pass(u, 1280, 720, 1280, 720) && !rsx_upscale_wants_pass(u, 1280, 720, 960, 1080), "equal or smaller: no pass");
    rsx_upscale_eval e; memset(&e, 0, sizeof e);
    rsx_upscale_result r;
    e.cmd_list = (void*)3; e.input.resource = (void*)4; e.input.width = 1280; e.input.height = 720;
    e.output_width = 2560; e.output_height = 1440; e.sharpness = 1.0f;
    OK(rsx_upscale_evaluate(u, &e, &r) && g_evals == 1 && g_last_sh == 1.0f && r.width == 2560, "evaluate passes the live sharpness");
    e.sharpness = -1.0f;
    OK(rsx_upscale_evaluate(u, &e, &r) && g_last_sh == 0.2f && rsx_upscale_passes(u) == 2, "negative sharpness: the configured one");
    rsx_upscale_destroy(u);
    /* FSR 1 constants: EASU con0 = input/output scale (as float bits), RCAS con0 = exp2(-sharpness) */
    uint32_t easu[16], rcas[4];
    rsx_upscale_fsr1_constants(1280, 720, 2560, 1440, 0.0f, easu, rcas);
    float f0; memcpy(&f0, &easu[0], 4);
    float r0; memcpy(&r0, &rcas[0], 4);
    OK(fabsf(f0 - 0.5f) < 1e-6f && fabsf(r0 - 1.0f) < 1e-6f, "EASU scale 0.5 and RCAS 2^-0 for 2x at sharpness 0");
    rsx_upscale_fsr1_constants(1280, 720, 2560, 1440, 1.0f, easu, rcas);
    memcpy(&r0, &rcas[0], 4);
    OK(fabsf(r0 - 0.5f) < 1e-6f, "RCAS 2^-1 at sharpness 1");
    size_t n = 0;
    char* src = rsx_upscale_fsr1_hlsl_source(&n);
    OK(src && n > 10000 && strstr(src, "mainCS") && strstr(src, "FsrEasuF") && strstr(src, "FsrRcasF"), "HLSL holds both passes");
    free(src);
    printf(fails ? "test_upscale_live: FAIL\n" : "test_upscale_live: ok\n");
    return fails ? 1 : 0;
}
