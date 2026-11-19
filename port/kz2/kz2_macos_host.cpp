/* Main-run-loop integration informed by Afro Samurai's port/main.cpp (Erik
 * Martins, MIT), also used in the author's Deadpool and Resistance ports.
 * Own implementation: no lifted game code. See NOTICE.md. */
#include "kz2_macos_host.h"
#include <CoreFoundation/CoreFoundation.h>
#include <pthread.h>
#include <atomic>
#include <cstdio>

int kz2_macos_run_guest(uint32_t entry, uint32_t stack_top,
                        int (*run)(uint32_t, uint32_t))
{
    if (!pthread_main_np() || !run) {
        std::fprintf(stderr, "[boot] macOS guest runner requires the main thread and an entry function\n");
        return 1;
    }
    struct Boot {
        uint32_t entry, stack;
        int (*run)(uint32_t, uint32_t);
        int result = 1;
        std::atomic<bool> done{false};
    } boot{entry, stack_top, run};
    pthread_attr_t attr;
    int error = pthread_attr_init(&attr);
    if (error) return 1;
    // Lifted guest calls use substantially more host stack than native code.
    error = pthread_attr_setstacksize(&attr, 256u * 1024u * 1024u);
    pthread_t thread;
    if (!error) error = pthread_create(&thread, &attr, [](void* arg) -> void* {
        auto& b = *static_cast<Boot*>(arg);
        b.result = b.run(b.entry, b.stack);
        b.done.store(true, std::memory_order_release);
        CFRunLoopWakeUp(CFRunLoopGetMain());
        return nullptr;
    }, &boot);
    pthread_attr_destroy(&attr);
    if (error) {
        std::fprintf(stderr, "[boot] could not start macOS guest thread: %d\n", error);
        return 1;
    }
    while (!boot.done.load(std::memory_order_acquire))
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.05, false);
    pthread_join(thread, nullptr);
    return boot.result;
}
