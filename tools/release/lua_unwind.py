#!/usr/bin/env python3
"""Generate host-unwind continuations at KZ2's three guest setjmp call sites.

Applied after the PPU lifter by both build paths. Guest bodies remain generated
from the player's executable. No hand-edited lifted output or game code ships.
Run under the project sandbox when processing real game-derived lift output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

SETJMP = {"129": "007C38E8", "101": "007B5F60"}
READY = "#define KZ2_LUA_UNWIND_READY 1\n"
CALL = r"ctx->lr = 0x([0-9A-F]{8}); func_{target}\(ctx\); DRAIN_TRAMPOLINE\(ctx\);"
FUNCTION = re.compile(r"^void (?:__attribute__\(\(weak\)\) )?(func_[0-9A-F]{8}(?:__lifted)?)\(ppu_context\* ctx\) \{\n(.*?)^}", re.M | re.S)


def transform(text, target):
    call = re.compile(CALL.replace("{target}", target))
    count = 0
    def function(m):
        nonlocal count
        body = m[2]
        sites = list(call.finditer(body))
        if not sites:
            return m[0]
        if len(sites) != 1:
            raise ValueError("multiple setjmp sites in one host frame require review")
        count += 1
        if "kz2lua::Frame _kz2_frame" in body:
            if "_kz2_frame.arm" not in body or "catch (const kz2lua::Jump&" not in body:
                raise ValueError("incomplete existing unwind continuation")
            return m[0]
        site = sites[0]
        label = "KZ2_LUA_RESUME_" + site[1]
        body = body.replace("    PPU_MM_SNAP\n", "", 1)
        # The lifter caches entry callee-saved registers in host locals. Keep
        # those original snapshots alive across the exception/continuation.
        snapshots = re.findall(r"^\s*uint64_t _cs_\d+ = ctx->gpr\[\d+\];\n", body, re.M)
        for line in snapshots:
            body = body.replace(line, "", 1)
        if re.search(r"\buint64_t _cs_", body):
            raise ValueError("unrecognized callee-save local requires review")
        body = call.sub(lambda c: "_kz2_frame.arm((uint32_t)ctx->gpr[3]); " + c[0] + "\n" + label + ":;", body)
        return (m[0][:m[0].index("{\n") + 2] +
                "    PPU_MM_SNAP\n" + "".join(snapshots) +
                "    kz2lua::Frame _kz2_frame(ctx);\n    bool _kz2_resume = false;\n"
                "    for (;;) {\n        try {\n"
                f"            if (_kz2_resume) goto {label};\n" + body +
                "            return;\n        } catch (const kz2lua::Jump& _kz2_jump) {\n"
                "            if (!_kz2_frame.matches(_kz2_jump)) throw;\n"
                "            _kz2_frame.land();\n            g_trampoline_fn = nullptr;\n"
                "            _kz2_resume = true;\n        }\n    }\n}")
    changed = FUNCTION.sub(function, text)
    if count and '#include "kz2_lua_unwind.h"' not in changed:
        anchor = '#include "ppu_recomp.h"'
        if anchor not in changed:
            raise ValueError("missing generated header include")
        changed = changed.replace(anchor, anchor + '\n#include "kz2_lua_unwind.h"', 1)
    if len(call.findall(changed)) != count:
        raise ValueError("a setjmp call is outside a recognized complete lifted function")
    return changed, count


def apply(directory, version):
    target = SETJMP[version]
    planned, count = [], 0
    for path in sorted(Path(directory).glob("ppu_recomp_*.cpp")):
        text = path.read_text()
        if not re.search(CALL.replace("{target}", target), text):
            continue
        updated, n = transform(text, target)
        planned.append((path, text, updated))
        count += n
    if count != 3:
        raise ValueError(f"expected all 3 setjmp callers, found {count}; refusing partial transformation")
    announcements = Path(directory) / "ppu_overrides.h"
    header = announcements.read_text()
    receipts = []
    for path, original, updated in planned:
        if updated != original:
            tmp = path.with_suffix(path.suffix + ".unwind-new")
            tmp.write_text(updated)
            tmp.replace(path)
        receipts.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if READY not in header:
        tmp = announcements.with_suffix(".h.unwind-new")
        tmp.write_text(header.rstrip() + "\n" + READY)
        tmp.replace(announcements)
    (Path(directory) / "lua-unwind.json").write_text(json.dumps({"schema": "kz2.lua-unwind/1", "version": version,
                    "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "callers": count, "files": receipts}, indent=2) + "\n")
    return count


def verify(directory, version):
    directory = Path(directory)
    receipt = json.loads((directory / "lua-unwind.json").read_text())
    if (receipt.get("schema") != "kz2.lua-unwind/1" or receipt.get("version") != version or
            receipt.get("callers") != 3 or
            receipt.get("generator_sha256") != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
        raise ValueError("stale or incomplete Lua unwind generation; relift and regenerate")
    if READY not in (directory / "ppu_overrides.h").read_text():
        raise ValueError("missing Lua unwind readiness marker")
    for item in receipt["files"]:
        if not re.fullmatch(r"ppu_recomp_[A-Za-z0-9_]+\.cpp", item["file"]):
            raise ValueError("invalid source name in Lua unwind receipt")
        if hashlib.sha256((directory / item["file"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("protected source changed; regenerate Lua unwind continuations")
    if not receipt["files"]:
        raise ValueError("Lua unwind receipt has no sources")
    return 3


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--recomp-dir", type=Path, required=True)
    p.add_argument("--version", choices=SETJMP, required=True)
    p.add_argument("--verify", action="store_true")
    a = p.parse_args()
    try:
        count = verify(a.recomp_dir, a.version) if a.verify else apply(a.recomp_dir, a.version)
        print(f"lua-unwind: {count} protected continuations" + (" verified" if a.verify else ""))
        return 0
    except (OSError, ValueError) as exc:
        print("lua-unwind: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
