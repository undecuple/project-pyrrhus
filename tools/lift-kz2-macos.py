#!/usr/bin/env python3
"""Generate the matching KZ2 1.29 PPU/SPU lift on macOS from an existing ELF.

Uses the same commands, TOC, code boundary, overrides and Lua fixup as lift.sh
and tools/spu/lift_spu.sh. No SELF conversion or keys. Run inside a read-only
input sandbox; only work/ and build/ need to be writable.
"""
import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eboot', type=Path, required=True, help='existing, decrypted 1.29 EBOOT.elf')
    parser.add_argument('--steps', choices=['all', 'ppu', 'spu'], default='all')
    args = parser.parse_args()
    if sys.platform != 'darwin' or sys.version_info < (3, 11):
        raise SystemExit('Requires macOS and Python 3.11+')
    os.chdir(ROOT)
    elf = args.eboot.resolve()
    expected = next(e for e in json.loads((ROOT / 'tools/release/eboot_sha256.json').read_text())['entries']
                    if e['title_id'] == 'BCUS98116' and e['app_ver'] == '01.29')
    if not elf.is_file() or digest(elf) != expected['sha256']:
        raise SystemExit('The input must match the known Killzone 2 USA 1.29 ELF')
    work = ROOT / 'work'
    toolkit = work / 'ps3recomp-patched'
    stamp = (toolkit / '.kz2-patchset').read_text().strip()
    wanted = hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT / 'port/patches').glob('*.patch')))).hexdigest()[:16]
    pin = subprocess.check_output(['git', 'ls-tree', 'HEAD', 'third_party/ps3recomp'], text=True).split()[2]
    patch_hash, _, revision = stamp.partition('-')
    if patch_hash != wanted or not revision or not pin.startswith(revision):
        raise SystemExit('Patched toolkit is stale; regenerate it before lifting')
    spec = importlib.util.spec_from_file_location('macos_builder', ROOT / 'tools/build-kz2-macos.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    work.mkdir(exist_ok=True)
    with (work / '.kz2-macos-build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('REFUSED: another native build/lift is running')
        if subprocess.run(['pgrep', '-x', 'ninja'], capture_output=True).returncode == 0:
            raise SystemExit('REFUSED: another Ninja build is running')
        temp = work / 'macos-tmp'
        temp.mkdir(exist_ok=True)
        # The SPU census reader uses this version-specific input location.
        staged = work / 'bin/EBOOT-129.elf'
        staged.parent.mkdir(exist_ok=True)
        if not staged.exists() or digest(staged) != expected['sha256']:
            if staged.exists():
                raise SystemExit('Refusing to replace a different staged EBOOT')
            staged.write_bytes(elf.read_bytes())
        os.environ.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(temp), KZ2_EBOOT_VER='129')
        logs = work / 'native-lift'
        logs.mkdir(exist_ok=True)

        def run(name, script, *arguments):
            log = logs / (name + '.log')
            print(f'{name}: running (one worker); log: {log}', flush=True)
            builder.run_guarded([sys.executable, '-B', str(script), *map(str, arguments)], log)
            print(f'{name}: complete', flush=True)

        analysis = work / 'analysis-129'
        recomp = work / 'recomp'
        analysis.mkdir(exist_ok=True)
        recomp.mkdir(exist_ok=True)
        if args.steps in ('all', 'ppu'):
            run('ppu-loader', toolkit / 'tools/ppu_loader.py', staged, '-o', analysis)
            run('ppu-functions', toolkit / 'tools/find_functions.py', staged,
                '--seed-json', analysis / 'EBOOT-129.functions.json', '--output', analysis / 'functions.json')
            run('ppu-lift', toolkit / 'tools/ppu_lifter.py', staged,
                '--functions', analysis / 'functions.json', '--hle-stubs', analysis / 'EBOOT-129.imports.json',
                '--toc', '0xec3038', '--code-end', '0xbd0d0c', '--overrides', ROOT / 'port/kz2/ppu_overrides.txt',
                '-j', '1', '--chunks', '64', '--output', recomp)
            run('lua-unwind', ROOT / 'tools/release/lua_unwind.py', '--recomp-dir', recomp, '--version', '129')
            (recomp / '.lift-stamp').write_text(
                f'ver=129 elf={staged} sha={expected["sha256"][:16]} code_end=0xbd0d0c toc=0xec3038 '
                f'overrides={digest(ROOT / "port/kz2/ppu_overrides.txt")[:16]} probes=none '
                f'patchset={stamp} chunks=64 date={datetime.datetime.now(datetime.timezone.utc).isoformat()}\n')
            (analysis / '.elf-sha').write_text(expected['sha256'][:16] + '\n')
        if args.steps in ('all', 'spu'):
            run('spu-lift', ROOT / 'tools/spu/lift_spu.py', '--ps3recomp', toolkit, '--out', work / 'spu', '-j', '1')
            run('spu-register', ROOT / 'tools/spu/gen_spu_register.py', '--lift', work / 'spu')
        print('Native lift steps complete. Generated sources remain under ignored work/.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc))
