/* Spu rounds 18-19 host test: the native gates' flag rule (port/kz2/spu/native_flags.h) with a fake environment.
 * every Gfx.Post flag on by default for the slots recorded in play, a flag's own 0 turns its job off (also
 * under KZ2_NATIVE_JOB_POST=1), KZ2_NATIVE_JOB_POST=0 turns everything off, slots without a recorded-in-play
 * equality (the shared kernels' copies in the other post images, three blur variants) off unless asked for. An earlier change:
 * EdgeAnim (75, 76) and VertexJob's .bss clear (77) on by default, VertexJob's memcpy (78) off. No game data. */
#include "native_flags.h"

#include <stdio.h>

static const char* g_env[8][2];
static const char* fake_get(const char* k)
{
    for (int i = 0; i < 8 && g_env[i][0]; i++)
        if (!strcmp(g_env[i][0], k)) return g_env[i][1];
    return NULL;
}
static void setenv_(int i, const char* k, const char* v) { g_env[i][0] = k; g_env[i][1] = v; g_env[i + 1][0] = NULL; }
static void clear(void) { g_env[0][0] = NULL; }

static int fails;
static void expect(const char* what, const char* env, const char* job, int slot, const char* want)
{
    char buf[96];
    const char* got = kz2_native_enabled_by(env, job, slot, fake_get, buf, sizeof buf);
    if ((got == NULL) != (want == NULL) || (got && strcmp(got, want))) {
        printf("FAIL %s: %s %s slot %d -> %s (want %s)\n", what, env, job, slot, got ? got : "off", want ? want : "off");
        fails++;
    }
}

/* The flags that are on by default and one recorded slot of each. */
static const struct { const char* flag; const char* job; int slot; } k_def[] = {
    { "KZ2_NATIVE_JOB_DOF", "Gfx.Post.DepthOfField", 0 },
    { "KZ2_NATIVE_JOB_UPSAMPLE", "Gfx.Post.Upsample", 3 },
    { "KZ2_NATIVE_JOB_POSTMIX", "Gfx.Post.Upsample", 8 },
    { "KZ2_NATIVE_JOB_BLUR", "Gfx.Post.VBlur", 52 },
    { "KZ2_NATIVE_JOB_BLOOM", "Gfx.Post.BloomCapture", 64 },
    { "KZ2_NATIVE_JOB_MODULATE", "Gfx.Post.Modulate", 66 },
    { "KZ2_NATIVE_JOB_BLOOMINT", "Gfx.Post.BloomIntegrate", 67 },
    { "KZ2_NATIVE_JOB_ILR", "Gfx.Post.ILR", 68 },
    { "KZ2_NATIVE_JOB_VIGNETTE", "Gfx.Post.Vignette", 69 },
    { "KZ2_NATIVE_JOB_DEPTHTOFUZZY", "Gfx.Post.DepthToFuzzy", 70 },
    { "KZ2_NATIVE_JOB_DOWNSAMPLE", "Gfx.Post.Downsample", 71 },
    { "KZ2_NATIVE_JOB_ZERO", "Gfx.Post.Zero", 73 },
    { "KZ2_NATIVE_JOB_DOFPASS", "Gfx.Post.DepthOfField", 74 },
};
#define NDEF (sizeof k_def / sizeof k_def[0])

int main(void)
{
    char want[96];
    for (size_t i = 0; i < NDEF; i++) {
        const char *f = k_def[i].flag, *j = k_def[i].job;
        const int s = k_def[i].slot;
        snprintf(want, sizeof want, "%s default", f);
        clear();
        expect("nothing set: on by default", f, j, s, want);
        setenv_(0, f, "");
        expect("empty: default", f, j, s, want);
        setenv_(0, f, "0");
        expect("flag=0: off", f, j, s, NULL);
        setenv_(0, "KZ2_NATIVE_JOB_POST", "1"); setenv_(1, f, "0");
        expect("POST=1 and flag=0: off", f, j, s, NULL);
        snprintf(want, sizeof want, "%s=1", f);
        setenv_(0, f, "1");
        expect("flag=1: on", f, j, s, want);
        setenv_(0, "KZ2_NATIVE_JOB_POST", "0");
        expect("POST=0: off", f, j, s, NULL);
        setenv_(0, "KZ2_NATIVE_JOB_POST", "0"); setenv_(1, f, "1");
        expect("POST=0 and flag=1: off", f, j, s, NULL);
        setenv_(0, "KZ2_NATIVE_JOB_POST", "1");
        expect("POST=1: on", f, j, s, "KZ2_NATIVE_JOB_POST=1");
        setenv_(0, "KZ2_NATIVE_JOB_POST", "default");
        snprintf(want, sizeof want, "%s default", f);
        expect("POST=default (the A/B's old side): default", f, j, s, want);
        /* another job's 0 leaves this one on */
        setenv_(0, k_def[(i + 1) % NDEF].flag, "0");
        expect("another flag=0: still default", f, j, s, want);
    }
    /* slots without a recorded-in-play equality: off by default, on when asked */
    const char* MIX = "KZ2_NATIVE_JOB_POSTMIX";
    clear();
    expect("Modulate's blend copy (never called in play): off", MIX, "Gfx.Post.Modulate", 10, NULL);
    expect("the 15th addh copy: off", MIX, "Gfx.Post.DepthToFuzzy", 51, NULL);
    expect("VBlur variant c (never called): off", "KZ2_NATIVE_JOB_BLUR", "Gfx.Post.VBlur", 54, NULL);
    expect("HBlur 16-bit clamped (never called): off", "KZ2_NATIVE_JOB_BLUR", "Gfx.Post.HBlur", 62, NULL);
    setenv_(0, MIX, "1");
    expect("POSTMIX=1 turns the unrecorded copy on", MIX, "Gfx.Post.Modulate", 10, "KZ2_NATIVE_JOB_POSTMIX=1");
    setenv_(0, "KZ2_NATIVE_JOB_POST", "1");
    expect("POST=1 turns the unrecorded copy on", MIX, "Gfx.Post.Modulate", 10, "KZ2_NATIVE_JOB_POST=1");
    /* two flags on one entry: DOF's blend (slot 2, DOF|POSTMIX) */
    const char *DB = "KZ2_NATIVE_JOB_DOF|KZ2_NATIVE_JOB_POSTMIX", *DJ = "Gfx.Post.DepthOfField";
    clear();
    expect("DOF blend: default", DB, DJ, 2, "KZ2_NATIVE_JOB_DOF default");
    setenv_(0, "KZ2_NATIVE_JOB_DOF", "0");
    expect("DOF blend, DOF=0: off", DB, DJ, 2, NULL);
    setenv_(0, MIX, "0");
    expect("DOF blend, POSTMIX=0: off", DB, DJ, 2, NULL);
    setenv_(0, MIX, "0"); setenv_(1, "KZ2_NATIVE_JOB_DOF", "1");
    expect("DOF blend, POSTMIX=0 DOF=1: an explicit 1 wins", DB, DJ, 2, "KZ2_NATIVE_JOB_DOF=1");
    /* non-post jobs: EdgeAnim's kernels and VertexJob's .bss clear on by default, POST=0/1 do not reach
     * them, their own 0 turns them off; VertexJob's memcpy (recorded, flag not default-on) off unless asked for */
    const char *EA = "KZ2_NATIVE_JOB_EDGEANIM", *EK = "KZ2_NATIVE_JOB_EDGEANIM_KEYS|KZ2_NATIVE_JOB_EDGEANIM";
    clear();
    expect("EdgeAnim on by default", EA, "Anim.EdgeAnim", 75, "KZ2_NATIVE_JOB_EDGEANIM default");
    expect("EdgeAnim keys on by default", EK, "Anim.EdgeAnim", 76, "KZ2_NATIVE_JOB_EDGEANIM default");
    expect("VJCLEAR on by default", "KZ2_NATIVE_JOB_VJCLEAR", "Particles.VertexJob", 77, "KZ2_NATIVE_JOB_VJCLEAR default");
    expect("VJCOPY off by default", "KZ2_NATIVE_JOB_VJCOPY", "Particles.VertexJob", 78, NULL);
    expect("EdgeAnim on an unrecorded slot: off", EA, "Anim.EdgeAnim", 99, NULL);
    setenv_(0, "KZ2_NATIVE_JOB_POST", "0");
    expect("POST=0 leaves EdgeAnim on", EA, "Anim.EdgeAnim", 75, "KZ2_NATIVE_JOB_EDGEANIM default");
    setenv_(0, "KZ2_NATIVE_JOB_POST", "1");
    expect("POST=1 leaves EdgeAnim default", EA, "Anim.EdgeAnim", 75, "KZ2_NATIVE_JOB_EDGEANIM default");
    expect("POST=1 leaves VJCOPY off", "KZ2_NATIVE_JOB_VJCOPY", "Particles.VertexJob", 78, NULL);
    setenv_(0, EA, "0");
    expect("EDGEANIM=0 off", EA, "Anim.EdgeAnim", 75, NULL);
    expect("EDGEANIM=0 turns the keys off", EK, "Anim.EdgeAnim", 76, NULL);
    setenv_(0, "KZ2_NATIVE_JOB_EDGEANIM_KEYS", "0");
    expect("EDGEANIM_KEYS=0: keys off", EK, "Anim.EdgeAnim", 76, NULL);
    expect("EDGEANIM_KEYS=0 leaves the decoder on", EA, "Anim.EdgeAnim", 75, "KZ2_NATIVE_JOB_EDGEANIM default");
    setenv_(0, "KZ2_NATIVE_JOB_VJCOPY", "1");
    expect("VJCOPY=1 on", "KZ2_NATIVE_JOB_VJCOPY", "Particles.VertexJob", 78, "KZ2_NATIVE_JOB_VJCOPY=1");
    /* the default list is exactly k_def's flags */
    const size_t n = sizeof kz2_native_default_on / sizeof kz2_native_default_on[0];
    if (n != NDEF + 2) {   /* + EDGEANIM, VJCLEAR */
        printf("FAIL the default-on list has %zu flags, the test %zu\n", n, NDEF + 2);
        fails++;
    }
    for (size_t i = 0; i < NDEF; i++)
        if (!kz2_native_is_default_on(k_def[i].flag)) {
            printf("FAIL %s not in the default-on list\n", k_def[i].flag);
            fails++;
        }
    if (fails) return 1;
    printf("PASS test_native_flags (%zu default-on flags)\n", NDEF);
    return 0;
}
