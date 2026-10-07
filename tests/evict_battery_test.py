#!/usr/bin/env python3
"""Serverless negative controls for the actual lruclock battery section."""
import ast
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class LruClockBattery(unittest.TestCase):
    def run_section(self, broken_key=None, fallback_attempts=0, clock_advanced=True,
                    publication_lag=0):
        tree = ast.parse(Path(__file__).with_name('evict_battery.py').read_text())
        section = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                       and isinstance(node.test, ast.Compare)
                       and isinstance(node.test.left, ast.Name) and node.test.left.id == 'SECTION'
                       and node.test.comparators[0].value == 'lruclock')
        code = compile(ast.Module(body=section.body, type_ignores=[]), 'evict_battery.py', 'exec')
        meta, checks, reads = {}, [], []
        lane_hits = pressure = 0
        no_touch = False
        elapsed = [0.0]
        eviction_polls = 0
        tick = int(clock_advanced)

        def cmd(*args):
            nonlocal lane_hits, no_touch
            name = args[0]
            if name == 'CONFIG':
                return b'+OK'
            if name == 'SET':
                meta[args[1]] = 0
                return b'+OK'
            if name == 'CLIENT':
                no_touch = args[-1] == 'ON'
                return b'+OK'
            if name == 'OBJECT':
                return b':%d' % ((tick - meta[args[-1]]) * 256)
            if name == 'GET':
                key = args[1]
                reads.append((key, no_touch))
                index = int(key.split(':')[1]) if key.startswith('lruold:') else -1
                fallback = not no_touch and 0 <= index < fallback_attempts * 50 and not pressure
                lane_hits += int(not fallback)
                if not no_touch and (key != broken_key or fallback):
                    meta[key] = tick
                return b'v' * (100 if key.startswith('lruold:') else 1)
            if args == ('DBSIZE', 'NOW'):
                return b':7488'  # 9002 accepted writes minus 1514 evictions.
            self.fail('unexpected command %r' % (args,))

        def cmd_on(conn, file, *args):
            nonlocal lane_hits
            if args[0] == 'CLIENT':
                return b'+OK'
            self.assertEqual(args, ('GET', 'lruc:no-touch'))
            lane_hits += 1
            return b'v'

        def fill(prefix, count, **kwargs):
            nonlocal pressure
            if prefix == 'lruold':
                meta.update(('lruold:%d' % i, 0) for i in range(count))
            else:
                pressure += count
            return 0

        def info_num(field):
            nonlocal eviction_polls
            if field == 'evicted_keys' and pressure:
                eviction_polls += 1
                return 1513 if eviction_polls <= publication_lag else 1514
            return {'read_local': 1, 'read_local_keyspace_hits': lane_hits,
                    'evicted_keys': 1514 if pressure else 0}[field]

        def sleep(seconds):
            elapsed[0] += seconds

        env = dict(cmd=cmd, must=cmd, cmd_on=cmd_on, fill=fill, info_num=info_num,
                   open_conn=lambda: (Mock(), None), as_int=lambda reply: int(reply[1:]),
                   check=lambda name, ok, detail='': checks.append((name, bool(ok))),
                   alive=lambda prefix, indices: 49 if indices.start < 150 else 25,
                   MM='1048576', time=SimpleNamespace(monotonic=lambda: elapsed[0], sleep=sleep))
        with contextlib.redirect_stdout(io.StringIO()):
            exec(code, env)
        return checks, reads

    def test_49_survivors_do_not_replace_the_exact_fifty_metadata_assertion(self):
        checks, _ = self.run_section()
        self.assertTrue(all(ok for _, ok in checks), checks)
        self.assertTrue(any('all 50 re-read keys reset' in name for name, _ in checks))

    def test_one_missing_lane_touch_fails_even_with_successful_pressure(self):
        checks, _ = self.run_section(broken_key='lruold:17')
        failed = [name for name, ok in checks if not ok]
        self.assertIn('lruclock: all 50 re-read keys reset IDLETIME before eviction', failed)
        self.assertEqual(len(failed), 2)  # Reset and strictly older-cohort assertions.

    def test_dispatch_fallback_rearms_on_fresh_old_keys(self):
        checks, reads = self.run_section(fallback_attempts=1)
        self.assertTrue(all(ok for _, ok in checks), checks)
        self.assertIn(('lruold:50', False), reads)
        # A touch defect on the new cohort remains observable after an invalid first arm.
        checks, _ = self.run_section(fallback_attempts=1, broken_key='lruold:67')
        self.assertTrue(any(not ok for _, ok in checks))

    def test_no_lane_window_is_a_bounded_failure(self):
        with self.assertRaisesRegex(AssertionError, 'no fully lane-served touch window in 3'):
            self.run_section(fallback_attempts=3)

    def test_unchanged_clock_cannot_arm(self):
        with self.assertRaisesRegex(AssertionError, 'never armed in an old bucket'):
            self.run_section(clock_advanced=False)

    def test_eviction_counter_publication_can_lag_but_count_must_converge(self):
        checks, _ = self.run_section(publication_lag=3)
        self.assertTrue(all(ok for _, ok in checks), checks)

    def test_one_unaccounted_write_fails_after_bounded_publication_wait(self):
        checks, _ = self.run_section(publication_lag=10000)
        failed = [name for name, ok in checks if not ok]
        self.assertEqual(failed, ['lruclock: every pressure write is accounted for'])


if __name__ == '__main__':
    unittest.main()
