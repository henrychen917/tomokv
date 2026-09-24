"""Serverless full-campaign fixtures and mechanism-removal controls.

Every binary here is an identity artifact and is NEVER executed. CPU geometry
is metadata; only topology is read. These are not measured results or receipts.
"""
import argparse
import copy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

import abbagate as abba
import abba_evidence as evidence
import gate_measurements as measurements
import gate_receipt as receipt
from abba_instrument import instrument_fingerprint
from abba_saturation import saturation_exempt
from abba_workloads import workload_command_names, require_workload_witness, require_workload_accounting
from _abba_test_fixtures import quiet_record, saturation_record

ROOT = Path(__file__).resolve().parents[1]


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def raw_run(cell, arm, n, sequence, env, *, fast=False, score=None):
    window = 10 if fast else 20
    names = workload_command_names(cell)
    before = {f'cmdstat_{name.lower()}': 'calls=0,usec=0' for name in names}
    after = {f'cmdstat_{name.lower()}': 'calls=100,usec=100' for name in names}
    modes = {'reorder_retired': '1', 'reorder': '0'} if cell.op == 'REORDER' else {}
    layout = abba.load_layout(env['load_cpus'], n, cell.conns)
    # Distribute exactly 100 completed commands per command over the generators.
    totals = []
    for i, placement in enumerate(layout):
        counts = {name: 100 // n + int(i < 100 % n) for name in names}
        conns = placement['threads'] * placement['clients']
        totals.append(dict(connections=conns, outstanding_bound=conns * cell.depth,
                           reported_counts=counts, completed_hdr_counts=counts))
    result = dict(arm=arm, instances=n, complete=True, pid=123, rate=100., busy_pct=99.,
        latency_ms=1., p999_ms=2., long_p999_ms=3., commands=2000,
        midpoint_monotonic=1 + window / 2, window_seconds=window,
        artifacts=f'{cell.id}/n{n}-{sequence}-{arm}', load_layout=layout,
        saturation=saturation_record(cell.mode, score=(1 if saturation_exempt(cell) else 99) if score is None else score,
                                     threads=len(env['server_cpus']), window_seconds=window),
        workload_raw=dict(before=before, after=after, mode_before=modes, mode_after=modes, legacy_control=None),
        workload_witness=require_workload_witness(cell, before, after, modes, modes),
        whole_run_commandstats_before=before, whole_run_commandstats_after=after, memtier=totals,
        whole_run_accounting=require_workload_accounting(cell, before, after, totals))
    if fast:
        result.update(calibration_only=True, population_reused=sequence > 1)
    return result


def fixture_report(cells, fingerprint, env, source, started, binary, *, fast=False):
    rows = []
    for cell in cells:
        counts = ([cell.instances or 1] if saturation_exempt(cell) else [1, 2]) if fast else [cell.instances or 1]
        rounds = [dict(instances=n, runs=[raw_run(cell, arm, n, rung + 1 if fast else i, env, fast=fast)
                   for i, arm in enumerate(['B'] if fast else abba.ORDER, 1)]) for rung, n in enumerate(counts)]
        row = dict(cell=asdict(cell), rounds=rounds)
        if fast:
            row['status'] = 'EXEMPT' if saturation_exempt(cell) else 'PIN'
        else:
            row.update(verdict='PASS', assessment=abba.assess(cell, rounds, abba.NULL_MODE))
        rows.append(row)
    elapsed = max(100., sum(len(row['rounds']) * (10 if fast else 80) for row in rows) + 100)
    report = dict(schema=1, run_kind='load-calibration' if fast else 'null-control',
        verdict=('EXEMPT' if all(saturation_exempt(c) for c in cells) else 'PIN') if fast else 'PARTIAL',
        complete=True, process_cleanup=dict(complete=True, remaining=0),
        measurement_valid=not fast, comparison_trusted=False, normal_gate_eligible=not fast,
        subset='full', only='', escalate=False, order=['B'] if fast else list(abba.ORDER),
        window_seconds=10 if fast else 20, elapsed_seconds=elapsed, started_utc=stamp(started),
        candidate=copy.deepcopy(binary), reference=copy.deepcopy(binary),
        receipt_harness_sha256='a' * 64, instrument_fingerprint=copy.deepcopy(fingerprint),
        cell_source=dict(text=source, sha256=evidence.digest(source.encode()), total_cells=len(cells)),
        coverage=abba.coverage(cells), cells=rows, environment=copy.deepcopy(env),
        quiet_box=quiet_record(cpus=env['server_cpus'] + env['load_cpus'], server_physical_cores=len(env['server_physical']),
            started_at=started + 1, finished_at=started + elapsed - 1, samples=int(elapsed) - 2))
    if fast:
        report['environment']['population_by_arm'] = {'B': 'wire'}
    else:
        report['statistical_verdict'] = 'PASS'
        report['null_control'] = evidence.null_result(report, now=time.time())
    return report


class PromotionControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='nullrefresh-controls-', dir=ROOT / 'build')
        cls.root = Path(cls.tmp.name)
        receipt.git(cls.root, 'init', '-q')
        (cls.root / '.gitignore').write_text('/build/\n/.gate-history/\n')
        (cls.root / 'build').mkdir()
        cls.fp = instrument_fingerprint(ROOT)
        for row in cls.fp['entries']:
            target = cls.root / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / row['path'], target)
        shutil.copy2(ROOT / 'tests/headline_cells.txt', cls.root / 'tests/headline_cells.txt')
        binary = cls.root / 'build/frozen-server'
        shutil.copy2(shutil.which('true'), binary)  # ELF identity fixture, never run.
        cls.binary = dict(path=str(binary), sha256=receipt.object_file(binary)[1])
        cls.env = dict(uname=list(os.uname()), python_runtime=cls.fp['python'],
            server_physical=list(range(32)), server_smt=[], server_cpus=list(range(32)),
            load_physical=list(range(32, 112)), load_smt=list(range(160, 240)),
            load_cpus=list(range(32, 112)) + list(range(160, 240)), split_ratio='16:16',
            port=8700, permitted_ports=[8700], load_instance_ceiling=16,
            keys=2000000, data_bytes=64, key_pattern='P:P', atomic='per-cell', split_flip_auto=0,
            memtier_path=str(binary), memtier_sha256=cls.binary['sha256'], memtier_version='identity fixture; never executed',
            population_by_arm={'A': 'wire', 'B': 'wire'})
        config = measurements.load()
        cells = abba.read_cells(ROOT / 'tests/headline_cells.txt')
        config['load_floors'] = {}
        for cell in cells:
            if not saturation_exempt(cell):
                config['load_floors'][cell.id] = dict(instances=1, shape=measurements.shape(cell),
                    geometry=measurements.geometry(cls.env), instrument_sha256=cls.fp['sha256'], status='calibrated',
                    observed_rate=dict(unit='ops_per_second', order=['B'], values=[100.]),
                    observed_busy=dict(unit='percent', order=['B'], values=[99.]),
                    provenance=dict(when='synthetic', how='serverless fixture, no measurement'))
        receipt.write_json(cls.root / 'tests/gate_measurements.json', config)
        cls.env['measurements_sha256'] = receipt.digest((cls.root / 'tests/gate_measurements.json').read_bytes())
        cls.inv = receipt.inventory(cls.root, cls.root / 'tests/headline_cells.txt')
        cls.started = int(time.time()) - 34000
        cls.campaign = dict(schema=1, kind='frozen-null-campaign', frozen_at=cls.started - 1,
            instrument=cls.fp, inventory=cls.inv, environment=cls.env,
            measurements_sha256=cls.env['measurements_sha256'], window_seconds=20,
            binary=cls.binary, generator=dict(path=str(binary), sha256=cls.binary['sha256']))
        cls.report = fixture_report([abba.Cell(**c) for c in cls.inv['cells']], cls.fp, cls.env,
            (cls.root / 'tests/headline_cells.txt').read_text(), cls.started, cls.binary)
        cls.campaign_path = cls.root / 'build/campaign.json'
        receipt.write_json(cls.campaign_path, cls.campaign)
        cls.source = cls.root / 'build/results.json'
        for arm in 'AB':
            shutil.copy2(binary, cls.source.parent / f'binary-{arm}')
        cls.args = argparse.Namespace(null_result=cls.source, campaign=cls.campaign_path)
        cls.standing = receipt.history_directory(cls.root) / 'baselines/full-null.json'

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        receipt.write_json(self.source, self.report)
        self.standing.parent.mkdir(parents=True, exist_ok=True)
        self.standing.write_bytes(b'previous good default must survive refusal\n')

    def test_absent_and_stale_prior_null_bootstrap_without_receipt(self):
        for prior in (None, b'{"started_utc":"2000-01-01T00:00:00Z"}'):
            with self.subTest(prior=prior):
                self.standing.unlink(missing_ok=True)
                if prior is not None:
                    self.standing.write_bytes(prior)
                self.assertEqual(receipt.promote_null(self.root, self.args), self.standing)
                result = receipt.read_json(self.standing)
                self.assertEqual((result['verdict'], result['comparison_trusted']), ('PARTIAL', False))
                self.assertEqual(receipt.read_json(self.source), self.report)
                self.assertTrue(list((self.standing.parent.parent / 'null-promotions').glob('*/*.promotion.json')))
                self.assertFalse(list((self.standing.parent.parent / 'runs').glob('*/receipt.json')))
                with self.assertRaisesRegex(ValueError, 'comparison is partial'):
                    evidence.validate_comparison(result, result, now=time.time())
                with self.assertRaisesRegex(ValueError, 'trusted comparison'):
                    receipt.validate_abba(result, dict(inventory=self.inv, instrument=self.fp), now=time.time())
        # Restore receipt-only publication: the positive bootstrap assertion must fail.
        with mock.patch.object(receipt, 'promote_null', side_effect=ValueError('receipt-only publication needs prior comparison')):
            with self.assertRaisesRegex(ValueError, 'receipt-only'):
                receipt.promote_null(self.root, self.args)

    def rejection(self, report, message):
        receipt.write_json(self.source, report)
        before = self.standing.read_bytes()
        with self.assertRaisesRegex((ValueError, RuntimeError), message):
            receipt.promote_null(self.root, self.args)
        self.assertEqual(self.standing.read_bytes(), before, message)

    def test_mutations_reject_before_replacing_previous_default(self):
        rate_index = next(i for i, row in enumerate(self.report['cells']) if not saturation_exempt(row['cell']))
        run = lambda r: r['cells'][rate_index]['rounds'][0]['runs'][0]
        changes = [
            ('different arm hashes', lambda r: r['reference'].update(sha256='b'*64), 'byte-identical'),
            ('different population', lambda r: r['environment']['population_by_arm'].update(B='snapshot'), 'environment/geometry'),
            ('missing cell', lambda r: r['cells'].pop(), 'parameters or selected cells'),
            ('duplicate cell', lambda r: r['cells'].append(copy.deepcopy(r['cells'][0])), 'duplicate ABBA cell'),
            ('unreached cell', lambda r: r['cells'][0].update(rounds=[]), 'unreached ABBA cell'),
            ('smoke salvage', lambda r: r.update(subset='smoke'), 'full coverage'),
            ('only salvage', lambda r: r.update(only='h01'), 'full coverage'),
            ('future', lambda r: r.update(started_utc=stamp(time.time()+10)), 'timestamps'),
            ('stale', lambda r: r.update(started_utc=stamp(time.time()-90000)), 'quiet timestamps'),
            ('incomplete timestamp', lambda r: r.update(elapsed_seconds=90000), 'timestamps'),
            ('instrument', lambda r: r['instrument_fingerprint'].update(sha256='0'*64), 'fingerprint digest'),
            ('imported inputs', lambda r: r['environment'].update(measurements_sha256='0'*64), 'environment/geometry'),
            ('generator runtime', lambda r: r['environment'].update(memtier_sha256='0'*64), 'environment/geometry'),
            ('inventory', lambda r: r['cell_source'].update(text='changed'), 'inventory provenance'),
            ('geometry', lambda r: r['environment'].update(split_ratio='24:8'), 'environment/geometry'),
            ('ladder', lambda r: r['cells'][0]['rounds'][0].update(instances=8), 'measured load block'),
            ('window', lambda r: r.update(window_seconds=21), 'shortened measurement'),
            ('cached saturation PASS', lambda r: run(r)['saturation'].update(score_pct=100), 'saturation'),
            ('raw unsaturated rate', lambda r: run(r).update(saturation=saturation_record('1s', score=1)), 'productive-role'),
            ('quiet missing', lambda r: r.update(quiet_box=None), 'quiet-box'),
            ('quiet span', lambda r: r['quiet_box'].update(finished_at=self.started+2), 'span all measurement windows'),
            ('unreaped', lambda r: r['process_cleanup'].update(remaining=1), 'unreaped'),
            ('unfinished', lambda r: r.update(complete=False), 'unreaped'),
            ('failed run', lambda r: run(r).update(error='generator failed'), 'incomplete measurement'),
            ('missing workload', lambda r: run(r).pop('workload_raw'), 'missing raw workload'),
            ('wrong workload', lambda r: run(r)['workload_raw'].update(after={}), 'did not execute'),
            ('spread integrity', lambda r: run(r).update(rate=110.), 'null control did not complete'),
        ]
        for state, mutate, message in changes:
            with self.subTest(state=state):
                changed = copy.deepcopy(self.report)
                mutate(changed)
                self.rejection(changed, message)
                print(f'MUTATION {state}: rejected ({message}); previous default intact')

    def test_removed_promotion_validation_is_detected_per_mechanism(self):
        mutations = [
            ('validate_campaign', lambda r: r.update(only='h01')),
            ('validate_null', lambda r: r['reference'].update(sha256='b'*64)),
            ('validate_null_integrity', None),
        ]
        for validator, mutate in mutations:
            changed = copy.deepcopy(self.report)
            if mutate:
                mutate(changed)
            else:
                # All cached evidence is internally consistent: only the fixed
                # integrity ceiling, not a stale cached null result, rejects it.
                row = next(row for row in changed['cells'] if not saturation_exempt(row['cell']))
                row['rounds'][0]['runs'][0]['rate'] = 110.
                changed['null_control'] = evidence.null_result(changed, now=time.time())
            receipt.write_json(self.source, changed)
            with self.assertRaises(ValueError):
                receipt.promote_null(self.root, self.args)
            with mock.patch.object(receipt, validator):
                # Negative control bypasses only the named validator. A test
                # demanding rejection now fails because the artifact is published.
                with self.assertRaises(AssertionError):
                    with self.assertRaises(ValueError):
                        receipt.promote_null(self.root, self.args)
            print(f'REMOVAL {validator}: rejecting assertion failed as required')

    def test_interrupted_atomic_replace_and_executable_byte_mutation(self):
        before = self.standing.read_bytes()
        with mock.patch.object(receipt.os, 'replace', side_effect=OSError('interrupted before replace')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                receipt.promote_null(self.root, self.args)
        self.assertEqual(self.standing.read_bytes(), before)
        # Corrupt one byte in an executable ELF section, never run it.
        arm = self.source.parent / 'binary-B'
        content = arm.read_bytes()
        import struct
        header = struct.unpack_from('<16sHHIQQQIHHHHHH', content)
        shoff, shsize, shcount = header[6], header[11], header[12]
        offset = next(struct.unpack_from('<IIQQQQIIQQ', content, shoff + i*shsize)[4]
                      for i in range(shcount)
                      if struct.unpack_from('<IIQQQQIIQQ', content, shoff + i*shsize)[2] & 4)
        broken = bytearray(content); broken[offset] ^= 1
        try:
            arm.write_bytes(broken)
            with self.assertRaisesRegex(ValueError, 'binary-B bytes differ'):
                receipt.promote_null(self.root, self.args)
            self.assertEqual(self.standing.read_bytes(), before)
        finally:
            arm.write_bytes(content)

    def test_current_instrument_config_generator_and_inventory_cannot_change(self):
        for relative in ('tests/abba_evidence.py', 'tests/gate_measurements.json', 'tests/headline_cells.txt', 'build/frozen-server'):
            with self.subTest(path=relative):
                path = self.root / relative; original = path.read_bytes()
                try:
                    path.write_bytes(original + (b'\n# changed\n' if path.suffix == '.py' else b'\n'))
                    with self.assertRaises(ValueError):
                        receipt.promote_null(self.root, self.args)
                finally:
                    path.write_bytes(original)

    def test_independent_holdout_cannot_use_its_own_error_to_widen_resolution(self):
        receipt.promote_null(self.root, self.args)
        control = receipt.read_json(self.standing)
        comparison = fixture_report([abba.Cell(**c) for c in self.inv['cells']], self.fp, self.env,
            self.report['cell_source']['text'], self.started + 17000, self.binary)
        comparison.update(run_kind='comparison', verdict='PASS', comparison_trusted=True)
        comparison.pop('null_control')
        def assess():
            for row in comparison['cells']:
                row['assessment'] = abba.assess(abba.Cell(**row['cell']), row['rounds'],
                                               abba.resolution_bounds(control, row['cell']['id']))
            comparison['standing_null'] = evidence.match_null(comparison, control, now=time.time())
        assess()
        result = evidence.validate_holdout(comparison, control, now=time.time())
        self.assertEqual(result['cycles_op_resolution'], 'UNPROVEN')
        row = next(row for row in comparison['cells'] if not saturation_exempt(row['cell']))
        for run in row['rounds'][0]['runs']:
            if run['arm'] == 'B': run['rate'] = 100.1
        assess()  # Favorable drift can pass a one-sided code comparison.
        with self.assertRaisesRegex(ValueError, 'frozen two-sided resolution'):
            evidence.validate_holdout(comparison, control, now=time.time())


class ExemptionControls(unittest.TestCase):
    def test_p999_depth32_and_p1_mixed_and_all_exempt_import_replay(self):
        fp = instrument_fingerprint(ROOT)
        env = copy.deepcopy(PromotionControls.env)
        cells = [abba.Cell('tail32', '1s', 0, 1, 1, 'REORDER', 32, 512, score='p999', mix='8:2'),
                 abba.Cell('latency', '2s', 0, 1, 1, 'GET', 1, 512),
                 abba.Cell('deep_rate', '1s', 0, 1, 1, 'GET', 32, 512, score='rate')]
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as tmp:
            path = Path(tmp) / 'calibration.json'
            for selected in (cells, cells[:2], cells[:1], cells[1:2]):
                report = fixture_report(selected, fp, env, 'synthetic real-shape cells\n', int(time.time())-10000,
                                        PromotionControls.binary, fast=True)
                receipt.write_json(path, report)
                config = measurements.load(); prior = copy.deepcopy(config)
                imported = measurements.import_calibration(path, config, selected)
                expected = [cell.id for cell in selected if not saturation_exempt(cell)]
                self.assertEqual(imported, expected)
                for cell in selected:
                    if saturation_exempt(cell):
                        self.assertNotIn(cell.id, config['load_floors'])
                        self.assertEqual(measurements.apply_floor(cell, config), cell)
                if not expected: self.assertEqual(config, prior)
                # The identical shapes also replay as full ABBA evidence at low occupancy.
                pinned = [replace(c, instances=1) if not saturation_exempt(c) else c for c in selected]
                normal = fixture_report(pinned, fp, env, 'synthetic real-shape cells\n',
                                        int(time.time())-10000, PromotionControls.binary)
                evidence.validate_measurements(normal, now=time.time())
                evidence.validate_campaign_evidence(normal)
                print('EXEMPT path:', ','.join(c.id for c in selected), 'imported=', imported)
            # The predicate cannot exempt an ordinary depth32 RATE cell.
            report = fixture_report(cells, fp, env, 'synthetic\n', int(time.time())-10000,
                                    PromotionControls.binary, fast=True)
            report['cells'][-1]['status'] = 'EXEMPT'
            receipt.write_json(path, report)
            with self.assertRaisesRegex(ValueError, 'failed calibration cell'):
                measurements.import_calibration(path, measurements.load(), cells)
            self.assertFalse(saturation_exempt(cells[-1]))
            for module in (measurements, evidence, abba):
                with mock.patch.object(module, 'saturation_exempt', return_value=True):
                    with self.assertRaises(AssertionError):
                        self.assertFalse(module.saturation_exempt(cells[-1]))


def self_test():
    suite = unittest.TestSuite()
    # Exemption fixtures use only immutable metadata retained by PromotionControls.
    for cls in (PromotionControls, ExemptionControls):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(self_test())
