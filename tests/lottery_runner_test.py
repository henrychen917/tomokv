#!/usr/bin/env python3
"""Serverless controls for witnessed stopping, verdicts, and confidence bounds."""
import math
import json
import random
import unittest
from lottery_runner import DEFAULT_HITS, ROOT, Tally, registry, repeat, upper_bound


def receipt(hit=1, passed=True, **kwargs):
    return dict(completed=True, passed=passed, evidence_complete=True,
                counters={'W': hit}, **kwargs)


class RunnerTests(unittest.TestCase):
    def test_known_quarter_rate_counts_attempts_not_events(self):
        now = [0]
        def fake(index, remaining):
            now[0] += 1
            return receipt(1000 if index % 4 == 0 else 0)
        r = repeat(fake, ['W'], 20, 100, clock=lambda: now[0])
        self.assertEqual((r['verdict'], r['attempts'], r['hits']), ('PASS', 80, 20))
        self.assertEqual(r['hit_rate'], .25)
        self.assertAlmostEqual(r['upper_95'], 1 - .05 ** (1 / 20))

    def test_failure_on_a_hit_stops_and_cannot_be_retried_away(self):
        r = repeat(lambda *a: receipt(passed=False), ['W'], 20, 10)
        self.assertEqual((r['verdict'], r['hits'], r['hit_failures']), ('FAIL', 1, 1))

    def test_failure_on_miss_also_fails(self):
        r = repeat(lambda *a: receipt(0, False), ['W'], 20, 10)
        self.assertEqual((r['verdict'], r['hits']), ('FAIL', 0))
        self.assertIsNone(r['upper_95'])

    def test_never_opens_is_insufficient(self):
        now = [0]
        def fake(*args):
            now[0] += 1
            return receipt(0)
        r = repeat(fake, ['W'], 20, 7, clock=lambda: now[0])
        self.assertEqual((r['verdict'], r['attempts'], r['hits']), ('INSUFFICIENT', 7, 0))

    def test_all_witnesses_required(self):
        t = Tally(('W', 'X'))
        r = receipt()
        r['counters']['X'] = 0
        self.assertFalse(t.add(r))
        r['counters']['X'] = 1
        self.assertTrue(t.add(r))
        self.assertEqual(t.hits, 1)

    def test_missing_negative_bool_or_bad_counter_is_error(self):
        for value in (None, -1, True, '1', 1.2):
            t = Tally(('W',))
            t.add(receipt(value))
            self.assertEqual(t.result(1)['verdict'], 'ERROR')

    def test_timeout_cannot_hit_or_pass(self):
        t = Tally(('W',))
        r = receipt(100)
        r['completed'] = False
        t.add(r)
        self.assertEqual((t.hits, t.result(1)['verdict']), (0, 'INSUFFICIENT'))

    def test_missing_verdict_cannot_pass(self):
        t = Tally(('W',), goal=1)
        r = receipt()
        del r['passed']
        t.add(r)
        self.assertEqual(t.result(1)['verdict'], 'ERROR')

    def test_cap_stops_new_attempts_but_never_cuts_one_short(self):
        now = [0]
        def slow(index, remaining):
            self.assertGreater(remaining, 0)
            now[0] += 40          # each attempt outlives the remaining cap
            return receipt(int(index % 2 == 1))
        r = repeat(slow, ['W'], 20, 100, clock=lambda: now[0])
        # Attempts start at t=0, 40, 80; none starts at t=120 >= cap.
        self.assertEqual((r['verdict'], r['attempts'], r['hits']), ('INSUFFICIENT', 3, 2))
        self.assertEqual(r['mean_attempt_seconds'], 40)
        self.assertEqual(r['estimated_attempts_for_k'], 30)
        self.assertEqual(r['estimated_seconds_for_k'], 1200)

    def test_k_hits_stop_immediately_with_rule_of_three_bound(self):
        calls = []
        def always(index, remaining):
            calls.append(index)
            return receipt()
        r = repeat(always, ['W'], DEFAULT_HITS, 1e9)
        self.assertEqual((r['verdict'], r['attempts'], len(calls)), ('PASS', 20, 20))
        # Exact one-sided 95% bound for 0/20 is 13.9%; the rule of three says 3/K = 15%.
        self.assertTrue(r['bound_fixed_k'])
        self.assertAlmostEqual(r['upper_95'], 1 - .05 ** (1 / DEFAULT_HITS))
        self.assertTrue(2.7 / DEFAULT_HITS < r['upper_95'] < 3 / DEFAULT_HITS)

    def test_exact_bounds(self):
        self.assertAlmostEqual(upper_bound(1), .95)
        self.assertAlmostEqual(upper_bound(20), .13910834066826516)
        self.assertAlmostEqual(upper_bound(10, 1), .3941633024365047)
        self.assertEqual(upper_bound(10, 10), 1)
        self.assertIsNone(upper_bound(0))
        self.assertAlmostEqual(upper_bound(1000000), -math.expm1(math.log(.05) / 1000000))

    def test_seeded_fake_rate(self):
        rng = random.Random(91)
        def fake(*args):
            return receipt(int(rng.random() < .25))
        r = repeat(fake, ['W'], 1000, 10)
        self.assertEqual(r['verdict'], 'PASS')
        self.assertTrue(.22 < r['hit_rate'] < .28)

    def test_inventory(self):
        rows = registry()
        self.assertEqual(len(rows), 58)
        self.assertEqual(DEFAULT_HITS, 20)
        mechanisms = json.loads((ROOT / 'docs/flakeaudit2/triage.json').read_text())['mechanisms']
        expected = {str(i) for m in mechanisms if m['category'] == 'B' for i in m['rows']}
        self.assertEqual({r['id'] for r in rows}, expected)
        self.assertEqual({r['id'] for r in rows if r['family'] == 'multi_exec'},
                         {'131', '165', '200', '207', '214', '249', '357'})


class DriverTests(unittest.TestCase):
    """The battery driver, serverless: marker insertion and observer connections."""

    def run_driver(self, family, source):
        import os
        import sys
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import lottery_test_driver as driver
        calls = []

        class FakeConn:
            def __init__(self, host, port):
                calls.append(('open', port))

            def must(self, *command):
                calls.append(command)
                return b'OK'

            def close(self):
                calls.append(('close',))

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'battery.py'
            path.write_text(source)
            with patch.dict(os.environ, LOTTERY_PORT='25399', LOTTERY_FAMILY=family), \
                    patch.object(driver, 'Conn', FakeConn), \
                    patch.object(sys, 'argv', ['driver', str(path)]):
                driver.main()
        return calls

    def test_expiry_sections_are_marked_in_order_on_short_lived_connections(self):
        names = ('test_fanout_hook', 'test_transaction_family', 'test_script_clock',
                 'test_ordinary_expiry_still_works')
        source = ''.join(f'def {name}(conn): pass\n' for name in names)
        source += 'def main():\n    conn = None\n    if conn is None:\n'
        source += ''.join(f'        {name}(conn)\n' for name in names) + 'main()\n'
        calls = self.run_driver('expwide', source)
        marks = [c[3] for c in calls if c[:3] == ('DEBUG', 'LOTTERY', 'MARK')]
        self.assertEqual(marks, ['expiry_section_fanout', 'expiry_section_exec',
                                 'expiry_section_script', 'expiry_section_ordinary'])
        # Every observer connection opens, sends one command and closes.
        self.assertEqual(calls, [c for mark in marks for c in
                                 (('open', 25399), ('DEBUG', 'LOTTERY', 'MARK', mark), ('close',))])

    def test_config_probe_follows_only_propagation_sleeps(self):
        source = 'import time\ntime.sleep(0.01)\ntime.sleep(0.06)\n'
        calls = self.run_driver('blocking', source)
        self.assertEqual(calls, [('open', 25399), ('DEBUG', 'LOTTERY', 'CONFIG'), ('close',)])

    def test_changed_battery_anchor_refuses_to_run(self):
        with self.assertRaisesRegex(ValueError, 'changed expiry section anchor'):
            self.run_driver('expwide', 'pass\n')


class CalibrationTests(unittest.TestCase):
    def result(self, row, attempts, hits, seconds, witnesses=None):
        return dict(row=dict(id=row), verdict='INSUFFICIENT', attempts=attempts, hits=hits,
                    failures=0, errors=0, incomplete=0, seconds=seconds,
                    witness_attempts=witnesses or {})

    def test_rate_limited_rows_name_their_pause_point(self):
        from lottery_calibration import calibrate
        rows = {r['id']: r for r in calibrate({
            '131': self.result('131', 40, 2, 120, {'W16': 2}),    # 3 s/attempt, 5% hits
            '130': self.result('130', 3, 3, 120, {'W3': 3}),      # 40 s/attempt, all hits
            '139': self.result('139', 30, 30, 60),                # 2 s/attempt, all hits
            '368': self.result('368', 10, 0, 100, {'W11': 0}),    # never hit
        }, 20, 600)}
        self.assertEqual((rows['131']['attempts_for_k'], rows['131']['seconds_for_k']), (400, 1200))
        self.assertEqual((rows['131']['limited_by'], rows['131']['limiting_witness']),
                         ('hit rate', 'W16'))
        self.assertIn('W16', rows['131']['pause_point'])
        self.assertEqual(rows['130']['limited_by'], 'attempt length')
        self.assertTrue(rows['139']['reaches_k_in_budget'])
        self.assertNotIn('pause_point', rows['139'])
        self.assertEqual(rows['368']['limited_by'], 'hit rate')
        self.assertAlmostEqual(rows['368']['hit_rate_upper95'], 1 - .05 ** .1)
        self.assertFalse(rows['164']['measured'])


if __name__ == '__main__':
    unittest.main()
