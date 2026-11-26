#!/usr/bin/env python3
"""Host test: why the install folder may not hold '[', ']' or ';' (firstrun_check P1, kz2.iss
HasBadPathChar). The same failure reported on Project Helghast (#20): its first-run configure stopped in CMake's
compiler-id step for an install folder named like D:\\games\\recomp[\\....

Reproduced here with the host's CMake, no game data:
  1. CMake's list rule: ';' splits a path in two, and an unbalanced '[' stops the splitting of the rest of the list
     (two folders become one element). CMake's own modules keep the compiler's folders in such lists.
  2. A C project configured in a build folder whose path holds ';' fails in CMakeDetermineCompilerId (needs a C
     compiler on PATH; skipped without one).
  3. A plain folder and '(' ')' '#' ' ' configure fine, so P1 refuses only the three characters.
  3b. A folder with spaces configures and builds a small program (case 4; the default install folder has a space),
      with a plain folder as the control; letters outside ASCII and other punctuation are probed and printed (INFO).
  4. firstrun_check.PATH_BAD_CHARS is exactly '[', ']' and ';'.
Not reproduced here: '[' in the folder that holds CMake itself (the player's toolchain\\cmake under the install
folder). KZ3 reproduced that on a Windows 10 VM (2026-10-29): CMake 4.4.4 under a '[' folder fails its own compiler
detection (CMakeCompilerIdDetection.cmake: "include could not find requested file" with the ';'-joined module list,
then 'No preprocessor test for "Intel"'), while the same CMake in a plain folder, and a project path with '[' with
CMake outside it, work. So no quoting in our configure call can avoid it: the refusal is the fix.
Needs cmake (`nix develop .#win`); without it the test says SKIP and passes.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun_check as fc  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"\n     {str(detail)[-700:]}"))
    if not cond:
        FAILS.append(name)


def run(args, cwd=None):
    r = subprocess.run(args, capture_output=True, text=True, timeout=180, cwd=cwd)
    return r.returncode, " ".join((r.stdout + r.stderr).split())


def main():
    check("P1 refuses exactly '[', ']' and ';'", set(fc.PATH_BAD_CHARS) == set("[];")
          and fc.path_bad_chars("D:\\games\\recomp[\\x") == "[" and fc.path_bad_chars("C:\\a (1) #2") == "")
    if not shutil.which("cmake"):
        print("test_cmake_path_chars: SKIP (no cmake on PATH; run in `nix develop .#win`)")
        return 1 if FAILS else 0
    tmp = tempfile.mkdtemp(prefix="kz2-pathchars-")
    try:
        script = os.path.join(tmp, "lists.cmake")
        with open(script, "w", encoding="utf-8") as f:
            f.write('set(a "D:/games/recomp[/tc/lib;D:/games/recomp[/tc/include")\nlist(LENGTH a n)\n'
                    'message("bracket ${n}")\nset(b "D:/games/x;y/tc/lib;D:/other")\nlist(LENGTH b m)\n'
                    'message("semicolon ${m}")\nset(c "D:/games/plain/tc/lib;D:/other")\nlist(LENGTH c k)\n'
                    'message("plain ${k}")\n')
        rc, out = run(["cmake", "-P", script])
        check("1 CMake lists: an unbalanced '[' joins two folders into one element, ';' splits one in two",
              rc == 0 and "bracket 1" in out and "semicolon 3" in out and "plain 2" in out, out)
        cc = shutil.which("cc") or shutil.which("gcc")
        tc = []
        if not cc and shutil.which("x86_64-w64-mingw32-gcc"):     # `nix develop .#win`: the cross compiler only
            cc, tc = "mingw", ["-DCMAKE_TOOLCHAIN_FILE=" + os.path.join(os.path.dirname(os.path.dirname(HERE)),
                                                                          "port", "cmake", "mingw-w64.cmake")]
        if not cc:
            print("SKIP 2/3: no C compiler on PATH")
        else:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "CMakeLists.txt"), "w", encoding="utf-8") as f:
                f.write("cmake_minimum_required(VERSION 3.20)\nproject(t C)\n")
            rc, out = run(["cmake", "-S", src, "-B", os.path.join(tmp, "build;1")] + tc)
            check("2 a build folder with ';' fails in CMake's compiler-id step", rc != 0
                  and "CMakeDetermineCompilerId" in out, out)
            for name in ("plain", "with (paren) #2"):
                rc, out = run(["cmake", "-S", src, "-B", os.path.join(tmp, name)] + tc)
                check(f"3 a build folder named {name!r} configures", rc == 0, out)
            # 4: configure AND build a small program whose source and build folders sit under a
            # folder with spaces (the default install folder ends in "Project Pyrrhus"), and probe letters outside
            # ASCII and the characters a Windows path may hold that CMake, Ninja or the compiler might mind. Spaces
            # must build (firstrun_check has no space check); the probe lines say what this host's tools do with the
            # rest (INFO only: Windows' code pages are not reproduced here, so P2 only warns).
            with open(os.path.join(src, "CMakeLists.txt"), "w", encoding="utf-8") as f:
                f.write("cmake_minimum_required(VERSION 3.20)\nproject(t C)\nadd_executable(t main.c)\n")
            with open(os.path.join(src, "main.c"), "w", encoding="utf-8") as f:
                f.write("#include <stdio.h>\nint main(void) { puts(\"ok\"); return 0; }\n")
            gen = ["-G", "Ninja"] if shutil.which("ninja") else []

            def builds(name):
                top = os.path.join(tmp, name)
                s2 = os.path.join(top, "src")
                shutil.copytree(src, s2)
                b = os.path.join(top, "build")
                rc1, o1 = run(["cmake", "-S", s2, "-B", b] + gen + tc)
                rc2, o2 = run(["cmake", "--build", b]) if rc1 == 0 else (rc1, "")
                return rc1 == 0 and rc2 == 0, (o1 + " " + o2)[-400:]

            ok, out = builds("Project Pyrrhus with spaces")
            check("4 a folder with spaces configures and builds", ok, out)
            ok, out = builds("plain_control")
            check("4 negative control: a plain folder configures and builds", ok, out)
            for name in ("Jos\u00e9 \u00f1 \u00e4", "x$y", "x&y", "x!y", "x%y", "x=y", "x'y", "x,y", "x+y", "x~1", "x@y", "x`y"):
                ok, out = builds("probe " + name)
                print(f"INFO 4 probe {name!r}: {'builds' if ok else 'FAILS: ' + out[-200:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"test_cmake_path_chars: {'PASS' if not FAILS else 'FAIL ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
