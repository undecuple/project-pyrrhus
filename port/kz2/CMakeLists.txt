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
#     it at the tools/runtime/ffmpeg-lgpl-win.nix output). Without it the
#     decoders stay callback-only (black pictures, silent AC3).
set(PS3RECOMP_AT3_SHARED ON CACHE BOOL "at3_standalone as its own DLL" FORCE)
set(KZ2_FFMPEG_INCLUDE_DIR "" CACHE PATH "FFmpeg headers for the run-time loaded decoders (empty: none)")
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
else()
    set(PS3RECOMP_FFMPEG_RUNTIME OFF CACHE BOOL "FFmpeg loaded at run time" FORCE)
    message(WARNING "No KZ2_FFMPEG_INCLUDE_DIR: movies decode to black pictures and silent AC3")
endif()
add_subdirectory("${PS3RECOMP_DIR}" "${CMAKE_BINARY_DIR}/ps3recomp_sdk"
                 EXCLUDE_FROM_ALL)

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
# registry self-register from constructors and are therefore optional -- a tree
# that has not lifted its SPU images yet configures and links without them.
set(SPU_DIR "${CMAKE_CURRENT_SOURCE_DIR}/spu" CACHE PATH
    "Directory holding the lifted SPU images (<SPU_DIR>/<image>/spu_recomp.c)")
option(PORT_ENABLE_SPU "Compile and register the title's lifted SPU images" ON)

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
        # Generated beside the lift; each is present only once its generator
        # has been run, so each is included only if it is actually here.
        foreach(gen IN ITEMS spu_workloads.c jobmods_register.c taskset_policy_bytes.c)
            if(EXISTS "${SPU_DIR}/${gen}")
                list(APPEND SPU_SOURCES "${SPU_DIR}/${gen}")
            else()
                message(STATUS "  (no ${gen} -- not registered)")
            endif()
        endforeach()
    else()
        message(STATUS "Lifted SPU:      none found in ${SPU_DIR}")
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
    kz2_prompts.cpp     # prompt glyph source for patches 2091-2093: keys, label fonts
    kz2_menu_pages.cpp  # EXIT TO DESKTOP and the Keyboard page in the game's menus
    kz2_session_log.c   # KZ2_CONSOLE, logs/kz2-<date>-<time>.log, the EBOOT beside the exe (kz2_session_log.h)
    ${PS3RECOMP_SCAFFOLD}
    ${HLE_NID_TABLE}
    ${RECOMP_SOURCES}
    ${SPU_SOURCES}
)

# The lifted SPU sources use bare #include "spu_context.h". Scope that include
# directory (and their flags) to those TUs alone: adding it to the whole target
# changes the compile command of every lifted PPU TU, and those are large enough
# that the needless rebuild is measured in tens of minutes.
#   SPU_USE_DISPATCH_MT -- route SPU_IB_DISPATCH through the musttail path.
#   -O2                 -- the target-wide -O1 exists for the huge PPU TUs; the
#                          SPU sources are small and decode-hot, so they get
#                          full optimization. The last -O on the line wins.
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
if(MSVC)
    set_source_files_properties(${RECOMP_SOURCES} PROPERTIES
        COMPILE_OPTIONS "/w;/bigobj")
else()
    set_source_files_properties(${RECOMP_SOURCES} PROPERTIES
        COMPILE_OPTIONS "-w;-ffp-contract=off")
endif()

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
install(TARGETS ${PROJECT_NAME} RUNTIME DESTINATION bin)
