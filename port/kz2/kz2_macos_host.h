#pragma once
#include <stdint.h>

/* Run the guest on a large-stack worker while the main thread services Cocoa. */
int kz2_macos_run_guest(uint32_t entry, uint32_t stack_top,
                        int (*run)(uint32_t, uint32_t));
