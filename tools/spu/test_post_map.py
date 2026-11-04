#!/usr/bin/env python3
"""Host test for tools/spu/post_map.py: a synthetic [pmap] log with one frame -- the walker writes back
a surface, Downsample GETs it and PUTs its output, Upsample GETs that, the walker binds Upsample's output, and a PPU
thread reads one output page -- must classify every input's writer and every output's reader."""
import io, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import post_map

L = """[pmap-thr] 0 100 wacct=rsx:frame ppu=- hook=2
[pmap-thr] 1 200 wacct=spu-k0 ppu=- hook=1
[pmap-thr] 2 300 wacct=- ppu=main hook=0
[pmap] 13 0 0 1 0 0 0 0
[pmap] 11 10 0 41000000 4000 1000080 1000 4
[pmap] 53 20 1 d0 64 0 0 0
[pmap] 1 21 1 41000000 4000 d0 4100 0
[pmap] 2 30 1 42000000 2000 d0 4100 0
[pmap] 53 40 1 d1 64 0 0 0
[pmap] 1 41 1 42000000 2000 d1 4100 0
[pmap] 2 50 1 43000000 4000 d1 4100 0
[pmap] 2 51 1 41d8424c 4 de 4100 0
[pmap] 2 52 1 44000000 40 d1 4100 0
[pmap] 12 60 0 43000000 4000 800040 4000 a5
[pmap] 90 61 2 43001010 1234 5678 0 1
[pmap] 13 1000 0 2 0 0 0 0
[pmap] 13 2000 0 3 0 0 0 0
"""
with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
    f.write(L)
thr, ev = post_map.load(f.name)
os.unlink(f.name)
out = io.StringIO()
r = post_map.analyse(thr, ev, frames=1, out=out)
fail = []
def want(cond, what):
    if not cond:
        fail.append(what)
want(r['inputs'].get('post:Downsample') == {'walker:writeback': 4}, 'Downsample input from the write-back: %s' % r['inputs'])
want(r['inputs'].get('post:Upsample') == {'post:Downsample': 2}, 'Upsample input from Downsample: %s' % r['inputs'])
want(r['outputs'].get('post:Downsample') == {'post:Upsample': 2}, 'Downsample output read by Upsample: %s' % r['outputs'])
want(r['outputs'].get('post:Upsample', {}).get('walker:texbind') == 4, 'Upsample output bound: %s' % r['outputs'])
want(r['outputs'].get('post:Upsample', {}).get('cpu:ppu:main') == 1, 'PPU reader seen: %s' % r['outputs'])
want(r['other_readers'] == 1, 'one other reader: %s' % r['other_readers'])
want('small P 0x41D84240 x1' in out.getvalue(), 'Unlock small put listed')
# the binary form (KZ2_POST_MAP_OUT) gives the same events
import struct
with tempfile.NamedTemporaryFile('wb', suffix='.bin', delete=False) as fb:
    fb.write(b'KZ2PMAP1' + struct.pack('<qq', len(ev), 0) + bytes(40))
    for t, k, ti, a, b, c, d, e in ev:
        fb.write(struct.pack('<QIIIIIHH', t, a, b, c, d, e, k, ti))
with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as ft:
    ft.write('\n'.join(l for l in L.splitlines() if l.startswith('[pmap-thr]')) + '\n')
thr2, ev2 = post_map.load(ft.name, fb.name)
os.unlink(fb.name); os.unlink(ft.name)
want(ev2 == ev and thr2 == thr, 'binary events equal the printed ones')
print('test_post_map: %s' % ('PASS' if not fail else 'FAIL\n  ' + '\n  '.join(fail)))
sys.exit(1 if fail else 0)
