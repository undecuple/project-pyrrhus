#!/usr/bin/env python3
"""Which characters the game's own text uses (D53: the CJK face for patch 6061 is cut down to them).

    cjk_codepoints.py scan SOURCE [--patches DIR] [--name NAME] --out work/.../NAME.json
    cjk_codepoints.py merge SCAN.json... [--exclude-font NotoSans-Regular.ttf] [--margin 3040-30FF]... --out LIST.txt

SOURCE is a PSARC file (data_ps3.psarc, an update's added_data_ps3.psarc) or a zip holding one disc ISO, whose
/PS3_GAME/USRDIR/DATA_PS3.PSARC is read as a forward stream (nothing is extracted to disk). --patches applies the 1.29
update's .pspatch files (tools/assets/pspatch.py) to the entries they rewrite, in memory.

Text read: every .jsp page (UTF-8 SVML) and every .core file's string banks (String = UTF-8 bytes, WString = UTF-16BE;
tools/core.py's header parser, no schema needed). Speech audio, textures and Lua byte code are not decoded as text.

scan writes, per bucket (the Lumps/<Language>/ or SVML/<code>/ folder, else "common"), the sorted code points above
U+007F with their occurrence counts. That is a table of numbers, not text, but it is still built from game data: it is
written under work/ only. merge unions scans into the list patch 6061's CJK face is cut to (tools/runtime/mkfont_cjk.py):
code points as hex ranges, one per line, minus those --exclude-font already covers (the bundled Noto Sans).
"""
import argparse, json, os, struct, sys, zipfile, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "assets"))
import core      # noqa: E402  (tools/core.py)
import pspatch   # noqa: E402  (tools/assets/pspatch.py)

S = 2048


class FileStream:
    def __init__(self, path, base=0):
        self.f, self.base = open(path, "rb"), base

    def read_at(self, off, n):
        self.f.seek(self.base + off)
        return self.f.read(n)


class ZipIsoStream:
    """A disc ISO inside a zip, read forward only (a backward read reopens the member: slow, avoided by the caller)."""
    def __init__(self, zpath):
        self.z = zipfile.ZipFile(zpath)
        self.m = [i for i in self.z.infolist() if i.filename.lower().endswith(".iso")][0]
        self.f, self.pos, self.base, self.reopens = self.z.open(self.m), 0, 0, 0

    def read_at(self, off, n):
        off += self.base
        if off < self.pos:
            self.f.close(); self.f = self.z.open(self.m); self.pos = 0; self.reopens += 1
        while self.pos < off:
            k = self.f.read(min(off - self.pos, 64 << 20))
            if not k:
                raise EOFError("ISO ends early")
            self.pos += len(k)
        b = self.f.read(n); self.pos += len(b)
        return b

    def find_psarc(self):
        """Point base at /PS3_GAME/USRDIR/DATA_PS3.PSARC (its extents must be contiguous)."""
        pvd = self.read_at(16 * S, S)
        if pvd[1:6] != b"CD001":
            raise ValueError("no ISO9660 volume descriptor")
        def recs(lba, size):
            d, i, r = self.read_at(lba * S, size), 0, []
            while i < len(d):
                L = d[i]
                if L == 0:
                    i = (i // S + 1) * S; continue
                ext, sz = struct.unpack("<I", d[i + 2:i + 6])[0], struct.unpack("<I", d[i + 10:i + 14])[0]
                nm = d[i + 33:i + 33 + d[i + 32]]
                if nm not in (b"\0", b"\1"):
                    r.append((nm.decode("latin1").split(";")[0].upper(), ext, sz, d[i + 25] & 2))
                i += L
            return r
        root = pvd[156:190]
        lba, size = struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0]
        for part in ("PS3_GAME", "USRDIR"):
            lba, size = next((e, s) for n, e, s, d in recs(lba, size) if n == part and d)
        ext = sorted((e, s) for n, e, s, d in recs(lba, size) if n == "DATA_PS3.PSARC" and not d)
        for (e0, s0), (e1, _) in zip(ext, ext[1:]):
            if e0 * S + s0 != e1 * S:
                raise ValueError("DATA_PS3.PSARC extents are not contiguous")
        self.base = ext[0][0] * S
        return sum(s for _, s in ext)


def psarc_entries(st):
    h = st.read_at(0, 32)
    magic, _maj, _min, comp, toc_len, esz, count, bsz, flags = struct.unpack(">4sHH4sIIIII", h)
    if magic != b"PSAR" or comp != b"zlib" or flags & 4:
        raise ValueError(f"not a plain zlib PSARC ({magic!r} {comp!r} flags {flags})")
    toc = st.read_at(32, toc_len - 32)
    ents = []
    for i in range(count):
        e = toc[i * esz:(i + 1) * esz]
        ents.append((struct.unpack(">I", e[16:20])[0], int.from_bytes(e[20:25], "big"), int.from_bytes(e[25:30], "big")))
    w = 1
    while 256 ** w < bsz:
        w += 1
    tbl = toc[count * esz:]
    blocks = [int.from_bytes(tbl[j:j + w], "big") for j in range(0, len(tbl) - w + 1, w)]

    last = [None, None]                             # entries sharing data (one offset) are read once: a stream
                                                    # cannot seek back without reading the ISO again from its start
    def read(idx):
        block, size, off = ents[idx]
        if last[0] == (off, size):
            return last[1]
        out, pos = bytearray(), off
        while len(out) < size:
            cs = blocks[block] or bsz
            d = st.read_at(pos, cs); pos += cs
            want = min(bsz, size - len(out))
            if cs == want:
                out += d
            else:
                try:
                    out += zlib.decompress(d)
                except zlib.error:
                    out += d
            block += 1
        last[0], last[1] = (off, size), bytes(out[:size])
        return last[1]
    names = [""] + read(0).decode("utf-8").split("\n")
    return ents, names, read


def bucket(path):
    p = path.replace("\\", "/").lower().split("/")
    for i, part in enumerate(p[:-1]):
        if part == "lumps" and i + 2 < len(p):
            return p[i + 1]
        if part == "svml" and i + 2 < len(p):
            return p[i + 1]
    return "common"


def text_of_core(data):
    c = core.Core(data, None)
    for name, items in c.groups.items():
        for s in items:
            if name == "WString":
                yield s
            else:
                try:
                    yield s.encode("latin-1").decode("utf-8")
                except UnicodeDecodeError:
                    pass                            # not UTF-8: a Filename or binary key, no display text


def scan(a):
    if zipfile.is_zipfile(a.source):
        st = ZipIsoStream(a.source); st.find_psarc()
    else:
        st = FileStream(a.source)
    ents, names, read = psarc_entries(st)
    patches = {}
    if a.patches:
        for fn in os.listdir(a.patches):
            if fn.endswith(".pspatch"):
                patches[fn.upper()] = os.path.join(a.patches, fn)
    counts, stats = {}, {"jsp": 0, "core": 0, "core_fail": 0, "patched": 0, "other": 0}
    order = sorted(range(1, len(ents)), key=lambda i: ents[i][2])
    for i in order:
        path = names[i] if i < len(names) else ""
        low = path.lower()
        if not (low.endswith(".jsp") or low.endswith(".core")):
            stats["other"] += 1; continue
        datas = [read(i)]
        pp = patches.get(pspatch.patch_name(path).upper())
        if pp:                                      # both versions: the union is the set either can show
            try:
                datas.append(pspatch.apply(open(pp, "rb").read(), datas[0])); stats["patched"] += 1
            except pspatch.PatchError:              # a patch for the disc's file of that name (an update archive)
                stats["patch_other"] = stats.get("patch_other", 0) + 1
        texts = []
        for data in datas:
            if low.endswith(".jsp"):
                stats["jsp"] += 1
                for enc in ("utf-8", "utf-16"):
                    try:
                        texts.append(data.decode(enc)); break
                    except UnicodeDecodeError:
                        pass
            else:
                stats["core"] += 1
                try:
                    texts.extend(text_of_core(data))
                except Exception as ex:             # core.DecodeError and short reads: count, keep going
                    stats["core_fail"] += 1
                    stats.setdefault("fail_paths", []).append(f"{path}: {str(ex)[:80]}")
        b = counts.setdefault(bucket(path), {})
        for t in texts:
            for ch in t:
                o = ord(ch)
                if o > 0x7F:
                    b[o] = b.get(o, 0) + 1
    out = {"name": a.name or os.path.basename(a.source), "stats": stats,
           "buckets": {k: {"%04X" % o: n for o, n in sorted(v.items())} for k, v in sorted(counts.items())}}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=0)
    allc = set().union(*[set(v) for v in counts.values()]) if counts else set()
    if isinstance(st, ZipIsoStream):
        stats["reopens"] = st.reopens
    print(f"{out['name']}: {stats}; {len(allc)} code points above U+007F in {len(counts)} buckets", flush=True)


def font_cmap(path):
    """Code points a TrueType file maps (format 4 and 12 subtables), stdlib only."""
    d = open(path, "rb").read()
    n = struct.unpack(">H", d[4:6])[0]
    off = next(struct.unpack(">I", d[12 + 16 * i + 8:12 + 16 * i + 12])[0]
               for i in range(n) if d[12 + 16 * i:16 + 16 * i] == b"cmap")
    cps = set()
    for k in range(struct.unpack(">H", d[off + 2:off + 4])[0]):
        sub = off + struct.unpack(">I", d[off + 4 + 8 * k + 4:off + 4 + 8 * k + 8])[0]
        fmt = struct.unpack(">H", d[sub:sub + 2])[0]
        if fmt == 4:
            segx2 = struct.unpack(">H", d[sub + 6:sub + 8])[0]
            ends, starts = sub + 14, sub + 16 + segx2
            delt, ro = starts + segx2, starts + 2 * segx2
            for s in range(segx2 // 2):
                e, b = struct.unpack(">H", d[ends + 2 * s:ends + 2 * s + 2])[0], struct.unpack(">H", d[starts + 2 * s:starts + 2 * s + 2])[0]
                dl, r = struct.unpack(">h", d[delt + 2 * s:delt + 2 * s + 2])[0], struct.unpack(">H", d[ro + 2 * s:ro + 2 * s + 2])[0]
                for c in range(b, e + 1):
                    if c == 0xFFFF:
                        continue
                    if r == 0:
                        g = (c + dl) & 0xFFFF
                    else:
                        ga = ro + 2 * s + r + 2 * (c - b)
                        g = struct.unpack(">H", d[ga:ga + 2])[0]
                        g = (g + dl) & 0xFFFF if g else 0
                    if g:
                        cps.add(c)
        elif fmt == 12:
            ng = struct.unpack(">I", d[sub + 12:sub + 16])[0]
            for j in range(ng):
                s0, e0, g0 = struct.unpack(">III", d[sub + 16 + 12 * j:sub + 28 + 12 * j])
                cps.update(c for c, g in zip(range(s0, e0 + 1), range(g0, g0 + e0 - s0 + 1)) if g)
    return cps


def ranges(cps):
    out, run = [], None
    for c in sorted(cps):
        if run and c == run[1] + 1:
            run[1] = c
        else:
            if run:
                out.append(run)
            run = [c, c]
    if run:
        out.append(run)
    return out


def merge(a):
    allc = set()
    for p in a.scans:
        for v in json.load(open(p))["buckets"].values():
            allc.update(int(k, 16) for k in v)
    allc -= set(range(0x80, 0xA0))                  # C1 controls (cp1252 quotes stored as Latin-1 in UTF-8): not drawn
    for m in a.margin or []:                        # extra ranges kept whether or not the text uses them
        lo, _, hi = m.partition("-")
        allc.update(range(int(lo, 16), int(hi or lo, 16) + 1))
    if a.exclude_font:
        allc -= font_cmap(a.exclude_font)
    rs = ranges(allc)
    with open(a.out, "w") as f:
        f.write("# Code points patch 6061's CJK face keeps (tools/runtime/cjk_codepoints.py merge; numbers only).\n")
        for s, e in rs:
            f.write("%04X\n" % s if s == e else "%04X-%04X\n" % (s, e))
    print(f"{len(allc)} code points, {len(rs)} ranges -> {a.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scan"); s.add_argument("source"); s.add_argument("--patches"); s.add_argument("--name")
    s.add_argument("--out", required=True)
    m = sp.add_parser("merge"); m.add_argument("scans", nargs="+"); m.add_argument("--exclude-font")
    m.add_argument("--margin", action="append", help="HEX-HEX range to keep in any case (repeatable)")
    m.add_argument("--out", required=True)
    a = ap.parse_args()
    scan(a) if a.cmd == "scan" else merge(a)


if __name__ == "__main__":
    main()
