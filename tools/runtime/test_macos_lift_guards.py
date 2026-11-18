#!/usr/bin/env python3
"""Reject stale versions/toolkits and missing overrides before native compilation; synthetic inputs only."""
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    spec = importlib.util.spec_from_file_location('builder', ROOT / 'tools/build-kz2-macos.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    with tempfile.TemporaryDirectory(prefix='kz2-lift-guards-') as tmp:
        directory = Path(tmp)
        overrides = directory / 'overrides.txt'
        overrides.write_text('00001000 # synthetic override\n00002000 # synthetic override\n')
        header = directory / 'ppu_overrides.h'
        header.write_text('#define PPU_OVERRIDE_00001000\n#define PPU_OVERRIDE_00002000\n')
        stamp = directory / '.lift-stamp'
        stamp.write_text('ver=129 patchset=abcdef-1234567\n')
        builder.verify_game_lift(directory, 'abcdef-1234567', overrides)
        for text, patchset in [('ver=101 patchset=abcdef-1234567\n', 'abcdef-1234567'),
                               ('ver=129 patchset=old-1234567\n', 'abcdef-1234567')]:
            stamp.write_text(text)
            try:
                builder.verify_game_lift(directory, patchset, overrides)
            except SystemExit:
                pass
            else:
                raise AssertionError('stale lift was accepted')
        stamp.write_text('ver=129 patchset=abcdef-1234567\n')
        header.write_text('#define PPU_OVERRIDE_00001000\n')
        try:
            builder.verify_game_lift(directory, 'abcdef-1234567', overrides)
        except SystemExit:
            pass
        else:
            raise AssertionError('missing override was accepted')
    print('PASS: matching lift accepted; stale version/toolkit and missing overrides rejected')


if __name__ == '__main__':
    main()
