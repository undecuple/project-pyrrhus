/* Spu an earlier change host test: the same-run toggle's slot list and phase rule (port/kz2/spu/native_toggle.h). */
#include "native_toggle.h"

#include <stdio.h>

static int fails;
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

int main(void)
{
    unsigned char m[128];
    CHECK(kz2_native_toggle_parse("75,76", m, 128) == 2 && m[75] && m[76] && !m[74] && !m[77]);
    CHECK(kz2_native_toggle_parse("75-77", m, 128) == 3 && m[75] && m[76] && m[77] && !m[78]);
    CHECK(kz2_native_toggle_parse("77,75-76,76", m, 128) == 3);
    CHECK(kz2_native_toggle_parse("0", m, 128) == 1 && m[0]);
    CHECK(kz2_native_toggle_parse("127", m, 128) == 1 && m[127]);
    CHECK(kz2_native_toggle_parse("128", m, 128) == -1 && !m[127]);
    CHECK(kz2_native_toggle_parse("76-75", m, 128) == -1);
    CHECK(kz2_native_toggle_parse("75,x", m, 128) == -1 && !m[75]);
    CHECK(kz2_native_toggle_parse("75;76", m, 128) == -1);
    CHECK(kz2_native_toggle_parse("-1", m, 128) == -1);
    CHECK(kz2_native_toggle_parse("", m, 128) == 0);
    CHECK(kz2_native_toggle_phase(0, 4000) == 0 && kz2_native_toggle_phase(3999, 4000) == 0);
    CHECK(kz2_native_toggle_phase(4000, 4000) == 1 && kz2_native_toggle_phase(8000, 4000) == 2);
    CHECK((kz2_native_toggle_phase(12345, 4000) & 1) == 1);
    if (fails) return 1;
    puts("test_native_toggle: ok");
    return 0;
}
