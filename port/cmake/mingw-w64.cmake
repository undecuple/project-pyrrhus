# From Project Helghast cmake/mingw-w64.cmake (unchanged below this line).
# Cross-compile to Windows x64 with MinGW-w64 from `nix develop .#win`.
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER   x86_64-w64-mingw32-gcc)
set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++)
set(CMAKE_RC_COMPILER  x86_64-w64-mingw32-windres)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
# Ship self-contained exes: no libgcc/libstdc++/winpthread DLLs next to the game.
set(CMAKE_EXE_LINKER_FLAGS_INIT "-static -static-libgcc -static-libstdc++")
# KZ2: the same for the DLLs the build makes (at3_standalone.dll, ps3recomp PS3RECOMP_AT3_SHARED): no MinGW runtime
# DLL beside them either.
set(CMAKE_SHARED_LINKER_FLAGS_INIT "-static -static-libgcc -static-libstdc++")
