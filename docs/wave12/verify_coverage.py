#!/usr/bin/env python3
"""Check whole-job receipts against the requested geometry matrix, not run totals."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from collect_jobs import collect
from select_jobs import job_names

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave12'
PERFORMANCE = {
    'flip_saturated': 'NOT RUN: memtier throughput workload is reserved for the maintainer.',
    'efficiency': 'NOT RUN: performance comparison is reserved for the maintainer.',
}
BUILD_ONLY = {
    'tailgen_build': 'NOT RUN as a gate job: gate_subset.sh rejects a build-only prerequisite '
                     'without a consuming job. Its only consumer is the reserved inline '
                     'client-lb load-generator check. make all/freshness is recorded separately.',
}
STREAM_MEMORY_BOUNDS = (
    'sustained exact trim reaches a memory plateau',
    'one-entry memory floor tracks ~140B design (well below 4.4KiB)',
    'growth across the embedded->macro boundary stays amortized-linear',
)
RESERVED_LABELS = {
    'expire-index growth bound', 'borrow-registry growth bound',
    'cross-shard dispatch scaling', 'FLIP applies under saturated load',
    'flip battery shutdown invariants', 'atomic MGET/MSET floor (N/s >= 120k)',
    'tailgen client-lb outstanding bound',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--partial', action='store_true')
    args = parser.parse_args()
    inventory = collect()
    (DOC / 'correctness-jobs.json').write_text(json.dumps(inventory, indent=2) + '\n')
    post = hashlib.sha256((ROOT / 'build/wave12/tomokv-POST').read_bytes()).hexdigest()
    matrix = json.loads((DOC / 'correctness-matrix.json').read_text())
    attempts = []
    for run in inventory['runs']:
        if not run['name'].startswith('landing-') or run['binary_sha256'] != post:
            continue
        receipt = json.loads((ROOT / run['receipt']).read_text())
        assert receipt['binary_unchanged'] and receipt['source_tree_unchanged'], run['name']
        for job in run['jobs']:
            passed = job.get('exit') == 0 and job.get('failed') == 0
            memory_lines = []
            if run['name'].startswith('landing-footprints-') and job['name'] in matrix['release_footprints_each_engine']:
                atomic = job['name'].rsplit('-', 1)[1]
                prefix = 'gate-fusedarmed-stream-' if 'armed' in job['name'] else 'gate-stream-'
                path = Path(job['artifact']) / (prefix + atomic + '.txt')
                lines = path.read_text().splitlines() if path.exists() else []
                memory_lines = [line for line in lines if any(name in line for name in STREAM_MEMORY_BOUNDS)]
                passed &= all(sum(line.startswith('  ok   ' + name) for line in memory_lines) == 1
                              for name in STREAM_MEMORY_BOUNDS)
            attempts.append(dict(run=run['name'], job=job['name'],
                                 mode='1s' if run['env']['GATE_TXN_FUSED'] == '1' else '2s',
                                 engine=run['env']['GATE_NET_IO'],
                                 atomic=run['env'].get('GATE_TXN_ATOMIC', '1'),
                                 release_footprints=run['env'].get('GATE_PROOF_NO_RATES') == '0',
                                 passed=passed, release_memory_bounds=memory_lines,
                                 details=job))

    requirements = []

    def require(job, **geometry):
        matches = [a for a in attempts if a['job'] == job and a['passed'] and
                   all(a[k] == v for k, v in geometry.items())]
        requirements.append(dict(job=job, **geometry, passed=bool(matches),
                                 receipts=sorted({a['run'] for a in matches})))

    for job in dict.fromkeys(matrix['once'] + matrix['new_lanes_once']):
        require(job)
    for job in matrix['each_mode']:
        for mode in ('1s', '2s'):
            require(job, mode=mode)
    for job in matrix['each_engine']:
        for engine in ('uring', 'epoll'):
            require(job, engine=engine)
    for job in matrix['each_mode_engine']:
        for mode in ('1s', '2s'):
            for engine in ('uring', 'epoll'):
                require(job, mode=mode, engine=engine,
                        **({'atomic': '1'} if job == 'script_bounds' else {}))
    for mode in ('1s', '2s'):
        for engine in ('uring', 'epoll'):
            require('script_bounds', mode=mode, engine=engine, atomic='0')
    for engine in ('uring', 'epoll'):
        for job in matrix['release_footprints_each_engine']:
            require(job, engine=engine, release_footprints=True)
        for job in ('differ-split-0', 'differ-split-1', 'differ-armed-0',
                    'differ-armed-1', 'differ-equivalence'):
            require(job, engine=engine)
    for job in matrix['tcl']:
        require(job, run='landing-tcl-quiet')
    require('flushfix3', run='landing-flush-idle')
    require('abba_selftest', run='landing-abba-selftest-final')

    registry = set(job_names())
    completed = {a['job'] for a in attempts if a['passed']}
    missing = sorted(registry - completed - PERFORMANCE.keys() - BUILD_ONLY.keys())
    assert not (completed & PERFORMANCE.keys()), 'unexpected performance job execution'
    expected = json.loads((DOC / 'row-inventory.json').read_text())['post']['rows']
    expected_counts = Counter(row['label'] for row in expected)
    # Select one complete passing invocation per registered job. Extra geometry
    # repeats cannot fill a missing duplicate declaration in another job.
    canonical_jobs = {}
    for attempt in attempts:
        if attempt['passed']:
            canonical_jobs.setdefault(attempt['job'], attempt)
    counts = Counter(row['label'] for a in canonical_jobs.values()
                     for row in a['details'].get('rows', []) if row['status'] == 'ok')
    ledger_rows = sum(min(counts[label], count) for label, count in expected_counts.items())
    folded_labels = []
    # GATE_ONLY_JOBS emits the five private children and omits the two public
    # folds. capture_differ uses gate.sh's own strict fold, including journals,
    # mode-equivalence witnesses and mandatory MULTI repeats, on both engines.
    folded = DOC / 'differential-proof.json'
    if folded.exists():
        proofs = json.loads(folded.read_text())
        assert {p['engine'] for p in proofs} == {'uring', 'epoll'} and len(proofs) == 2
        assert all(p['passed'] and p['binary_sha256'] == post and
                   all(f['complete'] for f in p['folds'].values()) for p in proofs)
        for label in ('Redis 7.4 differential matrix',
                      'Redis 7.4 differential matrix (armed fused + read-local)'):
            counts[label] = max(counts[label], 1)
            folded_labels.append(dict(label=label, proof=str(folded.relative_to(ROOT))))
    missing_counts = expected_counts - counts
    pending = missing_counts.copy()
    remaining = []
    for row in expected:
        if pending[row['label']]:
            remaining.append(row)
            pending[row['label']] -= 1
    row_multiset_passed = missing_counts == Counter({label: 1 for label in RESERVED_LABELS})
    arm_smokes = []
    for arm in ('PRE', 'PAD-A'):
        path = DOC / f'jobs/landing-arm-{arm}-smoke.json'
        row = dict(arm=arm, passed=False)
        if path.exists():
            receipt = json.loads(path.read_text())
            expected_sha = hashlib.sha256((ROOT / 'build/wave12' / ('tomokv-' + arm)).read_bytes()).hexdigest()
            directory = Path(receipt['artifacts']) / 'jobs/dbdefault'
            done = list(map(int, (directory / 'done').read_text().split()))
            result = json.loads((directory / 'dbdefault/results.json').read_text())
            row.update(receipt=str(path.relative_to(ROOT)), binary_sha256=receipt['binary_sha256'],
                       modes=result['results'])
            row['passed'] = (receipt['exit'] == 0 and receipt['binary_sha256'] == expected_sha and
                             receipt['binary_unchanged'] and done[0] == done[2] == 0 and
                             {r['mode'] for r in result['results']} == {'1s', '2s'} and
                             all(r['verdict'] == 'PASS' for r in result['results']))
        arm_smokes.append(row)
    output = dict(binary_sha256=post, requirements=requirements,
                  required_geometries=len(requirements),
                  satisfied_geometries=sum(r['passed'] for r in requirements),
                  registry_jobs=len(registry), completed_registry_jobs=len(registry & completed),
                  missing_required_registry_jobs=missing, not_run_performance=PERFORMANCE,
                  unselected_build_prerequisite=BUILD_ONLY,
                  declared_labels=len(expected), witnessed_declared_labels=len(expected) - len(remaining),
                  source_rows_witnessed_by_job_ledgers=ledger_rows,
                  public_differential_folds=folded_labels,
                  declared_row_multiset_passed=row_multiset_passed,
                  duplicate_declarations=[dict(label=label, required=count, witnessed=counts[label])
                                          for label, count in sorted(expected_counts.items()) if count > 1],
                  canonical_job_receipts={name: a['run'] for name, a in sorted(canonical_jobs.items())},
                  unwitnessed_declared_labels=remaining,
                  release_stream_memory_bounds=[dict(run=a['run'], job=a['job'], engine=a['engine'],
                      passed=a['passed'], assertions=a['release_memory_bounds'])
                      for a in attempts if a['release_memory_bounds']],
                  failed_attempts=[{k: v for k, v in a.items() if k != 'details'} | {
                      'exit': a['details'].get('exit'), 'failed': a['details'].get('failed')}
                      for a in attempts if not a['passed']],
                  arm_boot_controls=arm_smokes,
                  passed=not missing and all(r['passed'] for r in requirements) and
                         all(r['passed'] for r in arm_smokes) and row_multiset_passed,
                  note='Whole-job matrix coverage, not a full iteration or performance gate. '
                       'Failed and superseded attempts remain in correctness-jobs.json. '
                       'Inline/rate-only rows are separately identified in the report.')
    (DOC / 'correctness-coverage.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({k: v for k, v in output.items() if k not in
                      ('requirements', 'unwitnessed_declared_labels', 'failed_attempts',
                       'arm_boot_controls', 'release_stream_memory_bounds')}, indent=2))
    if not args.partial:
        assert output['passed'], 'missing required job or geometry; inspect correctness-coverage.json'


if __name__ == '__main__':
    main()
