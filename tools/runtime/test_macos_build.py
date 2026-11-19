#!/usr/bin/env python3
"""Compile the real native port with synthetic PPU/SPU inputs; no game data or GPU required."""
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    if sys.platform != 'darwin':
        print('SKIP: macOS build integration requires Apple frameworks')
        return
    subprocess.run([sys.executable, str(ROOT / 'tools/build-kz2-macos.py'), '--smoke'], check=True)
    build = ROOT / 'build/kz2-macos-smoke'
    commands = json.loads((build / 'compile_commands.json').read_text())
    spu = [c for c in commands if '/synthetic/spu_recomp.c' in c['file']]
    assert len(spu) == 1, 'synthetic SPU source was omitted'
    if platform.machine() == 'arm64':
        assert '-mfma' not in spu[0]['command'] and '-msse' not in spu[0]['command'], 'x86 ISA flags reached ARM64 SPU code'
    assert (build / 'kz2').is_file(), 'native executable is missing'
    print('PASS: full native port and runtime compile with synthetic PPU/SPU input')


if __name__ == '__main__':
    main()
