#!/usr/bin/env python3
"""Host test for tools/release/firstrun.py (from Project Helghast) on synthetic fake steps (no game data, no toolchain: each step runs the
current Python with a one-line script). Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_firstrun.py

Cases: PROGRESS/RESULT line format, the --status-file and a monotonic bar ending at 100; the real step table's weights (sum 100) and the
runner's normalisation; Ninja "[x/y]" parsing; resume after a failed step and after a cancel (no marker, earlier steps
skipped); a changed input fingerprint re-runs everything; log next to the setup, earlier log renamed by its start
time, fallback to the temp folder; home-folder redaction; the install's logs/ copy keeps five; --dry-run writes
nothing and lists every step; the RAM -> jobs rule; cleaning stays inside the build folder; --interactive (portable
zip): re-asks a missing folder, finds the EBOOT, runs the real check on synthetic fixtures, writes kz2-install.ini,
shows a console bar instead of raw lines and logs the answers; a failed check shows the update help and offers
check again / quit; the opt-in version check is asked first and logged; the console bar's compile count.
"""
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firstrun as fr  # noqa: E402

# The RPCS3 question is covered by test_rpcs3_import.py; here the folders are typed (no RPCS3 on this machine assumed).
fr.rpcs3_step = lambda *a, **k: None
FAILS = []
PY = sys.executable


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("FAIL", what)


def py(code):
    return [PY, "-c", code]


def append(path, text):
    return py(f"open({path!r}, 'a').write({text!r})")


def run(tmp, steps, *extra, log_dir=None):
    out = io.StringIO()
    args = ["--dump", os.path.join(tmp, "dump"), "--root", os.path.join(tmp, "root"), "--jobs", "1",
            "--log-dir", log_dir or os.path.join(tmp, "dl"), *extra]
    rc = fr.main(args, steps=steps, out=out)
    return rc, out.getvalue()


def progress(text):
    return [dict(kv.split("=", 1) for kv in l.split()[1:]) for l in text.splitlines() if l.startswith("PROGRESS ")]


def tables(root, names=("ppu_overrides.txt", "ppu_overrides-101.txt")):
    os.makedirs(os.path.join(root, "port", "kz2"), exist_ok=True)
    for n in names:
        with open(os.path.join(root, "port", "kz2", n), "w") as f:
            f.write("0x00010000  # x\n")


def main():
    tmp = tempfile.mkdtemp(prefix="kz2-firstrun-test-")
    try:
        os.makedirs(os.path.join(tmp, "dump"))
        os.makedirs(os.path.join(tmp, "root"))
        for r0 in (tmp, os.path.join(tmp, "root"), os.path.join(tmp, "verroot")):
            tables(r0)     # the lift needs its PPU override table (firstrun.overrides_file)
        cnt = os.path.join(tmp, "count.txt")
        gate = os.path.join(tmp, "gate")

        # 1. progress format, bar monotonic and complete
        steps = [fr.Step("a", "A", 1, lambda c: [append(cnt, "a")]),
                 fr.Step("b", "B", 2, lambda c: [append(cnt, "b"), append(cnt, "B")]),
                 fr.Step("c", "C", 1, lambda c: [])]
        rc, out = run(tmp, steps)
        p = progress(out)
        check(rc == 0, f"1 rc {rc}")
        check(all(set(x) >= {"step", "name", "done", "total", "elapsed", "pct"} for x in p), "1 progress fields")
        check(all(re.fullmatch(r"\d+/3", x["step"]) for x in p), "1 step=N/M")
        pcts = [float(x["pct"]) for x in p]
        check(pcts == sorted(pcts) and pcts[-1] == 100.0, f"1 pct monotonic to 100: {pcts}")
        check(any(x["name"] == "b" and x["done"] == "1" and x["total"] == "2" for x in p), "1 per-command progress")
        check("RESULT ok=1 step=-" in out, "1 RESULT ok")

        sf = os.path.join(tmp, "status.txt")
        rc, out = run(tmp, steps, "--build", os.path.join(tmp, "b1s"), "--status-file", sf)
        st = open(sf).read().splitlines()
        check(len(st) == 2 and st[0].startswith("LOG path=") and st[1].startswith("RESULT ok=1"),
              f"1 status file holds LOG + last line: {st}")

        # 2. weights
        check(sum(s.weight for s in fr.STEPS) == 100, "2 real STEPS weights sum to 100")
        check(len({s.name for s in fr.STEPS}) == len(fr.STEPS) and fr.STEPS[0].name == "check" and fr.STEPS[0].always,
              "2 check runs first, always; unique names")
        r = fr.Runner(fr.Ctx(root=tmp, build=tmp), steps, None)
        check(abs(sum(r.frac) - 1.0) < 1e-9, "2 normalised weights sum to 1")

        # 3. ninja
        nin = "import sys\nfor i in range(1,5): print(f'[{i}/4] Building CXX obj{i}.o')"
        rc, out = run(tmp, [fr.Step("compile", "Compiling", 1, lambda c: [py(nin)], ninja=True)],
                      "--build", os.path.join(tmp, "b3"))
        nd = [(x["done"], x["total"]) for x in progress(out) if x["total"] == "4"]
        check(nd == [("1", "4"), ("2", "4"), ("3", "4"), ("4", "4")], f"3 ninja parsed: {nd}")
        check(rc == 0 and "[3/4] Building CXX obj3.o" in out, "3 ninja output passed through")

        # 4. resume after a failure
        b4 = os.path.join(tmp, "b4")
        open(cnt, "w").close()
        gated = py(f"import os,sys; sys.exit(0 if os.path.exists({gate!r}) else 3)")
        steps4 = [fr.Step("one", "One", 1, lambda c: [append(cnt, "1")]),
                  fr.Step("two", "Two", 1, lambda c: [gated, append(cnt, "2")]),
                  fr.Step("three", "Three", 1, lambda c: [append(cnt, "3")])]
        rc, out = run(tmp, steps4, "--build", b4)
        check(rc == 1 and "RESULT ok=0 step=two" in out, f"4 failure reported (rc {rc})")
        check(os.path.exists(os.path.join(b4, ".firstrun", "01-one.done")), "4 marker for the finished step")
        check(not os.path.exists(os.path.join(b4, ".firstrun", "02-two.done")), "4 no marker for the failed step")
        open(gate, "w").close()
        rc, out = run(tmp, steps4, "--build", b4)
        check(rc == 0 and open(cnt).read() == "123", f"4 resumed at step two: rc {rc}, ran {open(cnt).read()!r}")

        # 5. cancel (Ctrl+C inside a step) leaves no marker; the next run resumes there
        b5 = os.path.join(tmp, "b5")
        open(cnt, "w").close()
        state = {"cancel": True}

        def maybe_cancel(c):
            if state["cancel"]:
                raise KeyboardInterrupt()
        steps5 = [fr.Step("one", "One", 1, lambda c: [append(cnt, "1")]),
                  fr.Step("two", "Two", 1, lambda c: [append(cnt, "2")], after=maybe_cancel),
                  fr.Step("three", "Three", 1, lambda c: [append(cnt, "3")])]
        rc, out = run(tmp, steps5, "--build", b5)
        check(rc == 130 and "RESULT ok=0 step=cancelled" in out, f"5 cancel rc {rc}")
        check(not os.path.exists(os.path.join(b5, ".firstrun", "02-two.done")), "5 no marker for the cancelled step")
        state["cancel"] = False
        rc, out = run(tmp, steps5, "--build", b5)
        check(rc == 0 and open(cnt).read() == "1223", f"5 resumed: ran {open(cnt).read()!r}")

        # 5b. --stop-file (the wizard's Stop button): the running child ends at once, no marker, rc 130, resume
        b5b, stopf = os.path.join(tmp, "b5b"), os.path.join(tmp, "stop.flag")
        open(cnt, "w").close()
        slow = py(f"import time; open({stopf!r}, 'w').close(); time.sleep(60)")
        state5b = {"stop": True}
        steps5b = [fr.Step("one", "One", 1, lambda c: [append(cnt, "1")]),
                   fr.Step("two", "Two", 1, lambda c: [slow if state5b["stop"] else append(cnt, "2")]),
                   fr.Step("three", "Three", 1, lambda c: [append(cnt, "3")])]
        t5 = time.monotonic()
        rc, out = run(tmp, steps5b, "--build", b5b, "--stop-file", stopf)
        check(rc == 130 and "RESULT ok=0 step=cancelled" in out and time.monotonic() - t5 < 20,
              f"5b stop file ends the step: rc {rc} after {time.monotonic() - t5:.1f} s")
        check(not os.path.exists(os.path.join(b5b, ".firstrun", "02-two.done")), "5b no marker for the stopped step")
        os.remove(stopf)
        state5b["stop"] = False
        rc, out = run(tmp, steps5b, "--build", b5b, "--stop-file", stopf)
        check(rc == 0 and open(cnt).read() == "123", f"5b resumed: ran {open(cnt).read()!r}")

        # 6. a changed input (another update folder) makes every marker stale
        open(cnt, "w").close()
        os.makedirs(os.path.join(tmp, "upd"), exist_ok=True)
        rc, out = run(tmp, steps5, "--build", b5, "--update", os.path.join(tmp, "upd"))
        check(rc == 0 and open(cnt).read() == "123", f"6 new inputs re-run all: {open(cnt).read()!r}")

        # 7. log location, rotation by start time, fallback
        dl = os.path.join(tmp, "dl")
        log = os.path.join(dl, fr.DEFAULT_LOG_NAME)
        check(os.path.isfile(log) and f"LOG path={log}" in out, "7 log next to the setup")
        first = open(log).readline()
        check(first.startswith("# started "), "7 log starts with its start time")
        stamp = first.split()[2].replace("-", "").replace(":", "").replace("T", "-")
        run(tmp, steps5, "--build", b5)
        rotated = [n for n in os.listdir(dl) if n.startswith("Project-Pyrrhus-setup-")]
        check(any(n.startswith(f"Project-Pyrrhus-setup-{stamp}") for n in rotated), f"7 earlier log renamed: {rotated}")
        body = open(log).read()
        check("$ " in body and "# exit 0" in body and "## step 1/3 one" in body, "7 log has commands, exits, steps")
        notdir = os.path.join(tmp, "a-file")
        open(notdir, "w").close()
        tdir = os.path.join(tmp, "tmpdir")
        os.makedirs(tdir)
        old_tmp = tempfile.tempdir
        tempfile.tempdir = tdir
        try:
            rc, out = run(tmp, steps5, "--build", b5, log_dir=notdir)
        finally:
            tempfile.tempdir = old_tmp
        check(os.path.isfile(os.path.join(tdir, fr.DEFAULT_LOG_NAME)), "7 fallback to the temp folder")
        check("log folder not writable" in open(os.path.join(tdir, fr.DEFAULT_LOG_NAME)).read(), "7 fallback noted")

        # 8. redaction of the home folder
        home = os.path.join(tmp, "Users", "Jane Doe")
        old_env = dict(os.environ)
        os.environ["USERPROFILE"] = home
        os.environ["HOME"] = home
        try:
            red = fr.redactor()
            check(red(f"{home}/Downloads/x") == "%USERPROFILE%/Downloads/x", "8 redacts the home path")
            check(red(home.replace("/", "\\") + "\\x") == "%USERPROFILE%\\x", "8 redacts backslash form")
            say = py(f"print({os.path.join(home, 'rpcs3', 'dev_hdd0')!r})")
            rc, out = run(tmp, [fr.Step("say", "Say", 1, lambda c: [say])], "--build", os.path.join(tmp, "b8"))
            body = open(log).read()
            check("Jane Doe" not in body and "%USERPROFILE%" in body, "8 log redacted")
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        # 9. install logs/ copy keeps five
        logs = os.path.join(tmp, "root", "logs")
        for i in range(7):
            open(os.path.join(logs, f"firstrun-20200101-00000{i}.log"), "w").close()
        fr.copy_to_install_logs(log, logs)
        kept = sorted(os.listdir(logs))
        check(len(kept) == fr.KEEP_LOG_COPIES and "firstrun-20200101-000000.log" not in kept, f"9 kept: {kept}")

        # 10. --dry-run on the real table writes nothing and lists all steps with commands
        b10 = os.path.join(tmp, "b10")
        dl10 = os.path.join(tmp, "dl10")
        os.makedirs(dl10)
        out = io.StringIO()
        rc = fr.main(["--dump", os.path.join(tmp, "dump"), "--update", os.path.join(tmp, "upd"),
                      "--eboot", os.path.join(tmp, "upd", "USRDIR", "EBOOT.elf"), "--root", os.path.join(tmp, "root"),
                      "--build", b10, "--jobs", "2", "--log-dir", dl10, "--dry-run"], out=out)
        o = out.getvalue()
        check(rc == 0 and not os.path.exists(b10) and os.listdir(dl10) == [], "10 dry-run writes nothing")
        check(all(f" {s.name} " in o for s in fr.STEPS) and "firstrun_check.py" in o and "ppu_lifter.py" in o
              and "spu_step.py" in o
              and "--build" in o and "-j 2" in o, "10 plan lists steps and commands")
        check(sum(float(m) for m in re.findall(r"(\d+\.\d)%", o)) > 99.9, "10 plan weights add to 100%")
        nolog = os.path.join(tmp, "nolog", "sub")
        fr.main(["--dump", os.path.join(tmp, "dump"), "--build", b10, "--log-dir", nolog, "--dry-run"], out=io.StringIO())
        check(not os.path.exists(os.path.join(tmp, "nolog")) and not os.path.exists(b10),
              "10 dry-run creates no log folder")

        # 11. RAM rule, clean boundary
        G = fr.GIB
        check([fr.jobs_for(x) for x in (None, 4 * G, 9 * G, 11.5 * G, 64 * G)] == [1, 1, 1, 2, 8], "11 jobs rule (64 chunks)")
        check([fr.jobs_for(x, clang=True, cores=12) for x in (None, 2 * G, 4 * G, 8.5 * G, 64 * G)] == [1, 1, 1, 5, 12]
              and fr.jobs_for(64 * G, clang=True, cores=32) == 16, "11 clang jobs rule (measured)")
        cj = fr.Ctx(root=tmp, build=os.path.join(tmp, "bj"), jobs=12)
        check(" -j 4 " in " ".join(fr.cmd_ppu_lift(cj)[-1]) + " "
              and fr.cmd_compile(cj)[0][-1] == "12", "11 lift capped at 4 workers, compile uses all jobs")
        # 11b. EBOOT version of the tree: tools/lift.sh's default code end and TOC pick the lift constants and env
        vr = os.path.join(tmp, "verroot")
        c = fr.Ctx(root=vr, build=os.path.join(vr, "b"))
        check(c.ver == "129", "11b no lift.sh: 129")
        os.makedirs(os.path.join(vr, "kz2-setup"))
        lsh = os.path.join(vr, "kz2-setup", "lift.sh")
        with open(lsh, "w") as f:
            f.write('CODE_END="${KZ2_CODE_END:-0xbba45c}"\nTOC="${KZ2_TOC:-0xeb2958}"\n')
        c = fr.Ctx(root=vr, build=os.path.join(vr, "b"))
        lift = " ".join(fr.cmd_ppu_lift(c)[-1])
        check(c.ver == "101" and "--toc 0xeb2958 --code-end 0xbba45c" in lift and c.env()["KZ2_EBOOT_VER"] == "101"
              and "port/kz2/ppu_overrides-101.txt" in lift.replace(os.sep, "/"),
              "11b lift.sh 1.01 defaults: 1.01 constants and lift.sh's 1.01 override list")
        with open(lsh, "w") as f:
            f.write('CODE_END="${KZ2_CODE_END:-0xBD0D0C}"\nTOC="${KZ2_TOC:-0xEC3038}"\n')
        c = fr.Ctx(root=vr, build=os.path.join(vr, "b"))
        lift = " ".join(fr.cmd_ppu_lift(c)[-1])
        check(c.ver == "129" and "--toc 0xec3038 --code-end 0xbd0d0c" in lift
              and "port/kz2/ppu_overrides.txt" in lift.replace(os.sep, "/"), "11b lift.sh 1.29 constants: 129")
        for v in ("101", "129"):    # lift.sh since the 1.29 move: VER="${KZ2_EBOOT_VER:-129}" and a version table
            with open(lsh, "w") as f:
                f.write(f'VER="${{KZ2_EBOOT_VER:-{v}}}"\ncase "$VER" in\n  129) D_END=0xbd0d0c ;;\nesac\n')
            check(fr.Ctx(root=vr, build=os.path.join(vr, "b")).ver == v, f"11b lift.sh VER default {v}: {v}")
        with open(lsh, "w") as f:
            f.write('CODE_END="${KZ2_CODE_END:-0xBD0D0C}"\nTOC="${KZ2_TOC:-0xEC3038}"\n')
        c = fr.Ctx(root=vr, build=os.path.join(vr, "b"))
        c.eboot = os.path.join(vr, "EBOOT-129.elf")
        lj = " ".join(fr.cmd_load(c)[-1] + fr.cmd_ppu_lift(c)[-1])
        check("EBOOT-129.functions.json" in lj and "EBOOT-129.imports.json" in lj,
              "11b the loader outputs are named after the player's EBOOT file (as lift.sh's STEM)")
        # 11c. SPU lift step: same scripts as BUILDING.md 3b, EBOOT version in step with the PPU lift, output under build/spu
        c.eboot = os.path.join(vr, "EBOOT.elf")
        sp = fr.cmd_spu_lift(c)
        spj = " ".join(sp[0]).replace(os.sep, "/")
        check(len(sp) == 1 and "release/spu_step.py" in spj
              and f"--eboot {c.eboot}" in spj and c.env()["KZ2_EBOOT_VER"] == "129", "11c spu_step on the EBOOT, version 129")
        order = [s.name for s in fr.STEPS]
        check(order.index("ppu-lift") < order.index("spu-lift") < order.index("configure"),
              "11c spu-lift runs between the PPU lift and configure")
        cf = " ".join(fr.cmd_configure(c)[0]).replace(os.sep, "/")
        check("-DSPU_DIR=" in cf and cf.split("-DSPU_DIR=")[1].split()[0].endswith("b/spu/lift"), "11c configure points SPU_DIR at build/spu/lift")
        h0 = fr.lift_inputs_hash(c)
        os.makedirs(os.path.join(vr, "re"), exist_ok=True)
        with open(os.path.join(vr, "re", "wws_jobs_v129.tsv"), "w") as f:
            f.write("kind\n")
        h1 = fr.lift_inputs_hash(c)
        with open(os.path.join(vr, "re", "wws_jobs_v129.tsv"), "w") as f:
            f.write("kind\nelf\n")
        check(h0 != h1 != fr.lift_inputs_hash(c), "11c a changed image table changes the lift fingerprint")
        r = fr.Runner(c, [], None, out=io.StringIO())
        c.facts = {"eboot_elf": {"version": "1.01"}}
        check("built for the 1.29 EBOOT" in r.version_mismatch(), "11b 1.01 EBOOT on a 1.29 tree refused")
        with open(lsh, "w") as f:
            f.write('CODE_END="${KZ2_CODE_END:-0xC00000}"\nTOC="${KZ2_TOC:-0xf00000}"\n')
        check(fr.Ctx(root=vr, build=os.path.join(vr, "b")).ver == "129", "11b unmapped constants: the default 129")
        with open(lsh, "w") as f:
            f.write('CODE_END="${KZ2_CODE_END:-0xbba45c}"\nTOC="${KZ2_TOC:-0xeb2958}"\n')
        c = fr.Ctx(root=vr, build=os.path.join(vr, "b"))
        r = fr.Runner(c, [], None, out=io.StringIO())
        c.facts = {"eboot_elf": {"version": "1.29"}}
        check("built for the 1.01 EBOOT" in r.version_mismatch(), "11b 1.29 EBOOT on a 1.01 tree refused")
        c.facts = {"eboot_elf": {"version": "1.01"}}
        check(r.version_mismatch() == "", "11b matching EBOOT accepted")
        c.facts = {"eboot_elf": {"version": None}}
        check(r.version_mismatch() == "", "11b unknown size: the check's warning only")
        b11 = os.path.join(tmp, "b11")
        os.makedirs(os.path.join(b11, "obj"))
        outside = os.path.join(tmp, "outside")
        os.makedirs(outside)
        c = fr.Ctx(root=tmp, build=b11)
        fr.safe_clean(c, outside)
        fr.safe_clean(c, b11)
        fr.safe_clean(c, os.path.join(b11, "obj"))
        check(os.path.isdir(outside) and os.path.isdir(b11) and not os.path.exists(os.path.join(b11, "obj")),
              "11 clean only inside the build folder")
        # 11c. install over an earlier version: changed payload files touched, toolchain change cleans obj
        r11 = os.path.join(tmp, "r11c")
        b11c = os.path.join(r11, "build")
        os.makedirs(os.path.join(r11, "port", "kz2"))
        os.makedirs(os.path.join(b11c, "obj"))
        for n in ("a.c", "b.c"):
            with open(os.path.join(r11, "port", "kz2", n), "w") as f:
                f.write(n)
            os.utime(os.path.join(r11, "port", "kz2", n), (1000, 1000))

        def man(entries):
            with open(os.path.join(r11, "manifest.json"), "w") as f:
                json.dump({"files": [{"path": p, "sha256": h} for p, h in entries]}, f)
        man([("port/kz2/a.c", "1"), ("port/kz2/b.c", "1"), ("toolchain/clang.exe", "1")])
        c = fr.Ctx(root=r11, build=b11c)
        check(fr.prepare_sources(c) == [] and os.path.getmtime(os.path.join(r11, "port", "kz2", "a.c")) == 1000,
              "11c no record (first build): nothing touched")
        fr.record_sources(c)
        man([("port/kz2/a.c", "2"), ("port/kz2/b.c", "1"), ("toolchain/clang.exe", "1")])
        cl = fr.prepare_sources(c)
        check(cl == [] and c.touched == ["port/kz2/a.c"]
              and os.path.getmtime(os.path.join(r11, "port", "kz2", "a.c")) > 1000
              and os.path.getmtime(os.path.join(r11, "port", "kz2", "b.c")) == 1000, "11c the changed source touched")
        man([("port/kz2/a.c", "1"), ("port/kz2/b.c", "1"), ("toolchain/clang.exe", "2")])
        check(fr.prepare_sources(c) == [c.b("obj")], "11c a changed toolchain cleans obj")
        check(fr.Ctx(root=tmp, build=os.path.join(tmp, "bx")) and fr.payload_hashes(tmp) == {}, "11c no manifest: {}")
        # 12. --interactive (portable zip's text UI), with the real firstrun_check on synthetic fixtures
        import types
        import firstrun_check as fc
        import test_firstrun_check as tfc
        fc.MIN_PSARC_BYTES = 1024             # the fixtures' psarc is a few KB
        t12 = os.path.join(tmp, "i12")
        d12, u12 = tfc.make_dump(t12), tfc.make_update(t12)
        root12, dl12 = os.path.join(t12, "root"), os.path.join(t12, "dl")
        os.makedirs(root12)
        os.makedirs(dl12)
        answers = iter([os.path.join(t12, "nope"), d12, u12, "", "n", "y", "xbox", "fullscreen", ""])
        asked = []

        def ask(q):
            asked.append(q)
            return next(answers)
        o12 = io.StringIO()
        rc = fr.main(["--interactive", "--portable", "--root", root12, "--log-dir", dl12, "--jobs", "1",
                      "--log-name", "kz2-firstrun.log"], steps=steps, out=o12, ask=ask)
        o = o12.getvalue()
        check(rc == 0 and "not found" in o and "OK   E1" in o and "Done in" in o and "[" + "#" * 30 + "]" in o
              and "PROGRESS " not in o, f"12 interactive build: rc {rc} {o[-400:]!r}")
        check(any("Decrypted EBOOT" in q and "EBOOT.elf" in q for q in asked), "12 EBOOT default offered")
        ini = open(os.path.join(root12, "kz2-install.ini")).read()
        check("portable = 1" in ini and "check_updates = 0" in ini and "layout = modern" in ini and "prompts = xbox" in ini and "mode = fullscreen" in ini and "prepare" not in ini, f"12 kz2-install.ini: {ini!r}")
        lg = open(os.path.join(dl12, "kz2-firstrun.log")).read()
        check(lg.startswith("# started") and "# interactive check" in lg and "E1:" in lg and "RESULT ok=1" in lg,
              "12 one log with header, the check and the build")

        a12 = types.SimpleNamespace(dump="", update="", eboot="", build=os.path.join(t12, "b"), portable=False)
        res = iter([(1, "FAIL U0: update folder not found\n"), (0, "OK   D1: fine\n")])
        answers = iter([d12, u12, "", "", "y", "y", "n", "PS5", "", "n"])
        notes, o12 = [], io.StringIO()
        go = fr.interactive(a12, root12, "x.log", notes, ask=lambda q: next(answers), out=o12,
                            check=lambda *x: next(res),
                            vcheck=lambda cur: {"status": "newer", "current": cur, "latest": "v9.0.0",
                                                "url": "https://example.invalid/r", "detail": ""})
        o = o12.getvalue()
        check(go is False and "install the 1.29 update in RPCS3" in o and "v9.0.0" in o and a12.update == u12, "12 failed check, help, retry")
        check(any("version check (player asked): status=newer" in n for n in notes), f"12 version check logged {notes}")
        ini = open(os.path.join(root12, "kz2-install.ini")).read()
        check("portable = 0" in ini and "check_updates = 1" in ini and "layout = original" in ini and "prompts = ps4" in ini and "mode = windowed" in ini, f"12 ini after opt-in: {ini!r}")
        answers = iter([d12, u12, "", "q"])
        go = fr.interactive(a12, root12, "x.log", [], ask=lambda q: next(answers), out=io.StringIO(),
                            check=lambda *x: (1, "FAIL D1: x\n"))
        check(go is False, "12 quit after a failed check")
        # 12d. folder answers one level too deep are stepped up (PS3_GAME/USRDIR, the update's USRDIR), and the EBOOT
        # question takes the folder holding EBOOT.elf, saying where it looked (adapted from Project Helghast v0.1.2 and v0.1.4)
        empty12 = os.path.join(t12, "empty")
        os.makedirs(empty12, exist_ok=True)
        got, o12d = [], io.StringIO()
        a12d = types.SimpleNamespace(dump="", update="", eboot="", build=os.path.join(t12, "b"), portable=False)
        answers = iter([os.path.join(d12, "PS3_GAME", "USRDIR"), os.path.join(u12, "USRDIR"), empty12, u12, "q"])
        fr.interactive(a12d, root12, "x.log", [], ask=lambda q: next(answers), out=o12d,
                       check=lambda *x: (got.append(x), (1, "FAIL D1: x\n"))[1])
        o = o12d.getvalue()
        check(got == [(os.path.abspath(d12), os.path.abspath(u12), os.path.abspath(os.path.join(u12, "USRDIR", "EBOOT.elf")))]
              and "is a folder without EBOOT.elf or " in o and o.count("using ") == 3, f"12d folder answers: {got} {o[-400:]!r}")

        # 12b. --check-first: the folders from setup (kz2-install.ini [paths], via launch.py) are checked before any
        # folder question; the wizard's other answers are kept (no version, pad, prompt or display question)
        a12b = types.SimpleNamespace(dump=d12, update=u12, eboot="", build=os.path.join(t12, "b"), portable=False,
                                     check_first=True)
        seen, asked, notes12b = [], [], []
        res = iter([(1, "FAIL U2: x\n"), (0, "OK   D1: fine\n")])

        def chk12b(*x):
            seen.append(x)
            return next(res)
        ini_before = open(os.path.join(root12, "kz2-install.ini")).read()
        answers = iter([""])     # Enter = check again
        go = fr.interactive(a12b, root12, "x.log", notes12b, ask=lambda q: (asked.append(q), next(answers))[1],
                            out=io.StringIO(), check=chk12b)
        check(go is True and len(seen) == 2 and seen[0][:2] == (os.path.abspath(d12), os.path.abspath(u12))
              and len(asked) == 1 and any("checked first" in n for n in notes12b)
              and open(os.path.join(root12, "kz2-install.ini")).read() == ini_before,
              f"12b check-first checks the given folders first, asks only after the FAIL, keeps the ini: {asked}")
        answers = iter(["c", d12, u12, ""])
        asked.clear()
        res = iter([(1, "FAIL U2: x\n"), (0, "OK\n")])
        fr.interactive(a12b, root12, "x.log", [], ask=lambda q: (asked.append(q), next(answers))[1], out=io.StringIO(),
                       check=chk12b)
        check(any("Disc dump" in q for q in asked), "12b c = change the folders brings the folder prompts back")
        o12c = io.StringIO()
        rc = fr.main(["--interactive", "--check-first", "--dump", d12, "--update", u12, "--root", root12,
                      "--log-dir", dl12, "--jobs", "1", "--log-name", "kz2-check-first.log"], steps=steps, out=o12c,
                     ask=lambda q: (_ for _ in ()).throw(AssertionError(f"asked: {q}")))
        check(rc == 0 and "OK   E1" in o12c.getvalue(), f"12b main --check-first: real check, no question, built (rc {rc})")

        # 13. the check step's archive hash: ARCHIVE-HASH lines become the check's progress, never output; the JSON
        # after them is still read for the facts; firstrun_check gets --build (its cache) and --progress
        hs = "import json\nfor d in (1, 2, 4): print(f'ARCHIVE-HASH done={d} total=4', flush=True)\n" \
             "print(json.dumps({'ok': True, 'checks': [], 'facts': {'psarc': {'sha256': 'ab'}}}))"
        c13 = fr.Ctx(root=os.path.join(tmp, "root"), build=os.path.join(tmp, "b13"), dump=os.path.join(tmp, "dump"))
        o13 = io.StringIO()
        r13 = fr.Runner(c13, [fr.Step("check", "Checking", 1, lambda c: [py(hs)], always=True)],
                        fr.Log(os.path.join(tmp, "13.log"), lambda x: x), out=o13)
        rc = r13.run()
        o = o13.getvalue()
        p13 = [(x["done"], x["total"]) for x in progress(o)]
        check(rc == 0 and "ARCHIVE-HASH" not in o and ("249", "1000") in p13 and ("999", "1000") in p13
              and p13[-1] == ("1000", "1000") and c13.facts.get("psarc", {}).get("sha256") == "ab",
              f"13 archive-hash progress on the check's permille, facts read: {p13}")
        cc = fr.cmd_check(c13)[0]
        check(cc[cc.index("--build") + 1] == c13.build and "--progress" in cc, f"13 check gets --build and --progress {cc}")
        check(cc[cc.index("--root") + 1] == c13.root, f"13 check gets --root (O1, OneDrive) {cc}")
        import firstrun_check as fc13
        got13 = []
        real_main = fc13.main
        fc13.main = lambda argv: (got13.append(argv), 0)[1]
        try:
            fr._check_files("d", "u", "")
        finally:
            fc13.main = real_main
        check(got13 and "--skip-archive-hash" in got13[0], "13 the console's quick check leaves the archive hash to the build")

        # 14. the PPU lift tables follow the tree's EBOOT version; a missing one stops the lift (no fallback)
        t14 = os.path.join(tmp, "t14")
        os.makedirs(os.path.join(t14, "kz2-setup"))
        open(os.path.join(t14, "kz2-setup", "eboot_ver.txt"), "w").write("101\n")
        tables(t14, ("ppu_overrides.txt",))
        c14 = fr.Ctx(root=t14, build=os.path.join(t14, "b"), eboot=os.path.join(t14, "EBOOT.elf"))
        try:
            fr.cmd_ppu_lift(c14)
            check(False, "14 a 1.01 tree without ppu_overrides-101.txt: the lift stops")
        except fr.StepFailed as e:
            check("ppu_overrides-101.txt" in str(e) and "reinstall" in str(e), f"14 missing 1.01 table stops the lift: {e}")
        o14 = io.StringIO()
        r14 = fr.Runner(c14, [fr.Step("ppu-lift", "Lifting", 1, fr.cmd_ppu_lift)],
                        fr.Log(os.path.join(tmp, "14.log"), lambda x: x), out=o14)
        check(r14.run() == 1 and "RESULT ok=0 step=ppu-lift" in o14.getvalue() and "ppu_overrides-101.txt" in o14.getvalue()
              and not os.path.exists(fr.marker_path(c14, 0, r14.steps[0])), "14 the runner stops with the message, no marker")
        o14 = io.StringIO()
        fr.dry_run(c14, [fr.Step("ppu-lift", "Lifting", 1, fr.cmd_ppu_lift)], "x.log", False, out=o14)
        check("STOP: the 1.01 PPU override table" in o14.getvalue(), "14 dry-run prints the stop")
        tables(t14, ("ppu_overrides-101.txt",))
        lift = fr.cmd_ppu_lift(c14)[-1]
        check(lift[lift.index("--overrides") + 1] == os.path.join(t14, "port", "kz2", "ppu_overrides-101.txt"),
              "14 the 1.01 lift uses ppu_overrides-101.txt")
        hdr = "\n".join(fr.header(c14, "x.log", False))
        check("PPU overrides port/kz2/ppu_overrides-101.txt, lift fixups none" in hdr, f"14 the log header names the tables")
        open(os.path.join(t14, "port", "kz2", "ppu_lift_fixups-101.txt"), "w").write("# none\n")
        check("lift fixups port/kz2/ppu_lift_fixups-101.txt" in "\n".join(fr.header(c14, "x.log", False)),
              "14 the header names the fixups table when there is one")
        h0 = fr.lift_inputs_hash(fr.Ctx(root=t14, build=c14.build))
        open(os.path.join(t14, "port", "kz2", "ppu_overrides-101.txt"), "a").write("0x00020000\n")
        check(fr.lift_inputs_hash(fr.Ctx(root=t14, build=c14.build)) != h0, "14 a changed 1.01 table changes the lift hash")

        # 15. future-dated port files (an install made by an installer that kept the build machine's UTC times as local
        # ones): found and refused with the plain message before configure and compile; files at the right time pass
        t15 = os.path.join(tmp, "t15")
        f15 = os.path.join(t15, "port", "kz2", "CMakeLists.txt")
        os.makedirs(os.path.dirname(f15))
        open(f15, "w").close()
        c15 = fr.Ctx(root=t15, build=os.path.join(t15, "b"))
        check(fr.future_files(c15) == (0, None), "15 a file at the right time is not future-dated")
        later = time.time() + 3 * 3600
        os.utime(f15, (later, later))
        n15, w15 = fr.future_files(c15)
        check(n15 == 1 and w15 == f15, f"15 a file 3 h in the future is found: {n15} {w15}")
        for fn in (fr.cmd_configure, fr.cmd_compile):
            try:
                fn(c15)
                check(False, f"15 {fn.__name__} refuses")
            except fr.StepFailed as e:
                check("dated in the future" in str(e) and "time zone" in str(e), f"15 {fn.__name__}: plain message")
        bfile = os.path.join(t15, "build", "x.o")
        os.makedirs(os.path.dirname(bfile))
        open(bfile, "w").close()
        os.utime(f15, None)
        os.utime(bfile, (later, later))
        check(fr.future_files(c15) == (0, None), "15 the build folder is not scanned")

        bar = io.StringIO()
        cb = fr.ConsoleBar(bar, tty=False)
        for ln in ("LOG path=/x/y.log", "some tool output",
                   "PROGRESS step=5/6 name=compile done=312 total=1204 elapsed=754 pct=60.3",
                   "RESULT ok=0 step=compile elapsed=800"):
            print(ln, file=cb)
        b = bar.getvalue()
        check("Compiling 312 / 1,204" in b and "12:34" in b and "some tool output" not in b and "issues" in b
              and "Log: /x/y.log" in b, f"12 console bar: {b!r}")

        # 16. a decrypted ISO as the dump (adapted from Project Helghast v0.1.2): the check step copies PS3_DISC.SFB and PS3_GAME
        # into <root>/game/disc, hashing the archive on the way (A1), the later steps see that folder, the bar stays
        # monotonic, a second run copies nothing, failures are plain
        from iso_fixture import build_iso
        import collections
        t16 = os.path.join(tmp, "t16")
        os.makedirs(os.path.join(t16, "root"))
        iso16 = os.path.join(t16, "game.iso")
        files16 = {"PS3_DISC.SFB": b".SFB" + b"\0" * 8, "PS3_GAME/PARAM.SFO": b"\0PSF" + b"s" * 30,
                   "PS3_GAME/ICON0.PNG": b"png", "PS3_GAME/TROPDIR/NPWR00000_00/TROPHY.TRP": b"trp",
                   "PS3_GAME/USRDIR/EBOOT.BIN": b"SCE\0" + b"e" * 20,
                   "PS3_GAME/USRDIR/data_ps3.psarc": b"PSAR" + bytes(range(256)) * 80}
        build_iso(iso16, files16, multi={"PS3_GAME/USRDIR/data_ps3.psarc": 4096})
        seen16 = os.path.join(t16, "seen.txt")
        facts16 = py("import json; print(json.dumps({'ok': True, 'facts': {'disc': {'TITLE_ID': 'BCUS98116'}}}))")
        steps16 = [fr.Step("check", "Check", 1, lambda c: [facts16], always=True, after=fr.after_check),
                   fr.Step("b", "B", 2, lambda c: [append(seen16, c.dump + "\n")])]
        out16 = io.StringIO()
        args16 = ["--dump", iso16, "--root", os.path.join(t16, "root"), "--jobs", "1", "--log-dir", os.path.join(t16, "dl")]
        known16 = os.path.join(t16, "known.json")
        psarc16 = files16["PS3_GAME/USRDIR/data_ps3.psarc"]
        with open(known16, "w") as f:
            json.dump({"sha256": hashlib.sha256(psarc16).hexdigest(), "size": len(psarc16), "discs": ["BCUS98116"],
                       "fail_on_mismatch": True}, f)
        import firstrun_check as fc16
        real_known, real_hash = fc16.PSARC_HASHES_FILE, fc16.hash_file
        reads16 = []
        fc16.hash_file = lambda p, progress=None: (reads16.append(p), real_hash(p, progress))[1]
        defaults = fc16.check_psarc_hash.__defaults__
        fc16.check_psarc_hash.__defaults__ = (known16,) + defaults[1:]
        try:
            rc = fr.main(args16, steps=steps16, out=out16)
            dest16 = os.path.join(t16, "root", "game", "disc")
            o16 = out16.getvalue()
            check(rc == 0 and "OK   A1: data_ps3.psarc matches the known disc archive" in o16 and not reads16,
                  f"16 rc {rc}, A1 from the hash taken while copying (no second read): {o16[-400:]}")
            got16 = {os.path.relpath(os.path.join(dd, n), dest16).replace(os.sep, "/"): open(os.path.join(dd, n), "rb").read()
                     for dd, _, ns in os.walk(dest16) for n in ns}
            check(got16 == files16, f"16 extracted tree equals the ISO's files, disc spelling kept: {sorted(got16)}")
            check(open(seen16).read().strip() == dest16, "16 later steps see the extracted folder as the dump")
            pj = json.load(open(os.path.join(t16, "root", "build", "paths.json")))
            check(pj["dump"] == dest16 and pj["iso"] == iso16 and pj["facts"]["psarc"]["sha256"]
                  == hashlib.sha256(psarc16).hexdigest(), "16 paths.json records the folder, the ISO and the hash")
            pr16 = progress(o16)
            pc16 = [float(x["pct"]) for x in pr16]
            check(pc16 == sorted(pc16) and pc16[-1] == 100.0, f"16 pct monotonic to 100: {pc16}")
            check(any(x["name"] == "check" and x["total"] == "1000" and x["done"] == "1000" for x in pr16),
                  "16 copy progress ends at 1000/1000")
            check(fr.steps_for(True)[0].weight > fr.STEPS[0].weight and fr.steps_for(False)[0].weight == fr.STEPS[0].weight,
                  "16 the check step weighs more for an ISO")
            out16 = io.StringIO()
            rc = fr.main(args16, steps=steps16, out=out16)
            check(rc == 0 and "0.00 GiB to copy" in out16.getvalue() and "OK   A1" in out16.getvalue() and len(reads16) <= 1
                  and not any(n.endswith(".part") for _, _, ns in os.walk(dest16) for n in ns),
                  f"16 a second run copies nothing; A1 read at most once (then cached): {len(reads16)}")
            victim = os.path.join(dest16, "PS3_GAME", "USRDIR", "data_ps3.psarc")
            with open(victim, "r+b") as f:
                f.truncate(100)
            c16 = fr.Ctx(root=os.path.join(t16, "root"), build=os.path.join(t16, "b"), iso=iso16, dump=iso16)
            said = []
            sha = fr.iso_extract(c16, say=said.append)
            check(open(victim, "rb").read() == psarc16 and c16.dump == dest16 and sha == hashlib.sha256(psarc16).hexdigest(),
                  "16 a short file is copied again (and hashed)")
            # a damaged archive inside the ISO fails A1 (fail_on_mismatch) with a plain message, RESULT ok=0
            bad16 = dict(files16, **{"PS3_GAME/USRDIR/data_ps3.psarc": b"PSAR" + bytes(255 - (k % 256) for k in range(20480))})
            shutil.rmtree(dest16)
            build_iso(iso16, bad16, multi={"PS3_GAME/USRDIR/data_ps3.psarc": 4096})
            out16 = io.StringIO()
            rc = fr.main(args16, steps=steps16, out=out16)
            check(rc == 1 and "FAIL A1" in out16.getvalue() and "failed the archive check (A1)" in out16.getvalue()
                  and "RESULT ok=0 step=check" in out16.getvalue(), f"16 damaged archive in the ISO: {out16.getvalue()[-300:]}")
        finally:
            fc16.PSARC_HASHES_FILE, fc16.hash_file = real_known, real_hash
            fc16.check_psarc_hash.__defaults__ = defaults
        build_iso(iso16, files16, multi={"PS3_GAME/USRDIR/data_ps3.psarc": 4096})
        shutil.rmtree(dest16)
        c16 = fr.Ctx(root=os.path.join(t16, "root"), build=os.path.join(t16, "b"), iso=iso16, dump=iso16)
        try:
            fr.iso_extract(c16, say=said.append, free=lambda p: collections.namedtuple("U", "free")(1000))
            check(False, "16 low disk space refused")
        except fr.StepFailed as e:
            check("Not enough free disk space" in str(e) and "GiB" in str(e)
                  and not os.path.exists(os.path.join(dest16, "PS3_GAME")), f"16 low disk space refused before writing: {e}")
        enc = bytearray(2048 * 40)
        enc[0:4] = b"\0\0\0\2"
        enc[8:24] = b"\0\0\0\0\0\0\0\x0f\0\0\0\x10\0\0\0\x1e"
        bad16 = os.path.join(t16, "enc.iso")
        open(bad16, "wb").write(bytes(enc))
        c16 = fr.Ctx(root=os.path.join(t16, "root"), build=os.path.join(t16, "b"), iso=bad16, dump=bad16)
        try:
            fr.iso_extract(c16, say=said.append)
            check(False, "16 encrypted ISO refused")
        except fr.StepFailed as e:
            check(str(e) == "this ISO is encrypted; use a decrypted dump", f"16 encrypted ISO message: {e}")
        open(bad16, "wb").write(b"not an iso" * 5000)
        try:
            fr.iso_extract(c16, say=said.append)
            check(False, "16 non-ISO refused")
        except fr.StepFailed as e:
            check("cannot read the ISO" in str(e), f"16 non-ISO message: {e}")
        # the console prompt takes a .iso file as the dump (and still re-asks a missing path)
        picked = []
        answers = iter([os.path.join(t16, "nope.iso"), iso16, u12, "", "q"])
        a16 = types.SimpleNamespace(dump="", update="", eboot="", build=os.path.join(t16, "b"), portable=False)
        go = fr.interactive(a16, root12, "x.log", [], ask=lambda q: next(answers), out=io.StringIO(),
                            check=lambda dd, uu, ee: (picked.append(dd), (1, "FAIL D1: x\n"))[1])
        check(go is False and picked == [iso16], f"16 the console accepts a decrypted .iso as the dump: {picked}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_firstrun:", "PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
