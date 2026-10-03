"""Serverless full-campaign fixtures and mechanism-removal controls.

Every binary here is an identity artifact and is NEVER executed. CPU geometry
is metadata; only topology is read. These are not measured results or receipts.
"""
import argparse
from contextlib import ExitStack
import inspect
import textwrap
import copy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from functools import lru_cache
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

import abbagate as abba
import abba_evidence as evidence
import abba_instrument as instrument_module
import gate_measurements as measurements
import gate_receipt as receipt
import abba_reorder_control as reorder_control
import abba_null_sampling as sampling
from abba_instrument import instrument_fingerprint
from abba_saturation import saturation_exempt
from abba_workloads import workload_command_names, require_workload_witness, require_workload_accounting
from _abba_test_fixtures import quiet_record, saturation_record

ROOT = Path(__file__).resolve().parents[1]


def fixture_measurements(path=measurements.DEFAULT):
    """Synthetic two-role geometry, confined to disposable fixture configs."""
    config = measurements.load(path)
    config['geometries']['abba']['2'] = dict(io=1, ex=1,
        provenance=dict(when='synthetic', how='serverless fixture; no measurement'))
    return config


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@lru_cache(maxsize=32)
def fixture_layout(cpus, n, conns):
    return abba.load_layout(list(cpus), n, conns)


def raw_run(cell, arm, n, sequence, env, *, fast=False, score=None):
    window = 10 if fast else 20
    names = workload_command_names(cell)
    before = {f'cmdstat_{name.lower()}': 'calls=0,usec=0' for name in names}
    after = {f'cmdstat_{name.lower()}': 'calls=100,usec=100' for name in names}
    modes = {'reorder_retired': '1', 'reorder': '0'} if cell.op == 'REORDER' else {}
    layout = fixture_layout(tuple(env['load_cpus']), n, cell.conns)
    # Distribute exactly 100 completed commands per command over the generators.
    totals = []
    for i, placement in enumerate(layout):
        counts = {name: 100 // n + int(i < 100 % n) for name in names}
        conns = placement['threads'] * placement['clients']
        totals.append(dict(connections=conns, outstanding_bound=conns * cell.depth,
                           reported_counts=counts, completed_hdr_counts=counts))
    result = dict(arm=arm, instances=n, data_bytes=cell.data_bytes, complete=True, pid=123, rate=100., busy_pct=99.,
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


def fixture_report(cells, fingerprint, env, source, started, binary, *, fast=False, ceiling_loads=None):
    rows = []
    for cell in cells:
        counts = ([cell.instances or 1] if saturation_exempt(cell) else [1, 2]) if fast else [cell.instances or 1]
        rounds = [dict(instances=n, runs=[raw_run(cell, arm, n, rung + 1 if fast else i, env, fast=fast,
                                                score=70 if cell.ceiling_status else None)
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
    if ceiling_loads:
        report['ceiling_loads'] = copy.deepcopy(ceiling_loads)
    if fast:
        report['environment']['population_by_arm'] = {'B': 'wire'}
    else:
        report['statistical_verdict'] = 'PASS'
        report['null_control'] = evidence.null_result(report, now=time.time())
    return json.loads(json.dumps(report))


def throwaway(module, name, old, new, occurrence=0):
    """Remove one named mechanism in memory; never edit or run a production binary."""
    source = textwrap.dedent(inspect.getsource(getattr(module, name)))
    offset = -1
    for _ in range(occurrence + 1):
        offset = source.index(old, offset + 1)
    source = source[:offset] + new + source[offset + len(old):]
    namespace = dict(module.__dict__)
    exec(compile(source, f"<throwaway {name} occurrence {occurrence}>", 'exec'), namespace)
    return mock.patch.object(module, name, namespace[name])


def sampled_fixture(report):
    """Finish the exact pilot-sized schedule with synthetic copies, never servers."""
    report['null_sampling_policy'] = sampling.policy()
    extra = 0
    for row in report['cells']:
        def measure(arm, sequence, instances):
            run = copy.deepcopy(row['rounds'][0]['runs'][(sequence - 1) % len(abba.ORDER)])
            run['artifacts'] = f"{row['cell']['id']}/n{instances}-{sequence}-{arm}"
            return run
        sampling.collect(abba.Cell(**row['cell']), row, measure, lambda: None)
        extra += len(row['null_repeats']) * len(abba.ORDER) * report['window_seconds']
    report['elapsed_seconds'] += extra
    report['quiet_box']['finished_at'] += extra
    report['quiet_box']['cpu_samples'] += int(extra)
    report['quiet_box']['samples'] += int(extra)
    report['null_control'] = evidence.null_result(report, now=time.time())
    return report


def holdout_fixture(comparison, control):
    """Synthetic independent blocks with the published count; never executes a binary."""
    from abba_holdout import plan, rejudge
    extra = 0
    for row in comparison['cells']:
        row['holdout_repeats'] = []
        for ordinal in range(1, plan(control)[row['cell']['id']]['planned_blocks']):
            block = copy.deepcopy(row['rounds'][0])
            block['sample_offset'] = ordinal * len(abba.ORDER)
            for sequence, run in enumerate(block['runs'], 1 + block['sample_offset']):
                run['artifacts'] = f"{row['cell']['id']}/n{block['instances']}-{sequence}-{run['arm']}"
            row['holdout_repeats'].append(block)
            extra += len(abba.ORDER) * comparison['window_seconds']
    comparison['elapsed_seconds'] += extra
    comparison['quiet_box']['finished_at'] += extra
    comparison['quiet_box']['cpu_samples'] += int(extra)
    comparison['quiet_box']['samples'] += int(extra)
    comparison.pop('null_control', None)
    rejudge(comparison, control)
    comparison['standing_null'] = evidence.match_null(comparison, control, now=time.time())
    return comparison


def armed_workload(cell, run, proof=None):
    mode = dict(reorder_retired='0', reorder=str(cell.reorder), read_local=str(cell.read_local))
    end = dict(mode)
    if cell.reorder:
        mode.update(reorder_shadow='1', reorder_permuted_runs='0', reorder_batches='10')
        end = {**mode, 'reorder_batches': '20', 'reorder_permuted_runs': '0' if cell.read_local else '1'}
    raw = run['workload_raw']
    raw.update(mode_before=mode, mode_after=end, read_local_control=proof)
    run['workload_witness'] = require_workload_witness(cell, raw['before'], raw['after'], mode, end,
                                                     read_local_control=proof)


def control_fixture(folder, cells, fp, env, binary, completed):
    """Synthetic proof artifacts; no executable or network boundary is crossed."""
    folder.mkdir()
    topology = dict(stamp_ns=1, shards={'0': dict(owner=1, migrations=0)},
                    threads={'0': dict(role='fused', clients=4, full=0, masked_full=0)})
    directed = []
    for ro in (0, 1):
        attempt = dict(armed=True, inversion=bool(ro), before=topology,
                       after={**topology, 'stamp_ns': 2}, versions_before={'atomic_groups': 0},
                       versions_after={'atomic_groups': 0})
        directed.append(dict(verdict='PASS', mode='1s', reorder=ro,
            knobs={'read-local': 1, 'reorder': ro}, boot_info={'read_local': '1'},
            armed_attempts=1, inversions=ro, preparatory_counter_delta=ro, attempts=[attempt]))
    path = folder / 'directed.json'
    receipt.write_json(path, directed)
    proof = dict(verdict='PASS', mode='1s', read_local=1, controls=[0, 1],
        on_counter_delta=1, binary_sha256=binary['sha256'], artifact=str(path),
        artifact_sha256=abba.sha256(path), scope='synthetic directed control, never measured')
    targets = [cell for cell in cells if reorder_control.controlled(cell)]
    variants = [variant for cell in targets for variant in reorder_control.pair(cell)]
    workloads = fixture_report(variants, fp, env, ''.join(reorder_control.cell_line(c) for c in variants),
                               completed - 1000, binary, fast=True)
    for row in workloads['cells']:
        cell = abba.Cell(**row['cell'])
        armed_workload(cell, row['rounds'][0]['runs'][0], proof if reorder_control.needs_proof(cell) else None)
    path = folder / 'workloads.json'
    receipt.write_json(path, workloads)
    control = dict(schema=1, kind='read-local-reorder-controls', verdict='PASS', completed_at=completed,
        cells=[asdict(c) for c in targets], instrument=fp, binary_sha256=binary['sha256'],
        workloads=reorder_control.identity(path), proofs={c.id: proof for c in targets if reorder_control.needs_proof(c)})
    path = folder / 'receipt.json'
    receipt.write_json(path, control)
    return reorder_control.identity(path), proof, control, workloads


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
        # Keep all 181 cells and every raw ABBA block. Two server threads are
        # sufficient to retain both split roles; duplicating their counters 16x
        # only inflates JSON/copies/replay in each mutation control. The separate
        # saturation suite retains inactive-peer and many-thread role checks.
        # Geometry here is metadata, never an instruction to run on these CPUs.
        cls.env = dict(uname=list(os.uname()), python_runtime=cls.fp['python'],
            server_physical=[0, 1], server_smt=[], server_cpus=[0, 1],
            load_physical=list(range(32, 64)), load_smt=[],
            load_cpus=list(range(32, 64)), split_ratio='1:1',
            port=8700, permitted_ports=[8700], load_instance_ceiling=16,
            keys=2000000, data_bytes=64, key_pattern='P:P', atomic='per-cell', split_flip_auto=0,
            memtier_path=str(binary), memtier_sha256=cls.binary['sha256'], memtier_version='identity fixture; never executed',
            population_by_arm={'A': 'wire', 'B': 'wire'})
        config = fixture_measurements()
        cells = abba.read_cells(ROOT / 'tests/headline_cells.txt')
        config['load_floors'] = {}
        config['ceiling_loads'] = {}
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
        receipt.write_json(self.standing, self.report)
        evidence.validate_null(receipt.read_json(self.standing), now=time.time())

    def controls(self):
        temporary = tempfile.TemporaryDirectory(dir=self.root / 'build')
        self.addCleanup(temporary.cleanup)
        return control_fixture(Path(temporary.name) / 'controls',
            [abba.Cell(**c) for c in self.inv['cells']], self.fp, self.env, self.binary, self.started - 100)

    def armed_report(self, binding, proof, *, started=None):
        result = fixture_report([abba.Cell(**c) for c in self.inv['cells']], self.fp, self.env,
            self.report['cell_source']['text'], self.started if started is None else started, self.binary)
        result['reorder_controls'] = binding
        for row in result['cells']:
            cell = abba.Cell(**row['cell'])
            if reorder_control.controlled(cell):
                for run in row['rounds'][0]['runs']:
                    armed_workload(cell, run, proof if reorder_control.needs_proof(cell) else None)
        return result

    def test_read_local_zero_permutations_promote_and_holdout_with_frozen_control(self):
        binding, proof, _, _ = self.controls()
        report = self.armed_report(binding, proof)
        campaign = {**self.campaign, 'reorder_controls': binding}
        campaign_path = self.root / 'build/armed-campaign.json'
        receipt.write_json(campaign_path, campaign)
        receipt.write_json(self.source, report)
        args = argparse.Namespace(campaign=campaign_path, null_result=self.source)
        receipt.promote_null(self.root, args)
        promoted = receipt.read_json(self.standing)
        self.assertEqual(promoted['reorder_controls'], binding)
        self.assertEqual(receipt.read_json(self.source), report)
        comparison = self.armed_report(binding, proof, started=self.started + 17000)
        comparison.update(run_kind='comparison', verdict='PASS', comparison_trusted=True)
        comparison.pop('null_control')
        comparison['standing_null'] = evidence.match_null(comparison, promoted, now=time.time())
        receipt.validate_campaign(self.root, campaign, comparison, now=time.time())
        holdout_fixture(comparison, promoted)
        self.assertEqual(evidence.validate_holdout(comparison, promoted, now=time.time())['verdict'], 'PASS')

    def test_read_local_raw_proof_replay_and_per_guard_removal(self):
        binding, proof, _, _ = self.controls()
        report = self.armed_report(binding, proof)
        row = next(row for row in report['cells'] if row['cell']['id'] == 't05')
        cell, run = abba.Cell(**row['cell']), row['rounds'][0]['runs'][0]
        evidence.validate_workload_evidence(cell, run, report=report)
        # Reproduce campaign 4: a good summary cannot stand in for omitted raw evidence.
        broken = copy.deepcopy(run)
        broken['workload_raw'].pop('read_local_control')
        with self.assertRaisesRegex(ValueError, 'workload_raw.read_local_control') as failure:
            evidence.validate_workload_evidence(cell, broken, report=report)
        self.assertIn('--collect-reorder-controls', str(failure.exception))
        command = next(line.strip() for line in str(failure.exception).splitlines() if line.startswith('  python3'))
        import shlex
        argv = shlex.split(command)
        self.assertEqual(abba.cpus(argv[argv.index('--load-cores') + 1]), self.env['load_physical'])
        with throwaway(evidence, 'validate_workload_evidence', 'raw.get("legacy_control"), proof)',
                       'raw.get("legacy_control"))'):
            with self.assertRaisesRegex(ValueError, 'live read-local OFF/ON'):
                evidence.validate_workload_evidence(cell, run, report=report)
        for change, reason in (({'after': {}}, 'did not execute'),
            ({'mode_after': {**run['workload_raw']['mode_after'], 'reorder_batches': '10'}}, 'batches'),
            ({'read_local_control': {**proof, 'binary_sha256': '0' * 64}}, 'binary SHA-256'),
            ({'read_local_control': {**proof, 'on_counter_delta': 0}}, 'on_counter_delta'),
            ({'read_local_control': {**proof, 'artifact_sha256': '0' * 64}}, 'artifact changed')):
            with self.subTest(reason=reason):
                broken = copy.deepcopy(run)
                broken['workload_raw'].update(change)
                with self.assertRaisesRegex(ValueError, reason):
                    evidence.validate_workload_evidence(cell, broken, report=report)

    def test_read_local_receipt_inventory_time_geometry_and_artifact_guards(self):
        binding, proof, control, workloads = self.controls()
        cells = [abba.Cell(**c) for c in self.inv['cells']]
        def validate(item=binding, **changes):
            options = dict(cells=cells, fingerprint=self.fp, binary_sha256=self.binary['sha256'],
                           environment=self.env, before=self.started)
            return reorder_control.validate_binding(item, **{**options, **changes})
        self.assertEqual(validate(), {'t05': proof})
        for changed in ({'binary_sha256': 'f' * 64}, {'before': self.started - 1000},
                        {'environment': {**self.env, 'load_cpus': [1]}}, {'cells': cells[:-1]}):
            with self.subTest(changed=changed), self.assertRaises(ValueError): validate(**changed)
        path = Path(binding['path'])
        for key, value in (('completed_at', time.time() - 90000), ('proofs', {}), ('verdict', 'FAIL')):
            receipt.write_json(path, {**control, key: value})
            with self.subTest(key=key), self.assertRaises(ValueError): validate(reorder_control.identity(path))
        receipt.write_json(path, control)
        workload_path = Path(control['workloads']['path'])
        # Altering a raw workload also invalidates its artifact binding.
        receipt.write_json(workload_path, {**workloads, 'complete': False})
        with self.assertRaisesRegex(ValueError, 'artifact changed'): validate()
        receipt.write_json(workload_path, workloads)
        directed = Path(proof['artifact'])
        rows = receipt.read_json(directed)
        for arm, change in ((0, {'inversions': 1}), (1, {'armed_attempts': 0}),
                            (1, {'preparatory_counter_delta': 0})):
            broken = copy.deepcopy(rows); broken[arm].update(change)
            receipt.write_json(directed, broken)
            with self.subTest(arm=arm, change=change), self.assertRaises((ValueError, RuntimeError)):
                reorder_control.validate_proof({**proof, 'artifact_sha256': abba.sha256(directed)})

    def test_read_local_campaign_missing_or_supplementary_proof_cannot_repair_collection(self):
        binding, proof, _, _ = self.controls()
        report = self.armed_report(binding, proof)
        for binding_override in (None, {**binding, 'sha256': 'f' * 64}):
            with self.subTest(binding=binding_override), self.assertRaises(ValueError):
                reorder_control.validate_report(report, binding_override, before=self.started)
        broken = copy.deepcopy(report)
        next(row for row in broken['cells'] if row['cell']['id'] == 't05')['rounds'][0]['runs'][0]['workload_raw'].pop('read_local_control')
        with self.assertRaisesRegex(ValueError, 'raw read-local evidence differs'):
            reorder_control.validate_report(broken, binding, before=self.started)
        # A later passing control cannot be backdated into the original collection.
        path = Path(binding['path']); control = receipt.read_json(path)
        receipt.write_json(path, {**control, 'completed_at': self.started + 100})
        late = reorder_control.identity(path)
        report['reorder_controls'] = late
        with self.assertRaisesRegex(ValueError, 'before collection/freeze'):
            reorder_control.validate_report(report, late, before=self.started)

    def test_read_local_receipt_reused_without_rerunning_directed_controls(self):
        binding, proof, _, _ = self.controls()
        report = self.armed_report(binding, proof)
        args = argparse.Namespace(server_cores='0-1', server_smt='', load_cores='32-63',
                                  load_smt='', port=8700, reorder_controls=Path(binding['path']))
        runner = abba.Runner(args, self.root / 'build', {'A': Path(self.binary['path']),
                            'B': Path(self.binary['path'])}, None)
        reorder_control.attach(runner, report, [abba.Cell(**c) for c in self.inv['cells']])
        cell = abba.Cell(**next(c for c in self.inv['cells'] if c['id'] == 't05'))
        with mock.patch.object(runner, 'execution_order_control', side_effect=AssertionError('must reuse')):
            for arm in ('A', 'B', 'B', 'A'):
                self.assertEqual(runner.read_local_reorder_control(cell, arm, {'reorder': 1}), proof)
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                runner.read_local_reorder_control(replace(cell, id='new-cell'), 'B', {'reorder': 1})

    def test_read_local_collection_uses_real_workload_path_once_and_retains_failures(self):
        import load_calibration
        _, _, _, workloads = self.controls()
        for broken in (False, True):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory(dir=self.root / 'build') as tmp:
                argv = ['abbagate.py', '--collect-reorder-controls', '--candidate', self.binary['path'],
                        '--cells', str(self.root / 'tests/headline_cells.txt'), '--output', str(Path(tmp) / 'control')]
                with mock.patch.object(sys, 'argv', argv):
                    args = abba.parse_args()
                def collect_workloads(options):
                    self.assertTrue(options.calibrate)
                    self.assertFalse(options.collect_reorder_controls)
                    self.assertIsNone(options.reorder_controls)
                    self.assertEqual(options.cells.read_text(), workloads['cell_source']['text'])
                    options.output.mkdir()
                    receipt.write_json(options.output / 'results.json', workloads)
                    return 1 if broken else 3
                with mock.patch.object(load_calibration, 'main', side_effect=collect_workloads) as collector, \
                     mock.patch.object(abba.Children, 'start', side_effect=AssertionError('no processes in fixture')):
                    if broken:
                        with self.assertRaisesRegex(ValueError, 'control failed'): abba.main(args)
                        self.assertFalse((args.output / 'receipt.json').exists())
                    else:
                        self.assertEqual(abba.main(args), 0)
                        control = receipt.read_json(args.output / 'receipt.json')
                        self.assertEqual([cell['id'] for cell in control['cells']], ['t05', 't06'])
                        self.assertEqual(set(control['proofs']), {'t05'})
                    collector.assert_called_once()
                    self.assertTrue((args.output / 'workloads/results.json').is_file())

    def test_read_local_freeze_binds_precalibration_receipt_and_requires_it(self):
        binding, proof, _, _ = self.controls()
        cells = [abba.Cell(**cell) for cell in self.inv['cells']]
        fast = fixture_report(cells, self.fp, self.env, self.report['cell_source']['text'],
                              self.started, self.binary, fast=True)
        fast['reorder_controls'] = binding
        for row in fast['cells']:
            cell = abba.Cell(**row['cell'])
            if reorder_control.controlled(cell):
                armed_workload(cell, row['rounds'][0]['runs'][0], proof if reorder_control.needs_proof(cell) else None)
        path = self.root / 'build/armed-calibration.json'
        receipt.write_json(path, fast)
        config_path = self.root / 'tests/gate_measurements.json'
        original = config_path.read_bytes()
        try:
            config = fixture_measurements(config_path)
            measurements.import_calibration(path, config, cells)
            receipt.write_json(config_path, config)
            args = argparse.Namespace(calibration=path, output=self.root / 'build/armed-freeze.json')
            with self.assertRaisesRegex(ValueError, 't05: missing frozen read-local'):
                receipt.freeze_null(self.root, args)
            args.reorder_controls = Path(binding['path'])
            receipt.freeze_null(self.root, args)
            self.assertEqual(receipt.read_json(args.output)['reorder_controls'], binding)
            with self.assertRaises((ValueError, FileExistsError)): receipt.freeze_null(self.root, args)
        finally:
            config_path.write_bytes(original)

    def test_absent_and_stale_prior_null_bootstrap_without_receipt(self):
        for prior in (None, b'{"started_utc":"2000-01-01T00:00:00Z"}'):
            with self.subTest(prior=prior):
                self.standing.unlink(missing_ok=True)
                if prior is not None:
                    self.standing.write_bytes(prior)
                self.assertEqual(receipt.promote_null(self.root, self.args), self.standing)
                result = receipt.read_json(self.standing)
                self.assertEqual((result['verdict'], result['comparison_trusted']), ('PARTIAL', False))
                self.assertTrue(receipt.read_json(self.source) == self.report, "source artifact retained")
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
        self.standing.unlink()
        original_write = receipt.write_bytes
        def receipt_only(path, *args, **kwargs):
            if path != self.standing:
                original_write(path, *args, **kwargs)
        with mock.patch.object(receipt, 'write_bytes', side_effect=receipt_only):
            with self.assertRaises(AssertionError):
                self.assertTrue(receipt.promote_null(self.root, self.args).is_file(),
                                'standalone bootstrap must publish without a prior receipt')

    def test_ceiling_import_freeze_promotion_holdout_and_forgery_controls(self):
        from load_calibration import select_calibration_floor
        path = self.root / 'build/ceiling-calibration.json'
        config_path = self.root / 'tests/gate_measurements.json'
        original = config_path.read_bytes()
        cells = [abba.Cell(**cell) for cell in self.inv['cells']]
        env = {**self.env, 'load_instance_ceiling': 24, 'load_physical': list(range(32, 128)),
               'load_smt': list(range(160, 256)), 'load_cpus': list(range(32, 128)) + list(range(160, 256))}
        fast = fixture_report(cells, self.fp, env, self.report['cell_source']['text'],
                              self.started, self.binary, fast=True)
        row = next(row for row in fast['cells'] if row['cell']['id'] == 'm09')
        cell = abba.Cell(**row['cell'])
        row['load_ladder'] = [1, 2, 4, 8, 12, 16, 24]
        row['rounds'] = []
        for i, n in enumerate(row['load_ladder'], 1):
            run = raw_run(cell, 'B', n, i, env, fast=True, score=70)
            run['rate'] = n * 100.
            row['rounds'].append(dict(instances=n, runs=[run]))
        row['selection'] = select_calibration_floor(cell, row['rounds'], ceiling=24)
        row['status'] = row['selection']['status']
        self.assertEqual(row['status'], 'LOADGEN-BOUND')
        fast['verdict'] = 'CEILING-LIMITED'
        receipt.write_json(path, fast)
        config = fixture_measurements(config_path)
        measurements.import_calibration(path, config, cells)
        self.assertNotIn('m09', config['load_floors'])
        self.assertEqual(config['ceiling_loads']['m09']['evidence']['saturated_peak_floor'], None)
        row_index = fast['cells'].index(row)
        for mutate in (lambda r: r['cells'][row_index]['selection']['ceiling_evidence'].update(achieved_rate=1),
                       lambda r: r.update(verdict='PIN')):
            broken = copy.deepcopy(fast); mutate(broken)
            with self.assertRaises(ValueError): measurements.validate_fast_calibration(broken, self.fp)
        try:
            receipt.write_json(config_path, config)
            campaign_path = self.root / 'build/ceiling-campaign.json'
            receipt.freeze_null(self.root, argparse.Namespace(calibration=path, output=campaign_path))
            campaign = receipt.read_json(campaign_path)
            frozen_cells = [abba.Cell(**c) for c in campaign['inventory']['cells']]
            started = int(campaign['frozen_at']) + 2
            with mock.patch.object(time, 'time', return_value=started + 34000):
                control = fixture_report(frozen_cells, self.fp, campaign['environment'],
                    self.report['cell_source']['text'], started, self.binary, ceiling_loads=config['ceiling_loads'])
                sampled_fixture(control)
                receipt.write_json(self.source, control)
                args = argparse.Namespace(null_result=self.source, campaign=campaign_path)
                receipt.promote_null(self.root, args)
                control = receipt.read_json(self.standing)
                comparison = fixture_report(frozen_cells, self.fp, campaign['environment'],
                    self.report['cell_source']['text'], started + 17000, self.binary,
                    ceiling_loads=config['ceiling_loads'])
                comparison.update(run_kind='comparison', verdict='PASS', comparison_trusted=True)
                comparison.pop('null_control')
                comparison['standing_null'] = evidence.match_null(comparison, control, now=time.time())
                holdout_fixture(comparison, control)
                result = evidence.validate_holdout(comparison, control, now=time.time())
                self.assertEqual(result['ceiling_only_cells'], {'m09': 'LOADGEN-BOUND'})
                for state, mutate, reason in (
                        ('different binary', lambda r: r['candidate'].update(sha256='f'*64), 'byte-identical'),
                        ('missing provenance', lambda r: r.pop('ceiling_loads'), 'provenance'),
                        ('different ceiling', lambda r: r['environment'].update(load_instance_ceiling=16), 'load/geometry'),
                        ('claimed floor', lambda r: next(x for x in r['cells'] if x['cell']['id']=='m09')['assessment'].update(capacity_claim='saturated-peak'), 'saturated peak')):
                    broken = copy.deepcopy(comparison); mutate(broken)
                    with self.assertRaisesRegex(ValueError, reason): evidence.validate_measurements(broken, now=time.time())
                    print('CEILING rejected:', state)
        finally:
            config_path.write_bytes(original)

    def rejection(self, report, message):
        receipt.write_json(self.source, report)
        before = self.standing.read_bytes()
        with self.assertRaisesRegex((ValueError, RuntimeError), message) as caught:
            receipt.promote_null(self.root, self.args)
        self.assertEqual(self.standing.read_bytes(), before, message)
        return type(caught.exception), str(caught.exception)

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
            ('raw unsaturated rate', lambda r: run(r).update(saturation=saturation_record('1s', score=1,
                threads=len(self.env['server_cpus']))), 'productive-role'),
            ('quiet missing', lambda r: r.update(quiet_box=None), 'quiet-box'),
            ('quiet span', lambda r: r['quiet_box'].update(finished_at=self.started+2), 'span all measurement windows'),
            ('unreaped', lambda r: r['process_cleanup'].update(remaining=1), 'unreaped'),
            ('unfinished', lambda r: r.update(complete=False), 'unreaped'),
            ('failed run', lambda r: run(r).update(error='generator failed'), 'incomplete measurement'),
            ('missing workload', lambda r: run(r).pop('workload_raw'), 'missing raw workload'),
            ('wrong workload', lambda r: run(r)['workload_raw'].update(after={}), 'did not execute'),
            ('value size', lambda r: run(r).update(data_bytes=1), 'value size differs'),
            ('spread integrity', lambda r: run(r).update(rate=110.), 'null control did not complete'),
        ]
        for state, mutate, message in changes:
            with self.subTest(state=state):
                changed = copy.deepcopy(self.report)
                mutate(changed)
                rejected = self.rejection(changed, message)
                print(f'MUTATION {state}: rejected ({message}); previous default intact')
                # Disable the exact rejecting mechanism in this disposable fixture.
                # A redundant later guard may still refuse; the named assertion
                # must then fail on that DIFFERENT reason, not falsely claim coverage.
                previous, hits = self.standing.read_bytes(), []
                with ExitStack() as stack:
                    for module in (receipt, evidence, instrument_module):
                        original = module.require
                        def removed(condition, reason, original=original):
                            if reason == rejected[1] and not condition:
                                hits.append(reason)
                            else:
                                original(condition, reason)
                        # These guards are called for every raw numeric field.
                        # Record only the explicit hits below, not a Mock call
                        # object for each successfully validated scalar.
                        stack.enter_context(mock.patch.object(module, 'require', new=removed))
                    if state == 'cached saturation PASS':
                        original = evidence.replay_saturation
                        def no_cached_check(record, **kwargs):
                            try:
                                return original(record, **kwargs)
                            except ValueError as error:
                                if str(error) != rejected[1]: raise
                                hits.append(str(error)); return record
                        for module in (evidence, abba):
                            stack.enter_context(mock.patch.object(module, 'replay_saturation', new=no_cached_check))
                    if state == 'wrong workload':
                        def no_workload(*_, **__): hits.append(rejected[1])
                        stack.enter_context(mock.patch.object(evidence, 'validate_workload_evidence', new=no_workload))
                    observed = None
                    try:
                        receipt.promote_null(self.root, self.args)
                    except Exception as error:
                        observed = type(error), str(error)
                    self.assertTrue(hits, f'{state}: removal never exercised its guard')
                    self.assertNotEqual(observed, rejected, f'{state}: exact rejection oracle survived removal')
                self.standing.write_bytes(previous)
                print(f'REMOVAL {state}: exact assertion failed; ' +
                      ('accepted in throwaway' if observed is None else 'next guard: ' + observed[1][:100]))

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
                # Integrity now protects the recorded status, not a magnitude
                # ceiling. Exercise its exact guard independently of validate_null.
                changed['null_control']['resolution'][0]['status'] = 'UNRESOLVED'
                with self.assertRaisesRegex(ValueError, 'resolution/status differs'):
                    evidence.validate_null_integrity(changed)
                with mock.patch.object(evidence, 'null_resolution', return_value=changed['null_control']['resolution']):
                    with self.assertRaises(AssertionError):
                        with self.assertRaisesRegex(ValueError, 'resolution/status differs'):
                            evidence.validate_null_integrity(changed)
                print('REMOVAL validate_null_integrity raw-status replay: exact rejection assertion failed')
                continue
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
        # Removing atomic replacement exposes a partial destination on interruption.
        original = receipt.write_bytes
        def non_atomic(path, *args, **kwargs):
            if path == self.standing:
                path.write_bytes(b'interrupted partial destination')
                raise OSError('interrupted direct write')
            return original(path, *args, **kwargs)
        with mock.patch.object(receipt, 'write_bytes', side_effect=non_atomic):
            with self.assertRaises(OSError): receipt.promote_null(self.root, self.args)
            with self.assertRaises(AssertionError): self.assertEqual(self.standing.read_bytes(), before)
        self.standing.write_bytes(before)
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

    def test_freeze_requires_full_replayed_import_and_is_immutable(self):
        config_path = self.root / 'tests/gate_measurements.json'
        original = config_path.read_bytes()
        try:
            cells = [abba.Cell(**cell) for cell in self.inv['cells']]
            calibration = fixture_report(cells, self.fp, self.env, self.report['cell_source']['text'],
                                         self.started - 1000, self.binary, fast=True)
            path = self.root / 'build/calibration.json'; receipt.write_json(path, calibration)
            args = argparse.Namespace(calibration=path, output=self.root / 'build/post-import-plan.json')
            with self.assertRaisesRegex(ValueError, 'replay/import'):
                receipt.freeze_null(self.root, args)
            config = fixture_measurements(config_path)
            imported = measurements.import_calibration(path, config, cells)
            self.assertEqual(len(imported), sum(not saturation_exempt(cell) for cell in cells))
            receipt.write_json(config_path, config)
            self.assertEqual(receipt.freeze_null(self.root, args), args.output)
            frozen = receipt.read_json(args.output)
            receipt.current_campaign(self.root, frozen)
            with self.assertRaises(FileExistsError):
                receipt.freeze_null(self.root, args)
            self.assertEqual(frozen['instrument'], self.fp)
            self.assertNotEqual(frozen['measurements_sha256'], self.campaign['measurements_sha256'])
        finally:
            config_path.write_bytes(original)

    def test_unresolved_complete_campaign_freezes_promotes_and_cannot_earn_pass(self):
        config_path = self.root / 'tests/gate_measurements.json'
        original = config_path.read_bytes()
        try:
            cells = [abba.Cell(**cell) for cell in self.inv['cells']]
            calibration = fixture_report(cells, self.fp, self.env, self.report['cell_source']['text'],
                                         self.started - 1000, self.binary, fast=True)
            path = self.root / 'build/unresolved-calibration.json'
            receipt.write_json(path, calibration)
            config = fixture_measurements(config_path)
            measurements.import_calibration(path, config, cells)
            receipt.write_json(config_path, config)
            frozen = self.root / 'build/unresolved-campaign.json'
            receipt.freeze_null(self.root, argparse.Namespace(calibration=path, output=frozen))
            campaign = receipt.read_json(frozen)
            started = int(campaign['frozen_at']) + 2
            with mock.patch.object(time, 'time', return_value=started + 34000):
                control = fixture_report([abba.Cell(**c) for c in campaign['inventory']['cells']],
                    self.fp, campaign['environment'], self.report['cell_source']['text'], started, self.binary)
                noisy = next(row for row in control['cells'] if row['cell']['id'] == 'h01')
                for run, value in zip(noisy['rounds'][0]['runs'], (98., 101., 101., 102.)):
                    run['rate'] = value
                noisy['assessment'] = abba.assess(abba.Cell(**noisy['cell']), noisy['rounds'], abba.NULL_MODE)
                sampled_fixture(control)
                receipt.write_json(self.source, control)
                receipt.promote_null(self.root, argparse.Namespace(null_result=self.source, campaign=frozen))
                promoted = receipt.read_json(self.standing)
                summary = evidence.resolution_summary(promoted)
                self.assertEqual(summary['unresolved_cells'], ['h01'], 'UNRESOLVED promotion lost the noisy cell')
                self.assertEqual(len(summary['resolving_cells']), len(cells) - 1)
                # Restoring the old magnitude veto must break the successful promotion assertion.
                def old_guard(report):
                    for row in evidence.null_resolution(report):
                        evidence.require(max(row['reference_spread_pct'], row['candidate_spread_pct'],
                                             row['absolute_delta_pct']) <= abba.MAX_SPREAD, 'removed magnitude veto')
                with mock.patch.object(receipt, 'validate_null_integrity', side_effect=old_guard):
                    with self.assertRaisesRegex(ValueError, 'removed magnitude veto'):
                        receipt.promote_null(self.root, argparse.Namespace(null_result=self.source, campaign=frozen))
                comparison = fixture_report([abba.Cell(**c) for c in campaign['inventory']['cells']],
                    self.fp, campaign['environment'], self.report['cell_source']['text'], started + 17000, self.binary)
                comparison.update(run_kind='comparison', verdict='UNRESOLVED', statistical_verdict='UNRESOLVED')
                comparison.pop('null_control')
                for row in comparison['cells']:
                    row['assessment'] = abba.assess(abba.Cell(**row['cell']), row['rounds'],
                                                   abba.resolution_bounds(promoted, row['cell']['id']))
                    row['verdict'] = row['assessment']['verdict']
                comparison['standing_null'] = evidence.match_null(comparison, promoted, now=time.time())
                summary = evidence.resolution_summary(comparison, promoted)
                self.assertEqual(len(summary['pass_evidence_cells']), len(cells) - 1)
                self.assertNotIn('h01', summary['pass_evidence_cells'], 'UNRESOLVED cell counted as PASS')
                with self.assertRaisesRegex(ValueError, 'comparison reporting-only: .*UNRESOLVED=1 \\[h01\\]'):
                    evidence.validate_comparison(comparison, promoted, now=time.time())
                held = holdout_fixture(copy.deepcopy(comparison), promoted)
                self.assertEqual(evidence.validate_holdout(held, promoted, now=time.time())['verdict'], 'PASS')
                changed = copy.deepcopy(comparison)
                changed.update(verdict='PASS', comparison_trusted=True)
                with throwaway(evidence, 'validate_comparison', 'not summary["unresolved_cells"]', 'True'):
                    # The other raw validators still work, but this exact refusal is gone.
                    with self.assertRaises(AssertionError):
                        with self.assertRaisesRegex(ValueError, 'comparison reporting-only:'):
                            evidence.validate_comparison(changed, promoted, now=time.time())
                print('UNRESOLVED freeze/promote + comparison: 180 PASS evidence, h01 reporting-only; old veto/refusal-removal detected')
        finally:
            config_path.write_bytes(original)

    def test_age_ladder_window_and_fixed_resolution_checks_cannot_be_bypassed(self):
        changes = []
        stale = copy.deepcopy(self.report)
        shift = 90000
        stale['started_utc'] = stamp(self.started - shift)
        stale['quiet_box']['started_at'] -= shift
        stale['quiet_box']['finished_at'] -= shift
        changes.append(('age', stale, 'at most 24 hours old'))
        ladder = copy.deepcopy(self.report)
        row = next(row for row in ladder['cells'] if not saturation_exempt(row['cell']))
        row['assessment']['instances'] = 2
        row['rounds'][0]['instances'] = 2
        for i, run in enumerate(row['rounds'][0]['runs'], 1):
            run.update(instances=2, artifacts=f"{row['cell']['id']}/n2-{i}-{run['arm']}")
        changes.append(('ladder', ladder, 'measured load ladder differs'))
        window = copy.deepcopy(self.report); window['window_seconds'] = 19
        changes.append(('window', window, 'campaign window differs'))
        for state, report, message in changes:
            self.rejection(report, message)
            module = receipt if state != 'ladder' else evidence
            saved = module.require
            def removed(condition, reason):
                if message not in reason:
                    saved(condition, reason)
            with mock.patch.object(module, 'require', new=removed):
                with self.assertRaises(AssertionError):
                    with self.assertRaisesRegex(ValueError, message):
                        receipt.promote_null(self.root, self.args)
            print(f'REMOVAL {state}: exact rejecting assertion failed')

    def test_independent_holdout_cannot_use_its_own_error_to_widen_resolution(self):
        receipt.promote_null(self.root, self.args)
        control = receipt.read_json(self.standing)
        comparison = fixture_report([abba.Cell(**c) for c in self.inv['cells']], self.fp, self.env,
            self.report['cell_source']['text'], self.started + 17000, self.binary)
        comparison.update(run_kind='comparison', verdict='PASS', comparison_trusted=True)
        comparison.pop('null_control')
        from abba_holdout import rejudge
        holdout_fixture(comparison, control)
        result = evidence.validate_holdout(comparison, control, now=time.time())
        self.assertEqual(result['cycles_op_resolution'], 'UNPROVEN')
        row = next(row for row in comparison['cells'] if not saturation_exempt(row['cell']))
        for run in row['rounds'][0]['runs']:
            if run['arm'] == 'B': run['rate'] = 100.1
        rejudge(comparison, control)
        comparison['standing_null'] = evidence.match_null(comparison, control, now=time.time())
        result = evidence.validate_holdout(comparison, control, now=time.time())
        self.assertEqual(result['verdict'], 'FAIL', 'favorable drift outside the fixed floor must FAIL')
        self.assertIn('holdout |pooled delta| exceeds published floor', result['failures'][0]['reasons'][0])
        forged = copy.deepcopy(control)
        forged['null_control']['resolution'][0]['metric'] = 'cycles/op'
        with self.assertRaisesRegex(ValueError, 'null control did not complete'):
            evidence.validate_null(forged, now=time.time())


class NullpublishControls(unittest.TestCase):
    def test_campaign6_compact_replay_preserves_exact_map_and_classification_control(self):
        path = ROOT / 'tests/fixtures/nullpublish-campaign6-compact.json'
        compact = receipt.read_json(path)
        self.assertEqual(compact['parent']['sha256'],
                         '501cefeeba9d1f3bb9a2d07ddfd8e6a9f641c422f1758c24f6d0d4fcadfecbb5')

        def assertion():
            result = receipt.replay_null(path)
            rows = result['resolution']
            self.assertEqual((len(rows), sum(r['status'] == 'RESOLVING' for r in rows),
                              sum(r['status'] == 'UNRESOLVED' for r in rows)), (188, 141, 47))
            by_key = {(r['cell'], r['metric'], r['instances']): r for r in rows}
            self.assertEqual(len(compact['expected']), len(by_key))
            for expected in compact['expected']:
                actual = by_key[expected['cell'], expected['metric'], int(expected['instances'])]
                self.assertEqual(actual['status'], expected['status_at_MAX_SPREAD_2'])
                for field in ('reference_spread_pct', 'candidate_spread_pct'):
                    self.assertEqual(f"{actual[field]:.3f}", expected[field])
                self.assertEqual(f"{actual['delta_pct']:.3f}", expected['paired_delta_pct'])
            t00 = next(r for r in rows if (r['cell'], r['metric']) == ('t00', 'p999_ms'))
            self.assertEqual(f"{t00['reference_spread_pct']:.2f}", '11.68')
            self.assertFalse(result['promotable'])
            self.assertTrue(result['reporting_only'])
            self.assertEqual(result['summary']['pass_evidence_cells'], [])
            with self.assertRaises(ValueError):
                evidence.validate_null(compact, now=time.time())

        assertion()
        with throwaway(evidence, 'null_resolution',
                       'max(threshold, candidate_spread, abs(delta)) <= MAX_SPREAD', 'True'), \
             mock.patch.object(receipt, 'null_resolution', new=lambda report: evidence.null_resolution(report)):
            with self.assertRaises(AssertionError):
                assertion()
        print('Campaign 6 compact replay: 188/141/47, t00 11.68%; classification removal detected; no PASS evidence')

    def test_replay_reads_once_and_hashes_exactly_the_parsed_bytes(self):
        _, row = self.row((90., 100., 100., 110.))
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as tmp:
            path = Path(tmp) / 'results.json'
            content = receipt.canonical({'cells': [row]})
            path.write_bytes(content)
            calls, read = [], Path.read_bytes

            def once(target):
                calls.append(target)
                self.assertEqual(calls, [path], 'historical report was read more than once')
                return read(target)

            with mock.patch.object(Path, 'read_bytes', new=once), \
                 mock.patch.object(Path, 'read_text', side_effect=AssertionError('unexpected second text read')):
                result = receipt.replay_null(path)
            self.assertEqual(calls, [path])
            self.assertEqual(result['source_sha256'], receipt.digest(content))
            self.assertFalse(result['promotable'])

    def row(self, values):
        cell = abba.Cell('resolution', '1s', 0, 1, 1, 'GET', 1, 512, score='latency')
        runs = [raw_run(cell, arm, 1, index, PromotionControls.env)
                for index, arm in enumerate(abba.ORDER, 1)]
        for run, value in zip(runs, values):
            run['latency_ms'] = value
        return cell, dict(cell=asdict(cell), rounds=[dict(instances=1, runs=runs)])

    def collect(self, values, extra):
        cell, row = self.row(values)
        calls, frozen = [], []
        def persist():
            frozen.append(copy.deepcopy(row['null_sampling_plan']))
        def measure(arm, sequence, instances):
            self.assertTrue(frozen, 'repeat requested before exact plan persistence')
            self.assertEqual(row['null_sampling_plan'], frozen[0], 'plan changed after sampling began')
            calls.append((arm, sequence, instances))
            run = raw_run(cell, arm, instances, sequence, PromotionControls.env)
            run['latency_ms'] = extra[(sequence - 1) % len(abba.ORDER)]
            return run
        sampling.collect(cell, row, measure, persist)
        sampling.validate(row, sampling.policy())
        return cell, row, calls

    def test_cv_permits_fixed_repeats_and_all_signed_deltas_pool_to_resolving(self):
        def assertion():
            _, row, calls = self.collect((99.5, 102.5, 103.5, 100.5), (99.5, 99.5, 100.5, 100.5))
            self.assertEqual(row['null_sampling_plan']['planned_blocks'], 2, 'permitted-CV plan must be two blocks')
            self.assertEqual(len(calls), 4, 'fixed repeat block did not complete')
            metric = evidence.null_resolution({'cells': [row]})[0]
            self.assertEqual(metric['status'], 'RESOLVING', 'pooled delta must resolve after all planned samples')
            self.assertAlmostEqual(metric['absolute_delta_pct'], 1.5)
        assertion()
        with throwaway(evidence, 'null_resolution', 'row["rounds"] + row.get("null_repeats", [])', 'row["rounds"]'):
            with self.assertRaises(AssertionError): assertion()
        print('CV-permitted: two blocks, pooled |delta| 1.5%, RESOLVING; removing all-block pooling fails exact assertion')

    def test_unattainable_cv_stops_at_frozen_budget_and_raw_maximum_never_shrinks(self):
        def assertion():
            _, row, calls = self.collect((90., 100., 100., 110.), (100., 100., 100., 100.))
            plan = row['null_sampling_plan']
            self.assertEqual(plan['metrics'][0]['required_samples_per_arm'], 25)
            self.assertEqual((plan['planned_blocks'], plan['budget_limited'], len(calls)), (4, True, 12))
            metric = evidence.null_resolution({'cells': [row]})[0]
            self.assertEqual((metric['status'], metric['reference_spread_pct']), ('UNRESOLVED', 20.))
        assertion()
        with throwaway(sampling, 'collect', 'range(1, row["null_sampling_plan"]["planned_blocks"])', 'range(1, 2)'):
            with self.assertRaisesRegex(ValueError, 'incomplete fixed null sampling plan'): assertion()
        with throwaway(evidence, 'null_resolution', 'samples),\n                                   "null reference spread"',
                       'samples[-1:]),\n                                   "null reference spread"'):
            with self.assertRaises(AssertionError): assertion()
        print('CV 10%: needs 25 samples/arm, cap 8; all 4 blocks retained, UNRESOLVED; truncation/max-removal detected')

    def test_repeat_plan_cannot_be_missing_truncated_reordered_or_refitted(self):
        _, row, _ = self.collect((90., 100., 100., 110.), (100.,) * 4)
        for name, mutate, reason in (
            ('missing plan', lambda r: r.pop('null_sampling_plan'), 'plan differs from pilot'),
            ('truncated repeats', lambda r: r['null_repeats'].pop(), 'incomplete fixed null sampling plan'),
            ('reordered repeats', lambda r: r['null_repeats'].reverse(), 'repeat order/load differs'),
            ('refitted plan', lambda r: r['null_sampling_plan'].update(planned_blocks=2), 'plan differs from pilot')):
            broken = copy.deepcopy(row); mutate(broken)
            with self.subTest(state=name), self.assertRaisesRegex(ValueError, reason):
                sampling.validate(broken, sampling.policy())
            with mock.patch.object(sampling, 'validate'):
                with self.assertRaises(AssertionError):
                    with self.assertRaisesRegex(ValueError, reason): sampling.validate(broken, sampling.policy())
            print(f'{name}: REFUSED ({reason}); removing plan validation breaks exact oracle')

    def test_unresolved_nonloss_is_reporting_only_and_beyond_floor_still_fails(self):
        cell, row = self.row((100.,) * 4)
        bounds = {'latency_ms': dict(spread=4., abs_delta=1., status='UNRESOLVED')}
        def assertion():
            assessment = abba.assess(cell, row['rounds'], bounds)
            self.assertEqual(assessment['verdict'], 'UNRESOLVED', 'non-loss on unresolved null cannot PASS')
            self.assertEqual(abba.overall([dict(cell=asdict(cell), assessment=assessment, verdict=assessment['verdict'])])[0],
                             'UNRESOLVED', 'overall cannot certify reporting-only rows')
        assertion()
        with throwaway(abba, 'assess', 'if unresolved else "PASS"', 'if False else "PASS"'):
            with self.assertRaises(AssertionError): assertion()
        for run in row['rounds'][0]['runs']:
            if run['arm'] == 'B': run['latency_ms'] = 101.5
        def loss_assertion():
            result = abba.assess(cell, row['rounds'], bounds)
            self.assertEqual((result['verdict'], result['reasons']),
                ('FAIL', ['paired regression exceeds measured reference spread']), '1.5% loss must FAIL a 1% floor')
        loss_assertion()
        with throwaway(abba, 'assess', 'loss > threshold', 'False'):
            with self.assertRaises(AssertionError): loss_assertion()
        print('UNRESOLVED non-loss/overall + beyond-floor FAIL; removing status or loss guard fails exact oracle')

    def test_replay_is_reporting_only_and_rejects_nonfinite_nonpositive_or_incomplete_blocks(self):
        _, row = self.row((90., 100., 100., 110.))
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as tmp:
            path = Path(tmp) / 'results.json'
            receipt.write_json(path, {'cells': [row]})
            result = receipt.replay_null(path)
            self.assertEqual((result['kind'], result['reporting_only'], result['promotable']),
                             ('null-resolution-replay', True, False))
            with self.assertRaisesRegex(ValueError, 'ABBA measurements did not all pass'):
                evidence.validate_null(result, now=time.time())
        for value in (0., -1., float('inf'), float('nan')):
            broken = copy.deepcopy(row); broken['rounds'][0]['runs'][0]['latency_ms'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'invalid null latency_ms'):
                evidence.null_resolution({'cells': [broken]})
        for values in ([0, 1, 2], [0, 3, 1, 2]):
            broken = copy.deepcopy(row)
            broken['rounds'][0]['runs'] = [broken['rounds'][0]['runs'][index] for index in values]
            with self.assertRaisesRegex(ValueError, 'incomplete or reordered null block'):
                evidence.null_resolution({'cells': [broken]})
        with throwaway(receipt, 'replay_null', 'promotable=False', 'promotable=True'):
            with tempfile.TemporaryDirectory(dir=ROOT / 'build') as tmp:
                path = Path(tmp) / 'results.json'; receipt.write_json(path, {'cells': [row]})
                with self.assertRaises(AssertionError): self.assertFalse(receipt.replay_null(path)['promotable'])
        print('Replay has no promotion identity; invalid raw values/ORDER refused; reporting-only marker removal detected')


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
                config = fixture_measurements(); prior = copy.deepcopy(config)
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
                measurements.import_calibration(path, fixture_measurements(), cells)
            self.assertFalse(saturation_exempt(cells[-1]))
            for module in (measurements, evidence, abba):
                with mock.patch.object(module, 'saturation_exempt', return_value=True):
                    with self.assertRaises(AssertionError):
                        self.assertFalse(module.saturation_exempt(cells[-1]))


    def test_each_depth_only_branch_restoration_breaks_its_exempt_fixture(self):
        cell = abba.Cell('tail32', '1s', 0, 1, 1, 'REORDER', 32, 512, score='p999', mix='8:2')
        fp = instrument_fingerprint(ROOT)
        env = copy.deepcopy(PromotionControls.env)
        fast = fixture_report([cell], fp, env, 'tail fixture\n', int(time.time())-10000,
                              PromotionControls.binary, fast=True)
        normal = fixture_report([cell], fp, env, 'tail fixture\n', int(time.time())-10000,
                                PromotionControls.binary)
        cases = [
            (measurements, 'validate_fast_calibration', 'saturation_exempt(cell)', 'cell.depth == 1', 0, 'row status'),
            (measurements, 'validate_fast_calibration', 'saturation_exempt(cell)', 'cell.depth == 1', 1, 'selection status'),
            (measurements, 'import_calibration', 'saturation_exempt(cell)', 'cell.depth == 1', 0, 'import selection'),
            (measurements, 'import_calibration', 'saturation_exempt(cell)', 'cell.depth == 1', 1, 'import skip'),
            (evidence, 'validate_measurements', 'if not exempt and', 'if cell["depth"] > 1 and', 0, 'replay occupancy'),
        ]
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as tmp:
            path = Path(tmp) / 'calibration.json'; receipt.write_json(path, fast)
            def assertion(module):
                if module is evidence:
                    evidence.validate_measurements(normal, now=time.time())
                else:
                    self.assertEqual(measurements.import_calibration(path, fixture_measurements(), [cell]), [])
            for module, name, old, new, occurrence, state in cases:
                with self.subTest(state=state):
                    assertion(module)
                    with throwaway(module, name, old, new, occurrence):
                        with self.assertRaises((ValueError, AssertionError)):
                            assertion(module)
                    print(f'RESTORED depth-only {state}: dedicated p999 depth32 fixture failed as required')

    def test_unsaturated_depth32_rate_cannot_claim_exempt_even_when_predicate_removed(self):
        from load_calibration import select_calibration_floor
        cell = abba.Cell('deep_rate', '1s', 0, 1, 1, 'GET', 32, 512, score='rate')
        env = PromotionControls.env
        rounds = [dict(instances=n, runs=[raw_run(cell, 'B', n, i, env, fast=True, score=1)])
                  for i, n in enumerate((1, 2), 1)]
        def assertion():
            self.assertEqual(select_calibration_floor(cell, rounds)['status'], 'UNPROVEN')
        assertion()
        with mock.patch.object(abba, 'saturation_exempt', return_value=True):
            with self.assertRaises(AssertionError): assertion()
        print('REMOVAL canonical predicate -> all exempt: unsaturated depth32 RATE assertion failed')


def self_test():
    suite = unittest.TestSuite()
    # Exemption fixtures use only immutable metadata retained by PromotionControls.
    for cls in (PromotionControls, NullpublishControls, ExemptionControls):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(self_test())
