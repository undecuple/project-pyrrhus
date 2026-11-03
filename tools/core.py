#!/usr/bin/env python3
"""Decode Killzone 3 `.core` files (RTTIBin<1.73>) and Killzone 2 files (RTTIBin<1.58>:
32-byte object entries, token tail F/G, opaque tail classes, Lua chunks) with the engine's RTTI schema.

    core.py FILE.core [--schema RTTI.json] [--header] [--max-objects N]   decode one file, exit 1 if it stops early,
                                                                            an object's length differs or bytes are left
    core.py --all DIR [-j N]                                                 decode every .core below DIR, print pass/fail
                                                                            per file kind and the failure causes, exit 1
                                                                            if any file fails
    # schema: `tools/rtti_dump.py work/bin/EBOOT.elf --json work/re-data/rtti.json` (default path)

Layout (big-endian). Evidence and open points: the RE notes. ASSUMPTION marks guesses.

  0x00  "RTTIBin<1.73>  " (15 bytes), u8 0x01, then 16 header bytes (counts/flags, not needed)
  0x20  type table: size-coded count, count x (u8 len, name)
  then  object list: size-coded n, n x u8 type index, size-coded m, n x (16-byte hash, u32 stored data length;
        hash and length are 0 for some objects), then size-coded count + that many units (skipped)
  then  string groups: count, each: u8 type index (String/Filename/WString), count, count x (size, len, data);
        size covers the length field + the characters, len is one byte (0xfe + u16 for 255+, 0xff + u32);
        WString = UTF-16BE
  then  allocation table: m, n, n x token;  token = size, align, 81 00 ff ff, owner   (sizes are size-coded)
  then, per object: list A (count, tokens: arrays the object owns), list B (count, tokens; empty except Texture and
        a few binary classes, whose payload follows directly), then the fields (below)

  size-coding: byte < 0x80 is the value, 0x80 = u32 follows, 0x81 = u16 follows (others ASSUMPTION k+1 bytes).

  Fields: the members of the serialised class chain (Schema.primary: first base + bases at a small non-zero offset),
  bases first, in member-list order. Only 0x2 members are left out (but see raw arrays); 0x1 and 0x100 are serialised.
    float/int/uint32/...     raw big-endian         bool/uint8  1 byte         enum  4 bytes
    String/Filename/WString  index into the group: u8 if the group has <= 255 entries, else u16
    T[]                      size-coded count, elements back to back
    T* / T^                  flag u8 (0 = internal: index+1 with the same u8/u16 rule over the objects, 0 = null;
                             2 = external: size-coded length + 32 hex digits of the target's hash)
    struct                   its members in order
    0x2 arrays of plain data raw bytes sized by the object's next array allocation (uint8[]: u32 length first)
    Pose                     Skeleton ref, u8 flag, u32 n, n*48, n*64 bytes, u32 m, m*4 bytes
  Classes with a MsgReadBinary base (Texture, Shader/IndexArray/VertexArray resources, ...) and SoundBank,
  PhysicsResource descendants (Havok), AIWaypointGrid, GameScript (Lua bytecode), Music/ControlledSound resources keep the rest of the object as
  an opaque blob (stored length minus fields). Objects without a stored length are checked by the next object's header.
"""
import argparse, hashlib, json, os, struct, sys


class DecodeError(Exception):
    pass


class Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def u8(self):
        if self.p >= len(self.d):
            raise DecodeError(f"read past end at {self.p:#x}")
        v = self.d[self.p]
        self.p += 1
        return v

    def raw(self, n):
        if self.p + n > len(self.d):
            raise DecodeError(f"read past end at {self.p:#x}")
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def size(self):
        b = self.u8()
        if b < 0x80:
            return b
        if b == 0x80:  # u32 (seen: array sizes of textures, e.g. 80 00 02 65 d0)
            return int.from_bytes(self.raw(4), "big")
        return int.from_bytes(self.raw((b & 0x7F) + 1), "big")  # 0x81 = u16; ASSUMPTION for 0x82..

    def strlen(self):
        """Character count of a string table entry: one byte, 0xfe + u16 (seen: fe 01 3e = 318), ASSUMPTION 0xff + u32."""
        b = self.u8()
        if b == 0xFE:
            return int.from_bytes(self.raw(2), "big")
        if b == 0xFF:
            return int.from_bytes(self.raw(4), "big")
        return b

    def unpack(self, fmt):
        n = struct.calcsize(fmt)
        return struct.unpack(fmt, self.raw(n))[0]


class Schema:
    def __init__(self, path):
        j = json.load(open(path))
        self.classes = {c["name"]: c for c in j["classes"]}
        self.types = j.get("types", {})
        self._chain, self._fields = {}, {}

    def chain(self, name):
        if name not in self._chain:
            self._chain[name] = self._chain_walk(name)
        return self._chain[name]

    def _chain_walk(self, name, seen=None, visiting=None):
        seen = seen if seen is not None else []
        visiting = visiting if visiting is not None else set()
        visiting.add(name)  # the base graph of a few classes has cycles
        c = self.classes[name]
        for b in c["bases"]:
            if b in self.classes and b not in seen and b not in visiting:
                self._chain_walk(b, seen, visiting)
        if name not in seen:
            seen.append(name)
        return seen

    def primary(self, name, seen=None):
        """Serialised class chain, bases first. A class's first base is always serialised; a further base only if
        its base-list word is a small non-zero subobject offset (GeometryObject: WorldNode + DrawableObjectInstance at
        0x50). Entity resources list the run-time instance classes (CameraEntityRep, ControlledEntity, ...) as
        offset-0 or pointer-word bases and those members are not in the stream (FirstPersonCameraEntityResource:
        CullInfo absent, verified by the stored length)."""
        seen = seen if seen is not None else []
        c = self.classes.get(name)
        if c is None or name in seen:
            return seen
        words = {b: w for b, w in c.get("base_words", [])}
        for i, b in enumerate(c["bases"]):
            if b in self.classes and (i == 0 or 0 < words.get(b, 0) < 0x1000):
                self.primary(b, seen)
        if name not in seen:
            seen.append(name)
        return seen

    def fields(self, name):
        if name not in self._fields:
            self._fields[name] = [(k, m) for k in self.primary(name) for m in self.classes[k]["members"]]
        return self._fields[name]


PRIMS = {  # name -> struct format
    "float": ">f", "double": ">d", "int": ">i", "int32": ">i", "uint": ">I", "uint32": ">I",
    "int16": ">h", "uint16": ">H", "int8": ">b", "uint8": ">B", "bool": ">B", "uint64": ">Q",
    "wchar": ">H", "HalfFloat": ">H", "MaterialType": ">H", "RenderDataPriority": ">H",
}
STRINGS = ("String", "Filename", "WString")
# classes whose MsgReadBinary handler appends data after the reflected fields (g2.py scan of the class records)
CUSTOM_TAIL = {"SimpleSoundResource": 12}
# member flag bits (low 16 bits of the RTTI offset word): 0x1 = serialized as usual (SoundResource sample data);
# 0x2 and 0x100 = not in the stream (MenuStyle.Selector 0x2; DependentConcreteAsset.IncludeAssets 0x102).
# ASSUMPTION: the meaning of 0x4 / 0x10 and of 0x100 alone (113 members) is unverified.
SKIP_FLAGS = 0x2
# members that the stream omits although the RTTI lists them (found by byte counting; ASSUMPTION: cause unknown)
NOT_SERIALIZED = set()
# classes with a custom payload that is kept opaque (MsgReadBinary base class: IndexArrayResource, ShaderResource,
# ShaderFromFileResource, Texture, VertexArrayResource, LightingManager; plus the two mesh instances whose handler
# is registered in the class record instead)
# the type table names the base class but the stream holds the "NG" variant (extra members, verified on 2,250 skinned
# meshes: SkinInfo ref, Primitives[], RenderFxResources[], PositionBoundsScale/Offset)
TYPE_ALIAS = {"RegularSkinnedMeshResource": "RegularSkinnedMeshResourceNG"}
# RTTIBin<1.58> only: classes whose tail after the reflected fields is kept as a blob (layouts: the RE notes)
OPAQUE_158 = ("SimpleSoundResource", "Skeleton", "RenderingPrimitiveResource", "ShaderResource", "Texture", "AIHTNPlannerResource",
              "CoreScript", "ShaderFromFileResource", "MapResource", "Font")
OPAQUE_TAIL = ("SoundBankResource", "PhysicsCollisionResource", "GameScript", "MusicResource", "ControlledSoundResource", "AIWaypointGrid")


LEARN158 = None


def lua51_chunk_len(d, p):
    """Length of the precompiled Lua 5.1 chunk at d[p:] (header 1b 'Lua' 51 00, big-endian, int/size_t/Instruction/
    number sizes taken from the header: KZ2 has 4/4/4/4). Used for CoreScript/GameScript objects without a stored
    length. Raises DecodeError when the chunk does not parse."""
    if d[p:p + 5] != b"\x1bLuaQ":
        raise DecodeError("no Lua 5.1 chunk")
    big = d[p + 6] == 0
    isz, szt, ins, num = d[p + 7], d[p + 8], d[p + 9], d[p + 10]
    q = p + 12
    bo = "big" if big else "little"

    def get(n):
        nonlocal q
        if q + n > len(d):
            raise DecodeError("Lua chunk past end")
        v = d[q:q + n]
        q += n
        return v

    def integer(n):
        return int.from_bytes(get(n), bo)

    def string():
        n = integer(szt)
        if n:
            get(n)

    def func():
        string()
        get(2 * isz + 4)  # linedefined, lastlinedefined, nups, numparams, is_vararg, maxstack
        get(integer(isz) * ins)
        for _ in range(integer(isz)):
            k = get(1)[0]
            if k == 1:
                get(1)
            elif k == 3:
                get(num)
            elif k == 4:
                string()
            elif k != 0:
                raise DecodeError(f"Lua constant type {k}")
        for _ in range(integer(isz)):
            func()
        get(integer(isz) * isz)  # line info
        for _ in range(integer(isz)):
            string()
            get(2 * isz)
        for _ in range(integer(isz)):
            string()

    func()
    return q - p


# ---- RTTIBin<1.58> payload checks (Texture, Vertex/IndexArrayResource, ShaderResource, ES00, EA02) --------------------
# Layouts from the format notes of Killzone2_Blender by Tzeentchnet (MIT, github.com/Tzeentchnet/Killzone2_Blender,
# docs v0.5.3), written here independently and re-checked on every unique core of data_ps3.psarc (1,249 decoded, all
# payloads below matched; numbers in the RE notes "Killzone2_Blender cross-check"). They turn the
# vacuous "stored length minus fields" opaque check into a real one: a payload that does not fit its own header
# raises DecodeError. The disc has no .corestream files: every Texture holds its whole payload.

def _enum_num(s):
    """'S3TC1 (19)' -> 19 (enum fields decode to 'Name (value)')."""
    return int(s[s.rindex("(") + 1:-1])


def _align(x, a):
    return (x + a - 1) // a * a


_TEX_RSX = {5: (0x85, 0xA5), 6: (0x85,), 19: (0x86,), 20: (0x87,), 21: (0x88,), 31: (0x9A,)}  # pixel format -> RSX format byte(s)


def _tex_level_bytes(pf, w, h):
    if pf == 19:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    if pf in (20, 21):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    if pf in (5, 6):
        return w * h * 4
    if pf == 31:
        return w * h * 8
    return None


def check_texture(blob, F):
    """Texture payload after the reflected fields: u32 allocation size (= payload + 128), u32 0x01050000, u32 payload
    size, four state words (1, 0, 128, end of the logical data), 24-byte RSX descriptor (format, mips, dimension 2,
    cube flag, ARGB remap, u16 width, height, depth 1, location 0, pad 0, u32 pitch, u32 offset 0), 80 bytes 0x50, then
    the pixels: faces x align128(sum of mip sizes), largest mip first. Returns the layout; raises DecodeError."""
    sf = F["Format"]
    w, h, pf = sf["Width"], sf["Height"], _enum_num(sf["PixelFormat"])
    typ, mips, cf = _enum_num(F["Type"]), F["NumSurfaces"], _enum_num(F["CreationFlags"])
    if len(blob) < 132:
        raise DecodeError(f"Texture payload {len(blob)} bytes, header needs 132")
    alloc, const, payload = struct.unpack(">III", blob[:12])
    st = struct.unpack(">IIII", blob[12:28])
    rsx = blob[28:52]
    faces = 6 if typ == 2 else 1
    if const != 0x01050000 or alloc != payload + 128 or st[:3] != (1, 0, 128):
        raise DecodeError("Texture header words (alloc/0x01050000/state) do not match")
    if (rsx[1], rsx[2], rsx[3]) != (mips, 2, 1 if typ == 2 else 0) or struct.unpack(">HHH", rsx[8:14]) != (w, h, 1) \
            or rsx[14:16] != bytes(2) or rsx[20:24] != bytes(4):
        raise DecodeError("Texture RSX descriptor disagrees with the reflected fields")
    if pf in _TEX_RSX and rsx[0] not in _TEX_RSX[pf]:
        raise DecodeError(f"Texture pixel format {pf} with RSX format {rsx[0]:#x}")
    if blob[52:132] != b"\x50" * 80:
        raise DecodeError("Texture fill bytes are not 0x50")
    if len(blob) - 132 != payload:
        raise DecodeError(f"Texture payload {len(blob) - 132} bytes, header says {payload}")
    lvl = [_tex_level_bytes(pf, max(1, w >> i), max(1, h >> i)) for i in range(mips)]
    if None not in lvl and not (cf == 3 and pf == 5):  # dynamic RGBA8 is linear, one level, no formula
        face = _align(sum(lvl), 128)
        if payload != face * faces or st[3] not in (payload, face * (faces - 1) + sum(lvl)):
            raise DecodeError(f"Texture payload {payload} != {faces} x align128({sum(lvl)})")
    return dict(payload=payload, faces=faces, rsx_format=rsx[0], remap=rsx[4:8].hex(), pitch=struct.unpack(">I", rsx[16:20])[0])


def check_vertex_array(blob, start):
    """VertexArrayResource payload: align 4 (file offset `start`), i32 vertex count, i32 (= vertex count on the disc),
    i32 stream count, per stream (i32 flags, i32 stride, i32 declaration count, 8-byte declarations: u32 semantic,
    u8 offset, u8 storage, u8 components, u8 0), then per stream align 4 + count x stride bytes. Ends exactly at the
    payload end. Semantic/storage codes are Killzone2_Blender's names (not decoded here)."""
    p = (-start) % 4
    try:
        vc, dup, sc = struct.unpack(">iii", blob[p:p + 12])
        p += 12
        streams = []
        for _ in range(sc):
            fl, stride, nd = struct.unpack(">iii", blob[p:p + 12])
            p += 12
            decls = [struct.unpack(">IBBBB", blob[p + 8 * k:p + 8 * k + 8]) for k in range(nd)]
            p += 8 * nd
            streams.append((fl, stride, decls))
    except struct.error:
        raise DecodeError("VertexArrayResource header runs past the payload")
    if vc < 0 or not 0 <= sc <= 64:
        raise DecodeError("VertexArrayResource counts out of range")
    for fl, stride, decls in streams:
        p = _align(p + start, 4) - start + vc * stride
    if p != len(blob):
        raise DecodeError(f"VertexArrayResource streams end at {p}, payload is {len(blob)} bytes")
    return dict(vertices=vc, vertices2=dup, streams=streams)


def check_index_array(blob, start):
    """IndexArrayResource payload: align 4, i32 index count, 8 bytes (always 00000001 00000002 on the disc), count u16
    indices, zero padding to a 4-byte boundary of the file."""
    p = (-start) % 4
    try:
        n, = struct.unpack(">i", blob[p:p + 4])
    except struct.error:
        raise DecodeError("IndexArrayResource header runs past the payload")
    end = p + 12 + 2 * n
    if n < 0 or end > len(blob) or _align(start + end, 4) - start != len(blob) or any(blob[end:]):
        raise DecodeError(f"IndexArrayResource: {n} indices do not fit the {len(blob)}-byte payload")
    return dict(indices=n, header=blob[p + 4:p + 12].hex())


def check_shader(blob):
    """ShaderResource payload after IBLRequirements: u32 size, then the compiled object, whose bytes 8..11 are 'SHO\\x08'."""
    if len(blob) < 16 or struct.unpack(">I", blob[:4])[0] != len(blob) - 4 or blob[12:16] != b"SHO\x08":
        raise DecodeError("ShaderResource payload is not size + SHO object")
    return dict(size=len(blob) - 4)


def check_es00(es):
    """Skeleton.EdgeAnimSkeleton ('ES00'): u32 magic, u32 unknown, u32 total size (= length), u16 joints, u16 user
    channels, u16, u16, six self-relative u32 offsets; fallback pose at +0x14 (48 bytes per joint, unit quaternion
    first), parent u16 per joint at +0x18 (0xFFFF = root, parents come before children on the disc)."""
    if not es:
        return None
    if es[:4] != b"ES00" or len(es) < 0x2C or struct.unpack(">I", es[8:12])[0] != len(es):
        raise DecodeError("EdgeAnimSkeleton is not an ES00 blob of its own length")
    nj = struct.unpack(">H", es[12:14])[0]
    offs = struct.unpack(">6I", es[0x14:0x2C])
    for k, v in enumerate(offs):
        if v and 0x14 + 4 * k + v > len(es):
            raise DecodeError(f"ES00 offset {k} points past the blob")
    pose, par = 0x14 + offs[0], 0x18 + offs[1]
    if pose + 48 * nj > len(es) or par + 2 * nj > len(es):
        raise DecodeError("ES00 pose/parent arrays run past the blob")
    parents = struct.unpack(f">{nj}H", es[par:par + 2 * nj])
    if any(p != 0xFFFF and p >= j for j, p in enumerate(parents)):
        raise DecodeError("ES00 parent index does not precede its child")
    return dict(joints=nj, parents=parents)


def check_ea02(ea, duration):
    """SkeletonAnimationResource.EdgeAnimAnimation ('EA02'): f32 duration (= the reflected Duration), f32 sample
    frequency (= (frames - 1) / duration), u16 header size, joints, frames, frame sets, evaluation size, 8 u16 channel
    counts, u16 flags at 0x26 (0 for all 53,315 clips on the disc), self-relative offsets from 0x34. The frame-set
    info table (u16 base frame, u16 intra frames) is increasing and ends with a sentinel at frames - 1."""
    if len(ea) < 0x54 or ea[:4] != b"EA02":
        raise DecodeError("EdgeAnimAnimation is not an EA02 clip")
    dur, freq = struct.unpack(">ff", ea[4:12])
    hs, nj, nf, nfs = struct.unpack(">HHHH", ea[12:20])
    flags, = struct.unpack(">H", ea[0x26:0x28])
    if abs(dur - duration) > 1e-4 * max(1.0, dur):
        raise DecodeError(f"EA02 duration {dur} != reflected Duration {duration}")
    if dur > 0 and nf > 1 and abs(freq - (nf - 1) / dur) > 1e-3 * max(1.0, freq):
        raise DecodeError("EA02 sample frequency != (frames - 1) / duration")
    info = 0x38 + struct.unpack(">I", ea[0x38:0x3C])[0]
    if nfs < 1 or info + 4 * nfs > len(ea):
        raise DecodeError("EA02 frame-set table out of range")
    bases = [struct.unpack(">H", ea[info + 4 * k:info + 4 * k + 2])[0] for k in range(nfs)]
    if bases != sorted(set(bases)) or bases[-1] != nf - 1:
        raise DecodeError("EA02 frame-set base frames are not increasing up to the sentinel")
    return dict(joints=nj, frames=nf, framesets=nfs, flags=flags, header=hs)


def object_id_display(h):
    """The form in which an external reference names an object: the 16-byte object id from the object list with each
    4-byte group reversed (32 lower-case hex digits). 906 of 906 external references of the Blood Meridian cores
    resolve to an object id of some core this way; none matches the plain hex. The function is its own inverse."""
    b = bytes.fromhex(h)
    return b"".join(b[i:i + 4][::-1] for i in range(0, 16, 4)).hex()


def walk_refs(v, path=""):
    """Yield (path, ref dict) for every object reference inside a decoded field value (nested structs and arrays)."""
    if isinstance(v, dict):
        if "ref" in v and "flag" in v:
            yield path, v
            return
        for k, x in v.items():
            yield from walk_refs(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from walk_refs(x, f"{path}[{i}]")


class CoreIndex:
    """Cross-core resolver. Indexes the object ids in the headers of many .core files (no field decode) and
    resolves external references (`ref == "external"`, 32 hex digits = object id with each 4-byte group reversed, see
    object_id_display) to (file, object index, class). A reference names its target only by id: the file name is not
    stored, so the index must contain the candidate files (a lump, or the whole disc). An id found in several files
    (the same object copied into more than one lump) yields every match in the order the files were added.
    resolve_core() decodes the referencing core's fields and resolves each external reference it holds."""

    def __init__(self, schema):
        self.s = schema
        self.by_ref = {}   # ref-form id -> [(path, object index, class)]
        self.paths = []
        self.copies = {}   # path of an indexed file -> paths of byte-identical files that were skipped (Lumps/lumps)
        self._seen = {}    # sha1 of the file bytes -> path

    def add(self, path, data):
        c = Core(data, self.s)
        key = hashlib.sha1(data).digest()
        if key in self._seen:  # the disc lists some lumps twice with different case: index the bytes once
            self.copies.setdefault(self._seen[key], []).append(path)
            return c
        self._seen[key] = path
        self.paths.append(path)
        for i, (h, _) in enumerate(c.hashes):
            if h == "00" * 16:  # no id stored (objects of old-format cores)
                continue
            self.by_ref.setdefault(object_id_display(h), []).append((path, i, c.types[c.roots[i]]))
        return c

    def add_dir(self, root, ext=".core"):
        n = 0
        for dp, _, fs in os.walk(root):
            for f in sorted(fs):
                if f.lower().endswith(ext):
                    p = os.path.join(dp, f)
                    try:
                        self.add(p, open(p, "rb").read())
                        n += 1
                    except DecodeError:
                        pass  # header not readable: file not indexed
        return n

    def resolve(self, ref):
        """ref: the 32-digit hash of an external reference. Returns the list of (path, index, class), empty if unknown."""
        return list(self.by_ref.get(ref.lower(), []))

    def resolve_core(self, core):
        """core: a Core with decoded objects. Returns a list of dicts (object, field path, hash, targets), one per
        external reference; internal references (ref = object number) are not listed."""
        out = []
        for o in core.objects:
            for owner, name, _t, _pos, v in o["fields"]:
                for p, r in walk_refs(v, f"{owner}.{name}"):
                    if r["ref"] == "external":
                        out.append(dict(object=o["index"], field=p, hash=r["hash"], targets=self.resolve(r["hash"])))
        return out


class Core:
    def __init__(self, data, schema):
        self.s, self.r = schema, Reader(data)
        r = self.r
        magic = r.raw(13)
        if magic not in (b"RTTIBin<1.73>", b"RTTIBin<1.58>"):
            raise DecodeError("not an RTTIBin<1.73> or <1.58> file")
        self.v158 = magic == b"RTTIBin<1.58>"  # Killzone 2: object list entries are 32 bytes, no count m before them
        r.raw(3)
        self.hdr = r.raw(0x20 - 16)
        # header u16 at 0x1e: 0x0080 = "wide" file: String/Filename/WString indices and object references in the
        # object fields are fixed u16 (not size-coded). Seen on the 342-object / 311-string basemenu_styles file.
        self.wide = bool(struct.unpack(">H", self.hdr[-2:])[0] & 0x80)
        r.p = 0x20
        self.types = [r.raw(r.u8()).decode("ascii") for _ in range(r.size())]
        n = r.size()
        tw = (lambda: r.unpack(">H")) if len(self.types) > 256 else r.u8  # type indices are u16 with more than 256 types (257 seen)
        self.roots = [tw() for _ in range(n)]
        if self.v158:
            # <1.58>: no count m; per object hash16, u32 stored length, 12 more bytes (zero in every sample so far)
            self.nhash = None
            self.hashes = []
            for _ in range(n):
                h, ln = r.raw(16).hex(), r.unpack(">I")
                if any(r.raw(12)):
                    raise DecodeError(f"nonzero tail in <1.58> object entry at {r.p - 12:#x}")
                self.hashes.append((h, ln))
        else:
            self.nhash = r.size()  # equals the number of entries whose hash is not all zero (not always: see notes)
            self.hashes = [(r.raw(16).hex(), r.unpack(">I")) for _ in range(n)]
        self.units = [self.token() for _ in range(r.size())]
        self.groups = {}
        for _ in range(r.size()):
            ti, cnt = tw(), r.size()
            name = self.types[ti]
            items = []
            for _ in range(cnt):
                sz = r.size()
                start = r.p
                ln = r.strlen()
                raw = r.raw(sz - (r.p - start))  # size covers the length field plus the characters
                items.append(raw.decode("utf-16-be") if name == "WString" else raw.decode("latin-1"))
            self.groups[name] = items
        self.nhash2 = r.size()  # equals the first count after the object list (m); differs from nobj when hashes are 0
        nobj = r.size()
        if nobj != len(self.roots):
            raise DecodeError(f"allocation table has {nobj} entries for {len(self.roots)} objects")
        self.objtab = [self.token() for _ in range(nobj)]
        self.objects = []
        self.stream_pos = 0

    def token(self):
        """size, alignment (size-coded; 0x10 usually, 0x81 0x00 0x80 = 128 for some arrays), the 4 constant bytes
        81 00 ff ff, owner index (size encoding; a single 0xff = none, used by units)."""
        sz = self.r.size()
        align = self.r.size()
        if self.v158:
            # <1.58>: the four constant bytes are really F (size-coded; 81 00 ff = 255 means "not streamed", then one
            # byte 0xff) or F = 0 / 128 followed by a size-coded .corestream offset (80 + u32 seen on VertexArray
            # and Texture B-list tokens). ASSUMPTION: the meaning of F beyond that is unknown.
            f = self.r.size()
            if f == 0xFF:
                if self.r.u8() != 0xFF:
                    raise DecodeError(f"unexpected token bytes at {self.r.p - 1:#x}")
            else:
                self.last_stream = self.r.size()
            fixed = b"\x81\x00\xff\xff"
        else:
            fixed = self.r.raw(4)
        if fixed != bytes.fromhex("8100ffff"):
            raise DecodeError(f"unexpected token bytes {fixed.hex()} at {self.r.p - 4:#x}")
        if self.r.d[self.r.p] == 0xFF:
            self.r.p += 1
            return sz, None
        return sz, self.r.size()

    def decode(self, max_objects=None):
        for i in range(len(self.roots)):
            if max_objects is not None and i >= max_objects:
                break
            self.decode_object(i)
        return self.objects

    def decode_object(self, i, trial=False):
        r = self.r
        cls_idx = self.roots[i]
        cname = TYPE_ALIAS.get(self.types[cls_idx], self.types[cls_idx])
        allocs = [self.token() for _ in range(r.size())]       # list A: arrays inside the object
        allocs_b = [self.token() for _ in range(r.size())]     # list B: empty (the old "marker" 0x00) except
        #                                                         for Texture/VertexArray-like binary payloads
        obj = dict(index=i, cls=cname, size=self.objtab[i][0], allocs=allocs, allocs_b=allocs_b, fields=[], start=r.p)
        self.objects.append(obj)
        self.cur_allocs, self.alloc_i = allocs, 0
        custom = cname in CUSTOM_TAIL and not self.v158
        unknown = self.v158 and cname not in self.s.classes  # type name without an RTTI class record (LightingSetupSet)
        opaque = unknown or not custom and (cname in OPAQUE_TAIL or (self.v158 and cname in OPAQUE_158) or "MsgReadBinary" in self.s.chain(cname) or "PhysicsResource" in self.s.chain(cname))
        if not unknown:
            self.decode_fields(cname, obj["fields"])
        if custom:  # exact class only: SoundCollection (derived) has none
            obj["tail"] = [r.unpack(">I") for _ in range(CUSTOM_TAIL[cname] // 4)]
        if (self.v158 and not opaque and self.hashes[i][1] > r.p - obj["start"] and LEARN158 is not None
                and cname not in OPAQUE_158):
            LEARN158.add(cname)  # exploration only: which classes carry an undecoded tail in 1.58
            opaque = True
        if opaque:
            # custom MsgReadBinary payload, format not decoded: keep it as a blob. Its length is the stored
            # per-object length minus the reflected fields, so the byte-count check is vacuous for these objects.
            want = self.hashes[i][1]
            if want == 0 and self.v158 and cname in ("CoreScript", "GameScript"):
                # no stored length: source text, then a precompiled Lua 5.1 chunk, whose length is parsed
                q = bytes(self.r.d).find(b"\x1bLuaQ", r.p, r.p + 70000)
                if q < 0:
                    raise DecodeError(f"{cname}: no Lua chunk found")
                want = self.script_end(q + lua51_chunk_len(self.r.d, q), i, trial) - obj["start"]
            if want == 0:
                # no stored length (all-zero hash entry): find where the next object's header starts
                nxt = self.find_header(r.p, i + 1)
                if nxt is None:
                    nxt = self.lookahead_end(r.p, i)
                if nxt is None:
                    raise DecodeError(f"{cname}: opaque tail, no stored length and no next header found")
                want = nxt - obj["start"]
            if want < r.p - obj["start"]:
                raise DecodeError(f"{cname}: opaque tail but stored length {want} unusable")
            obj["opaque"] = want - (r.p - obj["start"])
            obj["blob"] = r.raw(obj["opaque"])
        obj["end"] = r.p
        if self.v158:
            self.check_payload_158(obj, cname)
        if cname == "Texture" and "blob" in obj and len(obj["blob"]) >= 17 and not self.v158:
            # streamed top mips: u32 data size at blob[9:13] counts the whole mip chain, the list-B token only the
            # part stored in the .core; the rest is in the .corestream, back to back in object order
            full = struct.unpack(">I", obj["blob"][9:13])[0]
            inline = sum(t[0] for t in obj["allocs_b"])
            if full > inline:
                obj["stream"] = (self.stream_pos, full - inline)
                self.stream_pos += full - inline
        if custom and "tail" in obj:
            obj["stream"] = (obj["tail"][0], obj["tail"][1])  # SimpleSoundResource: offset, size, 0 (XVAG at offset)
        if self.hashes[i][1]:
            obj["size_ok"] = (r.p - obj["start"]) == self.hashes[i][1]
        else:  # no stored length: the next object's header must start here (its tokens name object i+1 as owner)
            obj["size_ok"] = self.next_header_ok(r.p, i + 1)

    def check_payload_158(self, obj, cname):
        """Validate the opaque payloads whose layout is known (check_* above); the result goes to obj[...]. A payload
        that does not fit its own header is a DecodeError, so the stored-length check is no longer vacuous for them."""
        F = {n: v for _, n, _, _, v in obj["fields"]}
        blob = obj.get("blob")
        start = obj["end"] - len(blob) if blob is not None else 0
        if cname == "Texture" and blob is not None:
            obj["texture"] = check_texture(blob, F)
        elif cname == "VertexArrayResource" and blob is not None:
            obj["vertex_array"] = check_vertex_array(blob, start)
        elif cname == "IndexArrayResource" and blob is not None:
            obj["index_array"] = check_index_array(blob, start)
        elif cname == "ShaderResource" and blob is not None:
            obj["shader"] = check_shader(blob)
        elif cname == "Skeleton" and "EdgeAnimSkeleton" in F:
            obj["es00"] = check_es00(bytes(F["EdgeAnimSkeleton"]))
        elif cname == "SkeletonAnimationResource" and "EdgeAnimAnimation" in F:
            obj["ea02"] = check_ea02(bytes(F["EdgeAnimAnimation"]), F["Duration"])

    def script_end(self, e, i, trial):
        """End of a CoreScript/GameScript object whose Lua chunk ends at e: 2 or 3 zero bytes follow it (not
        understood; ASSUMPTION: padding). Pick the count for which the next object decodes to its stored length."""
        if trial or i + 1 >= len(self.roots) or not self.hashes[i + 1][1]:
            return e + 2
        for k in (2, 3, 4, 1, 0):
            save, n, sp = self.r.p, len(self.objects), self.stream_pos
            self.r.p = e + k
            try:
                self.decode_object(i + 1, trial=True)
                ok = self.objects[-1].get("size_ok")
            except Exception:
                ok = False
            finally:
                del self.objects[n:]
                self.r.p, self.stream_pos = save, sp
            if ok:
                return e + k
        return e + 2

    def next_header_ok(self, p, nxt):
        """True if a valid object header with owner `nxt` (or an empty allocation list) starts at p, or the file ends."""
        if nxt >= len(self.roots):
            return p == len(self.r.d)
        save = self.r.p
        try:
            self.r.p = p
            k = self.r.size()
            toks = [self.token() for _ in range(k)]
            return all(t[1] == nxt for t in toks)
        except DecodeError:
            return False
        finally:
            self.r.p = save

    def find_header(self, p, nxt, limit=4096):
        """Offset of the next object's header at or after p: count + tokens whose owner is object `nxt`
        (used when an object has no stored length; needs at least one token). Hops between the constant token
        bytes `81 00 ff ff` instead of trying every offset."""
        if nxt >= len(self.roots):
            return len(self.r.d)
        d, save, end = self.r.d, self.r.p, min(p + limit, len(self.r.d))
        pat = bytes.fromhex("8100ffff")
        try:
            t = d.find(pat, p, end)
            while t != -1:
                for q in range(max(p, t - 12), t):
                    self.r.p = q
                    try:
                        k = self.r.size()
                        if not 0 < k <= 4096:
                            continue
                        toks = [self.token() for _ in range(k)]
                    except DecodeError:
                        continue
                    if all(x[1] == nxt for x in toks):
                        return q
                t = d.find(pat, t + 1, end)
            return None
        finally:
            self.r.p = save

    def lookahead_end(self, p, i, limit=8_000_000):
        """End of object i (no stored length, empty-header successors): find the header of the first later object
        that owns tokens and subtract the stored lengths + 2-byte empty headers of the objects in between."""
        gap = 0
        for j in range(i + 1, min(len(self.roots), i + 64)):
            h = self.find_header(p, j, limit)
            if h is not None:
                return h - gap
            if not self.hashes[j][1]:
                return None
            gap += self.hashes[j][1] + 2
        return None

    def decode_fields(self, cname, out):
        for owner, m in self.s.fields(cname):
            if (owner, m["name"]) in NOT_SERIALIZED:
                continue
            pos = self.r.p
            if m["flags"] & SKIP_FLAGS:
                t = m["type"]
                if m["flags"] == 0x2 and t.endswith("[]") and not t[:-2].endswith(("*", "^")):
                    # flag 0x2 array of plain data (SkinnedMeshBoneBindings.InverseBindMatrices, BitstreamData.Data,
                    # LightProbeSetResource.LightProbes): raw bytes in the stream, as many as the object's next
                    # array allocation (verified for the bone bindings: 69 bones x 64 = 4416 = stored length - fields)
                    et = t[:-2]
                    if et == "uint8":  # byte blobs carry a u32 length (BitstreamData.Data: 00 00 5c 00 = 23,552)
                        n = self.r.unpack(">I")
                        if n > len(self.r.d) - self.r.p:
                            raise DecodeError(f"blob length {n} past the end")
                        if n and self.alloc_i < len(self.cur_allocs):
                            self.alloc_i += 1
                        out.append((owner, m["name"], t, pos, self.r.raw(n)))
                        continue
                    esz = struct.calcsize(PRIMS[et]) if et in PRIMS else self.s.classes.get(et, {}).get("size", 0)
                    if et != "LightProbe" and self.alloc_i < len(self.cur_allocs) and esz and self.cur_allocs[self.alloc_i][0] % esz == 0:  # LightProbe[] is never in the stream (a 13,728-byte alloc is 143 tree nodes, not 78 probes)
                        n = self.cur_allocs[self.alloc_i][0]
                        self.alloc_i += 1
                        out.append((owner, m["name"], t, pos, self.r.raw(n)))
                    else:  # empty (LightProbeSetResource.LightProbes with a 96-byte alloc that belongs to the next array)
                        out.append((owner, m["name"], t, pos, b""))
                elif m["flags"] == 0x2 and t in self.s.classes and not t.endswith(("]", "*", "^")):
                    # flag 0x2 struct (AIStaticCoverMap.Data: BitstreamData, whose Data uint8[] is a raw array)
                    sub = []
                    self.decode_fields(t, sub)
                    out.append((owner, m["name"], t, pos, {n: v for _, n, _, _, v in sub}))
                continue
            out.append((owner, m["name"], m["type"], pos, self.value(m["type"])))

    def index(self, count, limit=255):
        """String-group / object index: u8 when the table has at most 255 entries, else big-endian u16
        (verified on basemenu_styles: 311 strings and 342 objects -> u16, 4 filenames -> u8)."""
        return self.r.unpack(">H") if count > limit else self.r.u8()

    def value(self, t):
        r = self.r
        if t.endswith("[]") or t.endswith("[tiny]"):
            et = t[:t.rindex("[")]
            n = r.size()
            if n > len(r.d) - r.p:  # every element takes at least one byte
                raise DecodeError(f"array count {n} larger than the rest of the file")
            if n:
                self.alloc_i += 1
            return [self.value(et) for _ in range(n)]
        if t.endswith("*") or t.endswith("^"):  # ASSUMPTION: T^ (cptr) is encoded like T*
            flag = r.u8()
            if flag == 2:
                # external reference: size-coded length + the target's hash as 32 hex digits (the 16-byte hash from
                # the object list of another file)
                return dict(ref="external", flag=flag, hash=r.raw(r.size()).decode("ascii"))
            if flag != 0:
                raise DecodeError(f"unknown reference flag {flag}")
            idx = self.index(len(self.roots))
            return dict(ref=None if idx == 0 else idx - 1, flag=flag)
        if t in STRINGS:
            items = self.groups.get(t)
            idx = self.index(len(items or ()), 256)  # a 256-entry group still fits a byte (indices 0..255)
            if items is None or idx >= len(items):
                raise DecodeError(f"{t} index {idx} outside its string group")
            return items[idx]
        if t in PRIMS:
            return r.unpack(PRIMS[t])
        info = self.s.types.get(t)
        if info and info["kind"].startswith("0x0404"):  # enum
            v = r.unpack({1: ">B", 2: ">H", 4: ">I"}[info["size"]])
            return f"{info['values'].get(str(v), '?')} ({v})"
        if info and info["kind"].startswith("0x01"):
            return r.raw(info["size"]).hex()
        if t == "Pose":
            # Pose: Skeleton ref, then (verified on SkinnedModelResource: stored length matches exactly) a u8 flag,
            # u32 bone count n, n x 48 bytes (quaternion, position, scale: 12 floats), n x 64 bytes (matrices),
            # u32 m (n + 1), m x 4 bytes. Kept raw.
            sub = []
            self.decode_fields(t, sub)
            res = {name: v for _, name, _, _, v in sub}
            flag = r.u8()
            res["flag"] = flag
            if flag:
                n = r.unpack(">I")
                res["bones"] = n
                res["local"] = r.raw(n * 48)
                res["matrices"] = r.raw(n * 64)
                m = r.unpack(">I")
                res["parents_m"] = m
                res["extra"] = r.raw(m * 4)
            return res
        if t in self.s.classes:  # embedded struct
            sub = []
            self.decode_fields(t, sub)
            return {name: v for _, name, _, _, v in sub}
        raise DecodeError(f"unknown type {t}")


def fmt(v, ind):
    pad = "  " * ind
    if isinstance(v, dict) and "ref" in v:
        if v["ref"] == "external":
            return f"-> external {v['hash']}"
        return "null" if v["ref"] is None else f"-> object #{v['ref']}"
    if isinstance(v, dict):
        return "{\n" + "".join(f"{pad}  {k} = {fmt(x, ind + 1)}\n" for k, x in v.items()) + pad + "}"
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[\n" + "".join(f"{pad}  {fmt(x, ind + 1)}\n" for x in v) + pad + "]"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} raw bytes> {bytes(v[:12]).hex(' ')}"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def check_file(path, schema, max_objects=None):
    """Decode one file. Returns (core, problems); problems is empty only if every object decoded, each object's
    decoded length equals the stored per-object length and no byte of the file is left over."""
    data = open(path, "rb").read()
    problems = []
    try:
        c = Core(data, schema)
    except Exception as e:  # any decoder failure is a failure of the file, not a crash
        return None, [f"header: {e}"]
    try:
        c.decode(max_objects)
    except Exception as e:  # any decoder failure is a failure of the file, not a crash
        o = c.objects[-1] if c.objects else None
        where = f"object #{o['index']} {o['cls']}" if o else "before first object"
        mem = o["fields"][-1][:2] if o and o["fields"] else None
        problems.append(f"decode stopped at {c.r.p:#x} in {where}, after member {mem}: {type(e).__name__}: {e}")
    for o in c.objects:
        if "end" in o and not o["size_ok"]:
            problems.append(f"object #{o['index']} {o['cls']}: decoded {o['end'] - o['start']} bytes, stored length "
                            f"{c.hashes[o['index']][1]}")
    if not problems and max_objects is None and c.r.p != len(data):
        problems.append(f"{len(data) - c.r.p} bytes left at {c.r.p:#x}: {data[c.r.p:c.r.p + 16].hex()}")
    return c, problems


def file_kind(path):
    """Coarse kind from the file name (for the pass-rate table): language folder, assets_description.<group>,
    levels.<mode>.<level>.<leveldescription|section_*|ambient|music|...>."""
    import re
    parts = path.replace("\\", "/").split("/")
    base = parts[-1].lower()
    lang = parts[-2] if len(parts) > 2 and parts[-3].lower() == "lumps" and parts[-2].lower() != "lumps" else None
    if base.endswith(".core"):
        base = base[:-5]
    m = re.match(r"levels\.(?:multi_player|single_player)\.[^.]+\.(.*)", base)
    if m:
        rest = m.group(1)
        k = "level." + re.split(r"[._]", rest)[0]
        if rest.startswith("section_"):
            k = "level.section_*." + (rest.split(".", 1)[1].split("_")[0] if "." in rest else "")
    elif base.startswith("assets_description."):
        k = "assets_description." + re.split(r"[._]", base[len("assets_description."):])[0]
    elif re.match(r"mp_\d+$", base):
        k = "mp_NN (level text)"
    else:
        k = re.split(r"[._]", base)[0]
    return "localized (per language): " + k if lang else k


def _check_one(args):
    f, schema_path = args
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = Schema(schema_path)
    c, probs = check_file(f, _SCHEMA)
    kind = "?"
    opaque = 0
    if c is not None:
        kind = c.types[c.roots[0]] if c.roots else "(empty)"
        opaque = sum(1 for o in c.objects if "blob" in o)
    return f, file_kind(f), probs, len(c.objects) if c else 0, opaque


_SCHEMA = None


def batch(root, schema_path, jobs):
    """Decode every .core below root. Exit status 1 if any file fails (decode stopped, an object's decoded length
    differs from the stored one, or bytes are left over)."""
    import collections, multiprocessing, re
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.lower().endswith(".core"))
    with multiprocessing.Pool(jobs) as pool:
        res = pool.map(_check_one, [(f, schema_path) for f in files], chunksize=4)
    fails = [r for r in res if r[2]]
    for f, kind, probs, n, op in fails:
        print(f"FAIL {f}\n     {probs[0]}" + (f" (+{len(probs) - 1} more)" if len(probs) > 1 else ""))
    by_kind = collections.defaultdict(lambda: [0, 0])
    for f, kind, probs, n, op in res:
        by_kind[kind][0 if not probs else 1] += 1
    print("\nfile kind: pass / fail")
    for k, (p, q) in sorted(by_kind.items(), key=lambda kv: -sum(kv[1])):
        print(f"  {k:36s} {p:5d} / {q:d}")
    causes = collections.Counter()
    for f, kind, probs, n, op in fails:
        causes[re.sub(r"0x[0-9a-f]+|\d+", "N", probs[0])[:160]] += 1
    if causes:
        print("\nfailure causes:")
        for k, v in causes.most_common(25):
            print(f"  {v:5d}  {k}")
    objs = sum(r[3] for r in res)
    opq = sum(r[4] for r in res)
    print(f"\n{len(files)} files: {len(files) - len(fails)} pass, {len(fails)} fail; {objs} objects decoded, "
          f"{opq} of them with an opaque (MsgReadBinary / mesh instance) payload")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("--all", metavar="DIR", help="decode every .core under DIR, print pass/fail summary")
    ap.add_argument("--schema", default="work/re-data/rtti.json")
    ap.add_argument("--header", action="store_true", help="print only the header tables")
    ap.add_argument("--max-objects", type=int)
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    a = ap.parse_args()
    if not os.path.exists(a.schema):
        sys.exit(f"{a.schema} missing: run tools/rtti_dump.py work/bin/EBOOT.elf --json {a.schema}")
    schema = Schema(a.schema)
    if a.all:
        sys.exit(batch(a.all, a.schema, a.jobs))
    if not a.file:
        ap.error("FILE or --all DIR required")
    data = open(a.file, "rb").read()
    if a.header:
        c = Core(data, schema)
        problems = []
    else:
        c, problems = check_file(a.file, schema, a.max_objects)
        if c is None:
            sys.exit(f"{a.file}: {problems[0]}")
    print(f"{a.file}: {len(data)} bytes, types {c.types}")
    print(f"roots {[c.types[i] for i in c.roots]}; {len(c.hashes)} class hashes; {len(c.units)} units; "
          f"strings { {k: len(v) for k, v in c.groups.items()} }")
    for k, items in c.groups.items():
        print(f"  {k}[]: {items}")
    for o in c.objects:
        chk = {True: "size matches root-list u32", False: "SIZE MISMATCH vs root-list u32"}.get(o.get("size_ok"), "?")
        print(f"\n#{o['index']} {o['cls']}  (instance size {o['size']:#x}, {len(o['allocs'])} array allocs, data {o['start']:#x}..{o.get('end', 0):#x}, {chk})")
        for owner, name, t, pos, v in o["fields"]:
            print(f"  {name} : {t} = {fmt(v, 1)}")
        if "blob" in o:
            print(f"  [opaque custom payload, {o['opaque']} bytes] {o['blob'][:24].hex(' ')}...")
        if "tail" in o:
            print(f"  [custom tail u32s] {o['tail']}")
    st = [(o["index"], o["cls"], o["stream"]) for o in c.objects if "stream" in o]
    if st:
        end = max(a + b for _, _, (a, b) in st)
        print(f"\n.corestream references: {len(st)} objects ({sum(1 for _, k, _ in st if k == 'Texture')} textures, "
              f"{sum(1 for _, k, _ in st if k != 'Texture')} sounds), highest byte referenced {end}")
        stem = os.path.splitext(a.file)[0]
        for ext in (".corestream", ".CoreStream", ".CORESTREAM"):
            if os.path.exists(stem + ext):
                print(f"  {stem + ext}: {os.path.getsize(stem + ext)} bytes")
    if problems:
        for p in problems:
            print(f"\nFAIL: {p}")
        sys.exit(1)
    if not a.header:
        print(f"\nOK: consumed all {len(data)} bytes" if a.max_objects is None else "\nOK (partial, --max-objects)")


if __name__ == "__main__":
    main()
