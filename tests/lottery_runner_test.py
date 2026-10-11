#!/usr/bin/env python3
"""Serverless controls for witnessed stopping, verdicts, and confidence bounds."""
import math
import random
import unittest
from lottery_runner import DEFAULT_HITS, Tally, registry, repeat, upper_bound


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
        self.assertEqual({r['id'] for r in rows if r['family'] == 'multi_exec'},
                         {'131', '165', '200', '207', '214', '249', '357'})


if __name__ == '__main__':
    unittest.main()
