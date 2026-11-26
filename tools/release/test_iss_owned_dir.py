#!/usr/bin/env python3
"""Host test for installer/kz2.iss's folder guard: an install into, or an uninstall from, a folder that is not Project
Pyrrhus's never deletes files there, and a player's own earlier install stays installable.

Behaviour (the routines run by tools/release/iss_pascal.py against a scratch folder; Inno Setup is not run here):
  B1 the uninstaller's last step (usPostUninstall) in a folder that is not ours leaves its gamedata, even on "Yes";
  B2 an uninstall that keeps gamedata keeps the marker, so DirIsOurs still accepts the folder for a reinstall; an
     install from before the marker gets one; with only unins000.* left the marker goes;
  B3 DirIsOurs: the marker; an install from before it (kz2-setup\release\firstrun.py); the launcher exe with an ini
     naming a game folder; not the launcher exe with any manifest.json;
  B4 OwnedSub, DataSub and RemoveVfsFolder never go through a junction or symbolic link (a symlink here);
  B5 the shared legacy VFS folder goes only when its link.json target is this install's game folder.
Negative controls: B1 and B2 are run again on a copy of kz2.iss with the guard taken out (the pre-fix code) and must
fail there. Text checks: every {app} delete line is guarded; the marker is written after the install only when
DirOwned; InstallDirProblem refuses a non-empty folder that is not ours, first; the P2 folder note.
Exit 0 = PASS.

    python3 tools/release/test_iss_owned_dir.py
"""
import hashlib
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import iss_pascal  # noqa: E402

ISS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "installer", "kz2.iss")
fails = []


def check(ok, msg, detail=""):
    print(("ok   " if ok else "FAIL ") + msg + ("" if ok else f"\n     {str(detail)[:300]}"))
    if not ok:
        fails.append(msg)


with open(ISS, encoding="utf-8-sig") as f:
    t = f.read()
sec, lines = None, []
for ln in t.splitlines():
    if ln.startswith("["):
        sec = ln.strip()
    if sec in ("[InstallDelete]", "[UninstallDelete]") and ln.startswith("Type:"):
        lines.append((sec, ln))
app = [ln for _, ln in lines if 'Name: "{app}' in ln]
check(len(app) >= 20, f"{len(app)} delete lines under {{app}}")
bad = [ln for ln in app if not (ln.rstrip().endswith("; Check: OwnedDir") or
       re.search(r'Type: filesandordirs; Name: "\{app\}\\([^"]+)"; Check: OwnedSub\(\'\1\'\)$', ln))]
whole = [ln for _, ln in lines if ln.startswith("Type: filesandordirs")]
check(all("Check: OwnedSub(" in ln or "Check: DataSub(" in ln for ln in whole),
      "every whole-folder delete checks for links (OwnedSub, DataSub)", [ln for ln in whole if "Sub(" not in ln][:3])
check(not bad, "every {app} delete line ends with Check: OwnedDir, or OwnedSub(its own folder)", bad[:3])
check('#define OwnedMarker "kz2-owned.txt"' in t, "marker name defined once")


def body(name):
    m = re.search(r"^(?:function|procedure) " + name + r"\b.*?^end;", t, re.M | re.S)
    return m.group(0) if m else ""


own, prob = body("OwnedDir"), body("InstallDirProblem")
check("IsUninstaller" in own and "DirIsOurs(ExpandConstant('{app}'))" in own and "UninstOwnedSet := True" in own
      and "Result := DirOwned" in own, "OwnedDir: DirOwned in setup, DirIsOurs({app}) once in the uninstaller", own)
first = prob.find("DirIsEmpty(D)")
check(first > 0 and "not DirIsOurs(D)" in prob and first < prob.find("InOneDrive"),
      "InstallDirProblem refuses a non-empty folder that is not ours, first", prob[:400])
prep = body("PrepareToInstall")
check("DirOwned := (Result = '')" in prep and prep.find("InstallDirProblem") < prep.find("DirOwned :="),
      "PrepareToInstall sets DirOwned from the folder check", prep[:300])
cur = body("CurStepChanged")
check(re.search(r"\(CurStep = ssPostInstall\) and DirOwned then\s+SaveStringToFile\(ExpandConstant\('\{app\}\\\{#OwnedMarker\}'\)",
                cur) is not None, "the marker is written after the install, only when DirOwned", cur)


# ---- behaviour: the guard routines run on a scratch folder ----
APP = "C:\\Games\\Pyrrhus"
ROUTINES = ["DirIsEmpty", "DirIsOurs", "IsReparse", "NoLinkOnWay", "OwnedDir", "OwnedSub", "DataSub",
            "AskDeleteSaves", "AskDeletePortableSaves", "InstallKey", "RemoveVfsFolder", "IsOwnAltVfs",
            "LegacyVfsIsOurs", "RemoveVfsFolders", "OnlyUninstallerLeft", "CurUninstallStepChanged"]


class World:
    """Windows paths (C:\\...) mapped into a scratch folder; MsgBox answers `answer`."""

    def __init__(self, src, answer=6, silent=False, uninstaller=True):
        self.tmp = tempfile.mkdtemp(prefix="kz2-owned-")
        self.answer, self.silent, self.asked, self.log = answer, silent, [], []
        self.consts = {"app": APP, "userappdata": "C:\\Users\\p\\AppData\\Roaming",
                       "localappdata": "C:\\Users\\p\\AppData\\Local"}
        self.find = {}
        b = {
            "FileExists": (lambda p: os.path.isfile(self.h(p)), ()),
            "DirExists": (lambda p: os.path.isdir(self.h(p)), ()),
            "AddBackslash": (lambda p: p if p.endswith("\\") else p + "\\", ()),
            "RemoveBackslashUnlessRoot": (lambda p: p.rstrip("\\") if len(p.rstrip("\\")) > 2 else p, ()),
            "ExpandConstant": (self.expand, ()),
            "Log": (self.log.append, ()),
            "MsgBox": (self.msgbox, ()),
            "UninstallSilent": (lambda: self.silent, ()),
            "IsUninstaller": (lambda: uninstaller, ()),
            "DelTree": (self.deltree, ()),
            "RemoveDir": (self.removedir, ()),
            "DeleteFile": (self.deletefile, ()),
            "SaveStringToFile": (self.save, ()),
            "LoadStringFromFile": (self.load, (1,)),
            "FindFirst": (self.findfirst, (1,)),
            "FindNext": (self.findnext, (0,)),
            "FindClose": (lambda r: None, (0,)),
            "IniKeyExists": (self.inikey, ()),
            "GetIniString": (self.iniget, ()),
            "Pos": (lambda a, b: b.find(a) + 1, ()),
            "Copy": (lambda s, i, n: s[i - 1:i - 1 + n], ()),
            "Length": (len, ()),
            "Lowercase": (lambda s: "".join(c.lower() if "A" <= c <= "Z" else c for c in s), ()),
            "CompareText": (lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()), ()),
            "ExtractFileExt": (lambda p: os.path.splitext(p.split("\\")[-1])[1], ()),
            "ExtractFileDir": (lambda p: p.rsplit("\\", 1)[0], ()),
            "ExtractFileName": (lambda p: p.rsplit("\\", 1)[-1], ()),
            "StringChangeEx": (lambda r, a, b, _all: r.set(r.get().replace(a, b)), (0,)),
            "GetSHA256OfUnicodeString": (lambda s: hashlib.sha256(s.encode("utf-16-le")).hexdigest(), ()),
        }
        g = {"DirOwned": False, "UninstOwned": False, "UninstOwnedSet": False, "usUninstall": 1, "usPostUninstall": 2,
             "IDYES": 6, "IDNO": 7, "mbConfirmation": 1, "MB_YESNO": 4, "MB_DEFBUTTON2": 256}
        self.prog = iss_pascal.Program(src, ROUTINES, b, g)

    def h(self, p):
        p = p.replace("/", "\\").rstrip("\\")
        return os.path.join(self.tmp, *[x.replace(":", "") for x in p.split("\\") if x])

    def expand(self, s):
        return re.sub(r"\{(\w+)\}", lambda m: self.consts[m.group(1)], s)

    def msgbox(self, text, *a):
        self.asked.append(text)
        return self.answer

    def deltree(self, p, isdir, files, subdirs):
        q = self.h(p)
        if os.path.islink(q):
            os.unlink(q)
        elif os.path.isdir(q):
            shutil.rmtree(q)

    def removedir(self, p):
        q = self.h(p)
        try:
            os.unlink(q) if os.path.islink(q) else os.rmdir(q)
            return True
        except OSError:
            return False

    def deletefile(self, p):
        try:
            os.unlink(self.h(p))
            return True
        except OSError:
            return False

    def save(self, p, text, append):
        os.makedirs(os.path.dirname(self.h(p)), exist_ok=True)
        with open(self.h(p), "a" if append else "w") as f:
            f.write(text)
        return True

    def load(self, p, ref):
        try:
            with open(self.h(p), encoding="utf-8") as f:
                ref.set(f.read())
            return True
        except OSError:
            return False

    def _rec(self, full):
        return iss_pascal.Record(Name=os.path.basename(full), Attributes=(0x400 if os.path.islink(full) else 0) |
                                 (0x10 if os.path.isdir(full) else 0))

    def findfirst(self, pattern, ref):
        if pattern.endswith("\\*"):
            d = self.h(pattern[:-2])
            if not os.path.isdir(d):
                return False
            names = [".", ".."] + sorted(os.listdir(d))
            self.find[id(ref.env)] = [iss_pascal.Record(Name=n, Attributes=0) for n in names]
            ref.set(self.find[id(ref.env)].pop(0))
            return True
        q = self.h(pattern)
        if not os.path.lexists(q):
            return False
        ref.set(self._rec(q))
        return True

    def findnext(self, ref):
        rest = self.find.get(id(ref.env)) or []
        if not rest:
            return False
        ref.set(rest.pop(0))
        return True

    def _ini(self, path):
        sec, out = None, {}
        try:
            for ln in open(self.h(path), encoding="utf-8"):
                ln = ln.strip()
                if ln.startswith("["):
                    sec = ln[1:-1].lower()
                elif "=" in ln and sec:
                    k, v = ln.split("=", 1)
                    out[(sec, k.strip().lower())] = v.strip()
        except OSError:
            pass
        return out

    def inikey(self, sec, key, path):
        return (sec.lower(), key.lower()) in self._ini(path)

    def iniget(self, sec, key, default, path):
        return self._ini(path).get((sec.lower(), key.lower()), default)

    def mk(self, rel, text="x"):
        q = self.h(rel)
        os.makedirs(os.path.dirname(q), exist_ok=True)
        with open(q, "w", encoding="utf-8") as f:
            f.write(text)

    def done(self):
        shutil.rmtree(self.tmp)


def b1(src):
    """not ours, gamedata there, the player answers Yes: gamedata must stay"""
    w = World(src, answer=6)
    try:
        w.mk(APP + "\\gamedata\\SAVE\\x.bin")
        w.mk(APP + "\\notes.txt")
        w.prog.call("CurUninstallStepChanged", 1)
        w.prog.call("CurUninstallStepChanged", 2)
        return os.path.isfile(w.h(APP + "\\gamedata\\SAVE\\x.bin"))
    finally:
        w.done()


def b2(src, marker=True):
    """ours (marker, or an install from before it), the player keeps gamedata, unins000.exe still there: the folder
    must still be ours afterwards (a reinstall is not refused)"""
    w = World(src, answer=7)
    try:
        if marker:
            w.mk(APP + "\\kz2-owned.txt")
        else:
            w.mk(APP + "\\Project Pyrrhus.exe")
            w.mk(APP + "\\kz2-install.ini", "[paths]\ndump=D:\\KZ2\n")
        w.mk(APP + "\\gamedata\\SAVE\\x.bin")
        w.mk(APP + "\\unins000.exe")
        w.prog.call("CurUninstallStepChanged", 1)
        # Inno's own deletes (the [UninstallDelete] lists, the installed files) happen between the two steps
        for n in ("Project Pyrrhus.exe", "kz2-install.ini"):
            if os.path.exists(w.h(APP + "\\" + n)):
                os.unlink(w.h(APP + "\\" + n))
        w.prog.call("CurUninstallStepChanged", 2)
        os.unlink(w.h(APP + "\\unins000.exe"))           # Inno removes its uninstaller after this step
        return (os.path.isfile(w.h(APP + "\\gamedata\\SAVE\\x.bin")) and bool(w.prog.call("DirIsOurs", APP)))
    finally:
        w.done()


def guard_removed(src):
    """the pre-fix usPostUninstall: no OwnedDir exit, AskDeletePortableSaves unguarded, the marker always deleted"""
    s = src.replace("  { Nothing more in a folder that is not ours: not its gamedata, not its marker, not the folder }\n"
                    "  if not OwnedDir then Exit;\n", "")
    s = s.replace("  if not OwnedDir or not NoLinkOnWay(App, 'gamedata') then Exit;\n", "")
    s = s.replace("  if OnlyUninstallerLeft(ExpandConstant('{app}')) then\n", "  if True then\n")
    return s


src = t
check(b1(src), "B1 an uninstall in a folder that is not ours keeps its gamedata (answer Yes)")
check(b2(src), "B2 an uninstall that keeps gamedata leaves the folder ours for a reinstall (marker)")
check(b2(src, marker=False), "B2 the same for an install from before the marker (launcher + ini): it gets a marker")
pre = guard_removed(src)
check(pre != src and not b1(pre), "B1 negative control: without the guard the not-ours gamedata is deleted")
check(pre != src and not b2(pre), "B2 negative control: without the guard the kept folder is refused afterwards")

w = World(src)
try:
    w.mk(APP + "\\kz2-owned.txt")
    w.mk(APP + "\\unins000.exe")
    w.mk(APP + "\\unins000.dat")
    w.prog.call("CurUninstallStepChanged", 2)
    check(not os.path.exists(w.h(APP + "\\kz2-owned.txt")), "B2 with only unins000.* left the marker goes")
finally:
    w.done()

w = World(src)
try:
    cases = []
    for name, files, want in (
            ("empty", [], False),
            ("marker", ["kz2-owned.txt"], True),
            ("an install from before the marker", ["kz2-setup\\release\\firstrun.py", "build\\x"], True),
            ("launcher + ini naming a game folder", ["Project Pyrrhus.exe", ("kz2-install.ini", "[paths]\ndump=D:\\g\n")], True),
            ("launcher + an ini without [paths] dump", ["Project Pyrrhus.exe", ("kz2-install.ini", "[x]\ny=1\n")], False),
            ("launcher + some manifest.json", ["Project Pyrrhus.exe", "manifest.json"], False)):
        d = APP + "-" + str(len(cases))
        for f in files:
            n, txt = f if isinstance(f, tuple) else (f, "x")
            w.mk(d + "\\" + n, txt)
        got = bool(w.prog.call("DirIsOurs", d))
        cases.append((name, got == want))
    check(all(ok for _, ok in cases), "B3 DirIsOurs: marker, pre-marker install, launcher + ini; not launcher + any manifest",
          [n for n, ok in cases if not ok])
finally:
    w.done()

w = World(src)
try:
    outside = w.h("D:\\Mine")
    os.makedirs(os.path.join(outside, "PS3_GAME"))
    open(os.path.join(outside, "keep.txt"), "w").close()
    os.makedirs(w.h(APP))
    os.symlink(outside, w.h(APP + "\\build"))
    os.symlink(outside, w.h(APP + "\\vfs"))
    w.prog.glob["uninstowned"], w.prog.glob["uninstownedset"] = True, True
    sub_build = w.prog.call("OwnedSub", "build")
    sub_vfs = w.prog.call("OwnedSub", "vfs\\cache")
    os.makedirs(w.h(APP + "\\logs"))
    sub_logs = w.prog.call("OwnedSub", "logs")
    w.prog.call("RemoveVfsFolder", APP + "\\vfs")
    check(sub_build is False and sub_vfs is False and sub_logs is True
          and os.path.isfile(os.path.join(outside, "keep.txt")) and os.path.isdir(os.path.join(outside, "PS3_GAME")),
          "B4 no whole-folder delete through a symlink (OwnedSub build, vfs\\cache; RemoveVfsFolder); a real folder passes",
          (sub_build, sub_vfs, sub_logs))
    os.makedirs(w.h("C:\\Users\\p\\AppData\\Roaming\\Project Pyrrhus"))
    os.symlink(outside, w.h("C:\\Users\\p\\AppData\\Roaming\\Project Pyrrhus\\cache"))
    check(w.prog.call("DataSub", "cache") is False, "B4 DataSub refuses a symlinked data cache")
finally:
    w.done()

for target, want in (("D:\\KZ2\\PS3_GAME", True), ("E:\\Other\\PS3_GAME", False), (None, False)):
    w = World(src)
    try:
        leg = "C:\\Users\\p\\AppData\\Local\\Project Pyrrhus\\vfs"
        w.mk(APP + "\\kz2-install.ini", "[paths]\ndump=D:\\KZ2\n")
        w.mk(leg + "\\psarc-cache\\a.bin")
        if target:
            w.mk(leg + "\\link.json", '{\n "link": "x",\n "target": "' + target.replace("\\", "\\\\") + '"\n}')
        w.prog.call("RemoveVfsFolders")
        check(os.path.isdir(w.h(leg)) != want, f"B5 legacy VFS folder linked to {target}: {'removed' if want else 'kept'}")
    finally:
        w.done()

check(not any("OwnedMarker" in ln for _, ln in lines), "the marker is not in a delete list (code removes it last)")
# the folder note for letters outside A to Z (firstrun_check P2's words): asked on the folder page, logged when silent
note, nbc = body("InstallDirNote"), body("NextButtonClick")
check("HasNonAscii(Dir)" in note and "outside A to Z" in note and "Use this folder anyway?" in note
      and re.search(r"Ord\(Dir\[I\]\) > 127", body("HasNonAscii")) is not None, "InstallDirNote: non-ASCII letters, P2's words")
check(re.search(r"InstallDirNote\(WizardDirValue\), mbConfirmation, MB_YESNO", nbc) is not None
      and nbc.find("InstallDirProblem(WizardDirValue)") < nbc.find("InstallDirNote(WizardDirValue)"),
      "the folder page asks after the refusals, and Yes takes the folder", nbc[:200])
check("install folder note (P2)" in prep and "InstallDirNote" not in prob, "a silent install logs the note; it never refuses")
with open(os.path.join(os.path.dirname(ISS), "..", "tools", "release", "firstrun_check.py"), encoding="utf-8") as f:
    fcs = f.read()
check('r.warn("P2"' in fcs and "not tested with letters" in fcs and "outside A to Z" in fcs
      and "digits, spaces and - _ . ( )" in fcs and "digits, spaces and - _ . ( )" in note,
      "firstrun_check P2 gives the same reason and the same advice")
try:
    iss_pascal.Program("[Code]\nfunction F: Integer;\nconst\n  C = 1;\nbegin\n  Result := C;\nend;\n", ["F"], {})
    refused = False
except iss_pascal.PascalError:
    refused = True
check(refused, "the interpreter refuses a routine's own const section, as ISCC 6.7.3 does ('BEGIN' expected)")
print("PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
