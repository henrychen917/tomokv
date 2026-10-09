#!/usr/bin/env python3
"""Mainline-only writeback null/sweep coordinator around the existing ABBA instrument.

--dry-run and --self-test are serverless. Other invocations run the owner's
scheduled experiment. Sampling, population, quiet checks and scoring stay in
tests/abbagate.py; only the sweep's per-arm boot plan differs.
"""
import argparse
import json
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import abbagate as abba

ARM_SETTINGS = {
    'A': {'wb-policy': 1, 'wb-small-pipe': 0, 'wb-complete-visits': 3},
    'B': {'wb-policy': 1, 'wb-small-pipe': 16, 'wb-complete-visits': 3},
}
BASE_PLAN, BASE_RUNNER = abba.knob_plan, abba.Runner


def sweep_plan(cell, support):
    flags = abba.server_arguments(cell.server_flags)
    if any(flag.split('=')[0] in {'--' + key for key in ARM_SETTINGS['A']} for flag in flags):
        raise ValueError('cell srv= flags cannot override the writeback sweep arms')
    plans, notes = BASE_PLAN(cell, support)
    return {arm: {**plan, **ARM_SETTINGS[arm]} for arm, plan in plans.items()}, notes


def verify_boot(conn, arm):
    fields = abba.info(conn, 'WRITEBACK')
    expected = ARM_SETTINGS[arm]
    for name, value in expected.items():
        if conn.must('CONFIG', 'GET', name) != [name.encode(), str(value).encode()]:
            raise ValueError('writeback sweep CONFIG mismatch: ' + name)
        if fields.get(name.replace('-', '_')) != str(value):
            raise ValueError('writeback sweep INFO mismatch: ' + name)
    return fields


class SweepRunner(BASE_RUNNER):
    def population_environment(self):
        return {**super().population_environment(), 'wbknobs_sweep': {
            'coordinator_sha256': abba.sha256(Path(__file__)), 'arms': ARM_SETTINGS,
            'same_binary_sha256': abba.sha256(Path(self.binaries['A']))}}

    def populate(self, cell, arm, conn, folder):
        if abba.sha256(Path(self.binaries['A'])) != abba.sha256(Path(self.binaries['B'])):
            raise ValueError('writeback sweep requires identical ELF bytes in both arms')
        boot = verify_boot(conn, arm)
        population = super().populate(cell, arm, conn, folder)
        return {**(population or {}), 'wbknobs_boot': boot}


class ProfileQuiet(abba.QuietMonitor):
    def set_phase(self, phase):
        # Match the existing ASLR diagnostic adapter: phase labels cannot relax
        # the ordinary selected-core/port budget or erase a latched refusal.
        self.check()


def self_test():
    import tempfile
    from types import SimpleNamespace
    class Connection:
        def __init__(self, arm): self.values = ARM_SETTINGS[arm]
        def must(self, *args):
            name = args[2]
            return [name.encode(), str(self.values[name]).encode()]
    def info(conn, section):
        assert section == 'WRITEBACK'
        return {key.replace('-', '_'): str(value) for key, value in conn.values.items()}
    with mock.patch.object(abba, 'info', info):
        for arm in ARM_SETTINGS:
            verify_boot(Connection(arm), arm)
        try:
            verify_boot(Connection('B'), 'A')
            raise AssertionError('ignored S=0 control passed')
        except ValueError as error:
            assert 'CONFIG mismatch: wb-small-pipe' in str(error)
    with mock.patch.object(abba, 'info', return_value={'wb_policy': '1'}):
        try:
            verify_boot(Connection('A'), 'A')
            raise AssertionError('missing INFO control passed')
        except ValueError as error:
            assert 'INFO mismatch: wb-small-pipe' in str(error)
    global BASE_PLAN
    original = BASE_PLAN
    try:
        BASE_PLAN = lambda cell, support: ({arm: {'atomic': 1} for arm in ARM_SETTINGS}, [])
        plans, _ = sweep_plan(SimpleNamespace(server_flags=''), {})
        assert plans['A']['wb-small-pipe'] == 0 and plans['B']['wb-small-pipe'] == 16
        assert all(plans[arm]['atomic'] == 1 for arm in plans)
        try:
            sweep_plan(SimpleNamespace(server_flags='--wb-small-pipe 16'), {})
            raise AssertionError('srv= override control passed')
        except ValueError as error:
            assert 'cannot override' in str(error)
    finally:
        BASE_PLAN = original
    # Exercise the real CLI/delegation boundary without entering the instrument
    # or starting a process. In particular PMU mode must stay diagnostic-only.
    with tempfile.TemporaryDirectory(prefix='wbknobs-plan-', dir=ROOT / 'build') as directory:
        candidate = Path(directory) / 'candidate'
        candidate.write_bytes(b'fixture bytes; never executed')
        for experiment, profile in (('null', 0), ('sweep', 0), ('sweep', 1)):
            def instrument(args, *, diagnostic_monitor, diagnostic_profile):
                assert args.candidate == candidate and args.build_reference == 0
                assert diagnostic_profile == profile
                assert diagnostic_monitor is (ProfileQuiet if profile else None)
                assert abba.knob_plan is (sweep_plan if experiment == 'sweep' else BASE_PLAN)
                assert abba.Runner is (SweepRunner if experiment == 'sweep' else BASE_RUNNER)
                if experiment == 'sweep':
                    assert args.reference_binary == candidate
                return 23
            argv = [__file__, '--experiment', experiment, '--profile', str(profile),
                    '--candidate', str(candidate)]
            with mock.patch.object(sys, 'argv', argv), mock.patch.object(abba, 'main', instrument):
                assert main() == 23
            assert abba.knob_plan is BASE_PLAN and abba.Runner is BASE_RUNNER
    print('PASS wbknobs coordinator: arm selection, ignored knob, missing INFO, override controls, '
          'normal/diagnostic delegation without server execution')


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--experiment', choices=('null', 'sweep'), default='null')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--profile', type=int, choices=(0, 1), default=0,
                        help='1 requests existing PMU diagnostics; that run is not gate/null evidence')
    options, remaining = parser.parse_known_args()
    if options.self_test:
        self_test(); return 0
    if '--cells' not in remaining:
        remaining += ['--cells', str(ROOT / 'tests' / (
            'wbknobs_sweep_cells.txt' if options.experiment == 'sweep' else 'wbland_merit_cells.txt'))]
    sys.argv = [sys.argv[0], *remaining]
    args = abba.parse_args()
    if any((args.collect_null, args.null_holdout, args.calibrate, args.pin, args.collect_reorder_controls)):
        raise ValueError('this coordinator runs only the declared null comparison or S=0/default sweep')
    args.build_reference = 0
    if options.experiment == 'sweep':
        if args.reference_binary and abba.sha256(args.reference_binary) != abba.sha256(args.candidate):
            raise ValueError('sweep reference must have the candidate ELF SHA-256')
        args.reference_binary = args.candidate
    if options.dry_run:
        cells = abba.selected_cells(abba.read_cells(args.cells), args.subset, args.only)
        print(json.dumps(dict(experiment=options.experiment, cells=[cell.id for cell in cells],
                              candidate=str(args.candidate), reference=str(args.reference_binary or 'newest headline'),
                              arms=ARM_SETTINGS if options.experiment == 'sweep' else 'both boot defaults',
                              order=list(abba.ORDER), profile=options.profile,
                              normal_gate_eligible=not options.profile), indent=2))
        return 0
    try:
        if options.experiment == 'sweep':
            abba.knob_plan, abba.Runner = sweep_plan, SweepRunner
        # The instrument explicitly reserves PMU collection for a diagnostic
        # run. Keep its permanent untrusted marker and the ordinary quiet checks.
        return abba.main(args, diagnostic_monitor=ProfileQuiet if options.profile else None,
                         diagnostic_profile=options.profile)
    finally:
        abba.knob_plan, abba.Runner = BASE_PLAN, BASE_RUNNER


if __name__ == '__main__':
    raise SystemExit(main())
