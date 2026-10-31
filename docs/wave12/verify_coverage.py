#!/usr/bin/env python3
"""Check whole-job receipts against the requested geometry matrix, not run totals."""
import argparse
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
            attempts.append(dict(run=run['name'], job=job['name'],
                                 mode='1s' if run['env']['GATE_TXN_FUSED'] == '1' else '2s',
                                 engine=run['env']['GATE_NET_IO'],
                                 atomic=run['env'].get('GATE_TXN_ATOMIC', '1'),
                                 release_footprints=run['env'].get('GATE_PROOF_NO_RATES') == '0',
                                 passed=job.get('exit') == 0 and job.get('failed') == 0,
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
    require('abba_selftest', run='landing-abba-selftest')

    registry = set(job_names())
    completed = {a['job'] for a in attempts if a['passed']}
    missing = sorted(registry - completed - PERFORMANCE.keys() - BUILD_ONLY.keys())
    assert not (completed & PERFORMANCE.keys()), 'unexpected performance job execution'
    expected = json.loads((DOC / 'row-inventory.json').read_text())['post']['rows']
    labels = {row['label'] for a in attempts if a['passed']
              for row in a['details'].get('rows', []) if row['status'] == 'ok'}
    # Collector-generated labels (notably the two differential aggregates) do
    # not live in child job ledgers; retain the final partial ledger as well.
    for run in inventory['runs']:
        if not run['name'].startswith('landing-') or run['binary_sha256'] != post or run['exit']:
            continue
        ledger = DOC / 'jobs' / (run['name'] + '.tsv.partial')
        if ledger.exists():
            for line in ledger.read_text().splitlines():
                fields = line.split('\t', 2)
                if len(fields) == 3 and fields[0] == 'ok':
                    labels.add(fields[2])
    remaining = [row for row in expected if row['label'] not in labels]
    output = dict(binary_sha256=post, requirements=requirements,
                  required_geometries=len(requirements),
                  satisfied_geometries=sum(r['passed'] for r in requirements),
                  registry_jobs=len(registry), completed_registry_jobs=len(registry & completed),
                  missing_required_registry_jobs=missing, not_run_performance=PERFORMANCE,
                  unselected_build_prerequisite=BUILD_ONLY,
                  declared_labels=len(expected), witnessed_declared_labels=len(expected) - len(remaining),
                  unwitnessed_declared_labels=remaining,
                  failed_attempts=[{k: v for k, v in a.items() if k != 'details'} | {
                      'exit': a['details'].get('exit'), 'failed': a['details'].get('failed')}
                      for a in attempts if not a['passed']],
                  passed=not missing and all(r['passed'] for r in requirements),
                  note='Whole-job matrix coverage, not a full iteration or performance gate. '
                       'Failed and superseded attempts remain in correctness-jobs.json. '
                       'Inline/rate-only rows are separately identified in the report.')
    (DOC / 'correctness-coverage.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({k: v for k, v in output.items() if k not in
                      ('requirements', 'unwitnessed_declared_labels', 'failed_attempts')}, indent=2))
    if not args.partial:
        assert output['passed'], 'missing required job or geometry; inspect correctness-coverage.json'


if __name__ == '__main__':
    main()
