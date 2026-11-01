#!/usr/bin/env python3
"""Bind the complete two-mode Tcl receipts to the reconciled assertion multiset."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave13'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    manifest_path = ROOT / 'tests/redis_tcl_passing.json'
    manifest = json.loads(manifest_path.read_text())
    receipt_path = DOC / 'jobs/landing-tcl-quiet.json'
    receipt = json.loads(receipt_path.read_text())
    assert receipt['exit'] == 0
    assert all(receipt[key] for key in
               ('binary_unchanged', 'source_tree_unchanged', 'tests_tools_unchanged'))
    assert receipt['binary_sha256'] == sha(ROOT / 'build/wave13/tomokv-POST')
    result = dict(receipt=str(receipt_path.relative_to(ROOT)), receipt_sha256=sha(receipt_path),
                  binary_sha256=receipt['binary_sha256'], manifest_sha256=sha(manifest_path),
                  runner_sha256=sha(ROOT / 'tests/redis_tcl.py'), modes={}, passed=True)
    for mode in ('1s', '2s'):
        path = Path(receipt['artifacts']) / 'jobs/redis_tcl' / ('redis-tcl-' + mode) / 'summary.json'
        report = json.loads(path.read_text())
        assert report['mode'] == mode and report['binary_sha256'] == result['binary_sha256']
        grouped = defaultdict(list)
        for row in report['rows']:
            assert not row['error'] and row['complete'], (mode, row['file'])
            grouped[row['file']].append(row)
        assert set(grouped) == set(manifest['files'])
        units = []
        for unit, spec in manifest['files'].items():
            rows = grouped[unit]
            actual = Counter(event['test'] for row in rows for event in row['events']
                             if event['status'] == 'ok')
            expected = Counter(spec['passed_tests'])
            assert actual == expected, (mode, unit, actual - expected, expected - actual)
            primary = [row for row in rows if 'skip_tests' in row]
            assert len(primary) == 1
            assert primary[0]['skip_tests'] == sorted(spec.get('skip_tests', ()))
            units.append(dict(file=unit, required_occurrences=sum(expected.values()),
                              witnessed_occurrences=sum(actual.values()),
                              named_skips=len(spec.get('skip_tests', ())),
                              setup_errors=primary[0].get('setup_errors', []),
                              fresh_runs=[run for row in rows for run in row.get('fresh_runs', [])],
                              order_retries=[row['monitor_order_retry'] for row in rows
                                             if 'monitor_order_retry' in row]))
        assert sum(row['required_occurrences'] for row in units) == 1878
        assert sum(row['named_skips'] for row in units) == 211
        result['modes'][mode] = dict(summary=str(path), summary_sha256=sha(path), units=units,
                                    required_occurrences=1878, witnessed_occurrences=1878,
                                    named_skips=211, passed=True)
    (DOC / 'tcl-positive-proof.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'modes'}, indent=2))


if __name__ == '__main__':
    main()
