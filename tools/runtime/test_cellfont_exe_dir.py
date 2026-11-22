#!/usr/bin/env python3
"""cellFont's executable folder on POSIX hosts (KZ2 patch 6085, libs/font/cellFontOutline.c).

Builds the real exe_dir() (pulled verbatim out of cellFontOutline.c, with the file's own includes) into a small host
program and checks that it names the folder holding that program, which is where the fontset chain looks for
fonts/NotoSans-Regular.ttf. Before 6085 it read /proc/self/exe off Windows, which macOS lacks: the chain logged
"dir none" and loaded no font on the first native macOS run. On Windows hosts the test prints SKIP (GetModuleFileNameW
path, unchanged). No game data is read.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
%s
%s
int main(void)
{
    char dir[1024];
    exe_dir(dir, sizeof dir);
    printf("%%s\n", dir);
    return dir[0] ? 0 : 1;
}
'''


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolkit', type=Path, help='patched toolkit (also accepts a tree without patch 6085 for a negative control)')
    args = parser.parse_args()
    if os.name == 'nt':
        print('SKIP: the POSIX exe_dir path is tested on POSIX hosts')
        return
    candidates = [args.toolkit] if args.toolkit else [
        Path(os.environ['KZ2_PATCHED_DIR']) if os.environ.get('KZ2_PATCHED_DIR') else None,
        Path(os.environ['KZ2_OUT']) / 'ps3recomp-patched' if os.environ.get('KZ2_OUT') else None,
        ROOT / 'work/runtime/ps3recomp-patched', ROOT / 'work/ps3recomp-patched',
    ]
    toolkit = next((p.resolve() for p in candidates if p and (p / 'libs/font/cellFontOutline.c').is_file()), None)
    if toolkit is None:
        if args.toolkit:
            raise SystemExit('FAIL: no toolkit at --toolkit path')
        print('SKIP: no patched toolkit; run tools/ps3recomp-patched.sh')
        return
    cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if not cc:
        print('SKIP: no host C compiler')
        return
    src = (toolkit / 'libs/font/cellFontOutline.c').read_text()
    inc = re.search(r'#ifdef _WIN32\n#  include <windows.h>\n#else\n.*?\n#endif\n', src, re.S)
    assert inc, 'platform include block not found'
    m = re.search(r'static void exe_dir\(char\* out, size_t cap\)\s*\{', src)
    assert m, 'exe_dir not found'
    i, depth = m.end(), 1
    while depth:
        depth += {'{': 1, '}': -1}.get(src[i], 0)
        i += 1
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp).resolve()
        (t / 'harness.c').write_text(HARNESS % (inc.group(0), src[m.start():i]))
        sub = t / 'bin'
        sub.mkdir()
        exe = sub / 'exe_dir_test'
        subprocess.run([cc, '-w', '-O1', str(t / 'harness.c'), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        got = result.stdout.strip()
        ok = result.returncode == 0 and Path(got).resolve() == sub
        print(f"[{'PASS' if ok else 'FAIL'}] exe_dir names the executable's folder (got '{got}')")
        if not ok:
            raise SystemExit('FAIL: cellFont exe_dir on this host (patch 6085)')
    print('PASS: patch 6085 cellFont executable folder on a POSIX host (no game data)')


if __name__ == '__main__':
    main()
