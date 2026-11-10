#!/usr/bin/env python3
"""Synthetic regressions for observable park dependencies (no game data)."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from park_chain import dependencies, overlap_index, overlaps, report_dependencies, workload_observation


class ParkChainTests(unittest.TestCase):
    def setUp(self):
        self.thr = {0: "rsx:frame", 1: "spurs-kern0:", 2: "ppu-main", 3: "ftr-inst"}

    def test_unchanged_positive_before_park_is_not_late_submission(self):
        self.assertEqual(workload_observation([(0, 3, 1)], 3, 1000, 2000),
                         ("positive at park start", None))

    def test_transition_is_sample_bracket_not_exact_submission(self):
        self.assertEqual(workload_observation([(0, 3, 0), (1200, 3, 0), (1500, 3, 1)], 3, 1000, 2000),
                         ("observed zero-to-positive", (1200, 1500)))

    def test_first_positive_without_zero_is_unknown(self):
        self.assertEqual(workload_observation([(1500, 3, 1)], 3, 1000, 2000),
                         ("positive, transition unknown", None))

    def test_long_running_call_not_lost_to_50ms_lookback(self):
        self.assertEqual(list(overlaps([(0, 100000, 201)], 80000, 90000)), [(80000, 90000, 201)])

    def test_zero_and_negative_overlaps_are_excluded(self):
        self.assertEqual(list(overlaps([(0, 10, 201), (20, 30, 202)], 10, 20)), [])

    def test_index_preserves_arbitrarily_old_nested_overlaps(self):
        calls = [(0, 100000, 201), (10, 20, 202), (30, 40, 203), (70000, 85000, 205),
                 (80000, 81000, 223), (90000, 110000, 224)]
        index = overlap_index(calls)
        self.assertEqual(index[1], [100000, 100000, 100000, 100000, 100000, 110000])
        for start, end in [(80000, 90000), (100000, 110000), (0, 10), (81000, 85000),
                           (110000, 120000), (90000, 90000), (90001, 90000)]:
            with self.subTest(start=start, end=end):
                self.assertEqual(list(overlaps(calls, start, end, index)), list(overlaps(calls, start, end)))

    def test_index_boundary_equality_excludes_touching_calls(self):
        calls = [(0, 10, 201), (10, 10, 202), (20, 30, 203)]
        self.assertEqual(list(overlaps(calls, 10, 20, overlap_index(calls))), [])
        self.assertEqual(list(overlaps([], 10, 20, overlap_index([]))), [])

    def test_index_skips_finished_prefix_instead_of_scanning(self):
        class CountedCalls(list):
            def __getitem__(self, i):
                self.reads += 1
                return super().__getitem__(i)

        calls = CountedCalls((i * 10, i * 10 + 5, 201) for i in range(1000))
        index = overlap_index(calls)
        calls.reads = 0
        self.assertEqual(list(overlaps(calls, 9990, 9995, index)), [(9990, 9995, 201)])
        self.assertEqual(calls.reads, 1)

    def test_kick_after_park_does_not_steal_next_dependency(self):
        rows, counts = dependencies(self.thr, {0: [(100, 200, 9, 0)],
                                              1: [(150, 250, 33, 201), (210, 210, 47, 0)]})
        self.assertEqual(rows, [])
        self.assertEqual(counts["no kick"], 1)

    def test_ppu_writer_retained(self):
        rows, counts = dependencies(self.thr, {0: [(100, 200, 9, 0)], 2: [(190, 190, 47, 0)]})
        self.assertEqual(rows[0]["writer"], 2)
        self.assertIsNone(rows[0]["call"])
        self.assertEqual(counts["writer without SPU job"], 1)

    def test_stages_ready_proxy_and_kernel_busy(self):
        ev = {0: [(1000, 5000, 9, 0)],
              1: [(2000, 4500, 5, 3), (2500, 4500, 33, 205), (4400, 4400, 47, 0),
                  (500, 2000, 33, 201)],
              3: [(0, 0, 40, 3 << 16), (1800, 1800, 40, (3 << 16) | 256)]}
        rows, counts = dependencies(self.thr, ev)
        r = rows[0]
        self.assertEqual((r["start"], r["call"][0], r["kick"], r["end"]), (1000, 2500, 4400, 5000))
        self.assertEqual(r["transition"], (1000, 1800))
        self.assertAlmostEqual(r["pre_call_busy"], 1000 / 1500)
        self.assertEqual(r["policy_start"], 2000)

    def test_multiple_instance_samplers_are_not_mixed(self):
        thr = dict(self.thr, **{})
        thr[4] = "ftr-inst-other"
        ev = {0: [(1000, 5000, 9, 0)], 1: [(2000, 4500, 5, 3), (2500, 4500, 33, 205),
                                              (4400, 4400, 47, 0)],
              3: [(0, 0, 40, 3 << 16), (1800, 1800, 40, (3 << 16) | 256)]}
        self.assertEqual(dependencies(thr, ev)[0][0]["readiness"], "unknown")

    def test_no_sampler_is_explicitly_unknown(self):
        ev = {0: [(1000, 5000, 9, 0)], 1: [(2500, 4500, 33, 205), (4400, 4400, 47, 0)]}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report_dependencies(self.thr, ev, {})
        self.assertIn("unknown=1", out.getvalue())
        self.assertIn("not proven wake delay", out.getvalue())

    def test_cli_images_and_long_overlap(self):
        trace = """[ftr-thr] 0 rsx:frame
[ftr-thr] 1 spurs-kern0:
[ftr] 0 9 0 80000 10000
[ftr] 1 33 C9 0 90000
[ftr] 1 47 0 89000 0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log") as f:
            f.write(trace)
            f.flush()
            p = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "park_chain.py"),
                                f.name, "--images", "205", "--manifest", "/nonexistent"],
                               capture_output=True, text=True, check=True)
        self.assertIn("kernels idle before the patch 0 %", p.stdout)
        self.assertNotIn("ovl201 (201)", p.stdout)

    def test_missing_walker_gives_useful_error(self):
        with self.assertRaisesRegex(ValueError, "expected one walker"):
            dependencies({1: "spurs-kern0:"}, {})


if __name__ == "__main__":
    unittest.main()
