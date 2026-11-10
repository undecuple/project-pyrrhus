#!/usr/bin/env python3
"""Regression tests for elapsed-time and descriptive walker comparisons (no GPU)."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import walker_ab


def block(t, wall=1000, flips=20, draw=400):
    return (f"[perf] t={t}s wall={wall}ms flips={flips} fifo-flips=0 presents=0 draws=200 "
            "| walk n=1 700.0ms methods=1 | gpuwait 9.0ms\n"
            f"[perf-walk] t={t}s draw {draw}.0ms (vtx 200.0, pso 80.0)\n")


def log(phase_draws, wall=1000, flips=20):
    out = ""
    t = 1
    for phase, draw in enumerate(phase_draws):
        out += f"[walker-toggle] t={t}.000s phase={phase} {'on' if phase & 1 else 'off'}\n"
        out += block(t, wall, flips, 9999)  # mixed interval must be excluded
        out += block(t + 1, wall, flips, draw)
        t += 2
    return out


class WalkerABTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.n = 0

    def file(self, text):
        self.n += 1
        p = Path(self.tmp.name) / f"run-{self.n}.log"
        p.write_text(text)
        return str(p)

    def run_cli(self, *args):
        out = io.StringIO()
        with patch.object(sys, "argv", ["walker_ab.py", *args]), contextlib.redirect_stdout(out):
            code = walker_ab.main()
        return code, out.getvalue()

    def test_uses_elapsed_wall_time_not_block_count(self):
        p = self.file(log([400, 400, 400], wall=1250, flips=25))
        phases = walker_ab.phases(p, 0, 100)
        self.assertEqual(phases[0]["secs"], 1.25)
        code, out = self.run_cli(p)
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^fps\s+20\.00\s+20\.00\s+\+0\.00")
        self.assertIn("clean seconds: off 2.5, on 1.25; pairs 1", out)

    def test_different_block_durations_are_summed(self):
        text = "[walker-toggle] t=0s phase=0 off\n" + block(0)
        text += block(1, wall=500, flips=10) + block(2, wall=1500, flips=30)
        s = walker_ab.phases(self.file(text), 0, 10)[0]
        self.assertEqual(s["secs"], 2)
        self.assertEqual(s["flips"], 40)
        self.assertEqual(s["blocks"], 2)

    def test_zero_wall_blocks_and_their_subrows_are_dropped(self):
        text = "[walker-toggle] t=0s phase=0 off\n" + block(0)
        text += block(1, wall=0, flips=99, draw=9999) + block(2)
        s = walker_ab.phases(self.file(text), 0, 10)[0]
        self.assertEqual(s["flips"], 20)
        self.assertEqual(s["draw"], 400)

    def test_subrow_after_switch_does_not_move_to_new_phase(self):
        text = "[walker-toggle] t=0s phase=0 off\n" + block(0)
        text += block(1).splitlines(keepends=True)[0]
        text += "[walker-toggle] t=1.1s phase=1 on\n[perf-walk] t=1s draw 400.0ms\n"
        text += block(2) + block(3, draw=380)
        phases = walker_ab.phases(self.file(text), 0, 10)
        self.assertEqual(phases[1]["draw"], 380)
        self.assertEqual(phases[0]["draw"], 400)
        self.assertEqual(phases[0]["flips"], 20)
        self.assertEqual(phases[1]["flips"], 20)

    def test_no_change_control_has_zero_contrasts_and_no_p_value(self):
        code, out = self.run_cli(self.file(log([400] * 7)), "--md")
        self.assertEqual(code, 0)
        self.assertIn("| draw ms/frame | 20.00 | 20.00 | +0.00 | +0.00 | 0/3 | +0.00 | 0/1 |", out)
        self.assertNotIn("sign p", out)
        self.assertIn("Descriptive only", out)

    def test_each_log_contributes_one_run_median(self):
        long = self.file(log([400, 360, 400, 360, 400, 360, 400]))
        short = self.file(log([400, 440, 400]))
        code, out = self.run_cli(long, short, "--md")
        self.assertEqual(code, 0)
        self.assertIn("| -2.00 | 3/4 | +0.00 | 1/2 |", out)
        self.assertIn("log count does not prove independent runs", out)

    def test_missing_neighbours_are_not_reported_as_zero_pairs(self):
        code, out = self.run_cli(self.file(log([400, 380])), "--md")
        self.assertEqual(code, 0)
        self.assertIn("| n/a | 0/0 | n/a | 0/0 |", out)

    def test_inverted_numbering_keeps_odd_phases_on(self):
        text = log([420, 380, 420])
        # Inverted runs begin at phase 1; parity remains the on/off contract.
        text = text.replace('phase=2 off', 'phase=3 on')
        text = text.replace('phase=1 on', 'phase=2 off')
        text = text.replace('phase=0 off', 'phase=1 on')
        code, out = self.run_cli(self.file(text))
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^draw ms/frame\s+19\.00\s+21\.00\s+\+2\.00")

    def test_empty_window_returns_failure(self):
        code, out = self.run_cli(self.file(log([420, 380, 420])), "--from", "100")
        self.assertEqual(code, 1)
        self.assertIn("no clean off and on", out)

    def test_window_and_existing_row_prefix(self):
        p = self.file(log([420, 380, 420, 380, 420, 380, 420]))
        code, out = self.run_cli(p)
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^draw ms/frame  *21.00  *19.00  *-2.00  *-2.00    3/3 ")
        self.assertEqual(walker_ab.phases(p, 3, 4)[1]["draw"], 380)


if __name__ == "__main__":
    unittest.main()
