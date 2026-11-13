"""Drives the Online settings window (online_dialog.py) under Proton (wizard_test.sh online; an earlier change,
fixed in an earlier change). Test only, never shipped. Windows Python, standard library.

    python.exe online_drive.py DIR        DIR holds online_ini.py, online_dialog.py, shared\\ and out\\

One process: the window runs on the main thread (online_dialog.run) and the driver on a second thread (main(DIR)).
An earlier change started the window and the driver as two `proton run` processes in one prefix; the driver never wrote its
first line in 600 s while the window process ran (its imports are in __pycache__), and the shell then waited on the
driver for ever. One process needs no second launch through Proton's steam.exe and wineserver start. faulthandler
writes every thread's stack to out\\hang.txt if the run is still going after 150 s.

Each step sends the window the messages a player's clicks and typing make (WM_SETTEXT into the edits, BM_CLICK on
the buttons and radios, LBN_SELCHANGE for a list pick), then writes out\\step-N.txt and waits for out\\shot-N.txt
(the shell's screenshot). The files are checked after each save; "RESULT ok=1|0" and one "CHECK" line per check go
to out\\drive.txt.
"""
import ctypes
import faulthandler
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes as w



def find_result(s):
    """Check 6: True only for a line that the Find on LAN result alone writes (online_dialog.Controller.find_lan):
    "<n> server(s) found.", "No server found ..." or "Find on LAN failed (...)". The in-progress "Looking ..." line,
    an empty line and the previous step's text (which names the server field) are not a result."""
    import re
    s = s or ""
    if s.startswith("Looking"):
        return False
    return bool(re.match(r"\d+ server\(s\) found\. ", s) or s.startswith("No server found on this network.")
                or re.match(r"Find on LAN failed \(.*\)\.$", s))


def main(D):
    sys.path.insert(0, D)
    import online_ini as oi  # noqa: E402

    SHARED, OUT = os.path.join(D, "shared"), os.path.join(D, "out")
    u32 = ctypes.windll.user32
    u32.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
    u32.FindWindowW.restype = w.HWND
    u32.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
    u32.GetDlgItem.restype = w.HWND
    u32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    u32.SendMessageW.restype = ctypes.c_ssize_t
    u32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    u32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    (R_OFF, R_REPSN, R_COM, E_SERVER, B_FIND, E_NAME, L_LAN, L_PRESETS, E_PLABEL, E_PADDR, E_PNAME, B_ADD, B_UPDATE,
     B_DELETE, B_USE, S_STATUS, B_SAVE, B_CLOSE) = range(101, 119)
    WM_SETTEXT, WM_COMMAND, BM_CLICK, LB_SETCURSEL = 0xC, 0x111, 0xF5, 0x186
    lines, ok = [], [True]


    def log(s):
        lines.append(s)
        with open(os.path.join(OUT, "drive.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")


    def check(c, what):
        ok[0] = ok[0] and bool(c)
        log(f"CHECK {'ok' if c else 'FAIL'} {what}")


    h = None
    for _ in range(300):
        h = u32.FindWindowW("KZ2OnlineSettings", None)
        if h:
            break
        time.sleep(0.1)
    if not h:
        log("RESULT ok=0 (no window)")
        return
    time.sleep(1.0)


    def item(i):
        return u32.GetDlgItem(h, i)


    def put(i, t):
        buf = ctypes.create_unicode_buffer(t)
        u32.SendMessageW(item(i), WM_SETTEXT, 0, ctypes.addressof(buf))


    def click(i):
        u32.SendMessageW(item(i), BM_CLICK, 0, 0)
        time.sleep(0.3)


    def pick(i, n):
        u32.SendMessageW(item(i), LB_SETCURSEL, n, 0)
        u32.SendMessageW(h, WM_COMMAND, (1 << 16) | i, item(i) or 0)    # LBN_SELCHANGE, as a click sends it
        time.sleep(0.3)


    def status():
        b = ctypes.create_unicode_buffer(400)
        u32.GetWindowTextW(item(S_STATUS), b, 400)
        return b.value


    def step(n, what):
        log(f"step {n}: {what}; status: {status()}")
        with open(os.path.join(OUT, f"step-{n}.txt"), "w") as f:
            f.write(what + "\n")
        for _ in range(200):
            if os.path.exists(os.path.join(OUT, f"shot-{n}.txt")):
                return
            time.sleep(0.1)


    def enabled():
        a = oi.load(os.path.join(SHARED, oi.REPSN), oi.REPSN)[0]
        b = oi.load(os.path.join(SHARED, oi.COMMUNITY), oi.COMMUNITY)[0]
        return a, b


    check("refuses" in status(), "1 both enabled by hand: the window says the game refuses, no method chosen")
    step(1, "opened over a both-enabled pair")

    put(E_PLABEL, "home")
    put(E_PADDR, "192.0.2.10")
    put(E_PNAME, "Rico")
    click(B_ADD)
    a, b = enabled()
    check("home" in b["presets"] and b["presets"]["home"]["address"] == "192.0.2.10:36100", "2 Add wrote the preset")
    step(2, "preset added")

    pick(L_PRESETS, 0)
    click(B_USE)
    check(enabled()[1]["active"] == "home", "3 Use made it the active preset")
    click(R_COM)
    click(B_SAVE)
    a, b = enabled()
    check(b["enabled"] is True and a["enabled"] is False, "3 Community saved: community on, re-psn off")
    check(oi.decide(SHARED, "")["method"] == "community", "3 the game's decision: community (offline in this build)")
    step(3, "community chosen and saved")

    click(R_REPSN)
    put(E_SERVER, "127.0.0.1")
    put(E_NAME, "Rico")
    click(B_SAVE)
    a, b = enabled()
    check(a["enabled"] is True and b["enabled"] is False and a["server"] == "127.0.0.1:36100" and a["name"] == "Rico",
          "4 re-psn saved: re-psn on with server and name, community off")
    step(4, "re-psn chosen and saved")

    put(E_SERVER, "127.0.0.1;calc")
    click(B_SAVE)
    check("Server" in status() and enabled()[0]["server"] == "127.0.0.1:36100", "5 a bad server is refused, the file kept")
    step(5, "bad server refused")

    click(B_FIND)
    for _ in range(60):
        s = status()
        if s and not s.startswith("Looking"):
            break
        time.sleep(0.1)
    check(find_result(status()), "6 Find on LAN came back with its own result line")
    step(6, "Find on LAN (no network in the sandbox)")

    pick(L_PRESETS, 0)
    click(B_DELETE)
    check(not enabled()[1]["presets"] and not enabled()[1]["active"], "7 Delete removed the preset and its use")
    click(R_OFF)
    click(B_SAVE)
    check(oi.decide(SHARED, "")["method"] == "off", "7 Off saved: both off")
    step(7, "preset deleted, Off saved")
    # RESULT first: Close ends the process (the window's thread returns from run()), and this daemon thread with it
    # (an earlier change's first walk: every check ok, no RESULT line)
    log(f"RESULT ok={1 if ok[0] else 0}")
    u32.PostMessageW(h, WM_COMMAND, B_CLOSE, 0)


def run_both(D):
    sys.path.insert(0, D)
    out = os.path.join(D, "out")
    os.makedirs(out, exist_ok=True)
    hang = open(os.path.join(out, "hang.txt"), "w")
    faulthandler.dump_traceback_later(150, exit=False, file=hang)
    with open(os.path.join(out, "drive.txt"), "w") as f:
        f.write("started\n")

    def driver():
        try:
            main(D)
        except Exception:      # said in drive.txt, never a silent thread end
            with open(os.path.join(out, "drive.txt"), "a") as f:
                f.write("RESULT ok=0 (driver error)\n" + traceback.format_exc())
    threading.Thread(target=driver, daemon=True).start()
    import online_dialog
    rc = online_dialog.run(os.path.join(D, "shared"), "", {})
    faulthandler.cancel_dump_traceback_later()
    return rc


if __name__ == "__main__":
    sys.exit(run_both(sys.argv[1]))
