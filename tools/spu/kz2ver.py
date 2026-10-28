"""EBOOT version switch and image table for the KZ2 SPU tools (lift_spu.py, gen_spu_register.py).

Adapted from Project Helghast tools/spu/kz3ver.py, much simpler: KZ2's image table is the re-data census
(re/wws_jobs_v129.tsv, re/wws_jobs_v101.tsv: kind, file offset, size, header, registered name), so every image is
carved from the EBOOT itself and named by its file offset in the selected version (elf_00ccb180, job_00d71900,
pm_00d92c80). KZ2_EBOOT_VER=129 (default) or 101.
"""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VER = os.environ.get("KZ2_EBOOT_VER", "129")
if VER == "129":
    EBOOT = os.path.join(ROOT, "work/bin/EBOOT-129.elf")
elif VER == "101":
    EBOOT = os.path.join(ROOT, "Game/PS3_GAME/USRDIR/EBOOT.elf")
else:
    raise SystemExit("KZ2_EBOOT_VER must be 129 or 101")
TSV = os.path.join(ROOT, f"re/wws_jobs_v{VER}.tsv")
EA_DELTA = 0x10000  # EA = file offset + 0x10000 for everything in the first PT_LOAD (both versions)


def rows():
    """Census rows as dicts (kind elf/job/pm, file_offset int, size int, name, ...), sorted by file offset."""
    lines = open(TSV).read().splitlines()
    hdr = lines[0].split("\t")
    out = []
    for l in lines[1:]:
        if not l.strip():
            continue
        r = dict(zip(hdr, l.split("\t")))
        r["file_offset"] = int(r["file_offset"], 16)
        r["size"] = int(r["size"])
        r["name"] = f"{r['kind']}_{r['file_offset']:08x}"
        out.append(r)
    return sorted(out, key=lambda r: r["file_offset"])


def check_lift(lift):
    p = os.path.join(lift, "eboot_ver")
    have = open(p).read().strip() if os.path.exists(p) else "?"
    if have != VER:
        raise SystemExit(f"lift in {lift} is for EBOOT {have}, KZ2_EBOOT_VER={VER}: rerun tools/spu/lift_spu.sh")
