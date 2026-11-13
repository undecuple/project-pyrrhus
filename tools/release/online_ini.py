#!/usr/bin/env python3
"""The online settings files, read and written by the launcher's Online settings window (online_dialog.py) and
checked at each start (launch.py). The game reads the same files before main() (port/kz2/kz2_online.cpp); the two
parsers follow the same rules, and test_online_ini.py runs the reader's test files through this one too.

Design after jsp-vs-ex PR #83 (Tsamiuy, "Online settings: launcher tab, game-side reader", MIT) and
shared-docs/repsn-ini.md (the shared folder and file split agreed between the ports). Code written here.

Files (untrusted input: 64 KB per file, 512 bytes per line, known sections and keys only, nothing executed):
  shared folder (shared_dir): PS3RECOMP_SHARED_DIR, else <install>/shared when portable, else %APPDATA%/PS3Recomp
    repsn.ini       [repsn] enabled = 0|1, server = host[:port] (36100 when left out), name = online ID
    community.ini   [community] enabled = 0|1, active = LABEL; [preset LABEL] address = host[:port], name = online ID
                    (made with a top comment that port-only features do not work there; no preset is ever shipped)
  game folder (launch.data_dir): repsn.ini [repsn] p2p_port, comm_id, report_rtt (the game's own values; also
    enabled/server/name, read after the shared file)

Rules for writing (shared-docs/repsn-ini.md "Rules for every writer"):
  - the file is read again just before each change; only the keys this module owns change, every other line
    (comments, unknown keys, rejected lines, the player's spacing) stays;
  - a file that cannot be used (over 64 KB, unreadable) is reported and never overwritten;
  - a save goes to a temporary file in the same folder, is flushed and fsynced, then os.replace()d over the old one;
  - choosing a method sets one file's enabled to 1 and the other's to 0 in the same save; the file being switched
    off is written first, so a stop between the two leaves both off, never both on;
  - the folder is made when the player saves (never at a plain start).

Find on LAN: one 64-byte DISCOVER to UDP port 36100 (broadcast), replies of 52 bytes collected for about 1.2 s,
for re-psn 0.5.0 or later started with -discover (re-psn main a625772f server/discover.go, client/psnr.h). Replies
are untrusted: exact length, magic, type and nonce checked, port 0 refused, text cut at the first NUL and made
printable, at most 16 results, de-duplicated; the address goes through the same check as a typed one.
"""
import os
import re
import socket
import struct
import tempfile
import time

MAX_FILE = 64 * 1024
MAX_LINE = 512
DEFAULT_PORT = 36100
SHARED_FOLDER = "PS3Recomp"
REPSN = "repsn.ini"
COMMUNITY = "community.ini"
METHODS = ("off", "repsn", "community")
COMMUNITY_HEADER = ("; Community server settings (Project Pyrrhus Online settings writes this file).",
                    "; Features that exist only in this port do not work on a community server.",
                    "; One method at a time: re-psn (repsn.ini) or a community server (this file), never both.")

_HOST = re.compile(r"[A-Za-z0-9._-]{1,253}")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,15}")
_LABEL = re.compile(r"[A-Za-z0-9_-]{1,32}")
_COMM = re.compile(r"[A-Z0-9_]{9,12}")


class OnlineError(Exception):
    """A settings file that cannot be read or written; str() names the file and the reason."""


# ------------------------------------------------------------------------------------------------------ checks
def valid_port(p):
    return bool(re.fullmatch(r"[0-9]{1,5}", p or "")) and 1 <= int(p) <= 65535


def valid_hostport(s):
    """host[:port]: letters, digits, '.', '-', '_' (no leading '.' or '-', no IPv6 literal), port 1-65535."""
    s = s or ""
    host, sep, port = s.partition(":")
    if sep and not valid_port(port):
        return False
    return bool(_HOST.fullmatch(host)) and host[0] not in ".-"


def valid_name(n):
    """The online ID: 3-16 of A-Za-z0-9_-, starting with a letter."""
    return bool(_NAME.fullmatch(n or ""))


def valid_label(n):
    return bool(_LABEL.fullmatch(n or ""))


def with_port(s):
    return s if ":" in s else f"{s}:{DEFAULT_PORT}"


def shown(v):
    """A value as a message shows it: printable ASCII, at most 64 characters."""
    o = "".join(c if " " <= c <= "~" else "?" for c in v[:64])
    return o + ("..." if len(v) > 64 else "")


# ------------------------------------------------------------------------------------------------------ folders
def shared_dir(root, portable, environ, appdata=None):
    """PS3RECOMP_SHARED_DIR, else <root>/shared when portable, else %APPDATA%/PS3Recomp ("" without %APPDATA%)."""
    ov = environ.get("PS3RECOMP_SHARED_DIR", "")
    if ov:
        return ov
    if portable:
        return os.path.join(root, "shared")
    appdata = appdata if appdata is not None else environ.get("APPDATA", "")
    return os.path.join(appdata, SHARED_FOLDER) if appdata else ""


# ------------------------------------------------------------------------------------------------------ reading
def _read_raw(path):
    """-> bytes, None for a missing file; OnlineError for one over 64 KB or unreadable."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE + 1)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise OnlineError(f"{path} could not be read ({e.strerror or e})") from e
    if len(raw) > MAX_FILE:
        raise OnlineError(f"{path} is larger than 64 KB")
    return raw


def _lines(raw):
    """bytes -> list of str lines (BOM dropped, split on \\n, a trailing \\r kept for the 512-byte count like the
    game's reader). Bytes outside UTF-8 become U+FFFD and fail every value check."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    parts = raw.split(b"\n")
    if parts and parts[-1] == b"":
        parts.pop()
    return parts


def parse(raw, kind, game=False):
    """-> (settings, rejected): settings {"enabled", "server", "name", "comm_id", "p2p_port", "report_rtt"} for
    repsn.ini, {"enabled", "active", "presets": {label: {"address", "name"}}} for community.ini; rejected = list of
    (line number, reason). The same rules as kz2_online.cpp parse()."""
    st = ({"enabled": None, "server": "", "name": "", "comm_id": "", "p2p_port": "", "report_rtt": ""} if kind == REPSN
          else {"enabled": None, "active": None, "presets": {}})
    rej = []
    sec, preset = 0, ""
    for n, b in enumerate(_lines(raw), 1):
        if len(b) > MAX_LINE:
            rej.append((n, "line over 512 bytes"))
            continue
        if b"\0" in b:
            rej.append((n, "NUL byte"))
            continue
        line = b.decode("utf-8", "replace").strip(" \t\r")
        if not line or line[0] in ";#":
            continue
        if line[0] == "[":
            sec = 0
            if not line.endswith("]"):
                rej.append((n, "bad section line"))
                continue
            s = line[1:-1].strip(" \t\r")
            ls = s.lower()
            if kind == REPSN and ls == "repsn":
                sec = 1
            elif kind == COMMUNITY and ls == "community":
                sec = 2
            elif ls.startswith("preset "):
                if kind == REPSN:
                    rej.append((n, "[preset] in repsn.ini: presets belong in community.ini"))
                else:
                    preset = s[7:].strip(" \t\r")
                    if valid_label(preset):
                        sec = 3
                        st["presets"].setdefault(preset, {})
                    else:
                        rej.append((n, "bad preset label, want 1-32 of A-Za-z0-9_-"))
            elif kind == REPSN and ls == "community":
                rej.append((n, "[community] in repsn.ini"))
            elif kind == COMMUNITY and ls == "repsn":
                rej.append((n, "[repsn] in community.ini"))
            else:
                rej.append((n, f"unknown section [{shown(s)}]"))
            continue
        if "=" not in line:
            rej.append((n, "no '='"))
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(" \t\r").lower(), v.strip(" \t\r")
        if sec == 0:
            rej.append((n, "key outside a known section"))
        elif sec == 1:
            if k == "enabled" and v in ("0", "1"):
                st["enabled"] = v == "1"
            elif k == "server" and valid_hostport(v):
                st["server"] = with_port(v)
            elif k == "name" and valid_name(v):
                st["name"] = v
            elif game and k == "comm_id" and _COMM.fullmatch(v):
                st["comm_id"] = v
            elif game and k == "p2p_port" and valid_port(v):
                st["p2p_port"] = v
            elif game and k == "report_rtt" and v in ("0", "1"):
                st["report_rtt"] = v
            elif k in ("enabled", "server", "name") or (game and k in ("comm_id", "p2p_port", "report_rtt")):
                rej.append((n, f"bad {k}"))
            else:
                rej.append((n, f"unknown key '{shown(k)}'"))
        elif sec == 2:
            if k == "enabled" and v in ("0", "1"):
                st["enabled"] = v == "1"
            elif k == "active" and (v == "" or valid_label(v)):
                st["active"] = v
            elif k in ("enabled", "active"):
                rej.append((n, f"bad {k}"))
            elif k == "server":
                rej.append((n, "re-psn key 'server' in community.ini"))
            else:
                rej.append((n, f"unknown key '{shown(k)}'"))
        else:
            if k == "address" and valid_hostport(v):
                st["presets"][preset]["address"] = with_port(v)
            elif k == "name" and valid_name(v):
                st["presets"][preset]["name"] = v
            elif k in ("address", "name"):
                rej.append((n, f"bad {k}"))
            else:
                rej.append((n, f"unknown key '{shown(k)}'"))
    return st, rej


def load(path, kind, game=False):
    """-> (settings, rejected) of the file at path (empty settings for a missing file). OnlineError when unusable."""
    raw = _read_raw(path)
    return parse(raw or b"", kind, game)


def decide(shared, game_dir, environ=None):
    """The game's decision for these files, as kz2_online.cpp apply() makes it without command-line flags.
    -> {"method": off|repsn|community|refused|env, "server", "name", "active", "rejected": int, "errors": [str]}."""
    environ = environ or {}
    rep = {"enabled": False, "server": "", "name": ""}
    com = {"enabled": False, "active": "", "presets": {}}
    rejected, errors = 0, []
    plan = []
    if shared:
        plan += [(os.path.join(shared, REPSN), REPSN, False), (os.path.join(shared, COMMUNITY), COMMUNITY, False)]
    if game_dir:
        plan.append((os.path.join(game_dir, REPSN), REPSN, True))
    for path, kind, game in plan:
        try:
            st, rej = load(path, kind, game)
        except OnlineError as e:
            errors.append(str(e))
            rejected += 1
            continue
        rejected += len(rej)
        tgt = rep if kind == REPSN else com
        for k, v in st.items():
            if k == "presets":
                for lab, vals in v.items():
                    com["presets"].setdefault(lab, {}).update(vals)
            elif v not in (None, ""):
                tgt[k] = v
    out = {"server": rep["server"], "name": rep["name"], "active": com["active"], "rejected": rejected,
           "errors": errors}
    # the runtime's switch is KZ3_ONLINE (patch 4001: set, non-empty, not "0"); PS3_NET_ONLINE is not read by it
    if environ.get("KZ3_ONLINE", "") not in ("", "0") or environ.get("PSNR_SERVER"):
        out["method"] = "env"
    elif rep["enabled"] and com["enabled"]:
        out["method"] = "refused"
    elif com["enabled"]:
        out["method"] = "community"
    elif rep["enabled"] and rep["server"]:
        out["method"] = "repsn"
    else:
        out["method"] = "off"
    return out


REFUSED_TEXT = ("Online play is off for this start: both re-psn and a community server are enabled, and the game "
                "never picks one by itself.\n\nOpen Online settings (Start menu, or run the launcher with --online) "
                "and choose one method.")


# ------------------------------------------------------------------------------------------------------ writing
class Doc:
    """One settings file as lines, changed in place: only owned keys change, every other line stays."""

    def __init__(self, path, kind):
        self.path, self.kind = path, kind
        raw = _read_raw(path)            # OnlineError: the file is reported and never overwritten
        self.existed = raw is not None
        raw = raw or b""
        self.crlf = b"\r\n" in raw
        self.lines = [b.decode("utf-8", "replace").rstrip("\r") for b in _lines(raw)]
        if not self.existed and kind == COMMUNITY:
            self.lines = list(COMMUNITY_HEADER) + [""]

    @staticmethod
    def _sec(line):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            return s[1:-1].strip().lower()
        return None

    def _span(self, section):
        """-> (header index, end index) of the first [section] (case-insensitive, inner spaces as written), or None."""
        want = section.lower()
        for i, line in enumerate(self.lines):
            if self._sec(line) is not None and " ".join(self._sec(line).split()) == want:
                j = i + 1
                while j < len(self.lines) and self._sec(self.lines[j]) is None:
                    j += 1
                return i, j
        return None

    def _spans(self, section):
        """-> every (header index, end index) of [section], in file order."""
        out, i = [], 0
        want = section.lower()
        while i < len(self.lines):
            sec = self._sec(self.lines[i])
            if sec is not None and " ".join(sec.split()) == want:
                j = i + 1
                while j < len(self.lines) and self._sec(self.lines[j]) is None:
                    j += 1
                out.append((i, j))
                i = j
            else:
                i += 1
        return out

    def collapse(self, section):
        """Repeated [section] blocks (the reader merges them, a later key winning) become the first one: the later
        blocks' lines move to its end in order, so the reader's result is unchanged and set() sees every key."""
        spans = self._spans(section)
        if len(spans) < 2:
            return
        moved = []
        for i, j in reversed(spans[1:]):
            moved[:0] = [x for x in self.lines[i + 1:j] if x.strip()]
            del self.lines[i:j]
        i, j = self._spans(section)[0]
        while j > i + 1 and not self.lines[j - 1].strip():
            j -= 1
        self.lines[j:j] = moved

    def set(self, section, key, value):
        self.collapse(section)
        sp = self._span(section)
        if sp is None:
            if self.lines and self.lines[-1].strip():
                self.lines.append("")
            self.lines += [f"[{section}]", f"{key} = {value}"]
            return
        i, j = sp
        self.lines[i] = f"[{section}]"      # the label as chosen: the reader's preset names are case-sensitive
        last = i
        for n in range(i + 1, j):
            s = self.lines[n].strip()
            if not s or s[0] in ";#" or "=" not in s:
                continue
            last = n
            if s.split("=", 1)[0].strip().lower() == key:
                self.lines[n] = f"{key} = {value}"
                # a later duplicate would win in the game's reader: drop it
                self.lines[n + 1:j] = [x for x in self.lines[n + 1:j]
                                       if not ("=" in x and x.strip()[:1] not in (";", "#")
                                               and x.split("=", 1)[0].strip().lower() == key)]
                return
        self.lines.insert(last + 1, f"{key} = {value}")

    def drop_section(self, section):
        """Every [section] block goes (the reader would still see a repeated one)."""
        for i, j in reversed(self._spans(section)):
            del self.lines[i:j]
            while i < len(self.lines) and i > 0 and not self.lines[i].strip() and not self.lines[i - 1].strip():
                del self.lines[i]

    def save(self, expect=None):
        """Write the file. expect(settings) -> True: the new text is parsed with the reader's rules first and a
        result that is not the choice raises OnlineError before anything is written."""
        d = os.path.dirname(os.path.abspath(self.path))
        nl = "\r\n" if (self.crlf or (not self.existed and os.name == "nt")) else "\n"
        data = (nl.join(self.lines) + nl).encode("utf-8")
        if expect is not None and not expect(parse(data, self.kind)[0]):
            raise OnlineError(f"{self.path}: the change would not read back as chosen (a hand edit the window cannot "
                              "follow); not saved. Fix or remove the file.")
        if len(data) > MAX_FILE:
            raise OnlineError(f"{self.path} would be larger than 64 KB; not saved")
        tmp = None
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".online-", suffix=".tmp", dir=d)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            tmp = None
        except OSError as e:
            raise OnlineError(f"{self.path} could not be written ({e.strerror or e})") from e
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def save_method(shared, method, server=None, name=None):
    """Choose the method: off, repsn or community. One file's enabled = 1, the other's 0 (the one switched off is
    written first). server/name (re-psn) are checked and written with it when given. OnlineError, ValueError."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}")
    if server is not None and server != "" and not valid_hostport(server):
        raise ValueError("Server: want host or host:port (letters, digits, '.', '-', '_'; port 1-65535).")
    if name is not None and name != "" and not valid_name(name):
        raise ValueError("Online name: 3-16 letters, digits, '-' or '_', starting with a letter.")
    if method == "repsn" and not (server or load(os.path.join(shared, REPSN), REPSN)[0]["server"]):
        raise ValueError("re-psn needs a server (host or host:port).")
    rep = Doc(os.path.join(shared, REPSN), REPSN)
    com = Doc(os.path.join(shared, COMMUNITY), COMMUNITY)     # both read before either is written
    rep.set("repsn", "enabled", "1" if method == "repsn" else "0")
    if server is not None and server != "":
        rep.set("repsn", "server", server)
    if name is not None and name != "":
        rep.set("repsn", "name", name)
    com.set("community", "enabled", "1" if method == "community" else "0")
    if method == "repsn":
        order = (com, rep)              # the one switched off first: a stop in between leaves both off
    elif method == "community":
        order = (rep, com)
    else:
        # "Off" makes no new file, except to keep a server or name the player typed
        order = tuple(d for d in (rep, com) if d.existed or (d is rep and (server or name)))
    srv = with_port(server) if server else None

    def rep_ok(st):
        return (st["enabled"] is (method == "repsn") and (srv is None or st["server"] == srv)
                and (not name or st["name"] == name))
    for d in order:
        d.save(rep_ok if d is rep else (lambda st: st["enabled"] is (method == "community")))


def save_preset(shared, label, address, name, old_label=None):
    """Add or change a preset ([preset LABEL] address, name); old_label renames. OnlineError, ValueError."""
    if not valid_label(label):
        raise ValueError("Preset name: 1-32 letters, digits, '-' or '_'.")
    if not valid_hostport(address):
        raise ValueError("Address: want host or host:port (letters, digits, '.', '-', '_'; port 1-65535).")
    if name and not valid_name(name):
        raise ValueError("Online name: 3-16 letters, digits, '-' or '_', starting with a letter.")
    doc = Doc(os.path.join(shared, COMMUNITY), COMMUNITY)
    if old_label and old_label.lower() != label.lower():
        if doc._span(f"preset {label}") is not None:     # never overwrite another preset by renaming onto it
            raise ValueError(f"A preset named {shown(label)} exists already; choose another name.")
        doc.drop_section(f"preset {old_label}")
        if (doc_active(doc) or "").lower() == old_label.lower():
            doc.set("community", "active", label)
    doc.set(f"preset {label}", "address", address)
    if name:
        doc.set(f"preset {label}", "name", name)
    gone = old_label if old_label and old_label.lower() != label.lower() else None
    doc.save(lambda st: st["presets"].get(label, {}).get("address") == with_port(address)
             and (not name or st["presets"][label].get("name") == name)
             and not (gone and any(k.lower() == gone.lower() for k in st["presets"])))


def doc_active(doc):
    """[community] active as the reader sees it: repeated blocks merged, the last key wins."""
    doc.collapse("community")
    sp = doc._span("community")
    if not sp:
        return None
    found = None
    for line in doc.lines[sp[0] + 1:sp[1]]:
        s = line.strip()
        if "=" in s and s[0] not in ";#" and s.split("=", 1)[0].strip().lower() == "active":
            found = s.split("=", 1)[1].strip()
    return found


def delete_preset(shared, label):
    doc = Doc(os.path.join(shared, COMMUNITY), COMMUNITY)
    doc.drop_section(f"preset {label}")
    if (doc_active(doc) or "").lower() == label.lower():
        doc.set("community", "active", "")
    doc.save(lambda st: not any(k.lower() == label.lower() for k in st["presets"])
             and (st["active"] or "").lower() != label.lower())


def pick_preset(shared, label):
    if not valid_label(label):
        raise ValueError("Preset name: 1-32 letters, digits, '-' or '_'.")
    doc = Doc(os.path.join(shared, COMMUNITY), COMMUNITY)
    doc.set("community", "active", label)
    doc.save(lambda st: st["active"] == label)


# ------------------------------------------------------------------------------------------------------ LAN
MAGIC = b"PSNR"
DISCOVER, DISCOVER_REPLY = 0x04, 0x84
REQUEST_LEN, REPLY_LEN = 64, 52
LAN_TIMEOUT = 1.2
LAN_MAX = 16


def discover_request(nonce):
    """The 64-byte DISCOVER: "PSNR", type 0x04, the 4-byte nonce, zeros."""
    return MAGIC + bytes([DISCOVER]) + nonce + bytes(REQUEST_LEN - 9)


def _text(b):
    b = b.split(b"\0", 1)[0]
    return "".join(chr(c) if 0x20 <= c <= 0x7e else "?" for c in b)


def parse_reply(pkt, nonce, src_ip):
    """One DISCOVER_REPLY -> {"address", "name", "version", "relay", "players"} or None (anything off is dropped)."""
    if len(pkt) != REPLY_LEN or pkt[:4] != MAGIC or pkt[4] != DISCOVER_REPLY or pkt[5:9] != nonce:
        return None
    tcp_port, udp_port, flags, players = struct.unpack(">HHBH", pkt[9:16])
    if tcp_port == 0:
        return None
    address = f"{src_ip}:{tcp_port}"
    if not valid_hostport(address):
        return None
    return {"address": address, "name": _text(pkt[16:40]), "version": _text(pkt[40:52]),
            "relay": bool(flags & 1), "players": players}


def find_on_lan(port=DEFAULT_PORT, timeout=LAN_TIMEOUT, targets=None, sock=None, nonce=None):
    """Broadcast one DISCOVER (targets: [(ip, port)], default the limited broadcast on port) and collect replies for
    timeout seconds. -> list of parse_reply dicts (at most 16, one per address)."""
    nonce = nonce or os.urandom(4)
    own = sock is None
    s = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    found, seen = [], set()
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if own:
            s.bind(("0.0.0.0", 0))
        for t in (targets or [("255.255.255.255", port)]):
            try:
                s.sendto(discover_request(nonce), t)
            except OSError:
                pass
        end = time.monotonic() + timeout
        while len(found) < LAN_MAX:
            left = end - time.monotonic()
            if left <= 0:
                break
            s.settimeout(left)
            try:
                pkt, (ip, _p) = s.recvfrom(256)
            except (socket.timeout, BlockingIOError):
                break
            except OSError:
                continue
            r = parse_reply(pkt, nonce, ip)
            if r and r["address"] not in seen:
                seen.add(r["address"])
                found.append(r)
    finally:
        if own:
            s.close()
    return found
