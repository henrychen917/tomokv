#!/usr/bin/env python3
"""Collect owned gate evidence without substituting a partial run for a full gate."""
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/readability-a1b/evidence'


def record(run, exit_code):
    path = ROOT / run
    ledger = (path / 'ledger.partial').read_text()
    rows = []
    for line in ledger.splitlines():
        fields = line.split('\t', 2)
        if len(fields) == 3 and fields[0] in ('ok', 'FAIL'):
            rows.append(dict(status=fields[0], seconds=fields[1], label=fields[2]))
    events = []
    log = path / 'jobs/flip/perfio-epoll-lb.log'
    if log.exists():
        for line in log.read_text().splitlines():
            if line.startswith('{'):
                events.append(json.loads(line))
    if exit_code:
        dest = OUT / 'earlier-failures'
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(log, dest / (path.name + '-epoll-lb.log'))
    return dict(run=str(path.relative_to(ROOT)), exit=exit_code, rows=rows, epoll_lb=events,
                passed=sum(r['status'] == 'ok' for r in rows), failed=sum(r['status'] == 'FAIL' for r in rows))


result = dict(selected=record('build/gate-run.cYAB8T', 0), repetitions={})
for label, directory in [('initial', 'flip-repeat-initial'), ('diagnostic', 'flip-repeat-diagnostic'), ('final', 'flip-repeat')]:
    source = ROOT / 'build/readability-a1b' / directory
    receipt = json.loads((source / 'results.json').read_text())
    assert len(receipt['records']) == 20, (label, len(receipt['records']))
    runs = []
    for row in receipt['records']:
        run = record(row['run'], row['returncode'])
        run.update(iteration=row['iteration'], revision=row.get('revision'), perfio_sha256=row.get('perfio_sha256'))
        runs.append(run)
    result['repetitions'][label] = dict(command=receipt['command'], environment=receipt['env'], runs=runs)
    (OUT / (label + '-gate.log')).write_text(''.join(
        f'RUN {r["iteration"]}: {r["run"]}\n' + (source / f'{r["iteration"]:02d}.log').read_text() + '\n'
        for r in runs))
    print(label, 'runs', len(runs), 'successful', sum(r['exit'] == 0 for r in runs),
          'rows', sum(r['passed'] for r in runs), 'failed', sum(r['failed'] for r in runs))
selected = ROOT / result['selected']['run']
shutil.copyfile(ROOT / 'build/readability-a1b/gate-initial.log', OUT / 'selected-gate.log')
slowlog = OUT / 'slowlog-legs'
slowlog.mkdir(exist_ok=True)
for file in (selected / 'jobs/bugs5').glob('slowlog_identity*.log'):
    shutil.copyfile(file, slowlog / file.name)
assert len(list(slowlog.glob('slowlog_identity-[12]s-*.log'))) == 8
shutil.copyfile(selected / 'jobs/witness_contracts/cd13b_window_test.log', OUT / 'cd13b-window.log')
(OUT / 'gate-runs.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
final = result['repetitions']['final']['runs']
assert all(r['exit'] == 0 and r['failed'] == 0 for r in final)
assert len({r['perfio_sha256'] for r in final}) == 1
assert all(any(row['label'] == 'perfio stale epoll registration (epoll-lb)' and row['status'] == 'ok'
               for row in r['rows']) for r in final)
for run in final:
    witness = next(e for e in run['epoll_lb'] if e.get('event') == 'lb-destination')
    assert witness['actual_ep'] == [witness['destination_ep']]
    assert witness['actual_io'] == witness['destination_io']
    for event in run['epoll_lb']:
        if event.get('event') == 'epoll':
            assert event['stale'] == 0 and event['duplicates'] == 0
        if event.get('event') == 'events':
            assert event['per_command'] == 1.0
