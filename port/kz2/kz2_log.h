/* Killzone 2 port: a stdio stand-in for KZ3's file logger (Project Helghast port/kz3/kz3_log.h), so the boot code
 * copied from port/kz3/main.cpp keeps its log calls. Log files: kz2_session_log.c copies stdout/stderr into
 * <exe dir>/logs/kz2-*.log. ENHANCEMENT candidate: the real logger for levels and crash files (patches 2030/2032 call
 * into it only with KZ3_LOG_REDIRECT_STDIO, not defined here). */
#pragma once
#include <stdio.h>
#define KZ2_LOGE(tag, ...) (fprintf(stderr, "[E][%s] ", tag), fprintf(stderr, __VA_ARGS__), fputc('\n', stderr))
#define KZ2_LOGI(tag, ...) (fprintf(stderr, "[I][%s] ", tag), fprintf(stderr, __VA_ARGS__), fputc('\n', stderr))
#include "kz2_session_log.h"   /* the session log file: kz2_log_shutdown drains its pipe */
static inline void kz2_log_shutdown(void) { fflush(stdout); fflush(stderr); kz2_session_log_flush(2000); }
static inline void kz2_log_set_thread_label(const char* label) { (void)label; }
