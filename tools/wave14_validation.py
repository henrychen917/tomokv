#!/usr/bin/env python3
"""Audit wave14's selected gate receipts without changing their verdicts."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from wave14 import ROOT, DOC, save, sha


def planned():
    names = ['merged-uring-consumers', 'merged-epoll']
    for filename in ('followthrough-plan.json', 'blockfix4-supplement-plan.json'):
        names.extend(p['tag'] for p in json.loads((DOC / filename).read_text())['plans'])
    return names


def phase(name, verify):
    base = DOC / 'jobs'
    started = base / (name + '-started.json')
    if not started.exists():
        return dict(tag=name, state='NOT STARTED')
    start = json.loads(started.read_text())
    command = start['command']
    assert start['env']['LC_ALL'] == 'C'
    assert command[:3] == ['taskset', '-c', '0-31']
    for flag in ('--server-cores', '--load-cores'):
        for piece in command[command.index(flag) + 1].split(','):
            limits = list(map(int, piece.split('-')))
            assert 0 <= min(limits) <= max(limits) <= 31
    lo, hi = map(int, command[command.index('--ports') + 1].split('-'))
    assert 20000 <= lo <= hi <= 20099
    paths = re.findall(r'^  artifacts: (.+)$', (base / (name + '.log')).read_text(), re.M)
    assert len(paths) == 1, (name, paths)
    root = Path(paths[0])
    requested = start['env']['GATE_ONLY_JOBS'].split()
    finished = base / (name + '.json')
    record = json.loads(finished.read_text()) if finished.exists() else None
    if record:
        assert record['binary_sha256'] == start['binary_sha256']
        if verify:
            assert sha(Path(record['archive'])) == record['archive_sha256']
    jobs = []
    for directory in sorted((root / 'jobs').iterdir()):
        done = directory / 'done'
        if not done.exists():
            continue
        rc, passed, failed = map(int, done.read_text().split())
        rows = []
        ledger = directory / 'ledger'
        if ledger.exists():
            for line in ledger.read_text().splitlines():
                status, seconds, label = line.split('\t', 2)
                rows.append(dict(status=status, seconds=float(seconds), label=label))
        assert passed == sum(r['status'] == 'ok' for r in rows), (name, directory)
        assert failed == sum(r['status'] != 'ok' for r in rows), (name, directory)
        # The gate's zero-exit done record follows successful bounded cleanup.
        # Nonzero exits need their original teardown log; do not infer a leak.
        jobs.append(dict(job=directory.name, exit_code=rc, passed=passed, failed=failed,
                         cleanup_proven_by_zero_exit=(True if rc == 0 else None), rows=rows))
    completed = {j['job'] for j in jobs}
    active = [p.name for p in (root / 'claimed').iterdir() if p.name not in completed]
    return dict(tag=name, state='COMPLETE' if record else 'RUNNING',
        binary_sha256=start['binary_sha256'], run_directory=str(root),
        requested=requested, unfinished=[n for n in requested if n not in completed],
        active=active, jobs=jobs, failed_jobs=[j['job'] for j in jobs if j['exit_code'] or j['failed']],
        passed=sum(j['passed'] for j in jobs), failed=sum(j['failed'] for j in jobs),
        exit_code=record['exit_code'] if record else None)


def differential(phases):
    sys.path.insert(0, str(ROOT / 'tests'))
    import differ_fanout as fanout
    results = []
    for phase in phases[:2]:
        if 'run_directory' not in phase:
            continue
        root = Path(phase['run_directory'])
        plan = fanout.load_plan(root / 'differ-plan.json')
        for group in ('split', 'armed'):
            try:
                result = fanout.fold(plan, group, root)
            except (ValueError, OSError, KeyError, TypeError) as error:
                result = dict(complete=False, error=str(error))
            results.append(dict(tag=phase['tag'], group=group, seeds=plan['manifest']['seeds'],
                mandatory_multi_repeats=plan['repeats'], evidence=result))
    return results


def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-archives', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    phases = [phase(name, args.verify_archives) for name in planned()]
    result = dict(phases=phases, differential=differential(phases),
        note='Repeated/prerequisite/private rows are not additions to the public gate count. '
             'Differential folds validate every seed, suite and equivalence cell; they do not '
             'publish or replace a full-gate timing/landing receipt.')
    if args.output:
        save(args.output, result)
    for item in phases:
        print(item['tag'], item['state'],
              f"{len(item.get('jobs', []))} jobs, {item.get('passed', 0)} pass, {item.get('failed', 0)} fail",
              'active=' + ','.join(item.get('active', [])),
              'red=' + ','.join(item.get('failed_jobs', [])))
    for item in result['differential']:
        print(item['tag'], item['group'], item['evidence'])


if __name__ == '__main__':
    main()
