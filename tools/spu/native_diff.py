#!/usr/bin/env python3
"""Lifted vs native (vs interpreted) check of KZ2's native SPU gates.

  tools/spu/native_diff.py synth [--slot N ...] [--trials T] [--seed S] [--interp]
  tools/spu/native_diff.py rec FILE_OR_DIR ... [--interp]

Builds tools/spu/native_diff_harness.c with the image's lifted spu_recomp.c ($KZ2_OUT/spu/lift/<image>: work/spu/lift
in the main checkout, KZ2_OUT=work/spu in the SPU), the patched runtime's spu_drain.c and spu_interp.c
($KZ2_OUT/ps3recomp-patched) and the native
sources (port/kz2/spu), with the lifted SPU code's flags (-O2 -msse4.1 -mfma -ffp-contract=off, as
port/kz2/CMakeLists.txt). `synth` runs synthetic inputs per gate (no game data beyond the lift itself); `rec` replays
the states the game recorded with KZ2_NATIVE_REC=DIR (game data: keep them under work/). Exit 0 when every case
matched. The gates and their images come from re/spu/native_gates.tsv.
"""
import argparse
import glob
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.environ.get("KZ2_OUT", "work")
OUT = OUT if os.path.isabs(OUT) else os.path.join(ROOT, OUT)
PT = os.environ.get("KZ2_PATCHED_DIR", os.path.join(OUT, "ps3recomp-patched"))
SPU = os.path.join(OUT, "spu")


def gates():
    rows = []
    for line in open(os.path.join(ROOT, "re", "spu", "native_gates.tsv")):
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\n").split("\t")
        rows.append(dict(image=f[0], addr=int(f[1], 16), slot=int(f[2]), job=f[3]))
    return rows


def image_bin(name, build):
    """The image's first PT_LOAD (the job module as the PM loads it at LS 0x4000) as a raw file."""
    b = open(os.path.join(SPU, "elf_in", name + ".elf"), "rb").read()
    phoff, = struct.unpack_from(">I", b, 0x1C)
    _, off, va, _, fs, _, _, _ = struct.unpack_from(">8I", b, phoff)
    p = os.path.join(build, name + ".bin")
    open(p, "wb").write(b[off:off + fs])
    return p, va


def build(name, bdir):
    os.makedirs(bdir, exist_ok=True)
    exe = os.path.join(bdir, "harness_" + name)
    lift = os.path.join(SPU, "lift", name)
    srcs = [os.path.join(ROOT, "tools/spu/native_diff_harness.c"), os.path.join(lift, "spu_recomp.c"),
            os.path.join(PT, "runtime/spu/spu_drain.c"), os.path.join(PT, "runtime/spu/spu_interp.c"),
            *sorted(glob.glob(os.path.join(ROOT, "port/kz2/spu/native_*.c")))]
    newest = max(os.path.getmtime(s) for s in srcs + [os.path.join(ROOT, "port/kz2/spu/kz2_native_jobs.h")])
    if not os.path.exists(exe) or os.path.getmtime(exe) < newest:
        inc = ["-I", os.path.join(PT, "runtime/spu"), "-I", os.path.join(PT, "include"), "-I",
               os.path.join(PT, "runtime"), "-I", lift, "-I", os.path.join(ROOT, "port/kz2/spu")]
        cmd = [os.environ.get("CC", "gcc"), "-O2", "-g", "-msse4.1", "-mfma", "-ffp-contract=off",
               "-fno-strict-aliasing", "-w", f"-DHARNESS_REGISTER={name}_spu_recomp_register", *inc, *srcs, "-lm",
               "-o", exe]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr[-4000:])
            raise SystemExit(f"build failed: {name}")
    return exe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["synth", "rec"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--slot", type=int, action="append")
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--seed", default="0x4B5A3215")
    ap.add_argument("--interp", action="store_true", help="also run the SPU interpreter (third side)")
    ap.add_argument("--build", default=os.path.join(OUT, "spu", "native_diff"))
    ap.add_argument("-v", action="store_true", help="print every case")
    ap.add_argument("--bench", type=int, default=0, help="also time each side: best of N runs per case")
    a = ap.parse_args()
    env = dict(os.environ, HARNESS_INTERP="1" if a.interp else "0", HARNESS_BENCH=str(a.bench))
    gs = gates()
    fails = 0
    totals = []
    if a.mode == "synth":
        for g in gs:
            if a.slot and g["slot"] not in a.slot:
                continue
            exe = build(g["image"], a.build)
            img, base = image_bin(g["image"], a.build)
            r = subprocess.run([exe, img, hex(base), "synth", str(g["slot"]), a.seed, str(a.trials)], env=env,
                               capture_output=True, text=True)
            lines = r.stdout.splitlines()
            bad = [l for l in lines if l.startswith("C ") and " ok " not in l]
            for l in (lines if a.v else bad[:10]):
                print(l[:300])
            t = [l for l in lines if l.startswith("T ") or l.startswith("B ")]
            print(f"{g['job']} 0x{g['addr']:X}: {' | '.join(t) if t else 'no result: ' + r.stderr[-500:]}")
            fails += r.returncode != 0
    else:
        files = []
        for f in a.files:
            files += sorted(glob.glob(os.path.join(f, "*.kz2nj"))) if os.path.isdir(f) else [f]
        by = {}
        for f in files:
            slot, = struct.unpack_from("<I", open(f, "rb").read(12), 8)
            by.setdefault(slot, []).append(f)
        for slot, fl in sorted(by.items()):
            g = next(x for x in gs if x["slot"] == slot)
            exe = build(g["image"], a.build)
            img, base = image_bin(g["image"], a.build)
            r = subprocess.run([exe, img, hex(base), "rec", *fl], env=env, capture_output=True, text=True)
            lines = r.stdout.splitlines()
            bad = [l for l in lines if l.startswith("C ") and " ok " not in l]
            for l in (lines if a.v else bad[:10]):
                print(l[:300])
            t = [l for l in lines if l.startswith("T ") or l.startswith("B ")]
            print(f"{g['job']} 0x{g['addr']:X}: {' | '.join(t) if t else 'no result: ' + r.stderr[-500:]}")
            fails += r.returncode != 0
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
