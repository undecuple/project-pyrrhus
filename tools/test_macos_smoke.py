#!/usr/bin/env python3
"""Run the native synthetic boot through Metal. Requires a built --smoke target and GPU access.

No game files; deliberately excluded from tools/host-tests.txt, which is GPU-free.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windowed', action='store_true', help='open a Cocoa window instead of an offscreen Metal target')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        print('SKIP: native Metal smoke requires macOS')
        return
    binary = ROOT / 'build/kz2-macos-smoke/kz2'
    out = ROOT / 'work/macos-smoke'
    if not binary.is_file() or not (out / 'smoke.elf').is_file():
        raise SystemExit('Build first: python3 tools/build-kz2-macos.py --smoke')
    with tempfile.TemporaryDirectory(prefix='kz2-native-smoke-') as tmp:
        usrdir = Path(tmp) / 'PS3_GAME/USRDIR'
        usrdir.mkdir(parents=True)
        image = usrdir / 'smoke.elf'
        shutil.copyfile(out / 'smoke.elf', image)
        env = os.environ.copy()
        # Explicit temporary roots keep the synthetic run away from user data.
        env.update(PS3RECOMP_METAL_HEADLESS='0' if args.windowed else '1',
                   KZ2_MENU_PAGES='0', KZ2_SKIP_INTRO='0',
                   KZ2_CACHE_ROOT=str(Path(tmp) / 'cache'),
                   KZ2_UPDATE_DIR=str(Path(tmp) / 'no-update'),
                   PS3_HDD0_ROOT=str(Path(tmp) / 'hdd0'),
                   PS3_HDD1_ROOT=str(Path(tmp) / 'hdd1'),
                   PS3_GAMEDATA_ROOT=str(Path(tmp) / 'gamedata'),
                   PS3_VERBOSE='0', PS3_STDIO_UNBUFFERED='1')
        log = out / ('run-windowed.log' if args.windowed else 'run-headless.log')
        with log.open('w') as output:
            subprocess.run([str(binary), str(image)], cwd=tmp, env=env, stdout=output,
                           stderr=subprocess.STDOUT, timeout=30, check=True)
        result = log.read_text()
        for marker in ('[smoke] PASS', 'frames presented: 3', 'guest shaders on', '[rsx] Metal backend init OK'):
            if marker not in result:
                raise SystemExit(f'FAIL: missing {marker}; see {log}')
        print(f'PASS: native Metal synthetic boot, threads, 3 frames, vblank and guest exit; log: {log}')


if __name__ == '__main__':
    main()
