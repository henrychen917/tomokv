#!/usr/bin/env python3
"""Serverless non-vacuity and gate-wiring controls for the upstream Tcl subset."""
import copy
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import json
from redis_tcl import counts, load_manifest, sha, validate_passing, ROOT


class Controls(unittest.TestCase):
    def test_no_missing_failed_skipped_renamed_or_duplicate_assertion_can_pass(self):
        row = dict(events=[dict(status='ok', test='a'), dict(status='ok', test='b')],
                   failed=0, error=None, complete=True, exit_code=0)
        validate_passing(row, ['a', 'b'])
        mutations = [lambda r: r['events'].pop(), lambda r: r['events'][0].update(status='skip'),
                     lambda r: r['events'][0].update(test='b'), lambda r: r.update(complete=False),
                     lambda r: r.update(failed=1), lambda r: r.update(error='timeout'),
                     lambda r: r.update(exit_code=1)]
        for mutate in mutations:
            bad = copy.deepcopy(row); mutate(bad)
            with self.assertRaises(ValueError): validate_passing(bad, ['a', 'b'])
        with self.assertRaises(ValueError): validate_passing({**row, 'events': []}, [])

    def test_only_the_exact_post_completion_controller_eof_is_not_an_assertion(self):
        eof = dict(status='exception', data='expected non-negative integer but got ""; read $::test_server_fd $bytes')
        done = dict(status='done', data='unit/fixture')
        before, complete = counts([eof, done], 'unit/fixture')
        self.assertEqual((before['failed'], complete), (1, True))
        after, complete = counts([done, eof], 'unit/fixture')
        self.assertEqual((after['failed'], after['teardown_exceptions'], complete), (0, 1, True))
        other, _ = counts([done, dict(status='exception', data='other failure')], 'unit/fixture')
        self.assertEqual(other['failed'], 1)

    def test_only_the_exact_named_block_setup_error_is_tolerated(self):
        reply = "ERR Unknown option or number of arguments for CONFIG SET - 'list-compress-depth'"
        err = dict(status='err', test='', data='n option or number of arguments\n' + reply +
                   '\n    while executing\n"[srv $level "client"] {*}$args"\n    (procedure "r" line 7)'
                   '\n    invoked from within\n"r config set list-compress-depth 2"\n    ("uplevel" body line 2)')
        known = [dict(command='r config set list-compress-depth 2', reply=reply, count=1)]
        row = dict(events=[err, dict(status='ok', test='a')], failed=1, error=None, complete=True, exit_code=1)
        validate_passing(row, ['a'], known)
        with self.assertRaises(ValueError):
            validate_passing(row, ['a'])  # an undeclared block-setup error fails
        mutations = {
            'twice': lambda r: (r['events'].append(dict(err)), r.update(failed=2)),
            'other command': lambda r: r['events'][0].update(data=err['data'].replace('depth 2"', 'depth 3"')),
            'other reply': lambda r: r['events'][0].update(data=err['data'].replace('CONFIG SET', 'CONFIG GET')),
            'named test failure': lambda r: r['events'][0].update(test='x in tests/unit/x.tcl'),
            'declared but absent': lambda r: (r['events'].pop(0), r.update(failed=0)),
            'another failure': lambda r: r.update(failed=2),
            'clean exit despite the error': lambda r: r.update(exit_code=0),
        }
        for name, mutate in mutations.items():
            bad = copy.deepcopy(row); mutate(bad)
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_passing(bad, ['a'], known)

    def test_manifest_binds_upstream_bytes_and_names_every_known_failure(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            (root / 'tests/unit').mkdir(parents=True)
            (root / 'tests/unit/fixture.tcl').write_text('test {a} {}\n')
            (root / 'runtest').write_text('#!/bin/sh\n')
            inventory = {'unit/fixture': sha(root / 'tests/unit/fixture.tcl')}
            good = dict(support={'runtest': sha(root / 'runtest')}, files={'unit/fixture': dict(
                sha256=inventory['unit/fixture'], passed_tests=['a'], skip_tests={'b': 'known failure'},
                extra_args=['--tags', '-needs:debug'])})
            path = root / 'manifest.json'
            path.write_text(json.dumps(good))
            self.assertEqual(load_manifest(path, root, inventory)['files']['unit/fixture']['passed_tests'], ['a'])
            spec = lambda m: m['files']['unit/fixture']
            mutations = {
                'no files': lambda m: m.update(files={}),
                'upstream bytes': lambda m: spec(m).update(sha256='0' * 64),
                'support bytes': lambda m: m['support'].update(runtest='0' * 64),
                'skip hides a required pass': lambda m: spec(m)['skip_tests'].update(a='hidden'),
                'no required pass': lambda m: spec(m).update(passed_tests=[]),
                'selection argument': lambda m: spec(m).update(extra_args=['--only', 'a']),
                'odd argument list': lambda m: spec(m).update(extra_args=['--tags']),
                'malformed setup error': lambda m: spec(m).update(known_setup_errors=[dict(command='', reply='x', count=1)]),
                'zero-count setup error': lambda m: spec(m).update(known_setup_errors=[dict(command='c', reply='x', count=0)]),
            }
            for name, mutate in mutations.items():
                bad = copy.deepcopy(good); mutate(bad)
                path.write_text(json.dumps(bad))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    load_manifest(path, root, inventory)

    def test_failed_or_missing_private_job_turns_existing_compatibility_row_red(self):
        gate = (ROOT / 'tests/gate.sh').read_text()
        body = gate[gate.index('job_compat2(){'):gate.index('\n# Each dispatchfix feature', gate.index('job_compat2(){'))]
        prelude = '''
set -u
CORES=32; PORT=45800; TMPDIR=$RUN_DIR; REDIS74_ROOT=unused; GATE_DIFFER_ORACLE_CORES=32
CANDIDATE_BINARY=unused
row_begin(){ :; }; py(){ :; }; taskset(){ :; }; unit_ready(){ :; }
ok(){ printf 'ok:%s\\n' "$1"; }; bad(){ printf 'FAIL:%s\\n' "$1"; }
'''
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            path = Path(directory) / 'unit-ready'; path.mkdir()
            for completed in (False, True):
                if completed: (path / 'redis-tcl').touch()
                result = subprocess.run(['bash', '-c', prelude + body + '\njob_compat2'],
                    env=dict(os.environ, RUN_DIR=directory), text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(('ok' if completed else 'FAIL') + ':compat2 autharity', result.stdout)


if __name__ == '__main__': unittest.main(verbosity=2)
