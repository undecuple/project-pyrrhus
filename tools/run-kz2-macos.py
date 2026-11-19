#!/usr/bin/env python3
"""Run the native game with read-only inputs, private writable data and no network.

The disc argument is a mounted/extracted directory containing PS3_GAME, not
the ISO filename. Mount the ISO read-only before using this runner.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def profile(work, build):
    quote = lambda p: json.dumps(str(p))
    return ('(version 1)(allow default)(deny network*)(deny file-write*)'
            '(allow file-write* (literal "/dev/null") '
            f'(subpath {quote(work)}) (subpath {quote(build)}))')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disc', type=Path, required=True)
    parser.add_argument('--update', type=Path, required=True)
    parser.add_argument('--eboot', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=60, help='maximum run duration, default 60 seconds')
    parser.add_argument('--skip-intro', action='store_true', help='diagnostic opt-in; do not save this setting')
    parser.add_argument('--headless', action='store_true', help='offscreen Metal rendering')
    parser.add_argument('--data', default='macos-game-data',
                        help='folder under work/ for saves and caches (default macos-game-data; a benchmark can keep its own)')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('Native Mac runner requires macOS')
    if args.seconds < 10:
        raise SystemExit('--seconds must be at least 10')
    disc, update, elf = args.disc.resolve(), args.update.resolve(), args.eboot.resolve()
    if not (disc / 'PS3_GAME/PARAM.SFO').is_file() or not (update / 'PARAM.SFO').is_file() or not elf.is_file():
        raise SystemExit('Missing disc metadata, update metadata, or ELF')
    binary = ROOT / 'build/kz2-macos/kz2'
    if not binary.is_file():
        raise SystemExit('Build first with tools/build-kz2-macos.py')
    work, build = ROOT / 'work', ROOT / 'build'
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    run = work / 'macos-runs' / stamp
    run.mkdir(parents=True, exist_ok=False)
    if '/' in args.data or args.data in ('', '.', '..'):
        raise SystemExit('--data names one folder under work/')
    data = work / args.data
    for folder in ('hdd0', 'hdd1', 'gamedata', 'tmp'):
        (data / folder).mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(PS3_VFS_ROOT=str(disc), KZ2_UPDATE_DIR=str(update / 'USRDIR'),
               KZ2_CACHE_ROOT=str(data / 'hdd1'), PS3_HDD0_ROOT=str(data / 'hdd0'),
               PS3_HDD1_ROOT=str(data / 'hdd1'), PS3_GAMEDATA_ROOT=str(data / 'gamedata'),
               TMPDIR=str(data / 'tmp'), PS3_STDIO_UNBUFFERED='1',
               PS3RECOMP_METAL_HEADLESS='1' if args.headless else '0',
               KZ2_SKIP_INTRO='1' if args.skip_intro else '0',
               KZ2_TEST_CLOSE=str(args.seconds - 5), KZ2_NO_ERROR_DIALOG='1')
    # Patch 2167's background builds still lose content drawn only during a pending
    # build's drop window: menu boxes, and now gameplay elements too (the owner's
    # report). Synchronous builds show everything (the owner confirmed the incomplete
    # menu with async on); an explicit PS3RECOMP_METAL_ASYNC_PSO value wins.
    env.setdefault('PS3RECOMP_METAL_ASYNC_PSO', '0')
    # The LGPL-only FFmpeg built into work/ffmpeg-macos (docs/BUILDING.md); an explicit environment choice wins.
    ffmpeg = work / 'ffmpeg-macos/lib'
    for name, lib in (('PS3RECOMP_FFMPEG_AVUTIL', 'libavutil.61.dylib'),
                      ('PS3RECOMP_FFMPEG_AVCODEC', 'libavcodec.63.dylib')):
        if not env.get(name) and (ffmpeg / lib).is_file():
            env[name] = str(ffmpeg / lib)
    sandbox = profile(work, build)
    # Same read-only sandbox for input verification and the actual run.
    checked = subprocess.run(['/usr/bin/sandbox-exec', '-p', sandbox, sys.executable, '-B',
                              str(ROOT / 'tools/release/firstrun_check.py'), '--dump', str(disc),
                              '--update', str(update), '--eboot', str(elf), '--skip-archive-hash'],
                             env=env, capture_output=True, text=True)
    (run / 'input-check.log').write_text(checked.stdout + checked.stderr)
    if checked.returncode:
        raise SystemExit(f'Input checks failed; see {run / "input-check.log"}')
    log = run / 'stdout.log'
    command = ['/usr/bin/sandbox-exec', '-p', sandbox, str(binary), str(elf)]
    print(f'Native run, offline, inputs read-only. Log: {log}', flush=True)
    timed_out = False
    with log.open('w') as output:
        process = subprocess.Popen(command, cwd=run, env=env, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            try:
                process.wait(timeout=args.seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    (run / 'run.json').write_text(json.dumps({'exit_code': process.returncode, 'timed_out': timed_out,
                                            'skip_intro': args.skip_intro, 'headless': args.headless,
                                            'disc': str(disc), 'update': str(update), 'elf': str(elf)}, indent=2) + '\n')
    print(f'Native process exit: {process.returncode}; timeout: {timed_out}; log: {log}')


if __name__ == '__main__':
    main()
