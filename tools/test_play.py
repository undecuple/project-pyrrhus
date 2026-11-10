#!/usr/bin/env python3
"""Synthetic play-controller tests; no game, GPU or external services."""
# Adapted from Project Helghast by undecuple (MIT), https://github.com/undecuple/project-helghast.
# Controller tests only; KZ3 provenance/comparison integration is not imported.
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("play", ROOT / "tools/gameplay/play.py")
play = importlib.util.module_from_spec(spec)
spec.loader.exec_module(play)


class PlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run = self.root / "run"
        (self.run / "app").mkdir(parents=True)
        self.recipe = self.root / "scenario.json"

    def tearDown(self):
        self.tmp.cleanup()

    def scenario(self, steps):
        self.recipe.write_text(json.dumps(dict(schema=play.SCHEMA, name="test", steps=steps)))
        return self.recipe

    def test_schema_rejects_bad_inputs(self):
        for steps in [[], [{"id": "../escape", "op": "capture"}],
                      [{"id": "early", "op": "capture"}],
                      [{"id": "bad", "op": "wait", "text": "", "timeout": 1}],
                      [{"id": "bad", "op": "key", "button": True}],
                      [{"id": "bad", "op": "flips", "count": -1}],
                      [{"id": "bad", "op": "wait", "text": "a", "timeout": float('nan')}],
                      [{"id": "dup", "op": "wait", "text": "a"}, {"id": "dup", "op": "wait", "text": "b"}]]:
            with self.subTest(steps=steps), self.assertRaises(play.PlayError):
                play.load_scenario(self.scenario(steps))

    def test_tail_preserves_partial_and_same_chunk_lines(self):
        path = self.run / "app/app_stdout.txt"
        tail = play.LogTail(path)
        self.assertIsNone(tail.line())
        path.write_bytes(b"first\nsec")
        self.assertEqual(tail.line(), "first")
        self.assertIsNone(tail.line())
        with path.open('ab') as stream:
            stream.write(b"ond\nthird\n")
        self.assertEqual(tail.line(), "second")
        self.assertEqual(tail.line(), "third")
        self.assertIsNone(tail.line())
        path.write_bytes(b"x\n")
        with self.assertRaises(play.PlayError):
            tail.line()

    def test_waits_consume_only_through_match(self):
        recipe = self.scenario([dict(id='a', op='wait', text='PAGE_A'), dict(id='b', op='wait', text='PAGE_B')])
        (self.run / 'app/app_stdout.txt').write_text('PAGE_A\nPAGE_B\n')
        driver = play.Driver(recipe, self.run, 2)
        self.assertEqual(driver.run_steps(), 0)
        self.assertEqual([s['gate']['line'] for s in driver.report['steps']], ['PAGE_A', 'PAGE_B'])

    def test_timeouts_and_fatal_markers_fail_closed(self):
        for text in ('', '[CRASH] fault\n', '[crash] fault\n', 'EXCEPTION_ACCESS fault\n', '[exit code 0]\n'):
            with self.subTest(text=text), tempfile.TemporaryDirectory(dir=self.root) as temp:
                run = Path(temp); (run / 'app').mkdir()
                (run / 'app/app_stdout.txt').write_text(text)
                recipe = self.scenario([dict(id='gate', op='wait', text='NEVER', timeout=0.05)])
                driver = play.Driver(recipe, run, 0.1)
                self.assertEqual(driver.run_steps(), 1)
                self.assertEqual(json.loads((run / 'play.json').read_text())['status'], 'failed')

    def test_key_timeout_without_admission(self):
        recipe = self.scenario([dict(id='key', op='key', button='CROSS', timeout=0.05)])
        driver = play.Driver(recipe, self.run, 0.1)
        self.assertEqual(driver.run_steps(), 1)
        self.assertIn('acknowledgement', driver.report['error'])

    def test_stale_reports_and_input_are_rejected(self):
        recipe = self.scenario([dict(id='gate', op='wait', text='READY', timeout=0.05)])
        (self.run / 'play.json').write_text('existing evidence')
        with self.assertRaises(play.PlayError):
            play.Driver(recipe, self.run, 0.1).run_steps()
        self.assertEqual((self.run / 'play.json').read_text(), 'existing evidence')
        other = self.root / 'other'
        (other / 'app').mkdir(parents=True)
        (other / 'app/play-input.txt').write_text('old command')
        driver = play.Driver(recipe, other, 0.1)
        self.assertEqual(driver.run_steps(), 1)
        self.assertIn('stale command', driver.report['error'])

    def test_backwards_flip_counter_is_a_failed_play(self):
        recipe = self.scenario([dict(id='gate', op='wait', text='MISSING', timeout=0.1)])
        (self.run / 'app/app_stdout.txt').write_text('[flip] 10 at 100 ms\n[flip] 9 at 110 ms\n')
        driver = play.Driver(recipe, self.run, 0.2)
        self.assertEqual(driver.run_steps(), 1)
        self.assertIn('backwards', driver.report['error'])

    def test_complete_play_and_admission_race(self):
        recipe = self.scenario([
            dict(id='checkpoint', op='wait', text='CHECKPOINT_READY'),
            dict(id='settle', op='flips', count=20, timeout=3),
            dict(id='press1', op='key', button='R1', reports=4, timeout=3),
            dict(id='press2', op='key', button='R1', reports=4, timeout=3),
            dict(id='result', op='wait', text='ACTION_DONE', timeout=3),
            dict(id='image', op='capture')])
        stop, admissions = threading.Event(), []
        log = self.run / 'app/app_stdout.txt'
        log.write_text('CHECKPOINT_READY\n[flip] 10 at 1000 ms\n')

        def game():
            n = 10
            with log.open('a', buffering=1) as out:
                while not stop.is_set():
                    n += 10
                    out.write(f'[flip] {n} at {n * 100} ms\n')
                    channel = self.run / 'app/play-input.txt'
                    if channel.exists() and channel.read_text():
                        admissions.append(channel.read_text())
                        out.write('[cellPad] PAD_FILE press 0x0800\n')
                        if len(admissions) == 2:
                            out.write('ACTION_DONE\n')  # marker arrives before truncate
                        time.sleep(0.02)
                        channel.write_text('')
                    time.sleep(0.02)

        def capture(path, timeout):
            self.assertGreater(timeout, 0)
            path.write_bytes(b'\x89PNG\r\n\x1a\nsynthetic')

        thread = threading.Thread(target=game)
        thread.start()
        try:
            driver = play.Driver(recipe, self.run, 5, capture)
            self.assertEqual(driver.run_steps(), 0, driver.report)
        finally:
            stop.set(); thread.join(timeout=2)
        self.assertEqual(admissions, ['0x0800 4\n', '0x0800 4\n'])
        steps = driver.report['steps']
        self.assertGreaterEqual(steps[1]['after']['count'], steps[1]['before']['count'] + 20)
        self.assertFalse(driver.report['captures'][0]['exact_frame'])
        self.assertEqual(driver.report['trace_sha256'], play.digest(self.run / 'play.jsonl'))
        with self.assertRaises(play.PlayError):
            play.Driver(recipe, self.run, 1, capture).run_steps()

    def test_capture_failure_is_not_success(self):
        recipe = self.scenario([dict(id='gate', op='wait', text='READY'), dict(id='image', op='capture')])
        (self.run / 'app/app_stdout.txt').write_text('READY\n[flip] 10 at 1000 ms\n')
        driver = play.Driver(recipe, self.run, 1, lambda p, _: p.write_bytes(b''))
        self.assertEqual(driver.run_steps(), 1)
        self.assertEqual(driver.report['captures'], [])


if __name__ == '__main__':
    unittest.main()
