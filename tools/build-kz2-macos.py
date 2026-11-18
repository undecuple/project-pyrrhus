#!/usr/bin/env python3
"""Native macOS build; --smoke builds against the toolkit's synthetic title.

Resource guards informed by Afro Samurai / PES 2013 tools/build.sh, Erik Martins
(MIT): one build, one compiler job, free-disk and memory-pressure checks. This
implementation uses an OS file lock and terminates only its own process group.
"""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def verify_game_lift(recomp, toolkit_stamp, override_list=None):
    """Reject a stale or foreign lift before starting expensive compilation."""
    override_list = override_list or ROOT / 'port/kz2/ppu_overrides.txt'
    stamp_file = recomp / '.lift-stamp'
    if not stamp_file.is_file():
        raise SystemExit('Missing .lift-stamp: run tools/lift-kz2-macos.py')
    stamp = stamp_file.read_text()
    if not re.search(r'(?:^|\s)ver=129(?:\s|$)', stamp) or f'patchset={toolkit_stamp}' not in stamp.split():
        raise SystemExit('PPU lift version/toolkit is stale: regenerate the 1.29 lift')
    wanted = {m.lower() for m in re.findall(r'^([0-9a-fA-F]{8})\b', override_list.read_text(), re.M)}
    announced = {m.lower() for m in re.findall(r'\bPPU_OVERRIDE_([0-9a-fA-F]{8})\b',
                                             (recomp / 'ppu_overrides.h').read_text())}
    if wanted != announced:
        raise SystemExit('PPU override announcements do not match the 1.29 override list; relift')


def run_guarded(command, log):
    if shutil.disk_usage(ROOT).free < 4 * 1024**3:
        raise SystemExit('REFUSED: less than 4 GiB of free disk space')
    with log.open('a') as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            while process.poll() is None:
                pressure = subprocess.run(['memory_pressure'], capture_output=True,
                                          text=True, timeout=10)
                match = re.search(r'System-wide memory free percentage:\s*(\d+)', pressure.stdout)
                if match and int(match[1]) < 15:
                    raise RuntimeError('memory guard: less than 15% free memory')
                time.sleep(2)
            if process.returncode:
                raise RuntimeError(f'command exited {process.returncode}; see {log}')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', action='store_true', help='use only synthetic toolkit code, no game data')
    parser.add_argument('--check', action='store_true', help='configure and show the build plan without compiling')
    parser.add_argument('--toolkit', type=Path, default=ROOT / 'work/ps3recomp-patched')
    parser.add_argument('--build-dir', type=Path)
    parser.add_argument('--ffmpeg-include', type=Path, help='directory containing libavcodec/avcodec.h')
    parser.add_argument('--allow-no-ffmpeg', action='store_true', help='developer build with black movies and silent AC3')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('This builder requires macOS; use tools/build-kz2.sh on Linux for Windows builds')
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11 or newer is required')
    for program in ('cmake', 'ninja', 'memory_pressure'):
        if not shutil.which(program):
            raise SystemExit(f'Missing build prerequisite: {program}')
    toolkit = args.toolkit.resolve()
    if not (toolkit / 'CMakeLists.txt').is_file():
        raise SystemExit('No patched toolkit: initialize the pinned submodule and run tools/ps3recomp-patched.sh')
    patch_hash = hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT / 'port/patches').glob('*.patch')))).hexdigest()[:16]
    pin = subprocess.check_output(['git', '-C', str(ROOT), 'ls-tree', 'HEAD', 'third_party/ps3recomp'], text=True).split()[2]
    stamp = (toolkit / '.kz2-patchset').read_text().strip() if (toolkit / '.kz2-patchset').is_file() else ''
    digest, _, revision = stamp.partition('-')
    if digest != patch_hash or not revision or not pin.startswith(revision):
        raise SystemExit('Toolkit stamp missing or stale: regenerate with tools/ps3recomp-patched.sh')
    out = ROOT / 'work/macos-smoke' if args.smoke else ROOT / 'work'
    build = (args.build_dir or ROOT / ('build/kz2-macos-smoke' if args.smoke else 'build/kz2-macos')).resolve()
    build.mkdir(parents=True, exist_ok=True)
    (ROOT / 'work').mkdir(exist_ok=True)
    # flock releases on interruption and process exit, without stale-PID removal.
    with (ROOT / 'work/.kz2-macos-build.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('REFUSED: another Pyrrhus macOS build is running')
        # The other local ports do not share our flock; respect their Ninja builds.
        active = subprocess.run(['pgrep', '-x', 'ninja'], capture_output=True, text=True)
        if active.returncode == 0:
            raise SystemExit('REFUSED: another Ninja build is running; wait for it to finish')
        recomp = out / 'recomp'
        if args.smoke:
            recomp.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, str(toolkit / 'tools/make_smoke_elf.py'),
                            '--out', str(out / 'smoke.elf'), '--header', str(recomp / 'ppu_recomp.h')], check=True)
            (recomp / 'ppu_overrides.h').write_text(
                '#pragma once\n#include "ppu_recomp.h"\n'
                '#define PPU_OVERRIDE_000821D0\n'
                'void func_000821D0__lifted(ppu_context*);\n')
            (recomp / 'override_probe.cpp').write_text(
                '#include "ppu_overrides.h"\n'
                'void func_000821D0__lifted(ppu_context*) {}\n')
            shutil.copyfile(toolkit / 'runtime/ppu/tests/smoke/smoke_recomp.c', recomp / 'smoke_recomp.c')
            # Compile the real SPU helper/dispatch path too, so an ARM build
            # cannot pass by omitting the sources that used to receive -mfma.
            probe = out / 'spu/lift/synthetic'
            probe.mkdir(parents=True, exist_ok=True)
            (probe / 'spu_recomp.c').write_text(
                '#include "spu_helpers.h"\n'
                'void kz2_synthetic_spu_probe(spu_context* ctx) {\n'
                '  ctx->gpr[3] = spu_fa(ctx->gpr[4], ctx->gpr[5]);\n}\n')
        elif not (recomp / 'ppu_overrides.h').is_file() or not (out / 'spu/lift/spu_workloads.c').is_file():
            raise SystemExit('Missing PPU/SPU lift in work/: see docs/BUILDING.md; other games\' lifts cannot be reused')
        else:
            verify_game_lift(recomp, stamp)
            if (out / 'spu/eboot_ver').read_text().strip() != '129':
                raise SystemExit('SPU lift is not for version 1.29; regenerate it')
            subprocess.run([sys.executable, '-B', str(ROOT / 'tools/release/lua_unwind.py'),
                            '--recomp-dir', str(recomp), '--version', '129', '--verify'], check=True)
        configure = ['cmake', '-S', str(ROOT / 'port/kz2'), '-B', str(build), '-G', 'Ninja',
                     '-DPS3RECOMP_DIR=' + str(toolkit), '-DRECOMP_DIR=' + str(recomp),
                     '-DSPU_DIR=' + str(out / 'spu/lift'), '-DPython3_EXECUTABLE=' + sys.executable,
                     '-DCMAKE_BUILD_TYPE=RelWithDebInfo', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON']
        if args.ffmpeg_include:
            configure.append('-DKZ2_FFMPEG_INCLUDE_DIR=' + str(args.ffmpeg_include.resolve()))
        configure.append('-DKZ2_ALLOW_NO_FFMPEG=' + ('ON' if args.smoke or args.allow_no_ffmpeg else 'OFF'))
        log = build / 'build-macos.log'
        print(f'Native macOS build: {build}\nLog: {log}', flush=True)
        run_guarded(configure, log)
        if args.check:
            subprocess.run(['ninja', '-C', str(build), '-n', 'kz2'], check=True)
            return
        run_guarded(['cmake', '--build', str(build), '--target', 'kz2', '--parallel', '1'], log)
        print(f'Built {build / "kz2"}')
        if args.smoke:
            print(f'Synthetic test image: {out / "smoke.elf"} (not Killzone 2)')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc))
