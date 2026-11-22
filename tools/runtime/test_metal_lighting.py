#!/usr/bin/env python3
"""Depth-bounds emulation and depth clamp on Metal (KZ2 patches 2174 and 2175).

Configures the patched toolkit with PS3RECOMP_BUILD_TESTS=ON in a temporary build folder, builds three of its own
tests and runs them:
  - test_shader_msl: the fragment-program text rewrite rsx_fp_apply_depth_bounds adds (cases from 2174);
  - test_metal_depth_bounds: draws through the real draw engine on the Metal device, with the depth-bounds test on,
    and checks which halves of the target survive for several [min, max] bounds;
  - test_metal_depth_clamp: SET_ZMIN_MAX_CONTROL modes 0x01/0x10/0x11/0x00 and the depth each leaves.
Before 2174/2175 the two Metal tests do not exist and the engine ignored both registers. macOS only (Metal device and
the toolkit's MSL translator: glslang, SPIRV-Tools, SPIRV-Cross); SKIP elsewhere. No game data is read.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ('test_shader_msl', 'test_metal_depth_bounds', 'test_metal_depth_clamp')


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolkit', type=Path, help='patched toolkit')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        print('SKIP: the Metal tests need macOS')
        return
    candidates = [args.toolkit] if args.toolkit else [
        Path(os.environ['KZ2_PATCHED_DIR']) if os.environ.get('KZ2_PATCHED_DIR') else None,
        Path(os.environ['KZ2_OUT']) / 'ps3recomp-patched' if os.environ.get('KZ2_OUT') else None,
        ROOT / 'work/runtime/ps3recomp-patched', ROOT / 'work/ps3recomp-patched',
    ]
    toolkit = next((p.resolve() for p in candidates if p and (p / 'CMakeLists.txt').is_file()), None)
    if toolkit is None:
        if args.toolkit:
            raise SystemExit('FAIL: no toolkit at --toolkit path')
        print('SKIP: no patched toolkit; run tools/ps3recomp-patched.sh')
        return
    if not all(shutil.which(t) for t in ('cmake', 'ninja')):
        print('SKIP: needs cmake and ninja')
        return
    if not (toolkit / 'libs/video/tests/test_metal_depth_bounds.m').is_file():
        raise SystemExit('FAIL: toolkit lacks patch 2174 (no test_metal_depth_bounds.m)')
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp) / 'build'
        cfg = subprocess.run(['cmake', '-S', str(toolkit), '-B', str(build), '-G', 'Ninja',
                              '-DPS3RECOMP_BUILD_TESTS=ON', '-DCMAKE_BUILD_TYPE=Release'],
                             capture_output=True, text=True)
        if cfg.returncode:
            sys.stdout.write(cfg.stdout[-2000:] + cfg.stderr[-2000:])
            raise SystemExit('FAIL: toolkit configure')
        missing = [t for t in TARGETS if t not in subprocess.run(['ninja', '-C', str(build), '-t', 'targets', 'all'],
                                                                 capture_output=True, text=True).stdout]
        if missing:
            print(f'SKIP: the toolkit configured without {", ".join(missing)} (no MSL translator libraries here)')
            return
        jobs = str(max(1, (os.cpu_count() or 2) // 2))
        b = subprocess.run(['ninja', '-C', str(build), '-j', jobs, *TARGETS], capture_output=True, text=True)
        if b.returncode:
            sys.stdout.write(b.stdout[-3000:])
            raise SystemExit('FAIL: build of the Metal lighting tests')
        failed = []
        # Both features are off by default (the macOS bring-up saw broken text and floors with them on); each target
        # checks the default and the opt-in.
        for t in TARGETS:
            for switch in ('0', '1'):
                env = dict(os.environ, PS3RECOMP_ENG_DEPTH_BOUNDS=switch, PS3RECOMP_ENG_DEPTH_CLAMP=switch)
                r = subprocess.run([str(build / t)], capture_output=True, text=True, timeout=300, env=env)
                last = [l for l in r.stdout.splitlines() if l.strip()] or [l for l in r.stderr.splitlines() if l.strip()]
                print(f"[{'PASS' if r.returncode == 0 else 'FAIL'}] {t} (switch {switch}): {last[-1] if last else ''}")
                if r.returncode:
                    failed.append(f'{t} (switch {switch})')
        if failed:
            raise SystemExit('FAIL: ' + ', '.join(failed))
    print('PASS: patches 2174/2175 depth bounds and depth clamp on Metal (no game data)')


if __name__ == '__main__':
    main()
