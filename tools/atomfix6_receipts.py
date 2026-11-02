#!/usr/bin/env python3
"""Collect completed lane receipts, retaining failures and exact count denominators."""
import ast
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
        record['jobs'] = []
        for job in sorted((run / 'jobs').iterdir()):
            if not job.is_dir(): continue
            dest = folder / 'jobs' / job.name
            dest.mkdir(parents=True, exist_ok=True)
            for name in ('ledger', 'done', 'output.log', 'timings', 'family.tsv'):
                if (job / name).exists(): shutil.copyfile(job / name, dest / name)
            completion = (job / 'done').read_text().strip() if (job / 'done').exists() else 'MISSING'
            record['jobs'].append(dict(name=job.name, completion=completion))
        live = []
        for path in sorted((run / 'jobs').glob('atomfix6-live-*/proof/result.json')):
            live.append(json.loads(path.read_text()))
        if live: save(folder / 'live-results.json', live)
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
