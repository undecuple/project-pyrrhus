#!/usr/bin/env python3
"""Host test for the default gameplay.ini (tools/release/launch.py ensure_gameplay_ini). Synthetic
folders in a temp directory: no game data, no Windows. Exit 0 = PASS, 1 = FAIL.

    python3 tools/release/test_gameplay_ini.py

Cases: a fresh folder gets the file; an existing file (any bytes, also empty) is left byte for byte; a folder named
gameplay.ini gives no exception and no change; every key in the file is one the runtime parses and every key the
runtime parses is in the file (both lists derived from port/kz2/kz2_gameplay.c, not typed here); the values equal the
defaults kz2_gp_defaults sets in that source; the launcher and firstrun call the writer.
"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launch as la  # noqa: E402

FAILS = []


def check(cond, what):
    if not cond:
        FAILS.append(what)


def parse_ini(text):
    sec, out = None, {}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln[0] in ";#":
            continue
        if ln.startswith("["):
            sec = ln.strip("[]").strip().lower()
        elif "=" in ln:
            k, v = ln.split("=", 1)
            out[(sec, k.strip().lower())] = v.strip()
    return out


def main():
    repo = os.path.dirname(os.path.dirname(HERE))
    src = open(os.path.join(repo, "port", "kz2", "kz2_gameplay.c"), encoding="utf-8").read()
    # keys the runtime parses: ieq(k, "name") in the [gameplay] parser and in kz2_gp_mouse_key
    mouse_fn = src[src.index("static int kz2_gp_mouse_key"):]
    mouse_fn = mouse_fn[:mouse_fn.index("\n}\n")]
    mouse_keys = set(re.findall(r'ieq\(k, "(\w+)"\)', mouse_fn))
    rest = src.replace(mouse_fn, "")
    gp_keys = set(re.findall(r'ieq\(k, "(\w+)"\)', rest))
    check(len(mouse_keys) >= 5 and len(gp_keys) >= 4, f"source key lists too short: {mouse_keys} {gp_keys}")

    with tempfile.TemporaryDirectory() as d:
        fresh = os.path.join(d, "fresh")
        check(la.ensure_gameplay_ini(fresh) == "", "fresh: reason returned")
        p = os.path.join(fresh, "gameplay.ini")
        check(os.path.isfile(p), "fresh: file written")
        raw = open(p, "rb").read()
        text = raw.decode("ascii")
        check(b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), "CRLF line ends")
        kv = parse_ini(text)
        got_g = {k for (s, k) in kv if s == "gameplay"}
        got_m = {k for (s, k) in kv if s == "mouse"}
        check(got_g == gp_keys, f"[gameplay] keys {sorted(got_g)} != runtime {sorted(gp_keys)}")
        check(got_m == mouse_keys, f"[mouse] keys {sorted(got_m)} != runtime {sorted(mouse_keys)}")
        check(not [k for (s, k) in kv if s not in ("gameplay", "mouse")], "keys outside the two sections")

        # defaults equal kz2_gp_defaults
        m = re.search(r"c->aim_assist = KZ2_AIM_(\w+); c->crouch_toggle = (\d); c->cover_toggle = (\d);", src)
        check(bool(m), "defaults line 1 not found in source")
        if m:
            check(kv[("gameplay", "aim_assist")] == m.group(1).lower(), "aim_assist default")
            check(kv[("gameplay", "crouch_toggle")] == m.group(2), "crouch_toggle default")
            check(kv[("gameplay", "cover_toggle")] == m.group(3), "cover_toggle default")
        mm = re.search(r"c->motion = KZ2_MOTION_(\w+);", src[src.index("c->aim_assist = KZ2_AIM_AUTO"):])
        check(bool(mm) and kv[("gameplay", "motion")] == mm.group(1).lower(), "motion default")
        hdr = open(os.path.join(repo, "port", "kz2", "kz2_gameplay.h"), encoding="utf-8").read()
        h = src[src.index("c->aim_assist = KZ2_AIM_AUTO"):][:400]
        for nm, val in re.findall(r"#define (KZ2_MOUSE_\w+_DEF)\s+([\d.]+)f", hdr):   # SENS_DEF, YAW_DEF
            h = h.replace(nm, val)
        ml = re.search(r"mouse_look = (\d)", h)
        ms = re.search(r"mouse_sens = ([\d.]+)f?", h)
        mz = re.search(r"mouse_zoom = ([\d.]+)f?", h)
        my = re.search(r"mouse_yaw = ([\d.]+)f?", h)
        mi = re.search(r"mouse_invert = (\d)", h)
        check(all((ml, ms, mz, my, mi)), "mouse defaults not found in source")
        if all((ml, ms, mz, my, mi)):
            for key, mt in (("mouse_look", ml), ("mouse_sensitivity", ms), ("mouse_zoom_sensitivity", mz),
                            ("mouse_yaw", my), ("mouse_invert_y", mi)):
                check(float(kv[("mouse", key)]) == float(mt.group(1)), f"{key} default {kv[('mouse', key)]} != {mt.group(1)}")

        # existing files stay byte for byte
        for name, data in (("custom", b"[gameplay]\r\ncrouch_toggle = 1\r\n"), ("empty", b""), ("odd", b"\xff\xfe\x00junk")):
            e = os.path.join(d, name)
            os.makedirs(e)
            q = os.path.join(e, "gameplay.ini")
            open(q, "wb").write(data)
            check(la.ensure_gameplay_ini(e) == "", f"{name}: reason returned")
            check(open(q, "rb").read() == data, f"{name}: changed")
        # a second call on the fresh folder changes nothing
        check(la.ensure_gameplay_ini(fresh) == "" and open(p, "rb").read() == raw, "second call changed the file")
        # a folder named gameplay.ini: no exception, untouched
        bad = os.path.join(d, "bad")
        os.makedirs(os.path.join(bad, "gameplay.ini"))
        check(la.ensure_gameplay_ini(bad) == "" and os.path.isdir(os.path.join(bad, "gameplay.ini")), "folder in the way")
        # a file where the data folder should be: a reason, no exception
        blocked = os.path.join(d, "blocked")
        open(blocked, "w").close()
        check(la.ensure_gameplay_ini(blocked) != "", "unwritable folder gives a reason")

    for f, what in (("launch.py", "launcher start"), ("firstrun.py", "first run / zip")):
        check("ensure_gameplay_ini(" in open(os.path.join(HERE, f), encoding="utf-8").read().replace("def ensure_gameplay_ini(", ""),
              f"{what} does not call ensure_gameplay_ini")

    if FAILS:
        for f in FAILS:
            print("FAIL", f)
        return 1
    print("PASS test_gameplay_ini")
    return 0


if __name__ == "__main__":
    sys.exit(main())
