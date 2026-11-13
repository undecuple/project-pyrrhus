#!/usr/bin/env python3
"""The launcher's Online settings window (launch.py --online; Start menu "Online settings"). ENHANCEMENT (decisions D56).

The player picks how the game goes online, one method at a time: Off, re-psn (server and online name, Find on LAN)
or a community server (named presets the player adds, changes, deletes and picks; none is shipped). The window writes
the files through online_ini.py; the game reads them at its next start (port/kz2/kz2_online.cpp).

Controller holds every rule and is what test_online_ini.py drives; the Win32 part (run_window, ctypes, no extra
packages: the payload's embeddable Python has no tkinter) only shows the controller's state and passes clicks on.
Outside Windows, run() prints the current settings and the game's decision (developer runs).
"""
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import online_ini as oi  # noqa: E402

TITLE = "Project Pyrrhus - Online settings"
REPSN_NOTE = ("Killzone 2's own online lobby does not run through re-psn yet. This saves the choice; online play "
              "needs a later update.")
COMMUNITY_NOTE = ("Features that exist only in this port do not work on a community server. This build keeps the "
                  "game offline in this mode until it can connect to a compatible server.")
SAVED = "Saved. It applies the next time the game starts."
METHOD_LABELS = {"off": "Off", "repsn": "re-psn", "community": "Community server (offline in this build)",
                 "refused": "no method (both enabled: online play refused)", "env": "the environment's settings"}


class Controller:
    """The window's state and rules, with no window."""

    def __init__(self, shared, game_dir="", find=oi.find_on_lan):
        self.shared, self.game_dir, self.find = shared, game_dir, find
        self.status = ""
        self.lan = []
        self.reload()

    def reload(self):
        self.errors = []
        rep = com = None
        try:
            rep, _ = oi.load(os.path.join(self.shared, oi.REPSN), oi.REPSN)
        except oi.OnlineError as e:
            self.errors.append(str(e))
        try:
            com, _ = oi.load(os.path.join(self.shared, oi.COMMUNITY), oi.COMMUNITY)
        except oi.OnlineError as e:
            self.errors.append(str(e))
        rep = rep or {"enabled": None, "server": "", "name": ""}
        com = com or {"enabled": None, "active": None, "presets": {}}
        self.server, self.name = rep["server"], rep["name"]
        self.presets = {k: dict(v) for k, v in com["presets"].items()}
        self.active = com["active"] or ""
        if rep["enabled"] and com["enabled"]:
            self.method = "both"         # a hand edit: the window shows no choice until the player picks one
            self.status = "Both methods are enabled, so the game refuses online play. Choose one and save."
        else:
            self.method = "repsn" if rep["enabled"] else ("community" if com["enabled"] else "off")
        self.override = self.override_note()
        if self.override and self.method != "both":
            self.status = self.override
        if self.errors:
            self.status = " ".join(self.errors) + " Fix or remove the file; it is not overwritten."
        return self

    def override_note(self):
        """The game folder's repsn.ini is read after the shared files (kz2_online.cpp, online_ini.decide): when it
        sets a method key, say what the game will really do. "" when it sets none."""
        if not self.game_dir:
            return ""
        path = os.path.join(self.game_dir, oi.REPSN)
        try:
            g, _ = oi.load(path, oi.REPSN, game=True)
        except oi.OnlineError as e:
            return f"{e}; the game ignores that file."
        keys = [k for k in ("enabled", "server", "name") if g[k] not in (None, "")]
        if not keys:
            return ""
        d = oi.decide(self.shared, self.game_dir)
        return (f"Note: {path} also sets {', '.join(keys)} and the game reads it last: at the next start it uses "
                f"{METHOD_LABELS.get(d['method'], d['method'])}. Remove those lines there to let this window decide.")

    def labels(self):
        return sorted(self.presets, key=str.lower)

    def label_text(self, label):
        return label + ("  (in use)" if label.lower() == self.active.lower() else "")

    def _do(self, fn, *a, ok=SAVED):
        try:
            fn(*a)
        except (ValueError, oi.OnlineError) as e:
            self.status = str(e)
            return False
        st = self.status
        self.reload()
        self.status = ok if not self.errors else st
        return True

    def save(self, method, server, name):
        """The Save button: method plus the re-psn fields."""
        if method not in oi.METHODS:
            self.status = "Choose Off, re-psn or Community server."
            return False
        server, name = server.strip(), name.strip()
        ok = SAVED
        if method == "community":
            if not self.presets:
                ok = SAVED + " Add a preset for your community server."
            elif not self.active or self.active.lower() not in (k.lower() for k in self.presets):
                ok = SAVED + " Pick the preset to use."
        done = self._do(oi.save_method, self.shared, method, server, name, ok=ok)
        if done and self.override:
            self.status = SAVED.split(".")[0] + ". " + self.override
        return done

    def preset_save(self, label, address, name, old_label=None):
        label, address, name = label.strip(), address.strip(), name.strip()
        if old_label is None and any(k.lower() == label.lower() for k in self.presets):
            self.status = f"A preset named {oi.shown(label)} exists; select it and use Update."
            return False
        return self._do(oi.save_preset, self.shared, label, address, name, old_label, ok="Preset saved.")

    def preset_delete(self, label):
        if label not in self.presets:
            self.status = "Select a preset first."
            return False
        return self._do(oi.delete_preset, self.shared, label, ok="Preset deleted.")

    def preset_use(self, label):
        if label not in self.presets:
            self.status = "Select a preset first."
            return False
        return self._do(oi.pick_preset, self.shared, label, ok=f"Preset {label} is the one in use.")

    def find_lan(self):
        """Runs the search (blocking, about 1.2 s; the window calls it on a worker thread). -> results."""
        try:
            self.lan = self.find()
        except OSError as e:
            self.lan = []
            self.status = f"Find on LAN failed ({e.strerror or e})."
            return self.lan
        self.status = (f"{len(self.lan)} server(s) found. Pick the one you know." if self.lan else
                       "No server found on this network. The host must run a compatible server with LAN discovery "
                       "turned on, on the same network.")
        return self.lan

    def lan_text(self, r):
        return (f"{r['name'] or '(no name)'}  {r['address']}  {r['players']} player(s)"
                f"{'  relay' if r['relay'] else ''}  {r['version']}")

    def lan_pick(self, i):
        if 0 <= i < len(self.lan):
            self.server = self.lan[i]["address"]
            return self.server
        return None


# ------------------------------------------------------------------------------------------------------ Win32
def run_window(ctl):     # pragma: no cover  (Windows only; the rules are in Controller)
    import ctypes
    from ctypes import wintypes as w
    u32, g32, k32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                    ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                    ("lpszClassName", w.LPCWSTR)]

    u32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    u32.DefWindowProcW.restype = LRESULT
    u32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
    u32.CreateWindowExW.restype = w.HWND
    u32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    u32.SendMessageW.restype = LRESULT
    u32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    u32.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
    u32.GetDlgItem.restype = w.HWND
    u32.IsDialogMessageW.argtypes = [w.HWND, ctypes.POINTER(w.MSG)]
    u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    u32.LoadCursorW.argtypes = [w.HINSTANCE, w.LPVOID]
    u32.LoadCursorW.restype = w.HANDLE
    for fn, args in (("SetWindowTextW", [w.HWND, w.LPCWSTR]), ("GetWindowTextW", [w.HWND, w.LPWSTR, ctypes.c_int]),
                     ("GetWindowTextLengthW", [w.HWND]), ("EnableWindow", [w.HWND, w.BOOL]),
                     ("DestroyWindow", [w.HWND]), ("TranslateMessage", [ctypes.POINTER(w.MSG)]),
                     ("DispatchMessageW", [ctypes.POINTER(w.MSG)]),
                     ("GetMessageW", [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT])):
        getattr(u32, fn).argtypes = args
    g32.GetStockObject.restype = w.HANDLE
    k32.GetModuleHandleW.restype = w.HMODULE

    WS_CHILD, WS_VISIBLE, WS_TABSTOP, WS_GROUP, WS_BORDER, WS_VSCROLL = (0x40000000, 0x10000000, 0x10000, 0x20000,
                                                                       0x800000, 0x200000)
    WS_CAPTION, WS_SYSMENU, WS_MINIMIZEBOX = 0xC00000, 0x80000, 0x20000
    BS_AUTORADIOBUTTON, BS_PUSHBUTTON, BS_DEFPUSHBUTTON = 9, 0, 1
    ES_AUTOHSCROLL, LBS_NOTIFY, LBS_NOINTEGRALHEIGHT = 0x80, 1, 0x100
    WM_SETFONT, WM_COMMAND, WM_CLOSE, WM_DESTROY, WM_APP = 0x30, 0x111, 0x10, 0x2, 0x8000
    BM_GETCHECK, BM_SETCHECK, EM_SETLIMITTEXT = 0xF0, 0xF1, 0xC5
    LB_ADDSTRING, LB_RESETCONTENT, LB_GETCURSEL, LB_SETCURSEL = 0x180, 0x184, 0x188, 0x186
    LBN_SELCHANGE, BN_CLICKED = 1, 0
    hinst = k32.GetModuleHandleW(None)
    font = g32.GetStockObject(17)     # DEFAULT_GUI_FONT

    (R_OFF, R_REPSN, R_COM, E_SERVER, B_FIND, E_NAME, L_LAN, L_PRESETS, E_PLABEL, E_PADDR, E_PNAME, B_ADD, B_UPDATE,
     B_DELETE, B_USE, S_STATUS, B_SAVE, B_CLOSE) = range(101, 119)
    state = {"labels": [], "busy": False}
    wndproc_ref = []

    def item(h, i):
        return u32.GetDlgItem(h, i)

    def text(h, i):
        hw = item(h, i)
        n = u32.GetWindowTextLengthW(hw)
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hw, buf, n + 1)
        return buf.value

    def set_text(h, i, t):
        u32.SetWindowTextW(item(h, i), t)

    def add(h, cls, txt, style, x, y, cx, cy, cid, limit=0):
        hw = u32.CreateWindowExW(0x200 if cls in ("EDIT", "LISTBOX") else 0, cls, txt, WS_CHILD | WS_VISIBLE | style,
                                 x, y, cx, cy, h, w.HMENU(cid), hinst, None)
        u32.SendMessageW(hw, WM_SETFONT, font or 0, 1)
        if limit:
            u32.SendMessageW(hw, EM_SETLIMITTEXT, limit, 0)
        return hw

    def add_string(hw, t):
        buf = ctypes.create_unicode_buffer(t)      # alive until SendMessage returns (the list box copies it)
        u32.SendMessageW(hw, LB_ADDSTRING, 0, ctypes.addressof(buf))

    def method_of(h):
        for rid, m in ((R_OFF, "off"), (R_REPSN, "repsn"), (R_COM, "community")):
            if u32.SendMessageW(item(h, rid), BM_GETCHECK, 0, 0) == 1:
                return m
        return ""

    def show(h):
        for rid, m in ((R_OFF, "off"), (R_REPSN, "repsn"), (R_COM, "community")):
            u32.SendMessageW(item(h, rid), BM_SETCHECK, 1 if ctl.method == m else 0, 0)
        set_text(h, E_SERVER, ctl.server)
        set_text(h, E_NAME, ctl.name)
        lp = item(h, L_PRESETS)
        u32.SendMessageW(lp, LB_RESETCONTENT, 0, 0)
        state["labels"] = ctl.labels()
        for lab in state["labels"]:
            add_string(lp, ctl.label_text(lab))
        set_text(h, S_STATUS, ctl.status)

    def show_lan(h):
        ll = item(h, L_LAN)
        u32.SendMessageW(ll, LB_RESETCONTENT, 0, 0)
        for r in ctl.lan:
            add_string(ll, ctl.lan_text(r))
        set_text(h, S_STATUS, ctl.status)
        u32.EnableWindow(item(h, B_FIND), True)

    def selected_label(h):
        i = u32.SendMessageW(item(h, L_PRESETS), LB_GETCURSEL, 0, 0)
        return state["labels"][i] if 0 <= i < len(state["labels"]) else None

    def build(h):
        S = 0
        add(h, "STATIC", "How the game goes online (one method at a time):", S, 12, 10, 400, 18, 0)
        add(h, "BUTTON", "Off", BS_AUTORADIOBUTTON | WS_GROUP | WS_TABSTOP, 12, 32, 80, 20, R_OFF)
        add(h, "BUTTON", "re-psn", BS_AUTORADIOBUTTON, 100, 32, 90, 20, R_REPSN)
        add(h, "BUTTON", "Community server", BS_AUTORADIOBUTTON, 200, 32, 160, 20, R_COM)
        add(h, "STATIC", "re-psn server (host or host:port, port 36100 when left out):", S, 12, 64, 400, 18, 0)
        add(h, "EDIT", "", ES_AUTOHSCROLL | WS_TABSTOP | WS_GROUP, 12, 84, 270, 22, E_SERVER, 260)
        add(h, "BUTTON", "Find on LAN", BS_PUSHBUTTON | WS_TABSTOP, 292, 83, 120, 24, B_FIND)
        add(h, "STATIC", "Online name (3-16 letters, digits, - or _, starting with a letter):", S, 12, 112, 400, 18, 0)
        add(h, "EDIT", "", ES_AUTOHSCROLL | WS_TABSTOP, 12, 132, 180, 22, E_NAME, 16)
        add(h, "LISTBOX", "", LBS_NOTIFY | LBS_NOINTEGRALHEIGHT | WS_VSCROLL | WS_TABSTOP, 12, 160, 400, 52, L_LAN)
        add(h, "STATIC", REPSN_NOTE, S, 12, 216, 400, 32, 0)
        add(h, "STATIC", "Community server presets (yours; none is shipped):", S, 12, 256, 400, 18, 0)
        add(h, "STATIC", COMMUNITY_NOTE, S, 12, 276, 400, 46, 0)
        add(h, "LISTBOX", "", LBS_NOTIFY | LBS_NOINTEGRALHEIGHT | WS_VSCROLL | WS_TABSTOP, 12, 326, 150, 140, L_PRESETS)
        add(h, "STATIC", "Preset name:", S, 172, 326, 240, 16, 0)
        add(h, "EDIT", "", ES_AUTOHSCROLL | WS_TABSTOP, 172, 343, 240, 22, E_PLABEL, 32)
        add(h, "STATIC", "Address (host or host:port):", S, 172, 369, 240, 16, 0)
        add(h, "EDIT", "", ES_AUTOHSCROLL | WS_TABSTOP, 172, 386, 240, 22, E_PADDR, 260)
        add(h, "STATIC", "Online name:", S, 172, 412, 240, 16, 0)
        add(h, "EDIT", "", ES_AUTOHSCROLL | WS_TABSTOP, 172, 429, 240, 22, E_PNAME, 16)
        add(h, "BUTTON", "Add", BS_PUSHBUTTON | WS_TABSTOP, 12, 474, 92, 24, B_ADD)
        add(h, "BUTTON", "Update", BS_PUSHBUTTON | WS_TABSTOP, 114, 474, 92, 24, B_UPDATE)
        add(h, "BUTTON", "Delete", BS_PUSHBUTTON | WS_TABSTOP, 216, 474, 92, 24, B_DELETE)
        add(h, "BUTTON", "Use this one", BS_PUSHBUTTON | WS_TABSTOP, 318, 474, 94, 24, B_USE)
        add(h, "STATIC", "", S, 12, 508, 400, 46, S_STATUS)
        add(h, "BUTTON", "Save", BS_DEFPUSHBUTTON | WS_TABSTOP, 216, 560, 92, 26, B_SAVE)
        add(h, "BUTTON", "Close", BS_PUSHBUTTON | WS_TABSTOP, 318, 560, 94, 26, B_CLOSE)
        show(h)

    def on_command(h, cid, code):
        if cid in (B_SAVE, 1):          # 1: Enter (IDOK through IsDialogMessage)
            ctl.save(method_of(h), text(h, E_SERVER), text(h, E_NAME))
            show(h)
        elif cid in (B_CLOSE, 2):       # 2: Esc (IDCANCEL)
            u32.DestroyWindow(h)
        elif cid == B_FIND and not state["busy"]:
            state["busy"] = True
            u32.EnableWindow(item(h, B_FIND), False)
            set_text(h, S_STATUS, "Looking for a compatible server on this network...")

            def work():
                ctl.find_lan()
                state["busy"] = False
                u32.PostMessageW(h, WM_APP, 0, 0)
            threading.Thread(target=work, daemon=True).start()
        elif cid == L_LAN and code == LBN_SELCHANGE:
            srv = ctl.lan_pick(u32.SendMessageW(item(h, L_LAN), LB_GETCURSEL, 0, 0))
            if srv:
                set_text(h, E_SERVER, srv)
        elif cid == L_PRESETS and code == LBN_SELCHANGE:
            lab = selected_label(h)
            if lab:
                p = ctl.presets.get(lab, {})
                set_text(h, E_PLABEL, lab)
                set_text(h, E_PADDR, p.get("address", ""))
                set_text(h, E_PNAME, p.get("name", ""))
        elif cid in (B_ADD, B_UPDATE, B_DELETE, B_USE) and code == BN_CLICKED:
            lab = selected_label(h)
            if cid == B_ADD:
                ctl.preset_save(text(h, E_PLABEL), text(h, E_PADDR), text(h, E_PNAME))
            elif cid == B_UPDATE:
                if lab:
                    ctl.preset_save(text(h, E_PLABEL), text(h, E_PADDR), text(h, E_PNAME), old_label=lab)
                else:
                    ctl.status = "Select a preset first."
            elif cid == B_DELETE:
                ctl.preset_delete(lab)
            else:
                ctl.preset_use(lab)
            m, srv, nm = method_of(h), text(h, E_SERVER), text(h, E_NAME)
            show(h)
            for rid, mm in ((R_OFF, "off"), (R_REPSN, "repsn"), (R_COM, "community")):   # unsaved choices stay
                u32.SendMessageW(item(h, rid), BM_SETCHECK, 1 if m == mm else 0, 0)
            set_text(h, E_SERVER, srv)
            set_text(h, E_NAME, nm)

    @WNDPROC
    def proc(h, msg, wp, lp):
        try:
            if msg == WM_COMMAND:
                on_command(h, wp & 0xFFFF, (wp >> 16) & 0xFFFF)
                return 0
            if msg == WM_APP:
                show_lan(h)
                return 0
            if msg == WM_CLOSE:
                u32.DestroyWindow(h)
                return 0
            if msg == WM_DESTROY:
                u32.PostQuitMessage(0)
                return 0
        except Exception as e:   # pythonw has no console: say it in the window
            try:
                set_text(h, S_STATUS, f"Error: {e}")
            except Exception:
                pass
            return 0
        return u32.DefWindowProcW(h, msg, wp, lp)

    wndproc_ref.append(proc)
    wc = WNDCLASSW()
    wc.lpfnWndProc = proc
    wc.hInstance = hinst
    wc.hCursor = u32.LoadCursorW(None, ctypes.c_void_p(32512))
    wc.hbrBackground = w.HBRUSH(16)     # COLOR_BTNFACE + 1
    wc.lpszClassName = "KZ2OnlineSettings"
    u32.RegisterClassW(ctypes.byref(wc))
    h = u32.CreateWindowExW(0, wc.lpszClassName, TITLE, WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_VISIBLE,
                            -0x80000000, -0x80000000, 440, 640, None, None, hinst, None)
    build(h)
    msg = w.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if not u32.IsDialogMessageW(h, ctypes.byref(msg)):
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
    return 0


def describe(ctl, decision):
    lines = [f"shared folder: {ctl.shared or '(none: no %APPDATA%)'}",
             f"method: {ctl.method}", f"re-psn server: {ctl.server or '-'}", f"online name: {ctl.name or '-'}",
             f"community presets: {', '.join(ctl.label_text(k) for k in ctl.labels()) or '-'}",
             f"the game's decision at the next start: {decision['method']}"]
    if ctl.status:
        lines.append(ctl.status)
    return "\n".join(lines)


def run(shared, game_dir, environ):
    """launch.py --online. -> exit code."""
    if not shared:
        print("Online settings: no shared folder (%APPDATA% is not set and the install is not portable).")
        return 1
    ctl = Controller(shared, game_dir)
    if os.name == "nt":
        return run_window(ctl)
    print(describe(ctl, oi.decide(shared, game_dir, environ)))
    return 0
