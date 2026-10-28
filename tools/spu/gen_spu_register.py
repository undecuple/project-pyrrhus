#!/usr/bin/env python3
"""Generate KZ2's SPU registration TU for ps3recomp's runtime from the lift in <lift>/lift.
From Project Helghast tools/spu/gen_spu_register.py (kz3 -> kz2; output is the spu_workloads.c that port/kz2/CMakeLists.txt
compiles from SPU_DIR, no port/spu subproject; no KZ3 skip/cull tables).

    gen_spu_register.py --lift work/spu/spu [--only NAME,...]

Writes (derived from the binary, never committed):
  <lift>/lift/spu_workloads.c   kz2_spu_register_all() + a constructor that calls it
  <lift>/kz2_spu_manifest.json  image ids, names, fingerprints, signatures, entry symbols

How each kind is found at run time (ps3recomp v0.13.0 runtime, runtime/spu/ and libs/spurs/):
  * SPURS policy module (pm_*): cellSpurs.c spurs_resolve_pm() fingerprints `sizePm` bytes at the guest EA
    (FNV-1a-64) and calls spu_workload_find_img(). Registered with spu_workload_register_img(fp, entry 0xA00, 2): the
    runtime's WWS job-code dispatch (spu_channels.c spu_indirect_branch: `ctx->image_id == 2`, code buffer pointer at
    LS 0x1320) is keyed to image id 2. KZ2's PM keeps the code buffer pointer at LS 0x1320 too (job call
    `bisl $r0,$r5` at LS 0x32BC).
  * WWS job modules (job_*): streamed into the job code buffer; the runtime matches the first 16 bytes (the four
    `ila` signature) against spu_overlay_register_sig() entries. Image ids 200+.
  * SPU ELFs (elf_*): fingerprint over spu_elf_image_size() bytes and over the executable PT_LOAD. Image ids 30+
    (clear of the runtime's special ids 1, 22, 23, 60-65, 100, 200+).
"""
import argparse, json, os, struct, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kz2ver  # noqa: E402

PM_IMAGE_ID = 2    # WWS job manager: id 2 is what the runtime's WWS hooks expect
ELF_IMAGE_BASE = 30
JOB_IMAGE_BASE = 200
PM_ENTRY = 0xA00
RESERVED = {1, 22, 23, 100} | set(range(60, 66))


def be16(b, o): return (b[o] << 8) | b[o + 1]
def be32(b, o): return struct.unpack_from(">I", b, o)[0]


def fnv1a64(b):
    """runtime/spu/spu_workload.c spu_workload_fingerprint (FNV-1a 64)."""
    h = 1469598103934665603
    for x in b:
        h = ((h ^ x) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def elf_image_size(b):
    """runtime/spu/spu_workload.c spu_elf_image_size (same as build_spu_workloads.py img_size)."""
    e_phoff, e_shoff = be32(b, 0x1C), be32(b, 0x20)
    e_phentsize, e_phnum = be16(b, 0x2A), be16(b, 0x2C)
    e_shentsize, e_shnum = be16(b, 0x2E), be16(b, 0x30)
    end = e_shoff + e_shnum * e_shentsize
    for k in range(e_phnum):
        po = e_phoff + k * e_phentsize
        if po + 0x14 > len(b):
            break
        end = max(end, be32(b, po + 4) + be32(b, po + 0x10))
    for k in range(e_shnum):
        so = e_shoff + k * e_shentsize
        if so + 0x18 > len(b):
            break
        if be32(b, so + 4) != 8:
            end = max(end, be32(b, so + 0x10) + be32(b, so + 0x14))
    return min(end, len(b))


def text_fp(b):
    """Fingerprint of the executable PT_LOAD's file bytes (build_spu_workloads.py text_fp)."""
    phoff, phes, phn = be32(b, 0x1C), be16(b, 0x2A), be16(b, 0x2C)
    for i in range(phn):
        o = phoff + i * phes
        if be32(b, o) == 1 and be32(b, o + 0x18) & 1:
            off, fsz = be32(b, o + 4), be32(b, o + 0x10)
            return fnv1a64(b[off:off + fsz])
    return None


def has_symbol(lift, name, sym):
    h = os.path.join(lift, "lift", name, "spu_recomp.h")
    return os.path.exists(h) and f"{sym}(" in open(h).read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lift", default=os.path.join(ROOT, "work/spu/spu"), help="lift_spu.py --out directory")
    ap.add_argument("--only", default="", help="comma list of image names to register (default: all)")
    a = ap.parse_args()
    kz2ver.check_lift(a.lift)
    a.out = os.path.join(a.lift, "lift")
    names = {r["name"]: (r.get("reg_name") or "") for r in kz2ver.rows()}
    R = json.load(open(os.path.join(a.lift, "spu_lift.json")))
    bad = [r["name"] for r in R if not r["ok"]]
    if bad:
        sys.exit(f"lift failed for {bad}; rerun tools/spu/lift_spu.sh")
    eboot = open(kz2ver.EBOOT, "rb").read()
    images, problems = [], []

    pms = [r for r in R if r["kind"] == "pm"]
    elfs = sorted((r for r in R if r["kind"] == "elf"), key=lambda r: r["file_offset"])
    jobs = sorted((r for r in R if r["kind"] == "job"), key=lambda r: r["file_offset"])

    for r in pms:
        raw = eboot[r["file_offset"]:r["file_offset"] + r["size"]]
        sym = f"{r['name']}_spu_func_{PM_ENTRY:08X}"
        images.append(dict(name=r["name"], kind="pm", image_id=PM_IMAGE_ID, fp=fnv1a64(raw),
                           size=len(raw), ea=r["file_offset"] + 0x10000, entry=PM_ENTRY, entry_sym=sym))

    for i, r in enumerate(elfs):
        b = open(os.path.join(a.lift, "elf_in", f"spu_{r['file_offset']:08x}.elf"), "rb").read()
        if b[:4] != b"\x7fELF" or be16(b, 0x12) != 0x17:
            problems.append(f"{r['name']}: not an SPU ELF")
            continue
        ent = be32(b, 0x18)
        sz = elf_image_size(b)
        images.append(dict(name=r["name"], kind="elf", image_id=ELF_IMAGE_BASE + i, fp=fnv1a64(b[:sz]),
                           size=sz, text_fp=text_fp(b), ea=r["file_offset"] + 0x10000, entry=ent,
                           entry_sym=f"{r['name']}_spu_func_{ent:08X}"))

    # Extra executable segments of an ELF (lift_spu.py kind "elfseg"): their functions go in under the parent
    # ELF's image id; no fingerprint of their own (the runtime dispatches the parent).
    elf_id = {m["name"]: m["image_id"] for m in images if m["kind"] == "elf"}
    for r in sorted((r for r in R if r["kind"] == "elfseg"), key=lambda r: r["name"]):
        if r["parent"] not in elf_id:
            problems.append(f"{r['name']}: parent {r['parent']} not registered")
            continue
        images.append(dict(name=r["name"], kind="elfseg", image_id=elf_id[r["parent"]], parent=r["parent"],
                           size=r["size"], ea=r["file_offset"] + 0x10000, entry=r["base"],
                           entry_sym=f"{r['name']}_spu_func_{r['base']:08X}"))

    for i, r in enumerate(jobs):
        raw = eboot[r["file_offset"]:r["file_offset"] + r["size"]]
        images.append(dict(name=r["name"], kind="job", image_id=JOB_IMAGE_BASE + i, sig=raw[:16].hex(),
                           size=len(raw), ea=r["file_offset"] + 0x10000, base=r["base"],
                           hdr_base=r["hdr_base"], flags=r["flags"], entry=r["base"] + r["entry_off"],
                           entry_sym=f"{r['name']}_spu_func_{r['base'] + r['entry_off']:08X}"))

    # Registration order: Edge zlib inflate task first (it gates the PSARC TOC reads at boot), then the WWS
    # job manager policy module, then the other ELFs and the job modules.
    first = {"pm": 0, "elf": 1, "job": 2}
    images.sort(key=lambda m: first.get(m["kind"], 3))
    images.sort(key=lambda m: m["kind"] == "elfseg")  # stable: segments after every primary image
    if a.only:
        keep = set(a.only.split(","))
        images = [m for m in images if m["name"] in keep]

    # Checks: entry symbols exist, ids unique and not reserved, signatures and fingerprints unique.
    for m in images:
        if not has_symbol(a.lift, m["name"], m["entry_sym"]):
            problems.append(f"{m['name']}: entry symbol {m['entry_sym']} not in the lift")
    ids = [m["image_id"] for m in images if m["kind"] != "elfseg"]
    if len(set(ids)) != len(ids):
        problems.append("duplicate image ids")
    for m in images:
        if m["image_id"] in RESERVED:
            problems.append(f"{m['name']}: image id {m['image_id']} is special-cased by the runtime")
    sigs = {}
    for m in images:
        if m["kind"] == "job":
            sigs.setdefault(m["sig"], []).append(m["name"])
    dup_sigs = {k: v for k, v in sigs.items() if len(v) > 1}
    fps = {}
    for m in images:
        for k in ("fp", "text_fp"):
            if m.get(k) is not None:
                fps.setdefault(m[k], set()).add(m["name"])
    dup_fps = {f"{k:016X}": sorted(v) for k, v in fps.items() if len(v) > 1}
    if dup_sigs:
        problems.append(f"job signature collisions: {dup_sigs}")
    if dup_fps:
        problems.append(f"fingerprint collisions: {dup_fps}")
    if problems:
        sys.exit("\n".join(problems))

    L = ["/* spu_workloads.c -- GENERATED by tools/spu/gen_spu_register.py from the KZ2 SPU lift. Do not edit.",
         " * Registers every lifted KZ2 SPU image with ps3recomp's runtime: the SPURS policy module and the SPU ELFs",
         " * by FNV-1a-64 image fingerprint (spu_workload_register_img), the WWS job modules by their 16-byte",
         " * header signature (spu_overlay_register_sig). Each image's functions go in under its own image id",
         " * (spu_begin_image before its spu_recomp_register). EBOOT %s. */" % kz2ver.VER,
         "#include <stdint.h>",
         '#include "spu_workload.h"',
         "",
         "#ifndef SPU_ABI   /* patch 1099: lifted SPU functions' calling convention (spu_context.h) */",
         "#define SPU_ABI",
         "#endif",
         "extern void spu_begin_image(int image_id);",
         "extern void spu_overlay_register_sig(const uint8_t sig[16], int image_id);",
         ""]
    for m in images:
        L.append(f"extern void {m['name']}_spu_recomp_register(void);")
        if m["kind"] in ("pm", "elf"):
            L.append(f"extern SPU_ABI void {m['entry_sym']}(spu_context*);")   # patch 1099 (from Project Helghast)
    L += ["", "unsigned kz2_spu_image_count = %du;" % sum(m["kind"] != "elfseg" for m in images), "",
          "void kz2_spu_register_all(void)", "{",
          "    static int done;", "    if (done) return;", "    done = 1;"]
    for m in images:
        m["label"] = names.get(m["name"], "") or m["name"]
        tag = f"{m['kind']} EA 0x{m['ea']:08X}, {m['size']} bytes, {m['label']}"
        L.append(f"    /* {m['name']}: {tag} */")
        L.append(f"    spu_begin_image({m['image_id']}); {m['name']}_spu_recomp_register();")
        if m["kind"] in ("pm", "elf"):
            L.append(f"    spu_workload_register_img(0x{m['fp']:016X}ULL, {m['entry_sym']}, {m['image_id']}, "
                     f"\"{m['name']}\");")
        if m.get("text_fp") is not None:
            L.append(f"    spu_workload_register_img(0x{m['text_fp']:016X}ULL, {m['entry_sym']}, "
                     f"{m['image_id']}, \"{m['name']}.text\");")
        if m["kind"] == "job":
            arr = ",".join(f"0x{x:02X}" for x in bytes.fromhex(m["sig"]))
            L.append(f"    {{ static const uint8_t sig[16] = {{{arr}}};")
            L.append(f"      spu_overlay_register_sig(sig, {m['image_id']}); }}")
    L += ["    spu_begin_image(0);", "}", "",
          "/* Image id -> census name (re/wws_jobs_v%s.tsv), for log lines. */" % kz2ver.VER,
          "typedef struct { int id; uint32_t ea; const char* name; } kz2_spu_image_name;",
          "const kz2_spu_image_name kz2_spu_image_names[] = {"]
    L += [f'    {{{m["image_id"]}, 0x{m["ea"]:08X}u, "{m["label"]}"}},' for m in images if m["kind"] != "elfseg"]
    L += ["};", "const unsigned kz2_spu_image_names_n = %du;" % sum(m["kind"] != "elfseg" for m in images), "",
          "const char* kz2_spu_image_name_of(int id)", "{",
          "    for (unsigned i = 0; i < kz2_spu_image_names_n; i++)",
          "        if (kz2_spu_image_names[i].id == id) return kz2_spu_image_names[i].name;",
          "    return 0;", "}", "",
          "/* Registers before main(), i.e. before the game adds any SPURS workload. */",
          "__attribute__((constructor)) static void kz2_spu_register_ctor(void)", "{",
          "    extern const char* (*g_kz2_spu_image_name)(int);   /* patch 7002 job log names */",
          "    g_kz2_spu_image_name = kz2_spu_image_name_of;",
          "    kz2_spu_register_all();", "}", ""]
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "spu_workloads.c"), "w").write("\n".join(L))
    for m in images:
        for k in ("fp", "text_fp"):
            if m.get(k) is not None:
                m[k] = f"0x{m[k]:016X}"
    json.dump(images, open(os.path.join(a.lift, "kz2_spu_manifest.json"), "w"), indent=1)
    n = {k: sum(1 for m in images if m["kind"] == k) for k in ("pm", "elf", "job", "elfseg")}
    print(f"registered {len(images) - n['elfseg']} images: {n['pm']} policy module(s), {n['elf']} ELFs, "
          f"{n['job']} job modules; {n['elfseg']} extra ELF code segment(s)")
    for m in images:
        if m["kind"] == "pm":
            print(f"  {m['name']}: EA 0x{m['ea']:08X} size {m['size']} fp {m['fp']} image id {m['image_id']}")
    print(f"wrote {a.out}/spu_workloads.c, {a.lift}/kz2_spu_manifest.json")


if __name__ == "__main__":
    main()
