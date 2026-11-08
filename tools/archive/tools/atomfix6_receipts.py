#!/usr/bin/env python3
"""Collect completed lane receipts, retaining failures and exact count denominators."""
import ast
import gzip
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/atomfix6'

def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

proof = []
for folder in sorted((DOC / 'proof').iterdir()):
    if not folder.is_dir() or not (folder / 'exit.json').exists():
        continue
    log = (folder / 'gate.log').read_text()
    roots = re.findall(r'artifacts: (\S+)', log)
    record = dict(label=folder.name, **json.loads((folder / 'exit.json').read_text()))
    record['passed'] = record['failed'] = 0
    record['failures'] = []
    ledger = folder / 'ledger.tsv.partial'
    for line in ledger.read_text().splitlines() if ledger.exists() else []:
        fields = line.split('\t')
        if fields[0] == 'ok': record['passed'] += 1
        if fields[0] == 'FAIL':
            record['failed'] += 1
            record['failures'].append(fields[-1])
    if roots:
        run = Path(roots[-1]); record['run'] = str(run)
        for source in run.glob('differ-*.json'):
            shutil.copyfile(source, folder / source.name)
        record['jobs'] = []
        for job in sorted((run / 'jobs').iterdir()):
            if not job.is_dir(): continue
            dest = folder / 'jobs' / job.name
            dest.mkdir(parents=True, exist_ok=True)
            for name in ('ledger', 'done', 'output.log', 'timings', 'family.tsv'):
                if (job / name).exists(): shutil.copyfile(job / name, dest / name)
            if job.name.startswith('differ-'):
                for name in ('legs.tsv', 'complete.json', 'seeds.json', 'summary.json'):
                    if (job / 'differ' / name).exists():
                        shutil.copyfile(job / 'differ' / name, dest / name)
            if job.name == 'wave14_order':
                for source, name in [('proof/results.json', 'results.json'), ('proof.log', 'proof.log')]:
                    if (job / source).exists(): shutil.copyfile(job / source, dest / name)
            if job.name == 'flipfix6':
                for source in job.glob('*.log'):
                    shutil.copyfile(source, dest / source.name)
                legs = []
                for source in sorted([*job.glob('*/results.json'),
                                      *job.glob('*/results.json.gz')]):
                    data = source.read_bytes()
                    if source.suffix == '.gz':
                        data = gzip.decompress(data)
                    for row in json.loads(data):
                        result = row.get('result', {})
                        compact = dict(suite=source.parent.name, leg=row.get('leg'),
                            passed=row.get('pass', False), error=row.get('error'))
                        if isinstance(result, list): compact['semantics'] = result
                        elif result:
                            flips = result.get('flips', [])
                            workers = result.get('workers', [])
                            compact.update(flips=len(flips),
                                flip_max=max((r['seconds'] for r in flips), default=0),
                                successful_flips=sum(r['reply'] == 'OK' for r in flips),
                                workers=len(workers), io_before=sorted({r['io_before'] for r in workers}),
                                worker_max_gap=max((r['max_gap'] for r in workers), default=0),
                                **{k: result.get(k) for k in ('ping_max', 'sessions_moved',
                                    'clients_moved', 'flip_refused_s2', 'flip_refused_close', 'errors')})
                        if 'value' in row: compact['value'] = row['value']
                        legs.append(compact)
                if legs: save(folder / 'flip-results.json', legs)
            if job.name == 'atomfix6_units':
                parked = []
                for source in sorted(job.glob('*.log')):
                    if source.name == 'build.log': continue
                    shutil.copyfile(source, dest / source.name)
                    for match in re.finditer(
                        r'atomfix6 park mode=(\S+) namespace=(\S+) read-local=(\d+) '
                        r'tasks=(\d+) passes=(\d+) polls=(\d+) scans=(\d+)',
                        source.read_text()):
                        mode, namespace, read_local, tasks, passes, polls, scans = match.groups()
                        parked.append(dict(log=source.name, mode=mode, namespace=namespace,
                            sanitizer='asan-ubsan' if 'asan' in source.name else
                                      'tsan' if 'tsan' in source.name else 'plain',
                            read_local=int(read_local), tasks=int(tasks), passes=int(passes),
                            polls=int(polls), scans=int(scans)))
                if parked: save(folder / 'park-results.json', parked)
            completion = (job / 'done').read_text().strip() if (job / 'done').exists() else 'MISSING'
            record['jobs'].append(dict(name=job.name, completion=completion))
        live = []
        for path in sorted((run / 'jobs').glob('atomfix6-live-*/proof/result.json')):
            live.append(json.loads(path.read_text()))
        if live: save(folder / 'live-results.json', live)
        fifo = []
        for path in sorted((run / 'jobs/txnorder_fifo_live').glob('fifo-*.json')):
            data = json.loads(path.read_text())
            raw = path.with_suffix('.log').read_text()
            errors = re.findall(r'^AssertionError: (.*)$', raw, re.M)
            fifo.append(dict(leg=path.stem, passed=data.get('pass', False),
                order_violations=data.get('deltas', {}).get('atomic_txn_order_violations'),
                exact_final_values=('actual' in data and 'expected' in data
                                    and data['actual'] == data['expected']),
                completions=sum(data.get('completions', [])),
                fifo=data.get('fifo', {}), assertions=errors))
            if errors:
                dest = folder / 'jobs/txnorder_fifo_live'
                shutil.copyfile(path.with_suffix('.log'), dest / path.with_suffix('.log').name)
        if fifo: save(folder / 'fifo-results.json', fifo)
    proof.append(record)
save(DOC / 'proof-summary.json', proof)

audits = []
index = DOC / 'audit/post-index.json'
for entry in json.loads(index.read_text()) if index.exists() else []:
    log = (ROOT / entry['log']).read_text()
    stats = []
    for blob in re.findall(r'\{[^{}\n]+\}', log):
        try: values = ast.literal_eval(blob)
        except (ValueError, SyntaxError): continue
        if 'mget' in values: stats.append(values)
    rest = [int(v) for v in re.findall(
        r'(?:AT REST[^\n]*?|IN MEMORY AT REST:|RESTORED FROM DUMP:[^\n]*?;)\s*(\d+) of 16 (?:pairs )?differ', log)]
    rounds = len(re.findall(r'^round \d+:', log, re.M))
    tears = sum(v.get('torn', v.get('one_nil', 0) + v.get('diff', 0)) for v in stats)
    errors = sum(v.get('errors', 0) for v in stats)
    bad = tears + errors + sum(rest)
    if rounds and re.search(r'first torn (?!\[\])', log): bad += 1
    if entry['case'] == 'T17' and (rounds != 6 or 'pending 0' not in log): bad += 1
    if 'Traceback' in log or 'Exception in thread' in log or entry['rc']: bad += 1
    audits.append(entry | dict(reads=sum(v['mget'] for v in stats), tears=tears,
        errors=errors, stats=stats, rest_bad=rest, rounds=rounds, violations=bad))
save(DOC / 'audit/counts.json', audits)
print('Proof groups:', [(r['label'], r['passed'], r['failed'], r['rc']) for r in proof])
print('Audit detectors:', len(audits), 'reads', sum(r['reads'] for r in audits),
      'tears', sum(r['tears'] for r in audits), 'violations', sum(r['violations'] for r in audits))
