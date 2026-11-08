#!/usr/bin/env python3
"""Collect selected gate job receipts without changing their verdicts."""
import hashlib
import json
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/storefix5'
result = {'runs': [], 'note': 'Selected correctness jobs; no full-gate/EXPECT/performance receipt.'}
for log in sorted(DOC.glob('gate-*.log')):
    text = log.read_text(errors='replace')
    match = re.search(r'^  artifacts: (.+)$', text, re.M)
    if not match:
        continue
    directory = Path(match[1])
    plan = {}
    for line in (directory / 'plan.sh').read_text().splitlines():
        if '=' in line and not line.startswith(('declare ', '#')):
            key, value = line.split('=', 1)
            try:
                fields = shlex.split(value)
                plan[key] = fields[0] if len(fields) == 1 else value
            except ValueError:
                pass
    binary = Path(plan['CANDIDATE_BINARY'])
    row = {'log': str(log.relative_to(ROOT)), 'directory': str(directory.relative_to(ROOT)),
           'binary': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
           'geometry': {k: plan.get(k) for k in ('GATE_SERVER_CORES', 'GATE_LOAD_CORES',
                        'GATE_RATIO', 'GATE_PORT_FIRST', 'GATE_PORT_LAST')}, 'jobs': []}
    final = re.search(r'^GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL;', text, re.M)
    row['complete'] = bool(final)
    if final:
        row.update(passed=int(final[1]), failed=int(final[2]))
    for done in sorted(directory.glob('jobs/*/done')):
        status, passed, failed = map(int, done.read_text().split())
        ledger = done.parent / 'ledger'
        job = {'name': done.parent.name, 'exit': status, 'passed': passed, 'failed': failed,
               'ledger': ledger.read_text().splitlines() if ledger.exists() else []}
        row['jobs'].append(job)
        if done.parent.name in ('differ-split-0', 'differ-split-1',
                                'differ-armed-0', 'differ-armed-1'):
            output = (done.parent / 'output.log').read_text(errors='replace')
            summary = re.search(r'DIFFER GATE: pass=(\d+) fail=(\d+) runtime=(\S+)', output)
            if summary:
                job['differ'] = dict(passed=int(summary[1]), failed=int(summary[2]),
                    runtime=summary[3], seeds=sorted(set(map(int, re.findall(r'seed=(\d+)', output)))))
    if final and any(j['name'] == 'redis_tcl' for j in row['jobs']):
        row['tcl'] = []
        for summary in sorted(directory.glob('jobs/redis_tcl/redis-tcl-*/summary.json')):
            data = json.loads(summary.read_text())
            for unit in data['rows']:
                row['tcl'].append({k: unit.get(k) for k in
                    ('mode', 'file', 'passed', 'failed', 'skipped', 'complete', 'error')})
                row['tcl'][-1]['failed_assertions'] = [e['test'] for e in unit['events']
                    if e['test'] and e['status'] in ('err', 'exception')]
    if log.name == 'gate-live-final.log' and (directory / 'jobs/storefix5/done').exists():
        samples = []
        for probe in sorted(directory.glob('jobs/storefix5/[12]s-*.log')):
            observations = [json.loads(line) for line in probe.read_text().splitlines()
                            if line.startswith('{')]
            assert len(observations) == 3, probe
            sample = observations[0]
            assert sample['expired_reaped_by_one_call'] < 400 and sample['chi2'] < 100, probe
            assert len(sample['counts']) == 32 and sum(sample['counts'].values()) == 16384, probe
            samples.append(dict(leg=probe.stem, randomkey=sample, idle=observations[2]))
        assert len(samples) == 32, len(samples)
        (DOC / 'randomkey-final-distribution.json').write_text(json.dumps(
            dict(sha256=row['sha256'], legs=samples), indent=2) + '\n')
    result['runs'].append(row)
(DOC / 'gate-summary.json').write_text(json.dumps(result, indent=2) + '\n')
fifo = {}
for arm, filename in (('PRE', 'gate-fifo-pre-final.log'), ('POST', 'gate-extra-final.log')):
    log = DOC / filename
    if not log.exists():
        continue
    match = re.search(r'^  artifacts: (.+)$', log.read_text(), re.M)
    directory = Path(match[1]) / 'jobs/txnorder_fifo_live'
    if not (directory / 'done').exists():
        continue
    rows = []
    for path in sorted(directory.glob('fifo-*.log')):
        text = path.read_text()
        errors = re.findall(r'^AssertionError: (.+)$', text, re.M)
        status = 'FAIL' if errors else 'PASS' if '"pass": true' in text else 'INCOMPLETE'
        rows.append(dict(leg=path.stem, status=status, errors=errors))
    fifo[arm] = dict(log=filename, complete=len(rows) == 16 and all(r['status'] != 'INCOMPLETE' for r in rows),
                     legs=rows)
if len(fifo) == 2:
    pre_fail = {r['leg'] for r in fifo['PRE']['legs'] if r['status'] == 'FAIL'}
    post_fail = {r['leg'] for r in fifo['POST']['legs'] if r['status'] == 'FAIL'}
    fifo['common_failures'] = sorted(pre_fail & post_fail)
    fifo['PRE_only_failures'] = sorted(pre_fail - post_fail)
    fifo['POST_only_failures'] = sorted(post_fail - pre_fail)
    (DOC / 'fifo-pre-post-final.json').write_text(json.dumps(fifo, indent=2) + '\n')
for run in result['runs']:
    print(Path(run['log']).name, run['sha256'][:12],
          f"{run.get('passed', '?')} ok / {run.get('failed', '?')} fail",
          'complete' if run['complete'] else 'incomplete/superseded')
