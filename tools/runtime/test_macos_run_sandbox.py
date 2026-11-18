#!/usr/bin/env python3
"""Check native-run write isolation with disposable files, without game data or GPU."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    if sys.platform != 'darwin':
        print('SKIP: macOS sandbox-exec test')
        return
    spec = importlib.util.spec_from_file_location('runner', ROOT / 'tools/run-kz2-macos.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    with tempfile.TemporaryDirectory(prefix='kz2-run-sandbox-') as tmp:
        base = Path(tmp).resolve()
        work, build = base / 'work', base / 'build'
        work.mkdir(); build.mkdir()
        code = '''from pathlib import Path
import sys
allowed, denied = map(Path, sys.argv[1:])
allowed.write_text('test')
assert allowed.read_text() == 'test'
try:
    denied.write_text('test')
except PermissionError:
    pass
else:
    raise AssertionError('write outside work/build was allowed')
print('PASS: writable output accepted; write outside output directories blocked')
'''
        subprocess.run(['/usr/bin/sandbox-exec', '-p', runner.profile(work, build),
                        sys.executable, '-B', '-c', code, str(work / 'allowed'),
                        str(base / 'denied')], check=True, timeout=10)


if __name__ == '__main__':
    main()
