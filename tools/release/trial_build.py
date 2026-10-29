#!/usr/bin/env python3
"""llvm-mingw trial driver (from Project Helghast tools/release/trial_build.py): configure and compile the port with the payload's bundled
toolchain, from lift outputs made elsewhere, and time it. Runs firstrun.py's own configure and compile commands
(the same payload_tools / cmd_configure / cmd_compile), so the trial tests what a player's machine will run, minus
the lift. Standard library only. Meant for Windows (under Proton) with the payload tree; also runs on Linux.

    trial_build.py --root PAYLOAD --build DIR [--jobs N] [--toolchain DIR | --cross] [--configure-only] [--stamp]

  --build   holds recomp/ (ppu_recomp.h + chunks) copied from a NixOS lift (KZ2 has no SPU lift yet); obj/
            and kz2.exe are written under it (firstrun.py's layout)
  --cross   no llvm-mingw: firstrun.py's own fallback (port/cmake/mingw-w64.cmake, the NixOS cross compiler; run in
            `nix develop .#win`). Same configure arguments otherwise, so the CMake decisions are the player's.
  --stamp   after the compile, firstrun.py's stamp step too: its command (firstrun_check --build-dir, the B rules) and
            after_stamp (kz2.exe, the decoder DLLs, fonts and SDL3.dll beside it in DIR), so DIR/kz2.exe runs as an
            installed build does (the issue #16 reproduction and fix check).
Writes DIR/trial.json: the tools used, the two commands, wall seconds each, return codes, kz2.exe size; and
DIR/trial.log (all output). Exit 0 = kz2.exe built, 1 = a step failed, 2 = usage / inputs missing.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402


def run(cmd, env, log):
    log.write("$ " + " ".join(cmd) + "\n")
    log.flush()
    t = time.monotonic()
    rc = subprocess.call(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    return rc, round(time.monotonic() - t, 1)


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True)
    ap.add_argument("--build", required=True)
    ap.add_argument("--jobs", type=int)
    ap.add_argument("--toolchain", default="")
    ap.add_argument("--configure-only", action="store_true")
    ap.add_argument("--cross", action="store_true", help="firstrun's fallback cross toolchain (no llvm-mingw)")
    ap.add_argument("--stamp", action="store_true", help="also run firstrun's stamp step and after_stamp")
    a = ap.parse_args(argv)
    root, build = os.path.abspath(a.root), os.path.abspath(a.build)
    tools = fr.payload_tools(root)
    tc = "" if a.cross else os.path.abspath(a.toolchain) if a.toolchain else tools.get("llvm_mingw", "")
    missing = [p for p in (os.path.join(build, "recomp", "ppu_recomp.h"),) if not os.path.exists(p)]
    if not tc and not a.cross:
        missing.append("an llvm-mingw toolchain (--toolchain or <root>/toolchain/llvm-mingw)")
    if missing:
        print("trial_build: missing " + "; ".join(missing), file=out)
        return 2
    ctx = fr.Ctx(root=root, build=build, jobs=a.jobs or fr.jobs_for(fr.available_ram(), clang=bool(tc), cores=os.cpu_count()), toolchain=tc,
                 python=tools.get("python", sys.executable), cmake=tools.get("cmake", "cmake"),
                 ninja=tools.get("ninja", ""))
    rep = {"host": platform.platform(), "cores": os.cpu_count(), "jobs": ctx.jobs, "toolchain": tc,
           "cmake": ctx.cmake, "ninja": ctx.ninja, "python": ctx.python, "steps": []}
    env = ctx.env()
    ok = True
    with open(os.path.join(build, "trial.log"), "w", encoding="utf-8", errors="replace") as log:
        steps = [("configure", fr.cmd_configure(ctx)[0])]
        if not a.configure_only:
            steps.append(("compile", fr.cmd_compile(ctx)[0]))
            if a.stamp:
                steps.append(("stamp", fr.cmd_stamp(ctx)[0]))
        for name, cmd in steps:
            rc, secs = run(cmd, env, log)
            rep["steps"].append({"name": name, "cmd": cmd, "rc": rc, "seconds": secs})
            print(f"{name}: rc={rc} {secs:.0f} s", file=out)
            if rc != 0:
                ok = False
                break
    if ok and a.stamp and not a.configure_only:
        fr.after_stamp(ctx)
    exe = os.path.join(build, "obj", "kz2.exe")
    rep["exe_bytes"] = os.path.getsize(exe) if os.path.isfile(exe) else None
    with open(os.path.join(build, "trial.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    built = ok and (a.configure_only or rep["exe_bytes"] is not None)
    print(f"trial: {'ok' if built else 'FAILED'}; trial.json and trial.log in {build}", file=out)
    return 0 if built else 1


if __name__ == "__main__":
    sys.exit(main())
