#!/usr/bin/env python3
"""Continuation generation tests with synthetic code; no game data."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lua_unwind as lu


def fixture(address="00100000", target="007C38E8"):
    return ('#include "ppu_recomp.h"\n'
            f'void func_{address}(ppu_context* ctx) {{\n'
            '    PPU_MM_SNAP\n'
            '    uint64_t _cs_14 = ctx->gpr[14];\n'
            '    ctx->gpr[1] -= 0x300;\n'
            '    ctx->gpr[3] = ctx->gpr[1] + 0x74;\n'
            f'    ctx->lr = 0x{int(address,16)+4:08X}; func_{target}(ctx); DRAIN_TRAMPOLINE(ctx);\n'
            '    if (!ctx->gpr[3]) { callback(ctx); ctx->gpr[3] = 0; }\n'
            '    ctx->gpr[1] += 0x300;\n'
            '    ctx->gpr[14] = _cs_14;\n'
            '    return;\n}\n')


class GenerationTests(unittest.TestCase):
    def test_snapshots_survive_resume_and_transformation_is_idempotent(self):
        text, count = lu.transform(fixture(), "007C38E8")
        self.assertEqual(count, 1)
        self.assertLess(text.index("uint64_t _cs_14"), text.index("for (;;)"))
        self.assertIn("goto KZ2_LUA_RESUME_00100004", text)
        self.assertEqual(lu.transform(text, "007C38E8"), (text, 1))

    def test_incomplete_coverage_changes_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ppu_recomp_000.cpp"
            original = fixture(); p.write_text(original)
            with self.assertRaisesRegex(ValueError, "expected all 3"):
                lu.apply(tmp, "129")
            self.assertEqual(p.read_text(), original)

    def test_all_callers_and_both_versions_are_supported(self):
        for version, target in lu.SETJMP.items():
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "ppu_overrides.h").write_text("#pragma once\n")
                for i in range(3):
                    (Path(tmp) / f"ppu_recomp_{i:03d}.cpp").write_text(fixture(f"{0x100000+i*256:08X}", target))
                self.assertEqual(lu.apply(tmp, version), 3)
                self.assertEqual(lu.apply(tmp, version), 3)
                self.assertTrue((Path(tmp) / "lua-unwind.json").is_file())
                self.assertEqual(lu.verify(tmp, version), 3)
                self.assertEqual((Path(tmp) / "ppu_overrides.h").read_text().count(lu.READY), 1)
                (Path(tmp) / "ppu_recomp_000.cpp").write_text("changed")
                with self.assertRaisesRegex(ValueError, "source changed"):
                    lu.verify(tmp, version)

    def test_unknown_frame_local_and_multiple_sites_fail_closed(self):
        text = fixture().replace("ctx->gpr[14];", "vm_read64(ctx->gpr[1]);")
        with self.assertRaisesRegex(ValueError, "callee-save"):
            lu.transform(text, "007C38E8")
        text = fixture().replace("    return;", "    ctx->lr = 0x00100008; func_007C38E8(ctx); DRAIN_TRAMPOLINE(ctx);\n    return;")
        with self.assertRaisesRegex(ValueError, "multiple setjmp"):
            lu.transform(text, "007C38E8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--emit-fixture":
        Path(sys.argv[2]).write_text(lu.transform(fixture(), "007C38E8")[0])
    else:
        unittest.main()
