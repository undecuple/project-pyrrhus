#!/usr/bin/env python3
"""Host test of the online settings files (online_ini.py, online_dialog.Controller; an earlier change, D56).
No game data, no network beyond 127.0.0.1 (Find on LAN against a responder in this test). Hosts are example.invalid,
192.0.2.x and 127.0.0.1 only.

    python3 -I tools/release/test_online_ini.py [--reader work/release/test/test_online_reader]

With --reader (test_online_reader.sh passes it) the same fixtures also go through the game's reader
(port/kz2/kz2_online.cpp) and both must reach the same decision.
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import online_ini as oi  # noqa: E402
import online_dialog as od  # noqa: E402

FAILS = []
N = [0]


def check(cond, what):
    N[0] += 1
    if not cond:
        FAILS.append(what)
        print(f"FAIL {what}")


def put(d, name, data):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


def get(d, name):
    with open(os.path.join(d, name), "rb") as f:
        return f.read().decode()


BASE = []


def fresh():
    if not BASE:
        BASE.append(tempfile.mkdtemp(prefix="kz2-online-test-"))
    t = tempfile.mkdtemp(dir=BASE[0])
    return t, os.path.join(t, "shared"), os.path.join(t, "game")


# (name, shared repsn.ini, shared community.ini, game repsn.ini, expected decision)
FIXTURES = [
    ("none", None, None, None, "off"),
    ("repsn", "[repsn]\nenabled = 1\nserver = 127.0.0.1\nname = Rico\n", None, None, "repsn"),
    ("both", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n", "[community]\nenabled = 1\n", None, "refused"),
    ("both-across", None, "[community]\nenabled = 1\n", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n", "refused"),
    ("community", None, "[community]\nenabled = 1\nactive = a\n[preset a]\naddress = 192.0.2.1\n", None, "community"),
    ("repsn-no-server", "[repsn]\nenabled = 1\n", None, None, "off"),
    ("game-wins", "[repsn]\nenabled = 0\n", None, "[repsn]\nenabled = 1\nserver = 127.0.0.1\n", "repsn"),
    ("oversize", "[repsn]\nenabled = 1\nserver = 127.0.0.1\n" + "\n" * oi.MAX_FILE, None, None, "off"),
    ("long-line", "[repsn]\nenabled = 1\nserver = 127.0.0.1" + " " * 500 + "\n", None, None, "off"),
    ("injection", "[repsn]\nenabled = 1\nserver = 127.0.0.1;calc\nserver = $(x)\n", None, None, "off"),
    ("mixed", "[repsn]\nenabled = 0\n[community]\nenabled = 1\n", "[community]\nserver = 127.0.0.1\n[repsn]\nenabled = 1\n",
     None, "off"),
    ("bom-crlf", "﻿[repsn]\r\nenabled = 1\r\nserver = example.invalid\r\n", None, None, "repsn"),
    ("bad-enabled", "[repsn]\nenabled = yes\nserver = 127.0.0.1\n", "[community]\nenabled = true\n", None, "off"),
]
READER_STATE = {"0": "off", "1": "repsn", "2": "community", "3": "refused", "4": "env"}


def lay(f):
    t, sh, gm = fresh()
    os.makedirs(sh)
    os.makedirs(gm)
    for d, name, text in ((sh, oi.REPSN, f[1]), (sh, oi.COMMUNITY, f[2]), (gm, oi.REPSN, f[3])):
        if text is not None:
            put(d, name, text.encode("utf-8"))
    return sh, gm


def test_decide(reader):
    for f in FIXTURES:
        sh, gm = lay(f)
        got = oi.decide(sh, gm)["method"]
        check(got == f[4], f"decide {f[0]}: {got} != {f[4]}")
        if reader:
            r = subprocess.run([reader, "--decide", sh, gm], capture_output=True, text=True, timeout=30)
            st = READER_STATE.get(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "", "?")
            check(st == f[4], f"game reader {f[0]}: {st} != {f[4]}")
    sh, gm = lay(FIXTURES[1])
    check(oi.decide(sh, gm, {"PSNR_SERVER": "127.0.0.2"})["method"] == "env", "decide: environment wins")
    check(oi.decide(sh, gm)["server"] == "127.0.0.1:36100", "decide: default port")
    check(oi.decide(sh, gm, {"KZ3_ONLINE": "0"})["method"] == "repsn", "decide: KZ3_ONLINE=0 is off, files apply")
    check(oi.decide(sh, gm, {"PS3_NET_ONLINE": "1"})["method"] == "repsn", "decide: PS3_NET_ONLINE is not the switch")
    check(oi.decide(sh, gm, {"KZ3_ONLINE": "1"})["method"] == "env", "decide: KZ3_ONLINE=1 wins")


def test_parse():
    st, rej = oi.parse(b"[repsn]\nenabled = 1\nserver = 127.0.0.1:0\nname = 1abc\nrelay = 1\n", oi.REPSN)
    check(st["enabled"] and not st["server"] and not st["name"] and len(rej) == 3, "parse: bad port, name, unknown key")
    st, rej = oi.parse(b"[repsn]\np2p_port = 3659\n", oi.REPSN, game=False)
    check(not st["p2p_port"] and rej, "parse: p2p_port only in the game's own file")
    st, rej = oi.parse(b"[repsn]\np2p_port = 3659\ncomm_id = NPWR00153_00\n", oi.REPSN, game=True)
    check(st["p2p_port"] == "3659" and st["comm_id"] == "NPWR00153_00" and not rej, "parse: game keys")
    st, rej = oi.parse(b"[community]\n[preset ../x]\naddress = 192.0.2.1\n[preset ok]\naddress = 192.0.2.2:7\n", oi.COMMUNITY)
    check(list(st["presets"]) == ["ok"] and st["presets"]["ok"]["address"] == "192.0.2.2:7", "parse: bad label dropped")
    st, rej = oi.parse(b"[repsn]\nserver = 127.0.0.1\x00x\n", oi.REPSN)
    check(not st["server"] and rej[0][1] == "NUL byte", "parse: NUL byte")
    st, rej = oi.parse(b"[repsn]\nname = \xc3\xa9abc\n", oi.REPSN)
    check(not st["name"], "parse: non-ASCII name rejected")
    for bad in ("", "a" * 254, "-x", ".x", "x:", "x:65536", "x:1:2", "[::1]", "a b", "x/y", "http://x"):
        check(not oi.valid_hostport(bad), f"valid_hostport refuses {bad!r}")
    for good in ("x", "127.0.0.1:36100", "example.invalid", "a_b-c.d:1"):
        check(oi.valid_hostport(good), f"valid_hostport takes {good!r}")
    t, sh, gm = fresh()
    put(sh, oi.REPSN, b"x" * (oi.MAX_FILE + 1))
    try:
        oi.load(os.path.join(sh, oi.REPSN), oi.REPSN)
        check(False, "load: oversize raises")
    except oi.OnlineError as e:
        check("64 KB" in str(e), "load: oversize raises")


def test_write():
    t, sh, gm = fresh()
    oi.save_method(sh, "off")
    check(not os.path.exists(sh), "Off with no files makes no folder")
    oi.save_method(sh, "repsn", "127.0.0.1", "Rico")
    d = oi.decide(sh, "")
    check(d["method"] == "repsn" and d["name"] == "Rico", "save re-psn")
    check("Features that exist only in this port" in get(sh, oi.COMMUNITY), "community.ini made with the disclaimer")
    check("[preset" not in get(sh, oi.COMMUNITY), "no preset shipped or made")
    oi.save_method(sh, "community")
    st_r, _ = oi.load(os.path.join(sh, oi.REPSN), oi.REPSN)
    st_c, _ = oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)
    check(st_r["enabled"] is False and st_c["enabled"] is True and st_r["server"] == "127.0.0.1:36100",
          "switching to community turns re-psn off, keeps its server")
    oi.save_method(sh, "off")
    check(oi.decide(sh, "")["method"] == "off", "Off turns both off")
    for m in ("repsn", "community", "off", "repsn"):
        oi.save_method(sh, m)
        a = oi.load(os.path.join(sh, oi.REPSN), oi.REPSN)[0]["enabled"]
        b = oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)[0]["enabled"]
        check(not (a and b), f"never both enabled after saving {m}")
    # comments, unknown keys and spacing stay; a duplicate key that would win is removed
    put(sh, oi.REPSN, "; mine\n[repsn]\n  enabled=1\nserver = 192.0.2.1\nfuture_key = x\nenabled = 1\n[other]\nk = v\n")
    oi.save_method(sh, "off")
    txt = get(sh, oi.REPSN)
    check("; mine" in txt and "future_key = x" in txt and "[other]" in txt and "k = v" in txt, "writer keeps other lines")
    check(txt.count("enabled") == 1 and "enabled = 0" in txt, "writer removes a later duplicate")
    # an unusable file is reported, never overwritten
    big = "[repsn]\nenabled = 1\n" + "; pad\n" * 12000
    put(sh, oi.REPSN, big)
    try:
        oi.save_method(sh, "community")
        check(False, "oversize repsn.ini blocks the save")
    except oi.OnlineError:
        check(get(sh, oi.REPSN) == big, "oversize repsn.ini blocks the save and stays as it was")
    check(oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)[0]["enabled"] is not True,
          "a blocked save switches nothing on")
    # input checks
    t, sh, gm = fresh()
    for args, what in (((sh, "repsn", "127.0.0.1;calc", ""), "bad server"), ((sh, "repsn", "127.0.0.1", "1x"), "bad name"),
                       ((sh, "repsn", "", ""), "re-psn without server"), ((sh, "both"), "unknown method")):
        try:
            oi.save_method(*args)
            check(False, f"save_method refuses {what}")
        except ValueError:
            check(not os.path.exists(os.path.join(sh, oi.REPSN)), f"save_method refuses {what}, writes nothing")
    # newline injection through a value cannot add a key
    try:
        oi.save_preset(sh, "a", "192.0.2.1\nenabled = 1", "")
        check(False, "address with a newline refused")
    except ValueError:
        check(True, "address with a newline refused")
    # CRLF file stays CRLF
    put(sh, oi.REPSN, "[repsn]\r\nenabled = 0\r\nserver = 127.0.0.1\r\n")
    oi.save_method(sh, "repsn")
    check(get(sh, oi.REPSN).count("\r\n") == 3, "CRLF kept")


def test_presets():
    t, sh, gm = fresh()
    oi.save_preset(sh, "home", "192.0.2.10", "Rico")
    oi.save_preset(sh, "lan", "192.0.2.11:10075", "")
    oi.pick_preset(sh, "home")
    st, rej = oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)
    check(set(st["presets"]) == {"home", "lan"} and st["active"] == "home" and not rej, "presets added and picked")
    oi.save_preset(sh, "house", "192.0.2.12", "Rico", old_label="home")
    st, _ = oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)
    check(set(st["presets"]) == {"house", "lan"} and st["active"] == "house" and
          st["presets"]["house"]["address"] == "192.0.2.12:36100", "rename keeps it in use")
    before = get(sh, oi.COMMUNITY)
    try:
        oi.save_preset(sh, "LAN", "192.0.2.99", "", old_label="house")
        check(False, "rename onto an existing preset refused")
    except ValueError as e:
        check("exists" in str(e) and get(sh, oi.COMMUNITY) == before, "rename onto an existing preset refused, file unchanged")
    c = od.Controller(sh, "")
    check(not c.preset_save("lan", "192.0.2.99", "", old_label="house") and "exists" in c.status,
          "controller: rename onto an existing preset says so")
    oi.delete_preset(sh, "house")
    st, _ = oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)
    check(set(st["presets"]) == {"lan"} and not st["active"], "delete clears the active one")
    txt = get(sh, oi.COMMUNITY)
    check(txt.startswith("; Community server settings") and "\n\n\n" not in txt, "header stays, no blank runs")


def test_repeated_sections():
    """Review fix 5: repeated [repsn] / [preset X] blocks are merged by the reader; the writer collapses the touched
    section first, and what it writes reads back as chosen."""
    t, sh, gm = fresh()
    put(sh, oi.REPSN, "[repsn]\nenabled = 0\nserver = 192.0.2.1\n; keep\n[repsn]\nenabled = 1\nname = Later\n")
    put(sh, oi.COMMUNITY, "[community]\nenabled = 1\n")
    oi.save_method(sh, "community")
    txt = get(sh, oi.REPSN)
    st = oi.load(os.path.join(sh, oi.REPSN), oi.REPSN)[0]
    check(txt.count("[repsn]") == 1 and "; keep" in txt and st["enabled"] is False and st["name"] == "Later"
          and st["server"] == "192.0.2.1:36100", "repeated [repsn]: collapsed, the second block's enabled = 1 is gone")
    check(oi.decide(sh, "")["method"] == "community", "repeated [repsn]: the game's decision is the choice")
    put(sh, oi.COMMUNITY, "[community]\nactive = x\n[preset x]\naddress = 192.0.2.1\n[community]\nenabled = 0\n"
                          "[preset x]\naddress = 192.0.2.2\nname = Second\n")
    oi.save_preset(sh, "x", "192.0.2.3", "")
    st = oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)[0]
    check(get(sh, oi.COMMUNITY).count("[preset x]") == 1 and st["presets"]["x"]["address"] == "192.0.2.3:36100"
          and st["presets"]["x"]["name"] == "Second", "repeated [preset x]: collapsed, the new address reads back")
    oi.pick_preset(sh, "x")
    check(oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)[0]["active"] == "x", "pick over repeated [community]")
    put(sh, oi.COMMUNITY, "[preset x]\naddress = 192.0.2.1\n[community]\nactive = x\n[preset x]\nname = Ab_c\n")
    oi.delete_preset(sh, "x")
    st = oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)[0]
    check(not st["presets"] and not st["active"], "delete_preset removes every repeated block")
    put(sh, oi.COMMUNITY, "[preset Home]\naddress = 192.0.2.1\n")
    oi.save_preset(sh, "home", "192.0.2.4", "")
    st = oi.load(os.path.join(sh, oi.COMMUNITY), oi.COMMUNITY)[0]
    check(list(st["presets"]) == ["home"], "a preset edited under another case takes the chosen label")
    # the read-back check refuses a change that would not read back (a case the writer cannot follow), writes nothing
    doc = oi.Doc(os.path.join(sh, oi.REPSN), oi.REPSN)
    doc.lines.append("[repsn]")
    doc.lines.append("enabled = 1")
    before = get(sh, oi.REPSN)
    try:
        doc.save(lambda st: st["enabled"] is False)
        check(False, "read-back check refuses")
    except oi.OnlineError:
        check(get(sh, oi.REPSN) == before, "read-back check refuses and writes nothing")


def test_controller():
    t, sh, gm = fresh()
    put(sh, oi.REPSN, "[repsn]\nenabled = 1\nserver = 127.0.0.1\n")
    put(sh, oi.COMMUNITY, "[community]\nenabled = 1\n")
    c = od.Controller(sh, gm)
    check(c.method == "both" and "refuses" in c.status, "controller shows both-enabled and picks nothing")
    check(c.save("community", "", ""), "controller: save community")
    check("Add a preset" in c.status and c.method == "community", "controller: community with no preset says so")
    check(not c.preset_save("bad label", "192.0.2.1", ""), "controller: bad label refused")
    check(c.preset_save("one", "192.0.2.1", "Sev") and not c.preset_save("ONE", "192.0.2.2", ""),
          "controller: a duplicate label (any case) is refused")
    check(c.preset_use("one") and c.active == "one" and "(in use)" in c.label_text("one"), "controller: use")
    check(not c.preset_delete("nope") and c.preset_delete("one") and not c.presets, "controller: delete")
    check(c.save("off", "", "") and oi.decide(sh, gm)["method"] == "off", "controller: off")
    check(not c.save("repsn", "example.invalid:0", "") and "Server" in c.status, "controller: bad server message")
    c2 = od.Controller(sh, gm, find=lambda: [{"address": "127.0.0.1:36100", "name": "x", "version": "0.5.0",
                                              "relay": False, "players": 0}])
    c2.find_lan()
    check(c2.lan_pick(0) == "127.0.0.1:36100" and "1 server" in c2.status and c2.lan_pick(5) is None, "controller: LAN pick")
    c3 = od.Controller(sh, gm, find=lambda: [])
    c3.find_lan()
    check("compatible server" in c3.status and "-discover" not in c3.status and "re-psn 0" not in c3.status,
          "controller: nothing found says how, naming no server project or flag")
    import launch
    src_dialog = open(os.path.join(HERE, "online_dialog.py"), encoding="utf-8").read()
    src_launch = open(os.path.join(HERE, "launch.py"), encoding="utf-8").read()
    check("D56" not in src_launch and "D56" not in oi.REFUSED_TEXT and "-discover" not in src_dialog
          and "D56" not in od.REPSN_NOTE + od.COMMUNITY_NOTE + od.SAVED + "".join(od.METHOD_LABELS.values())
          and launch.TITLE, "player-facing text names no decision number, server project flag")
    put(sh, oi.REPSN, "x" * (oi.MAX_FILE + 10))
    c4 = od.Controller(sh, gm)
    check(c4.errors and "not overwritten" in c4.status and not c4.save("off", "", ""), "controller: unusable file")
    check(get(sh, oi.REPSN) == "x" * (oi.MAX_FILE + 10), "controller: unusable file untouched")
    # review fix 3: the game folder's repsn.ini, read last by the game, is shown when it overrides the window
    t5, sh5, gm5 = fresh()
    put(gm5, oi.REPSN, "[repsn]\nenabled = 1\nserver = 127.0.0.1\n")
    c5 = od.Controller(sh5, gm5)
    check(c5.method == "off" and "reads it last" in c5.status and "re-psn" in c5.status,
          "controller: a game-folder repsn.ini that turns re-psn on is shown")
    check(c5.save("community", "", "") and "reads it last" in c5.status and "no method" in c5.status
          and oi.decide(sh5, gm5)["method"] == "refused", "controller: after Save the window says what the game will do")
    put(gm5, oi.REPSN, "[repsn]\np2p_port = 3659\n")
    check(not od.Controller(sh5, gm5).override, "controller: game-only keys are no override")
    for text in (od.REPSN_NOTE, od.COMMUNITY_NOTE, oi.REFUSED_TEXT):
        check("offline" in text or "re-psn" in text, "notes say what each mode does")


def test_lan():
    nonce = b"\x01\x02\x03\x04"
    req = oi.discover_request(nonce)
    check(len(req) == 64 and req[:5] == b"PSNR\x04" and req[5:9] == nonce and req[9:] == bytes(55), "DISCOVER bytes")

    def reply(n=nonce, port=36100, name=b"lan box", ver=b"0.5.0", magic=b"PSNR", typ=0x84, extra=b""):
        b = magic + bytes([typ]) + n + port.to_bytes(2, "big") + (36100).to_bytes(2, "big") + b"\x01" + (3).to_bytes(2, "big")
        return b + name.ljust(24, b"\0")[:24] + ver.ljust(12, b"\0")[:12] + extra
    r = oi.parse_reply(reply(), nonce, "192.0.2.5")
    check(r == {"address": "192.0.2.5:36100", "name": "lan box", "version": "0.5.0", "relay": True, "players": 3},
          "reply parsed")
    check(oi.parse_reply(reply()[:51], nonce, "192.0.2.5") is None, "short reply dropped")
    check(oi.parse_reply(reply(extra=b"x"), nonce, "192.0.2.5") is None, "long reply dropped")
    check(oi.parse_reply(reply(magic=b"PSNX"), nonce, "192.0.2.5") is None, "bad magic dropped")
    check(oi.parse_reply(reply(typ=0x04), nonce, "192.0.2.5") is None, "bad type dropped")
    check(oi.parse_reply(reply(n=b"\0\0\0\0"), nonce, "192.0.2.5") is None, "wrong nonce dropped")
    check(oi.parse_reply(reply(port=0), nonce, "192.0.2.5") is None, "port 0 dropped")
    check(oi.parse_reply(reply(name=b"a\x07b\xffc\0junk"), nonce, "192.0.2.5")["name"] == "a?b?c", "text made printable")

    # loopback: a responder in this test answers the DISCOVER (good, duplicate, wrong nonce, junk)
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(5)
    port = srv.getsockname()[1]

    def answer():
        try:
            pkt, addr = srv.recvfrom(256)
        except OSError:
            return
        if len(pkt) == 64 and pkt[:5] == b"PSNR\x04":
            n = pkt[5:9]
            for p in (reply(n=n), reply(n=n), reply(n=b"\xff\xff\xff\xff", port=1), b"junk"):
                srv.sendto(p, addr)
    th = threading.Thread(target=answer, daemon=True)
    th.start()
    found = oi.find_on_lan(port, timeout=0.8, targets=[("127.0.0.1", port)])
    th.join(2)
    srv.close()
    check(len(found) == 1 and found[0]["address"] == "127.0.0.1:36100", f"loopback Find on LAN: {found}")


def test_walk_shape():
    """An earlier change: the Proton walk runs the window and its driver in one process and has a time limit."""
    sys.path.insert(0, os.path.join(HERE, "wizard_test"))
    import online_drive
    check(callable(online_drive.run_both) and callable(online_drive.main), "online_drive: run_both + main")
    sh = open(os.path.join(HERE, "wizard_test.sh"), encoding="utf-8").read()
    block = sh[sh.index("\nonline)\n"):]
    block = block[:block.index("\n  ;;\n")]
    check(block.count('proton run "$PY"') == 1 and "KZ2_WT_ONLINE_MAX" in block and "wait " not in block,
          "wizard_test.sh online: one proton run of Python, a deadline, no unbounded wait")
    # Check 6 passes only on the Find result's own text (an earlier change review fix 4).
    fr = online_drive.find_result
    for good in ("0 server(s) found. Pick the one you know.", "2 server(s) found. Pick the one you know.",
                 "No server found on this network. The host must run a compatible server with LAN discovery "
                 "turned on, on the same network.", "Find on LAN failed (Network is unreachable)."):
        check(fr(good), f"find_result accepts {good[:30]!r}")
    for bad in ("Looking for a compatible server on this network...", "Looking 2 server(s) found. ", "", None,
                "Server address is not valid: kept the file as it was.", "Saved. failed", "server found",
                "Find on LAN failed"):
        check(not fr(bad), f"find_result refuses {str(bad)[:30]!r}")
    # The real Controller texts are accepted.
    src = open(os.path.join(HERE, "online_dialog.py"), encoding="utf-8").read()
    check('server(s) found. Pick' in src and '"No server found on this network.' in src
          and 'f"Find on LAN failed (' in src, "find_result's patterns match online_dialog's status texts")


def main(argv):
    reader = None
    if "--reader" in argv:
        reader = argv[argv.index("--reader") + 1]
    try:
        test_parse()
        test_decide(reader)
        test_write()
        test_presets()
        test_repeated_sections()
        test_controller()
        test_lan()
        test_walk_shape()
    finally:
        if BASE:
            shutil.rmtree(BASE[0], ignore_errors=True)
    print(f"{N[0] - len(FAILS)} of {N[0]} checks passed" + (" (with the game reader)" if reader else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
