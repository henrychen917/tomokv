#!/usr/bin/env python3
"""Revalidate both complete Tcl receipts with the runner's exact assertion multiset."""
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave12'
sys.path.insert(0, str(ROOT / 'tests'))
import redis_tcl as tcl


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    receipt = json.loads((DOC / 'jobs/landing-tcl-quiet.json').read_text())
    post = sha(ROOT / 'build/wave12/tomokv-POST')
    assert receipt['exit'] == 0 and receipt['binary_sha256'] == post
    assert receipt['source_tree_unchanged'] and receipt['tests_tools_unchanged']
    directory = Path(receipt['artifacts']) / 'jobs/redis_tcl'
    manifest_path = ROOT / 'tests/redis_tcl_passing.json'
    modes, archives = {}, []
    for mode in ('2s', '1s'):
        output = directory / ('redis-tcl-' + mode)
        summary = json.loads((output / 'summary.json').read_text())
        assert summary['mode'] == mode and summary['binary_sha256'] == post
        manifest = tcl.load_manifest(manifest_path, Path('/home/user/Projects/redis'), summary['inventory'])
        rows = iter(summary['rows'])
        required = 0
        for unit, spec in manifest['files'].items():
            row = next(rows)
            assert row['file'] == unit and row['mode'] == mode
            isolated = spec.get('isolated_tests', {})
            expected = [name for name in spec['passed_tests'] if name.split(' in tests/')[0] not in isolated]
            tcl.validate_passing(row, expected, spec.get('known_setup_errors', ()), spec.get('setup_only', False))
            required += len(expected)
            for name in isolated:
                row = next(rows)
                assert row['file'] == unit and row['mode'] == mode and row['isolation_reason']
                expected = [label for label in spec['passed_tests'] if label.split(' in tests/')[0] == name]
                tcl.validate_passing(row, expected)
                required += len(expected)
        assert next(rows, None) is None and required == 1875
        modes[mode] = dict(files=len(manifest['files']), executions=len(summary['rows']),
                           required_assertion_occurrences=required, exact_multisets_passed=True,
                           summary_sha256=sha(output / 'summary.json'))
        for path in sorted(output.rglob('*.json')):
            relative = path.relative_to(output)
            if relative.parts[0] == 'checkout':
                continue
            dest = DOC / 'tcl-final' / mode / (str(relative) + '.gz')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
            archives.append(dict(source=str(path.relative_to(ROOT)), source_sha256=sha(path),
                                 archive=str(dest.relative_to(ROOT)), archive_sha256=sha(dest)))
    negative = json.loads((DOC / 'isolated-regressions.json').read_text())[-1]
    assert negative['post_sha256'] == post and negative['exit'] == 1 and negative['verified']
    assert negative['runner_sha256'] == sha(ROOT / 'tests/redis_tcl.py')
    assert negative['manifest_sha256'] == sha(manifest_path)
    assert set(negative['modes']) == {'1s', '2s'}
    for row in negative['modes'].values():
        assert row['verified'] and not row['deadline'] and 'err' in row['statuses']
    result = dict(binary_sha256=post, runner_sha256=negative['runner_sha256'],
                  manifest_sha256=sha(manifest_path), modes=modes, archives=archives,
                  planted_regression=dict(root=negative['root'], binary_sha256=negative['binary_sha256'],
                                           modes=negative['modes'], expected_failure_verified=True),
                  passed=True)
    (DOC / 'tcl-final-proof.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(modes=modes, planted_regression_verified=True), indent=2))


if __name__ == '__main__':
    main()
