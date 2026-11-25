# Killzone 2 port. From Project Helghast port/kz3/CMakeLists.txt, KZ3-only parts removed (PSARC VFS, KZ3 HLE glue,
# file logger, port/spu and port/net subprojects).
# Killzone 3 port host. Based on ps3recomp templates/project (MIT licence: third_party/ps3recomp/LICENSE).
# Lifted code: work/recomp (tools/lift.sh, not committed). Toolkit: third_party/ps3recomp (pinned).
cmake_minimum_required(VERSION 3.20)
# No VERSION here: kz2.exe's version is the payload's app.rc (generated
# from installer/app.rc.in by tools/release/release_version.py); nothing read PROJECT_VERSION.
project(kz2
    LANGUAGES C CXX
    DESCRIPTION "Recompiled PS3 game project (ps3recomp)"
)

# ---------------------------------------------------------------------------
# Standards
# ---------------------------------------------------------------------------
set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Prefer Ninja if available
if(NOT CMAKE_GENERATOR MATCHES "Ninja" AND NOT DEFINED ENV{CMAKE_GENERATOR})
    message(STATUS "Tip: use -G Ninja for faster builds")
endif()

# ---------------------------------------------------------------------------
# The two directories this project is built from
# ---------------------------------------------------------------------------
# PS3RECOMP_DIR is the toolkit checkout: include/, runtime/, libs/, tools/.
# RECOMP_DIR is where the lifter's output for THIS game lives. They are
# separate on purpose -- a port keeps its generated code in its own tree and
# points at whatever toolkit checkout it is building against:
#
#   cmake -B build -G Ninja \
#         -DPS3RECOMP_DIR=/path/to/ps3recomp \
#         -DRECOMP_DIR=/path/to/my_game/recompiled
#
if(NOT DEFINED PS3RECOMP_DIR)
    # The patched copy (third_party/ps3recomp + port/patches), made by tools/ps3recomp-patched.sh.
    get_filename_component(PS3RECOMP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../work/ps3recomp-patched" ABSOLUTE)
endif()
get_filename_component(PS3RECOMP_DIR "${PS3RECOMP_DIR}" ABSOLUTE)

set(RECOMP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../work/recomp" CACHE PATH
    "Directory holding the lifter's output: ppu_recomp.h and the lifted sources")
get_filename_component(RECOMP_DIR "${RECOMP_DIR}" ABSOLUTE)

message(STATUS "ps3recomp SDK:   ${PS3RECOMP_DIR}")
message(STATUS "Lifted output:   ${RECOMP_DIR}")

if(NOT EXISTS "${RECOMP_DIR}/ppu_recomp.h")
    message(FATAL_ERROR
        "No ppu_recomp.h in ${RECOMP_DIR}.\n"
        "That header and the lifted sources beside it are what "
        "tools/ppu_lifter.py writes. Run the lifter, drop its output there, "
        "or point -DRECOMP_DIR= at wherever it already is.")
endif()

# The lifted translation units. A game's lift is hundreds of generated files,
# so they are globbed rather than listed; re-run CMake after a fresh lift.
file(GLOB RECOMP_SOURCES CONFIGURE_DEPENDS
    "${RECOMP_DIR}/*.c"
    "${RECOMP_DIR}/*.cpp"
)
if(NOT RECOMP_SOURCES)
    message(FATAL_ERROR
        "${RECOMP_DIR} has a ppu_recomp.h but no .c or .cpp beside it. The "
        "lifted functions and the function table live in those; without them "
        "there is nothing to run.")
endif()
list(LENGTH RECOMP_SOURCES RECOMP_SOURCE_COUNT)
message(STATUS "Lifted sources:  ${RECOMP_SOURCE_COUNT} file(s)")

# ---------------------------------------------------------------------------
# ps3recomp runtime library
# ---------------------------------------------------------------------------
# Built from source as a subdirectory rather than imported as a prebuilt
# archive. A static library carries none of its own link requirements, so an
# imported one arrives without SDL2, pthreads, the Metal frameworks or the
# Winsock/XInput imports -- the link then fails on every platform for a
# different reason. add_subdirectory hands all of that over with the target.
#
# The LGPL decoders stay outside kz2.exe, as DLLs beside it that a user can
# replace:
#   - at3_standalone.dll: FFmpeg's ATRAC3/3+ decoder as extracted by PPSSPP
#     (third_party/at3_standalone, unmodified), linked dynamically (patch 6022);
#   - avcodec-63.dll / avutil-61.dll: FFmpeg, never linked, loaded at run time
#     by the toolkit's PS3RECOMP_FFMPEG_RUNTIME path for movie pictures
#     (cellVdec H.264) and sound (cellAdec AC3, patch 6023). Building needs
#     only FFmpeg's headers: KZ2_FFMPEG_INCLUDE_DIR (tools/build-kz2.sh points
#     it at the tools/runtime/ffmpeg-lgpl-win.nix output; the release's
#     first-run build, tools/release/firstrun.py, at the payload's
#     ffmpeg/include). Without the headers the decoders stay callback-only
#     (black pictures, silent AC3), so configure stops unless
#     KZ2_ALLOW_NO_FFMPEG=ON says that is meant (developer builds only).
#     Issue #16: v0.1.2's first-run build passed no
#     headers, only warned, and every player's kz2.exe ignored the DLLs.
set(PS3RECOMP_AT3_SHARED ON CACHE BOOL "at3_standalone as its own DLL" FORCE)
# BEGIN ffmpeg-headers (tools/release/test_ffmpeg_cmake.py configures this block on its own)
set(KZ2_FFMPEG_INCLUDE_DIR "" CACHE PATH "FFmpeg headers for the run-time loaded decoders (empty: none)")
option(KZ2_ALLOW_NO_FFMPEG "Build without FFmpeg (black movie pictures, silent AC3): developer builds only" OFF)
# The remote build (tools/remote/kz2remote.py) syncs the headers as work/ffmpeg-headers/ in the source tree; the
# server's configure line cannot carry this option, so that folder is the default when nothing was given.
if(NOT KZ2_FFMPEG_INCLUDE_DIR AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../../work/ffmpeg-headers/libavcodec/avcodec.h")
    get_filename_component(KZ2_FFMPEG_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../work/ffmpeg-headers" ABSOLUTE)
    message(STATUS "KZ2_FFMPEG_INCLUDE_DIR defaults to ${KZ2_FFMPEG_INCLUDE_DIR}")
endif()
if(KZ2_FFMPEG_INCLUDE_DIR)
    if(NOT EXISTS "${KZ2_FFMPEG_INCLUDE_DIR}/libavcodec/avcodec.h")
        message(FATAL_ERROR "KZ2_FFMPEG_INCLUDE_DIR=${KZ2_FFMPEG_INCLUDE_DIR} has no libavcodec/avcodec.h")
    endif()
    set(PS3RECOMP_FFMPEG_RUNTIME ON CACHE BOOL "FFmpeg loaded at run time" FORCE)
    set(PS3RECOMP_FFMPEG_INCLUDE_DIR "${KZ2_FFMPEG_INCLUDE_DIR}" CACHE PATH "FFmpeg headers" FORCE)
elseif(KZ2_ALLOW_NO_FFMPEG)
    set(PS3RECOMP_FFMPEG_RUNTIME OFF CACHE BOOL "FFmpeg loaded at run time" FORCE)
    message(WARNING "No KZ2_FFMPEG_INCLUDE_DIR (KZ2_ALLOW_NO_FFMPEG=ON): movies decode to black pictures and silent AC3")
else()
    message(FATAL_ERROR "No KZ2_FFMPEG_INCLUDE_DIR: kz2.exe would never load avcodec/avutil (black movies, silent "
                        "AC3). Pass -DKZ2_FFMPEG_INCLUDE_DIR=<folder holding libavcodec/avcodec.h> (the include/ of "
                        "tools/runtime/ffmpeg-lgpl-win.nix's output; a release payload's ffmpeg/include), or "
                        "-DKZ2_ALLOW_NO_FFMPEG=ON for a developer build without movies.")
endif()
# END ffmpeg-headers
# KZ2_FAST_FLAGS (fps-why 2026-11-24 R4; default OFF = the toolchain's flags, unchanged). The Nix
# cc-wrapper puts its hardening flags ahead of ours on every compile line (flake.nix sets no hardeningDisable):
# -fzero-call-used-regs=used-gpr (an xor-zeroing epilogue in every function), -fstack-clash-protection (page probes
# on every large frame) and -fno-omit-frame-pointer. ON appends -fzero-call-used-regs=skip
# -fno-stack-clash-protection -fomit-frame-pointer to every TU of this directory and of the toolkit below (the RSX
# walker in libs/video, the SPU and PPU lifts, the runtime); the last flag on the line wins. Kept:
# -fno-strict-overflow (dropping it changes what signed overflow compiles to; the runtime is not audited for that).
# A pure code-generation change, no semantics. Expected (ASSUMPTION, fps-why): 0.3-1.4 ms per heavy frame on the
# walker, judged on a paired A/B of walker us per draw. The flake-level equivalent (hardeningDisable =
# [ "zerocallusedregs" "stackclashprotection" ]) belongs to the maintainer's flake.nix.
option(KZ2_FAST_FLAGS "drop the Nix hardening flags that cost time (zero-call-used-regs, stack-clash probes, frame pointer)" OFF)
if(KZ2_FAST_FLAGS AND NOT MSVC)
    add_compile_options(-fzero-call-used-regs=skip -fno-stack-clash-protection -fomit-frame-pointer)
    message(STATUS "KZ2_FAST_FLAGS=ON: -fzero-call-used-regs=skip -fno-stack-clash-protection -fomit-frame-pointer")
endif()
add_subdirectory("${PS3RECOMP_DIR}" "${CMAKE_BINARY_DIR}/ps3recomp_sdk"
                 EXCLUDE_FROM_ALL)

# Shader translator identity (patch 6047): a hash of the renderer's sources (libs/video), compiled into
# rsx_live_draw.c as RSX_TRANSLATOR_ID and written into the PSO preload's key file, so a shader cache made by another
# build (an older version installed underneath) is discarded instead of handing this build the old shaders. Any change
# to a file there re-runs this configure step (CMAKE_CONFIGURE_DEPENDS), so the id never goes stale.
file(GLOB _kz2_xl_files LIST_DIRECTORIES false "${PS3RECOMP_DIR}/libs/video/*.c" "${PS3RECOMP_DIR}/libs/video/*.h")
list(SORT _kz2_xl_files)
set(_kz2_xl_cat "")
foreach(_kz2_xl_f IN LISTS _kz2_xl_files)
    file(SHA256 "${_kz2_xl_f}" _kz2_xl_h)
    get_filename_component(_kz2_xl_n "${_kz2_xl_f}" NAME)
    string(APPEND _kz2_xl_cat "${_kz2_xl_n}:${_kz2_xl_h};")
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${_kz2_xl_f}")
endforeach()
string(SHA256 _kz2_xl_id "${_kz2_xl_cat}")
string(SUBSTRING "${_kz2_xl_id}" 0 16 _kz2_xl_id)
set_property(SOURCE "${PS3RECOMP_DIR}/libs/video/rsx_live_draw.c" DIRECTORY "${PS3RECOMP_DIR}"
             APPEND PROPERTY COMPILE_DEFINITIONS "RSX_TRANSLATOR_ID=0x${_kz2_xl_id}ull")
list(LENGTH _kz2_xl_files _kz2_xl_count)
message(STATUS "Shader translator id: ${_kz2_xl_id} (${_kz2_xl_count} files in libs/video)")

# ---------------------------------------------------------------------------
# The HLE NID table
# ---------------------------------------------------------------------------
# Maps each firmware import NID onto the handler in the runtime that answers
# it. A port may keep a hand-curated one beside its lift; otherwise generate
# the canonical every-module table, which is what the toolkit's own boot
# harness uses.
if(EXISTS "${RECOMP_DIR}/ppu_hle_nids.cpp")
    set(HLE_NID_TABLE "${RECOMP_DIR}/ppu_hle_nids.cpp")
    message(STATUS "HLE NID table:   ${HLE_NID_TABLE}")
else()
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    set(HLE_NID_TABLE "${CMAKE_CURRENT_BINARY_DIR}/ppu_hle_nids.cpp")
    set(KZ2_PATCHSET_STAMP "")
    if(EXISTS "${PS3RECOMP_DIR}/.kz2-patchset")
        set(KZ2_PATCHSET_STAMP "${PS3RECOMP_DIR}/.kz2-patchset")
    endif()
    add_custom_command(
        OUTPUT "${HLE_NID_TABLE}"
        COMMAND "${Python3_EXECUTABLE}"
                "${PS3RECOMP_DIR}/tools/gen_hle_nids.py"
                --out "${HLE_NID_TABLE}" --all
        DEPENDS "${PS3RECOMP_DIR}/tools/gen_hle_nids.py"
                "${PS3RECOMP_DIR}/tools/nid_database.py"
                # The patch-set stamp (tools/ps3recomp-patched.sh) changes with port/patches, so an HLE function a
                # patch adds is in the table without a clean build (three cellHttp NIDs once stayed unresolved).
                ${KZ2_PATCHSET_STAMP}
        COMMENT "Generating the HLE NID -> handler table")
    message(STATUS "HLE NID table:   generated (every module)")
endif()

# ---------------------------------------------------------------------------
# The game executable
# ---------------------------------------------------------------------------
# The PPU boot scaffold is compiled here rather than taken from the runtime
# library: every one of these files #includes the lifter's per-game
# ppu_recomp.h, so they can only be built against a particular lift.
set(PS3RECOMP_SCAFFOLD
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_loader.cpp"
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_hle.cpp"
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_fs.cpp"
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_sysprx.cpp"
)

# ---------------------------------------------------------------------------
# Lifted SPU images (optional)
# ---------------------------------------------------------------------------
# A title that runs SPU work gets its images lifted into <SPU_DIR>/<image>/ by
# tools/spu_lifter.py, with a registration TU generated by
# tools/build_spu_workloads.py. cellSpurs dispatches them by content
# fingerprint, so the generated table is keyed to the images THIS build ships:
# a table generated from another release registers signatures that can never
# match, which is worse than shipping none. Both the table and the job-module
# registry self-register from constructors; a tree that has not lifted its SPU
# images yet configures only with PORT_ENABLE_SPU=OFF or KZ2_ALLOW_NO_SPU=ON.
set(SPU_DIR "${CMAKE_CURRENT_SOURCE_DIR}/spu" CACHE PATH
    "Directory holding the lifted SPU images (<SPU_DIR>/<image>/spu_recomp.c)")
option(PORT_ENABLE_SPU "Compile and register the title's lifted SPU images" ON)
# PORT_ENABLE_SPU=ON with no lifted image in SPU_DIR stops the configure (the exe would run none of the game's SPU
# jobs); KZ2_ALLOW_NO_SPU=ON says that is meant (developer builds only), like KZ2_ALLOW_NO_FFMPEG.
option(KZ2_ALLOW_NO_SPU "Build with PORT_ENABLE_SPU=ON but no lifted SPU images: developer builds only" OFF)

set(SPU_SOURCES "")
if(PORT_ENABLE_SPU)
    file(GLOB SPU_LIFTED CONFIGURE_DEPENDS "${SPU_DIR}/*/spu_recomp.c")
    if(SPU_LIFTED)
        list(LENGTH SPU_LIFTED SPU_IMAGE_COUNT)
        message(STATUS "Lifted SPU:      ${SPU_IMAGE_COUNT} image(s)")
        # The musttail indirect-branch fast path. Excluded from the runtime
        # library on purpose (see the SDK root CMakeLists): it must be built
        # here, by clang, or the tail call degrades to a plain call and a guest
        # loop that branches indirectly walks the thread stack off its guard
        # page a few thousand iterations in.
        list(APPEND SPU_SOURCES ${SPU_LIFTED}
             "${PS3RECOMP_DIR}/runtime/spu/spu_dispatch_mt.c")
        # Native host versions of hot SPU job code (re/spu/native_gates.tsv): built with the
        # lifted SPU code's flags (same float helpers), registered by spu/kz2_native_jobs.c, off unless
        # KZ2_NATIVE_JOB_<NAME>=1.
        file(GLOB KZ2_NATIVE_SPU CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/spu/*.c")
        list(APPEND SPU_SOURCES ${KZ2_NATIVE_SPU})
        # Generated beside the lift; each is present only once its generator
        # has been run, so each is included only if it is actually here.
        foreach(gen IN ITEMS spu_workloads.c jobmods_register.c taskset_policy_bytes.c)
            if(EXISTS "${SPU_DIR}/${gen}")
                list(APPEND SPU_SOURCES "${SPU_DIR}/${gen}")
            else()
                message(STATUS "  (no ${gen} -- not registered)")
            endif()
        endforeach()
    elseif(KZ2_ALLOW_NO_SPU)
        message(WARNING "Lifted SPU: none found in ${SPU_DIR} (KZ2_ALLOW_NO_SPU=ON): this exe runs none of the "
                        "game's SPU jobs and freezes in the menu")
    else()
        # Build-1 (audit 2026-11-25): an exe without the lift froze in the menu while every guard passed.
        message(FATAL_ERROR "No lifted SPU images in SPU_DIR=${SPU_DIR} (no <image>/spu_recomp.c): point "
                            "-DSPU_DIR at the lift (tools/spu/lift_spu.sh output, <work>/spu/lift), set "
                            "-DPORT_ENABLE_SPU=OFF, or -DKZ2_ALLOW_NO_SPU=ON for a developer build without them.")
    endif()
endif()

add_executable(${PROJECT_NAME}
    main.cpp
    stubs.cpp
    hle_kz2.cpp         # Killzone 2: HLE for imports the runtime leaves unresolved
    kz2_ppu_overrides.cpp  # host bodies for port/kz2/ppu_overrides.txt
    kz2_probe.cpp       # ppu_probe for a lift made with KZ2_PROBES (patch 6017)
    kz2_watch.cpp       # KZ2_WATCH guest region poll and write trap
    guest_fiber.c       # host coroutines for the PPU job-fiber scheduler (from Project Helghast port/spu)
    kz2_cpu_check.c     # KZ2_SPU_FMA: refuses to start without AVX/FMA3/OS AVX state, with a message
    kz2_pad_layout.c    # KZ2_PAD_LAYOUT=original|modern: Modern pad preset through the profile map
    kz2_gameplay.c      # aim_assist / crouch_toggle / cover_toggle settings and latch logic
    kz2_prompts.cpp     # prompt glyph source for patches 2091-2093: keys, label fonts
    kz2_port_settings.cpp  # the Display page's port rows (fov, upscale, sharpness) and display.ini
    kz2_menu_pages.cpp  # EXIT TO DESKTOP and the Keyboard page in the game's menus
    kz2_cjk_face.cpp  # the CJK face per page language (patch 6061's kz2_cjk_face_index)
    kz2_session_log.c   # KZ2_CONSOLE, logs/kz2-<date>-<time>.log, the EBOOT beside the exe (kz2_session_log.h)
    kz2_edge_zlib.c     # patch 6039: the Edge zlib job on the host (KZ2_NATIVE_ZLIB, kz2_edge_zlib.h)
    kz2_edge_guest.c    # patch 6039: a guest write standing in for the task's DMA put
    kz2_online.cpp      # an earlier change: repsn.ini / community.ini read before main(), the online switch
    ${PS3RECOMP_SCAFFOLD}
    ${HLE_NID_TABLE}
    ${RECOMP_SOURCES}
    ${SPU_SOURCES}
)

# Private developer diagnostics of the online reader: compiled only when the file is present (the
# public tree has none); kz2_online.cpp then calls it (KZ2_ONLINE_DIAG). Only these two sources change.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/kz2_online_diag.cpp")
    target_sources(${PROJECT_NAME} PRIVATE kz2_online_diag.cpp)
    set_property(SOURCE kz2_online.cpp APPEND PROPERTY COMPILE_DEFINITIONS KZ2_ONLINE_DIAG=1)
endif()

# The lifted SPU sources use bare #include "spu_context.h". Scope that include
# directory (and their flags) to those TUs alone: adding it to the whole target
# changes the compile command of every lifted PPU TU, and those are large enough
# that the needless rebuild is measured in tens of minutes.
#   SPU_USE_DISPATCH_MT -- route SPU_IB_DISPATCH through the musttail path.
#   -O2                 -- explicit, so the SPU sources keep full optimization
#                          whatever the build type says. (The lifted PPU TUs get
#                          no -O of their own: they build at the build type's
#                          level, -O2 -g for tools/build-kz2.sh's RelWithDebInfo,
#                          not -O1; checked in build.ninja, an earlier change.)
if(SPU_SOURCES)
    set_source_files_properties(${SPU_SOURCES} PROPERTIES
        INCLUDE_DIRECTORIES "${PS3RECOMP_DIR}/runtime/spu"
        COMPILE_DEFINITIONS SPU_USE_DISPATCH_MT)
    if(NOT MSVC OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        # ISA flags for the lifted SPU code (Project Helghast+ port/spu/CMakeLists.txt):
        #   -msse4.1  the helpers' pshufb shufb and SSE4.1 lane ops (KZ3 1035/1041/1097; x86-64-v2);
        #   -mfma     spu__fma4 as one hardware fused multiply-add per vector, same bits (KZ3 1097/1106; AVX + FMA3);
        #   -ffp-contract=off  no spontaneous contraction once FMA instructions exist (SPU fma/fms are explicit);
        #   -mcmodel=small     direct RIP-relative loads of the runtime gates instead of .refptr slots (MinGW).
        set(KZ2_SPU_ISA "-msse4.1" CACHE STRING "ISA flags for the lifted SPU sources")
        option(KZ2_SPU_FMA "build the lifted SPU code with -mfma (needs AVX + FMA3)" ON)
        option(KZ2_SPU_CMODEL_SMALL "build the lifted SPU code with -mcmodel=small on MinGW" ON)
        set(_kz2_spu_opts -O2 ${KZ2_SPU_ISA} -ffp-contract=off)
        if(KZ2_SPU_FMA)
            list(APPEND _kz2_spu_opts -mfma)
            # kz2_cpu_check.c (not an SPU source, built without -mavx/-mfma) checks CPUID/XGETBV at startup.
            set_source_files_properties(kz2_cpu_check.c PROPERTIES COMPILE_DEFINITIONS KZ2_SPU_NEEDS_FMA)
        endif()
        if(KZ2_SPU_CMODEL_SMALL AND MINGW)
            list(APPEND _kz2_spu_opts -mcmodel=small)
        endif()
        set_source_files_properties(${SPU_SOURCES} PROPERTIES COMPILE_OPTIONS "${_kz2_spu_opts}")
    endif()
endif()

# The build header at the top of the game log (kz2_build_info.h): the patch-set id of the toolkit copy this exe is
# built from (.kz2-patchset, written by tools/ps3recomp-patched.sh) and the source tree's installer/VERSION, the
# last fallback when the exe has no version resource (a developer build has no app.rc). Both re-read when they change.
set(_kz2_bi_defs "")
foreach(_kz2_bi IN ITEMS "PATCHSET|${PS3RECOMP_DIR}/.kz2-patchset" "VERSION|${CMAKE_CURRENT_SOURCE_DIR}/../../installer/VERSION")
    string(REPLACE "|" ";" _kz2_bi "${_kz2_bi}")
    list(GET _kz2_bi 0 _kz2_bi_key)
    list(GET _kz2_bi 1 _kz2_bi_file)
    if(EXISTS "${_kz2_bi_file}")
        file(READ "${_kz2_bi_file}" _kz2_bi_val)
        string(STRIP "${_kz2_bi_val}" _kz2_bi_val)
        if(_kz2_bi_val MATCHES "^[0-9A-Za-z.-]+$")
            list(APPEND _kz2_bi_defs "KZ2_BUILD_${_kz2_bi_key}=\"${_kz2_bi_val}\"")
        endif()
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${_kz2_bi_file}")
    endif()
endforeach()
if(_kz2_bi_defs)
    set_source_files_properties(kz2_session_log.c PROPERTIES COMPILE_DEFINITIONS "${_kz2_bi_defs}")
endif()

# app.rc carries the icon, the version block and the manifest, and needs a
# resource compiler. Listing it as a source on a host that has none is not a
# link error, it is a "no rule to make" for a file nothing can consume.
if(WIN32 AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/app.rc")
    target_sources(${PROJECT_NAME} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/app.rc")
endif()

target_include_directories(${PROJECT_NAME} PRIVATE
    "${RECOMP_DIR}"                            # the generated ppu_recomp.h
    "${PS3RECOMP_DIR}/include"
    "${PS3RECOMP_DIR}/runtime/ppu"
    "${PS3RECOMP_DIR}/runtime/spu"
    "${PS3RECOMP_DIR}/runtime/memory"
    "${PS3RECOMP_DIR}/runtime/syscalls"
    "${PS3RECOMP_DIR}/runtime/platform"        # win32_compat.h and friends
    "${PS3RECOMP_DIR}/libs/video"
    "${CMAKE_CURRENT_SOURCE_DIR}"
)

target_link_libraries(${PROJECT_NAME} PRIVATE
    ps3recomp_runtime
)

# Patch 6039 (native zlib): the host decoder of the Edge zlib job. zlib (static, zlib licence) when the toolchain has it
# (the .#win shell needs pkgsCross.mingwW64.zlib: not yet in that shell); until then
# stb_image's decoder, already in the runtime (libs/codec/cellPngDec.c). Both are complete raw-deflate decoders.
set(ZLIB_USE_STATIC_LIBS ON)
find_package(ZLIB QUIET)
if(ZLIB_FOUND)
    set_source_files_properties(kz2_edge_zlib.c PROPERTIES COMPILE_DEFINITIONS KZ2_HAVE_ZLIB)
    target_link_libraries(${PROJECT_NAME} PRIVATE ZLIB::ZLIB)
    message(STATUS "Edge zlib job:   zlib ${ZLIB_VERSION_STRING} (${ZLIB_LIBRARIES})")
else()
    message(STATUS "Edge zlib job:   stb_image decoder (no zlib in the toolchain)")
endif()

# Killzone 2: no lifted SPU images yet (KZ3's port/spu subproject), no file logger and no online
# setup (KZ3 port/net); add them here when the port has its own.


# The runtime is C++, and on Apple also Objective-C. Letting CMake infer the
# link language from the generated C would leave the C++ standard library out.
set_target_properties(${PROJECT_NAME} PROPERTIES LINKER_LANGUAGE CXX)

# Windows system import libraries. dbghelp symbolizes crash-handler addresses
# against the PDB, user32 and gdi32 are what the backend's window and its GDI
# present are made of, and winmm is timeBeginPeriod. None of the four names
# anything a POSIX linker can find; the D3D12 backend's own imports come in
# through the #pragma comment(lib) in libs/video/rsx_d3d12_backend.c.
if(WIN32)
    # GUI subsystem: no console window beside the game (KZ2_CONSOLE=1 opens one, kz2_session_log.c). The entry stays
    # main(). From Project Helghast port/kz3/CMakeLists.txt.
    if(MSVC)
        target_link_options(${PROJECT_NAME} PRIVATE /SUBSYSTEM:WINDOWS /ENTRY:mainCRTStartup)
    else()
        target_link_options(${PROJECT_NAME} PRIVATE -mwindows)
    endif()
    target_link_libraries(${PROJECT_NAME} PRIVATE
        dbghelp
        user32
        gdi32
        winmm
    )
    # MinGW ignores #pragma comment(lib), so name the backend's imports (and the
    # rest of the runtime's) explicitly. Same list as tools/smoke/build-host.sh.
    # No xinput here (patch 4019): cellPad loads XInput at run time; libxinput = xinput1_3.dll is not on stock Windows.
    if(NOT MSVC)
        target_link_libraries(${PROJECT_NAME} PRIVATE
            d3d12 dxgi d3dcompiler dxguid ole32 ws2_32 bcrypt
            shlwapi synchronization psapi
        )
    endif()
endif()

# ---------------------------------------------------------------------------
# Compiler-specific flags
# ---------------------------------------------------------------------------
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(${PROJECT_NAME} PRIVATE
        -Wall -Wextra -Wno-unused-parameter
        -fno-strict-aliasing
    )
elseif(MSVC)
    target_compile_options(${PROJECT_NAME} PRIVATE
        /W3 /wd4100 /wd4244 /wd4267
        /Zc:__cplusplus         # report correct __cplusplus value
        # ppu_recomp.h defines PPU_FENCE, the lowering of the guest's
        # sync/lwsync/eieio/isync, and in C that is <stdatomic.h>. The lifter
        # writes C++ by default, but --single-file writes ppu_recomp.c, and a
        # port that took it would not compile without this. The runtime's own
        # build already carries the same flag for the same reason.
        /experimental:c11atomics
    )
    target_compile_definitions(${PROJECT_NAME} PRIVATE
        _CRT_SECURE_NO_WARNINGS
    )
endif()

# The lifted translation units are machine-generated and can run to hundreds of
# thousands of lines each, so they get their own flags:
#
#   - warnings off. They are about generated code and nobody will act on them,
#     and at this volume they bury the diagnostics that matter.
#   - no floating-point contraction. arm64 fuses a multiply and an add by
#     default; a PPC fmadd is spelt as one where the lifter means one.
#   - /bigobj on MSVC. A single lifted file routinely passes the 65,536-section
#     limit of the default object format.
#
# KZ2 patch 6094 (from KZ3 patch 2236; an earlier change, fps-why 2026-11-24 R1, R2, R3, R6). Four opt-in options for the
# lifted PPU sources, all default OFF = the flags above, unchanged. Each is its own A/B, judged on ppu-main's busy ms
# per flip ([wacct] / a resolved profile), not fps.
#   KZ2_PPU_ISA          -mfma -msse4.1 (keeps -ffp-contract=off: only the lifter's explicit fma()/fmaf() fuse).
#                        Scalar fma/fmaf become one vfmadd; patch 6094's four-lane vmaddfp/vnmsubfp (ppu_vmx.h) turns
#                        on. A CORRECTNESS fix against the PS3, not only speed: MinGW's software fmaf/fma are not
#                        correctly rounded (kz2.exe 0x149081ee0 / 0x149081f90 sum a split product with several
#                        roundings; KZ3 measured ~15 % of random inputs wrong), the PS3's vmaddfp and fmadd round once.
#                        So the -mfma build is checked against an exact reference (glibc in the host test, the exact
#                        software fmaf of ppu_isa_ref.cpp at boot), never against the pre-6094 exe. -mfma implies AVX
#                        and GCC vectorises with ymm at -O2; GCC bug 54412 (no 32-byte stack realignment on Win64) is
#                        why GNU also gets -Wa,-muse-unaligned-vector-move. Needs AVX + FMA3, the same CPUs as
#                        KZ2_SPU_FMA; kz2_cpu_check.c refuses the others (KZ2_PPU_NEEDS_FMA).
#   KZ2_PPU_ACC_INLINE   -DPPU_ACC_ALWAYS_INLINE=1: the lifter's guest accessors (vm_read*_mm, vm_write*_mm,
#                        ppu_mm_take, vm_raw_ld16/st16) always_inline instead of static inline (GCC kept about 60 .isra
#                        copies of each, one per TU: 8,140 of TU 010's 10,446 32-bit reads were calls; R3). Their
#                        slow paths are cold noinline stubs either way. Costs compile time and code size per TU.
#   KZ2_PPU_CMODEL_SMALL -mcmodel=small on MinGW: the medium model reaches every extern through a .refptr slot, and
#                        the inline store gate read three per store (vm_write32_mm.isra 0x1446f90e0). Also
#                        -DPPU_ST_GATE_WORD=1 (patch 6096): the store gate reads g_barrier_sync_watch and
#                        g_null_sweep_hi as one 64-bit word. kz2.exe is one image < 2 GiB.
#   KZ2_PPU_TRAMP_TEB    -DPPU_TRAMP_TEB=1: DRAIN_TRAMPOLINE after every lifted call reads g_trampoline_fn through
#                        the TEB slot of patch 6094 (KZ3 1115) instead of __emutls_get_address (runtime switch
#                        KZ2_TRAMP_TEB=0 turns the slot off again; self-check at first use).
# The [ppu-isa] boot line (ppu_isa_probe.cpp, built with these flags, against ppu_isa_ref.cpp built without FMA and
# with an exact fmaf) says which were built in and whether the lifted code's fmaf/vmaddfp/vnmsubfp give the exact
# bits on this machine (fma=64/64 is expected only with KZ2_PPU_ISA=ON: without it the count is MinGW's error).
option(KZ2_PPU_ISA "lifted PPU sources with -mfma (needs AVX + FMA3)" OFF)
option(KZ2_PPU_ACC_INLINE "lifted PPU sources with always_inline guest accessors (-DPPU_ACC_ALWAYS_INLINE=1)" OFF)
option(KZ2_PPU_CMODEL_SMALL "lifted PPU sources with -mcmodel=small on MinGW and the one-word store gate" OFF)
option(KZ2_PPU_TRAMP_TEB "lifted PPU sources with -DPPU_TRAMP_TEB=1 (the TEB slot for g_trampoline_fn)" OFF)
set(KZ2_PPU_PROBE_SRC "${CMAKE_CURRENT_SOURCE_DIR}/ppu_isa_probe.cpp")
target_sources(${PROJECT_NAME} PRIVATE "${KZ2_PPU_PROBE_SRC}" ppu_isa_ref.cpp)
if(MSVC)
    set_source_files_properties(${RECOMP_SOURCES} PROPERTIES
        COMPILE_OPTIONS "/w;/bigobj")
else()
    set(KZ2_PPU_LIFTED_OPTS -w -ffp-contract=off)
    set(KZ2_PPU_PROBE_DEFS "")
    if(KZ2_PPU_ISA)
        list(APPEND KZ2_PPU_LIFTED_OPTS -msse4.1 -mfma)
        if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
            list(APPEND KZ2_PPU_LIFTED_OPTS -Wa,-muse-unaligned-vector-move)
        endif()
        set_property(SOURCE kz2_cpu_check.c APPEND PROPERTY COMPILE_DEFINITIONS KZ2_PPU_NEEDS_FMA)
    endif()
    if(KZ2_PPU_ACC_INLINE)
        list(APPEND KZ2_PPU_LIFTED_OPTS -DPPU_ACC_ALWAYS_INLINE=1)
    endif()
    if(KZ2_PPU_CMODEL_SMALL AND MINGW)
        list(APPEND KZ2_PPU_LIFTED_OPTS -mcmodel=small -DPPU_ST_GATE_WORD=1)
        list(APPEND KZ2_PPU_PROBE_DEFS KZ2_PPU_PROBE_CMODEL_SMALL)
    endif()
    if(KZ2_PPU_TRAMP_TEB)
        list(APPEND KZ2_PPU_LIFTED_OPTS -DPPU_TRAMP_TEB=1)
        list(APPEND KZ2_PPU_PROBE_DEFS KZ2_PPU_PROBE_TRAMP_TEB)
    endif()
    set_source_files_properties(${RECOMP_SOURCES} "${KZ2_PPU_PROBE_SRC}" PROPERTIES
        COMPILE_OPTIONS "${KZ2_PPU_LIFTED_OPTS}")
    if(KZ2_PPU_PROBE_DEFS)
        set_property(SOURCE "${KZ2_PPU_PROBE_SRC}" APPEND PROPERTY COMPILE_DEFINITIONS ${KZ2_PPU_PROBE_DEFS})
    endif()
    # The reference half of the boot self-test: never FMA, whatever the lifted flags are.
    set_source_files_properties(ppu_isa_ref.cpp PROPERTIES COMPILE_OPTIONS "-mno-fma;-mno-avx;-ffp-contract=off")
    string(REPLACE ";" " " _kz2_ppu_opts_str "${KZ2_PPU_LIFTED_OPTS}")
    message(STATUS "KZ2 lifted PPU flags: ${_kz2_ppu_opts_str} (KZ2_PPU_ISA=${KZ2_PPU_ISA} KZ2_PPU_ACC_INLINE=${KZ2_PPU_ACC_INLINE} KZ2_PPU_CMODEL_SMALL=${KZ2_PPU_CMODEL_SMALL} KZ2_PPU_TRAMP_TEB=${KZ2_PPU_TRAMP_TEB})")
endif()

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
install(TARGETS ${PROJECT_NAME} RUNTIME DESTINATION bin)
