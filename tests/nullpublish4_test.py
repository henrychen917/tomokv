#!/usr/bin/env python3
"""Serverless holdout controls using campaign 7's nonconstant raw samples."""
import copy
import gzip
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import abbagate as abba
import abba_holdout as holdout
from abba_evidence import null_resolution, match_null, validate_holdout, utc_seconds
import abba_standing_null as standing
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
            run[cell.metric] = bound['reference_mean'] + (bound['quantum'] if run['arm'] == 'B' else 0)
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


class PublicationControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from datetime import datetime, timezone
        cls.control = standing.read_null(ROOT / 'tests/standing-null/current.json')
        cls.comparison = copy.deepcopy(dict(cls.control))
        report = cls.comparison
        report.pop('null_control')
        report.pop('null_sampling_policy')
        report.pop('promotion')
        for row in report['cells']:
            row['holdout_repeats'] = row.pop('null_repeats')
            row.pop('null_sampling_plan')
        # This is a serverless routing fixture, never independent measured data.
        shift = int(report['elapsed_seconds']) + 2
        report['started_utc'] = datetime.fromtimestamp(utc_seconds(report['started_utc']) + shift,
                                                       timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        for field in ('started_at', 'finished_at'):
            report['quiet_box'][field] += shift
        holdout.rejudge(report, cls.control)
        cls.now = utc_seconds(report['started_utc']) + report['elapsed_seconds'] + 1

    def test_archive_matches_without_access_to_campaign_worktree(self):
        original = Path.read_bytes
        def confined(path):
            self.assertTrue(path.resolve().is_relative_to(ROOT),
                            'tracked null must not read the campaign worktree')
            return original(path)
        with mock.patch.object(Path, 'read_bytes', new=confined):
            matched = match_null(self.comparison, self.control, now=self.now)
            self.assertEqual(matched['status'], 'MATCHED')
            report = {**self.comparison, 'standing_null': matched}
            self.assertEqual(validate_holdout(report, self.control, now=self.now)['verdict'], 'PASS')
        self.assertEqual(len(matched['matched_ids']), 181)
        self.assertEqual(self.control.receipt['independent_resolution'], 'PENDING HOLDOUT')

    def test_stale_fingerprint_inventory_and_age_are_explicit_refusals(self):
        from abba_instrument import instrument_fingerprint
        from datetime import datetime, timezone
        changed = {**self.comparison, 'instrument_fingerprint': instrument_fingerprint(ROOT)}
        with self.assertRaisesRegex(ValueError, 'null instrument differs'):
            match_null(changed, self.control, now=self.now)
        changed = {**self.comparison, 'cell_source': {**self.comparison['cell_source'], 'sha256': '0' * 64}}
        with self.assertRaisesRegex(ValueError, 'null inventory differs'):
            match_null(changed, self.control, now=self.now)
        changed = {**self.comparison, 'quiet_box': copy.deepcopy(self.comparison['quiet_box'])}
        changed['started_utc'] = datetime.fromtimestamp(utc_seconds(changed['started_utc']) + 90000,
                                                       timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        for field in ('started_at', 'finished_at'):
            changed['quiet_box'][field] += 90000
        with self.assertRaisesRegex(ValueError, 'more than 24 hours old'):
            match_null(changed, self.control, now=self.now + 90000)

    def test_tracked_default_and_retained_receipt_ignore_stale_local_null(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as tmp:
            root = Path(tmp)
            path = root / 'tests/standing-null/current.json'
            path.parent.mkdir(parents=True)
            standing.retain(self.control, path)
            stale = root / '.gate-history/receipts/baselines/full-null.json'
            stale.parent.mkdir(parents=True)
            stale.write_text('{"stale":true}')
            self.assertEqual(standing.default_path(root), path)
            loaded = standing.read_null(path)
            self.assertEqual(loaded, self.control)
            self.assertEqual(loaded.artifacts, self.control.artifacts)
            blob = path.parent / loaded.receipt['null']['path']
            blob.write_bytes(blob.read_bytes() + b'broken')
            with self.assertRaisesRegex(ValueError, 'compressed artifact changed'):
                standing.read_null(path)


def self_test():
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                               for cls in (HoldoutControls, PublicationControls))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    os.sched_setaffinity(0, set(range(112, 128)))
    raise SystemExit(self_test())
