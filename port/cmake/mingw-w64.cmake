# From Project Helghast cmake/mingw-w64.cmake; KZ2 additions marked "KZ2" (the root path and the PACKAGE mode, public #34).
# Cross-compile to Windows x64 with MinGW-w64 from `nix develop .#win`.
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER   x86_64-w64-mingw32-gcc)
set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++)
set(CMAKE_RC_COMPILER  x86_64-w64-mingw32-windres)
# KZ2 (public #34): the ONLY modes below re-root nothing without a root path, so a distro's GCC MinGW-w64 on a Linux
# host (firstrun.py's fallback without llvm-mingw) still found the host's own libraries and CMake packages. Use the
# distro's MinGW-w64 sysroot as the root path when there is one (Fedora .../sys-root/mingw, Debian/Arch
# /usr/x86_64-w64-mingw32); KZ2_MINGW_SYSROOT names another, or "" for none. Not in `nix develop .#win`: its MinGW
# libraries (zlib, SDL3) come through CMAKE_PREFIX_PATH from the Nix store, which re-rooting would hide; NixOS has no
# such folder either.
if(NOT DEFINED KZ2_MINGW_SYSROOT)
    set(KZ2_MINGW_SYSROOT "")
    if(NOT DEFINED ENV{IN_NIX_SHELL})
        foreach(_kz2_d /usr/x86_64-w64-mingw32/sys-root/mingw /usr/x86_64-w64-mingw32)
            if(IS_DIRECTORY "${_kz2_d}")
                set(KZ2_MINGW_SYSROOT "${_kz2_d}")
                break()
            endif()
        endforeach()
    endif()
endif()
if(KZ2_MINGW_SYSROOT AND NOT CMAKE_FIND_ROOT_PATH)
    set(CMAKE_FIND_ROOT_PATH "${KZ2_MINGW_SYSROOT}")
endif()
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
# KZ2 (public #34): find_package config files only from the target too: on a Linux host a CMake package of the
# host (an SDL3 or ZLIB config under /usr/lib/cmake) is a Linux library and must not be linked into the exe.
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
# Ship self-contained exes: no libgcc/libstdc++/winpthread DLLs next to the game.
set(CMAKE_EXE_LINKER_FLAGS_INIT "-static -static-libgcc -static-libstdc++")
# KZ2: the same for the DLLs the build makes (at3_standalone.dll, ps3recomp PS3RECOMP_AT3_SHARED): no MinGW runtime
# DLL beside them either.
set(CMAKE_SHARED_LINKER_FLAGS_INIT "-static -static-libgcc -static-libstdc++")
