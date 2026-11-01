#!/usr/bin/env python3
"""Close the delivery ledger without treating recorded exceptions as a gate pass."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave13'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    assert os.sched_getaffinity(0) <= set(range(16))
    inputs = {}

    def read(name):
        path = DOC / name
        inputs[name] = sha(path)
        return json.loads(path.read_text())

    delivery = read('delivery-verification.json')
    assert delivery['target_count'] == 51 and delivery['fresh_targets'] == 59
    assert all(row['exit'] == 0 for row in delivery['freshness'])
    assert not subprocess.check_output(
        ['git', 'diff', delivery['production_commit'], '--', 'src', 'third_party', 'Makefile'], cwd=ROOT)
    for arm in delivery['arms'].values():
        assert sha(ROOT / arm['path']) == arm['sha256']
        assert sha(ROOT / (arm['path'] + '.asserts.tsv')) == arm['asserts_sha256']
    post = delivery['arms']['POST']['sha256']
    assert sha(ROOT / 'build/tomokv') == post

    census = read('row-inventory.json')
    assert (census['post']['quick'], census['post']['full']) == (1046, 1063)
    assert census['landing_fixture_matches'] and census['archived_fixture_labels_match']
    assert sha(ROOT / census['fixture_path']) == census['fixture_sha256']
    coverage = read('correctness-coverage.json')
    assert coverage['binary_sha256'] == post
    missing = [row for row in coverage['requirements'] if not row['passed']]
    assert len(missing) == 1 and missing[0]['job'] == 'datafix1_locale', missing
    assert coverage['missing_required_registry_jobs'] == ['datafix1_locale']
    assert coverage['completed_registry_jobs'] == 284 and coverage['registry_jobs'] == 288
    assert coverage['witnessed_declared_labels'] == 1055
    assert all(row['passed'] for row in coverage['arm_boot_controls'])
    assert not coverage['passed'], 'The locale exception must remain visible'

    counts = read('instruction-comparison.json')['comparisons']
    assert len(counts['headline_native']) == 244 and len(counts['headline_lua']) == 96
    main_rows = [r for r in counts['headline_native'] if r['command'] in ('GET', 'SET', 'INCR')]
    expected = set(itertools.product(('normal', 'db0'), ('GET', 'SET', 'INCR'),
                                     ('1s', '2s'), (1, 32), (0, 1)))
    assert {(r['namespace'], r['command'], r['mode'], r['batch'], r['atomic'])
            for r in main_rows} == expected
    assert all(r['delta'] == 0 for r in main_rows)
    local_rows = [r for r in counts['headline_native'] if r['command'] == 'READLOCAL-GET']
    assert len(local_rows) == 4 and all(r['delta'] == 0 for r in local_rows)
    for name, arm, bodies in (
            ('binding-final-post.json', 'POST', 696), ('binding-pre.json', 'PRE', 696),
            ('binding-final-gc-lua.json', 'POST', 432), ('binding-pre-gc-lua.json', 'PRE', 432)):
        binding = read(name)
        assert binding['passed'] and len(binding['bodies']) == bodies
        assert binding['server_sha256'] == delivery['arms'][arm]['sha256']
    assert read('binding-supplied-headline.json')['passed']
    identity = read('identity/summary.json')
    assert identity['residual'] == 283
    assert read('interaction-receipts.json')['passed']
    assert read('aof-window-negative-control.json')['verified']
    assert read('locale-C-reruns.json')['passed']
    assert read('gates-test.json')['exit'] == 0
    differential = read('differential-proof.json')
    assert len(differential) == 2 and all(row['passed'] for row in differential)
    regressions = read('isolated-regressions.json')
    assert regressions and all(row['verified'] and row['post_sha256'] == post for row in regressions)

    copy = read('abba-copy-replay.json')
    assert copy['passed'] and copy['only_tracked_file_differences'] == ['tests/gate.sh']
    abba = read('jobs/landing-abba-selftest-isolated.json')
    assert abba['exit'] == 0 and abba['tests_tools_unchanged'] and abba['source_tree_unchanged']
    assert abba['gate_sha256'] == copy['copy_gate_sha256'] and abba['binary_sha256'] == post
    assert sha(ROOT / 'tests/gate.sh') == copy['root_gate_sha256']
    disk_bytes = int(subprocess.check_output(['du', '-s', '-B1', 'build'], cwd=ROOT).split()[0])
    assert disk_bytes < 40 * 1024**3
    result = dict(binary_sha256=post, row_counts=dict(quick=1046, full=1063, delta=47),
                  runnable_correctness_completed=True, full_gate_pass=False,
                  geometry_requirements=coverage['required_geometries'],
                  satisfied_geometries=coverage['satisfied_geometries'],
                  witnessed_labels=1055, main_zero_delta_cells=len(main_rows),
                  read_local_zero_delta_cells=len(local_rows), native_cells=244, lua_cells=96,
                  universal_body_identity=False, residual_body_groups=283,
                  not_run=coverage['not_run_performance'] | coverage['constraint_exclusions'],
                  build_bytes=disk_bytes, inputs=inputs,
                  note='All runnable authorized correctness requirements are witnessed. '
                       'The non-C locale row, universal body identity, PAD placement limits, '
                       'performance merit and the full landing iteration remain explicit exceptions.')
    (DOC / 'final-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
