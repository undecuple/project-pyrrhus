#!/usr/bin/env python3
"""Host test for rpcs3_locate.py's portable-RPCS3 places and the moved-folder redaction (no game data; Windows faked
on any host). Adapted from Project Helghast's launcher (tools/release/test_rpcs3_locate.py, same author, MIT).

  - an unzipped "rpcs3-v0.0.34-...-win64" in Downloads is found; a folder named like rpcs3 without rpcs3.exe, a
    deeper one and a folder that is not RPCS3 are not; a place that is itself a portable RPCS3 is found;
  - a hint at the portable folder's config/ child resolves to the portable root;
  - Documents/Desktop/Downloads come from the registry (moved, %VAR% expanded, an unknown %VAR% dropped) and the
    defaults under USERPROFILE stay in the list (a player may have left RPCS3 in the old place), once each;
  - a registry failure falls back to the defaults;
  - a moved Documents folder (outside the home folder) is redacted as <Documents> in rpcs3_locate.redact and in the
    first-run log (firstrun.redactor); a Documents folder inside the home folder stays %USERPROFILE%/<home>;
  - other users' folders, CMake's mangled form and URL-encoded forms of the home folder are redacted.

Exit 0 = PASS, 1 = FAIL."""
import json
import os
import sys
import tempfile
import urllib.parse
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firstrun as fr  # noqa: E402
import rpcs3_locate as L  # noqa: E402

fails = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        fails.append(what)


class FakeWR:
    HKEY_CURRENT_USER = 1
    vals = {}

    def OpenKey(self, root, sub):
        return object()

    def QueryValueEx(self, key, name):
        if name in self.vals:
            return self.vals[name], 2
        raise OSError(name)

    def CloseKey(self, key):
        pass


class NoWR(FakeWR):
    def OpenKey(self, root, sub):
        raise OSError("none")


def main():
    with tempfile.TemporaryDirectory() as td0:
        td = os.path.realpath(td0)
        home = Path(td) / "home"
        dl = home / "Downloads"
        port = dl / "rpcs3-v0.0.34-17000-win64"
        (port / "config").mkdir(parents=True)
        (port / "rpcs3.exe").write_bytes(b"MZ")
        (port / "config" / "vfs.yml").write_text("/dev_hdd0/: $(EmulatorDir)dev_hdd0/\n")
        (dl / "rpcs3-notes").mkdir()                       # named like rpcs3, no rpcs3.exe
        (dl / "other").mkdir()
        (dl / "other" / "rpcs3.exe").write_bytes(b"MZ")    # not named like rpcs3, not a place itself
        deep = dl / "a" / "rpcs3-deep"
        (deep / "config").mkdir(parents=True)
        (deep / "rpcs3.exe").write_bytes(b"MZ")
        games = Path(td) / "D" / "Games"                    # a drive's Games folder that is itself a portable RPCS3
        (games / "dev_hdd0").mkdir(parents=True)
        (games / "rpcs3.exe").write_bytes(b"MZ")
        env = {"USERPROFILE": str(home), "LOCALAPPDATA": str(Path(td) / "Local"), "APPDATA": str(Path(td) / "Roaming"),
               "ProgramFiles": str(Path(td) / "PF"), "ProgramFiles(x86)": "", "PUBLIC": "", "WINEHOMEDIR": "",
               "XDG_CONFIG_HOME": ""}
        with mock.patch.object(L, "_is_windows", return_value=True), \
                mock.patch.object(L, "_shell_folders", return_value=[]), \
                mock.patch.object(L, "_fixed_drives", return_value=[str(Path(td) / "D")]), \
                mock.patch.object(L.Path, "home", return_value=home), \
                mock.patch.dict(os.environ, env):
            res = L.find_rpcs3(None)
            roots = [(r["source"], r["root"]) for r in res]
            check(("windows-downloads", str(port)) in roots, f"an unzipped rpcs3-v... folder in Downloads is found {roots}")
            check(not any(str(deep) == r or r.endswith("rpcs3-notes") or r.endswith("other") for _, r in roots),
                  "a folder named like rpcs3 without rpcs3.exe, a deeper one and an unnamed one are not")
            check(("windows-drive-root", str(games)) in roots, "a drive's Games folder holding a portable RPCS3 is found")
            r0 = next(r for r in res if r["root"] == str(port))
            check(r0["dev_hdd0"] == str(port / "dev_hdd0"), "its dev_hdd0 comes from the portable vfs.yml")
            res = L.find_rpcs3(str(port / "config"))
            check(res and res[0]["source"] == "hint" and res[0]["root"] == str(port),
                  "a hint at the portable folder's config/ resolves to the portable root")
            check(len(roots) == len(set(r for _, r in roots)), "each folder once")
            with mock.patch.object(L, "_PORTABLE_MAX", 0):
                check(not any(r == str(port) for _, r in [(x["source"], x["root"]) for x in L.find_rpcs3(None)]),
                      "the children examined per place are capped")

        # registry: moved folders first, %VAR% expanded, unknown %VAR% dropped, defaults kept, once each
        FakeWR.vals = {"Personal": "%KZ2FAKE%\\Docs", "Desktop": "%NOPE_KZ2%\\Desktop",
                       "{374DE290-123F-4565-9164-39C4925E467B}": str(home / "Downloads")}
        with mock.patch.dict(os.environ, {"KZ2FAKE": "D:\\Jane Doe", "USERPROFILE": str(home)}):
            os.environ.pop("NOPE_KZ2", None)
            sf = L._shell_folders(FakeWR())
            check(sf == [("D:\\Jane Doe\\Docs", "windows-documents"), (str(home / "Downloads"), "windows-downloads")],
                  f"registry folders expanded, an unknown %VAR% dropped {sf}")
            uf = L._user_folders(FakeWR())
            check(uf[0] == ("D:\\Jane Doe\\Docs", "windows-documents")
                  and (os.path.join(str(home), "Documents"), "windows-documents") in uf
                  and len([u for u in uf if u[1] == "windows-downloads"]) == 1,
                  f"a moved Documents first, the default kept, Downloads once {uf}")
            check(L._shell_folders(NoWR()) == [] and len(L._user_folders(NoWR())) == 3,
                  "a registry failure falls back to the defaults")

        # redaction of a moved Documents folder
        moved = [("D:\\Jane Doe\\Docs", "windows-documents"), (str(home / "Desktop"), "windows-desktop")]
        with mock.patch.object(L.Path, "home", return_value=home), mock.patch.dict(os.environ, {"WINEHOMEDIR": ""}):
            check(L.redact("D:\\Jane Doe\\Docs\\RPCS3\\dev_hdd0", shell=moved) == "<Documents>/RPCS3/dev_hdd0",
                  "rpcs3_locate.redact: a moved Documents folder is <Documents>")
            check(L.redact(str(home / "Desktop" / "x"), shell=moved) == "<home>/Desktop/x",
                  "rpcs3_locate.redact: a Desktop inside the home folder stays <home>")
        with mock.patch.dict(os.environ, {"USERPROFILE": str(home), "HOME": str(home), "KZ2FAKE": "D:\\Jane Doe"}):
            sh = fr.moved_shell_folders((str(home),), FakeWR())
            check(("D:\\Jane Doe\\Docs", "<Documents>") in sh and not any(lab == "<Downloads>" for _, lab in sh),
                  f"firstrun.moved_shell_folders: only the folders outside home {sh}")
            red = fr.redactor(shell=sh)
            line = "dump D:\\Jane Doe\\Docs\\kz2 and " + json.dumps("D:\\Jane Doe\\Docs\\x")
            out = red(line)
            check("Jane" not in out and out.count("<Documents>") == 2, f"first-run log: a moved Documents folder ({out})")
            out = red("C:\\Users\\Other Person\\Games and C_/Users/Other_Person/x and C%3A%5CUsers%5COther%20Person%5Cy")
            check("Other" not in out and out.count("<user>") == 3, f"another user's folder in three forms ({out})")
            h = str(home)
            for form in (h.replace(" ", "_"), urllib.parse.quote(h, safe=""), urllib.parse.quote(h, safe="/:")):
                check(str(home) not in red(form + "/x") and "%USERPROFILE%" in red(form + "/x"),
                      f"the home folder's {form[:12]}... form is redacted")
    print("test_rpcs3_locate: " + ("FAIL" if fails else "PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
