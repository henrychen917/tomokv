#!/usr/bin/env python3
"""Serverless holdout controls using campaign 7's nonconstant raw samples."""
import copy
import gzip
import json
import os
from pathlib import Path
import unittest

import abbagate as abba
import abba_holdout as holdout
from abba_evidence import null_resolution
from _nullrefresh_test import throwaway

ROOT = Path(__file__).resolve().parents[1]


class HoldoutControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(gzip.decompress((ROOT / 'tests/fixtures/nullpublish-campaign7-samples.json.gz').read_bytes()))
        cls.control = cls.fixture['null']
        cls.saved = cls.fixture['holdout']

    def row(self, ident, source=None):
        return copy.deepcopy(next(row for row in (source or self.saved)['cells'] if row['cell']['id'] == ident))

    def test_campaign7_real_replay_names_all_outside_floors(self):
        report = holdout.rejudge(copy.deepcopy(self.saved), self.control)
        result = holdout.resolution(report, self.control, historical=True)
        failed = [row['cell'] for row in result['failures']]
        self.assertEqual(failed, self.fixture['expected']['failed_cells'])
        self.assertEqual(len(failed), 86)
        old = {row['cell']['id'] for row in self.saved['cells'] if row['verdict'] == 'FAIL'}
        self.assertEqual((len(old), len(old & set(failed))), (38, 27))
        self.assertEqual(result['plan_differences'], self.fixture['expected']['plan_differences'])
        self.assertEqual(result['independent_resolution'], 'PENDING HOLDOUT')
        self.assertFalse(result['full_gate_receipt'])

    def test_published_spread_makes_real_t02_pass_and_removing_it_fails_assertion(self):
        row = self.row('t02')
        self.assertEqual(row['verdict'], 'FAIL')
        cell = abba.Cell(**row['cell'])
        def assertion():
            result = holdout.assess(cell, row, self.control)
            self.assertEqual(result['verdict'], 'PASS', 't02 must be within its published floor')
            self.assertEqual(result['threshold_source'], holdout.CONTRACT)
        assertion()
        with throwaway(holdout, 'floors', 'max(values["abs_delta"], values["spread"], quantum_pct)',
                       'max(values["abs_delta"], quantum_pct)'):
            with self.assertRaisesRegex(AssertionError, 't02 must be within its published floor'):
                assertion()

    def test_two_sided_drift_and_spread_use_same_immutable_floor(self):
        row = self.row('t02')
        cell = abba.Cell(**row['cell'])
        threshold = holdout.floors(self.control, cell.id)[cell.metric]['threshold_pct']
        for sign in (-1, 1):
            changed = copy.deepcopy(row)
            for run in changed['rounds'][0]['runs']:
                run[cell.metric] = 1. + sign * threshold / 50 if run['arm'] == 'B' else 1.
            def assertion():
                result = holdout.assess(cell, changed, self.control)
                self.assertEqual(result['threshold_pct'], threshold)
                self.assertEqual(result['verdict'], 'FAIL', 'both signs outside the published floor must FAIL')
            assertion()
            with throwaway(holdout, 'assess', 'metric["absolute_delta_pct"] <= threshold', 'True'):
                with self.assertRaisesRegex(AssertionError, 'both signs outside'):
                    assertion()
        changed = copy.deepcopy(row)
        changed['rounds'][0]['runs'][0][cell.metric] *= 2
        result = holdout.assess(cell, changed, self.control)
        self.assertEqual(result['threshold_pct'], threshold)
        self.assertFalse(result['measurement_valid'])
        self.assertTrue(any('spread exceeds published floor' in reason for reason in result['reasons']))

    def test_zero_floor_gets_a_metric_quantum_from_published_samples_only(self):
        row = self.row('m25')
        cell = abba.Cell(**row['cell'])
        bound = holdout.floors(self.control, cell.id)[cell.metric]
        self.assertEqual((bound['abs_delta'], bound['spread']), (0., 0.))
        self.assertGreater(bound['threshold_pct'], 0)
        self.assertEqual(bound['quantum'], .001)
        tail = holdout.floors(self.control, 't02')['p999_ms']
        self.assertEqual(tail['quantum'], .008)
        self.assertEqual(holdout.quantum('p999_ms', [dict(p999_ms=2.055)]), .016)
        for run in row['rounds'][0]['runs']:
            run[cell.metric] = bound['reference_mean'] + (bound['quantum'] / 2 if run['arm'] == 'B' else 0)
        self.assertEqual(holdout.assess(cell, row, self.control)['verdict'], 'PASS')
        # The actual m25 holdout moved by more than one quantum: no free PASS.
        self.assertEqual(holdout.assess(cell, self.row('m25'), self.control)['verdict'], 'FAIL')

    def test_plan_is_copied_not_refitted_and_cap_is_visible(self):
        plan = holdout.plan(self.control)
        self.assertEqual(sum(value['planned_blocks'] for value in plan.values()), 249)
        self.assertEqual(sum(value['planned_blocks'] > 1 for value in plan.values()), 50)
        self.assertTrue(all(value['samples_per_arm_per_block'] == 2 and value['maximum_blocks'] == 4
                            for value in plan.values()))
        self.assertEqual(sum(value['budget_limited'] for value in plan.values()), 8)

    def test_all_planned_repeats_finish_even_after_an_outside_floor_block(self):
        row = self.row('t02')
        cell = abba.Cell(**row['cell'])
        expected = holdout.plan(self.control)[cell.id]
        persisted, calls = [], []
        def persist():
            persisted.append(len(row.get('holdout_repeats', [])))
        def measure(arm, sequence, instances):
            self.assertTrue(persisted, 'holdout plan must be persisted before repeats')
            calls.append((arm, sequence, instances))
            return copy.deepcopy(row['rounds'][0]['runs'][(sequence - 1) % len(abba.ORDER)])
        def assertion():
            calls.clear()
            holdout.collect(cell, row, self.control, measure, persist)
            self.assertEqual(len(calls), (expected['planned_blocks'] - 1) * 4,
                             'holdout must finish the published block count')
            self.assertEqual([call[1] for call in calls], list(range(5, 17)))
        assertion()
        with throwaway(holdout, 'collect', 'range(1, expected["planned_blocks"])', 'range(1, 2)'):
            with self.assertRaisesRegex(AssertionError, 'published block count'):
                assertion()

    def test_every_cell_inside_floors_makes_overall_pass_without_reclassifying_null(self):
        # Positive routing control only: reusing these samples is NOT independent
        # evidence. The CLI replay keeps PENDING HOLDOUT for exactly this reason.
        report = copy.deepcopy(self.control)
        for row in report['cells']:
            row['holdout_repeats'] = row.pop('null_repeats', [])
            row.pop('null_sampling_plan', None)
        holdout.rejudge(report, self.control)
        self.assertEqual(report['statistical_verdict'], 'PASS', 'within-floor holdout must reach PASS')
        self.assertEqual(holdout.resolution(report, self.control)['verdict'], 'PASS')
        self.assertFalse(report['comparison_trusted'])
        self.assertEqual(null_resolution(self.control), self.control['null_control']['resolution'],
                         'published null classification must remain bit-exact')


def self_test():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HoldoutControls)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    os.sched_setaffinity(0, set(range(112, 128)))
    raise SystemExit(self_test())
