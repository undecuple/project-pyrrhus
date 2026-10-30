{
  description = "Killzone 2 PC port: reverse-engineering toolchain and builds";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      # Only these unfree packages are allowed: RPCS3 (licence includes unfree parts) and
      # steam-run (runs the user's Proton for tests). Everything else must be free.
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfreePredicate = pkg: builtins.elem (nixpkgs.lib.getName pkg) [
          "rpcs3" "steam-run" "steam" "steam-unwrapped" "steam-original"
        ];
      };

      python = pkgs.python3.withPackages (ps: with ps; [
        capstone   # PPU disassembly in scripts
        numpy      # fast binary scans (branch xrefs, pattern search)
        pillow     # screenshots and texture dumps
        pyelftools # ELF / PRX parsing after decryption
        lz4
        zstandard
        # ps3recomp tool pipeline (third_party/ps3recomp/requirements.txt)
        construct
        pycryptodome
        cryptography  # SELF decryption
        tabulate
        tqdm
      ]);

      # Tools for the analysis stage: no GPU, no network needed.
      reTools = with pkgs; [
        python
        bubblewrap      # tools/sandbox.sh
        tinyxxd binutils file hexyl
        ghidra          # PPU (PowerPC 64 BE) static analysis
        radare2         # quick disassembly / patch checks
        duckdb          # tools/q: SQL over the TSV/JSON data in place
        (rizin.withPlugins (ps: [ ps.rz-ghidra ]))  # `pdg @ addr`: Ghidra decompiler per function, no project DB
        ffmpeg          # Bink video + ATRAC3 audio decode (asset previews)
        imagemagick
        p7zip
        git
      ];

      # Runtime / graphics stage: reference emulator, GPU capture, headless display.
      runtimeTools = with pkgs; [
        rpcs3           # reference runtime, SELF decryption, behaviour oracle
        renderdoc       # frame capture of RPCS3's Vulkan output
        vulkan-tools    # vulkaninfo
        vulkan-validation-layers
        xvfb xvfb-run xdotool
        mesa-demos
      ];

      # Host-side build tools (recompiler, asset converters run on Linux).
      buildTools = with pkgs; [
        cmake ninja pkg-config
        clang_19 lld_19 llvmPackages_19.llvm
        shaderc spirv-tools vulkan-headers
        steam-run       # runs the user's Proton for tests (tools/proton-test.sh)
      ];

      # Windows x64 target: the shipped port is a Windows exe, tested only under Proton.
      win = pkgs.pkgsCross.mingwW64;

      # mkShell sets $out to <repo>/outputs/out and the cc wrapper adds an unquoted "-rpath $out/lib" to
      # NIX_LDFLAGS. The repo path contains a space, so every host compile-and-link in a dev shell failed
      # ("cannot find 3/outputs/out/lib"). Nothing is installed to $out, so drop that entry in every shell.
      fixLdflags = ''
        if [ -n "''${NIX_LDFLAGS-}" ] && [ -n "''${out-}" ]; then
          export NIX_LDFLAGS="''${NIX_LDFLAGS//"-rpath $out/lib"/}"
        fi
      '';
    in {
      devShells.${system} = {
        # `nix develop` : everything
        default = pkgs.mkShell {
          packages = reTools ++ runtimeTools ++ buildTools;
          shellHook = fixLdflags + ''
            export KZ2_ROOT="$PWD"
            export KZ2_GAME="$PWD/Game"
            export KZ2_WORK="$PWD/work"
            # NixOS exposes the NVIDIA Vulkan ICD here; no nixGL needed.
            export VK_ICD_FILENAMES=/run/opengl-driver/share/vulkan/icd.d/nvidia_icd.json
          '';
        };
        # `nix develop .#ci` : the public CI's host tests and checks: Python, the host compilers and the basic tools,
        # without the unfree RPCS3 and the GPU tools (which have no binary cache and were built on every run).
        ci = pkgs.mkShell {
          packages = [ python pkgs.bubblewrap pkgs.tinyxxd pkgs.binutils pkgs.file pkgs.git ]
            ++ (with pkgs; [ cmake ninja pkg-config clang_19 lld_19 llvmPackages_19.llvm ]);
          shellHook = fixLdflags;
        };
        # `nix develop .#re` : lightweight shell for extraction / analysis
        re = pkgs.mkShell { packages = reTools; shellHook = fixLdflags; };
        # `nix develop .#win` : cross-compile the port to Windows x64 (MinGW-w64).
        # Vulkan is loaded at runtime (volk) from vulkan-1.dll, which Proton/the NVIDIA
        # driver provide, so no Windows Vulkan SDK is needed.
        win = win.mkShell {
          nativeBuildInputs = [ pkgs.cmake pkgs.ninja pkgs.pkg-config pkgs.shaderc pkgs.bubblewrap pkgs.python3 pkgs.ccache ];  # ccache: local and remote builds (tools/remote image, D9)
          # SDL3 (the pad standard): only its SDL3.dll is shipped next to the exe, loaded at run time by
          # patch 4010 (XInput fallback without it); the build needs no SDL headers. SDL2 build input dropped.
          # zlib: the Edge zlib job's host decoder (KZ2_NATIVE_ZLIB, port/kz2/kz2_edge_zlib.c); CMake's
          # FindZLIB with ZLIB_USE_STATIC_LIBS links its libz.a into the exe (no zlib DLL shipped).
          buildInputs = [ win.sdl3 win.zlib ];
          shellHook = fixLdflags;
        };
      };
    };
}
